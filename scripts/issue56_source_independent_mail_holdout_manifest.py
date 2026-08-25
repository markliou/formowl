#!/usr/bin/env python3
"""Author a sealed independent MAIL holdout manifest without executing it."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    ContractValidationError,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (  # noqa: E402
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    MailCandidateAdmissionTokenizerProfile,
    load_issue56_target_mail_tokenizer_profile,
)
from scripts.issue56_source_complete_snapshot_rebind import (  # noqa: E402
    _validate_native_retrieval_snapshot,
)
from scripts.issue56_source_development_uat_manifest import (  # noqa: E402
    ARTIFACT_ID as DEVELOPMENT_MANIFEST_ARTIFACT_ID,
    CASE_COUNT as DEVELOPMENT_CASE_COUNT,
    CLASSIFICATION as DEVELOPMENT_CLASSIFICATION,
    DEFAULT_BUNDLE_ARTIFACT,
    DEFAULT_RETRIEVAL_SNAPSHOT,
    MAX_ANCHOR_MESSAGE_FREQUENCY,
    MAX_IDENTIFIER_MESSAGE_FREQUENCY,
    MIN_IDENTIFIER_MESSAGE_FREQUENCY,
    RESULT_LIMIT,
    SAFE_REPORT_ARTIFACT_ID as DEVELOPMENT_SAFE_REPORT_ARTIFACT_ID,
    DevelopmentManifestError,
    _CaseCandidate,
    _EvidenceRecord,
    _candidate_query_is_bound,
    _candidate_query_text,
    _canonical_pretty_bytes,
    _load_json_bytes,
    _payload_fingerprint,
    _persist_immutable_bytes,
    _record_anchor_key,
    _require_sha256,
    _sha256_bytes,
    _stratum_rank,
    _validated_body_evidence_records,
    _validated_bundle_artifact,
)

ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_manifest_v1"
SAFE_REPORT_ARTIFACT_ID = "formowl_issue56_source_independent_mail_holdout_manifest_report_v1"
CLASSIFICATION = "independent_mail_holdout"
HOLDOUT_CASE_COUNT = 30
AUTHOR_ROLE_ID = "issue56_source_holdout_author_v1"
EVALUATOR_ROLE_ID = "issue56_independent_holdout_evaluator_v1"
PARTITION_POLICY_ID = "issue56_latest_quartile_thread_pure_mail_holdout_v1"
SELECTION_POLICY_ID = "issue56_independent_mail_holdout_relation_owner_match_selection_v1"
TIME_PARTITION_NUMERATOR = 1
TIME_PARTITION_DENOMINATOR = 4
DEFAULT_DEVELOPMENT_ROOT = ROOT / ".test-tmp" / "issue56-source-development-uat-v1"
DEFAULT_DEVELOPMENT_MANIFEST = DEFAULT_DEVELOPMENT_ROOT / "development-manifest.private.json"
DEFAULT_DEVELOPMENT_SAFE_REPORT = DEFAULT_DEVELOPMENT_ROOT / "development-manifest.safe.json"
DEFAULT_OUTPUT_ROOT = ROOT / ".test-tmp" / "issue56-source-independent-mail-holdout-v1"
DEFAULT_MANIFEST_OUTPUT = DEFAULT_OUTPUT_ROOT / "holdout-manifest.private.json"
DEFAULT_SAFE_REPORT_OUTPUT = DEFAULT_OUTPUT_ROOT / "holdout-manifest.safe.json"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_HOLDOUT_POLICY = {
    "partition_policy_id": PARTITION_POLICY_ID,
    "classification": CLASSIFICATION,
    "time_partition": {
        "order": "sent_at_utc_then_message_hash",
        "selected_fraction": {
            "numerator": TIME_PARTITION_NUMERATOR,
            "denominator": TIME_PARTITION_DENOMINATOR,
        },
        "selected_side": "latest",
    },
    "thread_partition": (
        "retain_only_threads_whose_complete_message_membership_is_in_time_partition"
    ),
    "development_exclusion": (
        "exclude_every_development_observation_message_occurrence_message_and_thread"
    ),
    "source_kind": "authorized_retrieval_ready_mail_body_observation",
    "case_count": HOLDOUT_CASE_COUNT,
    "identifier_message_frequency": {
        "minimum": MIN_IDENTIFIER_MESSAGE_FREQUENCY,
        "maximum": MAX_IDENTIFIER_MESSAGE_FREQUENCY,
    },
    "anchor_message_frequency_maximum": MAX_ANCHOR_MESSAGE_FREQUENCY,
    "selection_order": "stratum_round_robin_then_hash",
    "observation_reuse": "forbidden",
    "message_occurrence_reuse": "forbidden",
    "query_template_id": "cross_message_relationship_identifier_two_anchors_v1",
    "question_specific_aliases": False,
    "policy_or_runtime_tuning": False,
    "development_quality_output_read": False,
    "holdout_execution": False,
}
HOLDOUT_POLICY_FINGERPRINT = sha256_json(_HOLDOUT_POLICY)


class HoldoutManifestError(RuntimeError):
    """A fail-closed independent holdout authoring error."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _MessagePartition:
    eligible_records: tuple[_EvidenceRecord, ...]
    development_observation_ids: frozenset[str]
    development_occurrence_ids: frozenset[str]
    development_message_ids: frozenset[str]
    development_thread_ids: frozenset[str]
    observation_to_message_id: dict[str, str]
    observation_to_thread_id: dict[str, str]
    occurrence_to_message_id: dict[str, str]
    occurrence_to_thread_id: dict[str, str]
    latest_message_ids: frozenset[str]
    eligible_message_ids: frozenset[str]
    eligible_thread_ids: frozenset[str]
    time_boundary_fingerprint: str
    partition_fingerprint: str


@dataclass(frozen=True)
class HoldoutManifestArtifacts:
    manifest_path: Path
    safe_report_path: Path
    manifest_sha256: str
    manifest: dict[str, Any]
    safe_report: dict[str, Any]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-artifact", type=Path, default=DEFAULT_BUNDLE_ARTIFACT)
    parser.add_argument(
        "--retrieval-snapshot",
        type=Path,
        default=DEFAULT_RETRIEVAL_SNAPSHOT,
    )
    parser.add_argument(
        "--development-manifest",
        type=Path,
        default=DEFAULT_DEVELOPMENT_MANIFEST,
    )
    parser.add_argument(
        "--development-safe-report",
        type=Path,
        default=DEFAULT_DEVELOPMENT_SAFE_REPORT,
    )
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT)
    parser.add_argument(
        "--safe-report-output",
        type=Path,
        default=DEFAULT_SAFE_REPORT_OUTPUT,
    )
    parser.add_argument("--expected-message-count", type=int, default=2_793)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifacts = author_independent_mail_holdout_manifest(
            bundle_artifact_path=args.bundle_artifact,
            retrieval_snapshot_path=args.retrieval_snapshot,
            development_manifest_path=args.development_manifest,
            development_safe_report_path=args.development_safe_report,
            manifest_output=args.manifest_output,
            safe_report_output=args.safe_report_output,
            expected_message_count=args.expected_message_count,
        )
    except (
        ContractValidationError,
        DevelopmentManifestError,
        HoldoutManifestError,
        RuntimeError,
    ) as exc:
        reason_code = getattr(exc, "reason_code", str(exc))
        print(
            json.dumps(
                _blocked_report(reason_code),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(artifacts.safe_report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def author_independent_mail_holdout_manifest(
    *,
    bundle_artifact_path: Path,
    retrieval_snapshot_path: Path,
    development_manifest_path: Path,
    development_safe_report_path: Path,
    manifest_output: Path,
    safe_report_output: Path,
    expected_message_count: int,
) -> HoldoutManifestArtifacts:
    """Author and seal a source-derived holdout without running an evaluator."""

    if expected_message_count <= 0:
        raise HoldoutManifestError("expected_message_count_invalid")
    bundle_bytes, bundle_artifact = _load_json_bytes(
        bundle_artifact_path,
        "retrieval_ready_bundle_unavailable",
        "retrieval_ready_bundle_invalid",
    )
    snapshot_bytes, retrieval_snapshot = _load_json_bytes(
        retrieval_snapshot_path,
        "retrieval_ready_snapshot_unavailable",
        "retrieval_ready_snapshot_invalid",
    )
    development_bytes, development_manifest = _load_json_bytes(
        development_manifest_path,
        "development_exclusion_registry_unavailable",
        "development_exclusion_registry_invalid",
    )
    _safe_bytes, development_safe_report = _load_json_bytes(
        development_safe_report_path,
        "development_seal_report_unavailable",
        "development_seal_report_invalid",
    )
    bundle_payload = _validated_bundle_artifact(bundle_artifact)
    _validate_native_retrieval_snapshot(retrieval_snapshot)
    _validate_source_bindings(
        bundle_artifact=bundle_artifact,
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        expected_message_count=expected_message_count,
    )
    development_observation_ids, development_registry_fingerprint = (
        _validated_development_exclusion_registry(
            manifest=development_manifest,
            manifest_bytes=development_bytes,
            safe_report=development_safe_report,
        )
    )
    profile = load_issue56_target_mail_tokenizer_profile()
    if (
        profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
        or profile.profile_fingerprint != retrieval_snapshot["tokenizer_profile_fingerprint"]
    ):
        raise HoldoutManifestError("target_profile_binding_mismatch")
    records = _validated_body_evidence_records(
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        profile=profile,
    )
    partition = _partition_holdout_evidence(
        bundle_payload=bundle_payload,
        records=records,
        development_observation_ids=development_observation_ids,
    )
    candidates = _build_holdout_candidates(partition.eligible_records)
    selected = _select_holdout_candidates(
        candidates,
        case_count=HOLDOUT_CASE_COUNT,
        profile=profile,
    )
    cases = _build_holdout_cases(
        selected,
        owner_user_id=str(bundle_payload["mail_import_session"]["owner_user_id"]),
        profile=profile,
        partition=partition,
    )
    disjointness = _validate_case_disjointness(
        cases=cases,
        partition=partition,
    )
    strata = Counter(candidate.identifier_kind for candidate in selected)
    manifest: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": 1,
        "classification": CLASSIFICATION,
        "claim_boundary_status": "sealed_independent_holdout_not_executed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "seal_required_before_execution": True,
        "mail_evidence_bundle_id": bundle_payload["mail_evidence_bundle_id"],
        "mail_import_session_id": bundle_payload["mail_import_session"]["mail_import_session_id"],
        "archive_sha256": bundle_payload["mail_import_session"]["archive_sha256"],
        "author_evaluator_boundary": {
            "author_role_id": AUTHOR_ROLE_ID,
            "evaluator_role_id": EVALUATOR_ROLE_ID,
            "roles_are_distinct": AUTHOR_ROLE_ID != EVALUATOR_ROLE_ID,
            "evaluator_invoked": False,
            "development_quality_output_read": False,
        },
        "source_bindings": {
            "bundle_artifact_byte_hash": _sha256_bytes(bundle_bytes),
            "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
            "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
            "retrieval_snapshot_byte_hash": _sha256_bytes(snapshot_bytes),
            "retrieval_snapshot_fingerprint": retrieval_snapshot["snapshot_fingerprint"],
            "source_snapshot_fingerprint": retrieval_snapshot["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": retrieval_snapshot["source_inventory_fingerprint"],
            "source_provenance_fingerprint": retrieval_snapshot["source_provenance_fingerprint"],
            "permission_fingerprint": retrieval_snapshot["permission_fingerprint"],
            "tokenizer_profile_fingerprint": profile.profile_fingerprint,
            "index_fingerprint": retrieval_snapshot["index_fingerprint"],
        },
        "development_exclusion_binding": {
            "development_manifest_sha256": _sha256_bytes(development_bytes),
            "development_manifest_fingerprint": development_manifest["manifest_fingerprint"],
            "development_registry_fingerprint": development_registry_fingerprint,
            "development_case_count": development_manifest["case_count"],
            "development_observation_count": len(partition.development_observation_ids),
            "development_message_occurrence_count": len(partition.development_occurrence_ids),
            "development_message_count": len(partition.development_message_ids),
            "development_thread_count": len(partition.development_thread_ids),
        },
        "partition_policy": _HOLDOUT_POLICY,
        "partition_policy_fingerprint": HOLDOUT_POLICY_FINGERPRINT,
        "time_boundary_fingerprint": partition.time_boundary_fingerprint,
        "partition_fingerprint": partition.partition_fingerprint,
        "disjointness": disjointness,
        "case_count": len(cases),
        "case_strata_counts": dict(sorted(strata.items())),
        "cases": cases,
    }
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    manifest_bytes = _canonical_pretty_bytes(manifest)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    _persist_immutable_bytes(manifest_output, manifest_bytes, private=True)
    if (
        _sha256_bytes(manifest_output.read_bytes()) != manifest_sha256
        or manifest["execution_status"] != "not_run"
    ):
        raise HoldoutManifestError("seal_before_execution_preflight_failed")
    safe_report = _safe_report(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        bundle_payload=bundle_payload,
        partition=partition,
    )
    _persist_immutable_bytes(
        safe_report_output,
        _canonical_pretty_bytes(safe_report),
        private=False,
    )
    return HoldoutManifestArtifacts(
        manifest_path=manifest_output,
        safe_report_path=safe_report_output,
        manifest_sha256=manifest_sha256,
        manifest=manifest,
        safe_report=safe_report,
    )


def _validate_source_bindings(
    *,
    bundle_artifact: Mapping[str, Any],
    bundle_payload: Mapping[str, Any],
    retrieval_snapshot: Mapping[str, Any],
    expected_message_count: int,
) -> None:
    pairs = (
        ("source_snapshot_fingerprint", "source_snapshot_fingerprint"),
        ("source_inventory_fingerprint", "source_inventory_fingerprint"),
        ("source_provenance_fingerprint", "source_provenance_fingerprint"),
        ("bundle_fingerprint", "mail_evidence_bundle_fingerprint"),
    )
    if any(
        bundle_artifact[bundle_field] != retrieval_snapshot[snapshot_field]
        for bundle_field, snapshot_field in pairs
    ):
        raise HoldoutManifestError("retrieval_source_binding_mismatch")
    counts = retrieval_snapshot.get("counts")
    if (
        not isinstance(counts, Mapping)
        or len(bundle_payload["messages"]) != expected_message_count
        or counts.get("mail_bundle_message_count") != expected_message_count
        or counts.get("unexplained_loss_count") != 0
        or counts.get("blocker_count") != 0
        or retrieval_snapshot.get("blocker_fingerprints") != []
    ):
        raise HoldoutManifestError("source_complete_snapshot_required")


def _validated_development_exclusion_registry(
    *,
    manifest: Mapping[str, Any],
    manifest_bytes: bytes,
    safe_report: Mapping[str, Any],
) -> tuple[frozenset[str], str]:
    if (
        manifest.get("artifact_id") != DEVELOPMENT_MANIFEST_ARTIFACT_ID
        or manifest.get("classification") != DEVELOPMENT_CLASSIFICATION
        or manifest.get("case_count") != DEVELOPMENT_CASE_COUNT
        or manifest.get("quality_evaluation_status") != "not_run"
        or safe_report.get("artifact_id") != DEVELOPMENT_SAFE_REPORT_ARTIFACT_ID
        or safe_report.get("status") != "passed"
        or safe_report.get("classification") != DEVELOPMENT_CLASSIFICATION
        or safe_report.get("manifest_intake_status") != "passed"
    ):
        raise HoldoutManifestError("development_exclusion_registry_status_invalid")
    expected_seal = (
        safe_report.get("fingerprints", {}).get("manifest_sha256")
        if isinstance(safe_report.get("fingerprints"), Mapping)
        else None
    )
    _require_sha256(expected_seal, "development_manifest_seal")
    if expected_seal != _sha256_bytes(manifest_bytes):
        raise HoldoutManifestError("development_exclusion_registry_seal_mismatch")
    if manifest.get("manifest_fingerprint") != _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    ):
        raise HoldoutManifestError("development_exclusion_registry_fingerprint_drift")
    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != DEVELOPMENT_CASE_COUNT:
        raise HoldoutManifestError("development_exclusion_registry_cases_invalid")
    observation_ids: set[str] = set()
    case_fingerprints: set[str] = set()
    for case in raw_cases:
        if (
            not isinstance(case, Mapping)
            or case.get("result_kind") != "owner_match"
            or case.get("required_match_count") != 2
            or case.get("forbidden_source_observation_ids") != []
            or not isinstance(case.get("required_source_observation_ids"), list)
            or len(case["required_source_observation_ids"]) != 2
            or not isinstance(case.get("private_fingerprint"), str)
        ):
            raise HoldoutManifestError("development_exclusion_registry_case_invalid")
        observation_ids.update(str(value) for value in case["required_source_observation_ids"])
        case_fingerprints.add(str(case["private_fingerprint"]))
    if (
        len(observation_ids) != 2 * DEVELOPMENT_CASE_COUNT
        or len(case_fingerprints) != DEVELOPMENT_CASE_COUNT
    ):
        raise HoldoutManifestError("development_exclusion_registry_not_unique")
    registry_fingerprint = sha256_json(
        {
            "development_manifest_sha256": expected_seal,
            "development_manifest_fingerprint": manifest["manifest_fingerprint"],
            "case_fingerprints": sorted(case_fingerprints),
            "observation_id_hashes": sorted(
                sha256_json(observation_id) for observation_id in observation_ids
            ),
        }
    )
    return frozenset(observation_ids), registry_fingerprint


def _partition_holdout_evidence(
    *,
    bundle_payload: Mapping[str, Any],
    records: Sequence[_EvidenceRecord],
    development_observation_ids: frozenset[str],
) -> _MessagePartition:
    segments = {str(row["source_observation_id"]): row for row in bundle_payload["body_segments"]}
    occurrences = {
        str(row["message_occurrence_id"]): row for row in bundle_payload["message_occurrences"]
    }
    messages = {str(row["email_message_id"]): row for row in bundle_payload["messages"]}
    if development_observation_ids - set(segments):
        raise HoldoutManifestError("development_observation_lineage_missing")
    occurrence_to_message_id = {
        occurrence_id: str(row["email_message_id"]) for occurrence_id, row in occurrences.items()
    }
    message_to_thread_id: dict[str, str] = {}
    message_to_time: dict[str, datetime] = {}
    for message_id, message in messages.items():
        thread_id = message.get("thread_id")
        sent_at = message.get("sent_at")
        if not isinstance(thread_id, str) or not thread_id:
            raise HoldoutManifestError("holdout_thread_identity_missing")
        if not isinstance(sent_at, str) or not sent_at:
            raise HoldoutManifestError("holdout_message_time_missing")
        try:
            parsed = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HoldoutManifestError("holdout_message_time_invalid") from exc
        if parsed.tzinfo is None:
            raise HoldoutManifestError("holdout_message_time_timezone_missing")
        message_to_thread_id[message_id] = thread_id
        message_to_time[message_id] = parsed.astimezone(timezone.utc)
    development_occurrence_ids = frozenset(
        str(segments[observation_id]["message_occurrence_id"])
        for observation_id in development_observation_ids
    )
    development_message_ids = frozenset(
        occurrence_to_message_id[occurrence_id] for occurrence_id in development_occurrence_ids
    )
    development_thread_ids = frozenset(
        message_to_thread_id[message_id] for message_id in development_message_ids
    )
    ordered_messages = sorted(
        messages,
        key=lambda message_id: (
            message_to_time[message_id],
            sha256_json(message_id),
        ),
    )
    cutoff_index = (
        (TIME_PARTITION_DENOMINATOR - TIME_PARTITION_NUMERATOR) * len(ordered_messages)
    ) // TIME_PARTITION_DENOMINATOR
    latest_message_ids = frozenset(ordered_messages[cutoff_index:])
    thread_members: dict[str, set[str]] = defaultdict(set)
    for message_id, thread_id in message_to_thread_id.items():
        thread_members[thread_id].add(message_id)
    eligible_thread_ids = frozenset(
        thread_id
        for thread_id, member_ids in thread_members.items()
        if member_ids <= latest_message_ids and thread_id not in development_thread_ids
    )
    eligible_message_ids = frozenset(
        message_id for thread_id in eligible_thread_ids for message_id in thread_members[thread_id]
    )
    occurrence_to_thread_id = {
        occurrence_id: message_to_thread_id[message_id]
        for occurrence_id, message_id in occurrence_to_message_id.items()
    }
    observation_to_message_id = {
        observation_id: occurrence_to_message_id[str(segment["message_occurrence_id"])]
        for observation_id, segment in segments.items()
    }
    observation_to_thread_id = {
        observation_id: message_to_thread_id[message_id]
        for observation_id, message_id in observation_to_message_id.items()
    }
    eligible_occurrences = {
        occurrence_id
        for occurrence_id, message_id in occurrence_to_message_id.items()
        if message_id in eligible_message_ids and occurrence_id not in development_occurrence_ids
    }
    eligible_records = tuple(
        record
        for record in records
        if record.observation_id not in development_observation_ids
        and record.message_occurrence_id in eligible_occurrences
    )
    boundary_time = message_to_time[ordered_messages[cutoff_index]]
    time_boundary_fingerprint = sha256_json(
        {
            "partition_policy_id": PARTITION_POLICY_ID,
            "message_count": len(ordered_messages),
            "cutoff_rank": cutoff_index,
            "boundary_time": boundary_time.isoformat(),
        }
    )
    partition_fingerprint = sha256_json(
        {
            "partition_policy_fingerprint": HOLDOUT_POLICY_FINGERPRINT,
            "time_boundary_fingerprint": time_boundary_fingerprint,
            "latest_message_hashes": sorted(
                sha256_json(message_id) for message_id in latest_message_ids
            ),
            "eligible_message_hashes": sorted(
                sha256_json(message_id) for message_id in eligible_message_ids
            ),
            "eligible_thread_hashes": sorted(
                sha256_json(thread_id) for thread_id in eligible_thread_ids
            ),
            "development_thread_hashes": sorted(
                sha256_json(thread_id) for thread_id in development_thread_ids
            ),
        }
    )
    return _MessagePartition(
        eligible_records=eligible_records,
        development_observation_ids=development_observation_ids,
        development_occurrence_ids=development_occurrence_ids,
        development_message_ids=development_message_ids,
        development_thread_ids=development_thread_ids,
        observation_to_message_id=observation_to_message_id,
        observation_to_thread_id=observation_to_thread_id,
        occurrence_to_message_id=occurrence_to_message_id,
        occurrence_to_thread_id=occurrence_to_thread_id,
        latest_message_ids=latest_message_ids,
        eligible_message_ids=eligible_message_ids,
        eligible_thread_ids=eligible_thread_ids,
        time_boundary_fingerprint=time_boundary_fingerprint,
        partition_fingerprint=partition_fingerprint,
    )


def _build_holdout_candidates(
    records: Sequence[_EvidenceRecord],
) -> tuple[_CaseCandidate, ...]:
    token_occurrences: dict[str, set[str]] = defaultdict(set)
    for record in records:
        for token in record.tokens:
            token_occurrences[token].add(record.message_occurrence_id)
    document_frequency = {
        token: len(occurrence_ids) for token, occurrence_ids in token_occurrences.items()
    }
    identifier_records: dict[tuple[str, str], list[_EvidenceRecord]] = defaultdict(list)
    for record in records:
        for identifier, identifier_kind in record.identifiers:
            identifier_records[(identifier, identifier_kind)].append(record)
    candidates: list[_CaseCandidate] = []
    for (identifier, identifier_kind), identifier_rows in identifier_records.items():
        occurrence_ids = {record.message_occurrence_id for record in identifier_rows}
        if not (
            MIN_IDENTIFIER_MESSAGE_FREQUENCY
            <= len(occurrence_ids)
            <= MAX_IDENTIFIER_MESSAGE_FREQUENCY
        ):
            continue
        best_by_occurrence: dict[str, tuple[_EvidenceRecord, str]] = {}
        for record in identifier_rows:
            anchors = [
                token
                for token in record.lexical_tokens
                if 0 < document_frequency.get(token, 0) <= MAX_ANCHOR_MESSAGE_FREQUENCY
            ]
            if not anchors:
                continue
            anchor = min(
                anchors,
                key=lambda token: (
                    document_frequency[token],
                    sha256_json(token),
                ),
            )
            proposed = (record, anchor)
            current = best_by_occurrence.get(record.message_occurrence_id)
            if current is None or _record_anchor_key(
                proposed,
                document_frequency,
            ) < _record_anchor_key(current, document_frequency):
                best_by_occurrence[record.message_occurrence_id] = proposed
        pairs: list[tuple[tuple[Any, ...], _EvidenceRecord, str, _EvidenceRecord, str]] = []
        rows = sorted(
            best_by_occurrence.values(),
            key=lambda item: sha256_json(item[0].message_occurrence_id),
        )
        for index, (left, left_anchor) in enumerate(rows):
            for right, right_anchor in rows[index + 1 :]:
                if left_anchor == right_anchor:
                    continue
                pair_key = (
                    max(
                        document_frequency[left_anchor],
                        document_frequency[right_anchor],
                    ),
                    document_frequency[left_anchor] + document_frequency[right_anchor],
                    left.observation_hash,
                    right.observation_hash,
                )
                pairs.append((pair_key, left, left_anchor, right, right_anchor))
        if not pairs:
            continue
        _pair_key, left, left_anchor, right, right_anchor = min(pairs)
        candidate_fingerprint = sha256_json(
            {
                "partition_policy_fingerprint": HOLDOUT_POLICY_FINGERPRINT,
                "identifier_hash": sha256_json(identifier),
                "identifier_kind": identifier_kind,
                "left_observation_hash": left.observation_hash,
                "right_observation_hash": right.observation_hash,
                "left_anchor_hash": sha256_json(left_anchor),
                "right_anchor_hash": sha256_json(right_anchor),
            }
        )
        candidates.append(
            _CaseCandidate(
                identifier=identifier,
                identifier_kind=identifier_kind,
                left=left,
                right=right,
                left_anchor=left_anchor,
                right_anchor=right_anchor,
                candidate_fingerprint=candidate_fingerprint,
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                _stratum_rank(candidate.identifier_kind),
                candidate.candidate_fingerprint,
            ),
        )
    )


def _select_holdout_candidates(
    candidates: Sequence[_CaseCandidate],
    *,
    case_count: int,
    profile: MailCandidateAdmissionTokenizerProfile,
) -> tuple[_CaseCandidate, ...]:
    by_kind: dict[str, list[_CaseCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_kind[candidate.identifier_kind].append(candidate)
    kinds = sorted(by_kind, key=_stratum_rank)
    offsets = {kind: 0 for kind in kinds}
    selected: list[_CaseCandidate] = []
    used_occurrences: set[str] = set()
    while len(selected) < case_count:
        progressed = False
        for kind in kinds:
            rows = by_kind[kind]
            while offsets[kind] < len(rows):
                candidate = rows[offsets[kind]]
                offsets[kind] += 1
                occurrence_ids = {
                    candidate.left.message_occurrence_id,
                    candidate.right.message_occurrence_id,
                }
                if occurrence_ids & used_occurrences or not _candidate_query_is_bound(
                    candidate,
                    profile=profile,
                ):
                    continue
                selected.append(candidate)
                used_occurrences.update(occurrence_ids)
                progressed = True
                break
            if len(selected) == case_count:
                break
        if not progressed:
            break
    if len(selected) != case_count:
        raise HoldoutManifestError("disjoint_graph_required_holdout_evidence_coverage_insufficient")
    return tuple(selected)


def _build_holdout_cases(
    selected: Sequence[_CaseCandidate],
    *,
    owner_user_id: str,
    profile: MailCandidateAdmissionTokenizerProfile,
    partition: _MessagePartition,
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for candidate in selected:
        if not _candidate_query_is_bound(candidate, profile=profile):
            raise HoldoutManifestError("holdout_relation_query_binding_failed")
        required_ids = sorted((candidate.left.observation_id, candidate.right.observation_id))
        occurrence_ids = sorted(
            (
                candidate.left.message_occurrence_id,
                candidate.right.message_occurrence_id,
            )
        )
        message_ids = sorted(
            partition.occurrence_to_message_id[occurrence_id] for occurrence_id in occurrence_ids
        )
        thread_ids = sorted(
            partition.occurrence_to_thread_id[occurrence_id] for occurrence_id in occurrence_ids
        )
        case_payload: dict[str, Any] = {
            "case_id": (
                "issue56_holdout_relation_"
                + candidate.candidate_fingerprint.removeprefix("sha256:")[:24]
            ),
            "domain": f"mail_{candidate.identifier_kind}",
            "intent_kind": "relation_reasoning",
            "pattern": "independent_shared_identifier_cross_message_relation_v1",
            "result_kind": "owner_match",
            "query_text": _candidate_query_text(candidate),
            "requester_user_id": owner_user_id,
            "required_source_observation_ids": required_ids,
            "forbidden_source_observation_ids": [],
            "required_match_count": 2,
            "limit": RESULT_LIMIT,
            "source_evidence_binding": {
                "candidate_fingerprint": candidate.candidate_fingerprint,
                "required_observation_hashes": sorted(
                    (candidate.left.observation_hash, candidate.right.observation_hash)
                ),
                "required_message_occurrence_hashes": sorted(
                    sha256_json(occurrence_id) for occurrence_id in occurrence_ids
                ),
                "required_message_hashes": sorted(
                    sha256_json(message_id) for message_id in message_ids
                ),
                "required_thread_hashes": sorted(
                    sha256_json(thread_id) for thread_id in thread_ids
                ),
                "partition_fingerprint": partition.partition_fingerprint,
            },
        }
        case_payload["private_fingerprint"] = sha256_json(case_payload)
        if case_payload["private_fingerprint"] in fingerprints:
            raise HoldoutManifestError("holdout_case_fingerprint_duplicate")
        fingerprints.add(case_payload["private_fingerprint"])
        cases.append(case_payload)
    return cases


def _validate_case_disjointness(
    *,
    cases: Sequence[Mapping[str, Any]],
    partition: _MessagePartition,
) -> dict[str, Any]:
    holdout_observation_ids = {
        str(observation_id)
        for case in cases
        for observation_id in case["required_source_observation_ids"]
    }
    holdout_message_ids = {
        partition.observation_to_message_id[observation_id]
        for observation_id in holdout_observation_ids
    }
    holdout_thread_ids = {
        partition.observation_to_thread_id[observation_id]
        for observation_id in holdout_observation_ids
    }
    observation_overlap = holdout_observation_ids & partition.development_observation_ids
    message_overlap = holdout_message_ids & partition.development_message_ids
    thread_overlap = holdout_thread_ids & partition.development_thread_ids
    if observation_overlap or message_overlap or thread_overlap:
        raise HoldoutManifestError("development_holdout_disjointness_failed")
    if not holdout_message_ids <= partition.eligible_message_ids or not (
        holdout_thread_ids <= partition.eligible_thread_ids
    ):
        raise HoldoutManifestError("holdout_case_outside_frozen_partition")
    if len(holdout_observation_ids) != 2 * len(cases) or len(holdout_message_ids) != 2 * len(cases):
        raise HoldoutManifestError("holdout_case_evidence_reuse_detected")
    return {
        "status": "passed",
        "development_holdout_observation_overlap_count": 0,
        "development_holdout_message_overlap_count": 0,
        "development_holdout_thread_overlap_count": 0,
        "holdout_observation_count": len(holdout_observation_ids),
        "holdout_message_count": len(holdout_message_ids),
        "holdout_thread_count": len(holdout_thread_ids),
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


def _safe_report(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    bundle_payload: Mapping[str, Any],
    partition: _MessagePartition,
) -> dict[str, Any]:
    disjointness = manifest["disjointness"]
    report: dict[str, Any] = {
        "artifact_id": SAFE_REPORT_ARTIFACT_ID,
        "schema_version": 1,
        "status": "passed",
        "classification": CLASSIFICATION,
        "partition_preflight_status": "passed",
        "source_lineage_status": "passed",
        "disjointness_status": disjointness["status"],
        "author_evaluator_boundary_status": "passed_distinct_roles",
        "seal_before_execution_status": "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "development_quality_output_status": "not_read",
        "claim_boundary_status": "holdout_manifest_only",
        "counts": {
            "source_message_count": len(bundle_payload["messages"]),
            "source_body_segment_count": len(bundle_payload["body_segments"]),
            "latest_time_partition_message_count": len(partition.latest_message_ids),
            "eligible_thread_count": len(partition.eligible_thread_ids),
            "eligible_message_count": len(partition.eligible_message_ids),
            "eligible_body_observation_count": len(partition.eligible_records),
            "case_count": manifest["case_count"],
            "required_observation_count": disjointness["holdout_observation_count"],
            "required_message_count": disjointness["holdout_message_count"],
            "required_thread_count": disjointness["holdout_thread_count"],
            "development_holdout_observation_overlap_count": 0,
            "development_holdout_message_overlap_count": 0,
            "development_holdout_thread_overlap_count": 0,
            "unexplained_lineage_count": 0,
            "blocker_count": 0,
        },
        "strata": dict(manifest["case_strata_counts"]),
        "fingerprints": {
            "manifest_sha256": manifest_sha256,
            "manifest_fingerprint": manifest["manifest_fingerprint"],
            "partition_policy_fingerprint": HOLDOUT_POLICY_FINGERPRINT,
            "time_boundary_fingerprint": partition.time_boundary_fingerprint,
            "partition_fingerprint": partition.partition_fingerprint,
            "development_registry_fingerprint": manifest["development_exclusion_binding"][
                "development_registry_fingerprint"
            ],
            "development_manifest_sha256": manifest["development_exclusion_binding"][
                "development_manifest_sha256"
            ],
            "source_snapshot_fingerprint": manifest["source_bindings"][
                "source_snapshot_fingerprint"
            ],
            "permission_fingerprint": manifest["source_bindings"]["permission_fingerprint"],
            "candidate_admission_profile_fingerprint": manifest["source_bindings"][
                "tokenizer_profile_fingerprint"
            ],
            "index_fingerprint": manifest["source_bindings"]["index_fingerprint"],
            "holdout_observation_set_fingerprint": disjointness[
                "holdout_observation_set_fingerprint"
            ],
            "holdout_message_set_fingerprint": disjointness["holdout_message_set_fingerprint"],
            "holdout_thread_set_fingerprint": disjointness["holdout_thread_set_fingerprint"],
        },
        "blocker_ids": [],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    assert_no_public_raw_references(
        report,
        "issue56_source_independent_mail_holdout_manifest_report",
    )
    return report


def _blocked_report(reason_code: str) -> dict[str, Any]:
    blocker_id = (
        reason_code
        if isinstance(reason_code, str) and re.fullmatch(r"[a-z0-9_]+", reason_code)
        else "independent_mail_holdout_authoring_failed"
    )
    report: dict[str, Any] = {
        "artifact_id": SAFE_REPORT_ARTIFACT_ID,
        "schema_version": 1,
        "status": "blocked",
        "classification": CLASSIFICATION,
        "partition_preflight_status": "blocked",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "counts": {"case_count": 0, "blocker_count": 1},
        "strata": {},
        "blocker_ids": [blocker_id],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    assert_no_public_raw_references(
        report,
        "issue56_source_independent_mail_holdout_blocked_report",
    )
    return report


if __name__ == "__main__":
    raise SystemExit(main())
