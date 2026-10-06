#!/usr/bin/env python3
"""Run the Issue #56 100-case same-pipeline simulated-human UAT diagnostic."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
from typing import Any, Callable, Iterator, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    CandidateMention,
    ContractValidationError,
    Observation,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (  # noqa: E402
    DenseEmbeddingUnavailableError,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_mail import (  # noqa: E402
    EmailBodySegment,
    EmailMessage,
    MailEvidenceBundle,
    MailImportSession,
    MailParseRun,
    ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
    ISSUE56_TARGET_RUNTIME_METHOD_ID,
    SemanticPlanLimits,
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
    deterministic_query_class,
)
from formowl_mail.hybrid import (  # noqa: E402
    EvidenceIdentityLineageCrosswalk,
    build_evidence_identity_lineage_crosswalk,
)
from formowl_mail.candidates import (  # noqa: E402
    SourceBoundIdentifierMentionBatch,
    SourceIdentifierIdentityScope,
    TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
)
from formowl_graph.resolution import (  # noqa: E402
    resolve_exact_protected_identifier_candidates,
)
import formowl_mail.hybrid as hybrid_runtime  # noqa: E402
from formowl_mail.answer import (  # noqa: E402
    EvidenceAnswerBudget,
    ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID,
    ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT,
    ISSUE56_DETERMINISTIC_ANSWER_PROMPT_ID,
    render_governed_evidence_answer,
)
from scripts.issue56_operational_budget import (  # noqa: E402
    FROZEN_BUDGET_FINGERPRINT,
    FROZEN_CANONICAL_IMAGE_ID,
    FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    OperationalBudgetValidationError,
    ZERO_COST_GENERATION_MODE,
    deterministic_zero_cost_attestation_fingerprint,
    validate_persisted_bundle,
)
from scripts.issue56_execution_fingerprint import (  # noqa: E402
    ExecutionFingerprintValidationError,
    build_current_authority_component,
    build_current_code_component,
    build_image_component,
)
from scripts.issue56_source_identifier_candidates import (  # noqa: E402
    CANDIDATE_ARTIFACT_SCHEMA_VERSION as SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
    PRIVATE_ARTIFACT_ID as SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
    RESOLUTION_POLICY_FINGERPRINT as SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT,
    SourceIdentifierCandidateError,
    validate_private_identifier_candidate_artifact,
)

DEFAULT_WORK_DIR = ROOT / ".test-tmp" / "procurement-backup-may-domain-hard-work"
DEFAULT_BUNDLE_PATH = (
    ROOT / ".formowl-runtime-track1-0d552ef-20260813-r1" / "uat-state" / "may-bundle.private.json"
)
PRIVATE_MANIFEST_RELATIVE = Path("artifacts") / "domain_hard_case_manifest.private.json"
CASE_COUNT = 100
MAX_DECOY_SEGMENTS = 256
ARM_IDS = (
    "strong_rag",
    "rag_entity",
    "rag_candidate_kg",
    "hybrid_v2_soft",
    "legacy_hard_gate",
    "structured_exact",
)
FULL_CASE_ARM_IDS = ARM_IDS[:-1]
EVALUATOR_ID = "issue56_simulated_human_adjudication_v1"
CORPUS_POLICY_ID = "manifest_adjudicated_source_subset_plus_hash_decoys_v1"
PERMISSION_POLICY_ID = "mail_evidence_owner_or_governed_grant_v1"
GRAPH_ADAPTER_ID = "source_backed_mail_candidate_graph_v2"
SOURCE_GRAPH_POLICY_ID = "source_backed_mail_candidate_graph_v2"
SOURCE_IDENTIFIER_ADAPTER_ID = "source_bound_identifier_mentions_graph_adapter_v3"
ONTOLOGY_TARGET = "Artifact"
DIAGNOSTIC_RELATION_TYPES = ("co_occurs_with", "mentions_identifier")
DIAGNOSTIC_RELATION_DIRECTIONS = ("in", "out")
QUALITY_GATE_ID = "issue56_same_pipeline_diagnostic_quality_gate_v1"
EXECUTION_BUDGET_POLICY_ID = "issue56_same_pipeline_per_case_budget_v1"
DIRECT_REGRESSION_MAXIMUM_BASIS_POINTS = 200
GRAPH_REQUIRED_GAIN_MINIMUM_BASIS_POINTS = 1_000
CITATION_PRECISION_MINIMUM_BASIS_POINTS = 9_500
FROZEN_LATENCY_BUDGET_MS: float | None = None
FROZEN_COST_UNIT_BUDGET_PER_CASE: int | None = None
_SHA256_LENGTH = 71
NATIVE_MAIL_EVIDENCE_BUNDLE_ARTIFACT_ID = "formowl_issue56_native_mail_evidence_bundle_v1"
NATIVE_RETRIEVAL_READY_REPORT_ARTIFACT_ID = (
    "formowl_issue56_native_source_complete_retrieval_ready_report_v1"
)
OPERATIONAL_BUDGET_BINDING_ARTIFACT_ID = (
    "formowl_issue56_completed_uat_operational_budget_binding_v1"
)
OPERATIONAL_BUDGET_BINDING_REJECTION_ARTIFACT_ID = (
    "formowl_issue56_completed_uat_operational_budget_binding_rejection_v1"
)
PRIVATE_RELATION_TRACE_ARTIFACT_ID = "formowl_issue56_relation_phase_trace_private_v1"
SAFE_RELATION_TRACE_ARTIFACT_ID = "formowl_issue56_relation_phase_trace_safe_v1"
RELATION_TRACE_REASON_ENUMS = frozenset(
    (
        "answered",
        "exact_incomplete",
        "fallback_concept_coverage_missing",
        "fallback_identifier_coverage_missing",
        "fallback_no_connected_path",
        "fallback_repair_exhausted",
        "fallback_slot_unavailable",
        "graph_traversal_disabled",
        "insufficient_authorized_evidence",
        "permission_denied",
        "strict_relation_proof_unresolved",
        "unsupported_or_denied_path",
    )
)
FALLBACK_PATH_PROOF_REJECTION_ENUMS = frozenset(
    (
        "path_term_support_missing",
        "bound_candidate_term_support_missing",
        "support_only_on_connected_off_path_node",
        "additional_citation_exceeds_budget",
        "complete",
    )
)
RELATION_PATH_PROOF_REASON_ENUMS = frozenset(
    (
        "bound_candidate_term_support_missing",
        "evidence_budget_rejection",
        "off_path_support",
        "path_property_match",
    )
)
FALLBACK_PATH_PROOF_COUNT_FIELDS = (
    "path_node_count",
    "required_identifier_count",
    "required_concept_count",
    "on_path_node_property_term_match_count",
    "on_path_bound_candidate_term_support_count",
    "connected_off_path_support_count",
    "off_path_support_count",
    "base_citation_count",
    "minimal_additional_citation_count",
    "evidence_budget",
)
FALLBACK_PATH_PROOF_DIAGNOSTIC_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _NativeRetrievalReadyBundleIntake:
    bundle_payload: dict[str, Any]
    safe_binding: dict[str, Any]


@dataclass(frozen=True)
class _SourceIdentifierCandidateIntake:
    projected_batch: SourceBoundIdentifierMentionBatch
    safe_binding: dict[str, Any]


@dataclass(frozen=True)
class _RelationPathProofTraceIndex:
    node_by_id: Mapping[str, Any]
    node_by_hash: Mapping[str, Any]
    adjacent_node_ids_by_id: Mapping[str, frozenset[str]]
    candidate_slot_support_by_observation_hash: Mapping[
        str,
        frozenset[tuple[str, str]],
    ]
    node_property_slot_support_by_id: Mapping[
        str,
        frozenset[tuple[str, str]],
    ]
    node_bound_candidate_slot_support_by_id: Mapping[
        str,
        Mapping[str, frozenset[tuple[str, str]]],
    ]
    supporting_node_ids_by_slot: Mapping[tuple[str, str], frozenset[str]]
    authorized_observation_hashes: frozenset[str]


@dataclass
class _RelationPhaseProbe:
    invocation_counts: Counter[str] = field(default_factory=Counter)
    elapsed_ms: Counter[str] = field(default_factory=Counter)
    traversal_path_counts: list[int] = field(default_factory=list)
    strict_projection_citation_counts: list[int] = field(default_factory=list)
    fallback_evidence_budgets: list[int] = field(default_factory=list)

    def record(
        self,
        *,
        phase: str,
        elapsed_ms: float,
        result: Any,
    ) -> None:
        self.invocation_counts[phase] += 1
        self.elapsed_ms[phase] += elapsed_ms
        if phase == "graph_traversal" and isinstance(result, tuple) and result:
            self.traversal_path_counts.append(len(result[0]))
        elif phase == "strict_projection":
            self.strict_projection_citation_counts.append(len(tuple(result or ())))
        elif phase == "fallback_repair" and result is not None:
            self.fallback_evidence_budgets.append(int(result.plan.evidence_budget))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE_PATH)
    parser.add_argument(
        "--development-manifest",
        type=Path,
        help=(
            "Externally authored private development manifest. Requires its "
            "independently supplied SHA-256 seal and at least one positive "
            "graph-required owner case."
        ),
    )
    parser.add_argument(
        "--expected-development-manifest-sha256",
        help="Expected sha256:<hex> seal for --development-manifest.",
    )
    parser.add_argument(
        "--retrieval-ready-bundle-artifact",
        type=Path,
        help=(
            "Copernicus retrieval-ready native mail bundle artifact. Requires "
            "its independently supplied SHA-256 seal, the matching safe report, "
            "and that report's independently supplied seal."
        ),
    )
    parser.add_argument(
        "--expected-retrieval-ready-bundle-artifact-sha256",
        help="Expected sha256:<hex> byte seal for --retrieval-ready-bundle-artifact.",
    )
    parser.add_argument(
        "--retrieval-ready-report",
        type=Path,
        help="Safe Copernicus retrieval-ready report matching the bundle artifact.",
    )
    parser.add_argument(
        "--expected-retrieval-ready-report-sha256",
        help="Expected sha256:<hex> byte seal for --retrieval-ready-report.",
    )
    parser.add_argument(
        "--source-identifier-candidate-artifact",
        type=Path,
        help=(
            "Private source-authored identifier candidate artifact. Required "
            "for the explicit source-backed graph v2 development path."
        ),
    )
    parser.add_argument(
        "--expected-source-identifier-candidate-artifact-sha256",
        help=("Expected sha256:<hex> byte seal for " "--source-identifier-candidate-artifact."),
    )
    parser.add_argument(
        "--expected-identity-scope-fingerprint",
        help=(
            "Expected source-author identity-scope binding fingerprint for "
            "the identifier candidate artifact."
        ),
    )
    parser.add_argument(
        "--bind-completed-report",
        type=Path,
        help=(
            "Post-bind a completed safe UAT report to a separately validated "
            "operational-budget acceptance bundle without rerunning cases."
        ),
    )
    parser.add_argument(
        "--expected-completed-report-sha256",
        help="Expected sha256:<hex> byte seal for --bind-completed-report.",
    )
    parser.add_argument(
        "--operational-budget-bundle",
        type=Path,
        help="Persisted operational-budget acceptance bundle for the completed report.",
    )
    parser.add_argument(
        "--expected-operational-budget-bundle-sha256",
        help="Expected sha256:<hex> byte seal for --operational-budget-bundle.",
    )
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help=(
            "Return zero only for a completed diagnostic whose quality gate "
            "remains blocked; intake or execution blockers remain nonzero."
        ),
    )
    parser.add_argument(
        "--private-relation-trace-report",
        type=Path,
        help=(
            "Persist hash-only per-case/per-arm relation phase traces. Must be "
            "supplied with --safe-relation-trace-report."
        ),
    )
    parser.add_argument(
        "--safe-relation-trace-report",
        type=Path,
        help=(
            "Persist only aggregate relation reason counts and phase latency "
            "distributions. Must be supplied with --private-relation-trace-report."
        ),
    )
    parser.add_argument(
        "--diagnostic-case-manifest-entry-hash",
        "--diagnostic-case-hash",
        dest="diagnostic_case_hashes",
        action="append",
        default=[],
        help=(
            "Run only the sealed development-manifest entries matching this "
            "repeatable private SHA-256 fingerprint. Diagnostic trace only; "
            "requires --allow-blocked and both relation trace outputs."
        ),
    )
    parser.add_argument(
        "--canonical-image-id",
        default=os.environ.get("FORMOWL_CANONICAL_IMAGE_ID"),
    )
    parser.add_argument(
        "--canonical-image-metadata-fingerprint",
        default=os.environ.get("FORMOWL_CANONICAL_IMAGE_METADATA_FINGERPRINT"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    budget_binding_values = (
        args.bind_completed_report,
        args.expected_completed_report_sha256,
        args.operational_budget_bundle,
        args.expected_operational_budget_bundle_sha256,
    )
    budget_binding_mode = all(value is not None for value in budget_binding_values)
    diagnostic_case_hashes = tuple(args.diagnostic_case_hashes)
    if any(value is not None for value in budget_binding_values) and not budget_binding_mode:
        parser.error(
            "--bind-completed-report, --expected-completed-report-sha256, "
            "--operational-budget-bundle, and "
            "--expected-operational-budget-bundle-sha256 are required together"
        )
    if budget_binding_mode and any(
        value is not None
        for value in (
            args.development_manifest,
            args.expected_development_manifest_sha256,
            args.retrieval_ready_bundle_artifact,
            args.expected_retrieval_ready_bundle_artifact_sha256,
            args.retrieval_ready_report,
            args.expected_retrieval_ready_report_sha256,
            args.source_identifier_candidate_artifact,
            args.expected_source_identifier_candidate_artifact_sha256,
            args.expected_identity_scope_fingerprint,
            args.private_relation_trace_report,
            args.safe_relation_trace_report,
            *diagnostic_case_hashes,
        )
    ):
        parser.error("completed-report budget binding cannot execute UAT intake")
    if (args.private_relation_trace_report is None) != (args.safe_relation_trace_report is None):
        parser.error(
            "--private-relation-trace-report and "
            "--safe-relation-trace-report are required together"
        )
    if (args.development_manifest is None) != (args.expected_development_manifest_sha256 is None):
        parser.error(
            "--development-manifest and "
            "--expected-development-manifest-sha256 are required together"
        )
    retrieval_ready_values = (
        args.retrieval_ready_bundle_artifact,
        args.expected_retrieval_ready_bundle_artifact_sha256,
        args.retrieval_ready_report,
        args.expected_retrieval_ready_report_sha256,
    )
    if any(value is not None for value in retrieval_ready_values) and not all(
        value is not None for value in retrieval_ready_values
    ):
        parser.error(
            "--retrieval-ready-bundle-artifact, "
            "--expected-retrieval-ready-bundle-artifact-sha256, "
            "--retrieval-ready-report, and "
            "--expected-retrieval-ready-report-sha256 are required together"
        )
    source_identifier_values = (
        args.source_identifier_candidate_artifact,
        args.expected_source_identifier_candidate_artifact_sha256,
        args.expected_identity_scope_fingerprint,
    )
    if not budget_binding_mode and not all(value is not None for value in source_identifier_values):
        parser.error(
            "--source-identifier-candidate-artifact, "
            "--expected-source-identifier-candidate-artifact-sha256, and "
            "--expected-identity-scope-fingerprint are required together"
        )
    try:
        if budget_binding_mode:
            report = bind_completed_uat_operational_budget(
                completed_report_path=args.bind_completed_report,
                expected_completed_report_sha256=(args.expected_completed_report_sha256),
                operational_budget_bundle_path=args.operational_budget_bundle,
                expected_operational_budget_bundle_sha256=(
                    args.expected_operational_budget_bundle_sha256
                ),
            )
        else:
            report = run_simulated_uat(
                work_dir=args.work_dir,
                bundle_path=args.bundle,
                development_manifest_path=args.development_manifest,
                expected_development_manifest_sha256=(args.expected_development_manifest_sha256),
                retrieval_ready_bundle_artifact_path=(args.retrieval_ready_bundle_artifact),
                expected_retrieval_ready_bundle_artifact_sha256=(
                    args.expected_retrieval_ready_bundle_artifact_sha256
                ),
                retrieval_ready_report_path=args.retrieval_ready_report,
                expected_retrieval_ready_report_sha256=(
                    args.expected_retrieval_ready_report_sha256
                ),
                source_identifier_candidate_artifact_path=(
                    args.source_identifier_candidate_artifact
                ),
                expected_source_identifier_candidate_artifact_sha256=(
                    args.expected_source_identifier_candidate_artifact_sha256
                ),
                expected_identity_scope_fingerprint=(args.expected_identity_scope_fingerprint),
                canonical_image_id=args.canonical_image_id,
                canonical_image_metadata_fingerprint=(args.canonical_image_metadata_fingerprint),
                private_relation_trace_report_path=(args.private_relation_trace_report),
                safe_relation_trace_report_path=args.safe_relation_trace_report,
                diagnostic_case_hashes=diagnostic_case_hashes,
                allow_blocked=args.allow_blocked,
                enforce_diagnostic_subset_cli_contract=True,
            )
    except ContractValidationError as exc:
        report = (
            _safe_diagnostic_subset_rejection_report(str(exc))
            if diagnostic_case_hashes
            else _safe_binding_rejection_report(str(exc))
        )
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 3
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    if report["status"] == "passed" or (
        args.allow_blocked and report["execution_status"] == "passed"
    ):
        return 0
    return 2


def run_simulated_uat(
    *,
    work_dir: Path,
    bundle_path: Path,
    runtime_attestation: str = "pinned_real_e5_normal_path",
    development_manifest_path: Path | None = None,
    expected_development_manifest_sha256: str | None = None,
    retrieval_ready_bundle_artifact_path: Path | None = None,
    expected_retrieval_ready_bundle_artifact_sha256: str | None = None,
    retrieval_ready_report_path: Path | None = None,
    expected_retrieval_ready_report_sha256: str | None = None,
    source_identifier_candidate_artifact_path: Path | None = None,
    expected_source_identifier_candidate_artifact_sha256: str | None = None,
    expected_identity_scope_fingerprint: str | None = None,
    canonical_image_id: str | None = None,
    canonical_image_metadata_fingerprint: str | None = None,
    private_relation_trace_report_path: Path | None = None,
    safe_relation_trace_report_path: Path | None = None,
    diagnostic_case_hashes: Sequence[str] = (),
    diagnostic_case_manifest_entry_hashes: Sequence[str] = (),
    allow_blocked: bool = False,
    enforce_diagnostic_subset_cli_contract: bool = False,
) -> dict[str, Any]:
    """Run 100 private cases and return only aggregate safe evidence."""

    external_development_manifest = development_manifest_path is not None
    if external_development_manifest != (expected_development_manifest_sha256 is not None):
        raise ContractValidationError(
            "external development manifest path and seal are required together"
        )
    retrieval_ready_values = (
        retrieval_ready_bundle_artifact_path,
        expected_retrieval_ready_bundle_artifact_sha256,
        retrieval_ready_report_path,
        expected_retrieval_ready_report_sha256,
    )
    retrieval_ready_intake_supplied = all(value is not None for value in retrieval_ready_values)
    if any(value is not None for value in retrieval_ready_values) and not (
        retrieval_ready_intake_supplied
    ):
        raise ContractValidationError(
            "retrieval-ready bundle artifact, report, and seals are required together"
        )
    if external_development_manifest and not retrieval_ready_intake_supplied:
        raise ContractValidationError(
            "external development manifest requires retrieval-ready bundle binding"
        )
    source_identifier_values = (
        source_identifier_candidate_artifact_path,
        expected_source_identifier_candidate_artifact_sha256,
        expected_identity_scope_fingerprint,
    )
    if not all(value is not None for value in source_identifier_values):
        raise ContractValidationError(
            "source identifier candidate artifact, byte seal, and "
            "identity scope fingerprint are required"
        )
    trace_enabled = private_relation_trace_report_path is not None
    if trace_enabled != (safe_relation_trace_report_path is not None):
        raise ContractValidationError(
            "private and safe relation trace report paths are required together"
        )
    if diagnostic_case_hashes and diagnostic_case_manifest_entry_hashes:
        raise ContractValidationError(
            "diagnostic case selection cannot use both compatibility inputs"
        )
    selected_diagnostic_case_hashes = (
        diagnostic_case_hashes if diagnostic_case_hashes else diagnostic_case_manifest_entry_hashes
    )
    validated_diagnostic_case_hashes = _validated_diagnostic_case_manifest_entry_hashes(
        selected_diagnostic_case_hashes
    )
    diagnostic_subset_only = bool(validated_diagnostic_case_hashes)
    manifest_path = (
        development_manifest_path
        if development_manifest_path is not None
        else work_dir / PRIVATE_MANIFEST_RELATIVE
    )
    manifest_bytes = _read_private_bytes(
        manifest_path,
        blocker="private_manifest_unavailable",
    )
    manifest_byte_hash = _sha256_bytes(manifest_bytes)
    expected_seal_matches = not external_development_manifest
    if expected_development_manifest_sha256 is not None:
        _validate_external_manifest_seal(
            manifest_byte_hash,
            expected_development_manifest_sha256,
        )
        expected_seal_matches = True
    manifest = _read_json_object(
        manifest_bytes,
        blocker="private_manifest_invalid",
    )
    full_manifest_cases = _validated_cases(manifest)
    positive_graph_required_owner_case_count = _positive_graph_required_owner_case_count(
        full_manifest_cases
    )
    cases = (
        _diagnostic_subset_cases(
            full_manifest_cases,
            selected_hashes=validated_diagnostic_case_hashes,
        )
        if diagnostic_subset_only
        else full_manifest_cases
    )
    if (
        diagnostic_subset_only
        and enforce_diagnostic_subset_cli_contract
        and (not trace_enabled or not allow_blocked or not _is_development_manifest(manifest))
    ):
        raise ContractValidationError(
            "diagnostic subset CLI requires a development manifest, "
            "both relation trace outputs, and allow-blocked"
        )
    retrieval_ready_intake: _NativeRetrievalReadyBundleIntake | None = None
    if retrieval_ready_intake_supplied:
        retrieval_ready_intake = _load_native_retrieval_ready_bundle_intake(
            bundle_artifact_path=retrieval_ready_bundle_artifact_path,
            expected_bundle_artifact_sha256=(expected_retrieval_ready_bundle_artifact_sha256),
            report_path=retrieval_ready_report_path,
            expected_report_sha256=expected_retrieval_ready_report_sha256,
        )
        bundle_payload = retrieval_ready_intake.bundle_payload
        bundle_byte_hash = str(retrieval_ready_intake.safe_binding["bundle_artifact_byte_hash"])
    else:
        bundle_bytes = _read_private_bytes(
            bundle_path,
            blocker="preserved_bundle_unavailable",
        )
        bundle_byte_hash = _sha256_bytes(bundle_bytes)
        bundle_payload = _read_json_object(
            bundle_bytes,
            blocker="preserved_bundle_invalid",
        )
    bundle, observations = _bounded_preserved_projection(
        bundle_payload=bundle_payload,
        manifest=manifest,
        manifest_byte_hash=manifest_byte_hash,
        observations_directory=work_dir / "data" / "ingestion" / "observations",
    )
    selected_observations = tuple(observations[bundle.mail_evidence_bundle_id])
    source_observation_hashes = sorted(observations.source_observation_hash_by_id.values())
    source_observation_hash_set_fingerprint = sha256_json(source_observation_hashes)
    selected_projection_fingerprint = sha256_json(
        {
            "manifest_byte_hash": manifest_byte_hash,
            "bundle_byte_hash": bundle_byte_hash,
            "source_observation_hash_set_fingerprint": (source_observation_hash_set_fingerprint),
            "source_observation_count": len(source_observation_hashes),
            "corpus_policy_fingerprint": sha256_json(CORPUS_POLICY_ID),
        }
    )
    source_identifier_intake = _load_source_identifier_candidate_intake(
        artifact_path=source_identifier_candidate_artifact_path,
        expected_artifact_sha256=(expected_source_identifier_candidate_artifact_sha256),
        expected_identity_scope_fingerprint=(expected_identity_scope_fingerprint),
        expected_workspace_id=bundle.mail_import_session.workspace_id,
        selected_observations_by_id={
            observation.observation_id: observation for observation in selected_observations
        },
        selected_observation_hash_by_id=(observations.source_observation_hash_by_id),
        retrieval_ready_binding=(
            retrieval_ready_intake.safe_binding if retrieval_ready_intake is not None else None
        ),
    )
    source_snapshot_fingerprint = str(
        (
            retrieval_ready_intake.safe_binding
            if retrieval_ready_intake is not None
            else source_identifier_intake.safe_binding
        )["source_snapshot_fingerprint"]
    )
    identity_matches = _manifest_bundle_identity_matches(
        manifest,
        bundle_payload,
    )
    base = _base_report(
        manifest_byte_hash=manifest_byte_hash,
        bundle_byte_hash=bundle_byte_hash,
        case_count=len(cases),
        identity_matches=identity_matches,
        selected_observation_count=observations.selected_observation_count,
        runtime_attestation=runtime_attestation,
        manifest_intake_mode=(
            "external_hash_pinned" if external_development_manifest else "default_bound_manifest"
        ),
        expected_seal_matches=expected_seal_matches,
        positive_graph_required_owner_case_count=(positive_graph_required_owner_case_count),
        source_snapshot_fingerprint=source_snapshot_fingerprint,
        source_observation_hash_set_fingerprint=(source_observation_hash_set_fingerprint),
        selected_projection_fingerprint=selected_projection_fingerprint,
        retrieval_ready_binding=(
            retrieval_ready_intake.safe_binding if retrieval_ready_intake is not None else None
        ),
        source_identifier_candidate_binding=(source_identifier_intake.safe_binding),
        canonical_image_id=canonical_image_id,
        canonical_image_metadata_fingerprint=canonical_image_metadata_fingerprint,
    )
    if not identity_matches:
        return _blocked_report(
            base,
            blocker="manifest_bundle_identity_mismatch",
            manifest_path=manifest_path,
            manifest_byte_hash=manifest_byte_hash,
        )
    if external_development_manifest and positive_graph_required_owner_case_count == 0:
        return _blocked_report(
            base,
            blocker="positive_graph_required_development_cases_required",
            manifest_path=manifest_path,
            manifest_byte_hash=manifest_byte_hash,
        )

    owner_user_id = bundle.mail_import_session.owner_user_id
    requesters = sorted(
        {str(case["requester_user_id"]) for case in cases},
        key=lambda value: (value != owner_user_id, sha256_json(value)),
    )
    sessions = {}
    views = {}
    graph_builds = {}
    lineage_crosswalks = {}
    relation_path_proof_trace_indexes = {}
    try:
        for requester_user_id in requesters:
            sessions[requester_user_id] = build_authorized_semantic_mail_session(
                observations_by_bundle_id=observations,
                bundles=(bundle,),
                requester_user_id=requester_user_id,
                workspace_id=bundle.mail_import_session.workspace_id,
                mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            )
            graph_builds[requester_user_id] = build_authorized_source_backed_effective_graph_view(
                session=sessions[requester_user_id],
                observations_by_bundle_id=observations,
                source_binding_fingerprint=base["source"]["source_binding_fingerprint"],
                source_graph_policy_id=SOURCE_GRAPH_POLICY_ID,
                identifier_mention_batch=source_identifier_intake.projected_batch,
            )
            views[requester_user_id] = graph_builds[requester_user_id].effective_graph_view
            lineage_crosswalks[requester_user_id] = build_evidence_identity_lineage_crosswalk(
                session=sessions[requester_user_id],
                effective_graph_view=views[requester_user_id],
            )
            if trace_enabled:
                relation_path_proof_trace_indexes[requester_user_id] = (
                    _build_relation_path_proof_trace_index(
                        effective_graph_view=views[requester_user_id],
                        authorized_observation_hash_by_id=dict(
                            sessions[requester_user_id].authorized_observation_hashes
                        ),
                        candidates_by_hash={
                            candidate.source_observation_hash: candidate
                            for candidate in sessions[requester_user_id].index.candidates
                        },
                    )
                )
    except DenseEmbeddingUnavailableError as exc:
        return _blocked_report(
            base,
            blocker=exc.reason_code,
            manifest_path=manifest_path,
            manifest_byte_hash=manifest_byte_hash,
        )

    budget = EvidenceAnswerBudget()
    rows_by_arm: dict[str, list[dict[str, Any]]] = {arm_id: [] for arm_id in ARM_IDS}
    private_relation_trace_rows: list[dict[str, Any]] = []
    execution_bindings: set[str] = set()
    index_fingerprints: set[str] = set()
    peak_memory_before_kib = _peak_memory_kib()
    for case in cases:
        requester_user_id = str(case["requester_user_id"])
        session = sessions[requester_user_id]
        view = views[requester_user_id]
        query_text = str(case["query_text"])
        relation_phase_probes: dict[str, _RelationPhaseProbe] | None = {} if trace_enabled else None
        arm_results = _run_case_arms(
            session=session,
            effective_graph_view=view,
            query_text=query_text,
            result_limit=int(case["limit"]),
            relation_phase_probes=relation_phase_probes,
        )
        execution_bindings.add(session.index.execution_component_fingerprint)
        index_fingerprints.add(session.index.index_fingerprint)
        for (
            arm_id,
            result,
            elapsed_ms,
            cpu_ms,
            execution_budget_fingerprint,
        ) in arm_results:
            answer_started = time.perf_counter()
            answer = render_governed_evidence_answer(result, budget=budget)
            answer_elapsed_ms = (time.perf_counter() - answer_started) * 1_000
            scored_row = _score_case(
                case,
                result=result,
                answer_status=answer.status,
                citation_hashes=answer.citation_hashes,
                exact_count=answer.exact_count,
                answer_hash=answer.answer_hash,
                source_result_fingerprint=(answer.source_result_fingerprint),
                cost_units=answer.cost_units,
                elapsed_ms=elapsed_ms,
                cpu_ms=cpu_ms,
                execution_budget_fingerprint=(execution_budget_fingerprint),
                observation_hash_by_id=(observations.source_observation_hash_by_id),
                lineage_crosswalk=lineage_crosswalks[requester_user_id],
            )
            rows_by_arm[arm_id].append(scored_row)
            if relation_phase_probes is not None:
                private_relation_trace_rows.append(
                    _build_private_relation_phase_trace(
                        arm_id=arm_id,
                        hashed_case_id=str(scored_row["case_manifest_entry_hash"]),
                        query_text=query_text,
                        result=result,
                        answer_status=answer.status,
                        session=session,
                        effective_graph_view=view,
                        probe=relation_phase_probes[arm_id],
                        arm_elapsed_ms=elapsed_ms,
                        answer_projection_elapsed_ms=answer_elapsed_ms,
                        evidence_budget=(_frozen_per_case_limits(int(case["limit"])).max_evidence),
                        path_proof_trace_index=(
                            relation_path_proof_trace_indexes[requester_user_id]
                        ),
                    )
                )

    manifest_unchanged = (
        _sha256_bytes(
            _read_private_bytes(
                manifest_path,
                blocker="private_manifest_unavailable",
            )
        )
        == manifest_byte_hash
    )
    arm_summaries = {arm_id: _aggregate_arm(rows_by_arm[arm_id]) for arm_id in ARM_IDS}
    budget_fairness = _budget_fairness_report(rows_by_arm)
    paired_transitions = {
        "rag_entity_vs_strong_rag": _paired_transitions(
            rows_by_arm["strong_rag"],
            rows_by_arm["rag_entity"],
        ),
        "rag_candidate_kg_vs_rag_entity": _paired_transitions(
            rows_by_arm["rag_entity"],
            rows_by_arm["rag_candidate_kg"],
        ),
        "hybrid_v2_soft_vs_strong_rag": _paired_transitions(
            rows_by_arm["strong_rag"],
            rows_by_arm["hybrid_v2_soft"],
        ),
        "hybrid_v2_soft_vs_rag_candidate_kg": _paired_transitions(
            rows_by_arm["rag_candidate_kg"],
            rows_by_arm["hybrid_v2_soft"],
        ),
        "legacy_hard_gate_vs_hybrid_v2_soft": _paired_transitions(
            rows_by_arm["hybrid_v2_soft"],
            rows_by_arm["legacy_hard_gate"],
        ),
        "hybrid_v2_soft_vs_strong_rag_direct_cases": _paired_transitions(
            _rows_for_query_class(
                rows_by_arm["strong_rag"],
                "evidence_lookup",
            ),
            _rows_for_query_class(
                rows_by_arm["hybrid_v2_soft"],
                "evidence_lookup",
            ),
        ),
        "hybrid_v2_soft_vs_strong_rag_graph_required": _paired_transitions(
            _rows_for_positive_graph_required(
                rows_by_arm["strong_rag"],
            ),
            _rows_for_positive_graph_required(
                rows_by_arm["hybrid_v2_soft"],
            ),
        ),
    }
    structured_rows = rows_by_arm["structured_exact"]
    if structured_rows:
        strong_exact_rows = [
            row
            for row in rows_by_arm["strong_rag"]
            if row["query_class"] == "exact_set_or_inventory"
        ]
        paired_transitions["structured_exact_vs_strong_rag_exact_cases"] = _paired_transitions(
            strong_exact_rows, structured_rows
        )
    graph_build_summary = _aggregate_graph_builds(
        graph_builds,
        source_identifier_binding=source_identifier_intake.safe_binding,
    )
    private_run_fingerprint = sha256_json(
        {
            "manifest_byte_hash": manifest_byte_hash,
            "bundle_byte_hash": bundle_byte_hash,
            "source_binding_fingerprint": base["source"]["source_binding_fingerprint"],
            "source_identifier_candidate_binding_fingerprint": (
                source_identifier_intake.safe_binding["binding_fingerprint"]
            ),
            "graph_build_summary_fingerprint": sha256_json(graph_build_summary),
            "arm_rows": {
                arm_id: [
                    {
                        "case_manifest_entry_hash": row["case_manifest_entry_hash"],
                        "status": row["status"],
                        "answer_hash": row["answer_hash"],
                        "source_result_fingerprint": row["source_result_fingerprint"],
                    }
                    for row in rows
                ]
                for arm_id, rows in rows_by_arm.items()
            },
        }
    )
    quality_gate = _quality_gate_report(
        arm_summaries=arm_summaries,
        paired_transitions=paired_transitions,
        budget_fairness=budget_fairness,
    )
    diagnostic_subset: dict[str, Any] | None = None
    if diagnostic_subset_only:
        diagnostic_subset = {
            "status": "diagnostic_only",
            "selection_basis": "exact_private_manifest_entry_hash",
            "manifest_case_count": len(full_manifest_cases),
            "selected_case_count": len(cases),
            "selected_case_hash_count": len(validated_diagnostic_case_hashes),
            "selected_case_hash_set_fingerprint": sha256_json(
                sorted(validated_diagnostic_case_hashes)
            ),
            "quality_claim_eligible": False,
            "operational_budget_binding_eligible": False,
            "completion_binding_eligible": False,
        }
        diagnostic_subset_checks = {
            key: dict(value)
            for key, value in quality_gate.get("checks", {}).items()
            if isinstance(value, Mapping)
        }
        diagnostic_subset_checks["diagnostic_subset_eligibility"] = {
            "status": "blocked",
            "reason_hash": sha256_json("diagnostic_subset_not_quality_eligible"),
            "quality_eligible": False,
            "budget_eligible": False,
            "completion_binding_eligible": False,
        }
        quality_gate = {
            **quality_gate,
            "status": "blocked",
            "checks": diagnostic_subset_checks,
            "check_set_fingerprint": sha256_json(diagnostic_subset_checks),
            "reason_hash": sha256_json("diagnostic_subset_not_quality_eligible"),
        }
    quality_gate_status = str(quality_gate["status"])
    overall_status = {
        "passed": "passed",
        "failed": "quality_failed",
        "blocked": "blocked",
    }[quality_gate_status]
    if len(execution_bindings) != 1:
        raise ContractValidationError("same-pipeline execution component binding is not unique")
    execution_component_fingerprint = next(iter(execution_bindings))
    report = {
        **base,
        "status": overall_status,
        "execution_status": "passed",
        "quality_gate_status": quality_gate_status,
        "diagnostic_subset_only": diagnostic_subset_only,
        **({"diagnostic_subset": diagnostic_subset} if diagnostic_subset is not None else {}),
        "e2e_executed": True,
        "path_executed": [
            "preserved_source_observation",
            *(
                ["sealed_native_retrieval_ready_bundle_intake"]
                if retrieval_ready_intake is not None
                else []
            ),
            "sealed_source_identifier_candidate_intake",
            "permission_before_candidate_materialization",
            "explicit_source_backed_candidate_graph_v2",
            "frozen_same_profile_index",
            "bm25_plus_pinned_dense_retrieval",
            "typed_semantic_execution",
            "hash_only_evidence_identity_lineage",
            "shared_governed_answer_renderer",
            "private_adjudication",
            "safe_aggregate_report",
        ],
        "manifest_seal": {
            **base["manifest_seal"],
            "unchanged_after_execution": manifest_unchanged,
        },
        "source": {
            **base["source"],
            "loaded_observation_count": observations.loaded_observation_count,
            "source_observation_hash_count": len(observations.source_observation_hash_by_id),
            "source_observation_hash_set_fingerprint": (
                base["source"]["source_observation_hash_set_fingerprint"]
            ),
            "source_snapshot_fingerprint": base["source"]["source_snapshot_fingerprint"],
            "source_identifier_candidate_binding": base["source"][
                "source_identifier_candidate_binding"
            ],
            "raw_pst_reparsed": False,
            "source_complete": False,
        },
        "shared_pipeline": {
            **base["shared_pipeline"],
            "execution_component_fingerprint": execution_component_fingerprint,
            "execution_component_fingerprint_count": len(execution_bindings),
            "execution_component_fingerprint_set_hash": sha256_json(sorted(execution_bindings)),
            "permission_scoped_index_count": len(index_fingerprints),
            "permission_scoped_index_set_fingerprint": sha256_json(sorted(index_fingerprints)),
            "all_arms_share_answer_model_prompt_budget_evaluator": True,
            "execution_budget_fairness": budget_fairness,
            "graph_signal_active": any(
                summary["graph_signal_active_case_count"] > 0
                for arm_id, summary in arm_summaries.items()
                if arm_id != "strong_rag"
            ),
            "ontology_signal_active": (
                arm_summaries["hybrid_v2_soft"]["ontology_signal_active_case_count"] > 0
            ),
            "graph_builds": graph_build_summary,
            "evidence_identity_lineage": _aggregate_lineage_crosswalks(lineage_crosswalks),
        },
        "arms": arm_summaries,
        "paired_transitions": paired_transitions,
        "quality_gate": quality_gate,
        "resource_measurement": {
            "cpu_measurement": "process_time_per_arm_case",
            "peak_memory_kib": _peak_memory_kib(),
            "peak_memory_delta_lower_bound_kib": max(
                0,
                _peak_memory_kib() - peak_memory_before_kib,
            ),
            "model_usage_cost": (
                _public_safe_zero_cost_measurement()
                if diagnostic_subset_only
                else _deterministic_zero_cost_measurement()
            ),
        },
        "diagnostic_run_fingerprint": private_run_fingerprint,
        "execution_environment": base["execution_environment"],
        "claim_boundary": {
            **base["claim_boundary"],
            "supports_same_pipeline_diagnostic_claim": (
                not diagnostic_subset_only
                and manifest_unchanged
                and all(
                    arm_summaries[arm_id]["scored_case_count"] == CASE_COUNT
                    for arm_id in FULL_CASE_ARM_IDS
                )
                and arm_summaries["structured_exact"]["scored_case_count"]
                == sum(
                    deterministic_query_class(str(case["query_text"])) == "exact_set_or_inventory"
                    for case in cases
                )
            ),
        },
    }
    if trace_enabled:
        trace_summary = _safe_relation_trace_summary(private_relation_trace_rows)
        report["relation_phase_trace"] = {
            "status": "diagnostic",
            "private_case_arm_trace_count": len(private_relation_trace_rows),
            "behavior_fingerprint": _relation_trace_behavior_fingerprint(
                private_relation_trace_rows
            ),
            "safe_summary_fingerprint": trace_summary["summary_fingerprint"],
            "safe_projection": trace_summary,
        }
        report["path_executed"].append("hash_only_private_relation_phase_trace")
    _assert_safe_simulated_uat_report(report)
    if trace_enabled:
        _persist_relation_trace_reports(
            report=report,
            private_trace_rows=private_relation_trace_rows,
            private_report_path=private_relation_trace_report_path,
            safe_report_path=safe_relation_trace_report_path,
        )
    return report


def bind_completed_uat_operational_budget(
    *,
    completed_report_path: Path,
    expected_completed_report_sha256: str,
    operational_budget_bundle_path: Path,
    expected_operational_budget_bundle_sha256: str,
) -> dict[str, Any]:
    """Bind one passed operational acceptance artifact to its exact UAT run.

    This is a projection-only operation.  It does not rerun cases or replace
    any quality metric.  The persisted budget artifact must bind the exact
    completed report bytes, canonical report content, and diagnostic run
    fingerprint before only the operational-budget check can become passed.
    """

    completed_bytes = _read_private_bytes(
        completed_report_path,
        blocker="completed_uat_report_unavailable",
    )
    completed_byte_hash = _sha256_bytes(completed_bytes)
    _validate_expected_byte_seal(
        actual_sha256=completed_byte_hash,
        expected_sha256=expected_completed_report_sha256,
        label="completed UAT report",
    )
    completed_report = _read_json_object(
        completed_bytes,
        blocker="completed_uat_report_invalid",
    )

    budget_bytes = _read_private_bytes(
        operational_budget_bundle_path,
        blocker="operational_budget_bundle_unavailable",
    )
    budget_byte_hash = _sha256_bytes(budget_bytes)
    _validate_expected_byte_seal(
        actual_sha256=budget_byte_hash,
        expected_sha256=expected_operational_budget_bundle_sha256,
        label="operational budget bundle",
    )
    budget_bundle = _read_json_object(
        budget_bytes,
        blocker="operational_budget_bundle_invalid",
    )
    try:
        validated_budget = validate_persisted_bundle(operational_budget_bundle_path)
    except OperationalBudgetValidationError as exc:
        raise ContractValidationError(exc.reason_code) from exc

    component_binding = _validated_completed_uat_component_binding(completed_report)
    completed_content_fingerprint = _operational_budget_content_fingerprint(completed_report)
    diagnostic_run_fingerprint = _require_sha256_fingerprint(
        completed_report.get("diagnostic_run_fingerprint"),
        "completed UAT diagnostic run fingerprint",
    )
    if validated_budget.get("status") != "passed" or budget_bundle.get("status") != "passed":
        raise ContractValidationError("operational budget acceptance is not passed")
    if budget_bundle.get("budget_fingerprint") != FROZEN_BUDGET_FINGERPRINT:
        raise ContractValidationError("operational budget fingerprint mismatch")
    expected_budget_bindings = {
        "uat_report_fingerprint": completed_byte_hash,
        "uat_content_fingerprint": completed_content_fingerprint,
        "uat_run_fingerprint": diagnostic_run_fingerprint,
    }
    if any(
        budget_bundle.get(field_name) != expected_value
        for field_name, expected_value in expected_budget_bindings.items()
    ):
        raise ContractValidationError("operational budget UAT binding mismatch")
    if budget_bundle.get("bundle_fingerprint") != validated_budget.get("bundle_fingerprint"):
        raise ContractValidationError("operational budget validation projection mismatch")

    quality_gate = completed_report.get("quality_gate")
    if not isinstance(quality_gate, Mapping):
        raise ContractValidationError("completed UAT quality gate is invalid")
    original_checks = quality_gate.get("checks")
    if not isinstance(original_checks, Mapping):
        raise ContractValidationError("completed UAT quality checks are invalid")
    original_operational = original_checks.get("operational_budget")
    if (
        not isinstance(original_operational, Mapping)
        or original_operational.get("status") != "blocked"
    ):
        raise ContractValidationError("completed UAT operational check is not bindable")

    binding = {
        "artifact_id": OPERATIONAL_BUDGET_BINDING_ARTIFACT_ID,
        "schema_version": 1,
        "status": "passed",
        "completed_report_byte_hash": completed_byte_hash,
        "completed_report_content_fingerprint": completed_content_fingerprint,
        "diagnostic_run_fingerprint": diagnostic_run_fingerprint,
        "budget_bundle_byte_hash": budget_byte_hash,
        "budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
        "budget_bundle_fingerprint": budget_bundle["bundle_fingerprint"],
        "budget_check_set_fingerprint": budget_bundle["check_set_fingerprint"],
        "component_binding_fingerprint": component_binding["component_binding_fingerprint"],
        "source_binding_fingerprint": component_binding["source_binding_fingerprint"],
        "image_id": component_binding["image_id"],
        "image_metadata_fingerprint": component_binding["image_metadata_fingerprint"],
        "projection_only": True,
    }
    binding["binding_fingerprint"] = sha256_json(binding)

    updated_checks = {key: dict(value) for key, value in original_checks.items()}
    updated_checks["operational_budget"] = {
        "status": "passed",
        "budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
        "budget_bundle_fingerprint": budget_bundle["bundle_fingerprint"],
        "budget_check_set_fingerprint": budget_bundle["check_set_fingerprint"],
        "completed_report_byte_hash": completed_byte_hash,
        "binding_fingerprint": binding["binding_fingerprint"],
    }
    prerequisite_status = (
        "passed"
        if (
            component_binding["source_completeness_gate_status"] == "passed"
            and component_binding["real_source_ablation_gate_status"] == "passed"
        )
        else "blocked"
    )
    updated_checks["source_authority_prerequisites"] = {
        "status": prerequisite_status,
        "source_completeness_gate_status": (component_binding["source_completeness_gate_status"]),
        "real_source_ablation_gate_status": (component_binding["real_source_ablation_gate_status"]),
        "authority_execution_fingerprint": (component_binding["authority_execution_fingerprint"]),
        "reason_hash": (
            None
            if prerequisite_status == "passed"
            else sha256_json("source_authority_prerequisites_not_passed")
        ),
    }
    updated_status = _quality_status_from_checks(updated_checks)
    updated_quality_gate = {
        **quality_gate,
        "status": updated_status,
        "checks": updated_checks,
        "check_set_fingerprint": sha256_json(updated_checks),
        "operational_budget_binding_fingerprint": binding["binding_fingerprint"],
    }
    updated_report = {
        **completed_report,
        "status": {
            "passed": "passed",
            "failed": "quality_failed",
            "blocked": "blocked",
        }[updated_status],
        "quality_gate_status": updated_status,
        "quality_gate": updated_quality_gate,
        "operational_budget_binding": binding,
        "path_executed": list(
            dict.fromkeys(
                (
                    *completed_report.get("path_executed", ()),
                    "sealed_operational_budget_post_binding",
                )
            )
        ),
    }
    _assert_safe_simulated_uat_report(updated_report)
    return updated_report


def _validated_completed_uat_component_binding(
    report: Mapping[str, Any],
) -> dict[str, str]:
    if report.get("diagnostic_subset_only") is True or isinstance(
        report.get("diagnostic_subset"),
        Mapping,
    ):
        raise ContractValidationError(
            "diagnostic subset report is not eligible for completion or budget binding"
        )
    if report.get("artifact_id") != "formowl_issue56_simulated_human_uat_v1":
        raise ContractValidationError("completed UAT artifact is invalid")
    if report.get("schema_version") != 1:
        raise ContractValidationError("completed UAT schema is invalid")
    if report.get("execution_status") != "passed" or report.get("e2e_executed") is not True:
        raise ContractValidationError("completed UAT execution is not passed")

    manifest_seal = report.get("manifest_seal")
    if not isinstance(manifest_seal, Mapping) or any(
        manifest_seal.get(field_name) is not True
        for field_name in (
            "sealed_before_execution",
            "unchanged_after_execution",
            "expected_seal_matches",
        )
    ):
        raise ContractValidationError("completed UAT manifest seal is invalid")

    source = report.get("source")
    shared = report.get("shared_pipeline")
    environment = report.get("execution_environment")
    claim_boundary = report.get("claim_boundary")
    if not all(
        isinstance(value, Mapping) for value in (source, shared, environment, claim_boundary)
    ):
        raise ContractValidationError("completed UAT binding components are invalid")
    assert isinstance(source, Mapping)
    assert isinstance(shared, Mapping)
    assert isinstance(environment, Mapping)
    assert isinstance(claim_boundary, Mapping)
    if source.get("manifest_bundle_identity_matches") is not True:
        raise ContractValidationError("completed UAT source identity is invalid")
    retrieval_binding = source.get("retrieval_ready_binding")
    if (
        not isinstance(retrieval_binding, Mapping)
        or retrieval_binding.get("status") != "sealed_passed"
    ):
        raise ContractValidationError("completed UAT retrieval binding is invalid")
    graph_builds = shared.get("graph_builds")
    if not isinstance(graph_builds, Mapping):
        raise ContractValidationError("completed UAT graph binding is invalid")

    source_binding_fingerprint = _require_sha256_fingerprint(
        source.get("source_binding_fingerprint"),
        "completed UAT source binding fingerprint",
    )
    source_snapshot_fingerprint = _require_sha256_fingerprint(
        source.get("source_snapshot_fingerprint"),
        "completed UAT source snapshot fingerprint",
    )
    if retrieval_binding.get("source_snapshot_fingerprint") != source_snapshot_fingerprint:
        raise ContractValidationError("completed UAT source snapshot binding mismatch")
    if environment.get("attestation_run_binding_fingerprint") != source_binding_fingerprint:
        raise ContractValidationError("completed UAT attestation run binding mismatch")
    if (
        environment.get("image_id") != FROZEN_CANONICAL_IMAGE_ID
        or environment.get("image_metadata_fingerprint")
        != FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT
    ):
        raise ContractValidationError("completed UAT image binding mismatch")

    required_false_claims = (
        "independent_holdout",
        "methodology_ready",
        "methodology_complete",
        "issue56_complete",
        "production_ready",
        "supports_arm_superiority_claim",
    )
    if any(claim_boundary.get(field_name) is not False for field_name in required_false_claims):
        raise ContractValidationError("completed UAT claim boundary is invalid")

    component_fields = {
        "source_binding_fingerprint": source_binding_fingerprint,
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "selected_projection_fingerprint": source.get("selected_projection_fingerprint"),
        "source_observation_hash_set_fingerprint": (
            source.get("source_observation_hash_set_fingerprint")
        ),
        "retrieval_input_binding_fingerprint": (retrieval_binding.get("input_binding_fingerprint")),
        "retrieval_bundle_artifact_fingerprint": (
            retrieval_binding.get("bundle_artifact_fingerprint")
        ),
        "retrieval_report_fingerprint": (retrieval_binding.get("retrieval_report_fingerprint")),
        "index_fingerprint": retrieval_binding.get("index_fingerprint"),
        "candidate_admission_profile_fingerprint": (
            retrieval_binding.get("candidate_admission_profile_fingerprint")
        ),
        "permission_fingerprint": retrieval_binding.get("permission_fingerprint"),
        "lexical_profile_fingerprint": shared.get("lexical_profile_fingerprint"),
        "query_lexical_profile_fingerprint": (shared.get("query_lexical_profile_fingerprint")),
        "evidence_lexical_profile_fingerprint": (
            shared.get("evidence_lexical_profile_fingerprint")
        ),
        "dense_profile_fingerprint": shared.get("dense_profile_fingerprint"),
        "execution_component_fingerprint": (shared.get("execution_component_fingerprint")),
        "permission_policy_fingerprint": shared.get("permission_policy_fingerprint"),
        "permission_scoped_index_set_fingerprint": (
            shared.get("permission_scoped_index_set_fingerprint")
        ),
        "graph_adapter_fingerprint": shared.get("graph_adapter_fingerprint"),
        "graph_build_fingerprint_set_hash": (graph_builds.get("build_fingerprint_set_hash")),
        "ontology_target_fingerprint": shared.get("ontology_target_fingerprint"),
        "ontology_revision_fingerprint_set_hash": (
            graph_builds.get("ontology_revision_fingerprint_set_hash")
        ),
        "runtime_method_fingerprint": shared.get("runtime_method_fingerprint"),
        "answer_model_fingerprint": shared.get("answer_model_fingerprint"),
        "answer_prompt_fingerprint": shared.get("answer_prompt_fingerprint"),
        "answer_budget_fingerprint": shared.get("answer_budget_fingerprint"),
        "evaluator_fingerprint": shared.get("evaluator_fingerprint"),
        "code_attestation_fingerprint": environment.get("code_attestation_fingerprint"),
        "code_tree_fingerprint": environment.get("code_tree_fingerprint"),
        "image_attestation_fingerprint": environment.get("image_attestation_fingerprint"),
        "image_id": environment.get("image_id"),
        "image_metadata_fingerprint": environment.get("image_metadata_fingerprint"),
        "authority_attestation_fingerprint": (environment.get("authority_attestation_fingerprint")),
        "authority_execution_fingerprint": (environment.get("authority_execution_fingerprint")),
    }
    for field_name, value in component_fields.items():
        _require_sha256_fingerprint(value, f"completed UAT {field_name}")
    if (
        component_fields["lexical_profile_fingerprint"]
        != component_fields["query_lexical_profile_fingerprint"]
        or component_fields["lexical_profile_fingerprint"]
        != component_fields["evidence_lexical_profile_fingerprint"]
        or component_fields["lexical_profile_fingerprint"]
        != component_fields["candidate_admission_profile_fingerprint"]
    ):
        raise ContractValidationError("completed UAT tokenizer binding mismatch")
    lexical_profile = load_issue56_target_mail_tokenizer_profile()
    dense_profile = issue56_target_dense_embedding_profile()
    expected_evaluator_fingerprint = sha256_json(
        {
            "evaluator_id": EVALUATOR_ID,
            "case_count": CASE_COUNT,
            "result_kinds": [
                "owner_match",
                "no_match",
                "permission_denied",
            ],
        }
    )
    if component_fields["lexical_profile_fingerprint"] != lexical_profile.profile_fingerprint:
        raise ContractValidationError("completed UAT target tokenizer mismatch")
    if (
        shared.get("dense_model_id") != dense_profile.model_id
        or shared.get("dense_model_revision") != dense_profile.model_revision
        or component_fields["dense_profile_fingerprint"] != dense_profile.profile_fingerprint
    ):
        raise ContractValidationError("completed UAT dense model binding mismatch")
    if (
        shared.get("runtime_method_id") != ISSUE56_TARGET_RUNTIME_METHOD_ID
        or component_fields["runtime_method_fingerprint"]
        != ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT
    ):
        raise ContractValidationError("completed UAT runtime method mismatch")
    if (
        shared.get("answer_model_id") != ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID
        or shared.get("answer_prompt_id") != ISSUE56_DETERMINISTIC_ANSWER_PROMPT_ID
        or component_fields["answer_model_fingerprint"]
        != sha256_json(ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID)
        or component_fields["answer_prompt_fingerprint"]
        != ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT
        or component_fields["answer_budget_fingerprint"] != EvidenceAnswerBudget().fingerprint
    ):
        raise ContractValidationError("completed UAT answer binding mismatch")
    if (
        shared.get("evaluator_id") != EVALUATOR_ID
        or component_fields["evaluator_fingerprint"] != expected_evaluator_fingerprint
    ):
        raise ContractValidationError("completed UAT evaluator binding mismatch")
    if component_fields["permission_policy_fingerprint"] != sha256_json(PERMISSION_POLICY_ID):
        raise ContractValidationError("completed UAT permission policy mismatch")
    if component_fields["graph_adapter_fingerprint"] != sha256_json(
        GRAPH_ADAPTER_ID
    ) or component_fields["ontology_target_fingerprint"] != sha256_json(ONTOLOGY_TARGET):
        raise ContractValidationError("completed UAT graph ontology binding mismatch")

    statuses = {
        "source_completeness_gate_status": environment.get("source_completeness_gate_status"),
        "real_source_ablation_gate_status": environment.get("real_source_ablation_gate_status"),
    }
    if any(value not in {"passed", "blocked", "failed"} for value in statuses.values()):
        raise ContractValidationError("completed UAT authority gate status is invalid")
    return {
        **{key: str(value) for key, value in component_fields.items()},
        **{key: str(value) for key, value in statuses.items()},
        "component_binding_fingerprint": sha256_json(component_fields),
    }


def _quality_status_from_checks(
    checks: Mapping[str, Mapping[str, Any]],
) -> str:
    statuses = {str(check.get("status")) for check in checks.values()}
    if not statuses or not statuses.issubset({"passed", "failed", "blocked"}):
        raise ContractValidationError("completed UAT quality check status is invalid")
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    return "passed"


def _safe_binding_rejection_report(reason: str) -> dict[str, Any]:
    report = {
        "artifact_id": OPERATIONAL_BUDGET_BINDING_REJECTION_ARTIFACT_ID,
        "schema_version": 1,
        "status": "rejected",
        "execution_status": "blocked",
        "quality_gate_status": "blocked",
        "rejection_count": 1,
        "reason_hash": sha256_json(reason),
        "issue56_complete": False,
        "methodology_complete": False,
        "production_ready": False,
    }
    assert_no_public_raw_references(
        report,
        "issue56_completed_uat_operational_budget_binding_rejection",
    )
    return report


def _safe_diagnostic_subset_rejection_report(reason: str) -> dict[str, Any]:
    report = {
        "artifact_id": "formowl_issue56_diagnostic_subset_rejection_v1",
        "schema_version": 1,
        "status": "blocked",
        "execution_status": "blocked",
        "quality_gate_status": "blocked",
        "e2e_executed": False,
        "rejection_count": 1,
        "reason_hash": sha256_json(reason),
        "quality_claim_eligible": False,
        "operational_budget_binding_eligible": False,
        "completion_binding_eligible": False,
        "issue56_complete": False,
        "methodology_complete": False,
        "production_ready": False,
    }
    assert_no_public_raw_references(
        report,
        "issue56_diagnostic_subset_rejection",
    )
    return report


def _operational_budget_content_fingerprint(
    payload: Mapping[str, Any],
) -> str:
    """Match the frozen operational validator's canonical JSON projection."""

    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _run_case_arms(
    *,
    session,
    effective_graph_view,
    query_text: str,
    result_limit: int,
    relation_phase_probes: dict[str, _RelationPhaseProbe] | None = None,
) -> tuple[tuple[str, Any, float, float, str], ...]:
    limits = _frozen_per_case_limits(result_limit)
    execution_budget_fingerprint = _execution_budget_fingerprint(limits)
    strong_rag, strong_elapsed, strong_cpu = _run_instrumented_arm(
        arm_id="strong_rag",
        operation=lambda: session.index.query(
            query_text=query_text,
            query_class="evidence_lookup",
            candidate_limit=limits.max_candidates,
            result_limit=limits.max_results,
        ),
        relation_phase_probes=relation_phase_probes,
    )
    rag_entity, rag_entity_elapsed, rag_entity_cpu = _run_instrumented_arm(
        arm_id="rag_entity",
        operation=lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=DIAGNOSTIC_RELATION_TYPES,
            allowed_directions=DIAGNOSTIC_RELATION_DIRECTIONS,
            limits=limits,
            enable_graph_traversal=False,
        ),
        relation_phase_probes=relation_phase_probes,
    )
    candidate_kg, candidate_kg_elapsed, candidate_kg_cpu = _run_instrumented_arm(
        arm_id="rag_candidate_kg",
        operation=lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=DIAGNOSTIC_RELATION_TYPES,
            allowed_directions=DIAGNOSTIC_RELATION_DIRECTIONS,
            limits=limits,
        ),
        relation_phase_probes=relation_phase_probes,
    )
    hybrid_soft, hybrid_soft_elapsed, hybrid_soft_cpu = _run_instrumented_arm(
        arm_id="hybrid_v2_soft",
        operation=lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=DIAGNOSTIC_RELATION_TYPES,
            allowed_directions=DIAGNOSTIC_RELATION_DIRECTIONS,
            target_core_supertype_id=ONTOLOGY_TARGET,
            limits=limits,
        ),
        relation_phase_probes=relation_phase_probes,
    )
    legacy_hard_gate, legacy_elapsed, legacy_cpu = _run_instrumented_arm(
        arm_id="legacy_hard_gate",
        operation=lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=DIAGNOSTIC_RELATION_TYPES,
            allowed_directions=DIAGNOSTIC_RELATION_DIRECTIONS,
            target_core_supertype_id=ONTOLOGY_TARGET,
            limits=limits,
            legacy_hard_gate=True,
        ),
        relation_phase_probes=relation_phase_probes,
    )

    results: list[tuple[str, Any, float, float, str]] = [
        (
            "strong_rag",
            strong_rag,
            strong_elapsed,
            strong_cpu,
            execution_budget_fingerprint,
        ),
        (
            "rag_entity",
            rag_entity,
            rag_entity_elapsed,
            rag_entity_cpu,
            execution_budget_fingerprint,
        ),
        (
            "rag_candidate_kg",
            candidate_kg,
            candidate_kg_elapsed,
            candidate_kg_cpu,
            execution_budget_fingerprint,
        ),
        (
            "hybrid_v2_soft",
            hybrid_soft,
            hybrid_soft_elapsed,
            hybrid_soft_cpu,
            execution_budget_fingerprint,
        ),
        (
            "legacy_hard_gate",
            legacy_hard_gate,
            legacy_elapsed,
            legacy_cpu,
            execution_budget_fingerprint,
        ),
    ]
    if deterministic_query_class(query_text) == "exact_set_or_inventory":
        structured_exact, exact_elapsed, exact_cpu = _run_instrumented_arm(
            arm_id="structured_exact",
            operation=lambda: session.query(
                query_text=query_text,
                effective_graph_view=effective_graph_view,
                exact_inventory_kind=None,
                limits=limits,
            ),
            relation_phase_probes=relation_phase_probes,
        )
        results.append(
            (
                "structured_exact",
                structured_exact,
                exact_elapsed,
                exact_cpu,
                execution_budget_fingerprint,
            )
        )
    return tuple(results)


def _run_instrumented_arm(
    *,
    arm_id: str,
    operation: Callable[[], Any],
    relation_phase_probes: dict[str, _RelationPhaseProbe] | None,
) -> tuple[Any, float, float]:
    probe = _RelationPhaseProbe()
    started = time.perf_counter()
    cpu_started = time.process_time()
    if relation_phase_probes is None:
        result = operation()
    else:
        with _capture_relation_phase_metrics(probe):
            result = operation()
        relation_phase_probes[arm_id] = probe
    return (
        result,
        (time.perf_counter() - started) * 1_000,
        (time.process_time() - cpu_started) * 1_000,
    )


@contextmanager
def _capture_relation_phase_metrics(probe: _RelationPhaseProbe) -> Iterator[None]:
    targets = (
        (hybrid_runtime.AuthorizedHybridMailIndex, "query", "index_lookup"),
        (hybrid_runtime, "_semantic_evidence_scores", "evidence_scoring"),
        (hybrid_runtime, "_bounded_graph_traversal", "graph_traversal"),
        (
            hybrid_runtime,
            "_bounded_semantic_answer_citation_hashes",
            "strict_projection",
        ),
        (
            hybrid_runtime,
            "_execute_bounded_relation_fallback",
            "fallback_repair",
        ),
    )
    originals: list[tuple[Any, str, Any]] = []

    def wrapped(original, phase):
        def measured(*args, **kwargs):
            started = time.perf_counter()
            result = None
            try:
                result = original(*args, **kwargs)
                return result
            finally:
                probe.record(
                    phase=phase,
                    elapsed_ms=(time.perf_counter() - started) * 1_000,
                    result=result,
                )

        return measured

    try:
        for owner, attribute, phase in targets:
            original = getattr(owner, attribute)
            originals.append((owner, attribute, original))
            setattr(owner, attribute, wrapped(original, phase))
        yield
    finally:
        for owner, attribute, original in reversed(originals):
            setattr(owner, attribute, original)


def _frozen_per_case_limits(result_limit: int) -> SemanticPlanLimits:
    return SemanticPlanLimits(
        max_hops=2,
        max_fanout=6,
        max_candidates=24,
        max_results=max(1, min(result_limit, 10)),
        max_evidence=10,
        max_time_budget_ms=1_500,
        max_repairs=1,
    )


def _execution_budget_fingerprint(limits: SemanticPlanLimits) -> str:
    return sha256_json(
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


def _score_case(
    case: Mapping[str, Any],
    *,
    result: Any,
    answer_status: str,
    citation_hashes: Sequence[str],
    exact_count: int | None,
    answer_hash: str,
    source_result_fingerprint: str,
    cost_units: int,
    elapsed_ms: float,
    cpu_ms: float,
    execution_budget_fingerprint: str,
    observation_hash_by_id: Mapping[str, str],
    lineage_crosswalk: EvidenceIdentityLineageCrosswalk,
) -> dict[str, Any]:
    required_hashes = {
        observation_hash_by_id[observation_id]
        for observation_id in case["required_source_observation_ids"]
        if observation_id in observation_hash_by_id
    }
    forbidden_hashes = {
        observation_hash_by_id[observation_id]
        for observation_id in case["forbidden_source_observation_ids"]
        if observation_id in observation_hash_by_id
    }
    ordered_citations = tuple(dict.fromkeys(citation_hashes))
    citations = set(ordered_citations)
    matched_required = citations & required_hashes
    matched_forbidden = citations & forbidden_hashes
    result_kind = str(case["result_kind"])
    query_class = deterministic_query_class(str(case["query_text"]))
    if result_kind == "owner_match":
        passed = (
            answer_status in {"answered", "exact_complete"}
            and len(matched_required) >= int(case["required_match_count"])
            and not matched_forbidden
        )
    elif result_kind == "permission_denied":
        passed = answer_status == "permission_denied" and not citations
    elif result_kind == "no_match":
        passed = answer_status == "no_answer" and not citations
    else:
        passed = False
    scores = tuple(getattr(result, "scores", ()))
    graph_paths = tuple(getattr(result, "graph_paths", ()))
    exact_result = getattr(result, "exact_result", None)
    lineage_audit = getattr(result, "lineage_audit", None)
    lineage_entries_by_hash = {
        entry.source_observation_hash: entry for entry in lineage_crosswalk.entries
    }
    authorized_observation_hashes = set(observation_hash_by_id.values())
    path_required_matches = 0
    path_forbidden_matches = 0
    graph_hop_count = 0
    graph_hop_authorized_evidence_count = 0
    graph_hop_unresolved_evidence_count = 0
    for path in graph_paths:
        path_citations = set(path.cited_observation_hashes)
        if path_citations & required_hashes:
            path_required_matches += 1
        if path_citations & forbidden_hashes:
            path_forbidden_matches += 1
        for hop in path.hops:
            graph_hop_count += 1
            hop_citations = set(hop.cited_observation_hashes)
            if hop_citations and hop_citations <= authorized_observation_hashes:
                graph_hop_authorized_evidence_count += 1
            else:
                graph_hop_unresolved_evidence_count += 1
    recall_at_k = {str(k): len(set(ordered_citations[:k]) & required_hashes) for k in (1, 3, 5, 10)}
    exact_item_hashes = (
        [item.item_hash for item in exact_result.items] if exact_result is not None else []
    )
    exact_item_evidence_hashes = (
        {
            evidence_hash
            for item in exact_result.items
            for evidence_hash in item.cited_observation_hashes
        }
        if exact_result is not None
        else set()
    )
    required_lineage_entries = [
        lineage_entries_by_hash[evidence_hash]
        for evidence_hash in required_hashes
        if evidence_hash in lineage_entries_by_hash
    ]
    audited_unresolved_count = (
        len(lineage_audit.unresolved_evidence_hashes) if lineage_audit is not None else 0
    )
    return {
        "case_manifest_entry_hash": str(case["private_fingerprint"]),
        "pattern": str(case["pattern"]),
        "domain_hash": sha256_json(str(case["domain"])),
        "result_kind": result_kind,
        "query_class": query_class,
        "status": "passed" if passed else "failed",
        "answer_status": answer_status,
        "answer_hash": answer_hash,
        "source_result_fingerprint": source_result_fingerprint,
        "citation_count": len(citations),
        "required_evidence_count": len(required_hashes),
        "required_match_count": int(case["required_match_count"]),
        "matched_required_evidence_count": len(matched_required),
        "forbidden_evidence_match_count": len(matched_forbidden),
        "required_evidence_recall_at_k": recall_at_k,
        "required_bundle_coverage_passed": (
            len(matched_required) >= int(case["required_match_count"])
        ),
        "predicted_no_answer": answer_status == "no_answer",
        "entity_signal_count": sum(score.entity_score > 0.0 for score in scores),
        "graph_signal_count": (
            sum(score.entity_score > 0.0 for score in scores)
            + sum(score.graph_path_score > 0.0 for score in scores)
            + len(graph_paths)
        ),
        "ontology_signal_count": sum(score.ontology_bonus > 0.0 for score in scores),
        "graph_path_count": len(graph_paths),
        "graph_path_required_match_count": path_required_matches,
        "graph_path_forbidden_match_count": path_forbidden_matches,
        "graph_hop_count": graph_hop_count,
        "graph_hop_authorized_evidence_count": (graph_hop_authorized_evidence_count),
        "graph_hop_unresolved_evidence_count": (graph_hop_unresolved_evidence_count),
        "required_lineage_authorized_count": len(required_lineage_entries),
        "required_lineage_indexed_count": sum(
            bool(entry.index_binding_hashes) for entry in required_lineage_entries
        ),
        "required_lineage_occurrence_bound_count": sum(
            bool(entry.index_binding_hashes)
            and bool(entry.message_hashes)
            and bool(entry.occurrence_hashes)
            for entry in required_lineage_entries
        ),
        "required_lineage_graph_node_bound_count": sum(
            bool(entry.graph_node_hashes) for entry in required_lineage_entries
        ),
        "required_lineage_graph_edge_bound_count": sum(
            bool(entry.graph_edge_hashes) for entry in required_lineage_entries
        ),
        "required_lineage_graph_path_count": len(
            required_hashes
            & {
                evidence_hash
                for path in graph_paths
                for evidence_hash in path.cited_observation_hashes
            }
        ),
        "required_lineage_final_citation_count": len(matched_required),
        "required_lineage_exact_item_count": len(required_hashes & exact_item_evidence_hashes),
        "lineage_audit_unresolved_count": audited_unresolved_count,
        "positive_required_graph_case": (
            _is_positive_graph_required_owner_case(case) and bool(required_hashes)
        ),
        "unsupported_hop_rejected_count": int(getattr(result, "rejected_hop_count", 0)),
        "temporal_current_score_count": sum(score.temporal_current_score > 0.5 for score in scores),
        "temporal_superseded_score_count": sum(
            score.temporal_current_score < 0.5 for score in scores
        ),
        "exact_count": exact_count,
        "exact_status": (exact_result.status if exact_result is not None else "not_requested"),
        "exact_returned_item_count": (
            exact_result.returned_item_count if exact_result is not None else 0
        ),
        "exact_duplicate_item_count": (len(exact_item_hashes) - len(set(exact_item_hashes))),
        "cost_units": cost_units,
        "elapsed_ms": round(elapsed_ms, 3),
        "cpu_ms": round(cpu_ms, 3),
        "execution_budget_fingerprint": execution_budget_fingerprint,
    }


def _build_private_relation_phase_trace(
    *,
    arm_id: str,
    hashed_case_id: str,
    query_text: str,
    result: Any,
    answer_status: str,
    session: Any,
    effective_graph_view: Any,
    probe: _RelationPhaseProbe,
    arm_elapsed_ms: float,
    answer_projection_elapsed_ms: float,
    evidence_budget: int | None = None,
    path_proof_trace_index: _RelationPathProofTraceIndex | None = None,
) -> dict[str, Any]:
    query_class = deterministic_query_class(query_text)
    warnings = frozenset(str(value) for value in getattr(result, "warnings", ()))
    fallback_invoked = probe.invocation_counts["fallback_repair"] > 0
    targeted_retraversal_invoked = "bounded_relation_targeted_retraversal_attempted" in warnings
    candidates_by_hash = {
        candidate.source_observation_hash: candidate for candidate in session.index.candidates
    }
    required_identifier_tokens: frozenset[str] = frozenset()
    required_concept_tokens: frozenset[str] = frozenset()
    fallback_slots: Any | None = None
    if query_class == "relation_reasoning" and arm_id not in (
        "strong_rag",
        "structured_exact",
    ):
        strict_slots = hybrid_runtime._query_evidence_slots(
            query_text,
            query_class="relation_reasoning",
            tokenizer_profile=session.index._runtime_components.tokenizer_profile,
        )
        required_identifier_tokens = strict_slots.identifier_tokens
        required_concept_tokens = strict_slots.topic_tokens
        if fallback_invoked:
            fallback_slots = hybrid_runtime._deterministic_relation_fallback_slots(
                query_text,
                tokenizer_profile=(session.index._runtime_components.tokenizer_profile),
                document_frequency=dict(session.index.document_frequency),
                document_count=len(session.index.candidates),
                index_fingerprint=session.index.index_fingerprint,
                graph_revision_fingerprint=str(result.graph_revision_fingerprint),
                effective_graph_view=effective_graph_view,
                authorized_observation_hash_by_id=dict(session.authorized_observation_hashes),
                candidates_by_hash=candidates_by_hash,
            )
            if fallback_slots is not None:
                required_identifier_tokens = fallback_slots.identifier_tokens
                required_concept_tokens = fallback_slots.concept_tokens

    final_citation_hashes = tuple(dict.fromkeys(getattr(result, "answer_citation_hashes", ())))
    cited_candidates = tuple(
        candidates_by_hash[citation_hash]
        for citation_hash in final_citation_hashes
        if citation_hash in candidates_by_hash
    )
    covered_identifier_tokens = frozenset().union(
        *(candidate.observation_protected_identifier_tokens for candidate in cited_candidates)
    )
    covered_concept_tokens = frozenset().union(
        *(candidate.observation_tokens for candidate in cited_candidates)
    )
    required_identifier_slot_count = len(required_identifier_tokens)
    required_concept_slot_count = len(required_concept_tokens)
    covered_identifier_slot_count = len(required_identifier_tokens & covered_identifier_tokens)
    covered_concept_slot_count = len(required_concept_tokens & covered_concept_tokens)

    if query_class != "relation_reasoning" or arm_id in (
        "strong_rag",
        "structured_exact",
    ):
        strict_proof_status = "not_applicable"
    elif arm_id == "rag_entity":
        strict_proof_status = "not_executed_graph_disabled"
    elif probe.strict_projection_citation_counts and probe.strict_projection_citation_counts[0] > 0:
        strict_proof_status = "passed"
    else:
        strict_proof_status = "failed"

    graph_paths = tuple(getattr(result, "graph_paths", ()))
    resolved_evidence_budget = (
        probe.fallback_evidence_budgets[-1] if probe.fallback_evidence_budgets else evidence_budget
    )
    if resolved_evidence_budget is None:
        resolved_evidence_budget = 10
    if fallback_invoked and fallback_slots is not None and path_proof_trace_index is None:
        path_proof_trace_index = _build_relation_path_proof_trace_index(
            effective_graph_view=effective_graph_view,
            authorized_observation_hash_by_id=dict(session.authorized_observation_hashes),
            candidates_by_hash=candidates_by_hash,
            selection=fallback_slots,
        )
    fallback_path_proof_diagnostics = (
        _fallback_path_proof_diagnostics(
            graph_paths=graph_paths,
            selection=fallback_slots,
            trace_index=path_proof_trace_index,
            authorized_observation_hash_by_id=dict(session.authorized_observation_hashes),
            candidates_by_hash=candidates_by_hash,
            evidence_budget=resolved_evidence_budget,
        )
        if (fallback_invoked and fallback_slots is not None and path_proof_trace_index is not None)
        else ()
    )
    path_proof_reason_counts = _relation_path_proof_reason_counts(fallback_path_proof_diagnostics)
    initial_candidate_path_count = (
        probe.traversal_path_counts[0] if probe.traversal_path_counts else 0
    )
    repaired_path_count = len(graph_paths) if fallback_invoked else 0
    no_answer_reason = _relation_trace_reason(
        query_class=query_class,
        answer_status=answer_status,
        warnings=warnings,
        fallback_invoked=fallback_invoked,
        graph_path_count=len(graph_paths),
        rejected_hop_count=int(getattr(result, "rejected_hop_count", 0)),
        required_identifier_slot_count=required_identifier_slot_count,
        covered_identifier_slot_count=covered_identifier_slot_count,
        required_concept_slot_count=required_concept_slot_count,
        covered_concept_slot_count=covered_concept_slot_count,
    )
    phase_elapsed_ms = {
        phase: round(float(probe.elapsed_ms[phase]), 3)
        for phase in (
            "index_lookup",
            "evidence_scoring",
            "graph_traversal",
            "strict_projection",
            "fallback_repair",
        )
    }
    trace = {
        "hashed_case_id": hashed_case_id,
        "arm_id": arm_id,
        "query_class": query_class,
        "initial_candidate_path_count": initial_candidate_path_count,
        "strict_proof_status": strict_proof_status,
        "required_identifier_slot_count": required_identifier_slot_count,
        "covered_identifier_slot_count": covered_identifier_slot_count,
        "required_concept_slot_count": required_concept_slot_count,
        "covered_concept_slot_count": covered_concept_slot_count,
        "fallback_invoked": fallback_invoked,
        "targeted_retraversal_invoked": targeted_retraversal_invoked,
        "repaired_path_count": repaired_path_count,
        "final_citation_count": len(final_citation_hashes),
        "no_answer_reason": no_answer_reason,
        "no_answer_reason_hash": sha256_json(no_answer_reason),
        "index_lookup_invocation_count": probe.invocation_counts["index_lookup"],
        "evidence_scoring_invocation_count": probe.invocation_counts["evidence_scoring"],
        "graph_traversal_invocation_count": probe.invocation_counts["graph_traversal"],
        "strict_projection_invocation_count": probe.invocation_counts["strict_projection"],
        "fallback_repair_invocation_count": probe.invocation_counts["fallback_repair"],
        "fallback_path_proof_diagnostic_schema_version": (
            FALLBACK_PATH_PROOF_DIAGNOSTIC_SCHEMA_VERSION
        ),
        "fallback_path_proof_diagnostics": list(fallback_path_proof_diagnostics),
        "path_proof_reason_counts": path_proof_reason_counts,
        "arm_elapsed_ms": round(arm_elapsed_ms, 3),
        "answer_projection_elapsed_ms": round(answer_projection_elapsed_ms, 3),
        "phase_elapsed_ms": phase_elapsed_ms,
    }
    if no_answer_reason not in RELATION_TRACE_REASON_ENUMS:
        raise ContractValidationError("relation trace reason enum is invalid")
    assert_no_public_raw_references(trace, "issue56_private_relation_phase_trace_row")
    return trace


def _fallback_candidate_slot_coverage(
    candidate: Any,
    *,
    selection: Any | None,
) -> frozenset[tuple[str, str]]:
    coverage = frozenset(
        ("identifier", term_hash)
        for term_hash in hybrid_runtime._source_graph_term_hashes(
            tuple(candidate.observation_protected_identifier_tokens)
        )
    ) | frozenset(
        ("concept", term_hash)
        for term_hash in hybrid_runtime._source_graph_term_hashes(
            tuple(candidate.observation_tokens)
        )
    )
    if selection is None:
        return coverage
    required = frozenset(
        ("identifier", term_hash) for term_hash in selection.identifier_term_hashes
    ) | frozenset(("concept", term_hash) for term_hash in selection.concept_term_hashes)
    return coverage & required


def _build_relation_path_proof_trace_index(
    *,
    effective_graph_view: Any,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, Any],
    selection: Any | None = None,
) -> _RelationPathProofTraceIndex:
    node_by_id = {node.node_id: node for node in effective_graph_view.visible_nodes}
    node_by_hash = {sha256_json(node.node_id): node for node in effective_graph_view.visible_nodes}
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}
    for edge in effective_graph_view.visible_edges:
        if edge.source_node_id in node_by_id and edge.target_node_id in node_by_id:
            adjacency[edge.source_node_id].add(edge.target_node_id)
            adjacency[edge.target_node_id].add(edge.source_node_id)

    candidate_slot_support_by_observation_hash = {
        observation_hash: _fallback_candidate_slot_coverage(
            candidate,
            selection=None,
        )
        for observation_hash, candidate in candidates_by_hash.items()
    }
    node_property_slot_support_by_id: dict[
        str,
        frozenset[tuple[str, str]],
    ] = {}
    node_bound_candidate_slot_support_by_id: dict[
        str,
        dict[str, frozenset[tuple[str, str]]],
    ] = {}
    supporting_node_ids_by_slot: dict[tuple[str, str], set[str]] = {}
    for node_id, node in node_by_id.items():
        node_property_support = _fallback_node_property_slot_coverage(
            node,
            selection=None,
        )
        node_property_slot_support_by_id[node_id] = node_property_support
        bound_support = _fallback_node_bound_candidate_slot_coverage(
            node,
            selection=selection,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            candidates_by_hash=candidates_by_hash,
        )
        for support in bound_support.values():
            for slot in support:
                supporting_node_ids_by_slot.setdefault(slot, set()).add(node_id)
        node_bound_candidate_slot_support_by_id[node_id] = bound_support

    return _RelationPathProofTraceIndex(
        node_by_id=node_by_id,
        node_by_hash=node_by_hash,
        adjacent_node_ids_by_id={
            node_id: frozenset(neighbor_ids) for node_id, neighbor_ids in adjacency.items()
        },
        candidate_slot_support_by_observation_hash=(candidate_slot_support_by_observation_hash),
        node_property_slot_support_by_id=node_property_slot_support_by_id,
        node_bound_candidate_slot_support_by_id=(node_bound_candidate_slot_support_by_id),
        supporting_node_ids_by_slot={
            slot: frozenset(node_ids) for slot, node_ids in supporting_node_ids_by_slot.items()
        },
        authorized_observation_hashes=frozenset(authorized_observation_hash_by_id.values()),
    )


def _fallback_node_property_slot_coverage(
    node: Any,
    *,
    selection: Any | None,
) -> frozenset[tuple[str, str]]:
    coverage = frozenset(
        ("identifier", term_hash) for term_hash in hybrid_runtime._node_protected_term_hashes(node)
    ) | frozenset(
        ("concept", term_hash) for term_hash in hybrid_runtime._node_source_term_hashes(node)
    )
    if selection is None:
        return coverage
    required = frozenset(
        ("identifier", term_hash) for term_hash in selection.identifier_term_hashes
    ) | frozenset(("concept", term_hash) for term_hash in selection.concept_term_hashes)
    return coverage & required


def _fallback_node_bound_candidate_slot_coverage(
    node: Any,
    *,
    selection: Any | None,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, Any],
) -> dict[str, frozenset[tuple[str, str]]]:
    evidence_hashes = hybrid_runtime._authorized_property_evidence_hashes(
        node.properties,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
    )
    if evidence_hashes is None:
        return {}
    node_property_coverage = _fallback_node_property_slot_coverage(
        node,
        selection=selection,
    )
    support: dict[str, frozenset[tuple[str, str]]] = {}
    for evidence_hash in evidence_hashes:
        candidate = candidates_by_hash.get(evidence_hash)
        if candidate is None:
            continue
        coverage = node_property_coverage & _fallback_candidate_slot_coverage(
            candidate,
            selection=selection,
        )
        if coverage:
            support[evidence_hash] = coverage
    return support


def _minimal_additional_fallback_citation_count(
    *,
    required: frozenset[tuple[str, str]],
    covered_by_base: frozenset[tuple[str, str]],
    coverage_by_observation_hash: Mapping[str, frozenset[tuple[str, str]]],
    base_citations: Sequence[str],
) -> int | None:
    if required.issubset(covered_by_base):
        return 0
    states: dict[frozenset[tuple[str, str]], int] = {covered_by_base: 0}
    for observation_hash in sorted(set(coverage_by_observation_hash) - set(base_citations)):
        observation_coverage = coverage_by_observation_hash[observation_hash]
        if not observation_coverage:
            continue
        updated = dict(states)
        for covered, selected_count in states.items():
            proposed_covered = covered | observation_coverage
            proposed_count = selected_count + 1
            existing_count = updated.get(proposed_covered)
            if existing_count is None or proposed_count < existing_count:
                updated[proposed_covered] = proposed_count
        states = updated
    eligible_counts = [
        selected_count for covered, selected_count in states.items() if required.issubset(covered)
    ]
    return min(eligible_counts) if eligible_counts else None


def _connected_off_path_nodes(
    *,
    path_node_ids: frozenset[str],
    trace_index: _RelationPathProofTraceIndex,
) -> tuple[Any, ...]:
    off_path_node_ids = set().union(
        *(
            trace_index.adjacent_node_ids_by_id.get(
                node_id,
                frozenset(),
            )
            for node_id in path_node_ids
        )
    ) - set(path_node_ids)
    return tuple(
        trace_index.node_by_id[node_id]
        for node_id in sorted(off_path_node_ids)
        if node_id in trace_index.node_by_id
    )


def _fallback_path_proof_diagnostics(
    *,
    graph_paths: Sequence[Any],
    selection: Any,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, Any],
    evidence_budget: int,
    effective_graph_view: Any | None = None,
    trace_index: _RelationPathProofTraceIndex | None = None,
) -> tuple[dict[str, Any], ...]:
    if trace_index is None:
        if effective_graph_view is None:
            raise ContractValidationError(
                "path proof trace index or effective graph view is required"
            )
        trace_index = _build_relation_path_proof_trace_index(
            effective_graph_view=effective_graph_view,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            candidates_by_hash=candidates_by_hash,
            selection=selection,
        )
    required = frozenset(
        ("identifier", term_hash) for term_hash in selection.identifier_term_hashes
    ) | frozenset(("concept", term_hash) for term_hash in selection.concept_term_hashes)
    visible_nodes_by_hash = trace_index.node_by_hash
    authorized_hashes = trace_index.authorized_observation_hashes
    diagnostics: list[dict[str, Any]] = []
    for path in graph_paths:
        path_node_hashes = hybrid_runtime._path_node_hashes(path)
        path_nodes = tuple(
            visible_nodes_by_hash[node_hash]
            for node_hash in sorted(path_node_hashes)
            if node_hash in visible_nodes_by_hash
        )
        path_node_ids = frozenset(node.node_id for node in path_nodes)
        property_coverage = frozenset().union(
            *(
                trace_index.node_property_slot_support_by_id.get(
                    node.node_id,
                    frozenset(),
                )
                & required
                for node in path_nodes
            )
        )
        node_support_by_observation_hash: dict[
            str,
            frozenset[tuple[str, str]],
        ] = {}
        for node_id in path_node_ids:
            for (
                observation_hash,
                support,
            ) in trace_index.node_bound_candidate_slot_support_by_id.get(
                node_id,
                {},
            ).items():
                selected_support = support & required
                if selected_support:
                    node_support_by_observation_hash[observation_hash] = (
                        node_support_by_observation_hash.get(
                            observation_hash,
                            frozenset(),
                        )
                        | selected_support
                    )
        node_bound_coverage = frozenset().union(*node_support_by_observation_hash.values())
        base_citations = tuple(sorted(set(path.cited_observation_hashes)))
        coverage_by_observation_hash: dict[
            str,
            frozenset[tuple[str, str]],
        ] = {}
        for observation_hash in base_citations:
            support = trace_index.candidate_slot_support_by_observation_hash.get(observation_hash)
            if support is not None:
                coverage_by_observation_hash[observation_hash] = support & required
        for observation_hash, coverage in node_support_by_observation_hash.items():
            coverage_by_observation_hash[observation_hash] = (
                coverage_by_observation_hash.get(observation_hash, frozenset()) | coverage
            )
        covered_by_base = frozenset().union(
            *(
                coverage_by_observation_hash.get(
                    observation_hash,
                    frozenset(),
                )
                for observation_hash in base_citations
            )
        )
        minimal_additional_count = _minimal_additional_fallback_citation_count(
            required=required,
            covered_by_base=covered_by_base,
            coverage_by_observation_hash=coverage_by_observation_hash,
            base_citations=base_citations,
        )
        off_path_support_by_observation_hash: dict[
            str,
            frozenset[tuple[str, str]],
        ] = {}
        connected_off_path_node_ids = set().union(
            *(
                trace_index.adjacent_node_ids_by_id.get(
                    node_id,
                    frozenset(),
                )
                for node_id in path_node_ids
            )
        ) - set(path_node_ids)
        for node_id in sorted(connected_off_path_node_ids):
            for (
                observation_hash,
                coverage,
            ) in trace_index.node_bound_candidate_slot_support_by_id.get(
                node_id,
                {},
            ).items():
                selected_coverage = coverage & required
                if not selected_coverage:
                    continue
                off_path_support_by_observation_hash[observation_hash] = (
                    off_path_support_by_observation_hash.get(
                        observation_hash,
                        frozenset(),
                    )
                    | selected_coverage
                )
        off_path_coverage = frozenset().union(*off_path_support_by_observation_hash.values())
        all_off_path_coverage = frozenset(
            slot
            for slot in required
            for supporting_node_ids in (
                trace_index.supporting_node_ids_by_slot.get(
                    slot,
                    frozenset(),
                ),
            )
            if supporting_node_ids - set(path_node_ids)
        )
        projected_citations = hybrid_runtime._minimal_relation_fallback_path_citations(
            path=path,
            required=required,
            selection=selection,
            candidates_by_hash=candidates_by_hash,
            visible_nodes_by_hash=visible_nodes_by_hash,
            authorized_observation_hash_by_id=(authorized_observation_hash_by_id),
            evidence_budget=evidence_budget,
        )
        path_substrate_valid = (
            bool(path.hops)
            and len(base_citations) <= evidence_budget
            and set(base_citations).issubset(authorized_hashes)
            and {
                evidence_hash for hop in path.hops for evidence_hash in hop.cited_observation_hashes
            }
            == set(base_citations)
            and all(
                hop.cited_observation_hashes
                and set(hop.cited_observation_hashes).issubset(authorized_hashes)
                for hop in path.hops
            )
        )
        if projected_citations and path_substrate_valid:
            rejection = "complete"
        elif (
            minimal_additional_count is not None
            and len(base_citations) + minimal_additional_count > evidence_budget
        ):
            rejection = "additional_citation_exceeds_budget"
        else:
            locally_covered = covered_by_base | node_bound_coverage
            missing_local = required - locally_covered
            if missing_local and missing_local.issubset(off_path_coverage):
                rejection = "support_only_on_connected_off_path_node"
            elif not required.issubset(covered_by_base | property_coverage):
                rejection = "path_term_support_missing"
            else:
                rejection = "bound_candidate_term_support_missing"
        if rejection not in FALLBACK_PATH_PROOF_REJECTION_ENUMS:
            raise ContractValidationError("fallback path proof rejection enum is invalid")
        diagnostic = {
            "path_hash": path.path_hash,
            "path_node_count": len(path_node_hashes),
            "required_identifier_count": len(selection.identifier_term_hashes),
            "required_concept_count": len(selection.concept_term_hashes),
            "on_path_node_property_term_match_count": len(property_coverage),
            "on_path_bound_candidate_term_support_count": len(node_bound_coverage),
            "connected_off_path_support_count": len(off_path_coverage),
            "off_path_support_count": len(all_off_path_coverage),
            "base_citation_count": len(base_citations),
            "minimal_additional_citation_count": (
                minimal_additional_count if minimal_additional_count is not None else 0
            ),
            "minimal_additional_citation_available": (minimal_additional_count is not None),
            "evidence_budget": evidence_budget,
            "rejection": rejection,
        }
        diagnostic["proof_diagnostic_fingerprint"] = sha256_json(diagnostic)
        assert_no_public_raw_references(
            diagnostic,
            "issue56_fallback_path_proof_diagnostic",
        )
        diagnostics.append(diagnostic)
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                str(item["path_hash"]),
                str(item["proof_diagnostic_fingerprint"]),
            ),
        )
    )


def _relation_path_proof_reason_counts(
    diagnostics: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    counts = {reason: 0 for reason in sorted(RELATION_PATH_PROOF_REASON_ENUMS)}
    for diagnostic in diagnostics:
        rejection = str(diagnostic["rejection"])
        if rejection == "complete":
            reason = "path_property_match"
        elif rejection == "additional_citation_exceeds_budget":
            reason = "evidence_budget_rejection"
        elif (
            rejection == "support_only_on_connected_off_path_node"
            or int(diagnostic.get("off_path_support_count", 0)) > 0
        ):
            reason = "off_path_support"
        else:
            reason = "bound_candidate_term_support_missing"
        counts[reason] += 1
    return counts


def _relation_trace_reason(
    *,
    query_class: str,
    answer_status: str,
    warnings: frozenset[str],
    fallback_invoked: bool,
    graph_path_count: int,
    rejected_hop_count: int,
    required_identifier_slot_count: int,
    covered_identifier_slot_count: int,
    required_concept_slot_count: int,
    covered_concept_slot_count: int,
) -> str:
    if answer_status not in {"no_answer", "permission_denied", "exact_incomplete"}:
        return "answered"
    if answer_status == "permission_denied":
        return "permission_denied"
    if answer_status == "exact_incomplete":
        return "exact_incomplete"
    if query_class != "relation_reasoning":
        return "insufficient_authorized_evidence"
    if "graph_traversal_ablation_disabled" in warnings:
        return "graph_traversal_disabled"
    if rejected_hop_count > 0 and graph_path_count == 0:
        return "unsupported_or_denied_path"
    if fallback_invoked:
        if graph_path_count == 0:
            return "fallback_no_connected_path"
        if covered_identifier_slot_count < required_identifier_slot_count:
            return "fallback_identifier_coverage_missing"
        if covered_concept_slot_count < required_concept_slot_count:
            return "fallback_concept_coverage_missing"
        return "fallback_repair_exhausted"
    if "required_relation_slots_unresolved" in warnings:
        if int("bounded_relation_fallback_repair_attempted" in warnings) == 0:
            return "fallback_slot_unavailable"
        return "strict_relation_proof_unresolved"
    return "insufficient_authorized_evidence"


def _relation_trace_behavior_fingerprint(
    rows: Sequence[Mapping[str, Any]],
) -> str:
    timing_fields = {
        "arm_elapsed_ms",
        "answer_projection_elapsed_ms",
        "phase_elapsed_ms",
    }
    projection = [
        {key: value for key, value in sorted(row.items()) if key not in timing_fields}
        for row in sorted(
            rows,
            key=lambda row: (
                str(row["arm_id"]),
                str(row["hashed_case_id"]),
            ),
        )
    ]
    return sha256_json(projection)


def _safe_fallback_path_proof_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    all_diagnostic_fingerprints: list[str] = []
    for row in rows:
        arm_id = str(row["arm_id"])
        hashed_case_id = str(row["hashed_case_id"])
        diagnostics = row.get("fallback_path_proof_diagnostics", ())
        if not isinstance(diagnostics, (list, tuple)):
            raise ContractValidationError("fallback path proof diagnostics must be a sequence")
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, Mapping):
                raise ContractValidationError("fallback path proof diagnostic must be a mapping")
            rejection = str(diagnostic.get("rejection", ""))
            if rejection not in FALLBACK_PATH_PROOF_REJECTION_ENUMS:
                raise ContractValidationError("fallback path proof rejection enum is invalid")
            for field_name in FALLBACK_PATH_PROOF_COUNT_FIELDS:
                field_value = diagnostic.get(field_name)
                if (
                    not isinstance(field_value, int)
                    or isinstance(field_value, bool)
                    or field_value < 0
                ):
                    raise ContractValidationError("fallback path proof count is invalid")
            diagnostic_fingerprint = str(diagnostic.get("proof_diagnostic_fingerprint", ""))
            if not (
                diagnostic_fingerprint.startswith("sha256:")
                and len(diagnostic_fingerprint) == _SHA256_LENGTH
            ):
                raise ContractValidationError(
                    "fallback path proof diagnostic fingerprint is invalid"
                )
            grouped.setdefault(arm_id, []).append((hashed_case_id, diagnostic))
            all_diagnostic_fingerprints.append(diagnostic_fingerprint)

    def summarize(
        entries: Sequence[tuple[str, Mapping[str, Any]]],
    ) -> dict[str, Any]:
        return {
            "diagnostic_case_count": len({hashed_case_id for hashed_case_id, _ in entries}),
            "diagnostic_path_count": len(entries),
            "rejection_counts": dict(
                sorted(Counter(str(diagnostic["rejection"]) for _, diagnostic in entries).items())
            ),
            "count_field_totals": {
                field_name: sum(int(diagnostic[field_name]) for _, diagnostic in entries)
                for field_name in FALLBACK_PATH_PROOF_COUNT_FIELDS
            },
            "count_field_maxima": {
                field_name: max(
                    (int(diagnostic[field_name]) for _, diagnostic in entries),
                    default=0,
                )
                for field_name in FALLBACK_PATH_PROOF_COUNT_FIELDS
            },
            "minimal_additional_citation_unavailable_count": sum(
                not bool(
                    diagnostic.get(
                        "minimal_additional_citation_available",
                        False,
                    )
                )
                for _, diagnostic in entries
            ),
            "diagnostic_set_fingerprint": sha256_json(
                sorted(str(diagnostic["proof_diagnostic_fingerprint"]) for _, diagnostic in entries)
            ),
        }

    all_entries = tuple(entry for arm_entries in grouped.values() for entry in arm_entries)
    return {
        "schema_version": FALLBACK_PATH_PROOF_DIAGNOSTIC_SCHEMA_VERSION,
        **summarize(all_entries),
        "by_arm": {
            arm_id: summarize(tuple(arm_entries)) for arm_id, arm_entries in sorted(grouped.items())
        },
        "aggregate_fingerprint": sha256_json(sorted(all_diagnostic_fingerprints)),
    }


def _safe_relation_trace_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["arm_id"]), []).append(row)
    reason_counts_by_arm: dict[str, Any] = {}
    latency_distributions_by_arm: dict[str, Any] = {}
    for arm_id, arm_rows in sorted(grouped.items()):
        path_proof_reason_counts = {
            reason: 0 for reason in sorted(RELATION_PATH_PROOF_REASON_ENUMS)
        }
        for row in arm_rows:
            for reason, count in _relation_path_proof_reason_counts(
                row.get("fallback_path_proof_diagnostics", ())
            ).items():
                path_proof_reason_counts[reason] += count
        reason_counts_by_arm[arm_id] = {
            "no_answer_reason_counts": dict(
                sorted(Counter(str(row["no_answer_reason"]) for row in arm_rows).items())
            ),
            "strict_proof_status_counts": dict(
                sorted(Counter(str(row["strict_proof_status"]) for row in arm_rows).items())
            ),
            "fallback_invocation_counts": {
                "invoked": sum(bool(row["fallback_invoked"]) for row in arm_rows),
                "not_invoked": sum(not bool(row["fallback_invoked"]) for row in arm_rows),
                "targeted_retraversal": sum(
                    bool(row["targeted_retraversal_invoked"]) for row in arm_rows
                ),
            },
            "path_proof_reason_counts": path_proof_reason_counts,
        }
        phase_values: dict[str, list[float]] = {
            "arm_total": [float(row["arm_elapsed_ms"]) for row in arm_rows],
            "answer_projection": [float(row["answer_projection_elapsed_ms"]) for row in arm_rows],
        }
        for phase in (
            "index_lookup",
            "evidence_scoring",
            "graph_traversal",
            "strict_projection",
            "fallback_repair",
        ):
            phase_values[phase] = [float(row["phase_elapsed_ms"][phase]) for row in arm_rows]
        latency_distributions_by_arm[arm_id] = {
            phase: {
                "total": round(sum(values), 3),
                "p50": _percentile(sorted(values), 0.50),
                "p95": _percentile(sorted(values), 0.95),
                "max": round(max(values), 3) if values else 0.0,
            }
            for phase, values in sorted(phase_values.items())
        }
    summary = {
        "artifact_id": SAFE_RELATION_TRACE_ARTIFACT_ID,
        "schema_version": 1,
        "status": "diagnostic",
        "case_arm_trace_count": len(rows),
        "behavior_fingerprint": _relation_trace_behavior_fingerprint(rows),
        "reason_counts_by_arm": reason_counts_by_arm,
        "latency_distributions_by_arm": latency_distributions_by_arm,
        "fallback_path_proof": _safe_fallback_path_proof_summary(rows),
        "claim_boundary": {
            "runtime_behavior_changed": False,
            "quality_gate_changed": False,
            "case_content_included": False,
            "source_identity_included": False,
            "independent_holdout": False,
            "methodology_complete": False,
        },
    }
    summary["summary_fingerprint"] = sha256_json(summary)
    assert_no_public_raw_references(summary, "issue56_relation_phase_trace_safe_summary")
    return summary


def _persist_relation_trace_reports(
    *,
    report: Mapping[str, Any],
    private_trace_rows: Sequence[Mapping[str, Any]],
    private_report_path: Path,
    safe_report_path: Path,
) -> None:
    safe_summary = _safe_relation_trace_summary(private_trace_rows)
    source_report_fingerprint = sha256_json(report)
    diagnostic_subset_only = report.get("diagnostic_subset_only") is True
    diagnostic_subset = report.get("diagnostic_subset")
    if diagnostic_subset_only and not isinstance(diagnostic_subset, Mapping):
        raise ContractValidationError("diagnostic subset metadata is required")
    diagnostic_subset_projection = (
        dict(diagnostic_subset) if isinstance(diagnostic_subset, Mapping) else None
    )
    private_payload: dict[str, Any] = {
        "artifact_id": PRIVATE_RELATION_TRACE_ARTIFACT_ID,
        "schema_version": 1,
        "status": "diagnostic",
        **(
            {
                "diagnostic_subset_only": True,
                "diagnostic_subset": diagnostic_subset_projection,
            }
            if diagnostic_subset_projection is not None
            else {}
        ),
        "source_report_fingerprint": source_report_fingerprint,
        "behavior_fingerprint": safe_summary["behavior_fingerprint"],
        "case_arm_traces": [
            dict(row)
            for row in sorted(
                private_trace_rows,
                key=lambda row: (
                    str(row["arm_id"]),
                    str(row["hashed_case_id"]),
                ),
            )
        ],
        "claim_boundary": dict(safe_summary["claim_boundary"]),
    }
    private_payload["report_fingerprint"] = sha256_json(private_payload)
    safe_payload = {
        **safe_summary,
        **(
            {
                "diagnostic_subset_only": True,
                "diagnostic_subset": diagnostic_subset_projection,
            }
            if diagnostic_subset_projection is not None
            else {}
        ),
        "source_report_fingerprint": source_report_fingerprint,
    }
    safe_payload["report_fingerprint"] = sha256_json(safe_payload)
    assert_no_public_raw_references(
        private_payload,
        "issue56_relation_phase_trace_private_report",
    )
    assert_no_public_raw_references(
        safe_payload,
        "issue56_relation_phase_trace_safe_report",
    )
    _write_json_report(private_report_path, private_payload, private_mode=True)
    _write_json_report(safe_report_path, safe_payload, private_mode=False)


def _write_json_report(
    path: Path,
    payload: Mapping[str, Any],
    *,
    private_mode: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    temporary_path.write_bytes(encoded)
    if private_mode:
        temporary_path.chmod(0o600)
    temporary_path.replace(path)


def _aggregate_arm(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    elapsed = sorted(float(row["elapsed_ms"]) for row in rows)
    cpu = sorted(float(row["cpu_ms"]) for row in rows)
    result_kind_counts = Counter(str(row["result_kind"]) for row in rows)
    query_class_counts = Counter(str(row["query_class"]) for row in rows)
    passed = sum(row["status"] == "passed" for row in rows)
    exact_rows = [row for row in rows if row["query_class"] == "exact_set_or_inventory"]
    permission_rows = [row for row in rows if row["result_kind"] == "permission_denied"]
    no_answer_rows = [row for row in rows if row["result_kind"] == "no_match"]
    owner_rows = [row for row in rows if row["result_kind"] == "owner_match"]
    predicted_no_answer_rows = [row for row in rows if row["predicted_no_answer"]]
    no_answer_true_positive = sum(
        row["result_kind"] == "no_match" for row in predicted_no_answer_rows
    )
    no_answer_false_positive = sum(
        row["result_kind"] == "owner_match" for row in predicted_no_answer_rows
    )
    required_evidence_count = sum(int(row["required_evidence_count"]) for row in owner_rows)
    matched_required_count = sum(int(row["matched_required_evidence_count"]) for row in owner_rows)
    citation_count = sum(int(row["citation_count"]) for row in owner_rows)
    citation_precision = _ratio_basis_points(
        matched_required_count,
        citation_count,
    )
    citation_recall = _ratio_basis_points(
        matched_required_count,
        required_evidence_count,
    )
    exact_required = sum(int(row["required_evidence_count"]) for row in exact_rows)
    exact_matched = sum(int(row["matched_required_evidence_count"]) for row in exact_rows)
    exact_citations = sum(int(row["citation_count"]) for row in exact_rows)
    exact_precision = _ratio(exact_matched, exact_citations)
    exact_recall = _ratio(exact_matched, exact_required)
    path_count = sum(int(row["graph_path_count"]) for row in rows)
    path_matches = sum(int(row["graph_path_required_match_count"]) for row in rows)
    return {
        "scored_case_count": len(rows),
        "passed_case_count": passed,
        "failed_case_count": len(rows) - passed,
        "pass_rate_basis_points": (round((passed * 10_000) / len(rows)) if rows else 0),
        "citation_count": sum(int(row["citation_count"]) for row in rows),
        "matched_required_evidence_count": sum(
            int(row["matched_required_evidence_count"]) for row in rows
        ),
        "forbidden_evidence_match_count": sum(
            int(row["forbidden_evidence_match_count"]) for row in rows
        ),
        "permission_denial_case_count": len(permission_rows),
        "permission_denial_passed_count": sum(row["status"] == "passed" for row in permission_rows),
        "no_answer_case_count": len(no_answer_rows),
        "no_answer_passed_count": sum(row["status"] == "passed" for row in no_answer_rows),
        "exact_case_count": len(exact_rows),
        "exact_complete_answer_count": sum(
            row["answer_status"] == "exact_complete" for row in exact_rows
        ),
        "final_answer_correctness_by_stratum": _aggregate_strata(rows),
        "citation_metrics": {
            "precision_basis_points": citation_precision,
            "recall_basis_points": citation_recall,
            "required_evidence_recall_at_k_basis_points": {
                str(k): _ratio_basis_points(
                    sum(int(row["required_evidence_recall_at_k"][str(k)]) for row in owner_rows),
                    required_evidence_count,
                )
                for k in (1, 3, 5, 10)
            },
            "required_bundle_coverage_basis_points": _ratio_basis_points(
                sum(bool(row["required_bundle_coverage_passed"]) for row in owner_rows),
                len(owner_rows),
            ),
        },
        "entity_resolution": {
            "active_case_count": sum(int(row["entity_signal_count"]) > 0 for row in rows),
            "required_evidence_proxy_recall_basis_points": citation_recall,
            "precision_recall_status": "missing_entity_oracle",
        },
        "evidence_identity_lineage": {
            "required_evidence_count": sum(
                int(row["required_evidence_count"]) for row in owner_rows
            ),
            "authorized_count": sum(
                int(row["required_lineage_authorized_count"]) for row in owner_rows
            ),
            "indexed_count": sum(int(row["required_lineage_indexed_count"]) for row in owner_rows),
            "occurrence_bound_count": sum(
                int(row["required_lineage_occurrence_bound_count"]) for row in owner_rows
            ),
            "graph_node_bound_count": sum(
                int(row["required_lineage_graph_node_bound_count"]) for row in owner_rows
            ),
            "graph_edge_bound_count": sum(
                int(row["required_lineage_graph_edge_bound_count"]) for row in owner_rows
            ),
            "graph_path_count": sum(
                int(row["required_lineage_graph_path_count"]) for row in owner_rows
            ),
            "final_citation_count": sum(
                int(row["required_lineage_final_citation_count"]) for row in owner_rows
            ),
            "exact_item_count": sum(
                int(row["required_lineage_exact_item_count"]) for row in owner_rows
            ),
            "unresolved_runtime_count": sum(
                int(row["lineage_audit_unresolved_count"]) for row in rows
            ),
        },
        "path_metrics": {
            "path_count": path_count,
            "adjudicated_required_match_count": path_matches,
            "adjudicated_precision_basis_points": _ratio_basis_points(
                path_matches,
                path_count,
            ),
            "forbidden_match_count": sum(
                int(row["graph_path_forbidden_match_count"]) for row in rows
            ),
            "unsupported_hop_rejected_count": sum(
                int(row["unsupported_hop_rejected_count"]) for row in rows
            ),
            "hop_count": sum(int(row["graph_hop_count"]) for row in rows),
            "authorized_evidence_hop_count": sum(
                int(row["graph_hop_authorized_evidence_count"]) for row in rows
            ),
            "unresolved_evidence_hop_count": sum(
                int(row["graph_hop_unresolved_evidence_count"]) for row in rows
            ),
            "positive_required_case_count": sum(
                bool(row["positive_required_graph_case"]) for row in rows
            ),
        },
        "temporal_metrics": {
            "current_score_count": sum(int(row["temporal_current_score_count"]) for row in rows),
            "superseded_score_count": sum(
                int(row["temporal_superseded_score_count"]) for row in rows
            ),
            "correctness_status": "missing_temporal_oracle",
        },
        "exact_metrics": {
            "evidence_proxy_precision_basis_points": round(exact_precision * 10_000),
            "evidence_proxy_recall_basis_points": round(exact_recall * 10_000),
            "evidence_proxy_f1_basis_points": round(_f1(exact_precision, exact_recall) * 10_000),
            "duplicate_item_count": sum(
                int(row["exact_duplicate_item_count"]) for row in exact_rows
            ),
            "complete_case_count": sum(
                row["exact_status"] == "complete_authorized_scope" for row in exact_rows
            ),
            "incomplete_case_count": sum(row["exact_status"] == "incomplete" for row in exact_rows),
            "item_oracle_status": "missing",
        },
        "no_answer_metrics": {
            "true_positive_count": no_answer_true_positive,
            "false_positive_count": no_answer_false_positive,
            "false_negative_count": len(no_answer_rows) - no_answer_true_positive,
            "precision_basis_points": _ratio_basis_points(
                no_answer_true_positive,
                no_answer_true_positive + no_answer_false_positive,
            ),
            "recall_basis_points": _ratio_basis_points(
                no_answer_true_positive,
                len(no_answer_rows),
            ),
        },
        "permission_metrics": {
            "denial_passed_count": sum(row["status"] == "passed" for row in permission_rows),
            "cross_scope_forbidden_match_count": sum(
                int(row["forbidden_evidence_match_count"]) for row in rows
            ),
        },
        "graph_signal_active_case_count": sum(int(row["graph_signal_count"]) > 0 for row in rows),
        "ontology_signal_active_case_count": sum(
            int(row["ontology_signal_count"]) > 0 for row in rows
        ),
        "result_kind_counts": dict(sorted(result_kind_counts.items())),
        "query_class_counts": dict(sorted(query_class_counts.items())),
        "latency_ms": {
            "total": round(sum(elapsed), 3),
            "p50": _percentile(elapsed, 0.50),
            "p95": _percentile(elapsed, 0.95),
            "max": round(max(elapsed), 3) if elapsed else 0.0,
        },
        "cpu_ms": {
            "total": round(sum(cpu), 3),
            "p50": _percentile(cpu, 0.50),
            "p95": _percentile(cpu, 0.95),
            "max": round(max(cpu), 3) if cpu else 0.0,
        },
        "cost_units": {
            "total": sum(int(row["cost_units"]) for row in rows),
            "average_milli": (
                round(sum(int(row["cost_units"]) for row in rows) * 1_000 / len(rows))
                if rows
                else 0
            ),
            "maximum": max((int(row["cost_units"]) for row in rows), default=0),
        },
        "aggregate_fingerprint": sha256_json(
            [
                {
                    "case_manifest_entry_hash": row["case_manifest_entry_hash"],
                    "status": row["status"],
                    "answer_hash": row["answer_hash"],
                    "source_result_fingerprint": row["source_result_fingerprint"],
                }
                for row in rows
            ]
        ),
    }


def _aggregate_strata(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    dimensions = (
        ("pattern", False),
        ("result_kind", False),
        ("query_class", False),
        ("domain_hash", True),
    )
    aggregates: dict[str, list[dict[str, Any]]] = {}
    for dimension, already_hashed in dimensions:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row[dimension]), []).append(row)
        aggregates[dimension] = []
        for value, stratum_rows in sorted(grouped.items()):
            required = sum(
                int(row["required_evidence_count"])
                for row in stratum_rows
                if row["result_kind"] == "owner_match"
            )
            matched = sum(
                int(row["matched_required_evidence_count"])
                for row in stratum_rows
                if row["result_kind"] == "owner_match"
            )
            citations = sum(
                int(row["citation_count"])
                for row in stratum_rows
                if row["result_kind"] == "owner_match"
            )
            aggregates[dimension].append(
                {
                    "stratum": value if not already_hashed else None,
                    "stratum_hash": value if already_hashed else sha256_json(value),
                    "case_count": len(stratum_rows),
                    "passed_case_count": sum(row["status"] == "passed" for row in stratum_rows),
                    "correctness_basis_points": _ratio_basis_points(
                        sum(row["status"] == "passed" for row in stratum_rows),
                        len(stratum_rows),
                    ),
                    "citation_precision_basis_points": _ratio_basis_points(
                        matched,
                        citations,
                    ),
                    "citation_recall_basis_points": _ratio_basis_points(
                        matched,
                        required,
                    ),
                }
            )
    return aggregates


def _rows_for_query_class(
    rows: Sequence[Mapping[str, Any]],
    query_class: str,
) -> list[Mapping[str, Any]]:
    return [row for row in rows if row["query_class"] == query_class]


def _rows_for_positive_graph_required(
    rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return [row for row in rows if bool(row["positive_required_graph_case"])]


def _budget_fairness_report(
    rows_by_arm: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    per_arm: dict[str, dict[str, str]] = {}
    for arm_id, rows in rows_by_arm.items():
        values = {
            str(row["case_manifest_entry_hash"]): str(row["execution_budget_fingerprint"])
            for row in rows
        }
        if len(values) != len(rows):
            raise ContractValidationError("execution budget case binding is not unique")
        per_arm[arm_id] = values
    baseline = per_arm["strong_rag"]
    full_case_match = all(per_arm[arm_id] == baseline for arm_id in FULL_CASE_ARM_IDS)
    structured_exact_match = all(
        baseline.get(case_hash) == fingerprint
        for case_hash, fingerprint in per_arm["structured_exact"].items()
    )
    return {
        "policy_id": EXECUTION_BUDGET_POLICY_ID,
        "policy_fingerprint": sha256_json(EXECUTION_BUDGET_POLICY_ID),
        "per_arm_fingerprint_set_hashes": {
            arm_id: sha256_json(sorted(values.values()))
            for arm_id, values in sorted(per_arm.items())
        },
        "all_full_case_arms_match_per_case": full_case_match,
        "structured_exact_matches_routed_cases": structured_exact_match,
        "candidate_limit": 24,
        "maximum_result_limit": 10,
        "evidence_budget": 10,
        "time_budget_ms": 1_500,
    }


def _quality_gate_report(
    *,
    arm_summaries: Mapping[str, Mapping[str, Any]],
    paired_transitions: Mapping[str, Mapping[str, Any]],
    budget_fairness: Mapping[str, Any],
) -> dict[str, Any]:
    strong = arm_summaries["strong_rag"]
    hybrid = arm_summaries["hybrid_v2_soft"]
    direct = paired_transitions["hybrid_v2_soft_vs_strong_rag_direct_cases"]
    graph_required = paired_transitions["hybrid_v2_soft_vs_strong_rag_graph_required"]
    direct_delta = int(direct["paired_correctness_delta_basis_points"])
    graph_delta = int(graph_required["paired_correctness_delta_basis_points"])
    graph_ci = graph_required["paired_ci_95_basis_points"]
    citation_precision = int(hybrid["citation_metrics"]["precision_basis_points"])
    baseline_no_answer = strong["no_answer_metrics"]
    hybrid_no_answer = hybrid["no_answer_metrics"]
    leakage_count = sum(
        int(arm_summaries[arm_id]["permission_metrics"]["cross_scope_forbidden_match_count"])
        for arm_id in FULL_CASE_ARM_IDS
    )
    denial_case_count = sum(
        int(arm_summaries[arm_id]["permission_denial_case_count"]) for arm_id in FULL_CASE_ARM_IDS
    )
    denial_passed_count = sum(
        int(arm_summaries[arm_id]["permission_denial_passed_count"]) for arm_id in FULL_CASE_ARM_IDS
    )
    graph_arm_ids = (
        "rag_candidate_kg",
        "hybrid_v2_soft",
        "legacy_hard_gate",
    )
    graph_hop_count = sum(
        int(arm_summaries[arm_id]["path_metrics"]["hop_count"]) for arm_id in graph_arm_ids
    )
    authorized_graph_hop_count = sum(
        int(arm_summaries[arm_id]["path_metrics"]["authorized_evidence_hop_count"])
        for arm_id in graph_arm_ids
    )
    unresolved_graph_hop_count = sum(
        int(arm_summaries[arm_id]["path_metrics"]["unresolved_evidence_hop_count"])
        for arm_id in graph_arm_ids
    )
    positive_required_graph_case_count = int(hybrid["path_metrics"]["positive_required_case_count"])

    checks: dict[str, dict[str, Any]] = {
        "execution_budget_fairness": {
            "status": (
                "passed"
                if (
                    budget_fairness["all_full_case_arms_match_per_case"]
                    and budget_fairness["structured_exact_matches_routed_cases"]
                )
                else "failed"
            ),
            "all_full_case_arms_match_per_case": bool(
                budget_fairness["all_full_case_arms_match_per_case"]
            ),
            "structured_exact_matches_routed_cases": bool(
                budget_fairness["structured_exact_matches_routed_cases"]
            ),
            "policy_fingerprint": str(budget_fairness["policy_fingerprint"]),
        },
        "direct_regression": {
            "status": (
                "passed" if direct_delta >= -DIRECT_REGRESSION_MAXIMUM_BASIS_POINTS else "failed"
            ),
            "maximum_regression_basis_points": (DIRECT_REGRESSION_MAXIMUM_BASIS_POINTS),
            "measured_delta_basis_points": direct_delta,
            "paired_case_count": int(direct["paired_case_count"]),
            "paired_ci_95_basis_points": dict(direct["paired_ci_95_basis_points"]),
        },
        "graph_required_gain": {
            "status": (
                "blocked"
                if positive_required_graph_case_count == 0
                else (
                    "passed"
                    if (
                        int(graph_required["paired_case_count"]) > 0
                        and graph_delta >= GRAPH_REQUIRED_GAIN_MINIMUM_BASIS_POINTS
                        and int(graph_ci["lower"]) >= 0
                    )
                    else "failed"
                )
            ),
            "minimum_gain_basis_points": (GRAPH_REQUIRED_GAIN_MINIMUM_BASIS_POINTS),
            "measured_delta_basis_points": graph_delta,
            "paired_case_count": int(graph_required["paired_case_count"]),
            "positive_required_case_count": positive_required_graph_case_count,
            "paired_ci_95_basis_points": dict(graph_ci),
            "requires_nonnegative_ci_lower_bound": True,
        },
        "graph_required_positive_evidence": {
            "status": ("passed" if positive_required_graph_case_count > 0 else "blocked"),
            "positive_required_case_count": positive_required_graph_case_count,
            "reason_hash": (
                None
                if positive_required_graph_case_count > 0
                else sha256_json("diagnostic_manifest_has_no_positive_required_relation_cases")
            ),
        },
        "citation_precision": {
            "status": (
                "passed"
                if citation_precision >= CITATION_PRECISION_MINIMUM_BASIS_POINTS
                else "failed"
            ),
            "minimum_basis_points": (CITATION_PRECISION_MINIMUM_BASIS_POINTS),
            "measured_basis_points": citation_precision,
        },
        "no_answer_non_regression": {
            "status": (
                "passed"
                if (
                    int(hybrid_no_answer["true_positive_count"])
                    >= int(baseline_no_answer["true_positive_count"])
                    and int(hybrid_no_answer["false_positive_count"])
                    <= int(baseline_no_answer["false_positive_count"])
                )
                else "failed"
            ),
            "baseline_true_positive_count": int(baseline_no_answer["true_positive_count"]),
            "candidate_true_positive_count": int(hybrid_no_answer["true_positive_count"]),
            "baseline_false_positive_count": int(baseline_no_answer["false_positive_count"]),
            "candidate_false_positive_count": int(hybrid_no_answer["false_positive_count"]),
        },
        "permission_leakage": {
            "status": (
                "passed"
                if leakage_count == 0 and denial_passed_count == denial_case_count
                else "failed"
            ),
            "cross_scope_match_count": leakage_count,
            "denial_case_count": denial_case_count,
            "denial_passed_count": denial_passed_count,
        },
        "graph_hop_evidence": {
            "status": (
                "passed"
                if (
                    graph_hop_count > 0
                    and unresolved_graph_hop_count == 0
                    and authorized_graph_hop_count == graph_hop_count
                )
                else "failed"
            ),
            "hop_count": graph_hop_count,
            "authorized_evidence_hop_count": authorized_graph_hop_count,
            "unresolved_evidence_hop_count": (unresolved_graph_hop_count),
        },
    }
    if FROZEN_LATENCY_BUDGET_MS is None or FROZEN_COST_UNIT_BUDGET_PER_CASE is None:
        checks["operational_budget"] = {
            "status": "blocked",
            "latency_budget_frozen": (FROZEN_LATENCY_BUDGET_MS is not None),
            "cost_budget_frozen": (FROZEN_COST_UNIT_BUDGET_PER_CASE is not None),
            "reason_hash": sha256_json("diagnostic_operational_budget_not_frozen"),
        }
    else:
        measured_latency = float(hybrid["latency_ms"]["p95"])
        measured_cost = int(hybrid["cost_units"]["average_milli"])
        cost_budget_milli = FROZEN_COST_UNIT_BUDGET_PER_CASE * 1_000
        checks["operational_budget"] = {
            "status": (
                "passed"
                if (
                    measured_latency <= FROZEN_LATENCY_BUDGET_MS
                    and measured_cost <= cost_budget_milli
                )
                else "failed"
            ),
            "latency_budget_frozen": True,
            "cost_budget_frozen": True,
            "latency_p95_budget_ms": FROZEN_LATENCY_BUDGET_MS,
            "measured_latency_p95_ms": measured_latency,
            "cost_budget_milli": cost_budget_milli,
            "measured_cost_average_milli": measured_cost,
        }
    statuses = {str(check["status"]) for check in checks.values()}
    if "blocked" in statuses:
        status = "blocked"
    elif "failed" in statuses:
        status = "failed"
    else:
        status = "passed"
    return {
        "gate_id": QUALITY_GATE_ID,
        "gate_fingerprint": sha256_json(
            {
                "gate_id": QUALITY_GATE_ID,
                "direct_regression_maximum_basis_points": (DIRECT_REGRESSION_MAXIMUM_BASIS_POINTS),
                "graph_required_gain_minimum_basis_points": (
                    GRAPH_REQUIRED_GAIN_MINIMUM_BASIS_POINTS
                ),
                "citation_precision_minimum_basis_points": (
                    CITATION_PRECISION_MINIMUM_BASIS_POINTS
                ),
                "frozen_latency_budget_ms": FROZEN_LATENCY_BUDGET_MS,
                "frozen_cost_unit_budget_per_case": (FROZEN_COST_UNIT_BUDGET_PER_CASE),
            }
        ),
        "status": status,
        "checks": checks,
    }


def _paired_transitions(
    baseline_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(baseline_rows) != len(candidate_rows):
        raise ContractValidationError("paired UAT arm lengths differ")
    transitions = Counter()
    paired_differences: list[int] = []
    for baseline, candidate in zip(baseline_rows, candidate_rows):
        if baseline["case_manifest_entry_hash"] != candidate["case_manifest_entry_hash"]:
            raise ContractValidationError("paired UAT case order differs")
        baseline_passed = baseline["status"] == "passed"
        candidate_passed = candidate["status"] == "passed"
        paired_differences.append(int(candidate_passed) - int(baseline_passed))
        if not baseline_passed and candidate_passed:
            transitions["improved"] += 1
        elif baseline_passed and not candidate_passed:
            transitions["regressed"] += 1
        elif baseline_passed:
            transitions["unchanged_pass"] += 1
        else:
            transitions["unchanged_fail"] += 1
    delta, lower, upper = _paired_normal_ci(paired_differences)
    return {
        "paired_case_count": len(baseline_rows),
        "improved_count": transitions["improved"],
        "regressed_count": transitions["regressed"],
        "unchanged_pass_count": transitions["unchanged_pass"],
        "unchanged_fail_count": transitions["unchanged_fail"],
        "paired_correctness_delta_basis_points": delta,
        "paired_ci_95_basis_points": {
            "lower": lower,
            "upper": upper,
            "method": "paired_normal_approximation",
        },
    }


def _paired_normal_ci(values: Sequence[int]) -> tuple[int, int, int]:
    if not values:
        return 0, 0, 0
    mean = sum(values) / len(values)
    if len(values) == 1:
        point = round(mean * 10_000)
        return point, point, point
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    margin = 1.96 * math.sqrt(variance / len(values))
    return (
        round(mean * 10_000),
        round(max(-1.0, mean - margin) * 10_000),
        round(min(1.0, mean + margin) * 10_000),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _ratio_basis_points(numerator: int, denominator: int) -> int:
    return round(_ratio(numerator, denominator) * 10_000)


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _aggregate_graph_builds(
    graph_builds: Mapping[str, Any],
    *,
    source_identifier_binding: Mapping[str, Any],
) -> dict[str, Any]:
    safe_builds = [
        graph_build.to_safe_dict()
        for _, graph_build in sorted(
            graph_builds.items(),
            key=lambda item: sha256_json(item[0]),
        )
    ]
    if not safe_builds:
        raise ContractValidationError("source-backed graph v2 build set is empty")
    expected_relation_hashes = sorted(sha256_json(value) for value in DIAGNOSTIC_RELATION_TYPES)
    expected_artifact_id = "formowl_issue56_source_backed_graph_build_v2"
    identity_build_bindings = {
        "identity_scope_mode": source_identifier_binding["identity_scope_mode_status"],
        "identity_scope_fingerprint": source_identifier_binding["identity_scope_fingerprint"],
        "identity_scope_attestation_fingerprint": source_identifier_binding[
            "identity_scope_attestation_fingerprint"
        ],
        "identity_scope_policy_fingerprint": source_identifier_binding[
            "identity_scope_policy_fingerprint"
        ],
        "operator_approval_fingerprint": source_identifier_binding["operator_approval_fingerprint"],
    }
    if (
        source_identifier_binding["identity_scope_mode_status"]
        == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    ):
        identity_build_bindings["spec_approval_fingerprint"] = source_identifier_binding[
            "spec_approval_fingerprint"
        ]
    for build in safe_builds:
        if (
            build.get("artifact_id") != expected_artifact_id
            or build.get("graph_policy_id") != SOURCE_GRAPH_POLICY_ID
            or build.get("candidate_graph_only") is not True
            or build.get("human_review_complete") is not False
            or build.get("relation_type_hashes") != expected_relation_hashes
            or any(
                build.get(field_name) != value
                for field_name, value in identity_build_bindings.items()
            )
        ):
            raise ContractValidationError("source-backed graph v2 build binding is invalid")
        for field_name in (
            "complete_identifier_mention_fingerprint",
            "authorized_identifier_mention_fingerprint",
            "identifier_resolution_fingerprint",
            "identity_scope_graph_binding_fingerprint",
        ):
            _require_sha256_fingerprint(
                build.get(field_name),
                f"source-backed graph v2 {field_name}",
            )
        if build.get("identifier_mention_count") != source_identifier_binding.get(
            "selected_mention_count"
        ):
            raise ContractValidationError("source-backed graph v2 mention count binding mismatch")
    complete_mention_fingerprints = sorted(
        {str(build["complete_identifier_mention_fingerprint"]) for build in safe_builds}
    )
    authorized_mention_fingerprints = sorted(
        {str(build["authorized_identifier_mention_fingerprint"]) for build in safe_builds}
    )
    resolution_fingerprints = sorted(
        {str(build["identifier_resolution_fingerprint"]) for build in safe_builds}
    )
    return {
        "permission_scoped_build_count": len(safe_builds),
        "source_observation_count": sum(
            int(build["source_observation_count"]) for build in safe_builds
        ),
        "observation_node_count": sum(
            int(build["observation_node_count"]) for build in safe_builds
        ),
        "entity_node_count": sum(int(build["entity_node_count"]) for build in safe_builds),
        "edge_count": sum(int(build["edge_count"]) for build in safe_builds),
        "ontology_typed_node_count": sum(
            int(build["ontology_typed_node_count"]) for build in safe_builds
        ),
        "build_fingerprint_set_hash": sha256_json(
            sorted(build["build_fingerprint"] for build in safe_builds)
        ),
        "ontology_revision_fingerprint_set_hash": sha256_json(
            sorted(
                sha256_json(graph_build.effective_graph_view.ontology_revision_id)
                for _, graph_build in sorted(
                    graph_builds.items(),
                    key=lambda item: sha256_json(item[0]),
                )
            )
        ),
        "graph_adapter_fingerprint": sha256_json(GRAPH_ADAPTER_ID),
        "source_graph_policy_fingerprint": sha256_json(SOURCE_GRAPH_POLICY_ID),
        "source_identifier_adapter_fingerprint": sha256_json(SOURCE_IDENTIFIER_ADAPTER_ID),
        "relation_type_hashes": expected_relation_hashes,
        "relation_type_hash_set_fingerprint": sha256_json(expected_relation_hashes),
        "complete_identifier_mention_fingerprint_set_hash": sha256_json(
            complete_mention_fingerprints
        ),
        "authorized_identifier_mention_fingerprint_set_hash": sha256_json(
            authorized_mention_fingerprints
        ),
        "identifier_resolution_fingerprint_set_hash": sha256_json(resolution_fingerprints),
        "identifier_mention_count": int(source_identifier_binding["selected_mention_count"]),
        "authorized_identifier_mention_count": sum(
            int(build["authorized_identifier_mention_count"]) for build in safe_builds
        ),
        "source_identifier_candidate_artifact_fingerprint": (
            source_identifier_binding["source_artifact_fingerprint"]
        ),
        "source_identifier_candidate_binding_fingerprint": (
            source_identifier_binding["binding_fingerprint"]
        ),
        "candidate_artifact_schema_fingerprint": source_identifier_binding[
            "candidate_artifact_schema_fingerprint"
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
        "extraction_policy_fingerprint": source_identifier_binding["extraction_policy_fingerprint"],
        "resolution_policy_fingerprint": source_identifier_binding["resolution_policy_fingerprint"],
        "selected_identifier_mention_batch_fingerprint": (
            source_identifier_binding["selected_mention_batch_fingerprint"]
        ),
        "selected_identifier_resolution_fingerprint": (
            source_identifier_binding["selected_resolution_fingerprint"]
        ),
        "selected_resolved_candidate_count": int(
            source_identifier_binding["selected_resolved_candidate_count"]
        ),
        "candidate_graph_only": True,
        "human_review_complete": False,
        **(
            {"spec_approval_fingerprint": source_identifier_binding["spec_approval_fingerprint"]}
            if source_identifier_binding["identity_scope_mode_status"]
            == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            else {}
        ),
    }


def _aggregate_lineage_crosswalks(
    crosswalks: Mapping[str, EvidenceIdentityLineageCrosswalk],
) -> dict[str, Any]:
    ordered = [
        crosswalk
        for _, crosswalk in sorted(
            crosswalks.items(),
            key=lambda item: sha256_json(item[0]),
        )
    ]
    return {
        "permission_scoped_crosswalk_count": len(ordered),
        "authorized_evidence_count": sum(
            crosswalk.authorized_evidence_count for crosswalk in ordered
        ),
        "indexed_evidence_count": sum(crosswalk.indexed_evidence_count for crosswalk in ordered),
        "occurrence_bound_evidence_count": sum(
            crosswalk.occurrence_bound_evidence_count for crosswalk in ordered
        ),
        "graph_node_bound_evidence_count": sum(
            crosswalk.graph_node_bound_evidence_count for crosswalk in ordered
        ),
        "graph_edge_bound_evidence_count": sum(
            crosswalk.graph_edge_bound_evidence_count for crosswalk in ordered
        ),
        "crosswalk_fingerprint_set_hash": sha256_json(
            sorted(crosswalk.crosswalk_fingerprint for crosswalk in ordered)
        ),
        "hash_only": True,
        "adjudication_input": False,
    }


def _peak_memory_kib() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _bounded_preserved_projection(
    *,
    bundle_payload: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_byte_hash: str,
    observations_directory: Path,
) -> tuple[MailEvidenceBundle, "_LazyObservationSubset"]:
    cases = manifest["cases"]
    adjudicated_ids = {
        str(observation_id)
        for case in cases
        for field_name in (
            "required_source_observation_ids",
            "forbidden_source_observation_ids",
        )
        for observation_id in case[field_name]
    }
    body_payloads = bundle_payload.get("body_segments")
    message_payloads = bundle_payload.get("messages")
    if not isinstance(body_payloads, list) or not isinstance(
        message_payloads,
        list,
    ):
        raise ContractValidationError("preserved bundle projection is unavailable")
    body_by_source_id = {
        str(item.get("source_observation_id")): item
        for item in body_payloads
        if isinstance(item, dict) and isinstance(item.get("source_observation_id"), str)
    }
    if adjudicated_ids - set(body_by_source_id):
        raise ContractValidationError("adjudicated source Observation lineage is unavailable")
    decoy_ids = sorted(
        set(body_by_source_id) - adjudicated_ids,
        key=lambda observation_id: sha256_json(
            {
                "policy": CORPUS_POLICY_ID,
                "manifest_byte_hash": manifest_byte_hash,
                "observation_id": observation_id,
            }
        ),
    )[:MAX_DECOY_SEGMENTS]
    selected_ids = tuple(sorted(adjudicated_ids | set(decoy_ids)))
    selected_body_payloads = [body_by_source_id[observation_id] for observation_id in selected_ids]
    selected_message_ids = {str(item["email_message_id"]) for item in selected_body_payloads}
    message_by_id = {
        str(item.get("email_message_id")): item
        for item in message_payloads
        if isinstance(item, dict) and isinstance(item.get("email_message_id"), str)
    }
    if selected_message_ids - set(message_by_id):
        raise ContractValidationError("preserved bundle message lineage is unavailable")
    import_session_payload = bundle_payload.get("mail_import_session")
    parse_run_payload = bundle_payload.get("mail_parse_run")
    if not isinstance(import_session_payload, dict) or not isinstance(
        parse_run_payload,
        dict,
    ):
        raise ContractValidationError("preserved bundle metadata is unavailable")
    bundle = MailEvidenceBundle(
        mail_evidence_bundle_id=str(bundle_payload["mail_evidence_bundle_id"]),
        producer_type=str(bundle_payload["producer_type"]),
        mail_import_session=MailImportSession.from_dict(import_session_payload),
        archive_occurrences=[],
        folder_occurrences=[],
        messages=[
            EmailMessage.from_dict(message_by_id[email_message_id])
            for email_message_id in sorted(selected_message_ids)
        ],
        message_occurrences=[],
        body_segments=[EmailBodySegment.from_dict(item) for item in selected_body_payloads],
        attachments=[],
        attachment_occurrences=[],
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=MailParseRun.from_dict(parse_run_payload),
        parse_warnings=[],
        created_at=str(bundle_payload["created_at"]),
    )
    observations = _LazyObservationSubset(
        bundle_id=bundle.mail_evidence_bundle_id,
        observations_directory=observations_directory,
        selected_observation_ids=selected_ids,
        expected_segments=body_by_source_id,
    )
    return bundle, observations


class _LazyObservationSubset(Mapping[str, Sequence[Observation]]):
    def __init__(
        self,
        *,
        bundle_id: str,
        observations_directory: Path,
        selected_observation_ids: Sequence[str],
        expected_segments: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self._bundle_id = bundle_id
        self._observations_directory = observations_directory
        self._selected_observation_ids = tuple(selected_observation_ids)
        self._expected_segments = expected_segments
        self._loaded: tuple[Observation, ...] | None = None
        self._source_observation_hash_by_id: dict[str, str] = {}

    @property
    def selected_observation_count(self) -> int:
        return len(self._selected_observation_ids)

    @property
    def loaded_observation_count(self) -> int:
        return len(self._loaded or ())

    @property
    def source_observation_hash_by_id(self) -> Mapping[str, str]:
        return dict(self._source_observation_hash_by_id)

    def __getitem__(self, key: str) -> Sequence[Observation]:
        if key != self._bundle_id:
            raise KeyError(key)
        if self._loaded is None:
            self._loaded = self._load()
        return self._loaded

    def __iter__(self) -> Iterator[str]:
        yield self._bundle_id

    def __len__(self) -> int:
        return 1

    def _load(self) -> tuple[Observation, ...]:
        observations: list[Observation] = []
        for observation_id in self._selected_observation_ids:
            try:
                payload = json.loads(
                    (self._observations_directory / f"{observation_id}.json").read_text(
                        encoding="utf-8"
                    )
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise ContractValidationError(
                    "preserved Observation subset is unavailable"
                ) from exc
            observation = Observation.from_dict(payload)
            expected = self._expected_segments[observation_id]
            if (
                observation.observation_id != observation_id
                or observation.observation_type != "email_body_segment"
                or observation.modality != "mail"
                or observation.text != expected.get("text")
                or _observation_occurrence_id(observation) != expected.get("message_occurrence_id")
            ):
                raise ContractValidationError("preserved Observation lineage mismatch")
            observation_hash = sha256_json(observation.to_dict())
            self._source_observation_hash_by_id[observation_id] = observation_hash
            observations.append(observation)
        return tuple(observations)


def _observation_occurrence_id(observation: Observation) -> str | None:
    for source in (observation.location, observation.payload or {}):
        value = source.get("message_occurrence_id")
        if isinstance(value, str):
            return value
    return None


def _load_native_retrieval_ready_bundle_intake(
    *,
    bundle_artifact_path: Path | None,
    expected_bundle_artifact_sha256: str | None,
    report_path: Path | None,
    expected_report_sha256: str | None,
) -> _NativeRetrievalReadyBundleIntake:
    if (
        bundle_artifact_path is None
        or expected_bundle_artifact_sha256 is None
        or report_path is None
        or expected_report_sha256 is None
    ):
        raise ContractValidationError(
            "retrieval-ready bundle artifact, report, and seals are required together"
        )
    artifact_bytes = _read_private_bytes(
        bundle_artifact_path,
        blocker="retrieval_ready_bundle_artifact_unavailable",
    )
    artifact_byte_hash = _sha256_bytes(artifact_bytes)
    _validate_expected_byte_seal(
        actual_sha256=artifact_byte_hash,
        expected_sha256=expected_bundle_artifact_sha256,
        label="retrieval-ready bundle artifact",
    )
    artifact = _read_json_object(
        artifact_bytes,
        blocker="retrieval_ready_bundle_artifact_invalid",
    )
    bundle_payload = _validate_native_mail_evidence_bundle_artifact(artifact)

    report_bytes = _read_private_bytes(
        report_path,
        blocker="retrieval_ready_report_unavailable",
    )
    report_byte_hash = _sha256_bytes(report_bytes)
    _validate_expected_byte_seal(
        actual_sha256=report_byte_hash,
        expected_sha256=expected_report_sha256,
        label="retrieval-ready report",
    )
    report = _read_json_object(
        report_bytes,
        blocker="retrieval_ready_report_invalid",
    )
    _validate_native_retrieval_ready_report(report)
    _validate_native_retrieval_ready_cross_binding(
        artifact=artifact,
        report=report,
        bundle_payload=bundle_payload,
    )

    safe_binding = {
        "status": "sealed_passed",
        "bundle_artifact_id": NATIVE_MAIL_EVIDENCE_BUNDLE_ARTIFACT_ID,
        "bundle_artifact_byte_hash": artifact_byte_hash,
        "bundle_artifact_fingerprint": artifact["artifact_fingerprint"],
        "mail_evidence_bundle_fingerprint": artifact["bundle_fingerprint"],
        "retrieval_report_artifact_id": NATIVE_RETRIEVAL_READY_REPORT_ARTIFACT_ID,
        "retrieval_report_byte_hash": report_byte_hash,
        "retrieval_report_fingerprint": report["report_fingerprint"],
        "source_snapshot_fingerprint": report["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": report["source_inventory_fingerprint"],
        "source_provenance_fingerprint": report["source_provenance_fingerprint"],
        "index_fingerprint": report["index_fingerprint"],
        "candidate_admission_profile_fingerprint": report[
            "candidate_admission_profile_fingerprint"
        ],
        "permission_fingerprint": report["permission_fingerprint"],
        "retrieval_snapshot_fingerprint": report["retrieval_snapshot_fingerprint"],
    }
    safe_binding["input_binding_fingerprint"] = sha256_json(safe_binding)
    assert_no_public_raw_references(
        safe_binding,
        "issue56_native_retrieval_ready_uat_binding",
    )
    return _NativeRetrievalReadyBundleIntake(
        bundle_payload=bundle_payload,
        safe_binding=safe_binding,
    )


def _load_source_identifier_candidate_intake(
    *,
    artifact_path: Path | None,
    expected_artifact_sha256: str | None,
    expected_identity_scope_fingerprint: str | None,
    expected_workspace_id: str,
    selected_observations_by_id: Mapping[str, Observation],
    selected_observation_hash_by_id: Mapping[str, str],
    retrieval_ready_binding: Mapping[str, Any] | None,
) -> _SourceIdentifierCandidateIntake:
    if (
        artifact_path is None
        or expected_artifact_sha256 is None
        or expected_identity_scope_fingerprint is None
    ):
        raise ContractValidationError(
            "source identifier candidate artifact, byte seal, and "
            "identity scope fingerprint are required"
        )
    _require_sha256_fingerprint(
        expected_identity_scope_fingerprint,
        "expected identity scope fingerprint",
    )
    artifact_bytes = _read_private_bytes(
        artifact_path,
        blocker="source_identifier_candidate_artifact_unavailable",
    )
    artifact_byte_hash = _sha256_bytes(artifact_bytes)
    _validate_expected_byte_seal(
        actual_sha256=artifact_byte_hash,
        expected_sha256=expected_artifact_sha256,
        label="source identifier candidate artifact",
    )
    artifact = _read_json_object(
        artifact_bytes,
        blocker="source_identifier_candidate_artifact_invalid",
    )
    if (
        artifact.get("artifact_id") != SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID
        or artifact.get("schema_version") != SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION
    ):
        raise ContractValidationError(
            "source identifier candidate artifact v3 identity-scope contract is required"
        )
    try:
        validate_private_identifier_candidate_artifact(artifact)
    except SourceIdentifierCandidateError as exc:
        raise ContractValidationError(exc.reason_code) from exc

    identity_binding = artifact.get("identity_scope_binding")
    batch_payload = artifact.get("mention_batch")
    resolution_payload = artifact.get("resolution")
    counts = artifact.get("counts")
    if not all(
        isinstance(value, Mapping)
        for value in (identity_binding, batch_payload, resolution_payload, counts)
    ):
        raise ContractValidationError("source identifier candidate artifact binding is invalid")
    try:
        identity_scope = SourceIdentifierIdentityScope(**dict(identity_binding))
    except (ContractValidationError, TypeError) as exc:
        raise ContractValidationError(
            "source identifier candidate identity scope binding is invalid"
        ) from exc
    if (
        artifact.get("identity_scope_mode") != identity_scope.identity_scope_mode
        or identity_scope.identity_scope_fingerprint != expected_identity_scope_fingerprint
        or identity_scope.workspace_id != expected_workspace_id
    ):
        raise ContractValidationError("source identifier candidate identity scope binding mismatch")
    if identity_scope.identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        if identity_scope.tenant_id is None or identity_scope.spec_approval_fingerprint is not None:
            raise ContractValidationError(
                "source identifier candidate tenant identity scope is invalid"
            )
    elif identity_scope.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        if identity_scope.tenant_id is not None or identity_scope.spec_approval_fingerprint is None:
            raise ContractValidationError(
                "source identifier candidate workspace-only identity scope is invalid"
            )
    else:  # defensive; SourceIdentifierIdentityScope already rejects this.
        raise ContractValidationError("source identifier candidate identity scope mode is invalid")
    if (
        artifact.get("candidate_only") is not True
        or artifact.get("canonical_write_allowed") is not False
        or artifact.get("overflow_count") != 0
        or counts.get("overflow_count") != 0
    ):
        raise ContractValidationError("source identifier candidate claim boundary is invalid")
    if retrieval_ready_binding is not None:
        retrieval_cross_bindings = {
            "source_snapshot_fingerprint": "source_snapshot_fingerprint",
            "source_inventory_fingerprint": "source_inventory_fingerprint",
            "retrieval_snapshot_fingerprint": "retrieval_snapshot_fingerprint",
            "retrieval_report_fingerprint": "retrieval_report_fingerprint",
            "retrieval_report_byte_sha256": "retrieval_report_byte_hash",
            "tokenizer_profile_fingerprint": ("candidate_admission_profile_fingerprint"),
        }
        if any(
            artifact.get(artifact_field) != retrieval_ready_binding.get(retrieval_field)
            for artifact_field, retrieval_field in retrieval_cross_bindings.items()
        ):
            raise ContractValidationError("source identifier candidate retrieval binding mismatch")

    source_hashes = artifact.get("source_observation_hashes")
    if not isinstance(source_hashes, list):
        raise ContractValidationError("source identifier candidate source hash set is invalid")
    selected_hashes = sorted(selected_observation_hash_by_id.values())
    if len(selected_hashes) != len(selected_observation_hash_by_id) or not set(
        selected_hashes
    ).issubset(source_hashes):
        raise ContractValidationError(
            "source identifier candidate selected Observation coverage is incomplete"
        )

    raw_mentions = batch_payload.get("candidate_mentions")
    if not isinstance(raw_mentions, list):
        raise ContractValidationError("source identifier candidate mention batch is invalid")
    try:
        complete_mentions = tuple(
            sorted(
                (CandidateMention.from_dict(row) for row in raw_mentions),
                key=lambda item: item.candidate_mention_id,
            )
        )
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError(
            "source identifier candidate mention replay is invalid"
        ) from exc
    selected_observation_ids = set(selected_observation_hash_by_id)
    if set(selected_observations_by_id) != selected_observation_ids:
        raise ContractValidationError(
            "source identifier candidate selected Observation binding is invalid"
        )
    target_profile = load_issue56_target_mail_tokenizer_profile()
    expected_occurrences: set[tuple[str, int, int, str, str]] = set()
    for observation_id, observation in sorted(selected_observations_by_id.items()):
        if sha256_json(observation.to_dict()) != selected_observation_hash_by_id[observation_id]:
            raise ContractValidationError(
                "source identifier candidate selected Observation seal mismatch"
            )
        if not isinstance(observation.text, str) or not observation.text:
            continue
        analysis = target_profile.analyze(observation.text)
        expected_occurrences.update(
            (
                observation_id,
                span.start,
                span.end,
                span.identifier_kind,
                sha256_json(span.exact_token),
            )
            for span in analysis.protected_identifiers
        )
    projected_mentions: list[CandidateMention] = []
    actual_occurrences: set[tuple[str, int, int, str, str]] = set()
    expected_identity_scope_fields = identity_scope.to_dict()
    for mention in complete_mentions:
        if len(mention.source_observation_ids) != 1:
            raise ContractValidationError("source identifier candidate mention lineage is invalid")
        observation_id = mention.source_observation_ids[0]
        if observation_id not in selected_observation_ids:
            continue
        if (
            mention.metadata.get("source_observation_fingerprint")
            != selected_observation_hash_by_id[observation_id]
        ):
            raise ContractValidationError(
                "source identifier candidate Observation fingerprint mismatch"
            )
        observation = selected_observations_by_id[observation_id]
        occurrence_id = _observation_occurrence_id(observation)
        location = mention.location
        metadata = mention.metadata
        expected_source_provenance_fingerprint = sha256_json(
            {
                "asset_id": observation.asset_id,
                "evidence_snapshot_id": observation.evidence_snapshot_id,
                "extractor_run_id": observation.extractor_run_id,
                "modality": observation.modality,
                "observation_type": observation.observation_type,
            }
        )
        if (
            occurrence_id is None
            or location.get("source_observation_id") != observation_id
            or location.get("message_occurrence_fingerprint") != sha256_json(occurrence_id)
            or location.get("source_locator_fingerprint") != sha256_json(observation.location)
            or location.get("permission_boundary_fingerprint")
            != sha256_json(observation.permission_scope)
            or metadata.get("permission_scope") != dict(observation.permission_scope)
            or metadata.get("permission_boundary_fingerprint")
            != sha256_json(observation.permission_scope)
            or metadata.get("source_locator_fingerprint") != sha256_json(observation.location)
            or metadata.get("message_occurrence_fingerprint") != sha256_json(occurrence_id)
            or metadata.get("source_extractor_provenance_fingerprint")
            != expected_source_provenance_fingerprint
            or metadata.get("exact_protected_token_hash") != mention.text_hash
            or any(
                metadata.get(field_name) != value or location.get(field_name) != value
                for field_name, value in expected_identity_scope_fields.items()
            )
        ):
            raise ContractValidationError(
                "source identifier candidate permission, occurrence, or identity binding mismatch"
            )
        if (
            identity_scope.identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE
            and ("spec_approval_fingerprint" in metadata or "spec_approval_fingerprint" in location)
        ) or (
            identity_scope.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            and ("tenant_id" in metadata or "tenant_id" in location)
        ):
            raise ContractValidationError(
                "source identifier candidate identity mode fields are invalid"
            )
        try:
            actual_occurrence = (
                observation_id,
                int(location["span_start"]),
                int(location["span_end"]),
                str(location["identifier_kind"]),
                str(mention.text_hash),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError(
                "source identifier candidate span binding is invalid"
            ) from exc
        if actual_occurrence in actual_occurrences:
            raise ContractValidationError("source identifier candidate occurrence is duplicated")
        actual_occurrences.add(actual_occurrence)
        projected_mentions.append(mention)
    if actual_occurrences != expected_occurrences:
        raise ContractValidationError("source identifier candidate occurrence coverage mismatch")
    projected_mentions.sort(key=lambda item: item.candidate_mention_id)
    projected_batch_fingerprint = sha256_json(
        {
            "candidate_mention_ids": [
                mention.candidate_mention_id for mention in projected_mentions
            ],
            "extraction_policy_fingerprint": artifact["extraction_policy_fingerprint"],
            "identity_scope": identity_scope.to_dict(),
            "tokenizer_profile_fingerprint": artifact["tokenizer_profile_fingerprint"],
        }
    )
    projected_batch = SourceBoundIdentifierMentionBatch(
        candidate_mentions=tuple(projected_mentions),
        tokenizer_id=str(artifact["tokenizer_id"]),
        tokenizer_profile_fingerprint=str(artifact["tokenizer_profile_fingerprint"]),
        extraction_policy_id=str(artifact["extraction_policy_id"]),
        extraction_policy_fingerprint=str(artifact["extraction_policy_fingerprint"]),
        identity_scope_mode=identity_scope.identity_scope_mode,
        identity_scope_fingerprint=identity_scope.identity_scope_fingerprint,
        workspace_id=identity_scope.workspace_id,
        identity_scope_attestation_fingerprint=(
            identity_scope.identity_scope_attestation_fingerprint
        ),
        identity_scope_policy_fingerprint=identity_scope.identity_scope_policy_fingerprint,
        operator_approval_fingerprint=identity_scope.operator_approval_fingerprint,
        tenant_id=identity_scope.tenant_id,
        spec_approval_fingerprint=identity_scope.spec_approval_fingerprint,
        occurrence_count=len(projected_mentions),
        batch_fingerprint=projected_batch_fingerprint,
    )
    try:
        selected_resolution = resolve_exact_protected_identifier_candidates(
            projected_batch.candidate_mentions
        )
    except ContractValidationError as exc:
        raise ContractValidationError(
            "source identifier candidate selected resolution is invalid"
        ) from exc
    if (
        resolution_payload.get("resolution_policy_id") != selected_resolution.resolution_policy_id
        or artifact.get("resolution_policy_fingerprint")
        != SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT
    ):
        raise ContractValidationError("source identifier candidate resolution policy mismatch")

    relation_type_hashes = sorted(sha256_json(value) for value in DIAGNOSTIC_RELATION_TYPES)
    identity_scope_binding_fingerprint = sha256_json(identity_scope.to_dict())
    mode_approval_fingerprint = sha256_json(
        {
            "identity_scope_mode": identity_scope.identity_scope_mode,
            "operator_approval_fingerprint": identity_scope.operator_approval_fingerprint,
            "spec_approval_fingerprint": identity_scope.spec_approval_fingerprint,
        }
    )
    safe_binding: dict[str, Any] = {
        "status": "sealed_passed",
        "binding_id": SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
        "candidate_artifact_schema_version": SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
        "candidate_artifact_schema_fingerprint": sha256_json(
            {
                "artifact_id": SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
                "schema_version": SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
            }
        ),
        "source_artifact_byte_hash": artifact_byte_hash,
        "source_artifact_fingerprint": artifact["artifact_fingerprint"],
        "source_snapshot_fingerprint": artifact["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": artifact["source_inventory_fingerprint"],
        "source_observation_hash_set_fingerprint": artifact[
            "source_observation_hash_set_fingerprint"
        ],
        "retrieval_snapshot_fingerprint": artifact["retrieval_snapshot_fingerprint"],
        "retrieval_report_fingerprint": artifact["retrieval_report_fingerprint"],
        "candidate_admission_profile_fingerprint": artifact["tokenizer_profile_fingerprint"],
        "extraction_policy_fingerprint": artifact["extraction_policy_fingerprint"],
        "resolution_policy_fingerprint": artifact["resolution_policy_fingerprint"],
        "identity_scope_mode_status": identity_scope.identity_scope_mode,
        "identity_scope_mode_fingerprint": sha256_json(identity_scope.identity_scope_mode),
        "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
        "identity_scope_binding_fingerprint": identity_scope_binding_fingerprint,
        "identity_scope_attestation_byte_sha256": artifact[
            "identity_scope_attestation_byte_sha256"
        ],
        "identity_scope_attestation_fingerprint": (
            identity_scope.identity_scope_attestation_fingerprint
        ),
        "identity_scope_policy_fingerprint": identity_scope.identity_scope_policy_fingerprint,
        "operator_approval_fingerprint": identity_scope.operator_approval_fingerprint,
        "mode_approval_fingerprint": mode_approval_fingerprint,
        "workspace_scope_fingerprint": sha256_json(identity_scope.workspace_id),
        "complete_mention_batch_fingerprint": batch_payload["batch_fingerprint"],
        "complete_resolution_fingerprint": resolution_payload["resolution_fingerprint"],
        "complete_mention_count": int(counts["identifier_occurrence_count"]),
        "complete_resolved_candidate_count": int(counts["resolved_candidate_count"]),
        "selected_mention_batch_fingerprint": projected_batch.batch_fingerprint,
        "selected_resolution_fingerprint": selected_resolution.resolution_fingerprint,
        "selected_mention_count": projected_batch.occurrence_count,
        "selected_resolved_candidate_count": selected_resolution.candidate_count,
        "overflow_count": 0,
        "candidate_graph_only": True,
        "canonical_write_allowed": False,
        "source_graph_policy_fingerprint": sha256_json(SOURCE_GRAPH_POLICY_ID),
        "source_identifier_adapter_fingerprint": sha256_json(SOURCE_IDENTIFIER_ADAPTER_ID),
        "relation_type_hashes": relation_type_hashes,
        "relation_type_hash_set_fingerprint": sha256_json(relation_type_hashes),
    }
    if identity_scope.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        safe_binding["spec_approval_fingerprint"] = identity_scope.spec_approval_fingerprint
    safe_binding["binding_fingerprint"] = sha256_json(safe_binding)
    assert_no_public_raw_references(
        safe_binding,
        "issue56_source_identifier_candidate_uat_binding_v3",
    )
    return _SourceIdentifierCandidateIntake(
        projected_batch=projected_batch,
        safe_binding=safe_binding,
    )


def _validate_native_mail_evidence_bundle_artifact(
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    required_fields = {
        "artifact_id",
        "schema_version",
        "status",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "bundle",
        "bundle_fingerprint",
        "artifact_fingerprint",
    }
    if set(artifact) != required_fields:
        raise ContractValidationError("retrieval-ready bundle artifact schema is invalid")
    if artifact.get("artifact_id") != NATIVE_MAIL_EVIDENCE_BUNDLE_ARTIFACT_ID:
        raise ContractValidationError("retrieval-ready bundle artifact identity is invalid")
    if artifact.get("schema_version") != 1 or artifact.get("status") != "passed":
        raise ContractValidationError("retrieval-ready bundle artifact status is invalid")
    for field_name in (
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "bundle_fingerprint",
        "artifact_fingerprint",
    ):
        _require_sha256_fingerprint(
            artifact.get(field_name),
            f"retrieval-ready bundle artifact {field_name}",
        )
    if artifact["artifact_fingerprint"] != _payload_fingerprint(
        artifact,
        "artifact_fingerprint",
    ):
        raise ContractValidationError("retrieval-ready bundle artifact fingerprint mismatch")
    bundle_payload = artifact.get("bundle")
    if not isinstance(bundle_payload, dict):
        raise ContractValidationError("retrieval-ready mail evidence bundle is invalid")
    if artifact["bundle_fingerprint"] != sha256_json(bundle_payload):
        raise ContractValidationError("retrieval-ready mail evidence bundle fingerprint mismatch")
    try:
        bundle = MailEvidenceBundle.from_dict(bundle_payload)
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError("retrieval-ready mail evidence bundle is invalid") from exc
    if bundle.to_dict() != bundle_payload:
        raise ContractValidationError("retrieval-ready mail evidence bundle round trip mismatch")
    return bundle_payload


def _validate_native_retrieval_ready_report(report: Mapping[str, Any]) -> None:
    required_statuses = {
        "status": "passed",
        "source_completeness_status": "passed",
        "retrieval_ready_status": "passed",
        "bundle_round_trip_status": "passed",
        "query_evidence_profile_binding_status": "passed",
        "target_profile_status": "passed_no_ascii_fallback",
        "authorized_query_status": "passed",
        "denied_query_status": "passed_fail_closed",
        "canonical_fact_status": "not_asserted",
        "methodology_readiness_status": "blocked",
    }
    if report.get("artifact_id") != NATIVE_RETRIEVAL_READY_REPORT_ARTIFACT_ID:
        raise ContractValidationError("retrieval-ready report identity is invalid")
    if report.get("schema_version") != 1:
        raise ContractValidationError("retrieval-ready report schema is invalid")
    if any(report.get(field_name) != value for field_name, value in required_statuses.items()):
        raise ContractValidationError("retrieval-ready report status is invalid")
    required_fingerprints = {
        "source_asset_fingerprint",
        "native_manifest_fingerprint",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "permission_fingerprint",
        "parsed_observation_fingerprint",
        "mail_evidence_bundle_fingerprint",
        "candidate_admission_profile_fingerprint",
        "observation_snapshot_fingerprint",
        "candidate_manifest_fingerprint",
        "index_fingerprint",
        "query_fingerprint",
        "authorized_result_fingerprint",
        "authorized_cited_observation_fingerprint",
        "denied_result_fingerprint",
        "retrieval_snapshot_fingerprint",
        "bundle_artifact_fingerprint",
        "report_fingerprint",
    }
    if not required_fingerprints.issubset(report):
        raise ContractValidationError("retrieval-ready report fingerprint binding is incomplete")
    for field_name in required_fingerprints:
        _require_sha256_fingerprint(
            report.get(field_name),
            f"retrieval-ready report {field_name}",
        )
    if report["report_fingerprint"] != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise ContractValidationError("retrieval-ready report fingerprint mismatch")
    if report.get("blocker_fingerprints") != []:
        raise ContractValidationError("retrieval-ready report contains blockers")
    counts = report.get("counts")
    if not isinstance(counts, dict) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in counts.values()
    ):
        raise ContractValidationError("retrieval-ready report counts are invalid")
    for field_name in (
        "missing_source_inventory_binding_count",
        "missing_source_local_key_binding_count",
        "missing_content_hash_binding_count",
        "missing_permission_binding_count",
        "unexplained_loss_count",
        "blocker_count",
    ):
        if counts.get(field_name) != 0:
            raise ContractValidationError("retrieval-ready report source binding is incomplete")
    allowed_fixed_fields = {
        "artifact_id",
        "schema_version",
        "status",
        "counts",
        "blocker_fingerprints",
    }
    for field_name, value in report.items():
        if field_name.endswith("_fingerprint"):
            _require_sha256_fingerprint(
                value,
                f"retrieval-ready report {field_name}",
            )
        elif field_name.endswith("_status"):
            if not isinstance(value, str) or not value:
                raise ContractValidationError("retrieval-ready report status field is invalid")
        elif field_name not in allowed_fixed_fields:
            raise ContractValidationError("retrieval-ready report public schema is invalid")
    assert_no_public_raw_references(
        report,
        "issue56_native_retrieval_ready_uat_report",
    )


def _validate_native_retrieval_ready_cross_binding(
    *,
    artifact: Mapping[str, Any],
    report: Mapping[str, Any],
    bundle_payload: Mapping[str, Any],
) -> None:
    matching_fields = {
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "bundle_fingerprint": "mail_evidence_bundle_fingerprint",
        "artifact_fingerprint": "bundle_artifact_fingerprint",
    }
    if any(
        artifact[artifact_field] != report[report_field]
        for artifact_field, report_field in matching_fields.items()
    ):
        raise ContractValidationError("retrieval-ready bundle artifact and report binding mismatch")
    import_session = bundle_payload.get("mail_import_session")
    if (
        not isinstance(import_session, Mapping)
        or import_session.get("archive_sha256") != report["source_asset_fingerprint"]
    ):
        raise ContractValidationError("retrieval-ready source asset and bundle binding mismatch")
    lexical_profile = load_issue56_target_mail_tokenizer_profile()
    if report["candidate_admission_profile_fingerprint"] != lexical_profile.profile_fingerprint:
        raise ContractValidationError("retrieval-ready tokenizer profile binding mismatch")


def _validate_expected_byte_seal(
    *,
    actual_sha256: str,
    expected_sha256: str,
    label: str,
) -> None:
    _require_sha256_fingerprint(expected_sha256, f"{label} seal")
    if actual_sha256 != expected_sha256:
        raise ContractValidationError(f"{label} seal mismatch")


def _require_sha256_fingerprint(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ContractValidationError(f"{label} is invalid")
    return value


def _payload_fingerprint(
    payload: Mapping[str, Any],
    field_name: str,
) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != field_name})


def _validated_cases(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    if manifest.get("case_count") != CASE_COUNT:
        raise ContractValidationError("private manifest case count mismatch")
    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != CASE_COUNT:
        raise ContractValidationError("private manifest requires 100 cases")
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
    }
    validated: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for item in raw_cases:
        if not isinstance(item, dict) or not required_keys.issubset(item):
            raise ContractValidationError("private manifest case is invalid")
        if item["result_kind"] not in {
            "owner_match",
            "no_match",
            "permission_denied",
        }:
            raise ContractValidationError("private manifest result kind is invalid")
        if not isinstance(item["query_text"], str) or not item["query_text"].strip():
            raise ContractValidationError("private manifest query is invalid")
        for field_name in (
            "required_source_observation_ids",
            "forbidden_source_observation_ids",
        ):
            values = item[field_name]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise ContractValidationError("private manifest evidence ids are invalid")
        required_match_count = item["required_match_count"]
        if (
            isinstance(required_match_count, bool)
            or not isinstance(required_match_count, int)
            or required_match_count < 0
            or required_match_count > len(item["required_source_observation_ids"])
        ):
            raise ContractValidationError("private manifest required match count is invalid")
        result_limit = item["limit"]
        if isinstance(result_limit, bool) or not isinstance(result_limit, int) or result_limit <= 0:
            raise ContractValidationError("private manifest result limit is invalid")
        fingerprint = str(item["private_fingerprint"])
        if fingerprint in fingerprints:
            raise ContractValidationError("private manifest fingerprints are not unique")
        fingerprints.add(fingerprint)
        validated.append(item)
    return tuple(validated)


def _validated_diagnostic_case_manifest_entry_hashes(
    values: Sequence[str],
) -> tuple[str, ...]:
    validated = tuple(
        _require_sha256_fingerprint(
            value,
            "diagnostic case manifest entry fingerprint",
        )
        for value in values
    )
    if len(set(validated)) != len(validated):
        raise ContractValidationError("diagnostic case manifest entry fingerprints must be unique")
    return validated


def _diagnostic_subset_cases(
    cases: Sequence[dict[str, Any]],
    *,
    selected_hashes: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    selected = frozenset(selected_hashes)
    available = frozenset(str(case["private_fingerprint"]) for case in cases)
    if not selected or not selected.issubset(available):
        raise ContractValidationError(
            "diagnostic case manifest entry fingerprint is absent from sealed manifest"
        )
    return tuple(case for case in cases if str(case["private_fingerprint"]) in selected)


def _is_development_manifest(manifest: Mapping[str, Any]) -> bool:
    artifact_id = manifest.get("artifact_id")
    return isinstance(artifact_id, str) and "development" in artifact_id


def _is_positive_graph_required_owner_case(case: Mapping[str, Any]) -> bool:
    return (
        deterministic_query_class(str(case["query_text"])) == "relation_reasoning"
        and case["result_kind"] == "owner_match"
        and bool(case["required_source_observation_ids"])
        and int(case["required_match_count"]) > 0
    )


def _positive_graph_required_owner_case_count(
    cases: Sequence[Mapping[str, Any]],
) -> int:
    return sum(_is_positive_graph_required_owner_case(case) for case in cases)


def _validate_external_manifest_seal(
    actual_manifest_sha256: str,
    expected_manifest_sha256: str,
) -> None:
    if (
        len(expected_manifest_sha256) != _SHA256_LENGTH
        or not expected_manifest_sha256.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in expected_manifest_sha256[7:])
    ):
        raise ContractValidationError("external development manifest seal is invalid")
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise ContractValidationError("external development manifest seal mismatch")


def _manifest_bundle_identity_matches(
    manifest: Mapping[str, Any],
    bundle_payload: Mapping[str, Any],
) -> bool:
    import_session = bundle_payload.get("mail_import_session")
    if not isinstance(import_session, Mapping):
        return False
    return (
        bundle_payload.get("mail_evidence_bundle_id") == manifest.get("mail_evidence_bundle_id")
        and import_session.get("mail_import_session_id") == manifest.get("mail_import_session_id")
        and import_session.get("archive_sha256") == manifest.get("archive_sha256")
    )


def _base_report(
    *,
    manifest_byte_hash: str,
    bundle_byte_hash: str,
    case_count: int,
    identity_matches: bool,
    selected_observation_count: int,
    runtime_attestation: str,
    manifest_intake_mode: str,
    expected_seal_matches: bool,
    positive_graph_required_owner_case_count: int,
    source_snapshot_fingerprint: str,
    source_observation_hash_set_fingerprint: str,
    selected_projection_fingerprint: str,
    retrieval_ready_binding: Mapping[str, Any] | None,
    source_identifier_candidate_binding: Mapping[str, Any],
    canonical_image_id: str | None,
    canonical_image_metadata_fingerprint: str | None,
) -> dict[str, Any]:
    dense_profile = issue56_target_dense_embedding_profile()
    lexical_profile = load_issue56_target_mail_tokenizer_profile()
    source_binding_fingerprint = sha256_json(
        {
            "source_snapshot_fingerprint": source_snapshot_fingerprint,
            "selected_projection_fingerprint": selected_projection_fingerprint,
            "retrieval_ready_binding": (
                dict(retrieval_ready_binding)
                if retrieval_ready_binding is not None
                else {"status": "not_supplied"}
            ),
            "source_identifier_candidate_binding": dict(source_identifier_candidate_binding),
            "corpus_policy_id": CORPUS_POLICY_ID,
            "selected_observation_count": selected_observation_count,
        }
    )
    evaluator_fingerprint = sha256_json(
        {
            "evaluator_id": EVALUATOR_ID,
            "case_count": CASE_COUNT,
            "result_kinds": [
                "owner_match",
                "no_match",
                "permission_denied",
            ],
        }
    )
    budget = EvidenceAnswerBudget()
    if canonical_image_id is None or canonical_image_metadata_fingerprint is None:
        raise ContractValidationError("canonical image attestation is required")
    try:
        code_attestation = build_current_code_component(
            repository_root=ROOT,
            run_binding_fingerprint=source_binding_fingerprint,
        )
        image_attestation = build_image_component(
            run_binding_fingerprint=source_binding_fingerprint,
            image_id=canonical_image_id,
            image_metadata_fingerprint=canonical_image_metadata_fingerprint,
        )
        authority_attestation = build_current_authority_component(
            repository_root=ROOT,
            run_binding_fingerprint=source_binding_fingerprint,
        )
    except ExecutionFingerprintValidationError as exc:
        raise ContractValidationError(exc.reason_code) from exc
    return {
        "artifact_id": "formowl_issue56_simulated_human_uat_v1",
        "schema_version": 1,
        "issue": 56,
        "status": "pending",
        "execution_status": "pending",
        "quality_gate_status": "pending",
        "diagnostic_label": ("diagnostic_same_pipeline_not_independent_holdout"),
        "e2e_executed": False,
        "manifest_seal": {
            "sealed_before_execution": True,
            "unchanged_after_execution": False,
            "manifest_byte_hash": manifest_byte_hash,
            "intake_mode": manifest_intake_mode,
            "expected_seal_matches": expected_seal_matches,
            "positive_graph_required_owner_case_count": (positive_graph_required_owner_case_count),
        },
        "source": {
            "classification": ("operator_authorized_preserved_real_pst_diagnostic"),
            "source_binding_fingerprint": source_binding_fingerprint,
            "source_snapshot_fingerprint": source_snapshot_fingerprint,
            "selected_projection_fingerprint": selected_projection_fingerprint,
            "source_observation_hash_set_fingerprint": (source_observation_hash_set_fingerprint),
            "bundle_byte_hash": bundle_byte_hash,
            "manifest_bundle_identity_matches": identity_matches,
            "case_count": case_count,
            "selected_observation_count": selected_observation_count,
            "corpus_policy_id": CORPUS_POLICY_ID,
            "corpus_policy_fingerprint": sha256_json(CORPUS_POLICY_ID),
            "corpus_uses_adjudicated_manifest_ids": True,
            "bounded_decoy_limit": MAX_DECOY_SEGMENTS,
            "retrieval_ready_binding": (
                dict(retrieval_ready_binding)
                if retrieval_ready_binding is not None
                else {"status": "not_supplied"}
            ),
            "source_identifier_candidate_binding": dict(source_identifier_candidate_binding),
        },
        "shared_pipeline": {
            "arm_ids": list(ARM_IDS),
            "permission_policy_fingerprint": sha256_json(PERMISSION_POLICY_ID),
            "lexical_profile_id": lexical_profile.tokenizer_id,
            "lexical_profile_fingerprint": lexical_profile.profile_fingerprint,
            "query_lexical_profile_fingerprint": (lexical_profile.profile_fingerprint),
            "evidence_lexical_profile_fingerprint": (lexical_profile.profile_fingerprint),
            "dense_encoder_id": dense_profile.encoder_id,
            "dense_model_id": dense_profile.model_id,
            "dense_model_revision": dense_profile.model_revision,
            "dense_profile_fingerprint": dense_profile.profile_fingerprint,
            "dense_runtime_attestation": runtime_attestation,
            "answer_model_id": ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID,
            "answer_prompt_id": ISSUE56_DETERMINISTIC_ANSWER_PROMPT_ID,
            "answer_prompt_fingerprint": (ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT),
            "answer_budget_fingerprint": budget.fingerprint,
            "evaluator_id": EVALUATOR_ID,
            "evaluator_fingerprint": evaluator_fingerprint,
            "runtime_method_id": ISSUE56_TARGET_RUNTIME_METHOD_ID,
            "runtime_method_fingerprint": (ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT),
            "answer_model_fingerprint": sha256_json(ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID),
            "graph_adapter_fingerprint": sha256_json(GRAPH_ADAPTER_ID),
            "source_graph_policy_fingerprint": sha256_json(SOURCE_GRAPH_POLICY_ID),
            "source_identifier_adapter_fingerprint": sha256_json(SOURCE_IDENTIFIER_ADAPTER_ID),
            "relation_type_hash_set_fingerprint": sha256_json(
                sorted(sha256_json(value) for value in DIAGNOSTIC_RELATION_TYPES)
            ),
            "ontology_target_fingerprint": sha256_json(ONTOLOGY_TARGET),
        },
        "execution_environment": {
            "attestation_run_binding_fingerprint": source_binding_fingerprint,
            "code_attestation_fingerprint": code_attestation["artifact_fingerprint"],
            "code_tree_fingerprint": code_attestation["code_tree_fingerprint"],
            "code_tree_scope_fingerprint": code_attestation["code_tree_scope_fingerprint"],
            "image_attestation_fingerprint": image_attestation["artifact_fingerprint"],
            "image_reference_fingerprint": image_attestation["image_reference_fingerprint"],
            "image_id": image_attestation["image_id"],
            "image_metadata_fingerprint": image_attestation["image_metadata_fingerprint"],
            "authority_attestation_fingerprint": authority_attestation["artifact_fingerprint"],
            "authority_state_fingerprint": authority_attestation["authority_state_fingerprint"],
            "authority_execution_fingerprint": authority_attestation[
                "authority_execution_fingerprint"
            ],
            "authority_blocking_gate_set_fingerprint": authority_attestation[
                "blocking_gate_set_fingerprint"
            ],
            "authority_blocking_gate_count": authority_attestation["blocking_gate_count"],
            "source_completeness_gate_status": authority_attestation[
                "source_completeness_gate_status"
            ],
            "real_source_ablation_gate_status": authority_attestation[
                "real_source_ablation_gate_status"
            ],
            "methodology_ready_status": authority_attestation["methodology_ready_status"],
        },
        "claim_boundary": {
            "private_manifest_previously_used_for_diagnostics": True,
            "independent_holdout": False,
            "oracle_used_by_answer_renderer": False,
            "retrieval_corpus_independent_of_adjudication": False,
            "adjudication_ids_used_for_bounded_corpus_selection": True,
            "source_complete": False,
            "real_source_authority_gate_passed": False,
            "retrieval_ready_bundle_artifact_bound": (retrieval_ready_binding is not None),
            "source_identifier_candidate_artifact_bound": True,
            "source_backed_candidate_graph_v2_bound": True,
            "methodology_ready": False,
            "methodology_complete": False,
            "issue56_complete": False,
            "production_ready": False,
            "supports_same_pipeline_diagnostic_claim": False,
            "supports_arm_superiority_claim": False,
        },
    }


def _deterministic_zero_cost_measurement() -> dict[str, Any]:
    return {
        "status": "zero_cost_attested",
        "generation_mode": ZERO_COST_GENERATION_MODE,
        "external_generation_call_count": 0,
        "input_token_count": 0,
        "output_token_count": 0,
        "monetary_cost_microusd": 0,
        "attestation_fingerprint": deterministic_zero_cost_attestation_fingerprint(),
    }


def _public_safe_zero_cost_measurement() -> dict[str, Any]:
    measurement = _deterministic_zero_cost_measurement()
    measurement["input_usage_count"] = measurement.pop("input_token_count")
    measurement["output_usage_count"] = measurement.pop("output_token_count")
    return measurement


def _assert_safe_simulated_uat_report(report: Mapping[str, Any]) -> None:
    resource_measurement = report.get("resource_measurement")
    if not isinstance(resource_measurement, Mapping):
        raise ContractValidationError("resource measurement is required")
    usage = resource_measurement.get("model_usage_cost")
    if not isinstance(usage, Mapping):
        raise ContractValidationError("model usage cost attestation is required")
    expected = (
        _public_safe_zero_cost_measurement()
        if report.get("diagnostic_subset_only") is True
        else _deterministic_zero_cost_measurement()
    )
    if dict(usage) != expected:
        raise ContractValidationError("model usage cost attestation is invalid")

    public_projection = json.loads(json.dumps(report, ensure_ascii=True, sort_keys=True))
    projected_usage = public_projection["resource_measurement"]["model_usage_cost"]
    if "input_token_count" in projected_usage:
        projected_usage["input_usage_count"] = projected_usage.pop("input_token_count")
    if "output_token_count" in projected_usage:
        projected_usage["output_usage_count"] = projected_usage.pop("output_token_count")
    assert_no_public_raw_references(
        public_projection,
        "issue56_simulated_uat",
    )


def _blocked_report(
    base: Mapping[str, Any],
    *,
    blocker: str,
    manifest_path: Path,
    manifest_byte_hash: str,
) -> dict[str, Any]:
    manifest_unchanged = False
    try:
        manifest_unchanged = _sha256_bytes(manifest_path.read_bytes()) == manifest_byte_hash
    except OSError:
        pass
    report = {
        **base,
        "status": "blocked",
        "execution_status": "blocked",
        "quality_gate_status": "blocked",
        "blocker": blocker,
        "e2e_executed": False,
        "manifest_seal": {
            **base["manifest_seal"],
            "unchanged_after_execution": manifest_unchanged,
        },
    }
    assert_no_public_raw_references(report, "issue56_simulated_uat_blocked")
    return report


def _read_private_bytes(path: Path, *, blocker: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ContractValidationError(blocker) from exc


def _read_json_object(raw: bytes, *, blocker: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(blocker) from exc
    if not isinstance(value, dict):
        raise ContractValidationError(blocker)
    return value


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = max(0, math.ceil(len(values) * fraction) - 1)
    return round(float(values[index]), 3)


if __name__ == "__main__":
    raise SystemExit(main())
