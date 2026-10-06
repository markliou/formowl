#!/usr/bin/env python3
"""Validate a private libpst native-lineage export without rerunning readpst."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


PRIVATE_ARTIFACT_ID = "formowl_issue56_pst_native_lineage_private_manifest_v1"
PUBLIC_ARTIFACT_ID = "formowl_issue56_pst_native_lineage_public_report_v1"
SIDECAR_SCHEMA = "formowl_libpst_native_lineage_v1"
SCHEMA_VERSION = 1
SOURCE_COMMIT = "d963f2adf9fb7e65cdccbf7d35ceb06c63100f80"
EXPECTED_ASSET_SHA256 = "sha256:82dddb25fffd14cd0c5576a0791bc408aab0d15d5eb76be1727e14cff658caaf"
PARSER_CONFIG = {
    "flags": ["-S", "-t", "ea", "-j", "0", "-q"],
    "include_deleted_items": False,
    "msg_output_enabled": False,
    "source_native_lineage": True,
}
SIDECAR_HEADER = (
    "schema",
    "kind",
    "folder_d_id",
    "message_d_id",
    "message_i_id",
    "attachment_i_id",
    "disposition",
    "status",
    "reason",
    "path_hex",
    "content_sha256",
    "byte_count",
)
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_NODE_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class NativeLineageArtifacts:
    private_manifest: dict[str, Any]
    public_report: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _payload_fingerprint(value: Mapping[str, Any], field: str) -> str:
    return _sha256_json({key: item for key, item in value.items() if key != field})


def _source_local_key(kind: str, payload: Mapping[str, Any]) -> str:
    return f"pstnative_{kind}_{_sha256_json(payload).removeprefix('sha256:')[:32]}"


def _read_sidecar(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        header = tuple(handle.readline().rstrip("\n").split("\t"))
        if header != SIDECAR_HEADER:
            raise RuntimeError("native_lineage_sidecar_header_invalid")
        rows: list[dict[str, str]] = []
        for line_number, line in enumerate(handle, start=2):
            fields = line.rstrip("\n").split("\t")
            if len(fields) != len(SIDECAR_HEADER):
                raise RuntimeError(f"native_lineage_sidecar_row_invalid:{line_number}")
            row = dict(zip(SIDECAR_HEADER, fields, strict=True))
            _validate_sidecar_row(row, line_number=line_number)
            rows.append(row)
    if not rows:
        raise RuntimeError("native_lineage_sidecar_empty")
    return rows


def _validate_sidecar_row(row: Mapping[str, str], *, line_number: int) -> None:
    if row["schema"] != SIDECAR_SCHEMA:
        raise RuntimeError(f"native_lineage_sidecar_schema_invalid:{line_number}")
    if row["kind"] not in {"folder", "message", "attachment", "descriptor"}:
        raise RuntimeError(f"native_lineage_sidecar_kind_invalid:{line_number}")
    for field in (
        "folder_d_id",
        "message_d_id",
        "message_i_id",
        "attachment_i_id",
    ):
        if not _NODE_ID_RE.fullmatch(row[field]):
            raise RuntimeError(f"native_lineage_sidecar_node_id_invalid:{line_number}")
    if row["status"] not in {"started", "passed", "failed"}:
        raise RuntimeError(f"native_lineage_sidecar_status_invalid:{line_number}")
    if row["path_hex"] != "-":
        try:
            bytes.fromhex(row["path_hex"]).decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"native_lineage_sidecar_path_encoding_invalid:{line_number}"
            ) from exc
    if row["content_sha256"] != "-" and not _HEX64_RE.fullmatch(row["content_sha256"]):
        raise RuntimeError(f"native_lineage_sidecar_content_hash_invalid:{line_number}")
    try:
        byte_count = int(row["byte_count"])
    except ValueError as exc:
        raise RuntimeError(f"native_lineage_sidecar_byte_count_invalid:{line_number}") from exc
    if byte_count < 0:
        raise RuntimeError(f"native_lineage_sidecar_byte_count_invalid:{line_number}")


def _relative_private_output(row: Mapping[str, str], *, export_root: Path) -> str | None:
    if row["path_hex"] == "-":
        return None
    decoded = bytes.fromhex(row["path_hex"]).decode("utf-8")
    output_path = Path(decoded).resolve()
    try:
        relative = output_path.relative_to(export_root)
    except ValueError as exc:
        raise RuntimeError("native_lineage_output_outside_export_root") from exc
    if not output_path.is_file():
        raise RuntimeError("native_lineage_output_missing")
    if output_path.stat().st_size != int(row["byte_count"]):
        raise RuntimeError("native_lineage_output_byte_count_drift")
    if _sha256_file(output_path) != f"sha256:{row['content_sha256']}":
        raise RuntimeError("native_lineage_output_content_hash_drift")
    return relative.as_posix()


def _message_key(row: Mapping[str, str]) -> tuple[str, str, str]:
    return row["folder_d_id"], row["message_d_id"], row["message_i_id"]


def _attachment_records(
    rows: Iterable[Mapping[str, str]],
    *,
    export_root: Path,
    parent_source_local_key: str,
    source_asset_sha256: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    occurrence_counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        identity = (
            row["attachment_i_id"],
            row["disposition"],
            row["content_sha256"],
        )
        occurrence_counts[identity] += 1
        occurrence_ordinal = occurrence_counts[identity]
        relative_output = _relative_private_output(row, export_root=export_root)
        content_hash = f"sha256:{row['content_sha256']}" if row["content_sha256"] != "-" else None
        record = {
            "source_local_key": _source_local_key(
                "attachment",
                {
                    "source_asset_sha256": source_asset_sha256,
                    "parent_source_local_key": parent_source_local_key,
                    "attachment_i_id": row["attachment_i_id"],
                    "disposition": row["disposition"],
                    "content_hash": content_hash,
                    "occurrence_ordinal": occurrence_ordinal,
                },
            ),
            "pst_attachment_node_id": row["attachment_i_id"],
            "export_disposition": row["disposition"],
            "export_status": row["status"],
            "export_reason": row["reason"],
            "attachment_content_hash": content_hash,
            "byte_count": int(row["byte_count"]),
            "export_occurrence_ordinal": occurrence_ordinal,
            "relative_output_path": relative_output,
        }
        records.append(record)
    return records


def build_manifest_from_existing_native_export(
    *,
    pst_path: Path,
    export_root: Path,
    sidecar_path: Path,
    parser_binary_path: Path,
    runtime_library_path: Path,
    expected_asset_sha256: str = EXPECTED_ASSET_SHA256,
    source_commit: str = SOURCE_COMMIT,
) -> NativeLineageArtifacts:
    """Validate one completed native-lineage run and return safe artifacts."""

    export_root = export_root.resolve()
    if source_commit != SOURCE_COMMIT:
        raise RuntimeError("native_lineage_source_commit_mismatch")
    source_asset_sha256 = _sha256_file(pst_path)
    if source_asset_sha256 != expected_asset_sha256:
        raise RuntimeError("native_lineage_source_asset_mismatch")
    parser_binary_sha256 = _sha256_file(parser_binary_path)
    runtime_library_sha256 = _sha256_file(runtime_library_path)
    rows = _read_sidecar(sidecar_path)

    message_rows = [row for row in rows if row["kind"] == "message"]
    attachment_rows = [row for row in rows if row["kind"] == "attachment"]
    failed_rows = [row for row in rows if row["status"] == "failed"]
    unsupported_rows = [
        row
        for row in rows
        if row["kind"] == "descriptor" and row["reason"] == "unsupported_item_type"
    ]

    started_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    final_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    attachments_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in message_rows:
        target = started_by_key if row["status"] == "started" else final_by_key
        target[_message_key(row)].append(row)
    for row in attachment_rows:
        attachments_by_key[_message_key(row)].append(row)

    if any(len(group) != 1 for group in started_by_key.values()):
        raise RuntimeError("native_lineage_message_start_not_unique")
    if any(len(group) != 1 for group in final_by_key.values()):
        raise RuntimeError("native_lineage_message_final_not_unique")
    if set(started_by_key) != set(final_by_key):
        raise RuntimeError("native_lineage_message_start_final_mismatch")

    messages: list[dict[str, Any]] = []
    duplicate_attachment_identity_count = 0
    for key in sorted(started_by_key):
        final = final_by_key[key][0]
        if final["status"] != "passed" or final["disposition"] != "exported":
            raise RuntimeError("native_lineage_message_not_exported")
        relative_output = _relative_private_output(final, export_root=export_root)
        if relative_output is None:
            raise RuntimeError("native_lineage_message_output_missing")
        source_local_key = _source_local_key(
            "message",
            {
                "source_asset_sha256": source_asset_sha256,
                "folder_d_id": key[0],
                "message_d_id": key[1],
                "message_i_id": key[2],
            },
        )
        native_attachments = _attachment_records(
            attachments_by_key.get(key, []),
            export_root=export_root,
            parent_source_local_key=source_local_key,
            source_asset_sha256=source_asset_sha256,
        )
        attachment_identities = Counter(
            (
                row["pst_attachment_node_id"],
                row["export_disposition"],
                row["attachment_content_hash"],
            )
            for row in native_attachments
        )
        duplicate_attachment_identity_count += sum(
            count - 1 for count in attachment_identities.values() if count > 1
        )
        messages.append(
            {
                "source_local_key": source_local_key,
                "pst_folder_node_id": key[0],
                "pst_message_node_id": key[1],
                "pst_message_data_node_id": key[2],
                "export_disposition": final["disposition"],
                "export_status": final["status"],
                "export_reason": final["reason"],
                "message_content_hash": f"sha256:{final['content_sha256']}",
                "byte_count": int(final["byte_count"]),
                "relative_output_path": relative_output,
                "attachments": native_attachments,
            }
        )

    parser_config_fingerprint = _sha256_json(PARSER_CONFIG)
    sidecar_sha256 = _sha256_file(sidecar_path)
    counts = {
        "message_occurrence_count": len(messages),
        "message_exported_count": len(messages),
        "message_unexplained_count": 0,
        "attachment_output_occurrence_count": len(attachment_rows),
        "attachment_nonzero_node_id_count": sum(
            row["attachment_i_id"] != "0000000000000000" for row in attachment_rows
        ),
        "attachment_embedded_message_count": sum(
            row["disposition"] == "embedded_message_exported" for row in attachment_rows
        ),
        "attachment_synthetic_representation_count": sum(
            row["disposition"] == "synthetic_body_exported" for row in attachment_rows
        ),
        "duplicate_attachment_identity_count": duplicate_attachment_identity_count,
        "unsupported_non_message_record_count": len(unsupported_rows),
        "failed_record_count": len(failed_rows),
    }
    status = "passed" if not failed_rows else "blocked"
    blocker_ids = [] if status == "passed" else ["native_lineage_failed_record_present"]
    private_manifest: dict[str, Any] = {
        "artifact_id": PRIVATE_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source_asset_sha256": source_asset_sha256,
        "parser_source_commit": source_commit,
        "parser_binary_sha256": parser_binary_sha256,
        "runtime_library_sha256": runtime_library_sha256,
        "parser_config": PARSER_CONFIG,
        "parser_config_fingerprint": parser_config_fingerprint,
        "sidecar_sha256": sidecar_sha256,
        "counts": counts,
        "blocker_ids": blocker_ids,
        "messages": messages,
        "unsupported_non_message_records": [
            {
                "pst_folder_node_id": row["folder_d_id"],
                "pst_record_node_id": row["message_d_id"],
                "pst_record_data_node_id": row["message_i_id"],
                "export_disposition": row["disposition"],
                "export_status": row["status"],
                "export_reason": row["reason"],
            }
            for row in unsupported_rows
        ],
    }
    private_manifest["manifest_fingerprint"] = _payload_fingerprint(
        private_manifest,
        "manifest_fingerprint",
    )
    validate_private_manifest(private_manifest)

    public_report: dict[str, Any] = {
        "artifact_id": PUBLIC_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source_asset_sha256": source_asset_sha256,
        "parser_source_commit_fingerprint": _sha256_json(source_commit),
        "parser_binary_sha256": parser_binary_sha256,
        "runtime_library_sha256": runtime_library_sha256,
        "parser_config_fingerprint": parser_config_fingerprint,
        "sidecar_sha256": sidecar_sha256,
        "private_manifest_fingerprint": private_manifest["manifest_fingerprint"],
        "counts": counts,
        "blocker_ids": blocker_ids,
    }
    public_report["report_fingerprint"] = _payload_fingerprint(
        public_report,
        "report_fingerprint",
    )
    validate_public_report(public_report)
    return NativeLineageArtifacts(
        private_manifest=private_manifest,
        public_report=public_report,
    )


def validate_private_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("artifact_id") != PRIVATE_ARTIFACT_ID:
        raise RuntimeError("native_lineage_private_manifest_artifact_invalid")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("native_lineage_private_manifest_schema_invalid")
    if manifest.get("parser_source_commit") != SOURCE_COMMIT:
        raise RuntimeError("native_lineage_private_manifest_source_commit_invalid")
    for field in (
        "source_asset_sha256",
        "parser_binary_sha256",
        "runtime_library_sha256",
        "parser_config_fingerprint",
        "sidecar_sha256",
        "manifest_fingerprint",
    ):
        if not _FINGERPRINT_RE.fullmatch(str(manifest.get(field, ""))):
            raise RuntimeError(f"native_lineage_private_manifest_{field}_invalid")
    if manifest.get("parser_config_fingerprint") != _sha256_json(manifest.get("parser_config")):
        raise RuntimeError("native_lineage_private_manifest_config_drift")
    if manifest.get("manifest_fingerprint") != _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    ):
        raise RuntimeError("native_lineage_private_manifest_fingerprint_invalid")
    if not isinstance(manifest.get("messages"), list):
        raise RuntimeError("native_lineage_private_manifest_messages_invalid")


def validate_public_report(report: Mapping[str, Any]) -> None:
    if report.get("artifact_id") != PUBLIC_ARTIFACT_ID:
        raise RuntimeError("native_lineage_public_report_artifact_invalid")
    if report.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("native_lineage_public_report_schema_invalid")
    if report.get("status") not in {"passed", "blocked"}:
        raise RuntimeError("native_lineage_public_report_status_invalid")
    for field in (
        "source_asset_sha256",
        "parser_source_commit_fingerprint",
        "parser_binary_sha256",
        "runtime_library_sha256",
        "parser_config_fingerprint",
        "sidecar_sha256",
        "private_manifest_fingerprint",
        "report_fingerprint",
    ):
        if not _FINGERPRINT_RE.fullmatch(str(report.get(field, ""))):
            raise RuntimeError(f"native_lineage_public_report_{field}_invalid")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise RuntimeError("native_lineage_public_report_fingerprint_invalid")
    serialized = json.dumps(report, sort_keys=True)
    forbidden = ("path", "filename", "subject", "sender", "body", "payload")
    if any(term in serialized.casefold() for term in forbidden):
        raise RuntimeError("native_lineage_public_report_private_field_exposed")


def persist_artifacts(
    *,
    artifacts: NativeLineageArtifacts,
    private_manifest_output: Path,
    public_report_output: Path,
) -> None:
    for path, value in (
        (private_manifest_output, artifacts.private_manifest),
        (public_report_output, artifacts.public_report),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
    validate_private_manifest(json.loads(private_manifest_output.read_text(encoding="utf-8")))
    validate_public_report(json.loads(public_report_output.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pst", type=Path, required=True)
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--parser-binary", type=Path, required=True)
    parser.add_argument("--runtime-library", type=Path, required=True)
    parser.add_argument("--private-manifest-output", type=Path, required=True)
    parser.add_argument("--public-report-output", type=Path, required=True)
    parser.add_argument("--expected-asset-sha256", default=EXPECTED_ASSET_SHA256)
    args = parser.parse_args()
    artifacts = build_manifest_from_existing_native_export(
        pst_path=args.pst,
        export_root=args.export_root,
        sidecar_path=args.sidecar,
        parser_binary_path=args.parser_binary,
        runtime_library_path=args.runtime_library,
        expected_asset_sha256=args.expected_asset_sha256,
    )
    persist_artifacts(
        artifacts=artifacts,
        private_manifest_output=args.private_manifest_output,
        public_report_output=args.public_report_output,
    )
    print(json.dumps(artifacts.public_report, sort_keys=True, separators=(",", ":")))
    return 0 if artifacts.public_report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
