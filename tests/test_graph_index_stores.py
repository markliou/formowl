from __future__ import annotations

import unittest
import os
import math
from pathlib import Path
import uuid
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Grant, PermissionScope
from formowl_graph.index import (
    FileGraphProjectionStore,
    FileVectorStore,
    GraphProjectionEdge,
    GraphProjectionNode,
    VectorRecord,
)

NOW = "2026-06-18T00:00:00+00:00"


class GraphIndexStoreTests(unittest.TestCase):
    def test_candidate_resume_checkpoint_is_bound_single_key_mock_db(self) -> None:
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="resume_revision", workspace_id="resume_workspace",
            binding={"source": sha256_json("source")},
        )
        fingerprint = sha256_json({"source": "fixture", "profile": "fixture"})
        data = {"source_cursor": "observation_1", "candidate_count": 1,
                "resume_fingerprint": fingerprint}
        payload = {
            "revision_id": store.revision_id, "binding_hash": store._binding_hash,
            "kind": "checkpoint", "id": "candidate_build_progress_v1", "data": data,
        }
        connection.query_one.return_value = None
        self.assertIsNone(store.hybrid_build_checkpoint(resume_fingerprint=fingerprint))
        connection.query_one.assert_called_once()
        self.assertEqual(
            connection.query_one.call_args.args[0].parameters["record_id"],
            store._key("checkpoint", "candidate_build_progress_v1"),
        )
        connection.query_all.assert_not_called()
        for change in ({}, {"candidate_count": True}, {"candidate_count": 0},
                       {"source_cursor": "../invalid"},
                       {"resume_fingerprint": sha256_json("changed profile/source")}):
            with self.subTest(change=change):
                candidate = {**payload, "data": {**data, **change}}
                connection.query_one.return_value = {
                    "payload": candidate, "payload_hash": sha256_json(candidate),
                }
                if change:
                    with self.assertRaises(
                        ValueError if "source_cursor" in change else ContractValidationError,
                    ):
                        store.hybrid_build_checkpoint(resume_fingerprint=fingerprint)
                else:
                    self.assertEqual(
                        store.hybrid_build_checkpoint(resume_fingerprint=fingerprint), data,
                    )
        for change in ({"revision_id": "other_revision"}, {"binding_hash": sha256_json("other")}):
            candidate = {**payload, **change}
            connection.query_one.return_value = {
                "payload": candidate, "payload_hash": sha256_json(candidate),
            }
            with self.assertRaisesRegex(ContractValidationError, "record seal mismatch"):
                store.hybrid_build_checkpoint(resume_fingerprint=fingerprint)

    def test_candidate_batch_progress_commits_after_writes_mock_db(self) -> None:
        """Mock transaction calls only; live database durability is not asserted."""
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="resume_revision", workspace_id="resume_workspace",
            binding={"source": sha256_json("source")},
        )
        fingerprint, source_hash = sha256_json("profile/source"), sha256_json("observation")
        helper = {"observation_id": "observation_2", "observation_hash": source_hash}
        checkpoint = {"source_cursor": "observation_1", "candidate_count": 1,
                      "resume_fingerprint": fingerprint}
        with (
            patch.object(store, "_get", return_value={"data": {"sealed": False}}),
            patch.object(store, "hybrid_build_checkpoint", return_value=checkpoint),
            patch.object(store, "get_helper", return_value=helper),
            patch.object(store, "helpers_for_hashes", return_value={source_hash: helper}),
            patch.object(store, "_put_postings"),
            patch.object(store, "_put_dense_vectors"),
            patch.object(store, "_put_candidates") as candidates,
            patch.object(store, "_put") as put,
        ):
            def persist(count=2):
                store.persist_hybrid_batch(
                    (), (), [{"ordinal": count - 1, "source_observation_hash": source_hash}],
                    batch_id=f"candidates_{count}", source_cursor="observation_2",
                    binding=store.binding, candidate_count=count, resume_fingerprint=fingerprint,
                )
            candidates.side_effect = RuntimeError("synthetic batch failure")
            with self.assertRaisesRegex(RuntimeError, "synthetic batch"):
                persist()
            put.assert_not_called()
            connection.rollback.assert_called_once()
            connection.commit.assert_not_called()
            candidates.side_effect = None
            persist()
            self.assertEqual(put.call_args_list[-1].args, (
                "checkpoint", "candidate_build_progress_v1",
                {**checkpoint, "source_cursor": "observation_2", "candidate_count": 2},
            ))
            connection.commit.assert_called_once()
            put.reset_mock()
            with self.assertRaisesRegex(ContractValidationError, "does not advance"):
                persist(count=4)
            put.assert_not_called()

    def test_candidate_batch_reuses_helper_binding_lookup_mock_db(self) -> None:
        """Checkpoint validation must not fetch the candidate helpers twice."""
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        binding = {"source": sha256_json("source")}
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="resume_revision", workspace_id="resume_workspace",
            binding=binding,
        )
        fingerprint = sha256_json({"source": "profile"})
        source_hash = sha256_json("observation")
        helper = {"observation_id": "observation_2", "observation_hash": source_hash}
        candidate = {
            "source_observation_hash": source_hash,
            "dense_evidence_text_hash": sha256_json("text"),
            "searchable_tokens": ["anchor"],
            "ordinal": 1,
            "bundle_id": "bundle",
            "message_occurrence_hash": sha256_json("occurrence"),
        }
        with (
            patch.object(store, "_get", return_value={"data": {"sealed": False}}),
            patch.object(
                store, "hybrid_build_checkpoint",
                return_value={
                    "source_cursor": "observation_1",
                    "candidate_count": 1,
                    "resume_fingerprint": fingerprint,
                },
            ),
            patch.object(
                store, "helpers_for_hashes", return_value={source_hash: helper},
            ) as helper_lookup,
            patch.object(store, "get_helper") as get_helper,
            patch.object(store, "_put_postings"),
            patch.object(store, "_put_dense_vectors"),
            patch.object(store, "_put_many"),
            patch.object(store, "_put"),
        ):
            store.persist_hybrid_batch(
                (), (), [candidate],
                batch_id="candidates_2", source_cursor="observation_2",
                binding=binding, candidate_count=2,
                resume_fingerprint=fingerprint,
            )

        self.assertEqual(helper_lookup.call_count, 1)
        self.assertEqual(tuple(helper_lookup.call_args.args[0]), (source_hash,))
        get_helper.assert_not_called()

    def test_candidate_batch_rejects_helper_identity_and_checkpoint_mismatches(self) -> None:
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        binding = {"source": sha256_json("source")}
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="resume_revision", workspace_id="resume_workspace",
            binding=binding,
        )
        fingerprint = sha256_json({"source": "profile"})
        source_hash = sha256_json("observation")
        candidate = {
            "source_observation_hash": source_hash,
            "dense_evidence_text_hash": sha256_json("text"),
            "searchable_tokens": ["anchor"],
            "ordinal": 1,
            "bundle_id": "bundle",
            "message_occurrence_hash": sha256_json("occurrence"),
        }
        checkpoint = {
            "source_cursor": "cursor_1",
            "candidate_count": 1,
            "resume_fingerprint": fingerprint,
        }

        def row(*, payload_id: str, observation_id: str, observation_hash: str) -> dict:
            data = {"observation_id": observation_id, "observation_hash": observation_hash}
            payload = {
                "revision_id": store.revision_id,
                "binding_hash": store._binding_hash,
                "kind": "helper",
                "id": payload_id,
                "data": data,
                "observation_hash": source_hash,
            }
            return {"payload": payload, "payload_hash": sha256_json(payload)}

        cases = (
            (
                "payload_identity",
                row(
                    payload_id="wrong_payload_id", observation_id="cursor_2",
                    observation_hash=source_hash,
                ),
                "graph projection record identity mismatch",
            ),
            (
                "checkpoint_cursor",
                row(
                    payload_id="cursor_other", observation_id="cursor_other",
                    observation_hash=source_hash,
                ),
                "checkpoint source binding mismatch",
            ),
            (
                "helper_hash",
                row(
                    payload_id="cursor_2", observation_id="cursor_2",
                    observation_hash=sha256_json("other observation"),
                ),
                "graph projection record identity mismatch",
            ),
        )
        with (
            patch.object(store, "_get", return_value={"data": {"sealed": False}}),
            patch.object(store, "hybrid_build_checkpoint", return_value=checkpoint),
            patch.object(store, "_put_postings"),
            patch.object(store, "_put_dense_vectors"),
            patch.object(store, "_put_many"),
            patch.object(store, "_put") as put,
        ):
            for name, helper_row, expected_error in cases:
                with self.subTest(name=name):
                    connection.query_all.reset_mock()
                    connection.rollback.reset_mock()
                    connection.commit.reset_mock()
                    put.reset_mock()
                    connection.query_all.return_value = [helper_row]
                    with self.assertRaisesRegex(ContractValidationError, expected_error):
                        store.persist_hybrid_batch(
                            (), (), [candidate], batch_id="candidates_2",
                            source_cursor="cursor_2", binding=binding, candidate_count=2,
                            resume_fingerprint=fingerprint,
                        )
                    connection.query_all.assert_called_once()
                    self.assertIn(
                        "payload->>'observation_hash'",
                        connection.query_all.call_args.args[0].sql,
                    )
                    connection.rollback.assert_called_once()
                    connection.commit.assert_not_called()
                    put.assert_not_called()

    def test_candidate_order_retry_restarts_stable_keys_mock_db(self) -> None:
        """Exercise the real finalizer; mock SQL I/O is not PostgreSQL proof."""
        from copy import deepcopy
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="resume_revision", workspace_id="resume_workspace",
            binding={"source": sha256_json("source")},
        )
        original = [{
            "source_observation_hash": sha256_json(str(index)),
            "bundle_id": "fixture_bundle", "message_occurrence_hash": sha256_json("occurrence"),
            "ordinal": 9, "searchable_tokens": ["anchor"],
        } for index in range(2)]
        current = deepcopy(original)
        def query(statement):
            if "bundle" not in statement.parameters:
                return []  # No posting rows needed for this candidate-order diagnostic.
            after = tuple(statement.parameters[key] for key in ("bundle", "observation", "occurrence"))
            rows = sorted(current, key=lambda item: (
                item["bundle_id"], item["source_observation_hash"], item["message_occurrence_hash"],
            ))
            result = []
            for item in rows:
                key = (item["bundle_id"], item["source_observation_hash"],
                       item["message_occurrence_hash"])
                if key <= after:
                    continue
                payload = {
                    "revision_id": store.revision_id, "binding_hash": store._binding_hash,
                    "kind": "candidate", "id": item["source_observation_hash"], "data": item,
                }
                result.append({"payload": payload, "payload_hash": sha256_json(payload)})
            return result[:1]  # Force two bounded finalization batches.
        def put(items):
            for item in items:
                index = next(i for i, old in enumerate(current)
                             if old["source_observation_hash"] == item["source_observation_hash"])
                current[index] = deepcopy(item)
        connection.query_all.side_effect = query
        with (
            patch.object(store, "put_candidates", side_effect=put),
            patch.object(store, "put_token_statistics"),
            patch.object(store, "put_corpus_statistics"),
            patch.object(store, "checkpoint") as checkpoint,
        ):
            expected = store.finalize_candidate_order_and_statistics()
            expected_rows = deepcopy(current)
            current = deepcopy(original)
            checkpoint.side_effect = RuntimeError("synthetic post-order-batch interruption")
            with self.assertRaisesRegex(RuntimeError, "post-order-batch"):
                store.finalize_candidate_order_and_statistics()
            self.assertEqual(sorted(item["ordinal"] for item in current), [0, 9])
            checkpoint.side_effect = None
            self.assertEqual(store.finalize_candidate_order_and_statistics(), expected)
            self.assertEqual(current, expected_rows)

    def test_postgres_document_family_query_ports_mock_db_diagnostic(self) -> None:
        """Inspect real query ports/SQL with mock I/O, not live PostgreSQL."""
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="revision_fixture", workspace_id="workspace_fixture",
            binding={"source_seal": sha256_json("fixture source")},
        )
        records = {}
        for kind, record_id, data in (
            ("state", "manifest", {"sealed": True}),
            ("corpus_stat", "corpus", {"document_count": 1, "average_document_length": 1}),
        ):
            payload = {
                "revision_id": store.revision_id, "binding_hash": store._binding_hash,
                "kind": kind, "id": record_id, "data": data,
            }
            records[store._key(kind, record_id)] = {
                "payload": payload, "payload_hash": sha256_json(payload),
            }
        connection.query_one.side_effect = lambda statement: records[
            statement.parameters["record_id"]
        ]
        source_hash = sha256_json("fixture observation")
        ranked = [{"source_observation_hash": source_hash, "ordinal": 0}]
        calls = (
            ("count", lambda families: store.candidate_count_for_families(families),
             [{"candidate_count": 1}], 1, 1500),
            ("hybrid", lambda families: store.hybrid_ranked(
                query_tokens=("anchor",), query_vector=[1.0] + [0.0] * 383,
                limit=1, timeout_ms=1000, requested_source_families=families,
                allowed_source_observation_hashes=(source_hash,),
            ), ranked, ranked, 1000),
            ("tokens", lambda families: store.candidate_tokens_present(
                ("anchor",), "observation_tokens", requested_source_families=families,
            ), [{"token": "anchor"}], {"anchor"}, 1500),
            ("nodes", lambda families: store.node_candidates_by_terms(
                tokens=("anchor",), term_hashes=(), requested_source_families=families,
            ), [], [], 1500),
        )
        for families in (
            ("document_text",), ("mail",), ("attachment_table",),
            ("mail", "document_text", "attachment_table", "document_text"),
        ):
            for name, invoke, rows, expected, timeout in calls:
                with self.subTest(families=families, port=name):
                    connection.reset_mock()
                    connection.query_all.return_value = rows
                    self.assertEqual(invoke(families), expected)
                    connection.query_all.assert_called_once()
                    statement = connection.query_all.call_args.args[0]
                    self.assertEqual(statement.parameters["families"], sorted(set(families)))
                    self.assertFalse(statement.parameters.get("families_unrestricted", False))
                    self.assertEqual(statement.parameters["workspace_id"], store.workspace_id)
                    self.assertEqual(statement.parameters["revision_id"], store.revision_id)
                    self.assertIn("workspace_id = %(workspace_id)s", statement.sql)
                    self.assertIn("payload->>'revision_id' = %(revision_id)s", statement.sql)
                    self.assertIn(
                        "h.payload->'data'->>'retrieval_source_family' = ANY(%(families)s)",
                        statement.sql,
                    )
                    if name != "nodes":
                        self.assertIn(store._candidate_family_sql(), statement.sql)
                    if name == "hybrid":
                        self.assertEqual(statement.parameters["binding"], store._binding_hash)
                        self.assertEqual(statement.parameters["allowed"], [source_hash])
                        self.assertFalse(statement.parameters["unrestricted"])
                        self.assertIn("v.embedding_manifest_hash = %(binding)s", statement.sql)
                    connection.begin.assert_called_once()
                    connection.commit.assert_called_once()
                    connection.rollback.assert_not_called()
                    self.assertEqual(
                        connection.execute.call_args.args[0].parameters, {"timeout": str(timeout)},
                    )

    def test_postgres_unknown_family_query_ports_reject_before_mock_db(self) -> None:
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="revision_fixture", workspace_id="workspace_fixture",
            binding={"source_seal": sha256_json("fixture source")},
        )
        calls = (
            lambda: store.candidate_count_for_families(("document_text", "unknown")),
            lambda: store.hybrid_ranked(
                query_tokens=("anchor",), query_vector=[1.0] + [0.0] * 383,
                limit=1, timeout_ms=1000,
                requested_source_families=("document_text", "unknown"),
            ),
            lambda: store.candidate_tokens_present(
                ("anchor",), "observation_tokens",
                requested_source_families=("document_text", "unknown"),
            ),
            lambda: store.node_candidates_by_terms(
                tokens=("anchor",), term_hashes=(),
                requested_source_families=("document_text", "unknown"),
            ),
        )
        for index, invoke in enumerate(calls):
            with self.subTest(port=index):
                with self.assertRaisesRegex(
                    ContractValidationError, "requested source family is invalid",
                ):
                    invoke()
                self.assertEqual(connection.mock_calls, [])

    def test_postgres_helpers_can_page_retrieval_family_without_unfiltered_prefix(
        self,
    ) -> None:
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        binding = {"source_seal": sha256_json("fixture source")}
        store = PostgreSQLGraphProjectionStore(
            connection,
            revision_id="revision_fixture",
            workspace_id="workspace_fixture",
            binding=binding,
        )
        helper = {
            "observation_id": "observation_mail_001",
            "observation_hash": sha256_json("observation_mail_001"),
            "source_scope_id": "mail_scope",
            "reference": {"job_index": 0},
            "lineage": {"fixture": True},
            "permission_scope": {
                "scope_type": "public",
                "visibility": "public",
            },
            "retrieval": True,
            "retrieval_source_family": "mail",
        }
        payload = {
            "revision_id": store.revision_id,
            "binding_hash": store._binding_hash,
            "kind": "helper",
            "id": helper["observation_id"],
            "data": helper,
            "observation_hash": helper["observation_hash"],
        }
        connection.query_all.return_value = [
            {"payload": payload, "payload_hash": sha256_json(payload)}
        ]

        result = store.iter_helpers_for_source_family("mail")

        self.assertEqual(result, [helper])
        statement = connection.query_all.call_args.args[0]
        self.assertIn("payload->'data'->>'retrieval' = 'true'", statement.sql)
        self.assertIn(
            "payload->'data'->>'retrieval_source_family' = %(source_family)s",
            statement.sql,
        )
        self.assertEqual(statement.parameters["source_family"], "mail")

    def test_postgres_candidates_batch_loads_helpers_once(self) -> None:
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        binding = {"source_seal": sha256_json("fixture source")}
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="revision_fixture", workspace_id="workspace_fixture",
            binding=binding,
        )
        source_hashes = [sha256_json(f"observation_{index}") for index in range(2)]
        helpers = []
        for index, observation_hash in enumerate(source_hashes):
            helper = {
                "observation_id": f"observation_{index}",
                "observation_hash": observation_hash,
                "source_scope_id": "fixture_scope",
                "reference": {"observation_id": f"observation_{index}"},
                "lineage": {"fixture": index},
                "permission_scope": {
                    "scope_type": "public", "visibility": "public",
                },
            }
            payload = {
                "revision_id": store.revision_id, "binding_hash": store._binding_hash,
                "kind": "helper", "id": helper["observation_id"], "data": helper,
                "observation_hash": observation_hash,
            }
            helpers.append({"payload": payload, "payload_hash": sha256_json(payload)})
        connection.query_all.return_value = helpers
        candidates = [{
            "source_observation_hash": source_hashes[index],
            "dense_evidence_text_hash": sha256_json(f"text_{index}"),
            "searchable_tokens": [f"token_{index}"],
            "ordinal": index,
            "bundle_id": f"bundle_{index}",
            "message_occurrence_hash": sha256_json(f"occurrence_{index}"),
        } for index in range(2)]

        store._put_candidates(candidates)

        connection.query_all.assert_called_once()
        connection.execute.assert_called_once()

    def test_source_family_lexical_sql_uses_qualified_collation_and_keeps_guards(self) -> None:
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore

        connection = Mock()
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id="lexical_fixture", workspace_id="workspace_fixture",
            binding={"source_seal": sha256_json("lexical source")},
        )
        source_hash = sha256_json("lexical observation")
        connection.query_all.return_value = [{"observation_hash": source_hash}]
        with patch.object(store, "_get", return_value={"data": {"sealed": True}}):
            for family in ("mail", "document_text"):
                with self.subTest(family=family):
                    connection.reset_mock()
                    self.assertEqual(store.source_family_lexical_lookup(
                        ("beta", "alpha", "alpha"), source_family=family,
                        limit=2, timeout_ms=500,
                    ), [source_hash])
                    statement = connection.query_all.call_args.args[0]
                    self.assertIn(
                        "(p.payload->'data'->>'source_observation_hash') COLLATE \"C\"",
                        statement.sql,
                    )
                    self.assertNotIn('observation_hash COLLATE "C"', statement.sql)
                    self.assertIn("h.workspace_id = p.workspace_id", statement.sql)
                    self.assertIn(
                        "h.payload->>'revision_id' = p.payload->>'revision_id'", statement.sql,
                    )
                    self.assertIn(
                        "COUNT(DISTINCT p.payload->>'token') DESC", statement.sql,
                    )
                    # Match the existing digest expression index, then recheck
                    # raw tokens so a digest collision cannot admit evidence.
                    self.assertIn(
                        "AND md5(p.payload->>'token') = ANY(ARRAY("
                        "SELECT md5(t.token) FROM unnest(%(tokens)s::text[]) AS t(token))) "
                        "AND p.payload->>'token' = ANY(%(tokens)s)",
                        statement.sql,
                    )
                    self.assertIn(
                        "md5(payload->>'token')",
                        next(
                            index.sql for index in store.index_statements()
                            if "formowl_projection_token ON" in index.sql
                        ),
                    )
                    self.assertIn(
                        "AND h.payload->'data'->>'retrieval_source_family' = %(source_family)s "
                        "GROUP BY observation_hash",
                        statement.sql,
                    )
                    self.assertEqual(statement.sql.count("LIMIT "), 1)
                    self.assertTrue(statement.sql.endswith("LIMIT %(limit)s"))
                    self.assertEqual(statement.parameters, {
                        "workspace_id": store.workspace_id, "revision_id": store.revision_id,
                        "tokens": ["alpha", "beta"], "source_family": family, "limit": 2,
                    })
                    self.assertEqual(
                        connection.execute.call_args.args[0].parameters, {"timeout": "500"},
                    )
                    connection.begin.assert_called_once()
                    connection.commit.assert_called_once()
                    connection.rollback.assert_not_called()
            connection.reset_mock()
            connection.query_all.side_effect = RuntimeError("synthetic SQL failure")
            with self.assertRaisesRegex(RuntimeError, "synthetic SQL failure"):
                store.source_family_lexical_lookup(
                    ("alpha",), source_family="mail", timeout_ms=500,
                )
            connection.rollback.assert_called_once()
            connection.commit.assert_not_called()

    @unittest.skipUnless(
        os.environ.get("FORMOWL_TEST_PROJECTION_POSTGRES_PASSWORD_FILE"),
        "isolated PostgreSQL fixture not configured",
    )
    def test_postgres_projection_build_reopen_bounded_rank_query(self) -> None:
        import psycopg
        from psycopg.rows import dict_row
        from formowl_auth.postgres import PsycopgOAuthConnection
        from formowl_contract import sha256_json
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore
        from dataclasses import replace
        from unittest.mock import patch

        sql_counts = {}

        def measured(name, action):
            with (
                patch.object(connection, "execute", wraps=connection.execute) as execute,
                patch.object(connection, "query_one", wraps=connection.query_one) as query_one,
                patch.object(connection, "query_all", wraps=connection.query_all) as query_all,
            ):
                result = action()
            sql_counts[name] = {
                "insert": sum(
                    call.args[0].sql.startswith((
                        "INSERT INTO formowl_graph_records", "INSERT INTO formowl_vector_index",
                    ))
                    for call in execute.call_args_list
                ),
                "read": query_one.call_count + query_all.call_count,
            }
            return result

        raw = psycopg.connect(
            host="postgres", dbname="formowl", user="formowl",
            password=Path(os.environ["FORMOWL_TEST_PROJECTION_POSTGRES_PASSWORD_FILE"]).read_text(),
            row_factory=dict_row, autocommit=True,
        )
        self.addCleanup(raw.close)
        # Session-local fixture tables: never replace deployed owner indexes.
        for table in ("formowl_graph_records", "formowl_vector_index"):
            raw.execute(
                f"CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING DEFAULTS)"
            )
        raw.execute("ALTER TABLE formowl_graph_records ADD PRIMARY KEY (record_id)")
        raw.execute("ALTER TABLE formowl_vector_index ADD PRIMARY KEY (vector_id)")
        connection = PsycopgOAuthConnection(raw)
        for statement in PostgreSQLGraphProjectionStore.index_statements():
            connection.execute(statement)
        binding = {"source_seal": sha256_json("fixture source"), "profile": sha256_json("fixture profile")}
        revision_id = "test_projection_" + uuid.uuid4().hex
        store = PostgreSQLGraphProjectionStore(
            connection, revision_id=revision_id, workspace_id="workspace_fixture", binding=binding,
        )
        scope = PermissionScope(scope_type="public", visibility="public").to_dict()
        nodes = [_projection_node(f"node_{i}", f"obs_{i}", scope) for i in range(3)]
        nodes = [replace(node, properties={
            **node.properties,
            "relation_searchable_tokens": ["anchor"] if i < 2 else [],
            "relation_source_term_hashes": [sha256_json("source_term")] if i == 2 else [],
            "relation_protected_term_hashes": [sha256_json("protected")] if i == 0 else [],
        }) for i, node in enumerate(nodes)]
        store.checkpoint("fixture_initialized", "", binding)
        measured("nodes", lambda: store.put_nodes(nodes))
        self.assertEqual(sql_counts["nodes"], {"insert": 1, "read": 1})
        edges = [
            _projection_edge(f"edge_{i}", f"node_{i}", "node_2", scope) for i in range(2)
        ]
        measured("edges", lambda: store.put_edges(edges))
        self.assertEqual(sql_counts["edges"], {"insert": 1, "read": 2})
        measured("memberships", lambda: store.put_memberships([
            (f"node_{i}", f"obs_{i}") for i in range(3)
        ]))
        self.assertEqual(sql_counts["memberships"], {"insert": 1, "read": 2})
        self.assertEqual(
            {key: node.to_dict() for key, node in store.get_nodes(
                ["node_0", "node_2", "node_absent"]
            ).items()},
            {node.node_id: node.to_dict() for node in (nodes[0], nodes[2])},
        )
        with self.assertRaisesRegex(ContractValidationError, "endpoint unavailable"):
            store.put_edges([
                _projection_edge("edge_rollback", "node_0", "node_1", scope),
                _projection_edge("edge_missing", "node_0", "node_absent", scope),
            ])
        self.assertIsNone(store.get_edge("edge_rollback"))
        with self.assertRaisesRegex(ContractValidationError, "membership node unavailable"):
            store.put_memberships([("node_0", "obs_rollback"), ("node_absent", "obs_missing")])
        self.assertEqual(store.nodes_for_observation("obs_rollback"), [])
        self.assertEqual([n.node_id for n in store.iter_nodes(limit=2)], ["node_0", "node_1"])
        self.assertEqual([n.node_id for n in store.iter_nodes(after_id="node_1")], ["node_2"])
        self.assertEqual([n.node_id for n in store.nodes_for_observation("obs_2")], ["node_2"])
        self.assertEqual([e.edge_id for e in store.incident_edges("node_2")], ["edge_0", "edge_1"])
        self.assertEqual(store.edge_for_hash(sha256_json("edge_0")).edge_id, "edge_0")
        hashes = [sha256_json(f"obs_{i}") for i in range(3)]
        texts = [sha256_json("text_A"), sha256_json("text_B")]
        helpers = [{
            "observation_id": f"obs_{i}", "observation_hash": hashes[i],
            "source_scope_id": "fixture_scope", "reference": {"observation_id": f"obs_{i}"},
            "lineage": {"fixture_occurrence": i}, "permission_scope": scope,
            "source_families": ["attachment_table"] if i == 0 else (["mail"] if i == 1 else []),
            "retrieval_source_family": "attachment_table" if i == 0 else "mail",
        } for i in range(3)]
        measured("helpers", lambda: store.put_helpers(helpers))
        self.assertEqual(sql_counts["helpers"], {"insert": 1, "read": 1})
        self.assertEqual([store.get_helper(f"obs_{i}") for i in range(3)], helpers)
        tokens = [("shared", "alpha"), ("shared",), ("beta",)]
        candidates = [{
            "source_observation_hash": hashes[i], "dense_evidence_text_hash": texts[i % 2],
            "searchable_tokens": list(tokens[i]), "ordinal": 2 - i,
            "bundle_id": f"scope_{i}", "message_occurrence_hash": sha256_json(f"occurrence_{i}"),
            "observation_tokens": [f"source_token_{i}"],
            "observation_protected_identifier_tokens": [f"protected_{i}"],
        } for i in range(3)]
        measured("candidates", lambda: store.put_candidates(iter(candidates)))
        self.assertEqual(sql_counts["candidates"], {"insert": 1, "read": 2})
        for item in candidates:
            self.assertEqual(store.candidate_for_observation(item["source_observation_hash"]), item)
        postings = [{
            "token": token, "source_observation_hash": hashes[i], "document_length": len(tokens[i]),
        } for i in range(3) for token in tokens[i]]
        measured("postings", lambda: store.put_postings(iter(postings)))
        self.assertEqual(sql_counts["postings"], {"insert": 1, "read": 1})
        store.put_postings([{**postings[0], "document_length": 9}, postings[0]])
        self.assertEqual(store._get(
            "posting", sha256_json([postings[0]["token"], hashes[0]]),
        )["data"], postings[0])
        store.put_candidates([{**candidates[0], "ordinal": 99}, candidates[0]])
        self.assertEqual(store.candidate_for_observation(hashes[0]), candidates[0])
        with self.assertRaises(ContractValidationError):
            store.put_postings([
                {**postings[0], "document_length": 0}, postings[0],
            ])
        with self.assertRaises(ContractValidationError):
            store.put_candidates([{**candidates[0], "dense_vector": [1.0]}, candidates[0]])
        with self.assertRaises(ContractValidationError):
            store.put_candidates([
                {**candidates[0], "ordinal": 99},
                {**candidates[1], "source_observation_hash": sha256_json("missing helper")},
            ])
        self.assertEqual(store.candidate_for_observation(hashes[0]), candidates[0])
        statistics = store.finalize_candidate_order_and_statistics()
        self.assertEqual(statistics["document_count"], 3)
        self.assertEqual(statistics["average_document_length"], 4 / 3)
        self.assertEqual(measured("df", lambda: store.document_frequency(
            ("shared", "alpha", "missing")
        )), {
            "shared": 2, "alpha": 1, "missing": 0,
        })
        self.assertEqual(sql_counts["df"], {"insert": 0, "read": 1})
        self.assertEqual(
            [item["ordinal"] for item in store.iter_candidates(after_ordinal=0, limit=2)], [1, 2],
        )
        vectors = [[1.0, 0.0] + [0.0] * 382, [0.0, 1.0] + [0.0] * 382]
        vector_records = [
            {"text_hash": text_hash, "vector": vector}
            for text_hash, vector in zip(texts, vectors, strict=True)
        ]
        measured("vectors", lambda: store.put_dense_vectors(iter(vector_records)))
        self.assertEqual(sql_counts["vectors"], {"insert": 2, "read": 1})
        store.put_dense_vectors([
            {"text_hash": texts[0], "vector": vectors[1]}, vector_records[0],
        ])
        self.assertEqual(store.get_dense_vector(texts[0]), tuple(vectors[0]))
        with self.assertRaises(ContractValidationError):
            store.put_dense_vectors([
                {"text_hash": texts[0], "vector": [float("nan")] * 384}, vector_records[0],
            ])
        self.assertEqual(store.get_dense_vector(texts[0]), tuple(vectors[0]))
        store.checkpoint("batch_1", "obs_2", binding)
        seal = store.seal({"fixture": True}, binding)
        reopened = PostgreSQLGraphProjectionStore(
            connection, revision_id=revision_id, workspace_id="workspace_fixture", binding=binding,
        )
        self.assertEqual(reopened.reopen(seal["seal_hash"]), seal)
        self.assertEqual(seal["counts"]["helper"], 3)
        self.assertEqual(seal["counts"]["vector_ref"], 2)
        self.assertEqual(reopened.get_dense_vector(texts[0]), tuple(vectors[0]))
        self.assertEqual(reopened.candidate_by_ordinal(2)["source_observation_hash"], hashes[2])
        self.assertEqual(reopened.source_family_lexical_lookup(
            ("shared", "beta", "shared"), source_family="mail", timeout_ms=500,
        ), sorted(hashes[1:]))
        self.assertEqual(reopened.source_family_lexical_lookup(
            ("shared", "beta"), source_family="mail", limit=1, timeout_ms=500,
        ), sorted(hashes[1:])[:1])
        # Same hashes in another sealed revision must not bleed through the
        # helper join. Standalone document lookup uses the identical SQL port.
        document_store = PostgreSQLGraphProjectionStore(
            connection, revision_id=revision_id + "_document",
            workspace_id=store.workspace_id, binding=binding,
        )
        document_store.put_helpers([
            {**helper, "source_families": ["document_text"],
             "retrieval_source_family": "document_text"} for helper in helpers
        ])
        document_store.put_postings(postings)
        document_store.seal({"source_families": ["document_text"]}, binding)
        self.assertEqual(document_store.source_family_lexical_lookup(
            ("shared", "alpha", "beta"), source_family="document_text", timeout_ms=500,
        ), [hashes[0], *sorted(hashes[1:])])
        self.assertEqual(reopened.source_family_lexical_lookup(
            ("shared", "alpha", "beta"), source_family="document_text", timeout_ms=500,
        ), [])
        for lookup_store, family in ((reopened, "mail"), (document_store, "document_text")):
            with self.subTest(collision_recheck_family=family):
                with patch.object(
                    lookup_store, "_ranked_query", wraps=lookup_store._ranked_query,
                ) as ranked_query:
                    self.assertEqual(lookup_store.source_family_lexical_lookup(
                        ("beta", "beta"), source_family=family, timeout_ms=500,
                    ), [hashes[2]])
                statement = ranked_query.call_args.args[0]
                # Simulate digest collisions by admitting an extra raw token
                # only to the accelerator. Execute the real SQL raw recheck.
                colliding = replace(
                    statement,
                    sql=statement.sql.replace(
                        "unnest(%(tokens)s::text[])", "unnest(%(digest_tokens)s::text[])",
                    ),
                    parameters={**statement.parameters, "digest_tokens": ["beta", "shared"]},
                )
                self.assertEqual(lookup_store._ranked_query(colliding, 500), [
                    {"observation_hash": hashes[2]},
                ])
                without_recheck = replace(
                    colliding, sql=colliding.sql.replace(
                        "AND p.payload->>'token' = ANY(%(tokens)s) ", "",
                    ),
                )
                self.assertEqual(
                    len(lookup_store._ranked_query(without_recheck, 500)),
                    2 if family == "mail" else 3,
                )
        ranked = reopened.hybrid_ranked(
            query_tokens=("alpha", "beta"), query_vector=vectors[0], limit=1, timeout_ms=1000,
        )
        self.assertEqual([r["ordinal"] for r in ranked], [0, 2])
        self.assertEqual([(r["bm25_rank"], r["dense_rank"]) for r in ranked], [(2, 1), (1, 2)])
        for row in ranked:
            length = len(tokens[row["ordinal"]])
            expected = math.log(1 + (3 - 1 + 0.5) / (1 + 0.5)) * (
                2.2 / (1 + 1.2 * (0.25 + 0.75 * length / (4 / 3)))
            )
            self.assertAlmostEqual(row["bm25_score"], expected, places=12)
        allowed = reopened.hybrid_ranked(
            query_tokens=("alpha", "beta"), query_vector=vectors[0], limit=1, timeout_ms=1000,
            allowed_source_observation_hashes={hashes[2]},
        )
        self.assertEqual([(r["ordinal"], r["dense_rank"]) for r in allowed], [(2, 2)])
        family_ranked = reopened.hybrid_ranked(
            query_tokens=("alpha", "beta"), query_vector=vectors[0], limit=1, timeout_ms=1000,
            requested_source_families=("mail",),
        )
        self.assertEqual(
            [(r["ordinal"], r["bm25_rank"], r["dense_rank"]) for r in family_ranked],
            [(2, 1, 2)],
        )
        self.assertEqual(reopened.hybrid_ranked(
            query_tokens=("alpha", "beta"), query_vector=vectors[0], limit=1, timeout_ms=1000,
            requested_source_families=("mail",), allowed_source_observation_hashes={hashes[0]},
        ), [])
        self.assertEqual(reopened.candidate_count_for_families(("mail",)), 2)
        self.assertEqual(reopened.candidate_count_for_families(("attachment_table",)), 1)
        self.assertEqual(reopened.candidate_count_for_families(()), 0)
        self.assertEqual(reopened.candidate_tokens_present(
            ("source_token_0", "source_token_2", "alpha", "missing"),
            "observation_tokens", requested_source_families=("mail",),
        ), {"source_token_2"})
        self.assertEqual(reopened.candidate_tokens_present(
            ("protected_0", "protected_2"), "observation_protected_identifier_tokens",
        ), {"protected_0", "protected_2"})
        self.assertEqual([n.node_id for n in reopened.node_candidates_by_terms(
            tokens=("anchor",), term_hashes=(sha256_json("source_term"),), limit=2,
        )], ["node_0", "node_1"])
        self.assertEqual([n.node_id for n in reopened.node_candidates_by_terms(
            tokens=("anchor",), term_hashes=(sha256_json("source_term"),), after_id="node_1",
        )], ["node_2"])
        self.assertEqual([n.node_id for n in reopened.node_candidates_by_terms(
            tokens=("anchor",), term_hashes=(sha256_json("source_term"),),
            requested_source_families=("mail",),
        )], ["node_1", "node_2"])
        self.assertEqual([n.node_id for n in reopened.node_candidates_by_terms(
            tokens=(), term_hashes=(sha256_json("protected"),),
        )], ["node_0"])
        with self.assertRaises(ContractValidationError):
            reopened.candidate_tokens_present(("alpha",), "searchable_tokens")
        with self.assertRaises(ContractValidationError):
            reopened.put_nodes(nodes[:1])
        with self.assertRaises(ContractValidationError):
            reopened.reopen("sha256:" + "0" * 64)
        with self.assertRaises(ContractValidationError):
            reopened.iter_nodes(limit=257)
        # Incompressible > B-tree-entry-limit token, with unchanged raw data
        # and otherwise identical corpus: only the lookup representation differs.
        long_token = "".join(sha256_json(f"long-token-{i}")[7:] for i in range(128))
        long_store = PostgreSQLGraphProjectionStore(
            connection, revision_id=revision_id + "_long", workspace_id="workspace_fixture",
            binding=binding,
        )
        long_store.checkpoint("fixture_initialized", "", binding)
        long_store.put_helpers(helpers)
        long_candidates = [{**item, "searchable_tokens": [
            long_token if token == "alpha" else token for token in item["searchable_tokens"]
        ]} for item in candidates]
        long_store.put_candidates(long_candidates)
        long_postings = [{**item, "token": long_token if item["token"] == "alpha"
                          else item["token"]} for item in postings]
        long_store.put_postings(long_postings)
        self.assertEqual(long_store._get(
            "posting", sha256_json([long_token, hashes[0]]),
        )["data"], long_postings[1])
        long_store.finalize_candidate_order_and_statistics()
        self.assertEqual(long_store.document_frequency((long_token, "shared")),
                         {long_token: 1, "shared": 2})
        long_store.put_dense_vectors(vector_records)
        long_seal = long_store.seal({"fixture": True}, binding)
        long_reopened = PostgreSQLGraphProjectionStore(
            connection, revision_id=revision_id + "_long", workspace_id="workspace_fixture",
            binding=binding,
        )
        long_reopened.reopen(long_seal["seal_hash"])
        self.assertEqual(long_reopened.lexical_ranked(
            (long_token, "beta"), timeout_ms=1000,
        ), reopened.lexical_ranked(("alpha", "beta"), timeout_ms=1000))
        self.assertEqual(long_reopened.hybrid_ranked(
            query_tokens=(long_token, "beta"), query_vector=vectors[0], limit=1,
            timeout_ms=1000,
        ), ranked)
        print("bounded_store_fixture_sql_counts=" + str(sql_counts), flush=True)

    def test_vector_search_filters_ready_and_stale_records_by_permission(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-vectors-permission")
        store = FileVectorStore(temp_dir)
        allowed_scope = PermissionScope.project("project_formowl").to_dict()
        denied_scope = PermissionScope.project("project_private").to_dict()

        store.create(
            _vector_record(
                vector_id="vec_ready_allowed",
                source_id="obs_ready_allowed",
                embedding=[1.0, 0.0],
                permission_scope=allowed_scope,
                index_state="ready",
            )
        )
        store.create(
            _vector_record(
                vector_id="vec_stale_allowed",
                source_id="obs_stale_allowed",
                embedding=[0.9, 0.1],
                permission_scope=allowed_scope,
                index_state="stale",
            )
        )
        store.create(
            _vector_record(
                vector_id="vec_stale_denied",
                source_id="obs_stale_denied",
                embedding=[0.99, 0.01],
                permission_scope=denied_scope,
                index_state="stale",
            )
        )

        grant = _project_grant("project_formowl")
        without_stale = store.search(
            [1.0, 0.0],
            requester_user_id="user_yifan",
            grants=[grant],
            allow_stale=False,
            now=NOW,
        )
        self.assertEqual(
            [result.record.vector_id for result in without_stale], ["vec_ready_allowed"]
        )
        self.assertFalse(without_stale[0].stale)

        with_stale = store.search(
            [1.0, 0.0],
            requester_user_id="user_yifan",
            grants=[grant],
            allow_stale=True,
            now=NOW,
        )
        self.assertEqual(
            {result.record.vector_id for result in with_stale},
            {"vec_ready_allowed", "vec_stale_allowed"},
        )
        self.assertTrue(
            next(
                result for result in with_stale if result.record.vector_id == "vec_stale_allowed"
            ).stale
        )
        self.assertNotIn(
            "vec_stale_denied",
            {result.record.vector_id for result in with_stale},
        )

        no_grant_results = store.search(
            [1.0, 0.0],
            requester_user_id="user_yifan",
            grants=[],
            allow_stale=True,
            now=NOW,
        )
        self.assertEqual(no_grant_results, [])

        invalid_grants = [
            _project_grant("project_formowl", revoked_at=NOW),
            _project_grant("project_formowl", expires_at=NOW),
            _project_grant("project_formowl", grantee_user_id="user_other"),
            _project_grant("project_formowl", permission="raw_asset_admin"),
        ]
        for invalid_grant in invalid_grants:
            with self.subTest(grant=invalid_grant):
                self.assertEqual(
                    store.search(
                        [1.0, 0.0],
                        requester_user_id="user_yifan",
                        grants=[invalid_grant],
                        allow_stale=True,
                        now=NOW,
                    ),
                    [],
                )

    def test_grant_based_access_requires_current_time_for_expiration_checks(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-requires-now")
        vector_store = FileVectorStore(temp_dir)
        projection_store = FileGraphProjectionStore(temp_dir)
        permission_scope = PermissionScope.project("project_formowl").to_dict()
        grant = _project_grant("project_formowl")
        vector_store.create(
            _vector_record(
                vector_id="vec_stale",
                source_id="obs_stale",
                embedding=[1.0, 0.0],
                permission_scope=permission_scope,
                index_state="stale",
            )
        )
        projection_store.create_node(
            _projection_node("node_visible", "catom_visible", permission_scope)
        )

        with self.assertRaises(ContractValidationError):
            vector_store.search(
                [1.0, 0.0],
                requester_user_id="user_yifan",
                grants=[grant],
                allow_stale=True,
            )
        with self.assertRaises(ContractValidationError):
            projection_store.visible_nodes(requester_user_id="user_yifan", grants=[grant])
        with self.assertRaises(ContractValidationError):
            projection_store.neighbors(
                "node_visible", requester_user_id="user_yifan", grants=[grant]
            )

    def test_vector_store_persists_records_and_marks_source_vectors_stale(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-vectors-restart")
        store = FileVectorStore(temp_dir)
        record = _vector_record(
            vector_id="vec_obs_001",
            source_id="obs_001",
            embedding=[0.25, 0.75],
            permission_scope=PermissionScope.project("project_formowl").to_dict(),
        )

        self.assertEqual(store.create(record).to_dict(), record.to_dict())
        stale_records = store.mark_stale_for_source(
            source_type="observation",
            source_id="obs_001",
            reason="source permission changed",
        )

        self.assertEqual(len(stale_records), 1)
        self.assertEqual(stale_records[0].index_state, "stale")
        self.assertEqual(stale_records[0].metadata["stale_reason"], "source permission changed")

        restarted = FileVectorStore(temp_dir)
        restarted_record = restarted.get("vec_obs_001")
        self.assertIsNotNone(restarted_record)
        self.assertEqual(restarted_record.index_state, "stale")
        self.assertEqual(restarted_record.permission_scope, record.permission_scope)
        self.assertEqual(restarted_record.source_content_hash, record.source_content_hash)
        self.assertEqual([item.vector_id for item in restarted.list()], ["vec_obs_001"])
        restarted_results = restarted.search(
            [0.25, 0.75],
            requester_user_id="user_yifan",
            grants=[_project_grant("project_formowl")],
            allow_stale=True,
            now=NOW,
        )
        self.assertEqual([result.record.vector_id for result in restarted_results], ["vec_obs_001"])
        self.assertTrue(restarted_results[0].stale)
        self.assertEqual(
            restarted.search(
                [0.25, 0.75],
                requester_user_id="user_yifan",
                grants=[],
                allow_stale=True,
                now=NOW,
            ),
            [],
        )
        self.assertTrue((temp_dir / "graph" / "index" / "vectors" / "vec_obs_001.json").exists())
        self.assertFalse((temp_dir / "graph" / "vectors").exists())
        self.assertFalse((temp_dir / "graph" / "canonical").exists())

    def test_vector_store_rejects_invalid_payloads_without_partial_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-vectors-invalid")
        store = FileVectorStore(temp_dir)
        valid_record = _vector_record(
            vector_id="vec_valid",
            source_id="obs_valid",
            embedding=[1.0, 0.0],
            permission_scope=PermissionScope.project("project_formowl").to_dict(),
        )
        store.create(valid_record)

        invalid_embedding = valid_record.to_dict()
        invalid_embedding["vector_id"] = "vec_invalid_embedding"
        invalid_embedding["embedding"] = [True, 0.0]
        invalid_source_payloads = []
        for index, source_id in enumerate(
            [
                "/tmp/raw/path.txt",
                "tmp/raw.txt",
                "tmp\\raw.txt",
                "smb://nas/share/file.txt",
                "s3://bucket/key",
            ],
            start=1,
        ):
            invalid_source = valid_record.to_dict()
            invalid_source["vector_id"] = f"vec_invalid_source_{index}"
            invalid_source["source_id"] = source_id
            invalid_source_payloads.append(invalid_source)
        invalid_metadata_nan = valid_record.to_dict()
        invalid_metadata_nan["vector_id"] = "vec_invalid_metadata_nan"
        invalid_metadata_nan["metadata"] = {"score": float("nan")}
        invalid_metadata_raw_locator = valid_record.to_dict()
        invalid_metadata_raw_locator["vector_id"] = "vec_invalid_metadata_raw_locator"
        invalid_metadata_raw_locator["metadata"] = {"source": "smb://nas/share/file.txt"}
        invalid_metadata_raw_key = valid_record.to_dict()
        invalid_metadata_raw_key["vector_id"] = "vec_invalid_metadata_raw_key"
        invalid_metadata_raw_key["metadata"] = {"smb://nas/share/file.txt": "source"}
        invalid_metadata_non_string_key = valid_record.to_dict()
        invalid_metadata_non_string_key["vector_id"] = "vec_invalid_metadata_non_string_key"
        invalid_metadata_non_string_key["metadata"] = {1: "source"}
        invalid_metadata_nested_non_string_key = valid_record.to_dict()
        invalid_metadata_nested_non_string_key["vector_id"] = "vec_invalid_metadata_nested_key"
        invalid_metadata_nested_non_string_key["metadata"] = {"outer": {1: "source"}}
        invalid_metadata_tuple_raw_locator = valid_record.to_dict()
        invalid_metadata_tuple_raw_locator["vector_id"] = "vec_invalid_metadata_tuple"
        invalid_metadata_tuple_raw_locator["metadata"] = {
            "paths": ("smb://nas/share/file.txt",),
        }
        unsafe_id_payloads = []
        for unsafe_vector_id in _unsafe_index_ids("vec"):
            unsafe_id = valid_record.to_dict()
            unsafe_id["vector_id"] = unsafe_vector_id
            unsafe_id_payloads.append(unsafe_id)
        before_invalid_state = _tree_state(temp_dir)

        with self.assertRaises(ContractValidationError):
            store.create(invalid_embedding)
        for invalid_source in invalid_source_payloads:
            with self.subTest(source_id=invalid_source["source_id"]):
                with self.assertRaises(ContractValidationError):
                    store.create(invalid_source)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_nan)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_raw_locator)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_raw_key)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_non_string_key)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_nested_non_string_key)
        with self.assertRaises(ContractValidationError):
            store.create(invalid_metadata_tuple_raw_locator)
        for unsafe_id in unsafe_id_payloads:
            with self.subTest(vector_id=unsafe_id["vector_id"]):
                with self.assertRaises(ValueError):
                    store.create(unsafe_id)

        self.assertEqual([record.vector_id for record in store.list()], ["vec_valid"])
        self.assertEqual(_tree_state(temp_dir), before_invalid_state)

    def test_graph_projection_store_filters_nodes_and_edges_by_permission(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-projection-permission")
        store = FileGraphProjectionStore(temp_dir)
        allowed_scope = PermissionScope.project("project_formowl").to_dict()
        denied_scope = PermissionScope.project("project_private").to_dict()
        allowed_a = _projection_node("node_allowed_a", "catom_allowed_a", allowed_scope)
        allowed_b = _projection_node("node_allowed_b", "catom_allowed_b", allowed_scope)
        denied = _projection_node("node_denied", "catom_denied", denied_scope)

        store.create_node(allowed_a)
        store.create_node(allowed_b)
        store.create_node(denied)
        store.create_edge(
            _projection_edge("edge_allowed", allowed_a.node_id, allowed_b.node_id, allowed_scope)
        )
        store.create_edge(
            _projection_edge(
                "edge_allowed_nodes_denied_scope",
                allowed_a.node_id,
                allowed_b.node_id,
                denied_scope,
            )
        )
        store.create_edge(
            _projection_edge("edge_denied_node", allowed_a.node_id, denied.node_id, allowed_scope)
        )

        grant = _project_grant("project_formowl")
        self.assertEqual(
            [
                node.node_id
                for node in store.visible_nodes(
                    requester_user_id="user_yifan",
                    grants=[grant],
                    now=NOW,
                )
            ],
            ["node_allowed_a", "node_allowed_b"],
        )
        self.assertEqual(
            [
                edge.edge_id
                for edge in store.neighbors(
                    "node_allowed_a",
                    requester_user_id="user_yifan",
                    grants=[grant],
                    now=NOW,
                )
            ],
            ["edge_allowed"],
        )
        self.assertEqual(
            store.neighbors("node_denied", requester_user_id="user_yifan", grants=[grant], now=NOW),
            [],
        )
        self.assertEqual(store.visible_nodes(requester_user_id="user_yifan", grants=[]), [])
        self.assertEqual(
            store.neighbors("node_allowed_a", requester_user_id="user_yifan", grants=[]),
            [],
        )

        restarted = FileGraphProjectionStore(temp_dir)
        self.assertEqual(
            [
                node.node_id
                for node in restarted.visible_nodes(
                    requester_user_id="user_yifan",
                    grants=[grant],
                    now=NOW,
                )
            ],
            ["node_allowed_a", "node_allowed_b"],
        )
        self.assertEqual(
            [
                edge.edge_id
                for edge in restarted.neighbors(
                    "node_allowed_a",
                    requester_user_id="user_yifan",
                    grants=[grant],
                    now=NOW,
                )
            ],
            ["edge_allowed"],
        )
        self.assertEqual(
            [node.node_id for node in restarted.list_nodes()],
            [
                "node_allowed_a",
                "node_allowed_b",
                "node_denied",
            ],
        )
        self.assertEqual(
            [edge.edge_id for edge in restarted.list_edges()],
            ["edge_allowed", "edge_allowed_nodes_denied_scope", "edge_denied_node"],
        )

        graph_root = temp_dir / "graph"
        directory_names = {child.name for child in graph_root.iterdir() if child.is_dir()}
        self.assertEqual(directory_names, {"index"})
        self.assertFalse(any("canonical" in name for name in directory_names))

    def test_graph_projection_stale_and_dangling_records_still_filter_by_permission(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-projection-stale")
        store = FileGraphProjectionStore(temp_dir)
        allowed_scope = PermissionScope.project("project_formowl").to_dict()
        denied_scope = PermissionScope.project("project_private").to_dict()
        ready_node = _projection_node("node_ready", "catom_ready", allowed_scope)
        stale_node = _projection_node(
            "node_stale",
            "catom_stale",
            allowed_scope,
            projection_state="stale",
        )
        denied_stale_node = _projection_node(
            "node_denied_stale",
            "catom_denied_stale",
            denied_scope,
            projection_state="stale",
        )

        store.create_node(ready_node)
        store.create_node(stale_node)
        store.create_node(denied_stale_node)
        store.create_edge(
            _projection_edge(
                "edge_stale_allowed",
                ready_node.node_id,
                stale_node.node_id,
                allowed_scope,
                projection_state="stale",
            )
        )
        store.create_edge(
            _projection_edge(
                "edge_stale_denied",
                ready_node.node_id,
                stale_node.node_id,
                denied_scope,
                projection_state="stale",
            )
        )
        store.create_edge(
            _projection_edge("edge_dangling", ready_node.node_id, "node_missing", allowed_scope)
        )

        grant = _project_grant("project_formowl")
        self.assertEqual(
            [
                node.node_id
                for node in store.visible_nodes(
                    requester_user_id="user_yifan",
                    grants=[grant],
                    allow_stale=False,
                    now=NOW,
                )
            ],
            ["node_ready"],
        )
        self.assertEqual(
            store.neighbors(
                "node_ready",
                requester_user_id="user_yifan",
                grants=[grant],
                allow_stale=False,
                now=NOW,
            ),
            [],
        )
        self.assertEqual(
            [
                node.node_id
                for node in store.visible_nodes(
                    requester_user_id="user_yifan",
                    grants=[grant],
                    allow_stale=True,
                    now=NOW,
                )
            ],
            ["node_ready", "node_stale"],
        )
        self.assertEqual(
            [
                edge.edge_id
                for edge in store.neighbors(
                    "node_ready",
                    requester_user_id="user_yifan",
                    grants=[grant],
                    allow_stale=True,
                    now=NOW,
                )
            ],
            ["edge_stale_allowed"],
        )
        self.assertEqual(
            store.neighbors(
                "node_missing",
                requester_user_id="user_yifan",
                grants=[grant],
                allow_stale=True,
                now=NOW,
            ),
            [],
        )

    def test_graph_projection_rejects_invalid_payloads_without_partial_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-index-projection-invalid")
        store = FileGraphProjectionStore(temp_dir)
        permission_scope = PermissionScope.project("project_formowl").to_dict()
        invalid_node_source = _projection_node(
            "node_invalid_source",
            "internal/share/file.txt",
            permission_scope,
        )
        invalid_node_properties = _projection_node(
            "node_invalid_properties",
            "catom_invalid_properties",
            permission_scope,
        ).to_dict()
        invalid_node_properties["properties"] = {"weight": float("inf")}
        invalid_node_property_key = _projection_node(
            "node_invalid_property_key",
            "catom_invalid_property_key",
            permission_scope,
        ).to_dict()
        invalid_node_property_key["properties"] = {"/tmp/raw.txt": "label"}
        invalid_node_property_non_string_key = _projection_node(
            "node_invalid_property_non_string_key",
            "catom_invalid_property_non_string_key",
            permission_scope,
        ).to_dict()
        invalid_node_property_non_string_key["properties"] = {1: "label"}
        invalid_node_property_tuple = _projection_node(
            "node_invalid_property_tuple",
            "catom_invalid_property_tuple",
            permission_scope,
        ).to_dict()
        invalid_node_property_tuple["properties"] = {
            "paths": ("smb://nas/share/file.txt",),
        }
        invalid_node_label = _projection_node(
            "node_invalid_label",
            "catom_invalid_label",
            permission_scope,
        ).to_dict()
        invalid_node_label["labels"] = ["smb://nas/share/file.txt"]
        invalid_edge_properties = _projection_edge(
            "edge_invalid_properties",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_properties["properties"] = {"source": "object://bucket/key"}
        invalid_edge_property_key = _projection_edge(
            "edge_invalid_property_key",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_property_key["properties"] = {"s3://bucket/key": "source"}
        invalid_edge_property_non_string_key = _projection_edge(
            "edge_invalid_property_non_string_key",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_property_non_string_key["properties"] = {1: "source"}
        invalid_edge_property_tuple = _projection_edge(
            "edge_invalid_property_tuple",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_property_tuple["properties"] = {
            "paths": ("smb://nas/share/file.txt",),
        }
        invalid_edge_relation_type = _projection_edge(
            "edge_invalid_relation_type",
            "node_left",
            "node_right",
            permission_scope,
        ).to_dict()
        invalid_edge_relation_type["relation_type"] = "s3://bucket/key"
        invalid_node_id_payloads = []
        for unsafe_node_id in _unsafe_index_ids("node"):
            invalid_node_id_payloads.append(
                _projection_node(
                    unsafe_node_id,
                    "catom_invalid_node_id",
                    permission_scope,
                )
            )
        invalid_edge_id_payloads = []
        for unsafe_edge_id in _unsafe_index_ids("edge"):
            invalid_edge_id_payloads.append(
                _projection_edge(
                    unsafe_edge_id,
                    "node_left",
                    "node_right",
                    permission_scope,
                )
            )
        invalid_edge_endpoint_payloads = []
        for index, unsafe_endpoint_id in enumerate(_unsafe_index_ids("endpoint"), start=1):
            invalid_edge_endpoint_payloads.append(
                _projection_edge(
                    f"edge_invalid_source_endpoint_{index}",
                    unsafe_endpoint_id,
                    "node_right",
                    permission_scope,
                )
            )
            invalid_edge_endpoint_payloads.append(
                _projection_edge(
                    f"edge_invalid_target_endpoint_{index}",
                    "node_left",
                    unsafe_endpoint_id,
                    permission_scope,
                )
            )
        before_invalid_state = _tree_state(temp_dir)

        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_source)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_properties)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_property_key)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_property_non_string_key)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_property_tuple)
        with self.assertRaises(ContractValidationError):
            store.create_node(invalid_node_label)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_properties)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_property_key)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_property_non_string_key)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_property_tuple)
        with self.assertRaises(ContractValidationError):
            store.create_edge(invalid_edge_relation_type)
        for invalid_node in invalid_node_id_payloads:
            with self.subTest(node_id=invalid_node.node_id):
                with self.assertRaises(ValueError):
                    store.create_node(invalid_node)
        for invalid_edge in invalid_edge_id_payloads:
            with self.subTest(edge_id=invalid_edge.edge_id):
                with self.assertRaises(ValueError):
                    store.create_edge(invalid_edge)
        for invalid_edge in invalid_edge_endpoint_payloads:
            with self.subTest(edge_id=invalid_edge.edge_id):
                with self.assertRaises(ValueError):
                    store.create_edge(invalid_edge)

        self.assertEqual(store.list_nodes(), [])
        self.assertEqual(store.list_edges(), [])
        projection_root = temp_dir / "graph" / "index" / "graph-projections"
        self.assertEqual(list(projection_root.rglob("*.json")), [])
        self.assertEqual(list(projection_root.rglob("*.tmp")), [])
        self.assertEqual(_tree_state(temp_dir), before_invalid_state)


def _vector_record(
    *,
    vector_id: str,
    source_id: str,
    embedding: list[float],
    permission_scope: dict[str, object],
    index_state: str = "ready",
) -> VectorRecord:
    return VectorRecord(
        vector_id=vector_id,
        source_type="observation",
        source_id=source_id,
        source_content_hash=f"sha256:{source_id}",
        embedding_model="fixture-embedding-v1",
        embedding=embedding,
        permission_scope=permission_scope,
        index_state=index_state,
        metadata={"source_kind": "test"},
        created_at="2026-06-18T00:00:00+00:00",
    )


def _projection_node(
    node_id: str,
    source_id: str,
    permission_scope: dict[str, object],
    projection_state: str = "ready",
) -> GraphProjectionNode:
    return GraphProjectionNode(
        node_id=node_id,
        source_type="candidate_atom",
        source_id=source_id,
        labels=["CandidateAtom"],
        properties={"label": source_id},
        permission_scope=permission_scope,
        projection_state=projection_state,
    )


def _projection_edge(
    edge_id: str,
    source_node_id: str,
    target_node_id: str,
    permission_scope: dict[str, object],
    projection_state: str = "ready",
) -> GraphProjectionEdge:
    return GraphProjectionEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relation_type="related_to",
        properties={"basis": "candidate relation projection"},
        permission_scope=permission_scope,
        projection_state=projection_state,
    )


def _project_grant(
    project_id: str,
    *,
    grantee_user_id: str = "user_yifan",
    permission: str = "graph_snippet",
    expires_at: str = "2026-06-19T00:00:00+00:00",
    revoked_at: str | None = None,
) -> Grant:
    return Grant(
        grant_id=f"grant_{project_id}",
        owner_user_id="user_owner",
        grantee_user_id=grantee_user_id,
        scope_type="project",
        scope_id=project_id,
        permission=permission,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def _unsafe_index_ids(prefix: str) -> tuple[str, ...]:
    return (
        ".",
        "..",
        ".hidden",
        "-hidden",
        "_hidden",
        "+hidden",
        f"../{prefix}",
        rf"..\{prefix}",
        f"{prefix}/path",
        rf"{prefix}\path",
    )


def _tree_state(root) -> dict[str, str]:
    if not root.exists():
        return {}
    state: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root).as_posix()
        if path.is_dir():
            state[f"{relative_path}/"] = "<dir>"
        else:
            state[relative_path] = path.read_text(encoding="utf-8")
    return state


if __name__ == "__main__":
    unittest.main()
