#!/usr/bin/env python3
"""Materialize the sealed Issue #56 development UAT Observation subset.

This source-author boundary decodes the sealed development manifest only to
extract its frozen source Observation references.  It applies the same frozen
hash-decoy policy as ``issue56_simulated_uat.py`` and writes canonical
Observation records through the existing ingestion Observation store layout.
It does not execute or inspect quality evaluation.
"""

from __future__ import annotations

import argparse
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
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
for import_root in (ROOT, PYTHON_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import (  # noqa: E402
    Observation,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (  # noqa: E402
    ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_ingestion.storage.records import ObservationStore  # noqa: E402
from scripts.issue56_simulated_uat import (  # noqa: E402
    CORPUS_POLICY_ID,
    MAX_DECOY_SEGMENTS,
)
from scripts.issue56_source_complete_snapshot_rebind import (  # noqa: E402
    _validate_native_retrieval_report,
    _validate_native_retrieval_snapshot,
)
from scripts.issue56_source_development_uat_manifest import (  # noqa: E402
    ARTIFACT_ID as DEVELOPMENT_MANIFEST_ARTIFACT_ID,
    CLASSIFICATION as DEVELOPMENT_CLASSIFICATION,
    SELECTION_POLICY_FINGERPRINT as DEVELOPMENT_SELECTION_POLICY_FINGERPRINT,
    _validated_bundle_artifact,
)


SCHEMA_VERSION = 1
PRIVATE_ARTIFACT_ID = "formowl_issue56_development_uat_observation_materialization_private_v1"
SAFE_REPORT_ARTIFACT_ID = (
    "formowl_issue56_development_uat_observation_materialization_safe_report_v1"
)
PRIVATE_ARTIFACT_FILENAME = "development-uat-observations.private.json"
SAFE_REPORT_FILENAME = "development-uat-observations.safe.json"
OBSERVATION_RELATIVE_DIRECTORY = Path("data") / "ingestion" / "observations"
EXPECTED_CASE_COUNT = 100
EXPECTED_ADJUDICATED_OBSERVATION_COUNT = 200
EXPECTED_DECOY_OBSERVATION_COUNT = 256
EXPECTED_MATERIALIZED_OBSERVATION_COUNT = 456
CORPUS_POLICY_FINGERPRINT = sha256_json(CORPUS_POLICY_ID)

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_SAFE_RECORD_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")
_MAX_PRIVATE_INPUT_BYTES = 1024 * 1024 * 1024
_MAX_SAFE_INPUT_BYTES = 16 * 1024 * 1024
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class DevelopmentObservationMaterializationError(RuntimeError):
    """Fail-closed error carrying one stable public-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class DevelopmentObservationMaterializationArtifacts:
    work_dir: Path
    observations_directory: Path
    private_artifact_path: Path
    safe_report_path: Path
    private_artifact: dict[str, Any]
    safe_report: dict[str, Any]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-snapshot", type=Path, required=True)
    parser.add_argument(
        "--expected-retrieval-snapshot-sha256",
        required=True,
    )
    parser.add_argument("--bundle-artifact", type=Path, required=True)
    parser.add_argument(
        "--expected-bundle-artifact-sha256",
        required=True,
    )
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument(
        "--expected-retrieval-report-sha256",
        required=True,
    )
    parser.add_argument("--development-manifest", type=Path, required=True)
    parser.add_argument(
        "--expected-development-manifest-sha256",
        required=True,
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifacts = materialize_development_uat_observations(
            retrieval_snapshot_path=args.retrieval_snapshot,
            expected_retrieval_snapshot_sha256=(args.expected_retrieval_snapshot_sha256),
            bundle_artifact_path=args.bundle_artifact,
            expected_bundle_artifact_sha256=args.expected_bundle_artifact_sha256,
            retrieval_report_path=args.retrieval_report,
            expected_retrieval_report_sha256=args.expected_retrieval_report_sha256,
            development_manifest_path=args.development_manifest,
            expected_development_manifest_sha256=(args.expected_development_manifest_sha256),
            work_dir=args.work_dir,
        )
    except DevelopmentObservationMaterializationError as exc:
        print(
            json.dumps(
                _blocked_report(exc.reason_code),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            artifacts.safe_report,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def materialize_development_uat_observations(
    *,
    retrieval_snapshot_path: Path,
    expected_retrieval_snapshot_sha256: str,
    bundle_artifact_path: Path,
    expected_bundle_artifact_sha256: str,
    retrieval_report_path: Path,
    expected_retrieval_report_sha256: str,
    development_manifest_path: Path,
    expected_development_manifest_sha256: str,
    work_dir: Path,
) -> DevelopmentObservationMaterializationArtifacts:
    """Validate sealed source inputs and atomically publish exactly 456 records."""

    resolved_work_dir = _validated_new_work_dir(work_dir)
    snapshot_bytes, snapshot = _read_sealed_json(
        retrieval_snapshot_path,
        expected_sha256=expected_retrieval_snapshot_sha256,
        maximum_bytes=_MAX_PRIVATE_INPUT_BYTES,
        reason_prefix="retrieval_snapshot",
    )
    bundle_bytes, bundle_artifact = _read_sealed_json(
        bundle_artifact_path,
        expected_sha256=expected_bundle_artifact_sha256,
        maximum_bytes=_MAX_PRIVATE_INPUT_BYTES,
        reason_prefix="bundle_artifact",
    )
    report_bytes, retrieval_report = _read_sealed_json(
        retrieval_report_path,
        expected_sha256=expected_retrieval_report_sha256,
        maximum_bytes=_MAX_SAFE_INPUT_BYTES,
        reason_prefix="retrieval_report",
    )
    manifest_bytes, manifest = _read_sealed_json(
        development_manifest_path,
        expected_sha256=expected_development_manifest_sha256,
        maximum_bytes=_MAX_PRIVATE_INPUT_BYTES,
        reason_prefix="development_manifest",
    )

    _validate_source_artifacts(
        snapshot=snapshot,
        snapshot_byte_sha256=_sha256_bytes(snapshot_bytes),
        bundle_artifact=bundle_artifact,
        bundle_byte_sha256=_sha256_bytes(bundle_bytes),
        retrieval_report=retrieval_report,
        retrieval_report_byte_sha256=_sha256_bytes(report_bytes),
        manifest=manifest,
        manifest_byte_sha256=_sha256_bytes(manifest_bytes),
    )
    bundle_payload = _bundle_payload(bundle_artifact)
    body_by_observation_id, observation_by_id = _validated_body_lineage(
        snapshot=snapshot,
        bundle_payload=bundle_payload,
    )
    adjudicated_ids = _development_adjudicated_observation_ids(
        manifest=manifest,
        observation_by_id=observation_by_id,
    )
    eligible_decoy_ids = set(body_by_observation_id) - set(adjudicated_ids)
    if len(eligible_decoy_ids) < EXPECTED_DECOY_OBSERVATION_COUNT:
        raise DevelopmentObservationMaterializationError("development_decoy_capacity_insufficient")
    decoy_ids = tuple(
        sorted(
            eligible_decoy_ids,
            key=lambda observation_id: sha256_json(
                {
                    "policy": CORPUS_POLICY_ID,
                    "manifest_byte_hash": _sha256_bytes(manifest_bytes),
                    "observation_id": observation_id,
                }
            ),
        )[:MAX_DECOY_SEGMENTS]
    )
    if len(decoy_ids) != EXPECTED_DECOY_OBSERVATION_COUNT:
        raise DevelopmentObservationMaterializationError(
            "development_decoy_selection_count_invalid"
        )
    selected_ids = tuple(sorted(set(adjudicated_ids) | set(decoy_ids)))
    if len(selected_ids) != EXPECTED_MATERIALIZED_OBSERVATION_COUNT or set(adjudicated_ids) & set(
        decoy_ids
    ):
        raise DevelopmentObservationMaterializationError(
            "development_observation_selection_collision"
        )

    selection_proof = {
        "corpus_policy_id": CORPUS_POLICY_ID,
        "corpus_policy_fingerprint": CORPUS_POLICY_FINGERPRINT,
        "manifest_byte_sha256": _sha256_bytes(manifest_bytes),
        "adjudicated_observation_ids": list(adjudicated_ids),
        "eligible_decoy_observation_count": len(eligible_decoy_ids),
        "decoy_observation_ids": list(decoy_ids),
        "selected_observation_ids": list(selected_ids),
    }
    selection_proof_fingerprint = sha256_json(selection_proof)

    staging = _create_staging_directory(resolved_work_dir)
    try:
        observation_store = ObservationStore(staging / "data")
        for observation_id in selected_ids:
            observation_store.create(observation_by_id[observation_id])
        records = _validated_staged_record_inventory(
            staging=staging,
            selected_ids=selected_ids,
            adjudicated_ids=frozenset(adjudicated_ids),
            observation_by_id=observation_by_id,
        )
        record_inventory_fingerprint = sha256_json(records)
        private_artifact = _private_artifact(
            snapshot=snapshot,
            snapshot_byte_sha256=_sha256_bytes(snapshot_bytes),
            bundle_artifact=bundle_artifact,
            bundle_byte_sha256=_sha256_bytes(bundle_bytes),
            retrieval_report=retrieval_report,
            retrieval_report_byte_sha256=_sha256_bytes(report_bytes),
            manifest=manifest,
            manifest_byte_sha256=_sha256_bytes(manifest_bytes),
            adjudicated_ids=adjudicated_ids,
            decoy_ids=decoy_ids,
            eligible_decoy_count=len(eligible_decoy_ids),
            records=records,
            record_inventory_fingerprint=record_inventory_fingerprint,
            selection_proof_fingerprint=selection_proof_fingerprint,
        )
        validate_private_materialization_artifact(private_artifact)
        private_bytes = _canonical_json_bytes(private_artifact)
        _write_staged_file(
            staging / PRIVATE_ARTIFACT_FILENAME,
            private_bytes,
            mode=0o600,
        )
        safe_report = _safe_report(
            snapshot=snapshot,
            bundle_artifact=bundle_artifact,
            retrieval_report=retrieval_report,
            manifest=manifest,
            private_artifact=private_artifact,
            private_artifact_bytes=private_bytes,
        )
        validate_safe_materialization_report(
            safe_report,
            private_artifact_bytes=private_bytes,
        )
        safe_bytes = _canonical_json_bytes(safe_report)
        _write_staged_file(
            staging / SAFE_REPORT_FILENAME,
            safe_bytes,
            mode=0o644,
        )
        _fsync_tree(staging)
        _rename_directory_no_replace(staging, resolved_work_dir)
        _fsync_directory(resolved_work_dir.parent)
    except DevelopmentObservationMaterializationError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise DevelopmentObservationMaterializationError("atomic_materialization_failed") from exc

    return DevelopmentObservationMaterializationArtifacts(
        work_dir=resolved_work_dir,
        observations_directory=resolved_work_dir / OBSERVATION_RELATIVE_DIRECTORY,
        private_artifact_path=resolved_work_dir / PRIVATE_ARTIFACT_FILENAME,
        safe_report_path=resolved_work_dir / SAFE_REPORT_FILENAME,
        private_artifact=private_artifact,
        safe_report=safe_report,
    )


def validate_private_materialization_artifact(
    artifact: Mapping[str, Any],
) -> None:
    required_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "claim_boundary_status",
        "created_at",
        "retrieval_snapshot_byte_sha256",
        "bundle_artifact_byte_sha256",
        "retrieval_report_byte_sha256",
        "development_manifest_byte_sha256",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "permission_fingerprint",
        "tokenizer_profile_fingerprint",
        "bundle_artifact_fingerprint",
        "mail_evidence_bundle_fingerprint",
        "retrieval_snapshot_fingerprint",
        "retrieval_report_fingerprint",
        "development_manifest_fingerprint",
        "corpus_policy_id",
        "corpus_policy_fingerprint",
        "adjudicated_observation_ids",
        "decoy_observation_ids",
        "selected_observation_id_set_fingerprint",
        "selected_observation_hash_set_fingerprint",
        "record_byte_sha256_set_fingerprint",
        "record_inventory_fingerprint",
        "selection_proof_fingerprint",
        "records",
        "counts",
        "artifact_fingerprint",
    }
    if set(artifact) != required_keys:
        raise DevelopmentObservationMaterializationError("private_materialization_fields_invalid")
    if (
        artifact.get("artifact_id") != PRIVATE_ARTIFACT_ID
        or artifact.get("schema_version") != SCHEMA_VERSION
        or artifact.get("status") != "passed"
        or artifact.get("claim_boundary_status")
        != "development_observation_materialization_quality_not_run"
    ):
        raise DevelopmentObservationMaterializationError("private_materialization_status_invalid")
    for field_name in (
        "retrieval_snapshot_byte_sha256",
        "bundle_artifact_byte_sha256",
        "retrieval_report_byte_sha256",
        "development_manifest_byte_sha256",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "permission_fingerprint",
        "tokenizer_profile_fingerprint",
        "bundle_artifact_fingerprint",
        "mail_evidence_bundle_fingerprint",
        "retrieval_snapshot_fingerprint",
        "retrieval_report_fingerprint",
        "development_manifest_fingerprint",
        "corpus_policy_fingerprint",
        "selected_observation_id_set_fingerprint",
        "selected_observation_hash_set_fingerprint",
        "record_byte_sha256_set_fingerprint",
        "record_inventory_fingerprint",
        "selection_proof_fingerprint",
        "artifact_fingerprint",
    ):
        _require_sha256(artifact.get(field_name), field_name)
    if artifact.get("corpus_policy_id") != CORPUS_POLICY_ID:
        raise DevelopmentObservationMaterializationError("private_materialization_policy_invalid")
    adjudicated_ids = _validated_observation_id_list(
        artifact.get("adjudicated_observation_ids"),
        reason_code="private_materialization_adjudicated_ids_invalid",
        expected_count=EXPECTED_ADJUDICATED_OBSERVATION_COUNT,
    )
    decoy_ids = _validated_observation_id_list(
        artifact.get("decoy_observation_ids"),
        reason_code="private_materialization_decoy_ids_invalid",
        expected_count=EXPECTED_DECOY_OBSERVATION_COUNT,
    )
    if set(adjudicated_ids) & set(decoy_ids):
        raise DevelopmentObservationMaterializationError(
            "private_materialization_selection_collision"
        )
    records = artifact.get("records")
    if not isinstance(records, list) or len(records) != EXPECTED_MATERIALIZED_OBSERVATION_COUNT:
        raise DevelopmentObservationMaterializationError(
            "private_materialization_record_inventory_invalid"
        )
    record_ids: list[str] = []
    observation_hashes: list[str] = []
    record_byte_hashes: list[str] = []
    expected_roles = {observation_id: "adjudicated" for observation_id in adjudicated_ids} | {
        observation_id: "decoy" for observation_id in decoy_ids
    }
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {
            "observation_id",
            "selection_role",
            "observation_hash",
            "record_byte_sha256",
        }:
            raise DevelopmentObservationMaterializationError(
                "private_materialization_record_inventory_invalid"
            )
        observation_id = _safe_observation_id(record.get("observation_id"))
        if record.get("selection_role") != expected_roles.get(observation_id):
            raise DevelopmentObservationMaterializationError(
                "private_materialization_record_role_invalid"
            )
        observation_hashes.append(
            _require_sha256(record.get("observation_hash"), "observation_hash")
        )
        record_byte_hashes.append(
            _require_sha256(record.get("record_byte_sha256"), "record_byte_sha256")
        )
        record_ids.append(observation_id)
    selected_ids = sorted(expected_roles)
    if record_ids != selected_ids or len(set(record_ids)) != len(record_ids):
        raise DevelopmentObservationMaterializationError(
            "private_materialization_record_order_invalid"
        )
    if artifact.get("selected_observation_id_set_fingerprint") != sha256_json(selected_ids):
        raise DevelopmentObservationMaterializationError(
            "private_materialization_selected_id_fingerprint_drift"
        )
    if artifact.get("selected_observation_hash_set_fingerprint") != sha256_json(
        sorted(observation_hashes)
    ):
        raise DevelopmentObservationMaterializationError(
            "private_materialization_observation_hash_fingerprint_drift"
        )
    if artifact.get("record_byte_sha256_set_fingerprint") != sha256_json(
        sorted(record_byte_hashes)
    ):
        raise DevelopmentObservationMaterializationError(
            "private_materialization_record_byte_fingerprint_drift"
        )
    if artifact.get("record_inventory_fingerprint") != sha256_json(records):
        raise DevelopmentObservationMaterializationError(
            "private_materialization_record_inventory_fingerprint_drift"
        )
    counts = artifact.get("counts")
    if not isinstance(counts, Mapping) or counts != {
        "manifest_case_count": EXPECTED_CASE_COUNT,
        "adjudicated_observation_count": EXPECTED_ADJUDICATED_OBSERVATION_COUNT,
        "decoy_observation_count": EXPECTED_DECOY_OBSERVATION_COUNT,
        "materialized_observation_count": EXPECTED_MATERIALIZED_OBSERVATION_COUNT,
        "eligible_decoy_observation_count": counts.get("eligible_decoy_observation_count"),
        "selection_collision_count": 0,
        "overflow_count": 0,
        "blocker_count": 0,
    }:
        raise DevelopmentObservationMaterializationError("private_materialization_counts_invalid")
    eligible_count = counts.get("eligible_decoy_observation_count")
    if (
        not isinstance(eligible_count, int)
        or isinstance(eligible_count, bool)
        or eligible_count < EXPECTED_DECOY_OBSERVATION_COUNT
    ):
        raise DevelopmentObservationMaterializationError(
            "private_materialization_decoy_capacity_invalid"
        )
    if artifact.get("artifact_fingerprint") != _payload_fingerprint(
        artifact,
        "artifact_fingerprint",
    ):
        raise DevelopmentObservationMaterializationError(
            "private_materialization_fingerprint_drift"
        )


def validate_safe_materialization_report(
    report: Mapping[str, Any],
    *,
    private_artifact_bytes: bytes,
) -> None:
    required_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "claim_boundary_status",
        "quality_evaluation_status",
        "methodology_readiness_status",
        "owner_contract_status",
        "source_lineage_status",
        "permission_lineage_status",
        "candidate_admission_profile_status",
        "atomic_write_status",
        "selection_status",
        "corpus_policy_fingerprint",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "permission_fingerprint",
        "candidate_admission_profile_fingerprint",
        "retrieval_snapshot_fingerprint",
        "bundle_artifact_fingerprint",
        "retrieval_report_fingerprint",
        "development_manifest_fingerprint",
        "materialization_artifact_fingerprint",
        "materialization_artifact_byte_sha256",
        "selected_observation_id_set_fingerprint",
        "selected_observation_hash_set_fingerprint",
        "record_byte_sha256_set_fingerprint",
        "record_inventory_fingerprint",
        "selection_proof_fingerprint",
        "counts",
        "blocker_ids",
        "report_fingerprint",
    }
    if set(report) != required_keys:
        raise DevelopmentObservationMaterializationError("safe_materialization_fields_invalid")
    if (
        report.get("artifact_id") != SAFE_REPORT_ARTIFACT_ID
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("status") != "passed"
        or report.get("claim_boundary_status") != "materialization_only_no_quality_claim"
        or report.get("quality_evaluation_status") != "not_run"
        or report.get("methodology_readiness_status") != "blocked"
        or report.get("blocker_ids") != []
    ):
        raise DevelopmentObservationMaterializationError("safe_materialization_status_invalid")
    for status_field in (
        "owner_contract_status",
        "source_lineage_status",
        "permission_lineage_status",
        "candidate_admission_profile_status",
        "atomic_write_status",
        "selection_status",
    ):
        if report.get(status_field) != "passed":
            raise DevelopmentObservationMaterializationError("safe_materialization_status_invalid")
    for field_name in (
        "corpus_policy_fingerprint",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "permission_fingerprint",
        "candidate_admission_profile_fingerprint",
        "retrieval_snapshot_fingerprint",
        "bundle_artifact_fingerprint",
        "retrieval_report_fingerprint",
        "development_manifest_fingerprint",
        "materialization_artifact_fingerprint",
        "materialization_artifact_byte_sha256",
        "selected_observation_id_set_fingerprint",
        "selected_observation_hash_set_fingerprint",
        "record_byte_sha256_set_fingerprint",
        "record_inventory_fingerprint",
        "selection_proof_fingerprint",
        "report_fingerprint",
    ):
        _require_sha256(report.get(field_name), field_name)
    if report.get("materialization_artifact_byte_sha256") != _sha256_bytes(private_artifact_bytes):
        raise DevelopmentObservationMaterializationError(
            "safe_materialization_private_byte_seal_mismatch"
        )
    try:
        private_artifact = json.loads(
            private_artifact_bytes,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DevelopmentObservationMaterializationError(
            "safe_materialization_private_artifact_invalid"
        ) from exc
    if not isinstance(private_artifact, dict):
        raise DevelopmentObservationMaterializationError(
            "safe_materialization_private_artifact_invalid"
        )
    validate_private_materialization_artifact(private_artifact)
    private_bindings = {
        "corpus_policy_fingerprint": "corpus_policy_fingerprint",
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "permission_fingerprint": "permission_fingerprint",
        "candidate_admission_profile_fingerprint": ("tokenizer_profile_fingerprint"),
        "retrieval_snapshot_fingerprint": "retrieval_snapshot_fingerprint",
        "bundle_artifact_fingerprint": "bundle_artifact_fingerprint",
        "retrieval_report_fingerprint": "retrieval_report_fingerprint",
        "development_manifest_fingerprint": "development_manifest_fingerprint",
        "materialization_artifact_fingerprint": "artifact_fingerprint",
        "selected_observation_id_set_fingerprint": ("selected_observation_id_set_fingerprint"),
        "selected_observation_hash_set_fingerprint": ("selected_observation_hash_set_fingerprint"),
        "record_byte_sha256_set_fingerprint": ("record_byte_sha256_set_fingerprint"),
        "record_inventory_fingerprint": "record_inventory_fingerprint",
        "selection_proof_fingerprint": "selection_proof_fingerprint",
    }
    if any(
        report[report_field] != private_artifact[private_field]
        for report_field, private_field in private_bindings.items()
    ):
        raise DevelopmentObservationMaterializationError(
            "safe_materialization_private_binding_drift"
        )
    if report.get("counts") != private_artifact.get("counts"):
        raise DevelopmentObservationMaterializationError("safe_materialization_count_binding_drift")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise DevelopmentObservationMaterializationError("safe_materialization_fingerprint_drift")
    assert_no_public_raw_references(
        report,
        "issue56_development_uat_observation_materialization_safe_report",
    )


def _validate_source_artifacts(
    *,
    snapshot: Mapping[str, Any],
    snapshot_byte_sha256: str,
    bundle_artifact: Mapping[str, Any],
    bundle_byte_sha256: str,
    retrieval_report: Mapping[str, Any],
    retrieval_report_byte_sha256: str,
    manifest: Mapping[str, Any],
    manifest_byte_sha256: str,
) -> None:
    try:
        _validate_native_retrieval_snapshot(snapshot)
    except Exception as exc:
        raise DevelopmentObservationMaterializationError(
            "retrieval_snapshot_contract_invalid"
        ) from exc
    try:
        _validate_native_retrieval_report(retrieval_report)
    except Exception as exc:
        raise DevelopmentObservationMaterializationError(
            "retrieval_report_contract_invalid"
        ) from exc
    try:
        _validated_bundle_artifact(bundle_artifact)
    except Exception as exc:
        raise DevelopmentObservationMaterializationError(
            "bundle_artifact_contract_invalid"
        ) from exc
    profile = load_issue56_target_mail_tokenizer_profile()
    if (
        profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
        or profile.profile_fingerprint != ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
        or snapshot.get("tokenizer_profile_fingerprint") != profile.profile_fingerprint
        or retrieval_report.get("candidate_admission_profile_fingerprint")
        != profile.profile_fingerprint
    ):
        raise DevelopmentObservationMaterializationError("target_tokenizer_profile_binding_invalid")

    bundle_bindings = {
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "bundle_fingerprint": "mail_evidence_bundle_fingerprint",
    }
    if any(
        bundle_artifact[bundle_field] != snapshot[snapshot_field]
        for bundle_field, snapshot_field in bundle_bindings.items()
    ):
        raise DevelopmentObservationMaterializationError("bundle_snapshot_binding_mismatch")
    report_bindings = {
        "retrieval_snapshot_fingerprint": "snapshot_fingerprint",
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "permission_fingerprint": "permission_fingerprint",
        "parsed_observation_fingerprint": "parsed_observation_fingerprint",
        "mail_evidence_bundle_fingerprint": "mail_evidence_bundle_fingerprint",
        "candidate_admission_profile_fingerprint": "tokenizer_profile_fingerprint",
        "observation_snapshot_fingerprint": "observation_snapshot_fingerprint",
        "candidate_manifest_fingerprint": "candidate_manifest_fingerprint",
        "index_fingerprint": "index_fingerprint",
    }
    if any(
        retrieval_report[report_field] != snapshot[snapshot_field]
        for report_field, snapshot_field in report_bindings.items()
    ):
        raise DevelopmentObservationMaterializationError(
            "retrieval_report_snapshot_binding_mismatch"
        )
    if retrieval_report.get("bundle_artifact_fingerprint") != bundle_artifact.get(
        "artifact_fingerprint"
    ) or retrieval_report.get("counts") != snapshot.get("counts"):
        raise DevelopmentObservationMaterializationError(
            "retrieval_report_bundle_or_count_binding_mismatch"
        )
    _validate_development_manifest_contract(manifest)
    source_bindings = manifest["source_bindings"]
    expected_manifest_bindings = {
        "bundle_artifact_byte_hash": bundle_byte_sha256,
        "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
        "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
        "retrieval_snapshot_byte_hash": snapshot_byte_sha256,
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "tokenizer_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
        "index_fingerprint": snapshot["index_fingerprint"],
        "retrieval_report_byte_hash": retrieval_report_byte_sha256,
    }
    if any(
        source_bindings.get(field_name) != expected
        for field_name, expected in expected_manifest_bindings.items()
    ):
        raise DevelopmentObservationMaterializationError(
            "development_manifest_source_binding_mismatch"
        )
    _require_sha256(
        manifest_byte_sha256,
        "development_manifest_byte_sha256",
    )


def _validate_development_manifest_contract(manifest: Mapping[str, Any]) -> None:
    if (
        manifest.get("artifact_id") != DEVELOPMENT_MANIFEST_ARTIFACT_ID
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("classification") != DEVELOPMENT_CLASSIFICATION
        or manifest.get("quality_evaluation_status") != "not_run"
        or manifest.get("holdout_content_consumed") is not False
        or manifest.get("oracle_content_consumed") is not False
        or manifest.get("case_count") != EXPECTED_CASE_COUNT
        or manifest.get("selection_policy_fingerprint") != DEVELOPMENT_SELECTION_POLICY_FINGERPRINT
    ):
        raise DevelopmentObservationMaterializationError("development_manifest_contract_invalid")
    if manifest.get("manifest_fingerprint") != _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    ):
        raise DevelopmentObservationMaterializationError("development_manifest_fingerprint_drift")
    source_bindings = manifest.get("source_bindings")
    cases = manifest.get("cases")
    if not isinstance(source_bindings, Mapping) or not isinstance(cases, list):
        raise DevelopmentObservationMaterializationError("development_manifest_contract_invalid")
    if len(cases) != EXPECTED_CASE_COUNT:
        raise DevelopmentObservationMaterializationError("development_manifest_case_count_invalid")
    seen_case_fingerprints: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise DevelopmentObservationMaterializationError(
                "development_manifest_case_contract_invalid"
            )
        required_ids = case.get("required_source_observation_ids")
        forbidden_ids = case.get("forbidden_source_observation_ids")
        if (
            not isinstance(required_ids, list)
            or not isinstance(forbidden_ids, list)
            or not required_ids
            or forbidden_ids
            or any(not isinstance(value, str) or not value for value in required_ids)
        ):
            raise DevelopmentObservationMaterializationError(
                "development_manifest_case_evidence_invalid"
            )
        fingerprint = case.get("private_fingerprint")
        _require_sha256(fingerprint, "development_case_private_fingerprint")
        if fingerprint != _payload_fingerprint(case, "private_fingerprint"):
            raise DevelopmentObservationMaterializationError(
                "development_manifest_case_fingerprint_drift"
            )
        if fingerprint in seen_case_fingerprints:
            raise DevelopmentObservationMaterializationError(
                "development_manifest_case_fingerprint_duplicate"
            )
        seen_case_fingerprints.add(str(fingerprint))


def _bundle_payload(bundle_artifact: Mapping[str, Any]) -> dict[str, Any]:
    payload = bundle_artifact.get("bundle")
    if not isinstance(payload, dict):
        raise DevelopmentObservationMaterializationError("bundle_artifact_payload_invalid")
    return payload


def _validated_body_lineage(
    *,
    snapshot: Mapping[str, Any],
    bundle_payload: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Observation]]:
    parsed_rows = snapshot.get("parsed_mail_observations")
    body_segments = bundle_payload.get("body_segments")
    message_occurrences = bundle_payload.get("message_occurrences")
    if (
        not isinstance(parsed_rows, list)
        or not isinstance(body_segments, list)
        or not isinstance(message_occurrences, list)
    ):
        raise DevelopmentObservationMaterializationError("source_body_lineage_unavailable")
    observation_by_id: dict[str, Observation] = {}
    body_observation_by_id: dict[str, Observation] = {}
    for row in parsed_rows:
        if not isinstance(row, dict):
            raise DevelopmentObservationMaterializationError("source_observation_contract_invalid")
        observation = Observation.from_dict(row)
        if observation.observation_id in observation_by_id:
            raise DevelopmentObservationMaterializationError("source_observation_id_duplicate")
        observation_by_id[observation.observation_id] = observation
        if observation.observation_type == "email_body_segment":
            body_observation_by_id[observation.observation_id] = observation
    body_by_observation_id: dict[str, Mapping[str, Any]] = {}
    for segment in body_segments:
        if not isinstance(segment, Mapping):
            raise DevelopmentObservationMaterializationError("bundle_body_segment_contract_invalid")
        source_observation_id = segment.get("source_observation_id")
        if (
            not isinstance(source_observation_id, str)
            or source_observation_id in body_by_observation_id
        ):
            raise DevelopmentObservationMaterializationError("bundle_body_observation_id_duplicate")
        body_by_observation_id[source_observation_id] = segment
    if set(body_by_observation_id) != set(body_observation_by_id):
        raise DevelopmentObservationMaterializationError("bundle_snapshot_body_coverage_mismatch")
    occurrence_to_message: dict[str, str] = {}
    for occurrence in message_occurrences:
        if not isinstance(occurrence, Mapping):
            raise DevelopmentObservationMaterializationError(
                "bundle_message_occurrence_contract_invalid"
            )
        occurrence_id = occurrence.get("message_occurrence_id")
        email_message_id = occurrence.get("email_message_id")
        if (
            not isinstance(occurrence_id, str)
            or not isinstance(email_message_id, str)
            or occurrence_id in occurrence_to_message
        ):
            raise DevelopmentObservationMaterializationError("bundle_message_occurrence_collision")
        occurrence_to_message[occurrence_id] = email_message_id
    permission_fingerprint = str(snapshot["permission_fingerprint"])
    provenance_fingerprint = str(snapshot["source_provenance_fingerprint"])
    for observation_id, segment in body_by_observation_id.items():
        observation = body_observation_by_id[observation_id]
        occurrence_id = _observation_occurrence_id(observation)
        if (
            observation.modality != "mail"
            or observation.text != segment.get("text")
            or occurrence_id != segment.get("message_occurrence_id")
            or occurrence_to_message.get(str(occurrence_id)) != segment.get("email_message_id")
            or sha256_json(observation.permission_scope) != permission_fingerprint
            or observation.location.get("source_provenance_fingerprint") != provenance_fingerprint
            or not isinstance(
                observation.location.get("source_inventory_item_id"),
                str,
            )
            or not isinstance(observation.location.get("source_local_key"), str)
            or _SHA256_RE.fullmatch(str(observation.location.get("source_content_hash", "")))
            is None
        ):
            raise DevelopmentObservationMaterializationError(
                "bundle_snapshot_body_lineage_mismatch"
            )
    return body_by_observation_id, observation_by_id


def _development_adjudicated_observation_ids(
    *,
    manifest: Mapping[str, Any],
    observation_by_id: Mapping[str, Observation],
) -> tuple[str, ...]:
    required_references: list[str] = []
    for case in manifest["cases"]:
        required_ids = [
            _safe_observation_id(value) for value in case["required_source_observation_ids"]
        ]
        if len(set(required_ids)) != len(required_ids):
            raise DevelopmentObservationMaterializationError(
                "development_manifest_case_evidence_collision"
            )
        required_references.extend(required_ids)
        binding = case.get("source_evidence_binding")
        if not isinstance(binding, Mapping):
            raise DevelopmentObservationMaterializationError(
                "development_manifest_case_lineage_missing"
            )
        observations = [observation_by_id.get(value) for value in required_ids]
        if any(observation is None for observation in observations):
            raise DevelopmentObservationMaterializationError(
                "development_required_observation_missing"
            )
        validated_observations = [
            observation for observation in observations if observation is not None
        ]
        expected_observation_hashes = sorted(
            sha256_json(observation.to_dict()) for observation in validated_observations
        )
        expected_occurrence_hashes = sorted(
            sha256_json(_observation_occurrence_id(observation))
            for observation in validated_observations
        )
        if (
            binding.get("required_observation_hashes") != expected_observation_hashes
            or binding.get("required_message_occurrence_hashes") != expected_occurrence_hashes
        ):
            raise DevelopmentObservationMaterializationError(
                "development_manifest_case_lineage_mismatch"
            )
    adjudicated_ids = tuple(sorted(set(required_references)))
    if (
        len(required_references) != EXPECTED_ADJUDICATED_OBSERVATION_COUNT
        or len(adjudicated_ids) != EXPECTED_ADJUDICATED_OBSERVATION_COUNT
        or manifest.get("required_evidence_reference_count")
        != EXPECTED_ADJUDICATED_OBSERVATION_COUNT
        or manifest.get("distinct_required_observation_count")
        != EXPECTED_ADJUDICATED_OBSERVATION_COUNT
    ):
        raise DevelopmentObservationMaterializationError(
            "development_adjudicated_observation_count_invalid"
        )
    for observation_id in adjudicated_ids:
        observation = observation_by_id[observation_id]
        if observation.observation_type != "email_body_segment":
            raise DevelopmentObservationMaterializationError(
                "development_adjudicated_observation_type_invalid"
            )
    return adjudicated_ids


def _validated_staged_record_inventory(
    *,
    staging: Path,
    selected_ids: Sequence[str],
    adjudicated_ids: frozenset[str],
    observation_by_id: Mapping[str, Observation],
) -> list[dict[str, str]]:
    observations_directory = staging / OBSERVATION_RELATIVE_DIRECTORY
    actual_paths = sorted(observations_directory.glob("*.json"))
    if len(actual_paths) != EXPECTED_MATERIALIZED_OBSERVATION_COUNT:
        raise DevelopmentObservationMaterializationError("staged_observation_record_count_invalid")
    records: list[dict[str, str]] = []
    for observation_id in selected_ids:
        path = observations_directory / f"{observation_id}.json"
        try:
            metadata = path.lstat()
            raw = path.read_bytes()
            payload = json.loads(raw, object_pairs_hook=_unique_json_object)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise DevelopmentObservationMaterializationError(
                "staged_observation_record_invalid"
            ) from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise DevelopmentObservationMaterializationError("staged_observation_record_invalid")
        observation = Observation.from_dict(payload)
        expected = observation_by_id[observation_id]
        if observation.to_dict() != expected.to_dict():
            raise DevelopmentObservationMaterializationError("staged_observation_round_trip_drift")
        path.chmod(0o600)
        records.append(
            {
                "observation_id": observation_id,
                "selection_role": ("adjudicated" if observation_id in adjudicated_ids else "decoy"),
                "observation_hash": sha256_json(observation.to_dict()),
                "record_byte_sha256": _sha256_bytes(raw),
            }
        )
    return records


def _private_artifact(
    *,
    snapshot: Mapping[str, Any],
    snapshot_byte_sha256: str,
    bundle_artifact: Mapping[str, Any],
    bundle_byte_sha256: str,
    retrieval_report: Mapping[str, Any],
    retrieval_report_byte_sha256: str,
    manifest: Mapping[str, Any],
    manifest_byte_sha256: str,
    adjudicated_ids: Sequence[str],
    decoy_ids: Sequence[str],
    eligible_decoy_count: int,
    records: list[dict[str, str]],
    record_inventory_fingerprint: str,
    selection_proof_fingerprint: str,
) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "artifact_id": PRIVATE_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": ("development_observation_materialization_quality_not_run"),
        "created_at": snapshot["created_at"],
        "retrieval_snapshot_byte_sha256": snapshot_byte_sha256,
        "bundle_artifact_byte_sha256": bundle_byte_sha256,
        "retrieval_report_byte_sha256": retrieval_report_byte_sha256,
        "development_manifest_byte_sha256": manifest_byte_sha256,
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "tokenizer_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
        "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
        "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "retrieval_report_fingerprint": retrieval_report["report_fingerprint"],
        "development_manifest_fingerprint": manifest["manifest_fingerprint"],
        "corpus_policy_id": CORPUS_POLICY_ID,
        "corpus_policy_fingerprint": CORPUS_POLICY_FINGERPRINT,
        "adjudicated_observation_ids": list(adjudicated_ids),
        "decoy_observation_ids": list(decoy_ids),
        "selected_observation_id_set_fingerprint": sha256_json(
            sorted([*adjudicated_ids, *decoy_ids])
        ),
        "selected_observation_hash_set_fingerprint": sha256_json(
            sorted(record["observation_hash"] for record in records)
        ),
        "record_byte_sha256_set_fingerprint": sha256_json(
            sorted(record["record_byte_sha256"] for record in records)
        ),
        "record_inventory_fingerprint": record_inventory_fingerprint,
        "selection_proof_fingerprint": selection_proof_fingerprint,
        "records": records,
        "counts": {
            "manifest_case_count": EXPECTED_CASE_COUNT,
            "adjudicated_observation_count": (EXPECTED_ADJUDICATED_OBSERVATION_COUNT),
            "decoy_observation_count": EXPECTED_DECOY_OBSERVATION_COUNT,
            "materialized_observation_count": (EXPECTED_MATERIALIZED_OBSERVATION_COUNT),
            "eligible_decoy_observation_count": eligible_decoy_count,
            "selection_collision_count": 0,
            "overflow_count": 0,
            "blocker_count": 0,
        },
    }
    artifact["artifact_fingerprint"] = _payload_fingerprint(
        artifact,
        "artifact_fingerprint",
    )
    return artifact


def _safe_report(
    *,
    snapshot: Mapping[str, Any],
    bundle_artifact: Mapping[str, Any],
    retrieval_report: Mapping[str, Any],
    manifest: Mapping[str, Any],
    private_artifact: Mapping[str, Any],
    private_artifact_bytes: bytes,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "artifact_id": SAFE_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": "materialization_only_no_quality_claim",
        "quality_evaluation_status": "not_run",
        "methodology_readiness_status": "blocked",
        "owner_contract_status": "passed",
        "source_lineage_status": "passed",
        "permission_lineage_status": "passed",
        "candidate_admission_profile_status": "passed",
        "atomic_write_status": "passed",
        "selection_status": "passed",
        "corpus_policy_fingerprint": CORPUS_POLICY_FINGERPRINT,
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "candidate_admission_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
        "retrieval_report_fingerprint": retrieval_report["report_fingerprint"],
        "development_manifest_fingerprint": manifest["manifest_fingerprint"],
        "materialization_artifact_fingerprint": private_artifact["artifact_fingerprint"],
        "materialization_artifact_byte_sha256": _sha256_bytes(private_artifact_bytes),
        "selected_observation_id_set_fingerprint": private_artifact[
            "selected_observation_id_set_fingerprint"
        ],
        "selected_observation_hash_set_fingerprint": private_artifact[
            "selected_observation_hash_set_fingerprint"
        ],
        "record_byte_sha256_set_fingerprint": private_artifact[
            "record_byte_sha256_set_fingerprint"
        ],
        "record_inventory_fingerprint": private_artifact["record_inventory_fingerprint"],
        "selection_proof_fingerprint": private_artifact["selection_proof_fingerprint"],
        "counts": dict(private_artifact["counts"]),
        "blocker_ids": [],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    assert_no_public_raw_references(
        report,
        "issue56_development_uat_observation_materialization_safe_report",
    )
    return report


def _blocked_report(reason_code: str) -> dict[str, Any]:
    blocker_id = (
        reason_code
        if isinstance(reason_code, str) and re.fullmatch(r"[a-z0-9_]+", reason_code)
        else "development_observation_materialization_failed"
    )
    report: dict[str, Any] = {
        "artifact_id": SAFE_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "claim_boundary_status": "materialization_only_no_quality_claim",
        "quality_evaluation_status": "not_run",
        "methodology_readiness_status": "blocked",
        "counts": {
            "materialized_observation_count": 0,
            "blocker_count": 1,
        },
        "blocker_ids": [blocker_id],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    assert_no_public_raw_references(
        report,
        "issue56_development_uat_observation_materialization_blocked_report",
    )
    return report


def _read_sealed_json(
    path: Path,
    *,
    expected_sha256: str,
    maximum_bytes: int,
    reason_prefix: str,
) -> tuple[bytes, dict[str, Any]]:
    _require_sha256(expected_sha256, f"{reason_prefix}_expected_sha256")
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise OSError
        raw = path.read_bytes()
    except OSError as exc:
        raise DevelopmentObservationMaterializationError(f"{reason_prefix}_unavailable") from exc
    if _sha256_bytes(raw) != expected_sha256:
        raise DevelopmentObservationMaterializationError(f"{reason_prefix}_byte_seal_mismatch")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DevelopmentObservationMaterializationError(f"{reason_prefix}_json_invalid") from exc
    if not isinstance(payload, dict):
        raise DevelopmentObservationMaterializationError(f"{reason_prefix}_json_invalid")
    return raw, payload


def _validated_new_work_dir(work_dir: Path) -> Path:
    resolved = work_dir.absolute()
    if resolved.exists() or resolved.is_symlink():
        raise DevelopmentObservationMaterializationError("immutable_work_dir_already_exists")
    parent = resolved.parent
    try:
        metadata = parent.lstat()
    except OSError as exc:
        raise DevelopmentObservationMaterializationError("work_dir_parent_unavailable") from exc
    if parent.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise DevelopmentObservationMaterializationError("work_dir_parent_invalid")
    if resolved.name in {"", ".", ".."}:
        raise DevelopmentObservationMaterializationError("work_dir_name_invalid")
    return resolved


def _create_staging_directory(work_dir: Path) -> Path:
    try:
        return Path(
            tempfile.mkdtemp(
                prefix=f".{work_dir.name}.staging-",
                dir=work_dir.parent,
            )
        )
    except OSError as exc:
        raise DevelopmentObservationMaterializationError(
            "materialization_staging_unavailable"
        ) from exc


def _write_staged_file(path: Path, payload: bytes, *, mode: int) -> None:
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
        raise DevelopmentObservationMaterializationError(
            "staged_materialization_write_failed"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise DevelopmentObservationMaterializationError("atomic_no_replace_unavailable")
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
        raise DevelopmentObservationMaterializationError("immutable_work_dir_already_exists")
    raise DevelopmentObservationMaterializationError("atomic_no_replace_failed")


def _fsync_tree(root: Path) -> None:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        _fsync_directory(directory)
    _fsync_directory(root)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validated_observation_id_list(
    value: Any,
    *,
    reason_code: str,
    expected_count: int,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) != expected_count:
        raise DevelopmentObservationMaterializationError(reason_code)
    validated = tuple(_safe_observation_id(item) for item in value)
    if len(set(validated)) != len(validated):
        raise DevelopmentObservationMaterializationError(reason_code)
    return validated


def _safe_observation_id(value: Any) -> str:
    if not isinstance(value, str) or not value or _SAFE_RECORD_ID_RE.fullmatch(value) is None:
        raise DevelopmentObservationMaterializationError("observation_id_not_owner_store_safe")
    return value


def _observation_occurrence_id(observation: Observation) -> str | None:
    for source in (observation.location, observation.payload or {}):
        value = source.get("message_occurrence_id")
        if isinstance(value, str) and value:
            return value
    return None


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _payload_fingerprint(
    payload: Mapping[str, Any],
    fingerprint_field: str,
) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != fingerprint_field})


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise DevelopmentObservationMaterializationError(f"{field_name}_invalid")
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


if __name__ == "__main__":
    raise SystemExit(main())
