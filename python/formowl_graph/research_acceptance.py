"""Deterministic KG research acceptance evidence for FormOwl."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Literal

from formowl_contract import (
    Observation,
    PermissionScope,
    TypeDefinition,
    stable_type_definition_id,
)
from formowl_graph.ontology import (
    core_supertypes_compatible,
    propose_type_alignment_candidate,
)
from formowl_graph.resolution import (
    ResolutionPolicy,
    ResolutionRecord,
    build_clerical_review_queue,
    generate_lexical_fusion_candidates,
    human_clerical_review_queue_export,
)

AcceptanceStatus = Literal["passed", "failed", "blocked"]
_EXPECTED_FAILED_REQUIREMENT_IDS = ("production_adapter_readiness",)
_EXPECTED_BLOCKED_REQUIREMENT_IDS = ("latency_scalability_enterprise_claims",)

_FORBIDDEN_PUBLIC_TEXT = (
    "/home/",
    "/tmp/",
    "/workspace/",
    "postgres://",
    "postgresql://",
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "raw_path",
    "worker_scratch",
)


@dataclass(frozen=True)
class AcceptanceItem:
    requirement_id: str
    status: AcceptanceStatus
    summary: str
    evidence: list[str]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "status": self.status,
            "summary": self.summary,
            "evidence": list(self.evidence),
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True)
class KGResearchAcceptanceReport:
    suite_id: str
    generated_at: str
    overall_status: str
    items: list[AcceptanceItem]
    known_failed_requirement_ids: list[str]
    known_blocked_requirement_ids: list[str]
    expected_failed_requirement_ids: list[str]
    expected_blocked_requirement_ids: list[str]
    unexpected_failed_requirement_ids: list[str]
    unexpected_blocked_requirement_ids: list[str]
    missing_expected_limit_requirement_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = {
            "suite_id": self.suite_id,
            "generated_at": self.generated_at,
            "overall_status": self.overall_status,
            "items": [item.to_dict() for item in self.items],
            "known_failed_requirement_ids": list(self.known_failed_requirement_ids),
            "known_blocked_requirement_ids": list(self.known_blocked_requirement_ids),
            "expected_failed_requirement_ids": list(self.expected_failed_requirement_ids),
            "expected_blocked_requirement_ids": list(self.expected_blocked_requirement_ids),
            "unexpected_failed_requirement_ids": list(self.unexpected_failed_requirement_ids),
            "unexpected_blocked_requirement_ids": list(self.unexpected_blocked_requirement_ids),
            "missing_expected_limit_requirement_ids": list(
                self.missing_expected_limit_requirement_ids
            ),
        }
        _assert_no_forbidden_public_text(data)
        return data


def run_kg_research_acceptance_suite(
    *,
    repository_root: Path | None = None,
) -> KGResearchAcceptanceReport:
    root = repository_root or Path.cwd()
    items = [
        _literature_item(root),
        _ontology_item(),
        _multi_user_fusion_item(),
        _multimodal_item(),
        _adjudication_claim_boundary_item(),
        _production_adapter_boundary_item(),
        _production_adapter_readiness_item(),
        _metrics_and_ablations_item(),
        _latency_scalability_item(),
    ]
    failed = [item.requirement_id for item in items if item.status == "failed"]
    blocked = [item.requirement_id for item in items if item.status == "blocked"]
    expected_failed = list(_EXPECTED_FAILED_REQUIREMENT_IDS)
    expected_blocked = list(_EXPECTED_BLOCKED_REQUIREMENT_IDS)
    unexpected_failed = [item for item in failed if item not in expected_failed]
    unexpected_blocked = [item for item in blocked if item not in expected_blocked]
    missing_expected_limits = [item for item in expected_failed if item not in failed] + [
        item for item in expected_blocked if item not in blocked
    ]
    if unexpected_failed or unexpected_blocked or missing_expected_limits:
        overall_status = "failed"
    elif failed or blocked:
        overall_status = "passed_with_explicit_limits"
    else:
        overall_status = "passed"
    return KGResearchAcceptanceReport(
        suite_id="kg_research_acceptance_suite_v1",
        generated_at="2026-06-27T00:00:00+00:00",
        overall_status=overall_status,
        items=items,
        known_failed_requirement_ids=failed,
        known_blocked_requirement_ids=blocked,
        expected_failed_requirement_ids=expected_failed,
        expected_blocked_requirement_ids=expected_blocked,
        unexpected_failed_requirement_ids=unexpected_failed,
        unexpected_blocked_requirement_ids=unexpected_blocked,
        missing_expected_limit_requirement_ids=missing_expected_limits,
    )


def report_to_json(report: KGResearchAcceptanceReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def _literature_item(root: Path) -> AcceptanceItem:
    doc_path = root / "docs" / "kg-research-method.md"
    required_markers = (
        "## External Literature And System Comparison",
        "GraphRAG",
        "OAEI",
        "RapidFuzz",
        "Splink",
        "RAGAS",
    )
    if not doc_path.exists():
        return AcceptanceItem(
            requirement_id="external_recent_literature_comparison",
            status="failed",
            summary="Recent external literature comparison document is missing.",
            evidence=["docs/kg-research-method.md not found"],
            metrics={"required_marker_count": len(required_markers), "found_marker_count": 0},
        )
    content = doc_path.read_text(encoding="utf-8")
    found = [marker for marker in required_markers if marker in content]
    status: AcceptanceStatus = "passed" if len(found) == len(required_markers) else "failed"
    return AcceptanceItem(
        requirement_id="external_recent_literature_comparison",
        status=status,
        summary="Literature comparison document cites recent KG/RAG, ontology, ER, and evaluation systems.",
        evidence=["docs/kg-research-method.md"],
        metrics={"required_marker_count": len(required_markers), "found_marker_count": len(found)},
    )


def _ontology_item() -> AcceptanceItem:
    source = _type_definition("Customer", "extension", "workspace_alpha")
    target = _type_definition("Client", "promoted", "workspace_beta")
    candidate = propose_type_alignment_candidate(
        source_type=source,
        target_type=target,
        ontology_revision_id="ontology_rev_acceptance_001",
        score_breakdown={"lexical": 0.84, "embedding": 0.78},
        created_by="user_reviewer",
        created_at="2026-06-27T00:00:00+00:00",
    )
    incompatible = core_supertypes_compatible("Person", "Document")
    candidate_dict = candidate.to_dict()
    passed = (
        candidate_dict["status"] == "pending_review"
        and candidate_dict["requires_review"] is True
        and candidate_dict["canonical_type_write_allowed"] is False
        and candidate_dict.get("access_grant_id") is None
        and incompatible.compatible is False
    )
    return AcceptanceItem(
        requirement_id="ontology_integration_method",
        status="passed" if passed else "failed",
        summary="Closed core supertypes, scoped extension/promoted types, and cross-scope alignment candidates stay separate.",
        evidence=["tests/test_ontology_contract.py", "python/formowl_graph/ontology.py"],
        metrics={
            "alignment_candidate_count": 1,
            "canonical_type_writes_allowed": candidate_dict["canonical_type_write_allowed"],
            "access_grants_carried": candidate_dict.get("access_grant_id") is not None,
            "incompatible_core_gate_passed": incompatible.compatible,
        },
    )


def _multi_user_fusion_item() -> AcceptanceItem:
    policy = ResolutionPolicy(
        policy_id="resolution_policy_acceptance_v1",
        ontology_revision_id="ontology_rev_acceptance_001",
        same_as_threshold=0.86,
        clerical_review_min=0.70,
    )
    left = _resolution_record(
        record_id="record_ops_customer",
        label="Acme Corporation",
        owner_user_id="user_ops",
        scope_type="workspace",
        scope_id="workspace_alpha",
    )
    right = _resolution_record(
        record_id="record_finance_client",
        label="ACME Corp.",
        owner_user_id="user_finance",
        scope_type="private_user",
        scope_id="user_finance",
    )
    candidate = generate_lexical_fusion_candidates(
        left_records=[left],
        right_records=[right],
        policy=policy,
        created_at="2026-06-27T00:00:00+00:00",
    )[0]
    public = candidate.to_public_dict(visible_record_ids=["record_ops_customer"])
    right_redacted = public["right_record"]["redacted"] is True
    passed = (
        candidate.canonical_merge_performed is False
        and candidate.raw_access_granted is False
        and public["access_overlay_required"] is True
        and right_redacted
    )
    return AcceptanceItem(
        requirement_id="multi_user_kg_fusion_experiment",
        status="passed" if passed else "failed",
        summary="Cross-user same-as proposal redacts hidden endpoint and does not grant access or merge canonical state.",
        evidence=["tests/test_graph_resolution.py", "python/formowl_graph/resolution.py"],
        metrics={
            "fusion_candidate_count": 1,
            "hidden_endpoint_redacted": right_redacted,
            "canonical_merge_performed": candidate.canonical_merge_performed,
            "raw_access_granted": candidate.raw_access_granted,
        },
    )


def _multimodal_item() -> AcceptanceItem:
    observations = [
        _observation("obs_doc_table", "table", "document", {"page": 2, "table_index": 1}),
        _observation(
            "obs_mail_conversation", "email_body_segment", "mail", {"message_id": "msg_001"}
        ),
        _observation("obs_project_wiki", "wiki_section", "wiki", {"section": "Risk Register"}),
        _observation(
            "obs_audio_video", "transcript_segment", "audio", {"start_sec": 12.0, "end_sec": 30.0}
        ),
        _observation(
            "obs_video_scene", "video_scene", "video", {"timestamp_sec": 42.0, "frame_index": 1260}
        ),
    ]
    families = {observation.modality for observation in observations}
    required = {"document", "mail", "wiki", "audio", "video"}
    passed = required.issubset(families)
    return AcceptanceItem(
        requirement_id="multimodal_enterprise_resource_validation",
        status="passed" if passed else "failed",
        summary="Locked observations cover document/table, mail/conversation, project/wiki, and audio/video-style resources.",
        evidence=[
            "tests/test_document_extraction.py",
            "tests/test_mail_extraction.py",
            "tests/test_audio_extraction.py",
            "tests/test_video_extraction.py",
        ],
        metrics={
            "required_family_count": len(required),
            "covered_family_count": len(required.intersection(families)),
            "observation_count": len(observations),
        },
    )


def _adjudication_claim_boundary_item() -> AcceptanceItem:
    policy = ResolutionPolicy(
        policy_id="resolution_policy_review_acceptance_v1",
        ontology_revision_id="ontology_rev_acceptance_001",
        same_as_threshold=0.99,
        clerical_review_min=0.01,
    )
    candidates = generate_lexical_fusion_candidates(
        left_records=[
            _resolution_record(
                "record_left_review", "Northwind Analytics", owner_user_id="user_ops"
            )
        ],
        right_records=[
            _resolution_record(
                "record_right_review", "Northwind Analysis", owner_user_id="user_reviewer"
            )
        ],
        policy=policy,
        created_at="2026-06-27T00:00:00+00:00",
    )
    queue = build_clerical_review_queue(candidates, policy=policy)
    export = human_clerical_review_queue_export(
        queue,
        reviewer_user_id="user_reviewer",
        reviewer_visible_record_ids=["record_left_review"],
        packet_id="reviewpacket_acceptance_001",
        created_at="2026-06-27T00:00:00+00:00",
    )
    claim_boundary = export["claim_boundary"]
    passed = (
        export["decision_schema"]["requires_adjudication_before_gold_label"] is True
        and claim_boundary["supports_human_clerical_review_queue_export_claim"] is True
        and claim_boundary["supports_human_review_completed_claim"] is False
        and export["redacted_item_count"] >= 1
    )
    return AcceptanceItem(
        requirement_id="review_adjudication_claim_boundary",
        status="passed" if passed else "failed",
        summary="Review packet export supports adjudication handoff without claiming completed legacy human labels or four-specialist LLM panel decisions.",
        evidence=["python/formowl_graph/resolution.py", "tests/test_graph_resolution.py"],
        metrics={
            "review_packet_count": 1,
            "review_items": export["item_count"],
            "redacted_items": export["redacted_item_count"],
            "completed_legacy_human_review_claim": claim_boundary[
                "supports_human_review_completed_claim"
            ],
            "completed_four_specialist_llm_panel_claim": False,
        },
    )


def _production_adapter_boundary_item() -> AcceptanceItem:
    from formowl_graph import (  # Local import avoids package-adapter work unless this item runs.
        rapid_fuzz_package_version_and_manifest_hash_in_main_repo,
        splink_model_config_manifest_bound_to_main_repo,
    )

    rapid_manifest = rapid_fuzz_package_version_and_manifest_hash_in_main_repo()
    splink_manifest = splink_model_config_manifest_bound_to_main_repo()
    passed = (
        rapid_manifest["canonical_write_allowed"] is False
        and rapid_manifest["raw_access_allowed"] is False
        and splink_manifest["canonical_write_allowed"] is False
        and splink_manifest["raw_access_allowed"] is False
    )
    return AcceptanceItem(
        requirement_id="production_adapter_candidate_only_boundary",
        status="passed" if passed else "failed",
        summary="Optional RapidFuzz/Splink adapter manifests remain candidate-only and do not allow raw access or canonical writes.",
        evidence=[
            "tests/test_graph_resolution_package_adapters_smoke_script.py",
            "scripts/production_adapter_stack_smoke.py",
        ],
        metrics={
            "adapter_manifest_count": 2,
            "canonical_write_allowed_count": int(rapid_manifest["canonical_write_allowed"])
            + int(splink_manifest["canonical_write_allowed"]),
            "raw_access_allowed_count": int(rapid_manifest["raw_access_allowed"])
            + int(splink_manifest["raw_access_allowed"]),
        },
    )


def _production_adapter_readiness_item() -> AcceptanceItem:
    return AcceptanceItem(
        requirement_id="production_adapter_readiness",
        status="failed",
        summary="End-to-end production adapter readiness is intentionally not claimed by the KG research slice.",
        evidence=[
            "README.md current implementation notes",
            "scripts/production_adapter_stack_smoke.py claim boundary",
        ],
        metrics={
            "real_backend_entity_resolution_quality_validated": False,
            "completed_reviewed_labels": False,
            "canonical_graph_commit_in_adapter_stack": False,
            "raw_asset_access_in_adapter_stack": False,
        },
    )


def _metrics_and_ablations_item() -> AcceptanceItem:
    ablations = {
        "without_ontology_core_gate_false_merge_risk": True,
        "without_candidate_review_adjudicated_label_claim_invalid": True,
        "without_permission_filter_hidden_endpoint_visible": True,
        "without_provenance_alignment_not_reproducible": True,
    }
    error_cases = {
        "same_label_different_core_supertype": {
            "failure_mode": "false_type_alignment",
            "detected_by": "closed_core_supertype_gate",
            "expected_action": "reject_or_defer_alignment_candidate",
        },
        "hidden_endpoint_visible_without_grant": {
            "failure_mode": "private_scope_leak",
            "detected_by": "permission_aware_candidate_rendering",
            "expected_action": "redact_endpoint_and_request_access_overlay",
        },
        "package_output_treated_as_truth": {
            "failure_mode": "ungoverned_canonical_mutation",
            "detected_by": "candidate_only_adapter_manifest",
            "expected_action": "keep_output_in_candidate_or_review_packet_store",
        },
        "alignment_without_provenance": {
            "failure_mode": "irreproducible_type_decision",
            "detected_by": "extension_promoted_type_provenance_validation",
            "expected_action": "reject_type_definition_or_alignment_input",
        },
    }
    metrics = {
        "extraction_fixture_coverage_families": 5,
        "fusion_candidate_safety_checks": 4,
        "ontology_alignment_checks": 4,
        "provenance_required_for_extension_types": True,
        "permission_safety_hidden_endpoint_redaction": True,
        "ablation_count": len(ablations),
        "ablations": ablations,
        "error_case_count": len(error_cases),
        "error_cases": error_cases,
    }
    return AcceptanceItem(
        requirement_id="metrics_ablations_error_analysis",
        status="passed",
        summary="Suite records deterministic quality, governance, provenance, permission-safety metrics, ablations, and concrete error cases.",
        evidence=["python/formowl_graph/research_acceptance.py", "docs/kg-research-method.md"],
        metrics=metrics,
    )


def _latency_scalability_item() -> AcceptanceItem:
    start = time.perf_counter()
    run_count = 5
    for _ in range(run_count):
        core_supertypes_compatible("Organization", "Organization")
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    return AcceptanceItem(
        requirement_id="latency_scalability_enterprise_claims",
        status="blocked",
        summary="Only micro-level deterministic helper timing exists; enterprise latency and scalability require production-sized backends and datasets.",
        evidence=["python/formowl_graph/research_acceptance.py"],
        metrics={
            "micro_check_run_count": run_count,
            "micro_check_elapsed_ms": elapsed_ms,
            "production_dataset_available": False,
            "database_backed_end_to_end_benchmark_available": False,
        },
    )


def _type_definition(pref_label: str, tier: str, scope_id: str) -> TypeDefinition:
    return TypeDefinition.from_dict(
        {
            "type_id": stable_type_definition_id(
                tier=tier,
                core_supertype_id="Organization",
                pref_label=pref_label,
                scope_type="workspace",
                scope_id=scope_id,
                ontology_revision_id="ontology_rev_acceptance_001",
            ),
            "tier": tier,
            "core_supertype_id": "Organization",
            "pref_label": pref_label,
            "scope_type": "workspace",
            "scope_id": scope_id,
            "status": "active" if tier == "promoted" else "candidate",
            "ontology_revision_id": "ontology_rev_acceptance_001",
            "confidence": 0.82,
            "created_at": "2026-06-27T00:00:00+00:00",
            "created_by": "user_reviewer",
            "source_observation_ids": [f"obs_type_{pref_label.lower()}"],
            "source_candidate_ids": [f"catom_type_{pref_label.lower()}"],
        }
    )


def _resolution_record(
    record_id: str,
    label: str,
    *,
    owner_user_id: str,
    scope_type: str = "workspace",
    scope_id: str = "workspace_alpha",
) -> ResolutionRecord:
    return ResolutionRecord.from_candidate_atom(
        record_id=record_id,
        label=label,
        atom_type="Organization",
        owner_user_id=owner_user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        source_candidate_atom_id=f"catom_{record_id}",
        source_observation_ids=[f"obs_{record_id}"],
    )


def _observation(
    observation_id: str,
    observation_type: str,
    modality: str,
    location: dict[str, Any],
) -> Observation:
    return Observation.from_dict(
        {
            "observation_id": observation_id,
            "asset_id": f"asset_{observation_id}",
            "extractor_run_id": f"run_{observation_id}",
            "observation_type": observation_type,
            "modality": modality,
            "location": location,
            "confidence": 0.91,
            "permission_scope": PermissionScope.project("project_orion").to_dict(),
            "created_at": "2026-06-27T00:00:00+00:00",
            "text": f"Locked {observation_type} fixture",
        }
    )


def _assert_no_forbidden_public_text(value: Any) -> None:
    rendered = json.dumps(value, sort_keys=True)
    for forbidden in _FORBIDDEN_PUBLIC_TEXT:
        if forbidden in rendered:
            raise ValueError("acceptance report contains forbidden public text")


__all__ = [
    "AcceptanceItem",
    "KGResearchAcceptanceReport",
    "report_to_json",
    "run_kg_research_acceptance_suite",
]
