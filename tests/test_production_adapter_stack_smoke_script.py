from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "production_adapter_stack_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "production_adapter_stack_smoke",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load production adapter stack smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProductionAdapterStackSmokeScriptTests(unittest.TestCase):
    def test_valid_containerized_report_passes_without_production_claims(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()

        validation = smoke.validate_report(report)

        self.assertTrue(validation["passed"])
        self.assertTrue(
            validation["claim_boundary"][
                "supports_containerized_end_to_end_adapter_stack_smoke_claim"
            ]
        )
        self.assertFalse(validation["claim_boundary"]["supports_production_adapter_ready_claim"])

    def test_report_rejects_non_containerized_artifact(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["metrics"]["containerized_smoke_executed"] = False
        report["metrics"]["adapter_stack_smoke_passed"] = False
        report["claim_boundary"]["supports_containerized_end_to_end_adapter_stack_smoke_claim"] = (
            False
        )

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed: containerized_smoke_executed",
            validation["blockers"],
        )

    def test_report_rejects_raw_path_or_sql_leak(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["safe_outputs"]["debug"] = "/workspace/private/customer.xlsx"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "public artifact leaks raw paths, SQL, or internal values",
            validation["blockers"],
        )

    def test_report_rejects_canonical_or_raw_access_overclaim(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["claim_boundary"]["supports_canonical_graph_commit_claim"] = True
        report["claim_boundary"]["supports_raw_access_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim true: supports_canonical_graph_commit_claim",
            validation["blockers"],
        )
        self.assertIn(
            "forbidden claim true: supports_raw_access_claim",
            validation["blockers"],
        )

    def test_report_rejects_missing_visible_candidate(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["metrics"]["visible_candidate_count"] = 0

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("no requester-visible candidate was retained", validation["blockers"])

    def test_report_rejects_empty_or_unsafe_raw_asset_refs(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["safe_outputs"]["retrieval"]["raw_allowed_refs"] = []
        report["metrics"]["raw_asset_ref_count"] = 0
        report["metrics"]["raw_asset_ref_payload_safe"] = False
        report["metrics"]["adapter_stack_smoke_passed"] = False

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed: raw_asset_ref_payload_safe",
            validation["blockers"],
        )
        self.assertIn(
            "raw-asset reference payload was not exercised",
            validation["blockers"],
        )

    def test_report_rejects_self_reported_no_canonical_write_without_inventory(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["safe_outputs"]["state_verification"]["canonical_artifact_unexpected_paths"] = [
            "canonical-commits/commit_001.json"
        ]
        report["metrics"]["canonical_artifact_absent"] = False
        report["metrics"]["canonical_artifact_unexpected_count"] = 1
        report["metrics"]["adapter_stack_smoke_passed"] = False

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed: canonical_artifact_absent",
            validation["blockers"],
        )
        self.assertIn(
            "unexpected canonical graph artifact was written",
            validation["blockers"],
        )


def _valid_report() -> dict:
    return {
        "artifact_id": "main_repo_production_adapter_stack_smoke_v1",
        "repo_reference": "main_repo_workspace",
        "repo_path_redacted": True,
        "safe_outputs": {
            "retrieval": {
                "denied_status": "ok",
                "allowed_source_ids": ["obs_orion_visible"],
                "revoked_source_ids": [],
                "raw_denied_status": "permission_denied",
                "raw_allowed_content_returned": [False],
                "raw_allowed_refs": [
                    {
                        "source_type": "observation",
                        "source_id": "obs_orion_visible",
                        "access": "explicit_grant_required",
                        "content_returned": False,
                    }
                ],
            },
            "semantic_gateway": {
                "tool_names": [
                    "preview_graph_candidates",
                    "query_effective_graph",
                    "submit_graph_review_decision",
                    "generate_wiki_draft_from_graph_view",
                ],
                "query_status": "ok",
                "forbidden_tool_status": "error",
                "tool_call_log_count": 3,
            },
            "resolution": {
                "visible_candidate_ids": ["fusion_visible"],
                "private_candidate_count": 1,
                "review_packet_item_count": 1,
                "review_packet_reviewable_item_count": 1,
            },
            "wiki_projection": {
                "draft_id": "draft_graph_fixture",
                "revision_status": "draft",
                "projection_spec_id": "projection_fixture",
                "graph_revision_id": "graph_revision_adapter_stack_smoke_001",
                "ontology_revision_id": "ontology_revision_adapter_stack_smoke_001",
                "user_graph_revision_id": "ugraph_adapter_stack_smoke_001",
                "citation_count": 1,
            },
            "state_verification": {
                "initial_file_count": 4,
                "final_file_count": 6,
                "workspace_file_inventory": [
                    "audit/logs/audit_001.json",
                    "index/graph-projections/nodes/node_orion_visible.json",
                    "index/vectors/vec_orion_visible.json",
                    "logs/wiki-mcp-tool-calls.jsonl",
                    "wiki/drafts/draft_graph_fixture.json",
                ],
                "canonical_artifact_unexpected_paths": [],
            },
        },
        "metrics": {
            "containerized_smoke_executed": True,
            "retrieval_gateway_executed": True,
            "grant_check_before_content": True,
            "evidence_snippet_visible_after_grant": True,
            "revoked_grant_blocks_content": True,
            "raw_asset_requires_explicit_grant": True,
            "raw_asset_mode_returns_reference_not_content": True,
            "raw_asset_ref_count": 1,
            "raw_asset_ref_payload_safe": True,
            "semantic_mcp_gateway_executed": True,
            "semantic_mcp_forbidden_tool_rejected": True,
            "semantic_gateway_tool_call_logs_written": True,
            "rapidfuzz_package_imported": True,
            "splink_package_imported": True,
            "rapidfuzz_candidate_count": 2,
            "rapidfuzz_same_as_candidate_count": 1,
            "splink_candidate_count": 2,
            "splink_same_as_candidate_count": 1,
            "splink_clerical_review_item_count": 1,
            "visible_candidate_count": 1,
            "hidden_private_candidates_redacted": True,
            "all_candidates_candidate_only": True,
            "no_raw_access_grants": True,
            "canonical_merge_guard_rejects": True,
            "raw_asset_read_guard_rejects": True,
            "wiki_projection_draft_generated": True,
            "wiki_projection_preserves_graph_lineage": True,
            "wiki_projection_draft_not_published": True,
            "canonical_artifact_inventory_checked": True,
            "canonical_artifact_unexpected_count": 0,
            "canonical_artifact_absent": True,
            "no_canonical_writes": True,
            "raw_access_expanded": False,
            "raw_storage_path_exposed": False,
            "safe_output_no_raw_internal_leak": True,
            "adapter_stack_smoke_passed": True,
        },
        "claim_boundary": {
            "supports_main_repo_adapter_stack_smoke_claim": True,
            "supports_containerized_end_to_end_adapter_stack_smoke_claim": True,
            "supports_production_adapter_ready_claim": False,
            "supports_end_to_end_gateway_claim": False,
            "supports_human_review_completed_claim": False,
            "supports_human_reviewed_false_merge_labels_claim": False,
            "supports_canonical_graph_commit_claim": False,
            "supports_canonical_graph_write_claim": False,
            "supports_raw_access_claim": False,
            "supports_enterprise_quality_claim": False,
            "supports_enterprise_scale_entity_resolution_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


if __name__ == "__main__":
    unittest.main()
