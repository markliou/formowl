from __future__ import annotations

import csv
import io
import posixpath
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, is_zipfile

from formowl_contract import Observation, now_iso, stable_observation_id

from ...extraction import ExtractionInput, ExtractionResult

_Cells = list[tuple[int, str]]
_Rows = list[tuple[int, _Cells]]
_Tables = list[tuple[str | None, _Rows]]

class AttachmentDocumentExtractor:
    def name(self) -> str:
        return "attachment_document_parser"

    def version(self) -> str:
        return "0.1.0"

    def supported_mime_types(self) -> list[str]:
        return ["*/*"]

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
            tables = (
                _xlsx_tables(data, max_bytes=max_bytes)
                if is_zipfile(io.BytesIO(data))
                else _delimited_table(data)
            )
            if tables is None:
                return ExtractionResult(warnings=["attachment_document_unsupported_content"])
            if len(tables) > max_tables:
                return ExtractionResult(errors=["attachment_document_table_limit_reached"])
            if sum(len(cells) for _, rows in tables for _, cells in rows) > max_cells:
                return ExtractionResult(errors=["attachment_document_cell_limit_reached"])
            return ExtractionResult(observations=_observations(source, tables))
        except (BadZipFile, ET.ParseError, KeyError, OSError, UnicodeDecodeError, ValueError):
            return ExtractionResult(errors=["attachment_document_parse_failed"])

def _delimited_table(data: bytes) -> _Tables | None:
    text = data.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip()]
    for delimiter in ("\t", ","):
        if not lines or not all(delimiter in line for line in lines):
            continue
        rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(row)]
        if rows and all(len(row) > 1 for row in rows):
            return [(None, [(index, list(enumerate(row, 1))) for index, row in enumerate(rows, 1)])]
    return None

def _xlsx_tables(data: bytes, *, max_bytes: int) -> _Tables | None:
    with ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names:
            return None
        if any(item.file_size > max_bytes for item in archive.infolist()):
            raise ValueError("expanded attachment entry exceeds byte limit")
        shared = _shared_strings(archive, names)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            item.attrib.get("Id", ""): _target(item.attrib.get("Target", ""))
            for item in relations
            if _local(item.tag) == "Relationship"
        }
        tables = []
        for sheet in (item for item in workbook.iter() if _local(item.tag) == "sheet"):
            relation_id = next((value for key, value in sheet.attrib.items() if key.endswith("}id")), "")
            path = targets.get(relation_id, "")
            if path in names:
                tables.append((sheet.attrib.get("name", ""), _sheet_rows(archive, path, shared)))
        return tables

def _sheet_rows(archive: ZipFile, path: str, shared: list[str]) -> _Rows:
    rows = []
    for row in (item for item in ET.fromstring(archive.read(path)).iter() if _local(item.tag) == "row"):
        cells = []
        for cell in (item for item in row if _local(item.tag) == "c"):
            value = next((item.text or "" for item in cell if _local(item.tag) == "v"), "")
            if cell.attrib.get("t") == "s" and value.isdigit():
                value = shared[int(value)] if int(value) < len(shared) else ""
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(item.text or "" for item in cell.iter() if _local(item.tag) == "t")
            cells.append((_column(cell.attrib.get("r", "")) or len(cells) + 1, value))
        if cells:
            row_number = row.attrib.get("r", "")
            rows.append((int(row_number) if row_number.isdigit() else len(rows) + 1, cells))
    return rows

def _observations(source: ExtractionInput, tables: _Tables) -> list[Observation]:
    lineage = {
        "child_asset_id": source.asset.asset_id,
        "child_content_hash": source.asset.content_hash,
        "parent_asset_id": source.config.get("parent_asset_id"),
        "parent_source_ref": source.config.get("parent_source_ref"),
        "attachment_source_ref": source.config.get("attachment_source_ref"),
    }
    observations = []
    for table_index, (sheet_name, rows) in enumerate(tables, 1):
        for row_index, cells in rows:
            location = {"table_index": table_index, "row_index": row_index}
            if sheet_name is not None:
                location["sheet_name"] = sheet_name
            row_text = "\t".join(value for _, value in cells)
            observations.append(_observation(source, "table_row", location, row_text, lineage))
            for cell_index, value in cells:
                observations.append(
                    _observation(source, "table_cell", {**location, "cell_index": cell_index}, value, lineage)
                )
    return observations

def _observation(
    source: ExtractionInput,
    observation_type: str,
    location: dict[str, Any],
    text: str,
    lineage: dict[str, Any],
) -> Observation:
    payload = {"value": text, "lineage": lineage}
    observation_id = stable_observation_id(
        asset_id=source.asset.asset_id,
        extractor_run_id=source.extractor_run_id,
        observation_type=observation_type,
        modality="document",
        location=location,
        text=text,
        payload=payload,
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
        payload=payload,
    )

def _shared_strings(archive: ZipFile, names: set[str]) -> list[str]:
    if "xl/sharedStrings.xml" not in names:
        return []
    return [
        "".join(node.text or "" for node in item.iter() if _local(node.tag) == "t")
        for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))
        if _local(item.tag) == "si"
    ]

def _target(value: str) -> str:
    value = value.replace("\\", "/").lstrip("/")
    path = posixpath.normpath(value if value.startswith("xl/") else posixpath.join("xl", value))
    return path if path.startswith("xl/") else ""

def _column(reference: str) -> int:
    value = 0
    for character in reference:
        if not character.isalpha():
            break
        value = value * 26 + ord(character.upper()) - 64
    return value

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def _limit(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value
