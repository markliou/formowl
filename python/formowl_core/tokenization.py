"""Shared mail tokenization with an explicit frozen-profile POC boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import importlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
from typing import Any

ASCII_IDENTIFIER_REGEX_TOKENIZER_ID = "ascii_identifier_regex_v1"
JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID = (
    "jieba_sentencepiece_frozen_profile_candidate_admission_v1"
)

_MODEL_PATH_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL"
_MODEL_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"
_PROFILE_PACKAGE_ENV = "FORMOWL_MAIL_TOKENIZER_PROFILE_PACKAGE"
_TRAINING_CORPUS_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_TRAINING_CORPUS_SHA256"
_TOKENIZER_MODE_ENV = "FORMOWL_MAIL_TOKENIZER_MODE"
_FROZEN_MODE = "jieba_sentencepiece_frozen"
_LEGACY_ASCII_TEST_MODE = "legacy_ascii_test"
_CANDIDATE_ADMISSION_POLICY_ID = "frozen_profile_candidate_admission_v1"
_SEGMENTATION_POLICY_ID = "jieba_sentencepiece_process_frozen_v1"
_PROFILE_PACKAGE_ARTIFACT_ID = "formowl_mail_tokenizer_profile_package_v1"
_PROFILE_PACKAGE_DIRECTORY_PREFIX = "sha256-"
_PROFILE_PACKAGE_MANIFEST_NAME = "manifest.json"
_PROFILE_PACKAGE_KEYS = frozenset(
    {
        "artifact_id",
        "candidate_admission_policy_id",
        "model_path",
        "model_sha256",
        "profile_schema_id",
        "segmentation_policy_id",
        "tokenizer_id",
        "training_corpus_sha256",
    }
)
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_MODEL_BYTES = 16 * 1024 * 1024
_PROFILE_SCHEMA_ID = "formowl_mail_process_frozen_tokenizer_profile_v1"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
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
    package_fingerprint: str | None
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
    package_path = os.environ.get(_PROFILE_PACKAGE_ENV)
    if package_path is not None and mode == _LEGACY_ASCII_TEST_MODE:
        raise RuntimeError("frozen tokenizer profile is unavailable")
    if mode == _LEGACY_ASCII_TEST_MODE:
        return _profile(
            tokenizer_id=ASCII_IDENTIFIER_REGEX_TOKENIZER_ID,
            package_fingerprint=None,
            model_path=None,
            model_sha256=None,
            training_corpus_sha256=None,
        )
    if package_path is not None:
        if any(
            name in os.environ
            for name in (
                _MODEL_PATH_ENV,
                _MODEL_SHA256_ENV,
                _TRAINING_CORPUS_SHA256_ENV,
            )
        ):
            raise RuntimeError("frozen tokenizer profile is unavailable")
        return load_mail_tokenizer_profile_package(package_path)
    model_path = os.environ.get(_MODEL_PATH_ENV)
    model_sha256 = os.environ.get(_MODEL_SHA256_ENV)
    training_corpus_sha256 = os.environ.get(_TRAINING_CORPUS_SHA256_ENV)
    processor = _configured_sentencepiece_processor(model_path, model_sha256)
    if not training_corpus_sha256 or not _SHA256.fullmatch(training_corpus_sha256):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    jieba_module = _jieba_module()
    return _profile(
        tokenizer_id=JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        package_fingerprint=None,
        model_path=model_path,
        model_sha256=model_sha256,
        training_corpus_sha256=training_corpus_sha256,
        sentencepiece_processor=processor,
        jieba_module=jieba_module,
    )


def load_mail_tokenizer_profile_package(
    package_path: str | os.PathLike[str],
) -> MailTokenizerProfile:
    """Load one canonical, content-bound tokenizer package from an explicit path."""

    try:
        root = Path(package_path)
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("tokenizer package path must be absolute")
        _reject_symlink_ancestry(root)
        root_before = root.lstat()
        if stat.S_ISLNK(root_before.st_mode) or not stat.S_ISDIR(root_before.st_mode):
            raise OSError("tokenizer package root is unsafe")

        manifest_bytes = _read_stable_regular_file_bytes(
            root / _PROFILE_PACKAGE_MANIFEST_NAME,
            max_bytes=_MAX_MANIFEST_BYTES,
        )
        manifest = _load_profile_package_manifest(manifest_bytes)
        package_fingerprint = _sha256_bytes(manifest_bytes)
        if root.name != (
            _PROFILE_PACKAGE_DIRECTORY_PREFIX + package_fingerprint.removeprefix("sha256:")
        ):
            raise ValueError("tokenizer package identity is invalid")
        model_relative = _profile_package_model_path(manifest["model_path"])
        if {entry.name for entry in root.iterdir()} != {
            _PROFILE_PACKAGE_MANIFEST_NAME,
            model_relative.name,
        }:
            raise ValueError("tokenizer package contents are invalid")
        model_path = root / model_relative
        model_bytes = _read_stable_regular_file_bytes(
            model_path,
            max_bytes=_MAX_MODEL_BYTES,
        )
        if _sha256_bytes(model_bytes) != manifest["model_sha256"]:
            raise ValueError("tokenizer package model hash mismatch")

        root_after = root.lstat()
        if _stable_file_identity(root_after) != _stable_file_identity(root_before):
            raise OSError("tokenizer package root changed while loading")

        processor = _sentencepiece_processor_from_model_bytes(model_bytes)
        jieba_module = _jieba_module()
        return _profile(
            tokenizer_id=manifest["tokenizer_id"],
            package_fingerprint=package_fingerprint,
            model_path=str(model_path),
            model_sha256=manifest["model_sha256"],
            training_corpus_sha256=manifest["training_corpus_sha256"],
            sentencepiece_processor=processor,
            jieba_module=jieba_module,
        )
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc


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
    package_fingerprint: str | None,
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
    if package_fingerprint is not None:
        payload.update(
            {
                "candidate_admission_policy_id": _CANDIDATE_ADMISSION_POLICY_ID,
                "package_artifact_id": _PROFILE_PACKAGE_ARTIFACT_ID,
                "package_fingerprint": package_fingerprint,
                "segmentation_policy_id": _SEGMENTATION_POLICY_ID,
            }
        )
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return MailTokenizerProfile(
        tokenizer_id=tokenizer_id,
        profile_fingerprint="sha256:" + hashlib.sha256(encoded).hexdigest(),
        package_fingerprint=package_fingerprint,
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
    if not _SHA256.fullmatch(expected_sha256):
        raise RuntimeError("frozen tokenizer profile is unavailable")
    try:
        model_bytes = _read_stable_regular_file_bytes(
            Path(model_path),
            max_bytes=_MAX_MODEL_BYTES,
        )
        if _sha256_bytes(model_bytes) != expected_sha256:
            raise ValueError("tokenizer model hash mismatch")
        return _sentencepiece_processor_from_model_bytes(model_bytes)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc


def _load_profile_package_manifest(manifest_bytes: bytes) -> dict[str, str]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("tokenizer package manifest has duplicate keys")
            result[key] = value
        return result

    payload = json.loads(
        manifest_bytes.decode("utf-8", "strict"),
        object_pairs_hook=unique_object,
    )
    if not isinstance(payload, dict) or set(payload) != _PROFILE_PACKAGE_KEYS:
        raise ValueError("tokenizer package manifest fields are invalid")
    if any(type(value) is not str or not value for value in payload.values()):
        raise ValueError("tokenizer package manifest values are invalid")
    expected_identity = {
        "artifact_id": _PROFILE_PACKAGE_ARTIFACT_ID,
        "candidate_admission_policy_id": _CANDIDATE_ADMISSION_POLICY_ID,
        "profile_schema_id": _PROFILE_SCHEMA_ID,
        "segmentation_policy_id": _SEGMENTATION_POLICY_ID,
        "tokenizer_id": JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    }
    if any(payload[key] != value for key, value in expected_identity.items()):
        raise ValueError("tokenizer package identity is invalid")
    if not _SHA256.fullmatch(payload["model_sha256"]) or not _SHA256.fullmatch(
        payload["training_corpus_sha256"]
    ):
        raise ValueError("tokenizer package hashes are invalid")
    if manifest_bytes != _canonical_json_bytes(payload):
        raise ValueError("tokenizer package manifest is not canonical")
    return {key: str(value) for key, value in payload.items()}


def _profile_package_model_path(value: str) -> Path:
    if "\\" in value:
        raise ValueError("tokenizer package model path is invalid")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.parts[0] in {"", ".", "..", _PROFILE_PACKAGE_MANIFEST_NAME}
    ):
        raise ValueError("tokenizer package model path is invalid")
    return Path(candidate.parts[0])


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _read_stable_regular_file_bytes(path: Path, *, max_bytes: int) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or not 1 <= before.st_size <= max_bytes
        ):
            raise OSError("unsafe tokenizer package file")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _stable_file_identity(
            opened
        ) != _stable_file_identity(before):
            raise OSError("tokenizer package file changed while opening")
        payload = bytearray()
        while chunk := os.read(descriptor, 1024 * 1024):
            payload.extend(chunk)
            if len(payload) > max_bytes:
                raise OSError("tokenizer package file exceeds size limit")
        after = os.fstat(descriptor)
        path_after = path.lstat()
        if (
            len(payload) != opened.st_size
            or _stable_file_identity(after) != _stable_file_identity(opened)
            or _stable_file_identity(path_after) != _stable_file_identity(opened)
        ):
            raise OSError("tokenizer package file changed while reading")
        return bytes(payload)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _stable_file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _reject_symlink_ancestry(path: Path) -> None:
    for parent in path.parents:
        metadata = parent.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError("tokenizer package ancestry is unsafe")


def _sentencepiece_processor_from_model_bytes(model_bytes: bytes) -> Any:
    try:
        sentencepiece = importlib.import_module("sentencepiece")
        try:
            return sentencepiece.SentencePieceProcessor(model_proto=model_bytes)
        except TypeError:
            processor = sentencepiece.SentencePieceProcessor()
            if not processor.LoadFromSerializedProto(model_bytes):
                raise RuntimeError("frozen tokenizer profile is unavailable")
            return processor
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError("frozen tokenizer profile is unavailable") from exc


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


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
    "load_mail_tokenizer_profile_package",
    "validate_configured_mail_tokenizer",
]
