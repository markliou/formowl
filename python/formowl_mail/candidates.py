from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from formowl_contract import (
    CandidateAtom,
    CandidateMention,
    CandidateRelation,
    ContractValidationError,
    Observation,
    PermissionScope,
    SemanticMetadata,
    now_iso,
    sha256_json,
    stable_candidate_atom_id,
    stable_candidate_mention_id,
    stable_candidate_relation_id,
    stable_semantic_metadata_id,
)
from formowl_core import (
    ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    MailCandidateAdmissionTokenizerProfile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_graph.storage import (
    CandidateAtomStore,
    CandidateMentionStore,
    CandidateRelationStore,
    SemanticMetadataStore,
)

from ._guards import assert_public_payload_safe
from .evidence import MailEvidenceRecord, build_mail_evidence_pack

TENANT_WORKSPACE_IDENTITY_SCOPE_MODE = "tenant_workspace_v1"
WORKSPACE_ONLY_IDENTITY_SCOPE_MODE = "workspace_only_v1"
_APPROVED_IDENTITY_SCOPE_MODES = frozenset(
    {
        TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
        WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    }
)
SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID = "mail_source_bound_protected_identifier_mentions_v2"
_SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY = {
    "policy_id": SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
    "candidate_state": "pending_review",
    "canonical_write_allowed": False,
    "identifier_admission": "frozen_target_protected_identifier_occurrences_only",
    "occurrence_cardinality": "one_candidate_mention_per_source_occurrence",
    "occurrence_limit": None,
    "resolution_mode": "exact_protected_token_hash_only",
    "source_locator_storage": "fingerprint_only",
    "identity_scope_modes": sorted(_APPROVED_IDENTITY_SCOPE_MODES),
    "identity_scope_contract": {
        "tenant_workspace_v1": "tenant_and_workspace_required",
        "workspace_only_v1": ("tenant_absent_and_attestation_policy_operator_spec_approval_bound"),
        "legacy_raw_tenant_api_allowed": False,
    },
}
SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT = sha256_json(
    _SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY
)

_MARKERS = {
    "update": "status_update",
    "status": "status_update",
    "blocker": "blocker",
    "owner": "responsible_party",
    "responsible": "responsible_party",
    "next action": "next_action",
    "action item": "next_action",
    "deadline": "deadline",
    "decision": "decision",
    "risk": "risk",
}


@dataclass(frozen=True)
class MailCandidateBridgeResult:
    semantic_metadata: list[SemanticMetadata] = field(default_factory=list)
    candidate_atoms: list[CandidateAtom] = field(default_factory=list)
    candidate_relations: list[CandidateRelation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourceIdentifierIdentityScope:
    """Validated attestation binding used by source identifier owner APIs."""

    identity_scope_mode: str
    identity_scope_fingerprint: str
    workspace_id: str
    identity_scope_attestation_fingerprint: str
    identity_scope_policy_fingerprint: str
    operator_approval_fingerprint: str
    tenant_id: str | None = None
    spec_approval_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _validate_identity_scope(self)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "identity_scope_mode": self.identity_scope_mode,
            "identity_scope_fingerprint": self.identity_scope_fingerprint,
            "workspace_id": self.workspace_id,
            "identity_scope_attestation_fingerprint": (self.identity_scope_attestation_fingerprint),
            "identity_scope_policy_fingerprint": self.identity_scope_policy_fingerprint,
            "operator_approval_fingerprint": self.operator_approval_fingerprint,
        }
        if self.identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
            payload["tenant_id"] = self.tenant_id
        if self.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
            payload["spec_approval_fingerprint"] = self.spec_approval_fingerprint
        return payload


@dataclass(frozen=True)
class SourceBoundIdentifierMentionBatch:
    """One immutable candidate-only batch over source Observation occurrences."""

    candidate_mentions: tuple[CandidateMention, ...]
    tokenizer_id: str
    tokenizer_profile_fingerprint: str
    extraction_policy_id: str
    extraction_policy_fingerprint: str
    identity_scope_mode: str
    identity_scope_fingerprint: str
    workspace_id: str
    identity_scope_attestation_fingerprint: str
    identity_scope_policy_fingerprint: str
    operator_approval_fingerprint: str
    tenant_id: str | None
    spec_approval_fingerprint: str | None
    occurrence_count: int
    batch_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "candidate_mentions": [mention.to_dict() for mention in self.candidate_mentions],
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_profile_fingerprint": self.tokenizer_profile_fingerprint,
            "extraction_policy_id": self.extraction_policy_id,
            "extraction_policy_fingerprint": self.extraction_policy_fingerprint,
            "identity_scope_mode": self.identity_scope_mode,
            "identity_scope_fingerprint": self.identity_scope_fingerprint,
            "workspace_id": self.workspace_id,
            "identity_scope_attestation_fingerprint": (self.identity_scope_attestation_fingerprint),
            "identity_scope_policy_fingerprint": self.identity_scope_policy_fingerprint,
            "operator_approval_fingerprint": self.operator_approval_fingerprint,
            "occurrence_count": self.occurrence_count,
            "batch_fingerprint": self.batch_fingerprint,
        }
        if self.identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
            payload["tenant_id"] = self.tenant_id
        if self.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
            payload["spec_approval_fingerprint"] = self.spec_approval_fingerprint
        return payload


class IdentifierOccurrenceOverflowError(ContractValidationError):
    """Explicit fail-closed blocker for a caller-supplied occurrence cap."""

    blocker_id = "source_bound_identifier_occurrence_overflow"

    def __init__(self, *, occurrence_count: int, occurrence_limit: int) -> None:
        self.occurrence_count = occurrence_count
        self.occurrence_limit = occurrence_limit
        super().__init__(
            f"{self.blocker_id}: occurrence_count={occurrence_count} "
            f"occurrence_limit={occurrence_limit}"
        )


def extract_source_bound_identifier_mentions(
    observations: Sequence[Observation],
    *,
    identity_scope: SourceIdentifierIdentityScope,
    extractor_run_id: str,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile | None = None,
    created_at: str | None = None,
    max_identifier_occurrences: int | None = None,
) -> SourceBoundIdentifierMentionBatch:
    """Extract one candidate mention for every protected identifier occurrence.

    The normal path loads the packaged Issue #56 profile and fails closed when
    its runtime or artifacts are unavailable.  The optional profile argument is
    only an explicit dependency-injection surface; ASCII and fingerprint drift
    are rejected before any Observation is consumed.
    """

    if not isinstance(identity_scope, SourceIdentifierIdentityScope):
        raise ContractValidationError(
            "source-bound identifier extraction requires SourceIdentifierIdentityScope"
        )
    _validate_identity_scope(identity_scope)
    _validate_safe_id(extractor_run_id, "extractor_run_id")
    _validate_occurrence_limit(max_identifier_occurrences)
    active_profile = tokenizer_profile or load_issue56_target_mail_tokenizer_profile()
    _validate_target_identifier_profile(active_profile)
    resolved_created_at = created_at or now_iso()
    validated_observations = _validated_unique_observations(observations)
    mentions: list[CandidateMention] = []
    for observation in validated_observations:
        text = observation.text
        if text is None or not text:
            continue
        message_occurrence_id = _message_occurrence_id(observation)
        permission_scope = _permission_scope_dict(observation.permission_scope)
        permission_boundary_fingerprint = sha256_json(permission_scope)
        source_locator_fingerprint = sha256_json(observation.location)
        message_occurrence_fingerprint = sha256_json(message_occurrence_id)
        source_observation_fingerprint = sha256_json(observation.to_dict())
        source_provenance_fingerprint = sha256_json(
            {
                "asset_id": observation.asset_id,
                "evidence_snapshot_id": observation.evidence_snapshot_id,
                "extractor_run_id": observation.extractor_run_id,
                "modality": observation.modality,
                "observation_type": observation.observation_type,
            }
        )
        tokenization = active_profile.analyze(text)
        for span in tokenization.protected_identifiers:
            exact_protected_token_hash = sha256_json(span.exact_token)
            occurrence_scope_fingerprint = sha256_json(
                {
                    "source_observation_fingerprint": source_observation_fingerprint,
                    "message_occurrence_fingerprint": message_occurrence_fingerprint,
                    "source_locator_fingerprint": source_locator_fingerprint,
                    "span_start": span.start,
                    "span_end": span.end,
                    "identifier_kind": span.identifier_kind,
                }
            )
            location = {
                "source_observation_id": observation.observation_id,
                "message_occurrence_fingerprint": message_occurrence_fingerprint,
                "source_locator_fingerprint": source_locator_fingerprint,
                "identity_scope_mode": identity_scope.identity_scope_mode,
                "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
                "workspace_id": identity_scope.workspace_id,
                "identity_scope_attestation_fingerprint": (
                    identity_scope.identity_scope_attestation_fingerprint
                ),
                "identity_scope_policy_fingerprint": (
                    identity_scope.identity_scope_policy_fingerprint
                ),
                "operator_approval_fingerprint": (identity_scope.operator_approval_fingerprint),
                "permission_boundary_fingerprint": permission_boundary_fingerprint,
                "tokenizer_profile_fingerprint": active_profile.profile_fingerprint,
                "extraction_policy_fingerprint": (
                    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
                ),
                "span_start": span.start,
                "span_end": span.end,
                "identifier_kind": span.identifier_kind,
                "occurrence_scope_fingerprint": occurrence_scope_fingerprint,
            }
            if identity_scope.identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
                location["tenant_id"] = identity_scope.tenant_id
            else:
                location["spec_approval_fingerprint"] = identity_scope.spec_approval_fingerprint
            metadata = {
                "candidate_kind": "protected_identifier_occurrence",
                "canonical_write_allowed": False,
                "candidate_only": True,
                "exact_protected_token_hash": exact_protected_token_hash,
                **identity_scope.to_dict(),
                "permission_scope": permission_scope,
                "permission_boundary_fingerprint": permission_boundary_fingerprint,
                "tokenizer_id": active_profile.tokenizer_id,
                "tokenizer_profile_fingerprint": active_profile.profile_fingerprint,
                "normalization_id": active_profile.normalization_id,
                "normalization_fingerprint": active_profile.normalization_sha256,
                "protected_identifier_policy_id": (active_profile.protected_identifier_policy_id),
                "protected_identifier_policy_fingerprint": (
                    active_profile.protected_identifier_policy_sha256
                ),
                "candidate_admission_policy_id": (active_profile.candidate_admission_policy_id),
                "candidate_admission_policy_fingerprint": (
                    active_profile.candidate_admission_policy_sha256
                ),
                "extraction_policy_id": SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
                "extraction_policy_fingerprint": (
                    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
                ),
                "source_observation_fingerprint": source_observation_fingerprint,
                "source_extractor_provenance_fingerprint": (source_provenance_fingerprint),
                "message_occurrence_fingerprint": message_occurrence_fingerprint,
                "source_locator_fingerprint": source_locator_fingerprint,
                "occurrence_scope_fingerprint": occurrence_scope_fingerprint,
            }
            mention_id = stable_candidate_mention_id(
                source_observation_ids=[observation.observation_id],
                mention_type=f"protected_identifier:{span.identifier_kind}",
                normalized_label=exact_protected_token_hash,
                location=location,
                extractor_run_id=extractor_run_id,
            )
            mentions.append(
                CandidateMention.from_dict(
                    {
                        "candidate_mention_id": mention_id,
                        "source_observation_ids": [observation.observation_id],
                        "mention_type": (f"protected_identifier:{span.identifier_kind}"),
                        "normalized_label": exact_protected_token_hash,
                        "location": location,
                        "text_hash": exact_protected_token_hash,
                        "confidence": 1.0,
                        "extractor_run_id": extractor_run_id,
                        "status": "pending_review",
                        "requires_review": True,
                        "created_at": resolved_created_at,
                        "metadata": metadata,
                    }
                )
            )

    mentions.sort(key=lambda mention: mention.candidate_mention_id)
    if max_identifier_occurrences is not None and len(mentions) > max_identifier_occurrences:
        raise IdentifierOccurrenceOverflowError(
            occurrence_count=len(mentions),
            occurrence_limit=max_identifier_occurrences,
        )
    if len({mention.candidate_mention_id for mention in mentions}) != len(mentions):
        raise ContractValidationError("protected identifier occurrence identity is not unique")
    batch_fingerprint = sha256_json(
        {
            "candidate_mention_ids": [mention.candidate_mention_id for mention in mentions],
            "extraction_policy_fingerprint": (
                SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
            ),
            "identity_scope": identity_scope.to_dict(),
            "tokenizer_profile_fingerprint": active_profile.profile_fingerprint,
        }
    )
    return SourceBoundIdentifierMentionBatch(
        candidate_mentions=tuple(mentions),
        tokenizer_id=active_profile.tokenizer_id,
        tokenizer_profile_fingerprint=active_profile.profile_fingerprint,
        extraction_policy_id=SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
        extraction_policy_fingerprint=(SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT),
        identity_scope_mode=identity_scope.identity_scope_mode,
        identity_scope_fingerprint=identity_scope.identity_scope_fingerprint,
        workspace_id=identity_scope.workspace_id,
        identity_scope_attestation_fingerprint=(
            identity_scope.identity_scope_attestation_fingerprint
        ),
        identity_scope_policy_fingerprint=identity_scope.identity_scope_policy_fingerprint,
        operator_approval_fingerprint=identity_scope.operator_approval_fingerprint,
        tenant_id=identity_scope.tenant_id,
        spec_approval_fingerprint=identity_scope.spec_approval_fingerprint,
        occurrence_count=len(mentions),
        batch_fingerprint=batch_fingerprint,
    )


def extract_and_store_source_bound_identifier_mentions(
    observations: Sequence[Observation],
    *,
    candidate_mention_store: CandidateMentionStore,
    identity_scope: SourceIdentifierIdentityScope,
    extractor_run_id: str,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile | None = None,
    created_at: str | None = None,
    max_identifier_occurrences: int | None = None,
) -> SourceBoundIdentifierMentionBatch:
    """Validate the complete occurrence batch before candidate-store writes."""

    result = extract_source_bound_identifier_mentions(
        observations,
        identity_scope=identity_scope,
        extractor_run_id=extractor_run_id,
        tokenizer_profile=tokenizer_profile,
        created_at=created_at,
        max_identifier_occurrences=max_identifier_occurrences,
    )
    validated_mentions = tuple(
        CandidateMention.from_dict(mention.to_dict()) for mention in result.candidate_mentions
    )
    for mention in validated_mentions:
        candidate_mention_store.validate_candidate_mention_id(mention.candidate_mention_id)
        existing = candidate_mention_store.get(mention.candidate_mention_id)
        if existing is not None and existing.to_dict() != mention.to_dict():
            raise ContractValidationError("candidate mention immutable identity conflict")
    for mention in validated_mentions:
        candidate_mention_store.create(mention)
    return SourceBoundIdentifierMentionBatch(
        candidate_mentions=validated_mentions,
        tokenizer_id=result.tokenizer_id,
        tokenizer_profile_fingerprint=result.tokenizer_profile_fingerprint,
        extraction_policy_id=result.extraction_policy_id,
        extraction_policy_fingerprint=result.extraction_policy_fingerprint,
        identity_scope_mode=result.identity_scope_mode,
        identity_scope_fingerprint=result.identity_scope_fingerprint,
        identity_scope_attestation_fingerprint=(result.identity_scope_attestation_fingerprint),
        identity_scope_policy_fingerprint=result.identity_scope_policy_fingerprint,
        operator_approval_fingerprint=result.operator_approval_fingerprint,
        tenant_id=result.tenant_id,
        workspace_id=result.workspace_id,
        spec_approval_fingerprint=result.spec_approval_fingerprint,
        occurrence_count=result.occurrence_count,
        batch_fingerprint=result.batch_fingerprint,
    )


def extract_mail_semantics_and_candidates(
    observations: Sequence[Observation],
    *,
    extractor_run_id: str,
    created_at: str | None = None,
) -> MailCandidateBridgeResult:
    _validate_id(extractor_run_id, "extractor_run_id")
    resolved_created_at = created_at or now_iso()
    pack = build_mail_evidence_pack(observations, created_at=resolved_created_at)
    semantic_metadata: list[SemanticMetadata] = []
    candidate_atoms: list[CandidateAtom] = []
    candidate_relations: list[CandidateRelation] = []
    warnings = list(pack.warnings)
    thread_atoms: dict[str, CandidateAtom] = {}

    for record in pack.records:
        if record.thread_id:
            thread_atoms.setdefault(
                record.thread_id,
                _thread_atom(
                    record=record,
                    extractor_run_id=extractor_run_id,
                    created_at=resolved_created_at,
                ),
            )
        for source_observation_id, atom_type, label, source_line in _marked_items(record):
            value = _semantic_value(record=record, atom_type=atom_type, label=label)
            semantic = _semantic_metadata(
                source_observation_id=source_observation_id,
                metadata_type=atom_type,
                value=value,
                extractor_run_id=extractor_run_id,
                created_at=resolved_created_at,
            )
            atom = _candidate_atom(
                source_observation_id=source_observation_id,
                semantic_metadata_id=semantic.semantic_metadata_id,
                atom_type=atom_type,
                label=label,
                record=record,
                source_line=source_line,
                extractor_run_id=extractor_run_id,
                created_at=resolved_created_at,
            )
            semantic_metadata.append(semantic)
            candidate_atoms.append(atom)
            if record.thread_id:
                candidate_relations.append(
                    _candidate_relation_to_thread(
                        source_atom=atom,
                        target_atom=thread_atoms[record.thread_id],
                        source_observation_id=source_observation_id,
                        semantic_metadata_id=semantic.semantic_metadata_id,
                        extractor_run_id=extractor_run_id,
                        created_at=resolved_created_at,
                    )
                )

    candidate_atoms = [*thread_atoms.values(), *candidate_atoms]
    if not semantic_metadata:
        warnings.append("no_mail_semantic_markers")
    _assert_bridge_result_public_payload_safe(
        semantic_metadata=semantic_metadata,
        candidate_atoms=candidate_atoms,
        candidate_relations=candidate_relations,
    )
    return MailCandidateBridgeResult(
        semantic_metadata=semantic_metadata,
        candidate_atoms=candidate_atoms,
        candidate_relations=candidate_relations,
        warnings=warnings,
    )


def extract_and_store_mail_candidates(
    observations: Sequence[Observation],
    *,
    semantic_metadata_store: SemanticMetadataStore,
    candidate_atom_store: CandidateAtomStore,
    candidate_relation_store: CandidateRelationStore,
    extractor_run_id: str,
    created_at: str | None = None,
) -> MailCandidateBridgeResult:
    result = extract_mail_semantics_and_candidates(
        observations,
        extractor_run_id=extractor_run_id,
        created_at=created_at,
    )
    validated_semantics = [
        SemanticMetadata.from_dict(item.to_dict()) for item in result.semantic_metadata
    ]
    validated_atoms = [CandidateAtom.from_dict(item.to_dict()) for item in result.candidate_atoms]
    validated_relations = [
        CandidateRelation.from_dict(item.to_dict()) for item in result.candidate_relations
    ]

    for semantic in validated_semantics:
        semantic_metadata_store.validate_semantic_metadata_id(semantic.semantic_metadata_id)
    for atom in validated_atoms:
        candidate_atom_store.validate_candidate_atom_id(atom.candidate_atom_id)
    for relation in validated_relations:
        candidate_relation_store.validate_candidate_relation_id(relation.candidate_relation_id)

    for semantic in validated_semantics:
        semantic_metadata_store.create(semantic)
    for atom in validated_atoms:
        candidate_atom_store.create(atom)
    for relation in validated_relations:
        candidate_relation_store.create(relation)

    return MailCandidateBridgeResult(
        semantic_metadata=validated_semantics,
        candidate_atoms=validated_atoms,
        candidate_relations=validated_relations,
        warnings=list(result.warnings),
    )


def _marked_items(record: MailEvidenceRecord) -> list[tuple[str, str, str, str]]:
    items: list[tuple[str, str, str, str]] = []
    for segment in record.body_segments:
        for line in segment.text.splitlines():
            marker = _parse_marker_line(line)
            if marker is None:
                continue
            atom_type, label = marker
            _validate_public_label(label)
            items.append((segment.observation_id, atom_type, label, line.strip()))
    return items


def _parse_marker_line(line: str) -> tuple[str, str] | None:
    marker_text, separator, label = line.partition(":")
    if not separator:
        return None
    atom_type = _MARKERS.get(marker_text.strip().lower())
    if atom_type is None:
        return None
    label = label.strip()
    if not label:
        return None
    return atom_type, label


def _semantic_metadata(
    *,
    source_observation_id: str,
    metadata_type: str,
    value: dict[str, str],
    extractor_run_id: str,
    created_at: str,
) -> SemanticMetadata:
    semantic_metadata_id = stable_semantic_metadata_id(
        source_observation_ids=[source_observation_id],
        metadata_type=metadata_type,
        value=value,
        extractor_run_id=extractor_run_id,
    )
    return SemanticMetadata.from_dict(
        {
            "semantic_metadata_id": semantic_metadata_id,
            "source_observation_ids": [source_observation_id],
            "metadata_type": metadata_type,
            "value": value,
            "confidence": 1.0,
            "extractor_run_id": extractor_run_id,
            "requires_review": True,
            "created_at": created_at,
        }
    )


def _candidate_atom(
    *,
    source_observation_id: str,
    semantic_metadata_id: str,
    atom_type: str,
    label: str,
    record: MailEvidenceRecord,
    source_line: str,
    extractor_run_id: str,
    created_at: str,
) -> CandidateAtom:
    properties = {
        "source": "mail",
        "message_id": record.message_id,
        "thread_id": record.thread_id,
        "sender": record.sender,
        "sent_at": record.sent_at,
        "source_line": source_line,
    }
    candidate_atom_id = stable_candidate_atom_id(
        source_observation_ids=[source_observation_id],
        atom_type=atom_type,
        label=label,
        properties=properties,
        extractor_run_id=extractor_run_id,
    )
    return CandidateAtom.from_dict(
        {
            "candidate_atom_id": candidate_atom_id,
            "source_observation_ids": [source_observation_id],
            "source_semantic_metadata_ids": [semantic_metadata_id],
            "atom_type": atom_type,
            "label": label,
            "properties": properties,
            "confidence": 1.0,
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "created_at": created_at,
        }
    )


def _thread_atom(
    *,
    record: MailEvidenceRecord,
    extractor_run_id: str,
    created_at: str,
) -> CandidateAtom:
    source_observation_ids = list(record.observation_ids)
    label = record.normalized_subject or record.subject or record.thread_id or "mail thread"
    properties = {
        "source": "mail",
        "thread_id": record.thread_id,
        "mailbox_id": record.mailbox_id,
        "archive_id": record.archive_id,
    }
    candidate_atom_id = stable_candidate_atom_id(
        source_observation_ids=source_observation_ids,
        atom_type="mail_thread",
        label=label,
        properties=properties,
        extractor_run_id=extractor_run_id,
    )
    return CandidateAtom.from_dict(
        {
            "candidate_atom_id": candidate_atom_id,
            "source_observation_ids": source_observation_ids,
            "atom_type": "mail_thread",
            "label": label,
            "properties": properties,
            "confidence": 1.0,
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "created_at": created_at,
        }
    )


def _candidate_relation_to_thread(
    *,
    source_atom: CandidateAtom,
    target_atom: CandidateAtom,
    source_observation_id: str,
    semantic_metadata_id: str,
    extractor_run_id: str,
    created_at: str,
) -> CandidateRelation:
    properties = {"source": "mail", "relation_basis": "same_thread"}
    relation_id = stable_candidate_relation_id(
        source_candidate_atom_id=source_atom.candidate_atom_id,
        target_candidate_atom_id=target_atom.candidate_atom_id,
        relation_type="mentioned_in_mail_thread",
        source_observation_ids=[source_observation_id],
        properties=properties,
        extractor_run_id=extractor_run_id,
    )
    return CandidateRelation.from_dict(
        {
            "candidate_relation_id": relation_id,
            "source_candidate_atom_id": source_atom.candidate_atom_id,
            "target_candidate_atom_id": target_atom.candidate_atom_id,
            "relation_type": "mentioned_in_mail_thread",
            "source_observation_ids": [source_observation_id],
            "source_semantic_metadata_ids": [semantic_metadata_id],
            "properties": properties,
            "confidence": 1.0,
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "created_at": created_at,
        }
    )


def _semantic_value(record: MailEvidenceRecord, *, atom_type: str, label: str) -> dict[str, str]:
    value = {
        "source": "mail",
        "category": atom_type,
        "label": label,
        "message_id": record.message_id,
    }
    for key, item in (
        ("thread_id", record.thread_id),
        ("sender", record.sender),
        ("sent_at", record.sent_at),
        ("subject", record.subject),
    ):
        if item:
            value[key] = item
    return value


def _validate_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")


def _validate_safe_id(value: str, field_name: str) -> None:
    _validate_id(value, field_name)
    assert_public_payload_safe(value, field_name)


def _validate_occurrence_limit(value: int | None) -> None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
        raise ContractValidationError(
            "max_identifier_occurrences must be a positive integer or None"
        )


def _validate_identity_scope(identity_scope: SourceIdentifierIdentityScope) -> None:
    mode = identity_scope.identity_scope_mode
    if mode not in _APPROVED_IDENTITY_SCOPE_MODES:
        raise ContractValidationError("identity_scope_mode is not approved")
    _validate_safe_id(identity_scope.workspace_id, "identity_scope.workspace_id")
    for field_name, value in (
        ("identity_scope_fingerprint", identity_scope.identity_scope_fingerprint),
        (
            "identity_scope_attestation_fingerprint",
            identity_scope.identity_scope_attestation_fingerprint,
        ),
        (
            "identity_scope_policy_fingerprint",
            identity_scope.identity_scope_policy_fingerprint,
        ),
        ("operator_approval_fingerprint", identity_scope.operator_approval_fingerprint),
    ):
        _validate_sha256(value, f"identity_scope.{field_name}")
    if mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        _validate_safe_id(identity_scope.tenant_id, "identity_scope.tenant_id")
        if identity_scope.spec_approval_fingerprint is not None:
            raise ContractValidationError("tenant_workspace_v1 forbids spec_approval_fingerprint")
        expected_scope = {
            "mode": mode,
            "workspace_id": identity_scope.workspace_id,
            "tenant_id": identity_scope.tenant_id,
        }
    else:
        if identity_scope.tenant_id is not None:
            raise ContractValidationError("workspace_only_v1 forbids tenant_id fabrication")
        _validate_sha256(
            identity_scope.spec_approval_fingerprint,
            "identity_scope.spec_approval_fingerprint",
        )
        expected_scope = {
            "mode": mode,
            "workspace_id": identity_scope.workspace_id,
        }
    if identity_scope.identity_scope_fingerprint != sha256_json(expected_scope):
        raise ContractValidationError("identity_scope fingerprint binding mismatch")


def _validate_sha256(value: Any, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ContractValidationError(f"{field_name} must be a sha256 fingerprint")


def _validate_target_identifier_profile(
    profile: MailCandidateAdmissionTokenizerProfile,
) -> None:
    if not isinstance(profile, MailCandidateAdmissionTokenizerProfile):
        raise ContractValidationError(
            "protected identifier extraction requires a tokenizer profile"
        )
    if (
        profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
        or profile.profile_fingerprint != ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
        or sha256_json(profile.fingerprint_payload())
        != ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
    ):
        raise ContractValidationError(
            "protected identifier extraction requires the frozen target profile"
        )


def _validated_unique_observations(
    observations: Sequence[Observation],
) -> list[Observation]:
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise ContractValidationError("observations must be a sequence")
    validated: dict[str, Observation] = {}
    for observation in observations:
        if not isinstance(observation, Observation):
            raise ContractValidationError(
                "source-bound identifier extraction requires Observation records"
            )
        item = Observation.from_dict(observation.to_dict())
        if item.observation_id in validated:
            raise ContractValidationError(
                "source-bound identifier extraction requires unique Observation ids"
            )
        validated[item.observation_id] = item
    return [validated[observation_id] for observation_id in sorted(validated)]


def _message_occurrence_id(observation: Observation) -> str:
    values = {
        value
        for source in (observation.location, observation.payload or {})
        for value in [source.get("message_occurrence_id")]
        if isinstance(value, str) and value
    }
    if len(values) != 1:
        raise ContractValidationError(
            "source-bound identifier extraction requires one message occurrence lineage"
        )
    return next(iter(values))


def _permission_scope_dict(
    permission_scope: PermissionScope | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(permission_scope, PermissionScope):
        return permission_scope.to_dict()
    if not isinstance(permission_scope, Mapping):
        raise ContractValidationError("permission_scope must be an object")
    return dict(permission_scope)


def _validate_public_label(value: str) -> None:
    assert_public_payload_safe(value, "mail_candidate_label")


def _assert_bridge_result_public_payload_safe(
    *,
    semantic_metadata: Sequence[SemanticMetadata],
    candidate_atoms: Sequence[CandidateAtom],
    candidate_relations: Sequence[CandidateRelation],
) -> None:
    # Validate the full public payload before any store write so a rejected
    # candidate batch leaves semantic, atom, and relation stores untouched.
    assert_public_payload_safe(
        {
            "semantic_metadata": [item.to_dict() for item in semantic_metadata],
            "candidate_atoms": [item.to_dict() for item in candidate_atoms],
            "candidate_relations": [item.to_dict() for item in candidate_relations],
        },
        "mail_candidate_bridge_result",
    )


__all__ = [
    "IdentifierOccurrenceOverflowError",
    "MailCandidateBridgeResult",
    "SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT",
    "SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID",
    "SourceIdentifierIdentityScope",
    "SourceBoundIdentifierMentionBatch",
    "TENANT_WORKSPACE_IDENTITY_SCOPE_MODE",
    "WORKSPACE_ONLY_IDENTITY_SCOPE_MODE",
    "extract_and_store_source_bound_identifier_mentions",
    "extract_and_store_mail_candidates",
    "extract_source_bound_identifier_mentions",
    "extract_mail_semantics_and_candidates",
]
