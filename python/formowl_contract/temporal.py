"""Small temporal-evidence contract used by candidate assertions.

This is intentionally a POC contract. It gives heterogeneous Domain Packs one
shared temporal vocabulary without introducing canonical graph writes or a
full temporal reasoner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .primitives import ContractValidationError, JsonValue, to_plain

TEMPORAL_INSTANT_FIELDS = (
    "phenomenon_time",
    "captured_at",
    "source_created_at",
    "source_modified_at",
    "observed_at",
    "asserted_at",
    "effective_at",
    "result_time",
    "recorded_at",
    "due_at",
    "superseded_at",
)
TEMPORAL_INTERVAL_FIELDS = (
    "valid_from",
    "valid_to",
    "recorded_from",
    "recorded_to",
)
TEMPORAL_METADATA_FIELDS = (
    "timezone",
    "precision",
    "raw_time_expression",
    "normalization_rule",
    "uncertainty",
)
TEMPORAL_CONTEXT_FIELDS = frozenset(
    (*TEMPORAL_INSTANT_FIELDS, *TEMPORAL_INTERVAL_FIELDS, *TEMPORAL_METADATA_FIELDS)
)


@dataclass(frozen=True)
class TemporalContext:
    """Normalized temporal qualifiers for an observation-backed assertion."""

    phenomenon_time: str | None = None
    captured_at: str | None = None
    source_created_at: str | None = None
    source_modified_at: str | None = None
    observed_at: str | None = None
    asserted_at: str | None = None
    effective_at: str | None = None
    result_time: str | None = None
    recorded_at: str | None = None
    due_at: str | None = None
    superseded_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    recorded_from: str | None = None
    recorded_to: str | None = None
    timezone: str | None = None
    precision: str | None = None
    raw_time_expression: str | None = None
    normalization_rule: str | None = None
    uncertainty: float | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, JsonValue] | None) -> "TemporalContext":
        context = dict(value or {})
        unexpected = set(context).difference(TEMPORAL_CONTEXT_FIELDS)
        if unexpected:
            raise ContractValidationError(
                "TemporalContext contains unsupported fields: " + ", ".join(sorted(unexpected))
            )
        for field_name in (*TEMPORAL_INSTANT_FIELDS, *TEMPORAL_INTERVAL_FIELDS):
            field_value = context.get(field_name)
            if field_value is not None:
                parse_temporal_value(field_value, f"TemporalContext.{field_name}")
        for field_name in (
            "timezone",
            "precision",
            "raw_time_expression",
            "normalization_rule",
        ):
            field_value = context.get(field_name)
            if field_value is not None and (
                not isinstance(field_value, str) or not field_value.strip()
            ):
                raise ContractValidationError(
                    f"TemporalContext.{field_name} must contain non-whitespace text"
                )
        uncertainty = context.get("uncertainty")
        if uncertainty is not None:
            if isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float)):
                raise ContractValidationError("TemporalContext.uncertainty must be numeric")
            if not 0 <= float(uncertainty) <= 1:
                raise ContractValidationError("TemporalContext.uncertainty must be between 0 and 1")
            context["uncertainty"] = float(uncertainty)
        _validate_interval(context, "valid_from", "valid_to")
        _validate_interval(context, "recorded_from", "recorded_to")
        _validate_order(context, "source_created_at", "source_modified_at")
        _validate_order(context, "asserted_at", "superseded_at")
        return cls(**context)

    def to_dict(self) -> dict[str, JsonValue]:
        return to_plain(self)


def normalize_temporal_context(
    value: Mapping[str, JsonValue] | None,
    *,
    temporal_roles: Mapping[str, str] | None = None,
) -> dict[str, JsonValue]:
    """Map domain-specific time labels into the shared temporal vocabulary."""

    source = dict(value or {})
    roles = dict(temporal_roles or {})
    unexpected_role_targets = set(roles.values()).difference(TEMPORAL_CONTEXT_FIELDS)
    if unexpected_role_targets:
        raise ContractValidationError(
            "Domain Pack temporal roles must target TemporalContext fields"
        )
    normalized: dict[str, JsonValue] = {}
    for source_field, field_value in source.items():
        target_field = roles.get(source_field, source_field)
        if target_field not in TEMPORAL_CONTEXT_FIELDS:
            raise ContractValidationError(
                f"temporal field {source_field!r} has no canonical TemporalContext mapping"
            )
        if target_field in normalized:
            raise ContractValidationError(
                f"multiple temporal fields map to TemporalContext.{target_field}"
            )
        normalized[target_field] = field_value
    return TemporalContext.from_dict(normalized).to_dict()


def parse_temporal_value(value: Any, field_name: str = "temporal value") -> datetime:
    """Parse an ISO date or timestamp into a comparable UTC datetime."""

    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be an ISO date or timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be an ISO date or timestamp") from exc
    if ("T" in value or " " in value) and parsed.tzinfo is None:
        raise ContractValidationError(f"{field_name} timestamp must include an explicit UTC offset")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_interval(context: Mapping[str, JsonValue], start: str, end: str) -> None:
    _validate_order(context, start, end)


def _validate_order(context: Mapping[str, JsonValue], start: str, end: str) -> None:
    if context.get(start) is None or context.get(end) is None:
        return
    start_value = parse_temporal_value(context[start], f"TemporalContext.{start}")
    end_value = parse_temporal_value(context[end], f"TemporalContext.{end}")
    if end_value < start_value:
        raise ContractValidationError(f"TemporalContext.{end} must not precede {start}")


__all__ = [
    "TEMPORAL_CONTEXT_FIELDS",
    "TEMPORAL_INSTANT_FIELDS",
    "TEMPORAL_INTERVAL_FIELDS",
    "TEMPORAL_METADATA_FIELDS",
    "TemporalContext",
    "normalize_temporal_context",
    "parse_temporal_value",
]
