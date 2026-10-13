from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import io
import math
import posixpath
import re
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, is_zipfile

from formowl_contract import (
    Observation,
    now_iso,
    stable_observation_id,
    redact_public_raw_references,
)

from ...extraction import ExtractionInput, ExtractionResult

_Cells = list[tuple[int, str]]
_Rows = list[tuple[int, _Cells]]
_MergeRange = tuple[int, int, int, int]
_HeaderPath = tuple[dict[str, Any], ...]


@dataclass
class _TableData:
    name: str | None
    rows: _Rows
    formal_tables: tuple[dict[str, Any], ...] = ()
    merge_ranges: tuple[_MergeRange, ...] = ()
    cell_metadata: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    source_format: str = "delimited"


@dataclass(frozen=True)
class _TextBlock:
    observation_type: str
    text: str
    location: dict[str, Any]
    payload: dict[str, Any]


@dataclass
class _ParsedContent:
    tables: list[_TableData] = field(default_factory=list)
    blocks: list[_TextBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _ParserLimit(ValueError):
    """Only fixed public failure codes are passed through this boundary."""


_MAX_HEADER_PATH_DEPTH = 4

_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MIME_XLS = "application/vnd.ms-excel"
_MIME_PDF = "application/pdf"
_MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_SUPPORTED_MIME_TYPES = (
    "text/csv",
    "text/tab-separated-values",
    "text/plain",
    "text/markdown",
    _MIME_XLSX,
    _MIME_XLS,
    _MIME_PDF,
    _MIME_DOCX,
    _MIME_PPTX,
    "application/octet-stream",
)


class AttachmentDocumentExtractor:
    def name(self) -> str:
        return "attachment_document_parser"

    def version(self) -> str:
        return "0.6.2"

    def supported_mime_types(self) -> list[str]:
        # run_extractor uses this as a routing admission check for every child
        # attachment. Actual source-format capability is exposed separately by
        # capability_ids(); extract() still dispatches only after sniffing.
        return ["*/*"]

    def capability_ids(self) -> list[str]:
        return [
            "delimited_text",
            "text",
            "xlsx",
            "xlsm",
            "xls",
            "pdf",
            "docx",
            "pptx",
        ]

    def extractor_type(self) -> str:
        return "document_structure"

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        max_bytes = _limit(source.config, "attachment_max_bytes", 8 * 1024 * 1024)
        max_tables = _limit(source.config, "attachment_max_tables", 100)
        max_cells = _limit(source.config, "attachment_max_cells", 10_000)
        try:
            if source.object_path.stat().st_size > max_bytes:
                return ExtractionResult(errors=["attachment_document_byte_limit_reached"])
            data = source.object_path.read_bytes()
            declared_kind = _declared_kind(source.asset.mime_type, source.asset.original_filename)
            sniffed_kind = _sniff_kind(data, max_bytes=max_bytes)
            # Delimiter sniffing is only a fallback for undeclared/unknown
            # text.  A declared TXT/MD (or CSV/TSV) must retain its declared
            # dispatch even when its first line happens to contain a comma or
            # tab and later lines are ordinary prose.
            kind = declared_kind if declared_kind in {"text", "delimited"} else sniffed_kind
            warnings = []
            if declared_kind and kind and declared_kind != kind:
                warnings.append("attachment_document_mime_sniff_mismatch")
            parsed = _parse_content(
                data,
                kind=kind,
                declared_kind=declared_kind,
                max_bytes=max_bytes,
                config=source.config,
            )
            warnings.extend(parsed.warnings)
            if not parsed.tables and not parsed.blocks:
                warnings.append("attachment_document_unsupported_content")
                return ExtractionResult(warnings=_unique(warnings))
            if len(parsed.tables) > max_tables:
                return ExtractionResult(errors=["attachment_document_table_limit_reached"])
            cell_count = sum(len(cells) for table in parsed.tables for _, cells in table.rows)
            if cell_count > max_cells:
                return ExtractionResult(errors=["attachment_document_cell_limit_reached"])
            observations = _observations(
                source,
                parsed.tables,
                blocks=parsed.blocks,
            )
            return ExtractionResult(observations=observations, warnings=_unique(warnings))
        except _ParserLimit as exc:
            return ExtractionResult(errors=[str(exc)])
        except (BadZipFile, ET.ParseError, KeyError, OSError, UnicodeDecodeError, ValueError):
            return ExtractionResult(errors=["attachment_document_parse_failed"])


def _declared_kind(mime_type: str | None, filename: str | None) -> str | None:
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    by_mime = {
        _MIME_XLSX: "xlsx",
        "application/vnd.ms-excel.sheet.macroenabled.12": "xlsm",
        _MIME_XLS: "xls",
        _MIME_PDF: "pdf",
        _MIME_DOCX: "docx",
        _MIME_PPTX: "pptx",
        "text/csv": "delimited",
        "text/tab-separated-values": "delimited",
        "text/plain": "text",
        "text/markdown": "text",
        "text/html": "text",
    }
    if mime in by_mime:
        return by_mime[mime]
    suffix = posixpath.splitext(filename or "")[1].lower()
    return {
        ".xlsx": "xlsx",
        ".xlsm": "xlsm",
        ".xlsb": "xlsb",
        ".xls": "xls",
        ".pdf": "pdf",
        ".docx": "docx",
        ".pptx": "pptx",
        ".txt": "text",
        ".md": "text",
        ".markdown": "text",
        ".csv": "delimited",
        ".tsv": "delimited",
    }.get(suffix)


def _sniff_kind(data: bytes, *, max_bytes: int) -> str | None:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if is_zipfile(io.BytesIO(data)):
        with ZipFile(io.BytesIO(data)) as archive:
            _validate_zip_bounds(archive, max_bytes=max_bytes)
            names = set(archive.namelist())
            if "xl/workbook.xml" in names:
                content_types = _zip_text(archive, "[Content_Types].xml")
                return "xlsm" if "macroEnabled.main+xml" in content_types else "xlsx"
            if "word/document.xml" in names:
                return "docx"
            if "ppt/presentation.xml" in names:
                return "pptx"
        return None
    if _looks_like_delimited_text(data):
        return "delimited"
    return None


def _zip_text(archive: ZipFile, name: str) -> str:
    try:
        return archive.read(name)[:4096].decode("utf-8", errors="replace")
    except KeyError:
        return ""


def _validate_zip_bounds(archive: ZipFile, *, max_bytes: int) -> None:
    infos = archive.infolist()
    if len(infos) > 4096:
        raise ValueError("attachment ZIP entry limit reached")
    expanded_limit = max_bytes * 8
    expanded_size = 0
    for info in infos:
        if info.file_size > max_bytes:
            raise ValueError("expanded attachment entry exceeds byte limit")
        expanded_size += info.file_size
        if expanded_size > expanded_limit:
            raise ValueError("expanded attachment archive exceeds byte limit")


def _looks_like_delimited_text(data: bytes) -> bool:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return any(delimiter in lines[0] for delimiter in (",", "\t"))


def _parse_content(
    data: bytes,
    *,
    kind: str | None,
    declared_kind: str | None,
    max_bytes: int,
    config: dict[str, Any],
) -> _ParsedContent:
    if kind == "xlsx":
        return _xlsx_content(data, max_bytes=max_bytes)
    if kind == "xlsm":
        parsed = _xlsx_content(data, max_bytes=max_bytes)
        parsed.warnings.append("xlsx_macro_project_preserved_but_not_extracted")
        return parsed
    if kind == "xls":
        return _xls_content(data, config=config)
    if kind == "ole":
        if declared_kind == "xls":
            return _xls_content(data, config=config)
        return _ParsedContent(warnings=["attachment_document_ole_format_unsupported"])
    if kind == "pdf":
        return _pdf_content(data, config=config)
    if kind == "docx":
        return _docx_content(data, max_bytes=max_bytes, config=config)
    if kind == "pptx":
        return _pptx_content(data, max_bytes=max_bytes, config=config)
    if kind == "delimited":
        table = _delimited_table(data)
        return _ParsedContent(tables=[table] if table is not None else [])
    if kind == "text":
        return _text_content(data, config=config)
    if declared_kind in {"pdf", "xls", "xlsb", "doc", "ppt"}:
        return _ParsedContent(warnings=[f"attachment_document_{declared_kind}_parser_unavailable"])
    return _ParsedContent()


def _text_content(data: bytes, *, config: dict[str, Any]) -> _ParsedContent:
    text = data.decode("utf-8-sig")
    max_blocks = _limit(config, "attachment_max_document_blocks", 10_000)
    blocks: list[_TextBlock] = []
    for index, paragraph in enumerate(
        (part.strip() for part in re.split(r"\n\s*\n", text)),
        1,
    ):
        if not paragraph:
            continue
        blocks.append(
            _TextBlock(
                observation_type="paragraph",
                text=paragraph,
                location={"block_index": index, "paragraph_index": index},
                payload={"source_format": "text", "native_text": True},
            )
        )
        if len(blocks) >= max_blocks:
            return _ParsedContent(
                blocks=blocks,
                warnings=[
                    "attachment_document_block_limit_reached",
                    "attachment_document_partial_text_coverage",
                ],
            )
    return _ParsedContent(
        blocks=blocks,
        warnings=["text_page_locations_unavailable"] if blocks else [],
    )


def _xls_content(data: bytes, *, config: dict[str, Any]) -> _ParsedContent:
    try:
        import xlrd
    except ImportError:
        return _ParsedContent(warnings=["attachment_document_xls_parser_unavailable"])
    max_sheets = _limit(config, "attachment_max_tables", 100)
    try:
        book = xlrd.open_workbook(
            file_contents=data,
            on_demand=True,
            formatting_info=True,
            ragged_rows=True,
            logfile=io.StringIO(),
        )
    except Exception as exc:
        raise _ParserLimit("attachment_document_xls_parse_failed") from exc
    max_reads = _limit(config, "attachment_max_cells", 10_000)
    reads = 0
    tables: list[_TableData] = []
    warnings: list[str] = []
    if len(book.sheet_names()) > max_sheets:
        warnings.append("attachment_document_table_limit_reached")
    try:
        for sheet_name in book.sheet_names()[:max_sheets]:
            sheet = book.sheet_by_name(sheet_name)
            rows: _Rows = []
            metadata: dict[tuple[int, int], dict[str, Any]] = {}
            for row_index in range(sheet.nrows):
                cells: _Cells = []
                for cell_index in range(sheet.row_len(row_index)):
                    if reads >= max_reads:
                        raise _ParserLimit("attachment_document_cell_limit_reached")
                    reads += 1
                    cell = sheet.cell(row_index, cell_index)
                    # EMPTY is padding/missing, BLANK is a source BIFF blank record.
                    if cell.ctype == xlrd.XL_CELL_EMPTY:
                        continue
                    value = _xls_cell_text(cell, book.datemode, xlrd)
                    cells.append((cell_index + 1, value))
                    metadata[(row_index + 1, cell_index + 1)] = {
                        "coordinate": f"{_column_name(cell_index + 1)}{row_index + 1}",
                        "raw_value": cell.value,
                        "cached_value": None,
                        "formula": None,
                        "formula_kind": None,
                        "value_type": _xls_value_type(cell.ctype, xlrd),
                        "xml_type": None,
                        "style_index": cell.xf_index,
                        "number_format_id": None,
                        "number_format_code": None,
                        "date_system": "1900" if book.datemode == 0 else "1904",
                        "date_format_detected": cell.ctype == xlrd.XL_CELL_DATE,
                        "typed_value": cell.value,
                        "explicit_blank": cell.ctype == xlrd.XL_CELL_BLANK,
                        "formula_status": "unavailable_from_xlrd",
                        "cached_value_status": "formula_identity_unavailable",
                        "display_value": None,
                        "display_value_status": "unavailable_without_recalculation_or_formatting",
                    }
                if cells:
                    rows.append((row_index + 1, cells))
            tables.append(
                _TableData(
                    name=sheet_name,
                    rows=rows,
                    cell_metadata=metadata,
                    merge_ranges=tuple(
                        (col_start + 1, row_start + 1, col_end, row_end)
                        for row_start, row_end, col_start, col_end in sheet.merged_cells
                    ),
                    source_format="xls",
                )
            )
    except _ParserLimit:
        raise
    except Exception as exc:
        raise _ParserLimit("attachment_document_xls_parse_failed") from exc
    finally:
        book.release_resources()
    warnings.extend(
        [
            "xls_formula_metadata_unavailable",
            "xls_cached_value_identity_unavailable",
            "xls_display_value_unavailable",
        ]
    )
    return _ParsedContent(tables=tables, warnings=warnings)


def _xls_cell_text(cell: Any, datemode: int, xlrd: Any) -> str:
    if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
        return ""
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if cell.value else "FALSE"
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, datemode).isoformat()
        except (TypeError, ValueError, OverflowError):
            return str(cell.value)
    if isinstance(cell.value, float) and cell.value.is_integer():
        return str(int(cell.value))
    return str(cell.value)


def _xls_value_type(cell_type: int, xlrd: Any) -> str:
    return {
        xlrd.XL_CELL_EMPTY: "blank",
        xlrd.XL_CELL_BLANK: "blank",
        xlrd.XL_CELL_TEXT: "text",
        xlrd.XL_CELL_NUMBER: "number",
        xlrd.XL_CELL_DATE: "date",
        xlrd.XL_CELL_BOOLEAN: "boolean",
        xlrd.XL_CELL_ERROR: "error",
    }.get(cell_type, "unknown")


def _pdf_content(data: bytes, *, config: dict[str, Any]) -> _ParsedContent:
    try:
        return _pdf_content_impl(data, config=config)
    except _ParserLimit:
        raise
    except Exception as exc:
        raise _ParserLimit("attachment_document_pdf_parse_failed") from exc


def _pdf_content_impl(data: bytes, *, config: dict[str, Any]) -> _ParsedContent:
    try:
        from pypdf import PdfReader
    except ImportError:
        return _ParsedContent(warnings=["attachment_document_pdf_parser_unavailable"])
    max_pages = _limit(config, "attachment_max_pages", 100)
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
    except Exception as exc:
        raise _ParserLimit("attachment_document_pdf_parse_failed") from exc
    if reader.is_encrypted:
        return _ParsedContent(warnings=["attachment_document_pdf_encrypted_unsupported"])
    pages = reader.pages
    warnings: list[str] = []
    if len(pages) > max_pages:
        warnings.append("attachment_document_page_limit_reached")
    blocks: list[_TextBlock] = []
    empty_pages = 0
    admitted_pages = min(len(pages), max_pages)
    for page_index in range(1, admitted_pages + 1):
        page = pages[page_index - 1]
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise _ParserLimit("attachment_document_pdf_text_extract_failed") from exc
        if text.strip():
            blocks.append(
                _TextBlock(
                    observation_type="paragraph",
                    text=text.strip(),
                    location={
                        "page": page_index,
                        "block_index": 1,
                        "page_text_status": "extracted",
                    },
                    payload={"source_format": "pdf", "native_text": True},
                )
            )
        else:
            empty_pages += 1
            warnings.append("attachment_document_pdf_page_text_unavailable")
    if empty_pages == admitted_pages and admitted_pages:
        warnings.append("attachment_document_pdf_ocr_required")
    if len(pages) > max_pages or empty_pages:
        warnings.append("attachment_document_partial_native_text_coverage")
    return _ParsedContent(blocks=blocks, warnings=_unique(warnings))


def _docx_content(data: bytes, *, max_bytes: int, config: dict[str, Any]) -> _ParsedContent:
    with ZipFile(io.BytesIO(data)) as archive:
        _validate_zip_bounds(archive, max_bytes=max_bytes)
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            return _ParsedContent()
        document = _xml_from_zip(archive, "word/document.xml", max_bytes=max_bytes)
    blocks: list[_TextBlock] = []
    tables: list[_TableData] = []
    block_limit = _limit(config, "attachment_max_document_blocks", 10_000)
    paragraph_index = 0
    table_index = 0
    body = next((item for item in document.iter() if _local(item.tag) == "body"), document)
    for child in body:
        if _local(child.tag) == "p":
            text = "".join(
                item.text or "" for item in child.iter() if _local(item.tag) == "t"
            ).strip()
            if not text:
                continue
            paragraph_index += 1
            style = next(
                (
                    item.attrib.get(_qn("val"))
                    for item in child.iter()
                    if _local(item.tag) == "pStyle"
                ),
                None,
            )
            is_list = any(_local(item.tag) == "numPr" for item in child.iter())
            observation_type = (
                "heading"
                if (style or "").lower().startswith("heading")
                else "list_item"
                if is_list
                else "paragraph"
            )
            blocks.append(
                _TextBlock(
                    observation_type=observation_type,
                    text=text,
                    location={"block_index": paragraph_index, "paragraph_index": paragraph_index},
                    payload={
                        "source_format": "docx",
                        "style": style,
                        "page_location_status": "unavailable_in_docx_xml",
                    },
                )
            )
            if len(blocks) >= block_limit:
                return _ParsedContent(
                    tables=tables,
                    blocks=blocks,
                    warnings=[
                        "attachment_document_block_limit_reached",
                        "attachment_document_partial_text_coverage",
                    ],
                )
        elif _local(child.tag) == "tbl":
            table_index += 1
            rows, metadata, merge_ranges = _docx_table(child)
            tables.append(
                _TableData(
                    name=f"table_{table_index}",
                    rows=rows,
                    merge_ranges=merge_ranges,
                    cell_metadata=metadata,
                    source_format="docx",
                )
            )
    warnings = ["docx_page_locations_unavailable"] if blocks else []
    return _ParsedContent(tables=tables, blocks=blocks, warnings=warnings)


def _docx_table(
    table: ET.Element,
) -> tuple[_Rows, dict[tuple[int, int], dict[str, Any]], tuple[_MergeRange, ...]]:
    rows: _Rows = []
    metadata: dict[tuple[int, int], dict[str, Any]] = {}
    merges: list[_MergeRange] = []
    for row_index, row in enumerate((item for item in table if _local(item.tag) == "tr"), 1):
        cells: _Cells = []
        column_index = 1
        for cell in (item for item in row if _local(item.tag) == "tc"):
            text = " ".join(
                "".join(
                    item.text or "" for item in paragraph.iter() if _local(item.tag) == "t"
                ).strip()
                for paragraph in cell.iter()
                if _local(paragraph.tag) == "p"
            ).strip()
            span = (
                _optional_int(
                    next(
                        (
                            item.attrib.get(_qn("val"))
                            for item in cell.iter()
                            if _local(item.tag) == "gridSpan"
                        ),
                        None,
                    )
                )
                or 1
            )
            cells.append((column_index, text))
            metadata[(row_index, column_index)] = {
                "coordinate": f"{_column_name(column_index)}{row_index}",
                "raw_value": text,
                "cached_value": None,
                "formula": None,
                "value_type": "text" if text else "blank",
                "style_index": None,
                "date_system": None,
                "explicit_blank": not bool(text),
                "display_value": None,
                "display_value_status": "unavailable_without_word_rendering",
            }
            if span > 1:
                merges.append((column_index, row_index, column_index + span - 1, row_index))
            column_index += span
        if cells:
            rows.append((row_index, cells))
    return rows, metadata, tuple(merges)


def _pptx_content(data: bytes, *, max_bytes: int, config: dict[str, Any]) -> _ParsedContent:
    try:
        return _pptx_content_impl(data, max_bytes=max_bytes, config=config)
    except _ParserLimit:
        raise
    except Exception as exc:
        raise _ParserLimit("attachment_document_pptx_parse_failed") from exc


def _pptx_content_impl(data: bytes, *, max_bytes: int, config: dict[str, Any]) -> _ParsedContent:
    with ZipFile(io.BytesIO(data)) as archive:
        _validate_zip_bounds(archive, max_bytes=max_bytes)
        names = set(archive.namelist())
        slide_names: list[str] = []
        warnings: list[str] = []
        if "ppt/presentation.xml" in names and "ppt/_rels/presentation.xml.rels" in names:
            presentation = _xml_from_zip(archive, "ppt/presentation.xml", max_bytes=max_bytes)
            relations = _xml_from_zip(
                archive,
                "ppt/_rels/presentation.xml.rels",
                max_bytes=max_bytes,
            )
            targets = {
                item.attrib.get("Id", ""): _package_target(
                    item.attrib.get("Target", ""),
                    base_path="ppt/presentation.xml",
                )
                for item in relations
                if _local(item.tag) == "Relationship"
            }
            slide_list = next(
                (item for item in presentation.iter() if _local(item.tag) == "sldIdLst"),
                None,
            )
            if slide_list is not None:
                for item in slide_list:
                    relation_id = next(
                        (value for key, value in item.attrib.items() if key.endswith("}id")),
                        "",
                    )
                    target = targets.get(relation_id, "")
                    if target in names:
                        slide_names.append(target)
        if not slide_names:
            slide_names = sorted(
                [
                    name
                    for name in names
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                ],
                key=lambda name: int(re.search(r"slide(\d+)\.xml$", name).group(1)),
            )
            if slide_names:
                warnings.append("pptx_slide_order_unavailable")
        if not slide_names:
            return _ParsedContent()
        block_limit = _limit(config, "attachment_max_document_blocks", 10_000)
        blocks: list[_TextBlock] = []
        for slide_index, name in enumerate(slide_names, 1):
            slide = _xml_from_zip(archive, name, max_bytes=max_bytes)
            texts = [item.text or "" for item in slide.iter() if _local(item.tag) == "t"]
            text = " ".join(part.strip() for part in texts if part.strip()).strip()
            if not text:
                continue
            blocks.append(
                _TextBlock(
                    observation_type="paragraph",
                    text=text,
                    location={"slide": slide_index, "block_index": 1},
                    payload={"source_format": "pptx", "native_text": True},
                )
            )
            if len(blocks) >= block_limit:
                return _ParsedContent(
                    blocks=blocks,
                    warnings=[
                        *warnings,
                        "attachment_document_block_limit_reached",
                        "attachment_document_partial_text_coverage",
                    ],
                )
    return _ParsedContent(blocks=blocks, warnings=warnings)


def _delimited_table(data: bytes) -> _TableData | None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # A binary attachment is not a malformed supported text table. Preserve
        # its governed child Asset and report unsupported content to the parent.
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    for delimiter in ("\t", ","):
        if not lines or not all(delimiter in line for line in lines):
            continue
        rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(row)]
        if rows and all(len(row) > 1 for row in rows):
            return _TableData(
                name=None,
                rows=[(index, list(enumerate(row, 1))) for index, row in enumerate(rows, 1)],
            )
    return None


def _xlsx_content(data: bytes, *, max_bytes: int) -> _ParsedContent:
    with ZipFile(io.BytesIO(data)) as archive:
        _validate_zip_bounds(archive, max_bytes=max_bytes)
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names:
            return _ParsedContent()
        shared = _shared_strings(archive, names, max_bytes=max_bytes)
        styles = _xlsx_styles(archive, names, max_bytes=max_bytes)
        workbook = _xml_from_zip(archive, "xl/workbook.xml", max_bytes=max_bytes)
        relations = _xml_from_zip(archive, "xl/_rels/workbook.xml.rels", max_bytes=max_bytes)
        date_system = (
            "1904"
            if any(
                _local(item.tag) == "workbookPr" and item.attrib.get("date1904") in {"1", "true"}
                for item in workbook.iter()
            )
            else "1900"
        )
        targets = {
            item.attrib.get("Id", ""): _target(item.attrib.get("Target", ""))
            for item in relations
            if _local(item.tag) == "Relationship"
        }
        tables: list[_TableData] = []
        for sheet in (item for item in workbook.iter() if _local(item.tag) == "sheet"):
            relation_id = next(
                (value for key, value in sheet.attrib.items() if key.endswith("}id")), ""
            )
            path = targets.get(relation_id, "")
            if path in names:
                sheet_xml = _xml_from_zip(archive, path, max_bytes=max_bytes)
                rows, cell_metadata = _sheet_rows_with_metadata(
                    sheet_xml,
                    shared,
                    styles=styles,
                    date_system=date_system,
                )
                tables.append(
                    _TableData(
                        name=sheet.attrib.get("name", ""),
                        rows=rows,
                        formal_tables=_formal_tables(
                            archive,
                            sheet_path=path,
                            sheet_xml=sheet_xml,
                            names=names,
                            max_bytes=max_bytes,
                        ),
                        merge_ranges=_merged_ranges(sheet_xml),
                        cell_metadata=cell_metadata,
                        source_format="xlsx",
                    )
                )
        metadata = [value for table in tables for value in table.cell_metadata.values()]
        warnings: list[str] = []
        if any(item.get("formula_status") != "absent" for item in metadata):
            warnings.append("xlsx_formula_recalculation_unverified")
            if any(
                item.get("cached_value_status") == "absent"
                for item in metadata
                if item.get("formula_status") != "absent"
            ):
                warnings.append("xlsx_formula_cached_value_unavailable")
        if any(item.get("formula_si") is not None for item in metadata):
            warnings.append("xlsx_shared_formula_identity_preserved")
            if any(item.get("formula_status") == "shared_identity_only" for item in metadata):
                warnings.append("xlsx_shared_formula_text_unavailable")
        if any(item.get("date_value_status") == "phantom_1900_leap_day" for item in metadata):
            warnings.append("xlsx_1900_phantom_date_serial")
        if any(item.get("display_value_status") != "available" for item in metadata):
            warnings.append("xlsx_display_value_unavailable")
        return _ParsedContent(tables=tables, warnings=warnings)


def _xlsx_tables(data: bytes, *, max_bytes: int) -> list[_TableData] | None:
    """Compatibility helper retained for existing diagnostic callers."""
    parsed = _xlsx_content(data, max_bytes=max_bytes)
    return parsed.tables or None


def _sheet_rows(sheet_xml: ET.Element, shared: list[str]) -> _Rows:
    rows, _ = _sheet_rows_with_metadata(sheet_xml, shared, styles={}, date_system="1900")
    return rows


def _sheet_rows_with_metadata(
    sheet_xml: ET.Element,
    shared: list[str],
    *,
    styles: dict[int, dict[str, Any]],
    date_system: str,
) -> tuple[_Rows, dict[tuple[int, int], dict[str, Any]]]:
    rows = []
    metadata: dict[tuple[int, int], dict[str, Any]] = {}
    for row in (item for item in sheet_xml.iter() if _local(item.tag) == "row"):
        cells = []
        for cell in (item for item in row if _local(item.tag) == "c"):
            coordinate = cell.attrib.get("r", "")
            cell_index = _column(coordinate) or len(cells) + 1
            row_index = (
                int(row.attrib.get("r", "")) if row.attrib.get("r", "").isdigit() else len(rows) + 1
            )
            value, native = _xlsx_cell_value(cell, shared, styles, date_system)
            cells.append((cell_index, value))
            metadata[(row_index, cell_index)] = native
        if cells:
            row_number = row.attrib.get("r", "")
            row_index = int(row_number) if row_number.isdigit() else len(rows) + 1
            rows.append((row_index, cells))
    return rows, metadata


def _xlsx_cell_value(
    cell: ET.Element,
    shared: list[str],
    styles: dict[int, dict[str, Any]],
    date_system: str,
) -> tuple[str, dict[str, Any]]:
    cell_type = cell.attrib.get("t")
    style_index = _optional_int(cell.attrib.get("s"))
    style = dict(styles.get(style_index or 0, {}))
    formula_node = next((item for item in cell if _local(item.tag) == "f"), None)
    value_node = next((item for item in cell if _local(item.tag) == "v"), None)
    inline_node = next((item for item in cell if _local(item.tag) == "is"), None)
    raw_xml_value = value_node.text if value_node is not None else None
    if cell_type == "inlineStr":
        value = (
            "".join(item.text or "" for item in inline_node.iter() if _local(item.tag) == "t")
            if inline_node is not None
            else ""
        )
        value_type = "inline_string"
    elif cell_type == "s":
        index = int(raw_xml_value) if raw_xml_value and raw_xml_value.isdigit() else -1
        value = shared[index] if 0 <= index < len(shared) else ""
        value_type = "shared_string"
    elif cell_type == "b":
        value = (
            "TRUE"
            if raw_xml_value == "1"
            else "FALSE"
            if raw_xml_value == "0"
            else raw_xml_value or ""
        )
        value_type = "boolean"
    elif cell_type == "e":
        value = raw_xml_value or ""
        value_type = "error"
    elif cell_type == "str":
        value = raw_xml_value or ""
        value_type = "formula_string"
    else:
        value = raw_xml_value or ""
        value_type = "number" if raw_xml_value is not None else "blank"
    formula = formula_node.text if formula_node is not None else None
    formula_kind = formula_node.attrib.get("t") if formula_node is not None else None
    formula_si = formula_node.attrib.get("si") if formula_node is not None else None
    formula_ref = formula_node.attrib.get("ref") if formula_node is not None else None
    formula_present = formula_node is not None
    cached_value = raw_xml_value if formula_present else None
    typed_value = _typed_xlsx_value(value, value_type)
    formula_status = (
        "shared_identity_only"
        if formula_kind == "shared" and not formula
        else "shared_formula"
        if formula_kind == "shared"
        else "formula"
        if formula_present
        else "absent"
    )
    native = {
        "coordinate": cell.attrib.get("r"),
        "raw_value": raw_xml_value,
        "cached_value": cached_value,
        "formula": formula,
        "formula_kind": formula_kind,
        "formula_si": formula_si,
        "formula_ref": formula_ref,
        "formula_status": formula_status,
        "raw_value_status": "present" if raw_xml_value is not None else "absent",
        "value_type": value_type,
        "xml_type": cell_type,
        "style_index": style_index,
        "number_format_id": style.get("number_format_id"),
        "number_format_code": style.get("number_format_code"),
        "date_system": date_system,
        "date_format_detected": bool(style.get("is_date")),
        "typed_value": typed_value,
        "typed_value_kind": _typed_xlsx_value_kind(value, value_type),
        "cached_value_status": (
            "present"
            if formula_present and cached_value is not None
            else "absent"
            if formula_present
            else "not_applicable"
        ),
        "explicit_blank": (
            value_type == "blank" and formula is None and value_node is None and inline_node is None
        ),
        "display_value": None,
        "display_value_status": "unavailable_without_recalculation_or_formatting",
    }
    if style.get("is_date") and isinstance(typed_value, (int, float)):
        native["date_serial"] = typed_value
        native["date_value_iso"] = _excel_serial_to_iso(typed_value, date_system)
        native["date_value_status"] = (
            "phantom_1900_leap_day"
            if date_system == "1900" and typed_value == 60
            else "normalized_excel_serial"
        )
    return value, native


def _typed_xlsx_value(value: str, value_type: str) -> Any:
    if value_type == "number":
        if re.fullmatch(r"[+-]?\d+", value):
            return int(value)
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][+-]?\d+)?", value):
            return value
        return value
    if value_type == "boolean":
        return value == "TRUE"
    return value


def _typed_xlsx_value_kind(value: str, value_type: str) -> str | None:
    if value_type != "number":
        return "boolean" if value_type == "boolean" else value_type
    return "integer" if re.fullmatch(r"[+-]?\d+", value) else "decimal"


def _excel_serial_to_iso(value: int | float, date_system: str) -> str | None:
    if not math.isfinite(float(value)):
        return None
    try:
        if date_system == "1900":
            if value == 60:
                return None
            epoch = datetime(1899, 12, 31)
            days = float(value) if value < 60 else float(value) - 1
        else:
            epoch = datetime(1904, 1, 1)
            days = float(value)
        return (epoch + timedelta(days=days)).isoformat()
    except (OverflowError, ValueError):
        return None


def _observations(
    source: ExtractionInput,
    tables: list[_TableData],
    *,
    blocks: list[_TextBlock] | None = None,
) -> list[Observation]:
    lineage = {
        "child_asset_id": source.asset.asset_id,
        "child_content_hash": source.asset.content_hash,
        "parent_asset_id": source.config.get("parent_asset_id"),
        "parent_source_ref": source.config.get("parent_source_ref"),
        "attachment_source_ref": source.config.get("attachment_source_ref"),
    }
    observations = []
    for table_index, table in enumerate(tables, 1):
        sheet_name = table.name
        rows = table.rows
        formal_tables = table.formal_tables
        merge_ranges = table.merge_ranges
        candidate_structures, candidate_header_paths = _candidate_row_structures(
            rows,
            formal_tables,
            merge_ranges,
        )
        for row_index, cells in rows:
            location = {"table_index": table_index, "row_index": row_index}
            if sheet_name is not None:
                location["sheet_name"] = redact_public_raw_references(sheet_name)[0]
            row_structure = _row_structure(
                row_index=row_index,
                cells=cells,
                formal_tables=formal_tables,
                candidate_structures=candidate_structures,
            )
            header_paths = candidate_header_paths.get(row_index, {})
            row_text = "\t".join(value for _, value in cells)
            observations.append(
                _observation(
                    source,
                    "table_row",
                    location,
                    row_text,
                    lineage,
                    table_structure=row_structure,
                )
            )
            for cell_index, value in cells:
                observations.append(
                    _observation(
                        source,
                        "table_cell",
                        {**location, "cell_index": cell_index},
                        value,
                        lineage,
                        table_structure=_cell_structure(
                            row_structure,
                            cell_index=cell_index,
                            header_path=header_paths.get(cell_index, ()),
                        ),
                        native_metadata=table.cell_metadata.get((row_index, cell_index)),
                    )
                )
    for block in blocks or []:
        observations.append(
            _observation(
                source,
                block.observation_type,
                block.location,
                block.text,
                lineage,
                table_structure={},
                payload=block.payload,
            )
        )
    return observations


def _observation(
    source: ExtractionInput,
    observation_type: str,
    location: dict[str, Any],
    text: str,
    lineage: dict[str, Any],
    *,
    table_structure: dict[str, Any],
    native_metadata: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Observation:
    # Observation records are persisted and may be projected to public
    # evidence.  Sanitize every string-bearing branch, not only the rendered
    # text: attachment lineage can contain source references and the contract
    # also persists ``extracted_value`` separately from ``text``.  Keeping the
    # sanitized values in the stable-id input makes the serialized record and
    # its identity agree; raw parser inputs never cross this boundary.
    safe_lineage = _public_table_structure(lineage)
    extracted_value = _public_table_structure(text)
    text = redact_public_raw_references(text)[0]
    observation_payload = {
        "value": text,
        "lineage": safe_lineage,
        "table_structure": _public_table_structure(table_structure),
    }
    if native_metadata:
        observation_payload["native"] = _public_table_structure(native_metadata)
    if payload:
        observation_payload.update(_public_table_structure(payload))
    observation_id = stable_observation_id(
        asset_id=source.asset.asset_id,
        extractor_run_id=source.extractor_run_id,
        observation_type=observation_type,
        modality="document",
        location=location,
        text=text,
        payload=observation_payload,
        extracted_value=extracted_value,
    )
    return Observation(
        observation_id=observation_id,
        asset_id=source.asset.asset_id,
        extractor_run_id=source.extractor_run_id,
        observation_type=observation_type,
        modality="document",
        text=text,
        location=location,
        confidence=1.0,
        permission_scope=source.asset.permission_scope,
        created_at=source.created_at or now_iso(),
        payload=observation_payload,
        extracted_value=extracted_value,
    )


def _public_table_structure(value: Any) -> Any:
    if isinstance(value, str):
        return redact_public_raw_references(value)[0]
    if isinstance(value, list):
        return [_public_table_structure(item) for item in value]
    if isinstance(value, dict):
        return {key: _public_table_structure(item) for key, item in value.items()}
    return value


def _formal_tables(
    archive: ZipFile,
    *,
    sheet_path: str,
    sheet_xml: ET.Element,
    names: set[str],
    max_bytes: int,
) -> tuple[dict[str, Any], ...]:
    relation_path = posixpath.join(
        posixpath.dirname(sheet_path),
        "_rels",
        posixpath.basename(sheet_path) + ".rels",
    )
    if relation_path not in names:
        return ()
    relations = _xml_from_zip(archive, relation_path, max_bytes=max_bytes)
    targets = {
        item.attrib.get("Id", ""): _target(
            item.attrib.get("Target", ""),
            base_path=sheet_path,
        )
        for item in relations
        if _local(item.tag) == "Relationship"
    }
    table_relation_ids = [
        next((value for key, value in item.attrib.items() if key.endswith("}id")), "")
        for item in sheet_xml.iter()
        if _local(item.tag) == "tablePart"
    ]
    result: list[dict[str, Any]] = []
    for formal_table_index, relation_id in enumerate(table_relation_ids, 1):
        table_path = targets.get(relation_id, "")
        if table_path not in names:
            raise ValueError("worksheet table relationship is incomplete")
        table_xml = _xml_from_zip(archive, table_path, max_bytes=max_bytes)
        if _local(table_xml.tag) != "table":
            raise ValueError("worksheet table part is invalid")
        bounds = _range_bounds(table_xml.attrib.get("ref", ""))
        columns = [
            item.attrib.get("name", "")
            for item in table_xml.iter()
            if _local(item.tag) == "tableColumn"
        ]
        min_column, min_row, max_column, max_row = bounds
        if (
            not columns
            or len(columns) != max_column - min_column + 1
            or any(not isinstance(value, str) or not value for value in columns)
        ):
            raise ValueError("worksheet table columns are invalid")
        header_row_count = int(table_xml.attrib.get("headerRowCount", "1"))
        totals_row_count = int(table_xml.attrib.get("totalsRowCount", "0"))
        if header_row_count not in {0, 1} or totals_row_count not in {0, 1}:
            raise ValueError("worksheet table row metadata is unsupported")
        result.append(
            {
                "structure_status": "source_provided",
                "formal_table_index": formal_table_index,
                "table_name": (
                    table_xml.attrib.get("displayName")
                    or table_xml.attrib.get("name")
                    or f"table_{formal_table_index}"
                ),
                "table_ref": table_xml.attrib["ref"],
                "min_column_index": min_column,
                "max_column_index": max_column,
                "min_row_index": min_row,
                "max_row_index": max_row,
                "header_enabled": header_row_count == 1,
                "header_row_index": min_row if header_row_count else None,
                "totals_row_index": max_row if totals_row_count else None,
                "columns": [
                    {
                        "cell_index": min_column + offset,
                        "name": name,
                    }
                    for offset, name in enumerate(columns)
                ],
            }
        )
    return tuple(result)


def _row_structure(
    *,
    row_index: int,
    cells: _Cells,
    formal_tables: tuple[dict[str, Any], ...],
    candidate_structures: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    formal_matches = [
        table
        for table in formal_tables
        if table["min_row_index"] <= row_index <= table["max_row_index"]
        and any(
            table["min_column_index"] <= cell_index <= table["max_column_index"]
            for cell_index, _ in cells
        )
    ]
    if len(formal_matches) > 1:
        raise ValueError("worksheet table ranges overlap")
    if formal_matches:
        structure = dict(formal_matches[0])
        if row_index == structure["header_row_index"]:
            structure["row_role"] = "header"
        elif row_index == structure["totals_row_index"]:
            structure["row_role"] = "totals"
        else:
            structure["row_role"] = "data"
        return structure
    return dict(
        candidate_structures.get(
            row_index,
            {
                "structure_status": "unavailable",
                "row_role": "unclassified",
            },
        )
    )


def _candidate_row_structures(
    rows: _Rows,
    formal_tables: tuple[dict[str, Any], ...],
    merge_ranges: tuple[_MergeRange, ...],
) -> tuple[
    dict[int, dict[str, Any]],
    dict[int, dict[int, _HeaderPath]],
]:
    structures: dict[int, dict[str, Any]] = {}
    header_paths: dict[int, dict[int, _HeaderPath]] = {}
    region: _Rows = []

    def finish_region() -> None:
        if not region:
            return
        header = next(
            (item for item in region if sum(bool(value.strip()) for _, value in item[1]) >= 2),
            None,
        )
        if header is None:
            return
        header_row_index, header_cells = header
        header_position = region.index(header)
        leading_header_rows = region[: header_position + 1]
        if len(leading_header_rows) > _MAX_HEADER_PATH_DEPTH:
            return
        columns = [
            {"cell_index": cell_index, "name": value}
            for cell_index, value in header_cells
            if value.strip()
        ]
        if not columns:
            return
        region_columns = {
            cell_index
            for _candidate_row_index, candidate_cells in region
            for cell_index, _value in candidate_cells
        }
        bounded_paths = _bounded_header_paths(
            header_rows=leading_header_rows,
            target_columns={column["cell_index"] for column in columns},
            merge_ranges=merge_ranges,
            region_start_row_index=region[0][0],
            region_columns=region_columns,
        )
        if bounded_paths is None:
            return
        for candidate_row_index, _ in region:
            if candidate_row_index < header_row_index:
                continue
            structures[candidate_row_index] = {
                "structure_status": "candidate_only",
                "row_role": (
                    "header_candidate"
                    if candidate_row_index == header_row_index
                    else "data_candidate"
                ),
                "region_start_row_index": region[0][0],
                "region_end_row_index": region[-1][0],
                "header_row_index": header_row_index,
                "columns": columns,
            }
            if candidate_row_index > header_row_index:
                header_paths[candidate_row_index] = bounded_paths

    previous_row_index: int | None = None
    for row_index, cells in rows:
        formal = any(
            table["min_row_index"] <= row_index <= table["max_row_index"]
            and any(
                table["min_column_index"] <= cell_index <= table["max_column_index"]
                for cell_index, _ in cells
            )
            for table in formal_tables
        )
        if formal or (previous_row_index is not None and row_index != previous_row_index + 1):
            finish_region()
            region = []
        if not formal:
            region.append((row_index, cells))
        previous_row_index = row_index if not formal else None
    finish_region()
    return structures, header_paths


def _cell_structure(
    row_structure: dict[str, Any],
    *,
    cell_index: int,
    header_path: _HeaderPath = (),
) -> dict[str, Any]:
    structure = dict(row_structure)
    columns = structure.pop("columns", [])
    column_name = next(
        (column["name"] for column in columns if column.get("cell_index") == cell_index),
        None,
    )
    if isinstance(column_name, str) and column_name:
        structure["column_name"] = column_name
    if header_path:
        structure["header_path"] = [dict(component) for component in header_path]
    structure["column_index"] = cell_index
    return structure


def _bounded_header_paths(
    *,
    header_rows: _Rows,
    target_columns: set[int],
    merge_ranges: tuple[_MergeRange, ...],
    region_start_row_index: int,
    region_columns: set[int],
) -> dict[int, _HeaderPath] | None:
    header_end_row_index = header_rows[-1][0]
    if not region_columns:
        return None
    min_region_column = min(region_columns)
    max_region_column = max(region_columns)
    relevant_merges = tuple(
        bounds
        for bounds in merge_ranges
        if bounds[1] <= header_end_row_index
        and bounds[3] >= region_start_row_index
        and bounds[0] <= max_region_column
        and bounds[2] >= min_region_column
    )
    if any(
        min_row_index < region_start_row_index
        or max_row_index > header_end_row_index
        or min_column < min_region_column
        or max_column > max_region_column
        for min_column, min_row_index, max_column, max_row_index in relevant_merges
    ):
        return None
    paths: dict[int, list[dict[str, Any]]] = {column_index: [] for column_index in target_columns}
    for row_index, cells in header_rows:
        for cell_index, value in cells:
            if not value.strip():
                continue
            covering = tuple(
                bounds
                for bounds in relevant_merges
                if bounds[0] <= cell_index <= bounds[2] and bounds[1] <= row_index <= bounds[3]
            )
            if len(covering) > 1:
                return None
            if covering:
                min_column, min_row_index, max_column, max_row_index = covering[0]
                if (cell_index, row_index) != (min_column, min_row_index):
                    continue
            else:
                min_column = max_column = cell_index
                min_row_index = max_row_index = row_index
            component = {
                "row_index": row_index,
                "cell_index": cell_index,
                "min_row_index": min_row_index,
                "max_row_index": max_row_index,
                "min_column_index": min_column,
                "max_column_index": max_column,
                "value": value,
            }
            for column_index in sorted(target_columns):
                if min_column <= column_index <= max_column:
                    paths[column_index].append(component)
    if any(
        not components or len(components) > _MAX_HEADER_PATH_DEPTH for components in paths.values()
    ):
        return None
    return {
        column_index: tuple(dict(component) for component in components)
        for column_index, components in paths.items()
    }


def _merged_ranges(sheet_xml: ET.Element) -> tuple[_MergeRange, ...]:
    # Repeated declarations describe the same source rectangle. Collapse only
    # identical bounds; distinct overlapping rectangles remain a real failure.
    ranges = tuple(
        sorted(
            {
                _range_bounds(item.attrib.get("ref", ""))
                for item in sheet_xml.iter()
                if _local(item.tag) == "mergeCell"
            }
        )
    )
    for index, left in enumerate(ranges):
        for right in ranges[index + 1 :]:
            if (
                left[0] <= right[2]
                and left[2] >= right[0]
                and left[1] <= right[3]
                and left[3] >= right[1]
            ):
                raise ValueError("worksheet merged ranges overlap")
    return ranges


def _shared_strings(archive: ZipFile, names: set[str], *, max_bytes: int) -> list[str]:
    if "xl/sharedStrings.xml" not in names:
        return []
    return [
        "".join(node.text or "" for node in item.iter() if _local(node.tag) == "t")
        for item in _xml_from_zip(archive, "xl/sharedStrings.xml", max_bytes=max_bytes)
        if _local(item.tag) == "si"
    ]


def _xlsx_styles(
    archive: ZipFile,
    names: set[str],
    *,
    max_bytes: int,
) -> dict[int, dict[str, Any]]:
    if "xl/styles.xml" not in names:
        return {}
    styles_xml = _xml_from_zip(archive, "xl/styles.xml", max_bytes=max_bytes)
    number_formats: dict[int, str] = {}
    for item in styles_xml.iter():
        if _local(item.tag) == "numFmt":
            identifier = _optional_int(item.attrib.get("numFmtId"))
            code = item.attrib.get("formatCode")
            if identifier is not None and code:
                number_formats[identifier] = code
    built_in_formats = {
        14: "m/d/yy",
        15: "d-mmm-yy",
        16: "d-mmm",
        17: "mmm-yy",
        18: "h:mm AM/PM",
        19: "h:mm:ss AM/PM",
        20: "h:mm",
        21: "h:mm:ss",
        22: "m/d/yy h:mm",
        45: "mm:ss",
        46: "[h]:mm:ss",
        47: "mmss.0",
        48: "##0.0E+0",
    }
    cell_xfs = next((item for item in styles_xml.iter() if _local(item.tag) == "cellXfs"), None)
    if cell_xfs is None:
        return {}
    result: dict[int, dict[str, Any]] = {}
    for index, xf in enumerate(item for item in cell_xfs if _local(item.tag) == "xf"):
        number_format_id = _optional_int(xf.attrib.get("numFmtId"))
        code = number_formats.get(number_format_id or 0) or built_in_formats.get(
            number_format_id or 0
        )
        result[index] = {
            "number_format_id": number_format_id,
            "number_format_code": code,
            "is_date": _looks_like_date_format(code),
        }
    return result


def _looks_like_date_format(code: str | None) -> bool:
    if not code:
        return False
    lowered = code.lower()
    if re.search(r"\[(?:h|m|s)\]", lowered):
        return False
    stripped = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", lowered)
    return bool(re.search(r"(?:y{1,4}|d{1,4}|h{1,2}|s{1,2})", stripped))


def _xml_from_zip(archive: ZipFile, name: str, *, max_bytes: int) -> ET.Element:
    info = archive.getinfo(name)
    if info.file_size > max_bytes:
        raise ValueError("expanded attachment entry exceeds byte limit")
    data = archive.read(name)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("unsafe XML declaration")
    return ET.fromstring(data)


def _target(value: str, *, base_path: str = "xl/workbook.xml") -> str:
    value = value.replace("\\", "/").lstrip("/")
    path = posixpath.normpath(
        value if value.startswith("xl/") else posixpath.join(posixpath.dirname(base_path), value)
    )
    return path if path.startswith("xl/") else ""


def _package_target(value: str, *, base_path: str) -> str:
    value = value.replace("\\", "/").lstrip("/")
    return posixpath.normpath(
        value if value.startswith("ppt/") else posixpath.join(posixpath.dirname(base_path), value)
    )


def _range_bounds(reference: str) -> tuple[int, int, int, int]:
    if ":" not in reference:
        raise ValueError("worksheet table range is invalid")
    start, end = reference.split(":", 1)
    start_column, start_row = _cell_reference(start)
    end_column, end_row = _cell_reference(end)
    if start_column > end_column or start_row > end_row:
        raise ValueError("worksheet table range is invalid")
    return start_column, start_row, end_column, end_row


def _cell_reference(reference: str) -> tuple[int, int]:
    column = _column(reference)
    row = reference[len("".join(character for character in reference if character.isalpha())) :]
    if column < 1 or not row.isdigit() or int(row) < 1:
        raise ValueError("worksheet cell reference is invalid")
    return column, int(row)


def _column(reference: str) -> int:
    value = 0
    for character in reference:
        if not character.isalpha():
            break
        value = value * 26 + ord(character.upper()) - 64
    return value


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _qn(name: str) -> str:
    return "{" + "http://schemas.openxmlformats.org/wordprocessingml/2006/main" + "}" + name


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _limit(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value
