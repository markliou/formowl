#!/usr/bin/env python3
"""Generate a non-evidence fair-baseline assembly manifest scaffold.

The generated JSON is shaped for ``fair_external_baseline_packet_assembler`` so
operators can fill in real run artifacts later. It is intentionally not
evidence: it writes only under ``work_orders/``, contains placeholder values for
all real execution and human-review fields, and must fail assembler or validator
checks until real artifacts are supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import fair_external_baseline_packet_assembler as assembler
import fair_external_baseline_run_validator as validator


ROOT = Path(__file__).resolve().parent
WORK_ORDERS = ROOT / "work_orders"
DEFAULT_OUTPUT_PATH = WORK_ORDERS / "fair_external_baseline_comparison_assembly_manifest.json"
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


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _placeholder(field_name: str) -> str:
    normalized = field_name.replace("_", "-")
    return f"fill-with-real-{normalized}"


def _safe_real_artifact_reference(baseline_id: str, artifact_field: str) -> str:
    if baseline_id not in validator.REQUIRED_BASELINES:
        raise ManifestScaffoldError("baseline id is unsupported")
    if artifact_field not in validator.RUN_ARTIFACT_FIELDS:
        raise ManifestScaffoldError("artifact field is unsupported")
    return f"inputs/fair_baseline_real/{baseline_id}/{artifact_field}.json"


def build_run_environment_scaffold() -> dict[str, Any]:
    return {
        "non_synthetic_benchmark_context": _placeholder(
            "boolean_true_after_non_synthetic_corpus_review"
        ),
        "uses_real_external_packages": _placeholder("boolean_true_after_real_package_execution"),
        "uses_mocked_llm_or_retrieval": _placeholder("boolean_false_after_run_log_review"),
        "container_image_digest_sha256": _placeholder("container_image_digest_sha256"),
        "run_manifest_sha256": _placeholder("run_manifest_sha256"),
    }


def build_baseline_run_scaffold(baseline_id: str) -> dict[str, Any]:
    if baseline_id not in validator.REQUIRED_BASELINES:
        raise ManifestScaffoldError("baseline id is unsupported")
    row: dict[str, Any] = {
        "baseline_id": baseline_id,
        "package_source_url": validator.REQUIRED_BASELINE_URLS[baseline_id],
        "source_ids": list(validator.REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]),
        "package_version": _placeholder(f"{baseline_id}_package_version"),
        "real_package_execution": _placeholder("boolean_true_after_real_run"),
        "mock_or_dry_run": _placeholder("boolean_false_after_real_run"),
        "synthetic_corpus": _placeholder("boolean_false_after_corpus_review"),
    }
    for field in validator.EQUALIZED_FIELDS:
        row[field] = _placeholder(field)
    for field in validator.RUN_ARTIFACT_FIELDS:
        row[field] = _safe_real_artifact_reference(baseline_id, field)
    return row


def build_human_answer_adjudication_scaffold() -> dict[str, Any]:
    return {
        "artifact_id": "human_answer_adjudication_results_v1",
        "completed": _placeholder("boolean_true_after_human_adjudication"),
        "synthetic_or_agent_generated": _placeholder("boolean_false_after_human_custody_review"),
        "question_set_sha256": _placeholder("evaluation_question_set_sha256"),
        "reviewers": [
            {
                "reviewer_id": _placeholder("human_reviewer_alpha_id"),
                "reviewer_type": "human",
                "independent_first_pass": _placeholder(
                    "boolean_true_after_sealed_first_pass_alpha"
                ),
                "sealed_submission_sha256": _placeholder(
                    "human_reviewer_alpha_sealed_submission_sha256"
                ),
            },
            {
                "reviewer_id": _placeholder("human_reviewer_beta_id"),
                "reviewer_type": "human",
                "independent_first_pass": _placeholder("boolean_true_after_sealed_first_pass_beta"),
                "sealed_submission_sha256": _placeholder(
                    "human_reviewer_beta_sealed_submission_sha256"
                ),
            },
        ],
        "adjudicator_id": _placeholder("human_adjudicator_id"),
        "final_adjudication_sha256": _placeholder("final_adjudication_sha256"),
        "custody_receipt_sha256": _placeholder("custody_receipt_sha256"),
        "per_baseline_rows": [
            {
                "baseline_id": baseline_id,
                "question_count": _placeholder(f"{baseline_id}_question_count"),
                "answer_output_artifact_sha256": _placeholder(
                    f"{baseline_id}_answer_output_artifact_sha256"
                ),
            }
            for baseline_id in validator.REQUIRED_BASELINES
        ],
    }


def build_graph_quality_validation_scaffold() -> dict[str, Any]:
    return {
        "completed": _placeholder("boolean_true_after_graph_quality_review"),
        "human_reviewed": _placeholder("boolean_true_after_human_graph_review"),
        "per_baseline_rows": [
            {
                "baseline_id": baseline_id,
                "graph_output_artifact_sha256": _placeholder(
                    f"{baseline_id}_graph_output_artifact_sha256"
                ),
                "reviewed_entity_count": _placeholder(f"{baseline_id}_reviewed_entity_count"),
                "reviewed_relation_count": _placeholder(f"{baseline_id}_reviewed_relation_count"),
            }
            for baseline_id in validator.REQUIRED_BASELINES
        ],
    }


def build_permission_probe_scaffold() -> list[dict[str, Any]]:
    rows = []
    for baseline_id in validator.REQUIRED_BASELINES:
        row = {
            "baseline_id": baseline_id,
            "permission_probe_artifact_sha256": _placeholder(
                f"{baseline_id}_permission_probe_artifact_sha256"
            ),
            "private_content_leak_count": _placeholder(
                f"{baseline_id}_private_content_leak_count_zero"
            ),
            "raw_asset_access_count": _placeholder(f"{baseline_id}_raw_asset_access_count_zero"),
        }
        for probe in validator.REQUIRED_PERMISSION_PROBES:
            row[probe] = _placeholder(f"{baseline_id}_{probe}_true")
        rows.append(row)
    return rows


def build_claim_boundary_scaffold() -> dict[str, bool]:
    # The scaffold deliberately withholds the positive fair-baseline claim. A
    # real operator must flip it only after the real assembler and validator pass.
    return {field: False for field in sorted(validator.CLAIM_BOUNDARY_ALLOWED_FIELDS)}


def build_manifest_scaffold() -> dict[str, Any]:
    manifest = {
        "artifact_id": "fair_external_baseline_run_packet_v1",
        "evidence_kind": "non_synthetic_external_baseline_run",
        "recovered_after_tmp_loss": False,
        "run_environment": build_run_environment_scaffold(),
        "source_lock_sha256": validator.literature.required_baseline_source_lock_sha256(),
        "baseline_runs": [
            build_baseline_run_scaffold(baseline_id) for baseline_id in validator.REQUIRED_BASELINES
        ],
        "human_answer_adjudication": build_human_answer_adjudication_scaffold(),
        "graph_quality_validation": build_graph_quality_validation_scaffold(),
        "permission_probes": build_permission_probe_scaffold(),
        "claim_boundary": build_claim_boundary_scaffold(),
    }
    unsupported = sorted(set(manifest) - assembler.MANIFEST_ALLOWED_FIELDS)
    missing = sorted(assembler.MANIFEST_REQUIRED_FIELDS - set(manifest))
    mixed_or_missing_route = ("human_answer_adjudication" in manifest) == (
        "llm_subagent_adjudication" in manifest
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
