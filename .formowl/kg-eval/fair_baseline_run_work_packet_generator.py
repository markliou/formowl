#!/usr/bin/env python3
"""Generate non-evidence work packets for fair external baseline runs.

The generated packet describes assignment surfaces for future real package
execution. It does not execute packages, create run artifacts, create human
adjudication, write real evidence, or write the canonical fair-baseline packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import external_literature_baseline_protocol_recovery as literature
import fair_external_baseline_run_validator as validator


ROOT = Path(__file__).resolve().parent
WORK_PACKETS = ROOT / "work_packets"
DEFAULT_OUTPUT_PATH = WORK_PACKETS / "fair_baseline_run_work_packet_preview.json"
CANONICAL_PACKET_PATH = validator.INPUTS / "fair_external_baseline_run_packet.json"
REAL_ROOT = validator.INPUTS / "fair_baseline_real"
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

REQUIRED_SOURCE_IDS_BY_BASELINE = literature.REQUIRED_SOURCE_IDS_BY_BASELINE


class WorkPacketError(ValueError):
    """Raised when a work packet path or source lock would be unsafe."""


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


def _source_by_id() -> dict[str, dict[str, Any]]:
    sources = literature.default_sources()
    required_source_ids = {
        source_id
        for source_ids in REQUIRED_SOURCE_IDS_BY_BASELINE.values()
        for source_id in source_ids
    }
    by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise WorkPacketError("literature source rows must be objects")
        source_id = _ensure_safe_identifier(source.get("source_id"), "source_id")
        if source_id not in required_source_ids:
            continue
        if source_id in by_id:
            raise WorkPacketError("literature source ids must be distinct")
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith(
            ("https://github.com/", "https://arxiv.org/", "https://microsoft.github.io/")
        ):
            raise WorkPacketError("literature source URL must be an approved public source")
        _reject_forbidden_text(url, "source_url")
        by_id[source_id] = {
            "source_id": source_id,
            "source_type": source.get("source_type"),
            "year": source.get("year"),
            "url": url,
        }
    return by_id


def build_source_lock() -> dict[str, Any]:
    source_by_id = _source_by_id()
    locked_sources = []
    for baseline_id, source_ids in REQUIRED_SOURCE_IDS_BY_BASELINE.items():
        _ensure_safe_identifier(baseline_id, "baseline_id")
        for source_id in source_ids:
            if source_id not in source_by_id:
                raise WorkPacketError(f"missing source for {source_id}")
            locked_sources.append(source_by_id[source_id])
    return {
        "source_lock_type": "fair_external_baseline_source_lock_v1",
        "protocol_current_date": literature.CURRENT_DATE,
        "locked_sources": locked_sources,
        "source_lock_sha256": sha256_json(locked_sources),
    }


def build_equalized_surface_sha256s() -> dict[str, str]:
    return {
        surface_name: sha256_json(
            {
                "surface_name": surface_name,
                "protocol": "fair_external_baseline_non_evidence_assignment",
                "later_real_packet_field": surface_name,
            }
        )
        for surface_name in validator.EQUALIZED_FIELDS
    }


def build_run_manifest_artifact(source_lock: dict[str, Any]) -> dict[str, Any]:
    source_by_id = {
        source["source_id"]: source
        for source in source_lock["locked_sources"]
        if isinstance(source, dict)
    }
    locked_baselines = []
    for baseline_id in validator.REQUIRED_BASELINES:
        source_ids = REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]
        package_source_url = validator.REQUIRED_BASELINE_URLS[baseline_id]
        locked_baselines.append(
            {
                "baseline_id": baseline_id,
                "package_source_url": package_source_url,
                "source_ids": list(source_ids),
                "source_urls": [source_by_id[source_id]["url"] for source_id in source_ids],
            }
        )
    equalized_surface_contract_sha256s = build_equalized_surface_sha256s()
    manifest = {
        "artifact_type": "fair_external_baseline_run_manifest_v1",
        "baseline_ids": list(validator.REQUIRED_BASELINES),
        "locked_baselines": locked_baselines,
        "source_lock_sha256": source_lock["source_lock_sha256"],
        "equalized_surface_contract_sha256s": equalized_surface_contract_sha256s,
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    return manifest


def build_assignment_rows(
    *,
    run_manifest_artifact: dict[str, Any],
    source_lock: dict[str, Any],
) -> list[dict[str, Any]]:
    source_by_id = {
        source["source_id"]: source
        for source in source_lock["locked_sources"]
        if isinstance(source, dict)
    }
    equalized_surface_contract_sha256s = run_manifest_artifact["equalized_surface_contract_sha256s"]
    rows = []
    for baseline_id in validator.REQUIRED_BASELINES:
        baseline_id = _ensure_safe_identifier(baseline_id, "baseline_id")
        source_ids = REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]
        package_source_url = validator.REQUIRED_BASELINE_URLS[baseline_id]
        _reject_forbidden_text(package_source_url, "package_source_url")
        rows.append(
            {
                "baseline_id": baseline_id,
                "package_source_url": package_source_url,
                "source_ids": list(source_ids),
                "source_urls": [source_by_id[source_id]["url"] for source_id in source_ids],
                "run_artifact_field_names": list(validator.RUN_ARTIFACT_FIELDS),
                "equalized_surface_contract_sha256s": dict(equalized_surface_contract_sha256s),
                "permission_probe_names": list(validator.REQUIRED_PERMISSION_PROBES),
                "row_sha256": sha256_json(
                    {
                        "baseline_id": baseline_id,
                        "package_source_url": package_source_url,
                        "source_ids": source_ids,
                        "run_artifact_field_names": list(validator.RUN_ARTIFACT_FIELDS),
                        "equalized_surface_contract_sha256s": equalized_surface_contract_sha256s,
                        "permission_probe_names": list(validator.REQUIRED_PERMISSION_PROBES),
                    }
                ),
            }
        )
    return rows


def build_run_assignments_artifact(
    *,
    run_manifest_artifact: dict[str, Any],
    source_lock: dict[str, Any],
) -> dict[str, Any]:
    rows = build_assignment_rows(
        run_manifest_artifact=run_manifest_artifact,
        source_lock=source_lock,
    )
    artifact = {
        "artifact_type": "fair_external_baseline_run_assignments_v1",
        "manifest_sha256": run_manifest_artifact["manifest_sha256"],
        "assignment_count": len(rows),
        "assignment_rows": rows,
    }
    artifact["assignments_sha256"] = sha256_json(artifact)
    return artifact


def build_work_packet() -> dict[str, Any]:
    source_lock = build_source_lock()
    run_manifest = build_run_manifest_artifact(source_lock)
    run_assignments = build_run_assignments_artifact(
        run_manifest_artifact=run_manifest,
        source_lock=source_lock,
    )
    packet = {
        "work_packet_type": "fair_baseline_run_work_packet_preview_v1",
        "work_packet_state": "operator_assignment_only",
        "evidence_state": "non_evidence",
        "safe_output_root": "work_packets/",
        "forbidden_output_roots": [
            "inputs/fair_baseline_real/",
            "inputs/test_*",
            "results/",
            "templates/",
        ],
        "artifact_boundary": {
            "executes_packages": False,
            "creates_run_artifacts": False,
            "creates_human_adjudication": False,
            "creates_graph_quality_review": False,
            "creates_permission_probe_results": False,
            "writes_canonical_packet": False,
            "touches_real_evidence_root": False,
            "counts_as_acceptance_gate": False,
        },
        "canonical_packet_not_written": str(CANONICAL_PACKET_PATH.relative_to(ROOT)),
        "real_evidence_root_not_written": str(REAL_ROOT.relative_to(ROOT)),
        "run_manifest_artifact": run_manifest,
        "run_assignments_artifact": run_assignments,
        "validator_expectation": {
            "authoritative_validator_must_be_run_separately": True,
            "this_packet_is_sufficient_for_fair_baseline_gate": False,
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
