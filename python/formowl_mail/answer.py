"""Pinned deterministic final-answer contract for Issue #56 diagnostics.

The renderer consumes only governed execution results.  It never receives the
private adjudication manifest, expected evidence ids, or oracle answer text.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from formowl_contract import ContractValidationError, sha256_json

from ._guards import assert_public_payload_safe
from .candidates import WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
from .hybrid import AuthorizedSemanticMailSession, GovernedHybridRagResult, GovernedSemanticExecutionResult

ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID = "formowl_deterministic_evidence_answer_v1"
ISSUE56_DETERMINISTIC_ANSWER_PROMPT_ID = "issue56_shared_evidence_answer_prompt_v1"
_ANSWER_PROMPT = (
    "Render only the governed status, exact count when deterministically "
    "available, and authorized citation hashes. Do not infer missing facts."
)
ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT = sha256_json(_ANSWER_PROMPT)


def _candidate_table_session_binding(session: AuthorizedSemanticMailSession) -> str:
    source = session.authorized_source
    source_binding = session.source_session_binding_fingerprint
    if (source is None or source.workspace_id != session.workspace_id
            or source.source_scope_ids != session.authorized_source_scope_ids
            or not isinstance(source_binding, str) or len(source_binding) != 71
            or not source_binding.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in source_binding[7:])):
        raise ContractValidationError("candidate table source session binding is invalid")
    return sha256_json({
        "identity_scope_mode": WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        "source_session_binding_fingerprint": source_binding,
        "source_authorization_fingerprint": source.authorization_fingerprint,
        "requester_fingerprint": sha256_json(session.requester_user_id),
        "workspace_fingerprint": sha256_json(session.workspace_id),
        "selected_source_scope_hashes": [sha256_json(value)
                                         for value in session.selected_source_scope_ids],
        "authorized_source_scope_hashes": [sha256_json(value)
                                           for value in session.authorized_source_scope_ids],
        "authorized_observation_bindings": [sha256_json(value)
                                             for value in session.authorized_observation_hashes],
        "index_fingerprint": session.index.index_fingerprint,
    })


@dataclass(frozen=True)
class _CandidateTableLookup:
    profile_fingerprint: str; ledger_fingerprint: str; lookup_fingerprint: str
    _authorized_session_binding_fingerprint: str = field(repr=False)
    header_labels: frozenset[str]
    matches: Mapping[tuple[str, str], tuple[Mapping[str, Any], ...]] = field(repr=False)
    ambiguous_keys: frozenset[tuple[str, str]] = field(repr=False)

@dataclass(frozen=True)
class _CandidateTableInterpretation:
    query_hash: str; lookup_fingerprint: str
    header: str; value: str
    governed_citations: tuple[tuple[str, str, str], ...]
    result_fingerprint: str
    status: str = field(default="candidate_interpretation", init=False)
    canonical_kg: bool = field(default=False, init=False)
    deterministic_exact: bool = field(default=False, init=False)
    exact_result: None = field(default=None, init=False)

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": "formowl_candidate_table_interpretation_v1",
            "status": self.status, "query_hash": self.query_hash,
            "lookup_fingerprint": self.lookup_fingerprint,
            "header": self.header, "value": self.value,
            "governed_citations": [{"role": role, "observation_hash": observation_hash,
                "lineage_fingerprint": lineage_fingerprint}
                for role, observation_hash, lineage_fingerprint in self.governed_citations],
            "canonical_kg": self.canonical_kg, "deterministic_exact": self.deterministic_exact,
            "exact_result": self.exact_result,
            "result_fingerprint": self.result_fingerprint,
        }
        assert_public_payload_safe(payload, "candidate_table_interpretation"); return payload
def build_authorized_candidate_table_lookup(*, session: AuthorizedSemanticMailSession,
                                            ledger: Mapping[str, Any]) -> _CandidateTableLookup:
    if not isinstance(session, AuthorizedSemanticMailSession) or not isinstance(ledger, Mapping):
        raise ContractValidationError("candidate table lookup input is invalid")
    profile = session.index._runtime_components.tokenizer_profile
    ledger_fingerprint = ledger.get("ledger_fingerprint"); tables = ledger.get("tables")
    payload = {key: value for key, value in ledger.items() if key != "ledger_fingerprint"}
    if (profile.profile_fingerprint != session.index.profile_fingerprint
            or ledger.get("structure_status") != "candidate_only"
            or not isinstance(ledger_fingerprint, str)
            or ledger_fingerprint != sha256_json(payload)
            or not isinstance(tables, (list, tuple))):
        raise ContractValidationError("candidate table ledger is invalid")
    observations = {item.observation_id: item for item in session.authorized_observations}
    hashes = dict(session.authorized_observation_hashes)
    lineages = {item.source_observation_id: item.lineage_fingerprint
                for item in session.occurrence_lineages}
    if (len(observations) != len(session.authorized_observations)
            or len(lineages) != len(session.occurrence_lineages)
            or any(hashes.get(key) != sha256_json(value.to_dict())
                   for key, value in observations.items())):
        raise ContractValidationError("candidate table session binding is invalid")
    def resolve(reference: Any, expected_type: str) -> Any:
        if not isinstance(reference, Mapping):
            raise ContractValidationError("candidate table reference is invalid")
        observation_id = reference.get("observation_id")
        observation = observations.get(observation_id)
        payload = observation.payload if observation is not None else None
        structure = payload.get("table_structure") if isinstance(payload, Mapping) else None
        canonical_statuses = (() if not isinstance(structure, Mapping) else (
            structure.get("canonical_fact_status"), payload.get("canonical_fact_status")))
        if (observation is None or observation.observation_type != expected_type
                or hashes.get(observation_id) != reference.get("observation_hash")
                or lineages.get(observation_id) != reference.get("lineage_fingerprint")
                or not isinstance(observation.text, str) or not isinstance(structure, Mapping)
                or structure.get("structure_status") != "candidate_only"
                or any(value is not None and value != "not_asserted" for value in canonical_statuses)
                or ("value_hash" in reference
                    and sha256_json(observation.text) != reference.get("value_hash"))):
            raise ContractValidationError("candidate table binding is invalid")
        return observation
    matches: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    ambiguous: set[tuple[str, str]] = set(); header_labels: set[str] = set()
    for table in tables:
        if not isinstance(table, Mapping):
            raise ContractValidationError("candidate table is invalid")
        rows = table.get("rows")
        if (table.get("structure_status") != "candidate_only"
                or not isinstance(rows, (list, tuple)) or not rows
                or not isinstance(rows[0], Mapping)):
            raise ContractValidationError("candidate table is invalid")
        resolve(rows[0], "table_row")
        header_cell_ids = {
            resolve(item, "table_cell").observation_id for item in rows[0].get("cells", ())
        }
        headers = []
        for reference in table.get("header_hypotheses", ()):
            header = resolve(reference, "table_cell")
            column = reference.get("column_ordinal")
            if (reference.get("observation_id") not in header_cell_ids
                    or not isinstance(column, int) or isinstance(column, bool)):
                raise ContractValidationError("candidate table header binding is invalid")
            label = header.text.strip()
            if not label:
                raise ContractValidationError("candidate table header is invalid")
            headers.append((label, reference)); header_labels.add(label)
        for row_reference in rows[1:]:
            if not isinstance(row_reference, Mapping):
                raise ContractValidationError("candidate table row is invalid")
            resolve(row_reference, "table_row")
            cells: dict[int, list[tuple[Mapping[str, Any], Any]]] = {}
            identifiers: dict[str, list[tuple[Mapping[str, Any], Any]]] = {}
            for reference in row_reference.get("cells", ()):
                cell = resolve(reference, "table_cell")
                column = reference.get("column_ordinal")
                if not isinstance(column, int) or isinstance(column, bool) or column < 0:
                    raise ContractValidationError("candidate table cell is invalid")
                cells.setdefault(column, []).append((reference, cell))
                for span in profile.analyze(cell.text).protected_identifiers:
                    identifiers.setdefault(span.exact_token, []).append((reference, cell))
            for header, header_reference in headers:
                projections = cells.get(header_reference["column_ordinal"], ())
                for identifier, identifier_cells in identifiers.items():
                    key = (identifier, header)
                    if len(identifier_cells) != 1 or len(projections) != 1:
                        ambiguous.add(key); continue
                    value = projections[0][1].text.strip()
                    if not value:
                        continue
                    references = (("header", header_reference), ("row", row_reference),
                                  ("identifier_cell", identifier_cells[0][0]),
                                  ("projection_cell", projections[0][0]))
                    matches.setdefault(key, []).append(MappingProxyType({
                        "header": header, "value": value,
                        "governed_citations": tuple(
                            (role, ref["observation_hash"], ref["lineage_fingerprint"])
                            for role, ref in references),
                    }))
    frozen = {key: tuple(value) for key, value in matches.items()}
    ambiguous.update(key for key, value in frozen.items() if len(value) != 1)
    session_binding = _candidate_table_session_binding(session)
    lookup_fingerprint = sha256_json({
        "ledger_fingerprint": ledger_fingerprint, "profile_fingerprint": profile.profile_fingerprint,
        "authorized_session_binding_fingerprint": session_binding,
        "keys": sorted((sha256_json(key), len(value)) for key, value in frozen.items()),
        "ambiguous_keys": sorted(sha256_json(key) for key in ambiguous),
    })
    return _CandidateTableLookup(profile.profile_fingerprint, ledger_fingerprint,
        lookup_fingerprint, session_binding, frozenset(header_labels),
        MappingProxyType(frozen), frozenset(ambiguous))
def interpret_authorized_candidate_table_query(*, session: AuthorizedSemanticMailSession,
    query_text: str, lookup: _CandidateTableLookup) -> _CandidateTableInterpretation | None:
    if (not isinstance(session, AuthorizedSemanticMailSession)
            or not isinstance(query_text, str) or not query_text.strip()
            or not isinstance(lookup, _CandidateTableLookup)):
        raise ContractValidationError("candidate table query input is invalid")
    profile = session.index._runtime_components.tokenizer_profile
    session_binding = _candidate_table_session_binding(session)
    expected_lookup_fingerprint = sha256_json({
        "ledger_fingerprint": lookup.ledger_fingerprint,
        "profile_fingerprint": lookup.profile_fingerprint,
        "authorized_session_binding_fingerprint": session_binding,
        "keys": sorted((sha256_json(key), len(value))
                       for key, value in lookup.matches.items()),
        "ambiguous_keys": sorted(sha256_json(key) for key in lookup.ambiguous_keys),
    })
    if (profile.profile_fingerprint != lookup.profile_fingerprint
            or session_binding != lookup._authorized_session_binding_fingerprint
            or expected_lookup_fingerprint != lookup.lookup_fingerprint):
        raise ContractValidationError("candidate table query session binding mismatch")
    identifiers = profile.analyze(query_text).protected_identifiers
    if len(identifiers) != 1:
        return None
    labels = [query_text[term.start:term.end]
              for term in profile.analyze_query_grounding(query_text).terms
              if query_text[term.start:term.end] in lookup.header_labels]
    if len(labels) != 1:
        return None
    key = (identifiers[0].exact_token, labels[0])
    selected = lookup.matches.get(key, ())
    if key in lookup.ambiguous_keys or len(selected) != 1:
        return None
    match = selected[0]; citations = match["governed_citations"]
    if len(citations) != 4:
        raise ContractValidationError("candidate table citation binding is invalid")
    query_hash = sha256_json(query_text)
    binding = {
        "status": "candidate_interpretation", "query_hash": query_hash,
        "lookup_fingerprint": lookup.lookup_fingerprint,
        "header_hash": sha256_json(match["header"]), "value_hash": sha256_json(match["value"]),
        "governed_citations": citations, "canonical_kg": False,
        "deterministic_exact": False, "exact_result": None,
    }
    result = _CandidateTableInterpretation(
        query_hash=query_hash, lookup_fingerprint=lookup.lookup_fingerprint, header=match["header"],
        value=match["value"], governed_citations=citations,
        result_fingerprint=sha256_json(binding))
    result.to_safe_dict(); return result

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
    "build_authorized_candidate_table_lookup",
    "interpret_authorized_candidate_table_query",
    "render_governed_evidence_answer",
]
