from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence, TypeAlias

from formowl_contract import (
    ContractValidationError,
    Grant,
    Observation,
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
    check_source_evidence_deadline as _check_revision_source_deadline,
    source_evidence_supported_requested_fields,
    source_evidence_double_check,
)

from ._access import grant_expired, matching_bundles, normalize_grants
from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle
from .semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    AuthorizedSemanticSource,
    DEFAULT_SEMANTIC_PLAN_LIMITS,
    SEMANTIC_CLAIM_STRENGTH_BY_CLASS,
    deterministic_query_class,
    authorized_permission_scope_matches,
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


@dataclass(frozen=True)
class MailEvidenceQueryResult:
    status: str
    mail_import_session_id: str | None
    query_hash: str
    evidence_snippets: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "mail_evidence_query_result")
        return payload


@dataclass(frozen=True)
class _IndexedMailSnippet:
    mail_evidence_bundle_id: str
    searchable_tokens: set[str]
    payload: dict[str, Any]
    dense_evidence_text: str = field(repr=False)
    source_observation_hash: str | None = None
    protected_identifier_tokens: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _MailSnippetIndex:
    snippets: tuple[_IndexedMailSnippet, ...]
    snippet_indexes_by_token: dict[str, tuple[int, ...]]
    profile_fingerprint: str = MAIL_TOKENIZER_PROFILE_FINGERPRINT
    observation_snapshot_fingerprint: str | None = None
    candidate_manifest_fingerprint: str | None = None
    index_fingerprint: str | None = None
    protected_identifier_count: int = 0


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
            or observation.observation_type not in _ATTACHMENT_CHILD_OBSERVATION_TYPES
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
    ) -> None:
        if not isinstance(lazy_index, bool):
            raise ContractValidationError("lazy_index must be a boolean")
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
                if tokenizer_profile is None:
                    snippet_index = _build_snippet_index(bundle)
                else:
                    snippet_index = _build_snippet_index(
                        bundle,
                        tokenizer_profile=self._tokenizer_profile,
                    )
            if snippet_index is not None:
                _require_matching_profile(snippet_index, self._tokenizer_profile)
                self._snippet_index_by_bundle_id[bundle.mail_evidence_bundle_id] = snippet_index

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
                verified_citation_lineages.append(
                    (observation_hash, lineage.lineage_fingerprint)
                )
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
            project_source_observation.source_lookup_terms = tuple(sorted(
                required_terms if required_terms is not None else query_terms
            ))
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
            if (
                observed_selector not in selector_ids
                or observed_selector != active_scan_selector
            ):
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
            read_source=read_authorized_mail_sources
            if callable(scan_source)
            else None,
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
        if query_class == "evidence_lookup" and requested_fields and status not in {
            "error", "permission_denied"
        }:
            missing_fields = [
                field_name for field_name in requested_fields
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
    snippet_index: _MailSnippetIndex, terms: set[str]
) -> tuple[int, ...]:
    indexes: set[int] = set()
    for term in terms:
        indexes.update(snippet_index.snippet_indexes_by_token.get(term, ()))
    return tuple(sorted(indexes))


def _build_snippet_index(
    bundle: MailEvidenceBundle,
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile | None = None,
    source_observation_hashes: Mapping[str, str] | None = None,
    observation_snapshot_fingerprint: str | None = None,
) -> _MailSnippetIndex:
    profile = tokenizer_profile or _load_mail_tokenizer_profile()
    messages_by_id = {message.email_message_id: message for message in bundle.messages}
    indexed: list[_IndexedMailSnippet] = []
    indexes_by_token: dict[str, list[int]] = {}
    protected_identifier_count = 0
    for segment in bundle.body_segments:
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
                dense_evidence_text=searchable,
                payload={
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
    return _MailSnippetIndex(
        snippets=tuple(indexed),
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
    redacted, count = redact_public_raw_references(value)
    for pattern in _SEMANTIC_GATEWAY_TEXT_REDACTIONS:
        redacted, replacement_count = pattern.subn("[redacted_mail_evidence]", redacted)
        count += replacement_count
    return redacted, count


def _citation_for_snippet(snippet: dict[str, Any]) -> dict[str, Any]:
    citation = {
        "citation_id": "mailcitation_"
        + sha256_json(
            {
                "mail_import_session_id": snippet["mail_import_session_id"],
                "source_observation_id": snippet["source_observation_id"],
            }
        )[-24:],
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
