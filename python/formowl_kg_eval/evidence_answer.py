from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Iterable, Sequence

from formowl_contract import ContractValidationError, sha256_json
from formowl_mail import MailEvidenceBundle

from .structured_answer import (
    GoldAction,
    GoldCitation,
    GoldFact,
    LifecycleBinding,
    PredictedAction,
    PredictedFact,
    PrivateStructuredAnswerGold,
    StructuredAnswerPrediction,
)


_BLOCKER_TERMS = {
    "block",
    "blocked",
    "delay",
    "delayed",
    "failure",
    "hold",
    "issue",
    "missing",
    "risk",
    "shortage",
    "waiting",
}
_RESOLUTION_TERMS = {
    "cleared",
    "closed",
    "completed",
    "delivered",
    "fixed",
    "released",
    "resolved",
}
_REOPEN_TERMS = {"again", "recurred", "recurrence", "reopened", "returned"}
_ACTION_TERMS = {
    "approve",
    "confirm",
    "contact",
    "escalate",
    "follow",
    "provide",
    "review",
    "schedule",
    "send",
    "update",
}
_UNCERTAINTY_TERMS = {"maybe", "pending", "tbd", "unclear", "unconfirmed", "unknown"}
_STATUS_TERMS = (
    _BLOCKER_TERMS
    | _RESOLUTION_TERMS
    | _REOPEN_TERMS
    | {
        "approved",
        "complete",
        "on",
        "open",
        "ready",
        "status",
    }
)
_DATE_RE = re.compile(
    r"\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|"
    r"\d{1,2}[-/]\d{1,2}(?:[-/]20\d{2})?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2})\b",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STRICT_OWNER_PATTERNS = (
    re.compile(
        r"\b(?:owner|responsible(?: party)?|assigned to)\s*[:=-]\s*"
        r"(?P<owner>[A-Za-z][A-Za-z0-9_.+-]*(?:\s+[A-Z][A-Za-z0-9_.+-]*){0,2}"
        r"(?:@[A-Za-z0-9.-]+\.[A-Za-z]{2,})?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<owner>[A-Z][A-Za-z0-9_.+-]*(?:\s+[A-Z][A-Za-z0-9_.+-]*){0,2})\s+"
        r"(?:must|should|needs to|will|owns|is responsible for)\b"
    ),
)
_PREDICTION_OWNER_PATTERNS = (
    re.compile(
        r"\b(?P<owner>[A-Z][A-Za-z0-9_.+-]*(?:\s+[A-Z][A-Za-z0-9_.+-]*){0,2})\s+"
        r"(?:must|should|will|needs to)\b"
    ),
    re.compile(
        r"\b(?:assigned to|owner|responsible(?: party)?)\s*[:=-]\s*" r"(?P<owner>[^,.;]+)",
        re.IGNORECASE,
    ),
)
_DEPENDENCY_PATTERNS = (
    re.compile(r"\bdepends? on\s+(?P<dependency>[^.;]+)", re.IGNORECASE),
    re.compile(r"\bwaiting for\s+(?P<dependency>[^.;]+)", re.IGNORECASE),
    re.compile(r"\bblocked by\s+(?P<dependency>[^.;]+)", re.IGNORECASE),
)
_PREDICTION_DEPENDENCY_PATTERNS = (
    re.compile(r"\b(?:depends? on|blocked by)\s+(?P<dependency>[^.;]+)", re.IGNORECASE),
    re.compile(r"\bwaiting for\s+(?P<dependency>[^.;]+)", re.IGNORECASE),
    re.compile(r"\bafter\s+(?P<dependency>[^.;]+)", re.IGNORECASE),
)
_ACTION_MODAL_TERMS = {"must", "need", "needs", "should", "will"}
_PREDICTION_ACTION_CUES = _ACTION_MODAL_TERMS | {"action", "next", "please"}


@dataclass(frozen=True)
class EvidenceDocument:
    evidence_id: str
    text: str
    sent_at: str | None = None
    sender: str | None = None
    thread_id: str | None = None
    case_scope_id: str | None = None
    subject: str | None = None

    def __post_init__(self) -> None:
        if self.sent_at is not None:
            object.__setattr__(self, "sent_at", _normalize_evidence_timestamp(self.sent_at))


@dataclass(frozen=True)
class _SentenceRow:
    document: EvidenceDocument
    text: str
    index: int
    thread_id: str
    tokens: frozenset[str]

    @property
    def sort_key(self) -> tuple[str, str, int]:
        return (self.document.sent_at or "", self.document.evidence_id, self.index)


@dataclass(frozen=True)
class _ClaimSeed:
    category: str
    text: str
    row: _SentenceRow


@dataclass(frozen=True)
class _LifecycleEvent:
    state: str
    row: _SentenceRow
    event_id: str


def evidence_documents_from_bundle(
    bundle: MailEvidenceBundle,
    evidence_ids: Iterable[str],
) -> tuple[EvidenceDocument, ...]:
    selected = set(evidence_ids)
    messages = {message.email_message_id: message for message in bundle.messages}
    documents: list[EvidenceDocument] = []
    for segment in bundle.body_segments:
        if segment.source_observation_id not in selected:
            continue
        message = messages.get(segment.email_message_id)
        documents.append(
            EvidenceDocument(
                evidence_id=segment.source_observation_id,
                text=segment.text,
                sent_at=message.sent_at if message else None,
                sender=message.sender if message else None,
                thread_id=message.thread_id if message else None,
                subject=message.subject if message else None,
            )
        )
    return tuple(sorted(documents, key=lambda item: (item.sent_at or "", item.evidence_id)))


def _normalize_evidence_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError("evidence sent_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def build_private_gold_from_evidence(
    *,
    case_id: str,
    result_kind: str,
    query_text: str,
    documents: Sequence[EvidenceDocument],
) -> PrivateStructuredAnswerGold:
    """Build deterministic candidate gold from an evidence event ledger.

    The result is evidence-derived candidate gold, not human-authored or adjudicated
    gold. Its strict rules intentionally differ from prediction extraction.
    """

    outcome = _outcome(result_kind)
    if outcome != "answerable":
        return PrivateStructuredAnswerGold(case_id=case_id, outcome=outcome)
    rows, case_scope_id, thread_ids = _prepare_rows(case_id, documents)
    ledger = _build_gold_ledger(rows, query_text)
    return _materialize_gold(
        case_id=case_id,
        case_scope_id=case_scope_id,
        thread_ids=thread_ids,
        ledger=ledger,
    )


def build_prediction_from_evidence(
    *,
    case_id: str,
    result_kind: str,
    query_text: str,
    documents: Sequence[EvidenceDocument],
    permission_denied: bool = False,
) -> StructuredAnswerPrediction:
    """Build a deterministic query-focused prediction from selected evidence."""

    if permission_denied:
        return StructuredAnswerPrediction(outcome="permission_denied")
    if result_kind == "no_match" and not documents:
        return StructuredAnswerPrediction(outcome="no_match")
    if not documents:
        return StructuredAnswerPrediction(outcome="no_match")
    rows, case_scope_id, thread_ids = _prepare_rows(case_id, documents)
    return _build_query_focused_prediction(
        case_id=case_id,
        case_scope_id=case_scope_id,
        thread_ids=thread_ids,
        query_text=query_text,
        rows=rows,
    )


def _build_gold_ledger(
    rows: Sequence[_SentenceRow],
    query_text: str,
) -> dict[str, object]:
    query_tokens = _tokens(query_text)
    status_rows = [row for row in rows if row.tokens & _STATUS_TERMS]
    latest_status = max(
        status_rows or rows,
        key=lambda row: (row.sort_key, len(row.tokens & query_tokens), len(row.text)),
    )
    owner_seeds = _strict_owner_seeds(rows)
    action_seeds = _gold_action_seeds(rows)
    deadline_seeds = _gold_deadline_seeds(rows, action_seeds)
    dependency_seeds = _gold_dependency_seeds(rows)
    uncertainty_seeds = [
        _ClaimSeed("uncertainty", row.text, row) for row in rows if row.tokens & _UNCERTAINTY_TERMS
    ]
    blocker_history, open_blockers, lifecycle_events = _gold_blocker_ledger(rows)
    return {
        "latest_status": _ClaimSeed("latest", latest_status.text, latest_status),
        "blocker_history": blocker_history,
        "open_blockers": open_blockers,
        "owners": owner_seeds,
        "deadlines": deadline_seeds,
        "actions": action_seeds,
        "dependencies": dependency_seeds,
        "uncertainties": uncertainty_seeds,
        "lifecycle_events": lifecycle_events,
    }


def _materialize_gold(
    *,
    case_id: str,
    case_scope_id: str,
    thread_ids: tuple[str, ...],
    ledger: dict[str, object],
) -> PrivateStructuredAnswerGold:
    citations: dict[str, GoldCitation] = {}
    citation_claims: dict[str, set[str]] = {}

    def fact(seed: _ClaimSeed, ordinal: int) -> GoldFact:
        claim_id = _id(
            "gold", case_id, seed.category, seed.row.document.evidence_id, seed.text, ordinal
        )
        citation_id = _citation_id(seed.row.document.evidence_id)
        citation_claims.setdefault(citation_id, set()).add(claim_id)
        citations[citation_id] = _gold_citation(
            citation_id,
            seed.row,
            case_scope_id,
            tuple(sorted(citation_claims[citation_id])),
        )
        return GoldFact(
            claim_id=claim_id,
            text=seed.text,
            citation_ids=(citation_id,),
            valid_from=seed.row.document.sent_at,
            case_scope_id=case_scope_id,
            thread_id=seed.row.thread_id,
        )

    latest_status = fact(ledger["latest_status"], 0)  # type: ignore[arg-type]
    blocker_history = tuple(
        fact(seed, index)
        for index, seed in enumerate(ledger["blocker_history"])  # type: ignore[arg-type]
    )
    open_blockers = tuple(
        fact(seed, index)
        for index, seed in enumerate(ledger["open_blockers"])  # type: ignore[arg-type]
    )
    owners = tuple(
        fact(seed, index)
        for index, seed in enumerate(ledger["owners"])  # type: ignore[arg-type]
    )
    deadlines = tuple(
        fact(seed, index)
        for index, seed in enumerate(ledger["deadlines"])  # type: ignore[arg-type]
    )
    dependencies = tuple(
        fact(seed, index)
        for index, seed in enumerate(ledger["dependencies"])  # type: ignore[arg-type]
    )
    uncertainties = tuple(
        fact(seed, index)
        for index, seed in enumerate(ledger["uncertainties"])  # type: ignore[arg-type]
    )
    owner_by_row = _facts_by_row(owners, ledger["owners"])  # type: ignore[arg-type]
    deadline_by_row = _facts_by_row(deadlines, ledger["deadlines"])  # type: ignore[arg-type]
    dependency_by_row = _facts_by_row(dependencies, ledger["dependencies"])  # type: ignore[arg-type]
    actions: list[GoldAction] = []
    for index, seed in enumerate(ledger["actions"]):  # type: ignore[arg-type]
        base = fact(seed, index)
        actions.append(
            GoldAction(
                **base.__dict__,
                responsible_party_claim_ids=tuple(
                    item.claim_id for item in owner_by_row.get(seed.row, ())
                ),
                deadline_claim_ids=tuple(
                    item.claim_id for item in deadline_by_row.get(seed.row, ())
                ),
                dependency_claim_ids=tuple(
                    item.claim_id for item in dependency_by_row.get(seed.row, ())
                ),
            )
        )
    history_by_signature = {
        _gold_blocker_signature(seed.row): item
        for seed, item in zip(ledger["blocker_history"], blocker_history, strict=True)  # type: ignore[arg-type]
    }
    lifecycle: list[LifecycleBinding] = []
    for signature, events in ledger["lifecycle_events"].items():  # type: ignore[union-attr]
        subject = history_by_signature[signature]
        for event in events:
            citation_id = _citation_id(event.row.document.evidence_id)
            citation_claims.setdefault(citation_id, set()).add(subject.claim_id)
            citations[citation_id] = _gold_citation(
                citation_id,
                event.row,
                case_scope_id,
                tuple(sorted(citation_claims[citation_id])),
            )
            lifecycle.append(
                LifecycleBinding(
                    binding_id=_id("gold_lifecycle", case_id, signature, event.event_id),
                    subject_claim_id=subject.claim_id,
                    state=event.state,  # type: ignore[arg-type]
                    valid_from=event.row.document.sent_at or "1970-01-01T00:00:00+00:00",
                    resolved_by=event.event_id if event.state == "resolved" else None,
                    reopened_by=event.event_id if event.state == "reopened" else None,
                    citation_ids=(citation_id,),
                )
            )
    return PrivateStructuredAnswerGold(
        case_id=case_id,
        outcome="answerable",
        case_scope_id=case_scope_id,
        thread_ids=thread_ids,
        latest_status=latest_status,
        open_blockers=open_blockers,
        blocker_history=blocker_history,
        responsible_parties=owners,
        deadlines=deadlines,
        deadline_disclosure="explicit" if deadlines else "missing" if actions else "not_applicable",
        next_actions=tuple(actions),
        dependencies=dependencies,
        citations=tuple(citations.values()),
        uncertainties=uncertainties,
        lifecycle_bindings=tuple(lifecycle),
    )


def _build_query_focused_prediction(
    *,
    case_id: str,
    case_scope_id: str,
    thread_ids: tuple[str, ...],
    query_text: str,
    rows: Sequence[_SentenceRow],
) -> StructuredAnswerPrediction:
    query_tokens = _tokens(query_text)
    relevant = sorted(
        rows,
        key=lambda row: (len(row.tokens & query_tokens), row.sort_key),
        reverse=True,
    )
    status_pool = [row for row in rows if row.tokens & _STATUS_TERMS]
    latest_row = max(status_pool or relevant, key=lambda row: row.sort_key)
    owner_seeds = _prediction_owner_seeds(relevant)
    action_seeds = _prediction_action_seeds(relevant)
    deadline_seeds = _prediction_deadline_seeds(relevant, action_seeds)
    dependency_seeds = _prediction_dependency_seeds(relevant, action_seeds)
    blocker_history, open_blockers, lifecycle_events = _prediction_blocker_state(relevant)
    uncertainty_seeds = [
        _ClaimSeed("uncertainty", row.text, row)
        for row in relevant
        if row.tokens & _UNCERTAINTY_TERMS
    ][:3]

    def predicted(seed: _ClaimSeed, ordinal: int) -> PredictedFact:
        return PredictedFact(
            claim_id=_id(
                "pred",
                case_id,
                seed.category,
                seed.row.document.evidence_id,
                seed.text,
                ordinal,
            ),
            text=seed.text,
            citation_ids=(_citation_id(seed.row.document.evidence_id),),
            valid_from=seed.row.document.sent_at,
            case_scope_id=case_scope_id,
            thread_id=seed.row.thread_id,
        )

    latest_status = predicted(_ClaimSeed("latest", latest_row.text, latest_row), 0)
    history = tuple(predicted(seed, index) for index, seed in enumerate(blocker_history))
    blockers = tuple(predicted(seed, index) for index, seed in enumerate(open_blockers))
    owners = tuple(predicted(seed, index) for index, seed in enumerate(owner_seeds))
    deadlines = tuple(predicted(seed, index) for index, seed in enumerate(deadline_seeds))
    dependencies = tuple(predicted(seed, index) for index, seed in enumerate(dependency_seeds))
    uncertainties = tuple(predicted(seed, index) for index, seed in enumerate(uncertainty_seeds))
    owner_by_row = _facts_by_row(owners, owner_seeds)
    deadline_by_row = _facts_by_row(deadlines, deadline_seeds)
    dependency_by_row = _facts_by_row(dependencies, dependency_seeds)
    actions: list[PredictedAction] = []
    for index, seed in enumerate(action_seeds):
        base = predicted(seed, index)
        actions.append(
            PredictedAction(
                **base.__dict__,
                responsible_party_claim_ids=tuple(
                    item.claim_id for item in owner_by_row.get(seed.row, ())
                ),
                deadline_claim_ids=tuple(
                    item.claim_id for item in deadline_by_row.get(seed.row, ())
                ),
                dependency_claim_ids=tuple(
                    item.claim_id for item in dependency_by_row.get(seed.row, ())
                ),
            )
        )
    history_by_signature = {
        _prediction_blocker_key(seed.row): item
        for seed, item in zip(blocker_history, history, strict=True)
    }
    lifecycle: list[LifecycleBinding] = []
    for signature, events in lifecycle_events.items():
        subject = history_by_signature[signature]
        for event in events:
            lifecycle.append(
                LifecycleBinding(
                    binding_id=_id("pred_lifecycle", case_id, signature, event.event_id),
                    subject_claim_id=subject.claim_id,
                    state=event.state,  # type: ignore[arg-type]
                    valid_from=event.row.document.sent_at or "1970-01-01T00:00:00+00:00",
                    resolved_by=event.event_id if event.state == "resolved" else None,
                    reopened_by=event.event_id if event.state == "reopened" else None,
                    citation_ids=(_citation_id(event.row.document.evidence_id),),
                )
            )
    return StructuredAnswerPrediction(
        outcome="answerable",
        case_scope_id=case_scope_id,
        thread_ids=thread_ids,
        latest_status=latest_status,
        open_blockers=blockers,
        blocker_history=history,
        responsible_parties=owners,
        deadlines=deadlines,
        deadline_disclosure="explicit" if deadlines else "missing" if actions else "not_applicable",
        next_actions=tuple(actions),
        dependencies=dependencies,
        uncertainties=uncertainties,
        lifecycle_bindings=tuple(lifecycle),
    )


def _prepare_rows(
    case_id: str,
    documents: Sequence[EvidenceDocument],
) -> tuple[tuple[_SentenceRow, ...], str, tuple[str, ...]]:
    if not documents:
        raise ContractValidationError("answer extraction requires evidence documents")
    case_scopes = {item.case_scope_id for item in documents if item.case_scope_id}
    if len(case_scopes) > 1:
        raise ContractValidationError("evidence documents span multiple case scopes")
    case_scope_id = next(iter(case_scopes), case_id)
    fallback_thread = _id("thread", case_id)
    rows: list[_SentenceRow] = []
    for document in sorted(documents, key=lambda item: (item.sent_at or "", item.evidence_id)):
        thread_id = document.thread_id or fallback_thread
        for index, sentence in enumerate(_sentences(document.text)):
            rows.append(
                _SentenceRow(
                    document=document,
                    text=sentence,
                    index=index,
                    thread_id=thread_id,
                    tokens=frozenset(_tokens(sentence)),
                )
            )
    if not rows:
        raise ContractValidationError("answer extraction requires non-empty evidence text")
    thread_ids = tuple(sorted({row.thread_id for row in rows}))
    return tuple(rows), case_scope_id, thread_ids


def _gold_blocker_ledger(
    rows: Sequence[_SentenceRow],
) -> tuple[list[_ClaimSeed], list[_ClaimSeed], dict[str, list[_LifecycleEvent]]]:
    lifecycle: dict[str, list[_LifecycleEvent]] = {}
    first_rows: dict[str, _SentenceRow] = {}
    latest_rows: dict[str, _SentenceRow] = {}
    for row in sorted(rows, key=lambda item: item.sort_key):
        state = _gold_lifecycle_state(row)
        if state is None:
            continue
        signature = _gold_blocker_signature(row)
        if not signature:
            continue
        event = _lifecycle_event("event", row, state)
        lifecycle.setdefault(signature, []).append(event)
        first_rows.setdefault(signature, row)
        latest_rows[signature] = row
    history = [
        _ClaimSeed("blocker_history", first_rows[signature].text, first_rows[signature])
        for signature in sorted(first_rows)
    ]
    open_blockers = [
        _ClaimSeed("blocker", latest_rows[signature].text, latest_rows[signature])
        for signature in sorted(lifecycle)
        if lifecycle[signature][-1].state in {"open", "reopened"}
    ]
    return history, open_blockers, lifecycle


def _prediction_blocker_state(
    rows: Sequence[_SentenceRow],
) -> tuple[list[_ClaimSeed], list[_ClaimSeed], dict[str, list[_LifecycleEvent]]]:
    lifecycle: dict[str, list[_LifecycleEvent]] = {}
    history_rows: dict[str, _SentenceRow] = {}
    active_rows: dict[str, _SentenceRow] = {}
    for row in sorted(rows, key=lambda item: item.sort_key):
        state = _prediction_lifecycle_state(row)
        if state is None:
            continue
        signature = _prediction_blocker_key(row)
        if not signature:
            continue
        lifecycle.setdefault(signature, []).append(_lifecycle_event("event", row, state))
        history_rows.setdefault(signature, row)
        if state in {"open", "reopened"}:
            active_rows[signature] = row
        else:
            active_rows.pop(signature, None)
    history = [
        _ClaimSeed("blocker_history", history_rows[signature].text, history_rows[signature])
        for signature in sorted(history_rows)
    ]
    open_blockers = [
        _ClaimSeed("blocker", active_rows[signature].text, active_rows[signature])
        for signature in sorted(active_rows)
    ]
    return history, open_blockers, lifecycle


def _gold_lifecycle_state(row: _SentenceRow) -> str | None:
    if row.tokens & _REOPEN_TERMS:
        return "reopened"
    if row.tokens & _RESOLUTION_TERMS:
        return "resolved"
    if row.tokens & _BLOCKER_TERMS:
        return "open"
    return None


def _prediction_lifecycle_state(row: _SentenceRow) -> str | None:
    if "reopened" in row.tokens or "recurred" in row.tokens:
        return "reopened"
    if row.tokens & _RESOLUTION_TERMS:
        return "resolved"
    if row.tokens & _BLOCKER_TERMS:
        return "reopened" if "again" in row.tokens else "open"
    return None


def _lifecycle_event(prefix: str, row: _SentenceRow, state: str) -> _LifecycleEvent:
    return _LifecycleEvent(
        state=state,
        row=row,
        event_id=_id(
            prefix,
            row.document.evidence_id,
            row.thread_id,
            row.document.sent_at,
            row.index,
            row.text,
            state,
        ),
    )


def _gold_blocker_signature(row: _SentenceRow) -> str:
    ignored = (
        _BLOCKER_TERMS
        | _RESOLUTION_TERMS
        | _REOPEN_TERMS
        | _ACTION_TERMS
        | _UNCERTAINTY_TERMS
        | {
            "a",
            "an",
            "and",
            "at",
            "by",
            "for",
            "from",
            "has",
            "is",
            "it",
            "of",
            "on",
            "remains",
            "the",
            "to",
            "was",
            "we",
        }
    )
    meaningful = sorted(
        token for token in row.tokens if token not in ignored and not token.isdigit()
    )
    return ":".join(meaningful[:4]) or ":".join(sorted(row.tokens & _BLOCKER_TERMS))


def _prediction_blocker_key(row: _SentenceRow) -> str:
    ignored = (
        _STATUS_TERMS
        | _ACTION_TERMS
        | _UNCERTAINTY_TERMS
        | {
            "a",
            "an",
            "and",
            "by",
            "for",
            "from",
            "is",
            "of",
            "on",
            "the",
            "to",
            "was",
        }
    )
    ordered = [
        token
        for token in _TOKEN_RE.findall(row.text.casefold())
        if token not in ignored and not token.isdigit()
    ]
    return ":".join(dict.fromkeys(ordered))[:96]


def _strict_owner_seeds(rows: Sequence[_SentenceRow]) -> list[_ClaimSeed]:
    return _owner_seeds(rows, _STRICT_OWNER_PATTERNS)


def _prediction_owner_seeds(rows: Sequence[_SentenceRow]) -> list[_ClaimSeed]:
    return _owner_seeds(rows, _PREDICTION_OWNER_PATTERNS)


def _owner_seeds(
    rows: Sequence[_SentenceRow],
    patterns: Sequence[re.Pattern[str]],
) -> list[_ClaimSeed]:
    seeds: list[_ClaimSeed] = []
    seen: set[tuple[str, _SentenceRow]] = set()
    for row in rows:
        for pattern in patterns:
            match = pattern.search(row.text)
            if not match:
                continue
            owner = " ".join(match.group("owner").strip().split())
            key = (owner.casefold(), row)
            if owner and key not in seen:
                seen.add(key)
                seeds.append(_ClaimSeed("party", owner, row))
            break
    return seeds[:3]


def _gold_action_seeds(rows: Sequence[_SentenceRow]) -> list[_ClaimSeed]:
    return [
        _ClaimSeed("action", row.text, row)
        for row in rows
        if row.tokens & _ACTION_TERMS and row.tokens & _ACTION_MODAL_TERMS
    ][:3]


def _prediction_action_seeds(rows: Sequence[_SentenceRow]) -> list[_ClaimSeed]:
    return [
        _ClaimSeed("action", row.text, row)
        for row in rows
        if row.tokens & _ACTION_TERMS and row.tokens & _PREDICTION_ACTION_CUES
    ][:3]


def _gold_deadline_seeds(
    rows: Sequence[_SentenceRow],
    action_seeds: Sequence[_ClaimSeed],
) -> list[_ClaimSeed]:
    action_rows = {seed.row for seed in action_seeds}
    seeds: list[_ClaimSeed] = []
    for row in rows:
        if row not in action_rows and not row.tokens & {"deadline", "due"}:
            continue
        for match in _DATE_RE.finditer(row.text):
            seeds.append(_ClaimSeed("deadline", match.group(0), row))
    return seeds[:3]


def _prediction_deadline_seeds(
    rows: Sequence[_SentenceRow],
    action_seeds: Sequence[_ClaimSeed],
) -> list[_ClaimSeed]:
    action_rows = {seed.row for seed in action_seeds}
    seeds: list[_ClaimSeed] = []
    for row in rows:
        if row not in action_rows and not row.tokens & {"by", "deadline", "due"}:
            continue
        for match in _DATE_RE.finditer(row.text):
            seeds.append(_ClaimSeed("deadline", match.group(0), row))
            if len(seeds) == 3:
                return seeds
    return seeds


def _gold_dependency_seeds(rows: Sequence[_SentenceRow]) -> list[_ClaimSeed]:
    seeds: list[_ClaimSeed] = []
    for row in rows:
        for pattern in _DEPENDENCY_PATTERNS:
            match = pattern.search(row.text)
            if match:
                dependency = " ".join(match.group("dependency").strip().split())
                if dependency:
                    seeds.append(_ClaimSeed("dependency", dependency, row))
                break
    return seeds[:3]


def _prediction_dependency_seeds(
    rows: Sequence[_SentenceRow],
    action_seeds: Sequence[_ClaimSeed],
) -> list[_ClaimSeed]:
    action_rows = {seed.row for seed in action_seeds}
    seeds: list[_ClaimSeed] = []
    for row in rows:
        if row not in action_rows and not row.tokens & {"blocked", "waiting"}:
            continue
        for pattern in _PREDICTION_DEPENDENCY_PATTERNS:
            match = pattern.search(row.text)
            if not match:
                continue
            dependency = " ".join(match.group("dependency").strip().split())
            if dependency:
                seeds.append(_ClaimSeed("dependency", dependency, row))
            break
        if len(seeds) == 3:
            break
    return seeds


def _facts_by_row(
    facts: Sequence[GoldFact | PredictedFact],
    seeds: Sequence[_ClaimSeed],
) -> dict[_SentenceRow, tuple[GoldFact | PredictedFact, ...]]:
    grouped: dict[_SentenceRow, list[GoldFact | PredictedFact]] = {}
    for seed, item in zip(seeds, facts, strict=True):
        grouped.setdefault(seed.row, []).append(item)
    return {row: tuple(items) for row, items in grouped.items()}


def _gold_citation(
    citation_id: str,
    row: _SentenceRow,
    case_scope_id: str,
    supported_claim_ids: tuple[str, ...],
) -> GoldCitation:
    return GoldCitation(
        citation_id=citation_id,
        evidence_id=row.document.evidence_id,
        supported_claim_ids=supported_claim_ids,
        excerpt_hash=sha256_json(row.text),
        valid_from=row.document.sent_at,
        case_scope_id=case_scope_id,
        thread_id=row.thread_id,
    )


def _outcome(result_kind: str) -> str:
    if result_kind == "owner_match":
        return "answerable"
    if result_kind in {"no_match", "permission_denied"}:
        return result_kind
    raise ContractValidationError("unsupported result_kind")


def _sentences(text: str) -> tuple[str, ...]:
    return tuple(
        sentence.strip()[:500]
        for sentence in _SENTENCE_RE.split(text)
        if len(sentence.strip()) >= 12
    )


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _citation_id(evidence_id: str) -> str:
    return _id("citation", evidence_id)


def _id(prefix: str, *parts: object) -> str:
    return prefix + "_" + sha256_json(list(parts)).removeprefix("sha256:")[:24]


__all__ = [
    "EvidenceDocument",
    "build_prediction_from_evidence",
    "build_private_gold_from_evidence",
    "evidence_documents_from_bundle",
]
