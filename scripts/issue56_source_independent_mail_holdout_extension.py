#!/usr/bin/env python3
"""Author a sealed additive 59-case independent mail holdout extension.

This is a source-author-only tool.  It validates immutable source, tokenizer,
index, permission, development-exclusion, and existing 41-case holdout seals;
selects new cases without consulting runtime quality output or prior
adjudication values; and atomically publishes:

* one private manifest containing source-authored adjudication; and
* one public-safe projection containing hashes, counts, and typed routes only.

It never executes the holdout and never mutates the existing 41-case manifest.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    ContractValidationError,
    Observation,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (  # noqa: E402
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    MailCandidateAdmissionTokenizerProfile,
    load_issue56_target_mail_tokenizer_profile,
)
from scripts.issue56_source_development_uat_manifest import (  # noqa: E402
    ARTIFACT_ID as DEVELOPMENT_MANIFEST_ARTIFACT_ID,
    CASE_COUNT as DEVELOPMENT_CASE_COUNT,
    SAFE_REPORT_ARTIFACT_ID as DEVELOPMENT_SAFE_REPORT_ARTIFACT_ID,
    _EvidenceRecord,
    _payload_fingerprint,
    _stratum_rank,
    _validated_body_evidence_records,
    _validated_bundle_artifact,
)


SCHEMA_VERSION = 1
ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_extension_v1"
PROJECTION_ARTIFACT_ID = (
    "formowl_issue56_independent_mail_holdout_extension_oracle_free_projection_v1"
)
REJECTION_ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_extension_rejection_v1"
CLASSIFICATION = "independent_mail_holdout_extension"
BASE_HOLDOUT_ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_manifest_v2"
BASE_HOLDOUT_SAFE_ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_preflight_v2"
BASE_HOLDOUT_CASE_COUNT = 41
BASE_HOLDOUT_STRATA_COUNTS = {
    "exact_aggregation": 1,
    "exact_count": 1,
    "exact_set": 1,
    "graph_required": 30,
    "no_answer_near_miss_negative": 2,
    "permission_denied": 2,
    "single_document_direct_lookup": 4,
}
EXTENSION_CASE_COUNT = 59
COMBINED_ACCEPTANCE_CASE_COUNT = BASE_HOLDOUT_CASE_COUNT + EXTENSION_CASE_COUNT
SOURCE_AUTHOR_ROLE_ID = "issue56_independent_mail_holdout_extension_source_author_v1"
SELECTION_POLICY_ID = "issue56_independent_mail_holdout_extension_selection_v2"
PARTITION_POLICY_ID = "issue56_latest_quartile_thread_pure_extension_v1"
QUERY_TEMPLATE_VERSION = 1
RESULT_LIMIT = 10
MIN_IDENTIFIER_MESSAGE_FREQUENCY = 2
MAX_IDENTIFIER_MESSAGE_FREQUENCY = 6
MAX_CONCEPT_DOCUMENT_FREQUENCY = 12
NEGATIVE_DONOR_LIMIT_PER_IDENTIFIER = 64
TIME_PARTITION_NUMERATOR = 1
TIME_PARTITION_DENOMINATOR = 4

MANIFEST_FILENAME = "holdout-extension-manifest.private.json"
PROJECTION_FILENAME = "holdout-extension-oracle-free-projection.safe.json"

TARGET_STRATA_COUNTS = {
    "exact_aggregation": 2,
    "exact_count": 2,
    "exact_set": 12,
    "graph_required": 20,
    "no_answer_near_miss_negative": 10,
    "permission_denied": 8,
    "single_document_direct_lookup": 5,
}
LEGACY_TARGET_STRATA_COUNTS = {
    "exact_aggregation": 2,
    "exact_count": 2,
    "exact_set": 2,
    "graph_required": 20,
    "no_answer_near_miss_negative": 10,
    "permission_denied": 8,
    "single_document_direct_lookup": 15,
}
_SELECTION_STRATUM_ORDER = (
    "graph_required",
    "exact_set",
    "exact_count",
    "exact_aggregation",
    "no_answer_near_miss_negative",
    "permission_denied",
    "single_document_direct_lookup",
)
LEGACY_SELECTION_POLICY_FINGERPRINT = (
    "sha256:994d56860dcfad93e7d3a3481b8102b5d1347e3814ed5f6109d8f1525c9632ab"
)
CANDIDATE_IDENTITY_POLICY_FINGERPRINT = LEGACY_SELECTION_POLICY_FINGERPRINT
CAPACITY_AUDIT_POLICY_ID = "issue56_holdout_extension_actual_source_capacity_adjustment_v1"
_CAPACITY_AUDIT_POLICY = {
    "base_selection_policy_fingerprint": LEGACY_SELECTION_POLICY_FINGERPRINT,
    "selection_order": list(_SELECTION_STRATUM_ORDER),
    "capacity_adjustment_policy": (
        "replace_only_actual_direct_lookup_shortfall_with_"
        "exact_set_structurally_disjoint_spare_capacity_v1"
    ),
    "target_strata_counts": dict(TARGET_STRATA_COUNTS),
    "case_count": EXTENSION_CASE_COUNT,
    "quality_or_oracle_read": False,
    "runtime_or_ranking_change": False,
}
ALTERNATIVE_STRATA_POLICY_FINGERPRINT = sha256_json(_CAPACITY_AUDIT_POLICY)
FROZEN_ALTERNATIVE_STRATA_POLICY_FINGERPRINT = (
    "sha256:9806d41ef3b4bf18a6bbedabd9a1ddcb8ded2850825f96e78aa03ed38b4a558b"
)
if ALTERNATIVE_STRATA_POLICY_FINGERPRINT != FROZEN_ALTERNATIVE_STRATA_POLICY_FINGERPRINT:
    raise RuntimeError("holdout_extension_capacity_audit_policy_drift")
FROZEN_ACTUAL_SOURCE_SNAPSHOT_FINGERPRINT = (
    "sha256:2548c40f192a4f92d1965aefa684fde6bed3585cf16561e8772c660b15b5448b"
)
FROZEN_ACTUAL_PARTITION_FINGERPRINT = (
    "sha256:b0a884172c3bc03a3a430dfe4c437bcacbe562e5d0dd44c648e9f2fad2948b50"
)
FROZEN_ACTUAL_CANDIDATE_INVENTORY_FINGERPRINT = (
    "sha256:0bc6b7f8fa7c4c1e7a6b46e220996a497c8de74e4d76ce63635f2eee6143e045"
)
FROZEN_ACTUAL_SELECTED_CANDIDATE_FINGERPRINT = (
    "sha256:643402747c381a419df4bd0fe8540a1aec5b3493841a476b7f78b3b059508408"
)
FROZEN_ACTUAL_SELECTION_PROOF_FINGERPRINT = (
    "sha256:d00cbd2a87be2f92ebdd672e8f8da601df6becde0485dcce69228214aadcc85a"
)
_SELECTION_POLICY = {
    "selection_policy_id": SELECTION_POLICY_ID,
    "classification": CLASSIFICATION,
    "base_holdout_case_count": BASE_HOLDOUT_CASE_COUNT,
    "extension_case_count": EXTENSION_CASE_COUNT,
    "combined_acceptance_case_count": COMBINED_ACCEPTANCE_CASE_COUNT,
    "target_strata_counts": dict(TARGET_STRATA_COUNTS),
    "selection_order": {
        "primary": "stratum",
        "stratum_order": list(_SELECTION_STRATUM_ORDER),
        "secondary": "identifier_kind",
        "tertiary": "source_derived_candidate_hash",
    },
    "capacity_shortfall_policy": "fail_closed_no_redistribution",
    "candidate_identity_policy_fingerprint": CANDIDATE_IDENTITY_POLICY_FINGERPRINT,
    "capacity_audit_policy_id": CAPACITY_AUDIT_POLICY_ID,
    "capacity_audit_policy_fingerprint": ALTERNATIVE_STRATA_POLICY_FINGERPRINT,
    "negative_pair_candidate_cap_per_identifier": (NEGATIVE_DONOR_LIMIT_PER_IDENTIFIER),
    "partition_policy_id": PARTITION_POLICY_ID,
    "time_partition": {
        "order": "sent_at_utc_then_message_hash",
        "selected_fraction": {
            "numerator": TIME_PARTITION_NUMERATOR,
            "denominator": TIME_PARTITION_DENOMINATOR,
        },
        "selected_side": "latest",
        "thread_rule": "complete_thread_membership_only",
    },
    "exclusions": [
        "development_observation_message_thread",
        "existing_41_holdout_observation_message_thread",
    ],
    "observation_reuse": "forbidden_within_and_across_extension_cases",
    "message_reuse": "forbidden_within_and_across_extension_cases",
    "thread_reuse": "forbidden_within_and_across_extension_cases",
    "query_fingerprint_reuse": "forbidden_against_base_and_extension",
    "case_fingerprint_reuse": "forbidden_against_base_and_extension",
    "runtime_quality_read": False,
    "prior_adjudication_read": False,
    "holdout_execution": False,
    "query_specific_tuning": False,
}
SELECTION_POLICY_FINGERPRINT = sha256_json(_SELECTION_POLICY)
_PARTITION_POLICY = {
    "partition_policy_id": PARTITION_POLICY_ID,
    "selection_policy_fingerprint": CANDIDATE_IDENTITY_POLICY_FINGERPRINT,
    "source_kind": "authorized_retrieval_ready_mail_body_observation",
    "latest_fraction": [TIME_PARTITION_NUMERATOR, TIME_PARTITION_DENOMINATOR],
    "complete_threads_only": True,
    "excluded_registry_count": 2,
}
PARTITION_POLICY_FINGERPRINT = sha256_json(_PARTITION_POLICY)

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_EXCLUSION_LINEAGE_OBSERVATION_TYPES = frozenset(
    {
        "email_body_segment",
        "email_header",
    }
)
_MAX_SOURCE_BYTES = 256 * 1024 * 1024
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_SAFE_BYTES = 2 * 1024 * 1024
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class HoldoutExtensionError(RuntimeError):
    """Fail-closed source-authoring error with a public-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _SourceRecord:
    evidence: _EvidenceRecord
    message_id: str
    thread_id: str
    sent_at: datetime
    identifier_kinds: tuple[str, ...]

    @property
    def observation_id(self) -> str:
        return self.evidence.observation_id

    @property
    def occurrence_id(self) -> str:
        return self.evidence.message_occurrence_id


@dataclass(frozen=True)
class _ExclusionRegistry:
    observation_ids: frozenset[str]
    message_ids: frozenset[str]
    thread_ids: frozenset[str]
    query_hashes: frozenset[str]
    case_fingerprints: frozenset[str]
    registry_fingerprint: str


@dataclass(frozen=True)
class _Partition:
    eligible_records: tuple[_SourceRecord, ...]
    observation_to_message: Mapping[str, str]
    observation_to_thread: Mapping[str, str]
    excluded_observation_ids: frozenset[str]
    excluded_message_ids: frozenset[str]
    excluded_thread_ids: frozenset[str]
    latest_message_ids: frozenset[str]
    eligible_message_ids: frozenset[str]
    eligible_thread_ids: frozenset[str]
    time_boundary_fingerprint: str
    partition_fingerprint: str


@dataclass(frozen=True)
class _Candidate:
    stratum: str
    identifier_kind: str
    records: tuple[_SourceRecord, ...]
    query_text: str
    requester_user_id: str
    route: Mapping[str, Any]
    required_observation_ids: tuple[str, ...]
    forbidden_observation_ids: tuple[str, ...]
    authoring_observation_ids: tuple[str, ...]
    adjudication: Mapping[str, Any]
    candidate_fingerprint: str

    @property
    def observation_ids(self) -> frozenset[str]:
        return frozenset(record.observation_id for record in self.records)

    @property
    def message_ids(self) -> frozenset[str]:
        return frozenset(record.message_id for record in self.records)

    @property
    def thread_ids(self) -> frozenset[str]:
        return frozenset(record.thread_id for record in self.records)


@dataclass(frozen=True)
class HoldoutExtensionArtifacts:
    output_root: Path
    manifest_path: Path
    projection_path: Path
    manifest: dict[str, Any]
    projection: dict[str, Any]
    manifest_sha256: str
    projection_sha256: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-artifact", type=Path, required=True)
    parser.add_argument("--expected-bundle-artifact-sha256", required=True)
    parser.add_argument("--retrieval-snapshot", type=Path, required=True)
    parser.add_argument("--expected-retrieval-snapshot-sha256", required=True)
    parser.add_argument("--development-manifest", type=Path, required=True)
    parser.add_argument("--expected-development-manifest-sha256", required=True)
    parser.add_argument("--development-safe-report", type=Path, required=True)
    parser.add_argument("--expected-development-safe-report-sha256", required=True)
    parser.add_argument("--base-holdout-manifest", type=Path, required=True)
    parser.add_argument("--expected-base-holdout-manifest-sha256", required=True)
    parser.add_argument("--base-holdout-safe-report", type=Path, required=True)
    parser.add_argument("--expected-base-holdout-safe-report-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-message-count", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifacts = author_independent_mail_holdout_extension(
            bundle_artifact_path=args.bundle_artifact,
            expected_bundle_artifact_sha256=args.expected_bundle_artifact_sha256,
            retrieval_snapshot_path=args.retrieval_snapshot,
            expected_retrieval_snapshot_sha256=args.expected_retrieval_snapshot_sha256,
            development_manifest_path=args.development_manifest,
            expected_development_manifest_sha256=args.expected_development_manifest_sha256,
            development_safe_report_path=args.development_safe_report,
            expected_development_safe_report_sha256=(args.expected_development_safe_report_sha256),
            base_holdout_manifest_path=args.base_holdout_manifest,
            expected_base_holdout_manifest_sha256=(args.expected_base_holdout_manifest_sha256),
            base_holdout_safe_report_path=args.base_holdout_safe_report,
            expected_base_holdout_safe_report_sha256=(
                args.expected_base_holdout_safe_report_sha256
            ),
            output_root=args.output_root,
            expected_message_count=args.expected_message_count,
        )
    except (
        ContractValidationError,
        HoldoutExtensionError,
        RuntimeError,
        ValueError,
    ) as exc:
        reason = getattr(exc, "reason_code", str(exc))
        print(json.dumps(_rejection(reason), ensure_ascii=True, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "artifact_id": PROJECTION_ARTIFACT_ID,
                "schema_version": SCHEMA_VERSION,
                "status": "passed",
                "execution_status": "not_run",
                "counts": {
                    "base_case_count": BASE_HOLDOUT_CASE_COUNT,
                    "extension_case_count": EXTENSION_CASE_COUNT,
                    "combined_acceptance_case_count": COMBINED_ACCEPTANCE_CASE_COUNT,
                    "blocker_count": 0,
                },
                "hashes": {
                    "manifest_sha256": artifacts.manifest_sha256,
                    "projection_sha256": artifacts.projection_sha256,
                    "selection_proof_fingerprint": artifacts.manifest["selection_proof"][
                        "selection_proof_fingerprint"
                    ],
                    "candidate_inventory_fingerprint": artifacts.manifest["selection_proof"][
                        "candidate_inventory_fingerprint"
                    ],
                    "capacity_audit_policy_fingerprint": (
                        artifacts.manifest["capacity_audit_binding"][
                            "capacity_audit_policy_fingerprint"
                        ]
                    ),
                },
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


def author_independent_mail_holdout_extension(
    *,
    bundle_artifact_path: Path,
    expected_bundle_artifact_sha256: str,
    retrieval_snapshot_path: Path,
    expected_retrieval_snapshot_sha256: str,
    development_manifest_path: Path,
    expected_development_manifest_sha256: str,
    development_safe_report_path: Path,
    expected_development_safe_report_sha256: str,
    base_holdout_manifest_path: Path,
    expected_base_holdout_manifest_sha256: str,
    base_holdout_safe_report_path: Path,
    expected_base_holdout_safe_report_sha256: str,
    output_root: Path,
    expected_message_count: int,
    _write_staged_file: Callable[[Path, bytes, int], None] | None = None,
) -> HoldoutExtensionArtifacts:
    """Build and atomically publish one additive, unexecuted extension."""

    if expected_message_count <= 0:
        raise HoldoutExtensionError("expected_message_count_invalid")
    bundle_bytes, bundle_artifact = _read_sealed_json(
        bundle_artifact_path,
        expected_bundle_artifact_sha256,
        maximum_bytes=_MAX_SOURCE_BYTES,
        reason_prefix="bundle_artifact",
    )
    snapshot_bytes, retrieval_snapshot = _read_sealed_json(
        retrieval_snapshot_path,
        expected_retrieval_snapshot_sha256,
        maximum_bytes=_MAX_SOURCE_BYTES,
        reason_prefix="retrieval_snapshot",
    )
    development_bytes, development_manifest = _read_sealed_json(
        development_manifest_path,
        expected_development_manifest_sha256,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        reason_prefix="development_manifest",
    )
    development_safe_bytes, development_safe = _read_sealed_json(
        development_safe_report_path,
        expected_development_safe_report_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="development_safe_report",
    )
    base_bytes, base_manifest = _read_sealed_json(
        base_holdout_manifest_path,
        expected_base_holdout_manifest_sha256,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        reason_prefix="base_holdout_manifest",
    )
    base_safe_bytes, base_safe = _read_sealed_json(
        base_holdout_safe_report_path,
        expected_base_holdout_safe_report_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="base_holdout_safe_report",
    )

    bundle_payload = _validated_bundle_artifact(bundle_artifact)
    source_bindings = _validate_source_snapshot_and_bindings(
        bundle_artifact=bundle_artifact,
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        expected_message_count=expected_message_count,
    )
    profile = load_issue56_target_mail_tokenizer_profile()
    if (
        profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
        or profile.profile_fingerprint != source_bindings["tokenizer_profile_fingerprint"]
    ):
        raise HoldoutExtensionError("target_tokenizer_binding_mismatch")

    development_registry = _validate_development_exclusion(
        manifest=development_manifest,
        manifest_sha256=_sha256_bytes(development_bytes),
        safe_report=development_safe,
        safe_report_sha256=_sha256_bytes(development_safe_bytes),
        source_bindings=source_bindings,
    )
    base_registry = _validate_base_holdout_exclusion(
        manifest=base_manifest,
        manifest_sha256=_sha256_bytes(base_bytes),
        safe_report=base_safe,
        safe_report_sha256=_sha256_bytes(base_safe_bytes),
        source_bindings=source_bindings,
    )

    evidence_records = _validated_body_evidence_records(
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        profile=profile,
    )
    source_records, body_observation_to_message, body_observation_to_thread = _build_source_records(
        bundle_payload=bundle_payload,
        evidence_records=evidence_records,
    )
    observation_to_message, observation_to_thread = _build_exclusion_observation_lineage(
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        evidence_records=evidence_records,
    )
    if any(
        observation_to_message.get(observation_id) != message_id
        or observation_to_thread.get(observation_id) != body_observation_to_thread[observation_id]
        for observation_id, message_id in body_observation_to_message.items()
    ):
        raise HoldoutExtensionError("body_observation_exclusion_lineage_mismatch")
    development_registry = _bind_registry_lineage(
        development_registry,
        observation_to_message=observation_to_message,
        observation_to_thread=observation_to_thread,
        reason_prefix="development",
    )
    base_registry = _bind_registry_lineage(
        base_registry,
        observation_to_message=observation_to_message,
        observation_to_thread=observation_to_thread,
        reason_prefix="base_holdout",
    )
    partition = _partition_records(
        records=source_records,
        observation_to_message=observation_to_message,
        observation_to_thread=observation_to_thread,
        development_registry=development_registry,
        base_registry=base_registry,
    )
    candidates = _build_candidates(
        partition.eligible_records,
        profile=profile,
        owner_user_id=str(bundle_payload["mail_import_session"]["owner_user_id"]),
        workspace_id=str(bundle_payload["mail_import_session"]["workspace_id"]),
    )
    selected, capacity = _select_candidates(
        candidates,
        base_registry=base_registry,
    )
    cases = _build_private_cases(selected, partition=partition)
    disjointness = _validate_extension_disjointness(
        cases=cases,
        selected=selected,
        partition=partition,
        development_registry=development_registry,
        base_registry=base_registry,
    )
    selection_proof = _selection_proof(
        candidates=candidates,
        selected=selected,
        capacity=capacity,
    )
    capacity_audit_binding = _capacity_audit_binding(
        source_bindings=source_bindings,
        partition=partition,
        selection_proof=selection_proof,
    )

    manifest: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "classification": CLASSIFICATION,
        "status": "sealed",
        "claim_boundary_status": "source_authored_extension_not_executed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "final_acceptance_eligible": True,
        "diagnostic_only": False,
        "source_author_role_id": SOURCE_AUTHOR_ROLE_ID,
        "source_bindings": {
            **source_bindings,
            "bundle_artifact_sha256": _sha256_bytes(bundle_bytes),
            "retrieval_snapshot_sha256": _sha256_bytes(snapshot_bytes),
        },
        "base_holdout_binding": {
            "artifact_id": BASE_HOLDOUT_ARTIFACT_ID,
            "manifest_sha256": _sha256_bytes(base_bytes),
            "safe_report_sha256": _sha256_bytes(base_safe_bytes),
            "manifest_fingerprint": base_manifest["manifest_fingerprint"],
            "case_count": BASE_HOLDOUT_CASE_COUNT,
            "registry_fingerprint": base_registry.registry_fingerprint,
        },
        "development_exclusion_binding": {
            "artifact_id": DEVELOPMENT_MANIFEST_ARTIFACT_ID,
            "manifest_sha256": _sha256_bytes(development_bytes),
            "safe_report_sha256": _sha256_bytes(development_safe_bytes),
            "manifest_fingerprint": development_manifest["manifest_fingerprint"],
            "case_count": DEVELOPMENT_CASE_COUNT,
            "registry_fingerprint": development_registry.registry_fingerprint,
        },
        "selection_policy": _SELECTION_POLICY,
        "selection_policy_fingerprint": SELECTION_POLICY_FINGERPRINT,
        "capacity_audit_binding": capacity_audit_binding,
        "partition_policy": _PARTITION_POLICY,
        "partition_policy_fingerprint": PARTITION_POLICY_FINGERPRINT,
        "time_boundary_fingerprint": partition.time_boundary_fingerprint,
        "partition_fingerprint": partition.partition_fingerprint,
        "disjointness_proof": disjointness,
        "selection_proof": selection_proof,
        "base_case_count": BASE_HOLDOUT_CASE_COUNT,
        "extension_case_count": EXTENSION_CASE_COUNT,
        "combined_acceptance_case_count": COMBINED_ACCEPTANCE_CASE_COUNT,
        "case_strata_counts": dict(TARGET_STRATA_COUNTS),
        "cases": cases,
    }
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    manifest_bytes = _canonical_bytes(manifest)
    manifest_sha256 = _sha256_bytes(manifest_bytes)

    projection = _safe_projection(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        selected=selected,
        cases=cases,
        partition=partition,
        capacity=capacity,
    )
    projection_bytes = _canonical_bytes(projection)
    projection_sha256 = _sha256_bytes(projection_bytes)

    _persist_atomic_directory(
        output_root=output_root,
        files={
            MANIFEST_FILENAME: (manifest_bytes, 0o400),
            PROJECTION_FILENAME: (projection_bytes, 0o400),
        },
        write_staged_file=_write_staged_file or _write_file_exclusive,
    )
    if (output_root / MANIFEST_FILENAME).read_bytes() != manifest_bytes or (
        output_root / PROJECTION_FILENAME
    ).read_bytes() != projection_bytes:
        raise HoldoutExtensionError("persisted_artifact_byte_drift")
    return HoldoutExtensionArtifacts(
        output_root=output_root,
        manifest_path=output_root / MANIFEST_FILENAME,
        projection_path=output_root / PROJECTION_FILENAME,
        manifest=manifest,
        projection=projection,
        manifest_sha256=manifest_sha256,
        projection_sha256=projection_sha256,
    )


def _validate_source_snapshot_and_bindings(
    *,
    bundle_artifact: Mapping[str, Any],
    bundle_payload: Mapping[str, Any],
    retrieval_snapshot: Mapping[str, Any],
    expected_message_count: int,
) -> dict[str, str]:
    if (
        retrieval_snapshot.get("artifact_id")
        != "formowl_issue56_native_source_complete_retrieval_ready_snapshot_v1"
        or retrieval_snapshot.get("schema_version") != 1
        or retrieval_snapshot.get("status") != "passed"
        or retrieval_snapshot.get("claim_boundary_status")
        != "retrieval_ready_evidence_not_canonical_fact"
        or retrieval_snapshot.get("snapshot_fingerprint")
        != _payload_fingerprint(retrieval_snapshot, "snapshot_fingerprint")
        or retrieval_snapshot.get("blocker_fingerprints") != []
    ):
        raise HoldoutExtensionError("retrieval_snapshot_contract_invalid")
    required_fingerprints = (
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "permission_fingerprint",
        "mail_evidence_bundle_fingerprint",
        "tokenizer_profile_fingerprint",
        "index_fingerprint",
        "snapshot_fingerprint",
    )
    bindings = {
        field_name: _require_sha256(
            retrieval_snapshot.get(field_name),
            f"retrieval_snapshot_{field_name}_invalid",
        )
        for field_name in required_fingerprints
    }
    if (
        bundle_artifact["source_snapshot_fingerprint"] != bindings["source_snapshot_fingerprint"]
        or bundle_artifact["source_inventory_fingerprint"]
        != bindings["source_inventory_fingerprint"]
        or bundle_artifact["source_provenance_fingerprint"]
        != bindings["source_provenance_fingerprint"]
        or bundle_artifact["bundle_fingerprint"] != bindings["mail_evidence_bundle_fingerprint"]
    ):
        raise HoldoutExtensionError("retrieval_source_binding_mismatch")
    counts = retrieval_snapshot.get("counts")
    if (
        not isinstance(counts, Mapping)
        or any(
            counts.get(field_name) != 0
            for field_name in (
                "missing_source_inventory_binding_count",
                "missing_source_local_key_binding_count",
                "missing_content_hash_binding_count",
                "missing_permission_binding_count",
                "unexplained_loss_count",
                "blocker_count",
            )
        )
        or counts.get("mail_bundle_message_count") != expected_message_count
        or len(bundle_payload.get("messages", ())) != expected_message_count
    ):
        raise HoldoutExtensionError("source_complete_snapshot_required")
    parsed_rows = retrieval_snapshot.get("parsed_mail_observations")
    if not isinstance(parsed_rows, list):
        raise HoldoutExtensionError("parsed_observation_projection_missing")
    parsed_observations = [Observation.from_dict(row) for row in parsed_rows]
    if len({item.observation_id for item in parsed_observations}) != len(
        parsed_observations
    ) or counts.get("parsed_body_segment_observation_count") != sum(
        item.observation_type == "email_body_segment" for item in parsed_observations
    ):
        raise HoldoutExtensionError("parsed_observation_projection_invalid")
    permission_fingerprint = bindings["permission_fingerprint"]
    provenance_fingerprint = bindings["source_provenance_fingerprint"]
    parsed_type_counts = Counter(
        observation.observation_type for observation in parsed_observations
    )
    if (
        counts.get("parsed_body_segment_observation_count")
        != parsed_type_counts["email_body_segment"]
        or counts.get("parsed_header_observation_count") != parsed_type_counts["email_header"]
    ):
        raise HoldoutExtensionError("parsed_observation_type_count_invalid")
    for observation in parsed_observations:
        if observation.observation_type not in _EXCLUSION_LINEAGE_OBSERVATION_TYPES:
            continue
        if (
            sha256_json(observation.permission_scope) != permission_fingerprint
            or observation.location.get("source_provenance_fingerprint") != provenance_fingerprint
            or not isinstance(
                observation.location.get("source_inventory_item_id"),
                str,
            )
            or not isinstance(observation.location.get("source_local_key"), str)
            or not _SHA256_RE.fullmatch(str(observation.location.get("source_content_hash", "")))
        ):
            raise HoldoutExtensionError("parsed_observation_source_binding_invalid")
    return bindings


def _validate_development_exclusion(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    safe_report: Mapping[str, Any],
    safe_report_sha256: str,
    source_bindings: Mapping[str, str],
) -> _ExclusionRegistry:
    if (
        manifest.get("artifact_id") != DEVELOPMENT_MANIFEST_ARTIFACT_ID
        or manifest.get("schema_version") != 1
        or manifest.get("classification") != "development_not_holdout"
        or manifest.get("case_count") != DEVELOPMENT_CASE_COUNT
        or manifest.get("quality_evaluation_status") != "not_run"
        or manifest.get("manifest_fingerprint")
        != _payload_fingerprint(manifest, "manifest_fingerprint")
        or safe_report.get("artifact_id") != DEVELOPMENT_SAFE_REPORT_ARTIFACT_ID
        or safe_report.get("status") != "passed"
        or safe_report.get("quality_evaluation_status") != "not_run"
        or safe_report.get("fingerprints", {}).get("manifest_sha256") != manifest_sha256
    ):
        raise HoldoutExtensionError("development_exclusion_contract_invalid")
    _require_sha256(safe_report_sha256, "development_safe_report_sha256_invalid")
    source = manifest.get("source_bindings")
    if not isinstance(source, Mapping):
        raise HoldoutExtensionError("development_source_binding_missing")
    for manifest_field, source_field in (
        ("source_snapshot_fingerprint", "source_snapshot_fingerprint"),
        ("permission_fingerprint", "permission_fingerprint"),
        ("tokenizer_profile_fingerprint", "tokenizer_profile_fingerprint"),
        ("index_fingerprint", "index_fingerprint"),
    ):
        if source.get(manifest_field) != source_bindings[source_field]:
            raise HoldoutExtensionError("development_source_binding_mismatch")
    return _registry_from_cases(
        manifest.get("cases"),
        expected_count=DEVELOPMENT_CASE_COUNT,
        registry_kind="development",
        manifest_sha256=manifest_sha256,
        allow_adjudication_fields=False,
    )


def _validate_base_holdout_exclusion(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    safe_report: Mapping[str, Any],
    safe_report_sha256: str,
    source_bindings: Mapping[str, str],
) -> _ExclusionRegistry:
    if (
        manifest.get("artifact_id") != BASE_HOLDOUT_ARTIFACT_ID
        or manifest.get("schema_version") != 2
        or manifest.get("classification") != "independent_mail_holdout"
        or manifest.get("execution_status") != "not_run"
        or manifest.get("quality_result_status") != "not_read"
        or manifest.get("case_count") != BASE_HOLDOUT_CASE_COUNT
        or manifest.get("case_strata_counts") != BASE_HOLDOUT_STRATA_COUNTS
        or manifest.get("manifest_fingerprint")
        != _payload_fingerprint(manifest, "manifest_fingerprint")
        or safe_report.get("artifact_id") != BASE_HOLDOUT_SAFE_ARTIFACT_ID
        or safe_report.get("schema_version") != 2
        or safe_report.get("status") != "passed"
        or safe_report.get("execution_status") != "not_run"
        or safe_report.get("quality_result_status") != "not_read"
        or safe_report.get("counts", {}).get("case_count") != BASE_HOLDOUT_CASE_COUNT
        or safe_report.get("strata_counts") != BASE_HOLDOUT_STRATA_COUNTS
        or safe_report.get("hashes", {}).get("manifest_sha256") != manifest_sha256
        or safe_report.get("report_fingerprint")
        != _payload_fingerprint(safe_report, "report_fingerprint")
    ):
        raise HoldoutExtensionError("base_holdout_exclusion_contract_invalid")
    _require_sha256(safe_report_sha256, "base_holdout_safe_report_sha256_invalid")
    source = manifest.get("source_oracle_bindings")
    if not isinstance(source, Mapping):
        raise HoldoutExtensionError("base_holdout_source_binding_missing")
    for manifest_field, source_field in (
        ("source_snapshot_fingerprint", "source_snapshot_fingerprint"),
        ("permission_fingerprint", "permission_fingerprint"),
        ("index_fingerprint", "index_fingerprint"),
        ("tokenizer_profile_fingerprint", "tokenizer_profile_fingerprint"),
    ):
        if source.get(manifest_field) != source_bindings[source_field]:
            raise HoldoutExtensionError("base_holdout_source_binding_mismatch")
    return _registry_from_cases(
        manifest.get("cases"),
        expected_count=BASE_HOLDOUT_CASE_COUNT,
        registry_kind="base_holdout",
        manifest_sha256=manifest_sha256,
        allow_adjudication_fields=True,
    )


def _registry_from_cases(
    value: Any,
    *,
    expected_count: int,
    registry_kind: str,
    manifest_sha256: str,
    allow_adjudication_fields: bool,
) -> _ExclusionRegistry:
    if not isinstance(value, list) or len(value) != expected_count:
        raise HoldoutExtensionError(f"{registry_kind}_case_registry_invalid")
    observation_ids: set[str] = set()
    query_hashes: set[str] = set()
    case_fingerprints: set[str] = set()
    for case in value:
        if not isinstance(case, Mapping):
            raise HoldoutExtensionError(f"{registry_kind}_case_registry_invalid")
        # Intentionally project lineage fields only.  Existing adjudication/oracle
        # values are neither accessed nor copied into the extension authoring path.
        required = _string_list(
            case.get("required_source_observation_ids"),
            f"{registry_kind}_required_observations_invalid",
        )
        forbidden = _string_list(
            case.get("forbidden_source_observation_ids", []),
            f"{registry_kind}_forbidden_observations_invalid",
        )
        authoring = (
            _string_list(
                case.get("authoring_source_observation_ids"),
                f"{registry_kind}_authoring_observations_invalid",
            )
            if "authoring_source_observation_ids" in case
            else tuple(dict.fromkeys((*required, *forbidden)))
        )
        if not authoring:
            raise HoldoutExtensionError(f"{registry_kind}_authoring_observations_missing")
        observation_ids.update(authoring)
        query_text = case.get("query_text")
        case_fingerprint = _require_sha256(
            case.get("private_fingerprint"),
            f"{registry_kind}_case_fingerprint_invalid",
        )
        if not isinstance(query_text, str) or not query_text.strip():
            raise HoldoutExtensionError(f"{registry_kind}_query_binding_invalid")
        query_hash = sha256_json(query_text)
        if query_hash in query_hashes or case_fingerprint in case_fingerprints:
            raise HoldoutExtensionError(f"{registry_kind}_case_registry_not_unique")
        query_hashes.add(query_hash)
        case_fingerprints.add(case_fingerprint)
        if not allow_adjudication_fields and any(
            field_name in case for field_name in ("answer_oracle", "adjudication")
        ):
            raise HoldoutExtensionError("development_registry_contains_holdout_oracle")
    fingerprint = sha256_json(
        {
            "registry_kind": registry_kind,
            "manifest_sha256": manifest_sha256,
            "observation_hashes": sorted(sha256_json(item) for item in observation_ids),
            "query_hashes": sorted(query_hashes),
            "case_fingerprints": sorted(case_fingerprints),
        }
    )
    return _ExclusionRegistry(
        observation_ids=frozenset(observation_ids),
        message_ids=frozenset(),
        thread_ids=frozenset(),
        query_hashes=frozenset(query_hashes),
        case_fingerprints=frozenset(case_fingerprints),
        registry_fingerprint=fingerprint,
    )


def _build_source_records(
    *,
    bundle_payload: Mapping[str, Any],
    evidence_records: Sequence[_EvidenceRecord],
) -> tuple[tuple[_SourceRecord, ...], dict[str, str], dict[str, str]]:
    messages = _unique_bundle_rows(
        bundle_payload.get("messages"),
        key_field="email_message_id",
        reason_code="mail_message_lineage_invalid",
    )
    occurrences = _unique_bundle_rows(
        bundle_payload.get("message_occurrences"),
        key_field="message_occurrence_id",
        reason_code="message_occurrence_lineage_invalid",
    )
    occurrence_to_message = {
        occurrence_id: str(row["email_message_id"]) for occurrence_id, row in occurrences.items()
    }
    observation_to_message: dict[str, str] = {}
    observation_to_thread: dict[str, str] = {}
    records: list[_SourceRecord] = []
    for evidence in evidence_records:
        message_id = occurrence_to_message.get(evidence.message_occurrence_id)
        message = messages.get(str(message_id))
        if message is None:
            raise HoldoutExtensionError("body_observation_message_lineage_missing")
        thread_id = message.get("thread_id")
        sent_at = message.get("sent_at")
        if not isinstance(thread_id, str) or not thread_id:
            raise HoldoutExtensionError("body_observation_thread_lineage_missing")
        if not isinstance(sent_at, str) or not sent_at:
            raise HoldoutExtensionError("body_observation_time_lineage_missing")
        try:
            parsed_time = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HoldoutExtensionError("body_observation_time_invalid") from exc
        if parsed_time.tzinfo is None:
            raise HoldoutExtensionError("body_observation_time_timezone_missing")
        identifier_kinds = tuple(sorted({kind for _identifier, kind in evidence.identifiers}))
        if not identifier_kinds:
            identifier_kinds = ("none",)
        record = _SourceRecord(
            evidence=evidence,
            message_id=str(message_id),
            thread_id=thread_id,
            sent_at=parsed_time.astimezone(timezone.utc),
            identifier_kinds=identifier_kinds,
        )
        records.append(record)
        observation_to_message[evidence.observation_id] = record.message_id
        observation_to_thread[evidence.observation_id] = record.thread_id
    return (
        tuple(sorted(records, key=lambda item: item.evidence.observation_hash)),
        observation_to_message,
        observation_to_thread,
    )


def _build_exclusion_observation_lineage(
    *,
    bundle_payload: Mapping[str, Any],
    retrieval_snapshot: Mapping[str, Any],
    evidence_records: Sequence[_EvidenceRecord],
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve body/header Observations through source-native occurrence lineage."""

    messages_by_email_id = _unique_bundle_rows(
        bundle_payload.get("messages"),
        key_field="email_message_id",
        reason_code="mail_message_lineage_invalid",
    )
    for row in messages_by_email_id.values():
        source_message_id = row.get("message_id")
        thread_id = row.get("thread_id")
        if (
            not isinstance(source_message_id, str)
            or not source_message_id
            or not isinstance(thread_id, str)
            or not thread_id
        ):
            raise HoldoutExtensionError("mail_message_lineage_invalid")

    occurrences_by_id = _unique_bundle_rows(
        bundle_payload.get("message_occurrences"),
        key_field="message_occurrence_id",
        reason_code="message_occurrence_lineage_invalid",
    )
    for occurrence in occurrences_by_id.values():
        email_message_id = occurrence.get("email_message_id")
        source_message_id = occurrence.get("message_id")
        thread_id = occurrence.get("thread_id")
        message = messages_by_email_id.get(str(email_message_id))
        if (
            not isinstance(email_message_id, str)
            or not email_message_id
            or not isinstance(source_message_id, str)
            or not source_message_id
            or not isinstance(thread_id, str)
            or not thread_id
            or message is None
            or message.get("message_id") != source_message_id
            or message.get("thread_id") != thread_id
        ):
            raise HoldoutExtensionError("message_occurrence_lineage_invalid")

    body_segments_by_observation = _unique_bundle_rows(
        bundle_payload.get("body_segments"),
        key_field="source_observation_id",
        reason_code="body_observation_lineage_invalid",
    )
    evidence_by_observation: dict[str, _EvidenceRecord] = {}
    for evidence in evidence_records:
        if evidence.observation_id in evidence_by_observation:
            raise HoldoutExtensionError("body_observation_lineage_invalid")
        evidence_by_observation[evidence.observation_id] = evidence

    parsed_rows = retrieval_snapshot.get("parsed_mail_observations")
    if not isinstance(parsed_rows, list):
        raise HoldoutExtensionError("parsed_observation_projection_missing")
    observation_to_message: dict[str, str] = {}
    observation_to_thread: dict[str, str] = {}
    typed_observation_ids: set[str] = set()
    typed_body_ids: set[str] = set()
    for row in parsed_rows:
        if not isinstance(row, Mapping):
            raise HoldoutExtensionError("parsed_observation_projection_invalid")
        observation_type = row.get("observation_type")
        if observation_type not in _EXCLUSION_LINEAGE_OBSERVATION_TYPES:
            continue
        observation = Observation.from_dict(row)
        observation_id = observation.observation_id
        if observation_id in typed_observation_ids:
            raise HoldoutExtensionError("typed_observation_lineage_duplicate")
        typed_observation_ids.add(observation_id)

        location = observation.location
        payload = observation.payload
        if not isinstance(payload, Mapping):
            raise HoldoutExtensionError(f"{observation_type}_source_native_lineage_invalid")
        source_lineage: dict[str, str] = {}
        for field_name in (
            "message_occurrence_id",
            "message_id",
            "thread_id",
            "source_provenance_fingerprint",
        ):
            location_value = location.get(field_name)
            if (
                not isinstance(location_value, str)
                or not location_value
                or payload.get(field_name) != location_value
            ):
                raise HoldoutExtensionError(f"{observation_type}_source_native_lineage_invalid")
            source_lineage[field_name] = location_value

        occurrence_id = source_lineage["message_occurrence_id"]
        occurrence = occurrences_by_id.get(occurrence_id)
        if occurrence is None:
            raise HoldoutExtensionError(f"{observation_type}_message_occurrence_lineage_missing")
        email_message_id = occurrence.get("email_message_id")
        message = messages_by_email_id.get(str(email_message_id))
        if (
            not isinstance(email_message_id, str)
            or not email_message_id
            or message is None
            or occurrence.get("message_id") != source_lineage["message_id"]
            or occurrence.get("thread_id") != source_lineage["thread_id"]
            or message.get("message_id") != source_lineage["message_id"]
            or message.get("thread_id") != source_lineage["thread_id"]
        ):
            raise HoldoutExtensionError(f"{observation_type}_source_native_lineage_mismatch")

        if observation_type == "email_body_segment":
            typed_body_ids.add(observation_id)
            evidence = evidence_by_observation.get(observation_id)
            segment = body_segments_by_observation.get(observation_id)
            if (
                evidence is None
                or segment is None
                or evidence.message_occurrence_id != occurrence_id
                or segment.get("message_occurrence_id") != occurrence_id
                or segment.get("email_message_id") != email_message_id
            ):
                raise HoldoutExtensionError("body_observation_lineage_invalid")

        previous_message = observation_to_message.setdefault(
            observation_id,
            email_message_id,
        )
        previous_thread = observation_to_thread.setdefault(
            observation_id,
            source_lineage["thread_id"],
        )
        if previous_message != email_message_id or previous_thread != source_lineage["thread_id"]:
            raise HoldoutExtensionError("typed_observation_lineage_conflict")

    if typed_body_ids != set(evidence_by_observation) or typed_body_ids != set(
        body_segments_by_observation
    ):
        raise HoldoutExtensionError("body_observation_coverage_incomplete")
    return observation_to_message, observation_to_thread


def _unique_bundle_rows(
    value: Any,
    *,
    key_field: str,
    reason_code: str,
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        raise HoldoutExtensionError(reason_code)
    rows: dict[str, Mapping[str, Any]] = {}
    for row in value:
        if not isinstance(row, Mapping):
            raise HoldoutExtensionError(reason_code)
        key = row.get(key_field)
        if not isinstance(key, str) or not key or key in rows:
            raise HoldoutExtensionError(reason_code)
        rows[key] = row
    return rows


def _bind_registry_lineage(
    registry: _ExclusionRegistry,
    *,
    observation_to_message: Mapping[str, str],
    observation_to_thread: Mapping[str, str],
    reason_prefix: str,
) -> _ExclusionRegistry:
    missing = registry.observation_ids - observation_to_message.keys()
    if missing:
        raise HoldoutExtensionError(f"{reason_prefix}_observation_lineage_missing")
    message_ids = frozenset(
        observation_to_message[observation_id] for observation_id in registry.observation_ids
    )
    thread_ids = frozenset(
        observation_to_thread[observation_id] for observation_id in registry.observation_ids
    )
    return _ExclusionRegistry(
        observation_ids=registry.observation_ids,
        message_ids=message_ids,
        thread_ids=thread_ids,
        query_hashes=registry.query_hashes,
        case_fingerprints=registry.case_fingerprints,
        registry_fingerprint=sha256_json(
            {
                "base_registry_fingerprint": registry.registry_fingerprint,
                "message_hashes": sorted(sha256_json(item) for item in message_ids),
                "thread_hashes": sorted(sha256_json(item) for item in thread_ids),
            }
        ),
    )


def _partition_records(
    *,
    records: Sequence[_SourceRecord],
    observation_to_message: Mapping[str, str],
    observation_to_thread: Mapping[str, str],
    development_registry: _ExclusionRegistry,
    base_registry: _ExclusionRegistry,
) -> _Partition:
    message_times: dict[str, datetime] = {}
    message_threads: dict[str, str] = {}
    for record in records:
        previous_time = message_times.setdefault(record.message_id, record.sent_at)
        previous_thread = message_threads.setdefault(record.message_id, record.thread_id)
        if previous_time != record.sent_at or previous_thread != record.thread_id:
            raise HoldoutExtensionError("message_lineage_inconsistent")
    ordered_messages = sorted(
        message_times,
        key=lambda message_id: (
            message_times[message_id],
            sha256_json(message_id),
        ),
    )
    if not ordered_messages:
        raise HoldoutExtensionError("source_body_records_empty")
    cutoff = (
        (TIME_PARTITION_DENOMINATOR - TIME_PARTITION_NUMERATOR) * len(ordered_messages)
    ) // TIME_PARTITION_DENOMINATOR
    latest_message_ids = frozenset(ordered_messages[cutoff:])
    thread_members: dict[str, set[str]] = defaultdict(set)
    for message_id, thread_id in message_threads.items():
        thread_members[thread_id].add(message_id)
    excluded_observations = development_registry.observation_ids | base_registry.observation_ids
    excluded_messages = development_registry.message_ids | base_registry.message_ids
    excluded_threads = development_registry.thread_ids | base_registry.thread_ids
    eligible_thread_ids = frozenset(
        thread_id
        for thread_id, message_ids in thread_members.items()
        if message_ids <= latest_message_ids and thread_id not in excluded_threads
    )
    eligible_message_ids = frozenset(
        message_id
        for thread_id in eligible_thread_ids
        for message_id in thread_members[thread_id]
        if message_id not in excluded_messages
    )
    eligible_records = tuple(
        record
        for record in records
        if record.observation_id not in excluded_observations
        and record.message_id in eligible_message_ids
        and record.thread_id in eligible_thread_ids
    )
    boundary_time = message_times[ordered_messages[cutoff]]
    time_boundary_fingerprint = sha256_json(
        {
            "partition_policy_fingerprint": PARTITION_POLICY_FINGERPRINT,
            "source_message_count": len(ordered_messages),
            "cutoff_rank": cutoff,
            "boundary_time": boundary_time.isoformat(),
        }
    )
    partition_fingerprint = sha256_json(
        {
            "partition_policy_fingerprint": PARTITION_POLICY_FINGERPRINT,
            "time_boundary_fingerprint": time_boundary_fingerprint,
            "development_registry_fingerprint": development_registry.registry_fingerprint,
            "base_registry_fingerprint": base_registry.registry_fingerprint,
            "eligible_observation_hashes": sorted(
                record.evidence.observation_hash for record in eligible_records
            ),
            "eligible_message_hashes": sorted(sha256_json(item) for item in eligible_message_ids),
            "eligible_thread_hashes": sorted(sha256_json(item) for item in eligible_thread_ids),
        }
    )
    return _Partition(
        eligible_records=eligible_records,
        observation_to_message=observation_to_message,
        observation_to_thread=observation_to_thread,
        excluded_observation_ids=frozenset(excluded_observations),
        excluded_message_ids=frozenset(excluded_messages),
        excluded_thread_ids=frozenset(excluded_threads),
        latest_message_ids=latest_message_ids,
        eligible_message_ids=eligible_message_ids,
        eligible_thread_ids=eligible_thread_ids,
        time_boundary_fingerprint=time_boundary_fingerprint,
        partition_fingerprint=partition_fingerprint,
    )


def _build_candidates(
    records: Sequence[_SourceRecord],
    *,
    profile: MailCandidateAdmissionTokenizerProfile,
    owner_user_id: str,
    workspace_id: str,
) -> tuple[_Candidate, ...]:
    document_frequency = _document_frequency(records)
    record_concepts = {
        record.observation_id: _record_concepts(
            record,
            document_frequency=document_frequency,
        )
        for record in records
    }
    identifier_records: dict[tuple[str, str], list[_SourceRecord]] = defaultdict(list)
    for record in records:
        for identifier, identifier_kind in record.evidence.identifiers:
            identifier_records[(identifier, identifier_kind)].append(record)
    identifier_frequency = {
        key: len({record.message_id for record in rows}) for key, rows in identifier_records.items()
    }
    candidates: list[_Candidate] = []
    candidates.extend(
        _graph_candidates(
            identifier_records=identifier_records,
            identifier_frequency=identifier_frequency,
            record_concepts=record_concepts,
            profile=profile,
            requester_user_id=owner_user_id,
        )
    )
    candidates.extend(
        _exact_candidates(
            records,
            record_concepts=record_concepts,
            profile=profile,
            requester_user_id=owner_user_id,
        )
    )
    single_identifier_records = tuple(
        record
        for record in records
        if len(record.evidence.identifiers) == 1 and record_concepts[record.observation_id]
    )
    candidates.extend(
        _near_miss_candidates(
            single_identifier_records,
            all_records=records,
            record_concepts=record_concepts,
            profile=profile,
            requester_user_id=owner_user_id,
        )
    )
    candidates.extend(
        _single_record_candidates(
            single_identifier_records,
            stratum="permission_denied",
            record_concepts=record_concepts,
            profile=profile,
            requester_user_id=_denied_requester_id(
                owner_user_id=owner_user_id,
                workspace_id=workspace_id,
            ),
        )
    )
    candidates.extend(
        _single_record_candidates(
            single_identifier_records,
            stratum="single_document_direct_lookup",
            record_concepts=record_concepts,
            profile=profile,
            requester_user_id=owner_user_id,
        )
    )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                _SELECTION_STRATUM_ORDER.index(candidate.stratum),
                _stratum_rank(candidate.identifier_kind),
                candidate.candidate_fingerprint,
            ),
        )
    )


def _document_frequency(records: Sequence[_SourceRecord]) -> dict[str, int]:
    postings: dict[str, set[str]] = defaultdict(set)
    for record in records:
        for token in record.evidence.tokens:
            postings[token].add(record.message_id)
    return {token: len(message_ids) for token, message_ids in postings.items()}


def _record_concepts(
    record: _SourceRecord,
    *,
    document_frequency: Mapping[str, int],
) -> tuple[str, ...]:
    identifiers = {identifier for identifier, _kind in record.evidence.identifiers}
    concepts = [
        token
        for token in record.evidence.lexical_tokens
        if token not in identifiers
        and 0 < document_frequency.get(token, 0) <= MAX_CONCEPT_DOCUMENT_FREQUENCY
    ]
    return tuple(
        sorted(
            concepts,
            key=lambda token: (
                document_frequency[token],
                sha256_json(token),
            ),
        )
    )


def _graph_candidates(
    *,
    identifier_records: Mapping[tuple[str, str], Sequence[_SourceRecord]],
    identifier_frequency: Mapping[tuple[str, str], int],
    record_concepts: Mapping[str, tuple[str, ...]],
    profile: MailCandidateAdmissionTokenizerProfile,
    requester_user_id: str,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for (identifier, identifier_kind), rows in identifier_records.items():
        frequency = identifier_frequency[(identifier, identifier_kind)]
        if not (MIN_IDENTIFIER_MESSAGE_FREQUENCY <= frequency <= MAX_IDENTIFIER_MESSAGE_FREQUENCY):
            continue
        ordered = sorted(rows, key=lambda record: record.evidence.observation_hash)
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                left_concepts = record_concepts[left.observation_id]
                right_concepts = record_concepts[right.observation_id]
                if (
                    left.message_id == right.message_id
                    or left.thread_id == right.thread_id
                    or not left_concepts
                    or not right_concepts
                ):
                    continue
                left_concept = left_concepts[0]
                right_concept = right_concepts[0]
                if left_concept == right_concept:
                    continue
                query = (
                    f"Find the authorized relationship for {identifier} "
                    f"between {left_concept} and {right_concept}"
                )
                if not _query_covers(
                    profile,
                    query,
                    identifiers=(identifier,),
                    concepts=(left_concept, right_concept),
                ):
                    continue
                route = _route(
                    stratum="graph_required",
                    query_class="relation_reasoning",
                    result_kind="owner_match",
                )
                fingerprint = _candidate_fingerprint(
                    stratum="graph_required",
                    identifier_kind=identifier_kind,
                    observation_hashes=(
                        left.evidence.observation_hash,
                        right.evidence.observation_hash,
                    ),
                    identifier_hashes=(sha256_json(identifier),),
                    concept_hashes=(
                        sha256_json(left_concept),
                        sha256_json(right_concept),
                    ),
                    route=route,
                )
                candidates.append(
                    _Candidate(
                        stratum="graph_required",
                        identifier_kind=identifier_kind,
                        records=(left, right),
                        query_text=query,
                        requester_user_id=requester_user_id,
                        route=route,
                        required_observation_ids=tuple(
                            sorted((left.observation_id, right.observation_id))
                        ),
                        forbidden_observation_ids=(),
                        authoring_observation_ids=tuple(
                            sorted((left.observation_id, right.observation_id))
                        ),
                        adjudication={
                            "answer_kind": "source_backed_relation",
                            "shared_identifier": identifier,
                            "left_concept": left_concept,
                            "right_concept": right_concept,
                            "required_source_observation_ids": sorted(
                                (left.observation_id, right.observation_id)
                            ),
                        },
                        candidate_fingerprint=fingerprint,
                    )
                )
    return candidates


def _exact_candidates(
    records: Sequence[_SourceRecord],
    *,
    record_concepts: Mapping[str, tuple[str, ...]],
    profile: MailCandidateAdmissionTokenizerProfile,
    requester_user_id: str,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for record in records:
        identifiers = tuple(sorted({item for item, _kind in record.evidence.identifiers}))
        if len(identifiers) < 2 or not record_concepts[record.observation_id]:
            continue
        concept = record_concepts[record.observation_id][0]
        kind_counts = Counter(kind for _item, kind in record.evidence.identifiers)
        identifier_kind = next(iter(kind_counts)) if len(kind_counts) == 1 else "mixed_identifier"
        for stratum, directive in (
            ("exact_set", "list the complete protected identifier set"),
            ("exact_count", "count the complete protected identifier set"),
            (
                "exact_aggregation",
                "aggregate the complete protected identifier set by kind",
            ),
        ):
            query = f"For {concept}, {directive}"
            if not _query_covers(
                profile,
                query,
                identifiers=(),
                concepts=(concept,),
            ):
                continue
            route = _route(
                stratum=stratum,
                query_class="exact_inventory",
                result_kind=stratum,
            )
            adjudication: dict[str, Any] = {
                "answer_kind": stratum,
                "inventory_kind": "protected_identifier",
                "required_source_observation_ids": [record.observation_id],
            }
            if stratum == "exact_set":
                adjudication["items"] = list(identifiers)
            elif stratum == "exact_count":
                adjudication["count"] = len(identifiers)
            else:
                adjudication["counts_by_identifier_kind"] = dict(sorted(kind_counts.items()))
            fingerprint = _candidate_fingerprint(
                stratum=stratum,
                identifier_kind=identifier_kind,
                observation_hashes=(record.evidence.observation_hash,),
                identifier_hashes=tuple(sha256_json(item) for item in identifiers),
                concept_hashes=(sha256_json(concept),),
                route=route,
            )
            candidates.append(
                _Candidate(
                    stratum=stratum,
                    identifier_kind=identifier_kind,
                    records=(record,),
                    query_text=query,
                    requester_user_id=requester_user_id,
                    route=route,
                    required_observation_ids=(record.observation_id,),
                    forbidden_observation_ids=(),
                    authoring_observation_ids=(record.observation_id,),
                    adjudication=adjudication,
                    candidate_fingerprint=fingerprint,
                )
            )
    return candidates


def _near_miss_candidates(
    records: Sequence[_SourceRecord],
    *,
    all_records: Sequence[_SourceRecord],
    record_concepts: Mapping[str, tuple[str, ...]],
    profile: MailCandidateAdmissionTokenizerProfile,
    requester_user_id: str,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    ordered_donors = sorted(records, key=lambda item: item.evidence.observation_hash)
    observed_tokens_by_identifier: dict[str, set[str]] = defaultdict(set)
    for record in all_records:
        for identifier, _identifier_kind in record.evidence.identifiers:
            observed_tokens_by_identifier[identifier].update(record.evidence.tokens)
    eligible_observation_set_fingerprint = sha256_json(
        sorted(record.evidence.observation_hash for record in all_records)
    )
    for identifier_record in ordered_donors:
        identifier, identifier_kind = identifier_record.evidence.identifiers[0]
        donor_count = 0
        for donor in ordered_donors:
            if (
                donor.observation_id == identifier_record.observation_id
                or donor.message_id == identifier_record.message_id
                or donor.thread_id == identifier_record.thread_id
            ):
                continue
            donor_concepts = record_concepts[donor.observation_id]
            if not donor_concepts:
                continue
            concept = donor_concepts[0]
            if concept in observed_tokens_by_identifier[identifier]:
                continue
            query = f"Find the authorized relationship between {identifier} and {concept}"
            if not _query_covers(
                profile,
                query,
                identifiers=(identifier,),
                concepts=(concept,),
            ):
                continue
            route = _route(
                stratum="no_answer_near_miss_negative",
                query_class="relation_reasoning",
                result_kind="no_answer",
            )
            absence_fingerprint = sha256_json(
                {
                    "identifier_hash": sha256_json(identifier),
                    "concept_hash": sha256_json(concept),
                    "eligible_observation_set_fingerprint": (eligible_observation_set_fingerprint),
                    "cooccurrence_count": 0,
                }
            )
            fingerprint = _candidate_fingerprint(
                stratum="no_answer_near_miss_negative",
                identifier_kind=identifier_kind,
                observation_hashes=(
                    identifier_record.evidence.observation_hash,
                    donor.evidence.observation_hash,
                ),
                identifier_hashes=(sha256_json(identifier),),
                concept_hashes=(sha256_json(concept),),
                route=route,
            )
            authoring_ids = tuple(sorted((identifier_record.observation_id, donor.observation_id)))
            candidates.append(
                _Candidate(
                    stratum="no_answer_near_miss_negative",
                    identifier_kind=identifier_kind,
                    records=(identifier_record, donor),
                    query_text=query,
                    requester_user_id=requester_user_id,
                    route=route,
                    required_observation_ids=(),
                    forbidden_observation_ids=authoring_ids,
                    authoring_observation_ids=authoring_ids,
                    adjudication={
                        "answer_kind": "no_answer",
                        "absence_proof_fingerprint": absence_fingerprint,
                        "forbidden_source_observation_ids": list(authoring_ids),
                    },
                    candidate_fingerprint=fingerprint,
                )
            )
            donor_count += 1
            if donor_count >= NEGATIVE_DONOR_LIMIT_PER_IDENTIFIER:
                break
    return candidates


def _single_record_candidates(
    records: Sequence[_SourceRecord],
    *,
    stratum: str,
    record_concepts: Mapping[str, tuple[str, ...]],
    profile: MailCandidateAdmissionTokenizerProfile,
    requester_user_id: str,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for record in records:
        identifier, identifier_kind = record.evidence.identifiers[0]
        concept = record_concepts[record.observation_id][0]
        if stratum == "permission_denied":
            query = f"Retrieve authorized evidence for {identifier} and {concept}"
            result_kind = "permission_denied"
        else:
            query = f"Retrieve the source evidence for {identifier} and {concept}"
            result_kind = "source_evidence"
        if not _query_covers(
            profile,
            query,
            identifiers=(identifier,),
            concepts=(concept,),
        ):
            continue
        route = _route(
            stratum=stratum,
            query_class="evidence_lookup",
            result_kind=result_kind,
        )
        fingerprint = _candidate_fingerprint(
            stratum=stratum,
            identifier_kind=identifier_kind,
            observation_hashes=(record.evidence.observation_hash,),
            identifier_hashes=(sha256_json(identifier),),
            concept_hashes=(sha256_json(concept),),
            route=route,
        )
        adjudication: dict[str, Any] = {
            "answer_kind": result_kind,
            "required_source_observation_ids": [record.observation_id],
        }
        required_ids: tuple[str, ...]
        forbidden_ids: tuple[str, ...]
        if stratum == "permission_denied":
            required_ids = ()
            forbidden_ids = (record.observation_id,)
            adjudication["denied_source_observation_ids"] = [record.observation_id]
        else:
            required_ids = (record.observation_id,)
            forbidden_ids = ()
        adjudication["requester_user_id"] = requester_user_id
        candidates.append(
            _Candidate(
                stratum=stratum,
                identifier_kind=identifier_kind,
                records=(record,),
                query_text=query,
                requester_user_id=requester_user_id,
                route=route,
                required_observation_ids=required_ids,
                forbidden_observation_ids=forbidden_ids,
                authoring_observation_ids=(record.observation_id,),
                adjudication=adjudication,
                candidate_fingerprint=fingerprint,
            )
        )
    return candidates


def _route(
    *,
    stratum: str,
    query_class: str,
    result_kind: str,
) -> dict[str, Any]:
    route = {
        "router_profile_id": "issue56_source_authored_mail_holdout_router_v1",
        "source_kind": "mail",
        "stratum_id": stratum,
        "query_class": query_class,
        "intent_kind": (
            "relation_reasoning"
            if query_class == "relation_reasoning"
            else "exact_inventory"
            if query_class == "exact_inventory"
            else "evidence_lookup"
        ),
        "result_kind": result_kind,
        "query_template_version": QUERY_TEMPLATE_VERSION,
    }
    route["route_fingerprint"] = sha256_json(route)
    return route


def _candidate_fingerprint(
    *,
    stratum: str,
    identifier_kind: str,
    observation_hashes: Sequence[str],
    identifier_hashes: Sequence[str],
    concept_hashes: Sequence[str],
    route: Mapping[str, Any],
) -> str:
    return sha256_json(
        {
            "selection_policy_fingerprint": CANDIDATE_IDENTITY_POLICY_FINGERPRINT,
            "stratum": stratum,
            "identifier_kind": identifier_kind,
            "observation_hashes": sorted(observation_hashes),
            "identifier_hashes": sorted(identifier_hashes),
            "concept_hashes": sorted(concept_hashes),
            "route_fingerprint": route["route_fingerprint"],
        }
    )


def _query_covers(
    profile: MailCandidateAdmissionTokenizerProfile,
    query_text: str,
    *,
    identifiers: Sequence[str],
    concepts: Sequence[str],
) -> bool:
    analysis = profile.analyze(query_text)
    protected = {span.exact_token for span in analysis.protected_identifiers}
    return all(identifier in protected for identifier in identifiers) and all(
        concept in analysis.tokens for concept in concepts
    )


def _denied_requester_id(*, owner_user_id: str, workspace_id: str) -> str:
    suffix = sha256_json(
        {
            "policy_id": SELECTION_POLICY_ID,
            "owner_user_id_hash": sha256_json(owner_user_id),
            "workspace_id_hash": sha256_json(workspace_id),
        }
    ).removeprefix("sha256:")[:24]
    requester = f"unauthorized-holdout-{suffix}"
    if requester == owner_user_id:
        raise HoldoutExtensionError("denied_requester_collision")
    return requester


def _select_candidates(
    candidates: Sequence[_Candidate],
    *,
    base_registry: _ExclusionRegistry,
) -> tuple[tuple[_Candidate, ...], dict[str, Any]]:
    by_stratum: dict[str, list[_Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_stratum[candidate.stratum].append(candidate)
    selected: list[_Candidate] = []
    used_observations: set[str] = set()
    used_messages: set[str] = set()
    used_threads: set[str] = set()
    used_queries = set(base_registry.query_hashes)
    generated_fingerprints = set(base_registry.case_fingerprints)
    candidate_counts = {stratum: len(by_stratum[stratum]) for stratum in _SELECTION_STRATUM_ORDER}
    selected_counts: Counter[str] = Counter()
    for stratum in _SELECTION_STRATUM_ORDER:
        quota = TARGET_STRATA_COUNTS[stratum]
        for candidate in by_stratum[stratum]:
            query_hash = sha256_json(candidate.query_text)
            provisional_case_fingerprint = _provisional_case_fingerprint(candidate)
            if (
                candidate.observation_ids & used_observations
                or candidate.message_ids & used_messages
                or candidate.thread_ids & used_threads
                or len(candidate.observation_ids) != len(candidate.records)
                or len(candidate.message_ids) != len(candidate.records)
                or len(candidate.thread_ids) != len(candidate.records)
                or query_hash in used_queries
                or provisional_case_fingerprint in generated_fingerprints
            ):
                continue
            selected.append(candidate)
            selected_counts[stratum] += 1
            used_observations.update(candidate.observation_ids)
            used_messages.update(candidate.message_ids)
            used_threads.update(candidate.thread_ids)
            used_queries.add(query_hash)
            generated_fingerprints.add(provisional_case_fingerprint)
            if selected_counts[stratum] == quota:
                break
        if selected_counts[stratum] != quota:
            raise HoldoutExtensionError(f"capacity_shortfall_{stratum}")
    if len(selected) != EXTENSION_CASE_COUNT:
        raise HoldoutExtensionError("extension_case_count_mismatch")
    return (
        tuple(selected),
        {
            "candidate_counts": dict(sorted(candidate_counts.items())),
            "selected_counts": dict(sorted(selected_counts.items())),
            "eligible_candidate_count": sum(candidate_counts.values()),
        },
    )


def _provisional_case_fingerprint(candidate: _Candidate) -> str:
    return sha256_json(
        {
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "query_hash": sha256_json(candidate.query_text),
            "route_fingerprint": candidate.route["route_fingerprint"],
            "authoring_observation_hashes": sorted(
                record.evidence.observation_hash for record in candidate.records
            ),
        }
    )


def _build_private_cases(
    selected: Sequence[_Candidate],
    *,
    partition: _Partition,
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for candidate in selected:
        route = dict(candidate.route)
        route_fingerprint = route["route_fingerprint"]
        evidence_binding = {
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "required_observation_hashes": sorted(
                record.evidence.observation_hash
                for record in candidate.records
                if record.observation_id in candidate.required_observation_ids
            ),
            "authoring_observation_hashes": sorted(
                record.evidence.observation_hash for record in candidate.records
            ),
            "authoring_message_hashes": sorted(
                sha256_json(record.message_id) for record in candidate.records
            ),
            "authoring_thread_hashes": sorted(
                sha256_json(record.thread_id) for record in candidate.records
            ),
            "partition_fingerprint": partition.partition_fingerprint,
        }
        case: dict[str, Any] = {
            "case_id": (
                "issue56_holdout_extension_"
                + candidate.candidate_fingerprint.removeprefix("sha256:")[:24]
            ),
            "domain": "mail",
            "source_kind": "mail",
            "stratum_id": candidate.stratum,
            "intent_kind": route["intent_kind"],
            "pattern": f"source_authored_{candidate.stratum}_v1",
            "result_kind": route["result_kind"],
            "query_text": candidate.query_text,
            "query_hash": sha256_json(candidate.query_text),
            "requester_user_id": candidate.requester_user_id,
            "required_source_observation_ids": list(candidate.required_observation_ids),
            "forbidden_source_observation_ids": list(candidate.forbidden_observation_ids),
            "authoring_source_observation_ids": list(candidate.authoring_observation_ids),
            "required_match_count": len(candidate.required_observation_ids),
            "limit": RESULT_LIMIT,
            "typed_route": route,
            "route_fingerprint": route_fingerprint,
            "source_evidence_binding": evidence_binding,
            "adjudication": dict(candidate.adjudication),
        }
        case["private_fingerprint"] = _provisional_case_fingerprint(candidate)
        cases.append(case)
    return cases


def _validate_extension_disjointness(
    *,
    cases: Sequence[Mapping[str, Any]],
    selected: Sequence[_Candidate],
    partition: _Partition,
    development_registry: _ExclusionRegistry,
    base_registry: _ExclusionRegistry,
) -> dict[str, Any]:
    observation_ids = [item for candidate in selected for item in candidate.observation_ids]
    message_ids = [item for candidate in selected for item in candidate.message_ids]
    thread_ids = [item for candidate in selected for item in candidate.thread_ids]
    query_hashes = [str(case["query_hash"]) for case in cases]
    case_fingerprints = [str(case["private_fingerprint"]) for case in cases]
    if (
        len(observation_ids) != len(set(observation_ids))
        or len(message_ids) != len(set(message_ids))
        or len(thread_ids) != len(set(thread_ids))
        or len(query_hashes) != len(set(query_hashes))
        or len(case_fingerprints) != len(set(case_fingerprints))
    ):
        raise HoldoutExtensionError("extension_internal_reuse_detected")
    observation_set = frozenset(observation_ids)
    message_set = frozenset(message_ids)
    thread_set = frozenset(thread_ids)
    if (
        observation_set & partition.excluded_observation_ids
        or message_set & partition.excluded_message_ids
        or thread_set & partition.excluded_thread_ids
        or set(query_hashes) & base_registry.query_hashes
        or set(case_fingerprints) & base_registry.case_fingerprints
    ):
        raise HoldoutExtensionError("extension_exclusion_overlap_detected")
    if (
        not message_set <= partition.eligible_message_ids
        or not thread_set <= partition.eligible_thread_ids
    ):
        raise HoldoutExtensionError("extension_case_outside_frozen_partition")
    return {
        "status": "passed",
        "development_observation_overlap_count": len(
            observation_set & development_registry.observation_ids
        ),
        "development_message_overlap_count": len(message_set & development_registry.message_ids),
        "development_thread_overlap_count": len(thread_set & development_registry.thread_ids),
        "base_holdout_observation_overlap_count": len(
            observation_set & base_registry.observation_ids
        ),
        "base_holdout_message_overlap_count": len(message_set & base_registry.message_ids),
        "base_holdout_thread_overlap_count": len(thread_set & base_registry.thread_ids),
        "base_holdout_query_overlap_count": len(set(query_hashes) & base_registry.query_hashes),
        "base_holdout_case_fingerprint_overlap_count": len(
            set(case_fingerprints) & base_registry.case_fingerprints
        ),
        "extension_observation_reuse_count": len(observation_ids) - len(observation_set),
        "extension_message_reuse_count": len(message_ids) - len(message_set),
        "extension_thread_reuse_count": len(thread_ids) - len(thread_set),
        "extension_query_reuse_count": len(query_hashes) - len(set(query_hashes)),
        "extension_case_fingerprint_reuse_count": len(case_fingerprints)
        - len(set(case_fingerprints)),
        "extension_observation_count": len(observation_set),
        "extension_message_count": len(message_set),
        "extension_thread_count": len(thread_set),
        "extension_observation_set_fingerprint": sha256_json(
            sorted(sha256_json(item) for item in observation_set)
        ),
        "extension_message_set_fingerprint": sha256_json(
            sorted(sha256_json(item) for item in message_set)
        ),
        "extension_thread_set_fingerprint": sha256_json(
            sorted(sha256_json(item) for item in thread_set)
        ),
        "extension_query_set_fingerprint": sha256_json(sorted(query_hashes)),
        "extension_case_set_fingerprint": sha256_json(sorted(case_fingerprints)),
    }


def _selection_proof(
    *,
    candidates: Sequence[_Candidate],
    selected: Sequence[_Candidate],
    capacity: Mapping[str, Any],
) -> dict[str, Any]:
    proof: dict[str, Any] = {
        "status": "passed",
        "selection_order": _SELECTION_POLICY["selection_order"],
        "capacity_shortfall_policy": "fail_closed_no_redistribution",
        "candidate_counts": dict(capacity["candidate_counts"]),
        "selected_counts": dict(capacity["selected_counts"]),
        "eligible_candidate_count": capacity["eligible_candidate_count"],
        "selected_candidate_count": len(selected),
        "candidate_inventory_fingerprint": sha256_json(
            sorted(candidate.candidate_fingerprint for candidate in candidates)
        ),
        "selected_candidate_fingerprint": sha256_json(
            [candidate.candidate_fingerprint for candidate in selected]
        ),
    }
    proof["selection_proof_fingerprint"] = sha256_json(proof)
    return proof


def _capacity_audit_binding(
    *,
    source_bindings: Mapping[str, str],
    partition: _Partition,
    selection_proof: Mapping[str, Any],
) -> dict[str, Any]:
    binding: dict[str, Any] = {
        "artifact_id": "formowl_issue56_holdout_extension_capacity_audit_binding_v1",
        "status": "passed",
        "capacity_audit_policy_id": CAPACITY_AUDIT_POLICY_ID,
        "capacity_audit_policy_fingerprint": ALTERNATIVE_STRATA_POLICY_FINGERPRINT,
        "target_strata_counts": dict(TARGET_STRATA_COUNTS),
        "source_snapshot_fingerprint": source_bindings["source_snapshot_fingerprint"],
        "partition_fingerprint": partition.partition_fingerprint,
        "candidate_inventory_fingerprint": selection_proof["candidate_inventory_fingerprint"],
        "selected_candidate_fingerprint": selection_proof["selected_candidate_fingerprint"],
        "selection_proof_fingerprint": selection_proof["selection_proof_fingerprint"],
        "capacity_shortfall_policy": "fail_closed_no_redistribution",
    }
    binding["capacity_audit_binding_fingerprint"] = sha256_json(binding)
    return binding


def _safe_projection(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    selected: Sequence[_Candidate],
    cases: Sequence[Mapping[str, Any]],
    partition: _Partition,
    capacity: Mapping[str, Any],
) -> dict[str, Any]:
    safe_cases: list[dict[str, Any]] = []
    for candidate, case in zip(selected, cases, strict=True):
        safe_cases.append(
            {
                "manifest_entry_hash": case["private_fingerprint"],
                "case_id_hash": sha256_json(case["case_id"]),
                "query_hash": case["query_hash"],
                "stratum_id": candidate.stratum,
                "identifier_kind": candidate.identifier_kind,
                "route": dict(candidate.route),
                "route_fingerprint": candidate.route["route_fingerprint"],
                "authoring_observation_count": len(candidate.observation_ids),
                "authoring_message_count": len(candidate.message_ids),
                "authoring_thread_count": len(candidate.thread_ids),
                "authoring_observation_set_fingerprint": sha256_json(
                    sorted(record.evidence.observation_hash for record in candidate.records)
                ),
            }
        )
    projection: dict[str, Any] = {
        "artifact_id": PROJECTION_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "sealed_oracle_free",
        "classification": CLASSIFICATION,
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "final_acceptance_eligible": True,
        "diagnostic_only": False,
        "private_manifest_binding": {
            "artifact_id": ARTIFACT_ID,
            "schema_version": SCHEMA_VERSION,
            "manifest_sha256": manifest_sha256,
            "manifest_fingerprint": manifest["manifest_fingerprint"],
        },
        "base_holdout_binding": dict(manifest["base_holdout_binding"]),
        "source_binding_hashes": {
            (
                "segmentation_profile_fingerprint"
                if key == "tokenizer_profile_fingerprint"
                else key
            ): value
            for key, value in manifest["source_bindings"].items()
        },
        "selection_policy_fingerprint": SELECTION_POLICY_FINGERPRINT,
        "capacity_audit_binding": dict(manifest["capacity_audit_binding"]),
        "partition_policy_fingerprint": PARTITION_POLICY_FINGERPRINT,
        "partition_fingerprint": partition.partition_fingerprint,
        "selection_proof_fingerprint": manifest["selection_proof"]["selection_proof_fingerprint"],
        "counts": {
            "base_case_count": BASE_HOLDOUT_CASE_COUNT,
            "extension_case_count": EXTENSION_CASE_COUNT,
            "combined_acceptance_case_count": COMBINED_ACCEPTANCE_CASE_COUNT,
            "eligible_observation_count": len(partition.eligible_records),
            "eligible_message_count": len(partition.eligible_message_ids),
            "eligible_thread_count": len(partition.eligible_thread_ids),
            "selected_observation_count": manifest["disjointness_proof"][
                "extension_observation_count"
            ],
            "selected_message_count": manifest["disjointness_proof"]["extension_message_count"],
            "selected_thread_count": manifest["disjointness_proof"]["extension_thread_count"],
            "candidate_count": capacity["eligible_candidate_count"],
            "overlap_count": 0,
            "reuse_count": 0,
            "blocker_count": 0,
        },
        "strata_counts": dict(TARGET_STRATA_COUNTS),
        "disjointness_proof_hash": sha256_json(manifest["disjointness_proof"]),
        "cases": safe_cases,
    }
    projection["projection_fingerprint"] = _payload_fingerprint(
        projection,
        "projection_fingerprint",
    )
    serialized = json.dumps(projection, ensure_ascii=True, sort_keys=True)
    for forbidden_field in (
        "query_text",
        "requester_user_id",
        "required_source_observation_ids",
        "forbidden_source_observation_ids",
        "authoring_source_observation_ids",
        "adjudication",
        "shared_identifier",
        "items",
        "counts_by_identifier_kind",
    ):
        if forbidden_field in serialized:
            raise HoldoutExtensionError("safe_projection_private_field_leak")
    assert_no_public_raw_references(
        projection,
        "issue56_independent_mail_holdout_extension_projection",
    )
    return projection


def _read_sealed_json(
    path: Path,
    expected_sha256: str,
    *,
    maximum_bytes: int,
    reason_prefix: str,
) -> tuple[bytes, dict[str, Any]]:
    expected = _require_sha256(
        expected_sha256,
        f"{reason_prefix}_expected_sha256_invalid",
    )
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise HoldoutExtensionError(f"{reason_prefix}_missing_or_invalid") from exc
    if (
        stat.S_ISLNK(path_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_size <= 0
        or path_stat.st_size > maximum_bytes
    ):
        raise HoldoutExtensionError(f"{reason_prefix}_missing_or_invalid")
    payload = path.read_bytes()
    if _sha256_bytes(payload) != expected:
        raise HoldoutExtensionError(f"{reason_prefix}_seal_mismatch")
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldoutExtensionError(f"{reason_prefix}_missing_or_invalid") from exc
    if not isinstance(decoded, dict):
        raise HoldoutExtensionError(f"{reason_prefix}_missing_or_invalid")
    return payload, decoded


def _persist_atomic_directory(
    *,
    output_root: Path,
    files: Mapping[str, tuple[bytes, int]],
    write_staged_file: Callable[[Path, bytes, int], None],
) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise HoldoutExtensionError("immutable_output_already_exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.staging-",
            dir=output_root.parent,
        )
    )
    try:
        for filename, (payload, mode) in files.items():
            write_staged_file(staging / filename, payload, mode)
        _fsync_directory(staging)
        _rename_directory_noreplace(staging, output_root)
        _fsync_directory(output_root.parent)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if output_root.exists():
            shutil.rmtree(output_root, ignore_errors=True)
        raise


def _write_file_exclusive(path: Path, payload: bytes, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, mode)
    finally:
        os.close(descriptor)


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise HoldoutExtensionError("atomic_noreplace_unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {17, 39}:
        raise HoldoutExtensionError("immutable_output_already_exists")
    raise HoldoutExtensionError("atomic_publish_failed")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _require_sha256(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise HoldoutExtensionError(reason_code)
    return value


def _string_list(value: Any, reason_code: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise HoldoutExtensionError(reason_code)
    return tuple(value)


def _rejection(reason: Any) -> dict[str, Any]:
    blocker = (
        reason
        if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]+", reason)
        else "holdout_extension_authoring_failed"
    )
    report = {
        "artifact_id": REJECTION_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "execution_status": "not_run",
        "counts": {"case_count": 0, "blocker_count": 1},
        "blocker_ids": [blocker],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    assert_no_public_raw_references(
        report,
        "issue56_independent_mail_holdout_extension_rejection",
    )
    return report


if __name__ == "__main__":
    raise SystemExit(main())
