"""Fail-closed Issue #56 multilingual dense-embedding runtime.

The target profile is an exact-revision, CPU-only SentenceTransformer runtime.
It never substitutes a hash encoder, random vector, ASCII path, or historical
English-only model when dependencies or model artifacts are unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
from typing import Any, Protocol, Sequence
import unicodedata

from .tokenization import (
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    MailCandidateAdmissionTokenizerProfile,
    load_issue56_target_mail_tokenizer_profile,
)


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


ISSUE56_TARGET_DENSE_ENCODER_ID = "multilingual_e5_small_sentence_transformer_v1"
ISSUE56_TARGET_DENSE_MODEL_ID = "intfloat/multilingual-e5-small"
ISSUE56_TARGET_DENSE_MODEL_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
ISSUE56_TARGET_DENSE_DIMENSION = 384
ISSUE56_TARGET_DENSE_NORMALIZATION_ID = "unicode_nfkc_whitespace_l2_float32_v1"
ISSUE56_TARGET_DENSE_QUERY_PREFIX = "query: "
ISSUE56_TARGET_DENSE_EVIDENCE_PREFIX = "passage: "
ISSUE56_TARGET_DENSE_MODEL_FILE_SHA256 = (
    "sha256:1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"
)
ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT = (
    "sha256:39185d72bbf32944bd5498e7ac105311db90ca724f790d0bb123499691ae2b54"
)

_PROFILE_CONTRACT_ID = "formowl_issue56_dense_embedding_profile_v1"
_EXECUTION_COMPONENT_CONTRACT_ID = "formowl_issue56_execution_component_binding_v1"
_UNAVAILABLE_MESSAGE = "issue56 target dense embedding model is unavailable"
_DENSE_EVIDENCE_BATCH_CHUNK_SIZE = 32
_MODEL_FILE_NAME = "model.safetensors"
_MODEL_CONFIG_FILE_NAME = "config.json"
_MAX_MODEL_BYTES = 1024 * 1024 * 1024
_MAX_CONFIG_BYTES = 128 * 1024
_MAX_TOKENIZER_CONFIG_BYTES = 32 * 1024 * 1024
_RUNTIME_DEPENDENCIES = (
    ("huggingface-hub", "0.26.5"),
    ("numpy", "1.26.4"),
    ("safetensors", "0.4.5"),
    ("sentence-transformers", "3.3.1"),
    ("tokenizers", "0.20.3"),
    ("torch", "2.5.1+cpu"),
    ("transformers", "4.46.3"),
)
_MODEL_CONFIGURATION_CONTRACT = {
    "architectures": ["BertModel"],
    "hidden_size": ISSUE56_TARGET_DENSE_DIMENSION,
    "max_position_embeddings": 512,
    "model_embedding_vocabulary_size": 250037,
    "model_type": "bert",
    "num_attention_heads": 12,
    "num_hidden_layers": 12,
    "pad_token_id": 0,
}
_TOKENIZER_CONFIGURATION_CONTRACT = {
    "model_config_tokenizer_class": "XLMRobertaTokenizer",
    "tokenizer_config_tokenizer_class": "XLMRobertaTokenizer",
    "model_max_length": 512,
    "serialized_model_type": "Unigram",
    "serialized_vocabulary_size": 250002,
}
_SENTENCE_TRANSFORMER_CONFIGURATION_CONTRACT = {
    "module_types": [
        "sentence_transformers.models.Transformer",
        "sentence_transformers.models.Pooling",
        "sentence_transformers.models.Normalize",
    ],
    "max_sequence_length": 512,
    "pooling": {
        "pooling_mode_cls_token": False,
        "pooling_mode_max_tokens": False,
        "pooling_mode_mean_sqrt_len_tokens": False,
        "pooling_mode_mean_tokens": True,
        "word_embedding_dimension": ISSUE56_TARGET_DENSE_DIMENSION,
    },
}
_TEXT_POLICY_PAYLOAD = {
    "normalization_id": ISSUE56_TARGET_DENSE_NORMALIZATION_ID,
    "query_prefix": ISSUE56_TARGET_DENSE_QUERY_PREFIX,
    "evidence_prefix": ISSUE56_TARGET_DENSE_EVIDENCE_PREFIX,
    "input_semantics": "natural_authorized_observation_text",
    "output_dtype": "float32",
    "output_normalization": "l2",
}
_MODEL_ARTIFACT_PAYLOAD = {
    "model_id": ISSUE56_TARGET_DENSE_MODEL_ID,
    "model_revision": ISSUE56_TARGET_DENSE_MODEL_REVISION,
    "model_file": _MODEL_FILE_NAME,
    "model_file_sha256": ISSUE56_TARGET_DENSE_MODEL_FILE_SHA256,
    "model_configuration_contract_sha256": _canonical_sha256(_MODEL_CONFIGURATION_CONTRACT),
    "tokenizer_configuration_contract_sha256": _canonical_sha256(_TOKENIZER_CONFIGURATION_CONTRACT),
    "sentence_transformer_configuration_contract_sha256": _canonical_sha256(
        _SENTENCE_TRANSFORMER_CONFIGURATION_CONTRACT
    ),
}


class DenseEmbeddingUnavailableError(RuntimeError):
    """Safe fail-closed signal for a missing or drifting dense runtime."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(_UNAVAILABLE_MESSAGE)
        self.reason_code = reason_code


class DenseEncoder(Protocol):
    """Stable core boundary consumed by lexical+dense retrieval integrations."""

    encoder_id: str
    dimension: int
    diagnostic: bool
    profile_fingerprint: str

    def encode_query(self, text: str) -> tuple[float, ...]:
        """Encode one query with the frozen retrieval-query policy."""

    def encode_evidence(self, text: str) -> tuple[float, ...]:
        """Encode one authorized evidence text with the frozen passage policy."""

    def encode_evidence_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        """Encode authorized evidence texts with the frozen passage policy."""

    def encode_tokens(self, tokens: Sequence[str]) -> tuple[float, ...]:
        """Compatibility boundary for token-set consumers."""


@dataclass(frozen=True)
class DenseEmbeddingProfile:
    """Safe immutable declaration of the target embedding component."""

    encoder_id: str
    model_id: str
    model_revision: str
    dimension: int
    normalization_id: str
    query_prefix: str
    evidence_prefix: str
    model_file_sha256: str
    model_artifact_fingerprint: str
    dependency_versions: tuple[tuple[str, str], ...]
    python_version: str
    backend: str
    profile_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        """Return the canonical no-path/no-secret profile payload."""

        return {
            "profile_contract": _PROFILE_CONTRACT_ID,
            "encoder_id": self.encoder_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "dimension": self.dimension,
            "normalization_id": self.normalization_id,
            "query_prefix": self.query_prefix,
            "evidence_prefix": self.evidence_prefix,
            "model_file_sha256": self.model_file_sha256,
            "model_artifact_fingerprint": self.model_artifact_fingerprint,
            "dependency_versions": dict(self.dependency_versions),
            "python_version": self.python_version,
            "backend": self.backend,
            "text_policy_sha256": _canonical_sha256(_TEXT_POLICY_PAYLOAD),
        }


@dataclass(frozen=True)
class SentenceTransformerDenseEncoder:
    """Exact-revision multilingual E5 encoder loaded from a verified snapshot."""

    profile: DenseEmbeddingProfile
    _model: Any = field(repr=False, compare=False)
    encoder_id: str = field(init=False)
    dimension: int = field(init=False)
    diagnostic: bool = field(init=False, default=False)
    profile_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "encoder_id", self.profile.encoder_id)
        object.__setattr__(self, "dimension", self.profile.dimension)
        object.__setattr__(
            self,
            "profile_fingerprint",
            self.profile.profile_fingerprint,
        )

    def encode_query(self, text: str) -> tuple[float, ...]:
        return self._encode_one(ISSUE56_TARGET_DENSE_QUERY_PREFIX, text)

    def encode_evidence(self, text: str) -> tuple[float, ...]:
        return self._encode_one(ISSUE56_TARGET_DENSE_EVIDENCE_PREFIX, text)

    def encode_evidence_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        return self._encode_many(ISSUE56_TARGET_DENSE_EVIDENCE_PREFIX, texts)

    def encode_tokens(self, tokens: Sequence[str]) -> tuple[float, ...]:
        """Encode a deterministic symmetric token representation.

        New integrations should use ``encode_query`` and ``encode_evidence``.
        This method keeps the core boundary consumable by the current mail
        hybrid implementation without introducing a diagnostic hash fallback.
        """

        normalized_tokens = sorted(
            {
                _normalize_embedding_text(token)
                for token in tokens
                if isinstance(token, str) and token.strip()
            }
        )
        if not normalized_tokens:
            raise ValueError("dense encoder tokens are required")
        return self._encode_one(
            ISSUE56_TARGET_DENSE_QUERY_PREFIX,
            " ".join(normalized_tokens),
        )

    def _encode_one(self, prefix: str, text: str) -> tuple[float, ...]:
        return self._encode_many(prefix, (text,))[0]

    def _encode_many(
        self,
        prefix: str,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        normalized_texts = tuple(_normalize_embedding_text(text) for text in texts)
        if any(not text for text in normalized_texts):
            raise ValueError("dense encoder text is required")
        if not normalized_texts:
            return ()
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(normalized_texts), _DENSE_EVIDENCE_BATCH_CHUNK_SIZE):
            chunk = normalized_texts[start : start + _DENSE_EVIDENCE_BATCH_CHUNK_SIZE]
            try:
                encoded = self._model.encode(
                    [prefix + text for text in chunk],
                    batch_size=min(_DENSE_EVIDENCE_BATCH_CHUNK_SIZE, len(chunk)),
                    show_progress_bar=False,
                    precision="float32",
                    convert_to_numpy=True,
                    convert_to_tensor=False,
                    device="cpu",
                    normalize_embeddings=True,
                )
                if len(encoded) != len(chunk):
                    raise DenseEmbeddingUnavailableError(
                        "dense_batch_output_count_mismatch"
                    )
                chunk_vectors = tuple(
                    tuple(float(value) for value in row.tolist()) for row in encoded
                )
            except (AttributeError, IndexError, TypeError, ValueError) as exc:
                raise DenseEmbeddingUnavailableError("model_inference_failed") from exc
            for vector in chunk_vectors:
                _validate_normalized_vector(vector, expected_dimension=self.dimension)
            vectors.extend(chunk_vectors)
        return tuple(vectors)


@dataclass(frozen=True)
class Issue56ExecutionComponentBinding:
    """Tokenizer+dense runtime fingerprint with no path or secret material."""

    tokenizer_id: str
    tokenizer_profile_fingerprint: str
    dense_encoder_id: str
    dense_profile_fingerprint: str
    dense_model_id: str
    dense_model_revision: str
    dense_dependency_versions_sha256: str
    execution_component_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "component_contract": _EXECUTION_COMPONENT_CONTRACT_ID,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_profile_fingerprint": self.tokenizer_profile_fingerprint,
            "dense_encoder_id": self.dense_encoder_id,
            "dense_profile_fingerprint": self.dense_profile_fingerprint,
            "dense_model_id": self.dense_model_id,
            "dense_model_revision": self.dense_model_revision,
            "dense_dependency_versions_sha256": (self.dense_dependency_versions_sha256),
        }


@dataclass(frozen=True)
class Issue56TargetRuntimeComponents:
    """Target tokenizer and real dense encoder loaded as one fail-closed unit."""

    tokenizer_profile: MailCandidateAdmissionTokenizerProfile
    dense_encoder: SentenceTransformerDenseEncoder
    execution_binding: Issue56ExecutionComponentBinding


def issue56_target_dense_embedding_profile() -> DenseEmbeddingProfile:
    """Return the pinned declaration without importing neural dependencies."""

    payload = {
        "profile_contract": _PROFILE_CONTRACT_ID,
        "encoder_id": ISSUE56_TARGET_DENSE_ENCODER_ID,
        "model_id": ISSUE56_TARGET_DENSE_MODEL_ID,
        "model_revision": ISSUE56_TARGET_DENSE_MODEL_REVISION,
        "dimension": ISSUE56_TARGET_DENSE_DIMENSION,
        "normalization_id": ISSUE56_TARGET_DENSE_NORMALIZATION_ID,
        "query_prefix": ISSUE56_TARGET_DENSE_QUERY_PREFIX,
        "evidence_prefix": ISSUE56_TARGET_DENSE_EVIDENCE_PREFIX,
        "model_file_sha256": ISSUE56_TARGET_DENSE_MODEL_FILE_SHA256,
        "model_artifact_fingerprint": _canonical_sha256(_MODEL_ARTIFACT_PAYLOAD),
        "dependency_versions": dict(_RUNTIME_DEPENDENCIES),
        "python_version": "3.12.11",
        "backend": "sentence_transformers_torch_cpu",
        "text_policy_sha256": _canonical_sha256(_TEXT_POLICY_PAYLOAD),
    }
    profile_fingerprint = _canonical_sha256(payload)
    if profile_fingerprint != ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT:
        raise DenseEmbeddingUnavailableError("profile_declaration_drift")
    return DenseEmbeddingProfile(
        encoder_id=ISSUE56_TARGET_DENSE_ENCODER_ID,
        model_id=ISSUE56_TARGET_DENSE_MODEL_ID,
        model_revision=ISSUE56_TARGET_DENSE_MODEL_REVISION,
        dimension=ISSUE56_TARGET_DENSE_DIMENSION,
        normalization_id=ISSUE56_TARGET_DENSE_NORMALIZATION_ID,
        query_prefix=ISSUE56_TARGET_DENSE_QUERY_PREFIX,
        evidence_prefix=ISSUE56_TARGET_DENSE_EVIDENCE_PREFIX,
        model_file_sha256=ISSUE56_TARGET_DENSE_MODEL_FILE_SHA256,
        model_artifact_fingerprint=payload["model_artifact_fingerprint"],
        dependency_versions=_RUNTIME_DEPENDENCIES,
        python_version=payload["python_version"],
        backend=payload["backend"],
        profile_fingerprint=profile_fingerprint,
    )


def load_issue56_target_dense_encoder(
    *,
    cache_directory: str | Path | None = None,
    expected_profile_fingerprint: str = ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT,
) -> SentenceTransformerDenseEncoder:
    """Load the exact multilingual E5 snapshot locally or fail closed."""

    profile = issue56_target_dense_embedding_profile()
    if expected_profile_fingerprint != profile.profile_fingerprint:
        raise DenseEmbeddingUnavailableError("profile_fingerprint_mismatch")
    _validate_runtime_dependencies(profile)
    snapshot_directory = _resolve_local_model_snapshot(cache_directory)
    _validate_model_snapshot(snapshot_directory, profile)
    model = _load_sentence_transformer(snapshot_directory, profile)
    return SentenceTransformerDenseEncoder(profile=profile, _model=model)


def build_issue56_execution_component_binding(
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    dense_profile: DenseEmbeddingProfile,
) -> Issue56ExecutionComponentBinding:
    """Bind tokenizer and dense model components into one safe fingerprint."""

    if tokenizer_profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID:
        raise DenseEmbeddingUnavailableError("target_tokenizer_profile_required")
    if tokenizer_profile.profile_fingerprint != _canonical_sha256(
        tokenizer_profile.fingerprint_payload()
    ):
        raise DenseEmbeddingUnavailableError("target_tokenizer_profile_drift")
    expected_dense_profile = issue56_target_dense_embedding_profile()
    if (
        dense_profile != expected_dense_profile
        or dense_profile.profile_fingerprint
        != _canonical_sha256(dense_profile.fingerprint_payload())
    ):
        raise DenseEmbeddingUnavailableError("dense_profile_fingerprint_mismatch")
    dependency_versions_sha256 = _canonical_sha256(dict(dense_profile.dependency_versions))
    payload = {
        "component_contract": _EXECUTION_COMPONENT_CONTRACT_ID,
        "tokenizer_id": tokenizer_profile.tokenizer_id,
        "tokenizer_profile_fingerprint": tokenizer_profile.profile_fingerprint,
        "dense_encoder_id": dense_profile.encoder_id,
        "dense_profile_fingerprint": dense_profile.profile_fingerprint,
        "dense_model_id": dense_profile.model_id,
        "dense_model_revision": dense_profile.model_revision,
        "dense_dependency_versions_sha256": dependency_versions_sha256,
    }
    fingerprint = _canonical_sha256(payload)
    return Issue56ExecutionComponentBinding(
        tokenizer_id=tokenizer_profile.tokenizer_id,
        tokenizer_profile_fingerprint=tokenizer_profile.profile_fingerprint,
        dense_encoder_id=dense_profile.encoder_id,
        dense_profile_fingerprint=dense_profile.profile_fingerprint,
        dense_model_id=dense_profile.model_id,
        dense_model_revision=dense_profile.model_revision,
        dense_dependency_versions_sha256=dependency_versions_sha256,
        execution_component_fingerprint=fingerprint,
    )


def load_issue56_target_runtime_components(
    *,
    cache_directory: str | Path | None = None,
    expected_dense_profile_fingerprint: str = (ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT),
) -> Issue56TargetRuntimeComponents:
    """Load the only normal Issue #56 tokenizer+dense runtime path."""

    tokenizer_profile = load_issue56_target_mail_tokenizer_profile()
    dense_encoder = load_issue56_target_dense_encoder(
        cache_directory=cache_directory,
        expected_profile_fingerprint=expected_dense_profile_fingerprint,
    )
    binding = build_issue56_execution_component_binding(
        tokenizer_profile=tokenizer_profile,
        dense_profile=dense_encoder.profile,
    )
    return Issue56TargetRuntimeComponents(
        tokenizer_profile=tokenizer_profile,
        dense_encoder=dense_encoder,
        execution_binding=binding,
    )


def cosine_similarity(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    """Return cosine similarity for already normalized dense vectors."""

    if len(left) != len(right) or not left:
        raise ValueError("dense vector dimensions do not match")
    return float(sum(a * b for a, b in zip(left, right)))


def _validate_runtime_dependencies(profile: DenseEmbeddingProfile) -> None:
    if platform.python_version() != profile.python_version:
        raise DenseEmbeddingUnavailableError("python_runtime_version_mismatch")
    for package_name, expected_version in profile.dependency_versions:
        try:
            actual_version = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise DenseEmbeddingUnavailableError("dense_dependency_unavailable") from exc
        if actual_version != expected_version:
            raise DenseEmbeddingUnavailableError("dense_dependency_version_mismatch")
    try:
        torch = importlib.import_module("torch")
    except ImportError as exc:
        raise DenseEmbeddingUnavailableError("dense_dependency_unavailable") from exc
    if bool(torch.cuda.is_available()) or "+cpu" not in str(torch.__version__):
        raise DenseEmbeddingUnavailableError("dense_backend_runtime_mismatch")


def _resolve_local_model_snapshot(cache_directory: str | Path | None) -> Path:
    try:
        hub = importlib.import_module("huggingface_hub")
        snapshot = hub.snapshot_download(
            repo_id=ISSUE56_TARGET_DENSE_MODEL_ID,
            revision=ISSUE56_TARGET_DENSE_MODEL_REVISION,
            cache_dir=(str(cache_directory) if cache_directory is not None else None),
            local_files_only=True,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise DenseEmbeddingUnavailableError("multilingual_model_snapshot_unavailable") from exc
    snapshot_directory = Path(snapshot)
    if snapshot_directory.name != ISSUE56_TARGET_DENSE_MODEL_REVISION:
        raise DenseEmbeddingUnavailableError("model_revision_mismatch")
    return snapshot_directory


def _validate_model_snapshot(
    snapshot_directory: Path,
    profile: DenseEmbeddingProfile,
) -> None:
    model_sha256 = _verified_file_sha256(
        snapshot_directory / _MODEL_FILE_NAME,
        maximum_bytes=_MAX_MODEL_BYTES,
    )
    if model_sha256 != profile.model_file_sha256:
        raise DenseEmbeddingUnavailableError("model_artifact_fingerprint_mismatch")
    config = _read_json_object(
        snapshot_directory / _MODEL_CONFIG_FILE_NAME,
        maximum_bytes=_MAX_CONFIG_BYTES,
    )
    actual_model_contract = {
        "architectures": config.get("architectures"),
        "hidden_size": config.get("hidden_size"),
        "max_position_embeddings": config.get("max_position_embeddings"),
        "model_embedding_vocabulary_size": config.get("vocab_size"),
        "model_type": config.get("model_type"),
        "num_attention_heads": config.get("num_attention_heads"),
        "num_hidden_layers": config.get("num_hidden_layers"),
        "pad_token_id": config.get("pad_token_id"),
    }
    if actual_model_contract != _MODEL_CONFIGURATION_CONTRACT:
        raise DenseEmbeddingUnavailableError("model_configuration_drift")
    tokenizer_config = _read_json_object(
        snapshot_directory / "tokenizer_config.json",
        maximum_bytes=_MAX_CONFIG_BYTES,
    )
    tokenizer_json = _read_json_object(
        snapshot_directory / "tokenizer.json",
        maximum_bytes=_MAX_TOKENIZER_CONFIG_BYTES,
    )
    serialized_tokenizer_model = tokenizer_json.get("model")
    if not isinstance(serialized_tokenizer_model, dict):
        raise DenseEmbeddingUnavailableError("tokenizer_configuration_drift")
    serialized_vocabulary = serialized_tokenizer_model.get("vocab")
    if not isinstance(serialized_vocabulary, list):
        raise DenseEmbeddingUnavailableError("tokenizer_configuration_drift")
    actual_tokenizer_contract = {
        "model_config_tokenizer_class": config.get("tokenizer_class"),
        "tokenizer_config_tokenizer_class": tokenizer_config.get("tokenizer_class"),
        "model_max_length": tokenizer_config.get("model_max_length"),
        "serialized_model_type": serialized_tokenizer_model.get("type"),
        "serialized_vocabulary_size": len(serialized_vocabulary),
    }
    if actual_tokenizer_contract != _TOKENIZER_CONFIGURATION_CONTRACT:
        raise DenseEmbeddingUnavailableError("tokenizer_configuration_drift")
    modules = _read_json_array(
        snapshot_directory / "modules.json",
        maximum_bytes=_MAX_CONFIG_BYTES,
    )
    pooling = _read_json_object(
        snapshot_directory / "1_Pooling" / "config.json",
        maximum_bytes=_MAX_CONFIG_BYTES,
    )
    sentence_transformer_config = _read_json_object(
        snapshot_directory / "sentence_bert_config.json",
        maximum_bytes=_MAX_CONFIG_BYTES,
    )
    actual_sentence_transformer_contract = {
        "module_types": [
            module.get("type") if isinstance(module, dict) else None for module in modules
        ],
        "max_sequence_length": sentence_transformer_config.get("max_seq_length"),
        "pooling": {
            field: pooling.get(field)
            for field in _SENTENCE_TRANSFORMER_CONFIGURATION_CONTRACT["pooling"]
        },
    }
    if actual_sentence_transformer_contract != _SENTENCE_TRANSFORMER_CONFIGURATION_CONTRACT:
        raise DenseEmbeddingUnavailableError("sentence_transformer_configuration_drift")
    actual_artifact_fingerprint = _canonical_sha256(
        {
            "model_id": profile.model_id,
            "model_revision": profile.model_revision,
            "model_file": _MODEL_FILE_NAME,
            "model_file_sha256": model_sha256,
            "model_configuration_contract_sha256": _canonical_sha256(actual_model_contract),
            "tokenizer_configuration_contract_sha256": _canonical_sha256(actual_tokenizer_contract),
            "sentence_transformer_configuration_contract_sha256": _canonical_sha256(
                actual_sentence_transformer_contract
            ),
        }
    )
    if actual_artifact_fingerprint != profile.model_artifact_fingerprint:
        raise DenseEmbeddingUnavailableError("model_artifact_fingerprint_mismatch")


def _load_sentence_transformer(
    snapshot_directory: Path,
    profile: DenseEmbeddingProfile,
) -> Any:
    try:
        module = importlib.import_module("sentence_transformers")
        model = module.SentenceTransformer(
            str(snapshot_directory),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )
        model.eval()
        dimension = int(model.get_sentence_embedding_dimension())
        max_sequence_length = int(model.max_seq_length)
        tokenizer_vocabulary_size = int(model.tokenizer.vocab_size)
        tokenizer_size_with_added_tokens = int(len(model.tokenizer))
        model_embedding_vocabulary_size = int(model[0].auto_model.config.vocab_size)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise DenseEmbeddingUnavailableError("model_load_failed") from exc
    if dimension != profile.dimension or max_sequence_length != 512:
        raise DenseEmbeddingUnavailableError("model_runtime_configuration_drift")
    if (
        tokenizer_vocabulary_size != _TOKENIZER_CONFIGURATION_CONTRACT["serialized_vocabulary_size"]
        or tokenizer_size_with_added_tokens
        != _TOKENIZER_CONFIGURATION_CONTRACT["serialized_vocabulary_size"]
        or model_embedding_vocabulary_size
        != _MODEL_CONFIGURATION_CONTRACT["model_embedding_vocabulary_size"]
    ):
        raise DenseEmbeddingUnavailableError("model_runtime_configuration_drift")
    return model


def _normalize_embedding_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("dense encoder input must be text")
    normalized = unicodedata.normalize("NFKC", value).strip()
    return " ".join(normalized.split())


def _validate_normalized_vector(
    vector: Sequence[float],
    *,
    expected_dimension: int,
) -> None:
    if len(vector) != expected_dimension:
        raise DenseEmbeddingUnavailableError("dense_vector_dimension_mismatch")
    if any(not math.isfinite(value) for value in vector):
        raise DenseEmbeddingUnavailableError("dense_vector_non_finite")
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
        raise DenseEmbeddingUnavailableError("dense_vector_not_normalized")


def _read_json_object(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    payload = _read_json_value(path, maximum_bytes=maximum_bytes)
    if not isinstance(payload, dict):
        raise DenseEmbeddingUnavailableError("model_configuration_unavailable")
    return payload


def _read_json_array(path: Path, *, maximum_bytes: int) -> list[Any]:
    payload = _read_json_value(path, maximum_bytes=maximum_bytes)
    if not isinstance(payload, list):
        raise DenseEmbeddingUnavailableError("model_configuration_unavailable")
    return payload


def _read_json_value(path: Path, *, maximum_bytes: int) -> Any:
    try:
        metadata = path.stat()
        if not path.is_file() or metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise OSError
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DenseEmbeddingUnavailableError("model_configuration_unavailable") from exc
    return payload


def _verified_file_sha256(path: Path, *, maximum_bytes: int) -> str:
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat()
        if not resolved.is_file() or before.st_size <= 0 or before.st_size > maximum_bytes:
            raise OSError
        digest = _sha256_file(resolved)
        after = resolved.stat()
    except OSError as exc:
        raise DenseEmbeddingUnavailableError("model_artifact_unavailable") from exc
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or _sha256_file(resolved) != digest
    ):
        raise DenseEmbeddingUnavailableError("model_artifact_changed_during_load")
    return digest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


__all__ = [
    "DenseEmbeddingProfile",
    "DenseEmbeddingUnavailableError",
    "DenseEncoder",
    "ISSUE56_TARGET_DENSE_DIMENSION",
    "ISSUE56_TARGET_DENSE_ENCODER_ID",
    "ISSUE56_TARGET_DENSE_MODEL_FILE_SHA256",
    "ISSUE56_TARGET_DENSE_MODEL_ID",
    "ISSUE56_TARGET_DENSE_MODEL_REVISION",
    "ISSUE56_TARGET_DENSE_NORMALIZATION_ID",
    "ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT",
    "Issue56ExecutionComponentBinding",
    "Issue56TargetRuntimeComponents",
    "SentenceTransformerDenseEncoder",
    "build_issue56_execution_component_binding",
    "cosine_similarity",
    "issue56_target_dense_embedding_profile",
    "load_issue56_target_dense_encoder",
    "load_issue56_target_runtime_components",
]
