from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_core.dense_embedding import (
    DenseEmbeddingUnavailableError,
    DenseEvidenceVectorCache,
    ISSUE56_TARGET_DENSE_DIMENSION,
    SentenceTransformerDenseEncoder,
    PackedDenseVector,
    issue56_target_dense_embedding_profile,
)


class _FakeRow:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def tolist(self) -> list[float]:
        return list(self._values)


class _FakeModel:
    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.kwargs: dict[str, object] = {}

    def encode(self, inputs: list[str], **kwargs: object) -> list[_FakeRow]:
        self.inputs = list(inputs)
        self.kwargs = dict(kwargs)
        rows: list[_FakeRow] = []
        for index in range(len(inputs)):
            values = [0.0] * ISSUE56_TARGET_DENSE_DIMENSION
            values[index] = 1.0
            rows.append(_FakeRow(values))
        return rows


class _WrongCountModel(_FakeModel):
    def encode(self, inputs: list[str], **kwargs: object) -> list[_FakeRow]:
        super().encode(inputs, **kwargs)
        return []


class DenseEmbeddingBatchTests(unittest.TestCase):
    def test_env_256_pending_staging_keeps_hybrid_consumer_batches_at_32_on_resume(
        self,
    ):
        class RecordingModel(_FakeModel):
            def __init__(self):
                super().__init__()
                self.encode_batch_sizes: list[int] = []
                self.encode_requested_batch_sizes: list[int] = []

            def encode(self, inputs, **kwargs):
                self.encode_batch_sizes.append(len(inputs))
                self.encode_requested_batch_sizes.append(kwargs["batch_size"])
                return super().encode(inputs, **kwargs)

        model = RecordingModel()
        encoder = SentenceTransformerDenseEncoder(
            profile=issue56_target_dense_embedding_profile(), _model=model,
        )
        texts = tuple(f"two-level batch item {index}" for index in range(256))
        env_key = "FORMOWL_DENSE_EVIDENCE_BATCH_SIZE"
        with tempfile.TemporaryDirectory() as directory:
            cache = DenseEvidenceVectorCache(directory)
            first_consumer_batches = []

            def interrupt_after_first_consumer_batch(rows):
                first_consumer_batches.append(len(rows))
                raise InterruptedError("projection writer paused")

            with patch.dict(os.environ, {env_key: "256"}):
                with self.assertRaises(InterruptedError):
                    cache.encode(
                        encoder,
                        texts,
                        consume_batch=interrupt_after_first_consumer_batch,
                    )

                self.assertEqual(model.encode_batch_sizes, [256])
                self.assertEqual(model.encode_requested_batch_sizes, [256])
                self.assertEqual(first_consumer_batches, [32])

                resumed_consumer_batches = []
                with patch.object(
                    model, "encode", side_effect=AssertionError("must reuse cache"),
                ):
                    cache.encode(
                        encoder,
                        texts,
                        consume_batch=lambda rows: resumed_consumer_batches.append(
                            len(rows),
                        ),
                    )

            self.assertEqual(resumed_consumer_batches, [32] * 8)

    def test_cache_resumes_32_to_256_to_32_without_reencoding(self):
        model = _FakeModel()
        encoder = SentenceTransformerDenseEncoder(
            profile=issue56_target_dense_embedding_profile(), _model=model,
        )
        texts = tuple(f"batch resume item {index}" for index in range(288))
        env_key = "FORMOWL_DENSE_EVIDENCE_BATCH_SIZE"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = DenseEvidenceVectorCache(root)
            with patch.dict(os.environ, {env_key: "32"}):
                initial = cache.encode(encoder, texts[:32])
            self.assertEqual(len(initial), 32)
            initial_bytes = (root / "vectors.f32").read_bytes()
            profile_bytes = (root / "profile.json").read_bytes()
            consumed = []

            def consume_large_batch(rows):
                entries = [
                    json.loads(line)
                    for line in (root / "batches.jsonl").read_text().splitlines()
                ]
                self.assertEqual([len(e["text_hashes"]) for e in entries], [32] * 9)
                self.assertEqual(entries[1]["offset"], len(initial_bytes))
                consumed.append(len(rows))

            with patch.dict(os.environ, {env_key: "256"}):
                with patch.object(model, "encode", wraps=model.encode) as encode:
                    expanded = cache.encode(
                        encoder, texts[32:], consume_batch=consume_large_batch,
                    )
                    self.assertEqual(len(expanded), 256)
                    encode.assert_called_once()
                    self.assertEqual(encode.call_args.kwargs["batch_size"], 256)
            self.assertEqual(consumed, [32] * 8)
            saved = {
                name: (root / name).read_bytes()
                for name in ("profile.json", "vectors.f32", "batches.jsonl")
            }
            self.assertEqual(saved["profile.json"], profile_bytes)
            self.assertEqual(saved["vectors.f32"][:len(initial_bytes)], initial_bytes)
            consumed.clear()
            with patch.dict(os.environ, {env_key: "32"}):
                with patch.object(
                    model, "encode", side_effect=AssertionError("must reuse cache"),
                ):
                    vectors = cache.encode(
                        encoder, texts,
                        consume_batch=lambda rows: consumed.append(len(rows)),
                    )
            self.assertEqual(consumed, [32] * 9)
            self.assertEqual(len(vectors), 288)
            for name, contents in saved.items():
                self.assertEqual((root / name).read_bytes(), contents)

    def test_batch_256_duplicate_stream_flushes_consumer_without_drain_overflow(self):
        model = _FakeModel()
        encoder = SentenceTransformerDenseEncoder(
            profile=issue56_target_dense_embedding_profile(), _model=model,
        )
        consumed = []
        with tempfile.TemporaryDirectory() as directory:
            cache = DenseEvidenceVectorCache(directory)
            with patch.dict(
                os.environ, {"FORMOWL_DENSE_EVIDENCE_BATCH_SIZE": "256"},
            ):
                vectors = cache.encode(
                    encoder,
                    ("duplicate evidence",) * 257,
                    consume_batch=lambda rows: consumed.append(len(rows)),
                )

        self.assertEqual(len(vectors), 257)
        self.assertEqual(consumed, [32] * 8 + [1])

    def test_streaming_consumer_drains_duplicate_occurrences_and_reuses_durable_rows(self):
        model = _FakeModel()
        encoder = SentenceTransformerDenseEncoder(
            profile=issue56_target_dense_embedding_profile(), _model=model,
        )
        with tempfile.TemporaryDirectory() as directory:
            cache = DenseEvidenceVectorCache(directory)
            def interrupt(rows):
                self.assertEqual(len(rows), 32)
                self.assertTrue(all(isinstance(row, PackedDenseVector) for row in rows))
                raise InterruptedError("projection writer paused")
            with self.assertRaises(InterruptedError):
                cache.encode(encoder, ("alpha" for _ in range(65)), consume_batch=interrupt)
            batches = []
            original = model.encode
            def forbid_encode(*args, **kwargs):
                raise AssertionError("committed vectors must be reused")
            model.encode = forbid_encode
            vectors = cache.encode(
                encoder, ("alpha" for _ in range(65)),
                consume_batch=lambda rows: batches.append(len(rows)),
            )
            model.encode = original
            self.assertEqual(batches, [32, 32, 1])
            self.assertEqual(len(vectors), 65)
            self.assertEqual((Path(directory) / "vectors.f32").stat().st_size, 384 * 4)

    def test_committed_batches_resume_without_reencoding_and_keep_float32_rows(self) -> None:
        class RecordingModel(_FakeModel):
            def __init__(self):
                super().__init__()
                self.batches = []

            def encode(self, inputs, **kwargs):
                self.batches.append(tuple(inputs))
                return super().encode(inputs, **kwargs)

        model = RecordingModel()
        encoder = SentenceTransformerDenseEncoder(
            profile=issue56_target_dense_embedding_profile(), _model=model,
        )
        texts = tuple(f"source neutral item {index}" for index in range(40))
        with tempfile.TemporaryDirectory() as directory:
            cache = DenseEvidenceVectorCache(directory)

            def interrupt_after_commit(event):
                self.assertEqual(event["phase"], "dense_batch_committed")
                raise InterruptedError("operator pause after durable batch")

            with self.assertRaises(InterruptedError):
                cache.encode(encoder, texts, progress=interrupt_after_commit)
            self.assertEqual(len(model.batches), 1)
            vectors = cache.encode(encoder, (*texts, texts[0]))
            self.assertEqual([len(batch) for batch in model.batches], [32, 8])
            self.assertEqual(len(vectors), 41)
            self.assertIsInstance(vectors[0], PackedDenseVector)
            self.assertEqual(vectors[0], vectors[-1])
            self.assertEqual(len(vectors[0].packed_bytes()), 384 * 4)
            self.assertEqual(
                (Path(directory) / "vectors.f32").stat().st_size, 40 * 384 * 4,
            )
            with self.assertRaises(FrozenInstanceError):
                vectors[0]._offset = 4
            cache.encode(encoder, texts)
            self.assertEqual(len(model.batches), 2)

    def test_cache_rejects_committed_corruption_and_profile_drift(self) -> None:
        encoder = SentenceTransformerDenseEncoder(
            profile=issue56_target_dense_embedding_profile(), _model=_FakeModel(),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = DenseEvidenceVectorCache(root)
            cache.encode(encoder, ("alpha",))
            declaration = json.loads((root / "profile.json").read_bytes())
            declaration["profile_fingerprint"] = "drift"
            (root / "profile.json").write_text(json.dumps(declaration))
            with self.assertRaises(DenseEmbeddingUnavailableError) as caught:
                cache.encode(encoder, ("alpha",))
            self.assertEqual(caught.exception.reason_code, "dense_cache_profile_mismatch")
            declaration["profile_fingerprint"] = encoder.profile_fingerprint
            (root / "profile.json").write_text(json.dumps(declaration))
            with (root / "vectors.f32").open("r+b") as stream:
                stream.write(b"xxxx")
            with self.assertRaises(DenseEmbeddingUnavailableError) as caught:
                cache.encode(encoder, ("alpha",))
            self.assertEqual(caught.exception.reason_code, "dense_cache_payload_mismatch")

    def test_batch_preserves_frozen_evidence_contract(self) -> None:
        model = _FakeModel()
        encoder = SentenceTransformerDenseEncoder(
            profile=issue56_target_dense_embedding_profile(),
            _model=model,
        )

        vectors = encoder.encode_evidence_batch(("  alpha\u00a0beta  ", "gamma"))

        self.assertEqual(len(vectors), 2)
        self.assertEqual(
            [len(vector) for vector in vectors],
            [ISSUE56_TARGET_DENSE_DIMENSION] * 2,
        )
        self.assertEqual(model.inputs, ["passage: alpha beta", "passage: gamma"])
        self.assertEqual(model.kwargs["batch_size"], 2)
        self.assertEqual(model.kwargs["precision"], "float32")
        self.assertEqual(model.kwargs["device"], "cpu")
        self.assertTrue(model.kwargs["normalize_embeddings"])
        self.assertTrue(model.kwargs["convert_to_numpy"])
        self.assertFalse(model.kwargs["convert_to_tensor"])
        for vector in vectors:
            self.assertAlmostEqual(sum(value * value for value in vector), 1.0)

    def test_batch_rejects_wrong_output_count(self) -> None:
        encoder = SentenceTransformerDenseEncoder(
            profile=issue56_target_dense_embedding_profile(),
            _model=_WrongCountModel(),
        )

        with self.assertRaises(DenseEmbeddingUnavailableError) as caught:
            encoder.encode_evidence_batch(("alpha", "beta"))

        self.assertEqual(
            caught.exception.reason_code,
            "dense_batch_output_count_mismatch",
        )
