#!/usr/bin/env python3
"""External literature and baseline protocol recovery artifact.

This artifact records the current web-checked baseline/literature comparison
needed before fair KG/GraphRAG evaluation. It deliberately does not claim that
external packages have been executed or human-adjudicated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

CURRENT_DATE = "2026-06-25"

REQUIRED_BASELINES = ("microsoft_graphrag", "lightrag", "hipporag")

REQUIRED_SOURCE_IDS_BY_BASELINE = {
    "microsoft_graphrag": (
        "microsoft_graphrag_paper",
        "microsoft_graphrag_repo",
        "microsoft_graphrag_docs",
    ),
    "lightrag": (
        "lightrag_paper",
        "lightrag_repo",
    ),
    "hipporag": (
        "hipporag_paper",
        "hipporag2_paper",
        "hipporag_repo",
    ),
}

REQUIRED_SOURCE_IDS = {
    "microsoft_graphrag_paper",
    "microsoft_graphrag_repo",
    "microsoft_graphrag_docs",
    "lightrag_paper",
    "lightrag_repo",
    "hipporag_paper",
    "hipporag2_paper",
    "hipporag_repo",
    "graphrag_survey_2025",
}

REQUIRED_SOURCE_URLS = {
    "microsoft_graphrag_paper": "https://arxiv.org/abs/2404.16130",
    "microsoft_graphrag_repo": "https://github.com/microsoft/graphrag",
    "microsoft_graphrag_docs": "https://microsoft.github.io/graphrag/",
    "lightrag_paper": "https://arxiv.org/abs/2410.05779",
    "lightrag_repo": "https://github.com/HKUDS/LightRAG",
    "hipporag_paper": "https://arxiv.org/abs/2405.14831",
    "hipporag2_paper": "https://arxiv.org/abs/2502.14802",
    "hipporag_repo": "https://github.com/OSU-NLP-Group/HippoRAG",
    "graphrag_survey_2025": "https://arxiv.org/abs/2501.13958",
}

ALLOWED_SOURCE_TYPES = {
    "paper",
    "official_repo",
    "official_docs",
    "official_blog",
    "survey",
}

REQUIRED_COMPARISON_AXES = (
    "graph_construction",
    "retrieval_strategy",
    "incremental_update_path",
    "citation_and_provenance",
    "ontology_or_schema_grounding",
    "multimodal_enterprise_coverage",
    "permission_and_user_graph_safety",
    "human_review_and_adjudication",
    "cost_latency_reproducibility",
)

REQUIRED_PROTOCOL_FLAGS_TRUE = (
    "same_corpus_and_observations_required",
    "same_prompt_set_required",
    "same_model_or_budget_policy_required",
    "same_embedding_or_budget_policy_required",
    "same_access_policy_required",
    "same_evaluation_questions_required",
    "human_answer_adjudication_required",
    "graph_quality_adjudication_required",
    "permission_leak_probe_required",
    "raw_asset_access_probe_required",
)

REQUIRED_PROTOCOL_FLAGS_FALSE = (
    "literature_review_counts_as_model_execution",
    "paper_claims_count_as_enterprise_validation",
    "package_stars_count_as_quality_evidence",
    "offline_matrix_counts_as_human_adjudication",
)


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def required_baseline_source_lock_rows() -> list[dict[str, Any]]:
    source_by_id = {
        source["source_id"]: source
        for source in default_sources()
        if source["source_id"] in REQUIRED_SOURCE_IDS
    }
    rows: list[dict[str, Any]] = []
    for baseline_id in REQUIRED_BASELINES:
        for source_id in REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]:
            source = source_by_id[source_id]
            rows.append(
                {
                    "source_id": source["source_id"],
                    "source_type": source["source_type"],
                    "year": source["year"],
                    "url": source["url"],
                }
            )
    return rows


def required_baseline_source_lock_sha256() -> str:
    return sha256_json(required_baseline_source_lock_rows())


def _source(
    source_id: str,
    title: str,
    source_type: str,
    year: int,
    url: str,
    relevance: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "title": title,
        "source_type": source_type,
        "year": year,
        "url": url,
        "retrieved_at": CURRENT_DATE,
        "relevance": relevance,
    }


def default_sources() -> list[dict[str, Any]]:
    return [
        _source(
            "microsoft_graphrag_paper",
            "From Local to Global: A Graph RAG Approach to Query-Focused Summarization",
            "paper",
            2024,
            "https://arxiv.org/abs/2404.16130",
            "Microsoft GraphRAG method paper for community-level graph summarization baseline.",
        ),
        _source(
            "microsoft_graphrag_repo",
            "microsoft/graphrag repository",
            "official_repo",
            2026,
            "https://github.com/microsoft/graphrag",
            "Official package/release source for runnable Microsoft GraphRAG baseline.",
        ),
        _source(
            "microsoft_graphrag_docs",
            "Microsoft GraphRAG documentation",
            "official_docs",
            2026,
            "https://microsoft.github.io/graphrag/",
            "Official configuration and pipeline documentation for reproducing package behavior.",
        ),
        _source(
            "microsoft_graphrag_blog",
            "GraphRAG: Unlocking LLM discovery on narrative private data",
            "official_blog",
            2024,
            "https://www.microsoft.com/en-us/research/blog/graphrag-unlocking-llm-discovery-on-narrative-private-data/",
            "Official Microsoft Research motivation and private-data positioning.",
        ),
        _source(
            "lightrag_paper",
            "LightRAG: Simple and Fast Retrieval-Augmented Generation",
            "paper",
            2024,
            "https://arxiv.org/abs/2410.05779",
            "Graph-indexed lightweight RAG baseline focused on speed and incremental retrieval.",
        ),
        _source(
            "lightrag_repo",
            "HKUDS/LightRAG repository",
            "official_repo",
            2026,
            "https://github.com/HKUDS/LightRAG",
            "Official runnable LightRAG package source and configuration surface.",
        ),
        _source(
            "hipporag_paper",
            "HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models",
            "paper",
            2024,
            "https://arxiv.org/abs/2405.14831",
            "Long-term memory and graph/PPR-style retrieval baseline for multi-hop RAG.",
        ),
        _source(
            "hipporag2_paper",
            "From RAG to Memory: Non-Parametric Continual Learning for Large Language Models",
            "paper",
            2025,
            "https://arxiv.org/abs/2502.14802",
            "ICML 2025 structure-augmented RAG comparison source covering GraphRAG, LightRAG, and HippoRAG-style memory/retrieval methods.",
        ),
        _source(
            "hipporag_repo",
            "OSU-NLP-Group/HippoRAG repository",
            "official_repo",
            2026,
            "https://github.com/OSU-NLP-Group/HippoRAG",
            "Official runnable HippoRAG package source.",
        ),
        _source(
            "graphrag_survey_2025",
            "A Survey of Graph Retrieval-Augmented Generation for Customized Large Language Models",
            "survey",
            2025,
            "https://arxiv.org/abs/2501.13958",
            "Recent survey source used to keep the comparison axes broader than the three packages.",
        ),
    ]


def default_baselines() -> list[dict[str, Any]]:
    return [
        {
            "baseline_id": "microsoft_graphrag",
            "display_name": "Microsoft GraphRAG",
            "source_ids": [
                "microsoft_graphrag_paper",
                "microsoft_graphrag_repo",
                "microsoft_graphrag_docs",
                "microsoft_graphrag_blog",
            ],
            "baseline_role": "community-summary graph RAG baseline",
            "comparison": {
                "graph_construction": "LLM-derived entities/relationships plus community summaries.",
                "retrieval_strategy": "Global/local/drift-style graph retrieval configuration must be pinned before run.",
                "incremental_update_path": "Re-index/update behavior must be measured rather than inferred from docs.",
                "citation_and_provenance": "Package output citations must be mapped back to FormOwl observations before comparison.",
                "ontology_or_schema_grounding": "No FormOwl scoped ontology governance by default; requires adapter mapping.",
                "multimodal_enterprise_coverage": "Text-oriented baseline; multimodal inputs must enter as observations.",
                "permission_and_user_graph_safety": "No FormOwl user-graph permission model by default; must run behind filtered inputs.",
                "human_review_and_adjudication": "No canonical merge authority; outputs require same human adjudication packet.",
                "cost_latency_reproducibility": "Index and query cost/latency must be recorded from actual package execution.",
            },
            "formowl_adapter_requirements": [
                "observation-export adapter",
                "scoped ontology mapping adapter",
                "permission-filtered corpus adapter",
                "candidate-only import adapter",
            ],
        },
        {
            "baseline_id": "lightrag",
            "display_name": "LightRAG",
            "source_ids": ["lightrag_paper", "lightrag_repo"],
            "baseline_role": "lightweight graph-indexed RAG baseline",
            "comparison": {
                "graph_construction": "Lightweight entity/relation graph and vector-keyed retrieval index.",
                "retrieval_strategy": "Dual-level retrieval behavior must be pinned with the same prompt/model budget.",
                "incremental_update_path": "Incremental insertion claims need measured re-index and stale-result checks.",
                "citation_and_provenance": "Returned chunks/entities must be re-bound to observation ids and citations.",
                "ontology_or_schema_grounding": "No native FormOwl ontology revision pin; requires type-mapping wrapper.",
                "multimodal_enterprise_coverage": "Text observation baseline; spreadsheet/mail/audio/video need upstream extraction.",
                "permission_and_user_graph_safety": "No grant-aware user graph by default; evaluate only through filtered corpus.",
                "human_review_and_adjudication": "Generated graph content remains proposal-only and needs same adjudication packet.",
                "cost_latency_reproducibility": "Speed claims require logged index/query timing on identical corpus.",
            },
            "formowl_adapter_requirements": [
                "observation-export adapter",
                "type-candidate mapping adapter",
                "permission-filtered corpus adapter",
                "stale-index permission probe",
            ],
        },
        {
            "baseline_id": "hipporag",
            "display_name": "HippoRAG",
            "source_ids": ["hipporag_paper", "hipporag2_paper", "hipporag_repo"],
            "baseline_role": "multi-hop memory/retrieval baseline",
            "comparison": {
                "graph_construction": "OpenIE-style graph/memory construction must be preserved as candidate evidence only.",
                "retrieval_strategy": "PPR/memory retrieval should be tested on multi-hop questions and business-decision traces.",
                "incremental_update_path": "Memory update behavior must be measured on append/revoke scenarios.",
                "citation_and_provenance": "Retrieved facts must keep observation and extractor-run lineage.",
                "ontology_or_schema_grounding": "No scoped ontology/type governance by default; requires reviewable alignment rows.",
                "multimodal_enterprise_coverage": "Text observation baseline; multimodal source diversity comes from FormOwl extraction.",
                "permission_and_user_graph_safety": "No entity-match-is-not-access rule by default; must test revoked grants.",
                "human_review_and_adjudication": "No canonical write authority; use candidate import and adjudication queue.",
                "cost_latency_reproducibility": "Index build, memory retrieval, and query latency must be logged from real runs.",
            },
            "formowl_adapter_requirements": [
                "observation-export adapter",
                "candidate-only graph import adapter",
                "permission-filtered corpus adapter",
                "multi-hop adjudication question set",
            ],
        },
    ]


def default_protocol() -> dict[str, Any]:
    return {
        "protocol_id": "external_literature_baseline_protocol_recovery_v1",
        "same_corpus_and_observations_required": True,
        "same_prompt_set_required": True,
        "same_model_or_budget_policy_required": True,
        "same_embedding_or_budget_policy_required": True,
        "same_access_policy_required": True,
        "same_evaluation_questions_required": True,
        "human_answer_adjudication_required": True,
        "graph_quality_adjudication_required": True,
        "permission_leak_probe_required": True,
        "raw_asset_access_probe_required": True,
        "literature_review_counts_as_model_execution": False,
        "paper_claims_count_as_enterprise_validation": False,
        "package_stars_count_as_quality_evidence": False,
        "offline_matrix_counts_as_human_adjudication": False,
        "required_run_artifacts": [
            "package_lock_and_config_artifacts",
            "index_build_logs",
            "query_run_logs",
            "answer_outputs",
            "graph_outputs",
            "permission_probe_outputs",
            "human_adjudication_packet",
        ],
    }


def default_fixture() -> dict[str, Any]:
    return {
        "artifact_id": "external_literature_baseline_protocol_recovery_v1",
        "searched_at": CURRENT_DATE,
        "sources": default_sources(),
        "baselines": default_baselines(),
        "comparison_axes": list(REQUIRED_COMPARISON_AXES),
        "fair_baseline_protocol": default_protocol(),
        "claim_boundary": {
            "supports_external_recent_literature_comparison_claim": True,
            "supports_baseline_selection_rationale_claim": True,
            "supports_fair_external_baseline_run_claim": False,
            "supports_real_package_execution_claim": False,
            "supports_human_adjudicated_answer_quality_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


def validate_fixture(fixture: dict[str, Any]) -> list[str]:
    blockers: list[str] = []

    if fixture.get("artifact_id") != "external_literature_baseline_protocol_recovery_v1":
        blockers.append("artifact id mismatch")
    if fixture.get("searched_at") != CURRENT_DATE:
        blockers.append("literature search date is not current-session pinned")

    sources = fixture.get("sources")
    if not isinstance(sources, list):
        return ["sources list missing"]
    source_by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            blockers.append("source row is not an object")
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            blockers.append("source id missing")
            continue
        if source_id in source_by_id:
            blockers.append(f"duplicate source id: {source_id}")
        source_by_id[source_id] = source
        if source.get("source_type") not in ALLOWED_SOURCE_TYPES:
            blockers.append(f"{source_id} source type unsupported")
        year = source.get("year")
        if not isinstance(year, int) or isinstance(year, bool) or year < 2024 or year > 2026:
            blockers.append(f"{source_id} is not a recent 2024-2026 source")
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            blockers.append(f"{source_id} source URL missing or not https")
        expected_url = REQUIRED_SOURCE_URLS.get(source_id)
        if expected_url is not None and url != expected_url:
            blockers.append(f"{source_id} source URL does not match locked reference")
        if source.get("retrieved_at") != CURRENT_DATE:
            blockers.append(f"{source_id} retrieval date mismatch")
        for field in ("title", "relevance"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                blockers.append(f"{source_id} {field} missing")

    missing_sources = REQUIRED_SOURCE_IDS - set(source_by_id)
    if missing_sources:
        blockers.append("required literature/source coverage missing: " + ", ".join(sorted(missing_sources)))
    if not any(source.get("source_type") == "survey" for source in source_by_id.values()):
        blockers.append("recent survey source missing")

    baselines = fixture.get("baselines")
    if not isinstance(baselines, list):
        return blockers + ["baselines list missing"]
    baseline_ids = [row.get("baseline_id") for row in baselines if isinstance(row, dict)]
    if sorted(baseline_ids) != sorted(REQUIRED_BASELINES):
        blockers.append("required baseline coverage mismatch")

    axes = fixture.get("comparison_axes")
    if not isinstance(axes, list) or tuple(axes) != REQUIRED_COMPARISON_AXES:
        blockers.append("comparison axes are missing or not in the locked order")

    for row in baselines:
        if not isinstance(row, dict):
            blockers.append("baseline row is not an object")
            continue
        baseline_id = row.get("baseline_id")
        if baseline_id not in REQUIRED_BASELINES:
            blockers.append(f"unexpected baseline id: {baseline_id}")
            continue
        source_ids = row.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            blockers.append(f"{baseline_id} source ids missing")
            source_ids = []
        unknown = [source_id for source_id in source_ids if source_id not in source_by_id]
        if unknown:
            blockers.append(f"{baseline_id} references unknown sources: " + ", ".join(sorted(unknown)))
        source_types = {source_by_id[source_id]["source_type"] for source_id in source_ids if source_id in source_by_id}
        if "paper" not in source_types:
            blockers.append(f"{baseline_id} paper source missing")
        if not ({"official_repo", "official_docs", "official_blog"} & source_types):
            blockers.append(f"{baseline_id} official package/source evidence missing")

        comparison = row.get("comparison")
        if not isinstance(comparison, dict):
            blockers.append(f"{baseline_id} comparison matrix missing")
            comparison = {}
        for axis in REQUIRED_COMPARISON_AXES:
            if not isinstance(comparison.get(axis), str) or not comparison[axis].strip():
                blockers.append(f"{baseline_id} comparison axis missing: {axis}")
        requirements = row.get("formowl_adapter_requirements")
        if not isinstance(requirements, list) or len(requirements) < 3:
            blockers.append(f"{baseline_id} FormOwl adapter requirements incomplete")
        requirement_text = " ".join(str(item) for item in requirements)
        if "permission" not in requirement_text:
            blockers.append(f"{baseline_id} permission adapter requirement missing")
        if "adapter" not in requirement_text:
            blockers.append(f"{baseline_id} adapter-bound integration requirement missing")

    protocol = fixture.get("fair_baseline_protocol")
    if not isinstance(protocol, dict):
        blockers.append("fair baseline protocol missing")
        protocol = {}
    for flag in REQUIRED_PROTOCOL_FLAGS_TRUE:
        if protocol.get(flag) is not True:
            blockers.append(f"fair baseline protocol missing required true flag: {flag}")
    for flag in REQUIRED_PROTOCOL_FLAGS_FALSE:
        if protocol.get(flag) is not False:
            blockers.append(f"fair baseline protocol permits unsupported evidence: {flag}")
    required_artifacts = protocol.get("required_run_artifacts")
    if not isinstance(required_artifacts, list) or len(required_artifacts) < 6:
        blockers.append("fair baseline protocol required run artifacts incomplete")

    claims = fixture.get("claim_boundary")
    if not isinstance(claims, dict):
        blockers.append("claim boundary missing")
        claims = {}
    if claims.get("supports_external_recent_literature_comparison_claim") is not True:
        blockers.append("external literature comparison claim not enabled")
    for flag in (
        "supports_fair_external_baseline_run_claim",
        "supports_real_package_execution_claim",
        "supports_human_adjudicated_answer_quality_claim",
        "supports_production_ready_claim",
        "supports_top_tier_scientific_validation_claim",
    ):
        if claims.get(flag) is not False:
            blockers.append(f"claim boundary overclaims unsupported evidence: {flag}")

    return sorted(set(blockers))


def build_report(fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    fixture = default_fixture() if fixture is None else fixture
    blockers = validate_fixture(fixture)
    report = {
        **fixture,
        "passed": not blockers,
        "blockers": blockers,
        "metrics": {
            "source_count": len(fixture.get("sources", [])) if isinstance(fixture.get("sources"), list) else 0,
            "baseline_count": len(fixture.get("baselines", [])) if isinstance(fixture.get("baselines"), list) else 0,
            "comparison_axis_count": len(fixture.get("comparison_axes", []))
            if isinstance(fixture.get("comparison_axes"), list)
            else 0,
            "required_baseline_count": len(REQUIRED_BASELINES),
            "required_source_count": len(REQUIRED_SOURCE_IDS),
        },
    }
    report["protocol_sha256"] = sha256_json(
        {
            "sources": fixture.get("sources"),
            "baselines": fixture.get("baselines"),
            "comparison_axes": fixture.get("comparison_axes"),
            "fair_baseline_protocol": fixture.get("fair_baseline_protocol"),
            "claim_boundary": fixture.get("claim_boundary"),
        }
    )
    return report


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "external_literature_baseline_protocol_recovery.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
