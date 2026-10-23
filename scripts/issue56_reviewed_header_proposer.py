#!/usr/bin/env python3
"""Phase 2 of SPEC §7.5 reviewed header validation: deterministic proposer.

Offline, operator-only, resumable. Uses the sealed exact-cells row index to find
rows with candidate-labelled cells, reads one row per table to learn its region,
samples a few data rows, reads only those cells, groups them by per-table header
binding (``reviewed_header_binding_key``) and proposes, per
column, ``header_confirmed``, ``not_header`` or ``ambiguous`` from structural
evidence only. Output is a set of candidates: nothing here approves, renames,
translates or aliases a label. Proposals are private (they contain native
labels) and must stay in an operator-only directory.

Resumability: each pass writes an atomic checkpoint (``pass1-rows``,
``pass2-tables``, ``pass3-cells``, ``proposals`` JSONL); existing checkpoints are
reused on rerun.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any
import unicodedata

PROPOSAL_ARTIFACT_ID = "formowl_reviewed_header_proposal_v1"
PROPOSER_VERSION = "structural_v1"
_MAX_LABEL_WIDTH = 40  # display columns; East Asian wide/fullwidth count 2
_MIN_NONEMPTY_VALUES = 2
_NUMERIC = re.compile(r"^[\s+\-]?[\d,]+(?:\.\d+)?\s*%?$")
_DATE = re.compile(r"^\d{1,4}[-/.]\d{1,2}(?:[-/.]\d{1,4})?(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$")
_GENERIC = re.compile(r"^(?:column|欄)[ _]?\d+$", re.IGNORECASE)
# Identifier-shaped surface: alphanumeric segments joined by separators, with a digit.
_IDENTIFIER = re.compile(r"^(?=.*\d)[A-Za-z0-9]+(?:[.\-_/#][A-Za-z0-9]+)+$")


def _value_kind(text: str) -> str:
    text = text.strip()
    if not text:
        return "blank"
    if _NUMERIC.match(text):
        return "number"
    if _DATE.match(text):
        return "date"
    return "text"


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def decide(label: str, *, kinds: dict[str, int], values: list[str], duplicate_label: bool,
           header_path_depth: int, column_indexed: bool) -> tuple[str, list[str]]:
    """Pure structural decision for one per-table header column."""
    reasons: list[str] = []
    stripped = " ".join(label.split())
    nonempty = sum(count for kind, count in kinds.items() if kind != "blank")
    # Hard negatives win over every ambiguity so an LLM is never asked to
    # rescue a value-shaped, letterless, sentence-length or repeated label.
    if _display_width(stripped) > _MAX_LABEL_WIDTH:
        return "not_header", ["label_too_long"]
    if _value_kind(stripped) in {"number", "date"}:
        return "not_header", ["label_is_value_shaped"]
    if not any(character.isalpha() for character in stripped):
        return "not_header", ["label_has_no_letters"]
    if _IDENTIFIER.match(stripped) and values and sum(
            bool(_IDENTIFIER.match(" ".join(v.split()))) for v in values) * 2 >= len(values):
        # A data row mistaken for a header: the "label" is a value of the column.
        return "not_header", ["label_is_identifier_like_its_values"]
    folded = stripped.casefold()
    if values and sum(" ".join(v.split()).casefold() == folded for v in values) * 2 >= len(values):
        return "not_header", ["label_repeats_as_data"]
    if not column_indexed:
        reasons.append("column_not_indexed_candidate")
    if "[redacted" in stripped:
        reasons.append("label_redacted")
    if _GENERIC.match(stripped):
        reasons.append("generic_positional_label")
    if duplicate_label:
        reasons.append("duplicate_label_in_header_row")
    if header_path_depth > 1:
        reasons.append("multi_level_header_path")
    if nonempty < _MIN_NONEMPTY_VALUES:
        reasons.append("too_few_data_values")
    if _display_width(stripped) < 2:
        reasons.append("label_too_short")
    if reasons:
        return "ambiguous", reasons
    return "header_confirmed", ["structural_checks_passed"]


def _jsonl(path: Path) -> list[Any]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, items: list[Any]) -> None:
    _atomic_write(path, b"".join(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                                 for item in items))


def _shard_records(exact_directory: Path):
    for shard in sorted((exact_directory / "rows").glob("*.jsonl")):
        with shard.open("r", encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)


def _row_key(observation: Any) -> str:
    from formowl_contract import sha256_json

    location = observation.location or {}
    return sha256_json([observation.asset_id, location.get("parent_message_observation_id"),
                        location.get("mime_ordinal"), location.get("sheet_name"),
                        location.get("table_index"), location.get("row_index")])


def _region_row_key(observation: Any, row_index: int) -> str:
    from formowl_contract import sha256_json

    location = observation.location or {}
    return sha256_json([observation.asset_id, location.get("parent_message_observation_id"),
                        location.get("mime_ordinal"), location.get("sheet_name"),
                        location.get("table_index"), row_index])


def _parallel_get(stores: dict[int, Any], requests: list[tuple[int, str]], workers: int):
    from concurrent.futures import ThreadPoolExecutor

    def fetch(request):
        job_index, observation_id = request
        return request, stores[job_index].get(observation_id)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        yield from pool.map(fetch, requests)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ingestion-revision", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-rows", type=int, default=8)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args(argv)
    if not 1 <= args.sample_rows <= 64 or not 1 <= args.workers <= 64:
        parser.error("sample rows and workers must be between 1 and 64")
    from formowl_core import load_issue56_target_runtime_components
    from formowl_contract import redact_public_raw_references
    from formowl_ingestion.storage import ObservationStore
    from formowl_mail.exact import source_occurrence_column_capability_hash
    from formowl_mail.issue56_sealed_source import reviewed_header_binding_key

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    exact_directory = args.ingestion_revision / "exact-cells"
    manifest = json.loads((exact_directory / "manifest.json").read_bytes())
    candidate_columns = {(item["column_hash"], item["inline_table"])
                         for item in manifest["columns"] if item["structure_status"] == "candidate_only"}
    candidate_hashes = {column_hash for column_hash, _ in candidate_columns}
    snapshot = json.loads((args.ingestion_revision / "observations.json").read_bytes())
    stores = {binding["job_index"]: ObservationStore(Path(binding["store_directory"]))
              for binding in snapshot["job_store_bindings"]}
    del snapshot
    log = lambda **fields: print(json.dumps(fields, ensure_ascii=False), flush=True)  # noqa: E731

    # Pass 1: rows that hold at least one candidate-labelled cell (sequential).
    rows_path = out / "pass1-rows.jsonl"
    if not rows_path.is_file():
        started = time.monotonic()
        row_records: dict[str, list[Any]] = {}
        candidate_rows: set[str] = set()
        for record in _shard_records(exact_directory):
            if record[0] == "row":
                row_records[record[1]] = [record[2], record[3]]
            elif record[0] == "cell" and record[5] in candidate_hashes:
                candidate_rows.add(record[1])
        _write_jsonl(rows_path, [[key, *row_records[key]] for key in sorted(candidate_rows) if key in row_records])
        log(phase="pass1", candidate_rows=len(candidate_rows), seconds=round(time.monotonic() - started, 1))
    rows = {key: (job_index, observation_id) for key, job_index, observation_id in _jsonl(rows_path)}

    # Pass 2: one read per table discovers its region; choose sample data rows.
    tables_path = out / "pass2-tables.jsonl"
    if not tables_path.is_file():
        started = time.monotonic()
        covered: set[str] = set()
        tables: list[dict[str, Any]] = []
        pending = list(rows)
        while pending:
            batch = [key for key in pending[: args.workers * 8] if key not in covered]
            pending = pending[args.workers * 8:]
            for (job_index, _), observation in _parallel_get(stores, [rows[key] for key in batch], args.workers):
                if observation is None:
                    continue
                key = _row_key(observation)
                if key in covered:
                    continue
                covered.add(key)
                structure = (observation.payload or {}).get("table_structure") or {}
                start, end = structure.get("region_start_row_index"), structure.get("region_end_row_index")
                header = structure.get("header_row_index")
                if (structure.get("structure_status") != "candidate_only"
                        or not all(isinstance(value, int) for value in (start, end, header))):
                    continue
                region = [_region_row_key(observation, index) for index in range(start, end + 1)]
                covered.update(region)
                data_keys = [k for index, k in zip(range(start, end + 1), region) if index > header and k in rows]
                labels = [" ".join(str(column.get("name", "")).split()).casefold()
                          for column in structure.get("columns") or ()]
                tables.append({"job_index": job_index, "header_depth": header - start + 1,
                               "duplicate_labels": sorted({label for label in labels if labels.count(label) > 1}),
                               "sample_row_keys": data_keys[: args.sample_rows]})
        _write_jsonl(tables_path, tables)
        log(phase="pass2", tables=len(tables), seconds=round(time.monotonic() - started, 1))
    tables = _jsonl(tables_path)

    # Pass 3: cell ids of the sampled rows (sequential).
    cells_path = out / "pass3-cells.jsonl"
    if not cells_path.is_file():
        started = time.monotonic()
        wanted = {key: position for position, table in enumerate(tables) for key in table["sample_row_keys"]}
        cells = [[wanted[record[1]], record[2], record[3]] for record in _shard_records(exact_directory)
                 if record[0] == "cell" and record[1] in wanted]
        _write_jsonl(cells_path, cells)
        log(phase="pass3", cells=len(cells), seconds=round(time.monotonic() - started, 1))
    cells = _jsonl(cells_path)

    # Pass 4: read sampled cells; authoritative bindings come from the cells.
    proposals_path = out / "proposals.jsonl"
    if proposals_path.is_file():
        log(phase="done", status="skipped_existing")
        return 0
    started = time.monotonic()
    profile = load_issue56_target_runtime_components().tokenizer_profile
    columns: dict[str, dict[str, Any]] = {}
    table_of_cell = {observation_id: position for position, _, observation_id in cells}
    for (job_index, observation_id), cell in _parallel_get(
            stores, [(job_index, observation_id) for _, job_index, observation_id in cells], args.workers):
        if cell is None:
            continue
        structure = (cell.payload or {}).get("table_structure") or {}
        key = reviewed_header_binding_key(cell)
        if key is None or structure.get("row_role") != "data_candidate":
            continue
        entry = columns.get(key)
        if entry is None:
            position = table_of_cell[observation_id]
            safe_field = redact_public_raw_references(structure["column_name"])[0][:120]
            normalized = profile.normalize_exact_identifier_surface(safe_field)
            inline = (cell.payload or {}).get("lineage", {}).get("source_family") == "mail_inline_table"
            entry = columns[key] = {
                "binding": key, "inline_table": inline, "label": structure["column_name"], "table": position,
                "column_hash": source_occurrence_column_capability_hash(normalized) if normalized else None,
                "header_path_depth": max(len(structure.get("header_path") or ()),
                                         tables[position]["header_depth"]),
                "kinds": {}, "values": [],
            }
        text = cell.text or ""
        kind = _value_kind(text)
        entry["kinds"][kind] = entry["kinds"].get(kind, 0) + 1
        if kind != "blank":
            entry["values"].append(text[:200])
    proposals = []
    for entry in columns.values():
        folded = " ".join(entry["label"].split()).casefold()
        decision, reasons = decide(
            entry["label"], kinds=entry["kinds"], values=entry["values"],
            duplicate_label=folded in tables[entry["table"]]["duplicate_labels"],
            header_path_depth=entry["header_path_depth"],
            column_indexed=(entry["column_hash"], entry["inline_table"]) in candidate_columns,
        )
        proposals.append({
            "artifact_id": PROPOSAL_ARTIFACT_ID, "proposer_version": PROPOSER_VERSION,
            "binding": entry["binding"], "column_hash": entry["column_hash"],
            "inline_table": entry["inline_table"], "label": entry["label"], "decision": decision,
            "reasons": reasons, "value_kinds": entry["kinds"], "sample_values": entry["values"][:5],
        })
    _write_jsonl(proposals_path, proposals)
    counts = {decision: sum(item["decision"] == decision for item in proposals)
              for decision in ("header_confirmed", "not_header", "ambiguous")}
    _atomic_write(out / "proposals.done.json", json.dumps(
        {"proposer_version": PROPOSER_VERSION, "proposals": len(proposals), "counts": counts,
         "tables": len(tables), "sampled_cells": len(cells)}, sort_keys=True).encode("utf-8"))
    log(phase="pass4", proposals=len(proposals), counts=counts, seconds=round(time.monotonic() - started, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
