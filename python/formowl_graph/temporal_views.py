"""Candidate-only bitemporal filtering POC.

The view answers two independent questions:

* ``as_of_world_time``: had the asserted event/state become applicable?
* ``known_as_of``: was the supporting assertion available to FormOwl yet?

It deliberately does not perform canonical writes or temporal inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from formowl_contract import (
    ASSERTION_LIFECYCLE_STATUS_VALUES,
    CandidateAssertion,
    EPISTEMIC_STATUS_VALUES,
    parse_temporal_value,
)


@dataclass(frozen=True)
class CandidateTemporalView:
    candidate_assertions: list[CandidateAssertion]
    as_of_world_time: str | None = None
    known_as_of: str | None = None
    epistemic_statuses: tuple[str, ...] = ()
    lifecycle_statuses: tuple[str, ...] = ()
    excluded_assertion_ids_by_reason: dict[str, list[str]] = field(default_factory=dict)
    canonical_write_allowed: bool = field(default=False, init=False)


def build_candidate_temporal_view(
    candidate_assertions: Sequence[CandidateAssertion],
    *,
    as_of_world_time: str | None = None,
    known_as_of: str | None = None,
    epistemic_statuses: Sequence[str] | None = None,
    lifecycle_statuses: Sequence[str] | None = None,
) -> CandidateTemporalView:
    """Filter candidate assertions before lexical/vector ranking."""

    world_time = (
        parse_temporal_value(as_of_world_time, "as_of_world_time")
        if as_of_world_time is not None
        else None
    )
    knowledge_time = (
        parse_temporal_value(known_as_of, "known_as_of") if known_as_of is not None else None
    )
    requested_statuses = tuple(epistemic_statuses or ())
    unknown_statuses = set(requested_statuses).difference(EPISTEMIC_STATUS_VALUES)
    if unknown_statuses:
        raise ValueError(
            "epistemic_statuses contains unsupported values: " + ", ".join(sorted(unknown_statuses))
        )
    allowed_statuses = set(requested_statuses)
    requested_lifecycle_statuses = tuple(lifecycle_statuses or ())
    unknown_lifecycle_statuses = set(requested_lifecycle_statuses).difference(
        ASSERTION_LIFECYCLE_STATUS_VALUES
    )
    if unknown_lifecycle_statuses:
        raise ValueError(
            "lifecycle_statuses contains unsupported values: "
            + ", ".join(sorted(unknown_lifecycle_statuses))
        )
    allowed_lifecycle_statuses = set(requested_lifecycle_statuses)

    selected: list[CandidateAssertion] = []
    excluded: dict[str, list[str]] = {}
    for raw_assertion in candidate_assertions:
        assertion = CandidateAssertion.from_dict(raw_assertion.to_dict())
        if allowed_statuses and assertion.epistemic_status not in allowed_statuses:
            _record_exclusion(excluded, "epistemic_status", assertion)
            continue
        if (
            allowed_lifecycle_statuses
            and assertion.lifecycle_status not in allowed_lifecycle_statuses
        ):
            _record_exclusion(excluded, "lifecycle_status", assertion)
            continue
        if knowledge_time is not None and not _known_at(assertion, knowledge_time):
            _record_exclusion(excluded, "known_as_of", assertion)
            continue
        if world_time is not None and not _valid_at(assertion, world_time):
            _record_exclusion(excluded, "as_of_world_time", assertion)
            continue
        selected.append(assertion)

    return CandidateTemporalView(
        candidate_assertions=selected,
        as_of_world_time=as_of_world_time,
        known_as_of=known_as_of,
        epistemic_statuses=requested_statuses,
        lifecycle_statuses=requested_lifecycle_statuses,
        excluded_assertion_ids_by_reason=excluded,
    )


def _known_at(assertion: CandidateAssertion, as_of: datetime) -> bool:
    temporal = assertion.temporal_context
    if assertion.created_at is None:
        return False
    recorded_from = temporal.get("recorded_from")
    recorded_to = temporal.get("recorded_to")
    if recorded_from is not None and parse_temporal_value(recorded_from) > as_of:
        return False
    if recorded_to is not None and parse_temporal_value(recorded_to) < as_of:
        return False
    source_known_points = [
        value
        for value in (
            temporal.get("recorded_at"),
            temporal.get("captured_at"),
        )
        if value is not None
    ]
    if not source_known_points and recorded_from is None:
        return False
    return parse_temporal_value(assertion.created_at) <= as_of and all(
        parse_temporal_value(value) <= as_of for value in source_known_points
    )


def _valid_at(assertion: CandidateAssertion, as_of: datetime) -> bool:
    temporal = assertion.temporal_context
    valid_from = temporal.get("valid_from")
    valid_to = temporal.get("valid_to")
    if valid_from is not None and parse_temporal_value(valid_from) > as_of:
        return False
    if valid_to is not None and parse_temporal_value(valid_to) < as_of:
        return False
    world_points = [
        temporal[field_name]
        for field_name in ("phenomenon_time", "effective_at")
        if temporal.get(field_name) is not None
    ]
    if not world_points and temporal.get("observed_at") is not None:
        world_points.append(temporal["observed_at"])
    if not world_points and temporal.get("asserted_at") is not None:
        world_points.append(temporal["asserted_at"])
    return all(parse_temporal_value(value) <= as_of for value in world_points)


def _record_exclusion(
    excluded: dict[str, list[str]],
    reason: str,
    assertion: CandidateAssertion,
) -> None:
    excluded.setdefault(reason, []).append(assertion.candidate_assertion_id)


__all__ = ["CandidateTemporalView", "build_candidate_temporal_view"]
