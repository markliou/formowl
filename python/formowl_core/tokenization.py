"""Frozen mail candidate-admission tokenizer profiles.

The default profile is created once when this module is imported.  With no
profile configuration it remains the explicitly limited ASCII fallback.  A
Jieba plus SentencePiece profile is admitted only when its model is supplied
and pinned by SHA-256 before process startup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
import unicodedata

ASCII_IDENTIFIER_REGEX_TOKENIZER_ID = "ascii_identifier_regex_v1"
JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID = (
    "jieba_sentencepiece_frozen_profile_candidate_admission_v1"
)

_MODEL_PATH_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL"
_MODEL_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"
_MAX_MODEL_BYTES = 16 * 1024 * 1024
_PROFILE_CONTRACT_ID = "formowl_mail_candidate_admission_profile_v2"
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
        re.compile(r"(?i)\bhttps?://[^\s<>{}\[\]\"']+"),
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
    _jieba_module: Any | None = field(repr=False, compare=False, default=None)
    _sentencepiece_processor: Any | None = field(repr=False, compare=False, default=None)

    def tokenize(self, value: str) -> set[str]:
        """Return candidate-admission tokens under this fixed profile."""

        return set(self.analyze(value).tokens)

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
        }


def build_mail_candidate_admission_tokenizer_profile() -> MailCandidateAdmissionTokenizerProfile:
    """Build one profile from complete process configuration or fail closed."""

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
    )


def build_frozen_jieba_sentencepiece_tokenizer_profile(
    *,
    model_path: str | Path,
    model_sha256: str,
) -> MailCandidateAdmissionTokenizerProfile:
    """Build one explicitly pinned frozen Jieba + SentencePiece profile."""

    configured_path = _configured_value(str(model_path))
    configured_sha256 = _configured_value(model_sha256)
    if configured_path is None or configured_sha256 is None:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    processor = _load_sentencepiece_processor(configured_path, configured_sha256)
    jieba_tokenizer, jieba_version, jieba_dictionary_sha256 = _frozen_jieba_tokenizer()
    sentencepiece_version = _package_version("sentencepiece")
    vocabulary_sha256 = _sentencepiece_vocabulary_sha256(processor)
    payload = _profile_payload(
        tokenizer_id=JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        normalization_id=_FROZEN_NORMALIZATION_ID,
        jieba_version=jieba_version,
        jieba_dictionary_sha256=jieba_dictionary_sha256,
        jieba_user_dictionary_sha256=_sha256_bytes(b""),
        sentencepiece_version=sentencepiece_version,
        model_sha256=configured_sha256,
        sentencepiece_vocabulary_sha256=vocabulary_sha256,
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
        _jieba_module=jieba_tokenizer,
        _sentencepiece_processor=processor,
    )


def ascii_identifier_regex_tokens(value: str) -> set[str]:
    """Tokenize under the process-frozen profile, with honest ASCII fallback."""

    return DEFAULT_MAIL_CANDIDATE_ADMISSION_TOKENIZER_PROFILE.tokenize(value)


def configured_mail_tokenizer_id() -> str:
    """Return the identifier for a newly validated configured profile."""

    return build_mail_candidate_admission_tokenizer_profile().tokenizer_id


def configured_mail_candidate_admission_tokens(value: str) -> set[str]:
    """Tokenize under a newly validated configuration for isolated callers."""

    return build_mail_candidate_admission_tokenizer_profile().tokenize(value)


def jieba_sentencepiece_frozen_profile_candidate_admission_tokens(value: str) -> set[str]:
    """Tokenize only when a complete, pinned frozen profile is configured."""

    profile = build_mail_candidate_admission_tokenizer_profile()
    if profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return profile.tokenize(value)


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
    }


def _profile_fingerprint(payload: dict[str, Any]) -> str:
    return _canonical_sha256(payload)


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def _frozen_jieba_tokenizer() -> tuple[Any, str, str]:
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
    try:
        tokenizer = module.Tokenizer(dictionary=str(dictionary_path))
        tokenizer.initialize()
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    if (
        _regular_file_metadata(dictionary_path, maximum_bytes=32 * 1024 * 1024) != before
        or _sha256(dictionary_path) != dictionary_sha256
    ):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return tokenizer, _package_version("jieba"), dictionary_sha256


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


def _normalize_text(value: str, normalization_id: str) -> str:
    if normalization_id == _ASCII_NORMALIZATION_ID:
        return value.lower()
    if normalization_id == _FROZEN_NORMALIZATION_ID:
        return unicodedata.normalize("NFKC", value).casefold()
    raise RuntimeError("frozen tokenizer profile is unavailable")


def _require_text(value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError("tokenizer input must be text")


# Query and evidence import this single object.  Changes to environment values
# after import cannot silently change their candidate-admission behavior.
DEFAULT_MAIL_CANDIDATE_ADMISSION_TOKENIZER_PROFILE = (
    build_mail_candidate_admission_tokenizer_profile()
)


__all__ = [
    "ASCII_IDENTIFIER_REGEX_TOKENIZER_ID",
    "DEFAULT_MAIL_CANDIDATE_ADMISSION_TOKENIZER_PROFILE",
    "JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID",
    "MailCandidateAdmissionTokenization",
    "MailCandidateAdmissionTokenizerProfile",
    "ProtectedIdentifierSpan",
    "ascii_identifier_regex_tokens",
    "build_ascii_identifier_regex_tokenizer_profile",
    "build_frozen_jieba_sentencepiece_tokenizer_profile",
    "build_mail_candidate_admission_tokenizer_profile",
    "configured_mail_candidate_admission_tokens",
    "configured_mail_tokenizer_id",
    "jieba_sentencepiece_frozen_profile_candidate_admission_tokens",
]
