from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pgvector_repository_live_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("pgvector_repository_live_smoke", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load pgvector live smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PgVectorLiveSmokeScriptTests(unittest.TestCase):
    def test_valid_sanitized_live_smoke_report_passes(self) -> None:
        smoke = _load_smoke_module()

        validation = smoke.validate_report(_valid_report(smoke))

        self.assertTrue(validation["passed"])
        self.assertEqual(validation["blockers"], [])

    def test_live_smoke_report_rejects_production_overclaim(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report(smoke)
        report["claim_boundary"]["supports_production_adapter_ready_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("production readiness claim must remain false", validation["blockers"])

    def test_live_smoke_report_rejects_raw_sql_or_path_leak(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report(smoke)
        report["safe_outputs"]["debug"] = "SELECT * FROM formowl_vector_index"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("public artifact leaks raw paths or SQL", validation["blockers"])

    def test_live_smoke_report_rejects_missing_source_binding_hashes(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report(smoke)
        del report["runner_script_sha256"]
        del report["container_entrypoint_sha256"]
        del report["migration_manifest_sha256"]
        del report["output_manifest_sha256"]

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("runner script hash mismatch", validation["blockers"])
        self.assertIn("container entrypoint hash mismatch", validation["blockers"])
        self.assertIn("migration manifest hash mismatch", validation["blockers"])
        self.assertIn("output manifest hash mismatch", validation["blockers"])

    def test_live_smoke_report_rejects_stale_output_binding(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report(smoke)
        report["safe_outputs"]["ready_result_source_ids"] = ["obs_workspace_decision", "obs_extra"]

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("output manifest hash mismatch", validation["blockers"])
        self.assertIn(
            "ready result source ids do not prove permission filtering",
            validation["blockers"],
        )


def _valid_report(smoke) -> dict:
    safe_outputs = {
        "ready_result_source_ids": ["obs_workspace_decision"],
        "post_revoke_result_source_ids": [],
    }
    return {
        "artifact_id": "main_repo_pgvector_repository_live_smoke_v1",
        "run_id": "main-repo-pgvector-live-test",
        "image_reference": smoke.PGVECTOR_IMAGE,
        "runner_script_sha256": smoke.sha256_file(SCRIPT_PATH),
        "container_entrypoint_sha256": smoke.sha256_file(
            SCRIPT_PATH.parent / "pgvector_repository_live_smoke_container.sh"
        ),
        "repo_reference": "main_repo_workspace",
        "repo_path_redacted": True,
        "postgres_version": "16.14",
        "extension_version": "0.8.3",
        "migration_manifest_sha256": smoke.sha256_json(smoke.migration_manifest()),
        "migration_files_applied": ["001_metadata_store.sql", "002_vector_index.sql"],
        "output_manifest_sha256": smoke.sha256_json(safe_outputs),
        "safe_outputs": safe_outputs,
        "metrics": {
            "live_postgres_pgvector_repository_smoke_executed": True,
            "migration_replay_applied": True,
            "permission_filtered_sql_vector_query_tests": True,
            "stale_vector_regression_against_pgvector": True,
            "private_ungranted_vector_excluded": True,
            "revoked_grant_regression": True,
            "canonical_graph_writes": False,
            "raw_access_expanded": False,
            "raw_sql_exposed": False,
        },
        "claim_boundary": {
            "supports_main_repo_pgvector_live_smoke_claim": True,
            "supports_permission_filtered_sql_vector_query_claim": True,
            "supports_stale_vector_regression_against_pgvector_claim": True,
            "supports_production_adapter_ready_claim": False,
            "supports_end_to_end_gateway_claim": False,
            "supports_canonical_graph_write_claim": False,
        },
    }


if __name__ == "__main__":
    unittest.main()
