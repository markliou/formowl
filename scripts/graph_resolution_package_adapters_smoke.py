#!/usr/bin/env python3
"""Run or validate the main-repo graph resolution package-adapter smoke.

This harness exercises the optional RapidFuzz and Splink package bindings from
the main repo. It intentionally validates only candidate generation. It does
not claim entity-resolution quality, production readiness, raw-data sharing, or
canonical graph writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid


ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import ContractValidationError, sha256_json  # noqa: E402
from formowl_graph import (  # noqa: E402
    ResolutionPolicy,
    ResolutionRecord,
    build_clerical_review_queue,
    canonical_merge,
    human_clerical_review_queue_export,
    no_raw_access_grant,
    rapid_fuzz_package_version_and_manifest_hash_in_main_repo,
    raw_asset_read,
    real_rapid_fuzz_package_adapter_binding,
    real_splink_package_adapter_binding,
    splink_model_config_manifest_bound_to_main_repo,
)


DEFAULT_OUTPUT = Path(
    "/tmp/formowl-kg-eval/results/main_repo_graph_resolution_package_adapters_smoke.json"
)
CREATED_AT = "2026-06-21T00:00:00+00:00"
FORBIDDEN_TEXT = (
    "/home/",
    "/tmp/formowl",
    "/workspace/",
    "postgresql://",
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "raw_path",
    "internal_sql",
    "canonical_graph_revision_id",
)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _record(
    record_id: str,
    label: str,
    *,
    core_supertype: str = "Organization",
    owner_user_id: str = "user_ops",
    scope_type: str = "workspace",
    scope_id: str = "demo_workspace",
    source_candidate_atom_id: str | None = None,
    source_observation_ids: tuple[str, ...] | None = None,
    attributes: dict[str, str] | None = None,
) -> ResolutionRecord:
    return ResolutionRecord.from_candidate_atom(
        record_id=record_id,
        label=label,
        atom_type=core_supertype,
        owner_user_id=owner_user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        source_candidate_atom_id=source_candidate_atom_id or f"catom_{record_id}",
        source_observation_ids=source_observation_ids or (f"obs_{record_id}",),
        attributes=attributes or {},
    )


def containerized_rapid_fuzz_adapter_smoke(report: dict[str, Any]) -> bool:
    metrics = report.get("metrics", {})
    claims = report.get("claim_boundary", {})
    return (
        report.get("artifact_id") == "main_repo_graph_resolution_package_adapters_smoke_v1"
        and metrics.get("containerized_smoke_executed") is True
        and metrics.get("rapidfuzz_package_imported") is True
        and metrics.get("rapidfuzz_candidate_count", 0) >= 1
        and metrics.get("rapidfuzz_same_as_candidate_count", 0) >= 1
        and metrics.get("all_candidates_candidate_only") is True
        and metrics.get("no_raw_access_grants") is True
        and metrics.get("no_canonical_writes") is True
        and claims.get("supports_containerized_rapidfuzz_adapter_smoke_claim") is True
        and claims.get("supports_production_adapter_ready_claim") is False
        and claims.get("supports_canonical_graph_write_claim") is False
    )


def containerized_splink_adapter_smoke(report: dict[str, Any]) -> bool:
    metrics = report.get("metrics", {})
    claims = report.get("claim_boundary", {})
    return (
        report.get("artifact_id") == "main_repo_graph_resolution_package_adapters_smoke_v1"
        and metrics.get("containerized_smoke_executed") is True
        and metrics.get("splink_package_imported") is True
        and metrics.get("splink_candidate_count", 0) >= 1
        and metrics.get("splink_same_as_candidate_count", 0) >= 1
        and metrics.get("splink_clerical_review_item_count", 0) >= 1
        and metrics.get("human_clerical_review_queue_exported") is True
        and metrics.get("all_candidates_candidate_only") is True
        and metrics.get("no_raw_access_grants") is True
        and metrics.get("no_canonical_writes") is True
        and claims.get("supports_containerized_splink_adapter_smoke_claim") is True
        and claims.get("supports_production_adapter_ready_claim") is False
        and claims.get("supports_canonical_graph_write_claim") is False
    )


def graph_resolution_package_adapters_smoke_passed(report: dict[str, Any]) -> bool:
    return (
        containerized_rapid_fuzz_adapter_smoke(report)
        and containerized_splink_adapter_smoke(report)
        and report.get("metrics", {}).get("raw_access_expanded") is False
        and report.get("metrics", {}).get("raw_storage_path_exposed") is False
        and not _contains_forbidden_text(report)
    )


def build_report() -> dict[str, Any]:
    try:
        rapid_policy = ResolutionPolicy(
            policy_id="main_repo_rapidfuzz_package_smoke_policy_v1",
            same_as_threshold=0.86,
            clerical_review_min=0.70,
        )
        splink_policy = ResolutionPolicy(
            policy_id="main_repo_splink_package_smoke_policy_v1",
            same_as_threshold=0.84,
            clerical_review_min=0.40,
            model_config={
                "blocking_rules": ["core_supertype"],
                "comparisons": ["label", "city", "project", "tax_id_last4"],
            },
            training_manifest={
                "source": "locked_synthetic_fixture_no_enterprise_quality_claim",
            },
        )
        rapid_left = [
            _record(
                "left_acme_private",
                "Acme Corp",
                owner_user_id="user_finance",
                scope_type="private_user",
                scope_id="user_finance",
            )
        ]
        rapid_right = [_record("right_acme_workspace", "ACME Corporation")]
        splink_left = [
            _record(
                "left_acme_structured",
                "Acme Corp",
                owner_user_id="user_finance",
                scope_type="private_user",
                scope_id="user_finance",
                attributes={"city": "Taipei", "project": "Orion", "tax_id_last4": "4431"},
            ),
            _record(
                "left_delta_structured",
                "Delta Hardware",
                attributes={"city": "Taipei", "project": "Mercury", "tax_id_last4": "1188"},
            ),
        ]
        splink_right = [
            _record(
                "right_acme_structured",
                "ACME Corporation",
                attributes={
                    "city": "Taipei",
                    "project": "Orion Program",
                    "tax_id_last4": "4431",
                },
            ),
            _record(
                "right_delta_uncertain",
                "Delta Hardware",
                attributes={"city": "Taipei", "project": "Orion", "tax_id_last4": "1111"},
            ),
        ]

        rapid_generator = real_rapid_fuzz_package_adapter_binding(policy=rapid_policy)
        splink_generator = real_splink_package_adapter_binding(policy=splink_policy)
        rapid_manifest = rapid_fuzz_package_version_and_manifest_hash_in_main_repo(
            policy=rapid_policy
        )
        splink_manifest = splink_model_config_manifest_bound_to_main_repo(policy=splink_policy)
        rapid_candidates = rapid_generator.candidate_only_output(
            rapid_left,
            rapid_right,
            created_at=CREATED_AT,
        )
        splink_candidates = splink_generator.candidate_only_output(
            splink_left,
            splink_right,
            created_at=CREATED_AT,
        )
        all_candidates = [*rapid_candidates, *splink_candidates]
        splink_queue = build_clerical_review_queue(splink_candidates, policy=splink_policy)
        review_packet = human_clerical_review_queue_export(
            splink_queue,
            reviewer_user_id="reviewer_ops",
            reviewer_visible_record_ids={
                "left_acme_structured",
                "right_acme_structured",
                "left_delta_structured",
                "right_delta_uncertain",
            },
            created_at=CREATED_AT,
        )
        canonical_merge_guard_rejects = _raises_contract_validation(
            lambda: canonical_merge(all_candidates[0])
        )
        raw_asset_read_guard_rejects = _raises_contract_validation(
            lambda: raw_asset_read(all_candidates[0])
        )
        rapid_same_as = [
            candidate for candidate in rapid_candidates if candidate.status == "same_as_candidate"
        ]
        splink_same_as = [
            candidate for candidate in splink_candidates if candidate.status == "same_as_candidate"
        ]
        containerized = os.environ.get("FORMOWL_GRAPH_ADAPTER_SMOKE_CONTAINERIZED") == "1"
        image_reference = os.environ.get("FORMOWL_GRAPH_ADAPTER_SMOKE_IMAGE", "unknown")
        safe_outputs = {
            "rapidfuzz_candidate_statuses": [
                {
                    "fusion_candidate_id": candidate.fusion_candidate_id,
                    "status": candidate.status,
                    "confidence": candidate.confidence,
                }
                for candidate in rapid_candidates
            ],
            "splink_candidate_statuses": [
                {
                    "fusion_candidate_id": candidate.fusion_candidate_id,
                    "status": candidate.status,
                    "confidence": candidate.confidence,
                }
                for candidate in splink_candidates
            ],
            "splink_review_packet_item_count": review_packet["item_count"],
            "splink_review_packet_reviewable_item_count": review_packet["reviewable_item_count"],
        }
        input_manifest = {
            "rapid_left": [record.public_ref(visible=True) for record in rapid_left],
            "rapid_right": [record.public_ref(visible=True) for record in rapid_right],
            "splink_left": [record.public_ref(visible=True) for record in splink_left],
            "splink_right": [record.public_ref(visible=True) for record in splink_right],
        }
        metrics = {
            "containerized_smoke_executed": containerized,
            "rapidfuzz_package_imported": rapid_manifest["package_present"],
            "splink_package_imported": splink_manifest["package_present"],
            "rapidfuzz_candidate_count": len(rapid_candidates),
            "rapidfuzz_same_as_candidate_count": len(rapid_same_as),
            "splink_candidate_count": len(splink_candidates),
            "splink_same_as_candidate_count": len(splink_same_as),
            "splink_clerical_review_item_count": len(splink_queue),
            "human_clerical_review_queue_exported": review_packet["claim_boundary"][
                "supports_human_clerical_review_queue_export_claim"
            ],
            "all_candidates_candidate_only": all(
                candidate.canonical_merge_performed is False for candidate in all_candidates
            ),
            "no_raw_access_grants": all(
                no_raw_access_grant(candidate) for candidate in all_candidates
            ),
            "canonical_merge_guard_rejects": canonical_merge_guard_rejects,
            "raw_asset_read_guard_rejects": raw_asset_read_guard_rejects,
            "no_canonical_writes": True,
            "raw_access_expanded": False,
            "raw_storage_path_exposed": False,
        }
        claim_boundary = {
            "supports_main_repo_graph_resolution_package_adapter_smoke_claim": (
                metrics["containerized_smoke_executed"]
                and metrics["rapidfuzz_package_imported"]
                and metrics["splink_package_imported"]
            ),
            "supports_containerized_rapidfuzz_adapter_smoke_claim": (
                metrics["containerized_smoke_executed"]
                and metrics["rapidfuzz_package_imported"]
                and bool(rapid_candidates)
            ),
            "supports_containerized_splink_adapter_smoke_claim": (
                metrics["containerized_smoke_executed"]
                and metrics["splink_package_imported"]
                and bool(splink_candidates)
            ),
            "supports_fusion_candidate_generation_claim": True,
            "supports_human_clerical_review_queue_export_claim": review_packet["claim_boundary"][
                "supports_human_clerical_review_queue_export_claim"
            ],
            "supports_human_reviewed_false_merge_labels_claim": False,
            "supports_splink_model_quality_claim": False,
            "supports_enterprise_scale_entity_resolution_claim": False,
            "supports_production_adapter_ready_claim": False,
            "supports_end_to_end_gateway_claim": False,
            "supports_canonical_graph_write_claim": False,
            "supports_raw_access_claim": False,
        }
        return {
            "artifact_id": "main_repo_graph_resolution_package_adapters_smoke_v1",
            "run_id": os.environ.get(
                "FORMOWL_GRAPH_ADAPTER_SMOKE_RUN_ID",
                f"main-repo-graph-adapter-smoke-{uuid.uuid4().hex[:12]}",
            ),
            "repo_reference": "main_repo_workspace",
            "repo_path_redacted": True,
            "image_reference": image_reference,
            "runner_script_sha256": sha256_file(Path(__file__)),
            "package_manifests": {
                "rapidfuzz": rapid_manifest,
                "splink": splink_manifest,
            },
            "input_manifest": input_manifest,
            "input_manifest_sha256": sha256_json(input_manifest),
            "output_manifest_sha256": sha256_json(safe_outputs),
            "safe_outputs": safe_outputs,
            "metrics": metrics,
            "claim_boundary": claim_boundary,
            "blockers": [
                "locked synthetic fixture only",
                "human-reviewed false-merge fixture labels are not completed",
                "Splink package import is bound but Splink model quality is not validated",
                "no enterprise-scale entity-resolution quality claim",
                "no end-to-end gateway or canonical graph commit exercise",
            ],
        }
    except Exception as exc:  # pragma: no cover - exercised when dependencies are absent.
        return {
            "artifact_id": "main_repo_graph_resolution_package_adapters_smoke_v1",
            "repo_reference": "main_repo_workspace",
            "repo_path_redacted": True,
            "metrics": {
                "containerized_smoke_executed": (
                    os.environ.get("FORMOWL_GRAPH_ADAPTER_SMOKE_CONTAINERIZED") == "1"
                ),
                "rapidfuzz_package_imported": False,
                "splink_package_imported": False,
                "all_candidates_candidate_only": False,
                "no_raw_access_grants": False,
                "no_canonical_writes": False,
                "raw_access_expanded": False,
                "raw_storage_path_exposed": False,
            },
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "claim_boundary": {
                "supports_main_repo_graph_resolution_package_adapter_smoke_claim": False,
                "supports_containerized_rapidfuzz_adapter_smoke_claim": False,
                "supports_containerized_splink_adapter_smoke_claim": False,
                "supports_fusion_candidate_generation_claim": False,
                "supports_human_clerical_review_queue_export_claim": False,
                "supports_human_reviewed_false_merge_labels_claim": False,
                "supports_splink_model_quality_claim": False,
                "supports_enterprise_scale_entity_resolution_claim": False,
                "supports_production_adapter_ready_claim": False,
                "supports_end_to_end_gateway_claim": False,
                "supports_canonical_graph_write_claim": False,
                "supports_raw_access_claim": False,
            },
            "blockers": ["main-repo graph resolution package adapter smoke failed"],
        }


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    metrics = report.get("metrics", {})
    claims = report.get("claim_boundary", {})

    if report.get("artifact_id") != "main_repo_graph_resolution_package_adapters_smoke_v1":
        blockers.append("unexpected artifact id")
    if report.get("repo_path_redacted") is not True:
        blockers.append("repo path must be redacted")
    for key in [
        "containerized_smoke_executed",
        "rapidfuzz_package_imported",
        "splink_package_imported",
        "all_candidates_candidate_only",
        "no_raw_access_grants",
        "canonical_merge_guard_rejects",
        "raw_asset_read_guard_rejects",
    ]:
        if metrics.get(key) is not True:
            blockers.append(f"required metric failed: {key}")
    for key in [
        "no_canonical_writes",
        "raw_access_expanded",
        "raw_storage_path_exposed",
    ]:
        expected = False if key != "no_canonical_writes" else True
        if metrics.get(key) is not expected:
            blockers.append(f"unexpected safety metric: {key}")
    if metrics.get("rapidfuzz_same_as_candidate_count", 0) < 1:
        blockers.append("RapidFuzz smoke did not emit a same-as candidate")
    if metrics.get("splink_same_as_candidate_count", 0) < 1:
        blockers.append("Splink smoke did not emit a same-as candidate")
    if metrics.get("splink_clerical_review_item_count", 0) < 1:
        blockers.append("Splink smoke did not emit a clerical-review item")
    if claims.get("supports_containerized_rapidfuzz_adapter_smoke_claim") is not True:
        blockers.append("RapidFuzz container smoke claim is not supported")
    if claims.get("supports_containerized_splink_adapter_smoke_claim") is not True:
        blockers.append("Splink container smoke claim is not supported")
    for key in [
        "supports_human_reviewed_false_merge_labels_claim",
        "supports_splink_model_quality_claim",
        "supports_enterprise_scale_entity_resolution_claim",
        "supports_production_adapter_ready_claim",
        "supports_end_to_end_gateway_claim",
        "supports_canonical_graph_write_claim",
        "supports_raw_access_claim",
    ]:
        if claims.get(key) is not False:
            blockers.append(f"forbidden claim true: {key}")
    if _contains_forbidden_text(report):
        blockers.append("public artifact leaks raw paths or SQL")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "metrics": metrics,
        "claim_boundary": claims,
    }


def write_markdown(report: dict[str, Any], validation: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Main-Repo Graph Resolution Package Adapters Smoke",
        "",
        "This validates the optional RapidFuzz and Splink package bindings in the main repo.",
        "It is candidate-only and does not claim production readiness or canonical graph writes.",
        "",
        f"- Passed: {validation['passed']}",
        f"- Artifact: {output_path.name}",
        f"- RapidFuzz version: {report.get('package_manifests', {}).get('rapidfuzz', {}).get('package_version')}",
        f"- Splink version: {report.get('package_manifests', {}).get('splink', {}).get('package_version')}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in sorted(validation["metrics"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Claim Boundary", ""])
    for key, value in sorted(validation["claim_boundary"].items()):
        lines.append(f"- {key}: {value}")
    if validation["blockers"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in validation["blockers"]:
            lines.append(f"- {blocker}")
    output_path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _raises_contract_validation(callable_object: Any) -> bool:
    try:
        callable_object()
    except ContractValidationError:
        return True
    return False


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_forbidden_text(key) or _contains_forbidden_text(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_text(item) for item in value)
    if isinstance(value, str):
        return any(token in value for token in FORBIDDEN_TEXT)
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--from-existing", action="store_true")
    args = parser.parse_args()

    if args.from_existing:
        report = load_report(args.output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = build_report()
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    validation = validate_report(report)
    write_markdown(report, validation, args.output)
    if not validation["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
