from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from formowl_contract import ContractValidationError, sha256_json, to_plain

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PROFILE_IDS = {
    "low_spec_cpu": "deterministic_cpu_candidate_generation_v1",
    "standard_cpu": "local_embedding_candidate_generation_v1",
    "accelerated_gpu": "accelerated_neural_candidate_generation_v1",
    "remote_model_worker": "accelerated_neural_candidate_generation_v1",
}


@dataclass(frozen=True)
class CandidateGenerationProfile:
    """Candidate-generation capability profile for heterogeneous workers.

    Profiles describe what a worker may generate. They do not authorize raw
    access or canonical graph/type writes.
    """

    profile_id: str
    worker_tier: str
    display_name: str
    description: str
    candidate_generators: tuple[str, ...]
    output_records: tuple[str, ...]
    minimum_capabilities: Mapping[str, Any]
    default_model_profile: Mapping[str, Any] | None = None
    model_families: tuple[str, ...] = ()
    uses_neural_networks: bool = False
    produces_embeddings: bool = False
    requires_gpu: bool = False
    requires_model_download: bool = False
    canonical_write_allowed: bool = False
    raw_access_allowed: bool = False
    implementation_state: str = "adapter_contract_declared"
    adapter_contract_version: str = "kg_candidate_generation_profile_v1"

    def to_dict(self) -> dict[str, Any]:
        _validate_safe_id(self.profile_id, "CandidateGenerationProfile.profile_id")
        _validate_safe_id(self.worker_tier, "CandidateGenerationProfile.worker_tier")
        _validate_non_empty(self.display_name, "CandidateGenerationProfile.display_name")
        _validate_non_empty(self.description, "CandidateGenerationProfile.description")
        _validate_non_empty(
            self.implementation_state,
            "CandidateGenerationProfile.implementation_state",
        )
        _validate_non_empty(
            self.adapter_contract_version,
            "CandidateGenerationProfile.adapter_contract_version",
        )
        if self.canonical_write_allowed:
            raise ContractValidationError(
                "candidate generation profiles cannot write canonical state"
            )
        if self.raw_access_allowed:
            raise ContractValidationError("candidate generation profiles cannot grant raw access")
        _validate_string_tuple(self.candidate_generators, "candidate_generators")
        _validate_string_tuple(self.output_records, "output_records")
        _validate_string_tuple(self.model_families, "model_families", allow_empty=True)
        if not isinstance(self.minimum_capabilities, Mapping):
            raise ContractValidationError("minimum_capabilities must be an object")
        if self.default_model_profile is not None and not isinstance(
            self.default_model_profile, Mapping
        ):
            raise ContractValidationError("default_model_profile must be an object")
        payload = to_plain(self)
        payload["profile_hash"] = sha256_json(
            {
                "profile_id": self.profile_id,
                "worker_tier": self.worker_tier,
                "candidate_generators": self.candidate_generators,
                "output_records": self.output_records,
                "minimum_capabilities": self.minimum_capabilities,
                "default_model_profile": self.default_model_profile,
                "model_families": self.model_families,
                "uses_neural_networks": self.uses_neural_networks,
                "produces_embeddings": self.produces_embeddings,
                "requires_gpu": self.requires_gpu,
                "requires_model_download": self.requires_model_download,
                "canonical_write_allowed": self.canonical_write_allowed,
                "raw_access_allowed": self.raw_access_allowed,
                "implementation_state": self.implementation_state,
                "adapter_contract_version": self.adapter_contract_version,
            }
        )
        return payload


def list_candidate_generation_profiles() -> tuple[CandidateGenerationProfile, ...]:
    """Return stable capability profiles for KG candidate-generation workers."""

    return (
        CandidateGenerationProfile(
            profile_id="deterministic_cpu_candidate_generation_v1",
            worker_tier="low_spec_cpu",
            display_name="Deterministic CPU candidate generation",
            description=(
                "Lowest-spec path for lexical rules, gazetteers, fixture extractors, "
                "and RapidFuzz-compatible candidate generation without neural inference."
            ),
            candidate_generators=(
                "rules_and_gazetteers",
                "deterministic_text_markers",
                "unicode_normalization",
                "rapidfuzz_compatible_lexical_matching",
            ),
            output_records=(
                "SemanticMetadata",
                "CandidateAtom",
                "CandidateRelation",
                "FusionCandidate",
                "TypeAlignmentCandidate",
            ),
            minimum_capabilities={
                "cpu_required": True,
                "gpu_required": False,
                "memory_gb_floor": 2,
                "network_model_access_required": False,
            },
            implementation_state="implemented_baseline",
        ),
        CandidateGenerationProfile(
            profile_id="local_embedding_candidate_generation_v1",
            worker_tier="standard_cpu",
            display_name="Local embedding candidate generation",
            description=(
                "Standard worker path for SentenceTransformer or BERT-family "
                "embedding adapters that generate vectors and semantic similarity "
                "scores while leaving governance decisions to FormOwl."
            ),
            candidate_generators=(
                "sentence_transformer_embedding_adapter",
                "bert_family_embedding_adapter",
                "pgvector_similarity_candidates",
                "embedding_type_alignment_candidates",
            ),
            output_records=(
                "VectorStore",
                "FusionCandidate",
                "TypeAlignmentCandidate",
                "score_breakdown.embedding",
            ),
            minimum_capabilities={
                "cpu_required": True,
                "gpu_required": False,
                "memory_gb_floor": 8,
                "network_model_access_required": False,
            },
            default_model_profile={
                "profile_id": "legacy_cpu_bert",
                "default_model": "sentence-transformers/bert-base-nli-mean-tokens",
                "intended_runtime": "cpu_neural_fallback",
                "default_threshold": 0.70,
                "minimum_gpu": None,
                "minimum_vram_gb": None,
            },
            model_families=(
                "Sentence Transformers",
                "BERT-family encoder",
                "local embedding model",
            ),
            uses_neural_networks=True,
            produces_embeddings=True,
            requires_model_download=True,
            implementation_state="adapter_slot_declared",
        ),
        CandidateGenerationProfile(
            profile_id="accelerated_neural_candidate_generation_v1",
            worker_tier="accelerated_gpu",
            display_name="Accelerated neural candidate generation",
            description=(
                "High-spec worker path for BERT-family NER or relation extraction, "
                "local LLM graph extraction, multimodal semantic adapters, and "
                "large embedding batches. Output remains candidate-only."
            ),
            candidate_generators=(
                "bert_family_ner_adapter",
                "bert_family_relation_extraction_adapter",
                "llm_graph_transformer_candidate_adapter",
                "multimodal_semantic_candidate_adapter",
                "large_batch_embedding_adapter",
            ),
            output_records=(
                "SemanticMetadata",
                "CandidateAtom",
                "CandidateRelation",
                "ExternalGraphImport",
                "FusionCandidate",
                "TypeAlignmentCandidate",
            ),
            minimum_capabilities={
                "cpu_required": True,
                "gpu_required": True,
                "memory_gb_floor": 16,
                "gpu_floor": "one NVIDIA GeForce GTX 1080 Ti class device",
                "gpu_vram_gb_floor": 11,
                "network_model_access_required": False,
            },
            default_model_profile={
                "profile_id": "gpu_bge_large_en_v1_5",
                "default_model": "BAAI/bge-large-en-v1.5",
                "intended_runtime": "single_gpu_or_remote_model_worker",
                "default_threshold": 0.62,
                "minimum_gpu": "NVIDIA GeForce GTX 1080 Ti",
                "minimum_vram_gb": 11,
            },
            model_families=(
                "BERT-family NER",
                "BERT-family relation extraction",
                "Sentence Transformers",
                "local LLM graph extraction",
                "multimodal model adapter",
            ),
            uses_neural_networks=True,
            produces_embeddings=True,
            requires_gpu=True,
            requires_model_download=True,
            implementation_state="adapter_slot_declared",
        ),
    )


def get_candidate_generation_profile(profile_id: str) -> CandidateGenerationProfile:
    """Return one profile by stable id."""

    _validate_safe_id(profile_id, "profile_id")
    for profile in list_candidate_generation_profiles():
        if profile.profile_id == profile_id:
            return profile
    raise ValueError(f"unknown candidate generation profile: {profile_id}")


def select_candidate_generation_profile(worker_tier: str) -> CandidateGenerationProfile:
    """Select the strongest declared profile for a worker tier."""

    _validate_safe_id(worker_tier, "worker_tier")
    profile_id = _PROFILE_IDS.get(worker_tier)
    if not profile_id:
        allowed = ", ".join(sorted(_PROFILE_IDS))
        raise ValueError(f"unknown worker tier {worker_tier!r}; expected one of: {allowed}")
    return get_candidate_generation_profile(profile_id)


def build_candidate_generation_capability_summary() -> dict[str, Any]:
    """Build a stable integration summary for KG candidate-generation features."""

    profiles = [profile.to_dict() for profile in list_candidate_generation_profiles()]
    return {
        "artifact_id": "formowl_kg_candidate_generation_capability_profiles_v1",
        "selection_boundary": {
            "low_spec_remote_workers_supported": True,
            "neural_models_optional": True,
            "bert_or_sentence_transformer_available_as_adapter_slot": True,
            "candidate_output_only": True,
            "canonical_write_allowed": False,
            "raw_access_allowed": False,
            "system_agent_owns_worker_scheduling": True,
            "legacy_cpu_bert_preserved": True,
            "gpu_default_model_requires_1080ti_or_better": True,
        },
        "worker_tier_mapping": dict(_PROFILE_IDS),
        "profiles": profiles,
    }


def _validate_safe_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value or not _SAFE_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a safe identifier")


def _validate_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")


def _validate_string_tuple(
    values: tuple[str, ...],
    field_name: str,
    *,
    allow_empty: bool = False,
) -> None:
    if not isinstance(values, tuple) or (not values and not allow_empty):
        raise ContractValidationError(f"{field_name} must be a non-empty tuple")
    for value in values:
        _validate_non_empty(value, f"{field_name} entry")
