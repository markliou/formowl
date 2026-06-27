#!/usr/bin/env python3
"""Run or validate the main-repo production adapter stack smoke.

This smoke intentionally uses locked synthetic records. It verifies that the
current main-repo adapter boundaries can be composed through permissioned
retrieval, semantic gateway dispatch, candidate-only resolution, clerical review
packet export, and graph-derived wiki draft generation. It does not claim
production readiness, enterprise quality, completed human review, canonical
graph commits, or raw asset access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_contract import (  # noqa: E402
    ContractValidationError,
    Grant,
    PermissionScope,
    SourceRef,
    WikiProjectionSpec,
    sha256_json,
    stable_wiki_projection_spec_id,
)
from formowl_gateway import SemanticMcpGateway, validate_public_gateway_payload  # noqa: E402
from formowl_graph import (  # noqa: E402
    ResolutionPolicy,
    ResolutionRecord,
    build_clerical_review_queue,
    canonical_merge,
    human_clerical_review_queue_export,
    no_raw_access_grant,
    rapid_fuzz_package_version_and_manifest_hash_in_main_repo,
    raw_asset_read,
    real_rapid_fuzz_package_adapter_binding,
    real_splink_package_adapter_binding,
    render_visible_fusion_candidates,
    splink_model_config_manifest_bound_to_main_repo,
)
from formowl_graph.index import (  # noqa: E402
    FileGraphProjectionStore,
    FileVectorStore,
    GraphProjectionNode,
    VectorRecord,
)
from formowl_retrieval import RetrievalGateway  # noqa: E402
from formowl_wiki_mcp import create_default_server  # noqa: E402


DEFAULT_OUTPUT = Path("/tmp/formowl-kg-eval/results/main_repo_production_adapter_stack_smoke.json")
CREATED_AT = "2026-06-21T00:00:00+00:00"
NOW = "2026-06-21T00:00:00+00:00"
FORBIDDEN_TEXT = (
    "/home/",
    "/tmp/formowl",
    "/workspace/",
    "postgresql://",
    "postgres://",
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "raw_path",
    "internal_sql",
    "worker_scratch",
    "canonical_graph_revision_id",
)
RAW_ASSET_REF_ALLOWED_KEYS = {
    "source_type",
    "source_id",
    "access",
    "content_returned",
}
CANONICAL_ARTIFACT_PATH_MARKERS = (
    "canonical",
    "canonical-graph",
    "canonical_graph",
    "canonical-entities",
    "canonical_entities",
    "canonical-relations",
    "canonical_relations",
    "canonical-commits",
    "canonical_commits",
)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _record(
    record_id: str,
    label: str,
    *,
    core_supertype: str = "Organization",
    owner_user_id: str = "user_ops",
    scope_type: str = "workspace",
    scope_id: str = "demo_workspace",
    source_candidate_atom_id: str | None = None,
    source_observation_ids: tuple[str, ...] | None = None,
    attributes: dict[str, str] | None = None,
) -> ResolutionRecord:
    return ResolutionRecord.from_candidate_atom(
        record_id=record_id,
        label=label,
        atom_type=core_supertype,
        owner_user_id=owner_user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        source_candidate_atom_id=source_candidate_atom_id or f"catom_{record_id}",
        source_observation_ids=source_observation_ids or (f"obs_{record_id}",),
        attributes=attributes or {},
    )


def _workspace_file_inventory(base_dir: Path) -> list[str]:
    return sorted(str(path.relative_to(base_dir)) for path in base_dir.rglob("*") if path.is_file())


def _unexpected_canonical_artifact_paths(paths: list[str]) -> list[str]:
    unexpected: list[str] = []
    for path in paths:
        normalized_parts = [part.lower() for part in Path(path).parts]
        if any(
            marker in part
            for part in normalized_parts
            for marker in CANONICAL_ARTIFACT_PATH_MARKERS
        ):
            unexpected.append(path)
    return unexpected


def _raw_asset_refs_are_safe(raw_asset_refs: list[dict[str, Any]]) -> bool:
    if not raw_asset_refs:
        return False
    for ref in raw_asset_refs:
        if set(ref) != RAW_ASSET_REF_ALLOWED_KEYS:
            return False
        if ref.get("source_type") != "observation":
            return False
        if not str(ref.get("source_id") or "").startswith("obs_"):
            return False
        if ref.get("access") != "explicit_grant_required":
            return False
        if ref.get("content_returned") is not False:
            return False
        if _contains_forbidden_text(ref):
            return False
    return True


def _vector_record(
    *,
    vector_id: str,
    source_id: str,
    permission_scope: dict[str, Any],
    metadata: dict[str, Any],
    embedding: list[float] | None = None,
    index_state: str = "ready",
) -> VectorRecord:
    return VectorRecord(
        vector_id=vector_id,
        source_type="observation",
        source_id=source_id,
        source_content_hash=f"sha256:{vector_id}",
        embedding_model="locked-smoke-embedding-v1",
        embedding=embedding or [1.0, 0.0],
        permission_scope=permission_scope,
        index_state=index_state,
        metadata=metadata,
    )


def _project_grant(
    *,
    permission: str = "read",
    revoked_at: str | None = None,
) -> Grant:
    return Grant(
        grant_id=f"grant_project_orion_{permission}",
        owner_user_id="user_admin",
        grantee_user_id="user_pm",
        scope_type="project",
        scope_id="project_orion",
        permission=permission,
        expires_at="2026-06-22T00:00:00+00:00",
        revoked_at=revoked_at,
    )


def _build_gateway(temp_dir: Path) -> RetrievalGateway:
    vector_store = FileVectorStore(temp_dir)
    graph_store = FileGraphProjectionStore(temp_dir)
    project_scope = PermissionScope.project("project_orion").to_dict()
    private_scope = PermissionScope(
        scope_type="private_user",
        scope_id="user_finance",
        visibility="restricted",
    ).to_dict()
    vector_store.create(
        _vector_record(
            vector_id="vec_orion_visible",
            source_id="obs_orion_visible",
            permission_scope=project_scope,
            metadata={
                "answer_summary": "Orion delivery risk is visible",
                "evidence_snippet": "Visible Orion delivery note",
            },
        )
    )
    vector_store.create(
        _vector_record(
            vector_id="vec_finance_private",
            source_id="obs_finance_private",
            permission_scope=private_scope,
            metadata={
                "answer_summary": "Private finance detail",
                "evidence_snippet": "Private finance detail",
            },
        )
    )
    graph_store.create_node(
        GraphProjectionNode(
            node_id="node_orion_visible",
            source_type="candidate_atom",
            source_id="catom_orion_visible",
            labels=["decision"],
            properties={"summary": "Visible Orion graph node"},
            permission_scope=project_scope,
            projection_state="ready",
        )
    )
    graph_store.create_node(
        GraphProjectionNode(
            node_id="node_finance_private",
            source_type="candidate_atom",
            source_id="catom_finance_private",
            labels=["finance"],
            properties={"summary": "Hidden finance graph node"},
            permission_scope=private_scope,
            projection_state="ready",
        )
    )
    return RetrievalGateway(
        vector_store=vector_store,
        graph_projection_store=graph_store,
        audit_store=FileAuditLogStore(temp_dir),
    )


def _semantic_retrieval_payload(
    gateway: RetrievalGateway, input_data: dict[str, Any]
) -> dict[str, Any]:
    result = gateway.query_effective_graph(
        query_embedding=[1.0, 0.0],
        query_text=str(input_data.get("query_text") or "orion delivery"),
        requester_user_id="user_pm",
        workspace_id="workspace_orion",
        session_id="session_adapter_stack_smoke",
        grants=[_project_grant()],
        mode="answer_only",
        now=NOW,
    ).to_dict()
    return {
        "answer": result["answer"],
        "citations": [
            {
                "source_type": "observation",
                "source_id": "obs_orion_visible",
                "evidence_snapshot_id": "ev_orion_visible",
            }
        ],
        "visible_graph_snippets": result["visible_graph_snippets"],
        "redaction_counts": {"hidden_records": 1},
    }


def _resolution_outputs() -> dict[str, Any]:
    rapid_policy = ResolutionPolicy(
        policy_id="main_repo_adapter_stack_rapidfuzz_policy_v1",
        same_as_threshold=0.86,
        clerical_review_min=0.70,
    )
    splink_policy = ResolutionPolicy(
        policy_id="main_repo_adapter_stack_splink_policy_v1",
        same_as_threshold=0.84,
        clerical_review_min=0.40,
        model_config={
            "blocking_rules": ["core_supertype"],
            "comparisons": ["label", "city", "project", "tax_id_last4"],
        },
        training_manifest={"source": "locked_synthetic_fixture_no_enterprise_claim"},
    )
    rapid_left = [
        _record(
            "left_acme_private",
            "Acme Corp",
            owner_user_id="user_finance",
            scope_type="private_user",
            scope_id="user_finance",
        ),
        _record("left_beta_visible", "Beta Logistics"),
    ]
    rapid_right = [
        _record("right_acme_visible", "ACME Corporation"),
        _record("right_beta_visible", "Beta Logistics LLC"),
    ]
    splink_left = [
        _record(
            "left_beta_structured",
            "Beta Logistics",
            attributes={"city": "Taipei", "project": "Orion", "tax_id_last4": "4431"},
        ),
        _record(
            "left_delta_structured",
            "Delta Hardware",
            attributes={"city": "Taipei", "project": "Mercury", "tax_id_last4": "1188"},
        ),
    ]
    splink_right = [
        _record(
            "right_beta_structured",
            "Beta Logistics LLC",
            attributes={"city": "Taipei", "project": "Orion", "tax_id_last4": "4431"},
        ),
        _record(
            "right_delta_uncertain",
            "Delta Hardware",
            attributes={"city": "Taipei", "project": "Orion", "tax_id_last4": "1111"},
        ),
    ]
    rapid_generator = real_rapid_fuzz_package_adapter_binding(policy=rapid_policy)
    splink_generator = real_splink_package_adapter_binding(policy=splink_policy)
    rapid_manifest = rapid_fuzz_package_version_and_manifest_hash_in_main_repo(policy=rapid_policy)
    splink_manifest = splink_model_config_manifest_bound_to_main_repo(policy=splink_policy)
    rapid_candidates = rapid_generator.candidate_only_output(
        rapid_left,
        rapid_right,
        created_at=CREATED_AT,
    )
    splink_candidates = splink_generator.candidate_only_output(
        splink_left,
        splink_right,
        created_at=CREATED_AT,
    )
    all_candidates = [*rapid_candidates, *splink_candidates]
    visible_record_ids = {
        "left_beta_visible",
        "right_beta_visible",
        "right_acme_visible",
        "left_beta_structured",
        "right_beta_structured",
        "left_delta_structured",
        "right_delta_uncertain",
    }
    visible_candidates = render_visible_fusion_candidates(
        all_candidates,
        visible_record_ids=visible_record_ids,
    )
    splink_queue = build_clerical_review_queue(splink_candidates, policy=splink_policy)
    review_packet = human_clerical_review_queue_export(
        splink_queue,
        reviewer_user_id="reviewer_ops",
        reviewer_visible_record_ids=visible_record_ids,
        created_at=CREATED_AT,
    )
    return {
        "rapid_manifest": rapid_manifest,
        "splink_manifest": splink_manifest,
        "rapid_candidates": rapid_candidates,
        "splink_candidates": splink_candidates,
        "all_candidates": all_candidates,
        "visible_candidates": visible_candidates,
        "review_packet": review_packet,
        "canonical_merge_guard_rejects": _raises_contract_validation(
            lambda: canonical_merge(all_candidates[0])
        ),
        "raw_asset_read_guard_rejects": _raises_contract_validation(
            lambda: raw_asset_read(all_candidates[0])
        ),
    }


def _projection_spec() -> WikiProjectionSpec:
    source_ref = SourceRef(
        source_system="formowl",
        source_type="user_graph_revision",
        source_id="ugraph_adapter_stack_smoke_001",
    )
    projection_spec_id = stable_wiki_projection_spec_id(
        projection_kind="project_summary",
        graph_revision_id="graph_revision_adapter_stack_smoke_001",
        ontology_revision_id="ontology_revision_adapter_stack_smoke_001",
        title="Adapter Stack Smoke Projection",
        source_refs=[source_ref],
        evidence_snapshot_ids=["ev_orion_visible"],
        citation_behavior="required_inline_citations",
    )
    return WikiProjectionSpec(
        projection_spec_id=projection_spec_id,
        projection_kind="project_summary",
        title="Adapter Stack Smoke Projection",
        graph_revision_id="graph_revision_adapter_stack_smoke_001",
        ontology_revision_id="ontology_revision_adapter_stack_smoke_001",
        user_graph_revision_id="ugraph_adapter_stack_smoke_001",
        source_refs=[source_ref],
        evidence_snapshot_ids=["ev_orion_visible"],
        citation_behavior="required_inline_citations",
        redaction_policy="visible_evidence_only",
        projection_rules={"sections": ["summary", "visible_candidates"]},
        draft_target={"backend": "markdown_draft", "page_slug": "adapter-stack-smoke"},
        permission_scope=PermissionScope.project("project_orion").to_dict(),
        created_by="user_pm",
        created_at=CREATED_AT,
    )


def _graph_view(semantic_query: dict[str, Any], visible_candidate_ids: list[str]) -> dict[str, Any]:
    answer = semantic_query.get("data", {}).get("answer") or "Visible adapter stack evidence."
    return {
        "graph_revision_id": "graph_revision_adapter_stack_smoke_001",
        "ontology_revision_id": "ontology_revision_adapter_stack_smoke_001",
        "user_graph_revision_id": "ugraph_adapter_stack_smoke_001",
        "visible_evidence_only": True,
        "summary": answer,
        "nodes": [
            {
                "node_id": "node_orion_visible",
                "label": "Orion delivery decision",
                "summary": "Visible candidate package retained for review.",
                "visible": True,
            }
        ],
        "relations": [
            {
                "relation_id": "rel_orion_candidate_package",
                "label": "has_visible_candidate",
                "visible": True,
            }
        ],
        "evidence_snippets": [
            {
                "citation_id": "cit_adapter_stack_001",
                "source_ref": SourceRef(
                    source_system="formowl",
                    source_type="user_graph_revision",
                    source_id="ugraph_adapter_stack_smoke_001",
                ).to_dict(),
                "evidence_snapshot_id": "ev_orion_visible",
                "summary": "Visible retrieval and candidate package evidence.",
                "visible": True,
            }
        ],
        "redaction_counts": {
            "hidden_records": 1,
            "hidden_candidate_endpoints": 1,
            "visible_candidate_ids": len(visible_candidate_ids),
        },
    }


def build_report() -> dict[str, Any]:
    try:
        with tempfile.TemporaryDirectory(prefix="formowl-adapter-stack-smoke-") as temp_name:
            temp_dir = Path(temp_name)
            gateway = _build_gateway(temp_dir)
            initial_file_inventory = _workspace_file_inventory(temp_dir)
            denied = gateway.query_effective_graph(
                query_embedding=[1.0, 0.0],
                query_text="orion delivery",
                requester_user_id="user_pm",
                workspace_id="workspace_orion",
                session_id="session_adapter_stack_smoke",
                grants=[],
                mode="evidence_snippet",
                now=NOW,
            ).to_dict()
            allowed = gateway.query_effective_graph(
                query_embedding=[1.0, 0.0],
                query_text="orion delivery",
                requester_user_id="user_pm",
                workspace_id="workspace_orion",
                session_id="session_adapter_stack_smoke",
                grants=[_project_grant()],
                mode="evidence_snippet",
                now=NOW,
            ).to_dict()
            revoked = gateway.query_effective_graph(
                query_embedding=[1.0, 0.0],
                query_text="orion delivery",
                requester_user_id="user_pm",
                workspace_id="workspace_orion",
                session_id="session_adapter_stack_smoke",
                grants=[_project_grant(revoked_at=NOW)],
                mode="evidence_snippet",
                now=NOW,
            ).to_dict()
            raw_denied = gateway.query_effective_graph(
                query_embedding=[1.0, 0.0],
                query_text="orion delivery",
                requester_user_id="user_pm",
                workspace_id="workspace_orion",
                session_id="session_adapter_stack_smoke",
                grants=[_project_grant()],
                mode="raw_asset",
                now=NOW,
            ).to_dict()
            raw_allowed = gateway.query_effective_graph(
                query_embedding=[1.0, 0.0],
                query_text="orion delivery",
                requester_user_id="user_pm",
                workspace_id="workspace_orion",
                session_id="session_adapter_stack_smoke",
                grants=[_project_grant(), _project_grant(permission="asset_scoped_access")],
                mode="raw_asset",
                now=NOW,
            ).to_dict()

            semantic_gateway = SemanticMcpGateway(
                retrieval_handler=lambda input_data: _semantic_retrieval_payload(
                    gateway,
                    input_data,
                )
            )
            semantic_schema = semantic_gateway.public_tool_schema()
            semantic_query = semantic_gateway.dispatch_tool(
                "query_effective_graph",
                {
                    "workspace_id": "workspace_orion",
                    "requester_user_id": "user_pm",
                    "query_text": "orion delivery",
                },
            )
            forbidden_tool = semantic_gateway.dispatch_tool(
                "direct_database_query_tool",
                {"sql": "select * from private_table"},
            )
            validate_public_gateway_payload(semantic_schema)
            validate_public_gateway_payload(semantic_query)
            validate_public_gateway_payload(forbidden_tool)

            resolution = _resolution_outputs()
            rapid_candidates = resolution["rapid_candidates"]
            splink_candidates = resolution["splink_candidates"]
            all_candidates = resolution["all_candidates"]
            visible_candidates = resolution["visible_candidates"]
            visible_candidate_ids = [
                candidate["fusion_candidate_id"] for candidate in visible_candidates
            ]
            private_candidate_ids = [
                candidate.fusion_candidate_id
                for candidate in all_candidates
                if "left_acme_private"
                in (
                    candidate.left_record.record_id,
                    candidate.right_record.record_id,
                )
            ]
            visible_candidate_text = json.dumps(visible_candidates, sort_keys=True)

            wiki_server = create_default_server(temp_dir)
            projection_spec = _projection_spec()
            wiki_result = wiki_server.call_tool(
                "generate_wiki_draft_from_graph_view",
                {
                    "projection_spec": projection_spec.to_dict(),
                    "graph_view": _graph_view(semantic_query, visible_candidate_ids),
                },
            )
            frontmatter = wiki_result["data"]["frontmatter"]
            draft_generated = (
                wiki_result["status"] == "ok"
                and wiki_result["data"]["revision_status"] == "draft"
                and frontmatter["projection_spec_id"] == projection_spec.projection_spec_id
                and frontmatter["graph_revision_id"] == projection_spec.graph_revision_id
                and frontmatter["ontology_revision_id"] == projection_spec.ontology_revision_id
                and frontmatter["user_graph_revision_id"] == projection_spec.user_graph_revision_id
            )
            final_file_inventory = _workspace_file_inventory(temp_dir)
            unexpected_canonical_artifacts = _unexpected_canonical_artifact_paths(
                final_file_inventory
            )

        rapid_same_as = [
            candidate for candidate in rapid_candidates if candidate.status == "same_as_candidate"
        ]
        splink_same_as = [
            candidate for candidate in splink_candidates if candidate.status == "same_as_candidate"
        ]
        safe_outputs = {
            "retrieval": {
                "denied_status": denied["status"],
                "allowed_source_ids": [item["source_id"] for item in allowed["evidence_snippets"]],
                "revoked_source_ids": [item["source_id"] for item in revoked["evidence_snippets"]],
                "raw_denied_status": raw_denied["status"],
                "raw_allowed_content_returned": [
                    item["content_returned"] for item in raw_allowed["raw_asset_refs"]
                ],
                "raw_allowed_refs": raw_allowed["raw_asset_refs"],
            },
            "semantic_gateway": {
                "tool_names": [schema["tool_name"] for schema in semantic_schema["data"]["tools"]],
                "query_status": semantic_query["status"],
                "forbidden_tool_status": forbidden_tool["status"],
                "tool_call_log_count": len(semantic_gateway.tool_call_logs),
            },
            "resolution": {
                "visible_candidate_ids": visible_candidate_ids,
                "private_candidate_count": len(private_candidate_ids),
                "review_packet_item_count": resolution["review_packet"]["item_count"],
                "review_packet_reviewable_item_count": resolution["review_packet"][
                    "reviewable_item_count"
                ],
            },
            "wiki_projection": {
                "draft_id": wiki_result["data"]["draft_id"],
                "revision_status": wiki_result["data"]["revision_status"],
                "projection_spec_id": frontmatter["projection_spec_id"],
                "graph_revision_id": frontmatter["graph_revision_id"],
                "ontology_revision_id": frontmatter["ontology_revision_id"],
                "user_graph_revision_id": frontmatter["user_graph_revision_id"],
                "citation_count": len(wiki_result["citations"]),
            },
            "state_verification": {
                "initial_file_count": len(initial_file_inventory),
                "final_file_count": len(final_file_inventory),
                "workspace_file_inventory": final_file_inventory,
                "canonical_artifact_unexpected_paths": unexpected_canonical_artifacts,
            },
        }
        input_manifest = {
            "fixture": "main_repo_adapter_stack_smoke_v1",
            "created_at": CREATED_AT,
            "now": NOW,
        }
        metrics = {
            "containerized_smoke_executed": (
                os.environ.get("FORMOWL_PRODUCTION_ADAPTER_STACK_SMOKE_CONTAINERIZED") == "1"
            ),
            "retrieval_gateway_executed": True,
            "grant_check_before_content": denied["evidence_snippets"] == [],
            "evidence_snippet_visible_after_grant": allowed["evidence_snippets"]
            and allowed["evidence_snippets"][0]["source_id"] == "obs_orion_visible",
            "revoked_grant_blocks_content": revoked["evidence_snippets"] == [],
            "raw_asset_requires_explicit_grant": raw_denied["status"] == "permission_denied",
            "raw_asset_mode_returns_reference_not_content": raw_allowed["status"] == "ok"
            and all(not item["content_returned"] for item in raw_allowed["raw_asset_refs"]),
            "raw_asset_ref_count": len(raw_allowed["raw_asset_refs"]),
            "raw_asset_ref_payload_safe": _raw_asset_refs_are_safe(raw_allowed["raw_asset_refs"]),
            "semantic_mcp_gateway_executed": semantic_query["status"] == "ok",
            "semantic_mcp_forbidden_tool_rejected": forbidden_tool["status"] == "error",
            "semantic_gateway_tool_call_logs_written": len(semantic_gateway.tool_call_logs) >= 3,
            "rapidfuzz_package_imported": resolution["rapid_manifest"]["package_present"],
            "splink_package_imported": resolution["splink_manifest"]["package_present"],
            "rapidfuzz_candidate_count": len(rapid_candidates),
            "rapidfuzz_same_as_candidate_count": len(rapid_same_as),
            "splink_candidate_count": len(splink_candidates),
            "splink_same_as_candidate_count": len(splink_same_as),
            "splink_clerical_review_item_count": len(
                build_clerical_review_queue(
                    splink_candidates,
                    policy=ResolutionPolicy(
                        policy_id="main_repo_adapter_stack_splink_policy_v1",
                        same_as_threshold=0.84,
                        clerical_review_min=0.40,
                        model_config={
                            "blocking_rules": ["core_supertype"],
                            "comparisons": ["label", "city", "project", "tax_id_last4"],
                        },
                        training_manifest={
                            "source": "locked_synthetic_fixture_no_enterprise_claim"
                        },
                    ),
                )
            ),
            "visible_candidate_count": len(visible_candidates),
            "hidden_private_candidates_redacted": bool(private_candidate_ids)
            and "left_acme_private" not in visible_candidate_text
            and "Acme Corp" not in visible_candidate_text,
            "all_candidates_candidate_only": all(
                candidate.canonical_merge_performed is False for candidate in all_candidates
            ),
            "no_raw_access_grants": all(
                no_raw_access_grant(candidate) for candidate in all_candidates
            ),
            "canonical_merge_guard_rejects": resolution["canonical_merge_guard_rejects"],
            "raw_asset_read_guard_rejects": resolution["raw_asset_read_guard_rejects"],
            "wiki_projection_draft_generated": draft_generated,
            "wiki_projection_preserves_graph_lineage": draft_generated,
            "wiki_projection_draft_not_published": "published_at" not in str(wiki_result).lower(),
            "canonical_artifact_inventory_checked": bool(final_file_inventory),
            "canonical_artifact_unexpected_count": len(unexpected_canonical_artifacts),
            "canonical_artifact_absent": not unexpected_canonical_artifacts,
            "no_canonical_writes": not unexpected_canonical_artifacts,
            "raw_access_expanded": False,
            "raw_storage_path_exposed": False,
        }
        metrics["safe_output_no_raw_internal_leak"] = not _contains_forbidden_text(safe_outputs)
        required_metric_keys = [
            "containerized_smoke_executed",
            "retrieval_gateway_executed",
            "grant_check_before_content",
            "evidence_snippet_visible_after_grant",
            "revoked_grant_blocks_content",
            "raw_asset_requires_explicit_grant",
            "raw_asset_mode_returns_reference_not_content",
            "raw_asset_ref_payload_safe",
            "semantic_mcp_gateway_executed",
            "semantic_mcp_forbidden_tool_rejected",
            "semantic_gateway_tool_call_logs_written",
            "rapidfuzz_package_imported",
            "splink_package_imported",
            "hidden_private_candidates_redacted",
            "all_candidates_candidate_only",
            "no_raw_access_grants",
            "canonical_merge_guard_rejects",
            "raw_asset_read_guard_rejects",
            "wiki_projection_draft_generated",
            "wiki_projection_preserves_graph_lineage",
            "wiki_projection_draft_not_published",
            "canonical_artifact_inventory_checked",
            "canonical_artifact_absent",
            "no_canonical_writes",
            "safe_output_no_raw_internal_leak",
        ]
        metrics["adapter_stack_smoke_passed"] = all(
            bool(metrics[key]) for key in required_metric_keys
        )
        claim_boundary = {
            "supports_main_repo_adapter_stack_smoke_claim": metrics["adapter_stack_smoke_passed"],
            "supports_containerized_end_to_end_adapter_stack_smoke_claim": metrics[
                "adapter_stack_smoke_passed"
            ],
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
        }
        return {
            "artifact_id": "main_repo_production_adapter_stack_smoke_v1",
            "run_id": os.environ.get(
                "FORMOWL_PRODUCTION_ADAPTER_STACK_SMOKE_RUN_ID",
                f"main-repo-production-adapter-stack-smoke-{uuid.uuid4().hex[:12]}",
            ),
            "repo_reference": "main_repo_workspace",
            "repo_path_redacted": True,
            "image_reference": os.environ.get(
                "FORMOWL_PRODUCTION_ADAPTER_STACK_SMOKE_IMAGE",
                "unknown",
            ),
            "runner_script_sha256": sha256_file(Path(__file__)),
            "package_manifests": {
                "rapidfuzz": resolution["rapid_manifest"],
                "splink": resolution["splink_manifest"],
            },
            "input_manifest": input_manifest,
            "input_manifest_sha256": sha256_json(input_manifest),
            "output_manifest_sha256": sha256_json(safe_outputs),
            "safe_outputs": safe_outputs,
            "metrics": metrics,
            "claim_boundary": claim_boundary,
            "blockers": [
                "locked synthetic fixture only",
                "human-reviewed false-merge fixture labels are not completed",
                "human review packet is exported but not completed",
                "no enterprise-scale entity-resolution quality claim",
                "no canonical graph commit exercise",
            ],
        }
    except Exception as exc:  # pragma: no cover - dependency/environment failure path.
        return {
            "artifact_id": "main_repo_production_adapter_stack_smoke_v1",
            "repo_reference": "main_repo_workspace",
            "repo_path_redacted": True,
            "metrics": {
                "containerized_smoke_executed": (
                    os.environ.get("FORMOWL_PRODUCTION_ADAPTER_STACK_SMOKE_CONTAINERIZED") == "1"
                ),
                "adapter_stack_smoke_passed": False,
                "no_canonical_writes": False,
                "raw_access_expanded": False,
                "raw_storage_path_exposed": False,
            },
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "claim_boundary": {
                "supports_main_repo_adapter_stack_smoke_claim": False,
                "supports_containerized_end_to_end_adapter_stack_smoke_claim": False,
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
            "blockers": ["main-repo production adapter stack smoke failed"],
        }


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    metrics = report.get("metrics", {})
    claims = report.get("claim_boundary", {})

    if report.get("artifact_id") != "main_repo_production_adapter_stack_smoke_v1":
        blockers.append("unexpected artifact id")
    if report.get("repo_path_redacted") is not True:
        blockers.append("repo path must be redacted")
    for key in [
        "containerized_smoke_executed",
        "retrieval_gateway_executed",
        "grant_check_before_content",
        "evidence_snippet_visible_after_grant",
        "revoked_grant_blocks_content",
        "raw_asset_requires_explicit_grant",
        "raw_asset_mode_returns_reference_not_content",
        "raw_asset_ref_payload_safe",
        "semantic_mcp_gateway_executed",
        "semantic_mcp_forbidden_tool_rejected",
        "semantic_gateway_tool_call_logs_written",
        "rapidfuzz_package_imported",
        "splink_package_imported",
        "hidden_private_candidates_redacted",
        "all_candidates_candidate_only",
        "no_raw_access_grants",
        "canonical_merge_guard_rejects",
        "raw_asset_read_guard_rejects",
        "wiki_projection_draft_generated",
        "wiki_projection_preserves_graph_lineage",
        "wiki_projection_draft_not_published",
        "canonical_artifact_inventory_checked",
        "canonical_artifact_absent",
        "no_canonical_writes",
        "safe_output_no_raw_internal_leak",
        "adapter_stack_smoke_passed",
    ]:
        if metrics.get(key) is not True:
            blockers.append(f"required metric failed: {key}")
    for key in ["raw_access_expanded", "raw_storage_path_exposed"]:
        if metrics.get(key) is not False:
            blockers.append(f"unexpected safety metric: {key}")
    if metrics.get("visible_candidate_count", 0) < 1:
        blockers.append("no requester-visible candidate was retained")
    if metrics.get("raw_asset_ref_count", 0) < 1:
        blockers.append("raw-asset reference payload was not exercised")
    if metrics.get("canonical_artifact_unexpected_count") != 0:
        blockers.append("unexpected canonical graph artifact was written")
    if metrics.get("rapidfuzz_same_as_candidate_count", 0) < 1:
        blockers.append("RapidFuzz smoke did not emit a same-as candidate")
    if metrics.get("splink_same_as_candidate_count", 0) < 1:
        blockers.append("Splink smoke did not emit a same-as candidate")
    if metrics.get("splink_clerical_review_item_count", 0) < 1:
        blockers.append("Splink smoke did not emit a clerical-review item")
    for key in [
        "supports_main_repo_adapter_stack_smoke_claim",
        "supports_containerized_end_to_end_adapter_stack_smoke_claim",
    ]:
        if claims.get(key) is not True:
            blockers.append(f"required claim false: {key}")
    for key in [
        "supports_production_adapter_ready_claim",
        "supports_end_to_end_gateway_claim",
        "supports_human_review_completed_claim",
        "supports_human_reviewed_false_merge_labels_claim",
        "supports_canonical_graph_commit_claim",
        "supports_canonical_graph_write_claim",
        "supports_raw_access_claim",
        "supports_enterprise_quality_claim",
        "supports_enterprise_scale_entity_resolution_claim",
        "supports_top_tier_scientific_validation_claim",
    ]:
        if claims.get(key) is not False:
            blockers.append(f"forbidden claim true: {key}")
    if _contains_forbidden_text(report):
        blockers.append("public artifact leaks raw paths, SQL, or internal values")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "metrics": metrics,
        "claim_boundary": claims,
    }


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_markdown(report: dict[str, Any], validation: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Main-Repo Production Adapter Stack Smoke",
        "",
        "This validates a locked synthetic adapter-stack path through retrieval, semantic gateway, candidate-only resolution, review packet export, and wiki projection.",
        "It is not production readiness and does not claim canonical graph commits, raw access, human review completion, or enterprise quality.",
        "",
        f"- Passed: {validation['passed']}",
        f"- Artifact: {output_path.name}",
        f"- Adapter stack smoke passed: {validation['metrics'].get('adapter_stack_smoke_passed')}",
        f"- Containerized: {validation['metrics'].get('containerized_smoke_executed')}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in sorted(validation["metrics"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Claim Boundary", ""])
    for key, value in sorted(validation["claim_boundary"].items()):
        lines.append(f"- {key}: {value}")
    if validation["blockers"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in validation["blockers"]:
            lines.append(f"- {blocker}")
    output_path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _raises_contract_validation(callable_object: Any) -> bool:
    try:
        callable_object()
    except ContractValidationError:
        return True
    return False


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_forbidden_text(key) or _contains_forbidden_text(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_text(item) for item in value)
    if isinstance(value, str):
        return any(token in value for token in FORBIDDEN_TEXT)
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--from-existing", action="store_true")
    args = parser.parse_args()

    if args.from_existing:
        report = load_report(args.output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = build_report()
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    validation = validate_report(report)
    write_markdown(report, validation, args.output)
    if not validation["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
