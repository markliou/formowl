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
_MergeRange = tuple[int, int, int, int]
_HeaderPath = tuple[dict[str, Any], ...]
_Tables = list[
    tuple[
        str | None,
        _Rows,
        tuple[dict[str, Any], ...],
        tuple[_MergeRange, ...],
    ]
]
_MAX_HEADER_PATH_DEPTH = 4

class AttachmentDocumentExtractor:
    def name(self) -> str:
        return "attachment_document_parser"

    def version(self) -> str:
        return "0.3.0"

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
            if (
                sum(
                    len(cells)
                    for _, rows, _, _ in tables
                    for _, cells in rows
                )
                > max_cells
            ):
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
            return [
                (
                    None,
                    [(index, list(enumerate(row, 1))) for index, row in enumerate(rows, 1)],
                    (),
                    (),
                )
            ]
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
                sheet_xml = ET.fromstring(archive.read(path))
                tables.append(
                    (
                        sheet.attrib.get("name", ""),
                        _sheet_rows(sheet_xml, shared),
                        _formal_tables(
                            archive,
                            sheet_path=path,
                            sheet_xml=sheet_xml,
                            names=names,
                        ),
                        _merged_ranges(sheet_xml),
                    )
                )
        return tables

def _sheet_rows(sheet_xml: ET.Element, shared: list[str]) -> _Rows:
    rows = []
    for row in (item for item in sheet_xml.iter() if _local(item.tag) == "row"):
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
    for table_index, (
        sheet_name,
        rows,
        formal_tables,
        merge_ranges,
    ) in enumerate(tables, 1):
        candidate_structures, candidate_header_paths = _candidate_row_structures(
            rows,
            formal_tables,
            merge_ranges,
        )
        for row_index, cells in rows:
            location = {"table_index": table_index, "row_index": row_index}
            if sheet_name is not None:
                location["sheet_name"] = sheet_name
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
) -> Observation:
    payload = {
        "value": text,
        "lineage": lineage,
        "table_structure": table_structure,
    }
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


def _formal_tables(
    archive: ZipFile,
    *,
    sheet_path: str,
    sheet_xml: ET.Element,
    names: set[str],
) -> tuple[dict[str, Any], ...]:
    relation_path = posixpath.join(
        posixpath.dirname(sheet_path),
        "_rels",
        posixpath.basename(sheet_path) + ".rels",
    )
    if relation_path not in names:
        return ()
    relations = ET.fromstring(archive.read(relation_path))
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
        table_xml = ET.fromstring(archive.read(table_path))
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
            (
                item
                for item in region
                if sum(bool(value.strip()) for _, value in item[1]) >= 2
            ),
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
        if formal or (
            previous_row_index is not None and row_index != previous_row_index + 1
        ):
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
        (
            column["name"]
            for column in columns
            if column.get("cell_index") == cell_index
        ),
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
    paths: dict[int, list[dict[str, Any]]] = {
        column_index: [] for column_index in target_columns
    }
    for row_index, cells in header_rows:
        for cell_index, value in cells:
            if not value.strip():
                continue
            covering = tuple(
                bounds
                for bounds in relevant_merges
                if bounds[0] <= cell_index <= bounds[2]
                and bounds[1] <= row_index <= bounds[3]
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
        not components or len(components) > _MAX_HEADER_PATH_DEPTH
        for components in paths.values()
    ):
        return None
    return {
        column_index: tuple(dict(component) for component in components)
        for column_index, components in paths.items()
    }


def _merged_ranges(sheet_xml: ET.Element) -> tuple[_MergeRange, ...]:
    ranges = tuple(
        sorted(
            _range_bounds(item.attrib.get("ref", ""))
            for item in sheet_xml.iter()
            if _local(item.tag) == "mergeCell"
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

def _shared_strings(archive: ZipFile, names: set[str]) -> list[str]:
    if "xl/sharedStrings.xml" not in names:
        return []
    return [
        "".join(node.text or "" for node in item.iter() if _local(node.tag) == "t")
        for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))
        if _local(item.tag) == "si"
    ]

def _target(value: str, *, base_path: str = "xl/workbook.xml") -> str:
    value = value.replace("\\", "/").lstrip("/")
    path = posixpath.normpath(
        value
        if value.startswith("xl/")
        else posixpath.join(posixpath.dirname(base_path), value)
    )
    return path if path.startswith("xl/") else ""


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

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def _limit(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value
