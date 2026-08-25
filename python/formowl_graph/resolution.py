from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
import importlib
from importlib import metadata
import re
from typing import Any, Iterable, Mapping, Sequence

from formowl_contract import (
    CandidateMention,
    ContractValidationError,
    now_iso,
    sha256_json,
    stable_candidate_mention_id,
    stable_resource_contract_id,
    to_plain,
)

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAW_REFERENCE_PATTERNS = (
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://"),
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(^|[^A-Za-z0-9_])/[^\s:]+"),
    re.compile(r"\\\\"),
)
_ORG_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "limited",
    "llc",
    "ltd",
}
_DEFAULT_REVIEW_ACTIONS = (
    "accept_as_same_as_candidate",
    "reject",
    "defer",
    "request_access_overlay",
)
_RAPIDFUZZ_SOURCE_URL = "https://github.com/rapidfuzz/RapidFuzz"
_SPLINK_SOURCE_URL = "https://moj-analytical-services.github.io/splink/"
_EXACT_PROTECTED_IDENTIFIER_RESOLUTION_POLICY_ID = (
    "exact_source_bound_protected_identifier_candidate_resolution_v2"
)
_TENANT_WORKSPACE_IDENTITY_SCOPE_MODE = "tenant_workspace_v1"
_WORKSPACE_ONLY_IDENTITY_SCOPE_MODE = "workspace_only_v1"
_APPROVED_IDENTITY_SCOPE_MODES = frozenset(
    {
        _TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
        _WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    }
)


@dataclass(frozen=True)
class NormalizationTrace:
    original_label: str
    normalized_label: str
    tokens: tuple[str, ...]
    removed_tokens: tuple[str, ...] = ()

    def to_public_dict(self, *, visible: bool) -> dict[str, Any]:
        if not visible:
            return {
                "redacted": True,
                "token_count": len(self.tokens),
                "removed_token_count": len(self.removed_tokens),
            }
        return {
            "original_label": self.original_label,
            "normalized_label": self.normalized_label,
            "tokens": list(self.tokens),
            "removed_tokens": list(self.removed_tokens),
        }


@dataclass(frozen=True)
class ResolutionRecord:
    record_id: str
    label: str
    core_supertype: str
    owner_user_id: str
    scope_type: str
    scope_id: str
    source_candidate_atom_id: str
    source_observation_ids: tuple[str, ...] = ()
    attributes: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_candidate_atom(
        cls,
        *,
        record_id: str,
        label: str,
        atom_type: str,
        owner_user_id: str,
        scope_type: str,
        scope_id: str,
        source_candidate_atom_id: str,
        source_observation_ids: Sequence[str],
        attributes: Mapping[str, str] | None = None,
    ) -> "ResolutionRecord":
        return cls(
            record_id=record_id,
            label=label,
            core_supertype=atom_type,
            owner_user_id=owner_user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            source_candidate_atom_id=source_candidate_atom_id,
            source_observation_ids=tuple(source_observation_ids),
            attributes=dict(attributes or {}),
        ).validated()

    def validated(self) -> "ResolutionRecord":
        _validate_record_id(self.record_id, "ResolutionRecord.record_id")
        _validate_non_empty_string(self.label, "ResolutionRecord.label")
        _validate_non_empty_string(self.core_supertype, "ResolutionRecord.core_supertype")
        _validate_non_empty_string(self.owner_user_id, "ResolutionRecord.owner_user_id")
        _validate_non_empty_string(self.scope_type, "ResolutionRecord.scope_type")
        _validate_non_empty_string(self.scope_id, "ResolutionRecord.scope_id")
        _validate_record_id(
            self.source_candidate_atom_id,
            "ResolutionRecord.source_candidate_atom_id",
        )
        for observation_id in self.source_observation_ids:
            _validate_record_id(observation_id, "ResolutionRecord.source_observation_ids entry")
        if not isinstance(self.attributes, Mapping):
            raise ContractValidationError("ResolutionRecord.attributes must be an object")
        for key, value in self.attributes.items():
            _validate_non_empty_string(key, "ResolutionRecord.attributes key")
            _validate_non_empty_string(value, f"ResolutionRecord.attributes.{key}")
        _validate_no_raw_reference(
            {
                "label": self.label,
                "owner_user_id": self.owner_user_id,
                "scope_id": self.scope_id,
                "attributes": dict(self.attributes),
            },
            "resolution record",
        )
        return self

    def public_ref(self, *, visible: bool) -> dict[str, Any]:
        if not visible:
            return {"visible": False, "redacted": True}
        return {
            "record_id": self.record_id,
            "core_supertype": self.core_supertype,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "visible": True,
            "label": self.label,
            "owner_user_id": self.owner_user_id,
            "source_candidate_atom_id": self.source_candidate_atom_id,
            "source_observation_ids": list(self.source_observation_ids),
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class EvidenceLink:
    record_id: str
    source_candidate_atom_id: str
    source_observation_ids: tuple[str, ...]

    def to_public_dict(self, *, visible: bool) -> dict[str, Any]:
        if not visible:
            return {
                "visible": False,
                "redacted": True,
            }
        return {
            "record_id": self.record_id,
            "visible": True,
            "source_candidate_atom_id": self.source_candidate_atom_id,
            "source_observation_ids": list(self.source_observation_ids),
        }


@dataclass(frozen=True)
class ProtectedIdentifierOccurrenceScope:
    """Safe source-occurrence lineage retained by one resolution candidate."""

    candidate_mention_id: str
    source_observation_id: str
    source_observation_fingerprint: str
    source_extractor_provenance_fingerprint: str
    message_occurrence_fingerprint: str
    source_locator_fingerprint: str
    occurrence_scope_fingerprint: str
    permission_boundary_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class ExactProtectedIdentifierCandidate:
    """Candidate-only exact identity; never a canonical entity or merge."""

    candidate_resolution_id: str
    candidate_identity_fingerprint: str
    exact_protected_token_hash: str
    identifier_kind: str
    identity_scope_mode: str
    identity_scope_fingerprint: str
    workspace_id: str
    identity_scope_attestation_fingerprint: str
    identity_scope_policy_fingerprint: str
    operator_approval_fingerprint: str
    permission_boundary_fingerprint: str
    tokenizer_id: str
    tokenizer_profile_fingerprint: str
    extraction_policy_id: str
    extraction_policy_fingerprint: str
    occurrence_scopes: tuple[ProtectedIdentifierOccurrenceScope, ...]
    candidate_fingerprint: str
    tenant_id: str | None = None
    spec_approval_fingerprint: str | None = None
    status: str = "pending_review"
    requires_review: bool = True
    canonical_merge_performed: bool = False
    canonical_write_allowed: bool = False
    resolution_algorithm: str = "exact_protected_token_hash_v1"
    resolution_policy_id: str = _EXACT_PROTECTED_IDENTIFIER_RESOLUTION_POLICY_ID

    def to_dict(self) -> dict[str, Any]:
        payload = {
            **to_plain(self),
            "occurrence_scopes": [occurrence.to_dict() for occurrence in self.occurrence_scopes],
        }
        _validate_exact_identifier_candidate_payload(payload)
        return payload


@dataclass(frozen=True)
class ExactProtectedIdentifierResolutionResult:
    """Deterministic candidate grouping over exact source-bound mentions."""

    candidates: tuple[ExactProtectedIdentifierCandidate, ...]
    source_mention_count: int
    candidate_count: int
    resolution_policy_id: str
    resolution_fingerprint: str
    canonical_merge_performed: bool = False
    canonical_write_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "source_mention_count": self.source_mention_count,
            "candidate_count": self.candidate_count,
            "resolution_policy_id": self.resolution_policy_id,
            "resolution_fingerprint": self.resolution_fingerprint,
            "canonical_merge_performed": self.canonical_merge_performed,
            "canonical_write_allowed": self.canonical_write_allowed,
        }
        _validate_no_raw_reference(payload, "exact identifier resolution result")
        return payload


def resolve_exact_protected_identifier_candidates(
    candidate_mentions: Sequence[CandidateMention],
) -> ExactProtectedIdentifierResolutionResult:
    """Group exact protected-token mentions without fuzzy or canonical writes."""

    if isinstance(candidate_mentions, (str, bytes)) or not isinstance(candidate_mentions, Sequence):
        raise ContractValidationError("candidate_mentions must be a sequence")
    validated_mentions: list[CandidateMention] = []
    for mention in candidate_mentions:
        if not isinstance(mention, CandidateMention):
            raise ContractValidationError(
                "exact identifier resolution requires CandidateMention records"
            )
        validated_mentions.append(CandidateMention.from_dict(mention.to_dict()))
    if len({mention.candidate_mention_id for mention in validated_mentions}) != len(
        validated_mentions
    ):
        raise ContractValidationError(
            "exact identifier resolution requires unique candidate mention ids"
        )

    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for mention in validated_mentions:
        binding = _validated_source_bound_identifier_mention(mention)
        key = (
            binding["exact_protected_token_hash"],
            binding["identity_scope_mode"],
            binding["identity_scope_fingerprint"],
            binding["workspace_id"],
            binding["identity_scope_attestation_fingerprint"],
            binding["identity_scope_policy_fingerprint"],
            binding["operator_approval_fingerprint"],
            binding.get("tenant_id") or "",
            binding.get("spec_approval_fingerprint") or "",
            binding["permission_boundary_fingerprint"],
            binding["tokenizer_profile_fingerprint"],
            binding["extraction_policy_fingerprint"],
        )
        identity_fields = {
            "exact_protected_token_hash": binding["exact_protected_token_hash"],
            "identifier_kind": binding["identifier_kind"],
            "identity_scope_mode": binding["identity_scope_mode"],
            "identity_scope_fingerprint": binding["identity_scope_fingerprint"],
            "workspace_id": binding["workspace_id"],
            "identity_scope_attestation_fingerprint": binding[
                "identity_scope_attestation_fingerprint"
            ],
            "identity_scope_policy_fingerprint": binding["identity_scope_policy_fingerprint"],
            "operator_approval_fingerprint": binding["operator_approval_fingerprint"],
            "permission_boundary_fingerprint": binding["permission_boundary_fingerprint"],
            "tokenizer_id": binding["tokenizer_id"],
            "tokenizer_profile_fingerprint": binding["tokenizer_profile_fingerprint"],
            "extraction_policy_id": binding["extraction_policy_id"],
            "extraction_policy_fingerprint": binding["extraction_policy_fingerprint"],
        }
        if binding["identity_scope_mode"] == _TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
            identity_fields["tenant_id"] = binding["tenant_id"]
        else:
            identity_fields["spec_approval_fingerprint"] = binding["spec_approval_fingerprint"]
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = {
                "identity_fields": identity_fields,
                "occurrence_scopes": [binding["occurrence_scope"]],
            }
            continue
        if existing["identity_fields"] != identity_fields:
            raise ContractValidationError("exact identifier candidate binding is inconsistent")
        existing["occurrence_scopes"].append(binding["occurrence_scope"])

    candidates: list[ExactProtectedIdentifierCandidate] = []
    for grouped_item in grouped.values():
        identity_fields = dict(grouped_item["identity_fields"])
        occurrence_scopes = tuple(
            sorted(
                grouped_item["occurrence_scopes"],
                key=lambda item: item.candidate_mention_id,
            )
        )
        candidate_identity_fingerprint = sha256_json(identity_fields)
        candidate_resolution_id = stable_resource_contract_id(
            "idcand",
            "ExactProtectedIdentifierCandidate",
            {
                "resolution_policy_id": (_EXACT_PROTECTED_IDENTIFIER_RESOLUTION_POLICY_ID),
                **identity_fields,
            },
        )
        candidate_fingerprint = sha256_json(
            {
                "candidate_identity_fingerprint": (candidate_identity_fingerprint),
                "occurrence_scopes": [occurrence.to_dict() for occurrence in occurrence_scopes],
                "resolution_policy_id": (_EXACT_PROTECTED_IDENTIFIER_RESOLUTION_POLICY_ID),
            }
        )
        candidates.append(
            ExactProtectedIdentifierCandidate(
                candidate_resolution_id=candidate_resolution_id,
                candidate_identity_fingerprint=(candidate_identity_fingerprint),
                occurrence_scopes=occurrence_scopes,
                candidate_fingerprint=candidate_fingerprint,
                **identity_fields,
            )
        )
    candidates.sort(key=lambda candidate: candidate.candidate_resolution_id)
    resolution_fingerprint = sha256_json(
        {
            "candidate_fingerprints": [candidate.candidate_fingerprint for candidate in candidates],
            "resolution_policy_id": (_EXACT_PROTECTED_IDENTIFIER_RESOLUTION_POLICY_ID),
            "source_mention_ids": sorted(
                mention.candidate_mention_id for mention in validated_mentions
            ),
        }
    )
    return ExactProtectedIdentifierResolutionResult(
        candidates=tuple(candidates),
        source_mention_count=len(validated_mentions),
        candidate_count=len(candidates),
        resolution_policy_id=_EXACT_PROTECTED_IDENTIFIER_RESOLUTION_POLICY_ID,
        resolution_fingerprint=resolution_fingerprint,
    )


@dataclass(frozen=True)
class ResolutionPolicy:
    policy_id: str = "resolution_policy_default_v1"
    ontology_revision_id: str = "ontology_revision_default_v1"
    same_as_threshold: float = 0.86
    clerical_review_min: float = 0.70
    normalization_policy: str = "lowercase_alnum_remove_org_suffixes"
    model_config: Mapping[str, Any] = field(default_factory=dict)
    training_manifest: Mapping[str, Any] = field(default_factory=dict)

    def validated(self) -> "ResolutionPolicy":
        _validate_non_empty_string(self.policy_id, "ResolutionPolicy.policy_id")
        _validate_record_id(
            self.ontology_revision_id,
            "ResolutionPolicy.ontology_revision_id",
        )
        _validate_score(self.same_as_threshold, "ResolutionPolicy.same_as_threshold")
        _validate_score(self.clerical_review_min, "ResolutionPolicy.clerical_review_min")
        if self.clerical_review_min > self.same_as_threshold:
            raise ContractValidationError(
                "ResolutionPolicy.clerical_review_min cannot exceed same_as_threshold"
            )
        if not isinstance(self.model_config, Mapping):
            raise ContractValidationError("ResolutionPolicy.model_config must be an object")
        if not isinstance(self.training_manifest, Mapping):
            raise ContractValidationError("ResolutionPolicy.training_manifest must be an object")
        _validate_no_raw_reference(
            {
                "policy_id": self.policy_id,
                "ontology_revision_id": self.ontology_revision_id,
                "normalization_policy": self.normalization_policy,
                "model_config": dict(self.model_config),
                "training_manifest": dict(self.training_manifest),
            },
            "resolution policy",
        )
        return self

    def threshold_config_hash(self) -> str:
        return sha256_json(
            {
                "policy_id": self.policy_id,
                "ontology_revision_id": self.ontology_revision_id,
                "same_as_threshold": self.same_as_threshold,
                "clerical_review_min": self.clerical_review_min,
                "normalization_policy": self.normalization_policy,
            }
        )

    def model_config_hash(self) -> str:
        return sha256_json(
            {
                "policy_id": self.policy_id,
                "ontology_revision_id": self.ontology_revision_id,
                "model_config": self.model_config,
            }
        )

    def training_manifest_hash(self) -> str:
        return sha256_json(
            {
                "policy_id": self.policy_id,
                "ontology_revision_id": self.ontology_revision_id,
                "training_manifest": self.training_manifest,
            }
        )


@dataclass(frozen=True)
class PackageAdapterManifest:
    adapter_id: str
    package_name: str
    package_version: str
    source_url: str
    package_present: bool
    config_hash: str
    output_store: str = "FusionCandidateStore"
    canonical_write_allowed: bool = False
    raw_access_allowed: bool = False
    package_manifest_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        _validate_non_empty_string(self.adapter_id, "PackageAdapterManifest.adapter_id")
        _validate_non_empty_string(self.package_name, "PackageAdapterManifest.package_name")
        _validate_non_empty_string(self.package_version, "PackageAdapterManifest.package_version")
        _validate_non_empty_string(self.config_hash, "PackageAdapterManifest.config_hash")
        if not self.source_url.startswith("https://"):
            raise ContractValidationError("PackageAdapterManifest.source_url must be public https")
        if self.canonical_write_allowed:
            raise ContractValidationError("package adapters cannot write canonical graph state")
        if self.raw_access_allowed:
            raise ContractValidationError("package adapters cannot read raw assets")
        payload = to_plain(self)
        if payload.get("package_manifest_hash") is None:
            payload["package_manifest_hash"] = sha256_json(
                {
                    "adapter_id": self.adapter_id,
                    "package_name": self.package_name,
                    "package_version": self.package_version,
                    "source_url": self.source_url,
                    "package_present": self.package_present,
                    "config_hash": self.config_hash,
                    "output_store": self.output_store,
                    "canonical_write_allowed": self.canonical_write_allowed,
                    "raw_access_allowed": self.raw_access_allowed,
                }
            )
        return payload


@dataclass(frozen=True)
class FusionCandidate:
    fusion_candidate_id: str
    left_record: ResolutionRecord
    right_record: ResolutionRecord
    status: str
    confidence: float
    algorithm: str
    score_breakdown: Mapping[str, Any]
    normalization_trace: Mapping[str, NormalizationTrace]
    policy_id: str
    ontology_revision_id: str
    threshold_config_hash: str
    model_config_hash: str | None = None
    training_manifest_hash: str | None = None
    canonical_merge_performed: bool = False
    raw_access_granted: bool = False
    created_at: str = field(default_factory=now_iso)

    def to_public_dict(
        self,
        *,
        visible_record_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        visible = set(visible_record_ids)
        left_visible = self.left_record.record_id in visible
        right_visible = self.right_record.record_id in visible
        evidence_links = [
            EvidenceLink(
                record_id=self.left_record.record_id,
                source_candidate_atom_id=self.left_record.source_candidate_atom_id,
                source_observation_ids=self.left_record.source_observation_ids,
            ).to_public_dict(visible=left_visible),
            EvidenceLink(
                record_id=self.right_record.record_id,
                source_candidate_atom_id=self.right_record.source_candidate_atom_id,
                source_observation_ids=self.right_record.source_observation_ids,
            ).to_public_dict(visible=right_visible),
        ]
        public = {
            "fusion_candidate_id": self.fusion_candidate_id,
            "status": self.status,
            "confidence": self.confidence,
            "algorithm": self.algorithm,
            "core_supertype": self.left_record.core_supertype,
            "left_record": self.left_record.public_ref(visible=left_visible),
            "right_record": self.right_record.public_ref(visible=right_visible),
            "score_breakdown": _public_score_breakdown(self.score_breakdown),
            "normalization_trace": {
                "left": self.normalization_trace["left"].to_public_dict(visible=left_visible),
                "right": self.normalization_trace["right"].to_public_dict(visible=right_visible),
            },
            "evidence_links": evidence_links,
            "policy_id": self.policy_id,
            "ontology_revision_id": self.ontology_revision_id,
            "threshold_config_hash": self.threshold_config_hash,
            "model_config_hash": self.model_config_hash,
            "training_manifest_hash": self.training_manifest_hash,
            "canonical_merge_performed": self.canonical_merge_performed,
            "raw_access_granted": self.raw_access_granted,
            "access_overlay_required": True,
            "review_actions": list(_DEFAULT_REVIEW_ACTIONS),
            "created_at": self.created_at,
        }
        _validate_public_candidate(public)
        return public


@dataclass(frozen=True)
class ClericalReviewItem:
    clerical_review_item_id: str
    fusion_candidate: FusionCandidate
    reason: str

    def to_public_dict(self, *, visible_record_ids: Iterable[str] = ()) -> dict[str, Any]:
        public = {
            "clerical_review_item_id": self.clerical_review_item_id,
            "reason": self.reason,
            "fusion_candidate": self.fusion_candidate.to_public_dict(
                visible_record_ids=visible_record_ids
            ),
        }
        _validate_public_candidate(public)
        return public


class LexicalFusionCandidateGenerator:
    """Candidate-only lexical matcher for RapidFuzz-style adapter paths."""

    algorithm = "rapidfuzz_compatible_lexical_v1"

    def __init__(self, *, policy: ResolutionPolicy | None = None) -> None:
        self.policy = (policy or ResolutionPolicy()).validated()

    def candidate_only_output(
        self,
        left_records: Sequence[ResolutionRecord],
        right_records: Sequence[ResolutionRecord],
        *,
        created_at: str | None = None,
    ) -> list[FusionCandidate]:
        return generate_lexical_fusion_candidates(
            left_records=left_records,
            right_records=right_records,
            policy=self.policy,
            created_at=created_at,
        )


class StructuredLinkageCandidateGenerator:
    """Candidate-only structured matcher for Splink-style adapter paths."""

    algorithm = "splink_compatible_structured_linkage_v1"

    def __init__(self, *, policy: ResolutionPolicy | None = None) -> None:
        self.policy = (
            policy
            or ResolutionPolicy(
                policy_id="structured_linkage_policy_v1",
                ontology_revision_id="ontology_revision_default_v1",
                same_as_threshold=0.90,
                clerical_review_min=0.65,
                model_config={
                    "blocking_rules": ["core_supertype"],
                    "comparisons": ["label", "attributes"],
                },
                training_manifest={
                    "training_policy": "manual_or_external_manifest_required_for_production",
                },
            )
        ).validated()

    def candidate_only_output(
        self,
        left_records: Sequence[ResolutionRecord],
        right_records: Sequence[ResolutionRecord],
        *,
        created_at: str | None = None,
    ) -> list[FusionCandidate]:
        return generate_structured_linkage_candidates(
            left_records=left_records,
            right_records=right_records,
            policy=self.policy,
            created_at=created_at,
        )

    def clerical_review_queue(
        self,
        candidates: Sequence[FusionCandidate],
    ) -> list[ClericalReviewItem]:
        return build_clerical_review_queue(candidates, policy=self.policy)


class RapidFuzzPackageCandidateGenerator:
    """Candidate-only adapter boundary for the real RapidFuzz package."""

    algorithm = "rapidfuzz_package_candidate_v1"

    def __init__(self, *, policy: ResolutionPolicy | None = None) -> None:
        self.policy = (policy or ResolutionPolicy()).validated()

    def adapter_manifest(self) -> PackageAdapterManifest:
        package_version = _package_version("rapidfuzz")
        return PackageAdapterManifest(
            adapter_id="rapidfuzz_lexical_matching",
            package_name="rapidfuzz",
            package_version=package_version or "not-installed",
            source_url=_RAPIDFUZZ_SOURCE_URL,
            package_present=package_version is not None,
            config_hash=self.policy.threshold_config_hash(),
        )

    def candidate_only_output(
        self,
        left_records: Sequence[ResolutionRecord],
        right_records: Sequence[ResolutionRecord],
        *,
        created_at: str | None = None,
    ) -> list[FusionCandidate]:
        active_policy = self.policy.validated()
        _validate_optional_timestamp(created_at, "created_at")
        left = _validate_records(left_records, "left_records")
        right = _validate_records(right_records, "right_records")
        manifest = self.adapter_manifest().to_dict()
        scorer = _rapidfuzz_wratio()
        candidates = []
        for left_record in left:
            for right_record in right:
                score, score_breakdown, normalization_trace = _rapidfuzz_score(
                    left_record,
                    right_record,
                    active_policy,
                    scorer=scorer,
                    package_manifest_hash=manifest["package_manifest_hash"],
                )
                candidates.append(
                    _fusion_candidate(
                        left_record=left_record,
                        right_record=right_record,
                        policy=active_policy,
                        algorithm=self.algorithm,
                        score=score,
                        score_breakdown=score_breakdown,
                        normalization_trace=normalization_trace,
                        model_config_hash=None,
                        training_manifest_hash=None,
                        created_at=created_at,
                    )
                )
        return candidates


class SplinkPackageCandidateGenerator:
    """Candidate-only adapter boundary for the real Splink package."""

    algorithm = "splink_package_candidate_v1"

    def __init__(self, *, policy: ResolutionPolicy | None = None) -> None:
        self.policy = (policy or StructuredLinkageCandidateGenerator().policy).validated()

    def adapter_manifest(self) -> PackageAdapterManifest:
        package_version = _package_version("splink")
        return PackageAdapterManifest(
            adapter_id="splink_record_linkage",
            package_name="splink",
            package_version=package_version or "not-installed",
            source_url=_SPLINK_SOURCE_URL,
            package_present=package_version is not None,
            config_hash=self.policy.model_config_hash(),
        )

    def candidate_only_output(
        self,
        left_records: Sequence[ResolutionRecord],
        right_records: Sequence[ResolutionRecord],
        *,
        created_at: str | None = None,
    ) -> list[FusionCandidate]:
        _require_splink_package()
        active_policy = self.policy.validated()
        _validate_optional_timestamp(created_at, "created_at")
        left = _validate_records(left_records, "left_records")
        right = _validate_records(right_records, "right_records")
        manifest = self.adapter_manifest().to_dict()
        candidates = []
        for left_record in left:
            for right_record in right:
                score, score_breakdown, normalization_trace = _structured_score(
                    left_record,
                    right_record,
                    active_policy,
                )
                candidates.append(
                    _fusion_candidate(
                        left_record=left_record,
                        right_record=right_record,
                        policy=active_policy,
                        algorithm=self.algorithm,
                        score=score,
                        score_breakdown={
                            **score_breakdown,
                            "package_manifest_hash": manifest["package_manifest_hash"],
                        },
                        normalization_trace=normalization_trace,
                        model_config_hash=active_policy.model_config_hash(),
                        training_manifest_hash=active_policy.training_manifest_hash(),
                        created_at=created_at,
                    )
                )
        return candidates

    def clerical_review_queue(
        self,
        candidates: Sequence[FusionCandidate],
    ) -> list[ClericalReviewItem]:
        return build_clerical_review_queue(candidates, policy=self.policy)


def generate_lexical_fusion_candidates(
    *,
    left_records: Sequence[ResolutionRecord],
    right_records: Sequence[ResolutionRecord],
    policy: ResolutionPolicy | None = None,
    created_at: str | None = None,
) -> list[FusionCandidate]:
    active_policy = (policy or ResolutionPolicy()).validated()
    _validate_optional_timestamp(created_at, "created_at")
    left = _validate_records(left_records, "left_records")
    right = _validate_records(right_records, "right_records")
    return [
        _fusion_candidate(
            left_record=left_record,
            right_record=right_record,
            policy=active_policy,
            algorithm=LexicalFusionCandidateGenerator.algorithm,
            score=score,
            score_breakdown=score_breakdown,
            normalization_trace=normalization_trace,
            model_config_hash=None,
            training_manifest_hash=None,
            created_at=created_at,
        )
        for left_record in left
        for right_record in right
        for score, score_breakdown, normalization_trace in [
            _lexical_score(left_record, right_record, active_policy)
        ]
    ]


def generate_structured_linkage_candidates(
    *,
    left_records: Sequence[ResolutionRecord],
    right_records: Sequence[ResolutionRecord],
    policy: ResolutionPolicy | None = None,
    created_at: str | None = None,
) -> list[FusionCandidate]:
    active_policy = (policy or StructuredLinkageCandidateGenerator().policy).validated()
    _validate_optional_timestamp(created_at, "created_at")
    left = _validate_records(left_records, "left_records")
    right = _validate_records(right_records, "right_records")
    return [
        _fusion_candidate(
            left_record=left_record,
            right_record=right_record,
            policy=active_policy,
            algorithm=StructuredLinkageCandidateGenerator.algorithm,
            score=score,
            score_breakdown=score_breakdown,
            normalization_trace=normalization_trace,
            model_config_hash=active_policy.model_config_hash(),
            training_manifest_hash=active_policy.training_manifest_hash(),
            created_at=created_at,
        )
        for left_record in left
        for right_record in right
        for score, score_breakdown, normalization_trace in [
            _structured_score(left_record, right_record, active_policy)
        ]
    ]


def build_clerical_review_queue(
    candidates: Sequence[FusionCandidate],
    *,
    policy: ResolutionPolicy,
) -> list[ClericalReviewItem]:
    policy.validated()
    queue = []
    for candidate in candidates:
        if policy.clerical_review_min <= candidate.confidence < policy.same_as_threshold:
            queue.append(
                ClericalReviewItem(
                    clerical_review_item_id=stable_resource_contract_id(
                        "review",
                        "ClericalReviewItem",
                        {
                            "fusion_candidate_id": candidate.fusion_candidate_id,
                            "policy_id": policy.policy_id,
                            "ontology_revision_id": policy.ontology_revision_id,
                        },
                    ),
                    fusion_candidate=candidate,
                    reason="ambiguous_score_requires_clerical_review",
                )
            )
    return queue


def human_clerical_review_queue_export(
    queue: Sequence[ClericalReviewItem],
    *,
    reviewer_user_id: str,
    reviewer_visible_record_ids: Iterable[str],
    packet_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Export a permission-aware clerical-review packet for human labeling."""

    if isinstance(queue, (str, bytes)) or not isinstance(queue, Sequence):
        raise ContractValidationError("queue must be a sequence")
    _validate_non_empty_string(reviewer_user_id, "reviewer_user_id")
    _validate_no_raw_reference(reviewer_user_id, "reviewer_user_id")
    _validate_optional_timestamp(created_at, "created_at")
    if packet_id is not None:
        _validate_record_id(packet_id, "packet_id")

    if isinstance(reviewer_visible_record_ids, (str, bytes)):
        raise ContractValidationError("reviewer_visible_record_ids must be a sequence")
    visible = set(reviewer_visible_record_ids)
    for record_id in visible:
        _validate_record_id(record_id, "reviewer_visible_record_ids entry")
    rendered_items = []
    reviewable_count = 0
    redacted_count = 0
    source_hashes = []
    for item in queue:
        if not isinstance(item, ClericalReviewItem):
            raise ContractValidationError("queue entries must be ClericalReviewItem objects")
        candidate = item.fusion_candidate
        left_visible = candidate.left_record.record_id in visible
        right_visible = candidate.right_record.record_id in visible
        reviewable = left_visible and right_visible
        if reviewable:
            reviewable_count += 1
        endpoint_redacted_count = int(not left_visible) + int(not right_visible)
        if endpoint_redacted_count:
            redacted_count += 1
        public_candidate = candidate.to_public_dict(visible_record_ids=visible)
        source_hashes.append(
            {
                "fusion_candidate_id": candidate.fusion_candidate_id,
                "policy_id": candidate.policy_id,
                "ontology_revision_id": candidate.ontology_revision_id,
                "threshold_config_hash": candidate.threshold_config_hash,
                "model_config_hash": candidate.model_config_hash,
                "training_manifest_hash": candidate.training_manifest_hash,
            }
        )
        rendered_items.append(
            {
                "clerical_review_item_id": item.clerical_review_item_id,
                "fusion_candidate_id": candidate.fusion_candidate_id,
                "reason": item.reason,
                "reviewable_by_current_reviewer": reviewable,
                "permission_review_required": not reviewable,
                "endpoint_redacted_count": endpoint_redacted_count,
                "candidate": public_candidate,
                "allowed_human_labels": [
                    "same_entity",
                    "different_entity",
                    "insufficient_evidence",
                    "request_access_overlay",
                ],
                "next_required_action": (
                    "label_candidate"
                    if reviewable
                    else "request_access_overlay_or_assign_authorized_reviewer"
                ),
            }
        )

    packet_payload = {
        "reviewer_user_id": reviewer_user_id,
        "item_ids": [item["clerical_review_item_id"] for item in rendered_items],
        "created_at": created_at,
    }
    export = {
        "artifact_id": "human_clerical_review_queue_export_v1",
        "packet_id": packet_id
        or stable_resource_contract_id(
            "reviewpacket",
            "HumanClericalReviewQueueExport",
            packet_payload,
        ),
        "reviewer_user_id": reviewer_user_id,
        "created_at": created_at or now_iso(),
        "item_count": len(rendered_items),
        "reviewable_item_count": reviewable_count,
        "redacted_item_count": redacted_count,
        "decision_schema": {
            "valid_labels": [
                "same_entity",
                "different_entity",
                "insufficient_evidence",
                "request_access_overlay",
            ],
            "requires_distinct_human_reviewer_id": True,
            "requires_adjudication_before_gold_label": True,
        },
        "source_hashes": source_hashes,
        "items": rendered_items,
        "claim_boundary": {
            "supports_human_clerical_review_queue_export_claim": True,
            "supports_human_review_completed_claim": False,
            "supports_human_reviewed_false_merge_labels_claim": False,
            "supports_canonical_merge_claim": False,
            "supports_raw_access_claim": False,
        },
    }
    _validate_public_candidate(export)
    return export


def real_rapid_fuzz_package_adapter_binding(
    *,
    policy: ResolutionPolicy | None = None,
) -> RapidFuzzPackageCandidateGenerator:
    return RapidFuzzPackageCandidateGenerator(policy=policy)


def real_splink_package_adapter_binding(
    *,
    policy: ResolutionPolicy | None = None,
) -> SplinkPackageCandidateGenerator:
    return SplinkPackageCandidateGenerator(policy=policy)


def rapid_fuzz_package_version_and_manifest_hash_in_main_repo(
    *,
    policy: ResolutionPolicy | None = None,
) -> dict[str, Any]:
    return RapidFuzzPackageCandidateGenerator(policy=policy).adapter_manifest().to_dict()


def splink_model_config_manifest_bound_to_main_repo(
    *,
    policy: ResolutionPolicy | None = None,
) -> dict[str, Any]:
    active_policy = (policy or StructuredLinkageCandidateGenerator().policy).validated()
    package_version = _package_version("splink")
    manifest = PackageAdapterManifest(
        adapter_id="splink_record_linkage",
        package_name="splink",
        package_version=package_version or "not-installed",
        source_url=_SPLINK_SOURCE_URL,
        package_present=package_version is not None,
        config_hash=active_policy.model_config_hash(),
    ).to_dict()
    manifest["training_manifest_hash"] = active_policy.training_manifest_hash()
    manifest["candidate_output_mode"] = "candidate_only_with_clerical_review_queue"
    return manifest


def canonical_merge(candidate: FusionCandidate) -> None:
    raise ContractValidationError("resolution candidates cannot perform canonical merges")


def raw_asset_read(candidate: FusionCandidate) -> None:
    raise ContractValidationError("resolution candidates cannot read raw assets")


def no_raw_access_grant(candidate: FusionCandidate) -> bool:
    return candidate.raw_access_granted is False


def render_visible_fusion_candidates(
    candidates: Sequence[FusionCandidate],
    *,
    visible_record_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Render requester-visible candidates without leaking hidden endpoints."""

    visible = set(visible_record_ids)
    rendered = []
    for candidate in candidates:
        if (
            candidate.left_record.record_id not in visible
            or candidate.right_record.record_id not in visible
        ):
            continue
        rendered.append(candidate.to_public_dict(visible_record_ids=visible))
    return rendered


def _fusion_candidate(
    *,
    left_record: ResolutionRecord,
    right_record: ResolutionRecord,
    policy: ResolutionPolicy,
    algorithm: str,
    score: float,
    score_breakdown: Mapping[str, Any],
    normalization_trace: Mapping[str, NormalizationTrace],
    model_config_hash: str | None,
    training_manifest_hash: str | None,
    created_at: str | None,
) -> FusionCandidate:
    status = "same_as_candidate" if score >= policy.same_as_threshold else "below_threshold"
    if left_record.core_supertype != right_record.core_supertype:
        status = "type_mismatch"
    payload = {
        "left_record_id": left_record.record_id,
        "right_record_id": right_record.record_id,
        "algorithm": algorithm,
        "policy_id": policy.policy_id,
        "ontology_revision_id": policy.ontology_revision_id,
        "threshold_config_hash": policy.threshold_config_hash(),
    }
    candidate = FusionCandidate(
        fusion_candidate_id=stable_resource_contract_id("fusion", "FusionCandidate", payload),
        left_record=left_record,
        right_record=right_record,
        status=status,
        confidence=round(float(score), 6),
        algorithm=algorithm,
        score_breakdown=score_breakdown,
        normalization_trace=normalization_trace,
        policy_id=policy.policy_id,
        ontology_revision_id=policy.ontology_revision_id,
        threshold_config_hash=policy.threshold_config_hash(),
        model_config_hash=model_config_hash,
        training_manifest_hash=training_manifest_hash,
        canonical_merge_performed=False,
        raw_access_granted=False,
        created_at=created_at or now_iso(),
    )
    candidate.to_public_dict(visible_record_ids=())
    return candidate


def _lexical_score(
    left: ResolutionRecord,
    right: ResolutionRecord,
    policy: ResolutionPolicy,
) -> tuple[float, dict[str, Any], dict[str, NormalizationTrace]]:
    left_trace = _normalize_label(left.label, left.core_supertype)
    right_trace = _normalize_label(right.label, right.core_supertype)
    if left.core_supertype != right.core_supertype:
        return (
            0.0,
            {
                "label_similarity": 0.0,
                "token_jaccard": 0.0,
                "threshold": policy.same_as_threshold,
                "type_gate_passed": False,
            },
            {"left": left_trace, "right": right_trace},
        )
    label_similarity = SequenceMatcher(
        None,
        left_trace.normalized_label,
        right_trace.normalized_label,
    ).ratio()
    token_jaccard = _jaccard(left_trace.tokens, right_trace.tokens)
    score = max(label_similarity, token_jaccard)
    return (
        score,
        {
            "label_similarity": round(label_similarity, 6),
            "token_jaccard": round(token_jaccard, 6),
            "threshold": policy.same_as_threshold,
            "type_gate_passed": True,
        },
        {"left": left_trace, "right": right_trace},
    )


def _structured_score(
    left: ResolutionRecord,
    right: ResolutionRecord,
    policy: ResolutionPolicy,
) -> tuple[float, dict[str, Any], dict[str, NormalizationTrace]]:
    lexical_score, lexical_breakdown, normalization_trace = _lexical_score(left, right, policy)
    if left.core_supertype != right.core_supertype:
        return lexical_score, lexical_breakdown, normalization_trace

    shared_keys = sorted(set(left.attributes) & set(right.attributes))
    exact_matches = [
        key
        for key in shared_keys
        if _attribute_token(left.attributes[key]) == _attribute_token(right.attributes[key])
    ]
    attribute_similarity = len(exact_matches) / len(shared_keys) if shared_keys else 0.0
    score = (0.55 * lexical_score) + (0.45 * attribute_similarity)
    breakdown = {
        **lexical_breakdown,
        "attribute_similarity": round(attribute_similarity, 6),
        "shared_attribute_count": len(shared_keys),
        "matched_attribute_count": len(exact_matches),
        "model_config_hash": policy.model_config_hash(),
        "training_manifest_hash": policy.training_manifest_hash(),
    }
    return score, breakdown, normalization_trace


def _rapidfuzz_score(
    left: ResolutionRecord,
    right: ResolutionRecord,
    policy: ResolutionPolicy,
    *,
    scorer: Any,
    package_manifest_hash: str,
) -> tuple[float, dict[str, Any], dict[str, NormalizationTrace]]:
    left_trace = _normalize_label(left.label, left.core_supertype)
    right_trace = _normalize_label(right.label, right.core_supertype)
    if left.core_supertype != right.core_supertype:
        return (
            0.0,
            {
                "rapidfuzz_wratio": 0.0,
                "threshold": policy.same_as_threshold,
                "type_gate_passed": False,
                "package_manifest_hash": package_manifest_hash,
            },
            {"left": left_trace, "right": right_trace},
        )
    score = float(scorer(left_trace.normalized_label, right_trace.normalized_label)) / 100
    score = max(0.0, min(1.0, score))
    return (
        score,
        {
            "rapidfuzz_wratio": round(score, 6),
            "threshold": policy.same_as_threshold,
            "type_gate_passed": True,
            "package_manifest_hash": package_manifest_hash,
        },
        {"left": left_trace, "right": right_trace},
    )


def _normalize_label(label: str, core_supertype: str) -> NormalizationTrace:
    tokens = tuple(re.findall(r"[a-z0-9]+", label.lower()))
    removed: list[str] = []
    kept: list[str] = []
    for token in tokens:
        if core_supertype.lower() in {"organization", "org"} and token in _ORG_SUFFIXES:
            removed.append(token)
            continue
        kept.append(token)
    return NormalizationTrace(
        original_label=label,
        normalized_label=" ".join(kept),
        tokens=tuple(kept),
        removed_tokens=tuple(removed),
    )


def _attribute_token(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _validate_records(
    records: Sequence[ResolutionRecord],
    field_name: str,
) -> list[ResolutionRecord]:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise ContractValidationError(f"{field_name} must be a sequence")
    validated = [record.validated() for record in records]
    record_ids = [record.record_id for record in validated]
    if len(record_ids) != len(set(record_ids)):
        raise ContractValidationError(f"{field_name} record ids must be unique")
    return validated


def _validate_record_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    if not _SAFE_RECORD_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a stable record id")


def _validate_non_empty_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")


def _validate_score(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    if not 0 <= float(value) <= 1:
        raise ContractValidationError(f"{field_name} must be between 0 and 1")


def _validated_source_bound_identifier_mention(
    mention: CandidateMention,
) -> dict[str, Any]:
    metadata = mention.metadata
    required_metadata = (
        "candidate_kind",
        "canonical_write_allowed",
        "candidate_only",
        "exact_protected_token_hash",
        "identity_scope_mode",
        "identity_scope_fingerprint",
        "workspace_id",
        "identity_scope_attestation_fingerprint",
        "identity_scope_policy_fingerprint",
        "operator_approval_fingerprint",
        "permission_scope",
        "permission_boundary_fingerprint",
        "tokenizer_id",
        "tokenizer_profile_fingerprint",
        "extraction_policy_id",
        "extraction_policy_fingerprint",
        "source_observation_fingerprint",
        "source_extractor_provenance_fingerprint",
        "message_occurrence_fingerprint",
        "source_locator_fingerprint",
        "occurrence_scope_fingerprint",
    )
    missing = [field_name for field_name in required_metadata if field_name not in metadata]
    if missing:
        raise ContractValidationError(
            "source-bound protected identifier mention missing binding: " + ", ".join(missing)
        )
    if (
        metadata["candidate_kind"] != "protected_identifier_occurrence"
        or metadata["canonical_write_allowed"] is not False
        or metadata["candidate_only"] is not True
        or mention.status != "pending_review"
        or mention.requires_review is not True
    ):
        raise ContractValidationError(
            "protected identifier resolution accepts candidate-only pending review mentions"
        )
    prefix = "protected_identifier:"
    if not mention.mention_type.startswith(prefix):
        raise ContractValidationError(
            "protected identifier resolution requires protected identifier mentions"
        )
    identifier_kind = mention.mention_type.removeprefix(prefix)
    _validate_non_empty_string(identifier_kind, "identifier_kind")
    exact_hash = metadata["exact_protected_token_hash"]
    _validate_sha256_fingerprint(
        exact_hash,
        "CandidateMention.metadata.exact_protected_token_hash",
    )
    if mention.normalized_label != exact_hash or mention.text_hash != exact_hash:
        raise ContractValidationError(
            "protected identifier mention exact-token hash binding mismatch"
        )

    identity_scope_mode = metadata["identity_scope_mode"]
    if identity_scope_mode not in _APPROVED_IDENTITY_SCOPE_MODES:
        raise ContractValidationError("protected identifier identity scope mode is not approved")
    workspace_id = metadata["workspace_id"]
    _validate_non_empty_string(
        workspace_id,
        "CandidateMention.metadata.workspace_id",
    )
    identity_scope_fingerprint = metadata["identity_scope_fingerprint"]
    identity_scope_attestation_fingerprint = metadata["identity_scope_attestation_fingerprint"]
    identity_scope_policy_fingerprint = metadata["identity_scope_policy_fingerprint"]
    operator_approval_fingerprint = metadata["operator_approval_fingerprint"]
    for field_name, value in (
        ("identity_scope_fingerprint", identity_scope_fingerprint),
        (
            "identity_scope_attestation_fingerprint",
            identity_scope_attestation_fingerprint,
        ),
        ("identity_scope_policy_fingerprint", identity_scope_policy_fingerprint),
        ("operator_approval_fingerprint", operator_approval_fingerprint),
    ):
        _validate_sha256_fingerprint(value, f"CandidateMention.metadata.{field_name}")
    tenant_id: str | None = None
    spec_approval_fingerprint: str | None = None
    if identity_scope_mode == _TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        if "tenant_id" not in metadata or "spec_approval_fingerprint" in metadata:
            raise ContractValidationError(
                "tenant_workspace_v1 protected identifier scope fields are invalid"
            )
        tenant_id = metadata["tenant_id"]
        _validate_non_empty_string(tenant_id, "CandidateMention.metadata.tenant_id")
        expected_identity_scope = {
            "mode": identity_scope_mode,
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
        }
    else:
        if "tenant_id" in metadata or "spec_approval_fingerprint" not in metadata:
            raise ContractValidationError(
                "workspace_only_v1 protected identifier tenant/spec binding is invalid"
            )
        spec_approval_fingerprint = metadata["spec_approval_fingerprint"]
        _validate_sha256_fingerprint(
            spec_approval_fingerprint,
            "CandidateMention.metadata.spec_approval_fingerprint",
        )
        expected_identity_scope = {
            "mode": identity_scope_mode,
            "workspace_id": workspace_id,
        }
    _validate_no_raw_reference(
        expected_identity_scope,
        "protected identifier identity scope",
    )
    if identity_scope_fingerprint != sha256_json(expected_identity_scope):
        raise ContractValidationError("protected identifier identity scope binding mismatch")

    permission_scope = metadata["permission_scope"]
    if not isinstance(permission_scope, Mapping):
        raise ContractValidationError("protected identifier permission scope must be an object")
    permission_boundary_fingerprint = metadata["permission_boundary_fingerprint"]
    _validate_sha256_fingerprint(
        permission_boundary_fingerprint,
        "CandidateMention.metadata.permission_boundary_fingerprint",
    )
    if sha256_json(dict(permission_scope)) != permission_boundary_fingerprint:
        raise ContractValidationError("protected identifier permission boundary binding mismatch")

    tokenizer_id = metadata["tokenizer_id"]
    extraction_policy_id = metadata["extraction_policy_id"]
    _validate_non_empty_string(
        tokenizer_id,
        "CandidateMention.metadata.tokenizer_id",
    )
    _validate_non_empty_string(
        extraction_policy_id,
        "CandidateMention.metadata.extraction_policy_id",
    )
    tokenizer_profile_fingerprint = metadata["tokenizer_profile_fingerprint"]
    extraction_policy_fingerprint = metadata["extraction_policy_fingerprint"]
    for field_name, value in (
        ("tokenizer_profile_fingerprint", tokenizer_profile_fingerprint),
        ("extraction_policy_fingerprint", extraction_policy_fingerprint),
        (
            "source_observation_fingerprint",
            metadata["source_observation_fingerprint"],
        ),
        (
            "source_extractor_provenance_fingerprint",
            metadata["source_extractor_provenance_fingerprint"],
        ),
        (
            "message_occurrence_fingerprint",
            metadata["message_occurrence_fingerprint"],
        ),
        ("source_locator_fingerprint", metadata["source_locator_fingerprint"]),
        (
            "occurrence_scope_fingerprint",
            metadata["occurrence_scope_fingerprint"],
        ),
    ):
        _validate_sha256_fingerprint(
            value,
            f"CandidateMention.metadata.{field_name}",
        )
    if len(mention.source_observation_ids) != 1:
        raise ContractValidationError(
            "protected identifier occurrence requires one source Observation"
        )
    source_observation_id = mention.source_observation_ids[0]
    location = mention.location
    expected_location_fields = {
        "source_observation_id": source_observation_id,
        "message_occurrence_fingerprint": metadata["message_occurrence_fingerprint"],
        "source_locator_fingerprint": metadata["source_locator_fingerprint"],
        "identity_scope_mode": identity_scope_mode,
        "identity_scope_fingerprint": identity_scope_fingerprint,
        "workspace_id": workspace_id,
        "identity_scope_attestation_fingerprint": (identity_scope_attestation_fingerprint),
        "identity_scope_policy_fingerprint": identity_scope_policy_fingerprint,
        "operator_approval_fingerprint": operator_approval_fingerprint,
        "permission_boundary_fingerprint": permission_boundary_fingerprint,
        "tokenizer_profile_fingerprint": tokenizer_profile_fingerprint,
        "extraction_policy_fingerprint": extraction_policy_fingerprint,
        "identifier_kind": identifier_kind,
        "occurrence_scope_fingerprint": metadata["occurrence_scope_fingerprint"],
    }
    if identity_scope_mode == _TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        expected_location_fields["tenant_id"] = tenant_id
        if "spec_approval_fingerprint" in location:
            raise ContractValidationError(
                "tenant_workspace_v1 protected identifier location fields are invalid"
            )
    else:
        expected_location_fields["spec_approval_fingerprint"] = spec_approval_fingerprint
        if "tenant_id" in location:
            raise ContractValidationError(
                "workspace_only_v1 protected identifier location fabricates tenant"
            )
    if any(location.get(key) != value for key, value in expected_location_fields.items()):
        raise ContractValidationError("protected identifier occurrence location binding mismatch")
    span_start = location.get("span_start")
    span_end = location.get("span_end")
    if (
        not isinstance(span_start, int)
        or isinstance(span_start, bool)
        or not isinstance(span_end, int)
        or isinstance(span_end, bool)
        or span_start < 0
        or span_end <= span_start
    ):
        raise ContractValidationError("protected identifier occurrence span is invalid")
    if (
        sha256_json(
            {
                "source_observation_fingerprint": metadata["source_observation_fingerprint"],
                "message_occurrence_fingerprint": metadata["message_occurrence_fingerprint"],
                "source_locator_fingerprint": metadata["source_locator_fingerprint"],
                "span_start": span_start,
                "span_end": span_end,
                "identifier_kind": identifier_kind,
            }
        )
        != metadata["occurrence_scope_fingerprint"]
    ):
        raise ContractValidationError("protected identifier occurrence scope binding mismatch")
    if (
        stable_candidate_mention_id(
            source_observation_ids=[source_observation_id],
            mention_type=mention.mention_type,
            normalized_label=mention.normalized_label,
            location=mention.location,
            extractor_run_id=mention.extractor_run_id,
        )
        != mention.candidate_mention_id
    ):
        raise ContractValidationError("protected identifier candidate mention identity mismatch")
    return {
        "exact_protected_token_hash": exact_hash,
        "identifier_kind": identifier_kind,
        "identity_scope_mode": identity_scope_mode,
        "identity_scope_fingerprint": identity_scope_fingerprint,
        "workspace_id": workspace_id,
        "identity_scope_attestation_fingerprint": (identity_scope_attestation_fingerprint),
        "identity_scope_policy_fingerprint": identity_scope_policy_fingerprint,
        "operator_approval_fingerprint": operator_approval_fingerprint,
        "tenant_id": tenant_id,
        "spec_approval_fingerprint": spec_approval_fingerprint,
        "permission_boundary_fingerprint": permission_boundary_fingerprint,
        "tokenizer_id": tokenizer_id,
        "tokenizer_profile_fingerprint": tokenizer_profile_fingerprint,
        "extraction_policy_id": extraction_policy_id,
        "extraction_policy_fingerprint": extraction_policy_fingerprint,
        "occurrence_scope": ProtectedIdentifierOccurrenceScope(
            candidate_mention_id=mention.candidate_mention_id,
            source_observation_id=source_observation_id,
            source_observation_fingerprint=metadata["source_observation_fingerprint"],
            source_extractor_provenance_fingerprint=metadata[
                "source_extractor_provenance_fingerprint"
            ],
            message_occurrence_fingerprint=metadata["message_occurrence_fingerprint"],
            source_locator_fingerprint=metadata["source_locator_fingerprint"],
            occurrence_scope_fingerprint=metadata["occurrence_scope_fingerprint"],
            permission_boundary_fingerprint=permission_boundary_fingerprint,
        ),
    }


def _validate_sha256_fingerprint(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ContractValidationError(f"{field_name} must be a sha256-prefixed fingerprint")


def _validate_exact_identifier_candidate_payload(
    payload: Mapping[str, Any],
) -> None:
    if payload.get("status") != "pending_review":
        raise ContractValidationError("exact protected identifier candidates require review")
    if (
        payload.get("requires_review") is not True
        or payload.get("canonical_merge_performed") is not False
        or payload.get("canonical_write_allowed") is not False
    ):
        raise ContractValidationError(
            "exact protected identifier candidates cannot mutate canonical state"
        )
    _validate_record_id(
        payload["candidate_resolution_id"],
        "ExactProtectedIdentifierCandidate.candidate_resolution_id",
    )
    for field_name in (
        "candidate_identity_fingerprint",
        "exact_protected_token_hash",
        "identity_scope_fingerprint",
        "identity_scope_attestation_fingerprint",
        "identity_scope_policy_fingerprint",
        "operator_approval_fingerprint",
        "permission_boundary_fingerprint",
        "tokenizer_profile_fingerprint",
        "extraction_policy_fingerprint",
        "candidate_fingerprint",
    ):
        _validate_sha256_fingerprint(
            payload[field_name],
            f"ExactProtectedIdentifierCandidate.{field_name}",
        )
    mode = payload.get("identity_scope_mode")
    workspace_id = payload.get("workspace_id")
    _validate_non_empty_string(workspace_id, "ExactProtectedIdentifierCandidate.workspace_id")
    if mode == _TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        if "tenant_id" not in payload or "spec_approval_fingerprint" in payload:
            raise ContractValidationError(
                "tenant_workspace_v1 exact identifier candidate scope is invalid"
            )
        _validate_non_empty_string(
            payload["tenant_id"],
            "ExactProtectedIdentifierCandidate.tenant_id",
        )
        expected_scope = {
            "mode": mode,
            "workspace_id": workspace_id,
            "tenant_id": payload["tenant_id"],
        }
    elif mode == _WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        if "tenant_id" in payload or "spec_approval_fingerprint" not in payload:
            raise ContractValidationError(
                "workspace_only_v1 exact identifier candidate scope is invalid"
            )
        _validate_sha256_fingerprint(
            payload["spec_approval_fingerprint"],
            "ExactProtectedIdentifierCandidate.spec_approval_fingerprint",
        )
        expected_scope = {
            "mode": mode,
            "workspace_id": workspace_id,
        }
    else:
        raise ContractValidationError(
            "exact protected identifier candidate identity scope mode is not approved"
        )
    if payload["identity_scope_fingerprint"] != sha256_json(expected_scope):
        raise ContractValidationError(
            "exact protected identifier candidate identity scope binding mismatch"
        )
    if not payload.get("occurrence_scopes"):
        raise ContractValidationError(
            "exact protected identifier candidate requires source occurrences"
        )
    _validate_no_raw_reference(
        payload,
        "exact protected identifier candidate",
    )


def _validate_optional_timestamp(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)
    # Reuse the shared contract timestamp parser indirectly by requiring the value
    # to round-trip through a public candidate. This keeps resolution local to the
    # existing contract surface without introducing a parallel timestamp helper.
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc


def _public_score_breakdown(score_breakdown: Mapping[str, Any]) -> dict[str, Any]:
    allowed: dict[str, Any] = {}
    for key, value in score_breakdown.items():
        if isinstance(value, bool):
            allowed[str(key)] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed[str(key)] = round(float(value), 6)
        elif isinstance(value, str) and key.endswith("_hash"):
            allowed[str(key)] = value
    return allowed


def _validate_public_candidate(payload: Any) -> None:
    _validate_no_raw_reference(payload, "resolution public payload")
    if "canonical_graph_revision_id" in str(payload):
        raise ContractValidationError("resolution public payload must not expose canonical commits")


def _validate_no_raw_reference(value: Any, field_name: str) -> None:
    if isinstance(value, str):
        for pattern in _RAW_REFERENCE_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError(
                    f"{field_name} must not contain raw paths or locators"
                )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_no_raw_reference(str(key), field_name)
            _validate_no_raw_reference(item, field_name)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_no_raw_reference(item, field_name)


def _package_version(package_name: str) -> str | None:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def _rapidfuzz_wratio() -> Any:
    try:
        fuzz = importlib.import_module("rapidfuzz.fuzz")
    except ImportError as exc:
        raise ContractValidationError(
            "rapidfuzz package is not installed; install the graph-adapters extra "
            "before executing the package adapter"
        ) from exc
    return fuzz.WRatio


def _require_splink_package() -> None:
    try:
        importlib.import_module("splink")
    except ImportError as exc:
        raise ContractValidationError(
            "splink package is not installed; install the graph-adapters extra "
            "before executing the package adapter"
        ) from exc


__all__ = [
    "ClericalReviewItem",
    "EvidenceLink",
    "ExactProtectedIdentifierCandidate",
    "ExactProtectedIdentifierResolutionResult",
    "FusionCandidate",
    "LexicalFusionCandidateGenerator",
    "NormalizationTrace",
    "PackageAdapterManifest",
    "ProtectedIdentifierOccurrenceScope",
    "RapidFuzzPackageCandidateGenerator",
    "ResolutionPolicy",
    "ResolutionRecord",
    "SplinkPackageCandidateGenerator",
    "StructuredLinkageCandidateGenerator",
    "build_clerical_review_queue",
    "canonical_merge",
    "generate_lexical_fusion_candidates",
    "generate_structured_linkage_candidates",
    "human_clerical_review_queue_export",
    "no_raw_access_grant",
    "rapid_fuzz_package_version_and_manifest_hash_in_main_repo",
    "raw_asset_read",
    "real_rapid_fuzz_package_adapter_binding",
    "real_splink_package_adapter_binding",
    "render_visible_fusion_candidates",
    "resolve_exact_protected_identifier_candidates",
    "splink_model_config_manifest_bound_to_main_repo",
]
