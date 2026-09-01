from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence, TypeAlias

from formowl_contract import (
    ContractValidationError,
    Grant,
    Observation,
    redact_public_raw_references,
    sha256_json,
    to_plain,
)
from formowl_core import (
    jieba_sentencepiece_frozen_profile_candidate_admission_tokens,
    load_default_mail_candidate_admission_tokenizer_profile,
)
from formowl_core.tokenization import (
    ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    MailCandidateAdmissionTokenizerProfile,
)

from ._access import grant_expired, matching_bundles, normalize_grants
from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle
from .semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    AuthorizedSemanticSource,
    authorized_permission_scope_matches,
)

MAIL_TOKENIZER_ID = JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
MAIL_TOKENIZER_PROFILE_FINGERPRINT = ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
_MAIL_EVIDENCE_PERMISSIONS = {"read", "evidence_snippet", "mail_evidence_read"}
_SEMANTIC_GATEWAY_TEXT_REDACTIONS = (
    re.compile(r"\bwith\s+.+\s+as\s*\(", re.IGNORECASE),
    re.compile(r"\bcopy\s+.+\s+from\b", re.IGNORECASE),
    re.compile(r"\bTraceback \(most recent call last\):", re.IGNORECASE),
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
                "parent_attachment_observation_id": (
                    self.parent_attachment_observation_id
                ),
                "message_occurrence_id": self.message_occurrence_id,
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


SourceOccurrenceLineage: TypeAlias = (
    MailMessageOccurrenceLineage
    | MailAttachmentChildOccurrenceLineage
    | GitHubProjectOccurrenceLineage
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

    observation_by_id = {
        observation.observation_id: Observation.from_dict(observation.to_dict())
        for observation in observations
    }
    if len(observation_by_id) != len(observations):
        raise ContractValidationError("attachment lineage has duplicate Observation ids")
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
    resolved: list[SourceOccurrenceLineage] = []
    for observation_id in sorted(observation_by_id):
        observation = observation_by_id[observation_id]
        expected = child_lineage_by_id.get(observation_id)
        supplied = supplied_by_id.get(observation_id)
        if expected is None:
            if supplied is None:
                raise ContractValidationError(
                    "attachment lineage input is incomplete"
                )
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
        re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
        for value in matched_hashes
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
    ) -> None:
        self._bundles = list(bundles)
        self._tokenizer_profile = tokenizer_profile or _load_mail_tokenizer_profile()
        supplied_indexes = dict(snippet_index_by_bundle_id or {})
        known_bundle_ids = {bundle.mail_evidence_bundle_id for bundle in self._bundles}
        if set(supplied_indexes) - known_bundle_ids:
            raise ContractValidationError("mail evidence index does not match selected bundles")
        self._snippet_index_by_bundle_id: dict[str, _MailSnippetIndex] = {}
        for bundle in self._bundles:
            snippet_index = supplied_indexes.get(bundle.mail_evidence_bundle_id)
            if snippet_index is None:
                if tokenizer_profile is None:
                    snippet_index = _build_snippet_index(bundle)
                else:
                    snippet_index = _build_snippet_index(
                        bundle,
                        tokenizer_profile=self._tokenizer_profile,
                    )
            _require_matching_profile(snippet_index, self._tokenizer_profile)
            self._snippet_index_by_bundle_id[bundle.mail_evidence_bundle_id] = snippet_index

    @property
    def tokenizer_profile_fingerprint(self) -> str:
        return self._tokenizer_profile.profile_fingerprint

    @property
    def index_fingerprints(self) -> dict[str, str | None]:
        return {
            bundle_id: snippet_index.index_fingerprint
            for bundle_id, snippet_index in self._snippet_index_by_bundle_id.items()
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


def _search_visible_bundles(
    bundles: Sequence[MailEvidenceBundle],
    *,
    query_text: str,
    limit: int,
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex] | None = None,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile | None = None,
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
    if authorized_source.source_kind == AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND:
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
    if authorized_source.source_kind == GITHUB_PROJECT_OBSERVATION_SOURCE_KIND:
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
    raise ContractValidationError("semantic query source kind is unsupported")


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
        normalized_by_id[validated.observation_id] = validated
        observation_hash_by_id[validated.observation_id] = sha256_json(
            serialized_snapshot
        )
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
        _validate_observation_source_scope(
            observation,
            authorized_source=authorized_source,
        )
        if lineage.source_kind != authorized_source.source_kind:
            raise ContractValidationError("Observation index source occurrence mismatch")
        searchable = _source_neutral_searchable_text(
            observation,
            source_kind=authorized_source.source_kind,
        )
        tokenization = tokenizer_profile.analyze(searchable)
        tokens = (
            _tokenize(searchable)
            if _is_target_mail_tokenizer_profile(tokenizer_profile)
            else set(tokenization.tokens)
        )
        if not tokens:
            raise ContractValidationError("Observation index has no searchable evidence")
        protected_tokens = frozenset(
            span.exact_token for span in tokenization.protected_identifiers
        )
        snippet_index = len(indexed)
        permission_fingerprint = sha256_json(to_plain(observation.permission_scope))
        payload = {
            "source_type": observation.observation_type,
            "source_kind": authorized_source.source_kind,
            "source_observation_id": observation.observation_id,
            "source_occurrence_hash": sha256_json(lineage.occurrence_id),
            "source_occurrence_kind": lineage.occurrence_kind,
            "snippet": observation.text or observation.caption or "",
        }
        if lineage.parent_occurrence_id is not None:
            payload["parent_source_occurrence_hash"] = sha256_json(lineage.parent_occurrence_id)
        indexed.append(
            _IndexedObservationSnippet(
                source_access_fingerprint=authorized_source.authorization_fingerprint,
                searchable_tokens=tokens,
                dense_evidence_text=searchable,
                payload=payload,
                source_observation_hash=observation_hash_by_id[observation_id],
                protected_identifier_tokens=protected_tokens,
            )
        )
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
    candidate_manifest_fingerprint = sha256_json(
        [
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
        ]
    )
    index_fingerprint = sha256_json(
        {
            "source_access_fingerprint": (authorized_source.authorization_fingerprint),
            "observation_snapshot_fingerprint": observation_snapshot_fingerprint,
            "occurrence_lineage_fingerprint": occurrence_lineage_fingerprint,
            "permission_set_fingerprint": permission_set_fingerprint,
            "profile_fingerprint": tokenizer_profile.profile_fingerprint,
            "candidate_manifest_fingerprint": candidate_manifest_fingerprint,
            "postings": {
                sha256_json(token): tuple(indexes)
                for token, indexes in sorted(indexes_by_token.items())
            },
        }
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


def _validate_observation_source_scope(
    observation: Observation,
    *,
    authorized_source: AuthorizedSemanticSource,
) -> None:
    permission_scope = to_plain(observation.permission_scope)
    if not isinstance(permission_scope, dict):
        raise ContractValidationError("Observation index permission scope is invalid")
    scope_type = permission_scope.get("scope_type")
    scope_id = permission_scope.get("scope_id")
    if not isinstance(scope_type, str) or not isinstance(scope_id, str) or not scope_id:
        raise ContractValidationError("Observation index permission scope is invalid")
    if authorized_source.source_kind == GITHUB_PROJECT_OBSERVATION_SOURCE_KIND:
        if scope_type != "project" or scope_id not in authorized_source.source_scope_ids:
            raise ContractValidationError("Observation index permission scope mismatch")
        return
    if authorized_source.source_kind == AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND:
        workspace_scope_matches = (
            scope_type == "workspace" and scope_id == authorized_source.workspace_id
        )
        occurrence_scope_matches = (
            scope_type == "mail_import_session" and scope_id in authorized_source.source_scope_ids
        )
        project_scope_matches = (
            scope_type == "project"
            and scope_id in authorized_source.source_scope_ids
            and authorized_permission_scope_matches(
                permission_scope,
                authorized_source=authorized_source,
            )
        )
        if not (workspace_scope_matches or occurrence_scope_matches or project_scope_matches):
            raise ContractValidationError("Observation index permission scope mismatch")
        return
    raise ContractValidationError("semantic query source kind is unsupported")


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
    "SourceOccurrenceLineage",
    "authorize_mail_evidence_bundles",
    "build_authorized_observation_snippet_index",
    "build_existing_observation_snippet_index",
    "build_mail_evidence_query_handler",
    "normalized_authorized_observation_lineages",
    "require_issue56_target_tokenizer_profile",
    "source_occurrence_lineage_from_observation",
    "validate_source_neutral_attachment_observation_coverage",
]
