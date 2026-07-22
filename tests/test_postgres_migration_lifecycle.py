from __future__ import annotations

from pathlib import Path
import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_graph.storage import (
    PostgreSQLMigrationRunner,
    PostgreSQLUnitOfWork,
    SQLStatement,
    migration_files,
)
from formowl_graph.storage.postgres import _split_sql_statements


class _MigrationConnection:
    def __init__(
        self,
        *,
        ledger_rows: list[dict[str, object]] | None = None,
        fail_sql_contains: str | None = None,
    ) -> None:
        self.ledger_rows = list(ledger_rows or [])
        self.fail_sql_contains = fail_sql_contains
        self.actions: list[str] = []
        self.statements: list[SQLStatement] = []

    def execute(self, statement: SQLStatement) -> None:
        self.actions.append("execute")
        self.statements.append(statement)
        if self.fail_sql_contains and self.fail_sql_contains in statement.sql:
            raise RuntimeError("injected migration failure with private database detail")

    def query_one(self, statement: SQLStatement) -> dict[str, object] | None:
        self.actions.append("query_one")
        self.statements.append(statement)
        return None

    def query_all(self, statement: SQLStatement) -> list[dict[str, object]]:
        self.actions.append("query_all")
        self.statements.append(statement)
        return list(self.ledger_rows)

    def begin(self) -> None:
        self.actions.append("begin")

    def commit(self) -> None:
        self.actions.append("commit")

    def rollback(self) -> None:
        self.actions.append("rollback")


def _ledger_rows() -> list[dict[str, object]]:
    return [
        {
            "migration_id": migration.migration_id,
            "migration_version": int(migration.migration_id.split("_", 1)[0]),
            "filename": migration.filename,
            "sql_sha256": migration.sql_sha256,
            "statement_count": migration.statement_count,
            "runner_version": 1,
        }
        for migration in migration_files()
    ]


class PostgreSQLMigrationLifecycleTests(unittest.TestCase):
    def test_sql_splitter_ignores_semicolons_in_comments_quotes_and_dollar_blocks(self) -> None:
        statements = _split_sql_statements(
            """
            -- comment with a semicolon; it is not a statement boundary
            CREATE TABLE first_table (value text DEFAULT ';');
            /* block comment; still not a boundary */
            CREATE TABLE second_table (value text DEFAULT 'it''s;safe');
            DO $body$ BEGIN PERFORM ';'; END $body$;
            """
        )

        self.assertEqual(len(statements), 3)
        self.assertIn("CREATE TABLE first_table", statements[0])
        self.assertIn("CREATE TABLE second_table", statements[1])
        self.assertTrue(statements[2].startswith("DO $body$"))

    def test_mail_migration_comment_semicolon_is_not_an_executable_statement(self) -> None:
        mail_migration = next(
            item for item in migration_files() if item.filename == "004_mail_evidence.sql"
        )

        self.assertEqual(mail_migration.statement_count, 25)

    def test_apply_pending_locks_records_checksums_and_exact_replay_is_a_noop(self) -> None:
        first_connection = _MigrationConnection()
        with PostgreSQLUnitOfWork(first_connection) as unit:
            first = PostgreSQLMigrationRunner(first_connection).apply_pending()
            unit.commit()

        self.assertEqual(
            first.applied_migration_ids, tuple(item.migration_id for item in migration_files())
        )
        self.assertEqual(first.skipped_migration_ids, ())
        self.assertGreater(first.applied_statement_count, 0)
        self.assertEqual(first.latest_migration_version, 5)
        self.assertEqual(
            first.to_safe_dict(),
            {
                "status": "ok",
                "migration_ledger_version": 1,
                "applied_migration_count": 5,
                "skipped_migration_count": 0,
                "applied_statement_count": first.applied_statement_count,
                "latest_migration_version": 5,
            },
        )
        safe_result_text = str(first.to_safe_dict()).lower()
        for forbidden in (
            "migration_id",
            ".sql",
            "postgresql://",
            "formowl_schema_migrations",
        ):
            self.assertNotIn(forbidden, safe_result_text)
        self.assertEqual(first_connection.actions[0], "begin")
        self.assertIn("pg_advisory_xact_lock", first_connection.statements[0].sql)
        self.assertEqual(
            first_connection.statements[0].parameters,
            {"lock_key": 0x466F726D4F776C},
        )
        self.assertIn("formowl_schema_migrations", first_connection.statements[1].sql)
        inserts = [
            statement
            for statement in first_connection.statements
            if statement.sql.startswith("INSERT INTO formowl_schema_migrations")
        ]
        self.assertEqual(len(inserts), len(migration_files()))
        self.assertEqual(
            [statement.parameters["migration_version"] for statement in inserts],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(first_connection.actions[-1], "commit")

        replay_connection = _MigrationConnection(ledger_rows=_ledger_rows())
        with PostgreSQLUnitOfWork(replay_connection) as unit:
            replay = PostgreSQLMigrationRunner(replay_connection).apply_pending()
            unit.commit()

        self.assertEqual(replay.applied_migration_ids, ())
        self.assertEqual(
            replay.skipped_migration_ids, tuple(item.migration_id for item in migration_files())
        )
        self.assertEqual(replay.applied_statement_count, 0)
        self.assertFalse(
            any(
                statement.sql.startswith("INSERT INTO formowl_schema_migrations")
                for statement in replay_connection.statements
            )
        )
        self.assertEqual(
            replay_connection.actions, ["begin", "execute", "execute", "query_all", "commit"]
        )

    def test_checksum_version_and_history_drift_fail_closed(self) -> None:
        cases: list[tuple[str, list[dict[str, object]]]] = []
        checksum_rows = _ledger_rows()
        checksum_rows[0] = {**checksum_rows[0], "sql_sha256": "sha256:" + "0" * 64}
        cases.append(("checksum", checksum_rows))
        version_rows = _ledger_rows()
        version_rows[0] = {**version_rows[0], "migration_version": 99}
        cases.append(("version", version_rows))
        cases.append(("gap", _ledger_rows()[1:]))
        unknown_rows = _ledger_rows()
        unknown_rows.append(
            {
                "migration_id": "999_future",
                "migration_version": 999,
                "filename": "999_future.sql",
                "sql_sha256": "sha256:" + "9" * 64,
                "statement_count": 1,
                "runner_version": 2,
            }
        )
        cases.append(("future", unknown_rows))

        for case_name, rows in cases:
            with self.subTest(case=case_name):
                connection = _MigrationConnection(ledger_rows=rows)
                with self.assertRaises(ContractValidationError):
                    with PostgreSQLUnitOfWork(connection):
                        PostgreSQLMigrationRunner(connection).apply_pending()
                self.assertEqual(connection.actions[-1], "rollback")
                self.assertFalse(
                    any(
                        statement.sql.startswith("INSERT INTO formowl_schema_migrations")
                        for statement in connection.statements
                    )
                )

    def test_failed_pending_migration_rolls_back_prior_ledger_writes(self) -> None:
        connection = _MigrationConnection(
            fail_sql_contains="CREATE EXTENSION IF NOT EXISTS vector",
        )

        with self.assertRaisesRegex(RuntimeError, "injected migration failure"):
            with PostgreSQLUnitOfWork(connection) as unit:
                PostgreSQLMigrationRunner(connection).apply_pending()
                unit.commit()

        self.assertEqual(connection.actions[-1], "rollback")
        self.assertNotIn("commit", connection.actions)
        ledger_inserts = [
            statement.parameters["migration_id"]
            for statement in connection.statements
            if statement.sql.startswith("INSERT INTO formowl_schema_migrations")
        ]
        self.assertEqual(ledger_inserts, ["001_metadata_store"])

    def test_oauth_migration_replays_identity_user_pair_constraints(self) -> None:
        oauth_migration = next(
            item for item in migration_files() if item.filename == "005_oauth_identity.sql"
        )
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "python/formowl_graph/storage/migrations"
            / oauth_migration.filename
        )
        migration_sql = migration_path.read_text(encoding="utf-8")
        normalized_sql = " ".join(migration_sql.split())
        statements = _split_sql_statements(migration_sql)

        self.assertIn(
            "CONSTRAINT uq_formowl_external_identity_user "
            "UNIQUE (external_identity_id, user_id)",
            normalized_sql,
        )
        self.assertIn(
            "CONSTRAINT fk_formowl_client_authorization_identity_user "
            "FOREIGN KEY (external_identity_id, user_id) REFERENCES "
            "formowl_external_identities(external_identity_id, user_id) ON DELETE RESTRICT",
            normalized_sql,
        )
        self.assertEqual(
            sum("uq_formowl_external_identity_user" in statement for statement in statements),
            2,
        )
        self.assertEqual(
            sum(
                "fk_formowl_client_authorization_identity_user" in statement
                for statement in statements
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
