#!/usr/bin/env python3
"""Export sealed native table rows with their original, possibly partial labels.

Private operator output. Each committed shard is bound to the source and this
exporter's bytes. An interrupted shard is rebuilt on resume. Existing source
APIs own hash, permission, run and occurrence-lineage validation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import fcntl
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "python"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import ContractValidationError, sha256_json  # noqa: E402
from formowl_gateway.issue56_sealed_source_loader import (  # noqa: E402
    _IngestionExactCellLookup, _table_row_key, redact_public_raw_references,
)
from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision  # noqa: E402
from formowl_mail.query import (  # noqa: E402
    normalized_authorized_observation_lineages,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (  # noqa: E402
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND, authorized_permission_scope_matches,
)

ARTIFACT_ID = "formowl_native_table_records_v1"


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def atomic_write(path, payload):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def file_seal(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": "sha256:" + digest.hexdigest(), "size_bytes": size}


def safe_text(value):
    return redact_public_raw_references(value)[0] if isinstance(value, str) else None


def project_row(row, cells, parent, mail, *, job_fingerprint, row_hash, cell_hashes):
    """Project a fully validated group without filling missing native labels."""
    cells = sorted(cells, key=lambda cell: cell.location["cell_index"])
    projected = []
    for cell in cells:
        name = (cell.payload or {}).get("table_structure", {}).get("column_name")
        label = safe_text(name) if isinstance(name, str) and name.strip() else None
        projected.append({
            "cell_index": cell.location["cell_index"],
            "column_name": label,
            "text": safe_text(cell.text or ""),
            "observation_id": cell.observation_id,
            "observation_hash": cell_hashes[cell.observation_id],
        })
    names = [cell["column_name"] for cell in projected]
    named = sum(name is not None for name in names)
    inline = parent.observation_type == "email_message"
    mail_payload = (mail.payload or {}) if mail is not None else (parent.payload or {})
    table_id = sha256_json([
        job_fingerprint, row.extractor_run_id, row.permission_scope["scope_id"],
        *_table_row_key(row)[:-1],
    ])
    return {
        "observation_id": row.observation_id,
        "observation_hash": row_hash,
        "table_id": table_id,
        "source_family": "mail_inline_table" if inline else "attachment_table",
        "document_id": parent.observation_id,
        "attachment_observation_id": None if inline else parent.observation_id,
        "attachment_asset_id": None if inline else row.asset_id,
        "mail_observation_id": mail.observation_id if mail is not None else None,
        "mail_message_id": safe_text(mail_payload.get("message_id")),
        "mail_message_occurrence_id": parent.location.get("message_occurrence_id"),
        "sent_at": safe_text(mail_payload.get("sent_at")),
        "table_index": row.location.get("table_index"),
        "sheet_name": safe_text(row.location.get("sheet_name")),
        "row_index": row.location.get("row_index"),
        "row_role": (row.payload or {}).get("table_structure", {}).get("row_role"),
        "header_signature": names,
        "header_signature_hash": sha256_json(names) if named else None,
        "named_cell_count": named,
        "complete": bool(projected) and named == len(projected),
        "cells": projected,
        "permission_scope_id": row.permission_scope["scope_id"],
        "review_status": "pending_review",
    }


class NativeRows:
    def __init__(self, revision):
        self.revision = revision
        self.lookup = _IngestionExactCellLookup(revision)
        self.source = revision.authorized_source
        self.reader = revision.source_records
        if self.source is None or self.reader is None or self.reader.runtime_store is None:
            raise ContractValidationError("native export source authority is unavailable")
        self.shards = sorted(shard for kind, shard in self.lookup._shards if kind == "row")
        self.counts = dict(self.lookup._manifest["counts"])

    def load(self, job_index, observation_id, observation_hash):
        if type(job_index) is not int or not 0 <= job_index < len(self.revision.job_authorities):
            raise ContractValidationError("native export job reference is invalid")
        authority = self.revision.job_authorities[job_index]
        item = authority.load_indexed_observation(
            observation_id, expected_observation_hash=observation_hash,
            expected_job_fingerprint=authority.job_fingerprint,
        )
        if not authorized_permission_scope_matches(
            item.permission_scope, authorized_source=self.source,
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
        ):
            raise ContractValidationError("native export source permission is denied")
        return item

    def load_helper(self, helper, job_index):
        self.reader._authority_for_helper(helper)
        if helper["reference"]["job_index"] != job_index:
            raise ContractValidationError("native export parent job mismatch")
        return self.load(job_index, helper["observation_id"], helper["observation_hash"])

    @lru_cache(maxsize=8192)
    def parent(self, job_index, parent_id, asset_id):
        runtime = self.reader.runtime_store
        helper = runtime.get_helper(parent_id) if parent_id else runtime.helper_for_attachment_asset(asset_id)
        if helper is None:
            raise ContractValidationError("native export parent is unresolved")
        return self.load_helper(helper, job_index)

    @lru_cache(maxsize=8192)
    def mail_parent(self, job_index, asset_id, run_id, occurrence_id):
        helper = self.reader.runtime_store.helper_for_mail_parent(
            job_index=job_index, asset_id=asset_id, extractor_run_id=run_id,
            occurrence_id=occurrence_id,
        )
        if helper is None:
            return None
        item = self.load_helper(helper, job_index)
        if (item.observation_type != "email_message" or item.asset_id != asset_id
                or item.extractor_run_id != run_id
                or item.location.get("message_occurrence_id") != occurrence_id):
            raise ContractValidationError("native export mail parent binding mismatch")
        source_occurrence_lineage_from_observation(item, authorized_source=self.source)
        return item

    def rows(self, shard):
        groups = defaultdict(list)
        for ref in self.lookup._read_shard_records("row", shard, cache={}):
            self.lookup._decode_shard_record("row", json.dumps(ref))
            if len(ref) != (6 if ref[0] == "row" else 7) or ref[1][7:9] != shard:
                raise ContractValidationError("native export shard reference mismatch")
            groups[ref[1]].append(ref)
        for row_key, refs in sorted(groups.items()):
            yield self.project_group(row_key, refs)

    def project_group(self, row_key, refs):
        if len({ref[2] for ref in refs}) != 1 or len({ref[-1] for ref in refs}) != 1:
            raise ContractValidationError("native export mixed row reference")
        job_index, inline = refs[0][2], refs[0][-1]
        members, hashes = [], {}
        for ref in refs:
            item = self.load(ref[2], ref[3], ref[4])
            if (item.observation_id in hashes or sha256_json(_table_row_key(item)) != row_key
                    or item.observation_type != ("table_row" if ref[0] == "row" else "table_cell")):
                raise ContractValidationError("native export row binding mismatch")
            members.append(item)
            hashes[item.observation_id] = ref[4]
        rows = [item for item in members if item.observation_type == "table_row"]
        cells = [item for item in members if item.observation_type == "table_cell"]
        if len(rows) != 1:
            raise ContractValidationError("native export row reference is incomplete")
        row = rows[0]
        indexes = [cell.location.get("cell_index") for cell in cells]
        if any(type(index) is not int or index < 0 for index in indexes) or len(set(indexes)) != len(indexes):
            raise ContractValidationError("native export cell positions are invalid")
        if any(cell.permission_scope != row.permission_scope or cell.extractor_run_id != row.extractor_run_id for cell in cells):
            raise ContractValidationError("native export cell scope mismatch")
        nested = (row.payload or {}).get("lineage", {})
        if (nested.get("source_family") == "mail_inline_table") != inline:
            raise ContractValidationError("native export family mismatch")
        parent_id = nested.get("parent_message_observation_id" if inline else "parent_attachment_observation_id")
        parent = self.parent(job_index, parent_id, row.asset_id)
        if ((inline and parent.observation_type != "email_message") or
                (not inline and (parent.observation_type != "email_attachment_occurrence"
                                 or (parent.payload or {}).get("child_asset_id") != row.asset_id))):
            raise ContractValidationError("native export parent binding mismatch")
        parent_lineage = source_occurrence_lineage_from_observation(parent, authorized_source=self.source)
        normalized_authorized_observation_lineages(
            (parent, *members), authorized_source=self.source, occurrence_lineages=(parent_lineage,),
        )
        mail = parent if inline else self.mail_parent(
            job_index, parent.asset_id, parent.extractor_run_id,
            parent.location.get("message_occurrence_id"),
        )
        return project_row(
            row, cells, parent, mail,
            job_fingerprint=self.revision.job_authorities[job_index].job_fingerprint,
            row_hash=hashes[row.observation_id], cell_hashes=hashes,
        )


def ratio_bucket(named, count):
    if named == 0:
        return "0"
    if named == count:
        return "100%"
    return "1-49%" if named * 2 < count else "50-99%"


def summarize(output, completed):
    """Aggregate only sealed committed rows; keep at most five samples/signature."""
    signatures, tables = {}, {}
    buckets, roles, families = Counter(), Counter(), Counter()
    total_rows = total_cells = named_cells = missing_dates = 0
    for shard, seal in sorted(completed.items()):
        digest = hashlib.sha256()
        size = count = cells_in_shard = 0
        with (output / f"rows-{shard}.jsonl").open("rb") as stream:
            for raw in stream:
                digest.update(raw)
                size += len(raw)
                row = json.loads(raw)
                cells = row["cells"]
                count += 1
                cells_in_shard += len(cells)
                total_rows += 1
                total_cells += len(cells)
                named_cells += row["named_cell_count"]
                missing_dates += not bool(row["sent_at"])
                buckets[ratio_bucket(row["named_cell_count"], len(cells))] += 1
                roles[str(row["row_role"])] += 1
                families[row["source_family"]] += 1
                table = tables.setdefault(row["table_id"], {
                    "table_id": row["table_id"], "source_family": row["source_family"],
                    "row_count": 0, "named_cell_count": 0, "column_counts": Counter(),
                    "cell_count": 0, "nonempty_cell_count": 0, "multiline_cell_count": 0,
                })
                table["row_count"] += 1
                table["named_cell_count"] += row["named_cell_count"]
                table["column_counts"][len(cells)] += 1
                table["cell_count"] += len(cells)
                table["nonempty_cell_count"] += sum(bool(cell["text"].strip()) for cell in cells)
                table["multiline_cell_count"] += sum("\n" in cell["text"] for cell in cells)
                key = row["header_signature_hash"]
                if key is not None:
                    signature = signatures.setdefault(key, {
                        "header_signature_hash": key, "column_names": row["header_signature"],
                        "row_count": 0, "sample_cells": [],
                    })
                    if signature["column_names"] != row["header_signature"]:
                        raise ContractValidationError("native export signature collision")
                    signature["row_count"] += 1
                    if len(signature["sample_cells"]) < 5:
                        signature["sample_cells"].append([cell["text"] for cell in cells])
        observed = {"sha256": "sha256:" + digest.hexdigest(), "size_bytes": size,
                    "row_count": count, "cell_count": cells_in_shard}
        if any(observed[key] != seal[key] for key in observed):
            raise ContractValidationError("native export committed shard changed")
    no_names = []
    for table_id in sorted(tables):
        table = tables[table_id]
        if table["named_cell_count"] == 0 and len(no_names) < 20:
            widths = table["column_counts"]
            no_names.append({
                **table, "column_counts": {str(key): value for key, value in sorted(widths.items())},
                "layout_assessment": "possible_layout_by_shape" if max(widths) <= 2 or len(widths) > 1 else "undetermined",
            })
    summary = {
        "table_count": len(tables), "row_count": total_rows, "cell_count": total_cells,
        "named_cell_count": named_cells,
        "named_cell_ratio": named_cells / total_cells if total_cells else 0,
        "named_cell_ratio_row_distribution": {key: buckets[key] for key in ("0", "1-49%", "50-99%", "100%")},
        "ratio_bucket_definition": "0; 0 < fraction < 0.5; 0.5 <= fraction < 1; 1",
        "complete_header_row_ratio": buckets["100%"] / total_rows if total_rows else 0,
        "row_roles": dict(roles), "source_families": dict(families),
        "rows_without_mail_sent_at": missing_dates,
        "distinct_header_signatures": len(signatures),
        "top_header_signatures": [{"column_names": item["column_names"], "row_count": item["row_count"]}
            for item in sorted(signatures.values(), key=lambda item: (-item["row_count"], item["header_signature_hash"]))[:30]],
        "tables_without_named_cells": sum(table["named_cell_count"] == 0 for table in tables.values()),
        "unnamed_table_samples": no_names,
        "layout_assessment_rule": "Shape-only indication when maximum width is at most two cells or row widths vary; remaining tables need human assessment.",
    }
    return summary, [signatures[key] for key in sorted(signatures)]


def export_rows(native, output, binding, *, max_shards=None):
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".export.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _export_locked(native, output, binding, max_shards=max_shards)


def _export_locked(native, output, binding, *, max_shards):
    started = time.monotonic()
    checkpoint_path = output / "checkpoint.safe.json"
    checkpoint = {"artifact_id": ARTIFACT_ID, "binding": binding, "completed_shards": {}, "export_seconds": 0}
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_bytes())
        if checkpoint.get("artifact_id") != ARTIFACT_ID or checkpoint.get("binding") != binding:
            raise ContractValidationError("native export checkpoint binding changed")
    else:
        atomic_write(checkpoint_path, json_bytes(checkpoint))
    completed = checkpoint["completed_shards"]
    if set(completed) - set(native.shards):
        raise ContractValidationError("native export checkpoint shard scope changed")
    for shard, seal in completed.items():
        observed = file_seal(output / f"rows-{shard}.jsonl")
        if any(observed[key] != seal[key] for key in observed):
            raise ContractValidationError("native export checkpoint bytes changed")
    new_shards = 0
    for shard in native.shards:
        if shard in completed:
            continue
        if max_shards is not None and new_shards >= max_shards:
            break
        shard_started = time.monotonic()
        path = output / f"rows-{shard}.jsonl"
        temporary = path.with_name(path.name + ".tmp")
        digest = hashlib.sha256()
        row_count = cell_count = size = 0
        with temporary.open("wb") as stream:
            for row in native.rows(shard):
                raw = json_bytes(row)
                stream.write(raw)
                digest.update(raw)
                row_count += 1
                cell_count += len(row["cells"])
                size += len(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        elapsed = time.monotonic() - shard_started
        completed[shard] = {"sha256": "sha256:" + digest.hexdigest(), "size_bytes": size,
                            "row_count": row_count, "cell_count": cell_count,
                            "seconds": round(elapsed, 3)}
        checkpoint["export_seconds"] += elapsed
        atomic_write(checkpoint_path, json_bytes(checkpoint))
        new_shards += 1
        print(json.dumps({"phase": "shard_committed", "shard": shard, "rows": row_count,
                          "completed_shards": len(completed), "seconds": round(elapsed, 2)}), flush=True)
    complete = len(completed) == len(native.shards)
    totals = {key: sum(seal[key] for seal in completed.values()) for key in ("row_count", "cell_count", "size_bytes")}
    summary = {"artifact_id": ARTIFACT_ID, "status": "in_progress", "binding": binding,
               "completed_shards": len(completed), "total_shards": len(native.shards),
               "row_count": totals["row_count"], "cell_count": totals["cell_count"],
               "row_output_bytes": totals["size_bytes"], "export_seconds": round(checkpoint["export_seconds"], 3),
               "source_binding_validated": True, "methodology_claim_status": "blocked"}
    if complete:
        if totals["row_count"] != native.counts["table_row"] or totals["cell_count"] != native.counts["table_cell"]:
            raise ContractValidationError("native export whole-source count mismatch")
        aggregates, signatures = summarize(output, completed)
        signature_path = output / "header_signatures.jsonl"
        temporary = signature_path.with_name(signature_path.name + ".tmp")
        with temporary.open("wb") as stream:
            for signature in signatures:
                stream.write(json_bytes(signature))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(signature_path)
        summary.update(aggregates, status="complete", header_signature_output_bytes=signature_path.stat().st_size)
        summary["data_output_bytes"] = totals["size_bytes"] + signature_path.stat().st_size
    summary["current_invocation_seconds"] = round(time.monotonic() - started, 3)
    atomic_write(output / "summary.safe.json", json_bytes(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision-dir", type=Path, required=True)
    parser.add_argument("--revision-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-shards", type=int)
    args = parser.parse_args()
    if args.max_shards is not None and args.max_shards < 1:
        parser.error("--max-shards must be positive")
    started = time.monotonic()
    print(json.dumps({"phase": "loading_sealed_source"}), flush=True)
    revision = load_issue56_ingestion_revision(args.revision_dir, expected_revision_sha256=args.revision_sha256)
    native = NativeRows(revision)
    binding = {"schema_version": 1, "source_revision_sha256": args.revision_sha256,
               "source_authority_fingerprint": revision.safe_binding["source_authority_fingerprint"],
               "exact_manifest_fingerprint": native.lookup._manifest["manifest_fingerprint"],
               "exporter_sha256": file_seal(Path(__file__))["sha256"]}
    print(json.dumps({"phase": "source_loaded", "seconds": round(time.monotonic()-started, 3),
                      "expected_rows": native.counts["table_row"], "expected_cells": native.counts["table_cell"]}), flush=True)
    result = export_rows(native, args.output_dir, binding, max_shards=args.max_shards)
    print(json.dumps({"phase": "export_finished", "status": result["status"],
                      "row_count": result["row_count"], "seconds": round(time.monotonic()-started, 3)}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"phase": "export_failed", "error_type": type(exc).__name__,
                          "errno": getattr(exc, "errno", None),
                          "frames": [{"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                                     for frame in traceback.extract_tb(exc.__traceback__)]}), flush=True)
        raise SystemExit(1)
