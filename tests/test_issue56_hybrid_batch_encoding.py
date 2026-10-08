from __future__ import annotations

from dataclasses import replace
from collections import Counter
from copy import deepcopy
import json
import struct
import tempfile
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from unittest.mock import Mock

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    Observation,
    PermissionScope,
    sha256_json,
    to_plain,
)
from formowl_core import (
    ISSUE56_TARGET_DENSE_DIMENSION,
    Issue56TargetRuntimeComponents,
    SentenceTransformerDenseEncoder,
    build_ascii_identifier_regex_tokenizer_profile,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
    sha256_prefixed,
)
from formowl_mail import hybrid
from formowl_core.dense_embedding import DenseEvidenceVectorCache, PackedDenseVector
from formowl_graph.index.records import PostgreSQLGraphProjectionStore
from formowl_mail.exact import (
    AuthorizedSourceOccurrence,
    SourceOccurrenceProvider,
    authorized_source_occurrence_scope_fingerprint,
    source_occurrence_column_capability_hash,
)
from formowl_mail.query import (
    build_authorized_observation_snippet_index,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    validated_authorized_semantic_source,
)


WORKSPACE_ID = "workspace_issue56_batch_encoding"
SOURCE_SCOPE_ID = "project_issue56_batch_encoding"


class _MemoryProjectionStore(PostgreSQLGraphProjectionStore):
    """Synthetic I/O boundary; retain the owner's admission, seal and reopen.

    This does not exercise PostgreSQL SQL, transactions or query performance.
    """

    def __init__(self, connection, **kwargs):
        super().__init__(connection, **kwargs)
        self.rows = {}
        self.vectors = {}

    def _get(self, kind, record_id):
        row = self.rows.get((kind, record_id))
        return None if row is None else self._checked(deepcopy(row))

    def _put(self, kind, record_id, data, **keys):
        payload = deepcopy({
            "revision_id": self.revision_id, "binding_hash": self._binding_hash,
            "kind": kind, "id": record_id, "data": data, **keys,
        })
        self.rows[kind, record_id] = {"payload": payload, "payload_hash": sha256_json(payload)}

    def _put_many(self, kind, records):
        for record_id, data, keys in self._batch(records):
            self._put(kind, record_id, data, **keys)

    def _get_many(self, kind, ids):
        return {key: value for key in ids if (value := self._get(kind, key)) is not None}

    def _page(self, kind, *, after_id=None, limit=256, field="id", match=None):
        rows = [self._get(kind, key) for row_kind, key in self.rows if row_kind == kind]
        return sorted(
            (row for row in rows if row[field] > (after_id or "")
             and (match is None or row.get(match[0]) == match[1])),
            key=lambda row: row[field],
        )[:limit]

    def helpers_for_hashes(self, hashes):
        return {key: item for key in hashes if (item := self.helper_for_hash(key)) is not None}

    def iter_candidates(self, *, after_ordinal=None, limit=256):
        return sorted(
            (row["data"] for row in self._page("candidate")
             if int(row["ordinal"]) > (-1 if after_ordinal is None else after_ordinal)),
            key=lambda row: row["ordinal"],
        )[:limit]

    def candidate_by_ordinal(self, ordinal):
        return next(iter(self.iter_candidates(after_ordinal=ordinal - 1, limit=1)), None)

    def finalize_candidate_order_and_statistics(self):
        candidates = sorted(
            self.iter_candidates(),
            key=lambda row: (row["bundle_id"], row["source_observation_hash"],
                             row["message_occurrence_hash"]),
        )
        for ordinal, row in enumerate(candidates):
            row["ordinal"] = ordinal
        self.put_candidates(candidates)
        frequencies = Counter(row["token"] for row in self._page("posting"))
        self.put_token_statistics([
            {"token": key, "document_frequency": count} for key, count in frequencies.items()
        ])
        statistics = {
            "document_count": len(candidates),
            "average_document_length": sum(len(row["searchable_tokens"]) for row in candidates)
            / len(candidates),
            "candidate_content_fingerprint": sha256_json(candidates),
        }
        self.put_corpus_statistics(statistics)
        return statistics

    def _put_dense_vectors(self, records):
        for record in records:
            vector = tuple(record["vector"])
            self.vectors[record["text_hash"]] = vector
            self._put("vector_ref", record["text_hash"], {"vector_hash": sha256_json(list(vector))})

    def get_dense_vector(self, text_hash):
        return self.vectors[text_hash]


class _PerItemEncoder:
    encoder_id = "contract-test-dense-encoder"
    dimension = 3
    diagnostic = False
    profile_fingerprint = "contract-test-dense-profile"

    def __init__(self) -> None:
        self.evidence_texts: list[str] = []

    def encode_evidence(self, text: str) -> tuple[float, ...]:
        self.evidence_texts.append(text)
        return (1.0, 0.0, 0.0)


class _BatchEncoder(_PerItemEncoder):
    def __init__(self) -> None:
        super().__init__()
        self.batch_texts: list[tuple[str, ...]] = []

    def encode_evidence_batch(
        self,
        texts: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        self.batch_texts.append(tuple(texts))
        return tuple((1.0, 0.0, 0.0) for _text in texts)


class _VectorRow(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class _PinnedModel:
    def __init__(self, *, fail_on_encode: bool = False) -> None:
        self.call_count = 0
        self.fail_on_encode = fail_on_encode

    def encode(self, texts, **_kwargs):
        self.call_count += 1
        if self.fail_on_encode:
            raise AssertionError("evidence encoding must not run")
        vector = [0.0] * ISSUE56_TARGET_DENSE_DIMENSION
        vector[0] = 1.0
        return [_VectorRow(vector) for _text in texts]


def _observation(observation_id: str, text: str) -> Observation:
    return Observation.from_dict(
        Observation(
            observation_id=observation_id,
            extractor_run_id="extractor_issue56_batch_encoding",
            observation_type="mail_body_segment",
            modality="mail",
            location={"message_occurrence_id": f"message-{observation_id}"},
            confidence=1.0,
            permission_scope=PermissionScope.project(SOURCE_SCOPE_ID),
            created_at="2026-08-29T00:00:00+00:00",
            asset_id="asset_issue56_batch_encoding",
            text=text,
        ).to_dict()
    )


def _runtime(profile, dense_encoder):
    return SimpleNamespace(
        tokenizer_profile=profile,
        dense_encoder=dense_encoder,
        execution_binding=SimpleNamespace(
            dense_model_id="contract-test-model",
            dense_model_revision="contract-test-revision",
            execution_component_fingerprint="contract-test-execution",
        ),
    )


def _pinned_runtime(model: _PinnedModel) -> Issue56TargetRuntimeComponents:
    profile = load_issue56_target_mail_tokenizer_profile()
    dense_profile = issue56_target_dense_embedding_profile()
    return Issue56TargetRuntimeComponents(
        tokenizer_profile=profile,
        dense_encoder=SentenceTransformerDenseEncoder(
            profile=dense_profile,
            _model=model,
        ),
        execution_binding=build_issue56_execution_component_binding(
            tokenizer_profile=profile,
            dense_profile=dense_profile,
        ),
    )


class Issue56HybridBatchEncodingTests(unittest.TestCase):
    def test_streamed_candidate_resume_matches_uninterrupted_mock_storage(self) -> None:
        """Synthetic storage/encoder proof, not PostgreSQL crash durability."""
        runtime, source, observations, lineages, hashes, _snippets, _manifest = (
            self._artifact_fixture()
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict("os.environ", {"FORMOWL_DENSE_EVIDENCE_BATCH_SIZE": "1"}),
            patch.object(hybrid, "_load_pinned_issue56_runtime_components", return_value=runtime),
        ):
            def fixture():
                store = _MemoryProjectionStore(
                    Mock(), revision_id="resume_fixture", workspace_id=source.workspace_id,
                    binding={"source_access_fingerprint": source.authorization_fingerprint},
                )
                for observation, lineage in zip(observations, lineages, strict=True):
                    store.put_helpers([{
                        "observation_id": observation.observation_id,
                        "observation_hash": hashes[observation.observation_id],
                        "source_scope_id": SOURCE_SCOPE_ID, "reference": {},
                        "lineage": to_plain(lineage), "source_families": ["mail"],
                        "permission_scope": to_plain(observation.permission_scope),
                    }])
                reads = []
                def pages(*, after_id=None, limit=32):
                    reads.append(after_id)
                    remaining = tuple(o for o in observations
                                      if after_id is None or o.observation_id > after_id)
                    return iter((remaining,)) if remaining else iter(())
                records = SimpleNamespace(
                    runtime_store=store, requester_user_id="resume_actor",
                    workspace_id=source.workspace_id, iter_retrieval_pages=pages,
                    lineage=lambda oid: next(item for item in lineages
                                             if item.source_observation_id == oid),
                    observation_hash=hashes.__getitem__,
                )
                return store, records, reads

            def build(store, records, **kwargs):
                return hybrid.build_authorized_semantic_observation_session(
                    authorized_source=source, requester_user_id=records.requester_user_id,
                    source_records=records, runtime_store=store,
                    source_binding={"fixture": "bound source"},
                    dense_vector_cache=DenseEvidenceVectorCache(directory), **kwargs,
                )

            expected_store, expected_records, _ = fixture()
            expected = build(expected_store, expected_records)
            for interruption in ("batch", "finalized", "legacy"):
                with self.subTest(interruption=interruption):
                    store, records, reads = fixture()
                    if interruption == "finalized":
                        finalize = store.finalize_candidate_order_and_statistics
                        def fail_finalized():
                            finalize()
                            raise RuntimeError("synthetic post-finalize interruption")
                        with patch.object(store, "finalize_candidate_order_and_statistics",
                                          side_effect=fail_finalized):
                            with self.assertRaisesRegex(RuntimeError, "post-finalize"):
                                build(store, records)
                    else:
                        def stop_after_batch(event):
                            if event["phase"] == "candidate_batch_persisted":
                                raise RuntimeError("synthetic committed-batch interruption")
                        with self.assertRaisesRegex(RuntimeError, "committed-batch"):
                            build(store, records, dense_build_progress=stop_after_batch)
                        if interruption == "legacy":
                            del store.rows["checkpoint", "candidate_build_progress_v1"]
                            self.assertEqual(store.checkpoint_cursor("candidates_1"),
                                             observations[0].observation_id)
                    reopened = _MemoryProjectionStore(
                        Mock(), revision_id=store.revision_id, workspace_id=store.workspace_id,
                        binding=store.binding,
                    )
                    reopened.rows, reopened.vectors = deepcopy(store.rows), deepcopy(store.vectors)
                    records.runtime_store = reopened
                    reads.clear()
                    actual = build(reopened, records)
                    self.assertEqual(reads, [
                        None if interruption == "legacy" else observations[
                            -1 if interruption == "finalized" else 0
                        ].observation_id
                    ])
                    self.assertEqual(reopened.rows, expected_store.rows)
                    self.assertEqual(reopened.vectors, expected_store.vectors)
                    self.assertEqual(actual.index.index_fingerprint, expected.index.index_fingerprint)
                    self.assertEqual(actual.source_session_binding_fingerprint,
                                     expected.source_session_binding_fingerprint)
            limited_store, limited_records, reads = fixture()
            limited = build(limited_store, limited_records, streaming_candidate_limit=1)
            with patch.object(limited_records, "iter_retrieval_pages",
                              side_effect=AssertionError("completed limit must not read source")):
                again = build(limited_store, limited_records, streaming_candidate_limit=1)
                self.assertEqual(again.index.index_fingerprint, limited.index.index_fingerprint)
                with self.assertRaisesRegex(ContractValidationError, "checkpoint binding"):
                    build(limited_store, limited_records, streaming_candidate_limit=2)

    def test_streamed_source_families_require_known_authorized_kind(self) -> None:
        runtime, source, observations, lineages, hashes, _snippets, _manifest = (
            self._artifact_fixture()
        )
        for family in ("unknown_family", "document_text"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                store = _MemoryProjectionStore(
                    Mock(), revision_id="family_guard", workspace_id=source.workspace_id,
                    binding={"source_access_fingerprint": source.authorization_fingerprint},
                )
                for observation, lineage in zip(observations, lineages, strict=True):
                    store.put_helpers([{
                        "observation_id": observation.observation_id,
                        "observation_hash": hashes[observation.observation_id],
                        "source_scope_id": SOURCE_SCOPE_ID,
                        "reference": {}, "lineage": to_plain(lineage),
                        "permission_scope": to_plain(observation.permission_scope),
                        "source_families": [family],
                    }])
                records = SimpleNamespace(
                    runtime_store=store, requester_user_id="family_guard_actor",
                    workspace_id=source.workspace_id,
                    iter_retrieval_pages=lambda **_kwargs: iter((observations,)),
                    lineage=lambda oid: next(item for item in lineages
                                             if item.source_observation_id == oid),
                    observation_hash=hashes.__getitem__,
                )
                with patch.object(hybrid, "_load_pinned_issue56_runtime_components",
                                  return_value=runtime):
                    with self.assertRaisesRegex(ContractValidationError, "source-family binding"):
                        hybrid.build_authorized_semantic_observation_session(
                            authorized_source=source, requester_user_id=records.requester_user_id,
                            source_records=records, runtime_store=store,
                            source_binding={"fixture": "bound source"},
                            dense_vector_cache=DenseEvidenceVectorCache(directory),
                        )

    def test_cached_build_and_artifact_reload_do_not_expand_candidate_vectors(self) -> None:
        runtime, source, observations, lineages, _hashes, snippets, _manifest = (
            self._artifact_fixture()
        )
        with tempfile.TemporaryDirectory() as directory:
            cache = DenseEvidenceVectorCache(directory)
            cached = hybrid._build_authorized_hybrid_observation_index(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                runtime_components=runtime,
                dense_vector_cache=cache,
            )
            ordinary = hybrid._build_authorized_hybrid_observation_index(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                runtime_components=runtime,
            )
            self.assertEqual(cached.index_fingerprint, ordinary.index_fingerprint)
            self.assertTrue(all(
                isinstance(candidate.dense_vector, PackedDenseVector)
                for candidate in cached.candidates
            ))
            before = runtime.dense_encoder._model.call_count
            resumed = hybrid._build_authorized_hybrid_observation_index(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                runtime_components=runtime,
                dense_vector_cache=cache,
            )
            self.assertEqual(runtime.dense_encoder._model.call_count, before)
            self.assertEqual(resumed.index_fingerprint, ordinary.index_fingerprint)

    def _artifact_fixture(self):
        runtime = _pinned_runtime(_PinnedModel())
        source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        observations = tuple(
            _observation(
                f"observation-artifact-{index}",
                f"authorized evidence snippet {index}",
            )
            for index in range(2)
        )
        lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=source,
            )
            for observation in observations
        )
        hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in observations
        }
        snippets, manifest = build_authorized_observation_snippet_index(
            observations,
            authorized_source=source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=hashes,
            tokenizer_profile=runtime.tokenizer_profile,
        )
        return runtime, source, observations, lineages, hashes, snippets, manifest

    def test_batch_and_compatibility_paths_preserve_candidates_and_bindings(self) -> None:
        profile = build_ascii_identifier_regex_tokenizer_profile()
        authorized_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        observations = (
            _observation("observation-batch-1", "supplier alpha part A-1"),
            _observation("observation-batch-2", "supplier beta part B-2"),
        )
        lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in observations
        )
        authorized_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in observations
        }
        snippet_index, _manifest = build_authorized_observation_snippet_index(
            observations,
            authorized_source=authorized_source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=authorized_hashes,
            tokenizer_profile=profile,
        )
        expected_texts = tuple(
            snippet.dense_evidence_text for snippet in snippet_index.snippets
        )

        batch_encoder = _BatchEncoder()
        batch_index = hybrid._build_authorized_hybrid_observation_index(
            authorized_source=authorized_source,
            snippet_index=snippet_index,
            authorized_observations=observations,
            occurrence_lineages=lineages,
            runtime_components=_runtime(profile, batch_encoder),
        )
        per_item_encoder = _PerItemEncoder()
        per_item_index = hybrid._build_authorized_hybrid_observation_index(
            authorized_source=authorized_source,
            snippet_index=snippet_index,
            authorized_observations=observations,
            occurrence_lineages=lineages,
            runtime_components=_runtime(profile, per_item_encoder),
        )

        self.assertEqual(len(batch_index.candidates), len(observations))
        self.assertEqual(len(per_item_index.candidates), len(observations))
        self.assertEqual(batch_index.index_fingerprint, per_item_index.index_fingerprint)
        self.assertEqual(
            [
                (
                    candidate.source_observation_hash,
                    candidate.index_binding_hash,
                    candidate.message_occurrence_hash,
                    candidate.dense_vector,
                )
                for candidate in batch_index.candidates
            ],
            [
                (
                    candidate.source_observation_hash,
                    candidate.index_binding_hash,
                    candidate.message_occurrence_hash,
                    candidate.dense_vector,
                )
                for candidate in per_item_index.candidates
            ],
        )
        self.assertEqual(batch_encoder.batch_texts, [expected_texts])
        self.assertEqual(batch_encoder.evidence_texts, [])
        self.assertEqual(per_item_encoder.evidence_texts, list(expected_texts))

    def test_untyped_enumeration_selects_combined_present_provider(self) -> None:
        runtime, source, observations, lineages, _hashes, snippets, manifest = (
            self._artifact_fixture()
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime,
        ):
            session = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id="user_issue56_combined_provider",
            )
        graph = hybrid.build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=manifest.index_fingerprint,
        )
        query_text = "哪些 neutral catalog"
        exact_slots = hybrid._deterministic_exact_filter_slots(
            query_text,
            tokenizer_profile=runtime.tokenizer_profile,
        )
        self.assertEqual(exact_slots.identifier_hashes, ())
        matching_hash = sha256_json("neutral")
        projection_hash = sha256_json("catalog")
        self.assertIn(matching_hash, exact_slots.topic_hashes)
        self.assertIn(projection_hash, exact_slots.topic_hashes)
        citation_hash = dict(session.authorized_observation_hashes)[
            observations[0].observation_id
        ]
        lineage_fingerprint = next(
            lineage.lineage_fingerprint
            for lineage in session.occurrence_lineages
            if lineage.source_observation_id == observations[0].observation_id
        )
        scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_observation_hashes=session.authorized_observation_hashes,
            source_session_binding_fingerprint=(
                session.source_session_binding_fingerprint or ""
            ),
        )
        occurrence = AuthorizedSourceOccurrence(
            item_hash=sha256_json("neutral table row occurrence"),
            value_bindings=(
                (
                    matching_hash,
                    matching_hash,
                    citation_hash,
                    lineage_fingerprint,
                ),
                (
                    sha256_json("neutral catalog projected value"),
                    sha256_json("neutral catalog projected value"),
                    citation_hash,
                    lineage_fingerprint,
                ),
            ),
            projection_bindings=(
                (
                    "neutral_filter_value",
                    "neutral",
                    citation_hash,
                    lineage_fingerprint,
                ),
                (
                    "neutral_catalog_field",
                    "catalog entry",
                    citation_hash,
                    lineage_fingerprint,
                ),
            ),
            structure_status="source_provided",
            structured_column_bindings=(
                (
                    source_occurrence_column_capability_hash(
                        "neutral_filter_value"
                    ),
                    sha256_json("neutral filter column"),
                    matching_hash,
                    "neutral_filter_value",
                    "neutral",
                    citation_hash,
                    lineage_fingerprint,
                ),
                (
                    source_occurrence_column_capability_hash(
                        "neutral_catalog_field"
                    ),
                    projection_hash,
                    sha256_json("neutral catalog projected value"),
                    "neutral_catalog_field",
                    "catalog entry",
                    citation_hash,
                    lineage_fingerprint,
                ),
            ),
        )
        combined_provider = SourceOccurrenceProvider(
            provider_id="neutral_table_row_provider_v1",
            inventory_kind_alias="neutral_table_row",
            resource_kind="neutral_table_row_occurrence",
            normalized_field="table.row.cell_value",
            predicate="source_occurrence_row_contains",
            operator="case_insensitive_exact",
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_scope_fingerprint=scope_fingerprint,
            occurrences=(occurrence,),
            filter_slot_policy="combined_present_intersection_v1",
        )
        identifier_provider = replace(
            combined_provider,
            provider_id="neutral_identifier_provider_v1",
            inventory_kind_alias="neutral_identifier",
            resource_kind="neutral_identifier_occurrence",
            filter_slot_policy="identifier_union_v1",
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json("neutral identifier occurrence"),
                    value_bindings=(
                        (
                            matching_hash,
                            matching_hash,
                            citation_hash,
                            lineage_fingerprint,
                        ),
                    ),
                ),
            ),
        )
        routed_session = replace(
            session,
            source_occurrence_providers=(
                identifier_provider,
                combined_provider,
            ),
        )

        result = routed_session.query(
            query_text=query_text,
            effective_graph_view=graph.effective_graph_view,
        )

        self.assertEqual(result.query_class, "exact_set_or_inventory")
        self.assertEqual(result.status, "complete_authorized_scope")
        self.assertIsNotNone(result.exact_result)
        assert result.exact_result is not None
        self.assertEqual(result.exact_result.exact_count, 1)
        self.assertEqual(
            result.exact_result.items[0].matched_normalized_value_hashes,
            (matching_hash,),
        )
        self.assertEqual(
            result.exact_result.items[0].governed_references,
            ((citation_hash, lineage_fingerprint),),
        )

        value_only_provider = replace(
            combined_provider,
            provider_id="neutral_value_only_provider_v1",
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json("neutral value-only occurrence"),
                    value_bindings=(
                        (
                            matching_hash,
                            matching_hash,
                            citation_hash,
                            lineage_fingerprint,
                        ),
                    ),
                ),
            ),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "source occurrence provider selection is invalid",
        ):
            replace(
                session,
                source_occurrence_providers=(
                    identifier_provider,
                    value_only_provider,
                ),
            ).query(
                query_text=query_text,
                effective_graph_view=graph.effective_graph_view,
            )

        with self.assertRaisesRegex(
            ContractValidationError,
            "source occurrence provider selection is ambiguous",
        ):
            replace(
                routed_session,
                source_occurrence_providers=(
                    identifier_provider,
                    combined_provider,
                    replace(
                        combined_provider,
                        provider_id="neutral_table_row_peer_provider_v1",
                        inventory_kind_alias="neutral_table_row_peer",
                    ),
                ),
            ).query(
                query_text=query_text,
                effective_graph_view=graph.effective_graph_view,
            )

    def test_streaming_candidate_limit_is_forwarded_without_changing_full_default(self) -> None:
        runtime, source, _observations, _lineages, _hashes, _snippets, _manifest = (
            self._artifact_fixture()
        )
        runtime_store = SimpleNamespace(
            binding={"source_access_fingerprint": source.authorization_fingerprint},
        )
        source_records = SimpleNamespace(
            runtime_store=runtime_store,
            requester_user_id="user_issue56_combined_provider",
            workspace_id=source.workspace_id,
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "formowl_mail.hybrid._build_streamed_semantic_observation_session",
            return_value="streamed-session",
        ) as build_streamed:
            result = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                requester_user_id=source_records.requester_user_id,
                source_records=source_records,
                runtime_store=runtime_store,
                dense_vector_cache=DenseEvidenceVectorCache(directory),
                source_binding={"source_authority_fingerprint": "fixture-authority"},
                streaming_candidate_limit=7,
            )
        self.assertEqual(result, "streamed-session")
        self.assertEqual(build_streamed.call_args.kwargs["streaming_candidate_limit"], 7)

    def test_compact_artifact_roundtrip_reuses_vectors_before_graph_build(self) -> None:
        runtime, source, observations, lineages, _hashes, snippets, manifest = (
            self._artifact_fixture()
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime,
        ):
            fresh = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id="user_issue56_precomputed_index",
            )
        graph = hybrid.build_authorized_source_backed_effective_graph_view(
            session=fresh,
            source_binding_fingerprint=manifest.index_fingerprint,
        )
        artifact = hybrid.build_authorized_hybrid_observation_index_artifact(
            session=fresh,
            snippet_index=snippets,
            graph_build=graph,
        )
        artifact_manifest = artifact.to_dict()
        self.assertNotIn('"dense_vector":', json.dumps(artifact_manifest))
        loaded_artifact = hybrid.AuthorizedHybridObservationIndexArtifact.from_dict(
            artifact_manifest,
            dense_vector_payload=artifact.dense_vector_payload,
            expected_artifact_fingerprint=artifact.artifact_fingerprint,
        )

        zero_encode_model = _PinnedModel(fail_on_encode=True)
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=_pinned_runtime(zero_encode_model),
        ):
            loaded = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id="user_issue56_precomputed_index",
                precomputed_index_artifact=loaded_artifact,
                expected_precomputed_index_artifact_fingerprint=(
                    loaded_artifact.artifact_fingerprint
                ),
            )
        self.assertEqual(zero_encode_model.call_count, 0)
        self.assertTrue(all(
            isinstance(candidate.dense_vector, PackedDenseVector)
            for candidate in loaded.index.candidates
        ))
        self.assertEqual(loaded.index.index_fingerprint, fresh.index.index_fingerprint)
        self.assertEqual(
            loaded.source_session_binding_fingerprint,
            fresh.source_session_binding_fingerprint,
        )
        loaded_graph = hybrid.build_authorized_source_backed_effective_graph_view(
            session=loaded,
            source_binding_fingerprint=manifest.index_fingerprint,
        )
        self.assertEqual(
            loaded_graph.graph_revision_fingerprint,
            graph.graph_revision_fingerprint,
        )

    def test_artifact_payload_revision_and_missing_lineage_fail_closed(self) -> None:
        runtime, source, observations, lineages, hashes, snippets, manifest = (
            self._artifact_fixture()
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime,
        ):
            session = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id="user_issue56_precomputed_index",
            )
        graph = hybrid.build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=manifest.index_fingerprint,
        )
        artifact = hybrid.build_authorized_hybrid_observation_index_artifact(
            session=session,
            snippet_index=snippets,
            graph_build=graph,
        )
        tampered_payload = bytearray(artifact.dense_vector_payload)
        replacement_vector = [0.0] * ISSUE56_TARGET_DENSE_DIMENSION
        replacement_vector[1] = 1.0
        struct.pack_into(
            f"<{ISSUE56_TARGET_DENSE_DIMENSION}f",
            tampered_payload,
            0,
            *replacement_vector,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "artifact binding mismatch",
        ):
            hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id="user_issue56_precomputed_index",
                precomputed_index_artifact=replace(
                    artifact,
                    _dense_vector_payload=bytes(tampered_payload),
                ),
                expected_precomputed_index_artifact_fingerprint=(
                    artifact.artifact_fingerprint
                ),
            )

        wrong_graph_artifact = replace(
            artifact,
            graph_revision_fingerprint=sha256_json("wrong graph revision"),
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=_pinned_runtime(_PinnedModel(fail_on_encode=True)),
        ):
            wrong_graph_session = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id="user_issue56_precomputed_index",
                precomputed_index_artifact=wrong_graph_artifact,
                expected_precomputed_index_artifact_fingerprint=(
                    wrong_graph_artifact.artifact_fingerprint
                ),
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "graph binding mismatch",
        ):
            hybrid.build_authorized_source_backed_effective_graph_view(
                session=wrong_graph_session,
                source_binding_fingerprint=manifest.index_fingerprint,
            )

        with (
            patch(
                "formowl_mail.hybrid._validated_source_neutral_inputs",
                return_value=(observations, (), hashes),
            ),
            patch(
                "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
                return_value=runtime,
            ),
            self.assertRaisesRegex(
                ContractValidationError,
                "occurrence lineage is incomplete",
            ),
        ):
            hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                retrieval_observations=observations,
                occurrence_lineages=(),
                requester_user_id="user_issue56_precomputed_index",
            )

    def test_compact_payload_size_for_256_bounded_snippets(self) -> None:
        started = perf_counter()
        vector = (1.0, *([0.0] * (ISSUE56_TARGET_DENSE_DIMENSION - 1)))
        bindings = tuple(
            sorted(
                (
                    sha256_json(["observation", index]),
                    sha256_json(["snippet", index]),
                )
                for index in range(256)
            )
        )
        payload = hybrid._pack_precomputed_dense_vectors(
            tuple(vector for _binding in bindings)
        )
        fingerprint = sha256_json("bounded compact artifact")
        artifact = hybrid.AuthorizedHybridObservationIndexArtifact(
            source_access_fingerprint=fingerprint,
            source_session_binding_fingerprint=fingerprint,
            snippet_index_fingerprint=fingerprint,
            graph_revision_fingerprint=fingerprint,
            tokenizer_id="tokenizer_issue56_compact_benchmark",
            profile_fingerprint=fingerprint,
            dense_encoder_id="dense_encoder_issue56_compact_benchmark",
            dense_profile_fingerprint=fingerprint,
            dense_model_id="dense_model_issue56_compact_benchmark",
            dense_model_revision="revision_issue56_compact_benchmark",
            execution_component_fingerprint=fingerprint,
            index_fingerprint=fingerprint,
            dense_vector_payload_fingerprint=sha256_prefixed(payload),
            dense_vector_bindings=bindings,
            _dense_vector_payload=payload,
        )
        manifest = artifact.to_dict()
        loaded = hybrid.AuthorizedHybridObservationIndexArtifact.from_dict(
            manifest,
            dense_vector_payload=payload,
            expected_artifact_fingerprint=artifact.artifact_fingerprint,
        )
        elapsed_ms = (perf_counter() - started) * 1000.0
        expected_bytes = 256 * ISSUE56_TARGET_DENSE_DIMENSION * 4
        full_estimate = 46_826 * ISSUE56_TARGET_DENSE_DIMENSION * 4
        self.assertEqual(len(payload), expected_bytes)
        self.assertEqual(len(loaded.dense_vector_payload), expected_bytes)
        self.assertEqual(full_estimate, 71_924_736)
        print(
            json.dumps(
                {
                    "artifact_compact_benchmark": {
                        "dimension": ISSUE56_TARGET_DENSE_DIMENSION,
                        "elapsed_ms": round(elapsed_ms, 3),
                        "full_row_estimate": 46_826,
                        "full_vector_payload_bytes": full_estimate,
                        "manifest_bytes": len(
                            json.dumps(manifest, separators=(",", ":")).encode()
                        ),
                        "sample_row_count": 256,
                        "sample_vector_payload_bytes": len(payload),
                    }
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
