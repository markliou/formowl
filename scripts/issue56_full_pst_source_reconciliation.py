#!/usr/bin/env python3
"""Read-only full-PST oracle to preserved-Observation reconciliation.

The raw inventory is produced with ``lspst`` and persisted before any
Observation manifest is read.  Raw sender, subject, folder labels, dates,
filesystem locations, and parser output are never persisted or returned.
Only fingerprints, statuses, ordinals, and counts cross the report boundary.
This script never invokes ``readpst``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    SourceInventoryItem,
    SourceInventoryProcessingState,
    SourceInventoryRawRetentionState,
    assert_no_public_raw_references,
    sha256_json,
    stable_resource_contract_hash,
    stable_resource_contract_id,
)


ARTIFACT_ID = "formowl_issue56_full_pst_source_reconciliation_v1"
SCHEMA_VERSION = 1
IDENTITY_POLICY_ID = "pst_lspst_observation_subject_multiset_identity_v1"
EXCLUSION_POLICY_ID = "formowl_pst_deleted_items_exclusion_policy_v1"
EXCLUSION_POLICY_VERSION = "1.0.0"
EXCLUSION_REASON = "deleted_item_outside_issue56_target_observation_scope"
DEFAULT_AUTHORIZED_ACTOR_ID = "actor_issue56_source_reconciliation_operator"
EXPECTED_OBSERVATION_TYPES = frozenset(
    {
        "email_attachment_occurrence",
        "email_body_segment",
        "email_header",
        "email_message",
        "email_thread",
        "mail_folder_occurrence",
    }
)
_LSPST_ITEM_LABELS = frozenset({"Appointment", "Contact", "Email", "Folder", "Journal", "Task"})
_POLICY_EXCLUDED_FOLDER_LABELS = (
    "Deleted Items",
    "Deleted Messages",
    "Trash",
)


def _normalize_identity_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _date_day_identity(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return sha256_json(""), "blocked"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return sha256_json(""), "blocked"
    return sha256_json(parsed.date().isoformat()), "passed"


_POLICY_EXCLUDED_FOLDER_FINGERPRINTS = frozenset(
    sha256_json(_normalize_identity_text(label)) for label in _POLICY_EXCLUDED_FOLDER_LABELS
)
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

DEFAULT_PST = ROOT / "tests" / "pst-exm" / "archive.pst"
DEFAULT_PRESERVED_WORK_DIR = ROOT / ".test-tmp" / "exm-archive-domain-hard-work"
DEFAULT_ORACLE_OUTPUT = Path(tempfile.gettempdir()) / "formowl-issue56-full-pst-raw-oracle.json"
DEFAULT_OBSERVATION_OUTPUT = (
    Path(tempfile.gettempdir()) / "formowl-issue56-full-pst-observations.json"
)
DEFAULT_REPORT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-issue56-full-pst-reconciliation.json"


@dataclass(frozen=True)
class ReconciliationArtifacts:
    oracle_manifest: dict[str, Any]
    observation_manifest: dict[str, Any]
    report: dict[str, Any]


def run_full_pst_source_reconciliation(
    *,
    pst_path: Path,
    preserved_work_dir: Path,
    oracle_output: Path,
    observation_output: Path,
    report_output: Path,
    lspst_command: str = "lspst",
    authorized_actor_id: str = DEFAULT_AUTHORIZED_ACTOR_ID,
) -> ReconciliationArtifacts:
    """Build the ordered manifests and one safe reconciliation report."""

    source_asset_sha256 = _sha256_file(pst_path)
    oracle_manifest = _build_lspst_oracle_manifest(
        pst_path=pst_path,
        source_asset_sha256=source_asset_sha256,
        lspst_command=lspst_command,
    )
    persisted_oracle = _persist_round_trip(
        oracle_output,
        oracle_manifest,
        expected_artifact_id="formowl_issue56_full_pst_raw_oracle_manifest_v1",
    )

    # This call is intentionally after the raw oracle round-trip.  Observation
    # state must never define or influence the source-system inventory.
    observation_manifest, private_binding = _build_observation_manifest(
        preserved_work_dir=preserved_work_dir,
        source_asset_sha256=source_asset_sha256,
        oracle_manifest_fingerprint=persisted_oracle["manifest_fingerprint"],
    )
    persisted_observations = _persist_round_trip(
        observation_output,
        observation_manifest,
        expected_artifact_id="formowl_issue56_full_pst_observation_manifest_v1",
    )

    report = _reconcile_manifests(
        oracle_manifest=persisted_oracle,
        observation_manifest=persisted_observations,
        private_binding=private_binding,
        authorized_actor_id=authorized_actor_id,
    )
    persisted_report = _persist_round_trip(
        report_output,
        report,
        expected_artifact_id=ARTIFACT_ID,
        fingerprint_field="report_fingerprint",
    )
    return ReconciliationArtifacts(
        oracle_manifest=persisted_oracle,
        observation_manifest=persisted_observations,
        report=persisted_report,
    )


def _build_lspst_oracle_manifest(
    *,
    pst_path: Path,
    source_asset_sha256: str,
    lspst_command: str,
) -> dict[str, Any]:
    version = subprocess.run(
        [lspst_command, "-V"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    version_fingerprint = sha256_json(
        {
            "returncode": version.returncode,
            "stdout_sha256": _sha256_text(version.stdout),
            "stderr_sha256": _sha256_text(version.stderr),
        }
    )
    profile_fingerprint = stable_resource_contract_hash(
        "Issue56FullPstLspstOracleProfile",
        {
            "identity_policy_id": IDENTITY_POLICY_ID,
            "lspst_version_fingerprint": version_fingerprint,
            "flags": ["-l"],
            "network_required": False,
            "read_only": True,
        },
    )

    process = subprocess.Popen(
        [lspst_command, "-l", str(pst_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise RuntimeError("lspst_oracle_stream_unavailable")

    folders: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    unsupported_counts: Counter[str] = Counter()
    malformed_line_count = 0
    current_folder: dict[str, Any] | None = None
    current_message_ordinal = 0

    for line in process.stdout:
        value = line.rstrip("\n")
        if value.startswith("Folder "):
            match = re.fullmatch(r'Folder "(.*)"', value)
            if match is None:
                malformed_line_count += 1
                current_folder = None
                continue
            folder_ordinal = len(folders) + 1
            folder_identity_fingerprint = sha256_json(_normalize_identity_text(match.group(1)))
            current_folder = {
                "folder_ordinal": folder_ordinal,
                "folder_identity_fingerprint": folder_identity_fingerprint,
                "message_count": 0,
            }
            folders.append(current_folder)
            current_message_ordinal = 0
            continue

        label = value.split("\t", 1)[0].split(" ", 1)[0].rstrip(":")
        if label != "Email":
            if label in _LSPST_ITEM_LABELS:
                unsupported_counts[label.casefold()] += 1
            else:
                malformed_line_count += 1
            continue
        if current_folder is None:
            malformed_line_count += 1
            continue

        fields: dict[str, str] = {}
        for part in value.split("\t")[1:]:
            if ": " not in part:
                continue
            field_name, field_value = part.split(": ", 1)
            fields[field_name] = field_value
        current_message_ordinal += 1
        current_folder["message_count"] += 1
        normalized_subject = _normalize_identity_text(fields.get("Subject", ""))
        normalized_sender = _normalize_sender_display(fields.get("From", ""))
        subject_identity_fingerprint = _message_identity_fingerprint(fields.get("Subject", ""))
        sender_identity_fingerprint = sha256_json(normalized_sender)
        date_identity_fingerprint = sha256_json(_normalize_identity_text(fields.get("Date", "")))
        date_day_identity_fingerprint, date_day_identity_status = _date_day_identity(
            fields.get("Date", "")
        )
        oracle_occurrence_fingerprint = stable_resource_contract_hash(
            "Issue56LspstMessageOccurrence",
            {
                "source_asset_sha256": source_asset_sha256,
                "folder_ordinal": current_folder["folder_ordinal"],
                "message_ordinal": current_message_ordinal,
                "subject_identity_fingerprint": subject_identity_fingerprint,
                "sender_identity_fingerprint": sender_identity_fingerprint,
                "date_identity_fingerprint": date_identity_fingerprint,
            },
        )
        messages.append(
            {
                "folder_ordinal": current_folder["folder_ordinal"],
                "message_ordinal": current_message_ordinal,
                "folder_identity_fingerprint": current_folder["folder_identity_fingerprint"],
                "message_identity_fingerprint": subject_identity_fingerprint,
                "message_identity_status": ("passed" if normalized_subject else "blocked"),
                "sender_identity_fingerprint": sender_identity_fingerprint,
                "sender_identity_status": ("passed" if normalized_sender else "blocked"),
                "date_identity_fingerprint": date_identity_fingerprint,
                "date_day_identity_fingerprint": date_day_identity_fingerprint,
                "date_day_identity_status": date_day_identity_status,
                "oracle_occurrence_fingerprint": oracle_occurrence_fingerprint,
            }
        )

    stderr = process.stderr.read()
    returncode = process.wait()
    process.stdout.close()
    process.stderr.close()
    failure_count = int(returncode != 0) + int(version.returncode != 0)
    manifest: dict[str, Any] = {
        "artifact_id": "formowl_issue56_full_pst_raw_oracle_manifest_v1",
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if failure_count == 0 and malformed_line_count == 0 else "blocked",
        "pipeline_sequence": 1,
        "source_asset_sha256": source_asset_sha256,
        "identity_policy_fingerprint": sha256_json(IDENTITY_POLICY_ID),
        "oracle_profile_fingerprint": profile_fingerprint,
        "tool_version_fingerprint": version_fingerprint,
        "stderr_fingerprint": _sha256_text(stderr),
        "counts": {
            "folder_count": len(folders),
            "message_count": len(messages),
            "attachment_count": 0,
            "attachment_oracle_capability_gap_count": 1,
            "unsupported_structure_count": sum(unsupported_counts.values()),
            "failed_count": failure_count,
            "malformed_line_count": malformed_line_count,
        },
        "unsupported_structure_counts": dict(sorted(unsupported_counts.items())),
        "folders": folders,
        "messages": messages,
    }
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    _validate_oracle_manifest(manifest)
    return manifest


def _build_observation_manifest(
    *,
    preserved_work_dir: Path,
    source_asset_sha256: str,
    oracle_manifest_fingerprint: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ingestion_root = preserved_work_dir / "data" / "ingestion"
    asset_rows = _read_json_files(ingestion_root / "assets")
    matching_assets = [row for row in asset_rows if row.get("content_hash") == source_asset_sha256]
    if len(matching_assets) != 1:
        raise RuntimeError("preserved_asset_binding_unavailable")
    asset = matching_assets[0]
    source_asset_id = _required_string(asset.get("asset_id"), "asset_id")
    permission_scope = asset.get("permission_scope")
    if not isinstance(permission_scope, dict):
        raise RuntimeError("preserved_asset_permission_scope_unavailable")

    extractor_rows = _read_json_files(ingestion_root / "extractor-runs")
    matching_runs = [
        row
        for row in extractor_rows
        if row.get("asset_id") == source_asset_id and row.get("input_hash") == source_asset_sha256
    ]
    if len(matching_runs) != 1:
        raise RuntimeError("preserved_extractor_binding_unavailable")
    extractor_run = matching_runs[0]
    extractor_failed_count = int(extractor_run.get("status") != "succeeded") + len(
        extractor_run.get("errors") or []
    )

    observation_rows = _read_json_files(ingestion_root / "observations")
    type_counts: Counter[str] = Counter()
    foreign_asset_count = 0
    folder_labels: dict[str, str] = {}
    for row in observation_rows:
        observation_type = str(row.get("observation_type", ""))
        type_counts[observation_type] += 1
        foreign_asset_count += int(row.get("asset_id") != source_asset_id)
        if observation_type == "mail_folder_occurrence":
            payload = row.get("payload") or {}
            folder_path_fingerprint = payload.get("folder_path_hash")
            folder_label = payload.get("folder_label")
            if isinstance(folder_path_fingerprint, str) and isinstance(folder_label, str):
                folder_labels[folder_path_fingerprint] = folder_label

    messages: list[dict[str, Any]] = []
    missing_message_occurrence_identity_count = 0
    missing_exported_message_identity_count = 0
    missing_source_inventory_binding_count = 0
    for row in observation_rows:
        if row.get("observation_type") != "email_message":
            continue
        payload = row.get("payload") or {}
        location = row.get("location") or {}
        folder_path_fingerprint = location.get("folder_path_hash")
        folder_label = folder_labels.get(str(folder_path_fingerprint), "")
        message_occurrence_id = location.get("message_occurrence_id")
        source_inventory_item_id = location.get("source_inventory_item_id")
        exported_message_identity = payload.get("message_fingerprint")
        message_occurrence_identity_available = isinstance(message_occurrence_id, str) and bool(
            message_occurrence_id
        )
        exported_message_identity_available = (
            isinstance(exported_message_identity, str)
            and _FINGERPRINT_RE.fullmatch(exported_message_identity) is not None
        )
        source_inventory_binding_available = isinstance(source_inventory_item_id, str) and bool(
            source_inventory_item_id
        )
        missing_message_occurrence_identity_count += int(not message_occurrence_identity_available)
        missing_exported_message_identity_count += int(not exported_message_identity_available)
        missing_source_inventory_binding_count += int(not source_inventory_binding_available)
        date_day_identity_fingerprint, date_day_identity_status = _date_day_identity(
            str(payload.get("sent_at", ""))
        )
        normalized_subject = _normalize_identity_text(str(payload.get("subject", "")))
        normalized_sender = _normalize_sender_display(str(payload.get("sender", "")))
        messages.append(
            {
                "folder_path_fingerprint": _required_fingerprint(
                    folder_path_fingerprint,
                    "folder_path_hash",
                ),
                "folder_identity_fingerprint": sha256_json(_normalize_identity_text(folder_label)),
                "message_index": _required_nonnegative_int(
                    location.get("message_index"),
                    "message_index",
                ),
                "message_identity_fingerprint": _message_identity_fingerprint(
                    str(payload.get("subject", ""))
                ),
                "message_identity_status": ("passed" if normalized_subject else "blocked"),
                "sender_identity_fingerprint": sha256_json(normalized_sender),
                "sender_identity_status": ("passed" if normalized_sender else "blocked"),
                "date_identity_fingerprint": sha256_json(
                    _normalize_identity_text(str(payload.get("sent_at", "")))
                ),
                "date_day_identity_fingerprint": date_day_identity_fingerprint,
                "date_day_identity_status": date_day_identity_status,
                "message_occurrence_fingerprint": sha256_json(str(message_occurrence_id or "")),
                "message_occurrence_identity_status": (
                    "passed" if message_occurrence_identity_available else "blocked"
                ),
                "exported_message_identity_fingerprint": (
                    str(exported_message_identity)
                    if exported_message_identity_available
                    else sha256_json("")
                ),
                "exported_message_identity_status": (
                    "passed" if exported_message_identity_available else "blocked"
                ),
                "source_inventory_item_fingerprint": sha256_json(
                    str(source_inventory_item_id or "")
                ),
                "source_inventory_binding_status": (
                    "passed" if source_inventory_binding_available else "blocked"
                ),
            }
        )

    grouped_messages: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        grouped_messages.setdefault(message["folder_path_fingerprint"], []).append(message)
    folders: list[dict[str, Any]] = []
    ordered_groups = sorted(
        grouped_messages.items(),
        key=lambda item: (
            min(message["message_index"] for message in item[1]),
            item[0],
        ),
    )
    for folder_ordinal, (folder_path_fingerprint, folder_messages) in enumerate(
        ordered_groups,
        start=1,
    ):
        folder_messages.sort(
            key=lambda message: (
                message["message_index"],
                message["message_occurrence_fingerprint"],
            )
        )
        folders.append(
            {
                "folder_ordinal": folder_ordinal,
                "folder_path_fingerprint": folder_path_fingerprint,
                "folder_identity_fingerprint": folder_messages[0]["folder_identity_fingerprint"],
                "message_count": len(folder_messages),
            }
        )
        for message in folder_messages:
            message["folder_ordinal"] = folder_ordinal

    occurrence_fingerprints = [
        message["message_occurrence_fingerprint"]
        for message in messages
        if message["message_occurrence_identity_status"] == "passed"
    ]
    source_inventory_fingerprints = [
        message["source_inventory_item_fingerprint"]
        for message in messages
        if message["source_inventory_binding_status"] == "passed"
    ]
    unsupported_observation_count = sum(
        count
        for observation_type, count in type_counts.items()
        if observation_type not in EXPECTED_OBSERVATION_TYPES
    )
    manifest: dict[str, Any] = {
        "artifact_id": "formowl_issue56_full_pst_observation_manifest_v1",
        "schema_version": SCHEMA_VERSION,
        "status": (
            "passed"
            if foreign_asset_count == 0
            and extractor_failed_count == 0
            and missing_message_occurrence_identity_count == 0
            and missing_exported_message_identity_count == 0
            and missing_source_inventory_binding_count == 0
            else "blocked"
        ),
        "pipeline_sequence": 2,
        "source_asset_sha256": source_asset_sha256,
        "source_asset_id_fingerprint": sha256_json(source_asset_id),
        "oracle_manifest_fingerprint": oracle_manifest_fingerprint,
        "extractor_profile_fingerprint": sha256_json(
            {
                "extractor_name": extractor_run.get("extractor_name"),
                "extractor_version": extractor_run.get("extractor_version"),
                "config_hash": extractor_run.get("config_hash"),
                "input_hash": extractor_run.get("input_hash"),
            }
        ),
        "counts": {
            "observation_count": len(observation_rows),
            "folder_count": type_counts["mail_folder_occurrence"],
            "message_count": type_counts["email_message"],
            "attachment_count": type_counts["email_attachment_occurrence"],
            "body_segment_count": type_counts["email_body_segment"],
            "header_count": type_counts["email_header"],
            "thread_count": type_counts["email_thread"],
            "unsupported_structure_count": unsupported_observation_count,
            "failed_count": extractor_failed_count,
            "foreign_asset_count": foreign_asset_count,
            "missing_message_occurrence_identity_count": (
                missing_message_occurrence_identity_count
            ),
            "missing_exported_message_identity_count": (missing_exported_message_identity_count),
            "missing_source_inventory_binding_count": (missing_source_inventory_binding_count),
            "duplicate_occurrence_binding_count": (
                len(occurrence_fingerprints) - len(set(occurrence_fingerprints))
            ),
            "duplicate_source_inventory_binding_count": (
                len(source_inventory_fingerprints) - len(set(source_inventory_fingerprints))
            ),
        },
        "observation_type_counts": dict(sorted(type_counts.items())),
        "folders": folders,
        "messages": sorted(
            messages,
            key=lambda message: (
                message["folder_ordinal"],
                message["message_index"],
                message["message_occurrence_fingerprint"],
            ),
        ),
    }
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    _validate_observation_manifest(manifest)
    private_binding = {
        "source_asset_id": source_asset_id,
        "permission_scope": permission_scope,
    }
    return manifest, private_binding


def _reconcile_manifests(
    *,
    oracle_manifest: Mapping[str, Any],
    observation_manifest: Mapping[str, Any],
    private_binding: Mapping[str, Any],
    authorized_actor_id: str,
) -> dict[str, Any]:
    _validate_oracle_manifest(oracle_manifest)
    _validate_observation_manifest(observation_manifest)
    if oracle_manifest["source_asset_sha256"] != observation_manifest["source_asset_sha256"]:
        raise RuntimeError("source_asset_sha256_mismatch")
    if (
        observation_manifest["oracle_manifest_fingerprint"]
        != oracle_manifest["manifest_fingerprint"]
    ):
        raise RuntimeError("oracle_observation_sequence_binding_mismatch")

    oracle_folders = list(oracle_manifest["folders"])
    observation_folders = list(observation_manifest["folders"])
    oracle_messages = list(oracle_manifest["messages"])
    observation_messages = list(observation_manifest["messages"])
    folder_mapping = _map_folders_by_identity_overlap(
        oracle_folders=oracle_folders,
        observation_folders=observation_folders,
        oracle_messages=oracle_messages,
        observation_messages=observation_messages,
    )

    oracle_by_folder = _messages_by_folder(oracle_messages)
    observation_by_folder = _messages_by_folder(observation_messages)
    matched_message_count = 0
    raw_only_messages: list[dict[str, Any]] = []
    observation_only_message_count = 0
    matched_occurrence_binding_count = 0
    matched_identity_bindings: list[dict[str, str]] = []
    mapped_observation_ordinals: set[int] = set()
    exclusion_contract_fingerprints: list[str] = []
    intentionally_excluded_message_count = 0
    unknown_raw_message_count = 0

    for oracle_folder in oracle_folders:
        oracle_ordinal = int(oracle_folder["folder_ordinal"])
        observation_ordinal = folder_mapping.get(oracle_ordinal)
        oracle_folder_messages = oracle_by_folder.get(oracle_ordinal, [])
        if observation_ordinal is None:
            observation_queues: dict[str, list[Mapping[str, Any]]] = {}
        else:
            mapped_observation_ordinals.add(observation_ordinal)
            observation_queues = {}
            for message in observation_by_folder.get(observation_ordinal, []):
                observation_queues.setdefault(
                    str(message["message_identity_fingerprint"]),
                    [],
                ).append(message)
            for queue in observation_queues.values():
                queue.sort(
                    key=lambda message: (
                        int(message["message_index"]),
                        str(message["message_occurrence_fingerprint"]),
                    )
                )
        for message in oracle_folder_messages:
            identity = str(message["message_identity_fingerprint"])
            queue = observation_queues.get(identity)
            if queue:
                observation_message = queue.pop(0)
                matched_message_count += 1
                if observation_message["message_occurrence_identity_status"] == "passed":
                    matched_occurrence_binding_count += 1
                matched_identity_bindings.append(
                    {
                        "oracle_occurrence_fingerprint": str(
                            message["oracle_occurrence_fingerprint"]
                        ),
                        "observation_occurrence_fingerprint": str(
                            observation_message["message_occurrence_fingerprint"]
                        ),
                        "exported_message_identity_fingerprint": str(
                            observation_message["exported_message_identity_fingerprint"]
                        ),
                        "source_inventory_item_fingerprint": str(
                            observation_message["source_inventory_item_fingerprint"]
                        ),
                    }
                )
                continue
            raw_only_messages.append(message)
            if oracle_folder["folder_identity_fingerprint"] in _POLICY_EXCLUDED_FOLDER_FINGERPRINTS:
                exclusion_item = _intentionally_excluded_item(
                    source_asset_id=str(private_binding["source_asset_id"]),
                    permission_scope=private_binding["permission_scope"],
                    source_asset_sha256=str(oracle_manifest["source_asset_sha256"]),
                    parser_fingerprint=str(oracle_manifest["oracle_profile_fingerprint"]),
                    authorized_actor_id=authorized_actor_id,
                    oracle_occurrence_fingerprint=str(message["oracle_occurrence_fingerprint"]),
                    folder_identity_fingerprint=str(message["folder_identity_fingerprint"]),
                    message_identity_fingerprint=str(message["message_identity_fingerprint"]),
                    ordinal=int(message["message_ordinal"]),
                    structure_kind="pst_message_occurrence",
                )
                exclusion_contract_fingerprints.append(sha256_json(exclusion_item.to_dict()))
                intentionally_excluded_message_count += 1
            else:
                unknown_raw_message_count += 1

        if observation_ordinal is not None:
            observation_only_message_count += sum(
                len(queue) for queue in observation_queues.values()
            )

    for observation_folder in observation_folders:
        observation_ordinal = int(observation_folder["folder_ordinal"])
        if observation_ordinal not in mapped_observation_ordinals:
            observation_only_message_count += len(
                observation_by_folder.get(observation_ordinal, [])
            )

    intentionally_excluded_folder_count = 0
    unknown_raw_folder_count = 0
    mapped_oracle_ordinals = set(folder_mapping)
    for folder in oracle_folders:
        ordinal = int(folder["folder_ordinal"])
        if ordinal in mapped_oracle_ordinals:
            continue
        if folder["folder_identity_fingerprint"] in _POLICY_EXCLUDED_FOLDER_FINGERPRINTS:
            exclusion_item = _intentionally_excluded_item(
                source_asset_id=str(private_binding["source_asset_id"]),
                permission_scope=private_binding["permission_scope"],
                source_asset_sha256=str(oracle_manifest["source_asset_sha256"]),
                parser_fingerprint=str(oracle_manifest["oracle_profile_fingerprint"]),
                authorized_actor_id=authorized_actor_id,
                oracle_occurrence_fingerprint=sha256_json(
                    {
                        "folder_identity_fingerprint": folder["folder_identity_fingerprint"],
                        "folder_ordinal": ordinal,
                    }
                ),
                folder_identity_fingerprint=str(folder["folder_identity_fingerprint"]),
                message_identity_fingerprint=sha256_json("folder_occurrence"),
                ordinal=ordinal,
                structure_kind="pst_folder_occurrence",
            )
            exclusion_contract_fingerprints.append(sha256_json(exclusion_item.to_dict()))
            intentionally_excluded_folder_count += 1
        else:
            unknown_raw_folder_count += 1

    raw_message_count = int(oracle_manifest["counts"]["message_count"])
    observed_message_count = int(observation_manifest["counts"]["message_count"])
    raw_folder_count = int(oracle_manifest["counts"]["folder_count"])
    observed_folder_count = int(observation_manifest["counts"]["folder_count"])
    observed_attachment_count = int(observation_manifest["counts"]["attachment_count"])
    unsupported_structure_count = int(
        oracle_manifest["counts"]["unsupported_structure_count"]
    ) + int(observation_manifest["counts"]["unsupported_structure_count"])
    failed_count = int(oracle_manifest["counts"]["failed_count"]) + int(
        observation_manifest["counts"]["failed_count"]
    )
    attachment_oracle_capability_gap_count = int(
        observed_attachment_count > 0
        and oracle_manifest["counts"]["attachment_oracle_capability_gap_count"] > 0
    )
    missing_message_occurrence_identity_count = int(
        observation_manifest["counts"]["missing_message_occurrence_identity_count"]
    )
    missing_exported_message_identity_count = int(
        observation_manifest["counts"]["missing_exported_message_identity_count"]
    )
    missing_source_inventory_binding_count = int(
        observation_manifest["counts"]["missing_source_inventory_binding_count"]
    )
    duplicate_occurrence_binding_count = int(
        observation_manifest["counts"]["duplicate_occurrence_binding_count"]
    )
    duplicate_source_inventory_binding_count = int(
        observation_manifest["counts"]["duplicate_source_inventory_binding_count"]
    )
    occurrence_lineage_loss_count = (
        missing_message_occurrence_identity_count
        + missing_exported_message_identity_count
        + missing_source_inventory_binding_count
        + duplicate_occurrence_binding_count
        + duplicate_source_inventory_binding_count
    )
    unexplained_loss_count = (
        unknown_raw_message_count
        + unknown_raw_folder_count
        + unsupported_structure_count
        + failed_count
    )
    unexplained_identity_count = (
        unknown_raw_message_count + observation_only_message_count + unknown_raw_folder_count
    )
    blocker_codes: list[str] = []
    if oracle_manifest["status"] != "passed":
        blocker_codes.append("raw_oracle_manifest_blocked")
    if observation_manifest["status"] != "passed":
        blocker_codes.append("observation_manifest_blocked")
    if unknown_raw_message_count:
        blocker_codes.append("unexplained_raw_message_identity")
    if observation_only_message_count:
        blocker_codes.append("observation_identity_not_found_in_raw_oracle")
    if unknown_raw_folder_count:
        blocker_codes.append("unexplained_raw_folder_identity")
    if unsupported_structure_count:
        blocker_codes.append("unsupported_source_structure")
    if failed_count:
        blocker_codes.append("source_or_observation_failure")
    if attachment_oracle_capability_gap_count:
        blocker_codes.append("lspst_attachment_oracle_capability_gap")
    if missing_message_occurrence_identity_count:
        blocker_codes.append("missing_observation_occurrence_identity")
    if missing_exported_message_identity_count:
        blocker_codes.append("missing_exported_message_identity")
    if missing_source_inventory_binding_count:
        blocker_codes.append("missing_source_inventory_binding")
    if duplicate_occurrence_binding_count:
        blocker_codes.append("duplicate_observation_occurrence_binding")
    if duplicate_source_inventory_binding_count:
        blocker_codes.append("duplicate_source_inventory_binding")

    status = "passed" if not blocker_codes else "blocked"
    report: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source_completeness_gate_status": ("eligible" if status == "passed" else "blocked"),
        "source_asset_sha256": oracle_manifest["source_asset_sha256"],
        "oracle_manifest_fingerprint": oracle_manifest["manifest_fingerprint"],
        "observation_manifest_fingerprint": observation_manifest["manifest_fingerprint"],
        "identity_policy_fingerprint": oracle_manifest["identity_policy_fingerprint"],
        "folder_mapping_fingerprint": sha256_json(
            [
                {
                    "oracle_folder_ordinal": oracle_ordinal,
                    "observation_folder_ordinal": observation_ordinal,
                }
                for oracle_ordinal, observation_ordinal in sorted(folder_mapping.items())
            ]
        ),
        "matched_identity_binding_rollup_fingerprint": sha256_json(
            sorted(
                matched_identity_bindings,
                key=lambda binding: (
                    binding["oracle_occurrence_fingerprint"],
                    binding["observation_occurrence_fingerprint"],
                ),
            )
        ),
        "exclusion_policy_id_fingerprint": sha256_json(EXCLUSION_POLICY_ID),
        "exclusion_policy_version_fingerprint": sha256_json(EXCLUSION_POLICY_VERSION),
        "exclusion_authorized_actor_fingerprint": sha256_json(authorized_actor_id),
        "exclusion_reason_fingerprint": sha256_json(EXCLUSION_REASON),
        "exclusion_contract_rollup_fingerprint": sha256_json(
            sorted(exclusion_contract_fingerprints)
        ),
        "blocker_fingerprints": sorted(sha256_json(code) for code in blocker_codes),
        "round_trip_status": {
            "raw_oracle_manifest": "passed",
            "observation_manifest": "passed",
            "reconciliation_report": "passed",
        },
        "counts": {
            "raw_message_count": raw_message_count,
            "observed_message_count": observed_message_count,
            "matched_message_identity_count": matched_message_count,
            "net_message_occurrence_loss_count": max(
                raw_message_count - observed_message_count,
                0,
            ),
            "raw_only_message_identity_count": len(raw_only_messages),
            "observation_only_message_identity_count": (observation_only_message_count),
            "matched_observation_occurrence_identity_count": (matched_occurrence_binding_count),
            "preserved_exported_message_identity_count": (
                observed_message_count - missing_exported_message_identity_count
            ),
            "intentionally_excluded_message_count": (intentionally_excluded_message_count),
            "unknown_raw_message_count": unknown_raw_message_count,
            "unknown_observation_message_count": (observation_only_message_count),
            "raw_folder_count": raw_folder_count,
            "observed_folder_count": observed_folder_count,
            "matched_folder_count": len(folder_mapping),
            "net_folder_occurrence_loss_count": max(
                raw_folder_count - observed_folder_count,
                0,
            ),
            "intentionally_excluded_folder_count": (intentionally_excluded_folder_count),
            "unknown_raw_folder_count": unknown_raw_folder_count,
            "raw_attachment_count": 0,
            "observed_attachment_count": observed_attachment_count,
            "attachment_occurrence_loss_count": 0,
            "attachment_oracle_capability_gap_count": (attachment_oracle_capability_gap_count),
            "unsupported_structure_count": unsupported_structure_count,
            "failed_count": failed_count,
            "missing_message_occurrence_identity_count": (
                missing_message_occurrence_identity_count
            ),
            "missing_exported_message_identity_count": (missing_exported_message_identity_count),
            "missing_source_inventory_binding_count": (missing_source_inventory_binding_count),
            "duplicate_occurrence_binding_count": (duplicate_occurrence_binding_count),
            "duplicate_source_inventory_binding_count": (duplicate_source_inventory_binding_count),
            "occurrence_lineage_loss_count": occurrence_lineage_loss_count,
            "policy_excluded_count": (
                intentionally_excluded_message_count + intentionally_excluded_folder_count
            ),
            "unexplained_loss_count": unexplained_loss_count,
            "unexplained_identity_count": unexplained_identity_count,
            "blocker_count": len(blocker_codes),
        },
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    _validate_public_report(report)
    return report


def _map_folders_by_identity_overlap(
    *,
    oracle_folders: Sequence[Mapping[str, Any]],
    observation_folders: Sequence[Mapping[str, Any]],
    oracle_messages: Sequence[Mapping[str, Any]],
    observation_messages: Sequence[Mapping[str, Any]],
) -> dict[int, int]:
    oracle_by_folder = _messages_by_folder(oracle_messages)
    observation_by_folder = _messages_by_folder(observation_messages)
    oracle_ordinals = [int(folder["folder_ordinal"]) for folder in oracle_folders]
    observation_ordinals = [int(folder["folder_ordinal"]) for folder in observation_folders]
    if not oracle_ordinals or not observation_ordinals:
        return {}
    if len(oracle_ordinals) > 8 or len(observation_ordinals) > 8:
        raise RuntimeError("folder_identity_assignment_is_not_bounded")

    pair_count = min(len(oracle_ordinals), len(observation_ordinals))
    best_score: tuple[int, int, tuple[int, ...]] | None = None
    best_mapping: dict[int, int] = {}
    for selected_oracle in itertools.combinations(oracle_ordinals, pair_count):
        for selected_observations in itertools.permutations(
            observation_ordinals,
            pair_count,
        ):
            mapping = dict(zip(selected_oracle, selected_observations, strict=True))
            overlap = 0
            count_delta = 0
            for oracle_ordinal, observation_ordinal in mapping.items():
                oracle_counter = Counter(
                    message["message_identity_fingerprint"]
                    for message in oracle_by_folder.get(oracle_ordinal, [])
                )
                observation_counter = Counter(
                    message["message_identity_fingerprint"]
                    for message in observation_by_folder.get(
                        observation_ordinal,
                        [],
                    )
                )
                overlap += sum((oracle_counter & observation_counter).values())
                count_delta += abs(sum(oracle_counter.values()) - sum(observation_counter.values()))
            tie_breaker = tuple(mapping[ordinal] for ordinal in sorted(mapping))
            score = (overlap, -count_delta, tuple(-item for item in tie_breaker))
            if best_score is None or score > best_score:
                best_score = score
                best_mapping = mapping
    return best_mapping


def _intentionally_excluded_item(
    *,
    source_asset_id: str,
    permission_scope: Mapping[str, Any],
    source_asset_sha256: str,
    parser_fingerprint: str,
    authorized_actor_id: str,
    oracle_occurrence_fingerprint: str,
    folder_identity_fingerprint: str,
    message_identity_fingerprint: str,
    ordinal: int,
    structure_kind: str,
) -> SourceInventoryItem:
    proof_fingerprint = sha256_json(
        {
            "artifact_id": "formowl_issue56_pst_exclusion_proof_v1",
            "policy_id": EXCLUSION_POLICY_ID,
            "policy_version": EXCLUSION_POLICY_VERSION,
            "source_asset_sha256": source_asset_sha256,
            "oracle_occurrence_fingerprint": oracle_occurrence_fingerprint,
            "folder_identity_fingerprint": folder_identity_fingerprint,
            "message_identity_fingerprint": message_identity_fingerprint,
            "readpst_include_deleted_items": False,
        }
    )
    source_local_key = stable_resource_contract_id(
        "pstoracle",
        "Issue56PstOracleOccurrence",
        {
            "source_asset_sha256": source_asset_sha256,
            "oracle_occurrence_fingerprint": oracle_occurrence_fingerprint,
        },
    )
    return SourceInventoryItem.create(
        source_asset_id=source_asset_id,
        structure_kind=structure_kind,
        content_type=(
            "message/rfc822"
            if structure_kind == "pst_message_occurrence"
            else "application/vnd.ms-outlook-folder"
        ),
        ordinal=ordinal,
        processing_state=SourceInventoryProcessingState.INTENTIONALLY_EXCLUDED,
        raw_retention_state=SourceInventoryRawRetentionState.EXTERNALLY_MANAGED,
        source_fingerprint=source_asset_sha256,
        parser_fingerprint=parser_fingerprint,
        permission_scope=permission_scope,
        location={
            "source_local_key": source_local_key,
            "folder_identity_fingerprint": folder_identity_fingerprint,
            "message_identity_fingerprint": message_identity_fingerprint,
            "oracle_occurrence_fingerprint": oracle_occurrence_fingerprint,
        },
        exclusion_policy_id=EXCLUSION_POLICY_ID,
        exclusion_policy_version=EXCLUSION_POLICY_VERSION,
        exclusion_authorized_actor_id=authorized_actor_id,
        exclusion_reason=EXCLUSION_REASON,
        exclusion_out_of_scope_proof_fingerprint=proof_fingerprint,
    )


def _messages_by_folder(
    messages: Sequence[Mapping[str, Any]],
) -> dict[int, list[Mapping[str, Any]]]:
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for message in messages:
        grouped.setdefault(int(message["folder_ordinal"]), []).append(message)
    return grouped


def _message_identity_fingerprint(subject: str) -> str:
    return stable_resource_contract_hash(
        "Issue56PstMessageCoarseIdentity",
        {
            "identity_policy_id": IDENTITY_POLICY_ID,
            "normalized_subject": _normalize_identity_text(subject),
        },
    )


def _normalize_sender_display(value: str) -> str:
    without_address = re.sub(r"\s*<[^>]*>\s*$", "", value).strip().strip('"')
    return _normalize_identity_text(without_address)


def _read_json_files(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise RuntimeError("preserved_manifest_directory_unavailable")
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("preserved_manifest_entry_invalid")
        rows.append(value)
    return rows


def _persist_round_trip(
    path: Path,
    payload: Mapping[str, Any],
    *,
    expected_artifact_id: str,
    fingerprint_field: str = "manifest_fingerprint",
) -> dict[str, Any]:
    canonical = json.loads(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    )
    if canonical.get("artifact_id") != expected_artifact_id:
        raise RuntimeError("artifact_id_mismatch")
    expected_fingerprint = _payload_fingerprint(canonical, fingerprint_field)
    if canonical.get(fingerprint_field) != expected_fingerprint:
        raise RuntimeError("artifact_fingerprint_mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(canonical, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if loaded != canonical:
        raise RuntimeError("artifact_round_trip_mismatch")
    assert_no_public_raw_references(loaded, expected_artifact_id)
    return loaded


def _payload_fingerprint(payload: Mapping[str, Any], field_name: str) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != field_name})


def _validate_oracle_manifest(value: Mapping[str, Any]) -> None:
    if value.get("artifact_id") != "formowl_issue56_full_pst_raw_oracle_manifest_v1":
        raise RuntimeError("raw_oracle_artifact_invalid")
    if value.get("pipeline_sequence") != 1:
        raise RuntimeError("raw_oracle_sequence_invalid")
    _required_fingerprint(value.get("source_asset_sha256"), "source_asset_sha256")
    if value.get("manifest_fingerprint") != _payload_fingerprint(
        value,
        "manifest_fingerprint",
    ):
        raise RuntimeError("raw_oracle_fingerprint_invalid")
    counts = value.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("raw_oracle_counts_invalid")
    if counts.get("message_count") != len(value.get("messages") or []):
        raise RuntimeError("raw_oracle_message_count_invalid")
    if counts.get("folder_count") != len(value.get("folders") or []):
        raise RuntimeError("raw_oracle_folder_count_invalid")
    assert_no_public_raw_references(value, "issue56_full_pst_raw_oracle")


def _validate_observation_manifest(value: Mapping[str, Any]) -> None:
    if value.get("artifact_id") != "formowl_issue56_full_pst_observation_manifest_v1":
        raise RuntimeError("observation_manifest_artifact_invalid")
    if value.get("pipeline_sequence") != 2:
        raise RuntimeError("observation_manifest_sequence_invalid")
    _required_fingerprint(value.get("source_asset_sha256"), "source_asset_sha256")
    if value.get("manifest_fingerprint") != _payload_fingerprint(
        value,
        "manifest_fingerprint",
    ):
        raise RuntimeError("observation_manifest_fingerprint_invalid")
    counts = value.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("observation_manifest_counts_invalid")
    if counts.get("message_count") != len(value.get("messages") or []):
        raise RuntimeError("observation_manifest_message_count_invalid")
    assert_no_public_raw_references(value, "issue56_full_pst_observation_manifest")


def _validate_public_report(value: Mapping[str, Any]) -> None:
    if value.get("artifact_id") != ARTIFACT_ID:
        raise RuntimeError("reconciliation_artifact_invalid")
    if value.get("report_fingerprint") != _payload_fingerprint(
        value,
        "report_fingerprint",
    ):
        raise RuntimeError("reconciliation_fingerprint_invalid")
    counts = value.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(count, int) or isinstance(count, bool) for count in counts.values()
    ):
        raise RuntimeError("reconciliation_counts_invalid")
    for fingerprint in value.get("blocker_fingerprints") or []:
        _required_fingerprint(fingerprint, "blocker_fingerprint")
    forbidden_key_parts = {
        "bcc",
        "cc",
        "date",
        "filename",
        "folder_label",
        "from",
        "object",
        "path",
        "sender",
        "subject",
        "to",
        "uri",
    }
    for key in _walk_keys(value):
        normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
        parts = set(normalized.split("_"))
        if parts & forbidden_key_parts and not normalized.endswith("fingerprint"):
            raise RuntimeError("reconciliation_public_field_is_not_hash_status_or_count")
    assert_no_public_raw_references(value, "issue56_full_pst_source_reconciliation")


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(field_name + "_invalid")
    return value


def _required_fingerprint(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_RE.fullmatch(value):
        raise RuntimeError(field_name + "_invalid")
    return value


def _required_nonnegative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(field_name + "_invalid")
    return value


def _safe_blocked_report(error: Exception) -> dict[str, Any]:
    report: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "source_completeness_gate_status": "blocked",
        "blocker_fingerprints": [sha256_json(type(error).__name__ + ":" + str(error))],
        "round_trip_status": {
            "raw_oracle_manifest": "blocked",
            "observation_manifest": "blocked",
            "reconciliation_report": "passed",
        },
        "counts": {
            "raw_message_count": 0,
            "observed_message_count": 0,
            "matched_message_identity_count": 0,
            "net_message_occurrence_loss_count": 0,
            "raw_only_message_identity_count": 0,
            "observation_only_message_identity_count": 0,
            "matched_observation_occurrence_identity_count": 0,
            "preserved_exported_message_identity_count": 0,
            "intentionally_excluded_message_count": 0,
            "unknown_raw_message_count": 0,
            "unknown_observation_message_count": 0,
            "raw_folder_count": 0,
            "observed_folder_count": 0,
            "matched_folder_count": 0,
            "net_folder_occurrence_loss_count": 0,
            "intentionally_excluded_folder_count": 0,
            "unknown_raw_folder_count": 0,
            "raw_attachment_count": 0,
            "observed_attachment_count": 0,
            "attachment_occurrence_loss_count": 0,
            "attachment_oracle_capability_gap_count": 0,
            "unsupported_structure_count": 0,
            "failed_count": 1,
            "missing_message_occurrence_identity_count": 0,
            "missing_exported_message_identity_count": 0,
            "missing_source_inventory_binding_count": 0,
            "duplicate_occurrence_binding_count": 0,
            "duplicate_source_inventory_binding_count": 0,
            "occurrence_lineage_loss_count": 0,
            "policy_excluded_count": 0,
            "unexplained_loss_count": 1,
            "unexplained_identity_count": 0,
            "blocker_count": 1,
        },
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    _validate_public_report(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pst", type=Path, default=DEFAULT_PST)
    parser.add_argument(
        "--preserved-work-dir",
        type=Path,
        default=DEFAULT_PRESERVED_WORK_DIR,
    )
    parser.add_argument("--oracle-output", type=Path, default=DEFAULT_ORACLE_OUTPUT)
    parser.add_argument(
        "--observation-output",
        type=Path,
        default=DEFAULT_OBSERVATION_OUTPUT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_OUTPUT)
    parser.add_argument("--lspst-command", default="lspst")
    parser.add_argument(
        "--authorized-actor-id",
        default=DEFAULT_AUTHORIZED_ACTOR_ID,
    )
    args = parser.parse_args()
    try:
        artifacts = run_full_pst_source_reconciliation(
            pst_path=args.pst,
            preserved_work_dir=args.preserved_work_dir,
            oracle_output=args.oracle_output,
            observation_output=args.observation_output,
            report_output=args.output,
            lspst_command=args.lspst_command,
            authorized_actor_id=args.authorized_actor_id,
        )
        report = artifacts.report
    except Exception as exc:
        report = _safe_blocked_report(exc)
        report = _persist_round_trip(
            args.output,
            report,
            expected_artifact_id=ARTIFACT_ID,
            fingerprint_field="report_fingerprint",
        )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
