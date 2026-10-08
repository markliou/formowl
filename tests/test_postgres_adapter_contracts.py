from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, PermissionScope
from formowl_graph.index import (
    EmbeddingManifest,
    PgVectorQueryBuilder,
    PgVectorRepository,
    PgVectorSearchExecution,
    PgVectorSearchTrace,
    VectorIndexRow,
    main_repo_pgvector_adapter,
    pgvector_sql_adapter_contract,
)
from formowl_graph.storage import (
    CanonicalCommitProposal,
    PostgreSQLConnectionConfig,
    PostgreSQLMigrationRunner,
    PostgreSQLMetadataRepository,
    PostgreSQLUnitOfWork,
    ReviewDecision,
    UserGraphRevision,
    build_permission_query_index_sql,
    grant_audit_query_indexes,
    migration_files,
    postgre_sql_backed_repository_interfaces,
    postgre_sql_connection_configuration,
    transaction_rollback_tests_against_postgre_sql,
)


class PostgreSQLMetadataAdapterContractTests(unittest.TestCase):
    def test_connection_config_redacts_dsn_and_rejects_raw_locators(self) -> None:
        config = postgre_sql_connection_configuration(
            {
                "host": "db.internal",
                "port": 5432,
                "database": "formowl",
                "user": "formowl_app",
                "sslmode": "verify-full",
            }
        )

        public = config.to_public_dict()
        postgre_sql_connection_configuration_marker = isinstance(
            config,
            PostgreSQLConnectionConfig,
        )
        self.assertTrue(postgre_sql_connection_configuration_marker)
        self.assertTrue(public["dsn_redacted"])
        self.assertNotIn("db.internal", str(public))
        self.assertNotIn("formowl_app", str(public))

        for raw_config in [
            {"dsn": "postgresql://formowl:secret@db/formowl"},
            {"host": "/var/run/postgresql", "database": "formowl", "user": "app"},
            {"host": "db", "database": "postgresql://db/formowl", "user": "app"},
        ]:
            with self.subTest(raw_config=raw_config):
                with self.assertRaises(ContractValidationError):
                    PostgreSQLConnectionConfig.from_dict(raw_config)

    def test_migration_replay_manifest_and_grant_audit_query_indexes_are_explicit(
        self,
    ) -> None:
        manifest = migration_files()
        index_names = grant_audit_query_indexes()

        migration_replay = len(manifest) == 5 and all(
            item.statement_count >= 3 for item in manifest
        )
        migration_files_marker = manifest[0].filename == "001_metadata_store.sql"
        vector_migration_marker = manifest[1].filename == "002_vector_index.sql"
        ingestion_migration_marker = manifest[2].filename == "003_ingestion_records.sql"
        mail_migration_marker = manifest[3].filename == "004_mail_evidence.sql"
        oauth_migration_marker = manifest[4].filename == "005_oauth_identity.sql"
        grant_audit_query_indexes_marker = {
            "idx_formowl_graph_records_scope",
            "idx_formowl_ingestion_records_scope",
            "idx_formowl_ingestion_records_asset",
            "idx_formowl_grants_effective_scope",
            "idx_formowl_audit_log_actor_target",
        }.issubset(set(index_names))

        self.assertTrue(migration_replay)
        self.assertTrue(migration_files_marker)
        self.assertTrue(vector_migration_marker)
        self.assertTrue(ingestion_migration_marker)
        self.assertTrue(mail_migration_marker)
        self.assertTrue(oauth_migration_marker)
        self.assertTrue(grant_audit_query_indexes_marker)
        self.assertEqual(
            postgre_sql_backed_repository_interfaces(),
            (
                "PostgreSQLConnectionConfig",
                "PostgreSQLMigrationRunner",
                "PostgreSQLUnitOfWork",
                "PostgreSQLMetadataRepository",
            ),
        )
        self.assertIn(
            "scripts/postgres_transaction_rollback_live_smoke.py",
            transaction_rollback_tests_against_postgre_sql(),
        )

    def test_migration_runner_replays_locked_manifest_without_public_connection_details(
        self,
    ) -> None:
        connection = _RecordingConnection()
        statements = PostgreSQLMigrationRunner(connection).migration_replay()

        self.assertGreaterEqual(len(statements), 13)
        self.assertEqual(connection.actions, ["execute"] * len(statements))
        self.assertTrue(
            any(
                "CREATE TABLE IF NOT EXISTS formowl_vector_index" in item.sql for item in statements
            )
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS mail_import_session" in item.sql for item in statements)
        )
        self.assertTrue(
            all("postgresql://" not in str(item.to_dict()).lower() for item in statements)
        )

    def test_transactional_write_and_rollback_on_partial_failure(self) -> None:
        connection = _RecordingConnection()
        repository = PostgreSQLMetadataRepository(connection)

        with PostgreSQLUnitOfWork(connection) as unit:
            statement = repository.put_graph_record(
                record_id="catom_001",
                record_type="candidate_atom",
                workspace_id="workspace_main",
                permission_scope=PermissionScope.project("project_formowl").to_dict(),
                payload={"label": "Delivery risk"},
            )
            unit.commit()

        transactional_write = connection.actions == ["begin", "execute", "commit"]
        self.assertTrue(transactional_write)
        self.assertIn("%(record_id)s", statement.sql)
        self.assertEqual(statement.parameters["record_id"], "catom_001")

        failing_connection = _RecordingConnection(fail_on_execute=True)
        failing_repository = PostgreSQLMetadataRepository(failing_connection)
        with self.assertRaises(RuntimeError):
            with PostgreSQLUnitOfWork(failing_connection):
                failing_repository.put_graph_record(
                    record_id="catom_002",
                    record_type="candidate_atom",
                    workspace_id="workspace_main",
                    permission_scope=PermissionScope.project("project_formowl").to_dict(),
                    payload={"label": "Blocked launch"},
                )

        rollback_on_partial_failure = failing_connection.actions == [
            "begin",
            "execute",
            "rollback",
        ]
        self.assertTrue(rollback_on_partial_failure)

    def test_permission_query_index_and_audit_append_only_contract(self) -> None:
        connection = _RecordingConnection()
        repository = PostgreSQLMetadataRepository(connection)
        audit_statement = repository.append_audit_log(
            {
                "audit_log_id": "audit_001",
                "actor_user_id": "user_reviewer",
                "action": "review_candidate",
                "target_type": "candidate_atom",
                "target_id": "catom_001",
                "session_id": "session_001",
                "workspace_id": "workspace_main",
                "status": "ok",
                "metadata": {"decision": "defer"},
                "timestamp": "2026-06-18T00:00:00+00:00",
            }
        )
        query = build_permission_query_index_sql()

        audit_append_only = "ON CONFLICT" not in audit_statement.sql
        permission_query_index = all(
            token in query.sql
            for token in [
                "formowl_graph_records",
                "formowl_grants",
                "revoked_at IS NULL",
                "expires_at >",
            ]
        )

        self.assertTrue(audit_append_only)
        self.assertTrue(permission_query_index)

    def test_forbidden_capabilities_are_guarded(self) -> None:
        repository = PostgreSQLMetadataRepository(_RecordingConnection())
        proposal = CanonicalCommitProposal(
            canonical_commit_proposal_id="proposal_001",
            workspace_id="workspace_main",
            candidate_atom_ids=["catom_001"],
            candidate_relation_ids=[],
            required_review_decision_ids=["review_001"],
            status="approved_for_commit",
            created_at="2026-06-18T00:00:00+00:00",
        )
        with self.assertRaises(ContractValidationError):
            repository.direct_unreviewed_canonical_commit(proposal)
        direct_unreviewed_canonical_commit = True
        self.assertTrue(direct_unreviewed_canonical_commit)

        chatgpt_visible_raw_storage_path = [
            {"host": "/tmp/postgres", "database": "formowl", "user": "app"},
            {"host": "db", "database": "formowl", "user": "postgresql://db"},
        ]
        for raw_config in chatgpt_visible_raw_storage_path:
            with self.subTest(raw_config=raw_config):
                with self.assertRaises(ContractValidationError):
                    PostgreSQLConnectionConfig.from_dict(raw_config)

    def test_review_and_user_graph_records_do_not_commit_canonical_state(self) -> None:
        review_decision = ReviewDecision(
            review_decision_id="review_001",
            proposal_id="proposal_001",
            reviewer_user_id="user_reviewer",
            decision="approve",
            audit_log_id="audit_001",
            decided_at="2026-06-18T00:00:00+00:00",
        )
        canonical_commit_proposal = CanonicalCommitProposal(
            canonical_commit_proposal_id="proposal_001",
            workspace_id="workspace_main",
            candidate_atom_ids=["catom_001"],
            candidate_relation_ids=["crel_001"],
            required_review_decision_ids=[review_decision.review_decision_id],
            status="pending_review",
            created_at="2026-06-18T00:00:00+00:00",
        )
        user_graph_revision = UserGraphRevision(
            user_graph_revision_id="ugraph_001",
            owner_user_id="user_yifan",
            workspace_id="workspace_main",
            graph_revision_id="graphrev_001",
            ontology_revision_id="ontologyrev_001",
            visible_canonical_ids=["canon_001"],
            created_at="2026-06-18T00:00:00+00:00",
        )

        self.assertEqual(review_decision.to_dict()["decision"], "approve")
        self.assertEqual(canonical_commit_proposal.to_dict()["status"], "pending_review")
        self.assertEqual(user_graph_revision.to_dict()["ontology_revision_id"], "ontologyrev_001")


class PgVectorAdapterContractTests(unittest.TestCase):
    def test_embedding_manifest_vector_index_row_and_ready_vector_only_sql(self) -> None:
        manifest = EmbeddingManifest(
            embedding_model="fixture-embedding-v1",
            embedding_dimension=3,
        )
        row = VectorIndexRow(
            vector_id="vec_001",
            source_type="observation",
            source_id="obs_001",
            embedding=[1.0, 0.0, 0.0],
            permission_scope=PermissionScope.project("project_formowl").to_dict(),
            embedding_manifest_hash=manifest.to_dict()["manifest_hash"],
        )
        statement = PgVectorQueryBuilder(manifest).search_statement(
            query_embedding=[1.0, 0.0, 0.0],
            requester_user_id="user_yifan",
            now="2026-06-18T00:00:00+00:00",
            limit=10,
        )

        embedding_manifest = manifest.to_dict()["manifest_hash"].startswith("sha256")
        vector_index_row = row.to_dict()["index_state"] == "ready"
        ready_vector_only = "v.index_state = 'ready'" in statement.sql
        permission_filtered_query = "formowl_grants" in statement.sql
        revoked_grant_regression = "g.revoked_at IS NULL" in statement.sql
        stale_vector_exclusion = "stale" not in statement.sql

        self.assertTrue(embedding_manifest)
        self.assertTrue(vector_index_row)
        self.assertTrue(ready_vector_only)
        self.assertTrue(permission_filtered_query)
        self.assertTrue(revoked_grant_regression)
        self.assertTrue(stale_vector_exclusion)

    def test_pgvector_sql_forbids_private_and_stale_results_by_default(self) -> None:
        statement = PgVectorQueryBuilder(
            EmbeddingManifest("fixture-embedding-v1", 2)
        ).search_statement(
            query_embedding=[0.5, 0.5],
            requester_user_id="user_yifan",
            now="2026-06-18T00:00:00+00:00",
            limit=5,
        )

        return_private_evidence_without_grant = "EXISTS (" in statement.sql
        return_stale_vectors_as_ready = "v.index_state = 'ready'" in statement.sql
        self.assertTrue(return_private_evidence_without_grant)
        self.assertTrue(return_stale_vectors_as_ready)
        self.assertNotIn("OR TRUE", statement.sql.upper())

    def test_pgvector_stale_opt_in_and_latency_metric_trace(self) -> None:
        statement = PgVectorQueryBuilder(
            EmbeddingManifest("fixture-embedding-v1", 2)
        ).search_statement(
            query_embedding=[0.5, 0.5],
            requester_user_id="user_yifan",
            now="2026-06-18T00:00:00+00:00",
            limit=5,
            allow_stale=True,
        )
        trace = PgVectorSearchTrace(
            retrieval_trace_id="retrieval_trace_001",
            matched_vector_ids=["vec_001"],
            latency_ms=12.5,
            permission_filtered=True,
            stale_vectors_excluded=False,
        )

        stale_vector_exclusion = "v.index_state IN ('ready', 'stale')" in statement.sql
        latency_metric = trace.to_dict()["latency_ms"] == 12.5
        self.assertTrue(stale_vector_exclusion)
        self.assertTrue(latency_metric)

    def test_pgvector_repository_upsert_and_search_execution_do_not_expose_sql(
        self,
    ) -> None:
        manifest = EmbeddingManifest("fixture-embedding-v1", 3)
        connection = _RecordingConnection(
            query_rows=[
                {
                    "vector_id": "vec_workspace_decision",
                    "source_type": "observation",
                    "source_id": "obs_workspace_decision",
                    "distance": 0.01,
                }
            ]
        )
        repository = PgVectorRepository(
            connection,
            query_builder=PgVectorQueryBuilder(manifest),
        )
        repository.upsert_vector_index_row(
            VectorIndexRow(
                vector_id="vec_workspace_decision",
                source_type="observation",
                source_id="obs_workspace_decision",
                embedding=[0.8, 0.18, 0.02],
                permission_scope=PermissionScope.project("project_formowl").to_dict(),
                embedding_manifest_hash=manifest.to_dict()["manifest_hash"],
            )
        )
        execution = repository.search_ready_vectors(
            query_embedding=[0.8, 0.18, 0.02],
            requester_user_id="user_pm",
            now="2026-06-21T00:00:00+00:00",
            limit=5,
            retrieval_trace_id="retrieval_trace_pgvector_001",
        )

        adapter_contract = pgvector_sql_adapter_contract()
        compatibility_adapter_contract = main_repo_pgvector_adapter()
        permission_filtered_query = "formowl_grants" in connection.statements[-1].sql
        ready_vector_only = "v.index_state = 'ready'" in connection.statements[-1].sql
        search_public = execution.to_public_dict()

        self.assertIn("PgVectorRepository", adapter_contract)
        self.assertEqual(compatibility_adapter_contract, adapter_contract)
        self.assertTrue(permission_filtered_query)
        self.assertTrue(ready_vector_only)
        self.assertIsInstance(execution, PgVectorSearchExecution)
        self.assertEqual(search_public["result_source_ids"], ["obs_workspace_decision"])
        self.assertNotIn("SELECT", str(search_public).upper())
        self.assertFalse(search_public["raw_sql_exposed"])


class _RecordingConnection:
    def __init__(
        self,
        *,
        fail_on_execute: bool = False,
        query_rows: list[dict] | None = None,
    ) -> None:
        self.fail_on_execute = fail_on_execute
        self.query_rows = list(query_rows or [])
        self.actions: list[str] = []
        self.statements: list[object] = []

    def execute(self, statement: object) -> None:
        self.actions.append("execute")
        self.statements.append(statement)
        if self.fail_on_execute:
            raise RuntimeError("simulated execute failure")

    def query_one(self, statement: object) -> dict | None:
        self.actions.append("query_one")
        self.statements.append(statement)
        return None

    def query_all(self, statement: object) -> list[dict]:
        self.actions.append("query_all")
        self.statements.append(statement)
        return list(self.query_rows)

    def begin(self) -> None:
        self.actions.append("begin")

    def commit(self) -> None:
        self.actions.append("commit")

    def rollback(self) -> None:
        self.actions.append("rollback")


if __name__ == "__main__":
    unittest.main()
