from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_core.tokenization import (
    ASCII_IDENTIFIER_REGEX_TOKENIZER_ID,
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    build_mail_candidate_admission_tokenizer_profile,
    load_issue56_target_mail_tokenizer_profile,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL"
MODEL_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"


class RuntimeMailTokenizationPocTests(unittest.TestCase):
    def test_unconfigured_profile_keeps_explicit_ascii_fallback(self) -> None:
        with _profile_environment(None, None):
            profile = build_mail_candidate_admission_tokenizer_profile()

        self.assertEqual(profile.tokenizer_id, ASCII_IDENTIFIER_REGEX_TOKENIZER_ID)
        self.assertRegex(profile.profile_fingerprint, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            profile.tokenize("我要 PO470002002 的交期，料號是 03.80503G301"),
            {"po470002002", "03.80503g301"},
        )

    def test_packaged_target_loader_is_independent_of_legacy_environment(self) -> None:
        with _profile_environment(None, None):
            profile = load_issue56_target_mail_tokenizer_profile()

        self.assertEqual(
            profile.tokenizer_id,
            JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        )
        self.assertRegex(profile.profile_fingerprint, r"^sha256:[0-9a-f]{64}$")
        self.assertIsNotNone(profile.artifact_manifest_sha256)
        self.assertIsNotNone(profile.calibration_corpus_sha256)
        self.assertIsNotNone(profile.sentencepiece_vocabulary_artifact_sha256)
        self.assertTrue(
            {
                "zx-2048-alpha",
                "owner42@example.test",
                "2026-09-30",
                "https://example.test/cases/zx-2048-alpha",
                "交期",
                "採購單",
            }.issubset(
                profile.tokenize(
                    "採購單 ZX-2048-ALPHA 的交期由 owner42@example.test 更新，"
                    "截止 2026-09-30，詳見 "
                    "https://example.test/cases/ZX-2048-ALPHA。"
                )
            )
        )

    def test_partial_or_unpinned_profile_fails_closed(self) -> None:
        with _profile_environment("/tmp/not-used.model", None):
            with self.assertRaisesRegex(
                RuntimeError,
                "^frozen tokenizer profile is unavailable$",
            ):
                build_mail_candidate_admission_tokenizer_profile()
        with _profile_environment("/tmp/not-used.model", "sha256:not-a-valid-pin"):
            with self.assertRaisesRegex(
                RuntimeError,
                "^frozen tokenizer profile is unavailable$",
            ):
                build_mail_candidate_admission_tokenizer_profile()

    def test_legacy_environment_cannot_replace_packaged_runtime_target(self) -> None:
        environment = {
            **os.environ,
            MODEL_PATH_ENV: "/tmp/not-used.model",
            "PYTHONPATH": str(ROOT / "python"),
        }
        environment.pop(MODEL_SHA256_ENV, None)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from formowl_mail import evidence, query\n"
                    "print(query.MAIL_TOKENIZER_ID)\n"
                    "print(evidence.MAIL_TOKENIZER_ID)\n"
                ),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            completed.stdout.splitlines(),
            [JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID] * 2,
        )
        self.assertNotIn("/tmp/not-used.model", completed.stderr)

    def test_frozen_profile_preserves_identifiers_and_admits_cjk_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path, model_sha256 = _train_safe_sentencepiece_model(Path(temp_dir))
            with _profile_environment(str(model_path), model_sha256):
                profile = build_mail_candidate_admission_tokenizer_profile()
                tokens = profile.tokenize("我要 PO470002002 的交期；03.80503G301 的 COO 或產地嗎")

        self.assertEqual(
            profile.tokenizer_id,
            JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        )
        self.assertEqual(profile.model_sha256, model_sha256)
        self.assertRegex(profile.profile_fingerprint, r"^sha256:[0-9a-f]{64}$")
        self.assertTrue({"po470002002", "03.80503g301", "coo", "交期", "產地"}.issubset(tokens))
        self.assertTrue({"47000", "g301", "002", "03."}.isdisjoint(tokens), tokens)

    def test_query_and_evidence_share_one_frozen_profile_for_process_lifetime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path, model_sha256 = _train_safe_sentencepiece_model(Path(temp_dir))
            environment = {
                **os.environ,
                MODEL_PATH_ENV: str(model_path),
                MODEL_SHA256_ENV: model_sha256,
                "PYTHONPATH": str(ROOT / "python"),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json, os\n"
                        "from formowl_mail import evidence, query\n"
                        "value = 'PO470002002 的交期與 03.80503G301 的產地'\n"
                        "initial = {\n"
                        "  'query_id': query.MAIL_TOKENIZER_ID,\n"
                        "  'evidence_id': evidence.MAIL_TOKENIZER_ID,\n"
                        "  'query_fingerprint': query.MAIL_TOKENIZER_PROFILE_FINGERPRINT,\n"
                        "  'evidence_fingerprint': evidence.MAIL_TOKENIZER_PROFILE_FINGERPRINT,\n"
                        "  'query_tokens': sorted(query._tokenize(value)),\n"
                        "  'evidence_tokens': sorted(evidence._tokenize(value)),\n"
                        "}\n"
                        "os.environ.pop('FORMOWL_MAIL_SENTENCEPIECE_MODEL')\n"
                        "os.environ.pop('FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256')\n"
                        "initial['after_env_change'] = sorted(query._tokenize(value))\n"
                        "print(json.dumps(initial, ensure_ascii=False))\n"
                    ),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)

        self.assertEqual(
            payload["query_id"],
            JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        )
        self.assertEqual(payload["evidence_id"], payload["query_id"])
        self.assertEqual(payload["evidence_fingerprint"], payload["query_fingerprint"])
        self.assertRegex(payload["query_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(payload["query_tokens"], payload["evidence_tokens"])
        self.assertEqual(payload["after_env_change"], payload["query_tokens"])
        self.assertTrue(
            {
                "po470002002",
                "03.80503g301",
                "交期",
                "產地",
            }.issubset(payload["query_tokens"])
        )


class _profile_environment:
    def __init__(self, model_path: str | None, model_sha256: str | None) -> None:
        values = {}
        if model_path is not None:
            values[MODEL_PATH_ENV] = model_path
        if model_sha256 is not None:
            values[MODEL_SHA256_ENV] = model_sha256
        self._patcher = patch.dict(os.environ, values, clear=False)
        self._remove = {
            name
            for name, value in (
                (MODEL_PATH_ENV, model_path),
                (MODEL_SHA256_ENV, model_sha256),
            )
            if value is None
        }

    def __enter__(self) -> None:
        self._patcher.start()
        for name in self._remove:
            os.environ.pop(name, None)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._patcher.stop()


def _train_safe_sentencepiece_model(temp_dir: Path) -> tuple[Path, str]:
    try:
        import sentencepiece
    except ImportError as exc:  # pragma: no cover - canonical image supplies this
        raise unittest.SkipTest("sentencepiece is unavailable") from exc
    try:
        import jieba  # noqa: F401
    except ImportError as exc:  # pragma: no cover - canonical image supplies this
        raise unittest.SkipTest("jieba is unavailable") from exc

    corpus_path = temp_dir / "tokenizer-poc-corpus.txt"
    corpus_path.write_text(
        "\n".join(
            [
                "PO470002002 的目前交期與最新交貨日期",
                "03.80503G301 的 COO 與原產地資料",
                "請提供供應商承諾、截止期限與目前阻礙",
                "supplier@example.test 提供最新狀態",
            ]
            * 20
        )
        + "\n",
        encoding="utf-8",
    )
    model_prefix = temp_dir / "tokenizer-poc"
    sentencepiece.SentencePieceTrainer.Train(
        input=str(corpus_path),
        model_prefix=str(model_prefix),
        vocab_size=128,
        model_type="bpe",
        character_coverage=1.0,
        hard_vocab_limit=False,
        shuffle_input_sentence=False,
        num_threads=1,
        minloglevel=2,
        user_defined_symbols=[
            "PO470002002",
            "03.80503G301",
            "supplier@example.test",
        ],
    )
    model_path = model_prefix.with_suffix(".model")
    model_sha256 = "sha256:" + hashlib.sha256(model_path.read_bytes()).hexdigest()
    return model_path, model_sha256


if __name__ == "__main__":
    unittest.main()
