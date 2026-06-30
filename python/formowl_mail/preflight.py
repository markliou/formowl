from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from formowl_contract import now_iso, stable_resource_contract_id, to_plain


@dataclass(frozen=True)
class MailPreflightReadinessReview:
    review_id: str
    reviewed_at: str
    status: str
    completed_work_packages: list[str]
    scope: list[str]
    dependencies: list[str]
    parser_risks: list[str]
    privacy_guardrails: list[str]
    schedule_assumptions: list[str]
    production_expansion_blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


def build_mail_preflight_readiness_review(
    *,
    reviewed_at: str | None = None,
) -> MailPreflightReadinessReview:
    resolved_reviewed_at = reviewed_at or now_iso()
    payload = {
        "completed_work_packages": ["828", "829", "830", "831", "832", "833", "834", "835"],
        "scope": [
            "synthetic JSON mail archive fixture ingestion",
            "normalized mail observation schema for thread, header, message, body, and attachment",
            "mail evidence pack and deterministic search over persisted observations",
            "candidate-only semantic metadata and graph proposal bridge",
            "case-progress QA answer builder grounded in mail observation citations",
        ],
        "dependencies": [
            "AssetStore and ObjectStore registration",
            "IngestionJob, ExtractorRun, and ObservationStore records",
            "SemanticMetadataStore and CandidateAtom/CandidateRelation stores",
            "FormOwl permission scopes and source references",
        ],
        "parser_risks": [
            "real PST/OST parsing can require large local scratch space",
            "malformed archives and encrypted mail stores need parser-level isolation",
            "duplicate mail exports must preserve every folder and mailbox occurrence",
            "attachment extraction policy must decide when bytes become independent assets",
        ],
        "privacy_guardrails": [
            "raw mailbox paths, account credentials, object-store roots, SQL, and scratch paths stay out of public records",
            "mail evidence search returns observation-backed snippets rather than raw archive bytes",
            "candidate bridge writes only reviewable proposals and never canonical graph state",
            "case-progress answers cite mail observations and do not grant raw asset access",
        ],
        "schedule_assumptions": [
            "synthetic fixture phase is ready for project-management closure",
            "real archive support still needs an explicit production-parser assignment",
            "OpenProject derived dates remain planning inputs, not parser-readiness evidence",
        ],
        "production_expansion_blockers": [
            "select and sandbox a real PST/OST/MSG/EML parser",
            "add non-synthetic parser fixtures or operator-approved replay packets",
            "run privacy, scale, and malformed-archive tests against real parser outputs",
        ],
    }
    review_id = stable_resource_contract_id(
        "mailpreflight",
        "MailPreflightReadinessReview",
        payload,
    )
    return MailPreflightReadinessReview(
        review_id=review_id,
        reviewed_at=resolved_reviewed_at,
        status="synthetic_mail_phase_ready_production_parser_deferred",
        **payload,
    )


__all__ = [
    "MailPreflightReadinessReview",
    "build_mail_preflight_readiness_review",
]
