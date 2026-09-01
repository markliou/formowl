"""Frozen mail candidate-admission tokenizer profiles.

The process default remains the explicitly limited ASCII diagnostic unless an
older environment-supplied experiment is configured.  Issue #56 uses a
separate fail-closed loader for one tracked, packaged Jieba plus SentencePiece
profile; it never falls back to ASCII when an artifact or dependency drifts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Literal
import unicodedata

ASCII_IDENTIFIER_REGEX_TOKENIZER_ID = "ascii_identifier_regex_v1"
JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID = (
    "jieba_sentencepiece_frozen_profile_candidate_admission_v1"
)
ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT = (
    "sha256:aafd7dbf4583cc2cd28e679f9090b518e74da3eee9146fa578d9b257d71e1f1d"
)

_MODEL_PATH_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL"
_MODEL_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"
_MAX_MODEL_BYTES = 16 * 1024 * 1024
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_CALIBRATION_CORPUS_BYTES = 1024 * 1024
_MAX_USER_DICTIONARY_BYTES = 1024 * 1024
_MAX_VOCABULARY_BYTES = 4 * 1024 * 1024
_PROFILE_CONTRACT_ID = "formowl_mail_candidate_admission_profile_v2"
_ISSUE56_PACKAGED_PROFILE_CONTRACT_ID = "formowl_issue56_packaged_tokenizer_profile_v1"
_ISSUE56_TARGET_MANIFEST_SHA256 = (
    "sha256:f20e592ec1a492c07f6d74456eb548978ed1cc80fb6b28ec673d170b1559fa2b"
)
_FORMOWL_PACKAGE_NAME = "formowl"
_FORMOWL_PACKAGE_VERSION = "0.1.0"
_DEPENDENCY_REQUIREMENTS = {
    "formowl": "formowl==0.1.0",
    "jieba": "jieba>=0.42.1,<0.43",
    "sentencepiece": "sentencepiece>=0.2,<0.3",
}
_ISSUE56_SOURCE_POLICY = {
    "content_kind": "tracked_synthetic_cross_domain_calibration_text",
    "contains_private_source": False,
    "contains_oracle": False,
    "contains_uat_or_holdout_questions": False,
}
_ISSUE56_POLICY_BINDINGS = {
    "candidate_admission_policy_id": "formowl_mail_frozen_candidate_admission_v1",
    "normalization_id": "unicode_nfkc_casefold_v1",
    "protected_identifier_policy_id": "formowl_mail_protected_identifier_policy_v1",
}
_ISSUE56_TRAINING_CONFIGURATION = {
    "character_coverage": 1.0,
    "hard_vocab_limit": False,
    "model_type": "bpe",
    "normalization_rule_name": "nmt_nfkc",
    "num_threads": 1,
    "shuffle_input_sentence": False,
    "trainer": "sentencepiece.SentencePieceTrainer",
    "vocab_size": 192,
}
_ASCII_NORMALIZATION_ID = "ascii_lowercase_v1"
_FROZEN_NORMALIZATION_ID = "unicode_nfkc_casefold_v1"
_PROTECTED_IDENTIFIER_POLICY_ID = "formowl_mail_protected_identifier_policy_v1"
_CANDIDATE_ADMISSION_POLICY_ID = "formowl_mail_frozen_candidate_admission_v1"
_CANDIDATE_SCHEMA_VERSION = 1
_ASCII_IDENTIFIER_SEPARATOR = re.compile(r"[^a-zA-Z0-9_@.-]+")
_CJK_CHARACTER = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_TOKEN_EDGE = re.compile(
    r"^[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff@.-]+|"
    r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff@.-]+$"
)
_CJK_BOUNDARY_STOP_CHARACTERS = frozenset("的了和與或是在我想有嗎呢要請")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "of",
        "or",
        "the",
        "to",
        "一下",
        "可以",
        "了",
        "是否",
        "想要",
        "和",
        "嗎",
        "呢",
        "在",
        "想",
        "我",
        "或",
        "是",
        "有",
        "的",
        "與",
        "要",
        "請問",
        "請",
        "我要",
    }
)
_PROTECTED_IDENTIFIER_PATTERNS = (
    (
        "url",
        re.compile(
            r"(?i)\b(?:https?://[^\s<>{}\[\]\"']+|"
            r"www\.[A-Za-z0-9.-]+\.[A-Za-z]{2,}/[^\s<>{}\[\]\"']*)"
        ),
    ),
    (
        "email",
        re.compile(
            r"(?i)(?<![A-Za-z0-9._%+-])"
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
            r"(?![A-Za-z0-9._%+-])"
        ),
    ),
    (
        "date",
        re.compile(r"(?<!\d)\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)"),
    ),
    (
        "amount",
        re.compile(
            r"(?i)(?<![A-Za-z0-9])"
            r"(?:USD|EUR|JPY|TWD|NTD|CNY|RMB|GBP|\$|€|¥)\s*"
            r"\d+(?:,\d{3})*(?:\.\d+)?"
            r"(?![A-Za-z0-9])"
        ),
    ),
    (
        "business_identifier",
        re.compile(
            r"(?i)(?<![A-Za-z0-9])"
            r"(?=[A-Za-z0-9._-]*[A-Za-z])"
            r"(?=[A-Za-z0-9._-]*\d)"
            r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"
            r"(?![A-Za-z0-9])"
        ),
    ),
    (
        "domain",
        re.compile(
            r"(?i)(?<![A-Za-z0-9.-])"
            r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
            r"[A-Za-z]{2,}"
            r"(?![A-Za-z0-9.-])"
        ),
    ),
)
_NORMALIZATION_POLICY_PAYLOADS = {
    _ASCII_NORMALIZATION_ID: {
        "case": "lower",
        "unicode_normalization": "none",
    },
    _FROZEN_NORMALIZATION_ID: {
        "case": "casefold",
        "unicode_normalization": "NFKC",
    },
}
_PROTECTED_IDENTIFIER_POLICY_PAYLOAD = {
    "precedence": [name for name, _pattern in _PROTECTED_IDENTIFIER_PATTERNS],
    "patterns": [
        {
            "identifier_kind": name,
            "pattern": pattern.pattern,
            "flags": pattern.flags,
        }
        for name, pattern in _PROTECTED_IDENTIFIER_PATTERNS
    ],
    "segmentation_behavior": "replace_protected_spans_with_spaces",
    "span_offsets": "original_python_codepoint_offsets",
    "exact_token_normalization": _FROZEN_NORMALIZATION_ID,
}
_CANDIDATE_ADMISSION_POLICY_PAYLOAD = {
    "ascii_candidates": "legacy_identifier_regex_outside_protected_spans",
    "cjk_candidates": "jieba_and_sentencepiece_runs_plus_filtered_bigrams",
    "protected_identifiers": "always_admit_exact_token",
    "sentencepiece_ascii_fragments": "reject",
    "stopword_policy": "closed_static_v1",
    "stopwords": sorted(_STOPWORDS),
    "cjk_boundary_stop_characters": sorted(_CJK_BOUNDARY_STOP_CHARACTERS),
}
_QUERY_GROUNDING_GRAMMAR_POLICY_ID = "formowl_query_grounding_grammar_policy_v1"
_QUERY_GROUNDING_GRAMMAR_ROLE_BY_POS_PREFIX = {
    "c": "conjunction",
    "m": "operator",
    "p": "preposition",
    "q": "operator",
    "r": "pronoun",
    "u": "particle",
    "v": "verb",
    "y": "particle",
}
_QUERY_GROUNDING_GRAMMAR_POLICY_PAYLOAD = {
    "policy_id": _QUERY_GROUNDING_GRAMMAR_POLICY_ID,
    "segmenter": "jieba.posseg.POSTokenizer",
    "hmm": False,
    "roles_by_pos_prefix": _QUERY_GROUNDING_GRAMMAR_ROLE_BY_POS_PREFIX,
    "default_role": "lexical",
    "protected_identifiers": "atomic_lexical_terms",
    "punctuation": "omit_unicode_category_P",
    "whitespace": "omit",
    "offsets": "original_python_codepoint_offsets",
}


@dataclass(frozen=True)
class ProtectedIdentifierSpan:
    """One identifier frozen before lexical segmentation."""

    start: int
    end: int
    identifier_kind: str
    original_surface: str
    normalized_surface: str
    exact_token: str


@dataclass(frozen=True)
class MailCandidateAdmissionTokenization:
    """Tokens plus protected spans produced by one immutable profile."""

    tokens: frozenset[str]
    protected_identifiers: tuple[ProtectedIdentifierSpan, ...]


QueryGroundingGrammarRole = Literal[
    "conjunction",
    "lexical",
    "operator",
    "particle",
    "preposition",
    "pronoun",
    "verb",
]


@dataclass(frozen=True)
class OrderedQueryGroundingTerm:
    """One ordered normalized query span with a closed grammar role."""

    start: int
    end: int
    normalized_term: str
    grammar_role: QueryGroundingGrammarRole


@dataclass(frozen=True)
class OrderedQueryGroundingAnalysis:
    """Ordered query terms governed by one profile-bound grammar policy."""

    terms: tuple[OrderedQueryGroundingTerm, ...]
    grammar_policy_fingerprint: str


@dataclass(frozen=True)
class MailCandidateAdmissionTokenizerProfile:
    """An immutable, fingerprinted tokenizer contract for one process."""

    tokenizer_id: str
    profile_fingerprint: str
    model_sha256: str | None
    normalization_id: str
    normalization_sha256: str
    jieba_version: str | None
    jieba_dictionary_sha256: str | None
    jieba_user_dictionary_sha256: str | None
    sentencepiece_version: str | None
    sentencepiece_vocabulary_sha256: str | None
    protected_identifier_policy_id: str
    protected_identifier_policy_sha256: str
    candidate_admission_policy_id: str
    candidate_admission_policy_sha256: str
    candidate_schema_version: int
    artifact_manifest_sha256: str | None = None
    calibration_corpus_sha256: str | None = None
    sentencepiece_vocabulary_artifact_sha256: str | None = None
    package_name: str | None = None
    package_version: str | None = None
    dependency_requirements_sha256: str | None = None
    dependency_versions_sha256: str | None = None
    _jieba_module: Any | None = field(repr=False, compare=False, default=None)
    _sentencepiece_processor: Any | None = field(repr=False, compare=False, default=None)

    def tokenize(self, value: str) -> set[str]:
        """Return candidate-admission tokens under this fixed profile."""

        return set(self.analyze(value).tokens)

    def normalize_exact_identifier_surface(self, value: str) -> str:
        """Normalize one exact identifier with this profile's frozen policy."""

        _require_text(value)
        return _normalize_text(value, self.normalization_id).strip()

    def analyze(self, value: str) -> MailCandidateAdmissionTokenization:
        """Tokenize while retaining identifier spans admitted before segmentation."""

        _require_text(value)
        protected_identifiers = _protected_identifier_spans(value)
        if self.tokenizer_id == ASCII_IDENTIFIER_REGEX_TOKENIZER_ID:
            return MailCandidateAdmissionTokenization(
                tokens=frozenset(_legacy_ascii_identifier_regex_tokens(value)),
                protected_identifiers=protected_identifiers,
            )

        segmented_value = _without_protected_identifier_spans(value, protected_identifiers)
        admitted = _legacy_ascii_identifier_regex_tokens(
            _normalize_text(segmented_value, self.normalization_id)
        )
        admitted.update(span.exact_token for span in protected_identifiers)

        if self._jieba_module is None or self._sentencepiece_processor is None:
            raise RuntimeError("frozen tokenizer profile is unavailable")
        normalized_segmented_value = _normalize_text(segmented_value, self.normalization_id)
        for piece in self._jieba_module.cut(normalized_segmented_value, cut_all=False):
            admitted.update(_admitted_piece_tokens(piece))
        try:
            sentencepiece_pieces = self._sentencepiece_processor.encode(
                normalized_segmented_value,
                out_type=str,
            )
        except TypeError:
            sentencepiece_pieces = self._sentencepiece_processor.EncodeAsPieces(
                normalized_segmented_value
            )
        for piece in sentencepiece_pieces:
            admitted.update(_admitted_piece_tokens(str(piece).replace("\u2581", "")))
        return MailCandidateAdmissionTokenization(
            tokens=frozenset(admitted),
            protected_identifiers=protected_identifiers,
        )

    def analyze_query_grounding(self, value: str) -> OrderedQueryGroundingAnalysis:
        """Return all ordered non-punctuation spans with deterministic POS roles.

        This is a planning-only view.  It does not participate in candidate
        admission, retrieval token hashing, or this profile's fingerprint.
        """

        _require_text(value)
        if (
            self.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
            or self._jieba_module is None
        ):
            raise RuntimeError("frozen tokenizer query grounding is unavailable")
        try:
            posseg = importlib.import_module("jieba.posseg")
            pos_tokenizer = posseg.POSTokenizer(self._jieba_module)
        except (AttributeError, ImportError, TypeError) as exc:
            raise RuntimeError("frozen tokenizer query grounding is unavailable") from exc

        protected_identifiers = _protected_identifier_spans(value)
        segmented_value = _without_protected_identifier_spans(
            value,
            protected_identifiers,
        )
        terms = [
            OrderedQueryGroundingTerm(
                start=span.start,
                end=span.end,
                normalized_term=span.normalized_surface,
                grammar_role="lexical",
            )
            for span in protected_identifiers
        ]
        cursor = 0
        try:
            pos_terms = pos_tokenizer.cut(segmented_value, HMM=False)
            for pos_term in pos_terms:
                surface = str(pos_term.word)
                start = segmented_value.find(surface, cursor)
                if not surface or start < cursor:
                    raise RuntimeError
                end = start + len(surface)
                cursor = end
                if _query_grounding_omits(surface):
                    continue
                normalized_term = _normalize_text(surface, self.normalization_id).strip()
                if not normalized_term:
                    raise RuntimeError
                terms.append(
                    OrderedQueryGroundingTerm(
                        start=start,
                        end=end,
                        normalized_term=normalized_term,
                        grammar_role=_query_grounding_grammar_role(pos_term.flag),
                    )
                )
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            raise RuntimeError("frozen tokenizer query grounding is unavailable") from exc

        ordered_terms = tuple(sorted(terms, key=lambda term: (term.start, term.end)))
        if any(
            current.end > following.start
            for current, following in zip(ordered_terms, ordered_terms[1:])
        ):
            raise RuntimeError("frozen tokenizer query grounding is unavailable")
        covered_offsets = {
            offset
            for term in ordered_terms
            for offset in range(term.start, term.end)
        }
        if any(
            offset not in covered_offsets and not _query_grounding_omits(character)
            for offset, character in enumerate(value)
        ):
            raise RuntimeError("frozen tokenizer query grounding is unavailable")
        return OrderedQueryGroundingAnalysis(
            terms=ordered_terms,
            grammar_policy_fingerprint=_query_grounding_grammar_policy_fingerprint(self),
        )

    def fingerprint_payload(self) -> dict[str, Any]:
        """Return the canonical non-path profile payload bound by the fingerprint."""

        return {
            "profile_contract": _PROFILE_CONTRACT_ID,
            "tokenizer_id": self.tokenizer_id,
            "normalization_id": self.normalization_id,
            "normalization_sha256": self.normalization_sha256,
            "jieba_version": self.jieba_version,
            "jieba_dictionary_sha256": self.jieba_dictionary_sha256,
            "jieba_user_dictionary_sha256": self.jieba_user_dictionary_sha256,
            "sentencepiece_version": self.sentencepiece_version,
            "sentencepiece_model_sha256": self.model_sha256,
            "sentencepiece_vocabulary_sha256": self.sentencepiece_vocabulary_sha256,
            "protected_identifier_policy_id": self.protected_identifier_policy_id,
            "protected_identifier_policy_sha256": self.protected_identifier_policy_sha256,
            "candidate_admission_policy_id": self.candidate_admission_policy_id,
            "candidate_admission_policy_sha256": self.candidate_admission_policy_sha256,
            "candidate_schema_version": self.candidate_schema_version,
            "artifact_manifest_sha256": self.artifact_manifest_sha256,
            "calibration_corpus_sha256": self.calibration_corpus_sha256,
            "sentencepiece_vocabulary_artifact_sha256": (
                self.sentencepiece_vocabulary_artifact_sha256
            ),
            "package_name": self.package_name,
            "package_version": self.package_version,
            "dependency_requirements_sha256": self.dependency_requirements_sha256,
            "dependency_versions_sha256": self.dependency_versions_sha256,
        }


def load_issue56_target_mail_tokenizer_profile(
    *,
    artifact_directory: str | Path | None = None,
) -> MailCandidateAdmissionTokenizerProfile:
    """Load the tracked Issue #56 target profile or fail closed."""

    profile_root = (
        Path(artifact_directory)
        if artifact_directory is not None
        else Path(__file__).resolve().parent
        / "tokenizer_profiles"
        / JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
    )
    manifest_path = profile_root / "manifest.json"
    manifest, manifest_sha256 = _read_verified_json_object(
        manifest_path,
        expected_sha256=_ISSUE56_TARGET_MANIFEST_SHA256,
        maximum_bytes=_MAX_MANIFEST_BYTES,
    )
    artifacts, dependency_versions = _validate_issue56_target_manifest(manifest)
    _calibration_path, calibration_sha256 = _verified_manifest_artifact(
        profile_root,
        artifacts,
        "calibration_corpus",
        maximum_bytes=_MAX_CALIBRATION_CORPUS_BYTES,
    )
    user_dictionary_path, user_dictionary_sha256 = _verified_manifest_artifact(
        profile_root,
        artifacts,
        "jieba_user_dictionary",
        maximum_bytes=_MAX_USER_DICTIONARY_BYTES,
    )
    model_path, model_sha256 = _verified_manifest_artifact(
        profile_root,
        artifacts,
        "sentencepiece_model",
        maximum_bytes=_MAX_MODEL_BYTES,
    )
    _vocabulary_path, vocabulary_artifact_sha256 = _verified_manifest_artifact(
        profile_root,
        artifacts,
        "sentencepiece_vocabulary",
        maximum_bytes=_MAX_VOCABULARY_BYTES,
    )

    profile = build_frozen_jieba_sentencepiece_tokenizer_profile(
        model_path=model_path,
        model_sha256=model_sha256,
        user_dictionary_path=user_dictionary_path,
        user_dictionary_sha256=user_dictionary_sha256,
        expected_jieba_dictionary_sha256=str(
            manifest["dependencies"]["jieba"]["dictionary_sha256"]
        ),
        expected_jieba_version=dependency_versions["jieba"],
        expected_sentencepiece_version=dependency_versions["sentencepiece"],
        artifact_manifest_sha256=manifest_sha256,
        calibration_corpus_sha256=calibration_sha256,
        sentencepiece_vocabulary_artifact_sha256=vocabulary_artifact_sha256,
    )
    if profile.profile_fingerprint != ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return profile


@lru_cache(maxsize=1)
def load_default_mail_candidate_admission_tokenizer_profile(
    *,
    artifact_directory: str | Path | None = None,
) -> MailCandidateAdmissionTokenizerProfile:
    """Load the only normal target-runtime tokenizer profile.

    The older environment-configured/ASCII builder remains an explicit legacy
    diagnostic compatibility surface until its mail callers are migrated by
    their owning worker.
    """

    return load_issue56_target_mail_tokenizer_profile(artifact_directory=artifact_directory)


def build_mail_candidate_admission_tokenizer_profile() -> MailCandidateAdmissionTokenizerProfile:
    """Build the legacy environment-configured diagnostic compatibility profile."""

    model_path = os.environ.get(_MODEL_PATH_ENV)
    model_sha256 = os.environ.get(_MODEL_SHA256_ENV)
    configured_path = _configured_value(model_path)
    configured_sha256 = _configured_value(model_sha256)
    if configured_path is None and configured_sha256 is None:
        return build_ascii_identifier_regex_tokenizer_profile()
    if configured_path is None or configured_sha256 is None:
        raise RuntimeError("frozen tokenizer profile is unavailable")

    return build_frozen_jieba_sentencepiece_tokenizer_profile(
        model_path=configured_path,
        model_sha256=configured_sha256,
    )


def build_ascii_identifier_regex_tokenizer_profile() -> MailCandidateAdmissionTokenizerProfile:
    """Build the explicit limited baseline profile without reading environment state."""

    payload = _profile_payload(
        tokenizer_id=ASCII_IDENTIFIER_REGEX_TOKENIZER_ID,
        normalization_id=_ASCII_NORMALIZATION_ID,
        jieba_version=None,
        jieba_dictionary_sha256=None,
        jieba_user_dictionary_sha256=None,
        sentencepiece_version=None,
        model_sha256=None,
        sentencepiece_vocabulary_sha256=None,
    )
    return MailCandidateAdmissionTokenizerProfile(
        tokenizer_id=ASCII_IDENTIFIER_REGEX_TOKENIZER_ID,
        profile_fingerprint=_profile_fingerprint(payload),
        model_sha256=None,
        normalization_id=payload["normalization_id"],
        normalization_sha256=payload["normalization_sha256"],
        jieba_version=None,
        jieba_dictionary_sha256=None,
        jieba_user_dictionary_sha256=None,
        sentencepiece_version=None,
        sentencepiece_vocabulary_sha256=None,
        protected_identifier_policy_id=_PROTECTED_IDENTIFIER_POLICY_ID,
        protected_identifier_policy_sha256=payload["protected_identifier_policy_sha256"],
        candidate_admission_policy_id=_CANDIDATE_ADMISSION_POLICY_ID,
        candidate_admission_policy_sha256=payload["candidate_admission_policy_sha256"],
        candidate_schema_version=_CANDIDATE_SCHEMA_VERSION,
        artifact_manifest_sha256=None,
        calibration_corpus_sha256=None,
        sentencepiece_vocabulary_artifact_sha256=None,
        package_name=None,
        package_version=None,
        dependency_requirements_sha256=None,
        dependency_versions_sha256=None,
    )


def build_frozen_jieba_sentencepiece_tokenizer_profile(
    *,
    model_path: str | Path,
    model_sha256: str,
    user_dictionary_path: str | Path | None = None,
    user_dictionary_sha256: str | None = None,
    expected_jieba_dictionary_sha256: str | None = None,
    expected_jieba_version: str | None = None,
    expected_sentencepiece_version: str | None = None,
    artifact_manifest_sha256: str | None = None,
    calibration_corpus_sha256: str | None = None,
    sentencepiece_vocabulary_artifact_sha256: str | None = None,
) -> MailCandidateAdmissionTokenizerProfile:
    """Build one explicitly pinned frozen Jieba + SentencePiece profile."""

    configured_path = _configured_value(str(model_path))
    configured_sha256 = _configured_value(model_sha256)
    if configured_path is None or configured_sha256 is None:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    processor = _load_sentencepiece_processor(configured_path, configured_sha256)
    (
        jieba_tokenizer,
        jieba_version,
        jieba_dictionary_sha256,
        resolved_user_dictionary_sha256,
    ) = _frozen_jieba_tokenizer(
        user_dictionary_path=user_dictionary_path,
        expected_user_dictionary_sha256=user_dictionary_sha256,
        expected_dictionary_sha256=expected_jieba_dictionary_sha256,
    )
    sentencepiece_version = _package_version("sentencepiece")
    if expected_jieba_version is not None and jieba_version != expected_jieba_version:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    if (
        expected_sentencepiece_version is not None
        and sentencepiece_version != expected_sentencepiece_version
    ):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    vocabulary_sha256 = _sentencepiece_vocabulary_sha256(processor)
    dependency_versions_sha256 = _canonical_sha256(
        {
            "jieba": jieba_version,
            "sentencepiece": sentencepiece_version,
        }
    )
    payload = _profile_payload(
        tokenizer_id=JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        normalization_id=_FROZEN_NORMALIZATION_ID,
        jieba_version=jieba_version,
        jieba_dictionary_sha256=jieba_dictionary_sha256,
        jieba_user_dictionary_sha256=resolved_user_dictionary_sha256,
        sentencepiece_version=sentencepiece_version,
        model_sha256=configured_sha256,
        sentencepiece_vocabulary_sha256=vocabulary_sha256,
        artifact_manifest_sha256=artifact_manifest_sha256,
        calibration_corpus_sha256=calibration_corpus_sha256,
        sentencepiece_vocabulary_artifact_sha256=(sentencepiece_vocabulary_artifact_sha256),
        package_name=_FORMOWL_PACKAGE_NAME,
        package_version=_FORMOWL_PACKAGE_VERSION,
        dependency_requirements_sha256=_canonical_sha256(_DEPENDENCY_REQUIREMENTS),
        dependency_versions_sha256=dependency_versions_sha256,
    )
    return MailCandidateAdmissionTokenizerProfile(
        tokenizer_id=JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        profile_fingerprint=_profile_fingerprint(payload),
        model_sha256=configured_sha256,
        normalization_id=payload["normalization_id"],
        normalization_sha256=payload["normalization_sha256"],
        jieba_version=jieba_version,
        jieba_dictionary_sha256=jieba_dictionary_sha256,
        jieba_user_dictionary_sha256=payload["jieba_user_dictionary_sha256"],
        sentencepiece_version=sentencepiece_version,
        sentencepiece_vocabulary_sha256=vocabulary_sha256,
        protected_identifier_policy_id=_PROTECTED_IDENTIFIER_POLICY_ID,
        protected_identifier_policy_sha256=payload["protected_identifier_policy_sha256"],
        candidate_admission_policy_id=_CANDIDATE_ADMISSION_POLICY_ID,
        candidate_admission_policy_sha256=payload["candidate_admission_policy_sha256"],
        candidate_schema_version=_CANDIDATE_SCHEMA_VERSION,
        artifact_manifest_sha256=artifact_manifest_sha256,
        calibration_corpus_sha256=calibration_corpus_sha256,
        sentencepiece_vocabulary_artifact_sha256=(sentencepiece_vocabulary_artifact_sha256),
        package_name=_FORMOWL_PACKAGE_NAME,
        package_version=_FORMOWL_PACKAGE_VERSION,
        dependency_requirements_sha256=payload["dependency_requirements_sha256"],
        dependency_versions_sha256=dependency_versions_sha256,
        _jieba_module=jieba_tokenizer,
        _sentencepiece_processor=processor,
    )


def ascii_identifier_regex_tokens(value: str) -> set[str]:
    """Tokenize with the explicit legacy ASCII diagnostic baseline."""

    return DEFAULT_MAIL_CANDIDATE_ADMISSION_TOKENIZER_PROFILE.tokenize(value)


def configured_mail_tokenizer_id() -> str:
    """Return the identifier for a newly validated configured profile."""

    return build_mail_candidate_admission_tokenizer_profile().tokenizer_id


def configured_mail_candidate_admission_tokens(value: str) -> set[str]:
    """Tokenize under a newly validated configuration for isolated callers."""

    return build_mail_candidate_admission_tokenizer_profile().tokenize(value)


def jieba_sentencepiece_frozen_profile_candidate_admission_tokens(value: str) -> set[str]:
    """Tokenize with the packaged Issue #56 target profile or fail closed."""

    return load_default_mail_candidate_admission_tokenizer_profile().tokenize(value)


def _legacy_ascii_identifier_regex_tokens(value: str) -> set[str]:
    _require_text(value)
    return {token for token in _ASCII_IDENTIFIER_SEPARATOR.split(value.lower()) if token}


def _configured_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _profile_payload(
    *,
    tokenizer_id: str,
    normalization_id: str,
    jieba_version: str | None,
    jieba_dictionary_sha256: str | None,
    jieba_user_dictionary_sha256: str | None,
    sentencepiece_version: str | None,
    model_sha256: str | None,
    sentencepiece_vocabulary_sha256: str | None,
    artifact_manifest_sha256: str | None = None,
    calibration_corpus_sha256: str | None = None,
    sentencepiece_vocabulary_artifact_sha256: str | None = None,
    package_name: str | None = None,
    package_version: str | None = None,
    dependency_requirements_sha256: str | None = None,
    dependency_versions_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "profile_contract": _PROFILE_CONTRACT_ID,
        "tokenizer_id": tokenizer_id,
        "normalization_id": normalization_id,
        "normalization_sha256": _canonical_sha256(_NORMALIZATION_POLICY_PAYLOADS[normalization_id]),
        "jieba_version": jieba_version,
        "jieba_dictionary_sha256": jieba_dictionary_sha256,
        "jieba_user_dictionary_sha256": jieba_user_dictionary_sha256,
        "sentencepiece_version": sentencepiece_version,
        "sentencepiece_model_sha256": model_sha256,
        "sentencepiece_vocabulary_sha256": sentencepiece_vocabulary_sha256,
        "protected_identifier_policy_id": _PROTECTED_IDENTIFIER_POLICY_ID,
        "protected_identifier_policy_sha256": _canonical_sha256(
            _PROTECTED_IDENTIFIER_POLICY_PAYLOAD
        ),
        "candidate_admission_policy_id": _CANDIDATE_ADMISSION_POLICY_ID,
        "candidate_admission_policy_sha256": _canonical_sha256(_CANDIDATE_ADMISSION_POLICY_PAYLOAD),
        "candidate_schema_version": _CANDIDATE_SCHEMA_VERSION,
        "artifact_manifest_sha256": artifact_manifest_sha256,
        "calibration_corpus_sha256": calibration_corpus_sha256,
        "sentencepiece_vocabulary_artifact_sha256": (sentencepiece_vocabulary_artifact_sha256),
        "package_name": package_name,
        "package_version": package_version,
        "dependency_requirements_sha256": dependency_requirements_sha256,
        "dependency_versions_sha256": dependency_versions_sha256,
    }


def _profile_fingerprint(payload: dict[str, Any]) -> str:
    return _canonical_sha256(payload)


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_verified_json_object(
    path: Path,
    *,
    expected_sha256: str,
    maximum_bytes: int,
) -> tuple[dict[str, Any], str]:
    before = _regular_file_metadata(path, maximum_bytes=maximum_bytes)
    try:
        payload_bytes = path.read_bytes()
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    actual_sha256 = _sha256_bytes(payload_bytes)
    if (
        actual_sha256 != expected_sha256
        or _regular_file_metadata(path, maximum_bytes=maximum_bytes) != before
        or _sha256(path) != actual_sha256
        or not isinstance(payload, dict)
    ):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return payload, actual_sha256


def _validate_issue56_target_manifest(
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        if manifest["schema_version"] != 1:
            raise ValueError
        if manifest["profile_contract"] != _ISSUE56_PACKAGED_PROFILE_CONTRACT_ID:
            raise ValueError
        if manifest["tokenizer_id"] != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID:
            raise ValueError
        if manifest["source_partition"] != "calibration":
            raise ValueError
        if manifest["source_policy"] != _ISSUE56_SOURCE_POLICY:
            raise ValueError
        if manifest["policies"] != _ISSUE56_POLICY_BINDINGS:
            raise ValueError
        if manifest["training"] != _ISSUE56_TRAINING_CONFIGURATION:
            raise ValueError
        artifacts = manifest["artifacts"]
        if not isinstance(artifacts, dict) or set(artifacts) != {
            "calibration_corpus",
            "jieba_user_dictionary",
            "sentencepiece_model",
            "sentencepiece_vocabulary",
        }:
            raise ValueError
        dependencies = manifest["dependencies"]
        if not isinstance(dependencies, dict) or set(dependencies) != set(_DEPENDENCY_REQUIREMENTS):
            raise ValueError
        dependency_versions: dict[str, str] = {}
        for package_name, requirement in _DEPENDENCY_REQUIREMENTS.items():
            dependency = dependencies[package_name]
            if (
                not isinstance(dependency, dict)
                or dependency.get("requirement") != requirement
                or not isinstance(dependency.get("version"), str)
            ):
                raise ValueError
            installed_version = _package_version(package_name)
            if dependency["version"] != installed_version:
                raise ValueError
            dependency_versions[package_name] = installed_version
        dictionary_sha256 = dependencies["jieba"].get("dictionary_sha256")
        if not isinstance(dictionary_sha256, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            dictionary_sha256,
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    return artifacts, dependency_versions


def _verified_manifest_artifact(
    profile_root: Path,
    artifacts: dict[str, Any],
    artifact_name: str,
    *,
    maximum_bytes: int,
) -> tuple[Path, str]:
    try:
        artifact = artifacts[artifact_name]
        relative_path = artifact["path"]
        expected_sha256 = artifact["sha256"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    if (
        not isinstance(relative_path, str)
        or Path(relative_path).name != relative_path
        or not isinstance(expected_sha256, str)
    ):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    path = profile_root / relative_path
    return path, _verified_file_sha256(
        path,
        expected_sha256=expected_sha256,
        maximum_bytes=maximum_bytes,
    )


def _verified_file_sha256(
    path: Path,
    *,
    expected_sha256: str,
    maximum_bytes: int,
) -> str:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_sha256):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    before = _regular_file_metadata(path, maximum_bytes=maximum_bytes)
    actual_sha256 = _sha256(path)
    if (
        actual_sha256 != expected_sha256
        or _regular_file_metadata(path, maximum_bytes=maximum_bytes) != before
        or _sha256(path) != actual_sha256
    ):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return actual_sha256


def _admitted_piece_tokens(value: Any) -> set[str]:
    normalized = _TOKEN_EDGE.sub("", str(value).strip().lower())
    if not normalized or normalized in _STOPWORDS or normalized in {"<unk>", "<s>", "</s>"}:
        return set()
    if _CJK_CHARACTER.search(normalized):
        return _admitted_cjk_tokens(normalized)
    # Protected ASCII identifiers are admitted solely by the legacy regex.  Do
    # not admit SentencePiece fragments such as ``47000`` or ``g301``.
    return set()


def _admitted_cjk_tokens(value: str) -> set[str]:
    admitted: set[str] = set()
    for run in _CJK_RUN.findall(value):
        if len(run) < 2 or run in _STOPWORDS:
            continue
        admitted.add(run)
        if len(run) <= 2:
            continue
        for index in range(len(run) - 1):
            bigram = run[index : index + 2]
            if (
                bigram in _STOPWORDS
                or bigram[0] in _CJK_BOUNDARY_STOP_CHARACTERS
                or bigram[-1] in _CJK_BOUNDARY_STOP_CHARACTERS
            ):
                continue
            admitted.add(bigram)
    return admitted


def _frozen_jieba_tokenizer(
    *,
    user_dictionary_path: str | Path | None = None,
    expected_user_dictionary_sha256: str | None = None,
    expected_dictionary_sha256: str | None = None,
) -> tuple[Any, str, str, str]:
    try:
        module = importlib.import_module("jieba")
    except ImportError as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    set_log_level = getattr(module, "setLogLevel", None)
    if callable(set_log_level):
        set_log_level(30)
    module_path = Path(getattr(module, "__file__", "")).resolve()
    dictionary_path = module_path.parent / "dict.txt"
    before = _regular_file_metadata(dictionary_path, maximum_bytes=32 * 1024 * 1024)
    dictionary_sha256 = _sha256(dictionary_path)
    if expected_dictionary_sha256 is not None and dictionary_sha256 != expected_dictionary_sha256:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    configured_user_dictionary = (
        Path(user_dictionary_path) if user_dictionary_path is not None else None
    )
    if (configured_user_dictionary is None) != (expected_user_dictionary_sha256 is None):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    user_dictionary_before: tuple[int, int, int, int] | None = None
    user_dictionary_sha256 = _sha256_bytes(b"")
    if configured_user_dictionary is not None:
        user_dictionary_before = _regular_file_metadata(
            configured_user_dictionary,
            maximum_bytes=_MAX_USER_DICTIONARY_BYTES,
        )
        user_dictionary_sha256 = _sha256(configured_user_dictionary)
        if user_dictionary_sha256 != expected_user_dictionary_sha256:
            raise RuntimeError("frozen tokenizer profile is unavailable")
    try:
        tokenizer = module.Tokenizer(dictionary=str(dictionary_path))
        tokenizer.initialize()
        if configured_user_dictionary is not None:
            with configured_user_dictionary.open("rb") as user_dictionary:
                tokenizer.load_userdict(user_dictionary)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    if (
        _regular_file_metadata(dictionary_path, maximum_bytes=32 * 1024 * 1024) != before
        or _sha256(dictionary_path) != dictionary_sha256
    ):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    if configured_user_dictionary is not None and (
        _regular_file_metadata(
            configured_user_dictionary,
            maximum_bytes=_MAX_USER_DICTIONARY_BYTES,
        )
        != user_dictionary_before
        or _sha256(configured_user_dictionary) != user_dictionary_sha256
    ):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return (
        tokenizer,
        _package_version("jieba"),
        dictionary_sha256,
        user_dictionary_sha256,
    )


def _load_sentencepiece_processor(model_path: str, expected_sha256: str) -> Any:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_sha256):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    path = Path(model_path)
    before = _regular_model_metadata(path)
    if _sha256(path) != expected_sha256:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    try:
        sentencepiece = importlib.import_module("sentencepiece")
        try:
            processor = sentencepiece.SentencePieceProcessor(model_file=str(path))
        except TypeError:
            processor = sentencepiece.SentencePieceProcessor()
            if not processor.Load(str(path)):
                raise RuntimeError("frozen tokenizer profile is unavailable")
    except (ImportError, OSError, RuntimeError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    if _regular_model_metadata(path) != before or _sha256(path) != expected_sha256:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return processor


def _regular_model_metadata(path: Path) -> tuple[int, int, int, int]:
    return _regular_file_metadata(path, maximum_bytes=_MAX_MODEL_BYTES)


def _regular_file_metadata(
    path: Path,
    *,
    maximum_bytes: int,
) -> tuple[int, int, int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    return "sha256:" + digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _package_version(package_name: str) -> str:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc


def _sentencepiece_vocabulary_sha256(processor: Any) -> str:
    try:
        piece_count = int(processor.get_piece_size())
    except AttributeError:
        piece_count = int(processor.GetPieceSize())
    pieces: list[dict[str, Any]] = []
    for index in range(piece_count):
        try:
            piece = str(processor.id_to_piece(index))
        except AttributeError:
            piece = str(processor.IdToPiece(index))
        try:
            score = float(processor.get_score(index))
        except AttributeError:
            score = float(processor.GetScore(index))
        pieces.append({"id": index, "piece": piece, "score": score})
    return _canonical_sha256(pieces)


def _protected_identifier_spans(value: str) -> tuple[ProtectedIdentifierSpan, ...]:
    occupied: list[tuple[int, int]] = []
    spans: list[ProtectedIdentifierSpan] = []
    for identifier_kind, pattern in _PROTECTED_IDENTIFIER_PATTERNS:
        for match in pattern.finditer(value):
            start, end = match.span()
            if any(
                start < occupied_end and end > occupied_start
                for occupied_start, occupied_end in occupied
            ):
                continue
            original = match.group(0)
            normalized = _normalize_text(original, _FROZEN_NORMALIZATION_ID).strip()
            exact_token = _normalized_protected_token(normalized, identifier_kind)
            if not exact_token:
                continue
            occupied.append((start, end))
            spans.append(
                ProtectedIdentifierSpan(
                    start=start,
                    end=end,
                    identifier_kind=identifier_kind,
                    original_surface=original,
                    normalized_surface=normalized,
                    exact_token=exact_token,
                )
            )
    return tuple(sorted(spans, key=lambda span: (span.start, span.end, span.identifier_kind)))


def _without_protected_identifier_spans(
    value: str,
    spans: tuple[ProtectedIdentifierSpan, ...],
) -> str:
    if not spans:
        return value
    characters = list(value)
    for span in spans:
        characters[span.start : span.end] = " " * (span.end - span.start)
    return "".join(characters)


def _normalized_protected_token(value: str, identifier_kind: str) -> str:
    normalized = value.strip(" \t\r\n<>()[]{}\"'，。；：！？,;:!?")
    if identifier_kind == "amount":
        normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _query_grounding_omits(value: str) -> bool:
    return all(
        character.isspace() or unicodedata.category(character).startswith("P")
        for character in value
    )


def _query_grounding_grammar_role(pos_tag: Any) -> QueryGroundingGrammarRole:
    normalized_tag = str(pos_tag).strip().lower()
    if not normalized_tag:
        raise RuntimeError("frozen tokenizer query grounding is unavailable")
    return _QUERY_GROUNDING_GRAMMAR_ROLE_BY_POS_PREFIX.get(
        normalized_tag[0],
        "lexical",
    )


def _query_grounding_grammar_policy_fingerprint(
    profile: MailCandidateAdmissionTokenizerProfile,
) -> str:
    return _canonical_sha256(
        {
            "grammar_policy": _QUERY_GROUNDING_GRAMMAR_POLICY_PAYLOAD,
            "tokenizer_id": profile.tokenizer_id,
            "normalization_id": profile.normalization_id,
            "normalization_sha256": profile.normalization_sha256,
            "jieba_version": profile.jieba_version,
            "jieba_dictionary_sha256": profile.jieba_dictionary_sha256,
            "jieba_user_dictionary_sha256": profile.jieba_user_dictionary_sha256,
        }
    )


def _normalize_text(value: str, normalization_id: str) -> str:
    if normalization_id == _ASCII_NORMALIZATION_ID:
        return value.lower()
    if normalization_id == _FROZEN_NORMALIZATION_ID:
        return unicodedata.normalize("NFKC", value).casefold()
    raise RuntimeError("frozen tokenizer profile is unavailable")


def _require_text(value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError("tokenizer input must be text")


# This compatibility object is intentionally the explicit ASCII diagnostic
# baseline. Environment-configured experiments remain available only through
# ``build_mail_candidate_admission_tokenizer_profile``; they cannot interfere
# with the packaged Issue #56 target runtime at import time.
DEFAULT_MAIL_CANDIDATE_ADMISSION_TOKENIZER_PROFILE = (
    build_ascii_identifier_regex_tokenizer_profile()
)


__all__ = [
    "ASCII_IDENTIFIER_REGEX_TOKENIZER_ID",
    "DEFAULT_MAIL_CANDIDATE_ADMISSION_TOKENIZER_PROFILE",
    "ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT",
    "JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID",
    "MailCandidateAdmissionTokenization",
    "MailCandidateAdmissionTokenizerProfile",
    "OrderedQueryGroundingAnalysis",
    "OrderedQueryGroundingTerm",
    "ProtectedIdentifierSpan",
    "QueryGroundingGrammarRole",
    "ascii_identifier_regex_tokens",
    "build_ascii_identifier_regex_tokenizer_profile",
    "build_frozen_jieba_sentencepiece_tokenizer_profile",
    "build_mail_candidate_admission_tokenizer_profile",
    "configured_mail_candidate_admission_tokens",
    "configured_mail_tokenizer_id",
    "jieba_sentencepiece_frozen_profile_candidate_admission_tokens",
    "load_default_mail_candidate_admission_tokenizer_profile",
    "load_issue56_target_mail_tokenizer_profile",
]
