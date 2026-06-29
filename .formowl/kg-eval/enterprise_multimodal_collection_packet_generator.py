#!/usr/bin/env python3
"""Generate non-evidence collection packets for enterprise multimodal validation.

The generated packet is operator assignment material. It describes what future
real enterprise artifacts must capture for spreadsheet, mail, meeting audio,
and video OCR validation. It does not create real source rows, validation rows,
human review results, permission probe results, assembly manifests, or the
canonical validation packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import enterprise_multimodal_packet_assembler as assembler
import enterprise_multimodal_validation_validator as validator


ROOT = Path(__file__).resolve().parent
WORK_PACKETS = ROOT / "work_packets"
DEFAULT_OUTPUT_PATH = WORK_PACKETS / "enterprise_multimodal_collection_packet_preview.json"
CANONICAL_PACKET_PATH = validator.PACKET_PATH
REAL_ROOT = assembler.REAL_INPUT_ROOT
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,96}$")

FORBIDDEN_TEXT_MARKERS = (
    "file://",
    "s3://",
    "gs://",
    "object://",
    "postgres://",
    "postgresql://",
    "mysql://",
    "nas://",
    "smb://",
    "nfs://",
    "webdav://",
    "\\",
    "../",
    "/tmp/",
    "inputs/test_",
    "results/",
    "templates/",
    "template_only",
    "do_not_submit_as_evidence",
)

DEFAULT_MODALITY_REQUIREMENTS = {
    "spreadsheet": {
        "collection_task_id": "collect_spreadsheet_finance_tables",
        "source_family": "finance_table_asset",
        "locator_fields": ["sheet", "table_index", "row_index", "column_index", "cell_address"],
        "validation_focus": [
            "amount due extraction",
            "currency and date normalization",
            "row-to-claim traceability",
        ],
        "operator_checks": [
            "register the original workbook or CSV as a FormOwl asset",
            "bind every candidate to an observation id and extractor run id",
            "keep formulas, merged cells, and hidden sheets reviewable",
        ],
    },
    "mail": {
        "collection_task_id": "collect_mail_thread_obligations",
        "source_family": "mail_thread_or_archive_asset",
        "locator_fields": [
            "message_id",
            "mailbox_id",
            "folder_path_hash",
            "uri_fragment",
            "attachment_index",
        ],
        "validation_focus": [
            "thread-level obligation evidence",
            "sender and recipient identity consistency",
            "attachment occurrence binding",
        ],
        "operator_checks": [
            "register mail archives and attachments through FormOwl assets",
            "preserve message occurrence separate from attachment identity",
            "bind candidate claims to message-body or attachment observations",
        ],
    },
    "meeting_audio": {
        "collection_task_id": "collect_meeting_audio_decisions",
        "source_family": "meeting_audio_asset",
        "locator_fields": ["start_sec", "end_sec", "speaker"],
        "validation_focus": [
            "decision transcript support",
            "speaker attribution uncertainty",
            "cross-reference to mail or spreadsheet evidence",
        ],
        "operator_checks": [
            "register original audio or extracted audio as a FormOwl asset",
            "preserve ASR segment timing and speaker labels",
            "mark low-confidence transcript spans for human review",
        ],
    },
    "video_ocr": {
        "collection_task_id": "collect_video_keyframe_ocr_status",
        "source_family": "meeting_or_screen_video_asset",
        "locator_fields": ["timestamp_sec", "frame_index", "bbox"],
        "validation_focus": [
            "keyframe OCR status extraction",
            "screen-step or slide evidence binding",
            "visual text versus transcript disagreement",
        ],
        "operator_checks": [
            "register original video as a FormOwl asset",
            "preserve keyframe time, frame index, and OCR bounding boxes",
            "review OCR text against the visual frame before graph use",
        ],
    },
}


class WorkPacketError(ValueError):
    """Raised when a work packet would be unsafe or evidence-shaped."""


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ensure_safe_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkPacketError(f"{field_name} must be a non-empty string")
    if not SAFE_ID_RE.match(value):
        raise WorkPacketError(f"{field_name} must be a safe identifier")
    lowered = value.lower()
    if any(marker in lowered for marker in ("test_", "fixture", "template")):
        raise WorkPacketError(f"{field_name} must not use test fixture or template markers")
    return value


def _reject_forbidden_text(value: str, field_name: str) -> None:
    lowered = value.lower()
    if value.startswith(("/", "\\")):
        raise WorkPacketError(f"{field_name} must not expose a raw path")
    if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        raise WorkPacketError(
            f"{field_name} must not expose raw, test, result, or template sources"
        )


def _safe_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkPacketError(f"{field_name} must be a non-empty string")
    _reject_forbidden_text(value, field_name)
    return value


def _safe_text_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise WorkPacketError(f"{field_name} must be a non-empty list")
    normalized = [_safe_text(item, field_name) for item in value]
    if len(set(normalized)) != len(normalized):
        raise WorkPacketError(f"{field_name} values must be distinct")
    return normalized


def normalize_modality_requirements(
    requirements: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    source = requirements if requirements is not None else DEFAULT_MODALITY_REQUIREMENTS
    if not isinstance(source, dict) or not source:
        raise WorkPacketError("modality requirements must be a non-empty mapping")
    missing = sorted(set(validator.REQUIRED_MODALITIES) - set(source))
    extra = sorted(set(source) - set(validator.REQUIRED_MODALITIES))
    if missing:
        raise WorkPacketError("modality requirements missing modalities: " + ", ".join(missing))
    if extra:
        raise WorkPacketError(
            "modality requirements contain unsupported modalities: " + ", ".join(extra)
        )

    rows = []
    for modality in validator.REQUIRED_MODALITIES:
        spec = source[modality]
        if not isinstance(spec, dict):
            raise WorkPacketError("each modality requirement must be an object")
        collection_task_id = _ensure_safe_identifier(
            spec.get("collection_task_id"),
            "collection_task_id",
        )
        source_family = _ensure_safe_identifier(spec.get("source_family"), "source_family")
        row = {
            "modality": modality,
            "collection_task_id": collection_task_id,
            "source_family": source_family,
            "locator_fields": _safe_text_list(spec.get("locator_fields"), "locator_fields"),
            "validation_focus": _safe_text_list(spec.get("validation_focus"), "validation_focus"),
            "operator_checks": _safe_text_list(spec.get("operator_checks"), "operator_checks"),
        }
        row["row_sha256"] = sha256_json(row)
        rows.append(row)
    return rows


def build_source_collection_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "plan_type": "enterprise_multimodal_source_collection_plan_v1",
        "required_modality_count": len(validator.REQUIRED_MODALITIES),
        "modality_rows": rows,
        "later_real_packet_requirements": [
            "real enterprise pilot source rows must be supplied through the assembler path",
            "source rows must bind FormOwl asset locators to registered asset identifiers",
            "source rows must not use synthetic, demo, or text-proxy-only data",
            "source rows must not expose raw filesystem, storage, database, or worker paths",
        ],
    }


def build_review_collection_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "plan_type": "enterprise_multimodal_review_collection_plan_v1",
        "required_modality_count": len(rows),
        "review_rows": [
            {
                "review_task_id": f"review_{row['collection_task_id']}",
                "modality": row["modality"],
                "source_collection_row_sha256": row["row_sha256"],
                "minimum_review_checks": [
                    "validate observation identifier and extractor run binding",
                    "compare extracted candidate against source-local locator evidence",
                    "route business-decision candidates to the four-specialist LLM subagent panel",
                    "verify cross-modal access checks deny revoked or private content",
                ],
                "row_sha256": sha256_json(
                    {
                        "review_task_id": f"review_{row['collection_task_id']}",
                        "modality": row["modality"],
                        "source_collection_row_sha256": row["row_sha256"],
                    }
                ),
            }
            for row in rows
        ],
        "later_real_packet_requirements": [
            "four-specialist LLM subagent panel must cover every future validation row; legacy human adjudication remains a backward-compatible route",
            "business decision review must be four-specialist LLM-subagent-reviewed and non-autonomous; legacy human review remains a backward-compatible route",
            "permission probes must deny revoked grants, private content, raw assets, and entity-match-as-access",
        ],
    }


def build_work_packet(
    *,
    modality_requirements: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = normalize_modality_requirements(modality_requirements)
    packet = {
        "work_packet_type": "enterprise_multimodal_collection_packet_preview_v1",
        "work_packet_state": "operator_assignment_only",
        "evidence_state": "non_evidence",
        "safe_output_root": "work_packets/",
        "forbidden_output_roots": [
            "inputs/enterprise_multimodal_real/",
            "inputs/test_*",
            "results/",
            "templates/",
        ],
        "artifact_boundary": {
            "creates_real_source_rows": False,
            "creates_real_validation_rows": False,
            "creates_human_review_results": False,
            "creates_business_review_results": False,
            "creates_permission_probe_results": False,
            "writes_assembly_manifest": False,
            "writes_canonical_packet": False,
            "touches_real_evidence_root": False,
            "counts_as_acceptance_gate": False,
        },
        "canonical_packet_not_written": str(CANONICAL_PACKET_PATH.relative_to(ROOT)),
        "real_evidence_root_not_written": str(REAL_ROOT.relative_to(ROOT)),
        "source_collection_plan": build_source_collection_plan(rows),
        "review_collection_plan": build_review_collection_plan(rows),
        "validator_expectation": {
            "authoritative_validator_must_be_run_separately": True,
            "this_packet_is_sufficient_for_multimodal_gate": False,
        },
    }
    packet["work_packet_sha256"] = sha256_json(packet)
    return packet


def safe_output_path(path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise WorkPacketError("output path must be a non-empty string")
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise WorkPacketError("output path must be a safe relative path")
    if not path.parts or path.parts[0] != "work_packets":
        raise WorkPacketError("output path must live under work_packets/")
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise WorkPacketError("output path symlinks are not accepted")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(WORK_PACKETS.resolve())
    except ValueError as exc:
        raise WorkPacketError("output path escapes the work packet root") from exc
    return resolved


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH.relative_to(ROOT)),
        help="safe relative output path under work_packets/",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    output_path = safe_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    packet = build_work_packet()
    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
