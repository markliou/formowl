from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "closed_beta_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "closed_beta_smoke",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load closed beta smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClosedBetaSmokeScriptTests(unittest.TestCase):
    def test_valid_containerized_report_passes_without_production_claims(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()

        validation = smoke.validate_report(report)

        self.assertTrue(validation["passed"])
        self.assertTrue(
            validation["claim_boundary"][
                "supports_trusted_internal_closed_beta_baseline_smoke_claim"
            ]
        )
        self.assertFalse(validation["claim_boundary"]["supports_production_ready_claim"])
        self.assertFalse(validation["claim_boundary"]["supports_raw_asset_content_access_claim"])

    def test_report_rejects_raw_path_or_sql_leak(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["safe_outputs"]["debug"] = {"note": "/workspace/private/customer.xlsx"}

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "public artifact leaks raw paths, SQL, or internal values",
            validation["blockers"],
        )

    def test_report_rejects_production_live_db_or_raw_content_overclaim(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["claim_boundary"]["supports_production_ready_claim"] = True
        report["claim_boundary"]["supports_live_database_readiness_claim"] = True
        report["claim_boundary"]["supports_raw_asset_content_access_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim true: supports_production_ready_claim",
            validation["blockers"],
        )
        self.assertIn(
            "forbidden claim true: supports_live_database_readiness_claim",
            validation["blockers"],
        )
        self.assertIn(
            "forbidden claim true: supports_raw_asset_content_access_claim",
            validation["blockers"],
        )

    def test_report_rejects_missing_required_smoke_metric(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        del report["metrics"]["worker_ingestion_executed"]
        report["metrics"]["closed_beta_smoke_passed"] = False
        report["claim_boundary"]["supports_trusted_internal_closed_beta_baseline_smoke_claim"] = (
            False
        )
        report["claim_boundary"]["supports_containerized_closed_beta_smoke_claim"] = False

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed or missing: worker_ingestion_executed",
            validation["blockers"],
        )

    def test_report_rejects_raw_asset_content_returned(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["safe_outputs"]["retrieval"]["raw_asset_refs"][0]["content_returned"] = True
        report["metrics"]["raw_asset_ref_returns_no_content"] = False
        report["metrics"]["raw_asset_content_returned"] = True
        report["metrics"]["closed_beta_smoke_passed"] = False
        report["claim_boundary"]["supports_trusted_internal_closed_beta_baseline_smoke_claim"] = (
            False
        )
        report["claim_boundary"]["supports_containerized_closed_beta_smoke_claim"] = False

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed or missing: raw_asset_ref_returns_no_content",
            validation["blockers"],
        )
        self.assertIn(
            "unexpected safety metric: raw_asset_content_returned",
            validation["blockers"],
        )

    def test_report_rejects_kg_facade_drift_or_remaining_gate(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["safe_outputs"]["kg_eval"]["system_agent_should_call"] = (
            "import .formowl/kg-eval scripts"
        )
        report["metrics"]["kg_eval_facade_boundary_respected"] = False
        report["metrics"]["kg_eval_remaining_gate_count"] = 1
        report["metrics"]["closed_beta_smoke_passed"] = False
        report["claim_boundary"]["supports_trusted_internal_closed_beta_baseline_smoke_claim"] = (
            False
        )
        report["claim_boundary"]["supports_containerized_closed_beta_smoke_claim"] = False

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed or missing: kg_eval_facade_boundary_respected",
            validation["blockers"],
        )
        self.assertIn("KG-eval facade reports remaining gates", validation["blockers"])

    def test_report_rejects_canonical_artifact_inventory(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["safe_outputs"]["state_verification"]["canonical_artifact_unexpected_count"] = 1
        report["safe_outputs"]["state_verification"]["canonical_artifact_unexpected_paths"] = [
            "graph/canonical-commits/commit_001.json"
        ]
        report["metrics"]["no_canonical_writes"] = False
        report["metrics"]["canonical_artifact_unexpected_count"] = 1
        report["metrics"]["closed_beta_smoke_passed"] = False
        report["claim_boundary"]["supports_trusted_internal_closed_beta_baseline_smoke_claim"] = (
            False
        )
        report["claim_boundary"]["supports_containerized_closed_beta_smoke_claim"] = False

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed or missing: no_canonical_writes",
            validation["blockers"],
        )
        self.assertIn(
            "unexpected canonical graph artifact was written",
            validation["blockers"],
        )


def _valid_report() -> dict:
    return {
        "artifact_id": "formowl_closed_beta_readiness_smoke_v1",
        "repo_reference": "main_repo_workspace",
        "repo_path_redacted": True,
        "safe_outputs": {
            "storage": {
                "backend_status": "ok",
                "backend": {
                    "storage_backend_id": "storage_closed_beta_local",
                    "type": "local_fs",
                    "display_name": "Closed beta local object backend",
                    "access_mode": "read_write",
                    "trust_level": "trusted_internal",
                    "workspace_scope": "workspace_closed_beta",
                    "health_status": "healthy",
                    "root_prefix": "formowl://storage/storage_closed_beta_local",
                    "allowed_workers": ["worker_closed_beta"],
                },
                "private_root_returned": False,
            },
            "jsonrpc": {
                "project_server": "formowl-project-mcp-jsonrpc",
                "project_tool_count": 7,
                "project_context_status": "ok",
                "project_evidence_snapshot_count": 1,
                "wiki_server": "formowl-wiki-mcp-jsonrpc",
                "wiki_draft_status": "ok",
                "wiki_draft_id": "draft_adr_closed_beta",
                "publish_status": "pending_review",
                "transcript_entry_count": 6,
            },
            "worker_ingestion": {
                "asset_id": "asset_closed_beta",
                "ingestion_job_id": "job_closed_beta",
                "job_status": "succeeded",
                "worker_id": "worker_closed_beta",
                "processed_job_count": 1,
                "succeeded_job_count": 1,
                "observation_count": 1,
                "extractor_run_count": 1,
            },
            "observation_wiki_bridge": {
                "context_package_id": "ctx_closed_beta",
                "context_type": "text_observation_context",
                "draft_status": "ok",
                "draft_id": "draft_observation_closed_beta",
                "citation_count": 1,
            },
            "retrieval": {
                "denied_status": "ok",
                "denied_evidence_count": 0,
                "allowed_evidence_source_ids": ["obs_closed_beta_visible"],
                "raw_denied_status": "permission_denied",
                "raw_asset_refs": [
                    {
                        "source_type": "observation",
                        "source_id": "obs_closed_beta_visible",
                        "asset_locator": "formowl://asset/asset_closed_beta",
                        "access": "explicit_grant_required",
                        "content_returned": False,
                    }
                ],
            },
            "kg_eval": {
                "artifact_id": "formowl_kg_eval_acceptance_summary_v1",
                "command_returncodes": {
                    "total": 0,
                    "objective": 0,
                    "preflight": 0,
                    "work-orders": 0,
                    "progress": 0,
                },
                "total_acceptance_overall_passed": True,
                "remaining_gate_count": 0,
                "system_agent_should_call": "formowl-kg-eval summary",
                "raw_backend_surfaces_exposed": False,
            },
            "state_verification": {
                "initial_file_count": 0,
                "final_file_count": 8,
                "canonical_artifact_unexpected_count": 0,
                "canonical_artifact_unexpected_paths": [],
            },
        },
        "metrics": {
            "containerized_smoke_executed": True,
            "storage_backend_registry_configured": True,
            "storage_public_envelope_redacted": True,
            "project_jsonrpc_initialized": True,
            "project_jsonrpc_tools_listed": True,
            "project_context_snapshot_created": True,
            "wiki_jsonrpc_draft_generated": True,
            "wiki_publish_proposal_only": True,
            "jsonrpc_hash_only_transcripts": True,
            "jsonrpc_transcript_entry_count": 6,
            "worker_ingestion_executed": True,
            "worker_job_succeeded": True,
            "observation_persisted": True,
            "worker_result_no_raw_internal_leak": True,
            "observation_count": 1,
            "observation_context_package_built": True,
            "observation_context_wiki_draft_generated": True,
            "retrieval_gateway_executed": True,
            "retrieval_grant_check_before_content": True,
            "retrieval_evidence_visible_after_grant": True,
            "retrieval_evidence_snippet_count": 1,
            "raw_asset_requires_explicit_grant": True,
            "raw_asset_ref_returns_formowl_locator": True,
            "raw_asset_ref_returns_no_content": True,
            "raw_asset_ref_count": 1,
            "kg_eval_commands_refreshed": True,
            "kg_eval_facade_summary_loaded": True,
            "kg_eval_facade_boundary_respected": True,
            "kg_eval_remaining_gate_count": 0,
            "public_outputs_validated": True,
            "safe_output_no_raw_internal_leak": True,
            "no_canonical_writes": True,
            "canonical_artifact_unexpected_count": 0,
            "automatic_publish_not_performed": True,
            "raw_asset_content_returned": False,
            "raw_storage_path_exposed": False,
            "live_database_required": False,
            "mail_adapter_exercised": False,
            "canonical_graph_write_performed": False,
            "closed_beta_smoke_passed": True,
        },
        "claim_boundary": {
            "supports_trusted_internal_closed_beta_baseline_smoke_claim": True,
            "supports_containerized_closed_beta_smoke_claim": True,
            "supports_production_ready_claim": False,
            "supports_live_database_readiness_claim": False,
            "supports_automatic_publishing_claim": False,
            "supports_raw_asset_content_access_claim": False,
            "supports_canonical_graph_write_claim": False,
            "supports_mail_adapter_readiness_claim": False,
            "supports_enterprise_scale_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


if __name__ == "__main__":
    unittest.main()
