#!/usr/bin/env python3
"""Offline, query-independent attachment backfill using existing ingestion owners.

Use registered child Assets or the retained readpst -S sidecar adapter. The
private ledger contains only job/run references and input/config seals; evidence
remains in the existing Observation JSON store. Failed/interrupted extraction
requires a new batch ID, never overwriting an old run.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Sequence
import uuid

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "python"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import sha256_json, stable_extractor_run_id, stable_ingestion_job_id, to_plain  # noqa: E402
from formowl_ingestion.extraction import extraction_config_hash  # noqa: E402
from formowl_ingestion.extractors.document import AttachmentDocumentExtractor  # noqa: E402
from formowl_ingestion.extractors.mail.pst import (  # noqa: E402
    ReadpstSidecarBackfillExtractor, ReadpstSidecarParentBinding,
    _readpst_separate_attachment_index, _readpst_sidecar_parent_window,
)
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job  # noqa: E402
from formowl_ingestion.storage import (  # noqa: E402
    AssetStore, ExtractorRunStore, FileObjectStore, JobStore, ObservationStore,
    StorageBackendRegistry,
)

ARTIFACT_ID = "formowl_issue56_attachment_backfill_ledger_v1"
CONFIG_VERSION = "issue56_attachment_backfill_config_v1"


class BackfillError(RuntimeError):
    """Stable public-safe operator reason."""


def _report_object_verification(facts):
    if not facts["verified"]:
        # Same-call facts only: no second source read, locator, or exception text.
        print(json.dumps({"phase": "object_verification", **facts}, sort_keys=True),
              file=sys.stderr)


def _read(path):
    try:
        value = json.loads(Path(path).read_bytes())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError) as exc:
        raise BackfillError("artifact_unreadable") from exc


def _save(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def _locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackfillError("batch_already_running") from exc
        yield


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _export_seal(root, *, config=None):
    root = Path(root).resolve()
    by_parent, detached = _readpst_separate_attachment_index(root)
    if not detached:
        raise BackfillError("sidecar_export_empty")
    try:
        selected, window, _ = _readpst_sidecar_parent_window(
            by_parent, export_root=root, config=config or {},
        )
    except ValueError as exc:
        raise BackfillError("sidecar_parent_window_invalid") from exc
    if window is not None:
        by_parent = dict(selected)
        detached = [path for _, children in selected for path in children]
    digest = hashlib.sha256()
    count = 0
    for path in sorted({*by_parent, *detached}):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise BackfillError("sidecar_export_path_invalid")
        digest.update(sha256_json([
            str(path.relative_to(root)), _hash_file(path), path.stat().st_size,
        ]).encode("ascii"))
        count += 1
    return {"file_count": count, "sidecar_count": len(detached),
            **({"parent_window": window} if window is not None else {}),
            "file_stream_fingerprint": "sha256:" + digest.hexdigest()}


def _source(store_directory, manifest_path):
    stores = (AssetStore(store_directory), JobStore(store_directory),
              ExtractorRunStore(store_directory), ObservationStore(store_directory))
    assets, jobs, runs, observations = stores
    manifest = _read(manifest_path)
    fingerprint = manifest.pop("artifact_fingerprint", None)
    if fingerprint is not None and fingerprint != sha256_json(manifest):
        raise BackfillError("parent_manifest_seal_invalid")
    if fingerprint is not None:
        manifest["artifact_fingerprint"] = fingerprint
    job = jobs.get(manifest.get("prior_ingestion_job_id", ""))
    asset = assets.get(job.asset_id) if job else None
    records = manifest.get("records")
    if (
        job is None or asset is None or job.status != "succeeded"
        or asset.lifecycle_state != "active"
        or job.requested_by != asset.owner_user_id or job.workspace_id != asset.workspace_id
        or to_plain(job.permission_scope) != to_plain(asset.permission_scope)
        or manifest.get("schema_version") != 1
        or manifest.get("source_asset_id") != asset.asset_id
        or manifest.get("source_fingerprint") != asset.content_hash
        or manifest.get("prior_job_fingerprint") != sha256_json(job.to_dict())
        or manifest.get("permission_scope_fingerprint") != sha256_json(asset.permission_scope)
        or not isinstance(records, list) or not records
        or manifest.get("parent_binding_count") != len(records)
        or manifest.get("parent_binding_fingerprint") != sha256_json(records)
    ):
        raise BackfillError("parent_manifest_binding_invalid")
    run = runs.get(manifest.get("prior_parent_run_id", ""))
    if (
        run is None or run.status != "succeeded" or run.asset_id != asset.asset_id
        or run.input_hash != asset.content_hash or run.extractor_run_id not in job.extractor_run_ids
    ):
        raise BackfillError("parent_run_binding_invalid")
    parent_ids = set()
    occurrences = set()
    for record in records:
        try:
            ReadpstSidecarParentBinding.from_dict(record)
        except (TypeError, ValueError) as exc:
            raise BackfillError("parent_record_invalid") from exc
        parent_id = record["parent_observation_id"]
        if parent_id in parent_ids:
            raise BackfillError("parent_job_membership_invalid")
        parent_ids.add(parent_id)
        # The binding already pins the parent asset, run, permission scope,
        # and source occurrence.  A keyed lookup is the bounded membership
        # check; never enumerate the multi-million-observation store here.
        parent = observations.get(parent_id)
        if (
            parent is None or parent.observation_type != "email_message" or parent.modality != "mail"
            or parent.asset_id != asset.asset_id or parent.extractor_run_id != run.extractor_run_id
            or record["parent_extractor_run_id"] != run.extractor_run_id
            or to_plain(parent.permission_scope) != to_plain(asset.permission_scope)
            or any(record[k] != parent.location.get(k) for k in (
                "source_content_hash", "folder_path_hash", "message_id", "message_index",
                "archive_id", "mailbox_id", "message_occurrence_id", "thread_id"))
            or record["parent_source_inventory_id"] != parent.location.get("source_inventory_id")
            or record["parent_source_inventory_item_id"] != parent.location.get("source_inventory_item_id")
            or record["message_fingerprint"] != (parent.payload or {}).get("message_fingerprint")
            or record["message_occurrence_id"] in occurrences
        ):
            raise BackfillError("parent_observation_binding_invalid")
        occurrences.add(record["message_occurrence_id"])
    return stores, manifest, job, asset


def _ledger(path, binding, batch_id):
    if Path(path).exists():
        ledger = _read(path)
        fingerprint = ledger.pop("ledger_fingerprint", None)
        if (
            fingerprint != sha256_json(ledger) or ledger.get("artifact_id") != ARTIFACT_ID
            or ledger.get("binding") != binding
            or (batch_id is not None and ledger.get("batch_id") != batch_id)
        ):
            raise BackfillError("batch_ledger_binding_invalid")
        return ledger
    ledger = {"artifact_id": ARTIFACT_ID, "binding": binding,
              "batch_id": batch_id or uuid.uuid4().hex, "records": {},
              "source_completeness_certified": False}
    _write_ledger(path, ledger)
    return ledger


def _write_ledger(path, ledger):
    _save(path, {**ledger, "ledger_fingerprint": sha256_json(ledger)})


def _job_record(job, runs, observations):
    run_records = [runs.get(value) for value in job.extractor_run_ids]
    if any(run is None for run in run_records):
        raise BackfillError("backfill_run_missing")
    digest = hashlib.sha256()
    for value in job.observation_ids:
        observation = observations.get(value)
        if observation is None:
            raise BackfillError("backfill_observation_missing")
        digest.update(sha256_json(observation.to_dict()).encode("ascii"))
    warnings = Counter(code for run in run_records for code in run.warnings)
    errors = Counter(code for run in run_records for code in run.errors)
    if job.error:
        errors[job.error] += 1
    return {
        "ingestion_job_id": job.ingestion_job_id, "status": job.status,
        "job_fingerprint": sha256_json(job.to_dict()),
        "run_fingerprints": [sha256_json(run.to_dict()) for run in run_records],
        "observation_count": len(job.observation_ids),
        "observation_stream_fingerprint": "sha256:" + digest.hexdigest(),
        "warning_code_counts": dict(warnings), "error_code_counts": dict(errors),
        "incomplete_run_count": sum(bool(run.errors or run.warnings) for run in run_records),
    }


def _execute(*, stores, asset, adapter, config, object_store, materialize, previous=None):
    assets, jobs, runs, observations = stores
    config_hash = extraction_config_hash(config)
    job_id = stable_ingestion_job_id(
        asset_id=asset.asset_id, requested_by=asset.owner_user_id,
        workspace_id=asset.workspace_id, extractor_names=[adapter.name()], config_hash=config_hash)
    existing = jobs.get(job_id)
    if existing is not None:
        if existing.status not in {"succeeded", "failed"}:
            raise BackfillError("interrupted_job_requires_new_batch")
        record = _job_record(existing, runs, observations)
        if previous is not None and record != previous:
            raise BackfillError("backfill_output_changed")
        return record
    if previous is not None:
        raise BackfillError("backfill_job_missing")
    run_id = stable_extractor_run_id(
        asset_id=asset.asset_id, extractor_name=adapter.name(), extractor_version=adapter.version(),
        extractor_type=adapter.extractor_type(), input_hash=asset.content_hash, config_hash=config_hash)
    if runs.get(run_id) is not None:
        raise BackfillError("immutable_run_id_collision")
    job = create_ingestion_job(asset=asset, job_store=jobs, requested_by=asset.owner_user_id,
                               extractor_adapters=[adapter], config=config)
    job = run_ingestion_job(
        ingestion_job_id=job.ingestion_job_id, asset_store=assets, job_store=jobs,
        object_store=object_store, extractor_run_store=runs, observation_store=observations,
        extractor_adapters=[adapter], config=config,
        attachment_asset_store=assets if materialize else None)
    return _job_record(job, runs, observations)


def run_attachment_backfill(*, store_directory, parent_binding_manifest_path, ledger_path,
                            mode="pst-sidecar", existing_export_root=None, config=None, batch_id=None):
    """Pinned batch API. Selection depends only on retained source inventory."""
    with _locked(ledger_path):
        stores, manifest, prior, root_asset = _source(store_directory, parent_binding_manifest_path)
        assets, jobs, runs, observations = stores
        parser = AttachmentDocumentExtractor()
        settings = to_plain(dict(config or {}))
        if any(not key.startswith("attachment_") and key != "max_attachment_hash_bytes" for key in settings):
            raise BackfillError("unsupported_backfill_config")
        binding = {
            "mode": mode, "store_fingerprint": sha256_json(str(Path(store_directory).resolve())),
            "source_asset_fingerprint": sha256_json(root_asset.to_dict()),
            "parent_manifest_fingerprint": sha256_json(manifest),
            "prior_job_fingerprint": sha256_json(prior.to_dict()),
            "prior_parent_run_fingerprint": sha256_json(runs.get(manifest["prior_parent_run_id"]).to_dict()),
            "document_parser_name": parser.name(), "document_parser_version": parser.version(),
            "config": settings, "config_version": CONFIG_VERSION,
        }
        registry = StorageBackendRegistry(store_directory)
        object_store = FileObjectStore(registry, verification_observer=_report_object_verification)
        tasks = []
        if mode == "pst-sidecar":
            if existing_export_root is None:
                raise BackfillError("sidecar_export_required")
            marker = _read(Path(existing_export_root).parent / "readpst-export-complete.json")
            if marker.get("source_fingerprint") != root_asset.content_hash:
                raise BackfillError("export_marker_source_mismatch")
            seal = _export_seal(existing_export_root, config=settings)
            adapter = ReadpstSidecarBackfillExtractor(
                existing_export_root=existing_export_root, parent_binding_manifest=manifest)
            binding.update(export_seal=seal, export_marker_fingerprint=sha256_json(marker),
                           sidecar_parser_version=adapter.version())
            tasks.append((root_asset, adapter, {
                "existing_export_binding_fingerprint": sha256_json(marker),
                "parent_binding_manifest_fingerprint": sha256_json(manifest),
                "prior_ingestion_job_id": prior.ingestion_job_id,
                "prior_job_fingerprint": manifest["prior_job_fingerprint"],
                "prior_parent_run_id": manifest["prior_parent_run_id"],
                "repair_missing_sidecar_parents": False,
                "attachment_compact_child_results": True,
            }))
        elif mode == "registered":
            # One source-order keyed pass; never enumerate the Observation store.
            children = {}
            for observation_id in prior.observation_ids:
                occurrence = observations.get(observation_id)
                if occurrence is None:
                    raise BackfillError("source_observation_missing")
                payload = occurrence.payload or {}
                child_id = payload.get("child_asset_id")
                if occurrence.observation_type != "email_attachment_occurrence" or not child_id:
                    continue
                child = assets.get(child_id)
                if (
                    child is None or child.lifecycle_state != "active"
                    or child.workspace_id != root_asset.workspace_id
                    or child.owner_user_id != root_asset.owner_user_id
                    or child.content_hash != payload.get("content_hash")
                    or to_plain(child.permission_scope) != to_plain(root_asset.permission_scope)
                    or to_plain(occurrence.permission_scope) != to_plain(root_asset.permission_scope)
                    or occurrence.asset_id != root_asset.asset_id
                    or child_id in children
                ):
                    raise BackfillError("registered_attachment_binding_invalid")
                children[child_id] = sha256_json([child.to_dict(), occurrence.to_dict()])
                tasks.append((child, parser, {
                    "parent_asset_id": root_asset.asset_id,
                    "parent_source_ref": to_plain(root_asset.source_ref),
                    "attachment_source_ref": to_plain(child.source_ref),
                    "parent_attachment_observation_id": occurrence.observation_id,
                    "parent_attachment_observation_fingerprint": sha256_json(occurrence.to_dict()),
                }))
            binding["registered_inputs_fingerprint"] = sha256_json(children)
            binding["registered_asset_count"] = len(tasks)
        else:
            raise BackfillError("backfill_mode_invalid")
        ledger = _ledger(ledger_path, binding, batch_id)
        for asset, adapter, task_config in tasks:
            extraction_config = {
                **settings, **task_config, "backfill_batch_id": ledger["batch_id"],
                "backfill_config_version": CONFIG_VERSION,
                "input_binding_fingerprint": sha256_json(binding),
                # Existing materializer forwards attachment_* keys to child runs.
                "attachment_backfill_batch_id": ledger["batch_id"],
                "attachment_document_parser_version": parser.version(),
            }
            record = _execute(
                stores=stores, asset=asset, adapter=adapter, config=extraction_config,
                object_store=object_store, materialize=mode == "pst-sidecar",
                previous=ledger["records"].get(asset.asset_id))
            if mode == "pst-sidecar" and _export_seal(
                existing_export_root, config=settings,
            ) != binding["export_seal"]:
                raise BackfillError("retained_export_drift")
            ledger["records"][asset.asset_id] = record
            _write_ledger(ledger_path, ledger)
        return _report(ledger)


def _report(ledger):
    records = list(ledger["records"].values())
    warnings, errors = Counter(), Counter()
    for record in records:
        warnings.update(record["warning_code_counts"])
        errors.update(record["error_code_counts"])
    def safe_codes(counts):
        return {
            code if re.fullmatch(r"[a-z][a-z0-9_]{0,119}", code) else sha256_json(code): count
            for code, count in counts.items()
        }
    return {
        "artifact_id": ARTIFACT_ID, "batch_fingerprint": sha256_json(ledger),
        "status_counts": dict(Counter(record["status"] for record in records)),
        "job_count": len(records), "observation_count": sum(r["observation_count"] for r in records),
        "warning_code_counts": safe_codes(warnings), "error_code_counts": safe_codes(errors),
        "incomplete_run_count": sum(r["incomplete_run_count"] for r in records),
        "source_completeness_certified": False, "rag_activation_performed": False,
    }


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("registered", "pst-sidecar"), required=True)
    parser.add_argument("--store-directory", type=Path, required=True)
    parser.add_argument("--parent-binding-manifest", type=Path, required=True)
    parser.add_argument("--existing-export-root", type=Path)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--batch-id")
    parser.add_argument("--config-json", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_attachment_backfill(
            store_directory=args.store_directory, parent_binding_manifest_path=args.parent_binding_manifest,
            ledger_path=args.ledger, mode=args.mode, existing_export_root=args.existing_export_root,
            config=_read(args.config_json) if args.config_json else None, batch_id=args.batch_id)
    except BackfillError as exc:
        print(json.dumps({"status": "blocked", "reason_code": str(exc)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if not report["status_counts"].get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
