#!/usr/bin/env python3
"""Build an immutable Issue #56 source-bound identifier candidate artifact.

The builder consumes a sealed retrieval-ready snapshot and its safe
source-completeness report.  It may additionally bind to the canonical
materialized development Observation subset, in which case only the sealed
owner-store records in that subset are admitted.  It emits candidate-only
mention and exact-resolution records.  It never reads UAT/holdout answers and
never writes canonical graph state.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from datetime import datetime
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
from formowl_graph.resolution import (  # noqa: E402
    resolve_exact_protected_identifier_candidates,
)
from formowl_mail.candidates import (  # noqa: E402
    IdentifierOccurrenceOverflowError,
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
    SourceIdentifierIdentityScope,
    extract_source_bound_identifier_mentions,
)
from scripts.issue56_identity_scope_attestation import (  # noqa: E402
    POLICY_FINGERPRINT as IDENTITY_SCOPE_POLICY_FINGERPRINT,
    SPEC_OPERATOR_APPROVAL_KIND,
    TENANT_WORKSPACE_MODE,
    WORKSPACE_ONLY_MODE,
    IdentityScopeAttestationError,
    load_identity_scope_attestation,
)


SCHEMA_VERSION = 1
CANDIDATE_ARTIFACT_SCHEMA_VERSION = 3
PRIVATE_ARTIFACT_ID = "formowl_issue56_source_identifier_candidates_private_v3"
SAFE_REPORT_ARTIFACT_ID = "formowl_issue56_source_identifier_candidates_safe_report_v3"
ERROR_ARTIFACT_ID = "formowl_issue56_source_identifier_candidates_rejection_v1"
RETRIEVAL_SNAPSHOT_ARTIFACT_ID = (
    "formowl_issue56_native_source_complete_retrieval_ready_snapshot_v1"
)
RETRIEVAL_REPORT_ARTIFACT_ID = "formowl_issue56_native_source_complete_retrieval_ready_report_v1"
PRIVATE_ARTIFACT_FILENAME = "source-identifier-candidates.private.json"
SAFE_REPORT_FILENAME = "source-identifier-candidates.safe.json"
FULL_SOURCE_SELECTION_MODE = "retrieval_snapshot_all_observations_v1"
MATERIALIZED_SELECTION_MODE = "development_materialized_observation_subset_v1"
RESOLUTION_POLICY_ID = "exact_source_bound_protected_identifier_candidate_resolution_v2"
RESOLUTION_POLICY_FINGERPRINT = sha256_json(
    {
        "policy_id": RESOLUTION_POLICY_ID,
        "algorithm": "exact_protected_token_hash_v1",
        "identity_fields": [
            "exact_protected_token_hash",
            "identity_scope_mode",
            "identity_scope_fingerprint",
            "workspace_id",
            "identity_scope_attestation_fingerprint",
            "identity_scope_policy_fingerprint",
            "operator_approval_fingerprint",
            "mode_specific_tenant_or_spec_approval_fingerprint",
            "permission_boundary_fingerprint",
            "tokenizer_profile_fingerprint",
            "extraction_policy_fingerprint",
        ],
        "occurrence_scope_preserved": True,
        "fuzzy_matching_allowed": False,
        "canonical_merge_performed": False,
        "canonical_write_allowed": False,
    }
)

_MAX_INPUT_BYTES = 1024 * 1024 * 1024
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_CANDIDATE_OBSERVATION_TYPES = frozenset(
    {
        "email_message",
        "email_header",
        "email_body_segment",
    }
)
_ZERO_COUNT_FIELDS = (
    "missing_source_inventory_binding_count",
    "missing_source_local_key_binding_count",
    "missing_content_hash_binding_count",
    "missing_permission_binding_count",
    "unexplained_loss_count",
    "blocker_count",
)
_SAFE_REPORT_KEYS = frozenset(
    {
        "artifact_id",
        "schema_version",
        "status",
        "source_completeness_status",
        "candidate_artifact_status",
        "candidate_only_status",
        "canonical_write_status",
        "overflow_status",
        "tokenizer_profile_status",
        "permission_scope_status",
        "observation_selection_status",
        "observation_selection_binding_fingerprint",
        "retrieval_snapshot_byte_sha256",
        "retrieval_report_byte_sha256",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_observation_hash_set_fingerprint",
        "message_occurrence_hash_set_fingerprint",
        "tokenizer_profile_fingerprint",
        "extraction_policy_fingerprint",
        "resolution_policy_fingerprint",
        "identity_scope_fingerprint",
        "identity_scope_attestation_byte_sha256",
        "identity_scope_attestation_fingerprint",
        "identity_scope_policy_fingerprint",
        "identity_scope_binding_fingerprint",
        "operator_approval_fingerprint",
        "spec_approval_status",
        "attested_asset_fingerprint",
        "identity_scope_mode_status",
        "mention_batch_fingerprint",
        "resolution_fingerprint",
        "private_artifact_fingerprint",
        "private_artifact_byte_sha256",
        "counts",
        "report_fingerprint",
    }
)
_SAFE_COUNT_KEYS = frozenset(
    {
        "source_observation_count",
        "candidate_source_observation_count",
        "message_occurrence_count",
        "identifier_occurrence_count",
        "resolved_candidate_count",
        "permission_boundary_count",
        "overflow_count",
    }
)
_PRIVATE_ARTIFACT_KEYS = frozenset(
    {
        "artifact_id",
        "schema_version",
        "status",
        "claim_boundary_status",
        "created_at",
        "candidate_only",
        "canonical_write_allowed",
        "overflow_count",
        "retrieval_snapshot_byte_sha256",
        "retrieval_report_byte_sha256",
        "retrieval_snapshot_fingerprint",
        "retrieval_report_fingerprint",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_observation_hashes",
        "source_observation_hash_set_fingerprint",
        "message_occurrence_fingerprints",
        "message_occurrence_hash_set_fingerprint",
        "tokenizer_id",
        "tokenizer_profile_fingerprint",
        "extraction_policy_id",
        "extraction_policy_fingerprint",
        "resolution_policy_id",
        "resolution_policy_fingerprint",
        "identity_scope_mode",
        "identity_scope_attestation_byte_sha256",
        "identity_scope_attestation_fingerprint",
        "identity_scope_policy_fingerprint",
        "attested_asset_fingerprint",
        "identity_scope_binding",
        "observation_selection_binding",
        "observation_selection_binding_fingerprint",
        "extractor_run_id",
        "mention_batch",
        "resolution",
        "counts",
        "artifact_fingerprint",
    }
)
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class SourceIdentifierCandidateError(RuntimeError):
    """Fail-closed error carrying one stable, public-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class SourceIdentifierCandidateArtifacts:
    output_root: Path
    private_artifact_path: Path
    safe_report_path: Path
    private_artifact: dict[str, Any]
    safe_report: dict[str, Any]


def build_source_identifier_candidate_artifacts(
    *,
    retrieval_snapshot_path: Path,
    expected_retrieval_snapshot_sha256: str,
    retrieval_report_path: Path,
    expected_retrieval_report_sha256: str,
    identity_scope_attestation_path: Path,
    expected_identity_scope_attestation_sha256: str,
    output_root: Path,
    materialized_work_dir: Path | None = None,
    expected_materialization_artifact_sha256: str | None = None,
    expected_materialization_safe_report_sha256: str | None = None,
    max_identifier_occurrences: int | None = None,
    _write_staged_file: Callable[[Path, bytes], None] | None = None,
) -> SourceIdentifierCandidateArtifacts:
    """Extract, resolve, validate, and atomically persist one immutable batch."""

    if output_root.exists() or output_root.is_symlink():
        raise SourceIdentifierCandidateError("immutable_output_already_exists")
    try:
        identity_attestation = load_identity_scope_attestation(
            identity_scope_attestation_path,
            expected_sha256=expected_identity_scope_attestation_sha256,
        )
    except IdentityScopeAttestationError as exc:
        raise SourceIdentifierCandidateError(exc.reason_code) from exc

    snapshot_bytes, snapshot = _read_sealed_json(
        retrieval_snapshot_path,
        expected_sha256=expected_retrieval_snapshot_sha256,
        reason_prefix="retrieval_snapshot",
    )
    report_bytes, report = _read_sealed_json(
        retrieval_report_path,
        expected_sha256=expected_retrieval_report_sha256,
        reason_prefix="retrieval_report",
    )
    observations, inventory = _validate_retrieval_inputs(snapshot, report)
    observations, observation_selection_binding = _select_source_observations(
        observations=observations,
        snapshot=snapshot,
        snapshot_byte_sha256=_sha256_bytes(snapshot_bytes),
        report=report,
        report_byte_sha256=_sha256_bytes(report_bytes),
        materialized_work_dir=materialized_work_dir,
        expected_materialization_artifact_sha256=(expected_materialization_artifact_sha256),
        expected_materialization_safe_report_sha256=(expected_materialization_safe_report_sha256),
    )
    observation_selection_binding_fingerprint = sha256_json(observation_selection_binding)
    identity_scope, attested_asset_fingerprint = _validate_identity_scope_attestation_binding(
        identity_attestation,
        snapshot=snapshot,
        inventory=inventory,
    )
    profile = load_issue56_target_mail_tokenizer_profile()
    if (
        profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
        or profile.profile_fingerprint != ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
        or snapshot["tokenizer_profile_fingerprint"] != profile.profile_fingerprint
        or report["candidate_admission_profile_fingerprint"] != profile.profile_fingerprint
    ):
        raise SourceIdentifierCandidateError("target_tokenizer_profile_drift")

    frozen_created_at = _validate_timestamp(snapshot.get("created_at"), "source_created_at")
    candidate_observations = tuple(
        observation
        for observation in observations
        if observation.observation_type in _CANDIDATE_OBSERVATION_TYPES
        and isinstance(observation.text, str)
        and observation.text
    )
    source_observation_hashes = tuple(
        sorted(sha256_json(observation.to_dict()) for observation in observations)
    )
    message_occurrence_fingerprints = tuple(
        sorted(
            {
                sha256_json(_message_occurrence_id(observation))
                for observation in candidate_observations
            }
        )
    )
    extractor_run_id = _derived_extractor_run_id(
        source_snapshot_fingerprint=str(snapshot["snapshot_fingerprint"]),
        identity_scope_binding_fingerprint=sha256_json(identity_scope.to_dict()),
    )
    try:
        mention_batch = extract_source_bound_identifier_mentions(
            candidate_observations,
            identity_scope=identity_scope,
            extractor_run_id=extractor_run_id,
            tokenizer_profile=profile,
            created_at=frozen_created_at,
            max_identifier_occurrences=max_identifier_occurrences,
        )
    except IdentifierOccurrenceOverflowError as exc:
        raise SourceIdentifierCandidateError(exc.blocker_id) from exc
    except ContractValidationError as exc:
        raise SourceIdentifierCandidateError("identifier_mention_extraction_invalid") from exc

    resolution = resolve_exact_protected_identifier_candidates(mention_batch.candidate_mentions)
    if resolution.resolution_policy_id != RESOLUTION_POLICY_ID:
        raise SourceIdentifierCandidateError("identifier_resolution_policy_drift")
    permission_boundary_count = len(
        {
            mention.metadata["permission_boundary_fingerprint"]
            for mention in mention_batch.candidate_mentions
        }
    )
    private_artifact: dict[str, Any] = {
        "artifact_id": PRIVATE_ARTIFACT_ID,
        "schema_version": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": "candidate_only_not_canonical_fact",
        "created_at": frozen_created_at,
        "candidate_only": True,
        "canonical_write_allowed": False,
        "overflow_count": 0,
        "retrieval_snapshot_byte_sha256": _sha256_bytes(snapshot_bytes),
        "retrieval_report_byte_sha256": _sha256_bytes(report_bytes),
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "retrieval_report_fingerprint": report["report_fingerprint"],
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_observation_hashes": list(source_observation_hashes),
        "source_observation_hash_set_fingerprint": sha256_json(list(source_observation_hashes)),
        "message_occurrence_fingerprints": list(message_occurrence_fingerprints),
        "message_occurrence_hash_set_fingerprint": sha256_json(
            list(message_occurrence_fingerprints)
        ),
        "tokenizer_id": profile.tokenizer_id,
        "tokenizer_profile_fingerprint": profile.profile_fingerprint,
        "extraction_policy_id": SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
        "extraction_policy_fingerprint": (SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT),
        "resolution_policy_id": RESOLUTION_POLICY_ID,
        "resolution_policy_fingerprint": RESOLUTION_POLICY_FINGERPRINT,
        "identity_scope_mode": identity_scope.identity_scope_mode,
        "identity_scope_attestation_byte_sha256": (expected_identity_scope_attestation_sha256),
        "identity_scope_attestation_fingerprint": identity_attestation["attestation_fingerprint"],
        "identity_scope_policy_fingerprint": identity_attestation["policy_fingerprint"],
        "attested_asset_fingerprint": attested_asset_fingerprint,
        "identity_scope_binding": identity_scope.to_dict(),
        "observation_selection_binding": observation_selection_binding,
        "observation_selection_binding_fingerprint": (observation_selection_binding_fingerprint),
        "extractor_run_id": extractor_run_id,
        "mention_batch": mention_batch.to_dict(),
        "resolution": resolution.to_dict(),
        "counts": {
            "source_inventory_item_count": len(inventory.items),
            "source_observation_count": len(observations),
            "candidate_source_observation_count": len(candidate_observations),
            "message_occurrence_count": len(message_occurrence_fingerprints),
            "identifier_occurrence_count": mention_batch.occurrence_count,
            "resolved_candidate_count": resolution.candidate_count,
            "permission_boundary_count": permission_boundary_count,
            "overflow_count": 0,
        },
    }
    private_artifact["artifact_fingerprint"] = _payload_fingerprint(
        private_artifact,
        "artifact_fingerprint",
    )
    validate_private_identifier_candidate_artifact(private_artifact)
    private_bytes = _canonical_json_bytes(private_artifact)

    safe_report: dict[str, Any] = {
        "artifact_id": SAFE_REPORT_ARTIFACT_ID,
        "schema_version": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "status": "passed",
        "source_completeness_status": "passed",
        "candidate_artifact_status": "passed",
        "candidate_only_status": "passed",
        "canonical_write_status": "disabled",
        "overflow_status": "passed_zero",
        "tokenizer_profile_status": "passed_frozen_target",
        "permission_scope_status": "passed_bound",
        "observation_selection_status": observation_selection_binding["mode"],
        "observation_selection_binding_fingerprint": (observation_selection_binding_fingerprint),
        "retrieval_snapshot_byte_sha256": _sha256_bytes(snapshot_bytes),
        "retrieval_report_byte_sha256": _sha256_bytes(report_bytes),
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_observation_hash_set_fingerprint": private_artifact[
            "source_observation_hash_set_fingerprint"
        ],
        "message_occurrence_hash_set_fingerprint": private_artifact[
            "message_occurrence_hash_set_fingerprint"
        ],
        "tokenizer_profile_fingerprint": profile.profile_fingerprint,
        "extraction_policy_fingerprint": (SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT),
        "resolution_policy_fingerprint": RESOLUTION_POLICY_FINGERPRINT,
        "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
        "identity_scope_attestation_byte_sha256": (expected_identity_scope_attestation_sha256),
        "identity_scope_attestation_fingerprint": identity_attestation["attestation_fingerprint"],
        "identity_scope_policy_fingerprint": identity_attestation["policy_fingerprint"],
        "identity_scope_binding_fingerprint": sha256_json(identity_scope.to_dict()),
        "operator_approval_fingerprint": identity_scope.operator_approval_fingerprint,
        "spec_approval_status": (
            "passed_bound"
            if identity_scope.identity_scope_mode == WORKSPACE_ONLY_MODE
            else "not_required_for_mode"
        ),
        "attested_asset_fingerprint": attested_asset_fingerprint,
        "identity_scope_mode_status": identity_scope.identity_scope_mode,
        "mention_batch_fingerprint": mention_batch.batch_fingerprint,
        "resolution_fingerprint": resolution.resolution_fingerprint,
        "private_artifact_fingerprint": private_artifact["artifact_fingerprint"],
        "private_artifact_byte_sha256": _sha256_bytes(private_bytes),
        "counts": {key: private_artifact["counts"][key] for key in sorted(_SAFE_COUNT_KEYS)},
    }
    safe_report["report_fingerprint"] = _payload_fingerprint(
        safe_report,
        "report_fingerprint",
    )
    validate_safe_identifier_candidate_report(
        safe_report,
        private_artifact_bytes=private_bytes,
    )
    safe_bytes = _canonical_json_bytes(safe_report)
    _persist_atomic_artifact_directory(
        output_root=output_root,
        files={
            PRIVATE_ARTIFACT_FILENAME: private_bytes,
            SAFE_REPORT_FILENAME: safe_bytes,
        },
        write_staged_file=_write_staged_file or _write_file_exclusive,
    )

    persisted_private = _read_json_file(
        output_root / PRIVATE_ARTIFACT_FILENAME,
        maximum_bytes=_MAX_INPUT_BYTES,
        reason_code="private_artifact_round_trip_failed",
    )
    persisted_safe = _read_json_file(
        output_root / SAFE_REPORT_FILENAME,
        maximum_bytes=1024 * 1024,
        reason_code="safe_report_round_trip_failed",
    )
    validate_private_identifier_candidate_artifact(persisted_private)
    validate_safe_identifier_candidate_report(
        persisted_safe,
        private_artifact_bytes=(output_root / PRIVATE_ARTIFACT_FILENAME).read_bytes(),
    )
    if persisted_private != private_artifact or persisted_safe != safe_report:
        raise SourceIdentifierCandidateError("immutable_artifact_round_trip_failed")
    return SourceIdentifierCandidateArtifacts(
        output_root=output_root,
        private_artifact_path=output_root / PRIVATE_ARTIFACT_FILENAME,
        safe_report_path=output_root / SAFE_REPORT_FILENAME,
        private_artifact=persisted_private,
        safe_report=persisted_safe,
    )


def validate_private_identifier_candidate_artifact(
    artifact: Mapping[str, Any],
) -> None:
    """Validate a persisted private candidate artifact and deterministic replay."""

    if set(artifact) != _PRIVATE_ARTIFACT_KEYS:
        raise SourceIdentifierCandidateError("private_artifact_fields_invalid")
    if artifact.get("artifact_id") != PRIVATE_ARTIFACT_ID:
        raise SourceIdentifierCandidateError("private_artifact_id_invalid")
    if (
        artifact.get("schema_version") != CANDIDATE_ARTIFACT_SCHEMA_VERSION
        or artifact.get("status") != "passed"
    ):
        raise SourceIdentifierCandidateError("private_artifact_status_invalid")
    if (
        artifact.get("claim_boundary_status") != "candidate_only_not_canonical_fact"
        or artifact.get("candidate_only") is not True
        or artifact.get("canonical_write_allowed") is not False
        or artifact.get("overflow_count") != 0
    ):
        raise SourceIdentifierCandidateError("private_artifact_claim_boundary_invalid")
    if artifact.get("artifact_fingerprint") != _payload_fingerprint(
        artifact,
        "artifact_fingerprint",
    ):
        raise SourceIdentifierCandidateError("private_artifact_fingerprint_invalid")
    for field in (
        "retrieval_snapshot_byte_sha256",
        "retrieval_report_byte_sha256",
        "retrieval_snapshot_fingerprint",
        "retrieval_report_fingerprint",
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_observation_hash_set_fingerprint",
        "message_occurrence_hash_set_fingerprint",
        "tokenizer_profile_fingerprint",
        "extraction_policy_fingerprint",
        "resolution_policy_fingerprint",
        "identity_scope_attestation_byte_sha256",
        "identity_scope_attestation_fingerprint",
        "identity_scope_policy_fingerprint",
        "attested_asset_fingerprint",
        "observation_selection_binding_fingerprint",
        "artifact_fingerprint",
    ):
        _require_sha256(artifact.get(field), f"private_{field}_invalid")
    if (
        artifact.get("tokenizer_id") != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
        or artifact.get("tokenizer_profile_fingerprint")
        != ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
        or artifact.get("extraction_policy_id") != SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID
        or artifact.get("extraction_policy_fingerprint")
        != SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
        or artifact.get("resolution_policy_id") != RESOLUTION_POLICY_ID
        or artifact.get("resolution_policy_fingerprint") != RESOLUTION_POLICY_FINGERPRINT
        or artifact.get("identity_scope_mode") not in {TENANT_WORKSPACE_MODE, WORKSPACE_ONLY_MODE}
        or artifact.get("identity_scope_policy_fingerprint") != IDENTITY_SCOPE_POLICY_FINGERPRINT
    ):
        raise SourceIdentifierCandidateError("private_artifact_policy_binding_invalid")
    _validate_timestamp(artifact.get("created_at"), "private_created_at")
    selection_binding = artifact.get("observation_selection_binding")
    if not isinstance(selection_binding, Mapping):
        raise SourceIdentifierCandidateError(
            "private_artifact_observation_selection_binding_invalid"
        )
    _validate_observation_selection_binding(selection_binding)
    if artifact.get("observation_selection_binding_fingerprint") != sha256_json(
        dict(selection_binding)
    ):
        raise SourceIdentifierCandidateError("private_artifact_observation_selection_binding_drift")

    source_hashes = artifact.get("source_observation_hashes")
    occurrence_hashes = artifact.get("message_occurrence_fingerprints")
    if (
        not isinstance(source_hashes, list)
        or source_hashes != sorted(source_hashes)
        or len(source_hashes) != len(set(source_hashes))
        or not isinstance(occurrence_hashes, list)
        or occurrence_hashes != sorted(occurrence_hashes)
        or len(occurrence_hashes) != len(set(occurrence_hashes))
    ):
        raise SourceIdentifierCandidateError("private_artifact_source_hash_set_invalid")
    for value in [*source_hashes, *occurrence_hashes]:
        _require_sha256(value, "private_artifact_source_hash_invalid")
    if artifact["source_observation_hash_set_fingerprint"] != sha256_json(
        source_hashes
    ) or artifact["message_occurrence_hash_set_fingerprint"] != sha256_json(occurrence_hashes):
        raise SourceIdentifierCandidateError("private_artifact_source_hash_set_drift")

    identity_binding = artifact.get("identity_scope_binding")
    if not isinstance(identity_binding, Mapping):
        raise SourceIdentifierCandidateError("private_artifact_identity_scope_binding_invalid")
    try:
        identity_scope = SourceIdentifierIdentityScope(**dict(identity_binding))
    except (ContractValidationError, TypeError) as exc:
        raise SourceIdentifierCandidateError(
            "private_artifact_identity_scope_binding_invalid"
        ) from exc
    if (
        identity_scope.identity_scope_mode != artifact["identity_scope_mode"]
        or identity_scope.identity_scope_attestation_fingerprint
        != artifact["identity_scope_attestation_fingerprint"]
        or identity_scope.identity_scope_policy_fingerprint
        != artifact["identity_scope_policy_fingerprint"]
    ):
        raise SourceIdentifierCandidateError("private_artifact_identity_scope_binding_drift")

    batch = artifact.get("mention_batch")
    if not isinstance(batch, Mapping):
        raise SourceIdentifierCandidateError("private_artifact_mention_batch_invalid")
    raw_mentions = batch.get("candidate_mentions")
    if not isinstance(raw_mentions, list):
        raise SourceIdentifierCandidateError("private_artifact_mention_batch_invalid")
    try:
        mentions = tuple(CandidateMention.from_dict(row) for row in raw_mentions)
        replayed_resolution = resolve_exact_protected_identifier_candidates(mentions)
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise SourceIdentifierCandidateError("private_artifact_candidate_replay_invalid") from exc
    if (
        batch.get("tokenizer_id") != artifact["tokenizer_id"]
        or batch.get("tokenizer_profile_fingerprint") != artifact["tokenizer_profile_fingerprint"]
        or batch.get("extraction_policy_id") != artifact["extraction_policy_id"]
        or batch.get("extraction_policy_fingerprint") != artifact["extraction_policy_fingerprint"]
        or batch.get("identity_scope_mode") != identity_scope.identity_scope_mode
        or batch.get("identity_scope_fingerprint") != identity_scope.identity_scope_fingerprint
        or batch.get("workspace_id") != identity_scope.workspace_id
        or batch.get("identity_scope_attestation_fingerprint")
        != identity_scope.identity_scope_attestation_fingerprint
        or batch.get("identity_scope_policy_fingerprint")
        != identity_scope.identity_scope_policy_fingerprint
        or batch.get("operator_approval_fingerprint")
        != identity_scope.operator_approval_fingerprint
        or batch.get("occurrence_count") != len(mentions)
    ):
        raise SourceIdentifierCandidateError("private_artifact_mention_batch_binding_drift")
    if identity_scope.identity_scope_mode == TENANT_WORKSPACE_MODE:
        if (
            batch.get("tenant_id") != identity_scope.tenant_id
            or "spec_approval_fingerprint" in batch
        ):
            raise SourceIdentifierCandidateError("private_artifact_mention_batch_binding_drift")
    elif (
        "tenant_id" in batch
        or batch.get("spec_approval_fingerprint") != identity_scope.spec_approval_fingerprint
    ):
        raise SourceIdentifierCandidateError("private_artifact_mention_batch_binding_drift")
    expected_batch_fingerprint = sha256_json(
        {
            "candidate_mention_ids": [
                mention.candidate_mention_id
                for mention in sorted(
                    mentions,
                    key=lambda item: item.candidate_mention_id,
                )
            ],
            "extraction_policy_fingerprint": artifact["extraction_policy_fingerprint"],
            "identity_scope": identity_scope.to_dict(),
            "tokenizer_profile_fingerprint": artifact["tokenizer_profile_fingerprint"],
        }
    )
    if batch.get("batch_fingerprint") != expected_batch_fingerprint:
        raise SourceIdentifierCandidateError("private_artifact_mention_batch_fingerprint_drift")
    for mention in mentions:
        metadata = mention.metadata
        if (
            mention.created_at != artifact["created_at"]
            or metadata.get("source_observation_fingerprint") not in source_hashes
            or metadata.get("message_occurrence_fingerprint") not in occurrence_hashes
            or metadata.get("identity_scope_mode") != identity_scope.identity_scope_mode
            or metadata.get("identity_scope_fingerprint")
            != identity_scope.identity_scope_fingerprint
            or metadata.get("workspace_id") != identity_scope.workspace_id
            or metadata.get("identity_scope_attestation_fingerprint")
            != identity_scope.identity_scope_attestation_fingerprint
            or metadata.get("identity_scope_policy_fingerprint")
            != identity_scope.identity_scope_policy_fingerprint
            or metadata.get("operator_approval_fingerprint")
            != identity_scope.operator_approval_fingerprint
        ):
            raise SourceIdentifierCandidateError("private_artifact_occurrence_binding_drift")
        if identity_scope.identity_scope_mode == TENANT_WORKSPACE_MODE:
            if (
                metadata.get("tenant_id") != identity_scope.tenant_id
                or "spec_approval_fingerprint" in metadata
            ):
                raise SourceIdentifierCandidateError("private_artifact_occurrence_binding_drift")
        elif (
            "tenant_id" in metadata
            or metadata.get("spec_approval_fingerprint") != identity_scope.spec_approval_fingerprint
        ):
            raise SourceIdentifierCandidateError("private_artifact_occurrence_binding_drift")
    if artifact.get("resolution") != replayed_resolution.to_dict():
        raise SourceIdentifierCandidateError("private_artifact_resolution_replay_drift")

    counts = artifact.get("counts")
    if not isinstance(counts, Mapping):
        raise SourceIdentifierCandidateError("private_artifact_counts_invalid")
    if (
        counts.get("source_observation_count") != len(source_hashes)
        or counts.get("message_occurrence_count") != len(occurrence_hashes)
        or counts.get("identifier_occurrence_count") != len(mentions)
        or counts.get("resolved_candidate_count") != replayed_resolution.candidate_count
        or counts.get("overflow_count") != 0
    ):
        raise SourceIdentifierCandidateError("private_artifact_count_drift")


def validate_safe_identifier_candidate_report(
    report: Mapping[str, Any],
    *,
    private_artifact_bytes: bytes | None = None,
) -> None:
    """Validate that the public projection is hash/count/status-only."""

    if set(report) != _SAFE_REPORT_KEYS:
        raise SourceIdentifierCandidateError("safe_report_fields_invalid")
    if (
        report.get("artifact_id") != SAFE_REPORT_ARTIFACT_ID
        or report.get("schema_version") != CANDIDATE_ARTIFACT_SCHEMA_VERSION
        or report.get("status") != "passed"
        or report.get("source_completeness_status") != "passed"
        or report.get("candidate_artifact_status") != "passed"
        or report.get("candidate_only_status") != "passed"
        or report.get("canonical_write_status") != "disabled"
        or report.get("overflow_status") != "passed_zero"
        or report.get("tokenizer_profile_status") != "passed_frozen_target"
        or report.get("permission_scope_status") != "passed_bound"
        or report.get("observation_selection_status")
        not in {FULL_SOURCE_SELECTION_MODE, MATERIALIZED_SELECTION_MODE}
        or report.get("identity_scope_mode_status")
        not in {TENANT_WORKSPACE_MODE, WORKSPACE_ONLY_MODE}
    ):
        raise SourceIdentifierCandidateError("safe_report_status_invalid")
    expected_spec_status = (
        "passed_bound"
        if report.get("identity_scope_mode_status") == WORKSPACE_ONLY_MODE
        else "not_required_for_mode"
    )
    if report.get("spec_approval_status") != expected_spec_status:
        raise SourceIdentifierCandidateError("safe_report_status_invalid")
    for key, value in report.items():
        if key.endswith("_fingerprint") or key.endswith("_sha256"):
            _require_sha256(value, "safe_report_fingerprint_invalid")
    counts = report.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != _SAFE_COUNT_KEYS:
        raise SourceIdentifierCandidateError("safe_report_counts_invalid")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in counts.values()
    ):
        raise SourceIdentifierCandidateError("safe_report_counts_invalid")
    if counts.get("overflow_count") != 0:
        raise SourceIdentifierCandidateError("safe_report_overflow_nonzero")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise SourceIdentifierCandidateError("safe_report_fingerprint_invalid")
    if private_artifact_bytes is not None and report.get(
        "private_artifact_byte_sha256"
    ) != _sha256_bytes(private_artifact_bytes):
        raise SourceIdentifierCandidateError("safe_report_private_byte_seal_mismatch")
    if private_artifact_bytes is not None:
        try:
            private_artifact = json.loads(
                private_artifact_bytes,
                object_pairs_hook=_unique_json_object,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise SourceIdentifierCandidateError("safe_report_private_artifact_invalid") from exc
        if type(private_artifact) is not dict:
            raise SourceIdentifierCandidateError("safe_report_private_artifact_invalid")
        validate_private_identifier_candidate_artifact(private_artifact)
        expected_bindings = {
            "retrieval_snapshot_byte_sha256": private_artifact["retrieval_snapshot_byte_sha256"],
            "retrieval_report_byte_sha256": private_artifact["retrieval_report_byte_sha256"],
            "source_snapshot_fingerprint": private_artifact["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": private_artifact["source_inventory_fingerprint"],
            "source_observation_hash_set_fingerprint": private_artifact[
                "source_observation_hash_set_fingerprint"
            ],
            "message_occurrence_hash_set_fingerprint": private_artifact[
                "message_occurrence_hash_set_fingerprint"
            ],
            "tokenizer_profile_fingerprint": private_artifact["tokenizer_profile_fingerprint"],
            "extraction_policy_fingerprint": private_artifact["extraction_policy_fingerprint"],
            "resolution_policy_fingerprint": private_artifact["resolution_policy_fingerprint"],
            "identity_scope_fingerprint": private_artifact["identity_scope_binding"][
                "identity_scope_fingerprint"
            ],
            "identity_scope_attestation_byte_sha256": private_artifact[
                "identity_scope_attestation_byte_sha256"
            ],
            "identity_scope_attestation_fingerprint": private_artifact[
                "identity_scope_attestation_fingerprint"
            ],
            "identity_scope_policy_fingerprint": private_artifact[
                "identity_scope_policy_fingerprint"
            ],
            "identity_scope_binding_fingerprint": sha256_json(
                private_artifact["identity_scope_binding"]
            ),
            "operator_approval_fingerprint": private_artifact["identity_scope_binding"][
                "operator_approval_fingerprint"
            ],
            "spec_approval_status": (
                "passed_bound"
                if private_artifact["identity_scope_mode"] == WORKSPACE_ONLY_MODE
                else "not_required_for_mode"
            ),
            "attested_asset_fingerprint": private_artifact["attested_asset_fingerprint"],
            "observation_selection_status": private_artifact["observation_selection_binding"][
                "mode"
            ],
            "observation_selection_binding_fingerprint": private_artifact[
                "observation_selection_binding_fingerprint"
            ],
            "mention_batch_fingerprint": private_artifact["mention_batch"]["batch_fingerprint"],
            "resolution_fingerprint": private_artifact["resolution"]["resolution_fingerprint"],
            "private_artifact_fingerprint": private_artifact["artifact_fingerprint"],
        }
        if any(report.get(key) != value for key, value in expected_bindings.items()):
            raise SourceIdentifierCandidateError("safe_report_private_binding_drift")
        if report.get("identity_scope_mode_status") != private_artifact["identity_scope_mode"]:
            raise SourceIdentifierCandidateError("safe_report_private_binding_drift")
        expected_counts = {key: private_artifact["counts"][key] for key in sorted(_SAFE_COUNT_KEYS)}
        if dict(counts) != expected_counts:
            raise SourceIdentifierCandidateError("safe_report_private_count_drift")
    try:
        assert_no_public_raw_references(
            list(report.values()),
            "source_identifier_candidate_safe_report_values",
        )
    except ContractValidationError as exc:
        raise SourceIdentifierCandidateError("safe_report_private_reference_exposed") from exc


def _validate_retrieval_inputs(
    snapshot: Mapping[str, Any],
    report: Mapping[str, Any],
) -> tuple[tuple[Observation, ...], SourceInventory]:
    if (
        snapshot.get("artifact_id") != RETRIEVAL_SNAPSHOT_ARTIFACT_ID
        or snapshot.get("schema_version") != SCHEMA_VERSION
        or snapshot.get("status") != "passed"
        or snapshot.get("claim_boundary_status") != "retrieval_ready_evidence_not_canonical_fact"
    ):
        raise SourceIdentifierCandidateError("retrieval_snapshot_contract_invalid")
    if snapshot.get("snapshot_fingerprint") != _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    ):
        raise SourceIdentifierCandidateError("retrieval_snapshot_fingerprint_invalid")
    if snapshot.get("blocker_fingerprints") != []:
        raise SourceIdentifierCandidateError("retrieval_snapshot_blocked")
    counts = snapshot.get("counts")
    if not isinstance(counts, Mapping) or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in counts.values()
    ):
        raise SourceIdentifierCandidateError("retrieval_snapshot_counts_invalid")
    if any(counts.get(field) != 0 for field in _ZERO_COUNT_FIELDS):
        raise SourceIdentifierCandidateError("retrieval_snapshot_source_completeness_blocked")
    try:
        inventory = SourceInventory.from_dict(snapshot["source_inventory"])
        observations = tuple(
            Observation.from_dict(row) for row in snapshot["parsed_mail_observations"]
        )
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise SourceIdentifierCandidateError("retrieval_snapshot_observations_invalid") from exc
    if (
        sha256_json(inventory.to_dict()) != snapshot.get("source_inventory_fingerprint")
        or sha256_json([item.to_dict() for item in observations])
        != snapshot.get("parsed_observation_fingerprint")
        or counts.get("source_inventory_item_count") != len(inventory.items)
        or counts.get("parsed_observation_count") != len(observations)
    ):
        raise SourceIdentifierCandidateError("retrieval_snapshot_source_binding_drift")
    observation_ids = [observation.observation_id for observation in observations]
    if len(observation_ids) != len(set(observation_ids)):
        raise SourceIdentifierCandidateError("retrieval_snapshot_observation_duplicate")

    inventory_by_id = {item.source_inventory_item_id: item for item in inventory.items}
    for observation in observations:
        if observation.observation_type not in _CANDIDATE_OBSERVATION_TYPES:
            continue
        item_id = observation.location.get("source_inventory_item_id")
        item = inventory_by_id.get(str(item_id))
        if (
            item is None
            or observation.asset_id != inventory.source_asset_id
            or observation.location.get("source_local_key") != item.location.get("source_local_key")
            or observation.location.get("source_content_hash")
            != item.location.get("message_content_hash")
            or sha256_json(observation.permission_scope) != item.permission_fingerprint
        ):
            raise SourceIdentifierCandidateError("retrieval_snapshot_occurrence_lineage_invalid")
        if isinstance(observation.text, str) and observation.text:
            _message_occurrence_id(observation)

    if (
        report.get("artifact_id") != RETRIEVAL_REPORT_ARTIFACT_ID
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("status") != "passed"
        or report.get("source_completeness_status") != "passed"
        or report.get("retrieval_ready_status") != "passed"
        or report.get("target_profile_status") != "passed_no_ascii_fallback"
        or report.get("canonical_fact_status") != "not_asserted"
        or report.get("methodology_readiness_status") != "blocked"
        or report.get("blocker_fingerprints") != []
    ):
        raise SourceIdentifierCandidateError("retrieval_report_contract_invalid")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise SourceIdentifierCandidateError("retrieval_report_fingerprint_invalid")
    report_counts = report.get("counts")
    if not isinstance(report_counts, Mapping) or dict(report_counts) != dict(counts):
        raise SourceIdentifierCandidateError("retrieval_report_count_binding_drift")
    cross_bindings = (
        ("retrieval_snapshot_fingerprint", "snapshot_fingerprint"),
        ("source_snapshot_fingerprint", "source_snapshot_fingerprint"),
        ("source_inventory_fingerprint", "source_inventory_fingerprint"),
        ("parsed_observation_fingerprint", "parsed_observation_fingerprint"),
        ("candidate_admission_profile_fingerprint", "tokenizer_profile_fingerprint"),
        ("index_fingerprint", "index_fingerprint"),
    )
    if any(report.get(left) != snapshot.get(right) for left, right in cross_bindings):
        raise SourceIdentifierCandidateError("retrieval_snapshot_report_binding_drift")
    return observations, inventory


def _select_source_observations(
    *,
    observations: Sequence[Observation],
    snapshot: Mapping[str, Any],
    snapshot_byte_sha256: str,
    report: Mapping[str, Any],
    report_byte_sha256: str,
    materialized_work_dir: Path | None,
    expected_materialization_artifact_sha256: str | None,
    expected_materialization_safe_report_sha256: str | None,
) -> tuple[tuple[Observation, ...], dict[str, Any]]:
    materialization_values = (
        materialized_work_dir,
        expected_materialization_artifact_sha256,
        expected_materialization_safe_report_sha256,
    )
    if all(value is None for value in materialization_values):
        selected = tuple(observations)
        source_hashes = sorted(sha256_json(item.to_dict()) for item in selected)
        binding = {
            "mode": FULL_SOURCE_SELECTION_MODE,
            "retrieval_snapshot_byte_sha256": snapshot_byte_sha256,
            "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
            "selected_observation_count": len(selected),
            "selected_observation_hash_set_fingerprint": sha256_json(source_hashes),
        }
        _validate_observation_selection_binding(binding)
        return selected, binding
    if not all(value is not None for value in materialization_values):
        raise SourceIdentifierCandidateError("materialization_binding_inputs_incomplete")
    assert materialized_work_dir is not None
    assert expected_materialization_artifact_sha256 is not None
    assert expected_materialization_safe_report_sha256 is not None
    return _load_materialized_observation_subset(
        observations=observations,
        snapshot=snapshot,
        snapshot_byte_sha256=snapshot_byte_sha256,
        report=report,
        report_byte_sha256=report_byte_sha256,
        materialized_work_dir=materialized_work_dir,
        expected_materialization_artifact_sha256=(expected_materialization_artifact_sha256),
        expected_materialization_safe_report_sha256=(expected_materialization_safe_report_sha256),
    )


def _load_materialized_observation_subset(
    *,
    observations: Sequence[Observation],
    snapshot: Mapping[str, Any],
    snapshot_byte_sha256: str,
    report: Mapping[str, Any],
    report_byte_sha256: str,
    materialized_work_dir: Path,
    expected_materialization_artifact_sha256: str,
    expected_materialization_safe_report_sha256: str,
) -> tuple[tuple[Observation, ...], dict[str, Any]]:
    try:
        from scripts import issue56_materialize_development_uat_observations as materializer
    except ImportError as exc:
        raise SourceIdentifierCandidateError("materialization_owner_contract_unavailable") from exc

    private_path = materialized_work_dir / materializer.PRIVATE_ARTIFACT_FILENAME
    safe_path = materialized_work_dir / materializer.SAFE_REPORT_FILENAME
    private_bytes, private = _read_sealed_json(
        private_path,
        expected_sha256=expected_materialization_artifact_sha256,
        reason_prefix="materialization_artifact",
    )
    safe_bytes, safe = _read_sealed_json(
        safe_path,
        expected_sha256=expected_materialization_safe_report_sha256,
        reason_prefix="materialization_safe_report",
    )
    try:
        materializer.validate_private_materialization_artifact(private)
        materializer.validate_safe_materialization_report(
            safe,
            private_artifact_bytes=private_bytes,
        )
    except materializer.DevelopmentObservationMaterializationError as exc:
        raise SourceIdentifierCandidateError(exc.reason_code) from exc

    expected_private_bindings = {
        "retrieval_snapshot_byte_sha256": snapshot_byte_sha256,
        "retrieval_report_byte_sha256": report_byte_sha256,
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "retrieval_report_fingerprint": report["report_fingerprint"],
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "tokenizer_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
    }
    if any(private.get(field) != value for field, value in expected_private_bindings.items()):
        raise SourceIdentifierCandidateError("materialization_retrieval_binding_mismatch")
    expected_safe_bindings = {
        "materialization_artifact_byte_sha256": (expected_materialization_artifact_sha256),
        "materialization_artifact_fingerprint": private["artifact_fingerprint"],
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "candidate_admission_profile_fingerprint": (snapshot["tokenizer_profile_fingerprint"]),
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "retrieval_report_fingerprint": report["report_fingerprint"],
        "selected_observation_id_set_fingerprint": private[
            "selected_observation_id_set_fingerprint"
        ],
        "selected_observation_hash_set_fingerprint": private[
            "selected_observation_hash_set_fingerprint"
        ],
        "record_byte_sha256_set_fingerprint": private["record_byte_sha256_set_fingerprint"],
        "record_inventory_fingerprint": private["record_inventory_fingerprint"],
        "selection_proof_fingerprint": private["selection_proof_fingerprint"],
    }
    if any(safe.get(field) != value for field, value in expected_safe_bindings.items()):
        raise SourceIdentifierCandidateError("materialization_safe_binding_mismatch")

    source_by_id = {item.observation_id: item for item in observations}
    if len(source_by_id) != len(observations):
        raise SourceIdentifierCandidateError("materialization_source_observation_duplicate")
    records = private.get("records")
    if not isinstance(records, list):
        raise SourceIdentifierCandidateError("materialization_record_inventory_invalid")
    selected: list[Observation] = []
    selected_hashes: list[str] = []
    selected_ids: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise SourceIdentifierCandidateError("materialization_record_inventory_invalid")
        observation_id = record.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            raise SourceIdentifierCandidateError("materialization_record_inventory_invalid")
        record_path = (
            materialized_work_dir
            / materializer.OBSERVATION_RELATIVE_DIRECTORY
            / f"{observation_id}.json"
        )
        raw = _read_regular_file_bytes(
            record_path,
            maximum_bytes=16 * 1024 * 1024,
            reason_code="materialization_observation_record_unavailable",
        )
        if _sha256_bytes(raw) != record.get("record_byte_sha256"):
            raise SourceIdentifierCandidateError(
                "materialization_observation_record_byte_seal_mismatch"
            )
        try:
            payload = json.loads(raw, object_pairs_hook=_unique_json_object)
            materialized_observation = Observation.from_dict(payload)
        except (
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            ContractValidationError,
            KeyError,
            TypeError,
        ) as exc:
            raise SourceIdentifierCandidateError(
                "materialization_observation_record_invalid"
            ) from exc
        source_observation = source_by_id.get(observation_id)
        observation_hash = sha256_json(materialized_observation.to_dict())
        if (
            materialized_observation.observation_id != observation_id
            or source_observation is None
            or materialized_observation.to_dict() != source_observation.to_dict()
            or observation_hash != record.get("observation_hash")
        ):
            raise SourceIdentifierCandidateError(
                "materialization_observation_source_binding_mismatch"
            )
        selected.append(materialized_observation)
        selected_ids.append(observation_id)
        selected_hashes.append(observation_hash)

    if (
        len(selected) != materializer.EXPECTED_MATERIALIZED_OBSERVATION_COUNT
        or selected_ids != sorted(selected_ids)
        or sha256_json(selected_ids) != private["selected_observation_id_set_fingerprint"]
        or sha256_json(sorted(selected_hashes))
        != private["selected_observation_hash_set_fingerprint"]
    ):
        raise SourceIdentifierCandidateError("materialization_observation_selection_mismatch")
    binding = {
        "mode": MATERIALIZED_SELECTION_MODE,
        "retrieval_snapshot_byte_sha256": snapshot_byte_sha256,
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "materialization_artifact_byte_sha256": (expected_materialization_artifact_sha256),
        "materialization_safe_report_byte_sha256": (expected_materialization_safe_report_sha256),
        "materialization_artifact_fingerprint": private["artifact_fingerprint"],
        "materialization_report_fingerprint": safe["report_fingerprint"],
        "record_inventory_fingerprint": private["record_inventory_fingerprint"],
        "selection_proof_fingerprint": private["selection_proof_fingerprint"],
        "selected_observation_id_set_fingerprint": private[
            "selected_observation_id_set_fingerprint"
        ],
        "selected_observation_hash_set_fingerprint": private[
            "selected_observation_hash_set_fingerprint"
        ],
        "selected_observation_count": len(selected),
    }
    _validate_observation_selection_binding(binding)
    return tuple(selected), binding


def _validate_observation_selection_binding(
    binding: Mapping[str, Any],
) -> None:
    mode = binding.get("mode")
    common_keys = {
        "mode",
        "retrieval_snapshot_byte_sha256",
        "retrieval_snapshot_fingerprint",
        "selected_observation_count",
        "selected_observation_hash_set_fingerprint",
    }
    if mode == FULL_SOURCE_SELECTION_MODE:
        expected_keys = common_keys
    elif mode == MATERIALIZED_SELECTION_MODE:
        expected_keys = common_keys | {
            "materialization_artifact_byte_sha256",
            "materialization_safe_report_byte_sha256",
            "materialization_artifact_fingerprint",
            "materialization_report_fingerprint",
            "record_inventory_fingerprint",
            "selection_proof_fingerprint",
            "selected_observation_id_set_fingerprint",
        }
    else:
        raise SourceIdentifierCandidateError("observation_selection_mode_invalid")
    if set(binding) != expected_keys:
        raise SourceIdentifierCandidateError("observation_selection_binding_fields_invalid")
    count = binding.get("selected_observation_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise SourceIdentifierCandidateError("observation_selection_count_invalid")
    for field, value in binding.items():
        if field.endswith("_fingerprint") or field.endswith("_sha256"):
            _require_sha256(value, f"observation_selection_{field}_invalid")


def _validate_identity_scope_attestation_binding(
    attestation: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any],
    inventory: SourceInventory,
) -> tuple[SourceIdentifierIdentityScope, str]:
    scope = attestation.get("identity_scope")
    asset = attestation.get("asset_binding")
    approval = attestation.get("approval")
    if (
        not isinstance(scope, Mapping)
        or not isinstance(asset, Mapping)
        or not isinstance(approval, Mapping)
    ):
        raise SourceIdentifierCandidateError("identity_scope_attestation_binding_invalid")
    mode = scope.get("mode")
    if mode not in {TENANT_WORKSPACE_MODE, WORKSPACE_ONLY_MODE}:
        raise SourceIdentifierCandidateError("identity_scope_attestation_mode_invalid")
    workspace_id = _validate_safe_binding_id(scope.get("workspace_id"), "workspace_id")
    tenant_id: str | None = None
    spec_approval_fingerprint: str | None = None
    if mode == TENANT_WORKSPACE_MODE:
        if set(scope) != {"mode", "workspace_id", "tenant_id"}:
            raise SourceIdentifierCandidateError("identity_scope_attestation_binding_invalid")
        tenant_id = _validate_safe_binding_id(scope.get("tenant_id"), "tenant_id")
    else:
        if set(scope) != {"mode", "workspace_id"} or "tenant_id" in scope:
            raise SourceIdentifierCandidateError(
                "identity_scope_attestation_workspace_only_tenant_fabrication"
            )
        if (
            approval.get("operator_approved") is not True
            or approval.get("approval_kind") != SPEC_OPERATOR_APPROVAL_KIND
        ):
            raise SourceIdentifierCandidateError(
                "identity_scope_attestation_workspace_only_approval_invalid"
            )
        spec_approval_id = _validate_safe_binding_id(
            approval.get("spec_approval_id"),
            "spec_approval_id",
        )
        spec_approval_fingerprint = sha256_json(
            {
                "approval_kind": approval["approval_kind"],
                "spec_approval_id": spec_approval_id,
            }
        )
    expected_bindings = {
        "asset_id": inventory.source_asset_id,
        "asset_content_hash": snapshot.get("source_asset_sha256"),
    }
    if any(asset.get(field) != value for field, value in expected_bindings.items()):
        raise SourceIdentifierCandidateError("identity_scope_attestation_asset_mismatch")
    if attestation.get("source_fingerprint") != snapshot.get("source_snapshot_fingerprint"):
        raise SourceIdentifierCandidateError("identity_scope_attestation_source_mismatch")
    if attestation.get("permission_fingerprint") != snapshot.get("permission_fingerprint"):
        raise SourceIdentifierCandidateError("identity_scope_attestation_permission_mismatch")
    attested_asset_fingerprint = _require_sha256(
        asset.get("asset_fingerprint"),
        "identity_scope_attestation_asset_fingerprint_invalid",
    )
    if attestation.get("policy_fingerprint") != IDENTITY_SCOPE_POLICY_FINGERPRINT:
        raise SourceIdentifierCandidateError("identity_scope_attestation_policy_drift")
    operator_approval_fields = {
        key: approval.get(key)
        for key in (
            "operator_approved",
            "approver_actor",
            "authority_source",
            "approved_at",
            "reason",
        )
    }
    if operator_approval_fields["operator_approved"] is not True or any(
        not isinstance(operator_approval_fields[key], str) or not operator_approval_fields[key]
        for key in ("approver_actor", "authority_source", "approved_at", "reason")
    ):
        raise SourceIdentifierCandidateError("identity_scope_attestation_operator_approval_invalid")
    try:
        identity_scope = SourceIdentifierIdentityScope(
            identity_scope_mode=str(mode),
            identity_scope_fingerprint=sha256_json(dict(scope)),
            workspace_id=workspace_id,
            identity_scope_attestation_fingerprint=_require_sha256(
                attestation.get("attestation_fingerprint"),
                "identity_scope_attestation_fingerprint_invalid",
            ),
            identity_scope_policy_fingerprint=_require_sha256(
                attestation.get("policy_fingerprint"),
                "identity_scope_attestation_policy_fingerprint_invalid",
            ),
            operator_approval_fingerprint=sha256_json(operator_approval_fields),
            tenant_id=tenant_id,
            spec_approval_fingerprint=spec_approval_fingerprint,
        )
    except ContractValidationError as exc:
        raise SourceIdentifierCandidateError(
            "identity_scope_attestation_owner_binding_invalid"
        ) from exc
    return identity_scope, attested_asset_fingerprint


def _message_occurrence_id(observation: Observation) -> str:
    values = {
        value
        for source in (observation.location, observation.payload or {})
        for value in [source.get("message_occurrence_id")]
        if isinstance(value, str) and value
    }
    if len(values) != 1:
        raise SourceIdentifierCandidateError("message_occurrence_lineage_invalid")
    return next(iter(values))


def _derived_extractor_run_id(
    *,
    source_snapshot_fingerprint: str,
    identity_scope_binding_fingerprint: str,
) -> str:
    digest = sha256_json(
        {
            "source_snapshot_fingerprint": source_snapshot_fingerprint,
            "identity_scope_binding_fingerprint": identity_scope_binding_fingerprint,
            "tokenizer_profile_fingerprint": (ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT),
            "extraction_policy_fingerprint": (
                SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
            ),
            "resolution_policy_fingerprint": RESOLUTION_POLICY_FINGERPRINT,
        }
    ).removeprefix("sha256:")
    return f"run_issue56_source_identifier_candidates_{digest[:32]}"


def _read_sealed_json(
    path: Path,
    *,
    expected_sha256: str,
    reason_prefix: str,
) -> tuple[bytes, dict[str, Any]]:
    _require_sha256(expected_sha256, f"{reason_prefix}_expected_seal_invalid")
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size <= 0 or metadata.st_size > _MAX_INPUT_BYTES:
            raise OSError
        raw = path.read_bytes()
    except OSError as exc:
        raise SourceIdentifierCandidateError(f"{reason_prefix}_unavailable") from exc
    if _sha256_bytes(raw) != expected_sha256:
        raise SourceIdentifierCandidateError(f"{reason_prefix}_byte_seal_mismatch")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SourceIdentifierCandidateError(f"{reason_prefix}_json_invalid") from exc
    if type(payload) is not dict:
        raise SourceIdentifierCandidateError(f"{reason_prefix}_json_invalid")
    return raw, payload


def _read_json_file(
    path: Path,
    *,
    maximum_bytes: int,
    reason_code: str,
) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise OSError
        value = json.loads(path.read_bytes(), object_pairs_hook=_unique_json_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SourceIdentifierCandidateError(reason_code) from exc
    if type(value) is not dict:
        raise SourceIdentifierCandidateError(reason_code)
    return value


def _read_regular_file_bytes(
    path: Path,
    *,
    maximum_bytes: int,
    reason_code: str,
) -> bytes:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise OSError
        return path.read_bytes()
    except OSError as exc:
        raise SourceIdentifierCandidateError(reason_code) from exc


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _persist_atomic_artifact_directory(
    *,
    output_root: Path,
    files: Mapping[str, bytes],
    write_staged_file: Callable[[Path, bytes], None],
) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise SourceIdentifierCandidateError("immutable_output_already_exists")
    try:
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output_root.name}.staging-",
                dir=output_root.parent,
            )
        )
    except OSError as exc:
        raise SourceIdentifierCandidateError("artifact_staging_unavailable") from exc
    try:
        for filename, payload in files.items():
            write_staged_file(staging / filename, payload)
        _fsync_directory(staging)
        _rename_directory_no_replace(staging, output_root)
        _fsync_directory(output_root.parent)
    except SourceIdentifierCandidateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise SourceIdentifierCandidateError("atomic_artifact_persistence_failed") from exc


def _write_file_exclusive(path: Path, payload: bytes) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    except OSError as exc:
        raise SourceIdentifierCandidateError("staged_artifact_write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise SourceIdentifierCandidateError("atomic_no_replace_unavailable")
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
        raise SourceIdentifierCandidateError("immutable_output_already_exists")
    raise SourceIdentifierCandidateError("atomic_no_replace_failed")


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


def _payload_fingerprint(value: Mapping[str, Any], field_name: str) -> str:
    return sha256_json({key: item for key, item in value.items() if key != field_name})


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _require_sha256(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise SourceIdentifierCandidateError(reason_code)
    return value


def _validate_timestamp(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceIdentifierCandidateError(f"{field_name}_invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceIdentifierCandidateError(f"{field_name}_invalid") from exc
    return value


def _validate_safe_binding_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceIdentifierCandidateError(f"{field_name}_invalid")
    try:
        assert_no_public_raw_references(value, field_name)
    except ContractValidationError as exc:
        raise SourceIdentifierCandidateError(f"{field_name}_invalid") from exc
    return value


def _safe_error_payload(reason_code: str) -> dict[str, Any]:
    return {
        "artifact_id": ERROR_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "reason_fingerprint": sha256_json(reason_code),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-snapshot", type=Path, required=True)
    parser.add_argument("--expected-retrieval-snapshot-sha256", required=True)
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--expected-retrieval-report-sha256", required=True)
    parser.add_argument("--identity-scope-attestation", type=Path, required=True)
    parser.add_argument("--expected-identity-scope-attestation-sha256", required=True)
    parser.add_argument("--materialized-work-dir", type=Path)
    parser.add_argument("--expected-materialization-artifact-sha256")
    parser.add_argument("--expected-materialization-safe-report-sha256")
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifacts = build_source_identifier_candidate_artifacts(
            retrieval_snapshot_path=args.retrieval_snapshot,
            expected_retrieval_snapshot_sha256=(args.expected_retrieval_snapshot_sha256),
            retrieval_report_path=args.retrieval_report,
            expected_retrieval_report_sha256=args.expected_retrieval_report_sha256,
            identity_scope_attestation_path=args.identity_scope_attestation,
            expected_identity_scope_attestation_sha256=(
                args.expected_identity_scope_attestation_sha256
            ),
            materialized_work_dir=args.materialized_work_dir,
            expected_materialization_artifact_sha256=(
                args.expected_materialization_artifact_sha256
            ),
            expected_materialization_safe_report_sha256=(
                args.expected_materialization_safe_report_sha256
            ),
            output_root=args.output_root,
        )
    except SourceIdentifierCandidateError as exc:
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
