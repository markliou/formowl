#!/usr/bin/env python3
"""Author a sealed private Issue #56 development UAT manifest from source evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
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
    Observation,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (  # noqa: E402
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    MailCandidateAdmissionTokenizerProfile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_mail import MailEvidenceBundle, deterministic_query_class  # noqa: E402
from scripts.issue56_source_complete_snapshot_rebind import (  # noqa: E402
    _validate_native_retrieval_snapshot,
)

ARTIFACT_ID = "formowl_issue56_source_development_uat_manifest_v1"
SAFE_REPORT_ARTIFACT_ID = "formowl_issue56_source_development_uat_manifest_report_v1"
CLASSIFICATION = "development_not_holdout"
CASE_COUNT = 100
MIN_IDENTIFIER_MESSAGE_FREQUENCY = 2
MAX_IDENTIFIER_MESSAGE_FREQUENCY = 6
MAX_ANCHOR_MESSAGE_FREQUENCY = 8
RESULT_LIMIT = 10
DEFAULT_INPUT_ROOT = ROOT / ".test-tmp" / "issue56-native-retrieval-ready-real" / "retrieval"
DEFAULT_BUNDLE_ARTIFACT = DEFAULT_INPUT_ROOT / "mail-evidence-bundle.private.json"
DEFAULT_RETRIEVAL_SNAPSHOT = DEFAULT_INPUT_ROOT / "retrieval-ready-snapshot.private.json"
DEFAULT_RETRIEVAL_REPORT = DEFAULT_INPUT_ROOT / "retrieval-ready-report.safe.json"
DEFAULT_OUTPUT_ROOT = ROOT / ".test-tmp" / "issue56-source-development-uat-v1"
DEFAULT_MANIFEST_OUTPUT = DEFAULT_OUTPUT_ROOT / "development-manifest.private.json"
DEFAULT_SAFE_REPORT_OUTPUT = DEFAULT_OUTPUT_ROOT / "development-manifest.safe.json"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_STRATUM_ORDER = (
    "url",
    "email",
    "date",
    "amount",
    "business_identifier",
    "domain",
)
_SELECTION_POLICY = {
    "policy_id": "issue56_source_development_relation_owner_match_selection_v1",
    "classification": CLASSIFICATION,
    "source_kind": "authorized_retrieval_ready_mail_body_observation",
    "case_count": CASE_COUNT,
    "identifier_message_frequency": {
        "minimum": MIN_IDENTIFIER_MESSAGE_FREQUENCY,
        "maximum": MAX_IDENTIFIER_MESSAGE_FREQUENCY,
    },
    "anchor_message_frequency_maximum": MAX_ANCHOR_MESSAGE_FREQUENCY,
    "pair_policy": ("two_distinct_message_occurrences_with_one_shared_protected_identifier"),
    "anchor_policy": ("lowest_document_frequency_nonprotected_token_per_exact_body_observation"),
    "selection_order": "stratum_round_robin_then_hash",
    "observation_reuse": "forbidden",
    "query_template_id": "cross_message_relationship_identifier_two_anchors_v1",
    "required_match_count": 2,
    "result_limit": RESULT_LIMIT,
    "holdout_or_oracle_content_read": False,
    "quality_result_read": False,
}
SELECTION_POLICY_FINGERPRINT = sha256_json(_SELECTION_POLICY)


class DevelopmentManifestError(RuntimeError):
    """A fail-closed source-development manifest authoring error."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _EvidenceRecord:
    observation_id: str
    observation_hash: str
    message_occurrence_id: str
    text: str
    tokens: frozenset[str]
    identifiers: tuple[tuple[str, str], ...]
    lexical_tokens: frozenset[str]


@dataclass(frozen=True)
class _CaseCandidate:
    identifier: str
    identifier_kind: str
    left: _EvidenceRecord
    right: _EvidenceRecord
    left_anchor: str
    right_anchor: str
    candidate_fingerprint: str


@dataclass(frozen=True)
class DevelopmentManifestArtifacts:
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
    parser.add_argument("--retrieval-report", type=Path, default=DEFAULT_RETRIEVAL_REPORT)
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
        artifacts = author_development_manifest(
            bundle_artifact_path=args.bundle_artifact,
            retrieval_snapshot_path=args.retrieval_snapshot,
            retrieval_report_path=args.retrieval_report,
            manifest_output=args.manifest_output,
            safe_report_output=args.safe_report_output,
            expected_message_count=args.expected_message_count,
        )
    except (ContractValidationError, DevelopmentManifestError, RuntimeError) as exc:
        reason_code = getattr(exc, "reason_code", str(exc))
        report = _blocked_report(reason_code)
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 2
    print(json.dumps(artifacts.safe_report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def author_development_manifest(
    *,
    bundle_artifact_path: Path,
    retrieval_snapshot_path: Path,
    retrieval_report_path: Path,
    manifest_output: Path,
    safe_report_output: Path,
    expected_message_count: int,
) -> DevelopmentManifestArtifacts:
    """Build one deterministic, source-derived private development manifest."""

    if expected_message_count <= 0:
        raise DevelopmentManifestError("expected_message_count_invalid")
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
    report_bytes, _retrieval_report = _load_json_bytes(
        retrieval_report_path,
        "retrieval_ready_report_unavailable",
        "retrieval_ready_report_invalid",
    )
    bundle_payload = _validated_bundle_artifact(bundle_artifact)
    _validate_native_retrieval_snapshot(retrieval_snapshot)
    _validate_source_bindings(
        bundle_artifact=bundle_artifact,
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        expected_message_count=expected_message_count,
    )
    profile = load_issue56_target_mail_tokenizer_profile()
    if (
        profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
        or profile.profile_fingerprint != retrieval_snapshot["tokenizer_profile_fingerprint"]
    ):
        raise DevelopmentManifestError("target_tokenizer_binding_mismatch")

    records = _validated_body_evidence_records(
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        profile=profile,
    )
    candidates = _build_case_candidates(records)
    selected = _select_balanced_candidates(
        candidates,
        CASE_COUNT,
        profile=profile,
    )
    cases = _build_cases(
        selected,
        owner_user_id=str(bundle_payload["mail_import_session"]["owner_user_id"]),
        profile=profile,
    )
    strata = Counter(candidate.identifier_kind for candidate in selected)
    distinct_observation_ids = {
        observation_id
        for case in cases
        for observation_id in case["required_source_observation_ids"]
    }
    distinct_message_occurrences = {
        record.message_occurrence_id
        for candidate in selected
        for record in (candidate.left, candidate.right)
    }
    manifest: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": 1,
        "classification": CLASSIFICATION,
        "claim_boundary_status": "development_cases_not_quality_or_holdout_evidence",
        "quality_evaluation_status": "not_run",
        "holdout_content_consumed": False,
        "oracle_content_consumed": False,
        "mail_evidence_bundle_id": bundle_payload["mail_evidence_bundle_id"],
        "mail_import_session_id": bundle_payload["mail_import_session"]["mail_import_session_id"],
        "archive_sha256": bundle_payload["mail_import_session"]["archive_sha256"],
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
            "retrieval_report_byte_hash": _sha256_bytes(report_bytes),
        },
        "selection_policy": _SELECTION_POLICY,
        "selection_policy_fingerprint": SELECTION_POLICY_FINGERPRINT,
        "case_count": len(cases),
        "case_strata_counts": dict(sorted(strata.items())),
        "required_evidence_reference_count": sum(
            len(case["required_source_observation_ids"]) for case in cases
        ),
        "distinct_required_observation_count": len(distinct_observation_ids),
        "distinct_required_message_occurrence_count": len(distinct_message_occurrences),
        "cases": cases,
    }
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    manifest_bytes = _canonical_pretty_bytes(manifest)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    _persist_immutable_bytes(manifest_output, manifest_bytes, private=True)

    preflight = _run_intake_preflight(
        manifest=manifest,
        manifest_path=manifest_output,
        manifest_sha256=manifest_sha256,
        bundle_artifact_path=bundle_artifact_path,
        bundle_artifact_sha256=_sha256_bytes(bundle_bytes),
        retrieval_report_path=retrieval_report_path,
        retrieval_report_sha256=_sha256_bytes(report_bytes),
    )
    safe_report = _safe_report(
        manifest_sha256=manifest_sha256,
        manifest=manifest,
        bundle_payload=bundle_payload,
        retrieval_snapshot=retrieval_snapshot,
        preflight=preflight,
    )
    _persist_immutable_bytes(
        safe_report_output,
        _canonical_pretty_bytes(safe_report),
        private=False,
    )
    return DevelopmentManifestArtifacts(
        manifest_path=manifest_output,
        safe_report_path=safe_report_output,
        manifest_sha256=manifest_sha256,
        manifest=manifest,
        safe_report=safe_report,
    )


def _validated_bundle_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    required = {
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
    if set(artifact) != required:
        raise DevelopmentManifestError("retrieval_ready_bundle_schema_invalid")
    if (
        artifact.get("artifact_id") != "formowl_issue56_native_mail_evidence_bundle_v1"
        or artifact.get("schema_version") != 1
        or artifact.get("status") != "passed"
    ):
        raise DevelopmentManifestError("retrieval_ready_bundle_status_invalid")
    for field_name in (
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "bundle_fingerprint",
        "artifact_fingerprint",
    ):
        _require_sha256(artifact.get(field_name), field_name)
    if artifact["artifact_fingerprint"] != _payload_fingerprint(
        artifact,
        "artifact_fingerprint",
    ):
        raise DevelopmentManifestError("retrieval_ready_bundle_fingerprint_drift")
    bundle_payload = artifact.get("bundle")
    if not isinstance(bundle_payload, dict) or artifact["bundle_fingerprint"] != sha256_json(
        bundle_payload
    ):
        raise DevelopmentManifestError("mail_evidence_bundle_fingerprint_drift")
    bundle = MailEvidenceBundle.from_dict(bundle_payload)
    if bundle.to_dict() != bundle_payload:
        raise DevelopmentManifestError("mail_evidence_bundle_round_trip_drift")
    return bundle_payload


def _validate_source_bindings(
    *,
    bundle_artifact: Mapping[str, Any],
    bundle_payload: Mapping[str, Any],
    retrieval_snapshot: Mapping[str, Any],
    expected_message_count: int,
) -> None:
    matching_fields = (
        ("source_snapshot_fingerprint", "source_snapshot_fingerprint"),
        ("source_inventory_fingerprint", "source_inventory_fingerprint"),
        ("source_provenance_fingerprint", "source_provenance_fingerprint"),
        ("bundle_fingerprint", "mail_evidence_bundle_fingerprint"),
    )
    if any(
        bundle_artifact[bundle_field] != retrieval_snapshot[snapshot_field]
        for bundle_field, snapshot_field in matching_fields
    ):
        raise DevelopmentManifestError("retrieval_source_binding_mismatch")
    counts = retrieval_snapshot["counts"]
    if (
        len(bundle_payload["messages"]) != expected_message_count
        or counts.get("mail_bundle_message_count") != expected_message_count
        or counts.get("unexplained_loss_count") != 0
        or counts.get("blocker_count") != 0
    ):
        raise DevelopmentManifestError("source_complete_message_count_mismatch")
    if retrieval_snapshot.get("blocker_fingerprints") != []:
        raise DevelopmentManifestError("retrieval_snapshot_blocked")


def _validated_body_evidence_records(
    *,
    bundle_payload: Mapping[str, Any],
    retrieval_snapshot: Mapping[str, Any],
    profile: MailCandidateAdmissionTokenizerProfile,
) -> tuple[_EvidenceRecord, ...]:
    body_segments = bundle_payload.get("body_segments")
    parsed_rows = retrieval_snapshot.get("parsed_mail_observations")
    if not isinstance(body_segments, list) or not isinstance(parsed_rows, list):
        raise DevelopmentManifestError("body_observation_projection_unavailable")
    parsed_body: dict[str, Observation] = {}
    for row in parsed_rows:
        if not isinstance(row, dict) or row.get("observation_type") != "email_body_segment":
            continue
        observation = Observation.from_dict(row)
        if observation.observation_id in parsed_body:
            raise DevelopmentManifestError("body_observation_id_duplicate")
        parsed_body[observation.observation_id] = observation
    permission_fingerprint = str(retrieval_snapshot["permission_fingerprint"])
    source_provenance_fingerprint = str(retrieval_snapshot["source_provenance_fingerprint"])
    occurrence_ids = {
        str(row["message_occurrence_id"])
        for row in bundle_payload.get("message_occurrences", [])
        if isinstance(row, dict) and isinstance(row.get("message_occurrence_id"), str)
    }
    records: list[_EvidenceRecord] = []
    seen_segment_ids: set[str] = set()
    for segment in body_segments:
        if not isinstance(segment, dict):
            raise DevelopmentManifestError("body_segment_schema_invalid")
        observation_id = str(segment.get("source_observation_id", ""))
        message_occurrence_id = str(segment.get("message_occurrence_id", ""))
        segment_id = str(segment.get("email_body_segment_id", ""))
        text = segment.get("text")
        observation = parsed_body.get(observation_id)
        if (
            not segment_id
            or segment_id in seen_segment_ids
            or observation is None
            or not isinstance(text, str)
            or observation.text != text
            or observation.location.get("message_occurrence_id") != message_occurrence_id
            or message_occurrence_id not in occurrence_ids
            or sha256_json(observation.permission_scope) != permission_fingerprint
            or observation.location.get("source_provenance_fingerprint")
            != source_provenance_fingerprint
            or not isinstance(
                observation.location.get("source_inventory_item_id"),
                str,
            )
            or not isinstance(observation.location.get("source_local_key"), str)
            or not _SHA256_RE.fullmatch(str(observation.location.get("source_content_hash", "")))
        ):
            raise DevelopmentManifestError("body_observation_lineage_mismatch")
        seen_segment_ids.add(segment_id)
        analysis = profile.analyze(text)
        identifiers = tuple(
            sorted(
                {
                    (span.exact_token, span.identifier_kind)
                    for span in analysis.protected_identifiers
                }
            )
        )
        protected = {identifier for identifier, _kind in identifiers}
        lexical_tokens = frozenset(
            token for token in analysis.tokens - protected if 2 <= len(token.strip()) <= 80
        )
        records.append(
            _EvidenceRecord(
                observation_id=observation_id,
                observation_hash=sha256_json(observation.to_dict()),
                message_occurrence_id=message_occurrence_id,
                text=text,
                tokens=analysis.tokens,
                identifiers=identifiers,
                lexical_tokens=lexical_tokens,
            )
        )
    if len(records) != len(body_segments) or len(parsed_body) != len(body_segments):
        raise DevelopmentManifestError("body_observation_coverage_incomplete")
    return tuple(records)


def _build_case_candidates(
    records: Sequence[_EvidenceRecord],
) -> tuple[_CaseCandidate, ...]:
    token_occurrences: dict[str, set[str]] = defaultdict(set)
    for record in records:
        for token in record.tokens:
            token_occurrences[token].add(record.message_occurrence_id)
    document_frequency = {
        token: len(occurrences) for token, occurrences in token_occurrences.items()
    }
    identifier_records: dict[tuple[str, str], list[_EvidenceRecord]] = defaultdict(list)
    for record in records:
        for identifier, kind in record.identifiers:
            identifier_records[(identifier, kind)].append(record)

    candidates: list[_CaseCandidate] = []
    for (identifier, kind), identifier_rows in identifier_records.items():
        distinct_occurrences = {record.message_occurrence_id for record in identifier_rows}
        if not (
            MIN_IDENTIFIER_MESSAGE_FREQUENCY
            <= len(distinct_occurrences)
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
            existing = best_by_occurrence.get(record.message_occurrence_id)
            if existing is None or _record_anchor_key(
                proposed,
                document_frequency,
            ) < _record_anchor_key(existing, document_frequency):
                best_by_occurrence[record.message_occurrence_id] = proposed
        possible_pairs: list[
            tuple[tuple[Any, ...], _EvidenceRecord, str, _EvidenceRecord, str]
        ] = []
        occurrence_rows = sorted(
            best_by_occurrence.values(),
            key=lambda item: sha256_json(item[0].message_occurrence_id),
        )
        for index, (left, left_anchor) in enumerate(occurrence_rows):
            for right, right_anchor in occurrence_rows[index + 1 :]:
                if left_anchor == right_anchor:
                    continue
                pair_key = (
                    max(
                        document_frequency[left_anchor],
                        document_frequency[right_anchor],
                    ),
                    document_frequency[left_anchor] + document_frequency[right_anchor],
                    sha256_json(left.observation_id),
                    sha256_json(right.observation_id),
                )
                possible_pairs.append((pair_key, left, left_anchor, right, right_anchor))
        if not possible_pairs:
            continue
        _key, left, left_anchor, right, right_anchor = min(possible_pairs)
        candidate_fingerprint = sha256_json(
            {
                "selection_policy_fingerprint": SELECTION_POLICY_FINGERPRINT,
                "identifier_hash": sha256_json(identifier),
                "identifier_kind": kind,
                "left_observation_hash": left.observation_hash,
                "right_observation_hash": right.observation_hash,
                "left_anchor_hash": sha256_json(left_anchor),
                "right_anchor_hash": sha256_json(right_anchor),
            }
        )
        candidates.append(
            _CaseCandidate(
                identifier=identifier,
                identifier_kind=kind,
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


def _record_anchor_key(
    value: tuple[_EvidenceRecord, str],
    document_frequency: Mapping[str, int],
) -> tuple[int, str, str]:
    record, anchor = value
    return (
        document_frequency[anchor],
        sha256_json(anchor),
        record.observation_hash,
    )


def _select_balanced_candidates(
    candidates: Sequence[_CaseCandidate],
    case_count: int,
    *,
    profile: MailCandidateAdmissionTokenizerProfile,
) -> tuple[_CaseCandidate, ...]:
    by_kind: dict[str, list[_CaseCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_kind[candidate.identifier_kind].append(candidate)
    kinds = sorted(by_kind, key=_stratum_rank)
    selected: list[_CaseCandidate] = []
    used_observations: set[str] = set()
    offsets = {kind: 0 for kind in kinds}
    while len(selected) < case_count:
        progressed = False
        for kind in kinds:
            rows = by_kind[kind]
            while offsets[kind] < len(rows):
                candidate = rows[offsets[kind]]
                offsets[kind] += 1
                observation_ids = {
                    candidate.left.observation_id,
                    candidate.right.observation_id,
                }
                if observation_ids & used_observations or not _candidate_query_is_bound(
                    candidate,
                    profile=profile,
                ):
                    continue
                selected.append(candidate)
                used_observations.update(observation_ids)
                progressed = True
                break
            if len(selected) == case_count:
                break
        if not progressed:
            break
    if len(selected) != case_count:
        raise DevelopmentManifestError(
            "positive_graph_required_source_evidence_coverage_insufficient"
        )
    return tuple(selected)


def _build_cases(
    selected: Sequence[_CaseCandidate],
    *,
    owner_user_id: str,
    profile: MailCandidateAdmissionTokenizerProfile,
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for candidate in selected:
        query_text = _candidate_query_text(candidate)
        if not _candidate_query_is_bound(candidate, profile=profile):
            raise DevelopmentManifestError("relation_query_template_binding_failed")
        required_ids = sorted((candidate.left.observation_id, candidate.right.observation_id))
        binding = {
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "required_observation_hashes": sorted(
                (candidate.left.observation_hash, candidate.right.observation_hash)
            ),
            "required_message_occurrence_hashes": sorted(
                (
                    sha256_json(candidate.left.message_occurrence_id),
                    sha256_json(candidate.right.message_occurrence_id),
                )
            ),
        }
        case_payload: dict[str, Any] = {
            "case_id": (
                "issue56_dev_relation_"
                + candidate.candidate_fingerprint.removeprefix("sha256:")[:24]
            ),
            "domain": f"mail_{candidate.identifier_kind}",
            "intent_kind": "relation_reasoning",
            "pattern": "shared_protected_identifier_cross_message_relation_v1",
            "result_kind": "owner_match",
            "query_text": query_text,
            "requester_user_id": owner_user_id,
            "required_source_observation_ids": required_ids,
            "forbidden_source_observation_ids": [],
            "required_match_count": 2,
            "limit": RESULT_LIMIT,
            "source_evidence_binding": binding,
        }
        case_payload["private_fingerprint"] = sha256_json(case_payload)
        if case_payload["private_fingerprint"] in fingerprints:
            raise DevelopmentManifestError("development_case_fingerprint_duplicate")
        fingerprints.add(case_payload["private_fingerprint"])
        cases.append(case_payload)
    return cases


def _candidate_query_text(candidate: _CaseCandidate) -> str:
    return (
        "Find the cross-message relationship between "
        f"{candidate.identifier} and {candidate.left_anchor} "
        f"with {candidate.right_anchor}"
    )


def _candidate_query_is_bound(
    candidate: _CaseCandidate,
    *,
    profile: MailCandidateAdmissionTokenizerProfile,
) -> bool:
    query_text = _candidate_query_text(candidate)
    query_analysis = profile.analyze(query_text)
    protected_query_tokens = {span.exact_token for span in query_analysis.protected_identifiers}
    return (
        deterministic_query_class(query_text) == "relation_reasoning"
        and candidate.identifier in protected_query_tokens
        and candidate.left_anchor in query_analysis.tokens
        and candidate.right_anchor in query_analysis.tokens
    )


def _run_intake_preflight(
    *,
    manifest: Mapping[str, Any],
    manifest_path: Path,
    manifest_sha256: str,
    bundle_artifact_path: Path,
    bundle_artifact_sha256: str,
    retrieval_report_path: Path,
    retrieval_report_sha256: str,
) -> dict[str, Any]:
    from scripts import issue56_simulated_uat as intake

    intake._validate_external_manifest_seal(manifest_sha256, manifest_sha256)
    cases = intake._validated_cases(manifest)
    loaded = intake._load_native_retrieval_ready_bundle_intake(
        bundle_artifact_path=bundle_artifact_path,
        expected_bundle_artifact_sha256=bundle_artifact_sha256,
        report_path=retrieval_report_path,
        expected_report_sha256=retrieval_report_sha256,
    )
    identity_matches = intake._manifest_bundle_identity_matches(
        manifest,
        loaded.bundle_payload,
    )
    positive_count = intake._positive_graph_required_owner_case_count(cases)
    if (
        not identity_matches
        or positive_count != CASE_COUNT
        or _sha256_bytes(manifest_path.read_bytes()) != manifest_sha256
    ):
        raise DevelopmentManifestError("development_manifest_intake_preflight_failed")
    return {
        "status": "passed",
        "manifest_identity_matches": True,
        "positive_graph_required_owner_case_count": positive_count,
        "sealed_native_retrieval_ready_bundle_intake": True,
    }


def _safe_report(
    *,
    manifest_sha256: str,
    manifest: Mapping[str, Any],
    bundle_payload: Mapping[str, Any],
    retrieval_snapshot: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    cases = manifest["cases"]
    report: dict[str, Any] = {
        "artifact_id": SAFE_REPORT_ARTIFACT_ID,
        "schema_version": 1,
        "status": "passed",
        "classification": CLASSIFICATION,
        "manifest_intake_status": preflight["status"],
        "lineage_validation_status": "passed",
        "immutable_write_status": "passed",
        "quality_evaluation_status": "not_run",
        "holdout_content_status": "not_read",
        "claim_boundary_status": "development_manifest_only",
        "counts": {
            "source_message_count": len(bundle_payload["messages"]),
            "source_body_segment_count": len(bundle_payload["body_segments"]),
            "source_attachment_occurrence_count": len(bundle_payload["attachment_occurrences"]),
            "case_count": len(cases),
            "positive_graph_required_owner_case_count": preflight[
                "positive_graph_required_owner_case_count"
            ],
            "required_evidence_reference_count": manifest["required_evidence_reference_count"],
            "distinct_required_observation_count": manifest["distinct_required_observation_count"],
            "distinct_required_message_occurrence_count": manifest[
                "distinct_required_message_occurrence_count"
            ],
            "unexplained_evidence_binding_count": 0,
            "blocker_count": 0,
        },
        "strata": dict(manifest["case_strata_counts"]),
        "fingerprints": {
            "manifest_sha256": manifest_sha256,
            "manifest_fingerprint": manifest["manifest_fingerprint"],
            "selection_policy_fingerprint": SELECTION_POLICY_FINGERPRINT,
            "bundle_artifact_fingerprint": manifest["source_bindings"][
                "bundle_artifact_fingerprint"
            ],
            "mail_evidence_bundle_fingerprint": manifest["source_bindings"][
                "mail_evidence_bundle_fingerprint"
            ],
            "retrieval_snapshot_fingerprint": retrieval_snapshot["snapshot_fingerprint"],
            "source_snapshot_fingerprint": retrieval_snapshot["source_snapshot_fingerprint"],
            "permission_fingerprint": retrieval_snapshot["permission_fingerprint"],
            "candidate_admission_profile_fingerprint": retrieval_snapshot[
                "tokenizer_profile_fingerprint"
            ],
            "index_fingerprint": retrieval_snapshot["index_fingerprint"],
        },
        "blocker_ids": [],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    assert_no_public_raw_references(
        report,
        "issue56_source_development_uat_manifest_report",
    )
    return report


def _blocked_report(reason_code: str) -> dict[str, Any]:
    blocker_id = (
        reason_code
        if isinstance(reason_code, str) and re.fullmatch(r"[a-z0-9_]+", reason_code)
        else "development_manifest_authoring_failed"
    )
    report: dict[str, Any] = {
        "artifact_id": SAFE_REPORT_ARTIFACT_ID,
        "schema_version": 1,
        "status": "blocked",
        "classification": CLASSIFICATION,
        "manifest_intake_status": "blocked",
        "quality_evaluation_status": "not_run",
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
        "issue56_source_development_uat_manifest_blocked_report",
    )
    return report


def _load_json_bytes(
    path: Path,
    unavailable_reason: str,
    invalid_reason: str,
) -> tuple[bytes, dict[str, Any]]:
    try:
        payload_bytes = path.read_bytes()
    except OSError as exc:
        raise DevelopmentManifestError(unavailable_reason) from exc
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DevelopmentManifestError(invalid_reason) from exc
    if not isinstance(payload, dict):
        raise DevelopmentManifestError(invalid_reason)
    return payload_bytes, payload


def _persist_immutable_bytes(
    path: Path,
    payload: bytes,
    *,
    private: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(stat.S_IRWXU)
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise DevelopmentManifestError("immutable_output_conflict")
    else:
        path.write_bytes(payload)
    path.chmod(
        stat.S_IRUSR | stat.S_IWUSR
        if private
        else stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
    )


def _canonical_pretty_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _payload_fingerprint(
    payload: Mapping[str, Any],
    fingerprint_field: str,
) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != fingerprint_field})


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise DevelopmentManifestError(f"{field_name}_invalid")
    return value


def _stratum_rank(identifier_kind: str) -> tuple[int, str]:
    try:
        return (_STRATUM_ORDER.index(identifier_kind), identifier_kind)
    except ValueError:
        return (len(_STRATUM_ORDER), identifier_kind)


def safe_summary(artifacts: DevelopmentManifestArtifacts) -> dict[str, Any]:
    """Return the already validated public-safe summary for callers."""

    return dict(artifacts.safe_report)


if __name__ == "__main__":
    raise SystemExit(main())
