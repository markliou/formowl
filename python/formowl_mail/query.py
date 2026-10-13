from __future__ import annotations

import hashlib
import multiprocessing
import re
import sys
import threading
import unicodedata
from dataclasses import dataclass, field, replace
from time import perf_counter
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping, Sequence, TypeAlias

from formowl_contract import (
    ContractValidationError,
    CoverageLedger,
    DisplayPagination,
    ExecutableSemanticPlan,
    Grant,
    Observation,
    StructuralObservation,
    redact_public_raw_references,
    sha256_json,
    stable_resource_contract_id,
    to_plain,
)
from formowl_contract.primitives import canonical_json
from formowl_core import (
    jieba_sentencepiece_frozen_profile_candidate_admission_tokens,
    load_default_mail_candidate_admission_tokenizer_profile,
)
from formowl_core.tokenization import (
    ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    MailCandidateAdmissionTokenizerProfile,
)
from formowl_retrieval.gateway import (
    SOURCE_EVIDENCE_OBSERVATION_LIMIT,
    SOURCE_EVIDENCE_TIME_BUDGET_MS,
    SourceEvidenceScan,
    source_evidence_double_check,
    source_evidence_supported_requested_fields,
)
from formowl_retrieval.gateway import (
    check_source_evidence_deadline as _check_revision_source_deadline,
)

from ._access import grant_expired, matching_bundles, normalize_grants
from ._guards import (
    assert_authorized_evidence_payload_safe,
    assert_public_payload_safe,
    redact_authorized_evidence_text,
    safe_public_string,
)
from .bundle import MailEvidenceBundle
from .semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
    DEFAULT_SEMANTIC_PLAN_LIMITS,
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    SEMANTIC_CLAIM_STRENGTH_BY_CLASS,
    AuthorizedSemanticSource,
    authorized_permission_scope_matches,
    deterministic_query_class,
    validate_semantic_request_contract,
)

MAIL_TOKENIZER_ID = JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
MAIL_TOKENIZER_PROFILE_FINGERPRINT = ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
_MAIL_EVIDENCE_PERMISSIONS = {"read", "evidence_snippet", "mail_evidence_read"}
_SEMANTIC_GATEWAY_TEXT_REDACTIONS = (
    re.compile(r"\bwith\s+.+\s+as\s*\(", re.IGNORECASE),
    re.compile(r"\bcopy\s+.+\s+from\b", re.IGNORECASE),
    re.compile(r"\bTraceback \(most recent call last\):", re.IGNORECASE),
)
_LAZY_SOURCE_SCAN_SEGMENT_LIMIT = 4_096
# Keep the existing reader/import seam without a second mail-owned contract.
RevisionOwnedMailSourceScan = SourceEvidenceScan
_REVISION_SOURCE_FALLBACK_OBSERVATION_LIMIT = SOURCE_EVIDENCE_OBSERVATION_LIMIT
_REVISION_SOURCE_FALLBACK_TIME_BUDGET_MS = SOURCE_EVIDENCE_TIME_BUDGET_MS
_REVISION_SOURCE_QUERY_TIME_BUDGET_MS = min(
    1_500,
    DEFAULT_SEMANTIC_PLAN_LIMITS.max_time_budget_ms,
)
REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES = frozenset(
    {"email_body_segment", "email_message", "email_header"}
)
_REVISION_SOURCE_REQUEST_TIME_BUDGET_MS = (
    _REVISION_SOURCE_QUERY_TIME_BUDGET_MS + _REVISION_SOURCE_FALLBACK_TIME_BUDGET_MS
)
_REVISION_SOURCE_QUERY_LIMITS = replace(
    DEFAULT_SEMANTIC_PLAN_LIMITS,
    max_time_budget_ms=_REVISION_SOURCE_QUERY_TIME_BUDGET_MS,
)
_MAIL_EXPLICIT_EXACT_CONTROL_MARKERS = (
    "count",
    "exact set",
    "inventory",
    "list all",
    "how many",
    "全部",
    "都",
    "所有",
    "列出",
    "列舉",
    "清單",
    "盤點",
    "多少",
    "哪些",
    "明細",
    "數量",
    "數目",
    "幾封",
    "幾份",
    "幾筆",
    "幾則",
    "幾個",
)


_SourceItemKey = tuple[str, str, str]
_SourceItemIdentity = _SourceItemKey | str


@dataclass(frozen=True)
class MailEvidenceQueryResult:
    status: str
    mail_import_session_id: str | None
    query_hash: str
    evidence_snippets: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    evidence_completeness: str = "unknown"
    answerability_state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_authorized_evidence_payload_safe(
            payload,
            "mail_evidence_query_result",
        )
        return payload


@dataclass(frozen=True)
class _IndexedMailSnippet:
    mail_evidence_bundle_id: str
    searchable_tokens: set[str]
    payload: dict[str, Any]
    dense_evidence_text: str = field(repr=False)
    source_observation_hash: str | None = None
    protected_identifier_tokens: frozenset[str] = frozenset()
    source_item_id: str = ""
    source_item_key: _SourceItemKey | None = None


@dataclass(frozen=True)
class _MailSnippetIndex:
    snippets: tuple[_IndexedMailSnippet, ...]
    snippet_indexes_by_token: dict[str, tuple[int, ...]]
    profile_fingerprint: str = MAIL_TOKENIZER_PROFILE_FINGERPRINT
    observation_snapshot_fingerprint: str | None = None
    candidate_manifest_fingerprint: str | None = None
    index_fingerprint: str | None = None
    protected_identifier_count: int = 0
    source_item_ids_by_token: Mapping[str, frozenset[_SourceItemIdentity]] = field(
        default_factory=dict
    )
    snippet_indexes_by_source_item_id: Mapping[_SourceItemIdentity, tuple[int, ...]] = field(
        default_factory=dict
    )
    subject_by_source_item_id: Mapping[_SourceItemIdentity, str] = field(default_factory=dict)


IndexedMailSnippet = _IndexedMailSnippet
MailSnippetIndex = _MailSnippetIndex


@dataclass(frozen=True)
class _IndexedObservationSnippet:
    source_access_fingerprint: str
    searchable_tokens: set[str]
    payload: dict[str, Any]
    dense_evidence_text: str = field(repr=False)
    source_observation_hash: str
    protected_identifier_tokens: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _ObservationSnippetIndex:
    snippets: tuple[_IndexedObservationSnippet, ...]
    snippet_indexes_by_token: dict[str, tuple[int, ...]]
    profile_fingerprint: str
    source_access_fingerprint: str
    observation_snapshot_fingerprint: str
    occurrence_lineage_fingerprint: str
    candidate_manifest_fingerprint: str
    index_fingerprint: str
    protected_identifier_count: int = 0


IndexedObservationSnippet = _IndexedObservationSnippet
ObservationSnippetIndex = _ObservationSnippetIndex


@dataclass(frozen=True)
class ExistingObservationIndexBuildManifest:
    """Safe manifest for an Observation-only candidate re-index."""

    artifact_id: str
    schema_version: int
    input_kind: str
    observation_snapshot_fingerprint: str
    observation_count: int
    indexed_observation_count: int
    indexed_snippet_count: int
    admitted_candidate_count: int
    protected_identifier_count: int
    candidate_manifest_fingerprint: str
    index_fingerprint: str
    query_profile_fingerprint: str
    evidence_profile_fingerprint: str
    raw_pst_read_count: int
    pst_parser_invocation_count: int
    new_extractor_run_count: int
    missing_lineage_count: int

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "existing_observation_index_build_manifest")
        return payload


@dataclass(frozen=True)
class MailMessageOccurrenceLineage:
    source_observation_id: str
    message_occurrence_id: str

    @property
    def source_kind(self) -> str:
        return AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND

    @property
    def occurrence_kind(self) -> str:
        return "mail_message"

    @property
    def occurrence_id(self) -> str:
        return self.message_occurrence_id

    @property
    def parent_occurrence_id(self) -> None:
        return None

    @property
    def lineage_fingerprint(self) -> str:
        return sha256_json(
            {
                "schema_version": 1,
                "source_kind": self.source_kind,
                "occurrence_kind": self.occurrence_kind,
                "source_observation_id": self.source_observation_id,
                "message_occurrence_id": self.message_occurrence_id,
            }
        )


@dataclass(frozen=True)
class MailAttachmentChildOccurrenceLineage:
    source_observation_id: str
    observation_type: str
    child_asset_id: str
    parent_attachment_observation_id: str
    message_occurrence_id: str

    @property
    def source_kind(self) -> str:
        return AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND

    @property
    def occurrence_kind(self) -> str:
        return self.observation_type

    @property
    def occurrence_id(self) -> str:
        return self.source_observation_id

    @property
    def parent_occurrence_id(self) -> str:
        return self.message_occurrence_id

    @property
    def lineage_fingerprint(self) -> str:
        return sha256_json(
            {
                "schema_version": 1,
                "source_kind": self.source_kind,
                "occurrence_kind": self.occurrence_kind,
                "source_observation_id": self.source_observation_id,
                "child_asset_id": self.child_asset_id,
                "parent_attachment_observation_id": (self.parent_attachment_observation_id),
                "message_occurrence_id": self.message_occurrence_id,
            }
        )


@dataclass(frozen=True)
class MailInlineTableOccurrenceLineage:
    source_observation_id: str
    observation_type: str
    parent_message_observation_id: str
    message_occurrence_id: str
    mime_ordinal: int
    table_ordinal: int

    @property
    def source_kind(self) -> str:
        return AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND

    @property
    def occurrence_kind(self) -> str:
        return self.observation_type

    @property
    def occurrence_id(self) -> str:
        return self.source_observation_id

    @property
    def parent_occurrence_id(self) -> str:
        return self.message_occurrence_id

    @property
    def lineage_fingerprint(self) -> str:
        return sha256_json(
            {
                "schema_version": 1,
                "source_family": "mail_inline_table",
                **to_plain(self),
            }
        )


@dataclass(frozen=True)
class GitHubProjectOccurrenceLineage:
    source_observation_id: str
    record_kind: str
    source_local_key: str
    source_record_fingerprint: str
    parent_source_local_key: str | None = None

    @property
    def source_kind(self) -> str:
        return GITHUB_PROJECT_OBSERVATION_SOURCE_KIND

    @property
    def occurrence_kind(self) -> str:
        return self.record_kind

    @property
    def occurrence_id(self) -> str:
        return self.source_local_key

    @property
    def parent_occurrence_id(self) -> str | None:
        return self.parent_source_local_key

    @property
    def lineage_fingerprint(self) -> str:
        return sha256_json(
            {
                "schema_version": 1,
                "source_kind": self.source_kind,
                "occurrence_kind": self.occurrence_kind,
                "source_observation_id": self.source_observation_id,
                "source_local_key": self.source_local_key,
                "source_record_fingerprint": self.source_record_fingerprint,
                "parent_source_local_key": self.parent_source_local_key,
            }
        )


@dataclass(frozen=True)
class TextDocumentOccurrenceLineage:
    """Native standalone text occurrence bound to its registered Asset/run/lines."""

    source_observation_id: str
    asset_id: str
    extractor_run_id: str
    line_start: int
    line_end: int

    def __post_init__(self) -> None:
        safe_public_string(self.source_observation_id, "source_observation_id")
        safe_public_string(self.asset_id, "asset_id")
        safe_public_string(self.extractor_run_id, "extractor_run_id")
        _validate_text_line_range(self.line_start, self.line_end)

    @property
    def source_kind(self) -> str:
        return AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND

    @property
    def occurrence_kind(self) -> str:
        return "document_text_block"

    @property
    def occurrence_id(self) -> str:
        return sha256_json(
            {
                "asset_id": self.asset_id,
                "extractor_run_id": self.extractor_run_id,
                "line_start": self.line_start,
                "line_end": self.line_end,
            }
        )

    @property
    def parent_occurrence_id(self) -> None:
        return None

    @property
    def lineage_fingerprint(self) -> str:
        return sha256_json(
            {
                "schema_version": 1,
                "source_kind": self.source_kind,
                "source_observation_id": self.source_observation_id,
                "asset_id": self.asset_id,
                "extractor_run_id": self.extractor_run_id,
                "line_start": self.line_start,
                "line_end": self.line_end,
            }
        )


SourceOccurrenceLineage: TypeAlias = (
    MailMessageOccurrenceLineage
    | MailAttachmentChildOccurrenceLineage
    | MailInlineTableOccurrenceLineage
    | GitHubProjectOccurrenceLineage
    | TextDocumentOccurrenceLineage
)


_ATTACHMENT_CHILD_OBSERVATION_TYPES = {
    "table_row",
    "table_cell",
    "paragraph",
    "heading",
    "list_item",
}


def normalized_authorized_observation_lineages(
    observations: Sequence[Observation],
    *,
    authorized_source: AuthorizedSemanticSource,
    occurrence_lineages: Sequence[SourceOccurrenceLineage] = (),
) -> tuple[SourceOccurrenceLineage, ...]:
    """Resolve source-backed attachment children without changing their evidence."""

    observation_by_id: dict[str, Observation] = {}
    for observation in observations:
        validated = Observation.from_dict(observation.to_dict())
        if validated.observation_id in observation_by_id:
            raise ContractValidationError("attachment lineage has duplicate Observation ids")
        observation_by_id[validated.observation_id] = observation
    return _normalized_authorized_observation_lineages_from_snapshot(
        observation_by_id,
        authorized_source=authorized_source,
        occurrence_lineages=occurrence_lineages,
    )


def _normalized_authorized_observation_lineages_from_snapshot(
    observation_by_id: Mapping[str, Observation],
    *,
    authorized_source: AuthorizedSemanticSource,
    occurrence_lineages: Sequence[SourceOccurrenceLineage],
) -> tuple[SourceOccurrenceLineage, ...]:
    supplied_by_id: dict[str, SourceOccurrenceLineage] = {}
    for lineage in occurrence_lineages:
        observation_id = getattr(lineage, "source_observation_id", None)
        if (
            not isinstance(observation_id, str)
            or observation_id not in observation_by_id
            or observation_id in supplied_by_id
        ):
            raise ContractValidationError("attachment lineage input is invalid")
        supplied_by_id[observation_id] = lineage

    child_lineage_by_id = _attachment_child_lineages(observation_by_id)
    child_lineage_by_id.update(_inline_table_lineages(observation_by_id))
    resolved: list[SourceOccurrenceLineage] = []
    for observation_id in sorted(observation_by_id):
        observation = observation_by_id[observation_id]
        expected = child_lineage_by_id.get(observation_id)
        supplied = supplied_by_id.get(observation_id)
        if expected is None:
            if supplied is None:
                raise ContractValidationError("attachment lineage input is incomplete")
            expected = _source_occurrence_lineage_from_snapshot(
                observation,
                authorized_source=authorized_source,
            )
        if supplied is not None and supplied != expected:
            raise ContractValidationError("attachment lineage input mismatch")
        resolved.append(expected)
    return tuple(resolved)


def _attachment_child_lineages(
    observation_by_id: Mapping[str, Observation],
) -> dict[str, MailAttachmentChildOccurrenceLineage]:
    parent_ids_by_child_asset: dict[str, list[str]] = {}
    for observation_id, observation in observation_by_id.items():
        if observation.observation_type != "email_attachment_occurrence":
            continue
        child_asset_id = (observation.payload or {}).get("child_asset_id")
        if child_asset_id is None:
            continue
        if not isinstance(child_asset_id, str) or not child_asset_id:
            raise ContractValidationError("attachment parent child asset binding is invalid")
        safe_public_string(child_asset_id, "child_asset_id")
        parent_ids_by_child_asset.setdefault(child_asset_id, []).append(observation_id)

    child_lineage_by_id: dict[str, MailAttachmentChildOccurrenceLineage] = {}
    for observation_id, observation in observation_by_id.items():
        if (
            observation.modality != "document"
            or observation.observation_type not in _ATTACHMENT_CHILD_OBSERVATION_TYPES
        ):
            continue
        payload = observation.payload or {}
        nested_lineage = payload.get("lineage")
        if not isinstance(nested_lineage, Mapping):
            continue
        claimed_child_asset_id = nested_lineage.get("child_asset_id")
        if nested_lineage.get("source_family") == "mail_inline_table":
            continue
        if (
            not isinstance(claimed_child_asset_id, str)
            or not claimed_child_asset_id
            or claimed_child_asset_id != observation.asset_id
        ):
            raise ContractValidationError("attachment child asset binding is unavailable")
        parent_ids = parent_ids_by_child_asset.get(claimed_child_asset_id, [])
        if not parent_ids:
            raise ContractValidationError("attachment parent Observation binding is unavailable")
        if len(parent_ids) != 1:
            raise ContractValidationError("attachment parent Observation binding is ambiguous")
        parent_id = parent_ids[0]
        parent = observation_by_id[parent_id]
        message_occurrence_id = parent.location.get("message_occurrence_id")
        if (
            not isinstance(message_occurrence_id, str)
            or not message_occurrence_id
            or to_plain(observation.permission_scope) != to_plain(parent.permission_scope)
        ):
            raise ContractValidationError("attachment parent-child lineage binding mismatch")
        if observation.observation_type in {"paragraph", "heading", "list_item"}:
            if (
                parent.modality != "mail"
                or nested_lineage.get("parent_asset_id") != parent.asset_id
                or nested_lineage.get("child_content_hash")
                != (parent.payload or {}).get("content_hash")
                or not isinstance(nested_lineage.get("child_content_hash"), str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", nested_lineage["child_content_hash"])
                is None
            ):
                raise ContractValidationError("attachment text source hash/parent binding mismatch")
            attachment_ref = nested_lineage.get("attachment_source_ref")
            if (
                not isinstance(attachment_ref, Mapping)
                or attachment_ref.get("source_id")
                != (parent.payload or {}).get("source_inventory_item_id")
                or not attachment_ref.get("source_id")
            ):
                raise ContractValidationError("attachment text source occurrence binding mismatch")
        safe_public_string(parent_id, "parent_attachment_observation_id")
        safe_public_string(message_occurrence_id, "message_occurrence_id")
        child_lineage_by_id[observation_id] = MailAttachmentChildOccurrenceLineage(
            source_observation_id=observation_id,
            observation_type=observation.observation_type,
            child_asset_id=claimed_child_asset_id,
            parent_attachment_observation_id=parent_id,
            message_occurrence_id=message_occurrence_id,
        )
    return child_lineage_by_id


def _inline_table_lineages(
    observation_by_id: Mapping[str, Observation],
) -> dict[str, MailInlineTableOccurrenceLineage]:
    resolved = {}
    for observation_id, observation in observation_by_id.items():
        lineage = (observation.payload or {}).get("lineage")
        if not isinstance(lineage, Mapping) or lineage.get("source_family") != "mail_inline_table":
            continue
        parent_id = lineage.get("parent_message_observation_id")
        parent = observation_by_id.get(parent_id) if isinstance(parent_id, str) else None
        occurrence = lineage.get("message_occurrence_id")
        mime_ordinal = lineage.get("mime_ordinal")
        table_ordinal = lineage.get("table_ordinal")
        if (
            observation.modality != "document"
            or observation.observation_type not in {"table_row", "table_cell"}
            or parent is None
            or parent.observation_type != "email_message"
            or parent.modality != "mail"
            or observation.asset_id != parent.asset_id
            or observation.extractor_run_id != parent.extractor_run_id
            or lineage.get("parent_asset_id") != parent.asset_id
            or not isinstance(occurrence, str)
            or not occurrence
            or occurrence != parent.location.get("message_occurrence_id")
            or to_plain(observation.permission_scope) != to_plain(parent.permission_scope)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in (mime_ordinal, table_ordinal)
            )
            or any(observation.location.get(key) != value for key, value in lineage.items())
            or "child_asset_id" in lineage
            or "attachment_ordinal" in lineage
        ):
            raise ContractValidationError("inline table message/MIME lineage binding is invalid")
        resolved[observation_id] = MailInlineTableOccurrenceLineage(
            source_observation_id=observation_id,
            observation_type=observation.observation_type,
            parent_message_observation_id=parent_id,
            message_occurrence_id=occurrence,
            mime_ordinal=mime_ordinal,
            table_ordinal=table_ordinal,
        )
    return resolved


def validate_source_neutral_attachment_observation_coverage(
    observations: Sequence[Observation],
    *,
    matched_child_observation_hashes: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate child-attachment lineage and its extraction coverage partition."""

    observation_by_id = {
        observation.observation_id: Observation.from_dict(observation.to_dict())
        for observation in observations
    }
    if len(observation_by_id) != len(observations):
        raise ContractValidationError("attachment coverage has duplicate Observation ids")
    observation_hash_by_id = {
        observation_id: sha256_json(observation.to_dict())
        for observation_id, observation in observation_by_id.items()
    }
    return _validate_source_neutral_attachment_observation_coverage_from_snapshot(
        observation_by_id,
        observation_hash_by_id=observation_hash_by_id,
        matched_child_observation_hashes=matched_child_observation_hashes,
    )


def _validate_source_neutral_attachment_observation_coverage_from_snapshot(
    observation_by_id: Mapping[str, Observation],
    *,
    observation_hash_by_id: Mapping[str, str],
    matched_child_observation_hashes: Sequence[str],
) -> dict[str, Any]:
    if set(observation_hash_by_id) != set(observation_by_id):
        raise ContractValidationError("attachment coverage Observation hash binding is invalid")
    parents = {
        observation_id: observation
        for observation_id, observation in observation_by_id.items()
        if observation.observation_type == "email_attachment_occurrence"
    }
    child_lineages = _attachment_child_lineages(observation_by_id)
    child_parent_by_hash: dict[str, str] = {}
    returned_parent_ids: set[str] = set()
    for observation_id, lineage in child_lineages.items():
        child_hash = observation_hash_by_id[observation_id]
        child_parent_by_hash[child_hash] = lineage.parent_attachment_observation_id
        returned_parent_ids.add(lineage.parent_attachment_observation_id)

    partition = {
        "returned": len(returned_parent_ids),
        "unsupported": 0,
        "encrypted": 0,
        "redacted": 0,
        "unresolved": 0,
    }
    for parent_id, parent in parents.items():
        if parent_id in returned_parent_ids:
            continue
        status = (parent.payload or {}).get("attachment_extraction_status", "unresolved")
        if status == "returned" or status not in partition:
            raise ContractValidationError("attachment extraction status is invalid")
        partition[status] += 1
    if sum(partition.values()) != len(parents):
        raise ContractValidationError("attachment coverage partition is invalid")

    matched_hashes = tuple(matched_child_observation_hashes)
    if any(
        re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None for value in matched_hashes
    ) or not set(matched_hashes).issubset(child_parent_by_hash):
        raise ContractValidationError("attachment query match binding is invalid")
    coverage_fingerprint = sha256_json(
        {
            "schema_version": 1,
            "authorized_parent_hashes": sorted(
                observation_hash_by_id[parent_id] for parent_id in parents
            ),
            "returned_parent_hashes": sorted(
                observation_hash_by_id[parent_id] for parent_id in returned_parent_ids
            ),
            "partition": partition,
        }
    )
    payload = {
        "authorized_attachment_occurrence_count": len(parents),
        "returned_attachment_occurrence_count": partition["returned"],
        "unsupported_attachment_occurrence_count": partition["unsupported"],
        "encrypted_attachment_occurrence_count": partition["encrypted"],
        "redacted_attachment_occurrence_count": partition["redacted"],
        "unresolved_attachment_occurrence_count": partition["unresolved"],
        "query_matched_attachment_occurrence_count": len(
            {child_parent_by_hash[value] for value in matched_hashes}
        ),
        "authorized_scope_complete": not any(
            partition[key] for key in ("unsupported", "encrypted", "redacted", "unresolved")
        ),
        "coverage_fingerprint": coverage_fingerprint,
    }
    assert_public_payload_safe(payload, "source_neutral_attachment_coverage")
    return payload


@dataclass(frozen=True)
class AuthorizedObservationIndexBuildManifest:
    """Public-safe binding for one source-neutral authorized Observation index."""

    artifact_id: str
    schema_version: int
    input_kind: str
    source_kind_hash: str
    occurrence_schema_hash: str
    source_access_fingerprint: str
    permission_set_fingerprint: str
    occurrence_lineage_fingerprint: str
    observation_snapshot_fingerprint: str
    observation_count: int
    indexed_observation_count: int
    indexed_snippet_count: int
    admitted_candidate_count: int
    protected_identifier_count: int
    candidate_manifest_fingerprint: str
    index_fingerprint: str
    query_profile_fingerprint: str
    evidence_profile_fingerprint: str
    missing_lineage_count: int

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(
            payload,
            "authorized_observation_index_build_manifest",
        )
        return payload


class MailEvidenceQueryGateway:
    """Permission-checked query facade over normalized mail evidence bundles."""

    def __init__(
        self,
        bundles: Sequence[MailEvidenceBundle],
        *,
        tokenizer_profile: MailCandidateAdmissionTokenizerProfile | None = None,
        snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex] | None = None,
        lazy_index: bool = False,
        index_worker_count: int = 1,
    ) -> None:
        if not isinstance(lazy_index, bool):
            raise ContractValidationError("lazy_index must be a boolean")
        build_started = perf_counter()
        requested_worker_count = _validated_index_worker_count(index_worker_count)
        worker_counts = []
        self._bundles = list(bundles)
        self._lazy_index = lazy_index
        self._tokenizer_profile = tokenizer_profile or _load_mail_tokenizer_profile()
        supplied_indexes = dict(snippet_index_by_bundle_id or {})
        known_bundle_ids = {bundle.mail_evidence_bundle_id for bundle in self._bundles}
        if set(supplied_indexes) - known_bundle_ids:
            raise ContractValidationError("mail evidence index does not match selected bundles")
        self._snippet_index_by_bundle_id: dict[str, _MailSnippetIndex] = {}
        for bundle in self._bundles:
            snippet_index = supplied_indexes.get(bundle.mail_evidence_bundle_id)
            if snippet_index is None and not lazy_index:
                workers = _effective_index_worker_count(
                    requested_worker_count, segment_count=len(bundle.body_segments)
                )
                worker_counts.append(workers)
                kwargs = {}
                if tokenizer_profile is not None:
                    kwargs["tokenizer_profile"] = self._tokenizer_profile
                if workers > 1:
                    kwargs["worker_count"] = workers
                snippet_index = _build_snippet_index(bundle, **kwargs)
            if snippet_index is not None:
                _require_matching_profile(snippet_index, self._tokenizer_profile)
                self._snippet_index_by_bundle_id[bundle.mail_evidence_bundle_id] = snippet_index

        self.index_build_elapsed_ms = round((perf_counter() - build_started) * 1000, 3)
        self.index_worker_count = max(worker_counts, default=1)
        self.index_build_mode = "multiprocess" if self.index_worker_count > 1 else "single_process"

    @property
    def tokenizer_profile_fingerprint(self) -> str:
        return self._tokenizer_profile.profile_fingerprint

    @property
    def index_fingerprints(self) -> dict[str, str | None]:
        return {
            bundle.mail_evidence_bundle_id: (
                self._snippet_index_by_bundle_id[bundle.mail_evidence_bundle_id].index_fingerprint
                if bundle.mail_evidence_bundle_id in self._snippet_index_by_bundle_id
                else None
            )
            for bundle in self._bundles
        }

    def query_mail_evidence(
        self,
        *,
        query_text: str,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        grants: Sequence[Grant | dict[str, Any]] = (),
        limit: int = 5,
        now: str | None = None,
    ) -> MailEvidenceQueryResult:
        _validate_query_inputs(
            query_text=query_text,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
            limit=limit,
        )
        query_hash = sha256_json(query_text)
        selected_bundles = matching_bundles(
            self._bundles,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not selected_bundles:
            return MailEvidenceQueryResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["mail_evidence_not_found"],
                answerability_state="source_not_found",
            )

        resolved_now = now or "9999-12-31T23:59:59+00:00"
        grant_objects = normalize_grants(grants)
        visible_bundles = [
            bundle
            for bundle in selected_bundles
            if bundle.mail_import_session.workspace_id == workspace_id
            and _can_read_bundle(
                bundle,
                requester_user_id=requester_user_id,
                grants=grant_objects,
                now=resolved_now,
            )
        ]
        if not visible_bundles:
            return MailEvidenceQueryResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={
                    "hidden_bundles": len(selected_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in selected_bundles),
                },
                warnings=["mail_evidence_permission_denied"],
                answerability_state="permission_denied",
            )

        snippets = _search_visible_bundles(
            visible_bundles,
            query_text=query_text,
            limit=limit,
            snippet_index_by_bundle_id=self._snippet_index_by_bundle_id,
            tokenizer_profile=self._tokenizer_profile,
            defer_index_build=self._lazy_index,
        )
        if not snippets:
            return MailEvidenceQueryResult(
                status="ok",
                mail_import_session_id=(
                    visible_bundles[0].mail_import_session.mail_import_session_id
                ),
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["no_visible_mail_evidence_matched"],
                evidence_completeness=_source_completeness(visible_bundles),
                answerability_state="source_incomplete",
            )
        citations = [_citation_for_snippet(snippet) for snippet in snippets]
        unsafe_snippet_count = sum(bool(snippet.get("content_redacted")) for snippet in snippets)
        return MailEvidenceQueryResult(
            status="ok",
            mail_import_session_id=visible_bundles[0].mail_import_session.mail_import_session_id,
            query_hash=query_hash,
            evidence_snippets=snippets,
            citations=citations,
            redaction_counts={
                "hidden_bundles": 0,
                "hidden_messages": 0,
                "unsafe_snippets": unsafe_snippet_count,
            },
            warnings=(["unsafe_mail_evidence_content_redacted"] if unsafe_snippet_count else []),
            evidence_completeness=_matched_evidence_completeness(snippets),
            answerability_state=(
                "evidence_found_complete"
                if _matched_evidence_completeness(snippets) == "complete"
                else "evidence_found_source_incomplete"
            ),
        )

    @property
    def mail_evidence_bundle_ids(self) -> tuple[str, ...]:
        return tuple(bundle.mail_evidence_bundle_id for bundle in self._bundles)

    def execute_mail_evidence_query(
        self,
        *,
        query_text: str,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        grants: Sequence[Grant | dict[str, Any]] = (),
        limit: int = 5,
        now: str | None = None,
        required_terms: Sequence[str] = (),
        snippet_filter_groups: Sequence[Sequence[str]] = (),
        collapse_source_items: bool = False,
    ) -> _MailEvidenceQueryExecution:
        _validate_query_inputs(
            query_text=query_text,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
            limit=limit,
        )
        query_hash = sha256_json(query_text)
        selected_bundles = matching_bundles(
            self._bundles,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not selected_bundles:
            result = MailEvidenceQueryResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["mail_evidence_not_found"],
                evidence_completeness="unknown",
                answerability_state="source_not_found",
            )
            return _MailEvidenceQueryExecution(
                result=result,
                verified_source_item_keys=(frozenset() if required_terms else None),
                timings_ms=_zero_query_timings(),
            )

        resolved_now = now or "9999-12-31T23:59:59+00:00"
        grant_objects = normalize_grants(grants)
        visible_bundles = [
            bundle
            for bundle in selected_bundles
            if bundle.mail_import_session.workspace_id == workspace_id
            and _can_read_bundle(
                bundle,
                requester_user_id=requester_user_id,
                grants=grant_objects,
                now=resolved_now,
            )
        ]
        if not visible_bundles:
            result = MailEvidenceQueryResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={
                    "hidden_bundles": len(selected_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in selected_bundles),
                },
                warnings=["mail_evidence_permission_denied"],
                evidence_completeness="unknown",
                answerability_state="permission_denied",
            )
            return _MailEvidenceQueryExecution(
                result=result,
                verified_source_item_keys=(frozenset() if required_terms else None),
                timings_ms=_zero_query_timings(),
            )

        if self._lazy_index:
            if required_terms or snippet_filter_groups or collapse_source_items:
                raise ContractValidationError("structured lookup requires an existing mail index")
            return _MailEvidenceQueryExecution(
                result=self.query_mail_evidence(
                    query_text=query_text,
                    requester_user_id=requester_user_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    mail_import_session_id=mail_import_session_id,
                    mail_evidence_bundle_id=mail_evidence_bundle_id,
                    grants=grants,
                    limit=limit,
                    now=now,
                ),
                verified_source_item_keys=None,
                timings_ms=_zero_query_timings(),
            )
        # Do not derive query vocabulary, required-term postings, or business
        # filters until the effective permission boundary has been established.
        required_term_specs = _required_term_specs(required_terms)
        normalized_filter_groups = _normalized_filter_groups(snippet_filter_groups)
        source_completeness = _source_completeness(visible_bundles)
        verified_source_item_keys: frozenset[_SourceItemIdentity] | None = None
        required_matches_by_source_item: Mapping[
            _SourceItemIdentity,
            tuple[_RequiredTermMatch, ...],
        ] = MappingProxyType({})
        required_posting_ms = 0.0
        exact_verification_ms = 0.0
        if required_term_specs:
            (
                verified_source_item_keys,
                required_matches_by_source_item,
                required_posting_ms,
                exact_verification_ms,
            ) = _resolve_verified_required_source_item_ids(
                visible_bundles,
                required_term_specs=required_term_specs,
                snippet_index_by_bundle_id=self._snippet_index_by_bundle_id,
            )
        search = _search_visible_bundles_with_diagnostics(
            visible_bundles,
            query_text=query_text,
            limit=limit,
            snippet_index_by_bundle_id=self._snippet_index_by_bundle_id,
            allowed_source_item_ids=verified_source_item_keys,
            snippet_filter_groups=normalized_filter_groups,
            collapse_source_items=collapse_source_items,
        )
        snippets = search.snippets
        support_assembly_started = perf_counter()
        if required_term_specs and snippets:
            snippets = _assemble_required_term_supporting_evidence(
                snippets,
                bundle_ids=search.bundle_ids,
                matches_by_source_item=required_matches_by_source_item,
                snippet_index_by_bundle_id=self._snippet_index_by_bundle_id,
            )
        support_assembly_ms = (perf_counter() - support_assembly_started) * 1000.0
        timings_ms = {
            "posting_retrieval": round(
                required_posting_ms + search.posting_retrieval_ms,
                3,
            ),
            "exact_verification": round(exact_verification_ms, 3),
            "ranking": round(search.ranking_ms + support_assembly_ms, 3),
        }
        if not snippets:
            result = MailEvidenceQueryResult(
                status="ok",
                mail_import_session_id=(
                    visible_bundles[0].mail_import_session.mail_import_session_id
                ),
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["no_visible_mail_evidence_matched"],
                evidence_completeness=source_completeness,
                answerability_state=(
                    "target_not_found_in_complete_source"
                    if source_completeness == "complete"
                    else "source_incomplete"
                ),
            )
            return _MailEvidenceQueryExecution(
                result=result,
                verified_source_item_keys=verified_source_item_keys,
                timings_ms=timings_ms,
            )
        citations = [
            _citation_for_snippet(snippet, mail_evidence_bundle_id=bundle_id)
            for snippet, bundle_id in zip(snippets, search.bundle_ids, strict=True)
        ]
        unsafe_snippet_count = sum(bool(snippet.get("content_redacted")) for snippet in snippets)
        result = MailEvidenceQueryResult(
            status="ok",
            mail_import_session_id=visible_bundles[0].mail_import_session.mail_import_session_id,
            query_hash=query_hash,
            evidence_snippets=snippets,
            citations=citations,
            redaction_counts={
                "hidden_bundles": 0,
                "hidden_messages": 0,
                "unsafe_snippets": unsafe_snippet_count,
            },
            warnings=(["unsafe_mail_evidence_content_redacted"] if unsafe_snippet_count else []),
            evidence_completeness=_matched_evidence_completeness(snippets),
            answerability_state=(
                "evidence_found_complete"
                if _matched_evidence_completeness(snippets) == "complete"
                else "evidence_found_source_incomplete"
            ),
        )
        return _MailEvidenceQueryExecution(
            result=result,
            verified_source_item_keys=verified_source_item_keys,
            timings_ms=timings_ms,
        )

    def read_mail_evidence(
        self,
        *,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        source_observation_ids: Sequence[str] = (),
        email_message_ids: Sequence[str] = (),
        grants: Sequence[Grant | dict[str, Any]] = (),
        limit: int | None = None,
        now: str | None = None,
    ) -> MailEvidenceReadResult:
        _validate_read_inputs(
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
            source_observation_ids=source_observation_ids,
            email_message_ids=email_message_ids,
            limit=limit,
        )
        selected_bundles = matching_bundles(
            self._bundles,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not selected_bundles:
            return MailEvidenceReadResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                warnings=["mail_evidence_not_found"],
                answerability_state="source_not_found",
            )
        resolved_now = now or "9999-12-31T23:59:59+00:00"
        grant_objects = normalize_grants(grants)
        visible_bundles = [
            bundle
            for bundle in selected_bundles
            if bundle.mail_import_session.workspace_id == workspace_id
            and _can_read_bundle(
                bundle,
                requester_user_id=requester_user_id,
                grants=grant_objects,
                now=resolved_now,
            )
        ]
        if not visible_bundles:
            return MailEvidenceReadResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                redaction_counts={
                    "hidden_bundles": len(selected_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in selected_bundles),
                },
                warnings=["mail_evidence_permission_denied"],
                answerability_state="permission_denied",
            )
        requested_observations = set(source_observation_ids)
        requested_messages = set(email_message_ids)
        segments: list[dict[str, Any]] = []
        for bundle in visible_bundles:
            message_by_id = {message.email_message_id: message for message in bundle.messages}
            for segment in bundle.body_segments:
                if (
                    segment.source_observation_id not in requested_observations
                    and segment.email_message_id not in requested_messages
                ):
                    continue
                message = message_by_id.get(segment.email_message_id)
                segments.append(_safe_snippet(_segment_payload(bundle, segment, message)))
        segments = sorted(
            segments,
            key=lambda item: (
                str(item["email_message_id"]),
                str(item.get("segment_source_type", "")),
                str(item.get("attachment_id", "")),
                int(item.get("body_segment_index") or 0),
                str(item["source_observation_id"]),
            ),
        )
        if not segments:
            return MailEvidenceReadResult(
                status="not_found",
                mail_import_session_id=visible_bundles[
                    0
                ].mail_import_session.mail_import_session_id,
                warnings=["requested_mail_evidence_not_found"],
                evidence_completeness=_source_completeness(visible_bundles),
                answerability_state="requested_evidence_not_found",
            )
        limit_reached = limit is not None and len(segments) > limit
        if limit is not None:
            segments = segments[:limit]
        unsafe_segment_count = sum(bool(item.get("content_redacted")) for item in segments)
        completeness = _matched_evidence_completeness(segments)
        return MailEvidenceReadResult(
            status="partial" if limit_reached else "ok",
            mail_import_session_id=visible_bundles[0].mail_import_session.mail_import_session_id,
            evidence_segments=segments,
            redaction_counts={"unsafe_segments": unsafe_segment_count},
            warnings=[
                *(["unsafe_mail_evidence_content_redacted"] if unsafe_segment_count else []),
                *(["mail_evidence_read_limit_reached"] if limit_reached else []),
            ],
            evidence_completeness="incomplete" if limit_reached else completeness,
            answerability_state=(
                "read_limit_reached"
                if limit_reached
                else (
                    "evidence_read_complete"
                    if completeness == "complete"
                    else "evidence_read_source_incomplete"
                )
            ),
        )


def build_mail_evidence_query_handler(
    bundles: Sequence[MailEvidenceBundle],
    *,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> Any:
    gateway = MailEvidenceQueryGateway(bundles)
    trusted_grants = tuple(grants)

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        result = gateway.query_mail_evidence(
            query_text=input_data.get("query_text", ""),
            requester_user_id=input_data.get("requester_user_id", ""),
            workspace_id=input_data.get("workspace_id", ""),
            session_id=input_data.get("session_id", "semantic_gateway_session"),
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
            grants=trusted_grants,
            limit=input_data.get("limit", 5),
            now=now,
        )
        return result.to_dict()

    return handler


def build_revision_owned_mail_evidence_query_handler(
    *,
    session: Any,
    effective_graph_view: Any,
    source_records: Any,
    safe_binding: Mapping[str, Any],
    allowed_relation_types: Sequence[str] = (),
    max_selector_count: int = 128,
) -> Any:
    """Build the real mail handler for an indexed ingestion revision.

    This adapter uses the already sealed semantic session for candidate
    selection and ``source_records`` for keyed Observation rehydration.  It
    never aliases the graph handler, rebuilds an index, or materializes a
    synthetic bundle.
    """

    if (
        not hasattr(session, "query")
        or not hasattr(source_records, "observation_for_hash")
        or not hasattr(source_records, "observation_hash")
        or not hasattr(source_records, "lineage")
        or not hasattr(source_records, "mail_import_session_id_for_observation")
        or not isinstance(safe_binding, Mapping)
    ):
        raise ContractValidationError("revision-owned mail source binding is unavailable")
    raw_selector_ids = getattr(source_records, "authorized_mail_import_session_ids", ())
    if (
        not isinstance(raw_selector_ids, (tuple, list))
        or isinstance(raw_selector_ids, (str, bytes))
        or len(raw_selector_ids) > max_selector_count
        or any(not isinstance(value, str) or not value for value in raw_selector_ids)
    ):
        raise ContractValidationError("revision-owned mail selector binding is invalid")
    selector_ids = tuple(sorted(set(raw_selector_ids)))
    if not selector_ids:
        raise ContractValidationError("revision-owned mail selector is unavailable")

    coverage = safe_binding.get("extraction_coverage", {})
    coverage_complete = (
        isinstance(coverage, Mapping)
        and coverage.get("source_completeness_certified") is True
        and not safe_binding.get("bounded_canary_candidate_count")
    )
    authorized_source = getattr(session, "authorized_source", None)
    if not isinstance(authorized_source, AuthorizedSemanticSource):
        raise ContractValidationError("revision-owned mail authorized source is unavailable")

    def _denied_result(
        *,
        query_text: str,
        requester_user_id: str,
        warning: str,
        selector: str | None,
    ) -> dict[str, Any]:
        return MailEvidenceQueryResult(
            status="permission_denied",
            mail_import_session_id=selector,
            query_hash=sha256_json(query_text),
            redaction_counts={"hidden_bundles": 1, "hidden_messages": 0},
            warnings=[warning],
        ).to_dict()

    def _snippet_for_observation(
        observation: Observation,
        *,
        observation_hash: str,
        lineage: Any,
        mail_import_session_id: str,
        source_owned: bool = False,
        allow_non_body: bool = False,
    ) -> dict[str, Any] | None:
        if (
            observation.modality != "mail"
            or (
                observation.observation_type != "email_body_segment"
                and not (
                    allow_non_body
                    and observation.observation_type in {"email_message", "email_header"}
                )
            )
            or getattr(lineage, "source_observation_id", None) != observation.observation_id
            or getattr(lineage, "source_kind", None) != AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
        ):
            return None
        if (
            not authorized_permission_scope_matches(
                to_plain(observation.permission_scope),
                authorized_source=authorized_source,
            )
            or (
                (source_owned and sha256_json(observation.to_dict()) != observation_hash)
                or (
                    not source_owned
                    and source_records.observation_hash(observation.observation_id)
                    != observation_hash
                )
            )
            or sha256_json(observation.to_dict()) != observation_hash
        ):
            raise ContractValidationError("revision-owned mail Observation binding is invalid")
        location = to_plain(observation.location)
        payload = to_plain(observation.payload or {})
        message_occurrence_id = location.get("message_occurrence_id")
        message_fingerprint = payload.get("message_fingerprint")
        if (
            not isinstance(message_occurrence_id, str)
            or not message_occurrence_id
            or not isinstance(message_fingerprint, str)
            or not message_fingerprint
        ):
            return None
        email_message_id = stable_resource_contract_id(
            "emailmsg",
            "EmailMessage",
            {"message_fingerprint": message_fingerprint},
        )
        return _safe_snippet(
            {
                "source_type": {
                    "email_body_segment": "mail_body_segment",
                    "email_message": "mail_message",
                    "email_header": "mail_header",
                }[observation.observation_type],
                "source_observation_id": observation.observation_id,
                "mail_import_session_id": mail_import_session_id,
                "email_message_id": email_message_id,
                "message_occurrence_id": message_occurrence_id,
                "subject": payload.get("subject"),
                "snippet": observation.text,
                "source_observation_hash": observation_hash,
            }
        )

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(input_data, Mapping):
            raise ContractValidationError("revision-owned mail query input is invalid")
        query_text = input_data.get("query_text", "")
        requester_user_id = input_data.get("requester_user_id", "")
        workspace_id = input_data.get("workspace_id", "")
        selector = input_data.get("mail_import_session_id")
        bundle_selector = input_data.get("mail_evidence_bundle_id")
        limit = input_data.get("limit", 5)
        required_terms = (
            _validate_required_mail_terms(input_data["required_terms"])
            if "required_terms" in input_data
            else None
        )
        _validate_query_inputs(
            query_text=query_text,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=input_data.get("session_id", "revision_owned_mail_session"),
            mail_import_session_id=selector,
            mail_evidence_bundle_id=bundle_selector,
            limit=limit,
        )
        if (
            requester_user_id != session.requester_user_id
            or workspace_id != session.workspace_id
            or not isinstance(selector, str)
            or selector not in selector_ids
            or bundle_selector is not None
        ):
            return _denied_result(
                query_text=query_text,
                requester_user_id=requester_user_id,
                warning="mail_evidence_selector_denied",
                selector=selector if isinstance(selector, str) else None,
            )
        bounded_limit = min(limit, 128)
        supplied_request_contract = input_data.get("request_contract")
        if supplied_request_contract is None:
            query_class = _revision_owned_mail_query_class(query_text)
            request_contract = validate_semantic_request_contract(
                {
                    "original_query_hash": sha256_json(query_text),
                    "query_class": query_class,
                    "source_family_scope": ["mail"],
                    "requested_fields": [],
                    "maximum_claim_strength": SEMANTIC_CLAIM_STRENGTH_BY_CLASS[query_class],
                },
                available_source_families=("mail",),
            )
        else:
            request_contract = validate_semantic_request_contract(
                supplied_request_contract,
                available_source_families=("mail",),
            )
            query_class = request_contract["query_class"]
        semantic_result = session.query(
            query_text=query_text,
            request_contract=request_contract,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=allowed_relation_types,
            page_size=bounded_limit,
            # Keep the existing 1.5s semantic slice separate from the
            # existing 0.5s source-fallback phase, which starts its own
            # deadline after this query returns.
            limits=_REVISION_SOURCE_QUERY_LIMITS,
        )
        raw_semantic_status = getattr(semantic_result, "status", None)
        semantic_status = (
            raw_semantic_status
            if isinstance(raw_semantic_status, str) and 0 < len(raw_semantic_status) <= 64
            else None
        )
        # Only the governed result's explicit citation set may become a mail
        # citation.  Replan/failed retrieval scores are candidates, not proof.
        hashes = list(semantic_result.answer_citation_hashes)
        tokenizer_profile = None
        query_terms: set[str] = set()
        protected_query_tokens: set[str] = set()
        if hashes:
            tokenizer_profile = _revision_owned_tokenizer_profile(session)
            query_tokenization = tokenizer_profile.analyze(query_text)
            query_terms = set(query_tokenization.tokens)
            protected_query_tokens = {
                span.exact_token for span in query_tokenization.protected_identifiers
            }
        snippets: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        verified_citation_lineages: list[tuple[str, str]] = []
        for observation_hash in hashes:
            if observation_hash in seen_hashes or len(snippets) >= bounded_limit:
                continue
            observation = source_records.observation_for_hash(observation_hash)
            if observation is None:
                continue
            if (
                source_records.mail_import_session_id_for_observation(observation.observation_id)
                != selector
            ):
                continue
            lineage = source_records.lineage(observation.observation_id)
            expected_lineage = source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            if lineage != expected_lineage:
                raise ContractValidationError("revision-owned mail Observation lineage mismatch")
            if (
                _source_mail_observation_match(
                    observation,
                    query_terms=query_terms,
                    required_terms=required_terms,
                    protected_query_tokens=protected_query_tokens,
                    tokenizer_profile=tokenizer_profile,
                )
                is None
            ):
                continue
            snippet = _snippet_for_observation(
                observation,
                observation_hash=observation_hash,
                lineage=lineage,
                mail_import_session_id=selector,
            )
            if snippet is not None:
                snippets.append(snippet)
                seen_hashes.add(observation_hash)
                verified_citation_lineages.append((observation_hash, lineage.lineage_fingerprint))
        warnings = list(semantic_result.warnings)
        scan_source = getattr(source_records, "scan_authorized_mail_observations", None)
        fallback_evidence_found = False
        active_scan_selector: str | None = None

        def prepare_source_projection() -> None:
            nonlocal tokenizer_profile
            if tokenizer_profile is None:
                tokenizer_profile = _revision_owned_tokenizer_profile(session)

        def begin_source_projection(deadline: float) -> None:
            nonlocal query_terms, protected_query_tokens
            query_tokenization = tokenizer_profile.analyze(query_text)
            _check_revision_source_deadline(deadline)
            query_terms = set(query_tokenization.tokens)
            # Give the persisted source accelerator the same bounded lexical
            # candidate set used by the source matcher.  Explicit
            # ``required_terms`` remain the stronger conjunctive selector;
            # otherwise the query tokens are only an accelerator hint and the
            # source reader still revalidates every hydrated Observation.
            project_source_observation.source_lookup_terms = tuple(
                sorted(required_terms if required_terms is not None else query_terms)
            )
            _check_revision_source_deadline(deadline)
            protected_query_tokens = {
                span.exact_token for span in query_tokenization.protected_identifiers
            }

        def project_source_observation(
            observation: Observation,
            observed_selector: str,
            deadline: float,
        ) -> tuple[str, dict[str, Any]] | None:
            nonlocal fallback_evidence_found
            if observed_selector not in selector_ids or observed_selector != active_scan_selector:
                return None
            # Inventory records lack message lineage and are not snippets.
            if (
                observation.modality != "mail"
                or observation.observation_type not in REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES
            ):
                return None
            if (
                _source_mail_observation_match(
                    observation,
                    query_terms=query_terms,
                    required_terms=required_terms,
                    protected_query_tokens=protected_query_tokens,
                    tokenizer_profile=tokenizer_profile,
                    deadline_monotonic=deadline,
                )
                is None
            ):
                return None
            lineage = source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            # The sealed reader has already validated the helper's job,
            # permission, hash, and owner-bound selector before passing this
            # observed scope.  Rehydrating the same Observation by ID here
            # would spend the shared source-evidence budget on duplicate I/O.
            observation_hash = sha256_json(observation.to_dict())
            snippet = _snippet_for_observation(
                observation,
                observation_hash=observation_hash,
                lineage=lineage,
                mail_import_session_id=selector,
                source_owned=True,
                allow_non_body=True,
            )
            if snippet is None:
                return None
            fallback_evidence_found = True
            return observation_hash, {
                **snippet,
                "mail_import_session_id": observed_selector,
            }

        def read_authorized_mail_sources(**kwargs: Any) -> SourceEvidenceScan:
            """Try the selected scope first, then other authorized scopes only on a miss."""

            nonlocal active_scan_selector
            deadline = kwargs["deadline_monotonic"]
            callback = kwargs["observation_callback"]
            max_observations = kwargs["max_observations"]
            scanned_observation_count = 0
            complete = True
            stop_reason: str | None = None
            selector_order = (selector,) + tuple(
                candidate for candidate in selector_ids if candidate != selector
            )
            for candidate_selector in selector_order:
                _check_revision_source_deadline(deadline)
                remaining_observations = max_observations - scanned_observation_count
                if remaining_observations <= 0:
                    complete = False
                    stop_reason = "observation_limit"
                    break
                active_scan_selector = candidate_selector
                callback_invoked = False
                callback_stopped = False

                def consume(observation: Observation, observed_selector: str) -> bool:
                    nonlocal callback_invoked, callback_stopped
                    callback_invoked = True
                    accepted = callback(observation, observed_selector)
                    if not accepted:
                        callback_stopped = True
                    return accepted

                scan = scan_source(
                    max_observations=remaining_observations,
                    deadline_monotonic=deadline,
                    mail_import_session_id=candidate_selector,
                    observation_callback=consume,
                )
                if not isinstance(scan, SourceEvidenceScan):
                    raise ContractValidationError("source evidence scan result is invalid")
                if (
                    type(scan.scanned_observation_count) is not int
                    or scan.scanned_observation_count < 0
                ):
                    raise ContractValidationError("source evidence scan coverage is invalid")
                scanned_observation_count += scan.scanned_observation_count
                if not callback_invoked:
                    for observation, observed_selector in scan.observations:
                        if not callback(observation, observed_selector):
                            callback_stopped = True
                            break
                if callback_stopped or not scan.complete:
                    complete = False
                    stop_reason = "callback" if callback_stopped else scan.stop_reason
                    break
                if fallback_evidence_found:
                    break
            active_scan_selector = None
            return SourceEvidenceScan(
                observations=(),
                scanned_observation_count=scanned_observation_count,
                complete=complete,
                stop_reason=stop_reason,
            )

        requested_fields = tuple(request_contract["requested_fields"])
        supported_requested_fields = source_evidence_supported_requested_fields(
            requested_fields,
            exact_result=getattr(semantic_result, "exact_result", None),
            answer_citation_hashes=tuple(seen_hashes),
            verified_citation_lineages=verified_citation_lineages,
        )
        double_check = source_evidence_double_check(
            initial_status=semantic_status,
            query_class=query_class,
            result_query_class=getattr(semantic_result, "query_class", None),
            initial_warnings=warnings,
            verified_evidence_count=len(snippets),
            evidence_limit=bounded_limit,
            sealed_coverage_complete=coverage_complete,
            read_source=read_authorized_mail_sources if callable(scan_source) else None,
            project_observation=project_source_observation,
            prepare=prepare_source_projection,
            begin=begin_source_projection,
            excluded_hashes=tuple(seen_hashes),
            requested_fields=requested_fields,
            supported_requested_fields=supported_requested_fields,
        )
        snippets.extend(double_check.evidence)
        citations = [_citation_for_snippet(snippet) for snippet in snippets]
        if not coverage_complete:
            warnings.append("mail_evidence_coverage_incomplete")
        warnings.extend(
            f"mail_evidence_source_fallback_{warning}" for warning in double_check.warnings
        )
        if not citations:
            warnings.append("mail_evidence_no_verified_citations")
        warnings = sorted(set(warnings))
        if citations and semantic_status in {
            "partial",
            "pending_review",
            "replan_required",
            "unsupported",
            "incomplete",
            "no_answer",
            "not_found",
        }:
            # The mail tool's public contract has no internal replan/coverage
            # statuses.  Verified citations remain usable, but the warnings
            # below preserve the bounded/incomplete claim boundary.
            status = "ok"
        elif not citations and semantic_status in {
            "partial",
            "replan_required",
            "unsupported",
            "incomplete",
            "no_answer",
        }:
            # Do not expose an internal execution status through MCP.  With no
            # verified Observation there is no mail answer to claim.
            status = "pending_review"
        else:
            status = semantic_status
        if status not in {"ok", "not_found", "permission_denied", "error", "pending_review"}:
            status = "pending_review" if not citations else "ok"
        if double_check.status is not None:
            status = double_check.status
        if not citations and coverage_complete and status == "ok":
            status = "not_found"
        result_selector = selector
        if snippets:
            snippet_selectors = {
                snippet.get("mail_import_session_id")
                for snippet in snippets
                if isinstance(snippet.get("mail_import_session_id"), str)
            }
            if len(snippet_selectors) == 1:
                result_selector = next(iter(snippet_selectors))
        payload = MailEvidenceQueryResult(
            status=status,
            mail_import_session_id=result_selector,
            query_hash=sha256_json(query_text),
            evidence_snippets=snippets,
            citations=citations,
            redaction_counts={
                "hidden_bundles": 0,
                "hidden_messages": 0,
                "unsafe_snippets": sum(
                    bool(snippet.get("content_redacted")) for snippet in snippets
                ),
            },
            warnings=warnings,
        ).to_dict()
        if (
            query_class == "evidence_lookup"
            and requested_fields
            and status not in {"error", "permission_denied"}
        ):
            missing_fields = [
                field_name
                for field_name in requested_fields
                if field_name not in supported_requested_fields
            ]
            # Missing verified structured support is not source absence.
            # Recovered free text/citation counts cannot upgrade field proof.
            coverage = {
                "request_contract_fingerprint": sha256_json(request_contract),
                "requested_fields": list(requested_fields),
                "supported_fields": list(supported_requested_fields),
                "missing_fields": missing_fields,
                "status": "incomplete" if missing_fields else "verified",
                "absence_claim": False,
                "evidence_citation_hashes": sorted(
                    snippet["source_observation_hash"] for snippet in snippets
                ),
            }
            coverage["coverage_fingerprint"] = sha256_json(coverage)
            payload["requested_field_coverage"] = coverage
            assert_public_payload_safe(payload, "mail_evidence_query_result")
        return payload

    handler.authorized_capability_summary = {
        "artifact_id": "formowl_revision_owned_mail_capability_v1",
        "source_families": ["mail"],
        "mail_selector_kind": "mail_import_session_id",
        "authorized_mail_import_session_ids": list(selector_ids),
        "selector_count": len(selector_ids),
        "coverage_status": "complete" if coverage_complete else "incomplete",
        "candidate_cap": 128,
        "capability_fingerprint": sha256_json(
            {
                "source_session_binding_fingerprint": (session.source_session_binding_fingerprint),
                "selector_ids": list(selector_ids),
                "coverage_status": "complete" if coverage_complete else "incomplete",
            }
        ),
    }
    return handler


def _revision_owned_mail_query_class(query_text: str) -> str:
    """Keep mail summaries legal when the shared CJK grammar is ambiguous."""

    query_class = deterministic_query_class(query_text)
    if query_class != "exact_set_or_inventory":
        return query_class
    normalized = query_text.casefold()
    if any(marker in normalized for marker in _MAIL_EXPLICIT_EXACT_CONTROL_MARKERS):
        return query_class
    if "整理" in normalized:
        return "global_summarization"
    # The shared router can classify provider-expanded mail prose as exact
    # from a lexical/grammar cue even when the mail tool supplied no exact
    # field, predicate, or operator.  Keep the exact class fail-closed for
    # explicit controls, but use the ordinary evidence route for unstructured
    # mail prose so route_semantic_query is not given an incomplete exact
    # override.
    return "evidence_lookup"


def _search_visible_bundles(
    bundles: Sequence[MailEvidenceBundle],
    *,
    query_text: str,
    limit: int,
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex] | None = None,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile | None = None,
    defer_index_build: bool = False,
) -> list[dict[str, Any]]:
    profile = tokenizer_profile or _load_mail_tokenizer_profile()
    query_tokenization = profile.analyze(query_text)
    terms = (
        _tokenize(query_text)
        if _is_target_mail_tokenizer_profile(profile)
        else set(query_tokenization.tokens)
    )
    protected_query_tokens = {span.exact_token for span in query_tokenization.protected_identifiers}
    snippets: list[dict[str, Any]] = []
    for bundle in bundles:
        if snippet_index_by_bundle_id is None:
            snippet_index = _build_snippet_index(
                bundle,
                tokenizer_profile=profile,
            )
        else:
            snippet_index = snippet_index_by_bundle_id.get(bundle.mail_evidence_bundle_id)
            if snippet_index is None:
                if defer_index_build:
                    snippets.extend(
                        _scan_mail_bundle_source_text(
                            bundle,
                            terms=terms,
                            protected_query_tokens=protected_query_tokens,
                            limit=limit,
                            tokenizer_profile=profile,
                        )
                    )
                    continue
                snippet_index = _build_snippet_index(
                    bundle,
                    tokenizer_profile=profile,
                )
        _require_matching_profile(snippet_index, profile)
        candidate_indexes = _candidate_snippet_indexes(snippet_index, terms)
        for snippet_index_value in candidate_indexes:
            indexed = snippet_index.snippets[snippet_index_value]
            if protected_query_tokens and not protected_query_tokens.issubset(
                indexed.searchable_tokens
            ):
                continue
            matched_terms = sorted(term for term in terms if term in indexed.searchable_tokens)
            if not matched_terms:
                continue
            snippets.append(
                _safe_snippet(
                    {
                        **indexed.payload,
                        "score": len(matched_terms),
                        "matched_terms": matched_terms,
                    }
                )
            )
    return sorted(
        snippets,
        key=lambda snippet: (-int(snippet["score"]), str(snippet["source_observation_id"])),
    )[:limit]


def _scan_mail_bundle_source_text(
    bundle: MailEvidenceBundle,
    *,
    terms: set[str],
    protected_query_tokens: set[str],
    limit: int,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> list[dict[str, Any]]:
    """Scan bounded source text without materializing a posting index."""

    if limit == 0 or not terms:
        return []
    messages_by_id = {message.email_message_id: message for message in bundle.messages}
    snippets: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(bundle.body_segments):
        if segment_index >= _LAZY_SOURCE_SCAN_SEGMENT_LIMIT:
            break
        message = messages_by_id.get(segment.email_message_id)
        searchable = " ".join(
            item
            for item in (
                segment.text,
                message.subject if message else None,
                message.sender if message else None,
                message.message_id if message else None,
            )
            if isinstance(item, str)
        )
        tokenization = tokenizer_profile.analyze(searchable)
        searchable_tokens = (
            _tokenize(searchable)
            if _is_target_mail_tokenizer_profile(tokenizer_profile)
            else set(tokenization.tokens)
        )
        if protected_query_tokens and not protected_query_tokens.issubset(searchable_tokens):
            continue
        matched_terms = sorted(term for term in terms if term in searchable_tokens)
        if not matched_terms:
            continue
        snippets.append(
            _safe_snippet(
                {
                    "source_type": "mail_body_segment",
                    "source_observation_id": segment.source_observation_id,
                    "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
                    "email_message_id": segment.email_message_id,
                    "message_occurrence_id": segment.message_occurrence_id,
                    "subject": message.subject if message else None,
                    "snippet": segment.text,
                    "score": len(matched_terms),
                    "matched_terms": matched_terms,
                }
            )
        )
        if len(snippets) >= limit:
            break
    return snippets


def _source_mail_observation_match(
    observation: Observation,
    *,
    query_terms: set[str],
    required_terms: tuple[str, ...] | None,
    protected_query_tokens: set[str],
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile | None,
    deadline_monotonic: float | None = None,
) -> tuple[str, ...] | None:
    """Match one source-owned mail Observation without exposing raw payloads."""

    _check_revision_source_deadline(deadline_monotonic)
    if observation.modality != "mail" or (required_terms is None and not query_terms):
        return None
    payload = to_plain(observation.payload or {})
    searchable_values = [observation.text]
    if isinstance(payload, Mapping):
        for field_name in (
            "subject",
            "normalized_subject",
            "sender",
            "from",
            "to",
            "cc",
            "header_name",
            "header_value",
            "body_excerpt",
        ):
            value = payload.get(field_name)
            if isinstance(value, str) and value:
                searchable_values.append(value)
    searchable = " ".join(value for value in searchable_values if isinstance(value, str) and value)
    _check_revision_source_deadline(deadline_monotonic)
    if required_terms is not None:
        normalized_searchable = _normalize_mail_relevance_text(searchable)
        if not all(term in normalized_searchable for term in required_terms):
            return None
    else:
        if tokenizer_profile is None:
            return None
        searchable_tokens = set(tokenizer_profile.analyze(searchable).tokens)
        _check_revision_source_deadline(deadline_monotonic)
        # A legacy mail request without an explicit ``required_terms`` keeps
        # the historical all-lexical-term contract.  The source fallback is
        # not an open-ended relevance reranker: accepting an Observation that
        # matches only part of the query would make the initial citation look
        # verified and suppress the bounded source recheck.  Query-agent
        # action words therefore remain part of the legacy lexical contract;
        # callers that need grounded spans must supply ``required_terms``.
        if not query_terms.issubset(searchable_tokens):
            return None
    if protected_query_tokens:
        if tokenizer_profile is None:
            return None
        searchable_tokens = set(tokenizer_profile.analyze(searchable).tokens)
        _check_revision_source_deadline(deadline_monotonic)
        if not protected_query_tokens.issubset(searchable_tokens):
            return None
    if required_terms is not None:
        return required_terms
    return tuple(sorted(query_terms.intersection(searchable_tokens)))


def _validate_required_mail_terms(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 8
        or any(not isinstance(term, str) or not term.strip() or len(term) > 80 for term in value)
    ):
        raise ContractValidationError("mail required terms are invalid")
    normalized = tuple(_normalize_mail_relevance_text(term.strip()) for term in value)
    if any(not term for term in normalized):
        raise ContractValidationError("mail required terms are invalid")
    return normalized


def _normalize_mail_relevance_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _candidate_snippet_indexes(
    snippet_index: _MailSnippetIndex,
    terms: set[str],
    *,
    allowed_source_item_ids: frozenset[_SourceItemIdentity] | None = None,
) -> tuple[int, ...]:
    if allowed_source_item_ids is not None and not allowed_source_item_ids:
        return ()
    identifier_anchors = {term for term in terms if _PROTECTED_IDENTIFIER_TOKEN.fullmatch(term)}
    candidate_terms = identifier_anchors or terms
    indexes: set[int] = set()
    for term in candidate_terms:
        indexes.update(snippet_index.snippet_indexes_by_token.get(term, ()))
    if allowed_source_item_ids is not None:
        allowed_indexes: set[int] = set()
        for source_item_id in allowed_source_item_ids:
            allowed_indexes.update(_source_item_indexes(snippet_index, source_item_id))
        indexes.intersection_update(allowed_indexes)
    return tuple(sorted(indexes))


def _build_snippet_index(
    bundle: MailEvidenceBundle,
    *,
    worker_count: int = 1,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile | None = None,
    source_observation_hashes: Mapping[str, str] | None = None,
    observation_snapshot_fingerprint: str | None = None,
) -> _MailSnippetIndex:
    profile = tokenizer_profile or _load_mail_tokenizer_profile()
    messages_by_id = {message.email_message_id: message for message in bundle.messages}
    resolved_workers = _validated_index_worker_count(worker_count)
    parallel_tokens = None
    if resolved_workers > 1:
        if not _is_target_mail_tokenizer_profile(profile):
            raise ContractValidationError("parallel mail indexing requires the frozen profile")
        parallel_tokens = dict(
            _parallel_tokenized_segments(bundle, messages_by_id, worker_count=resolved_workers)
        )
    indexed: list[_IndexedMailSnippet] = []
    indexes_by_token: dict[str, list[int]] = {}
    protected_identifier_count = 0
    for segment_index, segment in enumerate(bundle.body_segments):
        message = messages_by_id.get(segment.email_message_id)
        searchable = " ".join(
            item
            for item in (
                segment.text,
                message.subject if message else None,
                message.sender if message else None,
                message.message_id if message else None,
            )
            if isinstance(item, str)
        )
        tokenization = profile.analyze(searchable)
        tokens = (
            _tokenize(searchable)
            if _is_target_mail_tokenizer_profile(profile)
            else set(tokenization.tokens)
        )
        if parallel_tokens is not None:
            tokens = set(parallel_tokens.get(segment_index, ()))
        protected_tokens = frozenset(
            span.exact_token for span in tokenization.protected_identifiers
        )
        if not tokens:
            continue
        protected_identifier_count += len(protected_tokens)
        snippet_index = len(indexed)
        indexed.append(
            _IndexedMailSnippet(
                mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
                searchable_tokens=tokens,
                source_item_id=segment.email_message_id,
                source_item_key=_source_item_key(bundle, segment.email_message_id),
                dense_evidence_text=searchable,
                payload={
                    **_segment_payload(bundle, segment, message),
                    "source_type": "mail_body_segment",
                    "source_observation_id": segment.source_observation_id,
                    "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
                    "email_message_id": segment.email_message_id,
                    "message_occurrence_id": segment.message_occurrence_id,
                    "subject": message.subject if message else None,
                    "snippet": segment.text,
                },
                source_observation_hash=(
                    source_observation_hashes.get(segment.source_observation_id)
                    if source_observation_hashes is not None
                    else None
                ),
                protected_identifier_tokens=protected_tokens,
            )
        )
        for token in tokens:
            indexes_by_token.setdefault(token, []).append(snippet_index)
    candidate_manifest_fingerprint = sha256_json(
        [
            {
                "source_observation_hash": snippet.source_observation_hash,
                "candidate_token_hashes": sorted(
                    sha256_json(token) for token in snippet.searchable_tokens
                ),
                "protected_identifier_token_hashes": sorted(
                    sha256_json(token) for token in snippet.protected_identifier_tokens
                ),
                "dense_evidence_text_hash": sha256_json(snippet.dense_evidence_text),
            }
            for snippet in indexed
        ]
    )
    index_fingerprint = sha256_json(
        {
            "observation_snapshot_fingerprint": observation_snapshot_fingerprint,
            "profile_fingerprint": profile.profile_fingerprint,
            "candidate_manifest_fingerprint": candidate_manifest_fingerprint,
            "postings": {
                sha256_json(token): tuple(indexes)
                for token, indexes in sorted(indexes_by_token.items())
            },
        }
    )
    source_indexes = {}
    source_postings = {}
    for number, item in enumerate(indexed):
        source_indexes.setdefault(item.source_item_key, []).append(number)
        for token in _indexable_tokens(item.dense_evidence_text):
            source_postings.setdefault(token, set()).add(item.source_item_key)
    return _MailSnippetIndex(
        snippets=tuple(indexed),
        source_item_ids_by_token=_immutable_posting_map(
            {k: frozenset(v) for k, v in source_postings.items()}
        ),
        snippet_indexes_by_source_item_id=_immutable_posting_map(
            {k: tuple(v) for k, v in source_indexes.items()}
        ),
        subject_by_source_item_id=_immutable_posting_map(
            {
                _source_item_key(bundle, item.email_message_id): item.subject or ""
                for item in bundle.messages
            }
        ),
        snippet_indexes_by_token={
            token: tuple(indexes) for token, indexes in indexes_by_token.items()
        },
        profile_fingerprint=profile.profile_fingerprint,
        observation_snapshot_fingerprint=observation_snapshot_fingerprint,
        candidate_manifest_fingerprint=candidate_manifest_fingerprint,
        index_fingerprint=index_fingerprint,
        protected_identifier_count=protected_identifier_count,
    )


def source_occurrence_lineage_from_observation(
    observation: Observation,
    *,
    authorized_source: AuthorizedSemanticSource,
) -> SourceOccurrenceLineage:
    """Derive typed occurrence lineage using only the validated source-kind schema."""

    if not isinstance(observation, Observation):
        raise ContractValidationError("source occurrence lineage requires an Observation")
    validated = Observation.from_dict(observation.to_dict())
    return _source_occurrence_lineage_from_snapshot(
        validated,
        authorized_source=authorized_source,
    )


def _source_occurrence_lineage_from_snapshot(
    validated: Observation,
    *,
    authorized_source: AuthorizedSemanticSource,
) -> SourceOccurrenceLineage:
    if not isinstance(authorized_source, AuthorizedSemanticSource):
        raise ContractValidationError("authorized Observation source is invalid")
    if (
        authorized_source.authorizes_source_kind(AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND)
        and validated.modality == "mail"
    ):
        if validated.modality != "mail":
            raise ContractValidationError("mail source occurrence modality mismatch")
        message_occurrence_id = validated.location.get("message_occurrence_id")
        if not isinstance(message_occurrence_id, str) or not message_occurrence_id:
            raise ContractValidationError("mail source occurrence lineage is missing")
        safe_public_string(message_occurrence_id, "message_occurrence_id")
        return MailMessageOccurrenceLineage(
            source_observation_id=validated.observation_id,
            message_occurrence_id=message_occurrence_id,
        )
    if (
        authorized_source.authorizes_source_kind(GITHUB_PROJECT_OBSERVATION_SOURCE_KIND)
        and validated.modality == "project"
    ):
        if validated.modality != "project" or validated.observation_type not in {
            "issue_record",
            "top_level_issue_comment",
        }:
            raise ContractValidationError("GitHub source occurrence schema mismatch")
        location = validated.location
        payload = validated.payload or {}
        source_local_key = location.get("source_local_key")
        source_record_fingerprint = location.get("source_record_fingerprint")
        record_kind = location.get("record_kind")
        parent_source_local_key = location.get("parent_source_local_key")
        if (
            not isinstance(source_local_key, str)
            or not source_local_key
            or not isinstance(source_record_fingerprint, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", source_record_fingerprint) is None
            or record_kind != validated.observation_type
            or payload.get("source_local_key") != source_local_key
            or payload.get("source_record_fingerprint") != source_record_fingerprint
            or payload.get("record_kind") != record_kind
        ):
            raise ContractValidationError("GitHub source occurrence lineage is invalid")
        if record_kind == "issue_record":
            if parent_source_local_key not in {None, ""} or payload.get(
                "parent_source_local_key"
            ) not in {None, ""}:
                raise ContractValidationError("GitHub issue occurrence parent is invalid")
            parent_source_local_key = None
        elif (
            not isinstance(parent_source_local_key, str)
            or not parent_source_local_key
            or payload.get("parent_source_local_key") != parent_source_local_key
        ):
            raise ContractValidationError("GitHub comment parent lineage is missing")
        for field_name, value in (
            ("source_local_key", source_local_key),
            ("record_kind", str(record_kind)),
        ):
            safe_public_string(value, field_name)
        if parent_source_local_key is not None:
            safe_public_string(parent_source_local_key, "parent_source_local_key")
        return GitHubProjectOccurrenceLineage(
            source_observation_id=validated.observation_id,
            record_kind=str(record_kind),
            source_local_key=source_local_key,
            source_record_fingerprint=source_record_fingerprint,
            parent_source_local_key=parent_source_local_key,
        )
    if validated.modality == "text":
        if not authorized_source.authorizes_source_kind(AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND):
            raise ContractValidationError("text document source kind is unauthorized")
        if validated.observation_type not in {"heading", "paragraph"}:
            raise ContractValidationError("text document occurrence type is unsupported")
        location = validated.location
        if not isinstance(location, Mapping) or set(location) != {
            "line_start",
            "line_end",
        }:
            raise ContractValidationError("text document line location is invalid")
        line_start = location.get("line_start")
        line_end = location.get("line_end")
        _validate_text_line_range(line_start, line_end)
        if not authorized_permission_scope_matches(
            validated.permission_scope,
            authorized_source=authorized_source,
            source_kind=AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
        ):
            raise ContractValidationError("text document permission scope mismatch")
        asset_id = validated.asset_id
        extractor_run_id = validated.extractor_run_id
        if (
            not isinstance(asset_id, str)
            or not asset_id
            or not isinstance(extractor_run_id, str)
            or not extractor_run_id
        ):
            raise ContractValidationError("text document native identity is missing")
        return TextDocumentOccurrenceLineage(
            source_observation_id=validated.observation_id,
            asset_id=asset_id,
            extractor_run_id=extractor_run_id,
            line_start=line_start,
            line_end=line_end,
        )
    raise ContractValidationError("semantic query source kind is unsupported")


def _validate_text_line_range(line_start: Any, line_end: Any) -> None:
    if (
        isinstance(line_start, bool)
        or not isinstance(line_start, int)
        or isinstance(line_end, bool)
        or not isinstance(line_end, int)
        or line_start < 1
        or line_end < line_start
    ):
        raise ContractValidationError("text document line range is invalid")


def build_authorized_observation_snippet_from_bound_record(
    observation: Observation,
    *,
    authorized_source: AuthorizedSemanticSource,
    occurrence_lineage: SourceOccurrenceLineage,
    expected_observation_hash: str,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    parent_observations: Sequence[Observation] = (),
) -> IndexedObservationSnippet:
    """Project one authority-read record with genuine, bounded parent context.

    This verifies local occurrence/permission lineage, not corpus completeness.
    Completeness remains bound to the caller's prepared source authority.
    """
    if len(parent_observations) > 1:
        raise ContractValidationError("record projection parent context exceeds bound")
    if sha256_json(observation.to_dict()) != expected_observation_hash:
        raise ContractValidationError("record projection source hash mismatch")
    context = {item.observation_id: item for item in parent_observations}
    if observation.observation_id in context:
        raise ContractValidationError("record projection parent identity mismatch")
    context[observation.observation_id] = observation
    lineages = (
        *(
            source_occurrence_lineage_from_observation(
                parent,
                authorized_source=authorized_source,
            )
            for parent in parent_observations
        ),
        occurrence_lineage,
    )
    normalized = _normalized_authorized_observation_lineages_from_snapshot(
        context,
        authorized_source=authorized_source,
        occurrence_lineages=lineages,
    )
    if occurrence_lineage not in normalized:
        raise ContractValidationError("record projection occurrence binding mismatch")
    return _snippet_from_validated_observation(
        observation,
        authorized_source=authorized_source,
        lineage=occurrence_lineage,
        observation_hash=expected_observation_hash,
        tokenizer_profile=tokenizer_profile,
    )


def _snippet_from_validated_observation(
    observation: Observation,
    *,
    authorized_source: AuthorizedSemanticSource,
    lineage: SourceOccurrenceLineage,
    observation_hash: str,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> IndexedObservationSnippet:
    _validate_observation_source_scope(
        observation,
        authorized_source=authorized_source,
        source_kind=lineage.source_kind,
    )
    if not authorized_source.authorizes_source_kind(lineage.source_kind):
        raise ContractValidationError("Observation index source occurrence mismatch")
    searchable = _source_neutral_searchable_text(
        observation,
        source_kind=lineage.source_kind,
    )
    tokenization = tokenizer_profile.analyze(searchable)
    tokens = set(tokenization.tokens)
    if not tokens:
        raise ContractValidationError("Observation index has no searchable evidence")
    payload = {
        "source_type": observation.observation_type,
        "source_kind": lineage.source_kind,
        "source_observation_id": observation.observation_id,
        "source_occurrence_hash": sha256_json(lineage.occurrence_id),
        "source_occurrence_kind": lineage.occurrence_kind,
        "snippet": _redact_mail_public_text(observation.text or observation.caption or "")[0],
    }
    if lineage.parent_occurrence_id is not None:
        payload["parent_source_occurrence_hash"] = sha256_json(lineage.parent_occurrence_id)
    if isinstance(
        lineage, MailAttachmentChildOccurrenceLineage
    ) and observation.observation_type in {"paragraph", "heading", "list_item"}:
        payload["attachment_locator"] = {
            "block_type": observation.observation_type,
            "child_asset_id": lineage.child_asset_id,
            "parent_attachment_observation_id": lineage.parent_attachment_observation_id,
            **{
                key: value
                for key, value in observation.location.items()
                if key
                in {
                    "page",
                    "paragraph_index",
                    "block_index",
                    "slide",
                    "shape_index",
                    "list_item_index",
                }
                and type(value) is int
                and value >= 1
            },
        }
    return _IndexedObservationSnippet(
        source_access_fingerprint=authorized_source.authorization_fingerprint,
        searchable_tokens=tokens,
        dense_evidence_text=searchable,
        payload=payload,
        source_observation_hash=observation_hash,
        protected_identifier_tokens=frozenset(
            span.exact_token for span in tokenization.protected_identifiers
        ),
    )


def build_authorized_observation_snippet_index(
    observations: Sequence[Observation],
    *,
    authorized_source: AuthorizedSemanticSource,
    occurrence_lineages: Sequence[SourceOccurrenceLineage],
    authorized_observation_hash_by_id: Mapping[str, str],
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> tuple[ObservationSnippetIndex, AuthorizedObservationIndexBuildManifest]:
    """Build a deterministic source-neutral index from authorized Observations."""

    if not isinstance(authorized_source, AuthorizedSemanticSource):
        raise ContractValidationError("authorized Observation source is invalid")
    if not isinstance(tokenizer_profile, MailCandidateAdmissionTokenizerProfile):
        raise ContractValidationError("Observation index tokenizer profile is invalid")
    normalized_by_id: dict[str, Observation] = {}
    observation_hash_by_id: dict[str, str] = {}
    for observation in observations:
        if not isinstance(observation, Observation):
            raise ContractValidationError("Observation index requires Observation records")
        serialized_snapshot = observation.to_dict()
        validated = Observation.from_dict(serialized_snapshot)
        if validated.observation_id in normalized_by_id:
            raise ContractValidationError("Observation index has duplicate observation ids")
        normalized_by_id[validated.observation_id] = observation
        observation_hash_by_id[validated.observation_id] = sha256_json(serialized_snapshot)
    if not normalized_by_id:
        raise ContractValidationError("Observation index requires observations")
    supplied_authorized_hashes = dict(authorized_observation_hash_by_id)
    if (
        set(supplied_authorized_hashes) != set(normalized_by_id)
        or supplied_authorized_hashes != observation_hash_by_id
    ):
        raise ContractValidationError("Observation index authorization binding mismatch")

    lineage_by_observation_id = {
        lineage.source_observation_id: lineage
        for lineage in _normalized_authorized_observation_lineages_from_snapshot(
            normalized_by_id,
            authorized_source=authorized_source,
            occurrence_lineages=occurrence_lineages,
        )
    }
    _validate_source_neutral_attachment_observation_coverage_from_snapshot(
        normalized_by_id,
        observation_hash_by_id=observation_hash_by_id,
        matched_child_observation_hashes=(),
    )

    indexed: list[_IndexedObservationSnippet] = []
    indexes_by_token: dict[str, list[int]] = {}
    ordered_observation_hashes: list[str] = []
    ordered_lineage_fingerprints: list[str] = []
    permission_fingerprints: list[str] = []
    protected_identifier_count = 0
    for observation_id in sorted(normalized_by_id):
        observation = normalized_by_id[observation_id]
        lineage = lineage_by_observation_id[observation_id]
        snippet = _snippet_from_validated_observation(
            observation,
            authorized_source=authorized_source,
            lineage=lineage,
            observation_hash=observation_hash_by_id[observation_id],
            tokenizer_profile=tokenizer_profile,
        )
        tokens = snippet.searchable_tokens
        protected_tokens = snippet.protected_identifier_tokens
        snippet_index = len(indexed)
        permission_fingerprint = sha256_json(to_plain(observation.permission_scope))
        indexed.append(snippet)
        for token in tokens:
            indexes_by_token.setdefault(token, []).append(snippet_index)
        ordered_observation_hashes.append(observation_hash_by_id[observation_id])
        ordered_lineage_fingerprints.append(lineage.lineage_fingerprint)
        permission_fingerprints.append(permission_fingerprint)
        protected_identifier_count += len(protected_tokens)

    observation_snapshot_fingerprint = sha256_json(
        {
            "schema_version": 1,
            "source_access_fingerprint": (authorized_source.authorization_fingerprint),
            "ordered_observation_hashes": ordered_observation_hashes,
            "observation_count": len(ordered_observation_hashes),
        }
    )
    occurrence_lineage_fingerprint = sha256_json(ordered_lineage_fingerprints)
    permission_set_fingerprint = sha256_json(sorted(permission_fingerprints))
    candidate_manifest_fingerprint = _sha256_streamed_canonical_list(
        (
            {
                "source_observation_hash": snippet.source_observation_hash,
                "source_occurrence_lineage_fingerprint": (ordered_lineage_fingerprints[index]),
                "candidate_token_hashes": sorted(
                    sha256_json(token) for token in snippet.searchable_tokens
                ),
                "protected_identifier_token_hashes": sorted(
                    sha256_json(token) for token in snippet.protected_identifier_tokens
                ),
                "dense_evidence_text_hash": sha256_json(snippet.dense_evidence_text),
            }
            for index, snippet in enumerate(indexed)
        )
    )
    index_fingerprint = _sha256_streamed_authorized_observation_index(
        source_access_fingerprint=authorized_source.authorization_fingerprint,
        observation_snapshot_fingerprint=observation_snapshot_fingerprint,
        occurrence_lineage_fingerprint=occurrence_lineage_fingerprint,
        permission_set_fingerprint=permission_set_fingerprint,
        profile_fingerprint=tokenizer_profile.profile_fingerprint,
        candidate_manifest_fingerprint=candidate_manifest_fingerprint,
        indexes_by_token=indexes_by_token,
    )
    snippet_index = _ObservationSnippetIndex(
        snippets=tuple(indexed),
        snippet_indexes_by_token={
            token: tuple(indexes) for token, indexes in indexes_by_token.items()
        },
        profile_fingerprint=tokenizer_profile.profile_fingerprint,
        source_access_fingerprint=authorized_source.authorization_fingerprint,
        observation_snapshot_fingerprint=observation_snapshot_fingerprint,
        occurrence_lineage_fingerprint=occurrence_lineage_fingerprint,
        candidate_manifest_fingerprint=candidate_manifest_fingerprint,
        index_fingerprint=index_fingerprint,
        protected_identifier_count=protected_identifier_count,
    )
    manifest = AuthorizedObservationIndexBuildManifest(
        artifact_id="formowl_authorized_observation_index_manifest_v1",
        schema_version=1,
        input_kind="authorized_observations_with_typed_occurrences",
        source_kind_hash=sha256_json(authorized_source.source_kind),
        occurrence_schema_hash=sha256_json(authorized_source.occurrence_schema_id),
        source_access_fingerprint=(authorized_source.authorization_fingerprint),
        permission_set_fingerprint=permission_set_fingerprint,
        occurrence_lineage_fingerprint=occurrence_lineage_fingerprint,
        observation_snapshot_fingerprint=observation_snapshot_fingerprint,
        observation_count=len(normalized_by_id),
        indexed_observation_count=len(indexed),
        indexed_snippet_count=len(indexed),
        admitted_candidate_count=sum(len(snippet.searchable_tokens) for snippet in indexed),
        protected_identifier_count=protected_identifier_count,
        candidate_manifest_fingerprint=candidate_manifest_fingerprint,
        index_fingerprint=index_fingerprint,
        query_profile_fingerprint=tokenizer_profile.profile_fingerprint,
        evidence_profile_fingerprint=tokenizer_profile.profile_fingerprint,
        missing_lineage_count=0,
    )
    manifest.to_safe_dict()
    return snippet_index, manifest


def _sha256_streamed_canonical_list(values: Iterable[Any]) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for value in values:
        if first:
            first = False
        else:
            digest.update(b",")
        digest.update(canonical_json(value).encode("utf-8"))
    digest.update(b"]")
    return f"sha256:{digest.hexdigest()}"


def _sha256_streamed_authorized_observation_index(
    *,
    source_access_fingerprint: str,
    observation_snapshot_fingerprint: str,
    occurrence_lineage_fingerprint: str,
    permission_set_fingerprint: str,
    profile_fingerprint: str,
    candidate_manifest_fingerprint: str,
    indexes_by_token: Mapping[str, Sequence[int]],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"{")
    for index, (key, value) in enumerate(
        (
            ("candidate_manifest_fingerprint", candidate_manifest_fingerprint),
            ("observation_snapshot_fingerprint", observation_snapshot_fingerprint),
            ("occurrence_lineage_fingerprint", occurrence_lineage_fingerprint),
            ("permission_set_fingerprint", permission_set_fingerprint),
        )
    ):
        if index:
            digest.update(b",")
        digest.update(canonical_json(key).encode("utf-8"))
        digest.update(b":")
        digest.update(canonical_json(value).encode("utf-8"))

    digest.update(b',"postings":{')
    postings_by_hash: dict[str, Sequence[int]] = {}
    for token, indexes in sorted(indexes_by_token.items()):
        postings_by_hash[sha256_json(token)] = indexes
    for posting_index, token_hash in enumerate(sorted(postings_by_hash)):
        if posting_index:
            digest.update(b",")
        digest.update(canonical_json(token_hash).encode("utf-8"))
        digest.update(b":[")
        for occurrence_index, snippet_index in enumerate(postings_by_hash[token_hash]):
            if occurrence_index:
                digest.update(b",")
            digest.update(str(snippet_index).encode("ascii"))
        digest.update(b"]")
    digest.update(b"}")

    for key, value in (
        ("profile_fingerprint", profile_fingerprint),
        ("source_access_fingerprint", source_access_fingerprint),
    ):
        digest.update(b",")
        digest.update(canonical_json(key).encode("utf-8"))
        digest.update(b":")
        digest.update(canonical_json(value).encode("utf-8"))
    digest.update(b"}")
    return f"sha256:{digest.hexdigest()}"


def _validate_observation_source_scope(
    observation: Observation,
    *,
    authorized_source: AuthorizedSemanticSource,
    source_kind: str,
) -> None:
    permission_scope = to_plain(observation.permission_scope)
    if not isinstance(permission_scope, dict):
        raise ContractValidationError("Observation index permission scope is invalid")
    scope_type = permission_scope.get("scope_type")
    scope_id = permission_scope.get("scope_id")
    if not isinstance(scope_type, str) or not isinstance(scope_id, str) or not scope_id:
        raise ContractValidationError("Observation index permission scope is invalid")
    legacy_mail_workspace_scope = (
        source_kind == AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
        and scope_type == "workspace"
        and scope_id == authorized_source.workspace_id
    )
    if (
        scope_id not in authorized_source.source_scope_ids and not legacy_mail_workspace_scope
    ) or not authorized_permission_scope_matches(
        permission_scope,
        authorized_source=authorized_source,
        source_kind=source_kind,
    ):
        raise ContractValidationError("Observation index permission scope mismatch")


def _source_neutral_searchable_text(
    observation: Observation,
    *,
    source_kind: str,
) -> str:
    values: list[str] = [
        value
        for value in (
            observation.text,
            observation.caption,
            observation.observation_type,
            observation.modality,
        )
        if isinstance(value, str) and value
    ]
    if source_kind == GITHUB_PROJECT_OBSERVATION_SOURCE_KIND:
        payload = observation.payload or {}
        for field_name in (
            "record_kind",
            "issue_number",
            "state",
            "state_reason",
            "created_at",
            "updated_at",
            "closed_at",
            "label_names",
            "source_native_issue_references",
        ):
            value = payload.get(field_name)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                values.append(str(value))
            elif isinstance(value, list):
                values.extend(
                    str(item)
                    for item in value
                    if isinstance(item, (str, int, float)) and not isinstance(item, bool)
                )
    elif (
        source_kind == AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
        and observation.modality == "document"
        and observation.observation_type in _ATTACHMENT_CHILD_OBSERVATION_TYPES
    ):
        table_structure = (observation.payload or {}).get("table_structure")
        if isinstance(table_structure, Mapping):
            for field_name in ("table_name", "column_name"):
                value = table_structure.get(field_name)
                if isinstance(value, str) and value:
                    values.append(value)
            columns = table_structure.get("columns")
            if isinstance(columns, list):
                values.extend(
                    str(column["name"])
                    for column in columns
                    if isinstance(column, Mapping)
                    and isinstance(column.get("name"), str)
                    and column["name"]
                )
    return "\n".join(values)


def build_existing_observation_snippet_index(
    observations: Sequence[Observation],
    *,
    bundle: MailEvidenceBundle,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> tuple[MailSnippetIndex, ExistingObservationIndexBuildManifest]:
    """Re-tokenize a bundle from existing Observation records only."""

    normalized: list[Observation] = []
    observation_ids: set[str] = set()
    ordered_observation_hashes: list[str] = []
    source_observation_hashes: dict[str, str] = {}
    for observation in observations:
        if not isinstance(observation, Observation):
            raise ContractValidationError("existing observation index requires Observation records")
        validated = Observation.from_dict(observation.to_dict())
        if validated.observation_id in observation_ids:
            raise ContractValidationError(
                "existing observation index has duplicate observation ids"
            )
        observation_ids.add(validated.observation_id)
        observation_hash = sha256_json(validated.to_dict())
        ordered_observation_hashes.append(observation_hash)
        source_observation_hashes[validated.observation_id] = observation_hash
        normalized.append(validated)
    if not normalized:
        raise ContractValidationError("existing observation index requires observations")

    body_observation_ids = {
        observation.observation_id
        for observation in normalized
        if observation.modality == "mail" and observation.observation_type == "email_body_segment"
    }
    indexed_source_observation_ids = {
        segment.source_observation_id for segment in bundle.body_segments
    }
    missing_lineage = sorted(indexed_source_observation_ids - observation_ids)
    unindexed_body_observations = sorted(body_observation_ids - indexed_source_observation_ids)
    if missing_lineage or unindexed_body_observations:
        raise ContractValidationError("existing observation index lineage is incomplete")

    observation_snapshot_fingerprint = sha256_json(
        {
            "schema_version": 1,
            "ordered_observation_hashes": ordered_observation_hashes,
            "observation_count": len(normalized),
        }
    )
    snippet_index = _build_snippet_index(
        bundle,
        tokenizer_profile=tokenizer_profile,
        source_observation_hashes=source_observation_hashes,
        observation_snapshot_fingerprint=observation_snapshot_fingerprint,
    )
    admitted_candidate_count = sum(
        len(snippet.searchable_tokens) for snippet in snippet_index.snippets
    )
    manifest = ExistingObservationIndexBuildManifest(
        artifact_id="formowl_existing_observation_mail_index_manifest_v1",
        schema_version=1,
        input_kind="existing_observations_only",
        observation_snapshot_fingerprint=observation_snapshot_fingerprint,
        observation_count=len(normalized),
        indexed_observation_count=len(indexed_source_observation_ids),
        indexed_snippet_count=len(snippet_index.snippets),
        admitted_candidate_count=admitted_candidate_count,
        protected_identifier_count=snippet_index.protected_identifier_count,
        candidate_manifest_fingerprint=str(snippet_index.candidate_manifest_fingerprint),
        index_fingerprint=str(snippet_index.index_fingerprint),
        query_profile_fingerprint=tokenizer_profile.profile_fingerprint,
        evidence_profile_fingerprint=tokenizer_profile.profile_fingerprint,
        raw_pst_read_count=0,
        pst_parser_invocation_count=0,
        new_extractor_run_count=0,
        missing_lineage_count=0,
    )
    manifest.to_safe_dict()
    return snippet_index, manifest


def authorize_mail_evidence_bundles(
    bundles: Sequence[MailEvidenceBundle],
    *,
    requester_user_id: str,
    workspace_id: str,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> tuple[MailEvidenceBundle, ...]:
    """Filter bundles before any query candidate or index materialization."""

    if not isinstance(requester_user_id, str) or not requester_user_id.strip():
        raise ContractValidationError("requester_user_id is required")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ContractValidationError("workspace_id is required")
    safe_public_string(requester_user_id, "requester_user_id")
    safe_public_string(workspace_id, "workspace_id")
    resolved_now = now or "9999-12-31T23:59:59+00:00"
    grant_objects = normalize_grants(grants)
    return tuple(
        bundle
        for bundle in bundles
        if bundle.mail_import_session.workspace_id == workspace_id
        and _can_read_bundle(
            bundle,
            requester_user_id=requester_user_id,
            grants=grant_objects,
            now=resolved_now,
        )
    )


def require_issue56_target_tokenizer_profile(
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    *,
    expected_profile_fingerprint: str,
) -> None:
    """Fail closed unless the available profile is the pinned Issue #56 target."""

    if not isinstance(tokenizer_profile, MailCandidateAdmissionTokenizerProfile):
        raise ContractValidationError("issue56 target tokenizer profile is unavailable")
    if tokenizer_profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID:
        raise ContractValidationError("issue56 target tokenizer profile is unavailable")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_profile_fingerprint):
        raise ContractValidationError("issue56 tokenizer profile fingerprint is invalid")
    if tokenizer_profile.profile_fingerprint != expected_profile_fingerprint:
        raise ContractValidationError("mail evidence tokenizer profile mismatch")
    try:
        tokenizer_profile.analyze("Issue56 交期 profile readiness")
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ContractValidationError("issue56 target tokenizer profile is unavailable") from exc


def _safe_snippet(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in payload.items() if value is not None}
    redaction_count = 0
    for field_name in ("subject", "snippet"):
        value = cleaned.get(field_name)
        if not isinstance(value, str):
            continue
        redacted, field_redaction_count = _redact_mail_public_text(value)
        cleaned[field_name] = redacted
        redaction_count += field_redaction_count
    if redaction_count:
        cleaned["content_redacted"] = True
    assert_public_payload_safe(cleaned, "mail_evidence_snippet")
    return cleaned


def _redact_mail_public_text(value: str) -> tuple[str, int]:
    # Remove complete credential/traceback spans before generic locator
    # redaction, which otherwise can hide their delimiters but leave values.
    redacted, count = redact_authorized_evidence_text(value)
    redacted, locator_count = redact_public_raw_references(redacted)
    count += locator_count
    for pattern in _SEMANTIC_GATEWAY_TEXT_REDACTIONS:
        redacted, replacement_count = pattern.subn("[redacted_mail_evidence]", redacted)
        count += replacement_count
    return redacted, count


def _citation_for_snippet(
    snippet: dict[str, Any],
    *,
    mail_evidence_bundle_id: str | None = None,
) -> dict[str, Any]:
    identity = {
        "mail_import_session_id": snippet["mail_import_session_id"],
        "source_observation_id": snippet["source_observation_id"],
    }
    if mail_evidence_bundle_id is not None:
        identity.update(
            {
                "mail_evidence_bundle_id": mail_evidence_bundle_id,
                "email_message_id": snippet["email_message_id"],
                "message_occurrence_id": snippet["message_occurrence_id"],
            }
        )
    citation = {
        "citation_id": "mailcitation_" + sha256_json(identity)[-24:],
        "source_type": snippet["source_type"],
        "source_observation_id": snippet["source_observation_id"],
        "mail_import_session_id": snippet["mail_import_session_id"],
        "email_message_id": snippet["email_message_id"],
        "message_occurrence_id": snippet["message_occurrence_id"],
    }
    assert_public_payload_safe(citation, "mail_evidence_citation")
    return citation


def _can_read_bundle(
    bundle: MailEvidenceBundle,
    *,
    requester_user_id: str,
    grants: Sequence[Grant],
    now: str,
) -> bool:
    if requester_user_id == bundle.mail_import_session.owner_user_id:
        return True
    for grant in grants:
        if grant.owner_user_id != bundle.mail_import_session.owner_user_id:
            continue
        if grant.grantee_user_id != requester_user_id:
            continue
        if grant.permission not in _MAIL_EVIDENCE_PERMISSIONS:
            continue
        if grant.revoked_at or grant_expired(grant, now):
            continue
        if (
            grant.scope_type == "workspace"
            and grant.scope_id == bundle.mail_import_session.workspace_id
        ):
            return True
        if (
            grant.scope_type == "mail_import_session"
            and grant.scope_id == bundle.mail_import_session.mail_import_session_id
        ):
            return True
    return False


def _validate_query_inputs(
    *,
    query_text: str,
    requester_user_id: str,
    workspace_id: str,
    session_id: str,
    mail_import_session_id: str | None,
    mail_evidence_bundle_id: str | None,
    limit: int,
) -> None:
    safe_public_string(query_text, "query_text")
    for field_name, value in (
        ("query_text", query_text),
        ("requester_user_id", requester_user_id),
        ("workspace_id", workspace_id),
        ("session_id", session_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"{field_name} is required")
        safe_public_string(value, field_name)
    if not mail_import_session_id and not mail_evidence_bundle_id:
        raise ContractValidationError(
            "mail_import_session_id or mail_evidence_bundle_id is required"
        )
    if mail_import_session_id is not None:
        safe_public_string(mail_import_session_id, "mail_import_session_id")
    if mail_evidence_bundle_id is not None:
        safe_public_string(mail_evidence_bundle_id, "mail_evidence_bundle_id")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ContractValidationError("limit must be a non-negative integer")


def _tokenize(value: str) -> set[str]:
    return jieba_sentencepiece_frozen_profile_candidate_admission_tokens(value)


def _load_mail_tokenizer_profile() -> MailCandidateAdmissionTokenizerProfile:
    profile = load_default_mail_candidate_admission_tokenizer_profile()
    if not _is_target_mail_tokenizer_profile(profile):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return profile


def _revision_owned_tokenizer_profile(
    session: Any,
) -> MailCandidateAdmissionTokenizerProfile:
    """Resolve the sealed session profile before the fallback deadline starts."""

    index = getattr(session, "index", None)
    runtime_components = getattr(index, "_runtime_components", None)
    profile = getattr(runtime_components, "tokenizer_profile", None)
    if profile is None:
        profile = getattr(index, "tokenizer_profile", None)
    if profile is None:
        profile = getattr(session, "tokenizer_profile", None)
    if profile is None:
        # Compatibility fixtures may expose only ``query``.  Keep their
        # pre-existing path, but perform this cold load before the bounded
        # source phase and validate the same pinned contract.
        if index is not None or runtime_components is not None:
            raise ContractValidationError("issue56 target tokenizer profile is unavailable")
        try:
            profile = _load_mail_tokenizer_profile()
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ContractValidationError(
                "issue56 target tokenizer profile is unavailable"
            ) from exc
    require_issue56_target_tokenizer_profile(
        profile,
        expected_profile_fingerprint=MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    )
    return profile


def _is_target_mail_tokenizer_profile(
    profile: MailCandidateAdmissionTokenizerProfile,
) -> bool:
    return (
        profile.tokenizer_id == MAIL_TOKENIZER_ID
        and profile.profile_fingerprint == MAIL_TOKENIZER_PROFILE_FINGERPRINT
    )


def _require_matching_profile(
    snippet_index: _MailSnippetIndex,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> None:
    if snippet_index.profile_fingerprint != tokenizer_profile.profile_fingerprint:
        raise ContractValidationError("mail evidence tokenizer profile mismatch")


__all__ = [
    "AuthorizedObservationIndexBuildManifest",
    "ExistingObservationIndexBuildManifest",
    "GitHubProjectOccurrenceLineage",
    "IndexedMailSnippet",
    "IndexedObservationSnippet",
    "MailAttachmentChildOccurrenceLineage",
    "MailMessageOccurrenceLineage",
    "MailEvidenceQueryGateway",
    "MailEvidenceQueryResult",
    "MailSnippetIndex",
    "ObservationSnippetIndex",
    "REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES",
    "SourceOccurrenceLineage",
    "TextDocumentOccurrenceLineage",
    "authorize_mail_evidence_bundles",
    "build_authorized_observation_snippet_index",
    "build_existing_observation_snippet_index",
    "build_mail_evidence_query_handler",
    "build_revision_owned_mail_evidence_query_handler",
    "normalized_authorized_observation_lineages",
    "require_issue56_target_tokenizer_profile",
    "source_occurrence_lineage_from_observation",
    "validate_source_neutral_attachment_observation_coverage",
]


_PROTECTED_IDENTIFIER_TOKEN = re.compile(r"(?=.{5,}\Z)(?=.*\d)[a-z0-9_@.-]+\Z")


_TYPED_NUMERIC_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]{2,5}[\s#:_-]*([0-9]{8,})(?![0-9])"
)


_SourceItemKey = tuple[str, str, str]


_SourceItemIdentity = _SourceItemKey | str


_MAX_INDEX_WORKERS = 4


_PARALLEL_INDEX_TASKS_PER_WORKER = 32


_PARALLEL_INDEX_BUILD_LOCK = threading.Lock()


_PARALLEL_INDEX_BUNDLE: MailEvidenceBundle | None = None


_PARALLEL_INDEX_MESSAGES_BY_ID: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class MailEvidenceReadResult:
    status: str
    mail_import_session_id: str | None
    evidence_segments: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    evidence_completeness: str = "unknown"
    answerability_state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_authorized_evidence_payload_safe(
            payload,
            "mail_evidence_read_result",
        )
        return payload


@dataclass(frozen=True)
class StructuralObservationMatchFact:
    """Governed row-coherent match identity for one structural observation."""

    source_observation_id: str
    structural_observation_id: str
    source_inventory_item_id: str
    matched_row_ordinals: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "source_observation_id",
            "structural_observation_id",
            "source_inventory_item_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"{field_name} is invalid")
            safe_public_string(value, field_name)
        if any(
            not isinstance(row_ordinal, int) or isinstance(row_ordinal, bool) or row_ordinal < 0
            for row_ordinal in self.matched_row_ordinals
        ):
            raise ContractValidationError("matched_row_ordinals are invalid")
        canonical = tuple(sorted(set(self.matched_row_ordinals)))
        if self.matched_row_ordinals != canonical:
            raise ContractValidationError("matched_row_ordinals must be ordered and unique")

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_authorized_evidence_payload_safe(
            payload,
            "structural_observation_match_fact",
        )
        return payload


@dataclass(frozen=True)
class StructuredSetMatch:
    """One row selected by a grounded semantic plan before presentation."""

    source_observation_id: str
    structural_observation_id: str
    source_inventory_item_id: str
    row_ordinal: int
    projection_values: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "source_observation_id",
            "structural_observation_id",
            "source_inventory_item_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"{field_name} is invalid")
        if (
            not isinstance(self.row_ordinal, int)
            or isinstance(self.row_ordinal, bool)
            or self.row_ordinal < 0
        ):
            raise ContractValidationError("structured set row ordinal is invalid")
        if any(not isinstance(value, str) or not value for value in self.projection_values):
            raise ContractValidationError("structured set projection values are invalid")
        object.__setattr__(self, "projection_values", tuple(self.projection_values))


@dataclass(frozen=True)
class StructuredSetExecution:
    """Structured-filter result plus inputs for the existing claim engine.

    ``coverage_ledger`` is passed through from the governed WP3 scope.  This
    executor intentionally does not derive final claim truth, completeness,
    conflict state, or user-facing prose.
    """

    plan: ExecutableSemanticPlan
    matches: tuple[StructuredSetMatch, ...]
    displayed_matches: tuple[StructuredSetMatch, ...]
    matched_structural_facts: tuple[StructuralObservationMatchFact, ...]
    total_matching_rows: int
    authorized_structural_observation_ids: tuple[str, ...]
    display_pagination: DisplayPagination
    coverage_ledger: CoverageLedger | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ExecutableSemanticPlan):
            raise ContractValidationError("structured set plan is invalid")
        if self.total_matching_rows != len(self.matches):
            raise ContractValidationError("structured set total is invalid")
        if any(not isinstance(match, StructuredSetMatch) for match in self.matches):
            raise ContractValidationError("structured set matches are invalid")
        if any(not isinstance(match, StructuredSetMatch) for match in self.displayed_matches):
            raise ContractValidationError("structured set displayed matches are invalid")
        if any(
            not isinstance(fact, StructuralObservationMatchFact)
            for fact in self.matched_structural_facts
        ):
            raise ContractValidationError("structured set match facts are invalid")
        if any(
            not isinstance(value, str) or not value
            for value in self.authorized_structural_observation_ids
        ):
            raise ContractValidationError("structured set authorized observations are invalid")
        if self.authorized_structural_observation_ids != tuple(
            sorted(set(self.authorized_structural_observation_ids))
        ):
            raise ContractValidationError("structured set authorized observations are invalid")
        if not isinstance(self.display_pagination, DisplayPagination):
            raise ContractValidationError("structured set pagination is invalid")
        if self.coverage_ledger is not None and not isinstance(
            self.coverage_ledger, CoverageLedger
        ):
            raise ContractValidationError("structured set coverage ledger is invalid")


@dataclass(frozen=True)
class _RequiredTermAlternative:
    normalized_text: str
    anchor_tokens: frozenset[str]


@dataclass(frozen=True)
class _RequiredTermSpec:
    display_text: str
    alternatives: tuple[_RequiredTermAlternative, ...]


@dataclass(frozen=True)
class _RequiredTermMatch:
    display_text: str
    normalized_alternatives: tuple[str, ...]
    snippet_index: int


@dataclass(frozen=True)
class _MailEvidenceQueryExecution:
    result: MailEvidenceQueryResult
    verified_source_item_keys: frozenset[_SourceItemIdentity] | None
    timings_ms: dict[str, float]

    @property
    def verified_source_item_ids(self) -> frozenset[str] | None:
        """Compatibility projection of the namespaced internal identities."""

        if self.verified_source_item_keys is None:
            return None
        return frozenset(
            source_item_key[2] if isinstance(source_item_key, tuple) else source_item_key
            for source_item_key in self.verified_source_item_keys
        )


@dataclass(frozen=True)
class _MailSnippetSearch:
    snippets: list[dict[str, Any]]
    bundle_ids: tuple[str, ...]
    posting_retrieval_ms: float
    ranking_ms: float


_SUBJECT_REQUIRED_TERM_MATCH = -1


def build_mail_evidence_read_handler(
    bundles: Sequence[MailEvidenceBundle],
    *,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> Any:
    gateway = MailEvidenceQueryGateway(bundles)
    trusted_grants = tuple(grants)

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        result = gateway.read_mail_evidence(
            requester_user_id=input_data.get("requester_user_id", ""),
            workspace_id=input_data.get("workspace_id", ""),
            session_id=input_data.get("session_id", "semantic_gateway_session"),
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
            source_observation_ids=input_data.get("source_observation_ids", ()),
            email_message_ids=input_data.get("email_message_ids", ()),
            grants=trusted_grants,
            limit=input_data.get("limit"),
            now=now,
        )
        return result.to_dict()

    return handler


def _search_visible_bundles_with_diagnostics(
    bundles: Sequence[MailEvidenceBundle],
    *,
    query_text: str,
    limit: int | None,
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex] | None = None,
    allowed_source_item_ids: frozenset[_SourceItemIdentity] | None = None,
    snippet_filter_groups: tuple[tuple[str, ...], ...] = (),
    collapse_source_items: bool = False,
) -> _MailSnippetSearch:
    terms = _indexable_tokens(query_text)
    posting_started = perf_counter()
    matched: list[tuple[_IndexedMailSnippet, tuple[str, ...]]] = []
    matched_by_source_item_id: dict[
        _SourceItemIdentity,
        tuple[_IndexedMailSnippet, tuple[str, ...]],
    ] = {}
    for bundle in bundles:
        if snippet_index_by_bundle_id is None:
            snippet_index = _build_snippet_index(bundle)
        else:
            snippet_index = snippet_index_by_bundle_id.get(bundle.mail_evidence_bundle_id)
            if snippet_index is None:
                snippet_index = _build_snippet_index(bundle)
        candidate_indexes = _candidate_snippet_indexes(
            snippet_index,
            terms,
            allowed_source_item_ids=allowed_source_item_ids,
        )
        for snippet_index_value in candidate_indexes:
            indexed = snippet_index.snippets[snippet_index_value]
            if (
                allowed_source_item_ids is not None
                and _indexed_source_item_identity(indexed) not in allowed_source_item_ids
            ):
                continue
            matched_terms = tuple(
                sorted(term for term in terms if term in indexed.searchable_tokens)
            )
            if not matched_terms:
                continue
            if snippet_filter_groups and not _payload_matches_filter_groups(
                indexed.payload,
                snippet_filter_groups,
            ):
                continue
            candidate = (indexed, matched_terms)
            if not collapse_source_items:
                matched.append(candidate)
                continue
            source_item_identity = _indexed_source_item_identity(indexed)
            current = matched_by_source_item_id.get(source_item_identity)
            if current is None or _matched_snippet_preference(candidate) > (
                _matched_snippet_preference(current)
            ):
                matched_by_source_item_id[source_item_identity] = candidate
    if collapse_source_items:
        matched = list(matched_by_source_item_id.values())
    posting_retrieval_ms = (perf_counter() - posting_started) * 1000.0

    ranking_started = perf_counter()
    ranked = sorted(
        matched,
        key=lambda item: (
            -len(item[1]),
            str(item[0].payload["source_observation_id"]),
        ),
    )
    if limit is not None:
        ranked = ranked[:limit]
    ranking_ms = (perf_counter() - ranking_started) * 1000.0
    snippets = [
        _safe_snippet(
            {
                **indexed.payload,
                "score": len(matched_terms),
                "matched_terms": list(matched_terms),
            }
        )
        for indexed, matched_terms in ranked
    ]
    return _MailSnippetSearch(
        snippets=snippets,
        bundle_ids=tuple(indexed.mail_evidence_bundle_id for indexed, _ in ranked),
        posting_retrieval_ms=posting_retrieval_ms,
        ranking_ms=ranking_ms,
    )


def _matched_snippet_preference(
    item: tuple[_IndexedMailSnippet, tuple[str, ...]],
) -> tuple[int, int]:
    indexed, matched_terms = item
    return (
        len(matched_terms),
        len(str(indexed.payload.get("snippet", ""))),
    )


def _assemble_required_term_supporting_evidence(
    snippets: list[dict[str, Any]],
    *,
    bundle_ids: tuple[str, ...],
    matches_by_source_item: Mapping[
        _SourceItemIdentity,
        tuple[_RequiredTermMatch, ...],
    ],
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex],
) -> list[dict[str, Any]]:
    assembled: list[dict[str, Any]] = []
    for primary, bundle_id in zip(snippets, bundle_ids, strict=True):
        source_item_key: _SourceItemIdentity = (
            bundle_id,
            str(primary["mail_import_session_id"]),
            str(primary["email_message_id"]),
        )
        required_term_matches = matches_by_source_item.get(source_item_key)
        if required_term_matches is None:
            # Compatibility for tests or callers that inject an older
            # bare-ID index.  Built indexes always use the namespaced key.
            required_term_matches = matches_by_source_item.get(
                str(primary["email_message_id"]),
                (),
            )
        snippet_index = snippet_index_by_bundle_id.get(bundle_id)
        if snippet_index is None or not required_term_matches:
            assembled.append(primary)
            continue

        primary_required_terms: list[str] = []
        required_terms_by_support_index: dict[int, list[str]] = {}
        for required_term_match in required_term_matches:
            support_index = required_term_match.snippet_index
            if (
                _snippet_matches_required_term(primary, required_term_match)
                or support_index == _SUBJECT_REQUIRED_TERM_MATCH
                or _indexed_snippet_is_primary(
                    snippet_index.snippets[support_index],
                    primary,
                )
            ):
                if required_term_match.display_text not in primary_required_terms:
                    primary_required_terms.append(required_term_match.display_text)
                continue
            support_terms = required_terms_by_support_index.setdefault(support_index, [])
            if required_term_match.display_text not in support_terms:
                support_terms.append(required_term_match.display_text)

        enriched_primary = dict(primary)
        if primary_required_terms:
            enriched_primary["matched_required_terms"] = primary_required_terms
        supporting_evidence: list[dict[str, Any]] = []
        for support_index, matched_required_terms in required_terms_by_support_index.items():
            indexed_support = snippet_index.snippets[support_index]
            support = _safe_snippet(
                {
                    **indexed_support.payload,
                    "matched_required_terms": matched_required_terms,
                }
            )
            support["citation"] = _citation_for_snippet(
                support,
                mail_evidence_bundle_id=bundle_id,
            )
            assert_authorized_evidence_payload_safe(
                support,
                "mail_evidence_required_term_support",
            )
            supporting_evidence.append(support)
        if supporting_evidence:
            enriched_primary["supporting_evidence"] = supporting_evidence
        assembled.append(enriched_primary)
    return assembled


def _indexed_snippet_is_primary(
    indexed: _IndexedMailSnippet,
    primary: Mapping[str, Any],
) -> bool:
    return all(
        indexed.payload.get(field_name) == primary.get(field_name)
        for field_name in (
            "source_observation_id",
            "message_occurrence_id",
            "segment_source_type",
            "attachment_id",
            "body_segment_index",
        )
    )


def _snippet_matches_required_term(
    snippet: Mapping[str, Any],
    required_term_match: _RequiredTermMatch,
) -> bool:
    normalized = _normalize_exact_text(
        " ".join(
            value
            for value in (snippet.get("subject"), snippet.get("snippet"))
            if isinstance(value, str)
        )
    )
    return any(
        alternative in normalized for alternative in required_term_match.normalized_alternatives
    )


def _payload_matches_filter_groups(
    payload: Mapping[str, Any],
    groups: tuple[tuple[str, ...], ...],
) -> bool:
    rendered = " ".join(
        value
        for value in (payload.get("subject"), payload.get("snippet"))
        if isinstance(value, str)
    ).casefold()
    rendered = _normalize_exact_text(rendered)
    return all(any(term in rendered for term in group) for group in groups)


def _assemble_snippet_index(
    bundle: MailEvidenceBundle,
    messages_by_id: Mapping[str, Any],
    tokenized_segments: Iterable[tuple[int, tuple[str, ...]]],
) -> _MailSnippetIndex:
    indexed: list[_IndexedMailSnippet] = []
    indexes_by_token: dict[str, list[int]] = {}
    source_item_ids_by_token: dict[str, set[_SourceItemKey]] = {}
    snippet_indexes_by_source_item_id: dict[_SourceItemKey, list[int]] = {}
    for segment_index, ordered_tokens in tokenized_segments:
        segment = bundle.body_segments[segment_index]
        message = messages_by_id.get(segment.email_message_id)
        tokens = frozenset(ordered_tokens)
        source_item_key = _source_item_key(bundle, segment.email_message_id)
        snippet_index = len(indexed)
        indexed.append(
            _IndexedMailSnippet(
                mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
                source_item_id=segment.email_message_id,
                dense_evidence_text=segment.text,
                searchable_tokens=frozenset(tokens),
                payload={
                    **_segment_payload(bundle, segment, message),
                },
                source_item_key=source_item_key,
            )
        )
        snippet_indexes_by_source_item_id.setdefault(
            source_item_key,
            [],
        ).append(snippet_index)
        for token in tokens:
            indexes_by_token.setdefault(token, []).append(snippet_index)
            source_item_ids_by_token.setdefault(token, set()).add(source_item_key)
    return _MailSnippetIndex(
        snippets=tuple(indexed),
        snippet_indexes_by_token=_immutable_posting_map(
            {token: tuple(indexes) for token, indexes in indexes_by_token.items()}
        ),
        source_item_ids_by_token=_immutable_posting_map(
            {
                token: frozenset(source_item_ids)
                for token, source_item_ids in source_item_ids_by_token.items()
            }
        ),
        snippet_indexes_by_source_item_id=_immutable_posting_map(
            {
                source_item_id: tuple(indexes)
                for source_item_id, indexes in snippet_indexes_by_source_item_id.items()
            }
        ),
        subject_by_source_item_id=_immutable_posting_map(
            {
                _source_item_key(bundle, message.email_message_id): message.subject or ""
                for message in bundle.messages
            }
        ),
    )


def _parallel_tokenized_segments(
    bundle: MailEvidenceBundle,
    messages_by_id: Mapping[str, Any],
    *,
    worker_count: int,
) -> Iterator[tuple[int, tuple[str, ...]]]:
    global _PARALLEL_INDEX_BUNDLE, _PARALLEL_INDEX_MESSAGES_BY_ID

    context = multiprocessing.get_context("fork")
    ranges = _parallel_index_ranges(
        len(bundle.body_segments),
        worker_count=worker_count,
    )
    with _PARALLEL_INDEX_BUILD_LOCK:
        _PARALLEL_INDEX_BUNDLE = bundle
        _PARALLEL_INDEX_MESSAGES_BY_ID = messages_by_id
        try:
            with context.Pool(processes=worker_count) as pool:
                for chunk in pool.imap(
                    _tokenize_segment_range,
                    ranges,
                    chunksize=1,
                ):
                    yield from chunk
        finally:
            _PARALLEL_INDEX_BUNDLE = None
            _PARALLEL_INDEX_MESSAGES_BY_ID = None


def _parallel_index_ranges(
    segment_count: int,
    *,
    worker_count: int,
) -> tuple[tuple[int, int], ...]:
    target_task_count = max(worker_count, worker_count * _PARALLEL_INDEX_TASKS_PER_WORKER)
    chunk_size = max(1, (segment_count + target_task_count - 1) // target_task_count)
    return tuple(
        (start, min(start + chunk_size, segment_count))
        for start in range(0, segment_count, chunk_size)
    )


def _tokenize_segment_range(
    bounds: tuple[int, int],
) -> tuple[tuple[int, tuple[str, ...]], ...]:
    bundle = _PARALLEL_INDEX_BUNDLE
    messages_by_id = _PARALLEL_INDEX_MESSAGES_BY_ID
    if bundle is None or messages_by_id is None:
        raise RuntimeError("parallel mail index worker is unavailable")
    start, stop = bounds
    rows: list[tuple[int, tuple[str, ...]]] = []
    for segment_index in range(start, stop):
        tokenized = _tokenize_segment(
            bundle,
            messages_by_id,
            segment_index,
        )
        if tokenized is not None:
            rows.append(tokenized)
    return tuple(rows)


def _tokenize_segment(
    bundle: MailEvidenceBundle,
    messages_by_id: Mapping[str, Any],
    segment_index: int,
) -> tuple[int, tuple[str, ...]] | None:
    segment = bundle.body_segments[segment_index]
    message = messages_by_id.get(segment.email_message_id)
    searchable = " ".join(
        item
        for item in (
            segment.text,
            message.subject if message else None,
            message.sender if message else None,
            message.message_id if message else None,
        )
        if isinstance(item, str)
    )
    tokens = _tokenize(searchable)
    if not tokens:
        return None
    return segment_index, tuple(sorted(tokens))


def _validated_index_worker_count(value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > _MAX_INDEX_WORKERS
    ):
        raise ContractValidationError("mail index worker count is invalid")
    return value


def _effective_index_worker_count(
    requested_worker_count: int,
    *,
    segment_count: int,
) -> int:
    if requested_worker_count == 1 or segment_count < 2:
        return 1
    if (
        sys.platform != "linux"
        or threading.current_thread() is not threading.main_thread()
        or threading.active_count() != 1
    ):
        return 1
    try:
        multiprocessing.get_context("fork")
    except ValueError:
        return 1
    return min(requested_worker_count, segment_count)


def _immutable_posting_map(
    values: dict[str, Any],
) -> Mapping[str, Any]:
    """Freeze the maps that make up the reusable query postings."""

    return MappingProxyType(values)


def _source_item_key(
    bundle: MailEvidenceBundle,
    email_message_id: str,
) -> _SourceItemKey:
    return (
        bundle.mail_evidence_bundle_id,
        bundle.mail_import_session.mail_import_session_id,
        email_message_id,
    )


def _indexed_source_item_identity(indexed: _IndexedMailSnippet) -> _SourceItemIdentity:
    return indexed.source_item_key or indexed.source_item_id


def _source_item_indexes(
    snippet_index: _MailSnippetIndex,
    source_item_identity: _SourceItemIdentity,
) -> tuple[int, ...]:
    indexes = snippet_index.snippet_indexes_by_source_item_id.get(source_item_identity)
    if indexes is not None:
        return indexes
    if isinstance(source_item_identity, tuple) and any(
        getattr(snippet, "mail_evidence_bundle_id", None) == source_item_identity[0]
        for snippet in snippet_index.snippets
    ):
        return snippet_index.snippet_indexes_by_source_item_id.get(
            source_item_identity[2],
            (),
        )
    return ()


def _canonical_source_item_identity(
    snippet_index: _MailSnippetIndex,
    source_item_identity: _SourceItemIdentity,
) -> _SourceItemIdentity:
    if isinstance(source_item_identity, tuple):
        return source_item_identity
    indexes = _source_item_indexes(snippet_index, source_item_identity)
    if indexes:
        return _indexed_source_item_identity(snippet_index.snippets[indexes[0]])
    return source_item_identity


def _source_item_subject(
    snippet_index: _MailSnippetIndex,
    source_item_identity: _SourceItemIdentity,
) -> str:
    subject = snippet_index.subject_by_source_item_id.get(source_item_identity)
    if subject is not None:
        return subject
    if isinstance(source_item_identity, tuple) and any(
        getattr(snippet, "mail_evidence_bundle_id", None) == source_item_identity[0]
        for snippet in snippet_index.snippets
    ):
        return snippet_index.subject_by_source_item_id.get(source_item_identity[2], "")
    return ""


def _required_term_specs(
    values: Sequence[str],
) -> tuple[_RequiredTermSpec, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ContractValidationError("required terms are invalid")
    if len(values) > 12:
        raise ContractValidationError("required terms are invalid")
    normalized_terms: list[str] = []
    specs: list[_RequiredTermSpec] = []
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise ContractValidationError("required term is invalid")
        safe_public_string(value, "required_term")
        normalized = _normalize_exact_text(value).strip()
        if not normalized or normalized in normalized_terms:
            raise ContractValidationError("required terms must be unique")
        normalized_terms.append(normalized)
        alternative_values = [normalized]
        for numeric_alias in typed_numeric_identifier_aliases(normalized):
            if numeric_alias not in alternative_values:
                alternative_values.append(numeric_alias)
        alternatives = tuple(
            _RequiredTermAlternative(
                normalized_text=alternative,
                # Equivalent forms are alternatives, not additional required
                # tokens.  A typed identifier therefore may match a numeric
                # source, while a normal phrase still uses conjunctive token
                # postings.
                anchor_tokens=frozenset(_tokenize(alternative)),
            )
            for alternative in alternative_values
        )
        specs.append(
            _RequiredTermSpec(
                display_text=value.strip(),
                alternatives=alternatives,
            )
        )
    return tuple(specs)


def _normalized_filter_groups(
    groups: Sequence[Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    if isinstance(groups, (str, bytes)) or not isinstance(groups, Sequence):
        raise ContractValidationError("snippet filter groups are invalid")
    normalized_groups: list[tuple[str, ...]] = []
    for group in groups:
        if isinstance(group, (str, bytes)) or not isinstance(group, Sequence):
            raise ContractValidationError("snippet filter group is invalid")
        normalized_group: list[str] = []
        for value in group:
            if not isinstance(value, str) or not value.strip():
                raise ContractValidationError("snippet filter term is invalid")
            safe_public_string(value, "snippet_filter_term")
            normalized = _normalize_exact_text(value).strip()
            if normalized not in normalized_group:
                normalized_group.append(normalized)
        if not normalized_group:
            raise ContractValidationError("snippet filter group is invalid")
        normalized_groups.append(tuple(normalized_group))
    return tuple(normalized_groups)


def _resolve_verified_required_source_item_ids(
    bundles: Sequence[MailEvidenceBundle],
    *,
    required_term_specs: tuple[_RequiredTermSpec, ...],
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex],
) -> tuple[
    frozenset[_SourceItemIdentity],
    Mapping[_SourceItemIdentity, tuple[_RequiredTermMatch, ...]],
    float,
    float,
]:
    indexes_by_bundle_id: dict[str, _MailSnippetIndex] = {}
    for bundle in bundles:
        snippet_index = snippet_index_by_bundle_id.get(bundle.mail_evidence_bundle_id)
        if snippet_index is None:
            snippet_index = _build_snippet_index(bundle)
        indexes_by_bundle_id[bundle.mail_evidence_bundle_id] = snippet_index

    posting_started = perf_counter()
    candidate_ids_by_bundle: dict[str, frozenset[_SourceItemIdentity]] = {}
    for bundle in bundles:
        snippet_index = indexes_by_bundle_id[bundle.mail_evidence_bundle_id]
        candidate_ids = _required_term_candidate_source_item_ids(
            snippet_index,
            required_term_specs,
        )
        if candidate_ids:
            candidate_ids_by_bundle[bundle.mail_evidence_bundle_id] = candidate_ids
    posting_retrieval_ms = (perf_counter() - posting_started) * 1000.0

    verification_started = perf_counter()
    verified: set[_SourceItemIdentity] = set()
    matches_by_source_item: dict[
        _SourceItemIdentity,
        tuple[_RequiredTermMatch, ...],
    ] = {}
    for bundle in bundles:
        candidate_ids = candidate_ids_by_bundle.get(bundle.mail_evidence_bundle_id)
        if not candidate_ids:
            continue
        snippet_index = indexes_by_bundle_id[bundle.mail_evidence_bundle_id]
        bundle_verified, bundle_matches = _verify_required_source_item_ids(
            snippet_index,
            candidate_ids=candidate_ids,
            required_term_specs=required_term_specs,
        )
        verified.update(bundle_verified)
        matches_by_source_item.update(bundle_matches)
    exact_verification_ms = (perf_counter() - verification_started) * 1000.0
    return (
        frozenset(verified),
        MappingProxyType(matches_by_source_item),
        posting_retrieval_ms,
        exact_verification_ms,
    )


def _required_term_candidate_source_item_ids(
    snippet_index: _MailSnippetIndex,
    required_term_specs: tuple[_RequiredTermSpec, ...],
) -> frozenset[_SourceItemIdentity]:
    candidates_for_all_terms: set[_SourceItemIdentity] | None = None
    for required_term_spec in required_term_specs:
        candidates_for_term: set[_SourceItemIdentity] = set()
        for alternative in required_term_spec.alternatives:
            if not alternative.anchor_tokens:
                continue
            token_postings = [
                snippet_index.source_item_ids_by_token.get(token, frozenset())
                for token in alternative.anchor_tokens
            ]
            if any(not postings for postings in token_postings):
                continue
            # Intersect the smallest postings first.  This is both the
            # conjunctive required-term rule and the useful cost bound before
            # exact source-field verification.
            token_postings.sort(key=len)
            alternative_candidates = set(token_postings[0])
            for postings in token_postings[1:]:
                alternative_candidates.intersection_update(postings)
                if not alternative_candidates:
                    break
            candidates_for_term.update(
                _canonical_source_item_identity(snippet_index, candidate_id)
                for candidate_id in alternative_candidates
            )
        if not candidates_for_term:
            return frozenset()
        if candidates_for_all_terms is None:
            candidates_for_all_terms = candidates_for_term
        else:
            candidates_for_all_terms.intersection_update(candidates_for_term)
        if not candidates_for_all_terms:
            return frozenset()
    return frozenset(candidates_for_all_terms or ())


def _verify_required_source_item_ids(
    snippet_index: _MailSnippetIndex,
    *,
    candidate_ids: frozenset[_SourceItemIdentity],
    required_term_specs: tuple[_RequiredTermSpec, ...],
) -> tuple[
    frozenset[_SourceItemIdentity],
    Mapping[_SourceItemIdentity, tuple[_RequiredTermMatch, ...]],
]:
    verified: set[_SourceItemIdentity] = set()
    matches_by_source_item: dict[
        _SourceItemIdentity,
        tuple[_RequiredTermMatch, ...],
    ] = {}
    for source_item_id in candidate_ids:
        subject = _normalize_exact_text(_source_item_subject(snippet_index, source_item_id))
        normalized_snippets: dict[int, str] = {}
        snippet_indexes = _source_item_indexes(snippet_index, source_item_id)
        required_term_matches: list[_RequiredTermMatch] = []
        for required_term_spec in required_term_specs:
            supporting_snippet_index = _required_term_supporting_snippet_index(
                snippet_index,
                subject=subject,
                snippet_indexes=snippet_indexes,
                normalized_snippets=normalized_snippets,
                required_term_spec=required_term_spec,
            )
            if supporting_snippet_index is None:
                break
            required_term_matches.append(
                _RequiredTermMatch(
                    display_text=required_term_spec.display_text,
                    normalized_alternatives=tuple(
                        alternative.normalized_text
                        for alternative in required_term_spec.alternatives
                    ),
                    snippet_index=supporting_snippet_index,
                )
            )
        else:
            verified.add(source_item_id)
            matches_by_source_item[source_item_id] = tuple(required_term_matches)
    return frozenset(verified), MappingProxyType(matches_by_source_item)


def _source_item_matches_required_term(
    snippet_index: _MailSnippetIndex,
    *,
    subject: str,
    snippet_indexes: tuple[int, ...],
    normalized_snippets: dict[int, str],
    required_term_spec: _RequiredTermSpec,
) -> bool:
    return (
        _required_term_supporting_snippet_index(
            snippet_index,
            subject=subject,
            snippet_indexes=snippet_indexes,
            normalized_snippets=normalized_snippets,
            required_term_spec=required_term_spec,
        )
        is not None
    )


def _required_term_supporting_snippet_index(
    snippet_index: _MailSnippetIndex,
    *,
    subject: str,
    snippet_indexes: tuple[int, ...],
    normalized_snippets: dict[int, str],
    required_term_spec: _RequiredTermSpec,
) -> int | None:
    for alternative in required_term_spec.alternatives:
        if alternative.normalized_text in subject:
            return _SUBJECT_REQUIRED_TERM_MATCH
        for snippet_index_value in snippet_indexes:
            indexed = snippet_index.snippets[snippet_index_value]
            normalized_snippet = normalized_snippets.get(snippet_index_value)
            if normalized_snippet is None:
                normalized_snippet = _normalize_exact_text(str(indexed.payload.get("snippet", "")))
                normalized_snippets[snippet_index_value] = normalized_snippet
            if alternative.normalized_text in normalized_snippet:
                return snippet_index_value
    return None


def _typed_numeric_identifier_alias(value: str) -> str | None:
    normalized = _normalize_exact_text(value).strip()
    match = _TYPED_NUMERIC_IDENTIFIER_RE.fullmatch(normalized)
    return match.group(1) if match is not None else None


def typed_numeric_identifier_aliases(value: str) -> tuple[str, ...]:
    normalized = _normalize_exact_text(value)
    aliases: list[str] = []
    for match in _TYPED_NUMERIC_IDENTIFIER_RE.finditer(normalized):
        alias = match.group(1)
        if alias not in aliases:
            aliases.append(alias)
    return tuple(aliases)


def _zero_query_timings() -> dict[str, float]:
    return {
        "posting_retrieval": 0.0,
        "exact_verification": 0.0,
        "ranking": 0.0,
    }


def _segment_payload(bundle: MailEvidenceBundle, segment: Any, message: Any) -> dict[str, Any]:
    return {
        "source_type": (
            "mail_attachment_text_segment"
            if segment.segment_source_type == "attachment_text"
            else "mail_body_segment"
        ),
        "source_observation_id": segment.source_observation_id,
        "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        "email_message_id": segment.email_message_id,
        "message_occurrence_id": segment.message_occurrence_id,
        "subject": message.subject if message else None,
        "snippet": segment.text,
        "segment_source_type": segment.segment_source_type,
        "attachment_id": segment.attachment_id,
        "body_segment_index": segment.body_segment_index,
        "body_segment_count": segment.body_segment_count,
        "source_body_char_count": segment.source_body_char_count,
        "stored_body_char_count": segment.stored_body_char_count,
        "body_evidence_state": (
            segment.body_evidence_state
            if segment.body_evidence_state != "unknown"
            else (message.body_evidence_state if message else "unknown")
        ),
        "unresolved_attachment_count": (message.unresolved_attachment_count if message else 0),
    }


def _source_completeness(bundles: Sequence[MailEvidenceBundle]) -> str:
    messages = [message for bundle in bundles for message in bundle.messages]
    if not messages:
        return "unknown"
    if any(
        message.body_evidence_state != "complete"
        or message.unresolved_attachment_count > 0
        or (
            message.source_body_char_count is not None
            and message.stored_body_char_count != message.source_body_char_count
        )
        for message in messages
    ):
        return "incomplete"
    return "complete"


def _matched_evidence_completeness(snippets: Sequence[Mapping[str, Any]]) -> str:
    if not snippets:
        return "unknown"
    if any(
        snippet.get("body_evidence_state") != "complete"
        or int(snippet.get("unresolved_attachment_count") or 0) > 0
        or (
            snippet.get("source_body_char_count") is not None
            and snippet.get("stored_body_char_count") != snippet.get("source_body_char_count")
        )
        for snippet in snippets
    ):
        return "incomplete"
    return "complete"


def execute_authorized_structured_set(
    *,
    plan: ExecutableSemanticPlan,
    structural_observations: Sequence[StructuralObservation],
    authorized_inventory_item_ids: Sequence[str],
    coverage_ledger: CoverageLedger | None = None,
) -> StructuredSetExecution:
    """Execute one exact all-matching filter over the complete authorized rows.

    The caller establishes permission/source/version/context/time/status
    admissibility before grounding ``plan`` and supplies every structured
    observation in that authorized scope here.  This function performs no
    lexical, fuzzy, embedding, or ontology-score retrieval: values are
    normalized only for exact equality against the already-grounded plan.

    The returned rows and match facts are inputs to
    :meth:`TaskAnsweringEngine.answer_canonical_claim`; final no-match,
    partial, conflict, and sufficient states remain owned by that engine and
    its ``CoverageLedger``.
    """

    if not isinstance(plan, ExecutableSemanticPlan):
        raise ContractValidationError("structured semantic plan is invalid")
    if plan.query_class != "attribute_filter" or plan.cardinality != "all_matching":
        raise ContractValidationError("structured semantic plan is not an all-matching filter")
    if coverage_ledger is not None and not isinstance(coverage_ledger, CoverageLedger):
        raise ContractValidationError("structured semantic coverage ledger is invalid")
    if isinstance(structural_observations, (str, bytes)) or not isinstance(
        structural_observations,
        Sequence,
    ):
        raise ContractValidationError("structured semantic observations are invalid")
    if isinstance(authorized_inventory_item_ids, (str, bytes)) or not isinstance(
        authorized_inventory_item_ids,
        Sequence,
    ):
        raise ContractValidationError("structured semantic authorized scope is invalid")
    authorized_values = tuple(authorized_inventory_item_ids)
    if not authorized_values or any(
        not isinstance(value, str) or not value for value in authorized_values
    ):
        raise ContractValidationError("structured semantic authorized scope is invalid")
    authorized_ids = frozenset(authorized_values)
    if any(
        not isinstance(observation, StructuralObservation)
        for observation in structural_observations
    ):
        raise ContractValidationError("structured semantic observations are invalid")

    # Permission is the first data-dependent boundary.  Neither column aliases
    # nor values from an unauthorized observation are inspected below.
    authorized_observations = tuple(
        observation
        for observation in structural_observations
        if observation.source_inventory_item_id in authorized_ids
    )
    object_type_forms = frozenset(plan.object_type_match_forms)
    matches: list[StructuredSetMatch] = []
    for observation in authorized_observations:
        if _normalize_structured_semantic_text(observation.structure_kind) not in object_type_forms:
            continue
        predicate_ordinals = _semantic_column_ordinals(
            observation,
            plan.predicate_match_forms,
        )
        if not predicate_ordinals:
            continue
        projection_ordinals = _semantic_column_ordinals(
            observation,
            plan.projection_match_forms,
        )
        for row in observation.rows:
            if not _semantic_row_matches(
                row,
                predicate_ordinals=predicate_ordinals,
                value_forms=plan.value_match_forms,
            ):
                continue
            matches.append(
                StructuredSetMatch(
                    source_observation_id=observation.source_observation_id,
                    structural_observation_id=observation.structural_observation_id,
                    source_inventory_item_id=observation.source_inventory_item_id,
                    row_ordinal=row.row_ordinal,
                    projection_values=_semantic_row_values(
                        row,
                        column_ordinals=projection_ordinals,
                    ),
                )
            )

    ordered_matches = tuple(
        sorted(
            matches,
            key=lambda match: _structured_set_match_sort_key(match, plan),
            reverse=plan.order_direction == "descending",
        )
    )
    page_start = (plan.page_number - 1) * plan.page_size
    displayed_matches = ordered_matches[page_start : page_start + plan.page_size]
    facts_by_observation: dict[
        tuple[str, str, str],
        list[int],
    ] = {}
    for match in ordered_matches:
        facts_by_observation.setdefault(
            (
                match.source_observation_id,
                match.structural_observation_id,
                match.source_inventory_item_id,
            ),
            [],
        ).append(match.row_ordinal)
    match_facts = tuple(
        StructuralObservationMatchFact(
            source_observation_id=source_observation_id,
            structural_observation_id=structural_observation_id,
            source_inventory_item_id=source_inventory_item_id,
            matched_row_ordinals=tuple(sorted(set(row_ordinals))),
        )
        for (
            source_observation_id,
            structural_observation_id,
            source_inventory_item_id,
        ), row_ordinals in sorted(facts_by_observation.items())
    )
    pagination = DisplayPagination(
        page_size=plan.page_size,
        page_number=plan.page_number,
        displayed_count=len(displayed_matches),
        has_more=len(ordered_matches) > page_start + len(displayed_matches),
    )
    return StructuredSetExecution(
        plan=plan,
        matches=ordered_matches,
        displayed_matches=displayed_matches,
        matched_structural_facts=match_facts,
        total_matching_rows=len(ordered_matches),
        authorized_structural_observation_ids=tuple(
            sorted({observation.source_observation_id for observation in authorized_observations})
        ),
        display_pagination=pagination,
        coverage_ledger=coverage_ledger,
    )


def _semantic_column_ordinals(
    observation: StructuralObservation,
    match_forms: Sequence[str],
) -> frozenset[int]:
    forms = frozenset(_normalize_structured_semantic_text(value) for value in match_forms)
    return frozenset(
        column.column_ordinal
        for column in observation.columns
        if any(
            _normalize_structured_semantic_text(value) in forms
            for value in (column.original_header, column.normalized_header)
            if isinstance(value, str)
        )
    )


def _semantic_row_matches(
    row: Any,
    *,
    predicate_ordinals: frozenset[int],
    value_forms: Sequence[str],
) -> bool:
    normalized_values = frozenset(
        _normalize_structured_semantic_text(value) for value in value_forms
    )
    return any(
        cell.cell_state == "populated"
        and cell.column_ordinal in predicate_ordinals
        and any(
            _normalize_structured_semantic_text(value) in normalized_values
            for value in (cell.normalized_value, cell.value)
            if isinstance(value, str)
        )
        for cell in row.cells
    )


def _semantic_row_values(
    row: Any,
    *,
    column_ordinals: frozenset[int],
) -> tuple[str, ...]:
    values: list[str] = []
    for cell in row.cells:
        if (
            cell.cell_state != "populated"
            or cell.column_ordinal not in column_ordinals
            or not isinstance(cell.value, str)
            or not cell.value
            or cell.value in values
        ):
            continue
        values.append(cell.value)
    return tuple(values)


def _structured_set_match_sort_key(
    match: StructuredSetMatch,
    plan: ExecutableSemanticPlan,
) -> tuple[Any, ...]:
    if plan.order_by == "projection":
        return (
            tuple(_normalize_structured_semantic_text(value) for value in match.projection_values),
            match.source_observation_id,
            match.row_ordinal,
        )
    if plan.order_by == "row_ordinal":
        return (
            match.row_ordinal,
            match.source_observation_id,
            tuple(_normalize_structured_semantic_text(value) for value in match.projection_values),
        )
    return (
        match.source_observation_id,
        match.row_ordinal,
        tuple(_normalize_structured_semantic_text(value) for value in match.projection_values),
    )


def _normalize_structured_semantic_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def _validate_read_inputs(
    *,
    requester_user_id: str,
    workspace_id: str,
    session_id: str,
    mail_import_session_id: str | None,
    mail_evidence_bundle_id: str | None,
    source_observation_ids: Sequence[str],
    email_message_ids: Sequence[str],
    limit: int,
) -> None:
    for field_name, value in (
        ("requester_user_id", requester_user_id),
        ("workspace_id", workspace_id),
        ("session_id", session_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"{field_name} is required")
        safe_public_string(value, field_name)
    if not mail_import_session_id and not mail_evidence_bundle_id:
        raise ContractValidationError(
            "mail_import_session_id or mail_evidence_bundle_id is required"
        )
    if not source_observation_ids and not email_message_ids:
        raise ContractValidationError("source_observation_ids or email_message_ids is required")
    for field_name, values in (
        ("source_observation_ids", source_observation_ids),
        ("email_message_ids", email_message_ids),
    ):
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ContractValidationError(f"{field_name} must be a list")
        for value in values:
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"{field_name} must contain non-empty strings")
            safe_public_string(value, field_name)
    if mail_import_session_id is not None:
        safe_public_string(mail_import_session_id, "mail_import_session_id")
    if mail_evidence_bundle_id is not None:
        safe_public_string(mail_evidence_bundle_id, "mail_evidence_bundle_id")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
        raise ContractValidationError("limit must be a positive integer")


def _indexable_tokens(value: str) -> set[str]:
    tokens = _tokenize(_normalize_exact_text(value))
    aliases: set[str] = set()
    for token in tokens:
        if not _PROTECTED_IDENTIFIER_TOKEN.fullmatch(token):
            continue
        stripped = token.strip(".")
        if stripped and stripped != token:
            aliases.add(stripped)
        aliases.update(typed_numeric_identifier_aliases(token))
    return {*tokens, *aliases}


def _normalize_exact_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()
