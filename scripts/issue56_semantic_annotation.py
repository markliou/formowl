#!/usr/bin/env python3
"""Offline ontology-aware semantic annotation of a frozen, query-independent scope.

``scope``: every message whose Date header falls in ``--month`` plus every attachment
Observation whose lineage ``attachment_source_ref.source_key`` is one of those messages.
A unit is one message (headers, body segments, body tables, message/attachment-occurrence
records) or one attachment asset; long units are split into focus chunks, with the
message headers (and a table's first row) carried as context. ``table_cell`` rows decompose
``table_row`` text that is read and stay available to deterministic execution;
``email_thread``/``mail_folder_occurrence`` are lineage handled deterministically.

``run``: each unit goes through ``graph.candidates.read_and_store_source_unit`` with
``LocalOllamaReader``, one thread per endpoint, resumable per run id. A unit that did
not end ``annotated`` is retried only under a NEW run id (the contract's rule).
"""

from __future__ import annotations

import argparse
import collections
import email.utils
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

HEADERS = ("subject", "from", "to", "cc", "date")
STRUCTURAL = {"email_thread", "mail_folder_occurrence"}
CELL = "table_cell"
BODY_TYPES = ("email_body_segment", "table_row", "paragraph", "list_item", "heading")


def _text_len(observation) -> int:
    return len(observation.text or "") + len(json.dumps(observation.payload or {}, ensure_ascii=False)) // 4


def chunks(items: list[tuple[str, int]], budget: int) -> list[list[str]]:
    """Consecutive groups of at most ``budget`` estimated chars; one oversize item stays whole."""
    out, current, size = [], [], 0
    for observation_id, length in items:
        if current and size + length > budget:
            out.append(current)
            current, size = [], 0
        current.append(observation_id)
        size += length
    if current:
        out.append(current)
    return out


def build_scope(jobs: list[tuple[str, str, str | None]], month: str, focus_chars: int):
    from formowl_ingestion.storage.records import JobStore, ObservationStore

    units, counts = [], collections.Counter()
    for root, mail_job, attach_job in jobs:
        observations = ObservationStore(root)
        messages = collections.defaultdict(lambda: {"head": {}, "body": [], "meta": [], "month": None})
        for observation_id in JobStore(root).get(mail_job).observation_ids:
            o = observations.get(observation_id)
            occurrence = (o.location or {}).get("message_occurrence_id")
            kind = o.observation_type
            if kind in STRUCTURAL or kind == CELL:
                counts[f"excluded:{kind}"] += 1
                continue
            if (o.payload or {}).get("lineage", {}).get("attachment_source_ref"):
                continue  # attachment content is grouped by asset below
            if not occurrence:
                counts[f"unassigned:{kind}"] += 1
                continue
            message = messages[occurrence]
            if kind == "email_header":
                name = (o.payload or {}).get("header_name", "").lower()
                if name == "date":
                    try:
                        message["month"] = email.utils.parsedate_to_datetime(
                            o.payload.get("header_value")).strftime("%Y-%m")
                    except Exception:
                        message["month"] = "unparsed"
                (message["head"].setdefault(name, []) if name in HEADERS else message["meta"]).append(
                    (observation_id, _text_len(o)))
            elif kind in BODY_TYPES:
                location = o.location or {}
                message["body"].append((location.get("mime_ordinal") or 0, location.get("body_segment_index") or 0,
                                        location.get("row_index") or 0, observation_id, _text_len(o)))
            else:
                message["meta"].append((observation_id, _text_len(o)))
        scoped = {key: value for key, value in messages.items() if value["month"] == month}
        counts[f"messages_in_scope:{mail_job}"] = len(scoped)
        for occurrence, message in sorted(scoped.items()):
            context = [oid for name in HEADERS for oid, _ in message["head"].get(name, [])]
            other_head = [(oid, n) for items in message["head"].values() for oid, n in items if oid not in context]
            focus = [(oid, n) for *_, oid, n in sorted(message["body"])] + message["meta"] + other_head
            parts = chunks(focus, focus_chars) or [[]]
            for index, part in enumerate(parts):
                units.append({"unit_id": f"msg:{occurrence}:{index}", "kind": "mail", "store": root,
                              "parent": occurrence, "observation_ids": context + part,
                              "focus_observation_ids": (context if index == 0 else []) + part})
            counts["message_units"] += len(parts)
        assets = collections.defaultdict(lambda: {"rows": [], "parent": None})
        for job_id in [mail_job] + ([attach_job] if attach_job else []):
            for observation_id in JobStore(root).get(job_id).observation_ids:
                o = observations.get(observation_id)
                parent = ((o.payload or {}).get("lineage", {}).get("attachment_source_ref") or {}).get("source_key")
                if not parent or parent not in scoped:
                    continue
                if o.observation_type == CELL:
                    counts["excluded:attachment_table_cell"] += 1
                    continue
                asset = assets[o.asset_id]
                asset["parent"] = parent
                location = o.location or {}
                asset["rows"].append((location.get("member_path_index") or 0, location.get("sheet_index") or 0,
                                      location.get("table_index") or 0, location.get("page") or 0,
                                      location.get("block_index") or 0, location.get("row_index") or 0,
                                      observation_id, _text_len(o), o.observation_type))
        for asset_id, asset in sorted(assets.items()):
            head = [oid for name in ("subject", "from", "date")
                    for oid, _ in scoped[asset["parent"]]["head"].get(name, [])]
            rows = sorted(asset["rows"])
            first_row = next((row[6] for row in rows if row[8] == "table_row"), None)
            parts = chunks([(row[6], row[7]) for row in rows], focus_chars)
            for index, part in enumerate(parts):
                context = head + ([first_row] if first_row and index > 0 and first_row not in part else [])
                units.append({"unit_id": f"att:{asset_id}:{index}", "kind": "attachment", "store": root,
                              "parent": asset["parent"], "observation_ids": context + part,
                              "focus_observation_ids": part})
            counts["attachment_assets"] += 1
            counts["attachment_units"] += len(parts)
    return units, counts


def scope_command(args) -> int:
    jobs = [(store, mail, attach or None) for store, mail, attach in args.job]
    units, counts = build_scope(jobs, args.month, args.focus_chars)
    out = Path(args.output)
    with out.open("w") as handle:
        for unit in units:
            handle.write(json.dumps(unit) + "\n")
    manifest = {"scope_rule": f"Date header month == {args.month}; attachments by lineage source_key",
                "focus_chars": args.focus_chars, "excluded_types": sorted(STRUCTURAL | {CELL}), "counts": counts,
                "units_sha256": "sha256:" + hashlib.sha256(out.read_bytes()).hexdigest()}
    Path(f"{out}.manifest.json").write_text(json.dumps(manifest, indent=1, default=dict))
    print(json.dumps(manifest, default=dict))
    return 0


class _RecordingLedgerStore:
    """Per-lane view of the shared ledger store that remembers the last ledger written."""

    def __init__(self, store) -> None:
        self.store, self.last = store, None

    def create(self, ledger):
        self.last = self.store.create(ledger)
        return self.last

    def get(self, ledger_id):
        return self.store.get(ledger_id)


_REASON_HINTS = {
    "provider_incomplete": "上一次輸出超過長度上限而被截斷；請只保留最重要的事實（最多 40 筆），quote 盡量短但必須唯一。",
    "schema_output_invalid": "上一次輸出不是完整的 JSON；請輸出完整、有效的 JSON。",
    "candidate_outside_focus": "每筆事實的 evidence 必須引用 focus_observation_ids 中的原文。",
    "time_surface_mismatch": "times.raw 必須逐字出現在 times.quote 之中。",
    "identity_surface_mismatch": "subject 與 subject_label 必須逐字出現在 subject_quote 之中。",
    "atomic_property_missing": "非 entity 的每筆紀錄都要有 property。",
}


def retry_feedback(units: dict, progress_path: Path, raw_path: Path, from_run: str) -> dict[str, list[str]]:
    """Units of ``from_run`` that did not end annotated, with problems recomputed from their raw output."""
    from formowl_graph.local_semantic_reader import Adapter
    from formowl_ingestion.storage.records import ObservationStore

    last = {}
    for row in map(json.loads, progress_path.open()):
        if row["run"] == from_run:
            last[row["unit"]] = row
    raw = {}
    if raw_path.exists():
        raw = {row["unit"]: row["content"] for row in map(json.loads, raw_path.open())}
    stores: dict[str, ObservationStore] = {}
    feedback = {}
    for unit_id, row in last.items():
        if row["status"] == "annotated" or row.get("reason") == "source_incomplete_or_unit_limit":
            continue  # done, or not fixable by asking again
        problems = []
        unit = units[unit_id]
        try:
            store = stores.setdefault(unit["store"], ObservationStore(unit["store"]))
            adapter = Adapter({oid: store.get(oid).to_dict() for oid in unit["observation_ids"]})
            adapter.convert(json.loads(raw[unit_id]))
            problems = adapter.problems
        except (KeyError, ValueError, TypeError):
            pass
        hint = _REASON_HINTS.get(row.get("reason"))
        feedback[unit_id] = problems + ([hint] if hint and hint not in problems else [])
    return feedback


def run_command(args, feedback: dict[str, list[str]] | None = None) -> int:
    from formowl_contract import sha256_json
    from formowl_graph.candidates import read_and_store_source_unit
    from formowl_graph.local_semantic_reader import LocalOllamaReader
    from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore, SemanticMetadataStore
    from formowl_ingestion.storage.records import ObservationStore

    out = Path(args.output)
    progress_path = out / "progress.jsonl"
    stores = {"semantic_metadata_store": SemanticMetadataStore(out),
              "candidate_atom_store": CandidateAtomStore(out),
              "candidate_relation_store": CandidateRelationStore(out)}
    done = set()
    if progress_path.exists():
        done = {row["unit"] for row in map(json.loads, progress_path.open()) if row["run"] == args.run_id}
    work: queue.Queue = queue.Queue()
    for line in open(args.units):
        unit = json.loads(line)
        if unit["unit_id"] not in done and (feedback is None or unit["unit_id"] in feedback):
            work.put(unit)
    print(json.dumps({"run": args.run_id, "queued": work.qsize(), "already_done": len(done)}), flush=True)
    observation_stores: dict[str, ObservationStore] = {}
    lock = threading.Lock()

    def lane(url: str) -> None:
        reader = LocalOllamaReader(url, args.model)
        ledgers = _RecordingLedgerStore(stores["semantic_metadata_store"])
        lane_stores = {**stores, "semantic_metadata_store": ledgers}
        while True:
            try:
                unit = work.get_nowait()
            except queue.Empty:
                return
            with lock:
                store = observation_stores.setdefault(unit["store"], ObservationStore(unit["store"]))
            items = [store.get(observation_id) for observation_id in unit["observation_ids"]]
            row = {"run": args.run_id, "unit": unit["unit_id"], "kind": unit["kind"], "lane": url.rsplit(":", 1)[-1],
                   "source_unit_id": "su_" + sha256_json(unit["unit_id"])[7:39]}
            reader.last, ledgers.last = {}, None
            reader.feedback = list((feedback or {}).get(unit["unit_id"], []))
            started = time.time()
            try:
                result = read_and_store_source_unit(
                    source_unit_id=row["source_unit_id"], observations=items,
                    expected_observation_hashes={o.observation_id: sha256_json(o.to_dict()) for o in items},
                    source_revision_fingerprint=args.source_revision,
                    permission_scope_fingerprint=sha256_json(items[0].to_dict()["permission_scope"]),
                    source_complete=True, extractor_run_id=args.run_id, ontology_revision_id=args.ontology_revision,
                    model_name=args.model, reasoning_effort="none", reader=reader.extract_structured_json,
                    configuration=reader.configuration, focus_observation_ids=unit["focus_observation_ids"],
                    **lane_stores)
                value = result.read_ledger.value
                row.update(status=value["annotation_status"],
                           reason=value.get("failure_reason") or value.get("stop_reason"),
                           atoms=len(result.candidate_atoms), relations=len(result.candidate_relations),
                           ledger=result.read_ledger.semantic_metadata_id)
            except Exception as exc:
                value = ledgers.last.value if ledgers.last is not None else {}
                row.update(status=value.get("annotation_status", "error"),
                           reason=value.get("failure_reason") or value.get("stop_reason") or str(exc)[:120],
                           ledger=ledgers.last.semantic_metadata_id if ledgers.last is not None else None)
            if feedback is not None:
                row["retry_of"] = args.from_run
            row.update(seconds=round(time.time() - started, 1),
                       **{key: value for key, value in reader.last.items() if key != "content"})
            with lock:
                with progress_path.open("a") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                if reader.last.get("content") is not None:
                    with (out / f"raw-{args.run_id}.jsonl").open("a") as handle:
                        handle.write(json.dumps({"unit": unit["unit_id"], "content": reader.last["content"]},
                                                ensure_ascii=False) + "\n")

    threads = [threading.Thread(target=lane, args=(url,)) for url in args.urls.split(",")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    print(json.dumps({"run": args.run_id, "finished": True}), flush=True)
    return 0


def report_command(args) -> int:
    """Per-scope ledger summary: each unit's best status over the given runs. Gaps stay gaps."""
    from formowl_contract import sha256_json

    units = [json.loads(line)["unit_id"] for line in open(args.units)]
    runs = list(args.run_id)
    best: dict[str, dict] = {}
    for row in map(json.loads, (Path(args.output) / "progress.jsonl").open()):
        current = best.get(row["unit"])
        if row["run"] in runs and (current is None or current["status"] != "annotated"):
            best[row["unit"]] = row  # an annotated read stands; otherwise the latest attempt
    status = collections.Counter()
    reasons = collections.Counter()
    for unit_id in units:
        row = best.get(unit_id)
        state = "not_attempted" if row is None else row["status"]
        status[state] += 1
        if row is not None and state != "annotated":
            reasons[row.get("reason") or "unknown"] += 1
    coverage = {unit_id: [best[unit_id]["run"], best[unit_id].get("ledger")] for unit_id in units
                if best.get(unit_id, {}).get("status") == "annotated"}
    report = {"artifact_id": "formowl_semantic_annotation_scope_report_v1",
              "units_sha256": "sha256:" + hashlib.sha256(Path(args.units).read_bytes()).hexdigest(),
              "run_ids": runs, "unit_count": len(units), "status_counts": dict(status),
              "gap_reasons": dict(reasons.most_common()),
              "candidate_atoms": sum(best[u].get("atoms") or 0 for u in coverage),
              "annotated_coverage_fingerprint": sha256_json(coverage),
              "scope_complete": status["annotated"] == len(units)}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    scope = commands.add_parser("scope")
    scope.add_argument("--job", nargs=3, action="append", required=True, metavar=("STORE", "MAIL_JOB", "ATTACH_JOB"),
                       help="ATTACH_JOB may be '' when attachments live in the mail job")
    scope.add_argument("--month", required=True)
    scope.add_argument("--focus-chars", type=int, default=3500)
    scope.add_argument("--output", required=True)
    run = commands.add_parser("run")
    retry = commands.add_parser("retry", help="rerun units that did not end annotated, with feedback")
    retry.add_argument("--from-run", required=True)
    for sub in (run, retry):
        _run_arguments(sub)
    report = commands.add_parser("report", help="per-scope ledger summary over one or more runs")
    report.add_argument("--units", required=True)
    report.add_argument("--output", required=True)
    report.add_argument("--run-id", action="append", required=True)
    args = parser.parse_args(argv)
    if args.command == "scope":
        return scope_command(args)
    if args.command == "report":
        return report_command(args)
    if args.command == "retry":
        if args.from_run == args.run_id:
            parser.error("a retry needs a NEW run id")
        units = {json.loads(line)["unit_id"]: json.loads(line) for line in open(args.units)}
        out = Path(args.output)
        return run_command(args, retry_feedback(units, out / "progress.jsonl", out / f"raw-{args.from_run}.jsonl",
                                                args.from_run))
    return run_command(args)


def _run_arguments(run) -> None:
    run.add_argument("--units", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--source-revision", required=True)
    run.add_argument("--ontology-revision", default="issue56_core_ontology_candidate_v1")
    run.add_argument("--model", default="hf.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf:latest")
    run.add_argument("--urls", default=os.environ.get("FORMOWL_OLLAMA_URLS", "http://127.0.0.1:11434"))


if __name__ == "__main__":
    raise SystemExit(main())
