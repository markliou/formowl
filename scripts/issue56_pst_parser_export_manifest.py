#!/usr/bin/env python3
"""Create one immutable Issue #56 readpst export and private manifest.

The parser export is intentionally private.  The only stdout payload is a
hash/count/status report.  Message text, headers, attachment names, export
names, filesystem paths, and parser output never cross that boundary.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    assert_no_public_raw_references,
    sha256_json,
    stable_resource_contract_hash,
    stable_resource_contract_id,
)
from formowl_ingestion.extractors.mail import pst as pst_extractor  # noqa: E402


PRIVATE_ARTIFACT_ID = "formowl_issue56_pst_parser_export_private_manifest_v1"
PUBLIC_ARTIFACT_ID = "formowl_issue56_pst_parser_export_public_report_v1"
SCHEMA_VERSION = 1
EXPECTED_ASSET_SHA256 = "sha256:82dddb25fffd14cd0c5576a0791bc408aab0d15d5eb76be1727e14cff658caaf"
PARSER_FLAGS = ("-S", "-t", "ea")
RAW_ORACLE_IDENTITY_POLICY_ID = "pst_lspst_observation_subject_multiset_identity_v1"
PARSER_CONFIG = {
    "max_messages": None,
    "timeout_seconds": 7200,
    "max_message_file_bytes": 25 * 1024 * 1024,
    "body_segment_max_chars": 4000,
    "max_body_segments_per_message": 3,
    "max_attachment_hash_bytes": 5 * 1024 * 1024,
    "include_deleted_items": False,
    "parser_workers": 1,
}
DEFAULT_PST = ROOT / "tests" / "pst-exm" / "archive.pst"
DEFAULT_OUTPUT_ROOT = ROOT / ".test-tmp" / "issue56-pst-parser-export-v1"
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class ParserExportArtifacts:
    private_manifest: dict[str, Any]
    public_report: dict[str, Any]


def run_parser_export_once(
    *,
    pst_path: Path,
    output_root: Path,
    parser_command: str = "readpst",
    expected_asset_sha256: str = EXPECTED_ASSET_SHA256,
    progress_interval_seconds: float = 30.0,
) -> ParserExportArtifacts:
    """Run the pinned parser once into a newly allocated private directory."""

    source_asset_sha256 = _sha256_file(pst_path)
    if source_asset_sha256 != expected_asset_sha256:
        raise RuntimeError("parser_export_source_asset_sha256_mismatch")
    try:
        output_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise RuntimeError("parser_export_output_root_not_new") from exc
    export_root = output_root / "export"
    export_root.mkdir(mode=0o700)
    stdout_path = output_root / "parser-stdout.private"
    stderr_path = output_root / "parser-stderr.private"

    version = subprocess.run(
        [parser_command, "-V"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    version_text = "\n".join((version.stdout, version.stderr)).strip()
    parser_version = _parser_version(version_text)
    command = [
        parser_command,
        *PARSER_FLAGS,
        "-o",
        str(export_root),
        str(pst_path),
    ]
    started = time.monotonic()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            command,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
        next_progress = started + max(progress_interval_seconds, 1.0)
        while process.poll() is None:
            now = time.monotonic()
            if now >= next_progress:
                file_count, byte_count = _tree_metrics(export_root)
                print(
                    json.dumps(
                        {
                            "artifact_id": "formowl_issue56_parser_export_progress_v1",
                            "elapsed_seconds": int(now - started),
                            "export_file_count": file_count,
                            "export_byte_count": byte_count,
                            "status": "running",
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                next_progress = now + max(progress_interval_seconds, 1.0)
            time.sleep(min(max(progress_interval_seconds / 10.0, 0.25), 2.0))
        returncode = int(process.returncode or 0)
    elapsed_seconds = time.monotonic() - started
    stdout_sha256 = _sha256_file(stdout_path)
    stderr_sha256 = _sha256_file(stderr_path)
    if returncode != 0 or version.returncode != 0:
        failure = {
            "artifact_id": PUBLIC_ARTIFACT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "source_asset_sha256": source_asset_sha256,
            "parser_version_fingerprint": sha256_json(parser_version),
            "parser_config_fingerprint": sha256_json(
                {"flags": list(PARSER_FLAGS), **PARSER_CONFIG}
            ),
            "stdout_fingerprint": stdout_sha256,
            "stderr_fingerprint": stderr_sha256,
            "counts": {
                "parser_failure_count": int(returncode != 0) + int(version.returncode != 0),
                "elapsed_seconds": int(elapsed_seconds),
            },
        }
        failure["report_fingerprint"] = _payload_fingerprint(
            failure,
            "report_fingerprint",
        )
        _persist_immutable(
            output_root / "public-report.json",
            failure,
            fingerprint_field="report_fingerprint",
        )
        raise RuntimeError("parser_export_process_failed")

    artifacts = build_manifest_from_existing_export(
        pst_path=pst_path,
        output_root=output_root,
        parser_version=parser_version,
        stdout_fingerprint=stdout_sha256,
        stderr_fingerprint=stderr_sha256,
        elapsed_seconds=elapsed_seconds,
        expected_asset_sha256=expected_asset_sha256,
    )
    _make_tree_read_only(export_root)
    return artifacts


def build_manifest_from_existing_export(
    *,
    pst_path: Path,
    output_root: Path,
    parser_version: str,
    stdout_fingerprint: str,
    stderr_fingerprint: str,
    elapsed_seconds: float,
    expected_asset_sha256: str = EXPECTED_ASSET_SHA256,
    private_manifest_output: Path | None = None,
    public_report_output: Path | None = None,
) -> ParserExportArtifacts:
    """Finalize a successful existing export without invoking readpst again."""

    source_asset_sha256 = _sha256_file(pst_path)
    if source_asset_sha256 != expected_asset_sha256:
        raise RuntimeError("parser_export_source_asset_sha256_mismatch")
    export_root = output_root / "export"
    if not export_root.is_dir():
        raise RuntimeError("parser_export_directory_unavailable")
    private_manifest = _build_private_manifest(
        export_root=export_root,
        source_asset_sha256=source_asset_sha256,
        parser_version=parser_version,
        stdout_fingerprint=stdout_fingerprint,
        stderr_fingerprint=stderr_fingerprint,
    )
    persisted_private = _persist_immutable(
        private_manifest_output or output_root / "private-parser-manifest.json",
        private_manifest,
        fingerprint_field="manifest_fingerprint",
    )
    public_report = _build_public_report(
        private_manifest=persisted_private,
        elapsed_seconds=elapsed_seconds,
    )
    persisted_public = _persist_immutable(
        public_report_output or output_root / "public-report.json",
        public_report,
        fingerprint_field="report_fingerprint",
    )
    return ParserExportArtifacts(
        private_manifest=persisted_private,
        public_report=persisted_public,
    )


def _build_private_manifest(
    *,
    export_root: Path,
    source_asset_sha256: str,
    parser_version: str,
    stdout_fingerprint: str,
    stderr_fingerprint: str,
) -> dict[str, Any]:
    config = pst_extractor._parser_config(PARSER_CONFIG)
    candidates = list(pst_extractor._iter_exported_files(export_root))
    candidate_records: dict[Path, dict[str, Any]] = {}
    groups: dict[tuple[Path, int], list[tuple[Path, str]]] = {}
    naming_contract_failure_count = 0
    for file_ordinal, candidate in enumerate(candidates, start=1):
        relative_fingerprint = _relative_file_fingerprint(
            candidate,
            export_root,
        )
        candidate_records[candidate] = {
            "content_hash": _sha256_file(candidate),
            "byte_count": candidate.stat().st_size,
            "export_file_ordinal": file_ordinal,
            "relative_export_fingerprint": relative_fingerprint,
        }
        match = re.fullmatch(r"([1-9][0-9]*)(.*)", candidate.name)
        if match is None:
            naming_contract_failure_count += 1
            continue
        source_local_ordinal = int(match.group(1))
        tail = match.group(2)
        if tail and not tail.startswith("-"):
            naming_contract_failure_count += 1
            continue
        groups.setdefault(
            (candidate.parent, source_local_ordinal),
            [],
        ).append((candidate, tail))

    messages: list[dict[str, Any]] = []
    separate_files: list[dict[str, Any]] = []
    parse_warning_fingerprints: list[str] = []
    unsupported_main_records: list[dict[str, Any]] = []
    message_index = 0
    ordered_groups = sorted(
        groups.items(),
        key=lambda item: min(
            candidate_records[path]["export_file_ordinal"] for path, _tail in item[1]
        ),
    )
    for (parent, source_local_ordinal), group_items in ordered_groups:
        parent_occurrence_fingerprint = sha256_json(
            str(parent.relative_to(export_root)).replace("\\", "/")
        )
        source_local_stem_fingerprint = sha256_json(
            {
                "parent_occurrence_fingerprint": parent_occurrence_fingerprint,
                "source_local_ordinal": source_local_ordinal,
            }
        )
        main_files = [path for path, tail in group_items if not tail]
        sidecars = sorted(
            ((path, tail) for path, tail in group_items if tail),
            key=lambda item: candidate_records[item[0]]["export_file_ordinal"],
        )
        if len(main_files) != 1:
            unsupported_main_records.append(
                _unsupported_main_record(
                    group_items=group_items,
                    candidate_records=candidate_records,
                    source_asset_sha256=source_asset_sha256,
                    source_local_stem_fingerprint=source_local_stem_fingerprint,
                    source_local_ordinal=source_local_ordinal,
                    folder_occurrence_hash=parent_occurrence_fingerprint,
                    reason_code="readpst_separate_main_cardinality_invalid",
                )
            )
            continue
        candidate = main_files[0]
        file_record = candidate_records[candidate]
        parsed_message, warnings = pst_extractor._parse_exported_message_file(
            candidate,
            export_root=export_root,
            message_index=message_index + 1,
            config=config,
        )
        parse_warning_fingerprints.extend(sha256_json(warning) for warning in warnings)
        if parsed_message is None:
            unsupported_main_records.append(
                _unsupported_main_record(
                    group_items=group_items,
                    candidate_records=candidate_records,
                    source_asset_sha256=source_asset_sha256,
                    source_local_stem_fingerprint=source_local_stem_fingerprint,
                    source_local_ordinal=source_local_ordinal,
                    folder_occurrence_hash=parent_occurrence_fingerprint,
                    reason_code="readpst_separate_main_not_rfc822_email",
                )
            )
            continue

        message_index += 1
        embedded_attachments = []
        for attachment_ordinal, attachment in enumerate(
            parsed_message.attachments,
            start=1,
        ):
            attachment_source_local_key = stable_resource_contract_id(
                "pstattsrc",
                "PstAttachmentSourceOccurrence",
                {
                    "parent_source_local_key": parsed_message.source_local_key,
                    "attachment_id": attachment.attachment_id,
                    "attachment_ordinal": attachment_ordinal,
                    "attachment_name_fingerprint": attachment.source_name_fingerprint,
                },
            )
            embedded_attachments.append(
                {
                    "source_local_key": attachment_source_local_key,
                    "parent_source_local_key": parsed_message.source_local_key,
                    "attachment_id_fingerprint": sha256_json(attachment.attachment_id),
                    "attachment_name_fingerprint": attachment.source_name_fingerprint,
                    "attachment_content_hash": attachment.content_hash,
                    "attachment_ordinal": attachment_ordinal,
                    "folder_occurrence_hash": parsed_message.folder_path_hash,
                    "export_ordinal": file_record["export_file_ordinal"],
                    "byte_count": attachment.size_bytes,
                    "content_type": attachment.mime_type or "application/octet-stream",
                    "representation_kind": "embedded_mime_attachment",
                    "content_type_fingerprint": sha256_json(
                        attachment.mime_type or "application/octet-stream"
                    ),
                }
            )

        separate_attachments: list[dict[str, Any]] = []
        body_sidecars: list[dict[str, Any]] = []
        for sidecar_ordinal, (sidecar_path, tail) in enumerate(
            sidecars,
            start=1,
        ):
            sidecar_record = candidate_records[sidecar_path]
            is_rtf_body = tail.casefold().startswith("-rtf-body.rtf")
            sidecar_role = "rtf_body_representation" if is_rtf_body else "separate_attachment"
            source_local_key = stable_resource_contract_id(
                "pstsidecarsrc",
                "Issue56ReadpstSeparateSidecarOccurrence",
                {
                    "parent_source_local_key": parsed_message.source_local_key,
                    "source_local_stem_fingerprint": (source_local_stem_fingerprint),
                    "source_local_ordinal": source_local_ordinal,
                    "sidecar_ordinal": sidecar_ordinal,
                    "sidecar_name_fingerprint": sha256_json(tail),
                    "sidecar_content_hash": sidecar_record["content_hash"],
                    "sidecar_role": sidecar_role,
                },
            )
            sidecar = {
                "source_local_key": source_local_key,
                "parent_source_local_key": parsed_message.source_local_key,
                "source_local_stem_fingerprint": (source_local_stem_fingerprint),
                "source_local_ordinal": source_local_ordinal,
                "sidecar_ordinal": sidecar_ordinal,
                "sidecar_name_fingerprint": sha256_json(tail),
                "content_hash": sidecar_record["content_hash"],
                "folder_occurrence_hash": parsed_message.folder_path_hash,
                "export_ordinal": sidecar_record["export_file_ordinal"],
                "relative_export_fingerprint": sidecar_record["relative_export_fingerprint"],
                "byte_count": sidecar_record["byte_count"],
                "content_type": ("application/rtf" if is_rtf_body else "application/octet-stream"),
                "representation_kind": sidecar_role,
            }
            separate_files.append(sidecar)
            if is_rtf_body:
                body_sidecars.append(
                    {
                        **sidecar,
                        "body_representation_content_hash": sidecar_record["content_hash"],
                    }
                )
            else:
                separate_attachments.append(
                    {
                        **sidecar,
                        "attachment_content_hash": sidecar_record["content_hash"],
                        "attachment_id_fingerprint": sha256_json(source_local_key),
                        "attachment_name_fingerprint": sha256_json(tail[1:]),
                        "attachment_ordinal": (
                            len(embedded_attachments) + len(separate_attachments) + 1
                        ),
                    }
                )

        messages.append(
            {
                "source_local_key": parsed_message.source_local_key,
                "source_local_stem_fingerprint": (source_local_stem_fingerprint),
                "source_local_ordinal": source_local_ordinal,
                "message_content_hash": file_record["content_hash"],
                "body_hash": parsed_message.body_hash,
                "folder_occurrence_hash": parsed_message.folder_path_hash,
                "folder_identity_fingerprint": sha256_json(
                    _normalize_identity_text(parsed_message.folder_label)
                ),
                "export_ordinal": message_index,
                "export_file_ordinal": file_record["export_file_ordinal"],
                "relative_export_fingerprint": file_record["relative_export_fingerprint"],
                "message_identity_fingerprint": sha256_json(
                    _normalize_identity_text(parsed_message.subject)
                ),
                "oracle_message_identity_fingerprint": (
                    _raw_oracle_message_identity_fingerprint(parsed_message.subject)
                ),
                "sender_identity_fingerprint": sha256_json(
                    _normalize_sender_display(parsed_message.sender)
                ),
                "date_identity_fingerprint": sha256_json(
                    _normalize_identity_text(parsed_message.sent_at)
                ),
                "date_day_identity_fingerprint": _date_day_identity_fingerprint(
                    parsed_message.sent_at
                ),
                "observation_message_fingerprint": _observation_message_fingerprint(parsed_message),
                "message_id_fingerprint": sha256_json(parsed_message.message_id),
                "attachments": [
                    *embedded_attachments,
                    *separate_attachments,
                ],
                "embedded_attachments": embedded_attachments,
                "separate_attachments": separate_attachments,
                "body_sidecars": body_sidecars,
            }
        )

    separate_attachment_count = sum(len(message["separate_attachments"]) for message in messages)
    rtf_body_sidecar_count = sum(len(message["body_sidecars"]) for message in messages)
    embedded_attachment_count = sum(len(message["embedded_attachments"]) for message in messages)
    unclassified_export_file_count = naming_contract_failure_count
    unsupported_export_file_count = sum(
        len(record["export_files"]) for record in unsupported_main_records
    )
    classified_export_file_count = (
        len(messages) + len(separate_files) + unsupported_export_file_count
    )
    missing_embedded_attachment_hash_count = sum(
        1
        for message in messages
        for attachment in message["embedded_attachments"]
        if not isinstance(attachment.get("attachment_content_hash"), str)
    )
    export_file_count, export_byte_count = _tree_metrics(export_root)
    blocker_codes = []
    if not messages:
        blocker_codes.append("parser_export_contains_no_messages")
    if unclassified_export_file_count:
        blocker_codes.append("parser_export_source_local_group_unclassified")
    if unsupported_main_records:
        blocker_codes.append("parser_export_unsupported_main_record")
    if missing_embedded_attachment_hash_count:
        blocker_codes.append("parser_export_attachment_hash_unavailable")
    manifest: dict[str, Any] = {
        "artifact_id": PRIVATE_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not blocker_codes else "blocked",
        "source_asset_sha256": source_asset_sha256,
        "parser_id": "readpst",
        "parser_version": parser_version,
        "parser_version_fingerprint": sha256_json(parser_version),
        "parser_config": {
            "flags": list(PARSER_FLAGS),
            **PARSER_CONFIG,
        },
        "parser_config_fingerprint": sha256_json({"flags": list(PARSER_FLAGS), **PARSER_CONFIG}),
        "stdout_fingerprint": stdout_fingerprint,
        "stderr_fingerprint": stderr_fingerprint,
        "export_rollup_fingerprint": sha256_json(
            [
                {
                    "relative_export_fingerprint": candidate_records[candidate][
                        "relative_export_fingerprint"
                    ],
                    "content_hash": candidate_records[candidate]["content_hash"],
                    "byte_count": candidate_records[candidate]["byte_count"],
                }
                for candidate in candidates
            ]
        ),
        "parse_warning_fingerprints": sorted(parse_warning_fingerprints),
        "blocker_fingerprints": sorted(sha256_json(code) for code in blocker_codes),
        "counts": {
            "export_file_count": export_file_count,
            "export_byte_count": export_byte_count,
            "message_count": len(messages),
            "main_message_file_count": len(messages),
            "main_export_record_count": len(messages) + len(unsupported_main_records),
            "classified_export_file_count": classified_export_file_count,
            "header_sidecar_count": 0,
            "rtf_body_sidecar_count": rtf_body_sidecar_count,
            "embedded_attachment_count": embedded_attachment_count,
            "separate_attachment_count": separate_attachment_count,
            "total_attachment_count": (embedded_attachment_count + separate_attachment_count),
            "separate_export_file_count": len(separate_files),
            "matched_separate_attachment_count": (separate_attachment_count),
            "unclassified_export_file_count": unclassified_export_file_count,
            "missing_embedded_attachment_hash_count": (missing_embedded_attachment_hash_count),
            "source_local_group_count": len(groups),
            "naming_contract_failure_count": (naming_contract_failure_count),
            "unsupported_main_record_count": len(unsupported_main_records),
            "unsupported_export_file_count": unsupported_export_file_count,
            "parse_warning_count": len(parse_warning_fingerprints),
            "blocker_count": len(blocker_codes),
        },
        "messages": messages,
        "unsupported_main_records": unsupported_main_records,
        "separate_export_files": separate_files,
    }
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    _validate_private_manifest(manifest)
    return manifest


def _unsupported_main_record(
    *,
    group_items: list[tuple[Path, str]],
    candidate_records: Mapping[Path, Mapping[str, Any]],
    source_asset_sha256: str,
    source_local_stem_fingerprint: str,
    source_local_ordinal: int,
    folder_occurrence_hash: str,
    reason_code: str,
) -> dict[str, Any]:
    ordered_records = sorted(
        (
            {
                "content_hash": candidate_records[path]["content_hash"],
                "export_file_ordinal": candidate_records[path]["export_file_ordinal"],
                "relative_export_fingerprint": candidate_records[path][
                    "relative_export_fingerprint"
                ],
                "representation_kind": (
                    "unsupported_main_candidate"
                    if not tail
                    else (
                        "rtf_body_representation"
                        if tail.casefold().startswith("-rtf-body.rtf")
                        else "unresolved_separate_sidecar"
                    )
                ),
            }
            for path, tail in group_items
        ),
        key=lambda row: int(row["export_file_ordinal"]),
    )
    main_records = [candidate_records[path] for path, tail in group_items if not tail]
    message_content_hash = (
        str(main_records[0]["content_hash"])
        if len(main_records) == 1
        else sha256_json(ordered_records)
    )
    export_file_ordinal = min(int(record["export_file_ordinal"]) for record in ordered_records)
    source_local_key = stable_resource_contract_id(
        "pstunsupportedsrc",
        "Issue56ReadpstUnsupportedMainOccurrence",
        {
            "source_asset_sha256": source_asset_sha256,
            "source_local_stem_fingerprint": source_local_stem_fingerprint,
            "source_local_ordinal": source_local_ordinal,
            "message_content_hash": message_content_hash,
            "reason_fingerprint": sha256_json(reason_code),
        },
    )
    return {
        "source_local_key": source_local_key,
        "source_local_stem_fingerprint": source_local_stem_fingerprint,
        "source_local_ordinal": source_local_ordinal,
        "message_content_hash": message_content_hash,
        "folder_occurrence_hash": folder_occurrence_hash,
        "export_ordinal": source_local_ordinal,
        "export_file_ordinal": export_file_ordinal,
        "export_group_fingerprint": sha256_json(ordered_records),
        "export_files": ordered_records,
        "reason_fingerprint": sha256_json(reason_code),
        "processing_state": "unsupported",
    }


def _observation_message_fingerprint(message: Any) -> str:
    return sha256_json(
        {
            "message_id": message.message_id,
            "normalized_subject": message.normalized_subject,
            "sender": message.sender,
            "sent_at": message.sent_at,
            "body_hash": message.body_hash,
            "attachment_hashes": sorted(
                attachment.content_hash
                for attachment in message.attachments
                if attachment.content_hash
            ),
        }
    )


def _raw_oracle_message_identity_fingerprint(subject: str) -> str:
    return stable_resource_contract_hash(
        "Issue56PstMessageCoarseIdentity",
        {
            "identity_policy_id": RAW_ORACLE_IDENTITY_POLICY_ID,
            "normalized_subject": _normalize_identity_text(subject),
        },
    )


def _date_day_identity_fingerprint(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return sha256_json("")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return sha256_json("")
    return sha256_json(parsed.date().isoformat())


def _build_public_report(
    *,
    private_manifest: Mapping[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "artifact_id": PUBLIC_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": private_manifest["status"],
        "source_asset_sha256": private_manifest["source_asset_sha256"],
        "private_manifest_fingerprint": private_manifest["manifest_fingerprint"],
        "parser_version_fingerprint": private_manifest["parser_version_fingerprint"],
        "parser_config_fingerprint": private_manifest["parser_config_fingerprint"],
        "export_rollup_fingerprint": private_manifest["export_rollup_fingerprint"],
        "blocker_fingerprints": private_manifest["blocker_fingerprints"],
        "round_trip_status": {
            "parser_export": "passed",
            "private_manifest": "passed",
            "public_report": "passed",
        },
        "counts": {
            **private_manifest["counts"],
            "elapsed_seconds": int(elapsed_seconds),
        },
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    _validate_public_report(report)
    return report


def _validate_private_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("artifact_id") != PRIVATE_ARTIFACT_ID:
        raise RuntimeError("parser_export_private_artifact_invalid")
    if not _FINGERPRINT_RE.fullmatch(str(manifest.get("source_asset_sha256", ""))):
        raise RuntimeError("parser_export_private_asset_binding_invalid")
    if manifest.get("manifest_fingerprint") != _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    ):
        raise RuntimeError("parser_export_private_fingerprint_invalid")
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("parser_export_private_counts_invalid")
    if int(counts.get("classified_export_file_count", -1)) + int(
        counts.get("unclassified_export_file_count", -1)
    ) != int(counts.get("export_file_count", -1)):
        raise RuntimeError("parser_export_file_classification_incomplete")
    required_message_fields = {
        "source_local_key",
        "message_content_hash",
        "body_hash",
        "folder_occurrence_hash",
        "folder_identity_fingerprint",
        "oracle_message_identity_fingerprint",
        "date_day_identity_fingerprint",
        "export_ordinal",
    }
    for message in manifest.get("messages", []):
        if not required_message_fields.issubset(message):
            raise RuntimeError("parser_export_message_contract_incomplete")
        for attachment in message.get("attachments", []):
            if not {
                "source_local_key",
                "attachment_content_hash",
                "folder_occurrence_hash",
                "export_ordinal",
            }.issubset(attachment):
                raise RuntimeError("parser_export_attachment_contract_incomplete")
    required_unsupported_fields = {
        "source_local_key",
        "source_local_stem_fingerprint",
        "source_local_ordinal",
        "message_content_hash",
        "folder_occurrence_hash",
        "export_ordinal",
        "reason_fingerprint",
        "processing_state",
        "export_files",
    }
    for record in manifest.get("unsupported_main_records", []):
        if not required_unsupported_fields.issubset(record):
            raise RuntimeError("parser_export_unsupported_main_contract_incomplete")
        if record.get("processing_state") != "unsupported":
            raise RuntimeError("parser_export_unsupported_main_state_invalid")
        if not isinstance(record.get("export_files"), list) or not record["export_files"]:
            raise RuntimeError("parser_export_unsupported_files_invalid")


def _validate_public_report(report: Mapping[str, Any]) -> None:
    if report.get("artifact_id") != PUBLIC_ARTIFACT_ID:
        raise RuntimeError("parser_export_public_artifact_invalid")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise RuntimeError("parser_export_public_fingerprint_invalid")
    counts = report.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(value, int) or isinstance(value, bool) for value in counts.values()
    ):
        raise RuntimeError("parser_export_public_counts_invalid")
    assert_no_public_raw_references(
        report,
        "issue56_pst_parser_export_public_report",
    )


def _persist_immutable(
    path: Path,
    payload: Mapping[str, Any],
    *,
    fingerprint_field: str,
) -> dict[str, Any]:
    canonical = json.loads(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    if canonical.get(fingerprint_field) != _payload_fingerprint(
        canonical,
        fingerprint_field,
    ):
        raise RuntimeError("parser_export_immutable_fingerprint_invalid")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = (json.dumps(canonical, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if loaded != canonical:
            raise RuntimeError("parser_export_immutable_conflict")
        return loaded
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if loaded != canonical:
        raise RuntimeError("parser_export_immutable_round_trip_failed")
    return loaded


def _make_tree_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o500 if path.is_dir() else 0o400)
    root.chmod(0o500)


def _tree_metrics(root: Path) -> tuple[int, int]:
    file_count = 0
    byte_count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            byte_count += path.stat().st_size
        except OSError:
            continue
        file_count += 1
    return file_count, byte_count


def _relative_file_fingerprint(path: Path, root: Path) -> str:
    return sha256_json(str(path.relative_to(root)).replace("\\", "/"))


def _normalize_identity_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _normalize_sender_display(value: str) -> str:
    text = _normalize_identity_text(value)
    match = re.match(r"^(.*?)\\s*<[^<>]+>$", text)
    return (match.group(1) if match else text).strip().strip('"')


def _parser_version(value: str) -> str:
    match = re.search(r"LibPST v([0-9.]+)", value)
    if match is None:
        raise RuntimeError("parser_export_version_unavailable")
    return match.group(1)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _payload_fingerprint(payload: Mapping[str, Any], field_name: str) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != field_name})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pst", type=Path, default=DEFAULT_PST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--parser-command", default="readpst")
    parser.add_argument("--expected-asset-sha256", default=EXPECTED_ASSET_SHA256)
    parser.add_argument("--progress-interval-seconds", type=float, default=30.0)
    args = parser.parse_args()
    artifacts = run_parser_export_once(
        pst_path=args.pst,
        output_root=args.output_root,
        parser_command=args.parser_command,
        expected_asset_sha256=args.expected_asset_sha256,
        progress_interval_seconds=args.progress_interval_seconds,
    )
    print(json.dumps(artifacts.public_report, sort_keys=True))
    return 0 if artifacts.public_report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
