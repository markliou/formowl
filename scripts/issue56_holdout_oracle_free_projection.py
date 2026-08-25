#!/usr/bin/env python3
"""Build the sealed Issue #56 holdout projection without decoding its oracle.

The source author must separately seal two oracle-free inputs:

* source lineage plus the executable case projection; and
* development exclusion plus source/thread disjointness.

This tool verifies those inputs, verifies the private holdout manifest by bytes
only, and atomically publishes the exact projection consumed by the independent
holdout runner.  It never parses the private manifest and never executes UAT.
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
import tempfile
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = 1
PROJECTION_ARTIFACT_ID = "formowl_issue56_independent_mail_holdout_oracle_free_projection_v1"
PROJECTION_SCHEMA_VERSION = 1
BUILD_REPORT_ARTIFACT_ID = "formowl_issue56_holdout_oracle_free_projection_build_report_v1"
REJECTION_ARTIFACT_ID = "formowl_issue56_holdout_oracle_free_projection_rejection_v1"
SOURCE_LINEAGE_ARTIFACT_ID = "formowl_issue56_holdout_source_author_oracle_free_lineage_v1"
DEVELOPMENT_DISJOINTNESS_ARTIFACT_ID = (
    "formowl_issue56_holdout_source_author_development_disjointness_v1"
)
HOLDOUT_MANIFEST_ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_manifest_v2"
HOLDOUT_PREFLIGHT_ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_preflight_v2"
PROJECTION_FILENAME = "holdout-oracle-free-projection.private.json"
SAFE_REPORT_FILENAME = "holdout-oracle-free-projection.safe.json"

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

_PRIVATE_ORACLE_FIELD_NAMES = frozenset({"answer_oracle", "expected_private"})
_ORACLE_FREE_CASE_FIELD_NAMES = frozenset(
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
        "authoring_source_observation_ids",
        "required_match_count",
        "limit",
        "private_fingerprint",
        "stratum_id",
        "source_evidence_binding",
    }
)
_SOURCE_BINDING_FIELDS = frozenset(
    {
        "bundle_artifact_sha256",
        "bundle_artifact_fingerprint",
        "mail_evidence_bundle_fingerprint",
        "retrieval_snapshot_sha256",
        "source_report_sha256",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "index_fingerprint",
        "tokenizer_profile_fingerprint",
    }
)
_DEVELOPMENT_BINDING_FIELDS = frozenset(
    {
        "development_case_count",
        "development_manifest_fingerprint",
        "development_manifest_sha256",
        "development_registry_fingerprint",
        "development_safe_report_sha256",
    }
)
_DISJOINTNESS_FIELDS = frozenset(
    {
        "status",
        "development_holdout_observation_overlap_count",
        "development_holdout_message_overlap_count",
        "development_holdout_thread_overlap_count",
        "holdout_authoring_observation_count",
        "holdout_authoring_message_count",
        "holdout_authoring_thread_count",
        "holdout_observation_set_fingerprint",
        "holdout_message_set_fingerprint",
        "holdout_thread_set_fingerprint",
    }
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_PRIVATE_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_SAFE_INPUT_BYTES = 8 * 1024 * 1024
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class HoldoutOracleFreeProjectionError(RuntimeError):
    """Fail-closed error carrying one stable public-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class HoldoutOracleFreeProjectionArtifacts:
    output_root: Path
    projection_path: Path
    safe_report_path: Path
    projection: dict[str, Any]
    safe_report: dict[str, Any]


def build_holdout_oracle_free_projection_artifacts(
    *,
    holdout_preflight_safe_path: Path,
    expected_holdout_preflight_safe_sha256: str,
    private_holdout_manifest_path: Path,
    expected_private_holdout_manifest_sha256: str,
    source_lineage_safe_path: Path,
    expected_source_lineage_safe_sha256: str,
    development_disjointness_safe_path: Path,
    expected_development_disjointness_safe_sha256: str,
    output_root: Path,
    _write_staged_file: Callable[[Path, bytes, int], None] | None = None,
) -> HoldoutOracleFreeProjectionArtifacts:
    """Validate source-authored safe inputs and publish one immutable bundle."""

    if output_root.exists() or output_root.is_symlink():
        raise HoldoutOracleFreeProjectionError("immutable_output_already_exists")

    private_manifest_bytes = _read_sealed_bytes(
        private_holdout_manifest_path,
        expected_private_holdout_manifest_sha256,
        maximum_bytes=_MAX_PRIVATE_MANIFEST_BYTES,
        reason_code="private_holdout_manifest_missing_or_invalid",
        seal_reason_code="private_holdout_manifest_seal_mismatch",
    )
    preflight_bytes, preflight = _read_sealed_json(
        holdout_preflight_safe_path,
        expected_holdout_preflight_safe_sha256,
        reason_prefix="holdout_preflight_safe",
    )
    source_lineage_bytes, source_lineage = _read_sealed_json(
        source_lineage_safe_path,
        expected_source_lineage_safe_sha256,
        reason_prefix="source_lineage_safe",
    )
    development_bytes, development_disjointness = _read_sealed_json(
        development_disjointness_safe_path,
        expected_development_disjointness_safe_sha256,
        reason_prefix="development_disjointness_safe",
    )

    preflight_summary = _validate_holdout_preflight(
        preflight,
        private_manifest_sha256=expected_private_holdout_manifest_sha256,
    )
    source_projection = _validate_source_lineage_artifact(
        source_lineage,
        source_lineage_sha256=_sha256_bytes(source_lineage_bytes),
        preflight_sha256=_sha256_bytes(preflight_bytes),
        private_manifest_sha256=_sha256_bytes(private_manifest_bytes),
        preflight_summary=preflight_summary,
    )
    development_projection = _validate_development_disjointness_artifact(
        development_disjointness,
        development_disjointness_sha256=_sha256_bytes(development_bytes),
        preflight_sha256=_sha256_bytes(preflight_bytes),
        private_manifest_sha256=_sha256_bytes(private_manifest_bytes),
        preflight_summary=preflight_summary,
    )

    manifest_fingerprint = preflight_summary["manifest_fingerprint"]
    private_manifest_binding = {
        "manifest_artifact_id": HOLDOUT_MANIFEST_ARTIFACT_ID,
        "manifest_schema_version": 2,
        "manifest_classification": "independent_mail_holdout",
        "private_manifest_id": _fingerprint_json(
            {
                "artifact_id": HOLDOUT_MANIFEST_ARTIFACT_ID,
                "manifest_fingerprint": manifest_fingerprint,
            }
        ),
        "manifest_sha256": expected_private_holdout_manifest_sha256,
        "manifest_fingerprint": manifest_fingerprint,
        "partition_fingerprint": preflight_summary["partition_fingerprint"],
        "case_count": EXPECTED_CASE_COUNT,
    }
    projection: dict[str, Any] = {
        "artifact_id": PROJECTION_ARTIFACT_ID,
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "status": "sealed_oracle_free",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "private_manifest_binding": private_manifest_binding,
        "source_oracle_bindings": source_projection["source_oracle_bindings"],
        "development_exclusion_binding": development_projection["development_exclusion_binding"],
        "disjointness": development_projection["disjointness"],
        "case_count": EXPECTED_CASE_COUNT,
        "case_strata_counts": dict(EXPECTED_STRATA_COUNTS),
        "cases": source_projection["cases"],
    }
    projection["projection_fingerprint"] = _payload_fingerprint(
        projection,
        "projection_fingerprint",
    )
    validate_holdout_oracle_free_projection(projection)
    projection_bytes = _canonical_json_bytes(projection)

    safe_report: dict[str, Any] = {
        "artifact_id": BUILD_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "projection_status": "sealed_oracle_free",
        "private_manifest_decode_status": "not_performed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "immutability_status": "atomic_no_overwrite",
        "input_binding_status": "passed",
        "source_lineage_status": "passed",
        "development_disjointness_status": "passed",
        "counts": {
            "case_count": EXPECTED_CASE_COUNT,
            "strata_count": len(EXPECTED_STRATA_COUNTS),
            "source_binding_count": len(_SOURCE_BINDING_FIELDS),
            "development_binding_count": len(_DEVELOPMENT_BINDING_FIELDS),
            "development_holdout_observation_overlap_count": 0,
            "development_holdout_message_overlap_count": 0,
            "development_holdout_thread_overlap_count": 0,
            "blocker_count": 0,
        },
        "strata_counts": dict(EXPECTED_STRATA_COUNTS),
        "hashes": {
            "private_manifest_sha256": _sha256_bytes(private_manifest_bytes),
            "holdout_preflight_safe_sha256": _sha256_bytes(preflight_bytes),
            "source_lineage_safe_sha256": _sha256_bytes(source_lineage_bytes),
            "development_disjointness_safe_sha256": _sha256_bytes(development_bytes),
            "manifest_fingerprint": manifest_fingerprint,
            "partition_fingerprint": preflight_summary["partition_fingerprint"],
            "projection_fingerprint": projection["projection_fingerprint"],
            "projection_byte_sha256": _sha256_bytes(projection_bytes),
        },
    }
    safe_report["report_fingerprint"] = _payload_fingerprint(
        safe_report,
        "report_fingerprint",
    )
    _validate_safe_report(safe_report, projection_bytes=projection_bytes)
    safe_report_bytes = _canonical_json_bytes(safe_report)

    _persist_atomic_artifact_directory(
        output_root=output_root,
        files={
            PROJECTION_FILENAME: (projection_bytes, 0o400),
            SAFE_REPORT_FILENAME: (safe_report_bytes, 0o400),
        },
        write_staged_file=_write_staged_file or _write_file_exclusive,
    )
    persisted_projection_bytes = (output_root / PROJECTION_FILENAME).read_bytes()
    persisted_safe_report_bytes = (output_root / SAFE_REPORT_FILENAME).read_bytes()
    if (
        persisted_projection_bytes != projection_bytes
        or persisted_safe_report_bytes != safe_report_bytes
    ):
        raise HoldoutOracleFreeProjectionError("persisted_artifact_byte_drift")
    return HoldoutOracleFreeProjectionArtifacts(
        output_root=output_root,
        projection_path=output_root / PROJECTION_FILENAME,
        safe_report_path=output_root / SAFE_REPORT_FILENAME,
        projection=projection,
        safe_report=safe_report,
    )


def validate_holdout_oracle_free_projection(projection: Mapping[str, Any]) -> None:
    """Validate the exact runner-facing projection schema without oracle data."""

    _assert_oracle_free(projection)
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "execution_status",
        "quality_result_status",
        "private_manifest_binding",
        "source_oracle_bindings",
        "development_exclusion_binding",
        "disjointness",
        "case_count",
        "case_strata_counts",
        "cases",
        "projection_fingerprint",
    }
    if (
        set(projection) != expected_keys
        or projection.get("artifact_id") != PROJECTION_ARTIFACT_ID
        or projection.get("schema_version") != PROJECTION_SCHEMA_VERSION
        or projection.get("status") != "sealed_oracle_free"
        or projection.get("execution_status") != "not_run"
        or projection.get("quality_result_status") != "not_read"
        or projection.get("case_count") != EXPECTED_CASE_COUNT
        or projection.get("case_strata_counts") != EXPECTED_STRATA_COUNTS
        or projection.get("projection_fingerprint")
        != _payload_fingerprint(projection, "projection_fingerprint")
    ):
        raise HoldoutOracleFreeProjectionError("oracle_free_projection_invalid")
    binding = projection.get("private_manifest_binding")
    if not isinstance(binding, Mapping):
        raise HoldoutOracleFreeProjectionError("private_manifest_binding_invalid")
    manifest_fingerprint = _require_sha256(
        binding.get("manifest_fingerprint"),
        "private_manifest_binding_invalid",
    )
    expected_manifest_id = _fingerprint_json(
        {
            "artifact_id": HOLDOUT_MANIFEST_ARTIFACT_ID,
            "manifest_fingerprint": manifest_fingerprint,
        }
    )
    if (
        binding.get("manifest_artifact_id") != HOLDOUT_MANIFEST_ARTIFACT_ID
        or binding.get("manifest_schema_version") != 2
        or binding.get("manifest_classification") != "independent_mail_holdout"
        or binding.get("private_manifest_id") != expected_manifest_id
        or binding.get("case_count") != EXPECTED_CASE_COUNT
    ):
        raise HoldoutOracleFreeProjectionError("private_manifest_binding_invalid")
    _require_sha256(
        binding.get("manifest_sha256"),
        "private_manifest_binding_invalid",
    )
    _require_sha256(
        binding.get("partition_fingerprint"),
        "private_manifest_binding_invalid",
    )
    source_bindings = projection.get("source_oracle_bindings")
    development_binding = projection.get("development_exclusion_binding")
    disjointness = projection.get("disjointness")
    if not isinstance(source_bindings, Mapping) or set(source_bindings) != _SOURCE_BINDING_FIELDS:
        raise HoldoutOracleFreeProjectionError("source_oracle_bindings_invalid")
    if (
        not isinstance(development_binding, Mapping)
        or set(development_binding) != _DEVELOPMENT_BINDING_FIELDS
    ):
        raise HoldoutOracleFreeProjectionError("development_exclusion_binding_invalid")
    if not isinstance(disjointness, Mapping) or set(disjointness) != _DISJOINTNESS_FIELDS:
        raise HoldoutOracleFreeProjectionError("development_disjointness_invalid")
    for field_name, value in source_bindings.items():
        _require_sha256(value, f"source_binding_{field_name}_invalid")
    for field_name, value in development_binding.items():
        if field_name == "development_case_count":
            if value != 100:
                raise HoldoutOracleFreeProjectionError("development_exclusion_binding_invalid")
        else:
            _require_sha256(value, "development_exclusion_binding_invalid")
    _validate_disjointness(disjointness)
    _validate_cases(projection.get("cases"))


def _validate_holdout_preflight(
    report: Mapping[str, Any],
    *,
    private_manifest_sha256: str,
) -> dict[str, Any]:
    _assert_oracle_free(report)
    if (
        report.get("artifact_id") != HOLDOUT_PREFLIGHT_ARTIFACT_ID
        or report.get("schema_version") != 2
        or report.get("status") != "passed"
        or report.get("classification") != "independent_mail_holdout"
        or report.get("execution_status") != "not_run"
        or report.get("quality_result_status") != "not_read"
        or report.get("development_quality_output_status") != "not_read"
        or report.get("source_lineage_status") != "passed"
        or report.get("source_oracle_status") != "passed"
        or report.get("disjointness_status") != "passed"
        or report.get("strata_coverage_status") != "passed"
        or report.get("seal_before_execution_status") != "passed"
        or report.get("blocker_ids") != []
        or report.get("strata_counts") != EXPECTED_STRATA_COUNTS
        or report.get("report_fingerprint") != _payload_fingerprint(report, "report_fingerprint")
    ):
        raise HoldoutOracleFreeProjectionError("holdout_preflight_safe_invalid")
    counts = report.get("counts")
    hashes = report.get("hashes")
    if not isinstance(counts, Mapping) or not isinstance(hashes, Mapping):
        raise HoldoutOracleFreeProjectionError("holdout_preflight_safe_invalid")
    required_zero_counts = (
        "development_holdout_observation_overlap_count",
        "development_holdout_message_overlap_count",
        "development_holdout_thread_overlap_count",
        "source_unexplained_loss_count",
        "blocker_count",
    )
    if counts.get("case_count") != EXPECTED_CASE_COUNT or any(
        counts.get(field_name) != 0 for field_name in required_zero_counts
    ):
        raise HoldoutOracleFreeProjectionError("holdout_preflight_counts_invalid")
    manifest_sha256 = _require_sha256(
        hashes.get("manifest_sha256"),
        "holdout_preflight_manifest_binding_invalid",
    )
    if manifest_sha256 != private_manifest_sha256:
        raise HoldoutOracleFreeProjectionError("holdout_preflight_manifest_binding_mismatch")
    required_hash_fields = (
        "manifest_fingerprint",
        "partition_fingerprint",
        "development_manifest_sha256",
        "development_registry_fingerprint",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "index_fingerprint",
        "segmentation_profile_fingerprint",
        "holdout_observation_set_fingerprint",
        "holdout_message_set_fingerprint",
        "holdout_thread_set_fingerprint",
    )
    validated_hashes = {
        field_name: _require_sha256(
            hashes.get(field_name),
            f"holdout_preflight_{field_name}_missing",
        )
        for field_name in required_hash_fields
    }
    authoring_count_fields = (
        "holdout_authoring_observation_count",
        "holdout_authoring_message_count",
        "holdout_authoring_thread_count",
    )
    validated_counts: dict[str, int] = {}
    for field_name in authoring_count_fields:
        value = counts.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise HoldoutOracleFreeProjectionError(f"holdout_preflight_{field_name}_missing")
        validated_counts[field_name] = value
    return validated_hashes | validated_counts


def _validate_source_lineage_artifact(
    artifact: Mapping[str, Any],
    *,
    source_lineage_sha256: str,
    preflight_sha256: str,
    private_manifest_sha256: str,
    preflight_summary: Mapping[str, Any],
) -> dict[str, Any]:
    _assert_oracle_free(artifact)
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "execution_status",
        "quality_result_status",
        "holdout_preflight_safe_sha256",
        "private_manifest_sha256",
        "manifest_fingerprint",
        "partition_fingerprint",
        "case_count",
        "case_strata_counts",
        "source_oracle_bindings",
        "cases",
        "source_lineage_fingerprint",
    }
    if (
        set(artifact) != expected_keys
        or artifact.get("artifact_id") != SOURCE_LINEAGE_ARTIFACT_ID
        or artifact.get("schema_version") != SCHEMA_VERSION
        or artifact.get("status") != "passed"
        or artifact.get("execution_status") != "not_run"
        or artifact.get("quality_result_status") != "not_read"
        or artifact.get("source_lineage_fingerprint")
        != _payload_fingerprint(artifact, "source_lineage_fingerprint")
        or artifact.get("holdout_preflight_safe_sha256") != preflight_sha256
        or artifact.get("private_manifest_sha256") != private_manifest_sha256
        or artifact.get("manifest_fingerprint") != preflight_summary["manifest_fingerprint"]
        or artifact.get("partition_fingerprint") != preflight_summary["partition_fingerprint"]
        or artifact.get("case_count") != EXPECTED_CASE_COUNT
        or artifact.get("case_strata_counts") != EXPECTED_STRATA_COUNTS
    ):
        raise HoldoutOracleFreeProjectionError("source_lineage_safe_invalid")
    _require_sha256(source_lineage_sha256, "source_lineage_safe_seal_invalid")
    source_bindings = artifact.get("source_oracle_bindings")
    if not isinstance(source_bindings, Mapping) or set(source_bindings) != _SOURCE_BINDING_FIELDS:
        raise HoldoutOracleFreeProjectionError("source_oracle_bindings_invalid")
    for field_name, value in source_bindings.items():
        _require_sha256(value, f"source_binding_{field_name}_invalid")
    preflight_source_crosswalk = {
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "index_fingerprint": "index_fingerprint",
        "tokenizer_profile_fingerprint": "segmentation_profile_fingerprint",
    }
    if any(
        source_bindings[source_field] != preflight_summary[preflight_field]
        for source_field, preflight_field in preflight_source_crosswalk.items()
    ):
        raise HoldoutOracleFreeProjectionError("source_lineage_preflight_mismatch")
    _validate_cases(artifact.get("cases"))
    return {
        "source_oracle_bindings": dict(source_bindings),
        "cases": [dict(case) for case in artifact["cases"]],
    }


def _validate_development_disjointness_artifact(
    artifact: Mapping[str, Any],
    *,
    development_disjointness_sha256: str,
    preflight_sha256: str,
    private_manifest_sha256: str,
    preflight_summary: Mapping[str, Any],
) -> dict[str, Any]:
    _assert_oracle_free(artifact)
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "execution_status",
        "quality_result_status",
        "holdout_preflight_safe_sha256",
        "private_manifest_sha256",
        "manifest_fingerprint",
        "partition_fingerprint",
        "case_count",
        "case_strata_counts",
        "development_exclusion_binding",
        "disjointness",
        "development_disjointness_fingerprint",
    }
    if (
        set(artifact) != expected_keys
        or artifact.get("artifact_id") != DEVELOPMENT_DISJOINTNESS_ARTIFACT_ID
        or artifact.get("schema_version") != SCHEMA_VERSION
        or artifact.get("status") != "passed"
        or artifact.get("execution_status") != "not_run"
        or artifact.get("quality_result_status") != "not_read"
        or artifact.get("development_disjointness_fingerprint")
        != _payload_fingerprint(
            artifact,
            "development_disjointness_fingerprint",
        )
        or artifact.get("holdout_preflight_safe_sha256") != preflight_sha256
        or artifact.get("private_manifest_sha256") != private_manifest_sha256
        or artifact.get("manifest_fingerprint") != preflight_summary["manifest_fingerprint"]
        or artifact.get("partition_fingerprint") != preflight_summary["partition_fingerprint"]
        or artifact.get("case_count") != EXPECTED_CASE_COUNT
        or artifact.get("case_strata_counts") != EXPECTED_STRATA_COUNTS
    ):
        raise HoldoutOracleFreeProjectionError("development_disjointness_safe_invalid")
    _require_sha256(
        development_disjointness_sha256,
        "development_disjointness_safe_seal_invalid",
    )
    development_binding = artifact.get("development_exclusion_binding")
    disjointness = artifact.get("disjointness")
    if (
        not isinstance(development_binding, Mapping)
        or set(development_binding) != _DEVELOPMENT_BINDING_FIELDS
    ):
        raise HoldoutOracleFreeProjectionError("development_exclusion_binding_invalid")
    if not isinstance(disjointness, Mapping) or set(disjointness) != _DISJOINTNESS_FIELDS:
        raise HoldoutOracleFreeProjectionError("development_disjointness_invalid")
    for field_name, value in development_binding.items():
        if field_name == "development_case_count":
            if value != 100:
                raise HoldoutOracleFreeProjectionError("development_exclusion_binding_invalid")
        else:
            _require_sha256(value, "development_exclusion_binding_invalid")
    if (
        development_binding["development_manifest_sha256"]
        != preflight_summary["development_manifest_sha256"]
        or development_binding["development_registry_fingerprint"]
        != preflight_summary["development_registry_fingerprint"]
    ):
        raise HoldoutOracleFreeProjectionError("development_exclusion_preflight_mismatch")
    _validate_disjointness(disjointness)
    count_crosswalk = {
        "holdout_authoring_observation_count": "holdout_authoring_observation_count",
        "holdout_authoring_message_count": "holdout_authoring_message_count",
        "holdout_authoring_thread_count": "holdout_authoring_thread_count",
    }
    fingerprint_crosswalk = {
        "holdout_observation_set_fingerprint": "holdout_observation_set_fingerprint",
        "holdout_message_set_fingerprint": "holdout_message_set_fingerprint",
        "holdout_thread_set_fingerprint": "holdout_thread_set_fingerprint",
    }
    if any(
        disjointness[disjointness_field] != preflight_summary[preflight_field]
        for disjointness_field, preflight_field in count_crosswalk.items()
    ) or any(
        disjointness[disjointness_field] != preflight_summary[preflight_field]
        for disjointness_field, preflight_field in fingerprint_crosswalk.items()
    ):
        raise HoldoutOracleFreeProjectionError("development_disjointness_preflight_mismatch")
    return {
        "development_exclusion_binding": dict(development_binding),
        "disjointness": dict(disjointness),
    }


def _validate_cases(value: Any) -> None:
    if not isinstance(value, list) or len(value) != EXPECTED_CASE_COUNT:
        raise HoldoutOracleFreeProjectionError("oracle_free_case_count_invalid")
    case_ids: set[str] = set()
    case_fingerprints: set[str] = set()
    strata: Counter[str] = Counter()
    required_fields = {
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
    for case in value:
        if (
            not isinstance(case, Mapping)
            or not required_fields.issubset(case)
            or set(case) - _ORACLE_FREE_CASE_FIELD_NAMES
        ):
            raise HoldoutOracleFreeProjectionError("oracle_free_case_shape_invalid")
        _assert_oracle_free(case)
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise HoldoutOracleFreeProjectionError("oracle_free_case_identity_invalid")
        case_ids.add(case_id)
        case_fingerprint = _require_sha256(
            case.get("private_fingerprint"),
            "oracle_free_case_fingerprint_invalid",
        )
        if case_fingerprint in case_fingerprints:
            raise HoldoutOracleFreeProjectionError("oracle_free_case_fingerprint_invalid")
        case_fingerprints.add(case_fingerprint)
        for field_name in (
            "domain",
            "intent_kind",
            "pattern",
            "result_kind",
            "query_text",
            "requester_user_id",
        ):
            if not isinstance(case.get(field_name), str) or not case[field_name]:
                raise HoldoutOracleFreeProjectionError("oracle_free_case_shape_invalid")
        if not isinstance(case.get("source_evidence_binding"), Mapping):
            raise HoldoutOracleFreeProjectionError("oracle_free_case_shape_invalid")
        required_ids = _string_list(
            case.get("required_source_observation_ids"),
            "oracle_free_case_required_ids_invalid",
        )
        forbidden_ids = _string_list(
            case.get("forbidden_source_observation_ids"),
            "oracle_free_case_forbidden_ids_invalid",
        )
        authoring_ids = (
            _string_list(
                case.get("authoring_source_observation_ids"),
                "oracle_free_case_authoring_ids_invalid",
            )
            if "authoring_source_observation_ids" in case
            else required_ids
        )
        required_match_count = case.get("required_match_count")
        limit = case.get("limit")
        if (
            not isinstance(required_match_count, int)
            or isinstance(required_match_count, bool)
            or required_match_count < 0
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
        ):
            raise HoldoutOracleFreeProjectionError("oracle_free_case_shape_invalid")
        stratum = _case_stratum(case)
        _validate_case_shape(
            stratum=stratum,
            result_kind=str(case["result_kind"]),
            required_ids=required_ids,
            forbidden_ids=forbidden_ids,
            authoring_ids=authoring_ids,
        )
        strata[stratum] += 1
    if dict(sorted(strata.items())) != EXPECTED_STRATA_COUNTS:
        raise HoldoutOracleFreeProjectionError("oracle_free_case_strata_invalid")


def _case_stratum(case: Mapping[str, Any]) -> str:
    stratum = case.get("stratum_id")
    if isinstance(stratum, str) and stratum:
        return stratum
    if case.get("result_kind") == "owner_match" and case.get("intent_kind") == (
        "relation_reasoning"
    ):
        return "graph_required"
    raise HoldoutOracleFreeProjectionError("oracle_free_case_stratum_missing")


def _validate_case_shape(
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
            and bool(forbidden_ids)
            and authoring_ids == forbidden_ids
        ),
        "permission_denied": (
            result_kind == "permission_denied"
            and not required_ids
            and bool(forbidden_ids)
            and authoring_ids == forbidden_ids
        ),
    }.get(stratum, False)
    if not valid:
        raise HoldoutOracleFreeProjectionError("oracle_free_case_contract_invalid")


def _validate_disjointness(value: Mapping[str, Any]) -> None:
    if value.get("status") != "passed" or any(
        value.get(field_name) != 0
        for field_name in (
            "development_holdout_observation_overlap_count",
            "development_holdout_message_overlap_count",
            "development_holdout_thread_overlap_count",
        )
    ):
        raise HoldoutOracleFreeProjectionError("development_disjointness_invalid")
    for field_name in (
        "holdout_authoring_observation_count",
        "holdout_authoring_message_count",
        "holdout_authoring_thread_count",
    ):
        count = value.get(field_name)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise HoldoutOracleFreeProjectionError("development_disjointness_invalid")
    for field_name in (
        "holdout_observation_set_fingerprint",
        "holdout_message_set_fingerprint",
        "holdout_thread_set_fingerprint",
    ):
        _require_sha256(value.get(field_name), "development_disjointness_invalid")


def _validate_safe_report(
    report: Mapping[str, Any],
    *,
    projection_bytes: bytes,
) -> None:
    if (
        report.get("artifact_id") != BUILD_REPORT_ARTIFACT_ID
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("status") != "passed"
        or report.get("projection_status") != "sealed_oracle_free"
        or report.get("private_manifest_decode_status") != "not_performed"
        or report.get("execution_status") != "not_run"
        or report.get("quality_result_status") != "not_read"
        or report.get("immutability_status") != "atomic_no_overwrite"
        or report.get("input_binding_status") != "passed"
        or report.get("source_lineage_status") != "passed"
        or report.get("development_disjointness_status") != "passed"
        or report.get("strata_counts") != EXPECTED_STRATA_COUNTS
        or report.get("report_fingerprint") != _payload_fingerprint(report, "report_fingerprint")
    ):
        raise HoldoutOracleFreeProjectionError("projection_safe_report_invalid")
    counts = report.get("counts")
    hashes = report.get("hashes")
    if (
        not isinstance(counts, Mapping)
        or not isinstance(hashes, Mapping)
        or counts.get("case_count") != EXPECTED_CASE_COUNT
        or counts.get("blocker_count") != 0
        or hashes.get("projection_byte_sha256") != _sha256_bytes(projection_bytes)
    ):
        raise HoldoutOracleFreeProjectionError("projection_safe_report_invalid")
    _assert_oracle_free(report)


def _read_sealed_bytes(
    path: Path,
    expected_sha256: str,
    *,
    maximum_bytes: int,
    reason_code: str,
    seal_reason_code: str,
) -> bytes:
    _require_sha256(expected_sha256, f"{reason_code}_expected_sha256_invalid")
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise OSError
        payload = path.read_bytes()
    except OSError as exc:
        raise HoldoutOracleFreeProjectionError(reason_code) from exc
    if _sha256_bytes(payload) != expected_sha256:
        raise HoldoutOracleFreeProjectionError(seal_reason_code)
    return payload


def _read_sealed_json(
    path: Path,
    expected_sha256: str,
    *,
    reason_prefix: str,
) -> tuple[bytes, dict[str, Any]]:
    payload = _read_sealed_bytes(
        path,
        expected_sha256,
        maximum_bytes=_MAX_SAFE_INPUT_BYTES,
        reason_code=f"{reason_prefix}_missing_or_invalid",
        seal_reason_code=f"{reason_prefix}_seal_mismatch",
    )
    try:
        value = json.loads(payload, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HoldoutOracleFreeProjectionError(f"{reason_prefix}_missing_or_invalid") from exc
    if type(value) is not dict:
        raise HoldoutOracleFreeProjectionError(f"{reason_prefix}_missing_or_invalid")
    return payload, value


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
        raise HoldoutOracleFreeProjectionError("immutable_output_already_exists")
    try:
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output_root.name}.staging-",
                dir=output_root.parent,
            )
        )
    except OSError as exc:
        raise HoldoutOracleFreeProjectionError("artifact_staging_unavailable") from exc
    try:
        for filename, (payload, mode) in files.items():
            write_staged_file(staging / filename, payload, mode)
        _fsync_directory(staging)
        _rename_directory_no_replace(staging, output_root)
        _fsync_directory(output_root.parent)
    except HoldoutOracleFreeProjectionError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise HoldoutOracleFreeProjectionError("atomic_artifact_persistence_failed") from exc


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
        raise HoldoutOracleFreeProjectionError("staged_artifact_write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise HoldoutOracleFreeProjectionError("atomic_no_replace_unavailable")
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
        raise HoldoutOracleFreeProjectionError("immutable_output_already_exists")
    raise HoldoutOracleFreeProjectionError("atomic_no_replace_failed")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def _payload_fingerprint(value: Mapping[str, Any], field_name: str) -> str:
    return _fingerprint_json({key: item for key, item in value.items() if key != field_name})


def _require_sha256(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise HoldoutOracleFreeProjectionError(reason_code)
    return value


def _string_list(value: Any, reason_code: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise HoldoutOracleFreeProjectionError(reason_code)
    return tuple(value)


def _assert_oracle_free(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _PRIVATE_ORACLE_FIELD_NAMES:
                raise HoldoutOracleFreeProjectionError("oracle_field_present_in_safe_artifact")
            _assert_oracle_free(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_oracle_free(nested)


def _safe_error_payload(reason_code: str) -> dict[str, Any]:
    return {
        "artifact_id": REJECTION_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "reason_fingerprint": _fingerprint_json(reason_code),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-preflight-safe", type=Path, required=True)
    parser.add_argument("--expected-holdout-preflight-safe-sha256", required=True)
    parser.add_argument("--private-holdout-manifest", type=Path, required=True)
    parser.add_argument("--expected-private-holdout-manifest-sha256", required=True)
    parser.add_argument("--source-lineage-safe", type=Path, required=True)
    parser.add_argument("--expected-source-lineage-safe-sha256", required=True)
    parser.add_argument("--development-disjointness-safe", type=Path, required=True)
    parser.add_argument(
        "--expected-development-disjointness-safe-sha256",
        required=True,
    )
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifacts = build_holdout_oracle_free_projection_artifacts(
            holdout_preflight_safe_path=args.holdout_preflight_safe,
            expected_holdout_preflight_safe_sha256=(args.expected_holdout_preflight_safe_sha256),
            private_holdout_manifest_path=args.private_holdout_manifest,
            expected_private_holdout_manifest_sha256=(
                args.expected_private_holdout_manifest_sha256
            ),
            source_lineage_safe_path=args.source_lineage_safe,
            expected_source_lineage_safe_sha256=(args.expected_source_lineage_safe_sha256),
            development_disjointness_safe_path=(args.development_disjointness_safe),
            expected_development_disjointness_safe_sha256=(
                args.expected_development_disjointness_safe_sha256
            ),
            output_root=args.output_root,
        )
    except HoldoutOracleFreeProjectionError as exc:
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
            artifacts.safe_report,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
