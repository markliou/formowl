"""Mail evidence workflow helpers for the FormOwl synthetic mail phase."""

from .candidates import (
    MailCandidateBridgeResult,
    extract_and_store_mail_candidates,
    extract_mail_semantics_and_candidates,
)
from .evidence import (
    MailBodySegment,
    MailEvidencePack,
    MailEvidencePackStore,
    MailEvidenceRecord,
    MailSearchResult,
    build_mail_evidence_pack,
    search_mail_evidence,
)
from .preflight import MailPreflightReadinessReview, build_mail_preflight_readiness_review
from .qa import CaseProgressAnswer, CaseProgressItem, build_case_progress_answer

__all__ = [
    "CaseProgressAnswer",
    "CaseProgressItem",
    "MailBodySegment",
    "MailCandidateBridgeResult",
    "MailEvidencePack",
    "MailEvidencePackStore",
    "MailEvidenceRecord",
    "MailPreflightReadinessReview",
    "MailSearchResult",
    "build_case_progress_answer",
    "build_mail_evidence_pack",
    "build_mail_preflight_readiness_review",
    "extract_and_store_mail_candidates",
    "extract_mail_semantics_and_candidates",
    "search_mail_evidence",
]
