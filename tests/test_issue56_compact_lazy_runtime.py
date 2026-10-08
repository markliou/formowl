from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import _paths  # noqa: F401
from formowl_auth.postgres import PsycopgOAuthConnection
from formowl_contract import ContractValidationError, sha256_json, to_plain
from formowl_core.dense_embedding import DenseEvidenceVectorCache
from formowl_graph.index.records import PostgreSQLGraphProjectionStore
from formowl_ingestion.storage import AssetStore, ObservationStore
from formowl_mail import hybrid
from formowl_mail import issue56_sealed_source
from formowl_mail.human_uat_orchestrator import _authorized_source_families
from formowl_mail.issue56_sealed_source import APPROVER_ACTOR, WORKSPACE_ID, Issue56IngestionRevision
from formowl_gateway.issue56_sealed_source_loader import (
    build_issue56_production_semantic_retrieval_handler,
)
from formowl_mail.exact import AuthorizedSourceOccurrence, SourceOccurrenceProvider
from formowl_mail.query import (
    build_authorized_observation_snippet_index,
    normalized_authorized_observation_lineages,
    source_occurrence_lineage_from_observation,
)
from formowl_gateway import issue56_sealed_source_loader as sealed_source_loader
import test_issue56_hybrid_batch_encoding as batch_fixture
from test_issue56_uat_handler_composition import _source_start_preparation_fixture


class ProjectionIndependentSourceStartupTests(unittest.TestCase):
    """Actual loader/source reads, synthetic jobs, no PG or provider required."""

    def test_preparation_load_ignores_missing_unsealed_and_unactivated_projection(self):
        """Explicit source-only preparation ignores projection connections.

        State sentinels forbid access; this is not live PG seal/activation proof.
        """
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(Path(directory))
            for state in ("missing", "unsealed", "unactivated"):
                with self.subTest(projection=state):
                    connection = None if state == "missing" else Mock()
                    with (
                        patch.object(issue56_sealed_source, "load_issue56_target_runtime_components",
                                     return_value=fixture.runtime),
                        patch.object(issue56_sealed_source, "build_issue56_ingestion_revision",
                                     side_effect=AssertionError("source start must not build a revision")),
                        patch.object(hybrid, "build_authorized_semantic_observation_session",
                                     side_effect=AssertionError("source start must not build an index")),
                        patch.object(hybrid, "build_authorized_source_backed_effective_graph_view",
                                     side_effect=AssertionError("source start must not build a graph")),
                        patch.object(hybrid, "reopen_authorized_semantic_observation_session",
                                     side_effect=AssertionError("source start must not reopen a projection")),
                        patch.object(type(fixture.runtime.dense_encoder), "encode_evidence_batch",
                                     side_effect=AssertionError("source start must not embed")),
                        patch("formowl_graph.index.records.PostgreSQLGraphProjectionStore") as store,
                    ):
                        # These states describe the independently unavailable
                        # projection, not a manufactured usable seal/session.
                        store.return_value.reopen.side_effect = ContractValidationError(
                            f"projection {state}",
                        )
                        revision = issue56_sealed_source.load_issue56_ingestion_revision(
                            fixture.directory,
                            expected_revision_sha256=fixture.preparation_sha256,
                            projection_connection=connection,
                        )
                        store.assert_not_called()
                    if connection is not None:
                        self.assertEqual(connection.mock_calls, [])
                    self.assertIsNone(revision.session)
                    self.assertIsNone(getattr(revision, "graph_build", None))
                    self.assertTrue(revision.safe_binding["source_start"])
                    self.assertEqual(revision.safe_binding["retrieval_projection_status"], "unavailable")
                    self.assertEqual(revision.safe_binding["source_revision_sha256"], fixture.preparation_sha256)
                    self.assertEqual(revision.source_records.job_authorities, fixture.authorities)
                    for family in ("mail", "document_text"):
                        scan = revision.source_records.scan_authorized_observations(
                            source_family=family,
                            source_scope_ids=(
                                () if family == "mail" else ("project_document",)
                            ),
                            mail_import_session_id=(
                                revision.source_records.authorized_mail_import_session_ids[0]
                                if family == "mail" else None
                            ),
                            max_observations=8192,
                        )
                        self.assertTrue(scan.complete)
                        self.assertTrue(scan.observations)
                        for observation, _scope in scan.observations:
                            self.assertIn(observation, fixture.observations)
                            if family == "document_text":
                                self.assertEqual(observation.modality, "text")
                                self.assertIn("line_start", observation.location)
                                self.assertNotIn("message_occurrence_id", observation.location)
                            else:
                                self.assertEqual(observation.modality, "mail")

    def test_source_start_rejects_metadata_snapshot_and_owner_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(Path(directory), families=("document_text",))
            def load(expected=fixture.preparation_sha256):
                return issue56_sealed_source.load_issue56_ingestion_revision(
                    fixture.directory, expected_revision_sha256=expected,
                )
            with self.assertRaisesRegex(
                issue56_sealed_source.Issue56SealedSourceLoadError, "byte_seal_mismatch",
            ):
                load(sha256_json("wrong preparation bytes"))
            finalized = fixture.directory / "revision.json"
            finalized.write_text('{"artifact_id":"corrupt_finalized_revision"}', encoding="utf-8")
            try:
                # A finalized artifact, even when corrupt, must not silently
                # downgrade to an adjacent independently valid preparation.
                with self.assertRaisesRegex(
                    issue56_sealed_source.Issue56SealedSourceLoadError,
                    "ingestion_revision_byte_seal_mismatch",
                ):
                    load()
            finally:
                finalized.unlink()
            snapshot_path = fixture.directory / "observations.json"
            original = snapshot_path.read_bytes()
            snapshot_path.write_bytes(original + b" ")
            with self.assertRaisesRegex(
                (issue56_sealed_source.Issue56SealedSourceLoadError, ContractValidationError),
                "seal|checkpoint",
            ):
                load()
            snapshot_path.write_bytes(original)
            authority = fixture.authorities[0]
            store = AssetStore(Path(fixture.snapshot["job_store_bindings"][0]["store_directory"]))
            store.create(replace(authority.asset, owner_user_id="user_unauthorized"))
            with self.assertRaisesRegex(ContractValidationError, "asset|authority|permission"):
                load()

    def test_source_start_revalidates_observation_hash_and_native_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(Path(directory), families=("document_text",))
            revision = issue56_sealed_source.load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            paragraph = next(item for item in fixture.observations if item.observation_type == "paragraph")
            store = ObservationStore(Path(fixture.snapshot["job_store_bindings"][0]["store_directory"]))
            # Tampering after startup must not be sheltered by cached authority.
            store.create(replace(paragraph, text="Corrupted source evidence."))
            with self.assertRaisesRegex(ContractValidationError, "Observation binding"):
                revision.source_records.scan_authorized_observations(
                    source_family="document_text", source_scope_ids=("project_document",),
                    max_observations=8192,
                )
            store.create(paragraph)
            lineage = source_occurrence_lineage_from_observation(
                paragraph,
                authorized_source=revision.authorized_source,
            )
            self.assertEqual(lineage.source_observation_id, paragraph.observation_id)
            self.assertEqual(lineage.asset_id, paragraph.asset_id)
            self.assertEqual((lineage.line_start, lineage.line_end), (3, 4))


class ExactCellStreamingLookupTests(unittest.TestCase):
    def test_streaming_shard_reader_retains_only_matching_records(self):
        matching_key = "sha256:" + "a" * 64
        unmatched_key = "sha256:" + "b" * 64
        records = (
            [matching_key, "sha256:" + "c" * 64, False],
            [unmatched_key, "sha256:" + "d" * 64, True],
        )
        payload = b"".join(
            json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"
            for record in records
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "values" / "aa.jsonl"
            path.parent.mkdir()
            path.write_bytes(payload)
            lookup = object.__new__(
                sealed_source_loader._IngestionExactCellLookup
            )
            lookup._directory = root
            lookup._shards = {
                ("value", "aa"): {
                    "size_bytes": len(payload),
                    "record_count": len(records),
                    "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                }
            }
            real_loads = sealed_source_loader.json.loads
            decoded = []

            def loads(value, *args, **kwargs):
                decoded.append(value)
                return real_loads(value, *args, **kwargs)

            with (
                patch.object(Path, "read_bytes", side_effect=AssertionError(
                    "streaming reader must not preload shard bytes"
                )),
                patch.object(
                    sealed_source_loader.json,
                    "loads",
                    side_effect=loads,
                ),
            ):
                selected = lookup._read_matching_shard_records(
                    "value",
                    "aa",
                    matching_keys={matching_key},
                )
        self.assertEqual(selected, (list(records[0]),))
        self.assertEqual(len(decoded), len(records))

    def test_request_candidates_only_scan_protected_identifiers_or_table_filters(self):
        class Profile:
            def __init__(self, protected):
                self.protected = protected
                self.queries = []

            def analyze(self, value):
                self.queries.append(value)
                return SimpleNamespace(
                    protected_identifiers=tuple(
                        SimpleNamespace(exact_token=item)
                        for item in self.protected
                    ),
                    tokens=frozenset({"一般", "自然語言", "token"}),
                )

        def lookup_for(profile):
            lookup = object.__new__(
                sealed_source_loader._IngestionExactCellLookup
            )
            lookup._revision = SimpleNamespace(
                session=SimpleNamespace(
                    index=SimpleNamespace(
                        _runtime_components=SimpleNamespace(
                            tokenizer_profile=profile,
                        ),
                    ),
                ),
            )
            lookup._normalized_columns = {"coo": frozenset({
                "sha256:" + "c" * 64,
            })}
            lookup._manifest = {"counts": {
                "inline_authorized_row": 0,
                "attachment_authorized_row": 0,
                "inline_unresolved_row": 0,
                "attachment_unresolved_row": 0,
                "candidate_only_row": 0,
            }}
            lookup._read_matching_shard_records = Mock(return_value=())
            return lookup

        ordinary_profile = Profile(())
        ordinary = lookup_for(ordinary_profile)
        batch = ordinary.providers_for_request(
            query_text="這是一段沒有料號的自然語句",
            table_query=None,
            authorized_scope_fingerprint="scope",
        )
        self.assertEqual(batch.providers, ())
        ordinary._read_matching_shard_records.assert_not_called()

        identifier_profile = Profile(("MPN-123",))
        identifier = lookup_for(identifier_profile)
        identifier.providers_for_request(
            query_text="查詢 MPN-123 的產地",
            table_query=None,
            authorized_scope_fingerprint="scope",
        )
        identifier._read_matching_shard_records.assert_called_once()
        self.assertEqual(
            identifier._read_matching_shard_records.call_args.args[:2],
            ("value", sha256_json("MPN-123")[7:9]),
        )

        table_profile = Profile(())
        table = lookup_for(table_profile)
        table.providers_for_request(
            query_text="找出 COO",
            table_query={
                "filters": [{"field": "COO", "value": "Japan"}],
                "projection_fields": ["COO"],
            },
            authorized_scope_fingerprint="scope",
        )
        table._read_matching_shard_records.assert_called_once()
        self.assertEqual(
            table._read_matching_shard_records.call_args.args[0],
            "value",
        )


class CompactLazyPageOrderingTests(unittest.TestCase):
    def test_redacted_display_preserves_bound_private_candidate_text(self):
        runtime, source, *_ = batch_fixture.Issue56HybridBatchEncodingTests()._artifact_fixture()
        observation = batch_fixture._observation(
            "display-redaction-fixture", "supplier alpha /workspace/private/part-A17.txt",
        )
        lineage = source_occurrence_lineage_from_observation(
            observation, authorized_source=source,
        )
        snippet = hybrid.build_authorized_observation_snippet_from_bound_record(
            observation, authorized_source=source, occurrence_lineage=lineage,
            expected_observation_hash=sha256_json(observation.to_dict()),
            tokenizer_profile=runtime.tokenizer_profile,
        )
        self.assertNotEqual(snippet.payload["snippet"], observation.text)
        self.assertIn(observation.text, snippet.dense_evidence_text)
        kwargs = dict(
            authorized_source=source, observation=observation,
            occurrence_lineage=lineage, dense_encoder=runtime.dense_encoder,
            tokenizer_profile=runtime.tokenizer_profile, dense_vector=(1.0,) * 384,
        )
        candidate = hybrid._hybrid_candidate_from_observation_snippet(snippet, **kwargs)
        self.assertEqual(candidate.observation_tokens, frozenset(
            runtime.tokenizer_profile.analyze(observation.text).tokens,
        ))
        self.assertEqual(candidate.searchable_tokens, frozenset(snippet.searchable_tokens))
        self.assertEqual(candidate.source_observation_hash, sha256_json(observation.to_dict()))
        self.assertEqual(candidate.dense_evidence_text_hash, sha256_json(snippet.dense_evidence_text))
        with self.assertRaisesRegex(ContractValidationError, "text lineage mismatch"):
            hybrid._hybrid_candidate_from_observation_snippet(
                replace(snippet, payload={**snippet.payload, "snippet": "tampered"}), **kwargs,
            )

    def test_helper_and_node_pages_collate_extracted_id_like_page_index(self):
        connection = Mock(spec=PsycopgOAuthConnection)
        connection.query_all.return_value = []
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="fixture_page_order",
            workspace_id="workspace_page_order",
            binding={"source_binding": sha256_json("page_order_fixture")},
        )
        expression = '(payload->>\'id\') COLLATE "C"'
        page_index = next(
            statement.sql for statement in store.index_statements()
            if "formowl_projection_page ON" in statement.sql
        )
        self.assertIn(f"({expression})", page_index)
        for kind, reader in (("helper", store.iter_helpers), ("node", store.iter_nodes)):
            with self.subTest(kind=kind):
                connection.query_all.reset_mock()
                self.assertEqual(reader(after_id="fixture_cursor", limit=17), [])
                connection.query_all.assert_called_once()
                statement = connection.query_all.call_args.args[0]
                self.assertIn(f"AND {expression} > %(after_id)s", statement.sql)
                self.assertIn(f"ORDER BY {expression} LIMIT %(limit)s", statement.sql)
                self.assertIn("record_type = 'bounded_graph_projection_v1'", statement.sql)
                self.assertIn("workspace_id = %(workspace_id)s", statement.sql)
                self.assertIn("payload->>'revision_id' = %(revision_id)s", statement.sql)
                self.assertIn("payload->>'kind' = %(kind)s", statement.sql)
                self.assertEqual(statement.parameters, {
                    "workspace_id": "workspace_page_order",
                    "revision_id": "fixture_page_order", "kind": kind,
                    "after_id": "fixture_cursor", "limit": 17,
                })


@unittest.skipUnless(
    os.environ.get("FORMOWL_RUN_COMPACT_POSTGRES_FIXTURE") == "1",
    "requires the explicitly approved isolated FormOwl PostgreSQL fixture",
)
class CompactLazyPostgreSQLRuntimeTests(unittest.TestCase):
    """Diagnostic synthetic evidence over real PG; not source coverage or UAT."""

    def test_reference_paged_streaming_build_graph_reopen_query(self):
        import psycopg
        from psycopg.rows import dict_row

        runtime, source, *_ = batch_fixture.Issue56HybridBatchEncodingTests()._artifact_fixture()
        source = replace(source, workspace_id=WORKSPACE_ID)
        observations = tuple(
            batch_fixture._observation(
                f"stream-fixture-{index:03d}",
                "supplier alpha A-1" if index % 2 else "supplier beta B-2",
            ) for index in range(35)
        )
        # Keep the same bounded fixture, now with one genuine parent-bound
        # document row so family narrowing is a real mixed-source operation.
        observations = (*observations[:-2], replace(
            observations[-2], observation_type="email_attachment_occurrence",
            payload={"child_asset_id": "asset_stream_fixture_document"},
        ), replace(
            observations[-1], observation_type="table_row", modality="document",
            asset_id="asset_stream_fixture_document",
            payload={"lineage": {"child_asset_id": "asset_stream_fixture_document"}},
        ))
        lineages = normalized_authorized_observation_lineages(
            observations, authorized_source=source,
            occurrence_lineages=tuple(source_occurrence_lineage_from_observation(
                observation, authorized_source=source,
            ) for observation in observations if observation.modality == "mail"),
        )
        lineage_by_id = {item.source_observation_id: item for item in lineages}
        actor = APPROVER_ACTOR
        binding = {
            "source_access_fingerprint": source.authorization_fingerprint,
            "profile_fingerprint": runtime.tokenizer_profile.profile_fingerprint,
            "dense_profile_fingerprint": runtime.dense_encoder.profile_fingerprint,
        }
        source_binding = {"fixture_source_hash": sha256_json([
            observation.to_dict() for observation in observations
        ])}
        with (
            psycopg.connect(
                host="postgres", dbname="formowl", user="formowl",
                password=Path("/secrets/postgres-password").read_text().strip(),
                row_factory=dict_row, autocommit=True,
            ) as connection,
            tempfile.TemporaryDirectory(dir="/workspace/.test-tmp") as directory,
        ):
            store = PostgreSQLGraphProjectionStore(
                PsycopgOAuthConnection(connection), revision_id=f"stream_fixture_{uuid4().hex}",
                workspace_id=source.workspace_id, binding=binding,
            )
            owner = ObservationStore(directory)
            for observation in observations:
                owner.create(observation)
                store.put_helpers([{
                    "observation_id": observation.observation_id,
                    "observation_hash": sha256_json(observation.to_dict()),
                    "permission_scope": to_plain(observation.permission_scope),
                    "source_families": list(hybrid._semantic_observation_source_families(
                        observation,
                    )),
                    "retrieval_source_family": hybrid._semantic_observation_retrieval_source_family(
                        observation,
                    ),
                    "source_scope_id": source.source_scope_ids[0],
                    "reference": {"observation_id": observation.observation_id},
                    "lineage": to_plain(lineage_by_id[observation.observation_id]),
                }])

            class ReferenceRecords:
                runtime_store = store
                requester_user_id = actor
                workspace_id = source.workspace_id
                job_authorities = ()
                max_page = 0

                def get_observation(self, oid):
                    observation = owner.get(oid)
                    if sha256_json(observation.to_dict()) != self.observation_hash(oid):
                        raise AssertionError("fixture source binding changed")
                    return observation

                def observation_hash(self, oid):
                    return store.get_helper(oid)["observation_hash"]

                def lineage(self, oid):
                    self.get_observation(oid)
                    return lineage_by_id[oid]

                def lineage_by_occurrence(self, occurrence_id, *, after_id=None, limit=64):
                    return tuple(item for item in lineages
                                 if item.occurrence_id == occurrence_id
                                 and (after_id is None or item.source_observation_id > after_id))[:limit]

                def iter_retrieval_pages(self, *, limit):
                    cursor = None
                    # Deliberately smaller pages than the 32-item dense batches.
                    while page := store.iter_helpers(after_id=cursor, limit=min(limit, 3)):
                        self.max_page = max(self.max_page, len(page))
                        yield tuple(self.get_observation(item["observation_id"]) for item in page)
                        cursor = page[-1]["observation_id"]

                def __iter__(self):
                    raise AssertionError("whole source iteration is forbidden")

            records = ReferenceRecords()
            events = []
            with (
                patch("formowl_mail.hybrid._load_pinned_issue56_runtime_components", return_value=runtime),
                patch("formowl_mail.hybrid.build_authorized_observation_snippet_index",
                      side_effect=AssertionError("eager snippet index")),
                patch("formowl_mail.hybrid._validated_source_neutral_inputs",
                      side_effect=AssertionError("eager source normalization")),
                patch.object(store, "put_postings", wraps=store.put_postings) as posting_writes,
            ):
                session = hybrid.build_authorized_semantic_observation_session(
                    authorized_source=source, requester_user_id=actor,
                    source_records=records, runtime_store=store, source_binding=source_binding,
                    dense_vector_cache=DenseEvidenceVectorCache(Path(directory) / "vectors"),
                    dense_build_progress=events.append,
                )
                with (
                    patch.object(store.connection, "query_one", wraps=store.connection.query_one) as one,
                    patch.object(store.connection, "query_all", wraps=store.connection.query_all) as many,
                    patch.object(store.connection, "execute", wraps=store.connection.execute) as execute,
                    patch.object(store, "get_node", wraps=store.get_node) as node_reads,
                    patch.object(store, "document_frequency", wraps=store.document_frequency) as df_reads,
                ):
                    graph = hybrid.build_authorized_source_backed_effective_graph_view(
                        session=session, source_records=records, runtime_store=store,
                        source_binding_fingerprint=sha256_json(source_binding),
                    )
                self.graph_build_sql_counts = {
                    "query_one": one.call_count,
                    "query_all": many.call_count,
                    "execute": execute.call_count,
                    "node_lookups": node_reads.call_count,
                    "document_frequency_batches": df_reads.call_count,
                }
            self.assertEqual(records.max_page, 3)
            self.assertEqual([
                event["candidate_count"] for event in events
                if event["phase"] == "candidate_batch_persisted"
            ], [32, 35])
            manifest = store.reopen(session.index._runtime_store_seal)
            self.assertEqual(
                manifest["view_metadata"]["source_families"],
                sorted({family for observation in observations for family in
                        hybrid._semantic_observation_source_families(observation)}),
            )
            self.assertEqual(manifest["counts"]["candidate"], 35)
            self.assertEqual(graph.observation_node_count, 35)
            # Storage layout changes, but source graph rules/memberships do not.
            snippets, _ = build_authorized_observation_snippet_index(
                observations, authorized_source=source, occurrence_lineages=lineages,
                authorized_observation_hash_by_id={
                    item.observation_id: sha256_json(item.to_dict()) for item in observations
                }, tokenizer_profile=runtime.tokenizer_profile,
            )
            self.assertEqual(
                manifest["counts"]["vector_ref"],
                len({snippet.dense_evidence_text for snippet in snippets.snippets}),
            )
            with patch("formowl_mail.hybrid._load_pinned_issue56_runtime_components", return_value=runtime):
                ordinary = hybrid.build_authorized_semantic_observation_session(
                    authorized_source=source, snippet_index=snippets,
                    authorized_observations=observations, occurrence_lineages=lineages,
                    requester_user_id=actor,
                )
            ordinary_graph = hybrid.build_authorized_source_backed_effective_graph_view(
                session=ordinary, source_binding_fingerprint=sha256_json(source_binding),
            )
            for expected_node in ordinary_graph.effective_graph_view.visible_nodes:
                actual_node = store.get_node(expected_node.node_id).to_dict()
                for key in tuple(actual_node["properties"]):
                    if key.startswith("relation_"):
                        actual_node["properties"].pop(key)
                actual_node["properties"]["source_observation_ids"] = store.observation_ids_for_node(
                    expected_node.node_id, limit=256,
                )
                self.assertEqual(actual_node, expected_node.to_dict())
            for expected_edge in ordinary_graph.effective_graph_view.visible_edges:
                self.assertEqual(store.get_edge(expected_edge.edge_id).to_dict(), expected_edge.to_dict())
            expected_candidates = {
                item.source_observation_hash: item for item in ordinary.index.candidates
            }
            expected_postings = []
            expected_posting_calls = 0
            for start in range(0, len(observations), 32):
                source_batch_postings = []
                for observation in observations[start:start + 32]:
                    candidate = expected_candidates[sha256_json(observation.to_dict())]
                    source_batch_postings.extend({
                        "token": token,
                        "source_observation_hash": candidate.source_observation_hash,
                        "document_length": len(candidate.searchable_tokens),
                    } for token in sorted(candidate.searchable_tokens))
                expected_postings.extend(source_batch_postings)
                expected_posting_calls += (len(source_batch_postings) + 255) // 256
            emitted_postings = []
            for call in posting_writes.call_args_list:
                self.assertGreater(len(call.args[0]), 0)
                self.assertLessEqual(len(call.args[0]), 256)
                emitted_postings.extend(call.args[0])
            self.assertEqual(emitted_postings, expected_postings)
            self.assertEqual(posting_writes.call_count, expected_posting_calls)
            self.assertLess(posting_writes.call_count, len(observations))
            persisted_postings, after_posting = [], None
            while page := store._page("posting", after_id=after_posting, limit=256):
                persisted_postings.extend(item["data"] for item in page)
                after_posting = page[-1]["id"]
            def posting_key(item):
                return item["source_observation_hash"], item["token"]
            self.assertEqual(
                sorted(persisted_postings, key=posting_key),
                sorted(expected_postings, key=posting_key),
            )
            self.posting_batch_counts = {
                "candidates": len(observations), "postings": len(expected_postings),
                "store_calls": posting_writes.call_count,
                "maximum_chunk": max(len(call.args[0]) for call in posting_writes.call_args_list),
            }
            for record in store.iter_candidates(limit=256):
                self.assertEqual(record["candidate_content_fingerprint"],
                    hybrid._hybrid_candidate_content_fingerprint(
                        expected_candidates[record["source_observation_hash"]]
                    ))
            expected_scope = hybrid.authorized_source_occurrence_scope_fingerprint(
                requester_user_id=actor, workspace_id=source.workspace_id,
                source_scope_ids=source.source_scope_ids,
                authorized_observation_hashes=[
                    (observation.observation_id, sha256_json(observation.to_dict()))
                    for observation in observations
                ],
                source_session_binding_fingerprint=session.source_session_binding_fingerprint,
            )
            self.assertEqual(
                manifest["view_metadata"]["session"]["provider_scope_fingerprint"], expected_scope,
            )
            fresh = PostgreSQLGraphProjectionStore(
                PsycopgOAuthConnection(connection), revision_id=store.revision_id,
                workspace_id=source.workspace_id, binding=binding,
            )
            reopened = hybrid.reopen_authorized_semantic_observation_session(
                runtime_store=fresh, expected_seal=manifest["seal_hash"],
                requester_user_id=actor, runtime_components=runtime,
            )
            view = hybrid.reopen_authorized_effective_graph_view(session=reopened)
            handler = build_issue56_production_semantic_retrieval_handler(
                ingestion_revision=Issue56IngestionRevision(
                    observations=(), bundles=(), session=reopened, snippet_index=None,
                    graph_build=replace(graph, effective_graph_view=view),
                    safe_binding={"extraction_coverage": {"source_completeness_certified": False}},
                    source_records=records,
                ),
            )
            capabilities = handler.authorized_capability_summary
            self.assertEqual(_authorized_source_families(capabilities), ("attachment_table", "mail"))
            self.assertEqual(capabilities["providers"], [])
            self.assertEqual(capabilities["listing_status"], "incomplete")
            with (
                patch.object(fresh, "iter_helpers", side_effect=AssertionError("query helper scan")),
                patch.object(fresh, "iter_candidates", side_effect=AssertionError("query candidate scan")),
                patch.object(fresh, "iter_nodes", side_effect=AssertionError("query node scan")),
                patch.object(fresh, "iter_edges", side_effect=AssertionError("query edge scan")),
            ):
                # Normal gateway exact-lookup attachment runs even for an empty
                # provider batch. A real bound nonempty provider uses only keys.
                empty = hybrid.attach_authorized_source_occurrence_providers(reopened, ())
                self.assertEqual(empty.source_occurrence_providers, ())
                exact_query = "List all mail messages involving B-2"
                exact_identifier = hybrid._deterministic_exact_filter_slots(
                    exact_query, tokenizer_profile=runtime.tokenizer_profile,
                ).identifier_hashes[0]
                provider = SourceOccurrenceProvider(
                    provider_id="stream_fixture_provider",
                    inventory_kind_alias="mail_observation",
                    resource_kind="mail_message_occurrence",
                    normalized_field="message.identifier",
                    predicate="source_occurrence_involves",
                    operator="case_insensitive_exact",
                    requester_user_id=actor, workspace_id=source.workspace_id,
                    source_scope_ids=source.source_scope_ids,
                    authorized_scope_fingerprint=expected_scope,
                    unresolved_count=len(observations) - 2,
                    authorized_occurrence_scope_count=len(observations) - 1,
                    extractable_occurrence_scope_count=1,
                    occurrences=(AuthorizedSourceOccurrence(
                        item_hash=sha256_json(lineages[0].occurrence_id),
                        value_bindings=((
                            exact_identifier, sha256_json("B-2"),
                            sha256_json(observations[0].to_dict()),
                            lineages[0].lineage_fingerprint,
                        ),),
                    ),),
                )
                attached = hybrid.attach_authorized_source_occurrence_providers(
                    reopened, (provider,),
                )
                self.assertEqual(attached.source_occurrence_providers, (provider,))
                with self.assertRaisesRegex(ContractValidationError, "provenance binding mismatch"):
                    hybrid.attach_authorized_source_occurrence_providers(
                        reopened, (replace(provider, occurrences=(replace(
                            provider.occurrences[0], value_bindings=((
                                *provider.occurrences[0].value_bindings[0][:3],
                                sha256_json("stale_lineage"),
                            ),),
                        ),)),),
                    )
                with self.assertRaisesRegex(ContractValidationError, "exact binding is invalid"):
                    hybrid.attach_authorized_source_occurrence_providers(
                        reopened, (replace(provider, authorized_scope_fingerprint=sha256_json("stale_scope")),),
                    )
                attachment_provider = replace(
                    provider, provider_id="stream_fixture_attachment_provider",
                    inventory_kind_alias="attachment_table_row",
                    resource_kind="attachment_table_row_occurrence",
                    normalized_field="table.row.cell_value",
                    filter_slot_policy="combined_present_intersection_v1",
                    unresolved_count=0, authorized_occurrence_scope_count=1,
                    occurrences=(AuthorizedSourceOccurrence(
                        item_hash=sha256_json(lineages[-1].occurrence_id),
                        value_bindings=((
                            exact_identifier, sha256_json("B-2"),
                            sha256_json(observations[-1].to_dict()),
                            lineages[-1].lineage_fingerprint,
                        ),),
                    ),),
                )
                attachment_session = hybrid.attach_authorized_source_occurrence_providers(
                    reopened, (attachment_provider,),
                )
                # This source row has no structured column declarations.
                # Accept its genuine provenance, but do not invent projection
                # capabilities to make an attachment exact request succeed.
                with self.assertRaisesRegex(
                    ContractValidationError, "source occurrence provider selection is invalid",
                ):
                    attachment_session.query(
                        query_text="B-2", effective_graph_view=view,
                        exact_inventory_kind=attachment_provider.inventory_kind_alias,
                    )
                reopened = attached
                exact_result = reopened.query(
                    query_text=exact_query, effective_graph_view=view,
                    exact_inventory_kind=provider.inventory_kind_alias,
                )
                self.assertIsNotNone(exact_result.exact_result)
                self.assertEqual(exact_result.exact_result.exact_count, 1)
                self.assertFalse(exact_result.exact_result.coverage.authorized_scope_complete)
                self.assertIn(
                    sha256_json(observations[0].to_dict()), exact_result.answer_citation_hashes,
                )
                result = reopened.query(query_text="supplier alpha A-1", effective_graph_view=view)
                family_query = "supplier beta B-2"
                family_contract = {
                    "original_query_hash": sha256_json(family_query),
                    "query_class": "evidence_lookup",
                    "source_family_scope": ["attachment_table"],
                    "requested_fields": [],
                    "maximum_claim_strength": "cited_evidence",
                }
                scoped = reopened.query(
                    query_text=family_query, request_contract=family_contract,
                    effective_graph_view=view,
                )
                expected_scoped = ordinary.query(
                    query_text=family_query, request_contract=family_contract,
                    effective_graph_view=ordinary_graph.effective_graph_view,
                )
                self.assertEqual(scoped.answer_citation_hashes, expected_scoped.answer_citation_hashes)
                self.assertEqual(scoped.answer_citation_hashes, (sha256_json(observations[-1].to_dict()),))
                self.assertFalse(scoped.lineage_audit.unresolved_evidence_hashes)
                relation_query = "How are A-1 and B-2 related?"
                relation_contract = {
                    "original_query_hash": sha256_json(relation_query),
                    "query_class": "relation_reasoning",
                    "source_family_scope": ["mail", "attachment_table"],
                    "requested_fields": [],
                    "maximum_claim_strength": "bounded_relation",
                }
                relation_trace = hybrid.SemanticPhaseTrace()
                related = reopened.query(
                    query_text=relation_query, request_contract=relation_contract,
                    effective_graph_view=view,
                    allowed_relation_types=tuple(manifest["relation_types"]),
                    phase_trace=relation_trace,
                )
                self.assertEqual(related.query_class, "relation_reasoning")
                # Unobserved free-text concepts must not become aliases merely
                # to make a relation answer pass.
                self.assertEqual(related.status, "no_answer")
                self.assertIn("required_relation_slots_unresolved", related.warnings)
                self.assertEqual(relation_trace.to_safe_dict()["terminal_status"], "completed")
                self.assertFalse(related.lineage_audit.unresolved_evidence_hashes)
                identifier_relation = "A-1 B-2"
                bound_relation = reopened.query(
                    query_text=identifier_relation,
                    request_contract={
                        **relation_contract,
                        "original_query_hash": sha256_json(identifier_relation),
                    },
                    effective_graph_view=view,
                    allowed_relation_types=tuple(manifest["relation_types"]),
                    allowed_directions=("out", "in"),
                )
                self.assertTrue(bound_relation.answer_citation_hashes, bound_relation.warnings)
                self.assertFalse(bound_relation.lineage_audit.unresolved_evidence_hashes)
            self.assertTrue(result.answer_citation_hashes)
            self.assertFalse(result.lineage_audit.unresolved_evidence_hashes)

    def test_build_persist_reopen_normal_hybrid_query_without_corpus_iteration(self):
        import psycopg
        from psycopg.rows import dict_row

        runtime, source, *_ = batch_fixture.Issue56HybridBatchEncodingTests()._artifact_fixture()
        observations = tuple(
            batch_fixture._observation(
                f"compact-fixture-{index}",
                "supplier alpha part A-1" if index < 2 else "supplier beta part B-2",
            )
            for index in range(3)
        )
        lineages = tuple(
            source_occurrence_lineage_from_observation(item, authorized_source=source)
            for item in observations
        )
        hashes = {item.observation_id: sha256_json(item.to_dict()) for item in observations}
        snippets, _ = build_authorized_observation_snippet_index(
            observations, authorized_source=source, occurrence_lineages=lineages,
            authorized_observation_hash_by_id=hashes,
            tokenizer_profile=runtime.tokenizer_profile,
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime,
        ):
            session = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source, snippet_index=snippets,
                authorized_observations=observations, occurrence_lineages=lineages,
                requester_user_id="user_compact_fixture",
            )
        index = session.index
        graph = hybrid.build_authorized_source_backed_effective_graph_view(
            session=session, source_binding_fingerprint=snippets.index_fingerprint,
        )
        expected_semantic = session.query(
            query_text="supplier alpha",
            effective_graph_view=graph.effective_graph_view,
        )
        self.assertTrue(expected_semantic.answer_citation_hashes)
        expected = index.query(
            query_text="supplier alpha part A-1", query_class="evidence_lookup",
            candidate_limit=2,
        )
        binding = {
            "source_access_fingerprint": source.authorization_fingerprint,
            "profile_fingerprint": runtime.tokenizer_profile.profile_fingerprint,
            "dense_profile_fingerprint": runtime.dense_encoder.profile_fingerprint,
            "index_fingerprint": index.index_fingerprint,
        }
        with (
            psycopg.connect(
                host="postgres", dbname="formowl", user="formowl",
                password=Path("/secrets/postgres-password").read_text().strip(),
                row_factory=dict_row, autocommit=True,
            ) as connection,
            tempfile.TemporaryDirectory(dir="/workspace/.test-tmp") as directory,
        ):
            store = PostgreSQLGraphProjectionStore(
                PsycopgOAuthConnection(connection),
                revision_id=f"compact_fixture_{uuid4().hex}",
                workspace_id=source.workspace_id, binding=binding,
            )
            source_store = ObservationStore(directory)
            references = {}
            for observation in observations:
                source_store.create(observation)
                references[observation.observation_id] = {
                    "store_directory": directory,
                    "observation_id": observation.observation_id,
                }
            metadata = hybrid.persist_authorized_semantic_observation_session(
                session=session, graph_build=graph, runtime_store=store,
                source_references=references,
            )
            self.assertEqual(
                metadata["source_families"],
                list(hybrid._semantic_session_source_families(session)),
            )
            manifest = store.seal(metadata, binding)
            self.assertEqual(manifest["counts"]["candidate"], 3)
            # Reopen from durable database state, not the writer's manifest cache.
            store = PostgreSQLGraphProjectionStore(
                PsycopgOAuthConnection(connection), revision_id=store.revision_id,
                workspace_id=source.workspace_id, binding=binding,
            )
            calls_before = runtime.dense_encoder._model.call_count
            reopened = hybrid.reopen_authorized_hybrid_index(
                runtime_store=store, expected_seal=manifest["seal_hash"],
                runtime_components=runtime,
            )
            self.assertEqual(runtime.dense_encoder._model.call_count, calls_before)
            reopened_session = hybrid.reopen_authorized_semantic_observation_session(
                runtime_store=store, expected_seal=manifest["seal_hash"],
                requester_user_id=session.requester_user_id, runtime_components=runtime,
            )
            reopened_view = hybrid.reopen_authorized_effective_graph_view(
                session=reopened_session,
            )
            with (
                patch.object(store, "iter_helpers", side_effect=AssertionError("full helper scan")),
                patch.object(store, "iter_nodes", side_effect=AssertionError("full graph scan")),
                patch.object(store, "iter_edges", side_effect=AssertionError("full edge scan")),
                patch.object(store, "get_dense_vector", side_effect=AssertionError("vector expansion")),
            ):
                actual = reopened.query(
                    query_text="supplier alpha part A-1", query_class="evidence_lookup",
                    candidate_limit=2,
                )
                actual_semantic = reopened_session.query(
                    query_text="supplier alpha", effective_graph_view=reopened_view,
                )
            self.assertEqual(actual.to_safe_dict(), expected.to_safe_dict())
            self.assertEqual(actual_semantic.to_safe_dict(), expected_semantic.to_safe_dict())
            self.assertTrue(actual.answer_citation_hashes)
            # The duplicate dense text remains two independent ranked occurrences.
            vector = runtime.dense_encoder.encode_query("supplier alpha part A-1")
            ranked = store.hybrid_ranked(
                query_tokens=tuple(runtime.tokenizer_profile.analyze(
                    "supplier alpha part A-1"
                ).tokens),
                query_vector=vector, limit=2, timeout_ms=1500,
                allowed_source_observation_hashes=None,
            )
            self.assertEqual(
                sorted(row["dense_rank"] for row in ranked if row["dense_rank"] <= 2),
                [1, 2],
            )


if __name__ == "__main__":
    unittest.main()
