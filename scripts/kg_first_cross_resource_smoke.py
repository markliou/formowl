#!/usr/bin/env python3
"""Run or validate the deterministic issue #16 KG-first fusion smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_contract import Observation, sha256_json  # noqa: E402
from formowl_gateway import (  # noqa: E402
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
)
from formowl_graph import EffectiveGraphView  # noqa: E402
from formowl_graph.index import FileVectorStore, GraphProjectionNode, VectorRecord  # noqa: E402
from formowl_ingestion.storage import ObservationStore  # noqa: E402
from formowl_retrieval import ObservationStoreEvidenceResolver, RetrievalGateway  # noqa: E402

DEFAULT_OUTPUT = Path("/tmp/formowl-kg-first-cross-resource-smoke.json")
NOW = "2026-07-10T08:00:00+00:00"
PUBLIC_SCOPE = {"scope_type": "public", "visibility": "public"}
FORBIDDEN_TEXT = (
    "/home/",
    "/srv/",
    "/tmp/",
    "postgresql://",
    "select *",
    "raw_path",
    "worker_scratch",
)
QUERY_TEXT = "What was the final Optoma quotation decision?"
IRRELEVANT_QUERY_TEXT = "What is the employee payroll retention policy?"
FALLBACK_REASON = "graph_evidence_incomplete_fallback_used"
GRAPH_MISS_REASON = "graph_miss_fallback_used"
FALLBACK_VECTOR_ID = "vec_optoma_project_fallback"
FALLBACK_OBSERVATION_ID = "obs_optoma_project_fallback"
QUERY_EMBEDDING = [1.0, 0.0]
GRAPH_SCORE_THRESHOLD = 0.25
GRAPH_CONFIDENCE_THRESHOLD = 0.6
MINIMUM_EVIDENCE_COUNT = 3


class CountingFileVectorStore(FileVectorStore):
    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)
        self.search_call_count = 0

    def search(self, *args: Any, **kwargs: Any) -> Any:
        self.search_call_count += 1
        return super().search(*args, **kwargs)


def build_report() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="formowl-kg-first-") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        observation_store = ObservationStore(temp_dir)
        observations = _observations()
        for observation in observations:
            observation_store.create(observation)
        fallback_seed_observation = _fallback_seed_observation()
        observation_store.create(fallback_seed_observation)
        vector_store = CountingFileVectorStore(temp_dir)
        vector_store.create(_fallback_vector())
        retrieval_gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
            graph_score_threshold=GRAPH_SCORE_THRESHOLD,
            graph_confidence_threshold=GRAPH_CONFIDENCE_THRESHOLD,
            minimum_evidence_count=MINIMUM_EVIDENCE_COUNT,
        )
        full_view = _view(
            source_observation_ids=[item.observation_id for item in observations],
            source_asset_ids=[str(item.asset_id) for item in observations],
        )
        incomplete_view = _view(
            source_observation_ids=["obs_optoma_mail", "obs_optoma_missing"],
            source_asset_ids=["asset_optoma_mail"],
        )

        def scenario_gateway(view: EffectiveGraphView) -> SemanticMcpJsonRpcGateway:
            def retrieval_handler(input_data: dict[str, Any]) -> dict[str, Any]:
                result = retrieval_gateway.query_effective_graph_view(
                    query_embedding=QUERY_EMBEDDING,
                    query_text=str(input_data.get("query_text") or ""),
                    requester_user_id=str(input_data["requester_user_id"]),
                    workspace_id=str(input_data["workspace_id"]),
                    session_id=str(input_data["session_id"]),
                    mode="evidence_snippet",
                    now=NOW,
                    effective_graph_view=view,
                )
                return _semantic_payload(result.to_dict())

            return SemanticMcpJsonRpcGateway(
                semantic_gateway=SemanticMcpGateway(retrieval_handler=retrieval_handler),
                session=SemanticGatewaySession(
                    session_id="session_issue16_smoke",
                    actor_user_id="user_pm",
                    workspace_id="workspace_main",
                ),
            )

        full_gateway = scenario_gateway(full_view)
        fallback_gateway = scenario_gateway(incomplete_view)
        negative_gateway = scenario_gateway(full_view)
        listed = full_gateway.handle_json_rpc(
            {"jsonrpc": "2.0", "id": "list", "method": "tools/list"}
        )
        search_count_before_primary = vector_store.search_call_count
        full_response = _call(
            full_gateway,
            request_id="full",
            query_text=QUERY_TEXT,
        )
        primary_vector_search_count = vector_store.search_call_count - search_count_before_primary
        search_count_before_fallback = vector_store.search_call_count
        fallback_response = _call(
            fallback_gateway,
            request_id="fallback",
            query_text=QUERY_TEXT,
        )
        fallback_vector_search_count = vector_store.search_call_count - search_count_before_fallback
        search_count_before_negative = vector_store.search_call_count
        negative_response = _call(
            negative_gateway,
            request_id="negative",
            query_text=IRRELEVANT_QUERY_TEXT,
        )
        negative_vector_search_count = vector_store.search_call_count - search_count_before_negative
        full_payload = full_response["result"]["content"][0]["json"]["data"]
        fallback_payload = fallback_response["result"]["content"][0]["json"]["data"]
        negative_payload = negative_response["result"]["content"][0]["json"]["data"]
        if "graph_hits" not in full_payload:
            raise RuntimeError(json.dumps(full_response, sort_keys=True))
        tool_names = sorted(tool["name"] for tool in listed["result"]["tools"])
        files = sorted(
            str(path.relative_to(temp_dir)) for path in temp_dir.rglob("*.json") if path.is_file()
        )
        canonical_files = [path for path in files if "canonical" in path.lower()]
        transcript = (
            full_gateway.leak_transcript()
            + fallback_gateway.leak_transcript()
            + negative_gateway.leak_transcript()
        )
        fallback_vector_ids = fallback_payload["retrieval_trace"]["matched_vector_ids"]
        fallback_seed_observation_ids = sorted(
            {
                observation_id
                for seed in fallback_payload["candidate_graph_proposal_seeds"]
                for observation_id in seed["source_observation_ids"]
            }
        )
        fallback_seed_asset_ids = sorted(
            {
                asset_id
                for seed in fallback_payload["candidate_graph_proposal_seeds"]
                for asset_id in seed["source_asset_ids"]
            }
        )
        report = {
            "report_type": "kg_first_cross_resource_smoke",
            "report_version": 1,
            "fixture_hash": _fixture_hash(),
            "safe_outputs": {
                "tool_names": tool_names,
                "full_graph_object_ids": [
                    hit["graph_object_id"] for hit in full_payload["graph_hits"]
                ],
                "full_matched_vector_ids": full_payload["retrieval_trace"]["matched_vector_ids"],
                "full_evidence_modalities": sorted(
                    item["modality"] for item in full_payload["evidence"]
                ),
                "full_evidence_locators": sorted(
                    item["evidence_locator"] for item in full_payload["evidence"]
                ),
                "fallback_reason": fallback_payload["fallback_reason"],
                "fallback_evidence_coverage": fallback_payload["evidence_coverage"],
                "fallback_matched_vector_ids": fallback_vector_ids,
                "fallback_seed_ids": [
                    item["proposal_seed_id"]
                    for item in fallback_payload["candidate_graph_proposal_seeds"]
                ],
                "fallback_seed_source_observation_ids": fallback_seed_observation_ids,
                "fallback_seed_source_asset_ids": fallback_seed_asset_ids,
                "negative_graph_object_ids": [
                    hit["graph_object_id"] for hit in negative_payload["graph_hits"]
                ],
                "negative_fallback_reason": negative_payload["fallback_reason"],
                "transcript": transcript,
            },
            "metrics": {
                "jsonrpc_tool_discovered": "query_effective_graph_view" in tool_names,
                "kg_first_graph_hit_count": len(full_payload["graph_hits"]),
                "kg_first_evidence_count": len(full_payload["evidence"]),
                "kg_first_evidence_coverage": full_payload["evidence_coverage"],
                "kg_first_fallback_used": full_payload["fallback_used"],
                "kg_first_primary_vector_search_count": primary_vector_search_count,
                "kg_first_primary_trace_has_no_vectors": full_payload["retrieval_trace"][
                    "matched_vector_ids"
                ]
                == [],
                "cross_resource_modalities_present": sorted(
                    item["modality"] for item in full_payload["evidence"]
                )
                == ["mail", "project", "slide"],
                "fallback_used_for_incomplete_graph": fallback_payload["fallback_used"],
                "fallback_reason_is_evidence_incomplete": fallback_payload["fallback_reason"]
                == FALLBACK_REASON,
                "fallback_evidence_coverage_incomplete": fallback_payload["evidence_coverage"]
                < 1.0,
                "fallback_vector_lineage_present": fallback_vector_ids == [FALLBACK_VECTOR_ID],
                "fallback_seed_matches_vector_lineage": fallback_seed_observation_ids
                == [FALLBACK_OBSERVATION_ID]
                and fallback_seed_asset_ids == ["asset_optoma_project_fallback"],
                "fallback_vector_search_count": fallback_vector_search_count,
                "irrelevant_query_has_no_graph_hits": negative_payload["graph_hits"] == [],
                "irrelevant_query_uses_graph_miss_fallback": negative_payload["fallback_reason"]
                == GRAPH_MISS_REASON,
                "irrelevant_query_vector_search_count": negative_vector_search_count,
                "fallback_candidate_seed_count": len(
                    fallback_payload["candidate_graph_proposal_seeds"]
                ),
                "fallback_candidate_seed_requires_review": all(
                    item["requires_review"]
                    and not item["canonical_write_performed"]
                    and item["status"] == "pending_review"
                    for item in fallback_payload["candidate_graph_proposal_seeds"]
                ),
                "canonical_artifact_count": len(canonical_files),
                "hash_only_transcript": all(
                    set(item) == {"method", "request_hash", "response_hash", "status"}
                    for item in transcript
                ),
            },
            "claim_boundary": {
                "supports_issue16_synthetic_vertical_slice_claim": True,
                "supports_kg_first_lookup_claim": True,
                "supports_evidence_resolution_claim": True,
                "supports_retrieval_fallback_claim": True,
                "supports_candidate_seed_claim": True,
                "supports_canonical_graph_write_claim": False,
                "supports_real_enterprise_data_claim": False,
                "supports_production_readiness_claim": False,
            },
        }
        report["metrics"]["safe_output_no_raw_internal_leak"] = not _contains_forbidden(
            report["safe_outputs"]
        )
        report["metrics"]["smoke_passed"] = all(
            (
                report["metrics"]["jsonrpc_tool_discovered"],
                report["metrics"]["kg_first_graph_hit_count"] >= 1,
                report["metrics"]["kg_first_evidence_count"] == 3,
                report["metrics"]["kg_first_evidence_coverage"] == 1.0,
                report["metrics"]["kg_first_fallback_used"] is False,
                report["metrics"]["kg_first_primary_vector_search_count"] == 0,
                report["metrics"]["kg_first_primary_trace_has_no_vectors"],
                report["metrics"]["cross_resource_modalities_present"],
                report["metrics"]["fallback_used_for_incomplete_graph"],
                report["metrics"]["fallback_reason_is_evidence_incomplete"],
                report["metrics"]["fallback_evidence_coverage_incomplete"],
                report["metrics"]["fallback_vector_lineage_present"],
                report["metrics"]["fallback_seed_matches_vector_lineage"],
                report["metrics"]["fallback_vector_search_count"] == 1,
                report["metrics"]["irrelevant_query_has_no_graph_hits"],
                report["metrics"]["irrelevant_query_uses_graph_miss_fallback"],
                report["metrics"]["irrelevant_query_vector_search_count"] == 1,
                report["metrics"]["fallback_candidate_seed_count"] >= 1,
                report["metrics"]["fallback_candidate_seed_requires_review"],
                report["metrics"]["canonical_artifact_count"] == 0,
                report["metrics"]["hash_only_transcript"],
                report["metrics"]["safe_output_no_raw_internal_leak"],
            )
        )
        report["semantic_hash"] = _semantic_report_hash(report)
        return report


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    metrics = report.get("metrics", {})
    claims = report.get("claim_boundary", {})
    if report.get("report_type") != "kg_first_cross_resource_smoke":
        errors.append("invalid_report_type")
    if report.get("report_version") != 1:
        errors.append("invalid_report_version")
    if report.get("fixture_hash") != _fixture_hash():
        errors.append("invalid_fixture_hash")
    if report.get("semantic_hash") != _semantic_report_hash(report):
        errors.append("invalid_semantic_hash")
    required_true = (
        "jsonrpc_tool_discovered",
        "cross_resource_modalities_present",
        "fallback_used_for_incomplete_graph",
        "fallback_reason_is_evidence_incomplete",
        "fallback_evidence_coverage_incomplete",
        "fallback_vector_lineage_present",
        "fallback_seed_matches_vector_lineage",
        "kg_first_primary_trace_has_no_vectors",
        "irrelevant_query_has_no_graph_hits",
        "irrelevant_query_uses_graph_miss_fallback",
        "fallback_candidate_seed_requires_review",
        "hash_only_transcript",
        "safe_output_no_raw_internal_leak",
        "smoke_passed",
    )
    for key in required_true:
        if metrics.get(key) is not True:
            errors.append(f"metric_not_true:{key}")
    if metrics.get("kg_first_graph_hit_count", 0) < 1:
        errors.append("missing_graph_hit")
    if metrics.get("kg_first_evidence_count") != 3:
        errors.append("invalid_evidence_count")
    if metrics.get("kg_first_evidence_coverage") != 1.0:
        errors.append("invalid_evidence_coverage")
    if metrics.get("kg_first_fallback_used") is not False:
        errors.append("unexpected_primary_fallback")
    if metrics.get("kg_first_primary_vector_search_count") != 0:
        errors.append("primary_vector_search_detected")
    if metrics.get("fallback_vector_search_count") != 1:
        errors.append("invalid_fallback_vector_search_count")
    if metrics.get("irrelevant_query_vector_search_count") != 1:
        errors.append("invalid_negative_vector_search_count")
    if metrics.get("fallback_candidate_seed_count", 0) < 1:
        errors.append("missing_candidate_seed")
    safe_outputs = report.get("safe_outputs", {})
    if safe_outputs.get("fallback_reason") != FALLBACK_REASON:
        errors.append("invalid_fallback_reason")
    fallback_coverage = safe_outputs.get("fallback_evidence_coverage")
    if not isinstance(fallback_coverage, int | float) or fallback_coverage >= 1.0:
        errors.append("invalid_fallback_evidence_coverage")
    if safe_outputs.get("fallback_matched_vector_ids") != [FALLBACK_VECTOR_ID]:
        errors.append("invalid_fallback_vector_lineage")
    if safe_outputs.get("fallback_seed_source_observation_ids") != [FALLBACK_OBSERVATION_ID]:
        errors.append("invalid_fallback_seed_lineage")
    if safe_outputs.get("fallback_seed_source_asset_ids") != ["asset_optoma_project_fallback"]:
        errors.append("invalid_fallback_seed_asset_lineage")
    if safe_outputs.get("full_matched_vector_ids") != []:
        errors.append("unexpected_primary_vector_lineage")
    if safe_outputs.get("negative_graph_object_ids") != []:
        errors.append("unexpected_negative_graph_hit")
    if safe_outputs.get("negative_fallback_reason") != GRAPH_MISS_REASON:
        errors.append("invalid_negative_fallback_reason")
    if metrics.get("canonical_artifact_count") != 0:
        errors.append("canonical_artifact_detected")
    for key in (
        "supports_canonical_graph_write_claim",
        "supports_real_enterprise_data_claim",
        "supports_production_readiness_claim",
    ):
        if claims.get(key) is not False:
            errors.append(f"unsafe_claim:{key}")
    if _contains_forbidden(report.get("safe_outputs", {})):
        errors.append("raw_internal_leak")
    return {"status": "ok" if not errors else "error", "errors": errors}


def _call(
    gateway: SemanticMcpJsonRpcGateway,
    *,
    request_id: str,
    query_text: str,
) -> dict[str, Any]:
    return gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": "query_effective_graph_view",
                "arguments": {"query_text": query_text},
            },
        }
    )


def _semantic_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": result.get("answer"),
        "graph_hits": result["graph_hits"],
        "evidence": result["evidence"],
        "fallback_used": result["fallback_used"],
        "fallback_reason": result.get("fallback_reason"),
        "evidence_coverage": result["evidence_coverage"],
        "retrieval_trace": result["retrieval_trace"],
        "candidate_graph_proposal_seeds": result["candidate_graph_proposal_seeds"],
        "citations": [
            {
                "source_type": "observation",
                "source_id": item["observation_id"],
                "locator": item["evidence_locator"],
            }
            for item in result["evidence"]
        ],
        "visible_graph_snippets": result["visible_graph_snippets"],
        "redaction_counts": {"hidden_records": 0},
        "warnings": result["warnings"],
    }


def _view(
    *,
    source_observation_ids: list[str],
    source_asset_ids: list[str],
) -> EffectiveGraphView:
    return EffectiveGraphView(
        requester_user_id="user_pm",
        user_graph_revision_id="ugraph_issue16",
        canonical_graph_revision_id="cgraph_issue16",
        ontology_revision_id="ontology_issue16",
        assembly_policy_id="policy_issue16",
        visible_nodes=[
            GraphProjectionNode(
                node_id="node_optoma_decision",
                source_type="candidate_frame",
                source_id="cframe_optoma_decision",
                labels=["optoma", "quotation", "decision"],
                properties={
                    "object_type": "candidate_decision_frame",
                    "label": "Final Optoma quotation decision",
                    "summary": "Optoma quotation final decision",
                    "confidence": 0.91,
                    "review_state": "candidate",
                    "source_observation_ids": sorted(source_observation_ids),
                    "source_asset_ids": sorted(source_asset_ids),
                },
                permission_scope=PUBLIC_SCOPE,
            ),
            GraphProjectionNode(
                node_id="node_employee_handbook_distractor",
                source_type="candidate_frame",
                source_id="cframe_employee_handbook",
                labels=["employee", "handbook", "vacation"],
                properties={
                    "object_type": "candidate_policy_frame",
                    "label": "Employee vacation handbook",
                    "summary": "Vacation request process",
                    "confidence": 0.93,
                    "review_state": "candidate",
                    "source_observation_ids": [],
                    "source_asset_ids": [],
                },
                permission_scope=PUBLIC_SCOPE,
            ),
        ],
    )


def _observations() -> list[Observation]:
    return [
        _observation(
            "obs_optoma_mail",
            "asset_optoma_mail",
            "mail_message",
            "mail",
            {"thread_id": "thread_optoma", "message_id": "msg_optoma"},
            "Optoma requested a revised quotation.",
        ),
        _observation(
            "obs_optoma_slide",
            "asset_optoma_slide",
            "slide_region",
            "slide",
            {"slide_number": 7, "shape_id": "shape_decision"},
            "Decision: accept the revised Optoma quotation.",
        ),
        _observation(
            "obs_optoma_project",
            "asset_optoma_project",
            "work_package_comment",
            "project",
            {"section_id": "work_package_42"},
            "The project owner confirmed the quotation decision.",
        ),
    ]


def _fallback_vector() -> VectorRecord:
    return VectorRecord(
        vector_id=FALLBACK_VECTOR_ID,
        source_type="observation",
        source_id=FALLBACK_OBSERVATION_ID,
        source_content_hash="sha256:optoma-project-fallback",
        embedding_model="fixture-embedding-v1",
        embedding=QUERY_EMBEDDING,
        permission_scope=PUBLIC_SCOPE,
        metadata={
            "evidence_snippet": "Project fallback confirms the final decision.",
            "asset_id": "asset_untrusted_vector_metadata",
            "source_observation_ids": ["obs_untrusted_vector_metadata"],
            "source_asset_ids": ["asset_untrusted_vector_metadata"],
        },
    )


def _fallback_seed_observation() -> Observation:
    return _observation(
        FALLBACK_OBSERVATION_ID,
        "asset_optoma_project_fallback",
        "work_package_comment",
        "project",
        {"section_id": "work_package_fallback"},
        "Project fallback confirms the final decision.",
    )


def _fixture_definition() -> dict[str, Any]:
    observations = _observations()
    return {
        "observations": [item.to_dict() for item in observations],
        "fallback_seed_observation": _fallback_seed_observation().to_dict(),
        "graph_views": {
            "complete": _view(
                source_observation_ids=[item.observation_id for item in observations],
                source_asset_ids=[str(item.asset_id) for item in observations],
            ).to_dict(),
            "incomplete": _view(
                source_observation_ids=["obs_optoma_mail", "obs_optoma_missing"],
                source_asset_ids=["asset_optoma_mail"],
            ).to_dict(),
        },
        "vector_record": _fallback_vector().to_dict(),
        "query": {
            "text": QUERY_TEXT,
            "irrelevant_text": IRRELEVANT_QUERY_TEXT,
            "embedding": QUERY_EMBEDDING,
        },
        "thresholds": {
            "graph_score_threshold": GRAPH_SCORE_THRESHOLD,
            "graph_confidence_threshold": GRAPH_CONFIDENCE_THRESHOLD,
            "minimum_evidence_count": MINIMUM_EVIDENCE_COUNT,
        },
        "expected_outputs": {
            "full_evidence_modalities": ["mail", "project", "slide"],
            "full_evidence_coverage": 1.0,
            "full_fallback_used": False,
            "full_primary_vector_search_count": 0,
            "fallback_reason": FALLBACK_REASON,
            "fallback_evidence_coverage_less_than": 1.0,
            "fallback_vector_ids": [FALLBACK_VECTOR_ID],
            "fallback_seed_observation_ids": [FALLBACK_OBSERVATION_ID],
            "fallback_vector_search_count": 1,
            "irrelevant_graph_hit_count": 0,
            "irrelevant_fallback_reason": GRAPH_MISS_REASON,
            "irrelevant_vector_search_count": 1,
            "canonical_artifact_count": 0,
        },
    }


def _fixture_hash() -> str:
    return sha256_json(_fixture_definition())


def _semantic_report_hash(report: dict[str, Any]) -> str:
    return sha256_json(
        {
            "report_type": report.get("report_type"),
            "report_version": report.get("report_version"),
            "fixture_hash": report.get("fixture_hash"),
            "safe_outputs": report.get("safe_outputs"),
            "metrics": report.get("metrics"),
            "claim_boundary": report.get("claim_boundary"),
        }
    )


def _observation(
    observation_id: str,
    asset_id: str,
    observation_type: str,
    modality: str,
    location: dict[str, Any],
    text: str,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        extractor_run_id=f"run_{observation_id}",
        observation_type=observation_type,
        modality=modality,
        location=location,
        confidence=0.9,
        permission_scope=PUBLIC_SCOPE,
        created_at=NOW,
        asset_id=asset_id,
        text=text,
    )


def _contains_forbidden(value: Any) -> bool:
    rendered = json.dumps(value, sort_keys=True).lower()
    return any(marker in rendered for marker in FORBIDDEN_TEXT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-report", type=Path)
    args = parser.parse_args()
    if args.validate_report:
        report = json.loads(args.validate_report.read_text(encoding="utf-8"))
    else:
        report = build_report()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    validation = validate_report(report)
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 0 if validation["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
