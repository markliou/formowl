#!/usr/bin/env python3
"""Preflight the sealed Issue #56 independent mail holdout without grading it.

The preflight reads the private manifest only as sealed bytes.  Every parseable
case and lineage field comes from a separately sealed oracle-free projection.
Only an atomically persisted consumed claim permits execute-once to decode the
private manifest and verify its exact projection binding.  Header evidence is
projected directly from sealed Observation owner records, body evidence stays
bound to preserved body segments, and exact cases use the existing
deterministic executor result.  No quality arm runs before runtime freeze.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import resource
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
for import_root in (ROOT, PYTHON_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import (  # noqa: E402
    CandidateMention,
    ContractValidationError,
    Observation,
    SourceInventory,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (  # noqa: E402
    ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_core.methodology_authority import check_methodology_authority  # noqa: E402
from formowl_graph.resolution import (  # noqa: E402
    resolve_exact_protected_identifier_candidates,
)
from formowl_mail import (  # noqa: E402
    DeterministicExactExecutionResult,
    MailEvidenceBundle,
    authorize_mail_evidence_bundles,
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
)
from formowl_mail.hybrid import build_evidence_identity_lineage_crosswalk  # noqa: E402
from formowl_mail.answer import EvidenceAnswerBudget, render_governed_evidence_answer  # noqa: E402
from formowl_mail.candidates import (  # noqa: E402
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
    TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    SourceBoundIdentifierMentionBatch,
    SourceIdentifierIdentityScope,
)
from scripts import issue56_simulated_uat as development_uat  # noqa: E402
from scripts.issue56_execution_fingerprint import (  # noqa: E402
    ExecutionFingerprintValidationError,
    build_current_authority_component,
    build_current_code_component,
    build_image_component,
    current_runtime_binding_fingerprints,
)
from scripts.issue56_operational_budget import (  # noqa: E402
    FROZEN_BUDGET_FINGERPRINT,
    FROZEN_CANONICAL_IMAGE_ID,
    FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    INTERNAL_COST_UNITS_PER_CASE_LIMIT,
    LATENCY_P95_LIMIT_MICROS,
    PEAK_RSS_LIMIT_KIB,
    deterministic_zero_cost_attestation_fingerprint,
)
from scripts.issue56_source_complete_snapshot_rebind import (  # noqa: E402
    _validate_native_authorized_report,
    _validate_native_retrieval_snapshot,
)
from scripts.issue56_source_development_uat_manifest import (  # noqa: E402
    ARTIFACT_ID as DEVELOPMENT_MANIFEST_ARTIFACT_ID,
    _payload_fingerprint,
    _validate_source_bindings,
    _validated_bundle_artifact,
)
from scripts.issue56_source_independent_mail_holdout_manifest import (  # noqa: E402
    _validated_development_exclusion_registry,
)
from scripts.issue56_source_independent_mail_holdout_extension import (  # noqa: E402
    ALTERNATIVE_STRATA_POLICY_FINGERPRINT as HOLDOUT_EXTENSION_CAPACITY_AUDIT_POLICY_FINGERPRINT,
    ARTIFACT_ID as HOLDOUT_EXTENSION_ARTIFACT_ID,
    BASE_HOLDOUT_ARTIFACT_ID as HOLDOUT_EXTENSION_BASE_ARTIFACT_ID,
    BASE_HOLDOUT_CASE_COUNT as HOLDOUT_EXTENSION_BASE_CASE_COUNT,
    BASE_HOLDOUT_SAFE_ARTIFACT_ID as HOLDOUT_EXTENSION_BASE_REPORT_ARTIFACT_ID,
    CLASSIFICATION as HOLDOUT_EXTENSION_CLASSIFICATION,
    COMBINED_ACCEPTANCE_CASE_COUNT as HOLDOUT_EXTENSION_COMBINED_CASE_COUNT,
    EXTENSION_CASE_COUNT as HOLDOUT_EXTENSION_CASE_COUNT,
    PARTITION_POLICY_FINGERPRINT as HOLDOUT_EXTENSION_PARTITION_POLICY_FINGERPRINT,
    PROJECTION_ARTIFACT_ID as HOLDOUT_EXTENSION_PROJECTION_ARTIFACT_ID,
    SCHEMA_VERSION as HOLDOUT_EXTENSION_SCHEMA_VERSION,
    SELECTION_POLICY_ID as HOLDOUT_EXTENSION_SELECTION_POLICY_ID,
    SELECTION_POLICY_FINGERPRINT as HOLDOUT_EXTENSION_SELECTION_POLICY_FINGERPRINT,
    TARGET_STRATA_COUNTS as HOLDOUT_EXTENSION_STRATA_COUNTS,
)
from scripts.issue56_source_identifier_candidates import (  # noqa: E402
    CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    PRIVATE_ARTIFACT_ID as SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
    RESOLUTION_POLICY_FINGERPRINT as SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT,
    RESOLUTION_POLICY_ID as SOURCE_IDENTIFIER_RESOLUTION_POLICY_ID,
    SourceIdentifierCandidateError,
    validate_private_identifier_candidate_artifact,
)
from scripts.issue56_identity_scope_attestation import (  # noqa: E402
    POLICY_FINGERPRINT as IDENTITY_SCOPE_POLICY_FINGERPRINT,
)
from scripts import issue56_holdout_source_author_projection_inputs as source_author_projection  # noqa: E402

SCHEMA_VERSION = 2
REPORT_ARTIFACT_ID = "formowl_issue56_independent_mail_holdout_uat_preflight_v2"
REJECTION_ARTIFACT_ID = "formowl_issue56_independent_mail_holdout_uat_rejection_v2"
EXECUTION_ARTIFACT_ID = "formowl_issue56_independent_mail_holdout_uat_execution_v2"
CONSUMED_CLAIM_ARTIFACT_ID = "formowl_issue56_independent_mail_holdout_uat_consumed_claim_v2"
HOLDOUT_ORACLE_FREE_PROJECTION_ARTIFACT_ID = (
    "formowl_issue56_independent_mail_holdout_oracle_free_projection_v1"
)
HOLDOUT_ORACLE_FREE_PROJECTION_SCHEMA_VERSION = 1
SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_ID = "independent_mail_holdout_source_identifier_graph_adapter_v3"
SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_FINGERPRINT = sha256_json(SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_ID)
CONSUMED_CLAIM_CONTRACT_FINGERPRINT = sha256_json(
    {
        "artifact_id": CONSUMED_CLAIM_ARTIFACT_ID,
        "claim_order": "persistent_claim_before_quality_oracle_read",
        "retry_policy": "never",
        "private_manifest_decode": "after_consumed_claim_only",
        "oracle_free_projection_required": True,
        "source_identifier_contract": SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_ID,
    }
)
EXECUTION_OUTPUT_CONTRACT_FINGERPRINT = sha256_json(
    {
        "artifact_id": EXECUTION_ARTIFACT_ID,
        "persistence": "exclusive_immutable_atomic_publish",
        "public_output_policy": "hash_status_count_stratified_metrics_only",
        "source_identifier_contract": SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_ID,
    }
)
HOLDOUT_ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_manifest_v2"
HOLDOUT_REPORT_ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_preflight_v2"
RETRIEVAL_REPORT_ARTIFACT_ID = "formowl_issue56_native_source_complete_retrieval_ready_report_v1"
EXPECTED_CASE_COUNT = 41
EXPECTED_STRATA_COUNTS = {
    "exact_aggregation": 1,
    "exact_count": 1,
    "exact_set": 1,
    "graph_required": 30,
    "no_answer_near_miss_negative": 2,
    "permission_denied": 2,
    "single_document_direct_lookup": 4,
}
BASE_HOLDOUT_POLICY_ID = "independent_mail_holdout_41_v2"
EXTENSION_HOLDOUT_POLICY_ID = "independent_mail_holdout_extension_59_v1"
EXPECTED_SOURCE_MESSAGE_COUNT = 2_793
HOLDOUT_RESULT_KINDS = {
    "exact_aggregation",
    "exact_count",
    "exact_set",
    "no_answer",
    "owner_match",
    "permission_denied",
    "source_evidence",
}
EXACT_EXECUTOR_ID = "structured_exact"
DEFAULT_RETRIEVAL_ROOT = ROOT / ".test-tmp" / "issue56-native-retrieval-ready-real" / "retrieval"
DEFAULT_HOLDOUT_ROOT = ROOT / ".test-tmp" / "issue56-source-independent-mail-holdout-v2"
DEFAULT_DEVELOPMENT_ROOT = ROOT / ".test-tmp" / "issue56-source-development-uat-v1"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_HOLDOUT_PROJECTION_BYTES = 4 * 1024 * 1024
MAX_SAFE_BYTES = 512 * 1024
MAX_QUALITY_REPORT_BYTES = 16 * 1024 * 1024
MAX_BUDGET_BUNDLE_BYTES = 2 * 1024 * 1024
_SHA256_LENGTH = 71
_DEVELOPMENT_HELPER_NAMES = (
    "_run_case_arms",
    "_score_case",
    "_aggregate_arm",
    "_budget_fairness_report",
    "_paired_transitions",
    "_quality_gate_report",
)
_OWNER_GAP_IDS = ("development_uat_generic_arm_helper_unavailable",)
_SOURCE_IDENTIFIER_CLAIM_HASH_FIELDS = (
    "source_identifier_candidate_artifact_sha256",
    "source_identifier_candidate_binding_fingerprint",
    "source_identifier_candidate_schema_version_fingerprint",
    "source_identifier_identity_scope_mode_fingerprint",
    "source_identifier_identity_scope_fingerprint",
    "source_identifier_identity_scope_attestation_sha256",
    "source_identifier_identity_scope_attestation_fingerprint",
    "source_identifier_identity_scope_policy_fingerprint",
    "source_identifier_identity_scope_binding_fingerprint",
    "source_identifier_identity_scope_graph_binding_fingerprint",
    "source_identifier_operator_approval_fingerprint",
    "source_identifier_mode_approval_binding_fingerprint",
    "source_identifier_attested_asset_fingerprint",
    "source_identifier_candidate_profile_fingerprint",
    "source_identifier_extraction_policy_fingerprint",
    "source_identifier_resolution_policy_fingerprint",
    "source_identifier_complete_mention_batch_fingerprint",
    "source_identifier_complete_resolution_fingerprint",
    "source_identifier_projected_mention_batch_fingerprint",
    "source_identifier_projected_resolution_fingerprint",
    "source_identifier_complete_mention_fingerprint_set_hash",
    "source_identifier_authorized_mention_fingerprint_set_hash",
    "source_identifier_resolution_fingerprint_set_hash",
    "source_identifier_requester_projection_fingerprint_set_hash",
    "source_graph_policy_fingerprint",
    "source_identifier_adapter_fingerprint",
    "holdout_source_identifier_adapter_fingerprint",
)
_ALLOWED_PRE_HOLDOUT_AUTHORITY_BLOCKERS = frozenset(
    {
        "independent_holdout_and_transfer_final_answer_acceptance",
        "independent_holdout_final_answer_acceptance",
        "real_user_end_answer_acceptance",
        "transfer_domain_final_answer_acceptance",
    }
)
_PRIVATE_ORACLE_FIELD_NAMES = frozenset(
    {
        "adjudication",
        "answer_oracle",
        "expected_private",
    }
)
_ORACLE_FREE_CASE_FIELD_NAMES = (
    "case_id",
    "domain",
    "intent_kind",
    "pattern",
    "result_kind",
    "query_text",
    "requester_user_id",
    "required_source_observation_ids",
    "forbidden_source_observation_ids",
    "authoring_source_observation_ids",
    "required_match_count",
    "limit",
    "private_fingerprint",
    "stratum_id",
    "source_evidence_binding",
)
_HOLDOUT_PROJECTION_CLAIM_HASH_FIELDS = (
    "holdout_policy_fingerprint",
    "holdout_oracle_free_projection_sha256",
    "holdout_oracle_free_projection_fingerprint",
    "holdout_private_manifest_id",
)


class IndependentMailHoldoutUatError(RuntimeError):
    """Fail-closed validation error carrying one safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _HoldoutPolicy:
    policy_id: str
    manifest_artifact_id: str
    manifest_schema_version: int
    manifest_classification: str
    manifest_claim_boundary_status: str
    projection_artifact_id: str
    projection_schema_version: int
    source_report_artifact_id: str
    source_report_schema_version: int
    case_count: int
    strata_counts: Mapping[str, int]
    projection_contract: str

    @property
    def exact_case_count(self) -> int:
        return sum(
            int(self.strata_counts[stratum])
            for stratum in ("exact_set", "exact_count", "exact_aggregation")
        )

    @property
    def policy_fingerprint(self) -> str:
        return sha256_json(
            {
                "policy_id": self.policy_id,
                "manifest_artifact_id": self.manifest_artifact_id,
                "manifest_schema_version": self.manifest_schema_version,
                "manifest_classification": self.manifest_classification,
                "manifest_claim_boundary_status": self.manifest_claim_boundary_status,
                "projection_artifact_id": self.projection_artifact_id,
                "projection_schema_version": self.projection_schema_version,
                "source_report_artifact_id": self.source_report_artifact_id,
                "source_report_schema_version": self.source_report_schema_version,
                "case_count": self.case_count,
                "strata_counts": dict(self.strata_counts),
                "projection_contract": self.projection_contract,
            }
        )


_BASE_HOLDOUT_POLICY = _HoldoutPolicy(
    policy_id=BASE_HOLDOUT_POLICY_ID,
    manifest_artifact_id=HOLDOUT_ARTIFACT_ID,
    manifest_schema_version=2,
    manifest_classification="independent_mail_holdout",
    manifest_claim_boundary_status="sealed_independent_holdout_manifest_not_executed",
    projection_artifact_id=HOLDOUT_ORACLE_FREE_PROJECTION_ARTIFACT_ID,
    projection_schema_version=HOLDOUT_ORACLE_FREE_PROJECTION_SCHEMA_VERSION,
    source_report_artifact_id=HOLDOUT_REPORT_ARTIFACT_ID,
    source_report_schema_version=2,
    case_count=EXPECTED_CASE_COUNT,
    strata_counts=EXPECTED_STRATA_COUNTS,
    projection_contract="executable_oracle_free_projection_v1",
)
_EXTENSION_HOLDOUT_POLICY = _HoldoutPolicy(
    policy_id=EXTENSION_HOLDOUT_POLICY_ID,
    manifest_artifact_id=HOLDOUT_EXTENSION_ARTIFACT_ID,
    manifest_schema_version=HOLDOUT_EXTENSION_SCHEMA_VERSION,
    manifest_classification=HOLDOUT_EXTENSION_CLASSIFICATION,
    manifest_claim_boundary_status="source_authored_extension_not_executed",
    projection_artifact_id=HOLDOUT_EXTENSION_PROJECTION_ARTIFACT_ID,
    projection_schema_version=HOLDOUT_EXTENSION_SCHEMA_VERSION,
    source_report_artifact_id=HOLDOUT_EXTENSION_BASE_REPORT_ARTIFACT_ID,
    source_report_schema_version=2,
    case_count=HOLDOUT_EXTENSION_CASE_COUNT,
    strata_counts=dict(HOLDOUT_EXTENSION_STRATA_COUNTS),
    projection_contract="hash_only_source_authored_extension_projection_v1",
)
_HOLDOUT_POLICIES = {
    policy.policy_id: policy
    for policy in (
        _BASE_HOLDOUT_POLICY,
        _EXTENSION_HOLDOUT_POLICY,
    )
}


@dataclass(frozen=True)
class _DevelopmentAcceptance:
    completed_report_sha256: str
    operational_budget_bundle_sha256: str
    operational_budget_fingerprint: str
    operational_budget_bundle_fingerprint: str
    operational_budget_check_set_fingerprint: str
    component_binding: Mapping[str, str]
    acceptance_fingerprint: str


@dataclass(frozen=True)
class _HoldoutExecutionContext:
    observations_by_bundle_id: Mapping[str, tuple[Observation, ...]]
    observations_by_id: Mapping[str, Observation]
    observation_hash_by_id: Mapping[str, str]
    sessions: Mapping[str, Any]
    effective_graph_views: Mapping[str, Any]
    lineage_crosswalks: Mapping[str, Any]
    graph_builds: Mapping[str, Any]
    graph_ontology_binding: Mapping[str, Any]
    source_binding_fingerprint: str | None = None
    identifier_mention_batch: SourceBoundIdentifierMentionBatch | None = None
    source_identifier_binding: Mapping[str, Any] | None = None
    development_observation_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _ConsumedClaimReceipt:
    claim_path: Path
    payload: Mapping[str, Any]
    byte_sha256: str
    claim_fingerprint: str
    execution_output_binding_fingerprint: str


@dataclass(frozen=True)
class _HoldoutSourceIdentifierCandidateIntake:
    projected_batch: Any
    safe_binding: Mapping[str, Any]
    artifact_sha256: str


def _holdout_policy(policy_id: str) -> _HoldoutPolicy:
    policy = _HOLDOUT_POLICIES.get(policy_id)
    if policy is None:
        raise IndependentMailHoldoutUatError("holdout_policy_id_invalid")
    return policy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute-once", action="store_true")
    parser.add_argument(
        "--holdout-policy-id",
        choices=tuple(_HOLDOUT_POLICIES),
        default=BASE_HOLDOUT_POLICY_ID,
        help=(
            "Sealed source-author policy contract. The default preserves the "
            "existing 41-case holdout; the additive extension is an independent "
            "59-case one-shot."
        ),
    )
    parser.add_argument(
        "--retrieval-ready-bundle-artifact",
        type=Path,
        default=DEFAULT_RETRIEVAL_ROOT / "mail-evidence-bundle.private.json",
    )
    parser.add_argument("--expected-retrieval-ready-bundle-sha256", required=True)
    parser.add_argument(
        "--retrieval-ready-snapshot",
        type=Path,
        default=DEFAULT_RETRIEVAL_ROOT / "retrieval-ready-snapshot.private.json",
    )
    parser.add_argument("--expected-retrieval-ready-snapshot-sha256", required=True)
    parser.add_argument(
        "--source-completeness-report",
        type=Path,
        default=DEFAULT_RETRIEVAL_ROOT.parent / "source-report.json",
    )
    parser.add_argument("--expected-source-completeness-report-sha256", required=True)
    parser.add_argument(
        "--source-identifier-candidate-artifact",
        type=Path,
        required=True,
        help=(
            "Private source-authored identifier candidate artifact required "
            "for the explicit source-backed graph v2 holdout path."
        ),
    )
    parser.add_argument(
        "--expected-source-identifier-candidate-artifact-sha256",
        required=True,
    )
    parser.add_argument(
        "--expected-identity-scope-mode",
        required=True,
    )
    parser.add_argument("--expected-identity-scope-fingerprint", required=True)
    parser.add_argument("--expected-identity-scope-attestation-sha256", required=True)
    parser.add_argument("--expected-identity-scope-attestation-fingerprint", required=True)
    parser.add_argument("--expected-identity-scope-policy-fingerprint", required=True)
    parser.add_argument("--expected-operator-approval-fingerprint", required=True)
    parser.add_argument("--expected-spec-approval-fingerprint")
    parser.add_argument(
        "--development-manifest",
        type=Path,
        default=DEFAULT_DEVELOPMENT_ROOT / "development-manifest.private.json",
    )
    parser.add_argument("--expected-development-manifest-sha256", required=True)
    parser.add_argument(
        "--development-safe-report",
        type=Path,
        default=DEFAULT_DEVELOPMENT_ROOT / "development-manifest.safe.json",
    )
    parser.add_argument("--expected-development-safe-report-sha256", required=True)
    parser.add_argument(
        "--completed-development-quality-report",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-completed-development-quality-report-sha256",
        required=True,
    )
    parser.add_argument(
        "--operational-budget-bundle",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-operational-budget-bundle-sha256",
        required=True,
    )
    parser.add_argument(
        "--holdout-manifest",
        type=Path,
        default=DEFAULT_HOLDOUT_ROOT / "holdout-manifest.private.json",
    )
    parser.add_argument("--expected-holdout-manifest-sha256", required=True)
    parser.add_argument(
        "--holdout-oracle-free-projection",
        type=Path,
        default=DEFAULT_HOLDOUT_ROOT / "holdout-oracle-free-projection.private.json",
    )
    parser.add_argument(
        "--expected-holdout-oracle-free-projection-sha256",
        required=True,
    )
    parser.add_argument(
        "--holdout-preflight-report",
        type=Path,
        default=DEFAULT_HOLDOUT_ROOT / "holdout-preflight.safe.json",
    )
    parser.add_argument("--expected-holdout-preflight-report-sha256", required=True)
    parser.add_argument(
        "--expected-runtime-fingerprint",
        help="Master-frozen preflight runtime fingerprint; execute-once only.",
    )
    parser.add_argument(
        "--execution-output",
        type=Path,
        help="Immutable safe output path required only for execute-once.",
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
        parser.error("--expected-runtime-fingerprint and --execution-output are execute-once only")
    try:
        report = build_independent_mail_holdout_preflight(
            retrieval_bundle_path=args.retrieval_ready_bundle_artifact,
            expected_retrieval_bundle_sha256=(args.expected_retrieval_ready_bundle_sha256),
            retrieval_snapshot_path=args.retrieval_ready_snapshot,
            expected_retrieval_snapshot_sha256=(args.expected_retrieval_ready_snapshot_sha256),
            source_report_path=args.source_completeness_report,
            expected_source_report_sha256=(args.expected_source_completeness_report_sha256),
            source_identifier_candidate_artifact_path=(args.source_identifier_candidate_artifact),
            expected_source_identifier_candidate_artifact_sha256=(
                args.expected_source_identifier_candidate_artifact_sha256
            ),
            expected_identity_scope_mode=args.expected_identity_scope_mode,
            expected_identity_scope_fingerprint=(args.expected_identity_scope_fingerprint),
            expected_identity_scope_attestation_sha256=(
                args.expected_identity_scope_attestation_sha256
            ),
            expected_identity_scope_attestation_fingerprint=(
                args.expected_identity_scope_attestation_fingerprint
            ),
            expected_identity_scope_policy_fingerprint=(
                args.expected_identity_scope_policy_fingerprint
            ),
            expected_operator_approval_fingerprint=(args.expected_operator_approval_fingerprint),
            expected_spec_approval_fingerprint=(args.expected_spec_approval_fingerprint),
            development_manifest_path=args.development_manifest,
            expected_development_manifest_sha256=(args.expected_development_manifest_sha256),
            development_report_path=args.development_safe_report,
            expected_development_report_sha256=(args.expected_development_safe_report_sha256),
            completed_development_quality_report_path=(args.completed_development_quality_report),
            expected_completed_development_quality_report_sha256=(
                args.expected_completed_development_quality_report_sha256
            ),
            operational_budget_bundle_path=args.operational_budget_bundle,
            expected_operational_budget_bundle_sha256=(
                args.expected_operational_budget_bundle_sha256
            ),
            holdout_manifest_path=args.holdout_manifest,
            expected_holdout_manifest_sha256=args.expected_holdout_manifest_sha256,
            holdout_oracle_free_projection_path=(args.holdout_oracle_free_projection),
            expected_holdout_oracle_free_projection_sha256=(
                args.expected_holdout_oracle_free_projection_sha256
            ),
            holdout_report_path=args.holdout_preflight_report,
            expected_holdout_report_sha256=(args.expected_holdout_preflight_report_sha256),
            holdout_policy_id=args.holdout_policy_id,
            execute_once=args.execute_once,
            expected_runtime_fingerprint=args.expected_runtime_fingerprint,
            execution_output=args.execution_output,
        )
    except (
        ContractValidationError,
        ExecutionFingerprintValidationError,
        IndependentMailHoldoutUatError,
        RuntimeError,
    ) as exc:
        reason_code = getattr(exc, "reason_code", str(exc))
        report = _rejection_report(reason_code)
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 3
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    if args.preflight_only and report.get("preflight_status") == "passed":
        return 0
    return 0 if report["status"] == "passed" else 2


def build_independent_mail_holdout_preflight(
    *,
    retrieval_bundle_path: Path,
    expected_retrieval_bundle_sha256: str,
    retrieval_snapshot_path: Path,
    expected_retrieval_snapshot_sha256: str,
    source_report_path: Path,
    expected_source_report_sha256: str,
    source_identifier_candidate_artifact_path: Path | None = None,
    expected_source_identifier_candidate_artifact_sha256: str | None = None,
    expected_identity_scope_mode: str | None = None,
    expected_identity_scope_fingerprint: str | None = None,
    expected_identity_scope_attestation_sha256: str | None = None,
    expected_identity_scope_attestation_fingerprint: str | None = None,
    expected_identity_scope_policy_fingerprint: str | None = None,
    expected_operator_approval_fingerprint: str | None = None,
    expected_spec_approval_fingerprint: str | None = None,
    development_manifest_path: Path,
    expected_development_manifest_sha256: str,
    development_report_path: Path,
    expected_development_report_sha256: str,
    completed_development_quality_report_path: Path,
    expected_completed_development_quality_report_sha256: str,
    operational_budget_bundle_path: Path,
    expected_operational_budget_bundle_sha256: str,
    holdout_manifest_path: Path,
    expected_holdout_manifest_sha256: str,
    holdout_oracle_free_projection_path: Path,
    expected_holdout_oracle_free_projection_sha256: str,
    holdout_report_path: Path,
    expected_holdout_report_sha256: str,
    holdout_policy_id: str = BASE_HOLDOUT_POLICY_ID,
    execute_once: bool = False,
    expected_runtime_fingerprint: str | None = None,
    execution_output: Path | None = None,
) -> dict[str, Any]:
    """Validate sealed holdout inputs and produce a quality-blind safe report."""

    holdout_policy = _holdout_policy(holdout_policy_id)
    if execute_once:
        _require_sha256(
            expected_runtime_fingerprint,
            "master_runtime_fingerprint_missing_or_invalid",
        )
        if execution_output is None:
            raise IndependentMailHoldoutUatError("one_shot_output_missing")
        if execution_output.exists():
            raise IndependentMailHoldoutUatError("one_shot_output_already_exists")
    elif expected_runtime_fingerprint is not None or execution_output is not None:
        raise IndependentMailHoldoutUatError("preflight_execution_inputs_not_allowed")
    source_identifier_values = (
        source_identifier_candidate_artifact_path,
        expected_source_identifier_candidate_artifact_sha256,
        expected_identity_scope_mode,
        expected_identity_scope_fingerprint,
        expected_identity_scope_attestation_sha256,
        expected_identity_scope_attestation_fingerprint,
        expected_identity_scope_policy_fingerprint,
        expected_operator_approval_fingerprint,
    )
    if not all(value is not None for value in source_identifier_values):
        raise IndependentMailHoldoutUatError("source_identifier_v3_candidate_artifact_required")
    _require_sha256(
        expected_source_identifier_candidate_artifact_sha256,
        "source_identifier_candidate_artifact_seal_invalid",
    )
    if expected_identity_scope_mode not in {
        TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
        WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    }:
        raise IndependentMailHoldoutUatError("expected_identity_scope_mode_invalid")
    _require_sha256(
        expected_identity_scope_fingerprint,
        "expected_identity_scope_fingerprint_invalid",
    )
    _require_sha256(
        expected_identity_scope_attestation_sha256,
        "expected_identity_scope_attestation_sha256_invalid",
    )
    _require_sha256(
        expected_identity_scope_attestation_fingerprint,
        "expected_identity_scope_attestation_fingerprint_invalid",
    )
    _require_sha256(
        expected_identity_scope_policy_fingerprint,
        "expected_identity_scope_policy_fingerprint_invalid",
    )
    _require_sha256(
        expected_operator_approval_fingerprint,
        "expected_operator_approval_fingerprint_invalid",
    )
    if expected_identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        _require_sha256(
            expected_spec_approval_fingerprint,
            "expected_spec_approval_fingerprint_invalid",
        )
    elif expected_spec_approval_fingerprint is not None:
        raise IndependentMailHoldoutUatError("tenant_workspace_spec_approval_fingerprint_forbidden")

    bundle_bytes, bundle_artifact = _read_sealed_json(
        retrieval_bundle_path,
        expected_retrieval_bundle_sha256,
        max_bytes=MAX_BUNDLE_BYTES,
        invalid_reason="retrieval_bundle_missing_or_invalid",
        seal_reason="retrieval_bundle_seal_mismatch",
    )
    snapshot_bytes, retrieval_snapshot = _read_sealed_json(
        retrieval_snapshot_path,
        expected_retrieval_snapshot_sha256,
        max_bytes=MAX_SNAPSHOT_BYTES,
        invalid_reason="retrieval_snapshot_missing_or_invalid",
        seal_reason="retrieval_snapshot_seal_mismatch",
    )
    source_report_bytes, source_report = _read_sealed_json(
        source_report_path,
        expected_source_report_sha256,
        max_bytes=MAX_SAFE_BYTES,
        invalid_reason="source_report_missing_or_invalid",
        seal_reason="source_report_seal_mismatch",
    )
    development_bytes, development_manifest = _read_sealed_json(
        development_manifest_path,
        expected_development_manifest_sha256,
        max_bytes=MAX_MANIFEST_BYTES,
        invalid_reason="development_manifest_missing_or_invalid",
        seal_reason="development_manifest_seal_mismatch",
    )
    development_report_bytes, development_report = _read_sealed_json(
        development_report_path,
        expected_development_report_sha256,
        max_bytes=MAX_SAFE_BYTES,
        invalid_reason="development_report_missing_or_invalid",
        seal_reason="development_report_seal_mismatch",
    )
    holdout_bytes = _read_sealed_bytes(
        holdout_manifest_path,
        expected_holdout_manifest_sha256,
        max_bytes=MAX_MANIFEST_BYTES,
        invalid_reason="holdout_manifest_missing_or_invalid",
        seal_reason="holdout_manifest_seal_mismatch",
    )
    holdout_projection_bytes, holdout_projection = _read_sealed_json(
        holdout_oracle_free_projection_path,
        expected_holdout_oracle_free_projection_sha256,
        max_bytes=MAX_HOLDOUT_PROJECTION_BYTES,
        invalid_reason="holdout_oracle_free_projection_missing_or_invalid",
        seal_reason="holdout_oracle_free_projection_seal_mismatch",
    )
    holdout_report_bytes, holdout_report = _read_sealed_json(
        holdout_report_path,
        expected_holdout_report_sha256,
        max_bytes=MAX_SAFE_BYTES,
        invalid_reason="holdout_report_missing_or_invalid",
        seal_reason="holdout_report_seal_mismatch",
    )
    development_acceptance = _validate_development_acceptance(
        completed_report_path=completed_development_quality_report_path,
        expected_completed_report_sha256=(expected_completed_development_quality_report_sha256),
        operational_budget_bundle_path=operational_budget_bundle_path,
        expected_operational_budget_bundle_sha256=(expected_operational_budget_bundle_sha256),
    )

    bundle_payload = _validated_bundle_artifact(bundle_artifact)
    bundle = MailEvidenceBundle.from_dict(bundle_payload)
    if bundle.to_dict() != bundle_payload:
        raise IndependentMailHoldoutUatError("mail_bundle_round_trip_drift")
    _validate_native_retrieval_snapshot(retrieval_snapshot)
    _validate_source_bindings(
        bundle_artifact=bundle_artifact,
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        expected_message_count=EXPECTED_SOURCE_MESSAGE_COUNT,
    )
    _validate_source_report(
        source_report,
        source_report_sha256=_sha256_bytes(source_report_bytes),
        bundle_artifact=bundle_artifact,
        retrieval_snapshot=retrieval_snapshot,
    )
    observations_by_id, observation_hash_by_id = _validated_retrieval_observation_maps(
        retrieval_snapshot
    )
    assert source_identifier_candidate_artifact_path is not None
    assert expected_source_identifier_candidate_artifact_sha256 is not None
    assert expected_identity_scope_mode is not None
    assert expected_identity_scope_fingerprint is not None
    assert expected_identity_scope_attestation_sha256 is not None
    assert expected_identity_scope_attestation_fingerprint is not None
    assert expected_identity_scope_policy_fingerprint is not None
    assert expected_operator_approval_fingerprint is not None
    source_identifier_intake = _load_holdout_source_identifier_candidate_intake(
        artifact_path=source_identifier_candidate_artifact_path,
        expected_artifact_sha256=(expected_source_identifier_candidate_artifact_sha256),
        expected_identity_scope_mode=expected_identity_scope_mode,
        expected_identity_scope_fingerprint=expected_identity_scope_fingerprint,
        expected_identity_scope_attestation_sha256=(expected_identity_scope_attestation_sha256),
        expected_identity_scope_attestation_fingerprint=(
            expected_identity_scope_attestation_fingerprint
        ),
        expected_identity_scope_policy_fingerprint=(expected_identity_scope_policy_fingerprint),
        expected_operator_approval_fingerprint=(expected_operator_approval_fingerprint),
        expected_spec_approval_fingerprint=expected_spec_approval_fingerprint,
        expected_workspace_id=bundle.mail_import_session.workspace_id,
        observations_by_id=observations_by_id,
        observation_hash_by_id=observation_hash_by_id,
        retrieval_snapshot=retrieval_snapshot,
        retrieval_snapshot_sha256=_sha256_bytes(snapshot_bytes),
        retrieval_report_sha256=_sha256_bytes(source_report_bytes),
        retrieval_report_fingerprint=str(source_report["report_fingerprint"]),
    )
    development_observation_ids, development_registry_fingerprint = (
        _validated_development_exclusion_registry(
            manifest=development_manifest,
            manifest_bytes=development_bytes,
            safe_report=development_report,
        )
    )
    lineage = _validate_holdout_projection(
        holdout_policy=holdout_policy,
        projection=holdout_projection,
        manifest_sha256=_sha256_bytes(holdout_bytes),
        safe_report=holdout_report,
        safe_report_sha256=_sha256_bytes(holdout_report_bytes),
        retrieval_bundle_sha256=_sha256_bytes(bundle_bytes),
        retrieval_snapshot_sha256=_sha256_bytes(snapshot_bytes),
        bundle_artifact=bundle_artifact,
        bundle=bundle,
        retrieval_snapshot=retrieval_snapshot,
        source_report_sha256=_sha256_bytes(source_report_bytes),
        development_manifest=development_manifest,
        development_manifest_sha256=_sha256_bytes(development_bytes),
        development_report_sha256=_sha256_bytes(development_report_bytes),
        development_observation_ids=development_observation_ids,
        development_registry_fingerprint=development_registry_fingerprint,
    )

    execution_contract = _development_execution_contract()
    source_binding_fingerprint = sha256_json(
        {
            "holdout_policy_id": holdout_policy.policy_id,
            "holdout_policy_fingerprint": holdout_policy.policy_fingerprint,
            "holdout_case_count": holdout_policy.case_count,
            "holdout_strata_counts": dict(holdout_policy.strata_counts),
            "source_snapshot_fingerprint": retrieval_snapshot["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": retrieval_snapshot["source_inventory_fingerprint"],
            "source_provenance_fingerprint": retrieval_snapshot["source_provenance_fingerprint"],
            "retrieval_snapshot_fingerprint": retrieval_snapshot["snapshot_fingerprint"],
            "holdout_manifest_sha256": _sha256_bytes(holdout_bytes),
            "holdout_manifest_fingerprint": lineage["manifest_fingerprint"],
            "holdout_private_manifest_id": lineage["private_manifest_id"],
            "holdout_oracle_free_projection_sha256": _sha256_bytes(holdout_projection_bytes),
            "holdout_oracle_free_projection_fingerprint": (
                holdout_projection["projection_fingerprint"]
            ),
            "partition_fingerprint": lineage["partition_fingerprint"],
            "source_identifier_candidate_artifact_sha256": (
                source_identifier_intake.artifact_sha256
            ),
            "source_identifier_candidate_binding_fingerprint": (
                source_identifier_intake.safe_binding["binding_fingerprint"]
            ),
            "source_identifier_candidate_schema_version": (
                source_identifier_intake.safe_binding["candidate_artifact_schema_version"]
            ),
            "identity_scope_mode": source_identifier_intake.safe_binding["identity_scope_mode"],
            "identity_scope_fingerprint": source_identifier_intake.safe_binding[
                "identity_scope_fingerprint"
            ],
            "identity_scope_attestation_fingerprint": (
                source_identifier_intake.safe_binding["identity_scope_attestation_fingerprint"]
            ),
            "identity_scope_policy_fingerprint": source_identifier_intake.safe_binding[
                "identity_scope_policy_fingerprint"
            ],
            "identity_scope_binding_fingerprint": source_identifier_intake.safe_binding[
                "identity_scope_binding_fingerprint"
            ],
            "identity_scope_graph_binding_fingerprint": (
                source_identifier_intake.safe_binding["identity_scope_graph_binding_fingerprint"]
            ),
            "operator_approval_fingerprint": source_identifier_intake.safe_binding[
                "operator_approval_fingerprint"
            ],
            "mode_approval_fingerprint": source_identifier_intake.safe_binding[
                "mode_approval_fingerprint"
            ],
            "spec_approval_fingerprint": source_identifier_intake.safe_binding.get(
                "spec_approval_fingerprint"
            ),
        }
    )
    execution_context = _build_holdout_execution_context(
        bundle=bundle,
        observations_by_id=observations_by_id,
        observation_hash_by_id=observation_hash_by_id,
        source_binding_fingerprint=source_binding_fingerprint,
        cases=_preflight_execution_cases(
            holdout_policy=holdout_policy,
            projection=holdout_projection,
            bundle=bundle,
        ),
        identifier_mention_batch=source_identifier_intake.projected_batch,
        source_identifier_binding=source_identifier_intake.safe_binding,
        development_observation_ids=development_observation_ids,
    )
    runtime_binding = _build_runtime_binding(
        source_binding_fingerprint=source_binding_fingerprint,
        index_fingerprint=str(retrieval_snapshot["index_fingerprint"]),
        tokenizer_profile_fingerprint=str(retrieval_snapshot["tokenizer_profile_fingerprint"]),
        execution_contract=execution_contract,
        development_acceptance=development_acceptance,
        graph_ontology_binding=execution_context.graph_ontology_binding,
        source_identifier_binding=source_identifier_intake.safe_binding,
    )
    runtime_fingerprint = runtime_binding["runtime_fingerprint"]
    if execute_once and expected_runtime_fingerprint != runtime_fingerprint:
        raise IndependentMailHoldoutUatError("master_runtime_fingerprint_mismatch")

    owner_gap_ids = _owner_gap_ids(
        holdout_projection,
        holdout_policy=holdout_policy,
        referenced_observation_type_counts=lineage["observation_type_counts"],
    )
    blocker_ids = list(owner_gap_ids)
    if not execute_once:
        blocker_ids.append("master_runtime_fingerprint_not_frozen")
        blocker_ids.append("independent_holdout_quality_not_executed")
    elif owner_gap_ids:
        blocker_ids.append("independent_holdout_quality_not_executed")

    report: dict[str, Any] = {
        "artifact_id": REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if blocker_ids else "passed",
        "preflight_status": "passed",
        "artifact_seal_status": "passed",
        "source_completeness_status": "passed",
        "source_lineage_status": "passed_sealed_hash_projection",
        "source_identifier_candidate_status": "passed_sealed",
        "source_identifier_candidate_only_status": "passed",
        "source_identifier_overflow_status": "passed_zero",
        "source_identifier_v3_graph_status": "passed",
        "observation_readability_status": "deferred_until_consumed_claim",
        "observation_projection_status": "passed_sealed_hash_projection",
        "permission_fixture_status": "deferred_until_consumed_claim",
        "development_disjointness_status": "passed",
        "strata_coverage_status": "passed",
        "runtime_pin_status": "passed",
        "development_quality_acceptance_status": "passed",
        "operational_budget_binding_status": "passed",
        "pre_holdout_authority_status": "passed",
        "graph_artifact_binding_status": "passed",
        "ontology_artifact_binding_status": "passed",
        "runtime_freeze_status": ("matched" if execute_once else "pending_master_confirmation"),
        "owner_execution_status": "blocked" if owner_gap_ids else "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "counts": {
            "artifact_seal_count": 11,
            "case_count": lineage["case_count"],
            "stratum_count": len(lineage["strata_counts"]),
            "development_case_count": int(development_manifest["case_count"]),
            "development_holdout_observation_overlap_count": 0,
            "development_holdout_message_overlap_count": 0,
            "development_holdout_thread_overlap_count": 0,
            "readable_holdout_observation_count": lineage["readable_observation_count"],
            "readable_holdout_header_observation_count": lineage["observation_type_counts"][
                "email_header"
            ],
            "readable_holdout_body_observation_count": lineage["observation_type_counts"][
                "email_body_segment"
            ],
            "sealed_holdout_observation_reference_count": lineage["projected_observation_count"],
            "projected_holdout_observation_count": lineage["projected_observation_count"],
            "projected_holdout_header_observation_count": lineage["projection_type_counts"][
                "email_header"
            ],
            "projected_holdout_body_observation_count": lineage["projection_type_counts"][
                "email_body_segment"
            ],
            "permission_denied_case_count": lineage["permission_denied_case_count"],
            "source_message_count": len(bundle.messages),
            "source_body_segment_count": len(bundle.body_segments),
            "source_inventory_item_count": retrieval_snapshot["counts"][
                "source_inventory_item_count"
            ],
            "unexplained_loss_count": retrieval_snapshot["counts"]["unexplained_loss_count"],
            "arm_count": len(development_uat.ARM_IDS),
            "full_case_arm_count": len(development_uat.FULL_CASE_ARM_IDS),
            "exact_executor_count": 1,
            "development_quality_check_count": len(development_acceptance.component_binding),
            "permission_scoped_graph_count": execution_context.graph_ontology_binding[
                "permission_scoped_graph_count"
            ],
            "graph_node_count": execution_context.graph_ontology_binding["graph_node_count"],
            "graph_edge_count": execution_context.graph_ontology_binding["graph_edge_count"],
            "ontology_revision_count": execution_context.graph_ontology_binding[
                "ontology_revision_count"
            ],
            "source_identifier_occurrence_count": source_identifier_intake.safe_binding[
                "selected_mention_count"
            ],
            "source_identifier_resolved_candidate_count": (
                source_identifier_intake.safe_binding["selected_resolved_candidate_count"]
            ),
            "source_identifier_overflow_count": source_identifier_intake.safe_binding[
                "overflow_count"
            ],
            "sealed_quality_field_read_count": 0,
            "executed_case_count": 0,
            "permission_leakage_measurement_count": 0,
            "citation_measurement_count": 0,
            "graph_hop_measurement_count": 0,
            "blocker_count": len(blocker_ids),
        },
        "strata_counts": lineage["strata_counts"],
        "metrics": {
            "permission_leakage_status": "not_measured",
            "citation_status": "not_measured",
            "no_answer_status": "not_measured",
            "exact_execution_status": "not_measured",
            "graph_hop_evidence_status": "not_measured",
            "operational_budget_status": "not_measured",
            "quality_status": "not_read",
        },
        "hashes": {
            "retrieval_bundle_sha256": _sha256_bytes(bundle_bytes),
            "retrieval_snapshot_sha256": _sha256_bytes(snapshot_bytes),
            "source_report_sha256": _sha256_bytes(source_report_bytes),
            "development_manifest_sha256": _sha256_bytes(development_bytes),
            "development_report_sha256": _sha256_bytes(development_report_bytes),
            "holdout_manifest_sha256": _sha256_bytes(holdout_bytes),
            "holdout_policy_fingerprint": holdout_policy.policy_fingerprint,
            "holdout_oracle_free_projection_sha256": _sha256_bytes(holdout_projection_bytes),
            "holdout_oracle_free_projection_fingerprint": (
                holdout_projection["projection_fingerprint"]
            ),
            "holdout_private_manifest_id": lineage["private_manifest_id"],
            "holdout_report_sha256": _sha256_bytes(holdout_report_bytes),
            "source_identifier_candidate_artifact_sha256": (
                source_identifier_intake.artifact_sha256
            ),
            "source_identifier_candidate_artifact_fingerprint": (
                source_identifier_intake.safe_binding["source_artifact_fingerprint"]
            ),
            "source_identifier_candidate_binding_fingerprint": (
                source_identifier_intake.safe_binding["binding_fingerprint"]
            ),
            "source_identifier_candidate_schema_version_fingerprint": sha256_json(
                source_identifier_intake.safe_binding["candidate_artifact_schema_version"]
            ),
            "source_identifier_identity_scope_mode_fingerprint": sha256_json(
                source_identifier_intake.safe_binding["identity_scope_mode"]
            ),
            "source_identifier_identity_scope_fingerprint": (
                source_identifier_intake.safe_binding["identity_scope_fingerprint"]
            ),
            "source_identifier_identity_scope_attestation_sha256": (
                source_identifier_intake.safe_binding["identity_scope_attestation_byte_sha256"]
            ),
            "source_identifier_identity_scope_attestation_fingerprint": (
                source_identifier_intake.safe_binding["identity_scope_attestation_fingerprint"]
            ),
            "source_identifier_identity_scope_policy_fingerprint": (
                source_identifier_intake.safe_binding["identity_scope_policy_fingerprint"]
            ),
            "source_identifier_identity_scope_binding_fingerprint": (
                source_identifier_intake.safe_binding["identity_scope_binding_fingerprint"]
            ),
            "source_identifier_identity_scope_graph_binding_fingerprint": (
                source_identifier_intake.safe_binding["identity_scope_graph_binding_fingerprint"]
            ),
            "source_identifier_operator_approval_fingerprint": (
                source_identifier_intake.safe_binding["operator_approval_fingerprint"]
            ),
            "source_identifier_mode_approval_binding_fingerprint": (
                source_identifier_intake.safe_binding["mode_approval_binding_fingerprint"]
            ),
            "source_identifier_attested_asset_fingerprint": (
                source_identifier_intake.safe_binding["attested_asset_fingerprint"]
            ),
            "source_identifier_candidate_profile_fingerprint": (
                source_identifier_intake.safe_binding["candidate_admission_profile_fingerprint"]
            ),
            "source_identifier_extraction_policy_fingerprint": (
                source_identifier_intake.safe_binding["extraction_policy_fingerprint"]
            ),
            "source_identifier_resolution_policy_fingerprint": (
                source_identifier_intake.safe_binding["resolution_policy_fingerprint"]
            ),
            "source_identifier_complete_mention_batch_fingerprint": (
                source_identifier_intake.safe_binding["complete_mention_batch_fingerprint"]
            ),
            "source_identifier_complete_resolution_fingerprint": (
                source_identifier_intake.safe_binding["complete_resolution_fingerprint"]
            ),
            "source_identifier_projected_mention_batch_fingerprint": (
                source_identifier_intake.safe_binding["selected_mention_batch_fingerprint"]
            ),
            "source_identifier_projected_resolution_fingerprint": (
                source_identifier_intake.safe_binding["selected_resolution_fingerprint"]
            ),
            "source_identifier_complete_mention_fingerprint_set_hash": (
                runtime_binding["source_identifier_complete_mention_fingerprint_set_hash"]
            ),
            "source_identifier_authorized_mention_fingerprint_set_hash": (
                runtime_binding["source_identifier_authorized_mention_fingerprint_set_hash"]
            ),
            "source_identifier_resolution_fingerprint_set_hash": (
                runtime_binding["source_identifier_resolution_fingerprint_set_hash"]
            ),
            "source_identifier_requester_projection_fingerprint_set_hash": (
                runtime_binding["source_identifier_requester_projection_fingerprint_set_hash"]
            ),
            "source_graph_policy_fingerprint": source_identifier_intake.safe_binding[
                "source_graph_policy_fingerprint"
            ],
            "source_identifier_adapter_fingerprint": (
                source_identifier_intake.safe_binding["source_identifier_adapter_fingerprint"]
            ),
            "holdout_source_identifier_adapter_fingerprint": (
                SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_FINGERPRINT
            ),
            "completed_development_quality_report_sha256": (
                development_acceptance.completed_report_sha256
            ),
            "operational_budget_bundle_sha256": (
                development_acceptance.operational_budget_bundle_sha256
            ),
            "development_acceptance_fingerprint": (development_acceptance.acceptance_fingerprint),
            "development_component_binding_fingerprint": (
                development_acceptance.component_binding["component_binding_fingerprint"]
            ),
            "source_binding_fingerprint": source_binding_fingerprint,
            "source_snapshot_fingerprint": retrieval_snapshot["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": retrieval_snapshot["source_inventory_fingerprint"],
            "source_provenance_fingerprint": retrieval_snapshot["source_provenance_fingerprint"],
            "retrieval_snapshot_fingerprint": retrieval_snapshot["snapshot_fingerprint"],
            "lexical_profile_fingerprint": runtime_binding["tokenizer_profile_fingerprint"],
            "index_fingerprint": runtime_binding["index_fingerprint"],
            "dense_profile_fingerprint": runtime_binding["dense_profile_fingerprint"],
            "runtime_component_fingerprint": runtime_binding["runtime_component_fingerprint"],
            "runtime_method_fingerprint": runtime_binding["runtime_method_fingerprint"],
            "graph_adapter_fingerprint": runtime_binding["graph_adapter_fingerprint"],
            "graph_artifact_fingerprint": runtime_binding["graph_artifact_fingerprint"],
            "graph_revision_fingerprint": runtime_binding["graph_revision_fingerprint"],
            "graph_revision_id_fingerprint": runtime_binding["graph_revision_id_fingerprint"],
            "graph_ontology_binding_fingerprint": runtime_binding[
                "graph_ontology_binding_fingerprint"
            ],
            "ontology_target_fingerprint": runtime_binding["ontology_target_fingerprint"],
            "ontology_artifact_fingerprint": runtime_binding["ontology_artifact_fingerprint"],
            "ontology_revision_fingerprint": runtime_binding["ontology_revision_fingerprint"],
            "answer_model_fingerprint": runtime_binding["answer_model_fingerprint"],
            "answer_prompt_fingerprint": runtime_binding["answer_prompt_fingerprint"],
            "answer_budget_fingerprint": runtime_binding["answer_budget_fingerprint"],
            "evaluator_fingerprint": runtime_binding["evaluator_fingerprint"],
            "operational_budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
            "code_attestation_fingerprint": runtime_binding["code_attestation_fingerprint"],
            "code_tree_fingerprint": runtime_binding["code_tree_fingerprint"],
            "image_attestation_fingerprint": runtime_binding["image_attestation_fingerprint"],
            "image_id": runtime_binding["image_id"],
            "image_metadata_fingerprint": runtime_binding["image_metadata_fingerprint"],
            "authority_attestation_fingerprint": runtime_binding[
                "authority_attestation_fingerprint"
            ],
            "authority_state_fingerprint": runtime_binding["authority_state_fingerprint"],
            "authority_execution_fingerprint": runtime_binding["authority_execution_fingerprint"],
            "authority_blocking_gate_set_fingerprint": runtime_binding[
                "authority_blocking_gate_set_fingerprint"
            ],
            "consumed_claim_contract_fingerprint": runtime_binding[
                "consumed_claim_contract_fingerprint"
            ],
            "execution_output_contract_fingerprint": runtime_binding[
                "execution_output_contract_fingerprint"
            ],
            "execution_contract_fingerprint": sha256_json(execution_contract),
            "observation_projection_fingerprint": lineage["projection_fingerprint"],
            "runtime_fingerprint": runtime_fingerprint,
            "owner_gap_set_fingerprint": sha256_json(owner_gap_ids),
            "blocker_set_fingerprint": sha256_json(blocker_ids),
        },
        "blocker_hashes": [sha256_json(blocker_id) for blocker_id in blocker_ids],
    }
    if (
        source_identifier_intake.safe_binding["identity_scope_mode_status"]
        == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    ):
        report["hashes"]["source_identifier_spec_approval_fingerprint"] = (
            source_identifier_intake.safe_binding["spec_approval_fingerprint"]
        )
    report["hashes"]["preflight_input_fingerprint"] = sha256_json(
        {
            "artifact_seals": [
                report["hashes"]["retrieval_bundle_sha256"],
                report["hashes"]["retrieval_snapshot_sha256"],
                report["hashes"]["source_report_sha256"],
                report["hashes"]["development_manifest_sha256"],
                report["hashes"]["development_report_sha256"],
                report["hashes"]["completed_development_quality_report_sha256"],
                report["hashes"]["operational_budget_bundle_sha256"],
                report["hashes"]["holdout_manifest_sha256"],
                report["hashes"]["holdout_oracle_free_projection_sha256"],
                report["hashes"]["holdout_report_sha256"],
                report["hashes"]["source_identifier_candidate_artifact_sha256"],
            ],
            "runtime_fingerprint": runtime_fingerprint,
            "execution_contract_fingerprint": report["hashes"]["execution_contract_fingerprint"],
        }
    )
    report["hashes"]["report_fingerprint"] = _report_fingerprint(report)
    _validate_public_report(report)
    if execute_once:
        if blocker_ids:
            raise IndependentMailHoldoutUatError(blocker_ids[0])
        assert execution_output is not None
        return _execute_independent_holdout_once(
            preflight_report=report,
            execution_context=execution_context,
            bundle=bundle,
            oracle_free_projection=holdout_projection,
            holdout_policy=holdout_policy,
            manifest_path=holdout_manifest_path,
            expected_manifest_sha256=_sha256_bytes(holdout_bytes),
            runtime_binding=runtime_binding,
            execution_output=execution_output,
        )
    return report


def validate_shared_arm_fingerprints(
    arm_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """Require all development arms to share one exact frozen runtime."""

    if set(arm_bindings) != set(development_uat.ARM_IDS):
        raise IndependentMailHoldoutUatError("holdout_arm_set_mismatch")
    required_fields = (
        "tokenizer_profile_fingerprint",
        "index_fingerprint",
        "dense_profile_fingerprint",
        "runtime_component_fingerprint",
        "graph_adapter_fingerprint",
        "ontology_target_fingerprint",
        "answer_model_fingerprint",
        "answer_prompt_fingerprint",
        "answer_budget_fingerprint",
        "evaluator_fingerprint",
        "operational_budget_fingerprint",
        "code_tree_fingerprint",
        "image_id",
        "authority_execution_fingerprint",
        "source_identifier_candidate_artifact_sha256",
        "source_identifier_candidate_binding_fingerprint",
        "source_identifier_candidate_schema_version_fingerprint",
        "source_identifier_identity_scope_mode_fingerprint",
        "source_identifier_identity_scope_fingerprint",
        "source_identifier_identity_scope_attestation_sha256",
        "source_identifier_identity_scope_attestation_fingerprint",
        "source_identifier_identity_scope_policy_fingerprint",
        "source_identifier_identity_scope_binding_fingerprint",
        "source_identifier_identity_scope_graph_binding_fingerprint",
        "source_identifier_operator_approval_fingerprint",
        "source_identifier_mode_approval_binding_fingerprint",
        "source_identifier_attested_asset_fingerprint",
        "source_identifier_candidate_profile_fingerprint",
        "source_identifier_extraction_policy_fingerprint",
        "source_identifier_resolution_policy_fingerprint",
        "source_identifier_complete_mention_batch_fingerprint",
        "source_identifier_complete_resolution_fingerprint",
        "source_identifier_projected_mention_batch_fingerprint",
        "source_identifier_projected_resolution_fingerprint",
        "source_identifier_complete_mention_fingerprint_set_hash",
        "source_identifier_authorized_mention_fingerprint_set_hash",
        "source_identifier_resolution_fingerprint_set_hash",
        "source_identifier_requester_projection_fingerprint_set_hash",
        "source_graph_policy_fingerprint",
        "source_identifier_adapter_fingerprint",
        "holdout_source_identifier_adapter_fingerprint",
    )
    shared: dict[str, str] = {}
    for field_name in required_fields:
        values = {
            _require_sha256(
                binding.get(field_name),
                "holdout_shared_fingerprint_missing_or_invalid",
            )
            for binding in arm_bindings.values()
        }
        if len(values) != 1:
            raise IndependentMailHoldoutUatError("holdout_shared_fingerprint_mismatch")
        shared[field_name] = next(iter(values))
    return shared


def validate_execution_safety_metrics(
    *,
    case_count: int,
    permission_leakage_count: int,
    unresolved_citation_count: int,
    unresolved_graph_hop_count: int,
    exact_incomplete_count: int,
    holdout_policy_id: str = BASE_HOLDOUT_POLICY_ID,
) -> dict[str, int]:
    """Validate only the universal safety gates of a future one-shot run."""

    holdout_policy = _holdout_policy(holdout_policy_id)
    if case_count != holdout_policy.case_count:
        raise IndependentMailHoldoutUatError("holdout_execution_case_count_mismatch")
    for value, reason in (
        (permission_leakage_count, "holdout_permission_leakage_detected"),
        (unresolved_citation_count, "holdout_citation_lineage_unresolved"),
        (unresolved_graph_hop_count, "holdout_graph_hop_lineage_unresolved"),
        (exact_incomplete_count, "holdout_exact_execution_incomplete"),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value != 0:
            raise IndependentMailHoldoutUatError(reason)
    return {
        "case_count": case_count,
        "permission_leakage_count": permission_leakage_count,
        "unresolved_citation_count": unresolved_citation_count,
        "unresolved_graph_hop_count": unresolved_graph_hop_count,
        "exact_incomplete_count": exact_incomplete_count,
    }


def _validate_development_acceptance(
    *,
    completed_report_path: Path,
    expected_completed_report_sha256: str,
    operational_budget_bundle_path: Path,
    expected_operational_budget_bundle_sha256: str,
) -> _DevelopmentAcceptance:
    """Validate the sealed development result after its budget is bound."""

    completed_bytes, _completed_report = _read_sealed_json(
        completed_report_path,
        expected_completed_report_sha256,
        max_bytes=MAX_QUALITY_REPORT_BYTES,
        invalid_reason="completed_development_quality_report_missing_or_invalid",
        seal_reason="completed_development_quality_report_seal_mismatch",
    )
    budget_bytes, budget_bundle = _read_sealed_json(
        operational_budget_bundle_path,
        expected_operational_budget_bundle_sha256,
        max_bytes=MAX_BUDGET_BUNDLE_BYTES,
        invalid_reason="operational_budget_bundle_missing_or_invalid",
        seal_reason="operational_budget_bundle_seal_mismatch",
    )
    try:
        accepted_report = development_uat.bind_completed_uat_operational_budget(
            completed_report_path=completed_report_path,
            expected_completed_report_sha256=expected_completed_report_sha256,
            operational_budget_bundle_path=operational_budget_bundle_path,
            expected_operational_budget_bundle_sha256=(expected_operational_budget_bundle_sha256),
        )
        component_binding = development_uat._validated_completed_uat_component_binding(
            accepted_report
        )
    except ContractValidationError as exc:
        raise IndependentMailHoldoutUatError(
            "development_quality_or_budget_acceptance_invalid"
        ) from exc
    if (
        accepted_report.get("status") != "passed"
        or accepted_report.get("quality_gate_status") != "passed"
    ):
        raise IndependentMailHoldoutUatError("development_quality_gate_not_passed")
    quality_gate = accepted_report.get("quality_gate")
    quality_checks = quality_gate.get("checks") if isinstance(quality_gate, Mapping) else None
    if (
        not isinstance(quality_gate, Mapping)
        or quality_gate.get("status") != "passed"
        or not isinstance(quality_checks, Mapping)
        or not quality_checks
        or any(
            not isinstance(check, Mapping) or check.get("status") != "passed"
            for check in quality_checks.values()
        )
    ):
        raise IndependentMailHoldoutUatError("development_quality_gate_not_passed")
    operational_binding = accepted_report.get("operational_budget_binding")
    if (
        not isinstance(operational_binding, Mapping)
        or operational_binding.get("status") != "passed"
        or operational_binding.get("completed_report_byte_hash") != expected_completed_report_sha256
        or operational_binding.get("budget_bundle_byte_hash")
        != expected_operational_budget_bundle_sha256
        or operational_binding.get("budget_fingerprint") != FROZEN_BUDGET_FINGERPRINT
        or budget_bundle.get("status") != "passed"
        or budget_bundle.get("budget_fingerprint") != FROZEN_BUDGET_FINGERPRINT
        or budget_bundle.get("bundle_fingerprint")
        != operational_binding.get("budget_bundle_fingerprint")
        or budget_bundle.get("check_set_fingerprint")
        != operational_binding.get("budget_check_set_fingerprint")
    ):
        raise IndependentMailHoldoutUatError("development_operational_budget_binding_mismatch")
    if _sha256_bytes(completed_report_path.read_bytes()) != _sha256_bytes(
        completed_bytes
    ) or _sha256_bytes(operational_budget_bundle_path.read_bytes()) != _sha256_bytes(budget_bytes):
        raise IndependentMailHoldoutUatError(
            "development_acceptance_artifact_changed_during_validation"
        )
    acceptance_payload = {
        "completed_report_sha256": _sha256_bytes(completed_bytes),
        "operational_budget_bundle_sha256": _sha256_bytes(budget_bytes),
        "operational_budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
        "operational_budget_bundle_fingerprint": budget_bundle["bundle_fingerprint"],
        "operational_budget_check_set_fingerprint": budget_bundle["check_set_fingerprint"],
        "component_binding_fingerprint": component_binding["component_binding_fingerprint"],
        "quality_check_set_fingerprint": sha256_json(quality_checks),
    }
    return _DevelopmentAcceptance(
        completed_report_sha256=acceptance_payload["completed_report_sha256"],
        operational_budget_bundle_sha256=acceptance_payload["operational_budget_bundle_sha256"],
        operational_budget_fingerprint=FROZEN_BUDGET_FINGERPRINT,
        operational_budget_bundle_fingerprint=acceptance_payload[
            "operational_budget_bundle_fingerprint"
        ],
        operational_budget_check_set_fingerprint=acceptance_payload[
            "operational_budget_check_set_fingerprint"
        ],
        component_binding={key: str(value) for key, value in component_binding.items()},
        acceptance_fingerprint=sha256_json(acceptance_payload),
    )


def _validated_retrieval_observation_maps(
    retrieval_snapshot: Mapping[str, Any],
) -> tuple[dict[str, Observation], dict[str, str]]:
    parsed_rows = retrieval_snapshot.get("parsed_mail_observations")
    if not isinstance(parsed_rows, list) or not parsed_rows:
        raise IndependentMailHoldoutUatError("retrieval_observation_snapshot_invalid")
    observations_by_id: dict[str, Observation] = {}
    for row in parsed_rows:
        if not isinstance(row, dict):
            raise IndependentMailHoldoutUatError("retrieval_observation_invalid")
        observation = Observation.from_dict(row)
        if observation.to_dict() != row or observation.observation_id in observations_by_id:
            raise IndependentMailHoldoutUatError("retrieval_observation_round_trip_failed")
        observations_by_id[observation.observation_id] = observation
    observation_hash_by_id = {
        observation_id: sha256_json(observation.to_dict())
        for observation_id, observation in observations_by_id.items()
    }
    if sha256_json([row for row in parsed_rows]) != retrieval_snapshot.get(
        "parsed_observation_fingerprint"
    ) or sorted(observation_hash_by_id.values()) != sorted(
        sha256_json(observation.to_dict()) for observation in observations_by_id.values()
    ):
        raise IndependentMailHoldoutUatError("retrieval_observation_snapshot_fingerprint_mismatch")
    return observations_by_id, observation_hash_by_id


def _mapping_contains_key(value: Any, target_key: str) -> bool:
    if isinstance(value, Mapping):
        return target_key in value or any(
            _mapping_contains_key(item, target_key) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_mapping_contains_key(item, target_key) for item in value)
    return False


def _identity_scope_graph_binding(
    identity_scope: SourceIdentifierIdentityScope,
) -> dict[str, str]:
    payload = {
        "identity_scope_mode": identity_scope.identity_scope_mode,
        "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
        "workspace_scope_fingerprint": sha256_json(identity_scope.workspace_id),
        "identity_scope_attestation_fingerprint": (
            identity_scope.identity_scope_attestation_fingerprint
        ),
        "identity_scope_policy_fingerprint": (identity_scope.identity_scope_policy_fingerprint),
        "operator_approval_fingerprint": identity_scope.operator_approval_fingerprint,
    }
    if identity_scope.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        assert identity_scope.spec_approval_fingerprint is not None
        payload["spec_approval_fingerprint"] = identity_scope.spec_approval_fingerprint
    return payload


def _observation_occurrence_id(observation: Observation) -> str | None:
    values = {
        value
        for source in (observation.location, observation.payload or {})
        for value in (source.get("message_occurrence_id"),)
        if isinstance(value, str) and value
    }
    return next(iter(values)) if len(values) == 1 else None


def _validate_source_identifier_occurrence_bindings(
    *,
    mentions: Sequence[CandidateMention],
    identity_scope: SourceIdentifierIdentityScope,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    tokenizer_profile: Any,
) -> None:
    actual_occurrences: set[tuple[str, int, int, str, str]] = set()
    expected_occurrences: set[tuple[str, int, int, str, str]] = set()
    candidate_observation_types = {
        "email_message",
        "email_header",
        "email_body_segment",
    }
    for observation_id, observation in sorted(observations_by_id.items()):
        if observation.observation_type not in candidate_observation_types:
            continue
        text = observation.text
        if not isinstance(text, str) or not text:
            continue
        expected_occurrences.update(
            (
                observation_id,
                span.start,
                span.end,
                span.identifier_kind,
                sha256_json(span.exact_token),
            )
            for span in tokenizer_profile.analyze(text).protected_identifiers
        )
    for mention in mentions:
        if len(mention.source_observation_ids) != 1:
            raise IndependentMailHoldoutUatError(
                "source_identifier_candidate_permission_or_lineage_mismatch"
            )
        observation_id = mention.source_observation_ids[0]
        observation = observations_by_id.get(observation_id)
        if observation is None:
            raise IndependentMailHoldoutUatError(
                "source_identifier_candidate_selected_observation_missing"
            )
        metadata = mention.metadata
        location = mention.location
        occurrence_id = _observation_occurrence_id(observation)
        permission_fingerprint = sha256_json(observation.permission_scope)
        source_locator_fingerprint = sha256_json(observation.location)
        provenance_fingerprint = sha256_json(
            {
                "asset_id": observation.asset_id,
                "evidence_snapshot_id": observation.evidence_snapshot_id,
                "extractor_run_id": observation.extractor_run_id,
                "modality": observation.modality,
                "observation_type": observation.observation_type,
            }
        )
        expected_identity = identity_scope.to_dict()
        try:
            span_start = int(location["span_start"])
            span_end = int(location["span_end"])
            identifier_kind = str(location["identifier_kind"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndependentMailHoldoutUatError(
                "source_identifier_candidate_span_binding_invalid"
            ) from exc
        if (
            occurrence_id is None
            or metadata.get("source_observation_fingerprint")
            != observation_hash_by_id.get(observation_id)
            or metadata.get("permission_scope") != dict(observation.permission_scope)
            or metadata.get("permission_boundary_fingerprint") != permission_fingerprint
            or metadata.get("source_locator_fingerprint") != source_locator_fingerprint
            or metadata.get("message_occurrence_fingerprint") != sha256_json(occurrence_id)
            or metadata.get("source_extractor_provenance_fingerprint") != provenance_fingerprint
            or metadata.get("exact_protected_token_hash") != mention.text_hash
            or any(
                metadata.get(field_name) != field_value
                for field_name, field_value in expected_identity.items()
            )
            or location.get("source_observation_id") != observation_id
            or location.get("permission_boundary_fingerprint") != permission_fingerprint
            or location.get("source_locator_fingerprint") != source_locator_fingerprint
            or location.get("message_occurrence_fingerprint") != sha256_json(occurrence_id)
            or any(
                location.get(field_name) != field_value
                for field_name, field_value in expected_identity.items()
            )
        ):
            raise IndependentMailHoldoutUatError(
                "source_identifier_candidate_permission_or_lineage_mismatch"
            )
        occurrence = (
            observation_id,
            span_start,
            span_end,
            identifier_kind,
            str(mention.text_hash),
        )
        if occurrence in actual_occurrences:
            raise IndependentMailHoldoutUatError("source_identifier_candidate_occurrence_duplicate")
        actual_occurrences.add(occurrence)
    if actual_occurrences != expected_occurrences:
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_occurrence_coverage_mismatch"
        )


def _source_identifier_batch_projection(
    complete_batch: SourceBoundIdentifierMentionBatch,
    *,
    selected_mentions: Sequence[CandidateMention],
) -> SourceBoundIdentifierMentionBatch:
    mentions = tuple(sorted(selected_mentions, key=lambda item: item.candidate_mention_id))
    identity_scope = SourceIdentifierIdentityScope(
        identity_scope_mode=complete_batch.identity_scope_mode,
        identity_scope_fingerprint=complete_batch.identity_scope_fingerprint,
        workspace_id=complete_batch.workspace_id,
        identity_scope_attestation_fingerprint=(
            complete_batch.identity_scope_attestation_fingerprint
        ),
        identity_scope_policy_fingerprint=(complete_batch.identity_scope_policy_fingerprint),
        operator_approval_fingerprint=complete_batch.operator_approval_fingerprint,
        tenant_id=complete_batch.tenant_id,
        spec_approval_fingerprint=complete_batch.spec_approval_fingerprint,
    )
    batch_fingerprint = sha256_json(
        {
            "candidate_mention_ids": [mention.candidate_mention_id for mention in mentions],
            "extraction_policy_fingerprint": complete_batch.extraction_policy_fingerprint,
            "identity_scope": identity_scope.to_dict(),
            "tokenizer_profile_fingerprint": (complete_batch.tokenizer_profile_fingerprint),
        }
    )
    return SourceBoundIdentifierMentionBatch(
        candidate_mentions=mentions,
        tokenizer_id=complete_batch.tokenizer_id,
        tokenizer_profile_fingerprint=complete_batch.tokenizer_profile_fingerprint,
        extraction_policy_id=complete_batch.extraction_policy_id,
        extraction_policy_fingerprint=complete_batch.extraction_policy_fingerprint,
        identity_scope_mode=identity_scope.identity_scope_mode,
        identity_scope_fingerprint=identity_scope.identity_scope_fingerprint,
        workspace_id=identity_scope.workspace_id,
        identity_scope_attestation_fingerprint=(
            identity_scope.identity_scope_attestation_fingerprint
        ),
        identity_scope_policy_fingerprint=(identity_scope.identity_scope_policy_fingerprint),
        operator_approval_fingerprint=identity_scope.operator_approval_fingerprint,
        tenant_id=identity_scope.tenant_id,
        spec_approval_fingerprint=identity_scope.spec_approval_fingerprint,
        occurrence_count=len(mentions),
        batch_fingerprint=batch_fingerprint,
    )


def _load_holdout_source_identifier_candidate_intake(
    *,
    artifact_path: Path,
    expected_artifact_sha256: str,
    expected_identity_scope_mode: str,
    expected_identity_scope_fingerprint: str,
    expected_identity_scope_attestation_sha256: str,
    expected_identity_scope_attestation_fingerprint: str,
    expected_identity_scope_policy_fingerprint: str,
    expected_operator_approval_fingerprint: str,
    expected_spec_approval_fingerprint: str | None,
    expected_workspace_id: str,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    retrieval_snapshot: Mapping[str, Any],
    retrieval_snapshot_sha256: str,
    retrieval_report_sha256: str,
    retrieval_report_fingerprint: str,
) -> _HoldoutSourceIdentifierCandidateIntake:
    """Validate one v3 artifact and project its source-bound occurrences."""

    artifact_bytes, artifact = _read_sealed_json(
        artifact_path,
        expected_artifact_sha256,
        max_bytes=MAX_SNAPSHOT_BYTES,
        invalid_reason="source_identifier_candidate_artifact_missing_or_invalid",
        seal_reason="source_identifier_candidate_artifact_seal_mismatch",
    )
    if (
        artifact.get("artifact_id") != SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID
        or artifact.get("schema_version") != CANDIDATE_ARTIFACT_SCHEMA_VERSION
    ):
        raise IndependentMailHoldoutUatError("source_identifier_v3_candidate_artifact_required")
    try:
        validate_private_identifier_candidate_artifact(artifact)
    except SourceIdentifierCandidateError as exc:
        raise IndependentMailHoldoutUatError(exc.reason_code) from exc
    identity_payload = artifact.get("identity_scope_binding")
    batch_payload = artifact.get("mention_batch")
    resolution_payload = artifact.get("resolution")
    counts = artifact.get("counts")
    if not all(
        isinstance(value, Mapping)
        for value in (identity_payload, batch_payload, resolution_payload, counts)
    ):
        raise IndependentMailHoldoutUatError(
            "source_identifier_v3_candidate_artifact_binding_invalid"
        )
    try:
        identity_scope = SourceIdentifierIdentityScope(**dict(identity_payload))
    except (ContractValidationError, TypeError) as exc:
        raise IndependentMailHoldoutUatError(
            "source_identifier_identity_scope_binding_invalid"
        ) from exc
    expected_identity_bindings = {
        "identity_scope_mode": expected_identity_scope_mode,
        "identity_scope_fingerprint": expected_identity_scope_fingerprint,
        "identity_scope_attestation_fingerprint": (expected_identity_scope_attestation_fingerprint),
        "identity_scope_policy_fingerprint": expected_identity_scope_policy_fingerprint,
        "operator_approval_fingerprint": expected_operator_approval_fingerprint,
    }
    if (
        any(
            getattr(identity_scope, field_name) != expected_value
            for field_name, expected_value in expected_identity_bindings.items()
        )
        or artifact.get("identity_scope_mode") != expected_identity_scope_mode
        or artifact.get("identity_scope_attestation_byte_sha256")
        != expected_identity_scope_attestation_sha256
        or artifact.get("identity_scope_attestation_fingerprint")
        != expected_identity_scope_attestation_fingerprint
        or artifact.get("identity_scope_policy_fingerprint")
        != expected_identity_scope_policy_fingerprint
        or expected_identity_scope_policy_fingerprint != IDENTITY_SCOPE_POLICY_FINGERPRINT
        or identity_scope.workspace_id != expected_workspace_id
    ):
        raise IndependentMailHoldoutUatError(
            "source_identifier_identity_scope_expected_binding_mismatch"
        )
    if expected_identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        if (
            expected_spec_approval_fingerprint is None
            or identity_scope.spec_approval_fingerprint != expected_spec_approval_fingerprint
            or identity_scope.tenant_id is not None
            or _mapping_contains_key(artifact, "tenant_id")
            or _mapping_contains_key(artifact, "tenant_workspace_fingerprint")
        ):
            raise IndependentMailHoldoutUatError(
                "source_identifier_workspace_only_identity_binding_invalid"
            )
    elif (
        expected_spec_approval_fingerprint is not None
        or identity_scope.spec_approval_fingerprint is not None
        or identity_scope.tenant_id is None
    ):
        raise IndependentMailHoldoutUatError(
            "source_identifier_tenant_workspace_identity_binding_invalid"
        )

    source_observation_hashes = sorted(observation_hash_by_id.values())
    if (
        artifact.get("retrieval_snapshot_byte_sha256") != retrieval_snapshot_sha256
        or artifact.get("retrieval_report_byte_sha256") != retrieval_report_sha256
        or artifact.get("retrieval_snapshot_fingerprint")
        != retrieval_snapshot.get("snapshot_fingerprint")
        or artifact.get("retrieval_report_fingerprint") != retrieval_report_fingerprint
        or artifact.get("source_snapshot_fingerprint")
        != retrieval_snapshot.get("source_snapshot_fingerprint")
        or artifact.get("source_inventory_fingerprint")
        != retrieval_snapshot.get("source_inventory_fingerprint")
        or artifact.get("tokenizer_profile_fingerprint")
        != retrieval_snapshot.get("tokenizer_profile_fingerprint")
        or artifact.get("source_observation_hashes") != source_observation_hashes
        or artifact.get("source_observation_hash_set_fingerprint")
        != sha256_json(source_observation_hashes)
    ):
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_retrieval_binding_mismatch"
        )
    try:
        inventory = SourceInventory.from_dict(retrieval_snapshot["source_inventory"])
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_source_inventory_invalid"
        ) from exc
    attested_asset_fingerprint = sha256_json(
        {
            "asset_id": inventory.source_asset_id,
            "asset_content_hash": retrieval_snapshot.get("source_asset_sha256"),
            "workspace_id": expected_workspace_id,
            "permission_fingerprint": retrieval_snapshot.get("permission_fingerprint"),
        }
    )
    if artifact.get("attested_asset_fingerprint") != attested_asset_fingerprint:
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_source_permission_binding_mismatch"
        )

    profile = load_issue56_target_mail_tokenizer_profile()
    if (
        artifact.get("tokenizer_id") != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
        or artifact.get("tokenizer_id") != profile.tokenizer_id
        or artifact.get("tokenizer_profile_fingerprint")
        != ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
        or artifact.get("tokenizer_profile_fingerprint") != profile.profile_fingerprint
        or artifact.get("extraction_policy_id") != SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID
        or artifact.get("extraction_policy_fingerprint")
        != SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
        or artifact.get("resolution_policy_id") != SOURCE_IDENTIFIER_RESOLUTION_POLICY_ID
        or artifact.get("resolution_policy_fingerprint")
        != SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT
        or artifact.get("candidate_only") is not True
        or artifact.get("canonical_write_allowed") is not False
        or artifact.get("overflow_count") != 0
        or counts.get("overflow_count") != 0
    ):
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_policy_or_profile_mismatch"
        )
    raw_mentions = batch_payload.get("candidate_mentions")
    if not isinstance(raw_mentions, list):
        raise IndependentMailHoldoutUatError("source_identifier_candidate_mention_batch_invalid")
    try:
        complete_mentions = tuple(
            sorted(
                (CandidateMention.from_dict(row) for row in raw_mentions),
                key=lambda item: item.candidate_mention_id,
            )
        )
        complete_batch = SourceBoundIdentifierMentionBatch(
            candidate_mentions=complete_mentions,
            tokenizer_id=str(batch_payload["tokenizer_id"]),
            tokenizer_profile_fingerprint=str(batch_payload["tokenizer_profile_fingerprint"]),
            extraction_policy_id=str(batch_payload["extraction_policy_id"]),
            extraction_policy_fingerprint=str(batch_payload["extraction_policy_fingerprint"]),
            identity_scope_mode=str(batch_payload["identity_scope_mode"]),
            identity_scope_fingerprint=str(batch_payload["identity_scope_fingerprint"]),
            workspace_id=str(batch_payload["workspace_id"]),
            identity_scope_attestation_fingerprint=str(
                batch_payload["identity_scope_attestation_fingerprint"]
            ),
            identity_scope_policy_fingerprint=str(
                batch_payload["identity_scope_policy_fingerprint"]
            ),
            operator_approval_fingerprint=str(batch_payload["operator_approval_fingerprint"]),
            tenant_id=(str(batch_payload["tenant_id"]) if "tenant_id" in batch_payload else None),
            spec_approval_fingerprint=(
                str(batch_payload["spec_approval_fingerprint"])
                if "spec_approval_fingerprint" in batch_payload
                else None
            ),
            occurrence_count=int(batch_payload["occurrence_count"]),
            batch_fingerprint=str(batch_payload["batch_fingerprint"]),
        )
        complete_resolution = resolve_exact_protected_identifier_candidates(
            complete_batch.candidate_mentions
        )
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise IndependentMailHoldoutUatError("source_identifier_candidate_replay_invalid") from exc
    if complete_batch.to_dict() != dict(batch_payload) or complete_resolution.to_dict() != dict(
        resolution_payload
    ):
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_batch_or_resolution_drift"
        )

    selected_observation_ids = set(observations_by_id)
    selected_mentions = tuple(
        mention
        for mention in complete_mentions
        if (
            len(mention.source_observation_ids) == 1
            and mention.source_observation_ids[0] in selected_observation_ids
        )
    )
    if any(len(mention.source_observation_ids) != 1 for mention in complete_mentions):
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_permission_or_lineage_mismatch"
        )
    _validate_source_identifier_occurrence_bindings(
        mentions=selected_mentions,
        identity_scope=identity_scope,
        observations_by_id=observations_by_id,
        observation_hash_by_id=observation_hash_by_id,
        tokenizer_profile=profile,
    )
    projected_batch = _source_identifier_batch_projection(
        complete_batch,
        selected_mentions=selected_mentions,
    )
    try:
        selected_resolution = resolve_exact_protected_identifier_candidates(
            projected_batch.candidate_mentions
        )
    except ContractValidationError as exc:
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_selected_resolution_invalid"
        ) from exc
    safe_binding = _validated_source_identifier_v3_safe_binding(
        artifact=artifact,
        expected_artifact_sha256=expected_artifact_sha256,
        identity_scope=identity_scope,
        projected_batch=projected_batch,
        selected_resolution=selected_resolution,
    )
    if _sha256_bytes(artifact_path.read_bytes()) != expected_artifact_sha256:
        raise IndependentMailHoldoutUatError(
            "source_identifier_candidate_artifact_changed_during_validation"
        )
    return _HoldoutSourceIdentifierCandidateIntake(
        projected_batch=projected_batch,
        safe_binding=safe_binding,
        artifact_sha256=_sha256_bytes(artifact_bytes),
    )


def _validated_source_identifier_v3_safe_binding(
    *,
    artifact: Mapping[str, Any],
    expected_artifact_sha256: str,
    identity_scope: SourceIdentifierIdentityScope,
    projected_batch: SourceBoundIdentifierMentionBatch,
    selected_resolution: Any,
) -> dict[str, Any]:
    graph_identity_binding = _identity_scope_graph_binding(identity_scope)
    safe_binding: dict[str, Any] = {
        "status": "sealed_passed",
        "candidate_artifact_schema_version": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "candidate_artifact_schema_fingerprint": sha256_json(CANDIDATE_ARTIFACT_SCHEMA_VERSION),
        "source_artifact_byte_hash": expected_artifact_sha256,
        "source_artifact_fingerprint": artifact["artifact_fingerprint"],
        "source_snapshot_fingerprint": artifact["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": artifact["source_inventory_fingerprint"],
        "source_observation_hash_set_fingerprint": artifact[
            "source_observation_hash_set_fingerprint"
        ],
        "retrieval_snapshot_fingerprint": artifact["retrieval_snapshot_fingerprint"],
        "retrieval_report_fingerprint": artifact["retrieval_report_fingerprint"],
        "retrieval_snapshot_byte_sha256": artifact["retrieval_snapshot_byte_sha256"],
        "retrieval_report_byte_sha256": artifact["retrieval_report_byte_sha256"],
        "candidate_admission_profile_fingerprint": artifact["tokenizer_profile_fingerprint"],
        "extraction_policy_fingerprint": artifact["extraction_policy_fingerprint"],
        "resolution_policy_fingerprint": artifact["resolution_policy_fingerprint"],
        "identity_scope_mode": identity_scope.identity_scope_mode,
        "identity_scope_mode_status": identity_scope.identity_scope_mode,
        "identity_scope_mode_fingerprint": sha256_json(identity_scope.identity_scope_mode),
        "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
        "identity_scope_attestation_byte_sha256": artifact[
            "identity_scope_attestation_byte_sha256"
        ],
        "identity_scope_attestation_fingerprint": (
            identity_scope.identity_scope_attestation_fingerprint
        ),
        "identity_scope_policy_fingerprint": (identity_scope.identity_scope_policy_fingerprint),
        "identity_scope_binding_fingerprint": sha256_json(identity_scope.to_dict()),
        "identity_scope_graph_binding_fingerprint": sha256_json(graph_identity_binding),
        "workspace_scope_fingerprint": sha256_json(identity_scope.workspace_id),
        "operator_approval_fingerprint": identity_scope.operator_approval_fingerprint,
        "spec_approval_status": (
            "passed_bound"
            if identity_scope.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            else "not_required_for_mode"
        ),
        "mode_approval_binding_fingerprint": sha256_json(
            {
                "identity_scope_mode": identity_scope.identity_scope_mode,
                "operator_approval_fingerprint": (identity_scope.operator_approval_fingerprint),
                "spec_approval_fingerprint": identity_scope.spec_approval_fingerprint,
            }
        ),
        "attested_asset_fingerprint": artifact["attested_asset_fingerprint"],
        "complete_mention_batch_fingerprint": artifact["mention_batch"]["batch_fingerprint"],
        "complete_resolution_fingerprint": artifact["resolution"]["resolution_fingerprint"],
        "complete_mention_count": int(artifact["counts"]["identifier_occurrence_count"]),
        "complete_resolved_candidate_count": int(artifact["counts"]["resolved_candidate_count"]),
        "selected_mention_batch_fingerprint": projected_batch.batch_fingerprint,
        "selected_resolution_fingerprint": selected_resolution.resolution_fingerprint,
        "selected_mention_count": projected_batch.occurrence_count,
        "selected_resolved_candidate_count": selected_resolution.candidate_count,
        "overflow_count": 0,
        "candidate_graph_only": True,
        "canonical_write_allowed": False,
        "source_graph_policy_fingerprint": sha256_json(development_uat.SOURCE_GRAPH_POLICY_ID),
        "source_identifier_adapter_fingerprint": sha256_json(
            development_uat.SOURCE_IDENTIFIER_ADAPTER_ID
        ),
        "holdout_adapter_fingerprint": SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_FINGERPRINT,
    }
    safe_binding["mode_approval_fingerprint"] = safe_binding["mode_approval_binding_fingerprint"]
    if identity_scope.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        safe_binding["spec_approval_fingerprint"] = identity_scope.spec_approval_fingerprint
    safe_binding["binding_fingerprint"] = sha256_json(safe_binding)
    try:
        assert_no_public_raw_references(
            safe_binding,
            "issue56_independent_holdout_source_identifier_v3_binding",
        )
    except ContractValidationError as exc:
        raise IndependentMailHoldoutUatError("source_identifier_v3_binding_private_leak") from exc
    return safe_binding


def _project_source_identifier_batch_for_session(
    *,
    complete_batch: SourceBoundIdentifierMentionBatch,
    session: Any,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]],
) -> SourceBoundIdentifierMentionBatch:
    selected_observation_ids: set[str] = set()
    for source_scope_id in session.authorized_source_scope_ids:
        observations = observations_by_bundle_id.get(source_scope_id)
        if observations is None:
            raise IndependentMailHoldoutUatError("source_identifier_requester_source_scope_missing")
        selected_observation_ids.update(observation.observation_id for observation in observations)
    mentions = tuple(
        mention
        for mention in complete_batch.candidate_mentions
        if (
            len(mention.source_observation_ids) == 1
            and mention.source_observation_ids[0] in selected_observation_ids
        )
    )
    return _source_identifier_batch_projection(
        complete_batch,
        selected_mentions=mentions,
    )


def _build_holdout_execution_context(
    *,
    bundle: MailEvidenceBundle,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    source_binding_fingerprint: str,
    cases: Sequence[Mapping[str, Any]],
    identifier_mention_batch: Any,
    source_identifier_binding: Mapping[str, Any],
    development_observation_ids: frozenset[str] = frozenset(),
) -> _HoldoutExecutionContext:
    """Build the actual permission-scoped index, graph, and ontology views."""

    observations_by_bundle_id = {
        bundle.mail_evidence_bundle_id: tuple(
            observations_by_id[observation_id] for observation_id in sorted(observations_by_id)
        )
    }
    requester_ids = {str(case.get("requester_user_id") or "") for case in cases}
    if not requester_ids or "" in requester_ids:
        raise IndependentMailHoldoutUatError("holdout_requester_set_invalid")
    sessions: dict[str, Any] = {}
    views: dict[str, Any] = {}
    crosswalks: dict[str, Any] = {}
    graph_builds: dict[str, Any] = {}
    requester_batches: dict[str, SourceBoundIdentifierMentionBatch] = {}
    for requester_user_id in sorted(requester_ids, key=sha256_json):
        session = build_authorized_semantic_mail_session(
            observations_by_bundle_id=observations_by_bundle_id,
            bundles=(bundle,),
            requester_user_id=requester_user_id,
            workspace_id=bundle.mail_import_session.workspace_id,
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
        )
        requester_batch = _project_source_identifier_batch_for_session(
            complete_batch=identifier_mention_batch,
            session=session,
            observations_by_bundle_id=observations_by_bundle_id,
        )
        graph_build = build_authorized_source_backed_effective_graph_view(
            session=session,
            observations_by_bundle_id=observations_by_bundle_id,
            source_binding_fingerprint=source_binding_fingerprint,
            source_graph_policy_id=development_uat.SOURCE_GRAPH_POLICY_ID,
            identifier_mention_batch=requester_batch,
        )
        view = graph_build.effective_graph_view
        crosswalk = build_evidence_identity_lineage_crosswalk(
            session=session,
            effective_graph_view=view,
        )
        sessions[requester_user_id] = session
        views[requester_user_id] = view
        crosswalks[requester_user_id] = crosswalk
        graph_builds[requester_user_id] = graph_build
        requester_batches[requester_user_id] = requester_batch
    graph_ontology_binding = _graph_ontology_binding(
        graph_builds,
        source_identifier_binding=source_identifier_binding,
        requester_batches=requester_batches,
    )
    return _HoldoutExecutionContext(
        observations_by_bundle_id=observations_by_bundle_id,
        observations_by_id=observations_by_id,
        observation_hash_by_id=observation_hash_by_id,
        sessions=sessions,
        effective_graph_views=views,
        lineage_crosswalks=crosswalks,
        graph_builds=graph_builds,
        graph_ontology_binding=graph_ontology_binding,
        source_binding_fingerprint=source_binding_fingerprint,
        identifier_mention_batch=identifier_mention_batch,
        source_identifier_binding=source_identifier_binding,
        development_observation_ids=development_observation_ids,
    )


def _graph_ontology_binding(
    graph_builds: Mapping[str, Any],
    *,
    source_identifier_binding: Mapping[str, Any],
    requester_batches: Mapping[str, SourceBoundIdentifierMentionBatch] | None = None,
) -> dict[str, Any]:
    if not graph_builds or requester_batches is None:
        raise IndependentMailHoldoutUatError("holdout_graph_binding_missing")
    if set(graph_builds) != set(requester_batches):
        raise IndependentMailHoldoutUatError(
            "holdout_source_identifier_v3_requester_projection_mismatch"
        )
    ordered = [
        (requester_id, graph_build)
        for requester_id, graph_build in sorted(
            graph_builds.items(),
            key=lambda item: sha256_json(item[0]),
        )
    ]
    safe_builds: list[dict[str, Any]] = []
    expected_relation_hashes = sorted(
        sha256_json(value) for value in development_uat.DIAGNOSTIC_RELATION_TYPES
    )
    expected_identity_bindings = {
        "identity_scope_mode": source_identifier_binding["identity_scope_mode_status"],
        "identity_scope_fingerprint": source_identifier_binding["identity_scope_fingerprint"],
        "identity_scope_attestation_fingerprint": source_identifier_binding[
            "identity_scope_attestation_fingerprint"
        ],
        "identity_scope_policy_fingerprint": source_identifier_binding[
            "identity_scope_policy_fingerprint"
        ],
        "operator_approval_fingerprint": source_identifier_binding["operator_approval_fingerprint"],
        "identity_scope_graph_binding_fingerprint": source_identifier_binding[
            "identity_scope_graph_binding_fingerprint"
        ],
    }
    if (
        source_identifier_binding["identity_scope_mode_status"]
        == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    ):
        expected_identity_bindings["spec_approval_fingerprint"] = source_identifier_binding[
            "spec_approval_fingerprint"
        ]
    for requester_id, graph_build in ordered:
        requester_batch = requester_batches[requester_id]
        safe_build = graph_build.to_safe_dict()
        if (
            safe_build.get("artifact_id") != "formowl_issue56_source_backed_graph_build_v2"
            or safe_build.get("graph_policy_id") != development_uat.SOURCE_GRAPH_POLICY_ID
            or safe_build.get("candidate_graph_only") is not True
            or safe_build.get("human_review_complete") is not False
            or safe_build.get("relation_type_hashes") != expected_relation_hashes
            or safe_build.get("identifier_mention_count") != requester_batch.occurrence_count
            or any(
                safe_build.get(field_name) != expected_value
                for field_name, expected_value in expected_identity_bindings.items()
            )
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_source_identifier_v3_graph_binding_invalid"
            )
        if (
            requester_batch.identity_scope_mode
            != source_identifier_binding["identity_scope_mode_status"]
            or requester_batch.identity_scope_fingerprint
            != source_identifier_binding["identity_scope_fingerprint"]
            or requester_batch.identity_scope_attestation_fingerprint
            != source_identifier_binding["identity_scope_attestation_fingerprint"]
            or requester_batch.identity_scope_policy_fingerprint
            != source_identifier_binding["identity_scope_policy_fingerprint"]
            or requester_batch.operator_approval_fingerprint
            != source_identifier_binding["operator_approval_fingerprint"]
            or (
                requester_batch.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
                and (
                    requester_batch.tenant_id is not None
                    or requester_batch.spec_approval_fingerprint
                    != source_identifier_binding["spec_approval_fingerprint"]
                )
            )
            or (
                requester_batch.identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE
                and (
                    requester_batch.tenant_id is None
                    or requester_batch.spec_approval_fingerprint is not None
                )
            )
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_source_identifier_v3_requester_projection_mismatch"
            )
        for field_name in (
            "complete_identifier_mention_fingerprint",
            "authorized_identifier_mention_fingerprint",
            "identifier_resolution_fingerprint",
            "identity_scope_graph_binding_fingerprint",
            "build_fingerprint",
            "graph_revision_fingerprint",
        ):
            _require_sha256(
                safe_build.get(field_name),
                "holdout_source_identifier_v3_graph_binding_invalid",
            )
        authorized_count = safe_build.get("authorized_identifier_mention_count")
        if (
            not isinstance(authorized_count, int)
            or isinstance(authorized_count, bool)
            or authorized_count < 0
            or authorized_count > requester_batch.occurrence_count
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_source_identifier_v3_graph_binding_invalid"
            )
        safe_builds.append(safe_build)
    graph_artifact_fingerprints = [
        _require_sha256(
            graph_build.build_fingerprint,
            "holdout_graph_artifact_fingerprint_invalid",
        )
        for _, graph_build in ordered
    ]
    graph_revision_fingerprints = [
        _require_sha256(
            graph_build.graph_revision_fingerprint,
            "holdout_graph_revision_fingerprint_invalid",
        )
        for _, graph_build in ordered
    ]
    graph_revision_id_fingerprints = [
        sha256_json(
            {
                "user_graph_revision_id": view.user_graph_revision_id,
                "canonical_graph_revision_id": (view.canonical_graph_revision_id),
                "assembly_policy_id": view.assembly_policy_id,
                "applied_grant_id_fingerprints": sorted(
                    sha256_json(grant_id) for grant_id in view.applied_grant_ids
                ),
            }
        )
        for view in (graph_build.effective_graph_view for _, graph_build in ordered)
    ]
    ontology_revision_fingerprints = [
        sha256_json(graph_build.effective_graph_view.ontology_revision_id)
        for _, graph_build in ordered
    ]
    graph_artifact_fingerprint = sha256_json(graph_artifact_fingerprints)
    graph_revision_fingerprint = sha256_json(graph_revision_fingerprints)
    graph_revision_id_fingerprint = sha256_json(graph_revision_id_fingerprints)
    ontology_revision_fingerprint = sha256_json(ontology_revision_fingerprints)
    ontology_artifact_fingerprint = sha256_json(
        {
            "ontology_target_fingerprint": sha256_json(development_uat.ONTOLOGY_TARGET),
            "ontology_revision_fingerprint": ontology_revision_fingerprint,
            "graph_revision_fingerprint": graph_revision_fingerprint,
        }
    )
    complete_mention_fingerprints = sorted(
        {str(build["complete_identifier_mention_fingerprint"]) for build in safe_builds}
    )
    authorized_mention_fingerprints = sorted(
        {str(build["authorized_identifier_mention_fingerprint"]) for build in safe_builds}
    )
    resolution_fingerprints = sorted(
        {str(build["identifier_resolution_fingerprint"]) for build in safe_builds}
    )
    requester_batch_fingerprints = sorted(
        batch.batch_fingerprint for batch in requester_batches.values()
    )
    binding: dict[str, Any] = {
        "graph_artifact_fingerprint": graph_artifact_fingerprint,
        "graph_revision_fingerprint": graph_revision_fingerprint,
        "graph_revision_id_fingerprint": graph_revision_id_fingerprint,
        "ontology_artifact_fingerprint": ontology_artifact_fingerprint,
        "ontology_revision_fingerprint": ontology_revision_fingerprint,
        "permission_scoped_graph_count": len(ordered),
        "graph_node_count": sum(
            len(build.effective_graph_view.visible_nodes) for _, build in ordered
        ),
        "graph_edge_count": sum(
            len(build.effective_graph_view.visible_edges) for _, build in ordered
        ),
        "ontology_revision_count": len(set(ontology_revision_fingerprints)),
        "source_graph_policy_fingerprint": source_identifier_binding[
            "source_graph_policy_fingerprint"
        ],
        "source_identifier_adapter_fingerprint": source_identifier_binding[
            "source_identifier_adapter_fingerprint"
        ],
        "source_identifier_candidate_artifact_fingerprint": source_identifier_binding[
            "source_artifact_fingerprint"
        ],
        "source_identifier_candidate_binding_fingerprint": source_identifier_binding[
            "binding_fingerprint"
        ],
        "candidate_artifact_schema_fingerprint": source_identifier_binding[
            "candidate_artifact_schema_fingerprint"
        ],
        "complete_identifier_mention_fingerprint_set_hash": sha256_json(
            complete_mention_fingerprints
        ),
        "authorized_identifier_mention_fingerprint_set_hash": sha256_json(
            authorized_mention_fingerprints
        ),
        "identifier_resolution_fingerprint_set_hash": sha256_json(resolution_fingerprints),
        "requester_projected_mention_batch_fingerprint_set_hash": sha256_json(
            requester_batch_fingerprints
        ),
        "selected_identifier_mention_batch_fingerprint": (
            source_identifier_binding["selected_mention_batch_fingerprint"]
        ),
        "selected_identifier_resolution_fingerprint": (
            source_identifier_binding["selected_resolution_fingerprint"]
        ),
        "identifier_mention_count": sum(
            batch.occurrence_count for batch in requester_batches.values()
        ),
        "authorized_identifier_mention_count": sum(
            int(build["authorized_identifier_mention_count"]) for build in safe_builds
        ),
        "selected_resolved_candidate_count": source_identifier_binding[
            "selected_resolved_candidate_count"
        ],
        "identity_scope_mode_status": source_identifier_binding["identity_scope_mode_status"],
        "identity_scope_mode_fingerprint": source_identifier_binding[
            "identity_scope_mode_fingerprint"
        ],
        "identity_scope_fingerprint": source_identifier_binding["identity_scope_fingerprint"],
        "identity_scope_binding_fingerprint": source_identifier_binding[
            "identity_scope_binding_fingerprint"
        ],
        "identity_scope_attestation_byte_sha256": source_identifier_binding[
            "identity_scope_attestation_byte_sha256"
        ],
        "identity_scope_attestation_fingerprint": source_identifier_binding[
            "identity_scope_attestation_fingerprint"
        ],
        "identity_scope_policy_fingerprint": source_identifier_binding[
            "identity_scope_policy_fingerprint"
        ],
        "operator_approval_fingerprint": source_identifier_binding["operator_approval_fingerprint"],
        "mode_approval_fingerprint": source_identifier_binding["mode_approval_fingerprint"],
        "workspace_scope_fingerprint": source_identifier_binding["workspace_scope_fingerprint"],
        "identity_scope_graph_binding_fingerprint_set_hash": sha256_json(
            sorted(
                {str(build["identity_scope_graph_binding_fingerprint"]) for build in safe_builds}
            )
        ),
        "candidate_graph_only": True,
        "human_review_complete": False,
    }
    if (
        source_identifier_binding["identity_scope_mode_status"]
        == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    ):
        binding["spec_approval_fingerprint"] = source_identifier_binding[
            "spec_approval_fingerprint"
        ]
    binding["graph_ontology_binding_fingerprint"] = sha256_json(binding)
    return binding


def _validate_pre_holdout_authority(
    *,
    run_binding_fingerprint: str,
) -> dict[str, Any]:
    authority = check_methodology_authority(repository_root=ROOT)
    blocker_ids = set(authority.blocking_gate_ids)
    if (
        not authority.authority_valid
        or authority.status != "blocked"
        or authority.methodology_ready
        or authority.errors
        or authority.execution_fingerprint is None
        or authority.authority_state_fingerprint is None
        or not blocker_ids
        or not blocker_ids <= _ALLOWED_PRE_HOLDOUT_AUTHORITY_BLOCKERS
    ):
        raise IndependentMailHoldoutUatError("pre_holdout_authority_has_unrelated_blocker")
    component = build_current_authority_component(
        repository_root=ROOT,
        run_binding_fingerprint=run_binding_fingerprint,
    )
    if (
        component.get("status") != "blocked"
        or component.get("methodology_ready_status") != "blocked"
        or component.get("authority_state_fingerprint") != authority.authority_state_fingerprint
        or component.get("authority_execution_fingerprint") != authority.execution_fingerprint
        or component.get("blocking_gate_count") != len(blocker_ids)
        or component.get("blocking_gate_set_fingerprint") != sha256_json(sorted(blocker_ids))
        or component.get("source_completeness_gate_status") != "passed"
        or component.get("real_source_ablation_gate_status") != "passed"
    ):
        raise IndependentMailHoldoutUatError("pre_holdout_authority_component_mismatch")
    return dict(component)


def _validate_source_report(
    report: Mapping[str, Any],
    *,
    source_report_sha256: str,
    bundle_artifact: Mapping[str, Any],
    retrieval_snapshot: Mapping[str, Any],
) -> None:
    _validate_native_authorized_report(report)
    expected = {
        "snapshot_fingerprint": retrieval_snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": retrieval_snapshot["source_inventory_fingerprint"],
        "native_manifest_fingerprint": retrieval_snapshot["native_manifest_fingerprint"],
        "permission_fingerprint": retrieval_snapshot["permission_fingerprint"],
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise IndependentMailHoldoutUatError("source_report_binding_mismatch")
    if (
        bundle_artifact["source_snapshot_fingerprint"] != report["snapshot_fingerprint"]
        or bundle_artifact["source_inventory_fingerprint"] != report["source_inventory_fingerprint"]
    ):
        raise IndependentMailHoldoutUatError("source_report_bundle_binding_mismatch")
    _require_sha256(source_report_sha256, "source_report_seal_invalid")
    try:
        assert_no_public_raw_references(report, RETRIEVAL_REPORT_ARTIFACT_ID)
    except ContractValidationError as exc:
        raise IndependentMailHoldoutUatError("source_report_private_leak") from exc


def build_oracle_free_holdout_projection(
    *,
    private_manifest: Mapping[str, Any],
    private_manifest_sha256: str,
    holdout_policy: _HoldoutPolicy = _BASE_HOLDOUT_POLICY,
) -> dict[str, Any]:
    """Project execution metadata while excluding every private oracle field.

    This helper belongs to the source-side authoring boundary.  The evaluator
    preflight consumes only its independently sealed output and never calls it
    on private manifest bytes.  Execute-once calls it only after the persistent
    consumed claim exists, to prove exact cross-binding.
    """

    _require_sha256(
        private_manifest_sha256,
        "holdout_manifest_seal_invalid",
    )
    if holdout_policy.policy_id != BASE_HOLDOUT_POLICY_ID:
        raise IndependentMailHoldoutUatError("holdout_extension_projection_is_source_author_owned")
    _validate_private_manifest_boundary(private_manifest, holdout_policy=holdout_policy)
    cases = private_manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != holdout_policy.case_count:
        raise IndependentMailHoldoutUatError("holdout_case_count_mismatch")
    projected_cases = [_oracle_free_case_projection(case) for case in cases]
    manifest_fingerprint = str(private_manifest["manifest_fingerprint"])
    private_manifest_id = sha256_json(
        {
            "artifact_id": holdout_policy.manifest_artifact_id,
            "manifest_fingerprint": manifest_fingerprint,
        }
    )
    projection: dict[str, Any] = {
        "artifact_id": holdout_policy.projection_artifact_id,
        "schema_version": holdout_policy.projection_schema_version,
        "status": "sealed_oracle_free",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "private_manifest_binding": {
            "manifest_artifact_id": holdout_policy.manifest_artifact_id,
            "manifest_schema_version": holdout_policy.manifest_schema_version,
            "manifest_classification": holdout_policy.manifest_classification,
            "private_manifest_id": private_manifest_id,
            "manifest_sha256": private_manifest_sha256,
            "manifest_fingerprint": manifest_fingerprint,
            "partition_fingerprint": private_manifest["partition_fingerprint"],
            "case_count": private_manifest["case_count"],
        },
        "source_oracle_bindings": private_manifest["source_oracle_bindings"],
        "development_exclusion_binding": private_manifest["development_exclusion_binding"],
        "disjointness": private_manifest["disjointness"],
        "case_count": private_manifest["case_count"],
        "case_strata_counts": private_manifest["case_strata_counts"],
        "cases": projected_cases,
    }
    projection["projection_fingerprint"] = _payload_fingerprint(
        projection,
        "projection_fingerprint",
    )
    _assert_oracle_free_projection(projection)
    return projection


def _validate_private_manifest_boundary(
    manifest: Mapping[str, Any],
    *,
    holdout_policy: _HoldoutPolicy = _BASE_HOLDOUT_POLICY,
) -> None:
    if holdout_policy.policy_id == EXTENSION_HOLDOUT_POLICY_ID:
        _validate_extension_private_manifest_boundary(
            manifest,
            holdout_policy=holdout_policy,
        )
        return
    if (
        manifest.get("artifact_id") != holdout_policy.manifest_artifact_id
        or manifest.get("schema_version") != holdout_policy.manifest_schema_version
        or manifest.get("classification") != holdout_policy.manifest_classification
        or manifest.get("case_count") != holdout_policy.case_count
        or manifest.get("execution_status") != "not_run"
        or manifest.get("quality_result_status") != "not_read"
        or manifest.get("seal_required_before_execution") is not True
        or manifest.get("claim_boundary_status") != holdout_policy.manifest_claim_boundary_status
        or manifest.get("manifest_fingerprint")
        != _payload_fingerprint(manifest, "manifest_fingerprint")
        or not isinstance(manifest.get("partition_fingerprint"), str)
    ):
        raise IndependentMailHoldoutUatError("holdout_manifest_boundary_invalid")
    if manifest.get("case_strata_counts") != dict(holdout_policy.strata_counts):
        raise IndependentMailHoldoutUatError("holdout_strata_coverage_mismatch")
    for field_name in (
        "source_oracle_bindings",
        "development_exclusion_binding",
        "disjointness",
        "case_strata_counts",
    ):
        if not isinstance(manifest.get(field_name), Mapping):
            raise IndependentMailHoldoutUatError("holdout_manifest_boundary_invalid")


def _validate_extension_capacity_audit_binding(
    *,
    binding: Any,
    source_snapshot_fingerprint: Any,
    partition_fingerprint: Any,
    selection_proof: Any | None = None,
    selection_proof_fingerprint: Any | None = None,
) -> None:
    if not isinstance(binding, Mapping):
        raise IndependentMailHoldoutUatError("holdout_extension_capacity_audit_binding_invalid")
    expected_keys = {
        "artifact_id",
        "status",
        "capacity_audit_policy_id",
        "capacity_audit_policy_fingerprint",
        "target_strata_counts",
        "source_snapshot_fingerprint",
        "partition_fingerprint",
        "candidate_inventory_fingerprint",
        "selected_candidate_fingerprint",
        "selection_proof_fingerprint",
        "capacity_shortfall_policy",
        "capacity_audit_binding_fingerprint",
    }
    if (
        set(binding) != expected_keys
        or binding.get("artifact_id")
        != "formowl_issue56_holdout_extension_capacity_audit_binding_v1"
        or binding.get("status") != "passed"
        or binding.get("capacity_audit_policy_id")
        != "issue56_holdout_extension_actual_source_capacity_adjustment_v1"
        or binding.get("capacity_audit_policy_fingerprint")
        != HOLDOUT_EXTENSION_CAPACITY_AUDIT_POLICY_FINGERPRINT
        or binding.get("target_strata_counts") != dict(HOLDOUT_EXTENSION_STRATA_COUNTS)
        or binding.get("source_snapshot_fingerprint") != source_snapshot_fingerprint
        or binding.get("partition_fingerprint") != partition_fingerprint
        or binding.get("capacity_shortfall_policy") != "fail_closed_no_redistribution"
        or binding.get("capacity_audit_binding_fingerprint")
        != _payload_fingerprint(binding, "capacity_audit_binding_fingerprint")
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_capacity_audit_binding_invalid")
    for field_name in (
        "source_snapshot_fingerprint",
        "partition_fingerprint",
        "candidate_inventory_fingerprint",
        "selected_candidate_fingerprint",
        "selection_proof_fingerprint",
        "capacity_audit_binding_fingerprint",
    ):
        _require_sha256(
            binding.get(field_name),
            "holdout_extension_capacity_audit_binding_invalid",
        )
    if selection_proof is not None:
        if (
            not isinstance(selection_proof, Mapping)
            or binding.get("candidate_inventory_fingerprint")
            != selection_proof.get("candidate_inventory_fingerprint")
            or binding.get("selected_candidate_fingerprint")
            != selection_proof.get("selected_candidate_fingerprint")
            or binding.get("selection_proof_fingerprint")
            != selection_proof.get("selection_proof_fingerprint")
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_extension_capacity_audit_binding_mismatch"
            )
    if (
        selection_proof_fingerprint is not None
        and binding.get("selection_proof_fingerprint") != selection_proof_fingerprint
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_capacity_audit_binding_mismatch")


def _validate_extension_private_manifest_boundary(
    manifest: Mapping[str, Any],
    *,
    holdout_policy: _HoldoutPolicy,
) -> None:
    if (
        manifest.get("artifact_id") != holdout_policy.manifest_artifact_id
        or manifest.get("schema_version") != holdout_policy.manifest_schema_version
        or manifest.get("classification") != holdout_policy.manifest_classification
        or manifest.get("status") != "sealed"
        or manifest.get("claim_boundary_status") != holdout_policy.manifest_claim_boundary_status
        or manifest.get("execution_status") != "not_run"
        or manifest.get("quality_result_status") != "not_read"
        or manifest.get("final_acceptance_eligible") is not True
        or manifest.get("diagnostic_only") is not False
        or manifest.get("extension_case_count") != holdout_policy.case_count
        or manifest.get("base_case_count") != HOLDOUT_EXTENSION_BASE_CASE_COUNT
        or manifest.get("combined_acceptance_case_count") != HOLDOUT_EXTENSION_COMBINED_CASE_COUNT
        or manifest.get("case_strata_counts") != dict(holdout_policy.strata_counts)
        or manifest.get("selection_policy_fingerprint")
        != HOLDOUT_EXTENSION_SELECTION_POLICY_FINGERPRINT
        or manifest.get("partition_policy_fingerprint")
        != HOLDOUT_EXTENSION_PARTITION_POLICY_FINGERPRINT
        or manifest.get("manifest_fingerprint")
        != _payload_fingerprint(manifest, "manifest_fingerprint")
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_manifest_boundary_invalid")
    for field_name in (
        "source_bindings",
        "base_holdout_binding",
        "development_exclusion_binding",
        "selection_policy",
        "capacity_audit_binding",
        "partition_policy",
        "disjointness_proof",
        "selection_proof",
    ):
        if not isinstance(manifest.get(field_name), Mapping):
            raise IndependentMailHoldoutUatError("holdout_extension_manifest_boundary_invalid")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != holdout_policy.case_count:
        raise IndependentMailHoldoutUatError("holdout_case_count_mismatch")
    strata = Counter(_case_stratum(case) for case in cases if isinstance(case, Mapping))
    if len(strata) != len(holdout_policy.strata_counts) or dict(sorted(strata.items())) != dict(
        holdout_policy.strata_counts
    ):
        raise IndependentMailHoldoutUatError("holdout_strata_coverage_mismatch")
    source_bindings = manifest["source_bindings"]
    selection_proof = manifest["selection_proof"]
    _validate_extension_capacity_audit_binding(
        binding=manifest["capacity_audit_binding"],
        source_snapshot_fingerprint=source_bindings.get("source_snapshot_fingerprint"),
        partition_fingerprint=manifest.get("partition_fingerprint"),
        selection_proof=selection_proof,
    )


def _validate_extension_manifest_projection_cross_binding(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    projection: Mapping[str, Any],
    holdout_policy: _HoldoutPolicy,
) -> None:
    manifest_binding = projection.get("private_manifest_binding")
    source_binding = projection.get("source_binding_hashes")
    if (
        not isinstance(manifest_binding, Mapping)
        or manifest_binding.get("artifact_id") != holdout_policy.manifest_artifact_id
        or manifest_binding.get("schema_version") != holdout_policy.manifest_schema_version
        or manifest_binding.get("manifest_sha256") != manifest_sha256
        or manifest_binding.get("manifest_fingerprint") != manifest.get("manifest_fingerprint")
        or not isinstance(source_binding, Mapping)
    ):
        raise IndependentMailHoldoutUatError(
            "holdout_private_manifest_projection_cross_binding_mismatch"
        )
    expected_source_binding = {
        (
            "segmentation_profile_fingerprint" if key == "tokenizer_profile_fingerprint" else key
        ): value
        for key, value in manifest["source_bindings"].items()
    }
    if (
        dict(source_binding) != expected_source_binding
        or projection.get("base_holdout_binding") != manifest.get("base_holdout_binding")
        or projection.get("selection_policy_fingerprint")
        != manifest.get("selection_policy_fingerprint")
        or projection.get("capacity_audit_binding") != manifest.get("capacity_audit_binding")
        or projection.get("partition_policy_fingerprint")
        != manifest.get("partition_policy_fingerprint")
        or projection.get("partition_fingerprint") != manifest.get("partition_fingerprint")
        or projection.get("selection_proof_fingerprint")
        != manifest["selection_proof"].get("selection_proof_fingerprint")
        or projection.get("disjointness_proof_hash") != sha256_json(manifest["disjointness_proof"])
        or projection.get("strata_counts") != manifest.get("case_strata_counts")
    ):
        raise IndependentMailHoldoutUatError(
            "holdout_private_manifest_projection_cross_binding_mismatch"
        )
    counts = projection.get("counts")
    if (
        not isinstance(counts, Mapping)
        or counts.get("extension_case_count") != manifest.get("extension_case_count")
        or counts.get("base_case_count") != manifest.get("base_case_count")
        or counts.get("combined_acceptance_case_count")
        != manifest.get("combined_acceptance_case_count")
        or counts.get("selected_observation_count")
        != manifest["disjointness_proof"].get("extension_observation_count")
        or counts.get("selected_message_count")
        != manifest["disjointness_proof"].get("extension_message_count")
        or counts.get("selected_thread_count")
        != manifest["disjointness_proof"].get("extension_thread_count")
        or counts.get("candidate_count")
        != manifest["selection_proof"].get("eligible_candidate_count")
    ):
        raise IndependentMailHoldoutUatError(
            "holdout_private_manifest_projection_cross_binding_mismatch"
        )
    projected_cases = projection.get("cases")
    private_cases = manifest.get("cases")
    if (
        not isinstance(projected_cases, list)
        or not isinstance(private_cases, list)
        or len(projected_cases) != len(private_cases)
    ):
        raise IndependentMailHoldoutUatError(
            "holdout_private_manifest_projection_cross_binding_mismatch"
        )
    for case, projected in zip(private_cases, projected_cases, strict=True):
        if not isinstance(case, Mapping) or not isinstance(projected, Mapping):
            raise IndependentMailHoldoutUatError(
                "holdout_private_manifest_projection_cross_binding_mismatch"
            )
        evidence_binding = case.get("source_evidence_binding")
        typed_route = case.get("typed_route")
        if (
            not isinstance(evidence_binding, Mapping)
            or not isinstance(typed_route, Mapping)
            or projected.get("manifest_entry_hash") != case.get("private_fingerprint")
            or projected.get("case_id_hash") != sha256_json(case.get("case_id"))
            or projected.get("query_hash") != case.get("query_hash")
            or case.get("query_hash") != sha256_json(case.get("query_text"))
            or projected.get("stratum_id") != case.get("stratum_id")
            or projected.get("route") != typed_route
            or projected.get("route_fingerprint") != case.get("route_fingerprint")
            or projected.get("route_fingerprint") != typed_route.get("route_fingerprint")
            or projected.get("authoring_observation_count")
            != len(case.get("authoring_source_observation_ids", ()))
            or projected.get("authoring_message_count")
            != len(evidence_binding.get("authoring_message_hashes", ()))
            or projected.get("authoring_thread_count")
            != len(evidence_binding.get("authoring_thread_hashes", ()))
            or projected.get("authoring_observation_set_fingerprint")
            != sha256_json(evidence_binding.get("authoring_observation_hashes", ()))
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_private_manifest_projection_cross_binding_mismatch"
            )


def _validate_extension_execution_manifest_lineage(
    *,
    manifest: Mapping[str, Any],
    projection: Mapping[str, Any],
    preflight_report: Mapping[str, Any],
    execution_context: _HoldoutExecutionContext,
    bundle: MailEvidenceBundle,
    holdout_policy: _HoldoutPolicy,
) -> None:
    """Validate private extension lineage after the persistent claim exists."""

    if holdout_policy.policy_id != EXTENSION_HOLDOUT_POLICY_ID:
        raise IndependentMailHoldoutUatError("holdout_policy_id_invalid")
    hashes = preflight_report.get("hashes")
    if not isinstance(hashes, Mapping):
        raise IndependentMailHoldoutUatError("holdout_extension_preflight_binding_invalid")
    source_bindings = manifest.get("source_bindings")
    development_binding = manifest.get("development_exclusion_binding")
    base_binding = manifest.get("base_holdout_binding")
    selection_policy = manifest.get("selection_policy")
    partition_policy = manifest.get("partition_policy")
    selection_proof = manifest.get("selection_proof")
    disjointness = manifest.get("disjointness_proof")
    if any(
        not isinstance(value, Mapping)
        for value in (
            source_bindings,
            development_binding,
            base_binding,
            selection_policy,
            partition_policy,
            selection_proof,
            disjointness,
        )
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_manifest_boundary_invalid")
    assert isinstance(source_bindings, Mapping)
    assert isinstance(development_binding, Mapping)
    assert isinstance(base_binding, Mapping)
    assert isinstance(selection_policy, Mapping)
    assert isinstance(partition_policy, Mapping)
    assert isinstance(selection_proof, Mapping)
    assert isinstance(disjointness, Mapping)

    permission_fingerprints = {
        sha256_json(observation.permission_scope)
        for observation in execution_context.observations_by_id.values()
    }
    if len(permission_fingerprints) != 1:
        raise IndependentMailHoldoutUatError("holdout_extension_source_binding_mismatch")
    expected_source_bindings = {
        "bundle_artifact_sha256": hashes.get("retrieval_bundle_sha256"),
        "retrieval_snapshot_sha256": hashes.get("retrieval_snapshot_sha256"),
        "source_snapshot_fingerprint": hashes.get("source_snapshot_fingerprint"),
        "source_inventory_fingerprint": hashes.get("source_inventory_fingerprint"),
        "source_provenance_fingerprint": hashes.get("source_provenance_fingerprint"),
        "permission_fingerprint": next(iter(permission_fingerprints)),
        "mail_evidence_bundle_fingerprint": sha256_json(bundle.to_dict()),
        "tokenizer_profile_fingerprint": hashes.get("lexical_profile_fingerprint"),
        "index_fingerprint": hashes.get("index_fingerprint"),
        "snapshot_fingerprint": hashes.get("retrieval_snapshot_fingerprint"),
    }
    if dict(source_bindings) != expected_source_bindings:
        raise IndependentMailHoldoutUatError("holdout_extension_source_binding_mismatch")
    if (
        development_binding.get("manifest_sha256") != hashes.get("development_manifest_sha256")
        or development_binding.get("safe_report_sha256") != hashes.get("development_report_sha256")
        or development_binding.get("case_count") != 100
        or development_binding.get("artifact_id") != DEVELOPMENT_MANIFEST_ARTIFACT_ID
        or not isinstance(development_binding.get("registry_fingerprint"), str)
        or not isinstance(development_binding.get("manifest_fingerprint"), str)
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_development_binding_mismatch")
    if (
        base_binding != projection.get("base_holdout_binding")
        or base_binding.get("artifact_id") != HOLDOUT_EXTENSION_BASE_ARTIFACT_ID
        or base_binding.get("case_count") != HOLDOUT_EXTENSION_BASE_CASE_COUNT
        or base_binding.get("safe_report_sha256") != hashes.get("holdout_report_sha256")
        or not isinstance(base_binding.get("manifest_sha256"), str)
        or not isinstance(base_binding.get("registry_fingerprint"), str)
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_base_binding_mismatch")
    for value, reason_code in (
        (
            development_binding.get("manifest_fingerprint"),
            "holdout_extension_development_binding_mismatch",
        ),
        (
            development_binding.get("registry_fingerprint"),
            "holdout_extension_development_binding_mismatch",
        ),
        (
            base_binding.get("manifest_sha256"),
            "holdout_extension_base_binding_mismatch",
        ),
        (
            base_binding.get("manifest_fingerprint"),
            "holdout_extension_base_binding_mismatch",
        ),
        (
            base_binding.get("registry_fingerprint"),
            "holdout_extension_base_binding_mismatch",
        ),
    ):
        _require_sha256(value, reason_code)
    if (
        sha256_json(selection_policy) != HOLDOUT_EXTENSION_SELECTION_POLICY_FINGERPRINT
        or sha256_json(partition_policy) != HOLDOUT_EXTENSION_PARTITION_POLICY_FINGERPRINT
        or selection_policy.get("selection_policy_id") != HOLDOUT_EXTENSION_SELECTION_POLICY_ID
        or selection_policy.get("target_strata_counts") != dict(holdout_policy.strata_counts)
        or selection_policy.get("extension_case_count") != holdout_policy.case_count
        or selection_policy.get("base_holdout_case_count") != HOLDOUT_EXTENSION_BASE_CASE_COUNT
        or selection_policy.get("combined_acceptance_case_count")
        != HOLDOUT_EXTENSION_COMBINED_CASE_COUNT
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_policy_binding_mismatch")
    if (
        selection_proof.get("status") != "passed"
        or selection_proof.get("selected_counts") != dict(holdout_policy.strata_counts)
        or selection_proof.get("selected_candidate_count") != holdout_policy.case_count
        or selection_proof.get("selection_proof_fingerprint")
        != _payload_fingerprint(selection_proof, "selection_proof_fingerprint")
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_selection_proof_invalid")
    _validate_extension_capacity_audit_binding(
        binding=manifest.get("capacity_audit_binding"),
        source_snapshot_fingerprint=source_bindings.get("source_snapshot_fingerprint"),
        partition_fingerprint=manifest.get("partition_fingerprint"),
        selection_proof=selection_proof,
    )

    occurrence_to_message = {
        occurrence.message_occurrence_id: occurrence.email_message_id
        for occurrence in bundle.message_occurrences
    }
    message_to_thread = {message.email_message_id: message.thread_id for message in bundle.messages}
    owner_user_id = bundle.mail_import_session.owner_user_id
    denied_requester_id = _extension_denied_requester_id(
        owner_user_id=owner_user_id,
        workspace_id=bundle.mail_import_session.workspace_id,
    )
    used_observation_ids: list[str] = []
    used_message_ids: list[str] = []
    used_thread_ids: list[str] = []
    query_hashes: list[str] = []
    case_fingerprints: list[str] = []
    strata = Counter()
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != holdout_policy.case_count:
        raise IndependentMailHoldoutUatError("holdout_case_count_mismatch")
    for case in cases:
        if not isinstance(case, Mapping):
            raise IndependentMailHoldoutUatError("holdout_extension_case_invalid")
        _validate_extension_execution_case(
            case=case,
            holdout_policy=holdout_policy,
            partition_fingerprint=_require_sha256(
                manifest.get("partition_fingerprint"),
                "holdout_extension_partition_binding_invalid",
            ),
            observations_by_id=execution_context.observations_by_id,
            observation_hash_by_id=execution_context.observation_hash_by_id,
            occurrence_to_message=occurrence_to_message,
            message_to_thread=message_to_thread,
            owner_user_id=owner_user_id,
            denied_requester_id=denied_requester_id,
            used_observation_ids=used_observation_ids,
            used_message_ids=used_message_ids,
            used_thread_ids=used_thread_ids,
            query_hashes=query_hashes,
            case_fingerprints=case_fingerprints,
            strata=strata,
        )
    if dict(sorted(strata.items())) != dict(holdout_policy.strata_counts):
        raise IndependentMailHoldoutUatError("holdout_strata_coverage_mismatch")
    if (
        len(used_observation_ids) != len(set(used_observation_ids))
        or len(used_message_ids) != len(set(used_message_ids))
        or len(used_thread_ids) != len(set(used_thread_ids))
        or len(query_hashes) != len(set(query_hashes))
        or len(case_fingerprints) != len(set(case_fingerprints))
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_internal_reuse_detected")
    observation_set = set(used_observation_ids)
    message_set = set(used_message_ids)
    thread_set = set(used_thread_ids)
    expected_disjointness = {
        "status": "passed",
        "development_observation_overlap_count": 0,
        "development_message_overlap_count": 0,
        "development_thread_overlap_count": 0,
        "base_holdout_observation_overlap_count": 0,
        "base_holdout_message_overlap_count": 0,
        "base_holdout_thread_overlap_count": 0,
        "base_holdout_query_overlap_count": 0,
        "base_holdout_case_fingerprint_overlap_count": 0,
        "extension_observation_reuse_count": 0,
        "extension_message_reuse_count": 0,
        "extension_thread_reuse_count": 0,
        "extension_query_reuse_count": 0,
        "extension_case_fingerprint_reuse_count": 0,
        "extension_observation_count": len(observation_set),
        "extension_message_count": len(message_set),
        "extension_thread_count": len(thread_set),
        "extension_observation_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in observation_set)
        ),
        "extension_message_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in message_set)
        ),
        "extension_thread_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in thread_set)
        ),
        "extension_query_set_fingerprint": sha256_json(sorted(query_hashes)),
        "extension_case_set_fingerprint": sha256_json(sorted(case_fingerprints)),
    }
    if dict(disjointness) != expected_disjointness:
        raise IndependentMailHoldoutUatError("holdout_extension_disjointness_proof_invalid")


def _validate_extension_execution_case(
    *,
    case: Mapping[str, Any],
    holdout_policy: _HoldoutPolicy,
    partition_fingerprint: str,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    occurrence_to_message: Mapping[str, str],
    message_to_thread: Mapping[str, str | None],
    owner_user_id: str,
    denied_requester_id: str,
    used_observation_ids: list[str],
    used_message_ids: list[str],
    used_thread_ids: list[str],
    query_hashes: list[str],
    case_fingerprints: list[str],
    strata: Counter[str],
) -> None:
    required_keys = {
        "case_id",
        "domain",
        "source_kind",
        "stratum_id",
        "intent_kind",
        "pattern",
        "result_kind",
        "query_text",
        "query_hash",
        "requester_user_id",
        "required_source_observation_ids",
        "forbidden_source_observation_ids",
        "authoring_source_observation_ids",
        "required_match_count",
        "limit",
        "typed_route",
        "route_fingerprint",
        "source_evidence_binding",
        "adjudication",
        "private_fingerprint",
    }
    if set(case) != required_keys:
        raise IndependentMailHoldoutUatError("holdout_extension_case_shape_invalid")
    stratum = _case_stratum(case)
    route = case.get("typed_route")
    evidence_binding = case.get("source_evidence_binding")
    adjudication = case.get("adjudication")
    if (
        stratum not in holdout_policy.strata_counts
        or case.get("domain") != "mail"
        or case.get("source_kind") != "mail"
        or not isinstance(route, Mapping)
        or not isinstance(evidence_binding, Mapping)
        or not isinstance(adjudication, Mapping)
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_case_shape_invalid")
    query_text = case.get("query_text")
    query_hash = _require_sha256(
        case.get("query_hash"),
        "holdout_extension_case_query_hash_invalid",
    )
    case_fingerprint = _require_sha256(
        case.get("private_fingerprint"),
        "holdout_case_fingerprint_invalid",
    )
    route_fingerprint = _require_sha256(
        case.get("route_fingerprint"),
        "holdout_extension_case_route_invalid",
    )
    candidate_fingerprint = _require_sha256(
        evidence_binding.get("candidate_fingerprint"),
        "holdout_extension_case_lineage_fingerprint_invalid",
    )
    if (
        not isinstance(case.get("case_id"), str)
        or not case["case_id"]
        or not isinstance(query_text, str)
        or not query_text
        or query_hash != sha256_json(query_text)
        or route_fingerprint != _payload_fingerprint(route, "route_fingerprint")
        or route.get("route_fingerprint") != route_fingerprint
        or route.get("stratum_id") != stratum
        or route.get("source_kind") != "mail"
        or route.get("intent_kind") != case.get("intent_kind")
        or route.get("result_kind") != case.get("result_kind")
        or route.get("query_template_version") != 1
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_case_route_invalid")
    expected_route = {
        "graph_required": ("relation_reasoning", "relation_reasoning", "owner_match"),
        "no_answer_near_miss_negative": (
            "relation_reasoning",
            "relation_reasoning",
            "no_answer",
        ),
        "exact_set": ("exact_inventory", "exact_inventory", "exact_set"),
        "exact_count": ("exact_inventory", "exact_inventory", "exact_count"),
        "exact_aggregation": (
            "exact_inventory",
            "exact_inventory",
            "exact_aggregation",
        ),
        "permission_denied": ("evidence_lookup", "evidence_lookup", "permission_denied"),
        "single_document_direct_lookup": (
            "evidence_lookup",
            "evidence_lookup",
            "source_evidence",
        ),
    }[stratum]
    if (
        route.get("query_class"),
        case.get("intent_kind"),
        case.get("result_kind"),
    ) != expected_route:
        raise IndependentMailHoldoutUatError("holdout_extension_case_route_invalid")
    required_ids = tuple(
        sorted(
            _string_list(
                case.get("required_source_observation_ids"),
                "holdout_required_observation_ids_invalid",
            )
        )
    )
    forbidden_ids = tuple(
        sorted(
            _string_list(
                case.get("forbidden_source_observation_ids"),
                "holdout_forbidden_observation_ids_invalid",
            )
        )
    )
    authoring_ids = tuple(
        sorted(
            _string_list(
                case.get("authoring_source_observation_ids"),
                "holdout_authoring_observation_ids_invalid",
            )
        )
    )
    _validate_extension_case_shape(
        stratum=stratum,
        result_kind=str(case["result_kind"]),
        required_ids=required_ids,
        forbidden_ids=forbidden_ids,
        authoring_ids=authoring_ids,
    )
    if (
        case.get("required_match_count") != len(required_ids)
        or not isinstance(case.get("limit"), int)
        or isinstance(case.get("limit"), bool)
        or int(case["limit"]) <= 0
        or set(authoring_ids) - set(observations_by_id)
        or set(authoring_ids) - set(observation_hash_by_id)
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_case_lineage_invalid")
    authoring_observation_hashes = sorted(
        observation_hash_by_id[observation_id] for observation_id in authoring_ids
    )
    required_observation_hashes = sorted(
        observation_hash_by_id[observation_id] for observation_id in required_ids
    )
    message_ids: list[str] = []
    thread_ids: list[str] = []
    for observation_id in authoring_ids:
        occurrence_id = _observation_occurrence_id(observations_by_id[observation_id])
        message_id = occurrence_to_message.get(str(occurrence_id))
        thread_id = message_to_thread.get(str(message_id))
        if not occurrence_id or not message_id or not thread_id:
            raise IndependentMailHoldoutUatError("holdout_extension_case_lineage_invalid")
        message_ids.append(message_id)
        thread_ids.append(thread_id)
    expected_evidence_binding = {
        "candidate_fingerprint": candidate_fingerprint,
        "required_observation_hashes": required_observation_hashes,
        "authoring_observation_hashes": authoring_observation_hashes,
        "authoring_message_hashes": sorted(sha256_json(value) for value in message_ids),
        "authoring_thread_hashes": sorted(sha256_json(value) for value in thread_ids),
        "partition_fingerprint": partition_fingerprint,
    }
    if dict(evidence_binding) != expected_evidence_binding or case_fingerprint != sha256_json(
        {
            "candidate_fingerprint": candidate_fingerprint,
            "query_hash": query_hash,
            "route_fingerprint": route_fingerprint,
            "authoring_observation_hashes": authoring_observation_hashes,
        }
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_case_lineage_invalid")
    _validate_extension_adjudication(
        stratum=stratum,
        adjudication=adjudication,
        required_ids=required_ids,
        forbidden_ids=forbidden_ids,
        requester_user_id=str(case["requester_user_id"]),
    )
    expected_requester = denied_requester_id if stratum == "permission_denied" else owner_user_id
    if case.get("requester_user_id") != expected_requester:
        raise IndependentMailHoldoutUatError("holdout_extension_requester_binding_mismatch")
    used_observation_ids.extend(authoring_ids)
    used_message_ids.extend(message_ids)
    used_thread_ids.extend(thread_ids)
    query_hashes.append(query_hash)
    case_fingerprints.append(case_fingerprint)
    strata[stratum] += 1


def _validate_extension_case_shape(
    *,
    stratum: str,
    result_kind: str,
    required_ids: tuple[str, ...],
    forbidden_ids: tuple[str, ...],
    authoring_ids: tuple[str, ...],
) -> None:
    valid = {
        "graph_required": (
            result_kind == "owner_match"
            and len(required_ids) == 2
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "single_document_direct_lookup": (
            result_kind == "source_evidence"
            and len(required_ids) == 1
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "exact_set": (
            result_kind == "exact_set"
            and len(required_ids) == 1
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "exact_count": (
            result_kind == "exact_count"
            and len(required_ids) == 1
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "exact_aggregation": (
            result_kind == "exact_aggregation"
            and len(required_ids) == 1
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "no_answer_near_miss_negative": (
            result_kind == "no_answer"
            and not required_ids
            and len(forbidden_ids) == 2
            and authoring_ids == forbidden_ids
        ),
        "permission_denied": (
            result_kind == "permission_denied"
            and not required_ids
            and len(forbidden_ids) == 1
            and authoring_ids == forbidden_ids
        ),
    }.get(stratum)
    if valid is not True:
        raise IndependentMailHoldoutUatError("holdout_extension_case_stratum_shape_invalid")


def _validate_extension_adjudication(
    *,
    stratum: str,
    adjudication: Mapping[str, Any],
    required_ids: tuple[str, ...],
    forbidden_ids: tuple[str, ...],
    requester_user_id: str,
) -> None:
    expected_answer_kind = {
        "graph_required": "source_backed_relation",
        "single_document_direct_lookup": "source_evidence",
        "exact_set": "exact_set",
        "exact_count": "exact_count",
        "exact_aggregation": "exact_aggregation",
        "no_answer_near_miss_negative": "no_answer",
        "permission_denied": "permission_denied",
    }[stratum]
    if adjudication.get("answer_kind") != expected_answer_kind:
        raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")
    if stratum in {
        "graph_required",
        "single_document_direct_lookup",
        "exact_set",
        "exact_count",
        "exact_aggregation",
    }:
        adjudicated_required_ids = tuple(
            sorted(
                _string_list(
                    adjudication.get("required_source_observation_ids"),
                    "holdout_extension_adjudication_invalid",
                )
            )
        )
        if adjudicated_required_ids != required_ids:
            raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")
    if stratum == "graph_required":
        for field_name in ("shared_identifier", "left_concept", "right_concept"):
            if not isinstance(adjudication.get(field_name), str) or not adjudication[field_name]:
                raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")
    elif stratum in {"exact_set", "exact_count", "exact_aggregation"}:
        if adjudication.get("inventory_kind") != "protected_identifier":
            raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")
        if stratum == "exact_set":
            _string_list(adjudication.get("items"), "holdout_extension_adjudication_invalid")
        elif stratum == "exact_count":
            count = adjudication.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")
        else:
            counts = adjudication.get("counts_by_identifier_kind")
            if (
                not isinstance(counts, Mapping)
                or not counts
                or any(
                    not isinstance(key, str)
                    or not key
                    or not isinstance(value, int)
                    or isinstance(value, bool)
                    or value <= 0
                    for key, value in counts.items()
                )
            ):
                raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")
    elif stratum == "no_answer_near_miss_negative":
        adjudicated_forbidden_ids = tuple(
            sorted(
                _string_list(
                    adjudication.get("forbidden_source_observation_ids"),
                    "holdout_extension_adjudication_invalid",
                )
            )
        )
        _require_sha256(
            adjudication.get("absence_proof_fingerprint"),
            "holdout_extension_adjudication_invalid",
        )
        if adjudicated_forbidden_ids != forbidden_ids:
            raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")
    elif stratum == "permission_denied":
        denied_ids = tuple(
            sorted(
                _string_list(
                    adjudication.get("denied_source_observation_ids"),
                    "holdout_extension_adjudication_invalid",
                )
            )
        )
        if denied_ids != forbidden_ids:
            raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")
    if stratum in {"single_document_direct_lookup", "permission_denied"} and (
        adjudication.get("requester_user_id") != requester_user_id
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_adjudication_invalid")


def _oracle_free_case_projection(case: Any) -> dict[str, Any]:
    if not isinstance(case, Mapping):
        raise IndependentMailHoldoutUatError("holdout_case_invalid")
    allowed = set(_ORACLE_FREE_CASE_FIELD_NAMES) | set(_PRIVATE_ORACLE_FIELD_NAMES)
    if set(case) - allowed:
        raise IndependentMailHoldoutUatError("holdout_case_unregistered_field")
    projected = {
        field_name: case[field_name]
        for field_name in _ORACLE_FREE_CASE_FIELD_NAMES
        if field_name in case
    }
    if any(field_name in projected for field_name in _PRIVATE_ORACLE_FIELD_NAMES):
        raise IndependentMailHoldoutUatError("holdout_projection_oracle_field_present")
    return projected


def _assert_oracle_free_projection(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _PRIVATE_ORACLE_FIELD_NAMES:
                raise IndependentMailHoldoutUatError("holdout_projection_oracle_field_present")
            _assert_oracle_free_projection(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_oracle_free_projection(nested)


def _validated_private_manifest_binding(
    projection: Mapping[str, Any],
    *,
    expected_manifest_sha256: str,
    holdout_policy: _HoldoutPolicy = _BASE_HOLDOUT_POLICY,
) -> Mapping[str, Any]:
    binding = projection.get("private_manifest_binding")
    if not isinstance(binding, Mapping):
        raise IndependentMailHoldoutUatError("holdout_projection_manifest_binding_missing")
    manifest_fingerprint = _require_sha256(
        binding.get("manifest_fingerprint"),
        "holdout_projection_manifest_binding_invalid",
    )
    if holdout_policy.policy_id == EXTENSION_HOLDOUT_POLICY_ID:
        manifest_fingerprint = _require_sha256(
            binding.get("manifest_fingerprint"),
            "holdout_extension_projection_manifest_binding_invalid",
        )
        if (
            binding.get("artifact_id") != holdout_policy.manifest_artifact_id
            or binding.get("schema_version") != holdout_policy.manifest_schema_version
            or binding.get("manifest_sha256") != expected_manifest_sha256
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_extension_projection_manifest_binding_mismatch"
            )
        return {
            **dict(binding),
            "private_manifest_id": sha256_json(
                {
                    "artifact_id": holdout_policy.manifest_artifact_id,
                    "manifest_fingerprint": manifest_fingerprint,
                }
            ),
            "case_count": holdout_policy.case_count,
            "partition_fingerprint": projection.get("partition_fingerprint"),
        }
    partition_fingerprint = _require_sha256(
        binding.get("partition_fingerprint"),
        "holdout_projection_manifest_binding_invalid",
    )
    expected_manifest_id = sha256_json(
        {
            "artifact_id": holdout_policy.manifest_artifact_id,
            "manifest_fingerprint": manifest_fingerprint,
        }
    )
    if (
        binding.get("manifest_artifact_id") != holdout_policy.manifest_artifact_id
        or binding.get("manifest_schema_version") != holdout_policy.manifest_schema_version
        or binding.get("manifest_classification") != holdout_policy.manifest_classification
        or binding.get("private_manifest_id") != expected_manifest_id
        or binding.get("manifest_sha256") != expected_manifest_sha256
        or binding.get("case_count") != holdout_policy.case_count
        or projection.get("case_count") != holdout_policy.case_count
        or projection.get("case_strata_counts") != dict(holdout_policy.strata_counts)
        or partition_fingerprint != binding.get("partition_fingerprint")
    ):
        raise IndependentMailHoldoutUatError("holdout_projection_manifest_binding_mismatch")
    return binding


def _decode_private_holdout_manifest_after_claim(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    oracle_free_projection: Mapping[str, Any],
    holdout_policy: _HoldoutPolicy = _BASE_HOLDOUT_POLICY,
    execution_context: _HoldoutExecutionContext | None = None,
    bundle: MailEvidenceBundle | None = None,
) -> dict[str, Any]:
    """Decode and cross-bind the private oracle only after claim acquisition."""

    _validated_private_manifest_binding(
        oracle_free_projection,
        expected_manifest_sha256=expected_manifest_sha256,
        holdout_policy=holdout_policy,
    )
    _payload, manifest = _read_sealed_json(
        manifest_path,
        expected_manifest_sha256,
        max_bytes=MAX_MANIFEST_BYTES,
        invalid_reason="holdout_manifest_missing_or_invalid_after_claim",
        seal_reason="holdout_manifest_seal_mismatch_after_claim",
    )
    _validate_private_manifest_boundary(manifest, holdout_policy=holdout_policy)
    if holdout_policy.policy_id == BASE_HOLDOUT_POLICY_ID:
        if _is_source_author_hashed_base_projection(oracle_free_projection):
            if execution_context is None or bundle is None:
                raise IndependentMailHoldoutUatError("holdout_post_claim_source_context_missing")
            _validate_base_manifest_projection_cross_binding_after_claim(
                manifest=manifest,
                projection=oracle_free_projection,
                execution_context=execution_context,
                bundle=bundle,
            )
        else:
            expected_projection = build_oracle_free_holdout_projection(
                private_manifest=manifest,
                private_manifest_sha256=expected_manifest_sha256,
                holdout_policy=holdout_policy,
            )
            if expected_projection != oracle_free_projection:
                raise IndependentMailHoldoutUatError(
                    "holdout_private_manifest_projection_cross_binding_mismatch"
                )
    else:
        _validate_extension_manifest_projection_cross_binding(
            manifest=manifest,
            manifest_sha256=expected_manifest_sha256,
            projection=oracle_free_projection,
            holdout_policy=holdout_policy,
        )
    return manifest


def _is_source_author_hashed_base_projection(
    projection: Mapping[str, Any],
) -> bool:
    cases = projection.get("cases")
    if not isinstance(cases, list) or not cases:
        return False
    return all(
        isinstance(case, Mapping)
        and isinstance(case.get("source_evidence_binding"), Mapping)
        and case["source_evidence_binding"].get("projection_policy_fingerprint")
        == source_author_projection.SOURCE_AUTHOR_POLICY_FINGERPRINT
        for case in cases
    )


def _validate_base_manifest_projection_cross_binding_after_claim(
    *,
    manifest: Mapping[str, Any],
    projection: Mapping[str, Any],
    execution_context: _HoldoutExecutionContext,
    bundle: MailEvidenceBundle,
) -> None:
    """Crosswalk raw private identities only after the consumed claim exists."""

    cases = manifest.get("cases")
    projected_cases = projection.get("cases")
    if (
        not isinstance(cases, list)
        or not isinstance(projected_cases, list)
        or len(cases) != EXPECTED_CASE_COUNT
        or len(projected_cases) != EXPECTED_CASE_COUNT
    ):
        raise IndependentMailHoldoutUatError(
            "holdout_private_manifest_projection_cross_binding_mismatch"
        )
    if (
        projection.get("source_oracle_bindings") != manifest.get("source_oracle_bindings")
        or projection.get("development_exclusion_binding")
        != manifest.get("development_exclusion_binding")
        or projection.get("disjointness") != manifest.get("disjointness")
        or projection.get("case_count") != manifest.get("case_count")
        or projection.get("case_strata_counts") != manifest.get("case_strata_counts")
    ):
        raise IndependentMailHoldoutUatError(
            "holdout_private_manifest_projection_cross_binding_mismatch"
        )

    observations_by_id = execution_context.observations_by_id
    observation_hash_by_id = execution_context.observation_hash_by_id
    if not observations_by_id or set(observations_by_id) != set(observation_hash_by_id):
        raise IndependentMailHoldoutUatError("holdout_post_claim_source_context_invalid")
    for observation_id, observation in observations_by_id.items():
        if observation.observation_id != observation_id or observation_hash_by_id[
            observation_id
        ] != sha256_json(observation.to_dict()):
            raise IndependentMailHoldoutUatError("holdout_post_claim_source_context_invalid")

    occurrence_to_message = {
        occurrence.message_occurrence_id: occurrence.email_message_id
        for occurrence in bundle.message_occurrences
    }
    message_to_thread = {message.email_message_id: message.thread_id for message in bundle.messages}
    if len(occurrence_to_message) != len(bundle.message_occurrences) or len(
        message_to_thread
    ) != len(bundle.messages):
        raise IndependentMailHoldoutUatError("holdout_post_claim_source_context_invalid")
    observation_to_occurrence: dict[str, str] = {}
    occurrence_to_thread: dict[str, str] = {}
    for observation_id, observation in observations_by_id.items():
        occurrence_id = _observation_occurrence_id(observation)
        message_id = occurrence_to_message.get(str(occurrence_id))
        thread_id = message_to_thread.get(str(message_id))
        if not occurrence_id or not message_id or not thread_id:
            raise IndependentMailHoldoutUatError("holdout_post_claim_source_context_invalid")
        observation_to_occurrence[observation_id] = str(occurrence_id)
        occurrence_to_thread[str(occurrence_id)] = str(thread_id)
    source_lineage = {
        "observation_hashes": dict(observation_hash_by_id),
        "observation_types": {
            observation_id: observation.observation_type
            for observation_id, observation in observations_by_id.items()
        },
        "observation_to_occurrence": observation_to_occurrence,
        "occurrence_to_email_message": occurrence_to_message,
        "occurrence_to_thread": occurrence_to_thread,
    }
    permission_fingerprints = {
        sha256_json(observation.permission_scope) for observation in observations_by_id.values()
    }
    if len(permission_fingerprints) != 1:
        raise IndependentMailHoldoutUatError("holdout_post_claim_permission_scope_invalid")
    try:
        validated_cases = source_author_projection._validated_holdout_case_lineage(
            cases,
            source_lineage=source_lineage,
            source_permission_fingerprint=next(iter(permission_fingerprints)),
            partition_fingerprint=_require_sha256(
                manifest.get("partition_fingerprint"),
                "holdout_partition_fingerprint_invalid",
            ),
        )
        expected_cases = [
            source_author_projection._oracle_free_nonreversible_case_projection(case)
            for case in validated_cases
        ]
    except (
        KeyError,
        TypeError,
        ValueError,
        source_author_projection.HoldoutSourceAuthorProjectionInputsError,
    ) as exc:
        raise IndependentMailHoldoutUatError(
            "holdout_private_manifest_raw_lineage_crosswalk_invalid"
        ) from exc
    if expected_cases != projected_cases:
        raise IndependentMailHoldoutUatError(
            "holdout_private_manifest_projection_cross_binding_mismatch"
        )

    holdout_observation_ids = {
        observation_id
        for validated_case in validated_cases
        for observation_id in validated_case["authoring_ids"]
    }
    if not holdout_observation_ids:
        raise IndependentMailHoldoutUatError("holdout_post_claim_observation_set_invalid")
    project_validated_holdout_observations(
        observations_by_id=observations_by_id,
        observation_ids=holdout_observation_ids,
        bundle=bundle,
    )
    holdout_message_ids, holdout_thread_ids = _raw_message_thread_sets(
        holdout_observation_ids,
        observation_to_occurrence=observation_to_occurrence,
        occurrence_to_message=occurrence_to_message,
        message_to_thread=message_to_thread,
    )
    development_observation_ids = execution_context.development_observation_ids
    if not development_observation_ids:
        raise IndependentMailHoldoutUatError("holdout_post_claim_development_lineage_missing")
    development_message_ids, development_thread_ids = _raw_message_thread_sets(
        set(development_observation_ids),
        observation_to_occurrence=observation_to_occurrence,
        occurrence_to_message=occurrence_to_message,
        message_to_thread=message_to_thread,
    )
    expected_disjointness = {
        "status": "passed",
        "development_holdout_observation_overlap_count": len(
            development_observation_ids & holdout_observation_ids
        ),
        "development_holdout_message_overlap_count": len(
            development_message_ids & holdout_message_ids
        ),
        "development_holdout_thread_overlap_count": len(
            development_thread_ids & holdout_thread_ids
        ),
        "holdout_authoring_observation_count": len(holdout_observation_ids),
        "holdout_authoring_message_count": len(holdout_message_ids),
        "holdout_authoring_thread_count": len(holdout_thread_ids),
        "holdout_observation_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in holdout_observation_ids)
        ),
        "holdout_message_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in holdout_message_ids)
        ),
        "holdout_thread_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in holdout_thread_ids)
        ),
    }
    if (
        any(
            expected_disjointness[field_name]
            for field_name in (
                "development_holdout_observation_overlap_count",
                "development_holdout_message_overlap_count",
                "development_holdout_thread_overlap_count",
            )
        )
        or projection.get("disjointness") != expected_disjointness
    ):
        raise IndependentMailHoldoutUatError("holdout_post_claim_disjointness_crosswalk_mismatch")

    owner_user_id = bundle.mail_import_session.owner_user_id
    for raw_case in cases:
        stratum = _case_stratum(raw_case)
        requester_user_id = raw_case.get("requester_user_id")
        if not isinstance(requester_user_id, str) or not requester_user_id:
            raise IndependentMailHoldoutUatError("holdout_private_manifest_raw_identity_missing")
        authorized = authorize_mail_evidence_bundles(
            (bundle,),
            requester_user_id=requester_user_id,
            workspace_id=bundle.mail_import_session.workspace_id,
        )
        if stratum == "permission_denied":
            if requester_user_id == owner_user_id or authorized:
                raise IndependentMailHoldoutUatError(
                    "holdout_post_claim_permission_crosswalk_mismatch"
                )
        elif requester_user_id != owner_user_id or not authorized:
            raise IndependentMailHoldoutUatError("holdout_post_claim_permission_crosswalk_mismatch")


def _raw_message_thread_sets(
    observation_ids: set[str] | frozenset[str],
    *,
    observation_to_occurrence: Mapping[str, str],
    occurrence_to_message: Mapping[str, str],
    message_to_thread: Mapping[str, str | None],
) -> tuple[set[str], set[str]]:
    message_ids: set[str] = set()
    thread_ids: set[str] = set()
    for observation_id in observation_ids:
        occurrence_id = observation_to_occurrence.get(observation_id)
        message_id = occurrence_to_message.get(str(occurrence_id))
        thread_id = message_to_thread.get(str(message_id))
        if not occurrence_id or not message_id or not thread_id:
            raise IndependentMailHoldoutUatError("holdout_post_claim_observation_lineage_missing")
        message_ids.add(message_id)
        thread_ids.add(thread_id)
    return message_ids, thread_ids


def _validate_holdout_projection(
    *,
    holdout_policy: _HoldoutPolicy,
    **kwargs: Any,
) -> dict[str, Any]:
    if holdout_policy.policy_id == BASE_HOLDOUT_POLICY_ID:
        return _validate_base_holdout_projection(**kwargs)
    if holdout_policy.policy_id == EXTENSION_HOLDOUT_POLICY_ID:
        return _validate_extension_holdout_projection(
            holdout_policy=holdout_policy,
            **kwargs,
        )
    raise IndependentMailHoldoutUatError("holdout_policy_id_invalid")


def _validate_extension_holdout_projection(
    *,
    holdout_policy: _HoldoutPolicy,
    projection: Mapping[str, Any],
    manifest_sha256: str,
    safe_report: Mapping[str, Any],
    safe_report_sha256: str,
    retrieval_bundle_sha256: str,
    retrieval_snapshot_sha256: str,
    bundle_artifact: Mapping[str, Any],
    bundle: MailEvidenceBundle,
    retrieval_snapshot: Mapping[str, Any],
    source_report_sha256: str,
    development_manifest: Mapping[str, Any],
    development_manifest_sha256: str,
    development_report_sha256: str,
    development_observation_ids: frozenset[str],
    development_registry_fingerprint: str,
) -> dict[str, Any]:
    del (
        bundle,
        source_report_sha256,
        development_observation_ids,
        development_registry_fingerprint,
    )
    _assert_oracle_free_projection(projection)
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "classification",
        "execution_status",
        "quality_result_status",
        "final_acceptance_eligible",
        "diagnostic_only",
        "private_manifest_binding",
        "base_holdout_binding",
        "source_binding_hashes",
        "selection_policy_fingerprint",
        "capacity_audit_binding",
        "partition_policy_fingerprint",
        "partition_fingerprint",
        "selection_proof_fingerprint",
        "counts",
        "strata_counts",
        "disjointness_proof_hash",
        "cases",
        "projection_fingerprint",
    }
    if (
        set(projection) != expected_keys
        or projection.get("artifact_id") != holdout_policy.projection_artifact_id
        or projection.get("schema_version") != holdout_policy.projection_schema_version
        or projection.get("status") != "sealed_oracle_free"
        or projection.get("classification") != holdout_policy.manifest_classification
        or projection.get("execution_status") != "not_run"
        or projection.get("quality_result_status") != "not_read"
        or projection.get("final_acceptance_eligible") is not True
        or projection.get("diagnostic_only") is not False
        or projection.get("strata_counts") != dict(holdout_policy.strata_counts)
        or projection.get("projection_fingerprint")
        != _payload_fingerprint(projection, "projection_fingerprint")
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_projection_invalid")
    manifest_binding = projection.get("private_manifest_binding")
    if (
        not isinstance(manifest_binding, Mapping)
        or manifest_binding.get("artifact_id") != holdout_policy.manifest_artifact_id
        or manifest_binding.get("schema_version") != holdout_policy.manifest_schema_version
        or manifest_binding.get("manifest_sha256") != manifest_sha256
    ):
        raise IndependentMailHoldoutUatError(
            "holdout_extension_projection_manifest_binding_mismatch"
        )
    manifest_fingerprint = _require_sha256(
        manifest_binding.get("manifest_fingerprint"),
        "holdout_extension_projection_manifest_binding_invalid",
    )
    private_manifest_id = sha256_json(
        {
            "artifact_id": holdout_policy.manifest_artifact_id,
            "manifest_fingerprint": manifest_fingerprint,
        }
    )
    source_binding = projection.get("source_binding_hashes")
    expected_source_binding = {
        "bundle_artifact_sha256": retrieval_bundle_sha256,
        "retrieval_snapshot_sha256": retrieval_snapshot_sha256,
        "source_snapshot_fingerprint": retrieval_snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": retrieval_snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": retrieval_snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": retrieval_snapshot["permission_fingerprint"],
        "mail_evidence_bundle_fingerprint": retrieval_snapshot["mail_evidence_bundle_fingerprint"],
        "segmentation_profile_fingerprint": retrieval_snapshot["tokenizer_profile_fingerprint"],
        "index_fingerprint": retrieval_snapshot["index_fingerprint"],
        "snapshot_fingerprint": retrieval_snapshot["snapshot_fingerprint"],
    }
    if (
        not isinstance(source_binding, Mapping)
        or dict(source_binding) != expected_source_binding
        or bundle_artifact.get("bundle_fingerprint")
        != source_binding["mail_evidence_bundle_fingerprint"]
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_source_binding_mismatch")
    if (
        projection.get("selection_policy_fingerprint")
        != HOLDOUT_EXTENSION_SELECTION_POLICY_FINGERPRINT
        or projection.get("partition_policy_fingerprint")
        != HOLDOUT_EXTENSION_PARTITION_POLICY_FINGERPRINT
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_policy_binding_mismatch")
    partition_fingerprint = _require_sha256(
        projection.get("partition_fingerprint"),
        "holdout_extension_partition_binding_invalid",
    )
    _require_sha256(
        projection.get("selection_proof_fingerprint"),
        "holdout_extension_selection_proof_invalid",
    )
    _validate_extension_capacity_audit_binding(
        binding=projection.get("capacity_audit_binding"),
        source_snapshot_fingerprint=source_binding["source_snapshot_fingerprint"],
        partition_fingerprint=partition_fingerprint,
        selection_proof_fingerprint=projection.get("selection_proof_fingerprint"),
    )
    _require_sha256(
        projection.get("disjointness_proof_hash"),
        "holdout_extension_disjointness_proof_invalid",
    )
    counts = projection.get("counts")
    if (
        not isinstance(counts, Mapping)
        or counts.get("base_case_count") != HOLDOUT_EXTENSION_BASE_CASE_COUNT
        or counts.get("extension_case_count") != holdout_policy.case_count
        or counts.get("combined_acceptance_case_count") != HOLDOUT_EXTENSION_COMBINED_CASE_COUNT
        or counts.get("overlap_count") != 0
        or counts.get("reuse_count") != 0
        or counts.get("blocker_count") != 0
        or not isinstance(counts.get("selected_observation_count"), int)
        or not isinstance(counts.get("selected_message_count"), int)
        or not isinstance(counts.get("selected_thread_count"), int)
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_projection_counts_invalid")
    base_binding = projection.get("base_holdout_binding")
    if (
        not isinstance(base_binding, Mapping)
        or base_binding.get("artifact_id") != HOLDOUT_EXTENSION_BASE_ARTIFACT_ID
        or base_binding.get("case_count") != HOLDOUT_EXTENSION_BASE_CASE_COUNT
        or base_binding.get("safe_report_sha256") != safe_report_sha256
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_base_binding_mismatch")
    _validate_extension_base_safe_report(
        safe_report,
        safe_report_sha256=safe_report_sha256,
        base_binding=base_binding,
    )
    cases = projection.get("cases")
    if not isinstance(cases, list) or len(cases) != holdout_policy.case_count:
        raise IndependentMailHoldoutUatError("holdout_case_count_mismatch")
    seen_manifest_entries: set[str] = set()
    seen_case_ids: set[str] = set()
    seen_query_hashes: set[str] = set()
    strata = Counter()
    expected_case_keys = {
        "manifest_entry_hash",
        "case_id_hash",
        "query_hash",
        "stratum_id",
        "identifier_kind",
        "route",
        "route_fingerprint",
        "authoring_observation_count",
        "authoring_message_count",
        "authoring_thread_count",
        "authoring_observation_set_fingerprint",
    }
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != expected_case_keys:
            raise IndependentMailHoldoutUatError("holdout_extension_case_invalid")
        manifest_entry_hash = _require_sha256(
            case.get("manifest_entry_hash"),
            "holdout_extension_case_manifest_entry_hash_invalid",
        )
        case_id_hash = _require_sha256(
            case.get("case_id_hash"),
            "holdout_extension_case_id_hash_invalid",
        )
        query_hash = _require_sha256(
            case.get("query_hash"),
            "holdout_extension_case_query_hash_invalid",
        )
        if (
            manifest_entry_hash in seen_manifest_entries
            or case_id_hash in seen_case_ids
            or query_hash in seen_query_hashes
        ):
            raise IndependentMailHoldoutUatError("holdout_extension_case_identity_duplicate")
        seen_manifest_entries.add(manifest_entry_hash)
        seen_case_ids.add(case_id_hash)
        seen_query_hashes.add(query_hash)
        stratum = case.get("stratum_id")
        if stratum not in holdout_policy.strata_counts:
            raise IndependentMailHoldoutUatError("holdout_extension_case_stratum_invalid")
        route = case.get("route")
        if (
            not isinstance(route, Mapping)
            or route.get("stratum_id") != stratum
            or route.get("source_kind") != "mail"
            or case.get("route_fingerprint")
            != _payload_fingerprint(
                route,
                "route_fingerprint",
            )
            or route.get("route_fingerprint") != case.get("route_fingerprint")
        ):
            raise IndependentMailHoldoutUatError("holdout_extension_case_route_invalid")
        for count_field in (
            "authoring_observation_count",
            "authoring_message_count",
            "authoring_thread_count",
        ):
            value = case.get(count_field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise IndependentMailHoldoutUatError("holdout_extension_case_count_invalid")
        _require_sha256(
            case.get("authoring_observation_set_fingerprint"),
            "holdout_extension_case_lineage_fingerprint_invalid",
        )
        strata[str(stratum)] += 1
    if dict(sorted(strata.items())) != dict(holdout_policy.strata_counts):
        raise IndependentMailHoldoutUatError("holdout_strata_coverage_mismatch")
    if development_manifest.get("case_count") != 100 or not isinstance(
        development_manifest.get("manifest_fingerprint"), str
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_development_binding_invalid")
    _require_sha256(
        development_manifest_sha256,
        "holdout_extension_development_binding_invalid",
    )
    _require_sha256(
        development_report_sha256,
        "holdout_extension_development_binding_invalid",
    )
    selected_count = int(counts["selected_observation_count"])
    return {
        "case_count": holdout_policy.case_count,
        "strata_counts": dict(holdout_policy.strata_counts),
        "readable_observation_count": selected_count,
        "observation_type_counts": {
            "email_header": 0,
            "email_body_segment": selected_count,
        },
        "projected_observation_count": selected_count,
        "projection_type_counts": {
            "email_header": 0,
            "email_body_segment": selected_count,
        },
        "projection_fingerprint": projection["projection_fingerprint"],
        "permission_denied_case_count": holdout_policy.strata_counts["permission_denied"],
        "manifest_fingerprint": manifest_fingerprint,
        "private_manifest_id": private_manifest_id,
        "partition_fingerprint": partition_fingerprint,
    }


def _validate_extension_base_safe_report(
    report: Mapping[str, Any],
    *,
    safe_report_sha256: str,
    base_binding: Mapping[str, Any],
) -> None:
    if (
        report.get("artifact_id") != HOLDOUT_EXTENSION_BASE_REPORT_ARTIFACT_ID
        or report.get("schema_version") != 2
        or report.get("status") != "passed"
        or report.get("execution_status") != "not_run"
        or report.get("quality_result_status") != "not_read"
        or report.get("strata_counts") != EXPECTED_STRATA_COUNTS
        or report.get("report_fingerprint")
        != _payload_fingerprint(
            report,
            "report_fingerprint",
        )
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_base_report_invalid")
    counts = report.get("counts")
    hashes = report.get("hashes")
    if (
        not isinstance(counts, Mapping)
        or not isinstance(hashes, Mapping)
        or counts.get("case_count") != HOLDOUT_EXTENSION_BASE_CASE_COUNT
        or counts.get("blocker_count") != 0
        or hashes.get("manifest_sha256") != base_binding.get("manifest_sha256")
        or safe_report_sha256 != base_binding.get("safe_report_sha256")
    ):
        raise IndependentMailHoldoutUatError("holdout_extension_base_report_binding_mismatch")
    try:
        assert_no_public_raw_references(
            report,
            HOLDOUT_EXTENSION_BASE_REPORT_ARTIFACT_ID,
        )
    except ContractValidationError as exc:
        raise IndependentMailHoldoutUatError("holdout_extension_base_report_private_leak") from exc


def _validate_base_holdout_projection(
    *,
    projection: Mapping[str, Any],
    manifest_sha256: str,
    safe_report: Mapping[str, Any],
    safe_report_sha256: str,
    retrieval_bundle_sha256: str,
    retrieval_snapshot_sha256: str,
    bundle_artifact: Mapping[str, Any],
    bundle: MailEvidenceBundle,
    retrieval_snapshot: Mapping[str, Any],
    source_report_sha256: str,
    development_manifest: Mapping[str, Any],
    development_manifest_sha256: str,
    development_report_sha256: str,
    development_observation_ids: frozenset[str],
    development_registry_fingerprint: str,
) -> dict[str, Any]:
    _assert_oracle_free_projection(projection)
    if (
        projection.get("artifact_id") != HOLDOUT_ORACLE_FREE_PROJECTION_ARTIFACT_ID
        or projection.get("schema_version") != HOLDOUT_ORACLE_FREE_PROJECTION_SCHEMA_VERSION
        or projection.get("status") != "sealed_oracle_free"
        or projection.get("execution_status") != "not_run"
        or projection.get("quality_result_status") != "not_read"
        or projection.get("projection_fingerprint")
        != _payload_fingerprint(projection, "projection_fingerprint")
    ):
        raise IndependentMailHoldoutUatError("holdout_oracle_free_projection_invalid")
    manifest_binding = _validated_private_manifest_binding(
        projection,
        expected_manifest_sha256=manifest_sha256,
    )
    source_binding = projection.get("source_oracle_bindings")
    if not isinstance(source_binding, Mapping):
        raise IndependentMailHoldoutUatError("holdout_source_binding_missing")
    expected_source_binding = {
        "bundle_artifact_sha256": retrieval_bundle_sha256,
        "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
        "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
        "retrieval_snapshot_sha256": retrieval_snapshot_sha256,
        "source_report_sha256": source_report_sha256,
        "source_snapshot_fingerprint": retrieval_snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": retrieval_snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": retrieval_snapshot["source_provenance_fingerprint"],
        "index_fingerprint": retrieval_snapshot["index_fingerprint"],
        "tokenizer_profile_fingerprint": retrieval_snapshot["tokenizer_profile_fingerprint"],
    }
    for key, expected_value in expected_source_binding.items():
        if source_binding.get(key) != expected_value:
            raise IndependentMailHoldoutUatError("holdout_source_binding_mismatch")

    development_binding = projection.get("development_exclusion_binding")
    if not isinstance(development_binding, Mapping):
        raise IndependentMailHoldoutUatError("holdout_development_binding_missing")
    expected_development = {
        "development_case_count": development_manifest["case_count"],
        "development_manifest_fingerprint": development_manifest["manifest_fingerprint"],
        "development_manifest_sha256": development_manifest_sha256,
        "development_registry_fingerprint": development_registry_fingerprint,
        "development_safe_report_sha256": development_report_sha256,
    }
    if dict(development_binding) != expected_development:
        raise IndependentMailHoldoutUatError("holdout_development_binding_mismatch")

    cases = projection.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        raise IndependentMailHoldoutUatError("holdout_case_count_mismatch")
    case_ids: set[str] = set()
    case_fingerprints: set[str] = set()
    strata = Counter()
    holdout_observation_hashes: set[str] = set()
    permission_cases: list[Mapping[str, Any]] = []
    expected_evidence_binding_keys = {
        "source_evidence_binding_fingerprint",
        "required_observation_hash_set_fingerprint",
        "forbidden_observation_hash_set_fingerprint",
        "authoring_observation_hash_set_fingerprint",
        "message_occurrence_evidence_hash_set_fingerprint",
        "message_evidence_hash_set_fingerprint",
        "thread_evidence_hash_set_fingerprint",
        "thread_occurrence_evidence_hash_sequence_fingerprint",
        "native_observation_evidence_hash_set_fingerprint",
        "projection_policy_fingerprint",
    }
    for case in cases:
        if not isinstance(case, Mapping):
            raise IndependentMailHoldoutUatError("holdout_case_invalid")
        required_keys = {
            "case_id",
            "domain",
            "intent_kind",
            "pattern",
            "result_kind",
            "query_text",
            "requester_user_id",
            "required_source_observation_ids",
            "forbidden_source_observation_ids",
            "required_match_count",
            "limit",
            "private_fingerprint",
            "source_evidence_binding",
        }
        if not required_keys.issubset(case):
            raise IndependentMailHoldoutUatError("holdout_case_shape_invalid")
        case_id = _require_sha256(
            case.get("case_id"),
            "holdout_case_sealed_identity_invalid",
        )
        _require_sha256(
            case.get("query_text"),
            "holdout_case_sealed_identity_invalid",
        )
        _require_sha256(
            case.get("requester_user_id"),
            "holdout_case_sealed_identity_invalid",
        )
        case_fingerprint = _require_sha256(
            case.get("private_fingerprint"),
            "holdout_case_fingerprint_invalid",
        )
        if case_id in case_ids or case_fingerprint in case_fingerprints:
            raise IndependentMailHoldoutUatError("holdout_case_identity_duplicate")
        case_ids.add(case_id)
        case_fingerprints.add(case_fingerprint)
        required_ids = _string_list(
            case.get("required_source_observation_ids"),
            "holdout_required_observation_ids_invalid",
        )
        forbidden_ids = _string_list(
            case.get("forbidden_source_observation_ids"),
            "holdout_forbidden_observation_ids_invalid",
        )
        authoring_ids = (
            _string_list(
                case.get("authoring_source_observation_ids"),
                "holdout_authoring_observation_ids_invalid",
            )
            if "authoring_source_observation_ids" in case
            else required_ids
        )
        for observation_hash in required_ids + forbidden_ids + authoring_ids:
            _require_sha256(
                observation_hash,
                "holdout_case_sealed_observation_reference_invalid",
            )
        holdout_observation_hashes.update(authoring_ids)
        evidence_binding = case.get("source_evidence_binding")
        if (
            not isinstance(evidence_binding, Mapping)
            or set(evidence_binding) != expected_evidence_binding_keys
            or evidence_binding.get("projection_policy_fingerprint")
            != source_author_projection.SOURCE_AUTHOR_POLICY_FINGERPRINT
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_case_source_evidence_hash_binding_invalid"
            )
        for field_name, value in evidence_binding.items():
            _require_sha256(
                value,
                "holdout_case_source_evidence_hash_binding_invalid",
            )
        stratum = _case_stratum(case)
        _validate_case_shape(
            stratum=stratum,
            result_kind=str(case.get("result_kind")),
            required_ids=required_ids,
            forbidden_ids=forbidden_ids,
            authoring_ids=authoring_ids,
        )
        strata[stratum] += 1
        if stratum == "permission_denied":
            permission_cases.append(case)
    normalized_strata = dict(sorted(strata.items()))
    if (
        normalized_strata != EXPECTED_STRATA_COUNTS
        or projection.get("case_strata_counts") != EXPECTED_STRATA_COUNTS
    ):
        raise IndependentMailHoldoutUatError("holdout_strata_coverage_mismatch")

    disjointness = projection.get("disjointness")
    overlap_counts = {
        "development_holdout_observation_overlap_count": 0,
        "development_holdout_message_overlap_count": 0,
        "development_holdout_thread_overlap_count": 0,
    }
    if (
        not isinstance(disjointness, Mapping)
        or set(disjointness) != source_author_projection._DISJOINTNESS_FIELDS
    ):
        raise IndependentMailHoldoutUatError("holdout_disjointness_binding_mismatch")
    if (
        disjointness.get("status") != "passed"
        or any(disjointness.get(key) != value for key, value in overlap_counts.items())
        or disjointness.get("holdout_authoring_observation_count")
        != len(holdout_observation_hashes)
        or not isinstance(disjointness.get("holdout_authoring_message_count"), int)
        or not isinstance(disjointness.get("holdout_authoring_thread_count"), int)
        or disjointness["holdout_authoring_message_count"] <= 0
        or disjointness["holdout_authoring_thread_count"] <= 0
    ):
        raise IndependentMailHoldoutUatError("holdout_disjointness_binding_mismatch")
    for field_name in (
        "holdout_observation_set_fingerprint",
        "holdout_message_set_fingerprint",
        "holdout_thread_set_fingerprint",
    ):
        _require_sha256(
            disjointness.get(field_name),
            "holdout_disjointness_binding_mismatch",
        )

    _validate_holdout_safe_report(
        safe_report,
        safe_report_sha256=safe_report_sha256,
        manifest_binding=manifest_binding,
        manifest_sha256=manifest_sha256,
        strata_counts=normalized_strata,
        overlap_counts=overlap_counts,
        readable_observation_count=len(holdout_observation_hashes),
        disjointness=disjointness,
    )
    return {
        "case_count": len(cases),
        "strata_counts": normalized_strata,
        "readable_observation_count": 0,
        "observation_type_counts": {
            "email_header": 0,
            "email_body_segment": 0,
        },
        "projected_observation_count": len(holdout_observation_hashes),
        "projection_type_counts": {
            "email_header": 0,
            "email_body_segment": 0,
        },
        "projection_fingerprint": sha256_json(sorted(holdout_observation_hashes)),
        "permission_denied_case_count": len(permission_cases),
        "manifest_fingerprint": manifest_binding["manifest_fingerprint"],
        "private_manifest_id": manifest_binding["private_manifest_id"],
        "partition_fingerprint": manifest_binding["partition_fingerprint"],
    }


def _validate_holdout_safe_report(
    report: Mapping[str, Any],
    *,
    safe_report_sha256: str,
    manifest_binding: Mapping[str, Any],
    manifest_sha256: str,
    strata_counts: Mapping[str, int],
    overlap_counts: Mapping[str, int],
    readable_observation_count: int,
    disjointness: Mapping[str, Any],
) -> None:
    if (
        report.get("artifact_id") != HOLDOUT_REPORT_ARTIFACT_ID
        or report.get("schema_version") != 2
        or report.get("status") != "passed"
        or report.get("execution_status") != "not_run"
        or report.get("quality_result_status") != "not_read"
        or report.get("seal_before_execution_status") != "passed"
        or report.get("source_lineage_status") != "passed"
        or report.get("disjointness_status") != "passed"
        or report.get("strata_coverage_status") != "passed"
        or report.get("blocker_ids") != []
        or report.get("strata_counts") != strata_counts
        or report.get("report_fingerprint") != _payload_fingerprint(report, "report_fingerprint")
    ):
        raise IndependentMailHoldoutUatError("holdout_safe_report_invalid")
    counts = report.get("counts")
    hashes = report.get("hashes")
    if not isinstance(counts, Mapping) or not isinstance(hashes, Mapping):
        raise IndependentMailHoldoutUatError("holdout_safe_report_shape_invalid")
    if (
        counts.get("case_count") != EXPECTED_CASE_COUNT
        or counts.get("holdout_authoring_observation_count") != readable_observation_count
        or any(counts.get(key) != value for key, value in overlap_counts.items())
        or counts.get("source_unexplained_loss_count") != 0
        or counts.get("blocker_count") != 0
        or hashes.get("manifest_sha256") != manifest_sha256
        or hashes.get("manifest_fingerprint") != manifest_binding["manifest_fingerprint"]
        or any(
            hashes.get(field_name) != disjointness.get(field_name)
            for field_name in (
                "holdout_observation_set_fingerprint",
                "holdout_message_set_fingerprint",
                "holdout_thread_set_fingerprint",
            )
        )
    ):
        raise IndependentMailHoldoutUatError("holdout_safe_report_binding_mismatch")
    _require_sha256(safe_report_sha256, "holdout_safe_report_seal_invalid")
    try:
        assert_no_public_raw_references(report, HOLDOUT_REPORT_ARTIFACT_ID)
    except ContractValidationError as exc:
        raise IndependentMailHoldoutUatError("holdout_safe_report_private_leak") from exc


def _validated_referenced_observation_lineage(
    *,
    observation_ids: set[str],
    bundle: MailEvidenceBundle,
    retrieval_snapshot: Mapping[str, Any],
) -> tuple[dict[str, Observation], dict[str, str]]:
    """Validate referenced header/body Observations by their native locator."""

    parsed_rows = retrieval_snapshot.get("parsed_mail_observations")
    if not isinstance(parsed_rows, list):
        raise IndependentMailHoldoutUatError("retrieval_observation_snapshot_invalid")
    readable: dict[str, Observation] = {}
    for row in parsed_rows:
        if not isinstance(row, dict):
            raise IndependentMailHoldoutUatError("retrieval_observation_invalid")
        observation_id = row.get("observation_id")
        if observation_id not in observation_ids:
            continue
        observation = Observation.from_dict(row)
        if observation.to_dict() != row or observation.observation_id in readable:
            raise IndependentMailHoldoutUatError("holdout_observation_round_trip_failed")
        readable[observation.observation_id] = observation
    if set(readable) != observation_ids:
        raise IndependentMailHoldoutUatError("holdout_observation_unreadable")

    source_inventory = SourceInventory.from_dict(retrieval_snapshot["source_inventory"])
    inventory_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
    occurrence_by_id = {
        occurrence.message_occurrence_id: occurrence for occurrence in bundle.message_occurrences
    }
    if len(occurrence_by_id) != len(bundle.message_occurrences):
        raise IndependentMailHoldoutUatError("holdout_message_occurrence_identity_duplicate")
    message_by_id = {message.email_message_id: message for message in bundle.messages}
    if len(message_by_id) != len(bundle.messages):
        raise IndependentMailHoldoutUatError("holdout_message_identity_duplicate")
    body_by_observation_id = {
        segment.source_observation_id: segment for segment in bundle.body_segments
    }
    if len(body_by_observation_id) != len(bundle.body_segments):
        raise IndependentMailHoldoutUatError("holdout_body_observation_identity_duplicate")

    permission_fingerprint = str(retrieval_snapshot["permission_fingerprint"])
    provenance_fingerprint = str(retrieval_snapshot["source_provenance_fingerprint"])
    observation_occurrence_ids: dict[str, str] = {}
    mirrored_location_fields = (
        "archive_id",
        "mailbox_id",
        "source_inventory_id",
        "source_inventory_item_id",
        "parent_inventory_item_id",
        "source_local_key",
        "parent_source_local_key",
        "source_content_hash",
        "folder_path_hash",
        "message_id",
        "message_occurrence_id",
        "thread_id",
        "pst_folder_node_id",
        "pst_message_node_id",
        "pst_message_data_node_id",
        "source_provenance_fingerprint",
    )
    native_inventory_fields = (
        "source_local_key",
        "parent_source_local_key",
        "pst_folder_node_id",
        "pst_message_node_id",
        "pst_message_data_node_id",
    )
    for observation_id, observation in readable.items():
        if (
            observation.observation_type not in {"email_header", "email_body_segment"}
            or observation.modality != "mail"
            or observation.asset_id != source_inventory.source_asset_id
            or sha256_json(observation.permission_scope) != permission_fingerprint
        ):
            raise IndependentMailHoldoutUatError("holdout_observation_source_boundary_mismatch")
        location = observation.location
        payload = observation.payload
        if not isinstance(payload, dict):
            raise IndependentMailHoldoutUatError("holdout_observation_payload_missing")
        if (
            location.get("source_inventory_id") != source_inventory.source_inventory_id
            or location.get("source_provenance_fingerprint") != provenance_fingerprint
            or payload.get("evidence_state") != "source_observation"
            or payload.get("canonical_fact_status") != "not_asserted"
            or any(
                payload.get(field_name) != location.get(field_name)
                for field_name in mirrored_location_fields
            )
        ):
            raise IndependentMailHoldoutUatError("holdout_observation_source_native_locator_drift")

        inventory_item_id = location.get("source_inventory_item_id")
        parent_inventory_item_id = location.get("parent_inventory_item_id")
        source_local_key = location.get("source_local_key")
        parent_source_local_key = location.get("parent_source_local_key")
        source_content_hash = location.get("source_content_hash")
        message_occurrence_id = location.get("message_occurrence_id")
        if not all(
            isinstance(value, str) and value
            for value in (
                inventory_item_id,
                parent_inventory_item_id,
                source_local_key,
                parent_source_local_key,
                message_occurrence_id,
            )
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_observation_source_native_locator_missing"
            )
        _require_sha256(
            source_content_hash,
            "holdout_observation_source_content_hash_invalid",
        )
        inventory_item = inventory_by_id.get(str(inventory_item_id))
        parent_inventory_item = inventory_by_id.get(str(parent_inventory_item_id))
        if (
            inventory_item is None
            or inventory_item.structure_kind != "email_message_occurrence"
            or str(inventory_item.processing_state) != "parsed"
            or inventory_item.permission_fingerprint != permission_fingerprint
            or inventory_item.source_asset_id != source_inventory.source_asset_id
            or inventory_item.location.get("message_content_hash") != source_content_hash
            or any(
                inventory_item.location.get(field_name) != location.get(field_name)
                for field_name in native_inventory_fields
            )
            or parent_inventory_item is None
            or parent_inventory_item.structure_kind != "mail_folder_descriptor_occurrence"
            or parent_inventory_item.location.get("source_local_key") != parent_source_local_key
            or parent_inventory_item.location.get("pst_folder_node_id")
            != location.get("pst_folder_node_id")
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_observation_source_inventory_lineage_mismatch"
            )

        occurrence = occurrence_by_id.get(str(message_occurrence_id))
        if occurrence is None:
            raise IndependentMailHoldoutUatError("holdout_observation_message_occurrence_missing")
        message = message_by_id.get(occurrence.email_message_id)
        if (
            message is None
            or occurrence.message_id != location.get("message_id")
            or occurrence.archive_id != location.get("archive_id")
            or occurrence.mailbox_id != location.get("mailbox_id")
            or occurrence.folder_path_hash != location.get("folder_path_hash")
            or occurrence.thread_id != location.get("thread_id")
            or message.message_id != occurrence.message_id
            or message.thread_id != occurrence.thread_id
        ):
            raise IndependentMailHoldoutUatError("holdout_observation_message_lineage_mismatch")

        if observation.observation_type == "email_body_segment":
            _validate_body_observation_binding(
                observation=observation,
                body_by_observation_id=body_by_observation_id,
                email_message_id=occurrence.email_message_id,
            )
        else:
            _validate_header_observation_binding(
                observation=observation,
                body_by_observation_id=body_by_observation_id,
            )
        observation_occurrence_ids[observation_id] = str(message_occurrence_id)
    return readable, observation_occurrence_ids


def _preflight_execution_cases(
    *,
    holdout_policy: _HoldoutPolicy,
    projection: Mapping[str, Any],
    bundle: MailEvidenceBundle,
) -> tuple[Mapping[str, Any], ...]:
    if holdout_policy.policy_id == BASE_HOLDOUT_POLICY_ID:
        del projection
        return ({"requester_user_id": bundle.mail_import_session.owner_user_id},)
    if holdout_policy.policy_id != EXTENSION_HOLDOUT_POLICY_ID:
        raise IndependentMailHoldoutUatError("holdout_policy_id_invalid")
    owner_user_id = bundle.mail_import_session.owner_user_id
    workspace_id = bundle.mail_import_session.workspace_id
    denied_requester_id = _extension_denied_requester_id(
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
    )
    return (
        {"requester_user_id": owner_user_id},
        {"requester_user_id": denied_requester_id},
    )


def _source_author_execution_context_after_claim(
    *,
    manifest: Mapping[str, Any],
    projection: Mapping[str, Any],
    preflight_context: _HoldoutExecutionContext,
    bundle: MailEvidenceBundle,
    runtime_binding: Mapping[str, Any],
) -> tuple[_HoldoutExecutionContext, dict[str, Any]]:
    """Build and bind raw requester contexts only after the claim is durable."""

    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        raise IndependentMailHoldoutUatError("holdout_case_count_mismatch")
    if not _is_source_author_hashed_base_projection(projection):
        raise IndependentMailHoldoutUatError("holdout_post_claim_projection_contract_invalid")
    if (
        not isinstance(preflight_context.source_binding_fingerprint, str)
        or not isinstance(
            preflight_context.identifier_mention_batch,
            SourceBoundIdentifierMentionBatch,
        )
        or not isinstance(preflight_context.source_identifier_binding, Mapping)
    ):
        raise IndependentMailHoldoutUatError("holdout_post_claim_source_context_missing")
    rebuilt = _build_holdout_execution_context(
        bundle=bundle,
        observations_by_id=preflight_context.observations_by_id,
        observation_hash_by_id=preflight_context.observation_hash_by_id,
        source_binding_fingerprint=preflight_context.source_binding_fingerprint,
        cases=cases,
        identifier_mention_batch=preflight_context.identifier_mention_batch,
        source_identifier_binding=preflight_context.source_identifier_binding,
        development_observation_ids=preflight_context.development_observation_ids,
    )
    binding = _validate_source_author_execution_context_after_claim(
        cases=cases,
        context=rebuilt,
        bundle=bundle,
        runtime_binding=runtime_binding,
    )
    return rebuilt, binding


def _validate_source_author_execution_context_after_claim(
    *,
    cases: Sequence[Mapping[str, Any]],
    context: _HoldoutExecutionContext,
    bundle: MailEvidenceBundle,
    runtime_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove raw requester permission contexts without publishing identities."""

    role_by_requester: dict[str, str] = {}
    for case in cases:
        requester_user_id = case.get("requester_user_id")
        if not isinstance(requester_user_id, str) or not requester_user_id:
            raise IndependentMailHoldoutUatError("holdout_private_manifest_raw_identity_missing")
        role = "denied" if _case_stratum(case) == "permission_denied" else "authorized"
        existing_role = role_by_requester.setdefault(requester_user_id, role)
        if existing_role != role:
            raise IndependentMailHoldoutUatError("holdout_post_claim_requester_role_conflict")
    requester_ids = set(role_by_requester)
    if not requester_ids or any(
        set(mapping) != requester_ids
        for mapping in (
            context.sessions,
            context.effective_graph_views,
            context.lineage_crosswalks,
            context.graph_builds,
        )
    ):
        raise IndependentMailHoldoutUatError("holdout_post_claim_requester_context_mismatch")
    if not isinstance(context.identifier_mention_batch, SourceBoundIdentifierMentionBatch):
        raise IndependentMailHoldoutUatError("holdout_post_claim_source_context_missing")
    if not isinstance(context.source_identifier_binding, Mapping):
        raise IndependentMailHoldoutUatError("holdout_post_claim_source_context_missing")

    owner_user_id = bundle.mail_import_session.owner_user_id
    workspace_id = bundle.mail_import_session.workspace_id
    owner_graph_builds: dict[str, Any] = {}
    owner_batches: dict[str, SourceBoundIdentifierMentionBatch] = {}
    context_rows: list[dict[str, str]] = []
    index_fingerprints: set[str] = set()
    authorized_requester_count = 0
    denied_requester_count = 0
    for requester_user_id in sorted(requester_ids, key=sha256_json):
        role = role_by_requester[requester_user_id]
        session = context.sessions[requester_user_id]
        view = context.effective_graph_views[requester_user_id]
        graph_build = context.graph_builds[requester_user_id]
        requester_batch = _project_source_identifier_batch_for_session(
            complete_batch=context.identifier_mention_batch,
            session=session,
            observations_by_bundle_id=context.observations_by_bundle_id,
        )
        authorized = authorize_mail_evidence_bundles(
            (bundle,),
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
        )
        if (
            session.requester_user_id != requester_user_id
            or session.workspace_id != workspace_id
            or graph_build.effective_graph_view != view
            or view.requester_user_id != requester_user_id
        ):
            raise IndependentMailHoldoutUatError("holdout_post_claim_requester_context_mismatch")
        index_fingerprint = _require_sha256(
            session.index.index_fingerprint,
            "holdout_post_claim_requester_context_mismatch",
        )
        index_fingerprints.add(index_fingerprint)
        if role == "authorized":
            authorized_requester_count += 1
            if (
                requester_user_id != owner_user_id
                or authorized != (bundle,)
                or session.authorized_source_scope_ids != (bundle.mail_evidence_bundle_id,)
                or session.index.authorized_bundle_count != 1
                or session.index.denied_bundle_count != 0
                or index_fingerprint != runtime_binding.get("index_fingerprint")
            ):
                raise IndependentMailHoldoutUatError(
                    "holdout_post_claim_permission_context_mismatch"
                )
            owner_graph_builds[requester_user_id] = graph_build
            owner_batches[requester_user_id] = requester_batch
        else:
            denied_requester_count += 1
            if (
                requester_user_id == owner_user_id
                or authorized
                or session.authorized_source_scope_ids
                or session.index.authorized_bundle_count != 0
                or session.index.denied_bundle_count != 1
                or requester_batch.occurrence_count != 0
                or graph_build.source_observation_count != 0
                or graph_build.observation_node_count != 0
                or graph_build.entity_node_count != 0
                or graph_build.edge_count != 0
                or view.visible_nodes
                or view.visible_edges
            ):
                raise IndependentMailHoldoutUatError(
                    "holdout_post_claim_permission_context_mismatch"
                )
        context_rows.append(
            {
                "requester_fingerprint": sha256_json(requester_user_id),
                "permission_role_fingerprint": sha256_json(role),
                "index_fingerprint": index_fingerprint,
                "graph_build_fingerprint": _require_sha256(
                    graph_build.build_fingerprint,
                    "holdout_post_claim_requester_context_mismatch",
                ),
                "graph_revision_fingerprint": _require_sha256(
                    graph_build.graph_revision_fingerprint,
                    "holdout_post_claim_requester_context_mismatch",
                ),
                "projected_mention_batch_fingerprint": requester_batch.batch_fingerprint,
            }
        )
    if authorized_requester_count != 1 or denied_requester_count < 1:
        raise IndependentMailHoldoutUatError("holdout_post_claim_permission_context_mismatch")

    owner_binding = _graph_ontology_binding(
        owner_graph_builds,
        source_identifier_binding=context.source_identifier_binding,
        requester_batches=owner_batches,
    )
    runtime_field_by_owner_binding_field = {
        "graph_artifact_fingerprint": "graph_artifact_fingerprint",
        "graph_revision_fingerprint": "graph_revision_fingerprint",
        "graph_revision_id_fingerprint": "graph_revision_id_fingerprint",
        "ontology_artifact_fingerprint": "ontology_artifact_fingerprint",
        "ontology_revision_fingerprint": "ontology_revision_fingerprint",
        "graph_ontology_binding_fingerprint": "graph_ontology_binding_fingerprint",
        "complete_identifier_mention_fingerprint_set_hash": (
            "source_identifier_complete_mention_fingerprint_set_hash"
        ),
        "authorized_identifier_mention_fingerprint_set_hash": (
            "source_identifier_authorized_mention_fingerprint_set_hash"
        ),
        "identifier_resolution_fingerprint_set_hash": (
            "source_identifier_resolution_fingerprint_set_hash"
        ),
        "requester_projected_mention_batch_fingerprint_set_hash": (
            "source_identifier_requester_projection_fingerprint_set_hash"
        ),
    }
    if any(
        owner_binding.get(owner_field) != runtime_binding.get(runtime_field)
        for owner_field, runtime_field in runtime_field_by_owner_binding_field.items()
    ):
        raise IndependentMailHoldoutUatError("holdout_post_claim_owner_runtime_binding_mismatch")
    return {
        "requester_context_count": len(context_rows),
        "authorized_requester_context_count": authorized_requester_count,
        "denied_requester_context_count": denied_requester_count,
        "requester_context_set_fingerprint": sha256_json(context_rows),
        "permission_scoped_index_fingerprint_set_hash": sha256_json(sorted(index_fingerprints)),
        "graph_ontology_binding_fingerprint": context.graph_ontology_binding[
            "graph_ontology_binding_fingerprint"
        ],
    }


def _extension_denied_requester_id(*, owner_user_id: str, workspace_id: str) -> str:
    suffix = sha256_json(
        {
            "policy_id": HOLDOUT_EXTENSION_SELECTION_POLICY_ID,
            "owner_user_id_hash": sha256_json(owner_user_id),
            "workspace_id_hash": sha256_json(workspace_id),
        }
    ).removeprefix("sha256:")[:24]
    requester = f"unauthorized-holdout-{suffix}"
    if requester == owner_user_id:
        raise IndependentMailHoldoutUatError("holdout_extension_denied_requester_collision")
    return requester


def _validate_body_observation_binding(
    *,
    observation: Observation,
    body_by_observation_id: Mapping[str, Any],
    email_message_id: str,
) -> None:
    segment = body_by_observation_id.get(observation.observation_id)
    segment_index = observation.location.get("body_segment_index")
    if (
        segment is None
        or not isinstance(segment_index, int)
        or isinstance(segment_index, bool)
        or segment_index < 1
        or observation.text != segment.text
        or segment.body_segment_index != segment_index
        or segment.message_occurrence_id != observation.location.get("message_occurrence_id")
        or segment.email_message_id != email_message_id
        or segment.body_segment_hash
        != sha256_json(
            {
                "email_message_id": email_message_id,
                "body_segment_index": segment_index,
                "text": observation.text,
            }
        )
        or (observation.payload or {}).get("body_segment_index") != segment_index
    ):
        raise IndependentMailHoldoutUatError("holdout_body_observation_bundle_binding_mismatch")


def _validate_header_observation_binding(
    *,
    observation: Observation,
    body_by_observation_id: Mapping[str, Any],
) -> None:
    payload = observation.payload or {}
    header_name = observation.location.get("header_name")
    header_index = observation.location.get("header_index")
    header_value = payload.get("header_value")
    if (
        observation.observation_id in body_by_observation_id
        or not isinstance(header_name, str)
        or not header_name
        or not isinstance(header_value, str)
        or not isinstance(header_index, int)
        or isinstance(header_index, bool)
        or header_index < 1
        or payload.get("header_name") != header_name
        or observation.text != f"{header_name}: {header_value}"
    ):
        raise IndependentMailHoldoutUatError("holdout_header_observation_native_binding_mismatch")


def project_validated_holdout_observations(
    *,
    observations_by_id: Mapping[str, Observation],
    observation_ids: set[str] | frozenset[str],
    bundle: MailEvidenceBundle,
) -> dict[str, Any]:
    """Project sealed header/body records without changing their source text.

    This is a private execution projection.  The caller may publish only its
    counts and fingerprint, never the returned records.
    """

    if not observation_ids or not observation_ids <= set(observations_by_id):
        raise IndependentMailHoldoutUatError("holdout_projection_observation_set_invalid")
    body_by_observation_id = {
        segment.source_observation_id: segment for segment in bundle.body_segments
    }
    occurrence_by_id = {
        occurrence.message_occurrence_id: occurrence for occurrence in bundle.message_occurrences
    }
    message_by_id = {message.email_message_id: message for message in bundle.messages}
    records: list[dict[str, Any]] = []
    type_counts = Counter()
    for observation_id in sorted(observation_ids):
        observation = observations_by_id[observation_id]
        owner_record = observation.to_dict()
        if Observation.from_dict(owner_record).to_dict() != owner_record:
            raise IndependentMailHoldoutUatError("holdout_projection_store_round_trip_failed")
        if (
            observation.observation_type not in {"email_header", "email_body_segment"}
            or not isinstance(observation.text, str)
            or not observation.text
        ):
            raise IndependentMailHoldoutUatError("holdout_projection_owner_record_invalid")
        location = observation.location
        occurrence_id = location.get("message_occurrence_id")
        occurrence = occurrence_by_id.get(str(occurrence_id))
        message = message_by_id.get(occurrence.email_message_id) if occurrence is not None else None
        if occurrence is None or message is None or message.thread_id != location.get("thread_id"):
            raise IndependentMailHoldoutUatError("holdout_projection_message_lineage_mismatch")
        observation_hash = sha256_json(owner_record)
        record: dict[str, Any] = {
            "projection_kind": (
                "sealed_email_header_observation"
                if observation.observation_type == "email_header"
                else "preserved_email_body_segment"
            ),
            "observation_id": observation.observation_id,
            "observation_hash": observation_hash,
            "observation_type": observation.observation_type,
            "raw_safe_text": observation.text,
            "normalized_text": observation.text,
            "text_fingerprint": sha256_json(observation.text),
            "store_record_fingerprint": observation_hash,
            "source_native_locator": dict(location),
            "source_native_locator_fingerprint": sha256_json(location),
            "permission_scope": owner_record["permission_scope"],
            "permission_fingerprint": sha256_json(owner_record["permission_scope"]),
            "source_provenance_fingerprint": location.get("source_provenance_fingerprint"),
            "source_inventory_id": location.get("source_inventory_id"),
            "source_inventory_item_id": location.get("source_inventory_item_id"),
            "source_local_key": location.get("source_local_key"),
            "message_occurrence_id": occurrence.message_occurrence_id,
            "email_message_id": occurrence.email_message_id,
            "thread_id": message.thread_id,
        }
        if observation.observation_type == "email_header":
            _validate_header_observation_binding(
                observation=observation,
                body_by_observation_id=body_by_observation_id,
            )
            payload = observation.payload or {}
            record["header_name"] = payload["header_name"]
            record["header_value"] = payload["header_value"]
            record["header_index"] = location["header_index"]
        else:
            _validate_body_observation_binding(
                observation=observation,
                body_by_observation_id=body_by_observation_id,
                email_message_id=occurrence.email_message_id,
            )
            segment = body_by_observation_id[observation.observation_id]
            record["email_body_segment_id"] = segment.email_body_segment_id
            record["body_segment_index"] = segment.body_segment_index
            record["body_segment_hash"] = segment.body_segment_hash
        if (
            record["raw_safe_text"] != owner_record["text"]
            or record["normalized_text"] != owner_record["text"]
            or record["store_record_fingerprint"] != sha256_json(owner_record)
        ):
            raise IndependentMailHoldoutUatError("holdout_projection_text_or_hash_drift")
        records.append(record)
        type_counts[observation.observation_type] += 1
    return {
        "records": tuple(records),
        "observation_type_counts": {
            observation_type: type_counts[observation_type]
            for observation_type in ("email_header", "email_body_segment")
        },
        "projection_fingerprint": sha256_json(records),
    }


def _case_stratum(case: Mapping[str, Any]) -> str:
    stratum = case.get("stratum_id")
    if isinstance(stratum, str) and stratum:
        return stratum
    if case.get("result_kind") == "owner_match" and case.get("intent_kind") == "relation_reasoning":
        return "graph_required"
    raise IndependentMailHoldoutUatError("holdout_case_stratum_missing")


def _validate_case_shape(
    *,
    stratum: str,
    result_kind: str,
    required_ids: tuple[str, ...],
    forbidden_ids: tuple[str, ...],
    authoring_ids: tuple[str, ...],
) -> None:
    if result_kind not in HOLDOUT_RESULT_KINDS:
        raise IndependentMailHoldoutUatError("holdout_result_kind_invalid")
    valid = {
        "graph_required": (
            result_kind == "owner_match"
            and len(required_ids) == 2
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "single_document_direct_lookup": (
            result_kind == "source_evidence"
            and len(required_ids) == 1
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "exact_set": (
            result_kind == "exact_set"
            and bool(required_ids)
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "exact_count": (
            result_kind == "exact_count"
            and bool(required_ids)
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "exact_aggregation": (
            result_kind == "exact_aggregation"
            and bool(required_ids)
            and not forbidden_ids
            and authoring_ids == required_ids
        ),
        "no_answer_near_miss_negative": (
            result_kind == "no_answer"
            and not required_ids
            and len(forbidden_ids) == 1
            and authoring_ids == forbidden_ids
        ),
        "permission_denied": (
            result_kind == "permission_denied"
            and not required_ids
            and len(forbidden_ids) == 1
            and authoring_ids == forbidden_ids
        ),
    }.get(stratum)
    if valid is not True:
        raise IndependentMailHoldoutUatError("holdout_case_stratum_shape_invalid")


def _message_thread_sets(
    observation_ids: set[str] | frozenset[str],
    *,
    observation_occurrence_ids: Mapping[str, str],
    occurrence_to_message: Mapping[str, str],
    message_to_thread: Mapping[str, str | None],
) -> tuple[set[str], set[str]]:
    message_ids: set[str] = set()
    thread_ids: set[str] = set()
    for observation_id in observation_ids:
        message_occurrence_id = observation_occurrence_ids.get(observation_id)
        message_id = occurrence_to_message.get(str(message_occurrence_id))
        thread_id = message_to_thread.get(str(message_id))
        if not message_occurrence_id or not message_id or not thread_id:
            raise IndependentMailHoldoutUatError("holdout_message_thread_lineage_missing")
        message_ids.add(message_id)
        thread_ids.add(thread_id)
    return message_ids, thread_ids


def _build_runtime_binding(
    *,
    source_binding_fingerprint: str,
    index_fingerprint: str,
    tokenizer_profile_fingerprint: str,
    execution_contract: Mapping[str, Any],
    development_acceptance: _DevelopmentAcceptance,
    graph_ontology_binding: Mapping[str, Any],
    source_identifier_binding: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = current_runtime_binding_fingerprints()
    if runtime["lexical_profile_fingerprint"] != tokenizer_profile_fingerprint:
        raise IndependentMailHoldoutUatError("target_tokenizer_profile_mismatch")
    _require_sha256(index_fingerprint, "index_fingerprint_invalid")
    development = development_acceptance.component_binding
    expected_development_matches = {
        "index_fingerprint": index_fingerprint,
        "lexical_profile_fingerprint": runtime["lexical_profile_fingerprint"],
        "query_lexical_profile_fingerprint": runtime["lexical_profile_fingerprint"],
        "evidence_lexical_profile_fingerprint": runtime["lexical_profile_fingerprint"],
        "candidate_admission_profile_fingerprint": runtime["lexical_profile_fingerprint"],
        "dense_profile_fingerprint": runtime["dense_profile_fingerprint"],
        "execution_component_fingerprint": runtime["runtime_component_fingerprint"],
        "runtime_method_fingerprint": runtime["runtime_method_fingerprint"],
        "graph_adapter_fingerprint": runtime["graph_adapter_fingerprint"],
        "ontology_target_fingerprint": runtime["ontology_target_fingerprint"],
        "answer_model_fingerprint": runtime["answer_model_fingerprint"],
        "answer_prompt_fingerprint": runtime["answer_prompt_fingerprint"],
        "answer_budget_fingerprint": runtime["answer_budget_fingerprint"],
        "evaluator_fingerprint": runtime["evaluator_fingerprint"],
        "image_id": FROZEN_CANONICAL_IMAGE_ID,
        "image_metadata_fingerprint": (FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
    }
    if any(
        development.get(field_name) != expected_value
        for field_name, expected_value in expected_development_matches.items()
    ):
        raise IndependentMailHoldoutUatError("development_runtime_component_binding_mismatch")
    for field_name in (
        "graph_artifact_fingerprint",
        "graph_revision_fingerprint",
        "graph_revision_id_fingerprint",
        "ontology_artifact_fingerprint",
        "ontology_revision_fingerprint",
        "graph_ontology_binding_fingerprint",
    ):
        _require_sha256(
            graph_ontology_binding.get(field_name),
            "holdout_graph_ontology_binding_invalid",
        )
    required_source_identifier_fingerprints = (
        "source_artifact_byte_hash",
        "source_artifact_fingerprint",
        "binding_fingerprint",
        "candidate_artifact_schema_fingerprint",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_observation_hash_set_fingerprint",
        "retrieval_snapshot_fingerprint",
        "retrieval_report_fingerprint",
        "retrieval_snapshot_byte_sha256",
        "retrieval_report_byte_sha256",
        "candidate_admission_profile_fingerprint",
        "extraction_policy_fingerprint",
        "resolution_policy_fingerprint",
        "identity_scope_mode_fingerprint",
        "identity_scope_fingerprint",
        "identity_scope_binding_fingerprint",
        "identity_scope_graph_binding_fingerprint",
        "identity_scope_attestation_byte_sha256",
        "identity_scope_attestation_fingerprint",
        "identity_scope_policy_fingerprint",
        "operator_approval_fingerprint",
        "mode_approval_fingerprint",
        "workspace_scope_fingerprint",
        "attested_asset_fingerprint",
        "complete_mention_batch_fingerprint",
        "complete_resolution_fingerprint",
        "selected_mention_batch_fingerprint",
        "selected_resolution_fingerprint",
        "source_graph_policy_fingerprint",
        "source_identifier_adapter_fingerprint",
        "holdout_adapter_fingerprint",
    )
    for field_name in required_source_identifier_fingerprints:
        _require_sha256(
            source_identifier_binding.get(field_name),
            "holdout_source_identifier_binding_invalid",
        )
    identity_scope_mode = source_identifier_binding.get("identity_scope_mode_status")
    expected_spec_approval_status = (
        "passed_bound"
        if identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
        else "not_required_for_mode"
    )
    if identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        _require_sha256(
            source_identifier_binding.get("spec_approval_fingerprint"),
            "holdout_source_identifier_binding_invalid",
        )
    elif identity_scope_mode != TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        raise IndependentMailHoldoutUatError("holdout_source_identifier_v3_binding_invalid")
    if (
        source_identifier_binding.get("status") != "sealed_passed"
        or source_identifier_binding.get("candidate_artifact_schema_version")
        != CANDIDATE_ARTIFACT_SCHEMA_VERSION
        or source_identifier_binding.get("candidate_artifact_schema_fingerprint")
        != sha256_json(CANDIDATE_ARTIFACT_SCHEMA_VERSION)
        or source_identifier_binding.get("identity_scope_mode") != identity_scope_mode
        or source_identifier_binding.get("identity_scope_mode_fingerprint")
        != sha256_json(identity_scope_mode)
        or source_identifier_binding.get("spec_approval_status") != expected_spec_approval_status
        or source_identifier_binding.get("overflow_count") != 0
        or source_identifier_binding.get("candidate_graph_only") is not True
        or source_identifier_binding.get("canonical_write_allowed") is not False
        or source_identifier_binding.get("candidate_admission_profile_fingerprint")
        != tokenizer_profile_fingerprint
        or source_identifier_binding.get("source_graph_policy_fingerprint")
        != sha256_json(development_uat.SOURCE_GRAPH_POLICY_ID)
        or source_identifier_binding.get("source_identifier_adapter_fingerprint")
        != sha256_json(development_uat.SOURCE_IDENTIFIER_ADAPTER_ID)
        or source_identifier_binding.get("holdout_adapter_fingerprint")
        != SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_FINGERPRINT
        or graph_ontology_binding.get("source_identifier_candidate_binding_fingerprint")
        != source_identifier_binding.get("binding_fingerprint")
        or graph_ontology_binding.get("candidate_artifact_schema_fingerprint")
        != source_identifier_binding.get("candidate_artifact_schema_fingerprint")
        or graph_ontology_binding.get("identity_scope_mode_status") != identity_scope_mode
        or graph_ontology_binding.get("identity_scope_mode_fingerprint")
        != source_identifier_binding.get("identity_scope_mode_fingerprint")
        or graph_ontology_binding.get("identity_scope_fingerprint")
        != source_identifier_binding.get("identity_scope_fingerprint")
        or graph_ontology_binding.get("identity_scope_binding_fingerprint")
        != source_identifier_binding.get("identity_scope_binding_fingerprint")
        or graph_ontology_binding.get("identity_scope_attestation_byte_sha256")
        != source_identifier_binding.get("identity_scope_attestation_byte_sha256")
        or graph_ontology_binding.get("identity_scope_attestation_fingerprint")
        != source_identifier_binding.get("identity_scope_attestation_fingerprint")
        or graph_ontology_binding.get("identity_scope_policy_fingerprint")
        != source_identifier_binding.get("identity_scope_policy_fingerprint")
        or graph_ontology_binding.get("operator_approval_fingerprint")
        != source_identifier_binding.get("operator_approval_fingerprint")
        or graph_ontology_binding.get("mode_approval_fingerprint")
        != source_identifier_binding.get("mode_approval_fingerprint")
        or graph_ontology_binding.get("workspace_scope_fingerprint")
        != source_identifier_binding.get("workspace_scope_fingerprint")
        or graph_ontology_binding.get("selected_identifier_mention_batch_fingerprint")
        != source_identifier_binding.get("selected_mention_batch_fingerprint")
        or graph_ontology_binding.get("selected_identifier_resolution_fingerprint")
        != source_identifier_binding.get("selected_resolution_fingerprint")
        or (
            identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            and graph_ontology_binding.get("spec_approval_fingerprint")
            != source_identifier_binding.get("spec_approval_fingerprint")
        )
        or (
            identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE
            and (
                "spec_approval_fingerprint" in graph_ontology_binding
                or "spec_approval_fingerprint" in source_identifier_binding
            )
        )
    ):
        raise IndependentMailHoldoutUatError("holdout_source_identifier_v3_binding_invalid")
    run_binding_fingerprint = sha256_json(
        {
            "source_binding_fingerprint": source_binding_fingerprint,
            "index_fingerprint": index_fingerprint,
            "runtime_component_fingerprint": runtime["runtime_component_fingerprint"],
            "runtime_method_fingerprint": runtime["runtime_method_fingerprint"],
            "development_acceptance_fingerprint": (development_acceptance.acceptance_fingerprint),
            "graph_ontology_binding_fingerprint": graph_ontology_binding[
                "graph_ontology_binding_fingerprint"
            ],
            "execution_contract_fingerprint": sha256_json(execution_contract),
            "source_identifier_candidate_binding_fingerprint": (
                source_identifier_binding["binding_fingerprint"]
            ),
            "source_identifier_candidate_artifact_sha256": (
                source_identifier_binding["source_artifact_byte_hash"]
            ),
            "source_identifier_candidate_schema_fingerprint": (
                source_identifier_binding["candidate_artifact_schema_fingerprint"]
            ),
            "source_identifier_identity_scope_mode_fingerprint": (
                source_identifier_binding["identity_scope_mode_fingerprint"]
            ),
            "source_identifier_identity_scope_fingerprint": (
                source_identifier_binding["identity_scope_fingerprint"]
            ),
            "source_identifier_identity_scope_attestation_fingerprint": (
                source_identifier_binding["identity_scope_attestation_fingerprint"]
            ),
            "source_identifier_identity_scope_policy_fingerprint": (
                source_identifier_binding["identity_scope_policy_fingerprint"]
            ),
            "source_identifier_operator_approval_fingerprint": (
                source_identifier_binding["operator_approval_fingerprint"]
            ),
            "source_identifier_mode_approval_fingerprint": (
                source_identifier_binding["mode_approval_fingerprint"]
            ),
        }
    )
    code = build_current_code_component(
        repository_root=ROOT,
        run_binding_fingerprint=run_binding_fingerprint,
    )
    image = build_image_component(
        run_binding_fingerprint=run_binding_fingerprint,
        image_id=FROZEN_CANONICAL_IMAGE_ID,
        image_metadata_fingerprint=FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    )
    authority = _validate_pre_holdout_authority(
        run_binding_fingerprint=run_binding_fingerprint,
    )
    pins = {
        "source_binding_fingerprint": source_binding_fingerprint,
        "development_acceptance_fingerprint": (development_acceptance.acceptance_fingerprint),
        "completed_development_quality_report_sha256": (
            development_acceptance.completed_report_sha256
        ),
        "operational_budget_bundle_sha256": (
            development_acceptance.operational_budget_bundle_sha256
        ),
        "tokenizer_profile_fingerprint": runtime["lexical_profile_fingerprint"],
        "index_fingerprint": index_fingerprint,
        "dense_profile_fingerprint": runtime["dense_profile_fingerprint"],
        "runtime_component_fingerprint": runtime["runtime_component_fingerprint"],
        "runtime_method_fingerprint": runtime["runtime_method_fingerprint"],
        "graph_adapter_fingerprint": runtime["graph_adapter_fingerprint"],
        "graph_artifact_fingerprint": graph_ontology_binding["graph_artifact_fingerprint"],
        "graph_revision_fingerprint": graph_ontology_binding["graph_revision_fingerprint"],
        "graph_revision_id_fingerprint": graph_ontology_binding["graph_revision_id_fingerprint"],
        "graph_ontology_binding_fingerprint": graph_ontology_binding[
            "graph_ontology_binding_fingerprint"
        ],
        "ontology_target_fingerprint": runtime["ontology_target_fingerprint"],
        "ontology_artifact_fingerprint": graph_ontology_binding["ontology_artifact_fingerprint"],
        "ontology_revision_fingerprint": graph_ontology_binding["ontology_revision_fingerprint"],
        "answer_model_fingerprint": runtime["answer_model_fingerprint"],
        "answer_prompt_fingerprint": runtime["answer_prompt_fingerprint"],
        "answer_budget_fingerprint": runtime["answer_budget_fingerprint"],
        "evaluator_fingerprint": runtime["evaluator_fingerprint"],
        "operational_budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
        "code_attestation_fingerprint": code["artifact_fingerprint"],
        "code_tree_fingerprint": code["code_tree_fingerprint"],
        "image_attestation_fingerprint": image["artifact_fingerprint"],
        "image_id": image["image_id"],
        "image_metadata_fingerprint": image["image_metadata_fingerprint"],
        "authority_attestation_fingerprint": authority["artifact_fingerprint"],
        "authority_state_fingerprint": authority["authority_state_fingerprint"],
        "authority_execution_fingerprint": authority["authority_execution_fingerprint"],
        "authority_blocking_gate_set_fingerprint": authority["blocking_gate_set_fingerprint"],
        "methodology_ready_status": authority["methodology_ready_status"],
        "source_identifier_candidate_artifact_sha256": source_identifier_binding[
            "source_artifact_byte_hash"
        ],
        "source_identifier_candidate_artifact_fingerprint": (
            source_identifier_binding["source_artifact_fingerprint"]
        ),
        "source_identifier_candidate_binding_fingerprint": (
            source_identifier_binding["binding_fingerprint"]
        ),
        "source_identifier_candidate_schema_version": (
            source_identifier_binding["candidate_artifact_schema_version"]
        ),
        "source_identifier_candidate_schema_version_fingerprint": (
            source_identifier_binding["candidate_artifact_schema_fingerprint"]
        ),
        "source_identifier_identity_scope_mode_status": identity_scope_mode,
        "source_identifier_identity_scope_mode_fingerprint": (
            source_identifier_binding["identity_scope_mode_fingerprint"]
        ),
        "source_identifier_identity_scope_fingerprint": (
            source_identifier_binding["identity_scope_fingerprint"]
        ),
        "source_identifier_identity_scope_binding_fingerprint": (
            source_identifier_binding["identity_scope_binding_fingerprint"]
        ),
        "source_identifier_identity_scope_graph_binding_fingerprint": (
            source_identifier_binding["identity_scope_graph_binding_fingerprint"]
        ),
        "source_identifier_identity_scope_attestation_sha256": (
            source_identifier_binding["identity_scope_attestation_byte_sha256"]
        ),
        "source_identifier_identity_scope_attestation_fingerprint": (
            source_identifier_binding["identity_scope_attestation_fingerprint"]
        ),
        "source_identifier_identity_scope_policy_fingerprint": (
            source_identifier_binding["identity_scope_policy_fingerprint"]
        ),
        "source_identifier_operator_approval_fingerprint": (
            source_identifier_binding["operator_approval_fingerprint"]
        ),
        "source_identifier_mode_approval_binding_fingerprint": (
            source_identifier_binding["mode_approval_fingerprint"]
        ),
        "source_identifier_workspace_scope_fingerprint": (
            source_identifier_binding["workspace_scope_fingerprint"]
        ),
        "source_identifier_attested_asset_fingerprint": (
            source_identifier_binding["attested_asset_fingerprint"]
        ),
        "source_identifier_candidate_profile_fingerprint": (
            source_identifier_binding["candidate_admission_profile_fingerprint"]
        ),
        "source_identifier_extraction_policy_fingerprint": (
            source_identifier_binding["extraction_policy_fingerprint"]
        ),
        "source_identifier_resolution_policy_fingerprint": (
            source_identifier_binding["resolution_policy_fingerprint"]
        ),
        "source_identifier_complete_mention_batch_fingerprint": (
            source_identifier_binding["complete_mention_batch_fingerprint"]
        ),
        "source_identifier_complete_resolution_fingerprint": (
            source_identifier_binding["complete_resolution_fingerprint"]
        ),
        "source_identifier_projected_mention_batch_fingerprint": (
            source_identifier_binding["selected_mention_batch_fingerprint"]
        ),
        "source_identifier_projected_resolution_fingerprint": (
            source_identifier_binding["selected_resolution_fingerprint"]
        ),
        "source_identifier_complete_mention_fingerprint_set_hash": (
            graph_ontology_binding["complete_identifier_mention_fingerprint_set_hash"]
        ),
        "source_identifier_authorized_mention_fingerprint_set_hash": (
            graph_ontology_binding["authorized_identifier_mention_fingerprint_set_hash"]
        ),
        "source_identifier_resolution_fingerprint_set_hash": (
            graph_ontology_binding["identifier_resolution_fingerprint_set_hash"]
        ),
        "source_identifier_requester_projection_fingerprint_set_hash": (
            graph_ontology_binding["requester_projected_mention_batch_fingerprint_set_hash"]
        ),
        "source_identifier_complete_mention_count": source_identifier_binding[
            "complete_mention_count"
        ],
        "source_identifier_complete_resolved_candidate_count": (
            source_identifier_binding["complete_resolved_candidate_count"]
        ),
        "source_identifier_projected_mention_count": source_identifier_binding[
            "selected_mention_count"
        ],
        "source_identifier_projected_resolved_candidate_count": (
            source_identifier_binding["selected_resolved_candidate_count"]
        ),
        "source_identifier_overflow_count": source_identifier_binding["overflow_count"],
        "source_identifier_candidate_graph_only": source_identifier_binding["candidate_graph_only"],
        "source_identifier_canonical_write_allowed": source_identifier_binding[
            "canonical_write_allowed"
        ],
        "source_graph_policy_fingerprint": source_identifier_binding[
            "source_graph_policy_fingerprint"
        ],
        "source_identifier_adapter_fingerprint": source_identifier_binding[
            "source_identifier_adapter_fingerprint"
        ],
        "holdout_source_identifier_adapter_fingerprint": source_identifier_binding[
            "holdout_adapter_fingerprint"
        ],
        "consumed_claim_contract_fingerprint": CONSUMED_CLAIM_CONTRACT_FINGERPRINT,
        "execution_output_contract_fingerprint": EXECUTION_OUTPUT_CONTRACT_FINGERPRINT,
    }
    if identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        pins["source_identifier_spec_approval_fingerprint"] = source_identifier_binding[
            "spec_approval_fingerprint"
        ]
    pins["runtime_fingerprint"] = sha256_json(pins)
    return pins


def _development_execution_contract() -> dict[str, Any]:
    return {
        "arm_ids": list(development_uat.ARM_IDS),
        "full_case_arm_ids": list(development_uat.FULL_CASE_ARM_IDS),
        "exact_executor_id": EXACT_EXECUTOR_ID,
        "quality_gate_id": development_uat.QUALITY_GATE_ID,
        "execution_budget_policy_id": development_uat.EXECUTION_BUDGET_POLICY_ID,
        "operational_budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
        "permission_policy_fingerprint": sha256_json(development_uat.PERMISSION_POLICY_ID),
        "citation_precision_minimum_basis_points": (
            development_uat.CITATION_PRECISION_MINIMUM_BASIS_POINTS
        ),
        "direct_regression_maximum_basis_points": (
            development_uat.DIRECT_REGRESSION_MAXIMUM_BASIS_POINTS
        ),
        "graph_required_gain_minimum_basis_points": (
            development_uat.GRAPH_REQUIRED_GAIN_MINIMUM_BASIS_POINTS
        ),
        "permission_leakage_maximum": 0,
        "graph_hop_authorization": "every_hop_requires_authorized_observation",
        "no_answer_gate": "no_citations_on_no_answer",
        "exact_gate": "deterministic_complete_authorized_scope_only",
        "public_output_policy": "hash_status_count_stratified_metrics_only",
        "quality_oracle_access": "execute_once_after_master_runtime_freeze_only",
        "source_graph_policy_id": development_uat.SOURCE_GRAPH_POLICY_ID,
        "source_identifier_adapter_id": development_uat.SOURCE_IDENTIFIER_ADAPTER_ID,
        "holdout_source_identifier_adapter_id": SOURCE_IDENTIFIER_HOLDOUT_ADAPTER_ID,
        "source_identifier_candidate_schema_version": (CANDIDATE_ARTIFACT_SCHEMA_VERSION),
        "source_identifier_identity_scope_modes": [
            TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
            WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        ],
        "source_identifier_graph_contract": ("requester_projected_batch_explicit_source_graph_v2"),
        "consumed_claim_contract_fingerprint": CONSUMED_CLAIM_CONTRACT_FINGERPRINT,
        "execution_output_contract_fingerprint": EXECUTION_OUTPUT_CONTRACT_FINGERPRINT,
        "case_specific_tuning": False,
        "retry_policy": "one_shot_no_retry",
    }


def run_holdout_case_arms(
    *,
    session: Any,
    effective_graph_view: Any,
    query_text: str,
    result_limit: int,
) -> tuple[tuple[str, Any, float, float, str], ...]:
    """Delegate unchanged arm execution to the existing development owner."""

    return development_uat._run_case_arms(
        session=session,
        effective_graph_view=effective_graph_view,
        query_text=query_text,
        result_limit=result_limit,
    )


def score_deterministic_exact_holdout_case(
    *,
    case: Mapping[str, Any],
    expected_private: Mapping[str, Any],
    exact_result: DeterministicExactExecutionResult,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    bundle: MailEvidenceBundle,
    holdout_policy: _HoldoutPolicy = _BASE_HOLDOUT_POLICY,
) -> dict[str, Any]:
    """Score a sealed exact case against the deterministic executor result.

    This adapter is execution-only.  Preflight never calls it or accesses
    ``expected_private``.
    """

    if holdout_policy.policy_id == EXTENSION_HOLDOUT_POLICY_ID:
        return _score_extension_protected_identifier_exact_case(
            case=case,
            expected_private=expected_private,
            exact_result=exact_result,
            observations_by_id=observations_by_id,
            observation_hash_by_id=observation_hash_by_id,
            bundle=bundle,
        )
    if holdout_policy.policy_id != BASE_HOLDOUT_POLICY_ID:
        raise IndependentMailHoldoutUatError("holdout_policy_id_invalid")

    result_kind = str(case.get("result_kind"))
    if result_kind not in {"exact_set", "exact_count", "exact_aggregation"}:
        raise IndependentMailHoldoutUatError("holdout_exact_case_kind_invalid")
    expected_observation_ids = _string_list(
        expected_private.get("exact_observation_ids"),
        "holdout_exact_observation_oracle_invalid",
    )
    required_observation_ids = _string_list(
        case.get("required_source_observation_ids"),
        "holdout_required_observation_ids_invalid",
    )
    if set(expected_observation_ids) != set(required_observation_ids) or len(
        expected_observation_ids
    ) != len(required_observation_ids):
        raise IndependentMailHoldoutUatError("holdout_exact_observation_oracle_binding_mismatch")
    if set(expected_observation_ids) - set(observations_by_id):
        raise IndependentMailHoldoutUatError("holdout_exact_observation_owner_record_missing")
    if set(expected_observation_ids) - set(observation_hash_by_id):
        raise IndependentMailHoldoutUatError("holdout_exact_observation_hash_missing")

    expected_item_by_hash = {
        sha256_json(
            {
                "inventory_kind": "mail_observation",
                "inventory_value": observation_id,
            }
        ): observation_id
        for observation_id in expected_observation_ids
    }
    if len(expected_item_by_hash) != len(expected_observation_ids):
        raise IndependentMailHoldoutUatError("holdout_exact_expected_item_identity_duplicate")
    actual_item_by_hash = {item.item_hash: item for item in exact_result.items}
    actual_item_hashes = set(actual_item_by_hash)
    expected_item_hashes = set(expected_item_by_hash)
    duplicate_item_count = len(exact_result.items) - len(actual_item_by_hash)
    authorized_hashes = set(observation_hash_by_id.values())
    cited_hashes = {
        citation_hash
        for item in exact_result.items
        for citation_hash in item.cited_observation_hashes
    }
    item_citation_lineage_complete = all(
        item.cited_observation_hashes
        and set(item.cited_observation_hashes) <= authorized_hashes
        and (
            item.item_hash not in expected_item_by_hash
            or observation_hash_by_id[expected_item_by_hash[item.item_hash]]
            in item.cited_observation_hashes
        )
        for item in exact_result.items
    )
    coverage = exact_result.coverage
    coverage_complete = (
        exact_result.status == "complete_authorized_scope"
        and coverage.authorized_scope_complete is True
        and coverage.missing_evidence_record_count == 0
        and not coverage.incompleteness_reason_hashes
        and coverage.eligible_record_count == coverage.enumerated_record_count
        and coverage.enumerated_record_count == exact_result.exact_count
        and exact_result.exact_count == exact_result.returned_item_count
        and exact_result.returned_item_count == len(exact_result.items)
        and exact_result.cited_observation_count == len(cited_hashes)
        and coverage.cited_observation_count == len(cited_hashes)
        and duplicate_item_count == 0
        and item_citation_lineage_complete
    )
    inventory_kind_match = exact_result.inventory_kind_hash == sha256_json("mail_observation")
    item_set_match = actual_item_hashes == expected_item_hashes

    occurrence_to_message = {
        occurrence.message_occurrence_id: occurrence.email_message_id
        for occurrence in bundle.message_occurrences
    }
    message_by_id = {message.email_message_id: message for message in bundle.messages}
    observation_to_message: dict[str, str] = {}
    for observation_id in expected_observation_ids:
        occurrence_id = observations_by_id[observation_id].location.get("message_occurrence_id")
        message_id = occurrence_to_message.get(str(occurrence_id))
        if not message_id or message_id not in message_by_id:
            raise IndependentMailHoldoutUatError("holdout_exact_message_lineage_missing")
        observation_to_message[observation_id] = message_id
    actual_message_ids = {
        observation_to_message[expected_item_by_hash[item_hash]]
        for item_hash in actual_item_hashes & expected_item_hashes
    }
    expected_message_ids = set(
        _string_list(
            expected_private.get("exact_message_ids"),
            "holdout_exact_message_oracle_invalid",
        )
    )
    derived_message_ids = set(observation_to_message.values())
    if expected_message_ids != derived_message_ids:
        raise IndependentMailHoldoutUatError("holdout_exact_message_oracle_binding_mismatch")
    expected_message_count = expected_private.get("exact_message_count")
    if (
        not isinstance(expected_message_count, int)
        or isinstance(expected_message_count, bool)
        or expected_message_count != len(expected_message_ids)
    ):
        raise IndependentMailHoldoutUatError("holdout_exact_message_count_oracle_invalid")
    message_set_match = actual_message_ids == expected_message_ids

    exact_value_match = False
    aggregation_match = result_kind != "exact_aggregation"
    expected_projection: Any
    actual_projection: Any
    if result_kind == "exact_set":
        exact_set_message_ids = set(
            _string_list(
                expected_private.get("exact_set_message_ids"),
                "holdout_exact_set_oracle_invalid",
            )
        )
        if exact_set_message_ids != expected_message_ids:
            raise IndependentMailHoldoutUatError("holdout_exact_set_oracle_binding_mismatch")
        expected_projection = sorted(expected_item_hashes)
        actual_projection = sorted(actual_item_hashes)
        exact_value_match = item_set_match and message_set_match
    elif result_kind == "exact_count":
        expected_count = expected_private.get("exact_count")
        if (
            not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or expected_count != len(expected_observation_ids)
        ):
            raise IndependentMailHoldoutUatError("holdout_exact_count_oracle_invalid")
        expected_projection = expected_count
        actual_projection = exact_result.exact_count
        exact_value_match = exact_result.exact_count == expected_count and message_set_match
    else:
        if expected_private.get("group_by") != "sender":
            raise IndependentMailHoldoutUatError("holdout_exact_aggregation_group_by_invalid")
        expected_groups = _normalized_expected_sender_groups(expected_private.get("groups"))
        actual_groups = _actual_sender_groups(
            message_ids=actual_message_ids,
            message_by_id=message_by_id,
        )
        expected_projection = expected_groups
        actual_projection = actual_groups
        aggregation_match = actual_groups == expected_groups
        exact_value_match = item_set_match and message_set_match and aggregation_match

    passed = (
        coverage_complete
        and inventory_kind_match
        and item_set_match
        and exact_value_match
        and aggregation_match
    )
    row: dict[str, Any] = {
        "case_manifest_entry_hash": _require_sha256(
            case.get("private_fingerprint"),
            "holdout_case_fingerprint_invalid",
        ),
        "result_kind": result_kind,
        "status": "passed" if passed else "failed",
        "exact_status": exact_result.status,
        "coverage_complete": coverage_complete,
        "inventory_kind_match": inventory_kind_match,
        "item_set_match": item_set_match,
        "message_set_match": message_set_match,
        "aggregation_match": aggregation_match,
        "expected_item_count": len(expected_item_hashes),
        "actual_item_count": len(actual_item_hashes),
        "expected_message_count": expected_message_count,
        "actual_message_count": len(actual_message_ids),
        "duplicate_item_count": duplicate_item_count,
        "unresolved_item_citation_count": (0 if item_citation_lineage_complete else 1),
        "expected_value_fingerprint": sha256_json(expected_projection),
        "actual_value_fingerprint": sha256_json(actual_projection),
        "exact_result_fingerprint": exact_result.result_fingerprint,
    }
    row["score_fingerprint"] = sha256_json(row)
    return row


def _score_extension_protected_identifier_exact_case(
    *,
    case: Mapping[str, Any],
    expected_private: Mapping[str, Any],
    exact_result: DeterministicExactExecutionResult,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    bundle: MailEvidenceBundle,
) -> dict[str, Any]:
    result_kind = str(case.get("result_kind"))
    if result_kind not in {"exact_set", "exact_count", "exact_aggregation"}:
        raise IndependentMailHoldoutUatError("holdout_exact_case_kind_invalid")
    required_observation_ids = tuple(
        sorted(
            _string_list(
                case.get("required_source_observation_ids"),
                "holdout_required_observation_ids_invalid",
            )
        )
    )
    adjudicated_observation_ids = tuple(
        sorted(
            _string_list(
                expected_private.get("required_source_observation_ids"),
                "holdout_exact_observation_oracle_invalid",
            )
        )
    )
    if (
        required_observation_ids != adjudicated_observation_ids
        or not required_observation_ids
        or set(required_observation_ids) - set(observations_by_id)
        or set(required_observation_ids) - set(observation_hash_by_id)
        or expected_private.get("inventory_kind") != "protected_identifier"
    ):
        raise IndependentMailHoldoutUatError("holdout_exact_observation_oracle_binding_mismatch")

    profile = load_issue56_target_mail_tokenizer_profile()
    supporting_hashes_by_token: dict[str, set[str]] = {}
    identifier_kind_by_token: dict[str, str] = {}
    for observation_id in required_observation_ids:
        observation = observations_by_id[observation_id]
        observation_hash = observation_hash_by_id[observation_id]
        for span in profile.analyze(observation.text or "").protected_identifiers:
            previous_kind = identifier_kind_by_token.setdefault(
                span.exact_token,
                span.identifier_kind,
            )
            if previous_kind != span.identifier_kind:
                raise IndependentMailHoldoutUatError("holdout_exact_identifier_kind_ambiguous")
            supporting_hashes_by_token.setdefault(span.exact_token, set()).add(observation_hash)
    if not supporting_hashes_by_token:
        raise IndependentMailHoldoutUatError("holdout_exact_identifier_inventory_empty")

    expected_item_by_hash = {
        sha256_json(
            {
                "inventory_kind": "protected_identifier",
                "inventory_value": token,
            }
        ): token
        for token in supporting_hashes_by_token
    }
    if len(expected_item_by_hash) != len(supporting_hashes_by_token):
        raise IndependentMailHoldoutUatError("holdout_exact_expected_item_identity_duplicate")
    derived_items = tuple(sorted(supporting_hashes_by_token))
    derived_counts_by_kind = dict(sorted(Counter(identifier_kind_by_token.values()).items()))
    if result_kind == "exact_set":
        expected_items = tuple(
            sorted(
                _string_list(
                    expected_private.get("items"),
                    "holdout_exact_set_oracle_invalid",
                )
            )
        )
        if expected_items != derived_items:
            raise IndependentMailHoldoutUatError("holdout_exact_set_oracle_binding_mismatch")
        expected_projection: Any = sorted(expected_item_by_hash)
    elif result_kind == "exact_count":
        expected_count = expected_private.get("count")
        if (
            not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or expected_count != len(derived_items)
        ):
            raise IndependentMailHoldoutUatError("holdout_exact_count_oracle_binding_mismatch")
        expected_projection = expected_count
    else:
        expected_counts = expected_private.get("counts_by_identifier_kind")
        if (
            not isinstance(expected_counts, Mapping)
            or dict(expected_counts) != derived_counts_by_kind
        ):
            raise IndependentMailHoldoutUatError(
                "holdout_exact_aggregation_oracle_binding_mismatch"
            )
        expected_projection = derived_counts_by_kind

    actual_item_by_hash = {item.item_hash: item for item in exact_result.items}
    actual_item_hashes = set(actual_item_by_hash)
    expected_item_hashes = set(expected_item_by_hash)
    duplicate_item_count = len(exact_result.items) - len(actual_item_by_hash)
    authorized_hashes = set(observation_hash_by_id.values())
    cited_hashes = {
        citation_hash
        for item in exact_result.items
        for citation_hash in item.cited_observation_hashes
    }
    item_citation_lineage_complete = all(
        item.cited_observation_hashes
        and set(item.cited_observation_hashes) <= authorized_hashes
        and (
            item.item_hash not in expected_item_by_hash
            or set(item.cited_observation_hashes)
            <= supporting_hashes_by_token[expected_item_by_hash[item.item_hash]]
        )
        for item in exact_result.items
    )
    coverage = exact_result.coverage
    coverage_complete = (
        exact_result.status == "complete_authorized_scope"
        and coverage.authorized_scope_complete is True
        and coverage.missing_evidence_record_count == 0
        and not coverage.incompleteness_reason_hashes
        and coverage.eligible_record_count == coverage.enumerated_record_count
        and coverage.enumerated_record_count == exact_result.exact_count
        and exact_result.exact_count == exact_result.returned_item_count
        and exact_result.returned_item_count == len(exact_result.items)
        and exact_result.cited_observation_count == len(cited_hashes)
        and coverage.cited_observation_count == len(cited_hashes)
        and duplicate_item_count == 0
        and item_citation_lineage_complete
    )
    inventory_kind_match = exact_result.inventory_kind_hash == sha256_json("protected_identifier")
    item_set_match = actual_item_hashes == expected_item_hashes
    if result_kind == "exact_set":
        actual_projection: Any = sorted(actual_item_hashes)
        exact_value_match = item_set_match
        aggregation_match = True
    elif result_kind == "exact_count":
        actual_projection = exact_result.exact_count
        exact_value_match = exact_result.exact_count == expected_projection and item_set_match
        aggregation_match = True
    else:
        actual_projection = derived_counts_by_kind if item_set_match else {"item_set_match": False}
        aggregation_match = item_set_match and actual_projection == expected_projection
        exact_value_match = aggregation_match

    occurrence_to_message = {
        occurrence.message_occurrence_id: occurrence.email_message_id
        for occurrence in bundle.message_occurrences
    }
    expected_message_ids: set[str] = set()
    cited_message_ids: set[str] = set()
    observation_id_by_hash = {
        observation_hash: observation_id
        for observation_id, observation_hash in observation_hash_by_id.items()
    }
    for observation_id in required_observation_ids:
        occurrence_id = _observation_occurrence_id(observations_by_id[observation_id])
        message_id = occurrence_to_message.get(str(occurrence_id))
        if not occurrence_id or not message_id:
            raise IndependentMailHoldoutUatError("holdout_exact_message_lineage_missing")
        expected_message_ids.add(message_id)
    for citation_hash in cited_hashes:
        observation_id = observation_id_by_hash.get(citation_hash)
        if observation_id is None:
            continue
        occurrence_id = _observation_occurrence_id(observations_by_id[observation_id])
        message_id = occurrence_to_message.get(str(occurrence_id))
        if message_id:
            cited_message_ids.add(message_id)
    message_set_match = cited_message_ids <= expected_message_ids
    passed = (
        coverage_complete
        and inventory_kind_match
        and item_set_match
        and exact_value_match
        and aggregation_match
        and message_set_match
    )
    row: dict[str, Any] = {
        "case_manifest_entry_hash": _require_sha256(
            case.get("private_fingerprint"),
            "holdout_case_fingerprint_invalid",
        ),
        "result_kind": result_kind,
        "status": "passed" if passed else "failed",
        "exact_status": exact_result.status,
        "coverage_complete": coverage_complete,
        "inventory_kind_match": inventory_kind_match,
        "item_set_match": item_set_match,
        "message_set_match": message_set_match,
        "aggregation_match": aggregation_match,
        "expected_item_count": len(expected_item_hashes),
        "actual_item_count": len(actual_item_hashes),
        "expected_message_count": len(expected_message_ids),
        "actual_message_count": len(cited_message_ids),
        "duplicate_item_count": duplicate_item_count,
        "unresolved_item_citation_count": (0 if item_citation_lineage_complete else 1),
        "expected_value_fingerprint": sha256_json(expected_projection),
        "actual_value_fingerprint": sha256_json(actual_projection),
        "exact_result_fingerprint": exact_result.result_fingerprint,
    }
    row["score_fingerprint"] = sha256_json(row)
    return row


def _execute_independent_holdout_once(
    *,
    preflight_report: Mapping[str, Any],
    execution_context: _HoldoutExecutionContext,
    bundle: MailEvidenceBundle,
    oracle_free_projection: Mapping[str, Any],
    holdout_policy: _HoldoutPolicy = _BASE_HOLDOUT_POLICY,
    manifest_path: Path,
    expected_manifest_sha256: str,
    runtime_binding: Mapping[str, Any],
    execution_output: Path,
) -> dict[str, Any]:
    """Execute one sealed holdout entirely in memory before atomic publish."""

    _assert_oracle_free_projection(oracle_free_projection)
    projection_fingerprint = _require_sha256(
        oracle_free_projection.get("projection_fingerprint"),
        "one_shot_holdout_projection_binding_invalid",
    )
    if projection_fingerprint != _payload_fingerprint(
        oracle_free_projection,
        "projection_fingerprint",
    ):
        raise IndependentMailHoldoutUatError("one_shot_holdout_projection_binding_invalid")
    projection_manifest_binding = _validated_private_manifest_binding(
        oracle_free_projection,
        expected_manifest_sha256=expected_manifest_sha256,
        holdout_policy=holdout_policy,
    )
    preflight_hashes = preflight_report.get("hashes")
    if (
        not isinstance(preflight_hashes, Mapping)
        or preflight_hashes.get("holdout_oracle_free_projection_fingerprint")
        != projection_fingerprint
        or preflight_hashes.get("holdout_private_manifest_id")
        != projection_manifest_binding["private_manifest_id"]
    ):
        raise IndependentMailHoldoutUatError("one_shot_holdout_projection_binding_mismatch")
    consumed_claim = _acquire_consumed_claim(
        preflight_report=preflight_report,
        runtime_binding=runtime_binding,
        expected_manifest_sha256=expected_manifest_sha256,
        execution_output=execution_output,
    )
    manifest = _decode_private_holdout_manifest_after_claim(
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        oracle_free_projection=oracle_free_projection,
        holdout_policy=holdout_policy,
        execution_context=execution_context,
        bundle=bundle,
    )
    post_claim_execution_binding: dict[str, Any] | None = None
    if (
        holdout_policy.policy_id == BASE_HOLDOUT_POLICY_ID
        and _is_source_author_hashed_base_projection(oracle_free_projection)
    ):
        execution_context, post_claim_execution_binding = (
            _source_author_execution_context_after_claim(
                manifest=manifest,
                projection=oracle_free_projection,
                preflight_context=execution_context,
                bundle=bundle,
                runtime_binding=runtime_binding,
            )
        )
    if holdout_policy.policy_id == EXTENSION_HOLDOUT_POLICY_ID:
        _validate_extension_execution_manifest_lineage(
            manifest=manifest,
            projection=oracle_free_projection,
            preflight_report=preflight_report,
            execution_context=execution_context,
            bundle=bundle,
            holdout_policy=holdout_policy,
        )
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != holdout_policy.case_count:
        raise IndependentMailHoldoutUatError("holdout_case_count_mismatch")
    rows_by_arm: dict[str, list[dict[str, Any]]] = {
        arm_id: [] for arm_id in development_uat.ARM_IDS
    }
    exact_score_rows: list[dict[str, Any]] = []
    execution_component_fingerprints: set[str] = set()
    index_fingerprints: set[str] = set()
    authorized_index_fingerprints: set[str] = set()
    peak_memory_before_kib = _peak_memory_kib()
    for case in cases:
        adapted_case = _adapt_holdout_case_for_development_helpers(case)
        requester_user_id = str(adapted_case["requester_user_id"])
        session = execution_context.sessions.get(requester_user_id)
        view = execution_context.effective_graph_views.get(requester_user_id)
        lineage_crosswalk = execution_context.lineage_crosswalks.get(requester_user_id)
        if session is None or view is None or lineage_crosswalk is None:
            raise IndependentMailHoldoutUatError("holdout_execution_requester_context_missing")
        query_text = str(adapted_case["query_text"])
        arm_results = run_holdout_case_arms(
            session=session,
            effective_graph_view=view,
            query_text=query_text,
            result_limit=int(adapted_case["limit"]),
        )
        execution_component_fingerprints.add(session.index.execution_component_fingerprint)
        index_fingerprints.add(session.index.index_fingerprint)
        if _case_stratum(case) != "permission_denied":
            authorized_index_fingerprints.add(session.index.index_fingerprint)
        for (
            arm_id,
            result,
            elapsed_ms,
            cpu_ms,
            execution_budget_fingerprint,
        ) in arm_results:
            answer = render_governed_evidence_answer(
                result,
                budget=EvidenceAnswerBudget(),
            )
            scored_row = development_uat._score_case(
                adapted_case,
                result=result,
                answer_status=answer.status,
                citation_hashes=answer.citation_hashes,
                exact_count=answer.exact_count,
                answer_hash=answer.answer_hash,
                source_result_fingerprint=answer.source_result_fingerprint,
                cost_units=answer.cost_units,
                elapsed_ms=elapsed_ms,
                cpu_ms=cpu_ms,
                execution_budget_fingerprint=execution_budget_fingerprint,
                observation_hash_by_id=(execution_context.observation_hash_by_id),
                lineage_crosswalk=lineage_crosswalk,
            )
            if (
                arm_id == EXACT_EXECUTOR_ID
                and adapted_case["score_adapter"] == "deterministic_exact"
            ):
                exact_result = getattr(result, "exact_result", None)
                if not isinstance(
                    exact_result,
                    DeterministicExactExecutionResult,
                ):
                    raise IndependentMailHoldoutUatError("holdout_exact_executor_result_missing")
                exact_score = score_deterministic_exact_holdout_case(
                    case=case,
                    expected_private=_exact_case_oracle(
                        case,
                        holdout_policy=holdout_policy,
                    ),
                    exact_result=exact_result,
                    observations_by_id=execution_context.observations_by_id,
                    observation_hash_by_id=(execution_context.observation_hash_by_id),
                    bundle=bundle,
                    holdout_policy=holdout_policy,
                )
                exact_score_rows.append(exact_score)
                scored_row = {
                    **scored_row,
                    "status": exact_score["status"],
                    "exact_status": exact_score["exact_status"],
                    "exact_returned_item_count": exact_score["actual_item_count"],
                    "exact_duplicate_item_count": exact_score["duplicate_item_count"],
                }
            rows_by_arm[arm_id].append(scored_row)

    if len(execution_component_fingerprints) != 1 or authorized_index_fingerprints != {
        runtime_binding["index_fingerprint"]
    }:
        raise IndependentMailHoldoutUatError("holdout_same_pipeline_runtime_binding_mismatch")
    if _sha256_bytes(manifest_path.read_bytes()) != expected_manifest_sha256:
        raise IndependentMailHoldoutUatError("holdout_manifest_changed_during_execution")

    arm_summaries = {
        arm_id: development_uat._aggregate_arm(rows_by_arm[arm_id])
        for arm_id in development_uat.ARM_IDS
    }
    budget_fairness = development_uat._budget_fairness_report(rows_by_arm)
    paired_transitions = _holdout_paired_transitions(rows_by_arm)
    quality_gate = development_uat._quality_gate_report(
        arm_summaries=arm_summaries,
        paired_transitions=paired_transitions,
        budget_fairness=budget_fairness,
    )
    quality_checks = {key: dict(value) for key, value in quality_gate["checks"].items()}
    operational_check = _holdout_operational_budget_check(
        hybrid_summary=arm_summaries["hybrid_v2_soft"],
        peak_memory_kib=_peak_memory_kib(),
    )
    quality_checks["operational_budget"] = operational_check
    exact_case_count = sum(
        _adapt_holdout_case_for_development_helpers(case)["score_adapter"] == "deterministic_exact"
        for case in cases
    )
    exact_failed_count = sum(row["status"] != "passed" for row in exact_score_rows)
    quality_checks["deterministic_exact_execution"] = {
        "status": (
            "passed"
            if (
                exact_case_count == holdout_policy.exact_case_count
                and len(exact_score_rows) == exact_case_count
                and exact_failed_count == 0
            )
            else "failed"
        ),
        "expected_case_count": holdout_policy.exact_case_count,
        "executed_case_count": len(exact_score_rows),
        "failed_case_count": exact_failed_count,
        "complete_case_count": sum(row["coverage_complete"] is True for row in exact_score_rows),
    }
    quality_status = _status_from_checks(quality_checks)
    quality_gate = {
        **quality_gate,
        "status": quality_status,
        "checks": quality_checks,
        "check_set_fingerprint": sha256_json(quality_checks),
    }

    permission_leakage_count = sum(
        int(row["forbidden_evidence_match_count"])
        for arm_id in development_uat.FULL_CASE_ARM_IDS
        for row in rows_by_arm[arm_id]
    )
    unresolved_citation_count = sum(
        int(row["lineage_audit_unresolved_count"])
        for arm_id in development_uat.FULL_CASE_ARM_IDS
        for row in rows_by_arm[arm_id]
    )
    unresolved_graph_hop_count = sum(
        int(row["graph_hop_unresolved_evidence_count"])
        for arm_id in (
            "rag_candidate_kg",
            "hybrid_v2_soft",
            "legacy_hard_gate",
        )
        for row in rows_by_arm[arm_id]
    )
    exact_incomplete_count = sum(row["coverage_complete"] is not True for row in exact_score_rows)
    safety = {
        "case_count": len(cases),
        "permission_leakage_count": permission_leakage_count,
        "unresolved_citation_count": unresolved_citation_count,
        "unresolved_graph_hop_count": unresolved_graph_hop_count,
        "exact_incomplete_count": exact_incomplete_count,
    }
    if len(cases) != holdout_policy.case_count:
        raise IndependentMailHoldoutUatError("holdout_execution_case_count_mismatch")
    universal_safety_failed = any(
        safety[field_name] != 0
        for field_name in (
            "permission_leakage_count",
            "unresolved_citation_count",
            "unresolved_graph_hop_count",
            "exact_incomplete_count",
        )
    )
    quality_checks["universal_safety"] = {
        "status": "failed" if universal_safety_failed else "passed",
        "permission_leakage_count": permission_leakage_count,
        "unresolved_citation_count": unresolved_citation_count,
        "unresolved_graph_hop_count": unresolved_graph_hop_count,
        "exact_incomplete_count": exact_incomplete_count,
    }
    quality_status = _status_from_checks(quality_checks)
    quality_gate = {
        **quality_gate,
        "status": quality_status,
        "checks": quality_checks,
        "check_set_fingerprint": sha256_json(quality_checks),
    }
    execution_status = {
        "passed": "passed",
        "failed": "quality_failed",
        "blocked": "blocked",
    }[quality_status]
    report: dict[str, Any] = {
        "artifact_id": EXECUTION_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": execution_status,
        "preflight_status": "passed",
        "execution_status": "passed",
        "quality_result_status": quality_status,
        "one_shot_status": "consumed",
        "consumed_claim_status": "bound",
        "artifact_seal_status": "passed",
        "development_quality_acceptance_status": "passed",
        "operational_budget_binding_status": "passed",
        "pre_holdout_authority_status": "passed",
        "runtime_freeze_status": "matched",
        "source_lineage_status": "passed",
        "permission_status": ("passed" if safety["permission_leakage_count"] == 0 else "failed"),
        "citation_lineage_status": (
            "passed" if safety["unresolved_citation_count"] == 0 else "failed"
        ),
        "graph_hop_lineage_status": (
            "passed" if safety["unresolved_graph_hop_count"] == 0 else "failed"
        ),
        "exact_execution_status": ("passed" if safety["exact_incomplete_count"] == 0 else "failed"),
        "counts": {
            "case_count": len(cases),
            "arm_count": len(development_uat.ARM_IDS),
            "full_case_arm_count": len(development_uat.FULL_CASE_ARM_IDS),
            "executed_case_count": len(cases),
            "executed_full_case_arm_count": sum(
                len(rows_by_arm[arm_id]) for arm_id in development_uat.FULL_CASE_ARM_IDS
            ),
            "executed_exact_case_count": len(exact_score_rows),
            "permission_leakage_count": permission_leakage_count,
            "unresolved_citation_count": unresolved_citation_count,
            "unresolved_graph_hop_count": unresolved_graph_hop_count,
            "exact_incomplete_count": exact_incomplete_count,
            "quality_check_count": len(quality_checks),
            "failed_quality_check_count": sum(
                check["status"] == "failed" for check in quality_checks.values()
            ),
            "blocked_quality_check_count": sum(
                check["status"] == "blocked" for check in quality_checks.values()
            ),
            "permission_scoped_graph_count": (
                execution_context.graph_ontology_binding["permission_scoped_graph_count"]
            ),
            **(
                {
                    "post_claim_requester_context_count": post_claim_execution_binding[
                        "requester_context_count"
                    ],
                    "post_claim_authorized_requester_context_count": (
                        post_claim_execution_binding["authorized_requester_context_count"]
                    ),
                    "post_claim_denied_requester_context_count": (
                        post_claim_execution_binding["denied_requester_context_count"]
                    ),
                }
                if post_claim_execution_binding is not None
                else {}
            ),
            "peak_memory_delta_lower_bound_kib": max(
                0,
                _peak_memory_kib() - peak_memory_before_kib,
            ),
            "sealed_quality_field_read_count": len(exact_score_rows),
            "blocker_count": sum(check["status"] != "passed" for check in quality_checks.values()),
        },
        "strata_counts": dict(preflight_report["strata_counts"]),
        "arms": arm_summaries,
        "paired_transitions": paired_transitions,
        "quality_gate": quality_gate,
        "hashes": {
            **{
                key: value
                for key, value in preflight_report["hashes"].items()
                if key != "report_fingerprint"
            },
            "execution_component_fingerprint": next(iter(execution_component_fingerprints)),
            "execution_row_set_fingerprint": sha256_json(
                {
                    arm_id: [
                        {
                            "case_manifest_entry_hash": row["case_manifest_entry_hash"],
                            "status": row["status"],
                            "answer_hash": row["answer_hash"],
                            "source_result_fingerprint": row["source_result_fingerprint"],
                        }
                        for row in rows_by_arm[arm_id]
                    ]
                    for arm_id in development_uat.ARM_IDS
                }
            ),
            "quality_check_set_fingerprint": sha256_json(quality_checks),
            "holdout_policy_fingerprint": holdout_policy.policy_fingerprint,
            "exact_score_set_fingerprint": sha256_json(exact_score_rows),
            "permission_scoped_index_fingerprint_set_hash": sha256_json(sorted(index_fingerprints)),
            "consumed_claim_sha256": consumed_claim.byte_sha256,
            "consumed_claim_fingerprint": consumed_claim.claim_fingerprint,
            "execution_output_binding_fingerprint": (
                consumed_claim.execution_output_binding_fingerprint
            ),
            **(
                {
                    "post_claim_requester_context_set_fingerprint": (
                        post_claim_execution_binding["requester_context_set_fingerprint"]
                    ),
                    "post_claim_graph_ontology_binding_fingerprint": (
                        post_claim_execution_binding["graph_ontology_binding_fingerprint"]
                    ),
                }
                if post_claim_execution_binding is not None
                else {}
            ),
        },
    }
    report["hashes"]["execution_artifact_binding_fingerprint"] = sha256_json(
        {
            "runtime_fingerprint": runtime_binding["runtime_fingerprint"],
            **{
                field_name: runtime_binding[field_name]
                for field_name in _SOURCE_IDENTIFIER_CLAIM_HASH_FIELDS
            },
            **(
                {
                    "source_identifier_spec_approval_fingerprint": runtime_binding[
                        "source_identifier_spec_approval_fingerprint"
                    ]
                }
                if runtime_binding.get("source_identifier_identity_scope_mode_status")
                == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
                else {}
            ),
            "consumed_claim_sha256": consumed_claim.byte_sha256,
            "consumed_claim_fingerprint": consumed_claim.claim_fingerprint,
            "execution_output_binding_fingerprint": (
                consumed_claim.execution_output_binding_fingerprint
            ),
            "execution_row_set_fingerprint": report["hashes"]["execution_row_set_fingerprint"],
            "quality_check_set_fingerprint": report["hashes"]["quality_check_set_fingerprint"],
            "exact_score_set_fingerprint": report["hashes"]["exact_score_set_fingerprint"],
            **(
                {
                    "post_claim_requester_context_set_fingerprint": report["hashes"][
                        "post_claim_requester_context_set_fingerprint"
                    ],
                    "post_claim_graph_ontology_binding_fingerprint": report["hashes"][
                        "post_claim_graph_ontology_binding_fingerprint"
                    ],
                }
                if post_claim_execution_binding is not None
                else {}
            ),
            "execution_output_contract_fingerprint": runtime_binding[
                "execution_output_contract_fingerprint"
            ],
        }
    )
    report["hashes"]["report_fingerprint"] = _report_fingerprint(report)
    _validate_public_report(report)
    _validate_consumed_claim_receipt(consumed_claim)
    _publish_immutable_json(execution_output, report)
    return report


def _holdout_paired_transitions(
    rows_by_arm: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    def direct(
        rows: Sequence[Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        return [row for row in rows if row["query_class"] == "evidence_lookup"]

    def graph_required(
        rows: Sequence[Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        return [row for row in rows if bool(row["positive_required_graph_case"])]

    transitions = {
        "rag_entity_vs_strong_rag": development_uat._paired_transitions(
            rows_by_arm["strong_rag"],
            rows_by_arm["rag_entity"],
        ),
        "rag_candidate_kg_vs_rag_entity": (
            development_uat._paired_transitions(
                rows_by_arm["rag_entity"],
                rows_by_arm["rag_candidate_kg"],
            )
        ),
        "hybrid_v2_soft_vs_strong_rag": (
            development_uat._paired_transitions(
                rows_by_arm["strong_rag"],
                rows_by_arm["hybrid_v2_soft"],
            )
        ),
        "hybrid_v2_soft_vs_rag_candidate_kg": (
            development_uat._paired_transitions(
                rows_by_arm["rag_candidate_kg"],
                rows_by_arm["hybrid_v2_soft"],
            )
        ),
        "legacy_hard_gate_vs_hybrid_v2_soft": (
            development_uat._paired_transitions(
                rows_by_arm["hybrid_v2_soft"],
                rows_by_arm["legacy_hard_gate"],
            )
        ),
        "hybrid_v2_soft_vs_strong_rag_direct_cases": (
            development_uat._paired_transitions(
                direct(rows_by_arm["strong_rag"]),
                direct(rows_by_arm["hybrid_v2_soft"]),
            )
        ),
        "hybrid_v2_soft_vs_strong_rag_graph_required": (
            development_uat._paired_transitions(
                graph_required(rows_by_arm["strong_rag"]),
                graph_required(rows_by_arm["hybrid_v2_soft"]),
            )
        ),
    }
    if rows_by_arm["structured_exact"]:
        transitions["structured_exact_vs_strong_rag_exact_cases"] = (
            development_uat._paired_transitions(
                [
                    row
                    for row in rows_by_arm["strong_rag"]
                    if row["query_class"] == "exact_set_or_inventory"
                ],
                rows_by_arm["structured_exact"],
            )
        )
    return transitions


def _holdout_operational_budget_check(
    *,
    hybrid_summary: Mapping[str, Any],
    peak_memory_kib: int,
) -> dict[str, Any]:
    latency_micros = round(float(hybrid_summary["latency_ms"]["p95"]) * 1_000)
    maximum_cost_units = int(hybrid_summary["cost_units"]["maximum"])
    zero_cost_fingerprint = deterministic_zero_cost_attestation_fingerprint()
    passed = (
        latency_micros <= LATENCY_P95_LIMIT_MICROS
        and maximum_cost_units <= INTERNAL_COST_UNITS_PER_CASE_LIMIT
        and peak_memory_kib <= PEAK_RSS_LIMIT_KIB
    )
    return {
        "status": "passed" if passed else "failed",
        "budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
        "latency_p95_limit_micros": LATENCY_P95_LIMIT_MICROS,
        "measured_latency_p95_micros": latency_micros,
        "internal_cost_units_per_case_limit": (INTERNAL_COST_UNITS_PER_CASE_LIMIT),
        "measured_maximum_internal_cost_units": maximum_cost_units,
        "peak_rss_limit_kib": PEAK_RSS_LIMIT_KIB,
        "measured_peak_rss_kib": peak_memory_kib,
        "zero_cost_attestation_fingerprint": zero_cost_fingerprint,
    }


def _exact_case_oracle(
    case: Mapping[str, Any],
    *,
    holdout_policy: _HoldoutPolicy = _BASE_HOLDOUT_POLICY,
) -> Mapping[str, Any]:
    oracle_fields = (
        ["adjudication"]
        if holdout_policy.policy_id == EXTENSION_HOLDOUT_POLICY_ID
        else [
            field_name for field_name in ("answer_oracle", "expected_private") if field_name in case
        ]
    )
    if len(oracle_fields) != 1:
        raise IndependentMailHoldoutUatError("holdout_exact_oracle_missing_or_ambiguous")
    oracle = case[oracle_fields[0]]
    if not isinstance(oracle, Mapping):
        raise IndependentMailHoldoutUatError("holdout_exact_oracle_invalid")
    return oracle


def _status_from_checks(
    checks: Mapping[str, Mapping[str, Any]],
) -> str:
    statuses = {str(check.get("status")) for check in checks.values()}
    if not statuses or not statuses <= {"passed", "failed", "blocked"}:
        raise IndependentMailHoldoutUatError("holdout_quality_check_status_invalid")
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    return "passed"


def _peak_memory_kib() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _consumed_claim_path(execution_output: Path) -> Path:
    return execution_output.with_name(f"{execution_output.name}.consumed.json")


def _execution_output_binding_fingerprint(execution_output: Path) -> str:
    claim_path = _consumed_claim_path(execution_output)
    return sha256_json(
        {
            "execution_output_locator_fingerprint": sha256_json(
                os.path.abspath(os.fspath(execution_output))
            ),
            "consumed_claim_locator_fingerprint": sha256_json(
                os.path.abspath(os.fspath(claim_path))
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
    """Atomically consume one sealed holdout before any quality-bearing read."""

    hashes = preflight_report.get("hashes")
    counts = preflight_report.get("counts")
    if (
        preflight_report.get("status") != "passed"
        or preflight_report.get("preflight_status") != "passed"
        or preflight_report.get("runtime_freeze_status") != "matched"
        or preflight_report.get("owner_execution_status") != "passed"
        or preflight_report.get("execution_status") != "not_run"
        or preflight_report.get("quality_result_status") != "not_read"
        or not isinstance(hashes, Mapping)
        or not isinstance(counts, Mapping)
        or counts.get("blocker_count") != 0
    ):
        raise IndependentMailHoldoutUatError("one_shot_preflight_not_passed")
    runtime_fingerprint = _require_sha256(
        runtime_binding.get("runtime_fingerprint"),
        "one_shot_runtime_fingerprint_invalid",
    )
    if hashes.get("runtime_fingerprint") != runtime_fingerprint:
        raise IndependentMailHoldoutUatError("one_shot_runtime_fingerprint_mismatch")
    _require_sha256(
        expected_manifest_sha256,
        "holdout_manifest_seal_invalid",
    )
    if hashes.get("holdout_manifest_sha256") != expected_manifest_sha256:
        raise IndependentMailHoldoutUatError("one_shot_manifest_binding_mismatch")
    holdout_projection_claim_hashes = {
        field_name: _require_sha256(
            hashes.get(field_name),
            "one_shot_holdout_projection_binding_invalid",
        )
        for field_name in _HOLDOUT_PROJECTION_CLAIM_HASH_FIELDS
    }
    source_identifier_claim_hashes = {
        field_name: _require_sha256(
            runtime_binding.get(field_name),
            "one_shot_source_identifier_artifact_binding_invalid",
        )
        for field_name in _SOURCE_IDENTIFIER_CLAIM_HASH_FIELDS
    }
    if any(
        hashes.get(field_name) != expected_value
        for field_name, expected_value in source_identifier_claim_hashes.items()
    ) or (
        runtime_binding.get("consumed_claim_contract_fingerprint")
        != CONSUMED_CLAIM_CONTRACT_FINGERPRINT
        or runtime_binding.get("execution_output_contract_fingerprint")
        != EXECUTION_OUTPUT_CONTRACT_FINGERPRINT
    ):
        raise IndependentMailHoldoutUatError("one_shot_source_identifier_artifact_binding_mismatch")
    if (
        runtime_binding.get("source_identifier_identity_scope_mode_status")
        == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    ):
        source_identifier_claim_hashes["source_identifier_spec_approval_fingerprint"] = (
            _require_sha256(
                runtime_binding.get("source_identifier_spec_approval_fingerprint"),
                "one_shot_source_identifier_artifact_binding_invalid",
            )
        )
        if (
            hashes.get("source_identifier_spec_approval_fingerprint")
            != source_identifier_claim_hashes["source_identifier_spec_approval_fingerprint"]
        ):
            raise IndependentMailHoldoutUatError(
                "one_shot_source_identifier_artifact_binding_mismatch"
            )
    preflight_input_fingerprint = _require_sha256(
        hashes.get("preflight_input_fingerprint"),
        "one_shot_preflight_fingerprint_invalid",
    )
    preflight_report_fingerprint = _require_sha256(
        hashes.get("report_fingerprint"),
        "one_shot_preflight_fingerprint_invalid",
    )
    execution_output_binding_fingerprint = _execution_output_binding_fingerprint(execution_output)
    claim: dict[str, Any] = {
        "artifact_id": CONSUMED_CLAIM_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "consumed",
        "claim_status": "acquired_before_quality_read",
        "retry_policy": "never",
        "hashes": {
            "preflight_input_fingerprint": preflight_input_fingerprint,
            "preflight_report_fingerprint": preflight_report_fingerprint,
            "runtime_fingerprint": runtime_fingerprint,
            "holdout_manifest_sha256": expected_manifest_sha256,
            **holdout_projection_claim_hashes,
            **source_identifier_claim_hashes,
            "consumed_claim_contract_fingerprint": (CONSUMED_CLAIM_CONTRACT_FINGERPRINT),
            "execution_output_contract_fingerprint": (EXECUTION_OUTPUT_CONTRACT_FINGERPRINT),
            "execution_output_binding_fingerprint": (execution_output_binding_fingerprint),
        },
    }
    claim["hashes"]["claim_fingerprint"] = _consumed_claim_fingerprint(claim)
    try:
        assert_no_public_raw_references(claim, CONSUMED_CLAIM_ARTIFACT_ID)
    except ContractValidationError as exc:
        raise IndependentMailHoldoutUatError("one_shot_consumed_claim_private_leak") from exc
    claim_path = _consumed_claim_path(execution_output)
    claim_sha256 = _publish_exclusive_immutable_json(
        claim_path,
        claim,
        exists_reason="one_shot_consumed_claim_already_exists",
        publish_reason="one_shot_consumed_claim_publish_failed",
    )
    receipt = _ConsumedClaimReceipt(
        claim_path=claim_path,
        payload=claim,
        byte_sha256=claim_sha256,
        claim_fingerprint=str(claim["hashes"]["claim_fingerprint"]),
        execution_output_binding_fingerprint=execution_output_binding_fingerprint,
    )
    _validate_consumed_claim_receipt(receipt)
    if execution_output.exists():
        raise IndependentMailHoldoutUatError("one_shot_output_already_exists")
    return receipt


def _validate_consumed_claim_receipt(receipt: _ConsumedClaimReceipt) -> None:
    try:
        metadata = receipt.claim_path.lstat()
        payload = receipt.claim_path.read_bytes()
        decoded = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndependentMailHoldoutUatError("one_shot_consumed_claim_audit_failed") from exc
    decoded_hashes = decoded.get("hashes", {})
    if (
        receipt.claim_path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o222
        or _sha256_bytes(payload) != receipt.byte_sha256
        or decoded != receipt.payload
        or receipt.claim_fingerprint != _consumed_claim_fingerprint(decoded)
        or decoded_hashes.get("claim_fingerprint") != receipt.claim_fingerprint
        or decoded_hashes.get("execution_output_binding_fingerprint")
        != receipt.execution_output_binding_fingerprint
        or decoded_hashes.get("consumed_claim_contract_fingerprint")
        != CONSUMED_CLAIM_CONTRACT_FINGERPRINT
        or decoded_hashes.get("execution_output_contract_fingerprint")
        != EXECUTION_OUTPUT_CONTRACT_FINGERPRINT
        or any(
            not isinstance(decoded_hashes.get(field_name), str)
            or not str(decoded_hashes[field_name]).startswith("sha256:")
            or len(str(decoded_hashes[field_name])) != _SHA256_LENGTH
            for field_name in _SOURCE_IDENTIFIER_CLAIM_HASH_FIELDS
        )
        or any(
            not isinstance(decoded_hashes.get(field_name), str)
            or not str(decoded_hashes[field_name]).startswith("sha256:")
            or len(str(decoded_hashes[field_name])) != _SHA256_LENGTH
            for field_name in _HOLDOUT_PROJECTION_CLAIM_HASH_FIELDS
        )
    ):
        raise IndependentMailHoldoutUatError("one_shot_consumed_claim_audit_failed")


def _consumed_claim_fingerprint(claim: Mapping[str, Any]) -> str:
    payload = dict(claim)
    hashes = dict(payload.get("hashes", {}))
    hashes.pop("claim_fingerprint", None)
    payload["hashes"] = hashes
    return sha256_json(payload)


def _publish_immutable_json(
    output_path: Path,
    payload: Mapping[str, Any],
) -> None:
    _publish_exclusive_immutable_json(
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
        raise IndependentMailHoldoutUatError(exists_reason)
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
        raise IndependentMailHoldoutUatError(exists_reason) from exc
    except OSError as exc:
        raise IndependentMailHoldoutUatError(publish_reason) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return _sha256_bytes(encoded)


def _normalized_expected_sender_groups(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise IndependentMailHoldoutUatError("holdout_exact_aggregation_groups_invalid")
    groups: list[dict[str, Any]] = []
    seen_senders: set[str] = set()
    for group in value:
        if not isinstance(group, Mapping):
            raise IndependentMailHoldoutUatError("holdout_exact_aggregation_groups_invalid")
        sender = group.get("sender")
        message_ids = _string_list(
            group.get("message_ids"),
            "holdout_exact_aggregation_groups_invalid",
        )
        count = group.get("count")
        if (
            not isinstance(sender, str)
            or not sender
            or sender in seen_senders
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count != len(message_ids)
        ):
            raise IndependentMailHoldoutUatError("holdout_exact_aggregation_groups_invalid")
        seen_senders.add(sender)
        groups.append(
            {
                "sender": sender,
                "count": count,
                "message_ids": sorted(message_ids),
            }
        )
    return tuple(sorted(groups, key=lambda group: group["sender"]))


def _actual_sender_groups(
    *,
    message_ids: set[str],
    message_by_id: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, set[str]] = {}
    for message_id in message_ids:
        message = message_by_id.get(message_id)
        sender = getattr(message, "sender", None)
        if not isinstance(sender, str) or not sender:
            raise IndependentMailHoldoutUatError("holdout_exact_aggregation_sender_missing")
        grouped.setdefault(sender, set()).add(message_id)
    return tuple(
        {
            "sender": sender,
            "count": len(grouped[sender]),
            "message_ids": sorted(grouped[sender]),
        }
        for sender in sorted(grouped)
    )


def _owner_gap_ids(
    manifest: Mapping[str, Any],
    *,
    holdout_policy: _HoldoutPolicy = _BASE_HOLDOUT_POLICY,
    referenced_observation_type_counts: Mapping[str, int],
) -> tuple[str, ...]:
    gaps: list[str] = []
    helper_parameters = {
        "_run_case_arms": {
            "session",
            "effective_graph_view",
            "query_text",
            "result_limit",
        },
        "_score_case": {
            "case",
            "result",
            "answer_status",
            "citation_hashes",
            "observation_hash_by_id",
            "lineage_crosswalk",
        },
        "_aggregate_arm": {"rows"},
        "_budget_fairness_report": {"rows_by_arm"},
        "_paired_transitions": {"baseline_rows", "candidate_rows"},
        "_quality_gate_report": {
            "arm_summaries",
            "paired_transitions",
            "budget_fairness",
        },
    }
    for helper_name in _DEVELOPMENT_HELPER_NAMES:
        helper = getattr(development_uat, helper_name, None)
        if not callable(helper):
            gaps.append(_OWNER_GAP_IDS[0])
            break
        if not helper_parameters[helper_name].issubset(inspect.signature(helper).parameters):
            gaps.append(_OWNER_GAP_IDS[0])
            break
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != holdout_policy.case_count:
        raise IndependentMailHoldoutUatError("holdout_case_count_mismatch")
    adapted_cases = (
        tuple(_adapt_holdout_case_for_development_helpers(case) for case in cases)
        if holdout_policy.policy_id == BASE_HOLDOUT_POLICY_ID
        else ()
    )
    if referenced_observation_type_counts.get("email_header", 0) > 0 and not callable(
        project_validated_holdout_observations
    ):
        gaps.append(_OWNER_GAP_IDS[0])
    if (
        any(case["score_adapter"] == "deterministic_exact" for case in adapted_cases)
        or holdout_policy.exact_case_count > 0
    ):
        exact_parameters = {
            "case",
            "expected_private",
            "exact_result",
            "observations_by_id",
            "observation_hash_by_id",
            "bundle",
        }
        if not exact_parameters.issubset(
            inspect.signature(score_deterministic_exact_holdout_case).parameters
        ):
            gaps.append(_OWNER_GAP_IDS[0])
    return tuple(dict.fromkeys(gaps))


def _adapt_holdout_case_for_development_helpers(
    case: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an oracle-free case projection for reusable owner helpers."""

    result_kind = str(case.get("result_kind"))
    result_kind_projection = {
        "owner_match": "owner_match",
        "source_evidence": "owner_match",
        "no_answer": "no_match",
        "permission_denied": "permission_denied",
        "exact_set": "exact_set",
        "exact_count": "exact_count",
        "exact_aggregation": "exact_aggregation",
    }
    projected_result_kind = result_kind_projection.get(result_kind)
    if projected_result_kind is None:
        raise IndependentMailHoldoutUatError("holdout_result_kind_invalid")
    required_fields = (
        "case_id",
        "domain",
        "intent_kind",
        "pattern",
        "query_text",
        "requester_user_id",
        "required_source_observation_ids",
        "forbidden_source_observation_ids",
        "required_match_count",
        "limit",
        "private_fingerprint",
    )
    if any(field_name not in case for field_name in required_fields):
        raise IndependentMailHoldoutUatError("holdout_case_shape_invalid")
    return {field_name: case[field_name] for field_name in required_fields} | {
        "result_kind": projected_result_kind,
        "holdout_result_kind": result_kind,
        "holdout_stratum_id": _case_stratum(case),
        "score_adapter": (
            "deterministic_exact" if result_kind.startswith("exact_") else "development_score_case"
        ),
    }


def _read_sealed_bytes(
    path: Path,
    expected_sha256: str,
    *,
    max_bytes: int,
    invalid_reason: str,
    seal_reason: str,
) -> bytes:
    """Read one sealed artifact without parsing or decoding its contents."""

    _require_sha256(expected_sha256, f"{invalid_reason}_seal_invalid")
    try:
        size = path.stat().st_size
        if size < 2 or size > max_bytes:
            raise IndependentMailHoldoutUatError(invalid_reason)
        payload = path.read_bytes()
    except IndependentMailHoldoutUatError:
        raise
    except OSError as exc:
        raise IndependentMailHoldoutUatError(invalid_reason) from exc
    if _sha256_bytes(payload) != expected_sha256:
        raise IndependentMailHoldoutUatError(seal_reason)
    return payload


def _read_sealed_json(
    path: Path,
    expected_sha256: str,
    *,
    max_bytes: int,
    invalid_reason: str,
    seal_reason: str,
) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = _read_sealed_bytes(
            path,
            expected_sha256,
            max_bytes=max_bytes,
            invalid_reason=invalid_reason,
            seal_reason=seal_reason,
        )
        value = json.loads(payload)
    except IndependentMailHoldoutUatError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndependentMailHoldoutUatError(invalid_reason) from exc
    if not isinstance(value, dict):
        raise IndependentMailHoldoutUatError(invalid_reason)
    return payload, value


def _string_list(value: Any, reason_code: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise IndependentMailHoldoutUatError(reason_code)
    if len(value) != len(set(value)):
        raise IndependentMailHoldoutUatError(reason_code)
    return tuple(value)


def _validate_public_report(report: Mapping[str, Any]) -> None:
    hashes = report.get("hashes")
    if not isinstance(hashes, Mapping):
        raise IndependentMailHoldoutUatError("public_report_hashes_invalid")
    if hashes.get("report_fingerprint") != _report_fingerprint(report):
        raise IndependentMailHoldoutUatError("public_report_fingerprint_drift")
    try:
        assert_no_public_raw_references(report, REPORT_ARTIFACT_ID)
    except ContractValidationError as exc:
        raise IndependentMailHoldoutUatError("public_report_private_leak") from exc
    serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
    forbidden = (
        "answer_oracle",
        "query_text",
        "requester_user_id",
        "observation_id",
        "message_id",
        "thread_id",
        "source_local_key",
        "manifest_path",
        "private.json",
    )
    if any(value in serialized for value in forbidden):
        raise IndependentMailHoldoutUatError("public_report_private_field_leak")


def _rejection_report(reason_code: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "artifact_id": REJECTION_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "preflight_status": "failed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "counts": {
            "sealed_quality_field_read_count": 0,
            "executed_case_count": 0,
            "blocker_count": 1,
        },
        "hashes": {
            "reason_fingerprint": sha256_json(reason_code),
        },
    }
    report["hashes"]["report_fingerprint"] = _report_fingerprint(report)
    assert_no_public_raw_references(report, REJECTION_ARTIFACT_ID)
    return report


def _report_fingerprint(report: Mapping[str, Any]) -> str:
    payload = dict(report)
    hashes = dict(payload.get("hashes", {}))
    hashes.pop("report_fingerprint", None)
    payload["hashes"] = hashes
    return sha256_json(payload)


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _require_sha256(value: Any, reason_code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise IndependentMailHoldoutUatError(reason_code)
    return value


__all__ = [
    "EXPECTED_CASE_COUNT",
    "EXPECTED_STRATA_COUNTS",
    "IndependentMailHoldoutUatError",
    "REPORT_ARTIFACT_ID",
    "build_independent_mail_holdout_preflight",
    "project_validated_holdout_observations",
    "run_holdout_case_arms",
    "score_deterministic_exact_holdout_case",
    "validate_execution_safety_metrics",
    "validate_shared_arm_fingerprints",
]


if __name__ == "__main__":
    raise SystemExit(main())
