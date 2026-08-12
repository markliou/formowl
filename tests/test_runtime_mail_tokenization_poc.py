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
    ascii_identifier_regex_tokens,
    configured_mail_tokenizer_profile,
    configured_mail_tokenizer_id,
    jieba_sentencepiece_frozen_profile_candidate_admission_tokens,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL"
MODEL_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"
PROFILE_PACKAGE_ENV = "FORMOWL_MAIL_TOKENIZER_PROFILE_PACKAGE"
TOKENIZER_MODE_ENV = "FORMOWL_MAIL_TOKENIZER_MODE"
TRAINING_CORPUS_SHA256_ENV = "FORMOWL_MAIL_SENTENCEPIECE_TRAINING_CORPUS_SHA256"
FROZEN_MODE = "jieba_sentencepiece_frozen"
LEGACY_ASCII_TEST_MODE = "legacy_ascii_test"
PACKAGE_ARTIFACT_ID = "formowl_mail_tokenizer_profile_package_v1"
PROFILE_SCHEMA_ID = "formowl_mail_process_frozen_tokenizer_profile_v1"
SEGMENTATION_POLICY_ID = "jieba_sentencepiece_process_frozen_v1"
CANDIDATE_ADMISSION_POLICY_ID = "frozen_profile_candidate_admission_v1"


class RuntimeMailTokenizationPocTests(unittest.TestCase):
    def setUp(self) -> None:
        self._package_environment_value = os.environ.pop(PROFILE_PACKAGE_ENV, None)
        configured_mail_tokenizer_profile.cache_clear()

    def tearDown(self) -> None:
        if self._package_environment_value is not None:
            os.environ[PROFILE_PACKAGE_ENV] = self._package_environment_value
        else:
            os.environ.pop(PROFILE_PACKAGE_ENV, None)
        configured_mail_tokenizer_profile.cache_clear()

    def test_unconfigured_runtime_requires_frozen_profile(self) -> None:
        with patch.dict(
            os.environ,
            {
                MODEL_PATH_ENV: "",
                MODEL_SHA256_ENV: "",
                TOKENIZER_MODE_ENV: FROZEN_MODE,
            },
            clear=False,
        ):
            os.environ.pop(MODEL_PATH_ENV, None)
            os.environ.pop(MODEL_SHA256_ENV, None)
            os.environ.pop(PROFILE_PACKAGE_ENV, None)
            os.environ.pop(TRAINING_CORPUS_SHA256_ENV, None)
            configured_mail_tokenizer_profile.cache_clear()
            with self.assertRaisesRegex(
                RuntimeError,
                "^frozen tokenizer profile is unavailable$",
            ):
                configured_mail_tokenizer_id()

    def test_ascii_tokenizer_requires_explicit_legacy_test_mode(self) -> None:
        with patch.dict(
            os.environ,
            {
                TOKENIZER_MODE_ENV: LEGACY_ASCII_TEST_MODE,
            },
            clear=False,
        ):
            os.environ.pop(MODEL_PATH_ENV, None)
            os.environ.pop(MODEL_SHA256_ENV, None)
            os.environ.pop(PROFILE_PACKAGE_ENV, None)
            os.environ.pop(TRAINING_CORPUS_SHA256_ENV, None)
            configured_mail_tokenizer_profile.cache_clear()
            self.assertEqual(configured_mail_tokenizer_id(), ASCII_IDENTIFIER_REGEX_TOKENIZER_ID)
            self.assertEqual(
                ascii_identifier_regex_tokens("我要 PO470002002 的交期，料號是 03.80503G301"),
                {"po470002002", "03.80503g301"},
            )

    def test_partial_or_unpinned_profile_fails_closed(self) -> None:
        with patch.dict(
            os.environ,
            {
                MODEL_PATH_ENV: "/tmp/not-used.model",
                TOKENIZER_MODE_ENV: FROZEN_MODE,
            },
            clear=False,
        ):
            os.environ.pop(MODEL_SHA256_ENV, None)
            os.environ.pop(PROFILE_PACKAGE_ENV, None)
            os.environ.pop(TRAINING_CORPUS_SHA256_ENV, None)
            configured_mail_tokenizer_profile.cache_clear()
            with self.assertRaisesRegex(
                RuntimeError,
                "^frozen tokenizer profile is unavailable$",
            ):
                configured_mail_tokenizer_id()

    def test_frozen_profile_preserves_identifiers_and_admits_cjk_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path, model_sha256 = _train_safe_sentencepiece_model(Path(temp_dir))
            with _frozen_profile_environment(
                model_path,
                model_sha256,
                _sha256_text("safe tokenizer test corpus"),
            ):
                self.assertEqual(
                    configured_mail_tokenizer_id(),
                    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
                )
                tokens = jieba_sentencepiece_frozen_profile_candidate_admission_tokens(
                    "我要 PO470002002 的交期；03.80503G301 的 COO 或產地嗎"
                )

            self.assertTrue({"po470002002", "03.80503g301", "coo", "交期", "產地"}.issubset(tokens))
            self.assertTrue(
                {"47000", "g301", "002", "03."}.isdisjoint(tokens),
                tokens,
            )

    def test_query_and_evidence_runtime_use_the_same_frozen_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path, model_sha256 = _train_safe_sentencepiece_model(Path(temp_dir))
            training_corpus_sha256 = _sha256_text("safe tokenizer test corpus")
            environment = {
                **os.environ,
                TOKENIZER_MODE_ENV: FROZEN_MODE,
                MODEL_PATH_ENV: str(model_path),
                MODEL_SHA256_ENV: model_sha256,
                TRAINING_CORPUS_SHA256_ENV: training_corpus_sha256,
                "PYTHONPATH": str(ROOT / "python"),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json\n"
                        "import sys\n"
                        "from pathlib import Path\n"
                        "from formowl_mail import evidence, query\n"
                        "sys.path.insert(0, str(Path.cwd() / 'scripts'))\n"
                        "import mail_full_pst_domain_hard_kg_fusion_eval as kg_eval\n"
                        "_, kg_runtime = kg_eval._apply_default_lexical_candidate_policy([])\n"
                        "value = 'PO470002002 的交期與 03.80503G301 的產地'\n"
                        "print(json.dumps({\n"
                        "  'query_id': query.MAIL_TOKENIZER_ID,\n"
                        "  'evidence_id': evidence.MAIL_TOKENIZER_ID,\n"
                        "  'kg_id': kg_eval.MAIL_TOKENIZER_ID,\n"
                        "  'query_fingerprint': query.MAIL_TOKENIZER_PROFILE_FINGERPRINT,\n"
                        "  'evidence_fingerprint': evidence.MAIL_TOKENIZER_PROFILE_FINGERPRINT,\n"
                        "  'kg_fingerprint': kg_eval.MAIL_TOKENIZER_PROFILE_FINGERPRINT,\n"
                        "  'kg_binding_fingerprint': kg_runtime.binding.candidate_admission_policy_hash,\n"
                        "  'kg_binding_model_sha256': kg_runtime.binding.sentencepiece_model_hash,\n"
                        "  'kg_binding_corpus_sha256': kg_runtime.binding.sentencepiece_training_corpus_hash,\n"
                        "  'query_tokens': sorted(query._tokenize(value)),\n"
                        "  'evidence_tokens': sorted(evidence._tokenize(value)),\n"
                        "  'kg_tokens': sorted(kg_eval._tokenize(value)),\n"
                        "}, ensure_ascii=False))\n"
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
        self.assertEqual(payload["kg_id"], payload["query_id"])
        self.assertEqual(payload["evidence_fingerprint"], payload["query_fingerprint"])
        self.assertEqual(payload["kg_fingerprint"], payload["query_fingerprint"])
        self.assertEqual(payload["kg_binding_fingerprint"], payload["query_fingerprint"])
        self.assertEqual(payload["kg_binding_model_sha256"], model_sha256)
        self.assertEqual(payload["kg_binding_corpus_sha256"], training_corpus_sha256)
        self.assertEqual(payload["query_tokens"], payload["evidence_tokens"])
        self.assertEqual(payload["kg_tokens"], payload["query_tokens"])
        self.assertTrue(
            {
                "po470002002",
                "03.80503g301",
                "交期",
                "產地",
            }.issubset(payload["query_tokens"])
        )

    def test_frozen_profile_fingerprint_is_stable_across_fresh_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path, model_sha256 = _train_safe_sentencepiece_model(Path(temp_dir))
            environment = {
                **os.environ,
                TOKENIZER_MODE_ENV: FROZEN_MODE,
                MODEL_PATH_ENV: str(model_path),
                MODEL_SHA256_ENV: model_sha256,
                TRAINING_CORPUS_SHA256_ENV: _sha256_text("safe tokenizer test corpus"),
                "PYTHONPATH": str(ROOT / "python"),
            }
            command = [
                sys.executable,
                "-c",
                (
                    "from formowl_core.tokenization import configured_mail_tokenizer_profile\n"
                    "print(configured_mail_tokenizer_profile().profile_fingerprint)\n"
                ),
            ]
            fingerprints = [
                subprocess.run(
                    command,
                    cwd=ROOT,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                for _ in range(2)
            ]

        self.assertEqual(fingerprints[0], fingerprints[1])
        self.assertRegex(fingerprints[0], r"^sha256:[0-9a-f]{64}$")

    def test_process_frozen_profile_ignores_later_environment_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path, model_sha256 = _train_safe_sentencepiece_model(Path(temp_dir))
            environment = {
                **os.environ,
                TOKENIZER_MODE_ENV: FROZEN_MODE,
                MODEL_PATH_ENV: str(model_path),
                MODEL_SHA256_ENV: model_sha256,
                TRAINING_CORPUS_SHA256_ENV: _sha256_text("safe tokenizer test corpus"),
                "PYTHONPATH": str(ROOT / "python"),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json, os\n"
                        "from formowl_core.tokenization import configured_mail_tokenizer_profile\n"
                        "profile = configured_mail_tokenizer_profile()\n"
                        "before = sorted(profile.tokenize('PO470002002 的交期與產地'))\n"
                        "os.environ['FORMOWL_MAIL_SENTENCEPIECE_MODEL'] = '/unavailable.model'\n"
                        "os.environ['FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256'] = 'sha256:' + '0' * 64\n"
                        "os.environ['FORMOWL_MAIL_SENTENCEPIECE_TRAINING_CORPUS_SHA256'] = 'sha256:' + '1' * 64\n"
                        "after_profile = configured_mail_tokenizer_profile()\n"
                        "print(json.dumps({\n"
                        "  'same_object': profile is after_profile,\n"
                        "  'same_fingerprint': profile.profile_fingerprint == after_profile.profile_fingerprint,\n"
                        "  'same_tokens': before == sorted(after_profile.tokenize('PO470002002 的交期與產地')),\n"
                        "}))\n"
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
            payload,
            {
                "same_object": True,
                "same_fingerprint": True,
                "same_tokens": True,
            },
        )

    def test_explicit_package_is_stable_across_paths_and_fresh_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path, model_sha256 = _train_safe_sentencepiece_model(root / "training")
            training_corpus_sha256 = _sha256_text("approved safe test corpus identity")
            first_package = _write_profile_package(
                root / "first",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=training_corpus_sha256,
            )
            second_package = _write_profile_package(
                root / "second",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=training_corpus_sha256,
            )
            first = _run_package_profile_probe(first_package)
            second = _run_package_profile_probe(second_package)

        self.assertEqual(first["package_fingerprint"], second["package_fingerprint"])
        self.assertEqual(first["profile_fingerprint"], second["profile_fingerprint"])
        self.assertEqual(first["tokens"], second["tokens"])
        self.assertEqual(first["model_sha256"], model_sha256)
        self.assertEqual(first["training_corpus_sha256"], training_corpus_sha256)
        self.assertRegex(first["package_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(first["profile_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(
            {
                "po470002002",
                "03.80503g301",
                "交期",
                "產地",
            }.issubset(first["tokens"])
        )

    def test_package_runtime_binds_query_evidence_and_kg_to_one_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path, model_sha256 = _train_safe_sentencepiece_model(root / "training")
            package = _write_profile_package(
                root / "package",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=_sha256_text("approved safe test corpus identity"),
            )
            environment = _package_environment(package)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json\n"
                        "import sys\n"
                        "from pathlib import Path\n"
                        "from formowl_mail import evidence, query\n"
                        "sys.path.insert(0, str(Path.cwd() / 'scripts'))\n"
                        "import mail_full_pst_domain_hard_kg_fusion_eval as kg_eval\n"
                        "_, kg_runtime = kg_eval._apply_default_lexical_candidate_policy([])\n"
                        "value = 'PO470002002 的交期與 03.80503G301 的產地'\n"
                        "print(json.dumps({\n"
                        "  'evidence_fingerprint': evidence.MAIL_TOKENIZER_PROFILE_FINGERPRINT,\n"
                        "  'evidence_tokens': sorted(evidence._tokenize(value)),\n"
                        "  'kg_binding_fingerprint': kg_runtime.binding.candidate_admission_policy_hash,\n"
                        "  'kg_fingerprint': kg_eval.MAIL_TOKENIZER_PROFILE_FINGERPRINT,\n"
                        "  'kg_tokens': sorted(kg_eval._tokenize(value)),\n"
                        "  'query_fingerprint': query.MAIL_TOKENIZER_PROFILE_FINGERPRINT,\n"
                        "  'query_tokens': sorted(query._tokenize(value)),\n"
                        "}, ensure_ascii=False, sort_keys=True))\n"
                    ),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)

        self.assertEqual(payload["evidence_fingerprint"], payload["query_fingerprint"])
        self.assertEqual(payload["kg_fingerprint"], payload["query_fingerprint"])
        self.assertEqual(payload["kg_binding_fingerprint"], payload["query_fingerprint"])
        self.assertEqual(payload["evidence_tokens"], payload["query_tokens"])
        self.assertEqual(payload["kg_tokens"], payload["query_tokens"])

    def test_package_rejects_mixed_legacy_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path, model_sha256 = _train_safe_sentencepiece_model(root / "training")
            package = _write_profile_package(
                root / "package",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=_sha256_text("approved safe test corpus identity"),
            )
            with patch.dict(
                os.environ,
                {
                    PROFILE_PACKAGE_ENV: str(package),
                    MODEL_PATH_ENV: str(model_path),
                    TOKENIZER_MODE_ENV: FROZEN_MODE,
                },
                clear=False,
            ):
                os.environ.pop(MODEL_SHA256_ENV, None)
                os.environ.pop(TRAINING_CORPUS_SHA256_ENV, None)
                configured_mail_tokenizer_profile.cache_clear()
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^frozen tokenizer profile is unavailable$",
                ):
                    configured_mail_tokenizer_profile()

        configured_mail_tokenizer_profile.cache_clear()

    def test_package_with_legacy_ascii_mode_fails_closed(self) -> None:
        with patch.dict(
            os.environ,
            {
                PROFILE_PACKAGE_ENV: "/not-used/tokenizer-package",
                TOKENIZER_MODE_ENV: LEGACY_ASCII_TEST_MODE,
            },
            clear=False,
        ):
            os.environ.pop(MODEL_PATH_ENV, None)
            os.environ.pop(MODEL_SHA256_ENV, None)
            os.environ.pop(TRAINING_CORPUS_SHA256_ENV, None)
            configured_mail_tokenizer_profile.cache_clear()
            with self.assertRaisesRegex(
                RuntimeError,
                "^frozen tokenizer profile is unavailable$",
            ):
                configured_mail_tokenizer_profile()

    def test_package_rejects_manifest_or_model_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path, model_sha256 = _train_safe_sentencepiece_model(root / "training")
            package = _write_profile_package(
                root / "manifest-tamper",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=_sha256_text("approved safe test corpus identity"),
            )
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["training_corpus_sha256"] = _sha256_text("tampered corpus identity")
            manifest_path.write_bytes(_canonical_json_bytes(manifest))
            _assert_package_rejected(package)

            package = _write_profile_package(
                root / "model-tamper",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=_sha256_text("approved safe test corpus identity"),
            )
            package.joinpath("sentencepiece.model").write_bytes(b"tampered model bytes")
            _assert_package_rejected(package)

    def test_package_rejects_noncanonical_or_malformed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path, model_sha256 = _train_safe_sentencepiece_model(root / "training")
            training_corpus_sha256 = _sha256_text("approved safe test corpus identity")
            for name, mutate in (
                ("extra", lambda value: {**value, "unexpected": "field"}),
                (
                    "missing",
                    lambda value: {
                        key: item for key, item in value.items() if key != "tokenizer_id"
                    },
                ),
                ("hash", lambda value: {**value, "model_sha256": "sha256:" + "0" * 64}),
                ("path", lambda value: {**value, "model_path": "../sentencepiece.model"}),
                ("profile", lambda value: {**value, "tokenizer_id": "different_tokenizer_v1"}),
            ):
                package = _write_profile_package(
                    root / name,
                    model_path=model_path,
                    model_sha256=model_sha256,
                    training_corpus_sha256=training_corpus_sha256,
                )
                manifest_path = package / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                package = _rewrite_package_manifest(package, mutate(manifest))
                _assert_package_rejected(package)

            package = _write_profile_package(
                root / "pretty-json",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=training_corpus_sha256,
            )
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            pretty_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
            package = _rewrite_package_manifest_bytes(package, pretty_bytes)
            _assert_package_rejected(package)

    def test_package_rejects_symlink_or_unexpected_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path, model_sha256 = _train_safe_sentencepiece_model(root / "training")
            training_corpus_sha256 = _sha256_text("approved safe test corpus identity")
            package = _write_profile_package(
                root / "model-link",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=training_corpus_sha256,
            )
            packaged_model = package / "sentencepiece.model"
            packaged_model.unlink()
            packaged_model.symlink_to(model_path)
            _assert_package_rejected(package)

            package = _write_profile_package(
                root / "extra-file",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=training_corpus_sha256,
            )
            package.joinpath("unexpected.txt").write_text("unexpected", encoding="utf-8")
            _assert_package_rejected(package)

            package = _write_profile_package(
                root / "model-directory",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=training_corpus_sha256,
            )
            packaged_model = package / "sentencepiece.model"
            packaged_model.unlink()
            packaged_model.mkdir()
            _assert_package_rejected(package)

            package = _write_profile_package(
                root / "package-link-target",
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=training_corpus_sha256,
            )
            package_link = root / "package-link"
            package_link.symlink_to(package, target_is_directory=True)
            _assert_package_rejected(package_link)

            linked_parent_target = root / "linked-parent-target"
            linked_parent_target.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(linked_parent_target, target_is_directory=True)
            package = _write_profile_package(
                linked_parent_target,
                model_path=model_path,
                model_sha256=model_sha256,
                training_corpus_sha256=training_corpus_sha256,
            )
            _assert_package_rejected(linked_parent / package.name)


class _frozen_profile_environment:
    def __init__(
        self,
        model_path: Path,
        model_sha256: str,
        training_corpus_sha256: str,
    ) -> None:
        self._patcher = patch.dict(
            os.environ,
            {
                TOKENIZER_MODE_ENV: FROZEN_MODE,
                MODEL_PATH_ENV: str(model_path),
                MODEL_SHA256_ENV: model_sha256,
                TRAINING_CORPUS_SHA256_ENV: training_corpus_sha256,
            },
            clear=False,
        )

    def __enter__(self) -> None:
        self._patcher.start()
        os.environ.pop(PROFILE_PACKAGE_ENV, None)
        configured_mail_tokenizer_profile.cache_clear()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._patcher.stop()
        configured_mail_tokenizer_profile.cache_clear()


def _train_safe_sentencepiece_model(temp_dir: Path) -> tuple[Path, str]:
    try:
        import sentencepiece
    except ImportError as exc:  # pragma: no cover - canonical dev image provides it
        raise unittest.SkipTest("sentencepiece is unavailable") from exc
    try:
        import jieba  # noqa: F401
    except ImportError as exc:  # pragma: no cover - canonical dev image provides it
        raise unittest.SkipTest("jieba is unavailable") from exc

    temp_dir.mkdir(parents=True, exist_ok=True)
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


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_profile_package(
    parent: Path,
    *,
    model_path: Path,
    model_sha256: str,
    training_corpus_sha256: str,
) -> Path:
    manifest = {
        "artifact_id": PACKAGE_ARTIFACT_ID,
        "candidate_admission_policy_id": CANDIDATE_ADMISSION_POLICY_ID,
        "model_path": "sentencepiece.model",
        "model_sha256": model_sha256,
        "profile_schema_id": PROFILE_SCHEMA_ID,
        "segmentation_policy_id": SEGMENTATION_POLICY_ID,
        "tokenizer_id": JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        "training_corpus_sha256": training_corpus_sha256,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    package_fingerprint = hashlib.sha256(manifest_bytes).hexdigest()
    package = parent / f"sha256-{package_fingerprint}"
    package.mkdir(parents=True)
    package.joinpath("manifest.json").write_bytes(manifest_bytes)
    package.joinpath("sentencepiece.model").write_bytes(model_path.read_bytes())
    return package


def _run_package_profile_probe(package: Path) -> dict[str, object]:
    environment = _package_environment(package)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json\n"
                "from formowl_core.tokenization import configured_mail_tokenizer_profile\n"
                "profile = configured_mail_tokenizer_profile()\n"
                "print(json.dumps({\n"
                "  'model_sha256': profile.model_sha256,\n"
                "  'package_fingerprint': profile.package_fingerprint,\n"
                "  'profile_fingerprint': profile.profile_fingerprint,\n"
                "  'tokens': sorted(profile.tokenize('PO470002002 的交期與 03.80503G301 的產地')),\n"
                "  'training_corpus_sha256': profile.training_corpus_sha256,\n"
                "}, ensure_ascii=False, sort_keys=True))\n"
            ),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _package_environment(package: Path) -> dict[str, str]:
    environment = {
        **os.environ,
        PROFILE_PACKAGE_ENV: str(package),
        TOKENIZER_MODE_ENV: FROZEN_MODE,
        "PYTHONPATH": str(ROOT / "python"),
    }
    for name in (
        MODEL_PATH_ENV,
        MODEL_SHA256_ENV,
        TRAINING_CORPUS_SHA256_ENV,
    ):
        environment.pop(name, None)
    return environment


def _rewrite_package_manifest(package: Path, manifest: dict[str, str]) -> Path:
    return _rewrite_package_manifest_bytes(package, _canonical_json_bytes(manifest))


def _rewrite_package_manifest_bytes(package: Path, manifest_bytes: bytes) -> Path:
    package.joinpath("manifest.json").write_bytes(manifest_bytes)
    target = package.parent / f"sha256-{hashlib.sha256(manifest_bytes).hexdigest()}"
    package.rename(target)
    return target


def _assert_package_rejected(package: Path) -> None:
    environment = _package_environment(package)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from formowl_core.tokenization import configured_mail_tokenizer_profile\n"
            "configured_mail_tokenizer_profile()\n",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        raise AssertionError(f"unsafe tokenizer package was accepted: {package}")
    if "frozen tokenizer profile is unavailable" not in completed.stderr:
        raise AssertionError(completed.stderr)


def _canonical_json_bytes(value: dict[str, str]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
