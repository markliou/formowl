from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "postgres_transaction_rollback_live_smoke.py"
)


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "postgres_transaction_rollback_live_smoke", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load PostgreSQL rollback live smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PostgresRollbackLiveSmokeScriptTests(unittest.TestCase):
    def test_transaction_rollback_tests_against_postgre_sql_live_report_passes(self) -> None:
        smoke = _load_smoke_module()

        validation = smoke.validate_report(_valid_report())

        self.assertTrue(validation["passed"])
        self.assertEqual(validation["blockers"], [])

    def test_live_smoke_report_rejects_failed_partial_failure_rollback(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["metrics"]["partial_failure_transaction_rolled_back"] = False
        report["safe_outputs"]["rolled_back_graph_record_count"] = 1

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed: partial_failure_transaction_rolled_back",
            validation["blockers"],
        )
        self.assertIn(
            "rolled-back graph record count should be zero",
            validation["blockers"],
        )

    def test_live_smoke_report_rejects_production_overclaim(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["claim_boundary"]["supports_production_adapter_ready_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("production readiness claim must remain false", validation["blockers"])

    def test_live_smoke_report_rejects_raw_sql_or_path_leak(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["safe_outputs"]["debug"] = "SELECT * FROM formowl_graph_records"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("public artifact leaks raw paths or SQL", validation["blockers"])


def _valid_report() -> dict:
    return {
        "artifact_id": "main_repo_postgres_transaction_rollback_live_smoke_v1",
        "run_id": "main-repo-postgres-rollback-test",
        "image_reference": "pgvector/pgvector@sha256:fixture",
        "repo_reference": "main_repo_workspace",
        "repo_path_redacted": True,
        "postgres_version": "16.14",
        "migration_files_applied": ["001_metadata_store.sql"],
        "safe_outputs": {
            "committed_graph_record_count": 1,
            "rolled_back_graph_record_count": 0,
            "rolled_back_audit_log_count": 0,
        },
        "metrics": {
            "live_postgres_transaction_rollback_smoke_executed": True,
            "metadata_migration_applied": True,
            "transactional_commit_persisted": True,
            "partial_failure_error_observed": True,
            "partial_failure_transaction_rolled_back": True,
            "graph_record_rollback_verified": True,
            "audit_log_rollback_verified": True,
            "canonical_graph_writes": False,
            "raw_access_expanded": False,
            "raw_sql_exposed": False,
            "raw_storage_path_exposed": False,
        },
        "claim_boundary": {
            "supports_main_repo_postgres_transaction_rollback_claim": True,
            "supports_live_postgresql_metadata_store_rollback_claim": True,
            "supports_production_adapter_ready_claim": False,
            "supports_end_to_end_gateway_claim": False,
            "supports_canonical_graph_write_claim": False,
        },
    }


if __name__ == "__main__":
    unittest.main()
