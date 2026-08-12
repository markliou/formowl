"""Shared mail tokenization with an explicit frozen-profile POC boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

ASCII_IDENTIFIER_REGEX_TOKENIZER_ID = "ascii_identifier_regex_v1"
JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID = (
    "jieba_sentencepiece_frozen_profile_candidate_admission_v1"
)

_MODEL_PATH_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL"
_MODEL_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"
_TRAINING_CORPUS_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_TRAINING_CORPUS_SHA256"
_TOKENIZER_MODE_ENV = "FORMOWL_MAIL_TOKENIZER_MODE"
_FROZEN_MODE = "jieba_sentencepiece_frozen"
_LEGACY_ASCII_TEST_MODE = "legacy_ascii_test"
_MAX_MODEL_BYTES = 16 * 1024 * 1024
_PROFILE_SCHEMA_ID = "formowl_mail_process_frozen_tokenizer_profile_v1"
_ASCII_IDENTIFIER_SEPARATOR = re.compile(r"[^a-zA-Z0-9_@.-]+")
_ASCII_TOKEN = re.compile(r"[a-zA-Z0-9_@.-]+")
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


@dataclass(frozen=True)
class MailTokenizerProfile:
    """The immutable tokenizer configuration bound to one runtime process."""

    tokenizer_id: str
    profile_fingerprint: str
    model_path: str | None
    model_sha256: str | None
    training_corpus_sha256: str | None
    _sentencepiece_processor: Any | None = field(
        repr=False,
        compare=False,
        default=None,
    )
    _jieba_module: Any | None = field(
        repr=False,
        compare=False,
        default=None,
    )

    def tokenize(self, value: str) -> set[str]:
        if self.tokenizer_id == ASCII_IDENTIFIER_REGEX_TOKENIZER_ID:
            return ascii_identifier_regex_tokens(value)
        if self._sentencepiece_processor is None or self._jieba_module is None:
            raise RuntimeError("frozen tokenizer profile is unavailable")
        return _frozen_profile_tokens(
            value,
            processor=self._sentencepiece_processor,
            jieba_module=self._jieba_module,
        )


def ascii_identifier_regex_tokens(value: str) -> set[str]:
    """Return the legacy ASCII identifier-like tokens."""

    _require_text(value)
    return {token for token in _ASCII_IDENTIFIER_SEPARATOR.split(value.lower()) if token}


@lru_cache(maxsize=1)
def configured_mail_tokenizer_profile() -> MailTokenizerProfile:
    """Validate and freeze the tokenizer profile for this process."""

    mode = _configured_tokenizer_mode()
    if mode == _LEGACY_ASCII_TEST_MODE:
        return _profile(
            tokenizer_id=ASCII_IDENTIFIER_REGEX_TOKENIZER_ID,
            model_path=None,
            model_sha256=None,
            training_corpus_sha256=None,
        )
    model_path = os.environ.get(_MODEL_PATH_ENV)
    model_sha256 = os.environ.get(_MODEL_SHA256_ENV)
    training_corpus_sha256 = os.environ.get(_TRAINING_CORPUS_SHA256_ENV)
    processor = _configured_sentencepiece_processor(model_path, model_sha256)
    if not training_corpus_sha256 or not re.fullmatch(
        r"sha256:[0-9a-f]{64}",
        training_corpus_sha256,
    ):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    jieba_module = _jieba_module()
    return _profile(
        tokenizer_id=JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        model_path=model_path,
        model_sha256=model_sha256,
        training_corpus_sha256=training_corpus_sha256,
        sentencepiece_processor=processor,
        jieba_module=jieba_module,
    )


def configured_mail_tokenizer_id() -> str:
    """Return the tokenizer profile actually bound to this process."""

    return configured_mail_tokenizer_profile().tokenizer_id


def configured_mail_candidate_admission_tokens(value: str) -> set[str]:
    """Tokenize with the immutable profile bound to this process."""

    return configured_mail_tokenizer_profile().tokenize(value)


def validate_configured_mail_tokenizer() -> str:
    """Fail closed unless the selected tokenizer profile is fully usable."""

    return configured_mail_tokenizer_id()


def jieba_sentencepiece_frozen_profile_candidate_admission_tokens(
    value: str,
) -> set[str]:
    """Return admitted tokens from the configured frozen Jieba+SentencePiece profile."""

    profile = configured_mail_tokenizer_profile()
    if profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return profile.tokenize(value)


def _frozen_profile_tokens(
    value: str,
    *,
    processor: Any,
    jieba_module: Any,
) -> set[str]:
    _require_text(value)

    admitted = ascii_identifier_regex_tokens(value)
    for piece in jieba_module.cut(value, cut_all=False):
        admitted.update(_admitted_piece_tokens(piece))
    try:
        sentencepiece_pieces = processor.encode(value, out_type=str)
    except TypeError:
        sentencepiece_pieces = processor.EncodeAsPieces(value)
    for piece in sentencepiece_pieces:
        admitted.update(_admitted_piece_tokens(str(piece).replace("\u2581", "")))
    return admitted


def _profile(
    *,
    tokenizer_id: str,
    model_path: str | None,
    model_sha256: str | None,
    training_corpus_sha256: str | None,
    sentencepiece_processor: Any | None = None,
    jieba_module: Any | None = None,
) -> MailTokenizerProfile:
    payload = {
        "profile_schema_id": _PROFILE_SCHEMA_ID,
        "tokenizer_id": tokenizer_id,
        "model_sha256": model_sha256,
        "training_corpus_sha256": training_corpus_sha256,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return MailTokenizerProfile(
        tokenizer_id=tokenizer_id,
        profile_fingerprint="sha256:" + hashlib.sha256(encoded).hexdigest(),
        model_path=model_path,
        model_sha256=model_sha256,
        training_corpus_sha256=training_corpus_sha256,
        _sentencepiece_processor=sentencepiece_processor,
        _jieba_module=jieba_module,
    )


def _admitted_piece_tokens(value: Any) -> set[str]:
    normalized = _TOKEN_EDGE.sub("", str(value).strip().lower())
    if not normalized or normalized in _STOPWORDS or normalized in {"<unk>", "<s>", "</s>"}:
        return set()
    if _CJK_CHARACTER.search(normalized):
        return _admitted_cjk_tokens(normalized)
    # Protected ASCII identifiers are admitted once by
    # ``ascii_identifier_regex_tokens``. SentencePiece fragments such as
    # ``47000`` or ``g301`` must not create additional broad match keys.
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


def _configured_tokenizer_mode() -> str:
    raw_mode = os.environ.get(_TOKENIZER_MODE_ENV, _FROZEN_MODE)
    if not isinstance(raw_mode, str):
        raise RuntimeError("mail tokenizer mode is invalid")
    mode = raw_mode.strip()
    if mode not in {_FROZEN_MODE, _LEGACY_ASCII_TEST_MODE}:
        raise RuntimeError("mail tokenizer mode is invalid")
    return mode


@lru_cache(maxsize=1)
def _jieba_module() -> Any:
    try:
        module = importlib.import_module("jieba")
    except ImportError as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    set_log_level = getattr(module, "setLogLevel", None)
    if callable(set_log_level):
        set_log_level(30)
    return module


def _configured_sentencepiece_processor(
    model_path: str | None,
    expected_sha256: str | None,
) -> Any:
    if not model_path or not expected_sha256:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    return _load_sentencepiece_processor(model_path, expected_sha256)


@lru_cache(maxsize=4)
def _load_sentencepiece_processor(model_path: str, expected_sha256: str) -> Any:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_sha256):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    path = Path(model_path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    if metadata.st_size <= 0 or metadata.st_size > _MAX_MODEL_BYTES:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    if _sha256(path) != expected_sha256:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    try:
        sentencepiece = importlib.import_module("sentencepiece")
        try:
            return sentencepiece.SentencePieceProcessor(model_file=str(path))
        except TypeError:
            processor = sentencepiece.SentencePieceProcessor()
            if not processor.Load(str(path)):
                raise RuntimeError("frozen tokenizer profile is unavailable")
            return processor
    except (ImportError, OSError, RuntimeError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _require_text(value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError("tokenizer input must be text")


__all__ = [
    "ASCII_IDENTIFIER_REGEX_TOKENIZER_ID",
    "JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID",
    "MailTokenizerProfile",
    "ascii_identifier_regex_tokens",
    "configured_mail_candidate_admission_tokens",
    "configured_mail_tokenizer_id",
    "configured_mail_tokenizer_profile",
    "jieba_sentencepiece_frozen_profile_candidate_admission_tokens",
    "validate_configured_mail_tokenizer",
]
