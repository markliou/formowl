#!/usr/bin/env python3
"""Fail-closed one-shot executor for the Issue #56 GitHub transfer fixture.

Preflight consumes the source export, source-completeness report, and the
independently sealed oracle-free holdout projection only.  It deliberately does
not open or decode the private transfer manifest.  Execute-once acquires a
persistent O_EXCL consumed claim after preflight and before the first private
manifest read.  A consumed claim is never removed after a crash or failure.

The current ten-case packet is a diagnostic fixture.  A completed execution is
therefore never represented as final transfer acceptance.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
for import_root in (ROOT, PYTHON_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import (  # noqa: E402
    Asset,
    ContractValidationError,
    ExtractorRun,
    Observation,
    SourceInventory,
    assert_no_public_raw_references,
    sha256_json,
    stable_resource_contract_id,
)
from formowl_core import load_issue56_target_mail_tokenizer_profile  # noqa: E402
from formowl_mail.answer import EvidenceAnswerBudget, render_governed_evidence_answer  # noqa: E402
from formowl_mail.hybrid import (  # noqa: E402
    build_authorized_semantic_observation_session,
    build_authorized_source_backed_effective_graph_view,
)
from formowl_mail.query import (  # noqa: E402
    build_authorized_observation_snippet_index,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (  # noqa: E402
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    SemanticPlanLimits,
    validated_authorized_semantic_source,
)
from scripts.issue56_execution_fingerprint import (  # noqa: E402
    build_current_authority_component,
    build_current_code_component,
    build_image_component,
    current_runtime_binding_fingerprints,
)
from scripts.issue56_operational_budget import (  # noqa: E402
    FROZEN_CANONICAL_IMAGE_ID,
    FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
)

SCHEMA_VERSION = 2
REPORT_ARTIFACT_ID = "formowl_issue56_github_transfer_uat_preflight_v2"
REJECTION_ARTIFACT_ID = "formowl_issue56_github_transfer_uat_rejection_v2"
EXECUTION_ARTIFACT_ID = "formowl_issue56_github_transfer_uat_execution_v2"
CONSUMED_CLAIM_ARTIFACT_ID = "formowl_issue56_github_transfer_uat_consumed_claim_v2"
SOURCE_EXPORT_ARTIFACT_ID = "formowl_issue56_github_transfer_source_export_v1"
SOURCE_REPORT_ARTIFACT_ID = "formowl_issue56_github_transfer_source_completeness_report_v1"
HOLDOUT_ARTIFACT_ID = "formowl_issue56_github_transfer_holdout_manifest_v1"
HOLDOUT_REPORT_ARTIFACT_ID = "formowl_issue56_github_transfer_holdout_preflight_v1"
ROUTING_PROFILE_ID = "issue56_github_transfer_source_authored_typed_routing_v1"
ROUTING_CONTRACT_SCHEMA_ID = "formowl_issue56_source_authored_query_route_v1"
ORACLE_FREE_PROJECTION_SCHEMA_ID = "formowl_issue56_github_transfer_oracle_free_projection_v1"
DIAGNOSTIC_CLASSIFICATION = "diagnostic_only_source_authored_transfer_fixture"
DIAGNOSTIC_CLAIM_BOUNDARY = "ten_case_diagnostic_not_final_acceptance"
SOURCE_KIND = GITHUB_PROJECT_OBSERVATION_SOURCE_KIND
SOURCE_GRAPH_POLICY_ID = "source_backed_github_candidate_graph_v1"
SOURCE_NATIVE_RELATION = "source_native_issue_reference"
CO_OCCURRENCE_RELATION = "co_occurs_with"
ONTOLOGY_TARGET = "Artifact"
TRANSFER_EVALUATOR_ID = "issue56_github_transfer_fixture_adjudication_v1"
EXECUTION_BUDGET_POLICY_ID = "issue56_github_transfer_same_pipeline_budget_v1"
EXACT_EXECUTOR_ID = "structured_exact"
ARM_IDS = (
    "strong_rag",
    "rag_entity",
    "rag_candidate_kg",
    "hybrid_v2_soft",
    "legacy_hard_gate",
    "structured_exact",
)
FULL_CASE_ARM_IDS = ARM_IDS[:-1]
STRATA_COUNTS = {
    "cross_issue_relation": 2,
    "direct": 2,
    "exact_count_inventory": 2,
    "no_answer": 1,
    "permission_denied": 1,
    "temporal_status": 2,
}
_ROUTING_INTENT_BY_STRATUM = {
    "direct": "source_native_field_lookup",
    "cross_issue_relation": "source_native_relation_path",
    "temporal_status": "source_native_temporal_state",
    "exact_count_inventory": "complete_source_inventory",
    "no_answer": "complete_scope_absence_lookup",
    "permission_denied": "permission_boundary_lookup",
}
_QUERY_CLASS_BY_ROUTING_INTENT = {
    "source_native_field_lookup": "evidence_lookup",
    "source_native_relation_path": "relation_reasoning",
    "source_native_temporal_state": "relation_reasoning",
    "complete_source_inventory": "exact_set_or_inventory",
    "complete_scope_absence_lookup": "evidence_lookup",
    "permission_boundary_lookup": "evidence_lookup",
}
_EXPECTED_QUERY_CLASS_COUNTS = dict(
    sorted(
        Counter(
            {
                query_class: sum(
                    STRATA_COUNTS[stratum]
                    for stratum, intent in _ROUTING_INTENT_BY_STRATUM.items()
                    if _QUERY_CLASS_BY_ROUTING_INTENT[intent] == query_class
                )
                for query_class in set(_QUERY_CLASS_BY_ROUTING_INTENT.values())
            }
        ).items()
    )
)
_EXPECTED_ROUTING_PROFILE = {
    "profile_id": ROUTING_PROFILE_ID,
    "schema_version": 1,
    "source_family": "github_project_issue_comment",
    "classifier_kind": "source_authored_typed_intent_router",
    "typed_input_schema": {
        "field": "authored_intent_kind",
        "allowed_values": sorted(_QUERY_CLASS_BY_ROUTING_INTENT),
    },
    "query_class_by_authored_intent": dict(sorted(_QUERY_CLASS_BY_ROUTING_INTENT.items())),
    "stratum_to_authored_intent": dict(sorted(_ROUTING_INTENT_BY_STRATUM.items())),
    "query_text_inference_authoritative": False,
    "query_text_mutation_allowed": False,
    "runtime_parameter_tuning_allowed": False,
}
ROUTING_PROFILE_FINGERPRINT = sha256_json(_EXPECTED_ROUTING_PROFILE)
ROUTING_CONTRACT_SCHEMA_FINGERPRINT = sha256_json(ROUTING_CONTRACT_SCHEMA_ID)
SHARED_FINGERPRINT_FIELDS = (
    "source_binding_fingerprint",
    "manifest_projection_fingerprint",
    "manifest_route_projection_fingerprint",
    "routing_profile_fingerprint",
    "routing_binding_set_fingerprint",
    "routing_contract_schema_fingerprint",
    "identity_scope_fingerprint",
    "segmentation_profile_fingerprint",
    "index_fingerprint",
    "dense_model_fingerprint",
    "graph_fingerprint",
    "ontology_fingerprint",
    "method_fingerprint",
    "answer_model_fingerprint",
    "answer_prompt_fingerprint",
    "evaluator_fingerprint",
    "budget_fingerprint",
    "code_fingerprint",
    "image_fingerprint",
    "authority_fingerprint",
)
DEFAULT_ARTIFACT_ROOT = ROOT / ".test-tmp" / "issue56-transfer-github-project-v1"
MAX_PRIVATE_BYTES = 4 * 1024 * 1024
MAX_SAFE_BYTES = 512 * 1024
_SHA256_LENGTH = 71
_PRIVATE_ORACLE_KEYS = frozenset({"private_query", "expected_private"})
_SUPPORTED_AUTHORED_QUERY_CLASSES = frozenset(
    {"evidence_lookup", "relation_reasoning", "exact_set_or_inventory"}
)


class TransferUatValidationError(RuntimeError):
    """One stable fail-closed validation reason."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _PreparedTransferExecution:
    report: dict[str, Any]
    source_export: dict[str, Any]
    source_export_sha256: str
    source_report_sha256: str
    oracle_free_projection: dict[str, Any]
    oracle_free_projection_sha256: str
    observations: tuple[Observation, ...]
    observation_hash_by_id: dict[str, str]
    session: Any
    graph_build: Any
    runtime_binding: dict[str, Any]


@dataclass(frozen=True)
class _ConsumedClaimReceipt:
    path: Path
    payload: dict[str, Any]
    byte_sha256: str
    claim_fingerprint: str
    output_binding_fingerprint: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute-once", action="store_true")
    parser.add_argument(
        "--source-export",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "source-export.private.json",
    )
    parser.add_argument("--expected-source-export-sha256", required=True)
    parser.add_argument(
        "--source-completeness-report",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "source-completeness.safe.json",
    )
    parser.add_argument("--expected-source-completeness-sha256", required=True)
    parser.add_argument(
        "--holdout-manifest",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "transfer-holdout-manifest.private.json",
    )
    parser.add_argument("--expected-holdout-manifest-sha256", required=True)
    parser.add_argument(
        "--holdout-oracle-free-projection",
        "--holdout-preflight-report",
        dest="holdout_oracle_free_projection",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "transfer-holdout-preflight.safe.json",
    )
    parser.add_argument(
        "--expected-holdout-oracle-free-projection-sha256",
        "--expected-holdout-preflight-sha256",
        dest="expected_holdout_oracle_free_projection_sha256",
        required=True,
    )
    parser.add_argument("--expected-runtime-fingerprint")
    parser.add_argument("--execution-output", type=Path)
    parser.add_argument("--expected-image-id", default=FROZEN_CANONICAL_IMAGE_ID)
    parser.add_argument(
        "--expected-image-metadata-fingerprint",
        default=FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.execute_once:
        if args.expected_runtime_fingerprint is None or args.execution_output is None:
            parser.error(
                "--expected-runtime-fingerprint and --execution-output are required "
                "with --execute-once"
            )
    elif args.expected_runtime_fingerprint is not None or args.execution_output is not None:
        parser.error("runtime fingerprint and execution output are execute-once only")
    kwargs = {
        "source_export_path": args.source_export,
        "expected_source_export_sha256": args.expected_source_export_sha256,
        "source_report_path": args.source_completeness_report,
        "expected_source_report_sha256": args.expected_source_completeness_sha256,
        "holdout_manifest_path": args.holdout_manifest,
        "expected_holdout_manifest_sha256": args.expected_holdout_manifest_sha256,
        "holdout_report_path": args.holdout_oracle_free_projection,
        "expected_holdout_report_sha256": (args.expected_holdout_oracle_free_projection_sha256),
        "expected_image_id": args.expected_image_id,
        "expected_image_metadata_fingerprint": args.expected_image_metadata_fingerprint,
    }
    try:
        if args.preflight_only:
            report = build_transfer_uat_preflight(**kwargs)
        else:
            report = execute_transfer_uat_once(
                **kwargs,
                expected_runtime_fingerprint=args.expected_runtime_fingerprint,
                execution_output=args.execution_output,
            )
    except (
        ContractValidationError,
        TransferUatValidationError,
        RuntimeError,
    ) as exc:
        reason_code = str(getattr(exc, "reason_code", str(exc)))
        report = _rejection_report(reason_code)
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 3
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    if args.preflight_only:
        return 0 if report.get("preflight_status") == "passed" else 2
    return 0 if report.get("execution_status") == "passed" else 2


def build_transfer_uat_preflight(
    *,
    source_export_path: Path,
    expected_source_export_sha256: str,
    source_report_path: Path,
    expected_source_report_sha256: str,
    holdout_manifest_path: Path,
    expected_holdout_manifest_sha256: str,
    holdout_report_path: Path,
    expected_holdout_report_sha256: str,
    expected_image_id: str = FROZEN_CANONICAL_IMAGE_ID,
    expected_image_metadata_fingerprint: str = FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    execute_once: bool = False,
    runtime_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Run oracle-free preflight; ``holdout_manifest_path`` is not opened."""

    if execute_once or runtime_fingerprint is not None:
        raise TransferUatValidationError("preflight_execution_arguments_not_allowed")
    prepared = _prepare_transfer_execution(
        source_export_path=source_export_path,
        expected_source_export_sha256=expected_source_export_sha256,
        source_report_path=source_report_path,
        expected_source_report_sha256=expected_source_report_sha256,
        holdout_manifest_path=holdout_manifest_path,
        expected_holdout_manifest_sha256=expected_holdout_manifest_sha256,
        holdout_report_path=holdout_report_path,
        expected_holdout_report_sha256=expected_holdout_report_sha256,
        expected_image_id=expected_image_id,
        expected_image_metadata_fingerprint=expected_image_metadata_fingerprint,
    )
    return prepared.report


def execute_transfer_uat_once(
    *,
    source_export_path: Path,
    expected_source_export_sha256: str,
    source_report_path: Path,
    expected_source_report_sha256: str,
    holdout_manifest_path: Path,
    expected_holdout_manifest_sha256: str,
    holdout_report_path: Path,
    expected_holdout_report_sha256: str,
    expected_runtime_fingerprint: str,
    execution_output: Path,
    expected_image_id: str = FROZEN_CANONICAL_IMAGE_ID,
    expected_image_metadata_fingerprint: str = FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    _after_claim_hook: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Execute exactly once after the persistent consumed claim is acquired."""

    _require_sha256(
        expected_runtime_fingerprint,
        "transfer_expected_runtime_fingerprint_invalid",
    )
    prepared = _prepare_transfer_execution(
        source_export_path=source_export_path,
        expected_source_export_sha256=expected_source_export_sha256,
        source_report_path=source_report_path,
        expected_source_report_sha256=expected_source_report_sha256,
        holdout_manifest_path=holdout_manifest_path,
        expected_holdout_manifest_sha256=expected_holdout_manifest_sha256,
        holdout_report_path=holdout_report_path,
        expected_holdout_report_sha256=expected_holdout_report_sha256,
        expected_image_id=expected_image_id,
        expected_image_metadata_fingerprint=expected_image_metadata_fingerprint,
    )
    if prepared.runtime_binding["runtime_fingerprint"] != expected_runtime_fingerprint:
        raise TransferUatValidationError("transfer_runtime_fingerprint_mismatch")
    claim = _acquire_consumed_claim(
        preflight_report=prepared.report,
        runtime_binding=prepared.runtime_binding,
        expected_manifest_sha256=expected_holdout_manifest_sha256,
        execution_output=execution_output,
    )
    if _after_claim_hook is not None:
        _after_claim_hook()
    manifest = _decode_private_transfer_manifest_after_claim(
        manifest_path=holdout_manifest_path,
        expected_manifest_sha256=expected_holdout_manifest_sha256,
        source_export=prepared.source_export,
        source_export_sha256=prepared.source_export_sha256,
        oracle_free_projection=prepared.oracle_free_projection,
    )
    report = _execute_transfer_cases(
        prepared=prepared,
        manifest=manifest,
        consumed_claim=claim,
    )
    _validate_consumed_claim_receipt(claim)
    output_sha256 = _publish_immutable_json(execution_output, report)
    _validate_published_execution_output(
        execution_output,
        expected_report=report,
        expected_sha256=output_sha256,
    )
    return report


def _prepare_transfer_execution(
    *,
    source_export_path: Path,
    expected_source_export_sha256: str,
    source_report_path: Path,
    expected_source_report_sha256: str,
    holdout_manifest_path: Path,
    expected_holdout_manifest_sha256: str,
    holdout_report_path: Path,
    expected_holdout_report_sha256: str,
    expected_image_id: str,
    expected_image_metadata_fingerprint: str,
) -> _PreparedTransferExecution:
    """Build all source/runtime state without touching the private manifest."""

    del holdout_manifest_path  # Explicit oracle-free preflight boundary.
    source_export_bytes, source_export = _read_sealed_json(
        source_export_path,
        expected_source_export_sha256,
        max_bytes=MAX_PRIVATE_BYTES,
        invalid_reason="source_export_missing_or_invalid",
        seal_reason="source_export_seal_mismatch",
    )
    source_report_bytes, source_report = _read_sealed_json(
        source_report_path,
        expected_source_report_sha256,
        max_bytes=MAX_SAFE_BYTES,
        invalid_reason="source_report_missing_or_invalid",
        seal_reason="source_report_seal_mismatch",
    )
    projection_bytes, projection = _read_sealed_json(
        holdout_report_path,
        expected_holdout_report_sha256,
        max_bytes=MAX_SAFE_BYTES,
        invalid_reason="holdout_projection_missing_or_invalid",
        seal_reason="holdout_projection_seal_mismatch",
    )
    source_export_sha256 = _sha256_bytes(source_export_bytes)
    source_report_sha256 = _sha256_bytes(source_report_bytes)
    projection_sha256 = _sha256_bytes(projection_bytes)
    source_lineage = _validate_source_export(
        source_export,
        source_export_sha256=source_export_sha256,
    )
    _validate_source_report(
        source_report,
        source_export=source_export,
        source_export_sha256=source_export_sha256,
    )
    projection_lineage = _validate_holdout_oracle_free_projection(
        projection,
        projection_sha256=projection_sha256,
        expected_manifest_sha256=expected_holdout_manifest_sha256,
        source_export=source_export,
        source_export_sha256=source_export_sha256,
    )

    observations = tuple(
        Observation.from_dict(dict(value)) for value in source_export["observations"]
    )
    observation_hash_by_id = {
        observation.observation_id: sha256_json(observation.to_dict())
        for observation in observations
    }
    asset = Asset.from_dict(dict(source_export["asset"]))
    if not asset.project_id:
        raise TransferUatValidationError("github_source_project_scope_missing")
    authorized_source = validated_authorized_semantic_source(
        source_kind=SOURCE_KIND,
        workspace_id=asset.workspace_id,
        source_scope_ids=(asset.project_id,),
    )
    lineages = tuple(
        source_occurrence_lineage_from_observation(
            observation,
            authorized_source=authorized_source,
        )
        for observation in observations
    )
    tokenizer_profile = load_issue56_target_mail_tokenizer_profile()
    snippet_index, index_manifest = build_authorized_observation_snippet_index(
        observations,
        authorized_source=authorized_source,
        occurrence_lineages=lineages,
        authorized_observation_hash_by_id=observation_hash_by_id,
        tokenizer_profile=tokenizer_profile,
    )
    session = build_authorized_semantic_observation_session(
        authorized_source=authorized_source,
        snippet_index=snippet_index,
        authorized_observations=observations,
        occurrence_lineages=lineages,
        requester_user_id=asset.owner_user_id,
        expected_profile_fingerprint=tokenizer_profile.profile_fingerprint,
    )
    source_binding_fingerprint = sha256_json(
        {
            "source_export_sha256": source_export_sha256,
            "source_report_sha256": source_report_sha256,
            "source_snapshot_fingerprint": source_export["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": sha256_json(source_export["source_inventory"]),
            "observation_snapshot_fingerprint": sha256_json(source_export["observations"]),
            "lineage_fingerprint": source_export["lineage_fingerprint"],
            "source_occurrence_schema_fingerprint": source_export[
                "source_occurrence_schema_fingerprint"
            ],
        }
    )
    graph_build = build_authorized_source_backed_effective_graph_view(
        session=session,
        source_binding_fingerprint=source_binding_fingerprint,
        source_graph_policy_id=SOURCE_GRAPH_POLICY_ID,
    )
    graph_safe = graph_build.to_safe_dict()
    expected_relation_hashes = sorted(
        (sha256_json(CO_OCCURRENCE_RELATION), sha256_json(SOURCE_NATIVE_RELATION))
    )
    if (
        graph_safe.get("graph_policy_id") != SOURCE_GRAPH_POLICY_ID
        or graph_safe.get("candidate_graph_only") is not True
        or graph_safe.get("human_review_complete") is not False
        or graph_safe.get("relation_type_hashes") != expected_relation_hashes
        or graph_build.source_observation_count != len(observations)
    ):
        raise TransferUatValidationError("github_source_graph_binding_invalid")

    runtime = current_runtime_binding_fingerprints()
    evaluator_fingerprint = sha256_json(
        {
            "evaluator_id": TRANSFER_EVALUATOR_ID,
            "case_count": projection_lineage["case_count"],
            "strata_counts": STRATA_COUNTS,
            "query_class_counts": projection_lineage["query_class_counts"],
            "routing_profile_fingerprint": projection_lineage["routing_profile_fingerprint"],
            "routing_binding_set_fingerprint": projection_lineage[
                "routing_binding_set_fingerprint"
            ],
            "manifest_route_projection_fingerprint": projection_lineage[
                "manifest_route_projection_fingerprint"
            ],
            "fixture_only": True,
        }
    )
    execution_contract = _execution_contract()
    base_pins = {
        "source_binding_fingerprint": source_binding_fingerprint,
        "source_export_sha256": source_export_sha256,
        "source_completeness_report_sha256": source_report_sha256,
        "manifest_projection_sha256": projection_sha256,
        "manifest_projection_fingerprint": projection["report_fingerprint"],
        "manifest_route_projection_fingerprint": projection_lineage[
            "manifest_route_projection_fingerprint"
        ],
        "manifest_sha256": expected_holdout_manifest_sha256,
        "manifest_fingerprint": projection["hashes"]["private_holdout_fingerprint"],
        "routing_profile_fingerprint": projection_lineage["routing_profile_fingerprint"],
        "routing_binding_set_fingerprint": projection_lineage["routing_binding_set_fingerprint"],
        "routing_contract_schema_fingerprint": ROUTING_CONTRACT_SCHEMA_FINGERPRINT,
        "source_kind_fingerprint": sha256_json(SOURCE_KIND),
        "identity_scope_fingerprint": authorized_source.authorization_fingerprint,
        "segmentation_profile_fingerprint": tokenizer_profile.profile_fingerprint,
        "index_fingerprint": session.index.index_fingerprint,
        "dense_model_fingerprint": runtime["dense_profile_fingerprint"],
        "runtime_component_fingerprint": session.index.execution_component_fingerprint,
        "graph_fingerprint": graph_build.build_fingerprint,
        "graph_revision_fingerprint": graph_build.graph_revision_fingerprint,
        "graph_relation_set_fingerprint": sha256_json(expected_relation_hashes),
        "ontology_fingerprint": sha256_json(
            {
                "target": ONTOLOGY_TARGET,
                "revision": graph_build.effective_graph_view.ontology_revision_id,
            }
        ),
        "method_fingerprint": runtime["runtime_method_fingerprint"],
        "answer_model_fingerprint": runtime["answer_model_fingerprint"],
        "answer_prompt_fingerprint": runtime["answer_prompt_fingerprint"],
        "answer_budget_fingerprint": runtime["answer_budget_fingerprint"],
        "evaluator_fingerprint": evaluator_fingerprint,
        "execution_contract_fingerprint": sha256_json(execution_contract),
        "index_manifest_fingerprint": sha256_json(index_manifest.to_safe_dict()),
    }
    base_run_binding_fingerprint = sha256_json(base_pins)
    components = _build_environment_components(
        run_binding_fingerprint=base_run_binding_fingerprint,
        expected_image_id=expected_image_id,
        expected_image_metadata_fingerprint=expected_image_metadata_fingerprint,
    )
    runtime_binding = {
        **base_pins,
        "base_run_binding_fingerprint": base_run_binding_fingerprint,
        "code_fingerprint": components["code_component"]["artifact_fingerprint"],
        "code_tree_fingerprint": components["code_component"]["code_tree_fingerprint"],
        "image_fingerprint": components["image_component"]["artifact_fingerprint"],
        "image_id": components["image_component"]["image_id"],
        "image_metadata_fingerprint": components["image_component"]["image_metadata_fingerprint"],
        "authority_fingerprint": components["authority_component"]["artifact_fingerprint"],
        "authority_state_fingerprint": components["authority_component"][
            "authority_state_fingerprint"
        ],
        "authority_execution_fingerprint": components["authority_component"][
            "authority_execution_fingerprint"
        ],
        "authority_blocking_gate_set_fingerprint": components["authority_component"][
            "blocking_gate_set_fingerprint"
        ],
        "authority_status": components["authority_component"]["status"],
    }
    runtime_binding["runtime_fingerprint"] = sha256_json(runtime_binding)
    shared = _shared_arm_fingerprints(runtime_binding)
    validate_shared_arm_fingerprints({arm_id: shared for arm_id in ARM_IDS})

    report: dict[str, Any] = {
        "artifact_id": REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "preflight_status": "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "oracle_access_status": "not_read",
        "claim_boundary_status": "ten_case_fixture_not_final_acceptance",
        "final_acceptance_eligible": False,
        "source_kind_status": "passed",
        "permission_pre_filter_status": "passed",
        "reference_relation_status": "passed",
        "routing_contract_status": "passed",
        "runtime_freeze_status": "ready_for_expected_fingerprint_match",
        "counts": {
            "artifact_seal_count": 3,
            "source_record_count": source_lineage["source_record_count"],
            "source_observation_count": source_lineage["source_observation_count"],
            "case_count": projection_lineage["case_count"],
            "arm_count": len(ARM_IDS),
            "full_case_arm_count": len(FULL_CASE_ARM_IDS),
            "exact_executor_count": 1,
            "sealed_quality_field_read_count": 0,
            "executed_case_count": 0,
            "graph_node_count": len(graph_build.effective_graph_view.visible_nodes),
            "graph_edge_count": len(graph_build.effective_graph_view.visible_edges),
            "blocker_count": 0,
        },
        "strata_counts": dict(projection_lineage["strata_counts"]),
        "query_class_counts": dict(projection_lineage["query_class_counts"]),
        "hashes": {
            "source_export_sha256": source_export_sha256,
            "source_completeness_report_sha256": source_report_sha256,
            "manifest_projection_sha256": projection_sha256,
            "source_binding_fingerprint": source_binding_fingerprint,
            "manifest_projection_fingerprint": projection["report_fingerprint"],
            "manifest_route_projection_fingerprint": projection_lineage[
                "manifest_route_projection_fingerprint"
            ],
            "manifest_fingerprint": projection["hashes"]["private_holdout_fingerprint"],
            "manifest_sha256": expected_holdout_manifest_sha256,
            "routing_profile_fingerprint": projection_lineage["routing_profile_fingerprint"],
            "routing_binding_set_fingerprint": projection_lineage[
                "routing_binding_set_fingerprint"
            ],
            "routing_contract_schema_fingerprint": ROUTING_CONTRACT_SCHEMA_FINGERPRINT,
            "identity_scope_fingerprint": authorized_source.authorization_fingerprint,
            "segmentation_profile_fingerprint": tokenizer_profile.profile_fingerprint,
            "index_fingerprint": session.index.index_fingerprint,
            "graph_fingerprint": graph_build.build_fingerprint,
            "graph_revision_fingerprint": graph_build.graph_revision_fingerprint,
            "graph_relation_set_fingerprint": sha256_json(expected_relation_hashes),
            "method_fingerprint": runtime["runtime_method_fingerprint"],
            "answer_model_fingerprint": runtime["answer_model_fingerprint"],
            "answer_prompt_fingerprint": runtime["answer_prompt_fingerprint"],
            "evaluator_fingerprint": evaluator_fingerprint,
            "budget_fingerprint": sha256_json(EXECUTION_BUDGET_POLICY_ID),
            "code_fingerprint": runtime_binding["code_fingerprint"],
            "image_fingerprint": runtime_binding["image_fingerprint"],
            "authority_fingerprint": runtime_binding["authority_fingerprint"],
            "runtime_fingerprint": runtime_binding["runtime_fingerprint"],
        },
    }
    report["hashes"]["preflight_input_fingerprint"] = sha256_json(
        {
            "source_export_sha256": source_export_sha256,
            "source_report_sha256": source_report_sha256,
            "projection_sha256": projection_sha256,
            "manifest_sha256": expected_holdout_manifest_sha256,
            "manifest_route_projection_fingerprint": projection_lineage[
                "manifest_route_projection_fingerprint"
            ],
            "routing_profile_fingerprint": projection_lineage["routing_profile_fingerprint"],
            "routing_binding_set_fingerprint": projection_lineage[
                "routing_binding_set_fingerprint"
            ],
            "runtime_fingerprint": runtime_binding["runtime_fingerprint"],
        }
    )
    report["hashes"]["report_fingerprint"] = _report_fingerprint(report)
    _validate_public_report(report, artifact_id=REPORT_ARTIFACT_ID)
    return _PreparedTransferExecution(
        report=report,
        source_export=source_export,
        source_export_sha256=source_export_sha256,
        source_report_sha256=source_report_sha256,
        oracle_free_projection=projection,
        oracle_free_projection_sha256=projection_sha256,
        observations=observations,
        observation_hash_by_id=observation_hash_by_id,
        session=session,
        graph_build=graph_build,
        runtime_binding=runtime_binding,
    )


def _build_environment_components(
    *,
    run_binding_fingerprint: str,
    expected_image_id: str,
    expected_image_metadata_fingerprint: str,
) -> dict[str, dict[str, Any]]:
    return {
        "code_component": build_current_code_component(
            repository_root=ROOT,
            run_binding_fingerprint=run_binding_fingerprint,
        ),
        "image_component": build_image_component(
            run_binding_fingerprint=run_binding_fingerprint,
            image_id=expected_image_id,
            image_metadata_fingerprint=expected_image_metadata_fingerprint,
        ),
        "authority_component": build_current_authority_component(
            repository_root=ROOT,
            run_binding_fingerprint=run_binding_fingerprint,
        ),
    }


def _execution_contract() -> dict[str, Any]:
    return {
        "source_kind": SOURCE_KIND,
        "source_graph_policy_id": SOURCE_GRAPH_POLICY_ID,
        "relation_types": [CO_OCCURRENCE_RELATION, SOURCE_NATIVE_RELATION],
        "routing_profile_id": ROUTING_PROFILE_ID,
        "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
        "routing_contract_schema_id": ROUTING_CONTRACT_SCHEMA_ID,
        "routing_contract_schema_fingerprint": ROUTING_CONTRACT_SCHEMA_FINGERPRINT,
        "routing_authority": "sealed_source_authored_typed_intent",
        "query_text_inference_authoritative": False,
        "arm_ids": list(ARM_IDS),
        "full_case_arm_ids": list(FULL_CASE_ARM_IDS),
        "exact_executor_id": EXACT_EXECUTOR_ID,
        "budget_policy_id": EXECUTION_BUDGET_POLICY_ID,
        "permission_policy": "filter_before_index_graph_and_answer",
        "graph_hop_policy": "every_hop_requires_authorized_observation",
        "oracle_access": "after_persistent_consumed_claim_only",
        "retry_policy": "one_shot_no_retry",
        "output_policy": "atomic_immutable_public_safe",
        "fixture_case_count": sum(STRATA_COUNTS.values()),
        "final_acceptance_eligible": False,
    }


def _shared_arm_fingerprints(runtime_binding: Mapping[str, Any]) -> dict[str, str]:
    mapping = {
        "source_binding_fingerprint": runtime_binding["source_binding_fingerprint"],
        "manifest_projection_fingerprint": runtime_binding["manifest_projection_fingerprint"],
        "manifest_route_projection_fingerprint": runtime_binding[
            "manifest_route_projection_fingerprint"
        ],
        "routing_profile_fingerprint": runtime_binding["routing_profile_fingerprint"],
        "routing_binding_set_fingerprint": runtime_binding["routing_binding_set_fingerprint"],
        "routing_contract_schema_fingerprint": runtime_binding[
            "routing_contract_schema_fingerprint"
        ],
        "identity_scope_fingerprint": runtime_binding["identity_scope_fingerprint"],
        "segmentation_profile_fingerprint": runtime_binding["segmentation_profile_fingerprint"],
        "index_fingerprint": runtime_binding["index_fingerprint"],
        "dense_model_fingerprint": runtime_binding["dense_model_fingerprint"],
        "graph_fingerprint": runtime_binding["graph_fingerprint"],
        "ontology_fingerprint": runtime_binding["ontology_fingerprint"],
        "method_fingerprint": runtime_binding["method_fingerprint"],
        "answer_model_fingerprint": runtime_binding["answer_model_fingerprint"],
        "answer_prompt_fingerprint": runtime_binding["answer_prompt_fingerprint"],
        "evaluator_fingerprint": runtime_binding["evaluator_fingerprint"],
        "budget_fingerprint": sha256_json(EXECUTION_BUDGET_POLICY_ID),
        "code_fingerprint": runtime_binding["code_fingerprint"],
        "image_fingerprint": runtime_binding["image_fingerprint"],
        "authority_fingerprint": runtime_binding["authority_fingerprint"],
    }
    return {
        key: _require_sha256(value, "transfer_shared_fingerprint_missing_or_invalid")
        for key, value in mapping.items()
    }


def validate_shared_arm_fingerprints(
    arm_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """Require one identical source/runtime binding for all six arms."""

    if set(arm_bindings) != set(ARM_IDS):
        raise TransferUatValidationError("transfer_arm_set_mismatch")
    shared: dict[str, str] = {}
    for field_name in SHARED_FINGERPRINT_FIELDS:
        values = {
            _require_sha256(
                binding.get(field_name),
                "transfer_shared_fingerprint_missing_or_invalid",
            )
            for binding in arm_bindings.values()
        }
        if len(values) != 1:
            raise TransferUatValidationError("transfer_shared_fingerprint_mismatch")
        shared[field_name] = next(iter(values))
    return shared


def validate_execution_metrics(
    *,
    case_count: int,
    permission_leakage_count: int,
    graph_hops: Sequence[Mapping[str, Any]],
    authorized_observation_hashes: Sequence[str],
) -> dict[str, int]:
    """Validate execution-only authorization and hop-lineage metrics."""

    if not isinstance(case_count, int) or isinstance(case_count, bool) or case_count < 1:
        raise TransferUatValidationError("transfer_execution_case_count_invalid")
    if permission_leakage_count != 0:
        raise TransferUatValidationError("transfer_permission_leakage_detected")
    authorized = set(authorized_observation_hashes)
    if not authorized or any(not _is_sha256(value) for value in authorized):
        raise TransferUatValidationError("transfer_authorized_observation_hash_set_invalid")
    hop_count = 0
    citation_count = 0
    for hop in graph_hops:
        citations = hop.get("cited_observation_hashes") if isinstance(hop, Mapping) else None
        if not isinstance(citations, (list, tuple)) or not citations:
            raise TransferUatValidationError("transfer_graph_hop_authorized_lineage_missing")
        if any(value not in authorized for value in citations):
            raise TransferUatValidationError("transfer_graph_hop_authorized_lineage_missing")
        hop_count += 1
        citation_count += len(citations)
    return {
        "case_count": case_count,
        "permission_leakage_count": permission_leakage_count,
        "authorized_graph_hop_count": hop_count,
        "authorized_graph_hop_citation_count": citation_count,
    }


def _decode_private_transfer_manifest_after_claim(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    source_export: Mapping[str, Any],
    source_export_sha256: str,
    oracle_free_projection: Mapping[str, Any],
) -> dict[str, Any]:
    _payload, manifest = _read_sealed_json(
        manifest_path,
        expected_manifest_sha256,
        max_bytes=MAX_PRIVATE_BYTES,
        invalid_reason="holdout_manifest_missing_or_invalid_after_claim",
        seal_reason="holdout_manifest_seal_mismatch_after_claim",
    )
    lineage = _validate_holdout_manifest_execution_projection(
        manifest,
        private_export=source_export,
        private_export_sha256=source_export_sha256,
    )
    hashes = oracle_free_projection.get("hashes")
    safe_manifest_projection = oracle_free_projection.get("manifest_projection")
    if (
        not isinstance(hashes, Mapping)
        or not isinstance(safe_manifest_projection, Mapping)
        or hashes.get("private_holdout_sha256") != expected_manifest_sha256
        or hashes.get("private_holdout_fingerprint") != manifest.get("manifest_fingerprint")
        or oracle_free_projection.get("counts", {}).get("case_count") != lineage["case_count"]
        or oracle_free_projection.get("strata_counts") != lineage["strata_counts"]
        or oracle_free_projection.get("query_class_counts") != lineage["query_class_counts"]
        or hashes.get("routing_profile_fingerprint") != lineage["routing_profile_fingerprint"]
        or hashes.get("routing_binding_set_fingerprint")
        != lineage["routing_binding_set_fingerprint"]
        or hashes.get("manifest_projection_fingerprint")
        != lineage["manifest_route_projection_fingerprint"]
        or dict(safe_manifest_projection) != lineage["manifest_projection"]
    ):
        raise TransferUatValidationError("holdout_private_projection_cross_binding_mismatch")
    return manifest


def _execute_transfer_cases(
    *,
    prepared: _PreparedTransferExecution,
    manifest: Mapping[str, Any],
    consumed_claim: _ConsumedClaimReceipt,
) -> dict[str, Any]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != sum(STRATA_COUNTS.values()):
        raise TransferUatValidationError("holdout_case_count_mismatch")
    rows_by_arm: dict[str, list[dict[str, Any]]] = {arm_id: [] for arm_id in ARM_IDS}
    graph_hops: list[dict[str, Any]] = []
    authorized_hashes = set(prepared.observation_hash_by_id.values())
    permission_leakage_count = 0
    budget = EvidenceAnswerBudget()
    for case in cases:
        if case.get("stratum") == "permission_denied":
            for arm_id in FULL_CASE_ARM_IDS:
                rows_by_arm[arm_id].append(_permission_denied_row(case, arm_id=arm_id))
            continue
        query_text, query_class = _validated_case_query(case)
        for arm_id, result, elapsed_ms, budget_fingerprint in _run_case_arms(
            session=prepared.session,
            effective_graph_view=prepared.graph_build.effective_graph_view,
            query_text=query_text,
            query_class=query_class,
        ):
            answer = render_governed_evidence_answer(result, budget=budget)
            row = _score_case(
                case,
                arm_id=arm_id,
                result=result,
                answer_status=answer.status,
                answer_citation_hashes=answer.citation_hashes,
                answer_hash=answer.answer_hash,
                answer_cost_units=answer.cost_units,
                elapsed_ms=elapsed_ms,
                budget_fingerprint=budget_fingerprint,
                observation_hash_by_id=prepared.observation_hash_by_id,
            )
            rows_by_arm[arm_id].append(row)
            if row["permission_leakage"]:
                permission_leakage_count += 1
            for path in getattr(result, "graph_paths", ()):
                for hop in path.hops:
                    graph_hops.append(
                        {"cited_observation_hashes": list(hop.cited_observation_hashes)}
                    )
    metrics = validate_execution_metrics(
        case_count=len(cases),
        permission_leakage_count=permission_leakage_count,
        graph_hops=graph_hops,
        authorized_observation_hashes=tuple(sorted(authorized_hashes)),
    )
    shared = _shared_arm_fingerprints(prepared.runtime_binding)
    shared_by_arm = {arm_id: dict(shared) for arm_id in ARM_IDS}
    validate_shared_arm_fingerprints(shared_by_arm)
    arm_summaries = {arm_id: _aggregate_arm(rows_by_arm[arm_id]) for arm_id in ARM_IDS}
    execution_row_set_fingerprint = sha256_json(
        {
            arm_id: [
                {
                    "case_fingerprint": row["case_fingerprint"],
                    "routing_contract_fingerprint": row["routing_contract_fingerprint"],
                    "status": row["status"],
                    "answer_hash": row["answer_hash"],
                    "citation_count": row["citation_count"],
                }
                for row in rows_by_arm[arm_id]
            ]
            for arm_id in ARM_IDS
        }
    )
    report: dict[str, Any] = {
        "artifact_id": EXECUTION_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "preflight_status": "passed",
        "execution_status": "passed",
        "quality_result_status": "diagnostic_only",
        "claim_boundary_status": "ten_case_fixture_not_final_acceptance",
        "final_acceptance_status": "blocked",
        "final_acceptance_eligible": False,
        "retry_policy": "consumed_no_retry",
        "counts": {
            "case_count": len(cases),
            "arm_count": len(ARM_IDS),
            "full_case_arm_count": len(FULL_CASE_ARM_IDS),
            "executed_full_case_arm_row_count": sum(
                len(rows_by_arm[arm_id]) for arm_id in FULL_CASE_ARM_IDS
            ),
            "executed_exact_case_count": len(rows_by_arm["structured_exact"]),
            "permission_leakage_count": metrics["permission_leakage_count"],
            "authorized_graph_hop_count": metrics["authorized_graph_hop_count"],
            "authorized_graph_hop_citation_count": metrics["authorized_graph_hop_citation_count"],
            "sealed_quality_field_read_count": len(cases),
            "blocker_count": 1,
        },
        "strata_counts": dict(STRATA_COUNTS),
        "query_class_counts": dict(_EXPECTED_QUERY_CLASS_COUNTS),
        "arms": arm_summaries,
        "runtime_binding": {
            "shared_arm_fingerprints": shared,
            "shared_arm_binding_status": "passed",
            "source_graph_policy_fingerprint": sha256_json(SOURCE_GRAPH_POLICY_ID),
            "source_native_relation_fingerprint": sha256_json(SOURCE_NATIVE_RELATION),
            "routing_profile_fingerprint": prepared.runtime_binding["routing_profile_fingerprint"],
            "routing_binding_set_fingerprint": prepared.runtime_binding[
                "routing_binding_set_fingerprint"
            ],
            "manifest_route_projection_fingerprint": prepared.runtime_binding[
                "manifest_route_projection_fingerprint"
            ],
        },
        "quality_gate": {
            "status": "blocked",
            "reason_fingerprint": sha256_json(
                "ten_case_fixture_is_not_final_independent_transfer_acceptance"
            ),
            "minimum_final_case_count": 100,
            "evaluated_case_count": len(cases),
        },
        "hashes": {
            **{
                key: value
                for key, value in prepared.report["hashes"].items()
                if key != "report_fingerprint"
            },
            "runtime_fingerprint": prepared.runtime_binding["runtime_fingerprint"],
            "execution_row_set_fingerprint": execution_row_set_fingerprint,
            "consumed_claim_sha256": consumed_claim.byte_sha256,
            "consumed_claim_fingerprint": consumed_claim.claim_fingerprint,
            "execution_output_binding_fingerprint": consumed_claim.output_binding_fingerprint,
        },
    }
    report["hashes"]["execution_artifact_binding_fingerprint"] = sha256_json(
        {
            "runtime_fingerprint": prepared.runtime_binding["runtime_fingerprint"],
            "manifest_projection_fingerprint": prepared.oracle_free_projection[
                "report_fingerprint"
            ],
            "manifest_route_projection_fingerprint": prepared.runtime_binding[
                "manifest_route_projection_fingerprint"
            ],
            "routing_profile_fingerprint": prepared.runtime_binding["routing_profile_fingerprint"],
            "routing_binding_set_fingerprint": prepared.runtime_binding[
                "routing_binding_set_fingerprint"
            ],
            "manifest_sha256": prepared.runtime_binding["manifest_sha256"],
            "consumed_claim_sha256": consumed_claim.byte_sha256,
            "consumed_claim_fingerprint": consumed_claim.claim_fingerprint,
            "execution_row_set_fingerprint": execution_row_set_fingerprint,
        }
    )
    report["hashes"]["report_fingerprint"] = _report_fingerprint(report)
    _validate_public_report(report, artifact_id=EXECUTION_ARTIFACT_ID)
    return report


def _run_case_arms(
    *,
    session: Any,
    effective_graph_view: Any,
    query_text: str,
    query_class: str,
) -> tuple[tuple[str, Any, float, str], ...]:
    if query_class not in _SUPPORTED_AUTHORED_QUERY_CLASSES:
        raise TransferUatValidationError("holdout_case_routing_contract_invalid")
    limits = SemanticPlanLimits(
        max_hops=2,
        max_fanout=6,
        max_candidates=24,
        max_results=10,
        max_evidence=10,
        max_time_budget_ms=1_500,
        max_repairs=1,
    )
    budget_fingerprint = sha256_json(
        {
            "policy_id": EXECUTION_BUDGET_POLICY_ID,
            "max_hops": limits.max_hops,
            "max_fanout": limits.max_fanout,
            "max_candidates": limits.max_candidates,
            "max_results": limits.max_results,
            "max_evidence": limits.max_evidence,
            "max_time_budget_ms": limits.max_time_budget_ms,
            "max_repairs": limits.max_repairs,
        }
    )

    def timed(operation: Callable[[], Any]) -> tuple[Any, float]:
        started = time.perf_counter()
        result = operation()
        return result, round((time.perf_counter() - started) * 1_000, 3)

    strong, strong_ms = timed(
        lambda: session.index.query(
            query_text=query_text,
            query_class="evidence_lookup",
            candidate_limit=limits.max_candidates,
            result_limit=limits.max_results,
        )
    )
    entity, entity_ms = timed(
        lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=(CO_OCCURRENCE_RELATION, SOURCE_NATIVE_RELATION),
            limits=limits,
            enable_graph_traversal=False,
        )
    )
    candidate_graph, graph_ms = timed(
        lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=(CO_OCCURRENCE_RELATION, SOURCE_NATIVE_RELATION),
            limits=limits,
        )
    )
    hybrid, hybrid_ms = timed(
        lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=(CO_OCCURRENCE_RELATION, SOURCE_NATIVE_RELATION),
            target_core_supertype_id=ONTOLOGY_TARGET,
            limits=limits,
        )
    )
    legacy, legacy_ms = timed(
        lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=(CO_OCCURRENCE_RELATION, SOURCE_NATIVE_RELATION),
            target_core_supertype_id=ONTOLOGY_TARGET,
            limits=limits,
            legacy_hard_gate=True,
        )
    )
    rows: list[tuple[str, Any, float, str]] = [
        ("strong_rag", strong, strong_ms, budget_fingerprint),
        ("rag_entity", entity, entity_ms, budget_fingerprint),
        ("rag_candidate_kg", candidate_graph, graph_ms, budget_fingerprint),
        ("hybrid_v2_soft", hybrid, hybrid_ms, budget_fingerprint),
        ("legacy_hard_gate", legacy, legacy_ms, budget_fingerprint),
    ]
    if query_class == "exact_set_or_inventory":
        inventory_kind = _github_exact_inventory_kind(query_text)
        exact, exact_ms = timed(
            lambda: session.query(
                query_text=query_text,
                effective_graph_view=effective_graph_view,
                exact_inventory_kind=inventory_kind,
                limits=limits,
            )
        )
        rows.append(("structured_exact", exact, exact_ms, budget_fingerprint))
    return tuple(rows)


def _github_exact_inventory_kind(query_text: str) -> str:
    normalized = query_text.casefold()
    comment_terms = ("comment", "comments", "top-level comment", "留言", "評論")
    issue_terms = ("issue record", "issue records", "issues", "議題")
    if any(term in normalized for term in comment_terms):
        return "top_level_issue_comment"
    if any(term in normalized for term in issue_terms):
        return "issue_record"
    raise TransferUatValidationError("github_exact_inventory_kind_unresolved")


def _score_case(
    case: Mapping[str, Any],
    *,
    arm_id: str,
    result: Any,
    answer_status: str,
    answer_citation_hashes: Sequence[str],
    answer_hash: str,
    answer_cost_units: int,
    elapsed_ms: float,
    budget_fingerprint: str,
    observation_hash_by_id: Mapping[str, str],
) -> dict[str, Any]:
    case_fingerprint = _require_sha256(
        case.get("case_fingerprint"),
        "holdout_case_fingerprint_invalid",
    )
    routing_contract_fingerprint = _validate_case_routing_contract(case)
    required_ids = case.get("required_source_observation_ids")
    if not isinstance(required_ids, list) or not required_ids:
        raise TransferUatValidationError("holdout_case_lineage_missing")
    required_hashes = {
        observation_hash_by_id[observation_id]
        for observation_id in required_ids
        if observation_id in observation_hash_by_id
    }
    if len(required_hashes) != len(set(required_ids)):
        raise TransferUatValidationError("holdout_case_lineage_missing")
    citations = tuple(dict.fromkeys(answer_citation_hashes))
    authorized = set(observation_hash_by_id.values())
    if any(citation not in authorized for citation in citations):
        raise TransferUatValidationError("transfer_answer_citation_authorized_lineage_missing")
    matched_required = set(citations) & required_hashes
    expected = case.get("expected_private")
    if not isinstance(expected, Mapping):
        raise TransferUatValidationError("holdout_expected_oracle_invalid")
    stratum = str(case.get("stratum"))
    graph_paths = tuple(getattr(result, "graph_paths", ()))
    exact_result = getattr(result, "exact_result", None)
    relation_path_found = any(
        any(hop.relation_type_hash == sha256_json(SOURCE_NATIVE_RELATION) for hop in path.hops)
        for path in graph_paths
    )
    exact_match = True
    if arm_id == "structured_exact":
        expected_count = expected.get("count")
        exact_match = (
            isinstance(expected_count, int)
            and not isinstance(expected_count, bool)
            and exact_result is not None
            and exact_result.status == "complete_authorized_scope"
            and exact_result.exact_count == expected_count
            and exact_result.returned_item_count == expected_count
            and all(
                item.cited_observation_hashes and set(item.cited_observation_hashes) <= authorized
                for item in exact_result.items
            )
        )
        passed = exact_match and answer_status == "exact_complete"
    elif stratum == "no_answer":
        passed = answer_status == "no_answer" and not citations
    else:
        passed = answer_status in {"answered", "exact_complete"} and bool(matched_required)
        if stratum == "cross_issue_relation" and arm_id in {
            "rag_candidate_kg",
            "hybrid_v2_soft",
            "legacy_hard_gate",
        }:
            passed = passed and relation_path_found
    graph_hop_count = 0
    graph_hop_authorized_count = 0
    for path in graph_paths:
        for hop in path.hops:
            graph_hop_count += 1
            if hop.cited_observation_hashes and set(hop.cited_observation_hashes) <= authorized:
                graph_hop_authorized_count += 1
            else:
                raise TransferUatValidationError("transfer_graph_hop_authorized_lineage_missing")
    return {
        "case_fingerprint": case_fingerprint,
        "routing_contract_fingerprint": routing_contract_fingerprint,
        "arm_id": arm_id,
        "stratum_hash": sha256_json(stratum),
        "query_class_hash": sha256_json(str(case.get("query_class"))),
        "status": "passed" if passed else "failed",
        "answer_status": answer_status,
        "answer_hash": answer_hash,
        "citation_count": len(citations),
        "matched_required_citation_count": len(matched_required),
        "unmatched_citation_count": len(set(citations) - required_hashes),
        "graph_path_count": len(graph_paths),
        "source_native_relation_path_found": relation_path_found,
        "graph_hop_count": graph_hop_count,
        "graph_hop_authorized_count": graph_hop_authorized_count,
        "exact_match": exact_match,
        "no_answer": answer_status == "no_answer",
        "permission_leakage": False,
        "cost_units": int(answer_cost_units),
        "elapsed_ms": elapsed_ms,
        "budget_fingerprint": budget_fingerprint,
    }


def _permission_denied_row(case: Mapping[str, Any], *, arm_id: str) -> dict[str, Any]:
    _validated_case_query(case)
    case_fingerprint = _require_sha256(
        case.get("case_fingerprint"),
        "holdout_case_fingerprint_invalid",
    )
    routing_contract_fingerprint = _validate_case_routing_contract(case)
    expected = case.get("expected_private")
    if not isinstance(expected, Mapping) or expected.get("outer_status") != "permission_denied":
        raise TransferUatValidationError("holdout_permission_oracle_invalid")
    return {
        "case_fingerprint": case_fingerprint,
        "routing_contract_fingerprint": routing_contract_fingerprint,
        "arm_id": arm_id,
        "stratum_hash": sha256_json("permission_denied"),
        "query_class_hash": sha256_json(str(case.get("query_class"))),
        "status": "passed",
        "answer_status": "permission_denied",
        "answer_hash": sha256_json(
            {"status": "permission_denied", "case_fingerprint": case_fingerprint}
        ),
        "citation_count": 0,
        "matched_required_citation_count": 0,
        "unmatched_citation_count": 0,
        "graph_path_count": 0,
        "source_native_relation_path_found": False,
        "graph_hop_count": 0,
        "graph_hop_authorized_count": 0,
        "exact_match": True,
        "no_answer": False,
        "permission_leakage": False,
        "cost_units": 0,
        "elapsed_ms": 0.0,
        "budget_fingerprint": sha256_json(EXECUTION_BUDGET_POLICY_ID),
    }


def _aggregate_arm(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    passed = sum(row.get("status") == "passed" for row in rows)
    citations = sum(int(row.get("citation_count", 0)) for row in rows)
    matched = sum(int(row.get("matched_required_citation_count", 0)) for row in rows)
    hop_count = sum(int(row.get("graph_hop_count", 0)) for row in rows)
    authorized_hops = sum(int(row.get("graph_hop_authorized_count", 0)) for row in rows)
    latencies = sorted(float(row.get("elapsed_ms", 0.0)) for row in rows)
    return {
        "scored_case_count": len(rows),
        "passed_case_count": passed,
        "correctness_basis_points": round(passed * 10_000 / len(rows)) if rows else 0,
        "citation_count": citations,
        "matched_required_citation_count": matched,
        "citation_precision_basis_points": (
            round(matched * 10_000 / citations) if citations else 10_000
        ),
        "no_answer_count": sum(bool(row.get("no_answer")) for row in rows),
        "permission_denial_count": sum(
            row.get("answer_status") == "permission_denied" for row in rows
        ),
        "source_native_relation_path_count": sum(
            bool(row.get("source_native_relation_path_found")) for row in rows
        ),
        "graph_hop_count": hop_count,
        "authorized_graph_hop_count": authorized_hops,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "maximum_cost_units": max((int(row.get("cost_units", 0)) for row in rows), default=0),
        "row_set_fingerprint": sha256_json(list(rows)),
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int((len(values) - 1) * quantile + 0.999999)))
    return round(float(values[index]), 3)


def _consumed_claim_path(execution_output: Path) -> Path:
    return execution_output.with_name(f"{execution_output.name}.consumed.json")


def _output_binding_fingerprint(execution_output: Path) -> str:
    return sha256_json(
        {
            "output_locator_fingerprint": sha256_json(os.path.abspath(execution_output)),
            "claim_locator_fingerprint": sha256_json(
                os.path.abspath(_consumed_claim_path(execution_output))
            ),
        }
    )


def _acquire_consumed_claim(
    *,
    preflight_report: Mapping[str, Any],
    runtime_binding: Mapping[str, Any],
    expected_manifest_sha256: str,
    execution_output: Path,
) -> _ConsumedClaimReceipt:
    if (
        preflight_report.get("status") != "passed"
        or preflight_report.get("preflight_status") != "passed"
        or preflight_report.get("execution_status") != "not_run"
        or preflight_report.get("quality_result_status") != "not_read"
        or preflight_report.get("oracle_access_status") != "not_read"
    ):
        raise TransferUatValidationError("one_shot_preflight_not_passed")
    runtime_fingerprint = _require_sha256(
        runtime_binding.get("runtime_fingerprint"),
        "one_shot_runtime_fingerprint_invalid",
    )
    hashes = preflight_report.get("hashes")
    if (
        not isinstance(hashes, Mapping)
        or hashes.get("runtime_fingerprint") != runtime_fingerprint
        or hashes.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise TransferUatValidationError("one_shot_preflight_binding_mismatch")
    output_binding = _output_binding_fingerprint(execution_output)
    claim: dict[str, Any] = {
        "artifact_id": CONSUMED_CLAIM_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "consumed",
        "claim_status": "acquired_before_oracle_read",
        "retry_policy": "never",
        "hashes": {
            "preflight_input_fingerprint": hashes["preflight_input_fingerprint"],
            "preflight_report_fingerprint": hashes["report_fingerprint"],
            "runtime_fingerprint": runtime_fingerprint,
            "manifest_projection_fingerprint": hashes["manifest_projection_fingerprint"],
            "manifest_route_projection_fingerprint": hashes[
                "manifest_route_projection_fingerprint"
            ],
            "routing_profile_fingerprint": hashes["routing_profile_fingerprint"],
            "routing_binding_set_fingerprint": hashes["routing_binding_set_fingerprint"],
            "manifest_sha256": expected_manifest_sha256,
            "output_binding_fingerprint": output_binding,
        },
    }
    claim["hashes"]["claim_fingerprint"] = _claim_fingerprint(claim)
    try:
        assert_no_public_raw_references(claim, CONSUMED_CLAIM_ARTIFACT_ID)
    except ContractValidationError as exc:
        raise TransferUatValidationError("one_shot_consumed_claim_private_leak") from exc
    claim_path = _consumed_claim_path(execution_output)
    claim_sha256 = _publish_exclusive_immutable_json(
        claim_path,
        claim,
        exists_reason="one_shot_consumed_claim_already_exists",
        publish_reason="one_shot_consumed_claim_publish_failed",
    )
    receipt = _ConsumedClaimReceipt(
        path=claim_path,
        payload=claim,
        byte_sha256=claim_sha256,
        claim_fingerprint=str(claim["hashes"]["claim_fingerprint"]),
        output_binding_fingerprint=output_binding,
    )
    _validate_consumed_claim_receipt(receipt)
    if execution_output.exists() or execution_output.is_symlink():
        raise TransferUatValidationError("one_shot_output_already_exists")
    return receipt


def _validate_consumed_claim_receipt(receipt: _ConsumedClaimReceipt) -> None:
    try:
        metadata = receipt.path.lstat()
        payload = receipt.path.read_bytes()
        decoded = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransferUatValidationError("one_shot_consumed_claim_audit_failed") from exc
    hashes = decoded.get("hashes", {})
    if (
        receipt.path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o222
        or _sha256_bytes(payload) != receipt.byte_sha256
        or decoded != receipt.payload
        or hashes.get("claim_fingerprint") != receipt.claim_fingerprint
        or receipt.claim_fingerprint != _claim_fingerprint(decoded)
        or hashes.get("output_binding_fingerprint") != receipt.output_binding_fingerprint
    ):
        raise TransferUatValidationError("one_shot_consumed_claim_audit_failed")


def _validate_published_execution_output(
    output_path: Path,
    *,
    expected_report: Mapping[str, Any],
    expected_sha256: str,
) -> None:
    try:
        metadata = output_path.lstat()
        payload = output_path.read_bytes()
        decoded = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransferUatValidationError("one_shot_output_audit_failed") from exc
    if (
        output_path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o222
        or _sha256_bytes(payload) != expected_sha256
        or decoded != expected_report
    ):
        raise TransferUatValidationError("one_shot_output_audit_failed")
    _validate_public_report(decoded, artifact_id=EXECUTION_ARTIFACT_ID)


def _claim_fingerprint(claim: Mapping[str, Any]) -> str:
    payload = dict(claim)
    hashes = dict(payload.get("hashes", {}))
    hashes.pop("claim_fingerprint", None)
    payload["hashes"] = hashes
    return sha256_json(payload)


def _publish_immutable_json(output_path: Path, payload: Mapping[str, Any]) -> str:
    return _publish_exclusive_immutable_json(
        output_path,
        payload,
        exists_reason="one_shot_output_already_exists",
        publish_reason="one_shot_output_publish_failed",
    )


def _publish_exclusive_immutable_json(
    output_path: Path,
    payload: Mapping[str, Any],
    *,
    exists_reason: str,
    publish_reason: str,
) -> str:
    if output_path.exists() or output_path.is_symlink():
        raise TransferUatValidationError(exists_reason)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    temporary_path: Path | None = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.chmod(0o444)
        os.link(temporary_path, output_path)
        directory_fd = os.open(output_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise TransferUatValidationError(exists_reason) from exc
    except OSError as exc:
        raise TransferUatValidationError(publish_reason) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return _sha256_bytes(encoded)


def _validate_source_export(
    export: Mapping[str, Any],
    *,
    source_export_sha256: str,
) -> dict[str, int]:
    source_occurrence_schema = export.get("source_occurrence_schema")
    if (
        export.get("artifact_id") != SOURCE_EXPORT_ARTIFACT_ID
        or export.get("schema_version") != 1
        or export.get("status") != "passed"
        or export.get("claim_boundary_status") != "source_observations_not_canonical_fact"
        or export.get("blocker_ids") != []
        or export.get("source_kind") != SOURCE_KIND
        or not isinstance(source_occurrence_schema, Mapping)
        or source_occurrence_schema.get("source_kind") != SOURCE_KIND
        or source_occurrence_schema.get("mixed_source_kinds_allowed") is not False
        or export.get("source_occurrence_schema_fingerprint")
        != sha256_json(dict(source_occurrence_schema))
    ):
        raise TransferUatValidationError("source_export_identity_or_status_invalid")
    if export.get("export_fingerprint") != _payload_fingerprint(
        export,
        "export_fingerprint",
    ):
        raise TransferUatValidationError("source_export_fingerprint_drift")
    try:
        asset = Asset.from_dict(dict(export["asset"]))
        run = ExtractorRun.from_dict(dict(export["extractor_run"]))
        inventory = SourceInventory.from_dict(dict(export["source_inventory"]))
        observations = [Observation.from_dict(dict(value)) for value in export["observations"]]
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise TransferUatValidationError("source_owner_contract_round_trip_failed") from exc
    if (
        run.asset_id != asset.asset_id
        or inventory.source_asset_id != asset.asset_id
        or any(observation.asset_id != asset.asset_id for observation in observations)
        or any(observation.extractor_run_id != run.extractor_run_id for observation in observations)
        or asset.workspace_id == ""
        or not asset.project_id
    ):
        raise TransferUatValidationError("source_owner_binding_mismatch")
    if (
        asset.content_hash != export.get("source_snapshot_fingerprint")
        or inventory.source_fingerprint != export.get("source_snapshot_fingerprint")
        or inventory.parser_fingerprint != export.get("parser_fingerprint")
    ):
        raise TransferUatValidationError("source_snapshot_binding_mismatch")
    records = export.get("source_records")
    bindings = export.get("record_bindings")
    counts = export.get("counts")
    if (
        not isinstance(records, list)
        or not isinstance(bindings, list)
        or not isinstance(counts, Mapping)
    ):
        raise TransferUatValidationError("source_lineage_collections_invalid")
    inventory_by_key = {
        str(item.location.get("source_local_key")): item for item in inventory.items
    }
    observations_by_key = {
        str(observation.location.get("source_local_key")): observation
        for observation in observations
    }
    binding_by_key = {
        str(binding.get("source_local_key")): binding
        for binding in bindings
        if isinstance(binding, Mapping)
    }
    if (
        len(binding_by_key) != len(bindings)
        or set(inventory_by_key) != set(observations_by_key)
        or set(observations_by_key) != set(binding_by_key)
    ):
        raise TransferUatValidationError("source_record_lineage_reconciliation_failed")
    record_identities: Counter[tuple[str, str]] = Counter()
    for record in records:
        if not isinstance(record, Mapping):
            raise TransferUatValidationError("source_record_invalid")
        fingerprint = record.get("source_record_fingerprint")
        normalized = {
            key: value
            for key, value in record.items()
            if key not in {"record_kind", "source_record_fingerprint"}
        }
        if fingerprint != sha256_json(normalized):
            raise TransferUatValidationError("source_record_fingerprint_drift")
        record_identities[(str(record.get("record_kind")), str(fingerprint))] += 1
    binding_identities: Counter[tuple[str, str]] = Counter()
    for source_local_key, binding in binding_by_key.items():
        observation = observations_by_key[source_local_key]
        item = inventory_by_key[source_local_key]
        if (
            binding.get("source_inventory_item_id") != item.source_inventory_item_id
            or binding.get("observation_id") != observation.observation_id
            or binding.get("record_kind") != observation.observation_type
            or binding.get("source_record_fingerprint")
            != (observation.payload or {}).get("source_record_fingerprint")
            or observation.modality != "project"
            or observation.permission_scope.get("scope_type") != "project"
            or observation.permission_scope.get("scope_id") != asset.project_id
        ):
            raise TransferUatValidationError("source_record_binding_mismatch")
        binding_identities[
            (str(binding.get("record_kind")), str(binding.get("source_record_fingerprint")))
        ] += 1
    if record_identities != binding_identities:
        raise TransferUatValidationError("source_record_identity_reconciliation_failed")
    if export.get("lineage_fingerprint") != sha256_json(bindings):
        raise TransferUatValidationError("source_lineage_fingerprint_drift")
    expected_counts = {
        "source_record_count": len(records),
        "source_inventory_item_count": len(inventory.items),
        "observation_count": len(observations),
        "unexplained_loss_count": 0,
        "missing_inventory_binding_count": 0,
        "missing_observation_binding_count": 0,
    }
    if any(counts.get(key) != value for key, value in expected_counts.items()):
        raise TransferUatValidationError("source_completeness_count_drift")
    _require_sha256(source_export_sha256, "source_export_seal_invalid")
    return {
        "source_record_count": len(records),
        "source_inventory_item_count": len(inventory.items),
        "source_observation_count": len(observations),
    }


def _validate_source_report(
    report: Mapping[str, Any],
    *,
    source_export: Mapping[str, Any],
    source_export_sha256: str,
) -> None:
    _validate_safe_report_identity(report, SOURCE_REPORT_ARTIFACT_ID)
    if (
        report.get("source_completeness_status") != "passed"
        or report.get("blocker_count") != 0
        or report.get("counts") != source_export.get("counts")
    ):
        raise TransferUatValidationError("source_safe_report_binding_invalid")
    hashes = report.get("hashes")
    expected = {
        "source_snapshot_fingerprint": source_export["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(source_export["source_inventory"]),
        "observation_snapshot_fingerprint": sha256_json(source_export["observations"]),
        "lineage_fingerprint": source_export["lineage_fingerprint"],
        "source_occurrence_schema_fingerprint": source_export[
            "source_occurrence_schema_fingerprint"
        ],
        "private_export_sha256": source_export_sha256,
        "private_export_fingerprint": source_export["export_fingerprint"],
    }
    if not isinstance(hashes, Mapping) or any(
        hashes.get(key) != value for key, value in expected.items()
    ):
        raise TransferUatValidationError("source_safe_report_hash_binding_mismatch")


def _source_authored_query_class(stratum: str) -> str:
    intent = _ROUTING_INTENT_BY_STRATUM.get(stratum)
    if intent is None:
        raise TransferUatValidationError("holdout_typed_stratum_unsupported")
    return _QUERY_CLASS_BY_ROUTING_INTENT[intent]


def _validate_source_authored_routing_profile(
    profile: Mapping[str, Any],
    *,
    profile_fingerprint: Any,
) -> None:
    if (
        not isinstance(profile, Mapping)
        or dict(profile) != _EXPECTED_ROUTING_PROFILE
        or profile_fingerprint != ROUTING_PROFILE_FINGERPRINT
        or sha256_json(dict(profile)) != ROUTING_PROFILE_FINGERPRINT
    ):
        raise TransferUatValidationError("holdout_routing_profile_invalid")


def _validate_oracle_free_route_projection(
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "schema_id",
        "classification",
        "claim_boundary_status",
        "diagnostic_only",
        "final_acceptance_eligible",
        "routing_profile_id",
        "routing_profile_fingerprint",
        "case_count",
        "strata_counts",
        "query_class_counts",
        "case_routes",
        "projection_fingerprint",
    }
    if (
        not isinstance(projection, Mapping)
        or set(projection) != expected_fields
        or projection.get("schema_id") != ORACLE_FREE_PROJECTION_SCHEMA_ID
        or projection.get("classification") != DIAGNOSTIC_CLASSIFICATION
        or projection.get("claim_boundary_status") != DIAGNOSTIC_CLAIM_BOUNDARY
        or projection.get("diagnostic_only") is not True
        or projection.get("final_acceptance_eligible") is not False
        or projection.get("routing_profile_id") != ROUTING_PROFILE_ID
        or projection.get("routing_profile_fingerprint") != ROUTING_PROFILE_FINGERPRINT
        or projection.get("case_count") != sum(STRATA_COUNTS.values())
        or projection.get("strata_counts") != STRATA_COUNTS
        or projection.get("query_class_counts") != _EXPECTED_QUERY_CLASS_COUNTS
        or projection.get("projection_fingerprint")
        != _payload_fingerprint(projection, "projection_fingerprint")
    ):
        raise TransferUatValidationError("holdout_route_projection_invalid")
    case_routes = projection.get("case_routes")
    if not isinstance(case_routes, list) or len(case_routes) != sum(STRATA_COUNTS.values()):
        raise TransferUatValidationError("holdout_route_projection_case_count_invalid")
    normalized_routes: list[dict[str, str]] = []
    case_entry_hashes: set[str] = set()
    route_fingerprints: set[str] = set()
    strata = Counter()
    query_classes = Counter()
    expected_fields = {
        "case_entry_hash",
        "stratum",
        "query_class",
        "routing_contract_fingerprint",
    }
    for route in case_routes:
        if not isinstance(route, Mapping) or set(route) != expected_fields:
            raise TransferUatValidationError("holdout_route_projection_entry_invalid")
        case_entry_hash = _require_sha256(
            route.get("case_entry_hash"),
            "holdout_route_projection_case_hash_invalid",
        )
        routing_contract_fingerprint = _require_sha256(
            route.get("routing_contract_fingerprint"),
            "holdout_route_projection_contract_hash_invalid",
        )
        stratum = route.get("stratum")
        query_class = route.get("query_class")
        if (
            not isinstance(stratum, str)
            or not isinstance(query_class, str)
            or query_class != _source_authored_query_class(stratum)
        ):
            raise TransferUatValidationError("holdout_route_projection_class_invalid")
        if (
            case_entry_hash in case_entry_hashes
            or routing_contract_fingerprint in route_fingerprints
        ):
            raise TransferUatValidationError("holdout_route_projection_duplicate")
        case_entry_hashes.add(case_entry_hash)
        route_fingerprints.add(routing_contract_fingerprint)
        strata[stratum] += 1
        query_classes[query_class] += 1
        normalized_routes.append(
            {
                "case_entry_hash": case_entry_hash,
                "stratum": stratum,
                "query_class": query_class,
                "routing_contract_fingerprint": routing_contract_fingerprint,
            }
        )
    sorted_routes = sorted(normalized_routes, key=lambda item: item["case_entry_hash"])
    if normalized_routes != sorted_routes:
        raise TransferUatValidationError("holdout_route_projection_order_invalid")
    normalized_strata = dict(sorted(strata.items()))
    normalized_query_classes = dict(sorted(query_classes.items()))
    if (
        normalized_strata != STRATA_COUNTS
        or normalized_query_classes != _EXPECTED_QUERY_CLASS_COUNTS
    ):
        raise TransferUatValidationError("holdout_route_projection_counts_invalid")
    return {
        "case_count": len(sorted_routes),
        "strata_counts": normalized_strata,
        "query_class_counts": normalized_query_classes,
        "case_routes": sorted_routes,
        "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
        "routing_binding_set_fingerprint": sha256_json(sorted(route_fingerprints)),
        "manifest_route_projection_fingerprint": projection["projection_fingerprint"],
    }


def _validate_case_routing_contract(case: Mapping[str, Any]) -> str:
    query_text = case.get("private_query")
    query_class = case.get("query_class")
    stratum = case.get("stratum")
    contract = case.get("routing_contract")
    expected_fields = {
        "schema_id",
        "routing_profile_id",
        "routing_profile_fingerprint",
        "typed_stratum",
        "authored_intent_kind",
        "authored_query_class",
        "private_query_hash",
        "query_text_inference_authoritative",
        "routing_contract_fingerprint",
    }
    if (
        not isinstance(query_text, str)
        or not query_text.strip()
        or not isinstance(query_class, str)
        or not isinstance(stratum, str)
        or not isinstance(contract, Mapping)
        or set(contract) != expected_fields
    ):
        raise TransferUatValidationError("holdout_case_routing_contract_invalid")
    expected_intent = _ROUTING_INTENT_BY_STRATUM.get(stratum)
    if expected_intent is None:
        raise TransferUatValidationError("holdout_typed_stratum_unsupported")
    expected_query_class = _QUERY_CLASS_BY_ROUTING_INTENT[expected_intent]
    if (
        query_class != expected_query_class
        or query_class not in _SUPPORTED_AUTHORED_QUERY_CLASSES
        or contract.get("schema_id") != ROUTING_CONTRACT_SCHEMA_ID
        or contract.get("routing_profile_id") != ROUTING_PROFILE_ID
        or contract.get("routing_profile_fingerprint") != ROUTING_PROFILE_FINGERPRINT
        or contract.get("typed_stratum") != stratum
        or contract.get("authored_intent_kind") != expected_intent
        or contract.get("authored_query_class") != query_class
        or contract.get("private_query_hash") != sha256_json(query_text)
        or contract.get("query_text_inference_authoritative") is not False
        or contract.get("routing_contract_fingerprint")
        != _payload_fingerprint(contract, "routing_contract_fingerprint")
    ):
        raise TransferUatValidationError("holdout_case_routing_contract_invalid")
    return _require_sha256(
        contract["routing_contract_fingerprint"],
        "holdout_case_routing_contract_fingerprint_invalid",
    )


def _manifest_route_projection(
    *,
    cases: Sequence[Mapping[str, Any]],
    strata_counts: Mapping[str, Any],
    query_class_counts: Mapping[str, Any],
) -> dict[str, Any]:
    case_routes = sorted(
        (
            {
                "case_entry_hash": sha256_json(str(case["case_id"])),
                "stratum": str(case["stratum"]),
                "query_class": str(case["query_class"]),
                "routing_contract_fingerprint": str(
                    case["routing_contract"]["routing_contract_fingerprint"]
                ),
            }
            for case in cases
        ),
        key=lambda item: item["case_entry_hash"],
    )
    projection: dict[str, Any] = {
        "schema_id": ORACLE_FREE_PROJECTION_SCHEMA_ID,
        "classification": DIAGNOSTIC_CLASSIFICATION,
        "claim_boundary_status": DIAGNOSTIC_CLAIM_BOUNDARY,
        "diagnostic_only": True,
        "final_acceptance_eligible": False,
        "routing_profile_id": ROUTING_PROFILE_ID,
        "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
        "case_count": len(cases),
        "strata_counts": dict(strata_counts),
        "query_class_counts": dict(query_class_counts),
        "case_routes": case_routes,
    }
    projection["projection_fingerprint"] = _payload_fingerprint(
        projection,
        "projection_fingerprint",
    )
    return projection


def _validate_holdout_oracle_free_projection(
    projection: Mapping[str, Any],
    *,
    projection_sha256: str,
    expected_manifest_sha256: str,
    source_export: Mapping[str, Any],
    source_export_sha256: str,
) -> dict[str, Any]:
    _assert_oracle_free(projection)
    _validate_safe_report_identity(projection, HOLDOUT_REPORT_ARTIFACT_ID)
    if (
        projection.get("execution_status") != "not_run"
        or projection.get("quality_result_status") != "not_read"
        or projection.get("runtime_freeze_status") != "pending_master_confirmation"
        or projection.get("routing_contract_status") != "passed"
        or projection.get("oracle_free_projection_status") != "passed"
        or projection.get("blocker_count") != 0
        or projection.get("strata_counts") != STRATA_COUNTS
        or projection.get("query_class_counts") != _EXPECTED_QUERY_CLASS_COUNTS
    ):
        raise TransferUatValidationError("holdout_projection_boundary_invalid")
    counts = projection.get("counts")
    hashes = projection.get("hashes")
    manifest_projection = projection.get("manifest_projection")
    if (
        not isinstance(counts, Mapping)
        or not isinstance(hashes, Mapping)
        or not isinstance(manifest_projection, Mapping)
    ):
        raise TransferUatValidationError("holdout_projection_shape_invalid")
    route_lineage = _validate_oracle_free_route_projection(manifest_projection)
    expected = {
        "source_snapshot_fingerprint": source_export["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(source_export["source_inventory"]),
        "observation_snapshot_fingerprint": sha256_json(source_export["observations"]),
        "source_occurrence_schema_fingerprint": source_export[
            "source_occurrence_schema_fingerprint"
        ],
        "routing_profile_fingerprint": route_lineage["routing_profile_fingerprint"],
        "routing_binding_set_fingerprint": route_lineage["routing_binding_set_fingerprint"],
        "manifest_projection_fingerprint": route_lineage["manifest_route_projection_fingerprint"],
        "private_export_sha256": source_export_sha256,
        "private_export_fingerprint": source_export["export_fingerprint"],
        "private_holdout_sha256": expected_manifest_sha256,
    }
    if (
        counts.get("case_count") != sum(STRATA_COUNTS.values())
        or counts.get("source_record_count") != source_export["counts"]["source_record_count"]
        or counts.get("source_observation_count") != source_export["counts"]["observation_count"]
        or any(hashes.get(key) != value for key, value in expected.items())
    ):
        raise TransferUatValidationError("holdout_projection_binding_mismatch")
    _require_sha256(
        hashes.get("private_holdout_fingerprint"),
        "holdout_projection_manifest_fingerprint_invalid",
    )
    _require_sha256(projection_sha256, "holdout_projection_seal_invalid")
    return {
        "case_count": int(counts["case_count"]),
        "strata_counts": dict(projection["strata_counts"]),
        "query_class_counts": dict(projection["query_class_counts"]),
        "case_routes": list(route_lineage["case_routes"]),
        "routing_profile_fingerprint": route_lineage["routing_profile_fingerprint"],
        "routing_binding_set_fingerprint": route_lineage["routing_binding_set_fingerprint"],
        "manifest_route_projection_fingerprint": route_lineage[
            "manifest_route_projection_fingerprint"
        ],
    }


def _validate_holdout_manifest_execution_projection(
    manifest: Mapping[str, Any],
    *,
    private_export: Mapping[str, Any],
    private_export_sha256: str,
) -> dict[str, Any]:
    if (
        manifest.get("artifact_id") != HOLDOUT_ARTIFACT_ID
        or manifest.get("schema_version") != 1
        or manifest.get("status") != "sealed"
        or manifest.get("execution_status") != "not_run"
        or manifest.get("quality_result_status") != "not_read"
        or manifest.get("runtime_freeze_status") != "pending_master_confirmation"
        or manifest.get("seal_required_before_execution") is not True
        or manifest.get("source_family") != "github_project_issue_comment"
        or manifest.get("mail_source_consumed") is not False
        or manifest.get("blocker_ids") != []
        or manifest.get("manifest_fingerprint")
        != _payload_fingerprint(manifest, "manifest_fingerprint")
    ):
        raise TransferUatValidationError("holdout_execution_boundary_invalid")
    routing_profile = manifest.get("routing_profile")
    _validate_source_authored_routing_profile(
        routing_profile if isinstance(routing_profile, Mapping) else {},
        profile_fingerprint=manifest.get("routing_profile_fingerprint"),
    )
    binding = manifest.get("source_export_binding")
    expected_binding = {
        "private_export_sha256": private_export_sha256,
        "private_export_fingerprint": private_export["export_fingerprint"],
        "source_snapshot_fingerprint": private_export["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(private_export["source_inventory"]),
        "observation_snapshot_fingerprint": sha256_json(private_export["observations"]),
        "permission_fingerprint": private_export["permission_fingerprint"],
        "lineage_fingerprint": private_export["lineage_fingerprint"],
        "source_occurrence_schema_fingerprint": private_export[
            "source_occurrence_schema_fingerprint"
        ],
    }
    if not isinstance(binding, Mapping) or dict(binding) != expected_binding:
        raise TransferUatValidationError("holdout_source_binding_mismatch")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or manifest.get("case_count") != len(cases):
        raise TransferUatValidationError("holdout_case_count_mismatch")
    observation_by_id = {
        str(value["observation_id"]): value for value in private_export["observations"]
    }
    case_ids: set[str] = set()
    strata = Counter()
    query_classes = Counter()
    routing_fingerprints: list[str] = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise TransferUatValidationError("holdout_case_invalid")
        identity_payload = {
            key: value for key, value in case.items() if key not in {"case_id", "case_fingerprint"}
        }
        expected_case_id = stable_resource_contract_id(
            "transfercase",
            "Issue56GitHubTransferHoldoutCase",
            identity_payload,
        )
        if (
            case.get("case_fingerprint") != _payload_fingerprint(case, "case_fingerprint")
            or case.get("execution_status") != "not_run"
            or case.get("question_specific_aliases") is not False
            or case.get("case_id") != expected_case_id
        ):
            raise TransferUatValidationError("holdout_case_boundary_invalid")
        case_id = str(case.get("case_id") or "")
        if not case_id or case_id in case_ids:
            raise TransferUatValidationError("holdout_case_identity_duplicate")
        case_ids.add(case_id)
        required_ids = case.get("required_source_observation_ids")
        required_record_fingerprints = case.get("required_source_record_fingerprints")
        if (
            not isinstance(required_ids, list)
            or not required_ids
            or not isinstance(required_record_fingerprints, list)
            or not required_record_fingerprints
            or not set(required_ids).issubset(observation_by_id)
        ):
            raise TransferUatValidationError("holdout_case_lineage_missing")
        expected_record_fingerprints = {
            observation_by_id[observation_id]["payload"]["source_record_fingerprint"]
            for observation_id in required_ids
        }
        if set(required_record_fingerprints) != expected_record_fingerprints:
            raise TransferUatValidationError("holdout_case_record_lineage_mismatch")
        _query_text, query_class = _validated_case_query(case)
        routing_fingerprints.append(str(case["routing_contract"]["routing_contract_fingerprint"]))
        stratum = str(case.get("stratum"))
        strata[stratum] += 1
        query_classes[query_class] += 1
    normalized_strata = dict(sorted(strata.items()))
    normalized_query_classes = dict(sorted(query_classes.items()))
    if normalized_strata != STRATA_COUNTS or manifest.get("strata_counts") != STRATA_COUNTS:
        raise TransferUatValidationError("holdout_strata_coverage_mismatch")
    if (
        normalized_query_classes != _EXPECTED_QUERY_CLASS_COUNTS
        or manifest.get("query_class_counts") != _EXPECTED_QUERY_CLASS_COUNTS
        or manifest.get("routing_binding_set_fingerprint")
        != sha256_json(sorted(routing_fingerprints))
    ):
        raise TransferUatValidationError("holdout_routing_binding_mismatch")
    fixture = manifest.get("permission_fixture")
    permission_cases = [case for case in cases if case.get("stratum") == "permission_denied"]
    if (
        len(permission_cases) != 1
        or not isinstance(fixture, Mapping)
        or permission_cases[0].get("permission_fixture_id") != fixture.get("fixture_id")
        or fixture.get("source_content_reused_without_modification") is not True
    ):
        raise TransferUatValidationError("holdout_permission_fixture_invalid")
    manifest_projection = _manifest_route_projection(
        cases=cases,
        strata_counts=normalized_strata,
        query_class_counts=normalized_query_classes,
    )
    route_lineage = _validate_oracle_free_route_projection(manifest_projection)
    return {
        "case_count": len(cases),
        "strata_counts": normalized_strata,
        "query_class_counts": normalized_query_classes,
        "case_routes": list(route_lineage["case_routes"]),
        "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
        "routing_binding_set_fingerprint": sha256_json(sorted(routing_fingerprints)),
        "manifest_route_projection_fingerprint": route_lineage[
            "manifest_route_projection_fingerprint"
        ],
        "manifest_projection": manifest_projection,
    }


def _validated_case_query(case: Mapping[str, Any]) -> tuple[str, str]:
    query_text = case.get("private_query")
    query_class = case.get("query_class")
    if not isinstance(query_text, str) or not query_text.strip():
        raise TransferUatValidationError("holdout_private_query_invalid")
    _validate_case_routing_contract(case)
    if not isinstance(query_class, str):
        raise TransferUatValidationError("holdout_case_routing_contract_invalid")
    return query_text, query_class


def _assert_oracle_free(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _PRIVATE_ORACLE_KEYS:
                raise TransferUatValidationError("holdout_projection_oracle_field_present")
            _assert_oracle_free(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_oracle_free(nested)


def _validate_safe_report_identity(report: Mapping[str, Any], artifact_id: str) -> None:
    if (
        report.get("artifact_id") != artifact_id
        or report.get("schema_version") != 1
        or report.get("status") != "passed"
        or report.get("report_fingerprint") != _payload_fingerprint(report, "report_fingerprint")
    ):
        raise TransferUatValidationError("sealed_safe_report_invalid")
    try:
        assert_no_public_raw_references(report, artifact_id)
    except ContractValidationError as exc:
        raise TransferUatValidationError("sealed_safe_report_private_leak") from exc


def _read_sealed_json(
    path: Path,
    expected_sha256: str,
    *,
    max_bytes: int,
    invalid_reason: str,
    seal_reason: str,
) -> tuple[bytes, dict[str, Any]]:
    _require_sha256(expected_sha256, f"{invalid_reason}_seal")
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise TransferUatValidationError(invalid_reason)
        size = metadata.st_size
        if size < 2 or size > max_bytes:
            raise TransferUatValidationError(invalid_reason)
        payload = path.read_bytes()
        value = json.loads(payload)
    except TransferUatValidationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransferUatValidationError(invalid_reason) from exc
    if not isinstance(value, dict):
        raise TransferUatValidationError(invalid_reason)
    if _sha256_bytes(payload) != expected_sha256:
        raise TransferUatValidationError(seal_reason)
    return payload, value


def _validate_public_report(report: Mapping[str, Any], *, artifact_id: str) -> None:
    hashes = report.get("hashes")
    if not isinstance(hashes, Mapping) or hashes.get("report_fingerprint") != _report_fingerprint(
        report
    ):
        raise TransferUatValidationError("public_report_fingerprint_drift")
    try:
        assert_no_public_raw_references(report, artifact_id)
    except ContractValidationError as exc:
        raise TransferUatValidationError("public_report_private_leak") from exc
    serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
    forbidden = (
        "private_query",
        "expected_private",
        "source_records",
        "observations",
        "source_local_key",
        "issue_number",
        "comment_id",
    )
    if any(fragment in serialized for fragment in forbidden):
        raise TransferUatValidationError("public_report_private_field_leak")


def _rejection_report(reason_code: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "artifact_id": REJECTION_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "preflight_status": "failed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "oracle_access_status": "not_read",
        "counts": {
            "sealed_quality_field_read_count": 0,
            "executed_case_count": 0,
            "blocker_count": 1,
        },
        "hashes": {"reason_fingerprint": sha256_json(reason_code)},
    }
    report["hashes"]["report_fingerprint"] = _report_fingerprint(report)
    assert_no_public_raw_references(report, REJECTION_ARTIFACT_ID)
    return report


def _payload_fingerprint(payload: Mapping[str, Any], field_name: str) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != field_name})


def _report_fingerprint(report: Mapping[str, Any]) -> str:
    payload = dict(report)
    hashes = dict(payload.get("hashes", {}))
    hashes.pop("report_fingerprint", None)
    payload["hashes"] = hashes
    return sha256_json(payload)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _require_sha256(value: Any, reason_code: str) -> str:
    if not _is_sha256(value):
        raise TransferUatValidationError(reason_code)
    return str(value)


__all__ = [
    "ARM_IDS",
    "CONSUMED_CLAIM_ARTIFACT_ID",
    "EXECUTION_ARTIFACT_ID",
    "EXACT_EXECUTOR_ID",
    "FULL_CASE_ARM_IDS",
    "REPORT_ARTIFACT_ID",
    "SHARED_FINGERPRINT_FIELDS",
    "SOURCE_GRAPH_POLICY_ID",
    "SOURCE_KIND",
    "SOURCE_NATIVE_RELATION",
    "STRATA_COUNTS",
    "TransferUatValidationError",
    "build_transfer_uat_preflight",
    "execute_transfer_uat_once",
    "validate_execution_metrics",
    "validate_shared_arm_fingerprints",
]


if __name__ == "__main__":
    raise SystemExit(main())
