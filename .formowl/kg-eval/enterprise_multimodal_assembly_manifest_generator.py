#!/usr/bin/env python3
"""Generate a non-evidence enterprise multimodal assembly manifest scaffold.

The generated JSON is shaped for ``enterprise_multimodal_packet_assembler`` so
operators can replace placeholder paths with real enterprise pilot artifacts
later. It is intentionally not evidence: it writes only under ``work_orders/``,
keeps all claim flags false, and must fail assembler or validator checks until
real artifacts and human/operator evidence exist.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import enterprise_multimodal_packet_assembler as assembler
import enterprise_multimodal_validation_validator as validator


ROOT = Path(__file__).resolve().parent
WORK_ORDERS = ROOT / "work_orders"
DEFAULT_OUTPUT_PATH = WORK_ORDERS / "multimodal_semantic_validation_assembly_manifest.json"
CANONICAL_PACKET_PATH = assembler.CANONICAL_PACKET_PATH
REAL_ROOT = assembler.REAL_INPUT_ROOT

FORBIDDEN_OUTPUT_ROOTS = {
    "inputs",
    "results",
    "templates",
    "work_packets",
}


class ManifestScaffoldError(ValueError):
    """Raised when the scaffold output path or contract would be unsafe."""


def _real_placeholder(name: str) -> str:
    return f"inputs/enterprise_multimodal_real/fill-with-real-{name}.json"


def build_validation_artifact_scaffold() -> list[dict[str, str]]:
    return [
        {
            "modality": modality,
            "artifact": _real_placeholder(f"{modality}-validation-rows"),
        }
        for modality in validator.REQUIRED_MODALITIES
    ]


def build_claim_boundary_scaffold() -> dict[str, bool]:
    return {field: False for field in sorted(validator.CLAIM_BOUNDARY_ALLOWED_FIELDS)}


def build_manifest_scaffold() -> dict[str, Any]:
    manifest = {
        "artifact_id": "enterprise_multimodal_validation_packet_v1",
        "evidence_kind": "real_enterprise_multimodal_validation",
        "recovered_after_tmp_loss": False,
        "pilot_manifest_artifact": _real_placeholder("pilot-manifest"),
        "validation_artifacts": build_validation_artifact_scaffold(),
        "human_adjudication_artifact": _real_placeholder("human-adjudication"),
        "business_decision_review_artifact": _real_placeholder("business-decision-review"),
        "permission_probe_artifact": _real_placeholder("permission-probe"),
        "claim_boundary": build_claim_boundary_scaffold(),
    }
    unsupported = sorted(set(manifest) - assembler.MANIFEST_ALLOWED_FIELDS)
    missing = sorted(assembler.MANIFEST_COMMON_REQUIRED_FIELDS - set(manifest))
    mixed_or_missing_route = ("human_adjudication_artifact" in manifest) == (
        "llm_subagent_adjudication_artifact" in manifest
    )
    if unsupported or missing or mixed_or_missing_route:
        raise ManifestScaffoldError("manifest scaffold does not match assembler field contract")
    return manifest


def safe_output_path(path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ManifestScaffoldError("output path must be a non-empty string")
    if "\\" in path_value or "://" in path_value:
        raise ManifestScaffoldError("output path must be a safe relative path")
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ManifestScaffoldError("output path must be a safe relative path")
    if any(":" in part for part in path.parts):
        raise ManifestScaffoldError("output path must be a safe relative path")
    if not path.parts or path.parts[0] != "work_orders":
        raise ManifestScaffoldError("output path must live under work_orders/")
    if path.parts[0] in FORBIDDEN_OUTPUT_ROOTS:
        raise ManifestScaffoldError("output path must not live under a forbidden root")
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ManifestScaffoldError("output path symlinks are not accepted")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(WORK_ORDERS.resolve())
    except ValueError as exc:
        raise ManifestScaffoldError("output path escapes the work order root") from exc
    return resolved


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH.relative_to(ROOT)),
        help="safe relative output path under work_orders/",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    output_path = safe_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest_scaffold()
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
