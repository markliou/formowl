#!/usr/bin/env python3
"""Author sealed oracle-free holdout projection inputs at the source boundary.

This tool is source-author-only.  It may decode sealed private holdout and
development manifests, but it emits only non-reversible execution metadata,
hashes, counts, and disjointness proof.  It never evaluates quality, executes
UAT, or returns private input content on stdout.
"""

from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from dataclasses import dataclass
import errno
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import (  # noqa: E402
    issue56_holdout_oracle_free_projection as projection_contract,
)


SCHEMA_VERSION = 1
RESULT_ARTIFACT_ID = "formowl_issue56_holdout_source_author_projection_inputs_result_v1"
REJECTION_ARTIFACT_ID = "formowl_issue56_holdout_source_author_projection_inputs_rejection_v1"
DEVELOPMENT_MANIFEST_ARTIFACT_ID = "formowl_issue56_source_development_uat_manifest_v1"
DEVELOPMENT_SAFE_REPORT_ARTIFACT_ID = "formowl_issue56_source_development_uat_manifest_report_v1"
SOURCE_REPORT_ARTIFACT_ID = (
    "formowl_issue56_native_source_complete_authorized_observation_report_v1"
)
SOURCE_LINEAGE_FILENAME = "holdout-source-lineage.safe.json"
DEVELOPMENT_DISJOINTNESS_FILENAME = "holdout-development-disjointness.safe.json"
SOURCE_AUTHOR_POLICY_ID = "issue56_holdout_source_author_oracle_free_projection_inputs_v1"

# The source-author boundary deliberately distinguishes three classes of
# private case fields:
#
# * fields consumed to validate or construct the oracle-free projection;
# * known oracle-only fields which are decoded here but never inspected; and
# * opaque private extensions, which are ignored and must not influence any
#   safe output fingerprint.
#
# The actual sealed v2 manifest has private extensions beyond the original v1
# authoring contract.  Treating the entire private object as a fingerprint
# input would make those extensions observable through the safe artifact.
_PRIVATE_CASE_PROJECTED_INPUT_FIELDS = frozenset(projection_contract._ORACLE_FREE_CASE_FIELD_NAMES)
_PRIVATE_CASE_IGNORED_ORACLE_FIELDS = frozenset(projection_contract._PRIVATE_ORACLE_FIELD_NAMES)
_PRIVATE_CASE_ALLOWED_FIELDS = (
    _PRIVATE_CASE_PROJECTED_INPUT_FIELDS | _PRIVATE_CASE_IGNORED_ORACLE_FIELDS
)
_CASE_REQUIRED_FIELDS = frozenset(
    {
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
)
_DEVELOPMENT_MANIFEST_FIELDS = frozenset(
    {
        "archive_sha256",
        "artifact_id",
        "case_count",
        "case_strata_counts",
        "cases",
        "claim_boundary_status",
        "classification",
        "distinct_required_message_occurrence_count",
        "distinct_required_observation_count",
        "holdout_content_consumed",
        "mail_evidence_bundle_id",
        "mail_import_session_id",
        "manifest_fingerprint",
        "oracle_content_consumed",
        "quality_evaluation_status",
        "required_evidence_reference_count",
        "schema_version",
        "selection_policy",
        "selection_policy_fingerprint",
        "source_bindings",
    }
)
_DEVELOPMENT_CASE_FIELDS = frozenset(
    {
        "case_id",
        "domain",
        "forbidden_source_observation_ids",
        "intent_kind",
        "limit",
        "pattern",
        "private_fingerprint",
        "query_text",
        "requester_user_id",
        "required_match_count",
        "required_source_observation_ids",
        "result_kind",
        "source_evidence_binding",
    }
)
_DEVELOPMENT_CASE_SOURCE_BINDING_FIELDS = frozenset(
    {
        "candidate_fingerprint",
        "required_message_occurrence_hashes",
        "required_observation_hashes",
    }
)
_DEVELOPMENT_SOURCE_BINDING_FIELDS = frozenset(
    {
        "bundle_artifact_byte_hash",
        "bundle_artifact_fingerprint",
        "index_fingerprint",
        "mail_evidence_bundle_fingerprint",
        "permission_fingerprint",
        "retrieval_report_byte_hash",
        "retrieval_snapshot_byte_hash",
        "retrieval_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "source_snapshot_fingerprint",
        "tokenizer_profile_fingerprint",
    }
)
_DEVELOPMENT_SELECTION_POLICY_FIELDS = frozenset(
    {
        "anchor_message_frequency_maximum",
        "anchor_policy",
        "case_count",
        "classification",
        "holdout_or_oracle_content_read",
        "identifier_message_frequency",
        "observation_reuse",
        "pair_policy",
        "policy_id",
        "quality_result_read",
        "query_template_id",
        "required_match_count",
        "result_limit",
        "selection_order",
        "source_kind",
    }
)
_DEVELOPMENT_STRATA = frozenset(
    {
        "amount",
        "business_identifier",
        "date",
        "domain",
        "email",
        "url",
    }
)
_DEVELOPMENT_SAFE_REPORT_FIELDS = frozenset(
    {
        "artifact_id",
        "blocker_ids",
        "claim_boundary_status",
        "classification",
        "counts",
        "fingerprints",
        "holdout_content_status",
        "immutable_write_status",
        "lineage_validation_status",
        "manifest_intake_status",
        "quality_evaluation_status",
        "report_fingerprint",
        "schema_version",
        "status",
        "strata",
    }
)
_DEVELOPMENT_SAFE_COUNT_FIELDS = frozenset(
    {
        "blocker_count",
        "case_count",
        "distinct_required_message_occurrence_count",
        "distinct_required_observation_count",
        "positive_graph_required_owner_case_count",
        "required_evidence_reference_count",
        "source_attachment_occurrence_count",
        "source_body_segment_count",
        "source_message_count",
        "unexplained_evidence_binding_count",
    }
)
_DEVELOPMENT_SAFE_FINGERPRINT_FIELDS = frozenset(
    {
        "bundle_artifact_fingerprint",
        "candidate_admission_profile_fingerprint",
        "index_fingerprint",
        "mail_evidence_bundle_fingerprint",
        "manifest_fingerprint",
        "manifest_sha256",
        "permission_fingerprint",
        "retrieval_snapshot_fingerprint",
        "selection_policy_fingerprint",
        "source_snapshot_fingerprint",
    }
)
_SOURCE_BUNDLE_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_fingerprint",
        "artifact_id",
        "bundle",
        "bundle_fingerprint",
        "schema_version",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "source_snapshot_fingerprint",
        "status",
    }
)
_SOURCE_COMPLETENESS_REPORT_FIELDS = frozenset(
    {
        "artifact_id",
        "schema_version",
        "status",
        "source_completeness_gate_status",
        "claim_boundary_status",
        "methodology_readiness_status",
        "canonical_fact_status",
        "source_asset_sha256",
        "native_manifest_fingerprint",
        "asset_binding_fingerprint",
        "permission_fingerprint",
        "source_ref_fingerprint",
        "parser_fingerprint",
        "source_inventory_fingerprint",
        "observation_snapshot_fingerprint",
        "message_lineage_fingerprint",
        "attachment_lineage_fingerprint",
        "folder_lineage_fingerprint",
        "unsupported_lineage_fingerprint",
        "snapshot_fingerprint",
        "blocker_fingerprints",
        "round_trip_status",
        "counts",
        "report_fingerprint",
    }
)
_SOURCE_COMPLETENESS_REQUIRED_COUNT_FIELDS = frozenset(
    {
        "folder_occurrence_count",
        "message_occurrence_count",
        "attachment_export_occurrence_count",
        "attachment_separate_export_count",
        "attachment_embedded_message_count",
        "attachment_synthetic_representation_count",
        "attachment_source_descriptor_binding_count",
        "attachment_export_file_binding_count",
        "attachment_source_inventory_binding_count",
        "attachment_parent_lineage_count",
        "attachment_content_hash_count",
        "message_source_inventory_binding_count",
        "message_parent_lineage_count",
        "unsupported_preserved_occurrence_count",
        "source_inventory_item_count",
        "observation_count",
        "missing_source_inventory_binding_count",
        "missing_parent_lineage_count",
        "missing_content_hash_count",
        "unexplained_loss_count",
        "failed_record_count",
        "blocker_count",
    }
)
_SOURCE_COMPLETENESS_OPTIONAL_COUNT_FIELDS = frozenset(
    {
        # Historical reports may carry this non-authoritative alias.  When it
        # exists it must equal attachment_export_occurrence_count.
        "attachment_occurrence_count",
    }
)
_SOURCE_COMPLETENESS_COUNT_FIELDS = (
    _SOURCE_COMPLETENESS_REQUIRED_COUNT_FIELDS | _SOURCE_COMPLETENESS_OPTIONAL_COUNT_FIELDS
)
_SOURCE_COMPLETENESS_ZERO_COUNT_FIELDS = frozenset(
    {
        "missing_source_inventory_binding_count",
        "missing_parent_lineage_count",
        "missing_content_hash_count",
        "unexplained_loss_count",
        "failed_record_count",
        "blocker_count",
    }
)
_SOURCE_OCCURRENCE_OBSERVATION_TYPES = {
    "mail_folder_occurrence": "folder_occurrence_count",
    "email_message_occurrence": "message_occurrence_count",
    "email_native_export_occurrence": "attachment_export_occurrence_count",
    "unsupported_pst_record_occurrence": "unsupported_preserved_occurrence_count",
}
_SOURCE_BINDING_FIELDS = projection_contract._SOURCE_BINDING_FIELDS
_DEVELOPMENT_BINDING_FIELDS = projection_contract._DEVELOPMENT_BINDING_FIELDS
_DISJOINTNESS_FIELDS = projection_contract._DISJOINTNESS_FIELDS
_CASE_EVIDENCE_HASH_FIELDS = {
    "message_occurrence_hashes": (
        "required_message_occurrence_hashes",
        "denied_message_occurrence_hashes",
    ),
    "message_hashes": (
        "required_message_hashes",
        "denied_message_hashes",
    ),
    "thread_hashes": (
        "required_thread_hashes",
        "denied_thread_hashes",
    ),
    "native_observation_hashes": (
        "required_observation_hashes",
        "denied_observation_hashes",
        "near_miss_source_observation_hash",
    ),
}
_CASE_BINDING_KNOWN_SHA256_FIELDS = frozenset(
    {
        "candidate_fingerprint",
        "partition_fingerprint",
        "permission_fingerprint",
        "full_source_absence_proof_fingerprint",
        "near_miss_mutation_fingerprint",
        "near_miss_source_candidate_fingerprint",
        "near_miss_source_observation_hash",
    }
)
_CASE_BINDING_KNOWN_COUNT_FIELDS = frozenset(
    {
        "complete_source_identifier_occurrence_count",
    }
)
_CASE_BINDING_KNOWN_LINEAGE_FIELDS = frozenset(
    field_name for aliases in _CASE_EVIDENCE_HASH_FIELDS.values() for field_name in aliases
)
_CASE_BINDING_KNOWN_FIELDS = (
    _CASE_BINDING_KNOWN_SHA256_FIELDS
    | _CASE_BINDING_KNOWN_COUNT_FIELDS
    | _CASE_BINDING_KNOWN_LINEAGE_FIELDS
)
_PARSED_MAIL_LINEAGE_OBSERVATION_TYPES = frozenset(
    {
        "email_body_segment",
        "email_header",
    }
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_SAFE_REPORT_BYTES = 2 * 1024 * 1024
_MAX_SOURCE_ARTIFACT_BYTES = 512 * 1024 * 1024
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _fingerprint_json(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _contract_fingerprint_json(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


SOURCE_AUTHOR_POLICY_FINGERPRINT = _fingerprint_json(
    {
        "policy_id": SOURCE_AUTHOR_POLICY_ID,
        "boundary": "source_author_only",
        "private_manifest_decode_allowed": [
            "sealed_holdout_manifest",
            "sealed_development_manifest",
        ],
        "holdout_manifest_contract": {
            "schema_version": 2,
            "byte_seal_authority": "external_expected_sha256",
            "safe_preflight_cross_binding": True,
            "manifest_fingerprint": "sealed_safe_binding_not_payload_recomputed",
            "private_case_fields": {
                "projected_input_fields": sorted(_PRIVATE_CASE_PROJECTED_INPUT_FIELDS),
                "oracle_only_fields": sorted(_PRIVATE_CASE_IGNORED_ORACLE_FIELDS),
                "unknown_private_extensions": "ignored_never_projected_or_fingerprinted",
            },
            "source_oracle_binding_input": "required_allowlist_subset",
        },
        "development_manifest_contract": {
            "schema_version": 1,
            "byte_seal_authority": "external_expected_sha256",
            "internal_fingerprint": "unicode_canonical_sha256_json",
            "private_fields": "strict_exact_allowlist",
            "safe_report_cross_binding": True,
            "source_run_cross_binding": True,
            "disjointness_sets": [
                "case",
                "observation",
                "message_occurrence",
                "message",
                "thread",
            ],
        },
        "source_report_contract": {
            "artifact_id": SOURCE_REPORT_ARTIFACT_ID,
            "byte_seal_authority": "external_expected_sha256",
            "source_completeness_status": "eligible_zero_unexplained_loss",
            "required_count_fields": sorted(_SOURCE_COMPLETENESS_REQUIRED_COUNT_FIELDS),
            "optional_count_fields": sorted(_SOURCE_COMPLETENESS_OPTIONAL_COUNT_FIELDS),
            "unknown_count_fields": "ignored_only_after_nonnegative_integer_validation",
            "source_count_parity": ("folder_message_attachment_unsupported_inventory_observation"),
            "bundle_retrieval_count_crosswalk": True,
            "retrieval_profile_crosswalk": (
                "sealed_retrieval_snapshot_and_oracle_free_safe_preflight"
            ),
            "retrieval_ready_report_required": False,
        },
        "quality_execution_allowed": False,
        "output_case_projection": {
            "case_id": "sealed_hash",
            "query_text": "sealed_hash_not_raw_query",
            "requester_user_id": "sealed_hash",
            "observation_ids": "sealed_hash_from_manifest_reference",
            "source_evidence_binding": (
                "authoritative_observation_occurrence_message_thread_lineage_hash_sets"
            ),
            "body_lineage": "sealed_bundle_body_segment_plus_snapshot_locator",
            "header_lineage": "sealed_snapshot_source_native_locator",
            "optional_case_lineage_fields": "validated_when_present_not_authoritative",
            "occurrence_cardinality": "preserved",
            "message_thread_global_sets": "unique_authoritative_source_mapping",
        },
        "forbidden_output": [
            "answer_oracle",
            "expected_private",
            "raw_query",
            "raw_answer",
            "raw_source_locator",
            "reversible_identifier",
        ],
        "persistence": "atomic_no_overwrite_no_partial",
    }
)


class HoldoutSourceAuthorProjectionInputsError(RuntimeError):
    """Fail-closed source-author error with one stable safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class HoldoutSourceAuthorProjectionInputArtifacts:
    output_root: Path
    source_lineage_path: Path
    development_disjointness_path: Path
    source_lineage: dict[str, Any]
    development_disjointness: dict[str, Any]
    result: dict[str, Any]


def build_holdout_source_author_projection_inputs(
    *,
    holdout_manifest_path: Path,
    expected_holdout_manifest_sha256: str,
    holdout_preflight_safe_path: Path,
    expected_holdout_preflight_safe_sha256: str,
    development_manifest_path: Path,
    expected_development_manifest_sha256: str,
    development_safe_report_path: Path,
    expected_development_safe_report_sha256: str,
    source_bundle_artifact_path: Path,
    expected_source_bundle_artifact_sha256: str,
    source_retrieval_snapshot_path: Path,
    expected_source_retrieval_snapshot_sha256: str,
    source_report_path: Path,
    expected_source_report_sha256: str,
    output_root: Path,
    _write_staged_file: Callable[[Path, bytes, int], None] | None = None,
) -> HoldoutSourceAuthorProjectionInputArtifacts:
    """Decode source-author manifests and atomically emit two safe inputs."""

    if output_root.exists() or output_root.is_symlink():
        raise HoldoutSourceAuthorProjectionInputsError("immutable_output_already_exists")

    holdout_bytes, holdout_manifest = _read_sealed_json(
        holdout_manifest_path,
        expected_holdout_manifest_sha256,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        reason_prefix="holdout_manifest",
    )
    preflight_bytes, preflight = _read_sealed_json(
        holdout_preflight_safe_path,
        expected_holdout_preflight_safe_sha256,
        maximum_bytes=_MAX_SAFE_REPORT_BYTES,
        reason_prefix="holdout_preflight_safe",
    )
    development_bytes, development_manifest = _read_sealed_json(
        development_manifest_path,
        expected_development_manifest_sha256,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        reason_prefix="development_manifest",
    )
    development_report_bytes, development_report = _read_sealed_json(
        development_safe_report_path,
        expected_development_safe_report_sha256,
        maximum_bytes=_MAX_SAFE_REPORT_BYTES,
        reason_prefix="development_safe_report",
    )
    source_bundle_bytes = _read_sealed_bytes(
        source_bundle_artifact_path,
        expected_source_bundle_artifact_sha256,
        maximum_bytes=_MAX_SOURCE_ARTIFACT_BYTES,
        reason_prefix="source_bundle_artifact",
    )
    source_snapshot_bytes = _read_sealed_bytes(
        source_retrieval_snapshot_path,
        expected_source_retrieval_snapshot_sha256,
        maximum_bytes=_MAX_SOURCE_ARTIFACT_BYTES,
        reason_prefix="source_retrieval_snapshot",
    )
    source_report_bytes, source_report = _read_sealed_json(
        source_report_path,
        expected_source_report_sha256,
        maximum_bytes=_MAX_SAFE_REPORT_BYTES,
        reason_prefix="source_report",
    )

    _validate_holdout_manifest_structure(holdout_manifest)
    preflight_summary = _validate_preflight(
        preflight,
        private_manifest_sha256=_sha256_bytes(holdout_bytes),
    )
    _validate_holdout_manifest_preflight_binding(
        holdout_manifest,
        preflight_summary=preflight_summary,
    )
    source_artifact_bindings = _validated_source_artifact_bindings(
        source_bundle_bytes=source_bundle_bytes,
        source_snapshot_bytes=source_snapshot_bytes,
        preflight_summary=preflight_summary,
    )
    source_lineage = _development_source_lineage(
        source_bundle_bytes,
        source_snapshot_bytes,
        source_bindings=source_artifact_bindings,
    )
    _validate_source_completeness_report(
        source_report,
        source_artifact_bindings=source_artifact_bindings,
    )
    development_registry = _validate_development_manifest_and_report(
        development_manifest=development_manifest,
        development_manifest_sha256=_sha256_bytes(development_bytes),
        development_report=development_report,
        development_report_sha256=_sha256_bytes(development_report_bytes),
        source_bundle_bytes=source_bundle_bytes,
        source_bundle_sha256=_sha256_bytes(source_bundle_bytes),
        source_snapshot_bytes=source_snapshot_bytes,
        source_snapshot_sha256=_sha256_bytes(source_snapshot_bytes),
        source_artifact_bindings=source_artifact_bindings,
        source_lineage=source_lineage,
    )
    source_bindings = _validate_source_bindings(
        holdout_manifest=holdout_manifest,
        source_artifact_bindings=source_artifact_bindings,
        source_bundle_sha256=_sha256_bytes(source_bundle_bytes),
        source_snapshot_sha256=_sha256_bytes(source_snapshot_bytes),
        source_report_sha256=_sha256_bytes(source_report_bytes),
    )
    development_binding = _validate_development_binding(
        holdout_manifest=holdout_manifest,
        development_registry=development_registry,
        development_manifest_sha256=_sha256_bytes(development_bytes),
        development_report_sha256=_sha256_bytes(development_report_bytes),
    )
    private_cases = _validated_private_cases(holdout_manifest)
    validated_holdout_cases = _validated_holdout_case_lineage(
        private_cases,
        source_lineage=source_lineage,
        source_permission_fingerprint=source_artifact_bindings["permission_fingerprint"],
        partition_fingerprint=holdout_manifest["partition_fingerprint"],
    )
    development_case_sets = development_registry["case_sets"]
    holdout_case_sets = _holdout_case_sets(validated_holdout_cases)
    disjointness = _validated_disjointness(
        holdout_manifest=holdout_manifest,
        development_case_sets=development_case_sets,
        holdout_case_sets=holdout_case_sets,
        preflight_summary=preflight_summary,
    )
    projected_cases = [
        _oracle_free_nonreversible_case_projection(validated_case)
        for validated_case in validated_holdout_cases
    ]
    projected_strata = Counter(_case_stratum(case) for case in projected_cases)
    if dict(sorted(projected_strata.items())) != (projection_contract.EXPECTED_STRATA_COUNTS):
        raise HoldoutSourceAuthorProjectionInputsError("projected_case_strata_mismatch")

    source_lineage: dict[str, Any] = {
        "artifact_id": projection_contract.SOURCE_LINEAGE_ARTIFACT_ID,
        "schema_version": projection_contract.SCHEMA_VERSION,
        "status": "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "holdout_preflight_safe_sha256": _sha256_bytes(preflight_bytes),
        "private_manifest_sha256": _sha256_bytes(holdout_bytes),
        "manifest_fingerprint": holdout_manifest["manifest_fingerprint"],
        "partition_fingerprint": holdout_manifest["partition_fingerprint"],
        "case_count": projection_contract.EXPECTED_CASE_COUNT,
        "case_strata_counts": dict(projection_contract.EXPECTED_STRATA_COUNTS),
        "source_oracle_bindings": source_bindings,
        "cases": projected_cases,
    }
    source_lineage["source_lineage_fingerprint"] = _payload_fingerprint(
        source_lineage,
        "source_lineage_fingerprint",
    )

    development_disjointness: dict[str, Any] = {
        "artifact_id": projection_contract.DEVELOPMENT_DISJOINTNESS_ARTIFACT_ID,
        "schema_version": projection_contract.SCHEMA_VERSION,
        "status": "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "holdout_preflight_safe_sha256": _sha256_bytes(preflight_bytes),
        "private_manifest_sha256": _sha256_bytes(holdout_bytes),
        "manifest_fingerprint": holdout_manifest["manifest_fingerprint"],
        "partition_fingerprint": holdout_manifest["partition_fingerprint"],
        "case_count": projection_contract.EXPECTED_CASE_COUNT,
        "case_strata_counts": dict(projection_contract.EXPECTED_STRATA_COUNTS),
        "development_exclusion_binding": development_binding,
        "disjointness": disjointness,
    }
    development_disjointness["development_disjointness_fingerprint"] = _payload_fingerprint(
        development_disjointness,
        "development_disjointness_fingerprint",
    )

    _assert_safe_output(source_lineage)
    _assert_safe_output(development_disjointness)
    source_lineage_bytes = _canonical_json_bytes(source_lineage)
    development_disjointness_bytes = _canonical_json_bytes(development_disjointness)
    projection_contract._validate_source_lineage_artifact(
        source_lineage,
        source_lineage_sha256=_sha256_bytes(source_lineage_bytes),
        preflight_sha256=_sha256_bytes(preflight_bytes),
        private_manifest_sha256=_sha256_bytes(holdout_bytes),
        preflight_summary=preflight_summary,
    )
    projection_contract._validate_development_disjointness_artifact(
        development_disjointness,
        development_disjointness_sha256=_sha256_bytes(development_disjointness_bytes),
        preflight_sha256=_sha256_bytes(preflight_bytes),
        private_manifest_sha256=_sha256_bytes(holdout_bytes),
        preflight_summary=preflight_summary,
    )

    result: dict[str, Any] = {
        "artifact_id": RESULT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "source_author_boundary_status": "passed",
        "private_manifest_decode_status": "source_author_only",
        "quality_execution_status": "not_run",
        "oracle_output_status": "excluded",
        "raw_query_output_status": "excluded",
        "reversible_identifier_output_status": "excluded",
        "immutability_status": "atomic_no_overwrite",
        "policy_fingerprint": SOURCE_AUTHOR_POLICY_FINGERPRINT,
        "counts": {
            "holdout_case_count": projection_contract.EXPECTED_CASE_COUNT,
            "development_case_count": 100,
            "source_lineage_artifact_count": 1,
            "development_disjointness_artifact_count": 1,
            "overlap_count": 0,
            "blocker_count": 0,
        },
        "hashes": {
            "holdout_manifest_sha256": _sha256_bytes(holdout_bytes),
            "holdout_preflight_safe_sha256": _sha256_bytes(preflight_bytes),
            "development_manifest_sha256": _sha256_bytes(development_bytes),
            "development_safe_report_sha256": _sha256_bytes(development_report_bytes),
            "source_bundle_artifact_sha256": _sha256_bytes(source_bundle_bytes),
            "source_retrieval_snapshot_sha256": _sha256_bytes(source_snapshot_bytes),
            "source_report_sha256": _sha256_bytes(source_report_bytes),
            "source_lineage_fingerprint": source_lineage["source_lineage_fingerprint"],
            "source_lineage_byte_sha256": _sha256_bytes(source_lineage_bytes),
            "development_disjointness_fingerprint": (
                development_disjointness["development_disjointness_fingerprint"]
            ),
            "development_disjointness_byte_sha256": _sha256_bytes(development_disjointness_bytes),
        },
    }
    result["result_fingerprint"] = _payload_fingerprint(
        result,
        "result_fingerprint",
    )
    _assert_safe_stdout_result(result)

    _persist_atomic_artifact_directory(
        output_root=output_root,
        files={
            SOURCE_LINEAGE_FILENAME: (source_lineage_bytes, 0o400),
            DEVELOPMENT_DISJOINTNESS_FILENAME: (
                development_disjointness_bytes,
                0o400,
            ),
        },
        write_staged_file=_write_staged_file or _write_file_exclusive,
    )
    if (output_root / SOURCE_LINEAGE_FILENAME).read_bytes() != source_lineage_bytes or (
        output_root / DEVELOPMENT_DISJOINTNESS_FILENAME
    ).read_bytes() != development_disjointness_bytes:
        raise HoldoutSourceAuthorProjectionInputsError("persisted_artifact_byte_drift")
    return HoldoutSourceAuthorProjectionInputArtifacts(
        output_root=output_root,
        source_lineage_path=output_root / SOURCE_LINEAGE_FILENAME,
        development_disjointness_path=(output_root / DEVELOPMENT_DISJOINTNESS_FILENAME),
        source_lineage=source_lineage,
        development_disjointness=development_disjointness,
        result=result,
    )


def _validate_holdout_manifest_structure(manifest: Mapping[str, Any]) -> None:
    if (
        manifest.get("artifact_id") != projection_contract.HOLDOUT_MANIFEST_ARTIFACT_ID
        or manifest.get("schema_version") != 2
    ):
        raise HoldoutSourceAuthorProjectionInputsError(
            "holdout_manifest_legacy_or_unknown_schema_rejected"
        )
    if (
        manifest.get("classification") != "independent_mail_holdout"
        or manifest.get("execution_status") != "not_run"
        or manifest.get("quality_result_status") != "not_read"
        or manifest.get("seal_required_before_execution") is not True
        or manifest.get("case_count") != projection_contract.EXPECTED_CASE_COUNT
        or manifest.get("case_strata_counts") != projection_contract.EXPECTED_STRATA_COUNTS
    ):
        raise HoldoutSourceAuthorProjectionInputsError("holdout_manifest_contract_invalid")
    _require_sha256(
        manifest.get("manifest_fingerprint"),
        "holdout_manifest_fingerprint_invalid",
    )
    _require_sha256(
        manifest.get("partition_fingerprint"),
        "holdout_manifest_partition_fingerprint_invalid",
    )
    for field_name in (
        "source_oracle_bindings",
        "development_exclusion_binding",
        "disjointness",
    ):
        if not isinstance(manifest.get(field_name), Mapping):
            raise HoldoutSourceAuthorProjectionInputsError("holdout_manifest_contract_invalid")
    _validated_private_cases(manifest)


def _validate_holdout_manifest_preflight_binding(
    manifest: Mapping[str, Any],
    *,
    preflight_summary: Mapping[str, Any],
) -> None:
    if manifest.get("manifest_fingerprint") != preflight_summary.get(
        "manifest_fingerprint"
    ) or manifest.get("partition_fingerprint") != preflight_summary.get("partition_fingerprint"):
        raise HoldoutSourceAuthorProjectionInputsError(
            "holdout_manifest_preflight_cross_binding_mismatch"
        )


def _validate_preflight(
    report: Mapping[str, Any],
    *,
    private_manifest_sha256: str,
) -> dict[str, Any]:
    try:
        return projection_contract._validate_holdout_preflight(
            report,
            private_manifest_sha256=private_manifest_sha256,
        )
    except projection_contract.HoldoutOracleFreeProjectionError as exc:
        raise HoldoutSourceAuthorProjectionInputsError(exc.reason_code) from exc


def _validate_development_manifest_and_report(
    *,
    development_manifest: Mapping[str, Any],
    development_manifest_sha256: str,
    development_report: Mapping[str, Any],
    development_report_sha256: str,
    source_bundle_bytes: bytes,
    source_bundle_sha256: str,
    source_snapshot_bytes: bytes,
    source_snapshot_sha256: str,
    source_artifact_bindings: Mapping[str, str],
    source_lineage: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    if (
        set(development_manifest) != _DEVELOPMENT_MANIFEST_FIELDS
        or development_manifest.get("artifact_id") != DEVELOPMENT_MANIFEST_ARTIFACT_ID
        or development_manifest.get("schema_version") != 1
        or development_manifest.get("classification") != "development_not_holdout"
        or development_manifest.get("claim_boundary_status")
        != "development_cases_not_quality_or_holdout_evidence"
        or development_manifest.get("case_count") != 100
        or development_manifest.get("quality_evaluation_status") != "not_run"
        or development_manifest.get("holdout_content_consumed") is not False
        or development_manifest.get("oracle_content_consumed") is not False
        or development_manifest.get("manifest_fingerprint")
        != _contract_payload_fingerprint(
            development_manifest,
            "manifest_fingerprint",
        )
    ):
        raise HoldoutSourceAuthorProjectionInputsError("development_manifest_contract_invalid")
    _require_sha256(
        development_manifest.get("archive_sha256"),
        "development_manifest_archive_sha256_invalid",
    )
    for field_name in ("mail_evidence_bundle_id", "mail_import_session_id"):
        _require_nonempty_string(
            development_manifest.get(field_name),
            "development_manifest_contract_invalid",
        )
    selection_policy = development_manifest.get("selection_policy")
    if (
        not isinstance(selection_policy, Mapping)
        or set(selection_policy) != _DEVELOPMENT_SELECTION_POLICY_FIELDS
        or selection_policy.get("case_count") != 100
        or selection_policy.get("classification") != "development_not_holdout"
        or selection_policy.get("holdout_or_oracle_content_read") is not False
        or selection_policy.get("quality_result_read") is not False
        or selection_policy.get("required_match_count") != 2
        or development_manifest.get("selection_policy_fingerprint")
        != _contract_fingerprint_json(selection_policy)
    ):
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_selection_policy_contract_invalid"
        )
    strata = development_manifest.get("case_strata_counts")
    if (
        not isinstance(strata, Mapping)
        or set(strata) != _DEVELOPMENT_STRATA
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in strata.values()
        )
        or sum(strata.values()) != 100
    ):
        raise HoldoutSourceAuthorProjectionInputsError("development_case_strata_invalid")
    source_bindings = _validated_development_source_bindings(
        development_manifest=development_manifest,
        source_bundle_sha256=source_bundle_sha256,
        source_snapshot_sha256=source_snapshot_sha256,
        source_artifact_bindings=source_artifact_bindings,
    )
    case_sets = _development_case_sets(
        development_manifest,
        source_lineage=source_lineage,
    )
    if (
        development_manifest.get("required_evidence_reference_count") != 200
        or development_manifest.get("distinct_required_observation_count")
        != len(case_sets["observation_ids"])
        or development_manifest.get("distinct_required_message_occurrence_count")
        != len(case_sets["message_occurrence_hashes"])
    ):
        raise HoldoutSourceAuthorProjectionInputsError("development_manifest_count_binding_invalid")
    if (
        set(development_report) != _DEVELOPMENT_SAFE_REPORT_FIELDS
        or development_report.get("artifact_id") != DEVELOPMENT_SAFE_REPORT_ARTIFACT_ID
        or development_report.get("schema_version") != 1
        or development_report.get("status") != "passed"
        or development_report.get("classification") != "development_not_holdout"
        or development_report.get("manifest_intake_status") != "passed"
        or development_report.get("lineage_validation_status") != "passed"
        or development_report.get("immutable_write_status") != "passed"
        or development_report.get("quality_evaluation_status") != "not_run"
        or development_report.get("holdout_content_status") != "not_read"
        or development_report.get("claim_boundary_status") != "development_manifest_only"
        or development_report.get("blocker_ids") != []
        or development_report.get("strata") != strata
        or development_report.get("report_fingerprint")
        != _contract_payload_fingerprint(development_report, "report_fingerprint")
    ):
        raise HoldoutSourceAuthorProjectionInputsError("development_safe_report_contract_invalid")
    report_counts = development_report.get("counts")
    report_fingerprints = development_report.get("fingerprints")
    if (
        not isinstance(report_counts, Mapping)
        or set(report_counts) != _DEVELOPMENT_SAFE_COUNT_FIELDS
        or not isinstance(report_fingerprints, Mapping)
        or set(report_fingerprints) != _DEVELOPMENT_SAFE_FINGERPRINT_FIELDS
        or report_counts.get("case_count") != 100
        or report_counts.get("positive_graph_required_owner_case_count") != 100
        or report_counts.get("required_evidence_reference_count") != 200
        or report_counts.get("distinct_required_observation_count")
        != len(case_sets["observation_ids"])
        or report_counts.get("distinct_required_message_occurrence_count")
        != len(case_sets["message_occurrence_hashes"])
        or report_counts.get("unexplained_evidence_binding_count") != 0
        or report_counts.get("blocker_count") != 0
        or report_fingerprints.get("manifest_sha256") != development_manifest_sha256
        or report_fingerprints.get("manifest_fingerprint")
        != development_manifest["manifest_fingerprint"]
        or report_fingerprints.get("selection_policy_fingerprint")
        != development_manifest["selection_policy_fingerprint"]
        or report_fingerprints.get("bundle_artifact_fingerprint")
        != source_bindings["bundle_artifact_fingerprint"]
        or report_fingerprints.get("mail_evidence_bundle_fingerprint")
        != source_bindings["mail_evidence_bundle_fingerprint"]
        or report_fingerprints.get("retrieval_snapshot_fingerprint")
        != source_bindings["retrieval_snapshot_fingerprint"]
        or report_fingerprints.get("source_snapshot_fingerprint")
        != source_bindings["source_snapshot_fingerprint"]
        or report_fingerprints.get("permission_fingerprint")
        != source_bindings["permission_fingerprint"]
        or report_fingerprints.get("candidate_admission_profile_fingerprint")
        != source_bindings["tokenizer_profile_fingerprint"]
        or report_fingerprints.get("index_fingerprint") != source_bindings["index_fingerprint"]
    ):
        raise HoldoutSourceAuthorProjectionInputsError("development_safe_report_binding_mismatch")
    _require_sha256(
        development_report_sha256,
        "development_safe_report_sha256_invalid",
    )
    registry_fingerprint = _contract_fingerprint_json(
        {
            "development_manifest_sha256": development_manifest_sha256,
            "development_manifest_fingerprint": development_manifest["manifest_fingerprint"],
            "case_fingerprints": sorted(case_sets["case_fingerprints"]),
            "observation_id_hashes": sorted(
                _contract_fingerprint_json(value) for value in case_sets["observation_ids"]
            ),
        }
    )
    return {
        "development_case_count": 100,
        "development_manifest_fingerprint": development_manifest["manifest_fingerprint"],
        "development_registry_fingerprint": registry_fingerprint,
        "case_sets": case_sets,
    }


def _validated_development_source_bindings(
    *,
    development_manifest: Mapping[str, Any],
    source_bundle_sha256: str,
    source_snapshot_sha256: str,
    source_artifact_bindings: Mapping[str, str],
) -> dict[str, str]:
    bindings = development_manifest.get("source_bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != _DEVELOPMENT_SOURCE_BINDING_FIELDS:
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_bindings_contract_invalid"
        )
    validated = {
        field_name: _require_sha256(
            bindings.get(field_name),
            f"development_source_binding_{field_name}_invalid",
        )
        for field_name in _DEVELOPMENT_SOURCE_BINDING_FIELDS
    }
    byte_seals = {
        "bundle_artifact_byte_hash": source_bundle_sha256,
        "retrieval_snapshot_byte_hash": source_snapshot_sha256,
    }
    artifact_crosswalk = {
        "bundle_artifact_fingerprint": "bundle_artifact_fingerprint",
        "mail_evidence_bundle_fingerprint": "mail_evidence_bundle_fingerprint",
        "retrieval_snapshot_fingerprint": "retrieval_snapshot_fingerprint",
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "permission_fingerprint": "permission_fingerprint",
        "tokenizer_profile_fingerprint": "tokenizer_profile_fingerprint",
        "index_fingerprint": "index_fingerprint",
    }
    if any(validated[field_name] != expected for field_name, expected in byte_seals.items()):
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_artifact_byte_seal_mismatch"
        )
    if any(
        validated[binding_field] != source_artifact_bindings[artifact_field]
        for binding_field, artifact_field in artifact_crosswalk.items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_artifact_cross_run_mismatch"
        )
    return validated


def _validated_source_artifact_bindings(
    *,
    source_bundle_bytes: bytes,
    source_snapshot_bytes: bytes,
    preflight_summary: Mapping[str, Any],
) -> dict[str, Any]:
    bundle_artifact = _decode_json_bytes(
        source_bundle_bytes,
        "source_bundle_artifact_invalid_json",
    )
    if (
        set(bundle_artifact) != _SOURCE_BUNDLE_ARTIFACT_FIELDS
        or bundle_artifact.get("artifact_id") != "formowl_issue56_native_mail_evidence_bundle_v1"
        or bundle_artifact.get("schema_version") != 1
        or bundle_artifact.get("status") != "passed"
        or bundle_artifact.get("artifact_fingerprint")
        != _contract_payload_fingerprint(
            bundle_artifact,
            "artifact_fingerprint",
        )
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_bundle_artifact_contract_invalid")
    bundle = bundle_artifact.get("bundle")
    if not isinstance(bundle, Mapping) or bundle_artifact.get(
        "bundle_fingerprint"
    ) != _contract_fingerprint_json(bundle):
        raise HoldoutSourceAuthorProjectionInputsError("source_bundle_artifact_contract_invalid")
    bundle_collection_fields = (
        "folder_occurrences",
        "message_occurrences",
        "messages",
        "attachment_occurrences",
        "attachments",
        "body_segments",
    )
    if any(not isinstance(bundle.get(field_name), list) for field_name in bundle_collection_fields):
        raise HoldoutSourceAuthorProjectionInputsError("source_bundle_artifact_contract_invalid")
    bundle_counts = {field_name: len(bundle[field_name]) for field_name in bundle_collection_fields}

    retrieval_snapshot = _decode_json_bytes(
        source_snapshot_bytes,
        "source_retrieval_snapshot_invalid_json",
    )
    if (
        retrieval_snapshot.get("artifact_id")
        != "formowl_issue56_native_source_complete_retrieval_ready_snapshot_v1"
        or retrieval_snapshot.get("schema_version") != 1
        or retrieval_snapshot.get("status") != "passed"
        or retrieval_snapshot.get("claim_boundary_status")
        != "retrieval_ready_evidence_not_canonical_fact"
        or retrieval_snapshot.get("blocker_fingerprints") != []
        or retrieval_snapshot.get("snapshot_fingerprint")
        != _contract_payload_fingerprint(
            retrieval_snapshot,
            "snapshot_fingerprint",
        )
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_retrieval_snapshot_contract_invalid")
    counts = retrieval_snapshot.get("counts")
    if not isinstance(counts, Mapping) or any(
        _require_nonnegative_int(
            counts.get(field_name),
            "source_retrieval_snapshot_contract_invalid",
        )
        != 0
        for field_name in (
            "missing_source_inventory_binding_count",
            "missing_source_local_key_binding_count",
            "missing_content_hash_binding_count",
            "missing_permission_binding_count",
            "unexplained_loss_count",
            "blocker_count",
        )
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_retrieval_snapshot_contract_invalid")
    source_inventory = retrieval_snapshot.get("source_inventory")
    source_inventory_items = (
        source_inventory.get("items") if isinstance(source_inventory, Mapping) else None
    )
    source_occurrence_observations = retrieval_snapshot.get("source_occurrence_observations")
    if (
        not isinstance(source_inventory, Mapping)
        or not isinstance(source_inventory_items, list)
        or not isinstance(source_occurrence_observations, list)
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_retrieval_snapshot_contract_invalid")
    occurrence_type_counts: Counter[str] = Counter()
    for observation in source_occurrence_observations:
        if not isinstance(observation, Mapping):
            raise HoldoutSourceAuthorProjectionInputsError(
                "source_retrieval_snapshot_contract_invalid"
            )
        observation_type = observation.get("observation_type")
        if observation_type not in _SOURCE_OCCURRENCE_OBSERVATION_TYPES:
            raise HoldoutSourceAuthorProjectionInputsError(
                "source_retrieval_snapshot_contract_invalid"
            )
        occurrence_type_counts[str(observation_type)] += 1

    retrieval_count_crosswalk = {
        "mail_bundle_message_occurrence_count": bundle_counts["message_occurrences"],
        "mail_bundle_message_count": bundle_counts["messages"],
        "mail_bundle_attachment_occurrence_count": bundle_counts["attachment_occurrences"],
        "mail_bundle_attachment_count": bundle_counts["attachments"],
        "mail_bundle_body_segment_count": bundle_counts["body_segments"],
        "parsed_message_observation_count": bundle_counts["message_occurrences"],
        "parsed_attachment_observation_count": bundle_counts["attachment_occurrences"],
        "parsed_body_segment_observation_count": bundle_counts["body_segments"],
        "parsed_folder_observation_count": bundle_counts["folder_occurrences"],
        "source_inventory_item_count": len(source_inventory_items),
        "source_occurrence_observation_count": len(source_occurrence_observations),
    }
    if any(
        _require_nonnegative_int(
            counts.get(field_name),
            "source_retrieval_snapshot_contract_invalid",
        )
        != expected_count
        for field_name, expected_count in retrieval_count_crosswalk.items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_bundle_snapshot_count_mismatch")
    if (
        len(source_inventory_items) != len(source_occurrence_observations)
        or counts["source_inventory_item_count"] != counts["source_occurrence_observation_count"]
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_bundle_snapshot_count_mismatch")

    bindings = {
        "bundle_artifact_fingerprint": _require_sha256(
            bundle_artifact.get("artifact_fingerprint"),
            "source_bundle_artifact_contract_invalid",
        ),
        "mail_evidence_bundle_fingerprint": _require_sha256(
            retrieval_snapshot.get("mail_evidence_bundle_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "retrieval_snapshot_fingerprint": _require_sha256(
            retrieval_snapshot.get("snapshot_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "source_snapshot_fingerprint": _require_sha256(
            retrieval_snapshot.get("source_snapshot_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "source_asset_sha256": _require_sha256(
            retrieval_snapshot.get("source_asset_sha256"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "native_manifest_fingerprint": _require_sha256(
            retrieval_snapshot.get("native_manifest_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "source_inventory_fingerprint": _require_sha256(
            retrieval_snapshot.get("source_inventory_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "source_provenance_fingerprint": _require_sha256(
            retrieval_snapshot.get("source_provenance_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "permission_fingerprint": _require_sha256(
            retrieval_snapshot.get("permission_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "tokenizer_profile_fingerprint": _require_sha256(
            retrieval_snapshot.get("tokenizer_profile_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "index_fingerprint": _require_sha256(
            retrieval_snapshot.get("index_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "parser_fingerprint": _require_sha256(
            source_inventory.get("parser_fingerprint"),
            "source_retrieval_snapshot_contract_invalid",
        ),
        "source_count_crosswalk": {
            "bundle_folder_occurrence_count": bundle_counts["folder_occurrences"],
            "bundle_message_occurrence_count": bundle_counts["message_occurrences"],
            "bundle_attachment_occurrence_count": bundle_counts["attachment_occurrences"],
            "retrieval_source_inventory_item_count": counts["source_inventory_item_count"],
            "retrieval_source_occurrence_observation_count": counts[
                "source_occurrence_observation_count"
            ],
            **{
                report_count_field: occurrence_type_counts.get(
                    observation_type,
                    0,
                )
                for observation_type, report_count_field in (
                    _SOURCE_OCCURRENCE_OBSERVATION_TYPES.items()
                )
            },
        },
    }
    if source_inventory.get("permission_fingerprint") != bindings["permission_fingerprint"]:
        raise HoldoutSourceAuthorProjectionInputsError("source_retrieval_snapshot_contract_invalid")
    bundle_crosswalk = {
        "artifact_fingerprint": "bundle_artifact_fingerprint",
        "bundle_fingerprint": "mail_evidence_bundle_fingerprint",
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
    }
    if any(
        bundle_artifact.get(bundle_field) != bindings[binding_field]
        for bundle_field, binding_field in bundle_crosswalk.items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_bundle_snapshot_binding_mismatch")
    preflight_crosswalk = {
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "index_fingerprint": "index_fingerprint",
        "tokenizer_profile_fingerprint": "segmentation_profile_fingerprint",
    }
    if any(
        bindings[binding_field] != preflight_summary[preflight_field]
        for binding_field, preflight_field in preflight_crosswalk.items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError(
            "source_retrieval_preflight_binding_mismatch"
        )
    return bindings


def _validate_source_completeness_report(
    report: Mapping[str, Any],
    *,
    source_artifact_bindings: Mapping[str, Any],
) -> None:
    if (
        set(report) != _SOURCE_COMPLETENESS_REPORT_FIELDS
        or report.get("artifact_id") != SOURCE_REPORT_ARTIFACT_ID
        or report.get("schema_version") != 1
        or report.get("status") != "passed"
        or report.get("source_completeness_gate_status") != "eligible"
        or report.get("claim_boundary_status") != "source_complete_observation_snapshot_only"
        or report.get("methodology_readiness_status") != "blocked"
        or report.get("canonical_fact_status") != "not_asserted"
        or report.get("round_trip_status") != "passed"
        or report.get("blocker_fingerprints") != []
        or report.get("report_fingerprint")
        != _contract_payload_fingerprint(
            report,
            "report_fingerprint",
        )
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_report_contract_invalid")
    for field_name in (
        "source_asset_sha256",
        "native_manifest_fingerprint",
        "asset_binding_fingerprint",
        "permission_fingerprint",
        "source_ref_fingerprint",
        "parser_fingerprint",
        "source_inventory_fingerprint",
        "observation_snapshot_fingerprint",
        "message_lineage_fingerprint",
        "attachment_lineage_fingerprint",
        "folder_lineage_fingerprint",
        "unsupported_lineage_fingerprint",
        "snapshot_fingerprint",
        "report_fingerprint",
    ):
        _require_sha256(
            report.get(field_name),
            "source_report_contract_invalid",
        )
    counts = report.get("counts")
    if (
        not isinstance(counts, Mapping)
        or not _SOURCE_COMPLETENESS_REQUIRED_COUNT_FIELDS.issubset(counts)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in counts.values()
        )
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_report_counts_invalid")
    if (
        "attachment_occurrence_count" in counts
        and counts["attachment_occurrence_count"] != counts["attachment_export_occurrence_count"]
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_report_counts_invalid")
    if any(counts[field_name] != 0 for field_name in _SOURCE_COMPLETENESS_ZERO_COUNT_FIELDS):
        raise HoldoutSourceAuthorProjectionInputsError("source_report_unexplained_loss")
    attachment_occurrence_count = counts["attachment_export_occurrence_count"]
    if (
        counts["attachment_separate_export_count"]
        + counts["attachment_embedded_message_count"]
        + counts["attachment_synthetic_representation_count"]
        != attachment_occurrence_count
        or counts["attachment_export_file_binding_count"]
        != counts["attachment_separate_export_count"]
        + counts["attachment_synthetic_representation_count"]
        or counts["attachment_source_descriptor_binding_count"]
        != counts["attachment_embedded_message_count"]
        or counts["attachment_export_file_binding_count"]
        + counts["attachment_source_descriptor_binding_count"]
        != attachment_occurrence_count
        or counts["attachment_source_inventory_binding_count"] != attachment_occurrence_count
        or counts["attachment_parent_lineage_count"] != attachment_occurrence_count
        or counts["attachment_content_hash_count"] != attachment_occurrence_count
        or counts["message_source_inventory_binding_count"] != counts["message_occurrence_count"]
        or counts["message_parent_lineage_count"] != counts["message_occurrence_count"]
        or counts["source_inventory_item_count"]
        != counts["folder_occurrence_count"]
        + counts["message_occurrence_count"]
        + attachment_occurrence_count
        + counts["unsupported_preserved_occurrence_count"]
        or counts["observation_count"] != counts["source_inventory_item_count"]
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_report_count_parity_invalid")
    source_count_crosswalk = source_artifact_bindings.get("source_count_crosswalk")
    if not isinstance(source_count_crosswalk, Mapping):
        raise HoldoutSourceAuthorProjectionInputsError("source_report_count_binding_mismatch")
    count_crosswalk = {
        "folder_occurrence_count": "bundle_folder_occurrence_count",
        "message_occurrence_count": "bundle_message_occurrence_count",
        "attachment_export_occurrence_count": "bundle_attachment_occurrence_count",
        "source_inventory_item_count": "retrieval_source_inventory_item_count",
        "observation_count": "retrieval_source_occurrence_observation_count",
    }
    occurrence_type_crosswalk = {
        field_name: field_name for field_name in _SOURCE_OCCURRENCE_OBSERVATION_TYPES.values()
    }
    if any(
        counts[report_count_field] != source_count_crosswalk.get(artifact_count_field)
        for report_count_field, artifact_count_field in (
            count_crosswalk | occurrence_type_crosswalk
        ).items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_report_count_binding_mismatch")
    source_provenance_fingerprint = _contract_fingerprint_json(
        {
            "source_asset_sha256": report["source_asset_sha256"],
            "native_manifest_fingerprint": report["native_manifest_fingerprint"],
            "source_ref_fingerprint": report["source_ref_fingerprint"],
            "asset_binding_fingerprint": report["asset_binding_fingerprint"],
            "parser_fingerprint": report["parser_fingerprint"],
        }
    )
    crosswalk = {
        "source_asset_sha256": "source_asset_sha256",
        "native_manifest_fingerprint": "native_manifest_fingerprint",
        "permission_fingerprint": "permission_fingerprint",
        "parser_fingerprint": "parser_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "snapshot_fingerprint": "source_snapshot_fingerprint",
    }
    if (
        any(
            report[report_field] != source_artifact_bindings[binding_field]
            for report_field, binding_field in crosswalk.items()
        )
        or source_provenance_fingerprint
        != source_artifact_bindings["source_provenance_fingerprint"]
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_report_binding_mismatch")


def _development_source_lineage(
    source_bundle_bytes: bytes,
    source_snapshot_bytes: bytes,
    *,
    source_bindings: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    """Build one source-authoritative parsed-Observation lineage projection.

    The sealed evidence bundle is authoritative for message occurrences,
    messages, threads, and body-segment membership.  The sealed retrieval
    snapshot adds source-native ``email_header`` Observations which are not a
    separate MailEvidenceBundle collection.  Header rows are accepted only
    when their location and payload independently agree with the same sealed
    bundle occurrence/message/thread chain.
    """

    artifact = _decode_json_bytes(
        source_bundle_bytes,
        "development_source_bundle_invalid_json",
    )
    if (
        set(artifact) != _SOURCE_BUNDLE_ARTIFACT_FIELDS
        or artifact.get("artifact_id") != "formowl_issue56_native_mail_evidence_bundle_v1"
        or artifact.get("schema_version") != 1
        or artifact.get("status") != "passed"
        or artifact.get("artifact_fingerprint")
        != _contract_payload_fingerprint(artifact, "artifact_fingerprint")
    ):
        raise HoldoutSourceAuthorProjectionInputsError("development_source_bundle_contract_invalid")
    for field_name in (
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "bundle_fingerprint",
        "artifact_fingerprint",
    ):
        _require_sha256(
            artifact.get(field_name),
            "development_source_bundle_contract_invalid",
        )
    bundle_binding_crosswalk = {
        "artifact_fingerprint": "bundle_artifact_fingerprint",
        "bundle_fingerprint": "mail_evidence_bundle_fingerprint",
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
    }
    if any(
        artifact.get(artifact_field) != source_bindings[binding_field]
        for artifact_field, binding_field in bundle_binding_crosswalk.items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_bundle_cross_run_mismatch"
        )
    bundle = artifact.get("bundle")
    if not isinstance(bundle, Mapping) or artifact.get(
        "bundle_fingerprint"
    ) != _contract_fingerprint_json(bundle):
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_bundle_fingerprint_invalid"
        )
    bundle_body_to_occurrence = _unique_string_crosswalk(
        bundle.get("body_segments"),
        key_field="source_observation_id",
        value_field="message_occurrence_id",
        reason_code="development_source_body_lineage_invalid",
    )
    bundle_body_to_email_message = _unique_string_crosswalk(
        bundle.get("body_segments"),
        key_field="source_observation_id",
        value_field="email_message_id",
        reason_code="development_source_body_lineage_invalid",
    )
    occurrence_to_source_message = _unique_string_crosswalk(
        bundle.get("message_occurrences"),
        key_field="message_occurrence_id",
        value_field="message_id",
        reason_code="development_source_message_occurrence_lineage_invalid",
    )
    occurrence_to_email_message = _unique_string_crosswalk(
        bundle.get("message_occurrences"),
        key_field="message_occurrence_id",
        value_field="email_message_id",
        reason_code="development_source_message_occurrence_lineage_invalid",
    )
    occurrence_to_thread = _unique_string_crosswalk(
        bundle.get("message_occurrences"),
        key_field="message_occurrence_id",
        value_field="thread_id",
        reason_code="development_source_message_occurrence_lineage_invalid",
        allow_missing_values=True,
    )
    email_message_to_message = _unique_string_crosswalk(
        bundle.get("messages"),
        key_field="email_message_id",
        value_field="message_id",
        reason_code="development_source_thread_lineage_invalid",
    )
    email_message_to_thread = _unique_string_crosswalk(
        bundle.get("messages"),
        key_field="email_message_id",
        value_field="thread_id",
        reason_code="development_source_thread_lineage_invalid",
        allow_missing_values=True,
    )
    source_snapshot = _decode_json_bytes(
        source_snapshot_bytes,
        "development_source_snapshot_invalid_json",
    )
    snapshot_binding_crosswalk = {
        "snapshot_fingerprint": "retrieval_snapshot_fingerprint",
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "permission_fingerprint": "permission_fingerprint",
        "tokenizer_profile_fingerprint": "tokenizer_profile_fingerprint",
        "index_fingerprint": "index_fingerprint",
    }
    if any(
        source_snapshot.get(snapshot_field) != source_bindings[binding_field]
        for snapshot_field, binding_field in snapshot_binding_crosswalk.items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_snapshot_cross_run_mismatch"
        )
    parsed_observations = source_snapshot.get("parsed_mail_observations")
    if not isinstance(parsed_observations, list):
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_observation_lineage_invalid"
        )
    observation_hashes: dict[str, str] = {}
    observation_types: dict[str, str] = {}
    observation_to_occurrence: dict[str, str] = {}
    for row in parsed_observations:
        if not isinstance(row, Mapping):
            raise HoldoutSourceAuthorProjectionInputsError(
                "development_source_observation_lineage_invalid"
            )
        observation_type = row.get("observation_type")
        if observation_type not in _PARSED_MAIL_LINEAGE_OBSERVATION_TYPES:
            continue
        observation_id = row.get("observation_id")
        location = row.get("location")
        payload = row.get("payload")
        if (
            not isinstance(observation_id, str)
            or not observation_id
            or observation_id in observation_hashes
            or not isinstance(location, Mapping)
            or not isinstance(payload, Mapping)
            or not isinstance(row.get("permission_scope"), Mapping)
        ):
            raise HoldoutSourceAuthorProjectionInputsError(
                "development_source_observation_lineage_invalid"
            )
        native_lineage: dict[str, str] = {}
        for field_name in (
            "message_occurrence_id",
            "message_id",
            "thread_id",
            "source_provenance_fingerprint",
        ):
            location_value = location.get(field_name)
            payload_value = payload.get(field_name)
            if (
                not isinstance(location_value, str)
                or not location_value
                or payload_value != location_value
            ):
                raise HoldoutSourceAuthorProjectionInputsError(
                    "development_source_observation_lineage_invalid"
                )
            native_lineage[field_name] = location_value
        occurrence_id = native_lineage["message_occurrence_id"]
        message_id = native_lineage["message_id"]
        thread_id = native_lineage["thread_id"]
        email_message_id = occurrence_to_email_message.get(occurrence_id)
        if (
            native_lineage["source_provenance_fingerprint"]
            != source_bindings["source_provenance_fingerprint"]
            or occurrence_to_source_message.get(occurrence_id) != message_id
            or occurrence_to_thread.get(occurrence_id) != thread_id
            or email_message_id is None
            or email_message_to_message.get(email_message_id) != message_id
            or email_message_to_thread.get(email_message_id) != thread_id
            or (
                observation_type == "email_body_segment"
                and (
                    bundle_body_to_occurrence.get(observation_id) != occurrence_id
                    or bundle_body_to_email_message.get(observation_id) != email_message_id
                )
            )
        ):
            raise HoldoutSourceAuthorProjectionInputsError(
                "development_source_observation_lineage_invalid"
            )
        observation_hashes[observation_id] = _contract_fingerprint_json(row)
        observation_types[observation_id] = str(observation_type)
        observation_to_occurrence[observation_id] = occurrence_id
    body_observation_ids = {
        observation_id
        for observation_id, observation_type in observation_types.items()
        if observation_type == "email_body_segment"
    }
    if not observation_hashes or set(bundle_body_to_occurrence) != body_observation_ids:
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_observation_lineage_invalid"
        )
    if set(observation_to_occurrence.values()) - set(occurrence_to_source_message):
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_source_message_occurrence_lineage_invalid"
        )
    occurrence_ids = set(occurrence_to_source_message)
    if (
        occurrence_ids != set(occurrence_to_email_message)
        or occurrence_ids != set(occurrence_to_thread)
        or len(set(occurrence_to_email_message.values())) != len(occurrence_to_email_message)
        or set(occurrence_to_email_message.values()) != set(email_message_to_message)
        or set(occurrence_to_email_message.values()) != set(email_message_to_thread)
        or any(
            email_message_to_message[occurrence_to_email_message[occurrence_id]]
            != occurrence_to_source_message[occurrence_id]
            or email_message_to_thread[occurrence_to_email_message[occurrence_id]]
            != occurrence_to_thread[occurrence_id]
            for occurrence_id in occurrence_ids
        )
    ):
        raise HoldoutSourceAuthorProjectionInputsError("development_source_thread_lineage_invalid")
    return {
        "observation_hashes": observation_hashes,
        "observation_types": observation_types,
        "observation_to_occurrence": observation_to_occurrence,
        "occurrence_to_source_message": occurrence_to_source_message,
        "occurrence_to_email_message": occurrence_to_email_message,
        "occurrence_to_thread": {
            occurrence_id: email_message_to_thread[email_message_id]
            for occurrence_id, email_message_id in occurrence_to_email_message.items()
        },
    }


def _contract_payload_fingerprint(
    value: Mapping[str, Any],
    field_name: str,
) -> str:
    return _contract_fingerprint_json(
        {key: item for key, item in value.items() if key != field_name}
    )


def _decode_json_bytes(
    payload: bytes,
    reason_code: str,
) -> dict[str, Any]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HoldoutSourceAuthorProjectionInputsError(reason_code) from exc
    if type(value) is not dict:
        raise HoldoutSourceAuthorProjectionInputsError(reason_code)
    return value


def _unique_string_crosswalk(
    rows: Any,
    *,
    key_field: str,
    value_field: str,
    reason_code: str,
    allow_missing_values: bool = False,
) -> dict[str, str]:
    if not isinstance(rows, list):
        raise HoldoutSourceAuthorProjectionInputsError(reason_code)
    crosswalk: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise HoldoutSourceAuthorProjectionInputsError(reason_code)
        key = row.get(key_field)
        value = row.get(value_field)
        if allow_missing_values and value is None:
            continue
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or not value
            or key in crosswalk
        ):
            raise HoldoutSourceAuthorProjectionInputsError(reason_code)
        crosswalk[key] = value
    return crosswalk


def _validate_source_bindings(
    *,
    holdout_manifest: Mapping[str, Any],
    source_artifact_bindings: Mapping[str, str],
    source_bundle_sha256: str,
    source_snapshot_sha256: str,
    source_report_sha256: str,
) -> dict[str, Any]:
    bindings = holdout_manifest.get("source_oracle_bindings")
    if not isinstance(bindings, Mapping) or not _SOURCE_BINDING_FIELDS.issubset(bindings):
        raise HoldoutSourceAuthorProjectionInputsError("source_oracle_bindings_invalid")
    projected_bindings = {
        field_name: _require_sha256(
            bindings.get(field_name),
            f"source_binding_{field_name}_invalid",
        )
        for field_name in _SOURCE_BINDING_FIELDS
    }
    if (
        projected_bindings["bundle_artifact_sha256"] != source_bundle_sha256
        or projected_bindings["retrieval_snapshot_sha256"] != source_snapshot_sha256
        or projected_bindings["source_report_sha256"] != source_report_sha256
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_artifact_byte_seal_mismatch")
    artifact_crosswalk = {
        "bundle_artifact_fingerprint": "bundle_artifact_fingerprint",
        "mail_evidence_bundle_fingerprint": "mail_evidence_bundle_fingerprint",
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "index_fingerprint": "index_fingerprint",
        "tokenizer_profile_fingerprint": "tokenizer_profile_fingerprint",
    }
    if any(
        projected_bindings[binding_field] != source_artifact_bindings[artifact_field]
        for binding_field, artifact_field in artifact_crosswalk.items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError("source_artifact_binding_mismatch")
    return projected_bindings


def _validate_development_binding(
    *,
    holdout_manifest: Mapping[str, Any],
    development_registry: Mapping[str, Any],
    development_manifest_sha256: str,
    development_report_sha256: str,
) -> dict[str, Any]:
    binding = holdout_manifest.get("development_exclusion_binding")
    if not isinstance(binding, Mapping) or set(binding) != (_DEVELOPMENT_BINDING_FIELDS):
        raise HoldoutSourceAuthorProjectionInputsError("development_exclusion_binding_invalid")
    expected = {
        "development_case_count": development_registry["development_case_count"],
        "development_manifest_fingerprint": development_registry[
            "development_manifest_fingerprint"
        ],
        "development_manifest_sha256": development_manifest_sha256,
        "development_registry_fingerprint": development_registry[
            "development_registry_fingerprint"
        ],
        "development_safe_report_sha256": development_report_sha256,
    }
    if dict(binding) != expected:
        raise HoldoutSourceAuthorProjectionInputsError(
            "development_exclusion_cross_manifest_mismatch"
        )
    return expected


def _validated_private_cases(
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != projection_contract.EXPECTED_CASE_COUNT:
        raise HoldoutSourceAuthorProjectionInputsError("holdout_private_cases_invalid")
    case_ids: set[str] = set()
    case_fingerprints: set[str] = set()
    strata: Counter[str] = Counter()
    validated: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict) or not _CASE_REQUIRED_FIELDS.issubset(case):
            raise HoldoutSourceAuthorProjectionInputsError("holdout_private_case_invalid")
        # Unknown v2 private extensions are intentionally opaque at this
        # boundary.  Only the explicit projected-input allowlist below is ever
        # read; oracle-only and unknown fields are excluded from every safe
        # fingerprint.
        if any(not isinstance(field_name, str) or not field_name for field_name in case):
            raise HoldoutSourceAuthorProjectionInputsError("holdout_private_case_invalid")
        for ignored_field_name in set(case) - _PRIVATE_CASE_ALLOWED_FIELDS:
            if not ignored_field_name:
                raise HoldoutSourceAuthorProjectionInputsError("holdout_private_case_invalid")
        case_id = _require_nonempty_string(
            case.get("case_id"),
            "holdout_private_case_invalid",
        )
        case_fingerprint = _require_sha256(
            case.get("private_fingerprint"),
            "holdout_private_case_fingerprint_invalid",
        )
        if case_id in case_ids or case_fingerprint in case_fingerprints:
            raise HoldoutSourceAuthorProjectionInputsError(
                "holdout_private_case_identity_duplicate"
            )
        case_ids.add(case_id)
        case_fingerprints.add(case_fingerprint)
        for field_name in (
            "domain",
            "intent_kind",
            "pattern",
            "result_kind",
            "query_text",
            "requester_user_id",
        ):
            _require_nonempty_string(
                case.get(field_name),
                "holdout_private_case_invalid",
            )
        _string_list(
            case.get("required_source_observation_ids"),
            "holdout_private_case_required_ids_invalid",
        )
        _string_list(
            case.get("forbidden_source_observation_ids"),
            "holdout_private_case_forbidden_ids_invalid",
        )
        if "authoring_source_observation_ids" in case:
            _string_list(
                case["authoring_source_observation_ids"],
                "holdout_private_case_authoring_ids_invalid",
            )
        if not isinstance(case.get("source_evidence_binding"), Mapping):
            raise HoldoutSourceAuthorProjectionInputsError(
                "holdout_private_case_source_binding_invalid"
            )
        _require_nonnegative_int(
            case.get("required_match_count"),
            "holdout_private_case_invalid",
        )
        if (
            _require_nonnegative_int(
                case.get("limit"),
                "holdout_private_case_invalid",
            )
            == 0
        ):
            raise HoldoutSourceAuthorProjectionInputsError("holdout_private_case_invalid")
        stratum = _case_stratum(case)
        strata[stratum] += 1
        validated.append(case)
    if dict(sorted(strata.items())) != (projection_contract.EXPECTED_STRATA_COUNTS):
        raise HoldoutSourceAuthorProjectionInputsError("holdout_private_case_strata_invalid")
    return validated


def _validated_holdout_case_lineage(
    cases: Sequence[Mapping[str, Any]],
    *,
    source_lineage: Mapping[str, Mapping[str, str]],
    source_permission_fingerprint: str,
    partition_fingerprint: str,
) -> list[dict[str, Any]]:
    """Validate optional case hints against one sealed source authority."""

    observation_hashes = source_lineage["observation_hashes"]
    observation_types = source_lineage["observation_types"]
    observation_to_occurrence = source_lineage["observation_to_occurrence"]
    occurrence_to_email_message = source_lineage["occurrence_to_email_message"]
    occurrence_to_thread = source_lineage["occurrence_to_thread"]
    validated_cases: list[dict[str, Any]] = []
    for case in cases:
        required_ids = _string_list(
            case.get("required_source_observation_ids"),
            "holdout_case_required_ids_invalid",
        )
        forbidden_ids = _string_list(
            case.get("forbidden_source_observation_ids"),
            "holdout_case_forbidden_ids_invalid",
        )
        authoring_ids = (
            _string_list(
                case.get("authoring_source_observation_ids"),
                "holdout_case_authoring_ids_invalid",
            )
            if "authoring_source_observation_ids" in case
            else (required_ids or forbidden_ids)
        )
        if (
            not authoring_ids
            or set(required_ids) - set(authoring_ids)
            or set(forbidden_ids) - set(authoring_ids)
            or any(
                observation_id not in observation_hashes
                or observation_types.get(observation_id)
                not in _PARSED_MAIL_LINEAGE_OBSERVATION_TYPES
                for observation_id in authoring_ids
            )
        ):
            raise HoldoutSourceAuthorProjectionInputsError(
                "holdout_case_observation_lineage_invalid"
            )
        occurrence_ids = tuple(
            observation_to_occurrence[observation_id] for observation_id in authoring_ids
        )
        message_ids = tuple(
            occurrence_to_email_message[occurrence_id] for occurrence_id in occurrence_ids
        )
        thread_ids = tuple(occurrence_to_thread[occurrence_id] for occurrence_id in occurrence_ids)
        authoritative_hashes = {
            "native_observation_hashes": tuple(
                sorted(observation_hashes[observation_id] for observation_id in authoring_ids)
            ),
            # Observation cardinality is preserved: multiple header/body
            # observations may intentionally bind one message occurrence.
            "message_occurrence_hashes": tuple(
                sorted(_contract_fingerprint_json(value) for value in occurrence_ids)
            ),
            "message_hashes": tuple(
                sorted({_contract_fingerprint_json(value) for value in message_ids})
            ),
            "thread_hashes": tuple(
                sorted({_contract_fingerprint_json(value) for value in thread_ids})
            ),
            "thread_occurrence_hashes": tuple(
                sorted(_contract_fingerprint_json(value) for value in thread_ids)
            ),
        }
        binding = case.get("source_evidence_binding")
        if not isinstance(binding, Mapping):
            raise HoldoutSourceAuthorProjectionInputsError(
                "holdout_private_case_source_binding_invalid"
            )
        for ignored_field_name in set(binding) - _CASE_BINDING_KNOWN_FIELDS:
            if not isinstance(ignored_field_name, str) or not ignored_field_name:
                raise HoldoutSourceAuthorProjectionInputsError(
                    "holdout_private_case_source_binding_invalid"
                )
        safe_metadata: dict[str, Any] = {}
        for field_name in _CASE_BINDING_KNOWN_SHA256_FIELDS:
            if field_name not in binding:
                continue
            safe_metadata[field_name] = _require_sha256(
                binding[field_name],
                f"holdout_case_{field_name}_invalid",
            )
        for field_name in _CASE_BINDING_KNOWN_COUNT_FIELDS:
            if field_name not in binding:
                continue
            safe_metadata[field_name] = _require_nonnegative_int(
                binding[field_name],
                f"holdout_case_{field_name}_invalid",
            )
        if safe_metadata.get("partition_fingerprint") != partition_fingerprint:
            raise HoldoutSourceAuthorProjectionInputsError(
                "holdout_case_partition_binding_mismatch"
            )
        if (
            "permission_fingerprint" in safe_metadata
            and safe_metadata["permission_fingerprint"] != source_permission_fingerprint
        ):
            raise HoldoutSourceAuthorProjectionInputsError(
                "holdout_case_permission_binding_mismatch"
            )
        if "complete_source_identifier_occurrence_count" in safe_metadata and safe_metadata[
            "complete_source_identifier_occurrence_count"
        ] != len(authoring_ids):
            raise HoldoutSourceAuthorProjectionInputsError(
                "holdout_case_complete_source_count_mismatch"
            )

        expected_by_kind = {
            "native_observation_hashes": authoritative_hashes["native_observation_hashes"],
            "message_occurrence_hashes": authoritative_hashes["message_occurrence_hashes"],
            "message_hashes": authoritative_hashes["message_hashes"],
            "thread_hashes": (
                authoritative_hashes["thread_hashes"]
                if "complete_source_identifier_occurrence_count" in safe_metadata
                else authoritative_hashes["thread_occurrence_hashes"]
            ),
        }
        for lineage_kind, aliases in _CASE_EVIDENCE_HASH_FIELDS.items():
            provided = _optional_case_evidence_hashes(
                binding,
                aliases,
                f"holdout_case_{lineage_kind}_invalid",
            )
            if provided is not None and tuple(sorted(provided)) != expected_by_kind[lineage_kind]:
                raise HoldoutSourceAuthorProjectionInputsError(
                    f"holdout_case_{lineage_kind}_binding_mismatch"
                )

        safe_binding_fingerprint = _fingerprint_json(
            {
                "known_safe_metadata": safe_metadata,
                "authoritative_lineage": {
                    "native_observation_hashes": authoritative_hashes["native_observation_hashes"],
                    "message_occurrence_hashes": authoritative_hashes["message_occurrence_hashes"],
                    "message_hashes": authoritative_hashes["message_hashes"],
                    "thread_hashes": authoritative_hashes["thread_hashes"],
                    "thread_occurrence_hashes": authoritative_hashes["thread_occurrence_hashes"],
                },
                "source_author_policy_fingerprint": SOURCE_AUTHOR_POLICY_FINGERPRINT,
            }
        )
        validated_cases.append(
            {
                "case": case,
                "required_ids": required_ids,
                "forbidden_ids": forbidden_ids,
                "authoring_ids": authoring_ids,
                "authoritative_hashes": authoritative_hashes,
                "safe_binding_fingerprint": safe_binding_fingerprint,
            }
        )
    return validated_cases


def _development_case_sets(
    manifest: Mapping[str, Any],
    *,
    source_lineage: Mapping[str, Mapping[str, str]],
) -> dict[str, set[str]]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 100:
        raise HoldoutSourceAuthorProjectionInputsError("development_cases_invalid")
    observation_to_occurrence = source_lineage["observation_to_occurrence"]
    source_observation_hashes = source_lineage["observation_hashes"]
    occurrence_to_email_message = source_lineage["occurrence_to_email_message"]
    occurrence_to_thread = source_lineage["occurrence_to_thread"]
    case_ids: set[str] = set()
    case_fingerprints: set[str] = set()
    observation_ids: set[str] = set()
    observation_hashes: set[str] = set()
    message_occurrence_hashes: set[str] = set()
    message_hashes: set[str] = set()
    thread_hashes: set[str] = set()
    for case in cases:
        if (
            not isinstance(case, Mapping)
            or set(case) != _DEVELOPMENT_CASE_FIELDS
            or case.get("result_kind") != "owner_match"
            or case.get("intent_kind") != "relation_reasoning"
            or case.get("required_match_count") != 2
            or case.get("forbidden_source_observation_ids") != []
            or case.get("limit") != 10
        ):
            raise HoldoutSourceAuthorProjectionInputsError("development_case_contract_invalid")
        for field_name in (
            "case_id",
            "domain",
            "intent_kind",
            "pattern",
            "query_text",
            "requester_user_id",
            "result_kind",
        ):
            _require_nonempty_string(
                case.get(field_name),
                "development_case_contract_invalid",
            )
        case_id = str(case["case_id"])
        if case_id in case_ids:
            raise HoldoutSourceAuthorProjectionInputsError("development_case_uniqueness_invalid")
        case_ids.add(case_id)
        required_ids = _string_list(
            case.get("required_source_observation_ids"),
            "development_case_observation_ids_invalid",
        )
        if len(required_ids) != 2 or any(
            observation_id not in observation_to_occurrence for observation_id in required_ids
        ):
            raise HoldoutSourceAuthorProjectionInputsError(
                "development_case_observation_lineage_invalid"
            )
        case_fingerprint = _require_sha256(
            case.get("private_fingerprint"),
            "development_case_fingerprint_invalid",
        )
        if case_fingerprint != _contract_payload_fingerprint(case, "private_fingerprint"):
            raise HoldoutSourceAuthorProjectionInputsError("development_case_fingerprint_drift")
        case_fingerprints.add(case_fingerprint)
        observation_ids.update(required_ids)
        binding = case.get("source_evidence_binding")
        if (
            not isinstance(binding, Mapping)
            or set(binding) != _DEVELOPMENT_CASE_SOURCE_BINDING_FIELDS
        ):
            raise HoldoutSourceAuthorProjectionInputsError(
                "development_case_source_binding_invalid"
            )
        _require_sha256(
            binding.get("candidate_fingerprint"),
            "development_case_candidate_fingerprint_invalid",
        )
        required_observation_hashes = _sha256_list(
            binding.get("required_observation_hashes"),
            "development_case_observation_hashes_invalid",
        )
        expected_observation_hashes = tuple(
            sorted(source_observation_hashes[observation_id] for observation_id in required_ids)
        )
        expected_occurrence_hashes = tuple(
            sorted(
                _contract_fingerprint_json(observation_to_occurrence[observation_id])
                for observation_id in required_ids
            )
        )
        required_occurrence_hashes = tuple(
            sorted(
                _sha256_list(
                    binding.get("required_message_occurrence_hashes"),
                    "development_case_message_occurrence_hashes_invalid",
                )
            )
        )
        if (
            len(required_observation_hashes) != 2
            or tuple(sorted(required_observation_hashes)) != expected_observation_hashes
            or len(required_occurrence_hashes) != 2
            or required_occurrence_hashes != expected_occurrence_hashes
        ):
            raise HoldoutSourceAuthorProjectionInputsError(
                "development_case_source_lineage_binding_mismatch"
            )
        observation_hashes.update(required_observation_hashes)
        message_occurrence_hashes.update(required_occurrence_hashes)
        for observation_id in required_ids:
            occurrence_id = observation_to_occurrence[observation_id]
            message_id = occurrence_to_email_message.get(occurrence_id)
            thread_id = occurrence_to_thread.get(occurrence_id)
            if message_id is None or thread_id is None:
                raise HoldoutSourceAuthorProjectionInputsError(
                    "development_case_source_lineage_binding_mismatch"
                )
            message_hashes.add(_contract_fingerprint_json(message_id))
            thread_hashes.add(_contract_fingerprint_json(thread_id))
    if (
        len(case_ids) != 100
        or len(case_fingerprints) != 100
        or len(observation_ids) != 200
        or len(observation_hashes) != 200
        or len(message_occurrence_hashes) != 189
    ):
        raise HoldoutSourceAuthorProjectionInputsError("development_case_uniqueness_invalid")
    return {
        "case_fingerprints": case_fingerprints,
        "observation_ids": observation_ids,
        "observation_hashes": observation_hashes,
        "message_occurrence_hashes": message_occurrence_hashes,
        "message_hashes": message_hashes,
        "thread_hashes": thread_hashes,
    }


def _holdout_case_sets(
    validated_cases: Sequence[Mapping[str, Any]],
) -> dict[str, set[str]]:
    observation_ids: set[str] = set()
    message_hashes: set[str] = set()
    message_occurrence_hashes: set[str] = set()
    thread_hashes: set[str] = set()
    native_observation_hashes: set[str] = set()
    for validated_case in validated_cases:
        observation_ids.update(validated_case["authoring_ids"])
        authoritative_hashes = validated_case["authoritative_hashes"]
        message_occurrence_hashes.update(authoritative_hashes["message_occurrence_hashes"])
        message_hashes.update(authoritative_hashes["message_hashes"])
        thread_hashes.update(authoritative_hashes["thread_hashes"])
        native_observation_hashes.update(authoritative_hashes["native_observation_hashes"])
    return {
        "observation_ids": observation_ids,
        "message_occurrence_hashes": message_occurrence_hashes,
        "message_hashes": message_hashes,
        "thread_hashes": thread_hashes,
        "native_observation_hashes": native_observation_hashes,
    }


def _validated_disjointness(
    *,
    holdout_manifest: Mapping[str, Any],
    development_case_sets: Mapping[str, set[str]],
    holdout_case_sets: Mapping[str, set[str]],
    preflight_summary: Mapping[str, Any],
) -> dict[str, Any]:
    independently_computable_overlap_counts = {
        "development_holdout_observation_overlap_count": len(
            development_case_sets["observation_ids"] & holdout_case_sets["observation_ids"]
        ),
        "development_holdout_message_overlap_count": len(
            development_case_sets["message_hashes"] & holdout_case_sets["message_hashes"]
        ),
        "development_holdout_thread_overlap_count": len(
            development_case_sets["thread_hashes"] & holdout_case_sets["thread_hashes"]
        ),
    }
    if any(independently_computable_overlap_counts.values()):
        raise HoldoutSourceAuthorProjectionInputsError("development_holdout_overlap_detected")
    authoritative_disjointness = {
        "status": "passed",
        **independently_computable_overlap_counts,
        "holdout_authoring_observation_count": len(holdout_case_sets["observation_ids"]),
        "holdout_authoring_message_count": len(holdout_case_sets["message_hashes"]),
        "holdout_authoring_thread_count": len(holdout_case_sets["thread_hashes"]),
        "holdout_observation_set_fingerprint": _fingerprint_json(
            sorted(
                _contract_fingerprint_json(value) for value in holdout_case_sets["observation_ids"]
            )
        ),
        "holdout_message_set_fingerprint": _fingerprint_json(
            sorted(holdout_case_sets["message_hashes"])
        ),
        "holdout_thread_set_fingerprint": _fingerprint_json(
            sorted(holdout_case_sets["thread_hashes"])
        ),
    }
    manifest_disjointness = holdout_manifest.get("disjointness")
    if (
        not isinstance(manifest_disjointness, Mapping)
        or set(manifest_disjointness) != _DISJOINTNESS_FIELDS
        or dict(manifest_disjointness) != authoritative_disjointness
    ):
        raise HoldoutSourceAuthorProjectionInputsError(
            "holdout_disjointness_cross_manifest_mismatch"
        )
    preflight_expected = {
        "holdout_authoring_observation_count": preflight_summary[
            "holdout_authoring_observation_count"
        ],
        "holdout_authoring_message_count": preflight_summary["holdout_authoring_message_count"],
        "holdout_authoring_thread_count": preflight_summary["holdout_authoring_thread_count"],
        "holdout_observation_set_fingerprint": preflight_summary[
            "holdout_observation_set_fingerprint"
        ],
        "holdout_message_set_fingerprint": preflight_summary["holdout_message_set_fingerprint"],
        "holdout_thread_set_fingerprint": preflight_summary["holdout_thread_set_fingerprint"],
    }
    if any(
        authoritative_disjointness[field_name] != value
        for field_name, value in preflight_expected.items()
    ):
        raise HoldoutSourceAuthorProjectionInputsError(
            "holdout_disjointness_preflight_cross_binding_mismatch"
        )
    return authoritative_disjointness


def _oracle_free_nonreversible_case_projection(
    validated_case: Mapping[str, Any],
) -> dict[str, Any]:
    case = validated_case["case"]
    private_fingerprint = _require_sha256(
        case.get("private_fingerprint"),
        "holdout_private_case_fingerprint_invalid",
    )
    required_ids = validated_case["required_ids"]
    forbidden_ids = validated_case["forbidden_ids"]
    authoring_ids = validated_case["authoring_ids"]
    projected_required_ids = [_sealed_identifier("observation", value) for value in required_ids]
    projected_forbidden_ids = [_sealed_identifier("observation", value) for value in forbidden_ids]
    projected_authoring_ids = [_sealed_identifier("observation", value) for value in authoring_ids]
    authoritative_hashes = validated_case["authoritative_hashes"]
    source_evidence_binding = {
        "source_evidence_binding_fingerprint": validated_case["safe_binding_fingerprint"],
        "required_observation_hash_set_fingerprint": _fingerprint_json(
            sorted(projected_required_ids)
        ),
        "forbidden_observation_hash_set_fingerprint": _fingerprint_json(
            sorted(projected_forbidden_ids)
        ),
        "authoring_observation_hash_set_fingerprint": _fingerprint_json(
            sorted(projected_authoring_ids)
        ),
        "message_occurrence_evidence_hash_set_fingerprint": (
            _fingerprint_json(sorted(authoritative_hashes["message_occurrence_hashes"]))
        ),
        "message_evidence_hash_set_fingerprint": _fingerprint_json(
            sorted(authoritative_hashes["message_hashes"])
        ),
        "thread_evidence_hash_set_fingerprint": _fingerprint_json(
            sorted(authoritative_hashes["thread_hashes"])
        ),
        "thread_occurrence_evidence_hash_sequence_fingerprint": _fingerprint_json(
            sorted(authoritative_hashes["thread_occurrence_hashes"])
        ),
        "native_observation_evidence_hash_set_fingerprint": _fingerprint_json(
            sorted(authoritative_hashes["native_observation_hashes"])
        ),
        "projection_policy_fingerprint": SOURCE_AUTHOR_POLICY_FINGERPRINT,
    }
    return {
        "case_id": _sealed_identifier("case", str(case["case_id"])),
        "domain": "mail",
        "intent_kind": str(case["intent_kind"]),
        "pattern": f"oracle_free_{_case_stratum(case)}_v1",
        "result_kind": str(case["result_kind"]),
        "query_text": _sealed_identifier("query", str(case["query_text"])),
        "requester_user_id": _sealed_identifier(
            "requester",
            str(case["requester_user_id"]),
        ),
        "required_source_observation_ids": projected_required_ids,
        "forbidden_source_observation_ids": projected_forbidden_ids,
        "authoring_source_observation_ids": projected_authoring_ids,
        "required_match_count": case["required_match_count"],
        "limit": case["limit"],
        "private_fingerprint": private_fingerprint,
        "stratum_id": _case_stratum(case),
        "source_evidence_binding": source_evidence_binding,
    }


def _case_stratum(case: Mapping[str, Any]) -> str:
    value = case.get("stratum_id")
    if isinstance(value, str) and value in (projection_contract.EXPECTED_STRATA_COUNTS):
        return value
    if case.get("result_kind") == "owner_match" and case.get("intent_kind") == "relation_reasoning":
        return "graph_required"
    raise HoldoutSourceAuthorProjectionInputsError("holdout_private_case_stratum_invalid")


def _assert_safe_output(value: Any) -> None:
    forbidden_keys = {
        "answer_oracle",
        "expected_private",
        "raw_query",
        "raw_answer",
        "raw_source_locator",
        "source_locator",
        "path",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in forbidden_keys or key.endswith("_path"):
                raise HoldoutSourceAuthorProjectionInputsError(
                    "safe_output_field_allowlist_violation"
                )
            _assert_safe_output(nested)
        if "cases" in value:
            for case in value["cases"]:
                _assert_nonreversible_case(case)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_safe_output(nested)
    elif isinstance(value, str) and ("://" in value or "/" in value or "\\" in value):
        raise HoldoutSourceAuthorProjectionInputsError("safe_output_raw_locator_detected")


def _assert_nonreversible_case(case: Any) -> None:
    if not isinstance(case, Mapping):
        raise HoldoutSourceAuthorProjectionInputsError("safe_output_case_invalid")
    for field_name in ("case_id", "query_text", "requester_user_id"):
        _require_sha256(
            case.get(field_name),
            "safe_output_reversible_identifier_detected",
        )
    for field_name in (
        "required_source_observation_ids",
        "forbidden_source_observation_ids",
        "authoring_source_observation_ids",
    ):
        for value in _string_list(
            case.get(field_name),
            "safe_output_reversible_identifier_detected",
        ):
            _require_sha256(
                value,
                "safe_output_reversible_identifier_detected",
            )
    binding = case.get("source_evidence_binding")
    if not isinstance(binding, Mapping) or any(
        not isinstance(value, str) or not _SHA256_RE.fullmatch(value) for value in binding.values()
    ):
        raise HoldoutSourceAuthorProjectionInputsError("safe_output_source_binding_invalid")


def _assert_safe_stdout_result(result: Mapping[str, Any]) -> None:
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "source_author_boundary_status",
        "private_manifest_decode_status",
        "quality_execution_status",
        "oracle_output_status",
        "raw_query_output_status",
        "reversible_identifier_output_status",
        "immutability_status",
        "policy_fingerprint",
        "counts",
        "hashes",
        "result_fingerprint",
    }
    if (
        set(result) != expected_keys
        or result.get("artifact_id") != RESULT_ARTIFACT_ID
        or result.get("status") != "passed"
        or result.get("quality_execution_status") != "not_run"
        or result.get("result_fingerprint") != _payload_fingerprint(result, "result_fingerprint")
    ):
        raise HoldoutSourceAuthorProjectionInputsError("stdout_result_contract_invalid")
    _assert_safe_output(result)


def _read_sealed_json(
    path: Path,
    expected_sha256: str,
    *,
    maximum_bytes: int,
    reason_prefix: str,
) -> tuple[bytes, dict[str, Any]]:
    payload = _read_sealed_bytes(
        path,
        expected_sha256,
        maximum_bytes=maximum_bytes,
        reason_prefix=reason_prefix,
    )
    try:
        value = json.loads(payload, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HoldoutSourceAuthorProjectionInputsError(f"{reason_prefix}_invalid_json") from exc
    if type(value) is not dict:
        raise HoldoutSourceAuthorProjectionInputsError(f"{reason_prefix}_invalid_json")
    return payload, value


def _read_sealed_bytes(
    path: Path,
    expected_sha256: str,
    *,
    maximum_bytes: int,
    reason_prefix: str,
) -> bytes:
    _require_sha256(
        expected_sha256,
        f"{reason_prefix}_expected_sha256_invalid",
    )
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise OSError
        payload = path.read_bytes()
    except OSError as exc:
        raise HoldoutSourceAuthorProjectionInputsError(
            f"{reason_prefix}_missing_or_invalid"
        ) from exc
    if _sha256_bytes(payload) != expected_sha256:
        raise HoldoutSourceAuthorProjectionInputsError(f"{reason_prefix}_seal_mismatch")
    return payload


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _persist_atomic_artifact_directory(
    *,
    output_root: Path,
    files: Mapping[str, tuple[bytes, int]],
    write_staged_file: Callable[[Path, bytes, int], None],
) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise HoldoutSourceAuthorProjectionInputsError("immutable_output_already_exists")
    try:
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output_root.name}.staging-",
                dir=output_root.parent,
            )
        )
    except OSError as exc:
        raise HoldoutSourceAuthorProjectionInputsError("artifact_staging_unavailable") from exc
    try:
        for filename, (payload, mode) in files.items():
            write_staged_file(staging / filename, payload, mode)
        _fsync_directory(staging)
        _rename_directory_no_replace(staging, output_root)
        _fsync_directory(output_root.parent)
    except HoldoutSourceAuthorProjectionInputsError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise HoldoutSourceAuthorProjectionInputsError(
            "atomic_artifact_persistence_failed"
        ) from exc


def _write_file_exclusive(path: Path, payload: bytes, mode: int) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
        )
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    except OSError as exc:
        raise HoldoutSourceAuthorProjectionInputsError("staged_artifact_write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise HoldoutSourceAuthorProjectionInputsError("atomic_no_replace_unavailable")
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
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise HoldoutSourceAuthorProjectionInputsError("immutable_output_already_exists")
    raise HoldoutSourceAuthorProjectionInputsError("atomic_no_replace_failed")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_list(value: Any, reason_code: str) -> tuple[str, ...]:
    values = _string_list(value, reason_code)
    for item in values:
        _require_sha256(item, reason_code)
    return values


def _optional_case_evidence_hashes(
    binding: Mapping[str, Any],
    field_names: Sequence[str],
    reason_code: str,
) -> tuple[str, ...] | None:
    present_fields = [field_name for field_name in field_names if field_name in binding]
    if not present_fields:
        return None
    if len(present_fields) != 1:
        raise HoldoutSourceAuthorProjectionInputsError(reason_code)
    raw_value = binding[present_fields[0]]
    if isinstance(raw_value, str):
        return (_require_sha256(raw_value, reason_code),)
    if not isinstance(raw_value, list):
        raise HoldoutSourceAuthorProjectionInputsError(reason_code)
    values: list[str] = []
    for value in raw_value:
        values.append(_require_sha256(value, reason_code))
    return tuple(values)


def _string_list(value: Any, reason_code: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise HoldoutSourceAuthorProjectionInputsError(reason_code)
    return tuple(value)


def _require_sha256(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise HoldoutSourceAuthorProjectionInputsError(reason_code)
    return value


def _require_nonempty_string(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not value:
        raise HoldoutSourceAuthorProjectionInputsError(reason_code)
    return value


def _require_nonnegative_int(value: Any, reason_code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HoldoutSourceAuthorProjectionInputsError(reason_code)
    return value


def _sealed_identifier(kind: str, value: str) -> str:
    return _fingerprint_json(
        {
            "projection_policy_fingerprint": (SOURCE_AUTHOR_POLICY_FINGERPRINT),
            "identifier_kind": kind,
            "private_value": value,
        }
    )


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _payload_fingerprint(
    value: Mapping[str, Any],
    field_name: str,
) -> str:
    return _fingerprint_json({key: item for key, item in value.items() if key != field_name})


def _safe_error_payload(reason_code: str) -> dict[str, Any]:
    return {
        "artifact_id": REJECTION_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "reason_fingerprint": _fingerprint_json(reason_code),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-manifest", type=Path, required=True)
    parser.add_argument("--expected-holdout-manifest-sha256", required=True)
    parser.add_argument("--holdout-preflight-safe", type=Path, required=True)
    parser.add_argument(
        "--expected-holdout-preflight-safe-sha256",
        required=True,
    )
    parser.add_argument("--development-manifest", type=Path, required=True)
    parser.add_argument(
        "--expected-development-manifest-sha256",
        required=True,
    )
    parser.add_argument(
        "--development-safe-report",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-development-safe-report-sha256",
        required=True,
    )
    parser.add_argument(
        "--source-bundle-artifact",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-source-bundle-artifact-sha256",
        required=True,
    )
    parser.add_argument(
        "--source-retrieval-snapshot",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-source-retrieval-snapshot-sha256",
        required=True,
    )
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--expected-source-report-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifacts = build_holdout_source_author_projection_inputs(
            holdout_manifest_path=args.holdout_manifest,
            expected_holdout_manifest_sha256=(args.expected_holdout_manifest_sha256),
            holdout_preflight_safe_path=args.holdout_preflight_safe,
            expected_holdout_preflight_safe_sha256=(args.expected_holdout_preflight_safe_sha256),
            development_manifest_path=args.development_manifest,
            expected_development_manifest_sha256=(args.expected_development_manifest_sha256),
            development_safe_report_path=args.development_safe_report,
            expected_development_safe_report_sha256=(args.expected_development_safe_report_sha256),
            source_bundle_artifact_path=args.source_bundle_artifact,
            expected_source_bundle_artifact_sha256=(args.expected_source_bundle_artifact_sha256),
            source_retrieval_snapshot_path=args.source_retrieval_snapshot,
            expected_source_retrieval_snapshot_sha256=(
                args.expected_source_retrieval_snapshot_sha256
            ),
            source_report_path=args.source_report,
            expected_source_report_sha256=(args.expected_source_report_sha256),
            output_root=args.output_root,
        )
    except HoldoutSourceAuthorProjectionInputsError as exc:
        print(
            json.dumps(
                _safe_error_payload(exc.reason_code),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    print(
        json.dumps(
            artifacts.result,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
