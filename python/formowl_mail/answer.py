"""Pinned deterministic final-answer contract for Issue #56 diagnostics.

The renderer consumes only governed execution results.  It never receives the
private adjudication manifest, expected evidence ids, or oracle answer text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from formowl_contract import ContractValidationError, sha256_json

from ._guards import assert_public_payload_safe
from .hybrid import GovernedHybridRagResult, GovernedSemanticExecutionResult

ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID = "formowl_deterministic_evidence_answer_v1"
ISSUE56_DETERMINISTIC_ANSWER_PROMPT_ID = "issue56_shared_evidence_answer_prompt_v1"
_ANSWER_PROMPT = (
    "Render only the governed status, exact count when deterministically "
    "available, and authorized citation hashes. Do not infer missing facts."
)
ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT = sha256_json(_ANSWER_PROMPT)


@dataclass(frozen=True)
class EvidenceAnswerBudget:
    max_citations: int = 10
    max_answer_characters: int = 240

    @property
    def fingerprint(self) -> str:
        return sha256_json(
            {
                "max_citations": self.max_citations,
                "max_answer_characters": self.max_answer_characters,
            }
        )

    def validate(self) -> None:
        if not 1 <= self.max_citations <= 64:
            raise ContractValidationError("answer citation budget is invalid")
        if not 80 <= self.max_answer_characters <= 2_000:
            raise ContractValidationError("answer character budget is invalid")


@dataclass(frozen=True)
class GovernedEvidenceAnswer:
    artifact_id: str
    status: str
    query_hash: str
    source_result_fingerprint: str
    answer_model_id: str
    prompt_id: str
    prompt_fingerprint: str
    budget_fingerprint: str
    answer_hash: str
    citation_hashes: tuple[str, ...]
    exact_count: int | None
    cost_units: int
    answer_text: str = field(repr=False, compare=False)

    def to_safe_dict(self) -> dict[str, Any]:
        """Return the public hash/status/count-only form; omit private answer text."""

        payload = {
            "artifact_id": self.artifact_id,
            "status": self.status,
            "query_hash": self.query_hash,
            "source_result_fingerprint": self.source_result_fingerprint,
            "answer_model_id": self.answer_model_id,
            "prompt_id": self.prompt_id,
            "prompt_fingerprint": self.prompt_fingerprint,
            "budget_fingerprint": self.budget_fingerprint,
            "answer_hash": self.answer_hash,
            "citation_hashes": list(self.citation_hashes),
            "citation_count": len(self.citation_hashes),
            "exact_count": self.exact_count,
            "cost_units": self.cost_units,
        }
        assert_public_payload_safe(payload, "issue56_governed_evidence_answer")
        return payload


def render_governed_evidence_answer(
    result: GovernedHybridRagResult | GovernedSemanticExecutionResult,
    *,
    budget: EvidenceAnswerBudget = EvidenceAnswerBudget(),
    evidence_count: int = 0,
) -> GovernedEvidenceAnswer:
    """Render one shared deterministic answer from authorized result metadata."""

    budget.validate()
    if isinstance(result, GovernedHybridRagResult):
        source_result_fingerprint = sha256_json(result.to_safe_dict())
        citation_hashes = _hybrid_citation_hashes(result)
        exact_count = None
    elif isinstance(result, GovernedSemanticExecutionResult):
        source_result_fingerprint = result.result_fingerprint
        citation_hashes = _semantic_citation_hashes(result)
        exact_count = result.exact_result.exact_count if result.exact_result is not None else None
    else:
        raise ContractValidationError("unsupported governed answer input")

    if not isinstance(evidence_count, int) or isinstance(evidence_count, bool) or evidence_count < 0:
        raise ContractValidationError("answer evidence count is invalid")
    selected_citations = citation_hashes[: budget.max_citations]
    answer_status, answer_text = _answer_text(
        result_status=result.status,
        citation_count=len(selected_citations),
        exact_count=exact_count,
        query_class=result.query_class,
        evidence_count=evidence_count,
    )
    if len(answer_text) > budget.max_answer_characters:
        raise ContractValidationError("answer exceeded pinned character budget")
    answer_hash = sha256_json(answer_text)
    cost_units = len(answer_text) + (8 * len(selected_citations))
    answer = GovernedEvidenceAnswer(
        artifact_id="formowl_issue56_governed_evidence_answer_v1",
        status=answer_status,
        query_hash=result.query_hash,
        source_result_fingerprint=source_result_fingerprint,
        answer_model_id=ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID,
        prompt_id=ISSUE56_DETERMINISTIC_ANSWER_PROMPT_ID,
        prompt_fingerprint=(ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT),
        budget_fingerprint=budget.fingerprint,
        answer_hash=answer_hash,
        citation_hashes=selected_citations,
        exact_count=exact_count,
        cost_units=cost_units,
        answer_text=answer_text,
    )
    answer.to_safe_dict()
    return answer


def _hybrid_citation_hashes(
    result: GovernedHybridRagResult,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(result.answer_citation_hashes))


def _semantic_citation_hashes(
    result: GovernedSemanticExecutionResult,
) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    if result.exact_result is not None:
        candidates = (
            observation_hash
            for item in result.exact_result.items
            for observation_hash in item.cited_observation_hashes
        )
    else:
        candidates = iter(result.answer_citation_hashes)
    for observation_hash in candidates:
        if observation_hash not in seen:
            seen.add(observation_hash)
            ordered.append(observation_hash)
    return tuple(ordered)


def _answer_text(
    *,
    result_status: str,
    citation_count: int,
    exact_count: int | None,
    query_class: str,
    evidence_count: int,
) -> tuple[str, str]:
    if result_status == "permission_denied":
        return (
            "permission_denied",
            "Permission denied for requested evidence.",
        )
    if query_class == "evidence_lookup":
        if evidence_count:
            return (
                "answered",
                f"Supported: {evidence_count} authorized evidence snippet(s).",
            )
        return ("unsupported", "Authorized evidence snippets are unavailable.")
    if result_status == "complete_authorized_scope" and exact_count is not None:
        if exact_count == 0:
            return (
                "no_answer",
                "Complete authorized count: 0.",
            )
        if citation_count == 0:
            return (
                "no_answer",
                f"Count {exact_count}; authorized citations missing, so unverified.",
            )
        return (
            "exact_complete",
            f"Complete authorized count: {exact_count}.",
        )
    if result_status == "incomplete" and exact_count is not None:
        return (
            "exact_incomplete",
            f"Incomplete authorized count: {exact_count}; not definitive.",
        )
    if result_status in {"no_answer", "not_found", "route_blocked"}:
        return (
            "no_answer",
            "Insufficient authorized evidence to answer.",
        )
    if result_status == "ok" and citation_count:
        citation_label = "citation" if citation_count == 1 else "citations"
        return (
            "answered",
            f"Supported: {citation_count} authorized {citation_label}.",
        )
    return (
        "no_answer",
        "Insufficient authorized evidence to answer.",
    )


__all__ = [
    "EvidenceAnswerBudget",
    "GovernedEvidenceAnswer",
    "ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID",
    "ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT",
    "ISSUE56_DETERMINISTIC_ANSWER_PROMPT_ID",
    "render_governed_evidence_answer",
]
