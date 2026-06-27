from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from formowl_contract import (
    ContractValidationError,
    SourceRef,
    stable_resource_contract_id,
    to_plain,
)

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAW_REFERENCE_BOUNDARY = r"(^|[\s'\"(\[{=:,])"
_RELATIVE_PATH_PREFIXES = (
    "assets",
    "customer",
    "data",
    "docs",
    "files",
    "home",
    "mnt",
    "nas",
    "private",
    "raw",
    "root",
    "scratch",
    "secret",
    "secrets",
    "share",
    "srv",
    "tmp",
    "workspace",
)
_RAW_PUBLIC_REFERENCE_PATTERNS = (
    re.compile(_RAW_REFERENCE_BOUNDARY + r"\\\\[A-Za-z0-9_.-]+\\"),
    re.compile(r"(^|[^A-Za-z])[A-Za-z]:[\\/]"),
    re.compile(_RAW_REFERENCE_BOUNDARY + r"/(?!/)(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+"),
    re.compile(
        _RAW_REFERENCE_BOUNDARY + r"(?!https?:[\\/]{2})"
        r"\.{1,2}[\\/]+"
        r"[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*",
    ),
    re.compile(
        _RAW_REFERENCE_BOUNDARY
        + r"(?!https?:[\\/]{2})(?:"
        + "|".join(_RELATIVE_PATH_PREFIXES)
        + r")[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*",
        re.IGNORECASE,
    ),
    re.compile(
        _RAW_REFERENCE_BOUNDARY + r"(?!https?:[\\/]{2})"
        r"[A-Za-z0-9_.-]+[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*"
        r"\.[A-Za-z0-9]{2,8}\b",
    ),
    re.compile(r"(^|[\s'\"])/(srv|home|tmp|var|mnt|opt|root)/", re.IGNORECASE),
    re.compile(r"\b(?!https?://)[A-Za-z][A-Za-z0-9+.-]*://", re.IGNORECASE),
    re.compile(r"\b(file|smb|nfs|postgres|postgresql|mysql|sqlite)://", re.IGNORECASE),
    re.compile(r"\bformowl://(asset|object|storage|worker|evidence)\b", re.IGNORECASE),
    re.compile(r"\b(select|with|copy|insert|update|delete|drop|alter)\b\s+", re.IGNORECASE),
)
_RECORD_KINDS = {"atom", "entity", "relation"}
_EVENT_TYPES = {"split", "merge", "archive", "deprecate", "supersede", "equivalence"}
_RESOLUTION_STATUSES = {
    "current",
    "split",
    "merged",
    "archived",
    "deprecated",
    "superseded",
    "equivalent",
}


@dataclass(frozen=True)
class CanonicalLifecycleEvent:
    lifecycle_event_id: str
    record_kind: str
    event_type: str
    scope_type: str
    scope_id: str
    previous_ids: list[str]
    target_ids: list[str]
    canonical_graph_revision_id: str
    ontology_revision_id: str
    lifecycle_policy_id: str
    review_decision_ids: list[str]
    created_at: str
    created_by: str
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    evidence_snapshot_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalLifecycleEvent":
        event = dict(value)
        _validate_event_payload(event)
        return cls(
            lifecycle_event_id=str(event["lifecycle_event_id"]),
            record_kind=str(event["record_kind"]),
            event_type=str(event["event_type"]),
            scope_type=str(event["scope_type"]),
            scope_id=str(event["scope_id"]),
            previous_ids=list(event["previous_ids"]),
            target_ids=list(event["target_ids"]),
            canonical_graph_revision_id=str(event["canonical_graph_revision_id"]),
            ontology_revision_id=str(event["ontology_revision_id"]),
            lifecycle_policy_id=str(event["lifecycle_policy_id"]),
            review_decision_ids=list(event["review_decision_ids"]),
            created_at=str(event["created_at"]),
            created_by=str(event["created_by"]),
            source_refs=[dict(item) for item in event.get("source_refs", [])],
            evidence_snapshot_ids=list(event.get("evidence_snapshot_ids", [])),
            metadata=dict(event.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        _validate_event_payload(data)
        return data


@dataclass(frozen=True)
class CanonicalLifecycleResolution:
    record_kind: str
    requested_id: str
    resolution_status: str
    current_ids: list[str]
    lifecycle_event_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        _validate_record_kind(self.record_kind)
        _validate_record_id(self.requested_id, "requested_id")
        _validate_resolution_status(self.resolution_status)
        _validate_record_id_sequence(self.current_ids, "current_ids", allow_empty=False)
        _validate_record_id_sequence(
            self.lifecycle_event_ids,
            "lifecycle_event_ids",
            allow_empty=True,
        )
        return data


class CanonicalLifecycleStore:
    """File-backed lifecycle event store.

    Lifecycle events are mappings. They preserve old canonical ids instead of
    rewriting records in place.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir) / "graph" / "canonical-lifecycle-events"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_event(self, lifecycle_event_id: str) -> CanonicalLifecycleEvent | None:
        path = self._record_path(lifecycle_event_id)
        if not path.exists():
            return None
        return CanonicalLifecycleEvent.from_dict(_read_json(path))

    def list_events(self) -> list[CanonicalLifecycleEvent]:
        return [
            CanonicalLifecycleEvent.from_dict(_read_json(path))
            for path in sorted(self.base_dir.glob("*.json"))
        ]

    def _persist_reviewed_event(self, event: CanonicalLifecycleEvent) -> CanonicalLifecycleEvent:
        validated = CanonicalLifecycleEvent.from_dict(event.to_dict())
        payload = validated.to_dict()
        path = self._record_path(validated.lifecycle_event_id)
        original = path.read_bytes() if path.exists() else None
        if original is not None:
            if json.loads(original.decode("utf-8")) == payload:
                return validated
            raise ContractValidationError("lifecycle event id already exists")
        _reject_conflicting_previous_ids(validated, self.list_events())
        _write_json(path, payload)
        return validated

    def _record_path(self, lifecycle_event_id: str) -> Path:
        _validate_record_id(lifecycle_event_id, "lifecycle_event_id")
        return self.base_dir / f"{lifecycle_event_id}.json"


def record_canonical_lifecycle_event(
    *,
    lifecycle_store: CanonicalLifecycleStore,
    record_kind: str,
    event_type: str,
    scope_type: str,
    scope_id: str,
    previous_ids: Sequence[str],
    target_ids: Sequence[str] = (),
    canonical_graph_revision_id: str,
    ontology_revision_id: str,
    lifecycle_policy_id: str,
    review_decision_ids: Sequence[str],
    created_by: str,
    created_at: str,
    source_refs: Sequence[dict[str, Any] | SourceRef] = (),
    evidence_snapshot_ids: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> CanonicalLifecycleEvent:
    _validate_iso_timestamp(created_at, "created_at")
    previous = _validate_record_id_sequence(previous_ids, "previous_ids", allow_empty=False)
    targets = _validate_record_id_sequence(target_ids, "target_ids", allow_empty=True)
    _validate_record_kind(record_kind)
    _validate_event_type(event_type)
    _validate_record_id(scope_type, "scope_type")
    _validate_record_id(scope_id, "scope_id")
    _validate_record_id(canonical_graph_revision_id, "canonical_graph_revision_id")
    _validate_record_id(ontology_revision_id, "ontology_revision_id")
    _validate_record_id(lifecycle_policy_id, "lifecycle_policy_id")
    _validate_record_id(created_by, "created_by")
    review_ids = _validate_record_id_sequence(
        review_decision_ids,
        "review_decision_ids",
        allow_empty=False,
    )
    evidence_ids = _validate_record_id_sequence(
        evidence_snapshot_ids,
        "evidence_snapshot_ids",
        allow_empty=True,
    )
    if metadata is not None and not isinstance(metadata, Mapping):
        raise ContractValidationError("metadata must be an object")
    _validate_lifecycle_shape(event_type, previous, targets)
    payload = {
        "lifecycle_event_id": stable_resource_contract_id(
            "life",
            "CanonicalLifecycleEvent",
            {
                "record_kind": record_kind,
                "event_type": event_type,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "previous_ids": previous,
                "target_ids": targets,
                "canonical_graph_revision_id": canonical_graph_revision_id,
                "ontology_revision_id": ontology_revision_id,
                "lifecycle_policy_id": lifecycle_policy_id,
                "review_decision_ids": review_ids,
                "created_at": created_at,
            },
        ),
        "record_kind": record_kind,
        "event_type": event_type,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "previous_ids": previous,
        "target_ids": targets,
        "canonical_graph_revision_id": canonical_graph_revision_id,
        "ontology_revision_id": ontology_revision_id,
        "lifecycle_policy_id": lifecycle_policy_id,
        "review_decision_ids": review_ids,
        "created_at": created_at,
        "created_by": created_by,
        "source_refs": [to_plain(item) for item in source_refs],
        "evidence_snapshot_ids": evidence_ids,
        "metadata": dict(metadata or {}),
    }
    event = CanonicalLifecycleEvent.from_dict(payload)
    _validate_no_raw_public_reference(event.to_dict(), "canonical lifecycle event")
    return lifecycle_store._persist_reviewed_event(event)


def resolve_canonical_lifecycle_id(
    *,
    lifecycle_store: CanonicalLifecycleStore,
    record_kind: str,
    canonical_id: str,
) -> CanonicalLifecycleResolution:
    _validate_record_kind(record_kind)
    _validate_record_id(canonical_id, "canonical_id")
    events_by_previous_id: dict[str, CanonicalLifecycleEvent] = {}
    for event in lifecycle_store.list_events():
        if event.record_kind != record_kind:
            continue
        for previous_id in event.previous_ids:
            events_by_previous_id[previous_id] = event

    current_ids: list[str] = []
    event_ids: list[str] = []
    statuses: list[str] = []
    stack = [canonical_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop(0)
        if current in seen:
            continue
        seen.add(current)
        event = events_by_previous_id.get(current)
        if event is None:
            current_ids.append(current)
            continue
        if event.lifecycle_event_id not in event_ids:
            event_ids.append(event.lifecycle_event_id)
        statuses.append(_resolution_status(event.event_type))
        if event.event_type == "archive" or not event.target_ids:
            current_ids.append(current)
            continue
        stack.extend(event.target_ids)

    status = statuses[-1] if statuses else "current"
    return CanonicalLifecycleResolution(
        record_kind=record_kind,
        requested_id=canonical_id,
        resolution_status=status,
        current_ids=sorted(set(current_ids)),
        lifecycle_event_ids=event_ids,
    )


def _validate_event_payload(event: dict[str, Any]) -> None:
    required = (
        "lifecycle_event_id",
        "record_kind",
        "event_type",
        "scope_type",
        "scope_id",
        "previous_ids",
        "target_ids",
        "canonical_graph_revision_id",
        "ontology_revision_id",
        "lifecycle_policy_id",
        "review_decision_ids",
        "created_at",
        "created_by",
    )
    for field_name in required:
        if field_name not in event:
            raise ContractValidationError(f"CanonicalLifecycleEvent.{field_name} is required")
    _validate_record_id(event["lifecycle_event_id"], "lifecycle_event_id")
    _validate_record_kind(event["record_kind"])
    _validate_event_type(event["event_type"])
    _validate_record_id(event["scope_type"], "scope_type")
    _validate_record_id(event["scope_id"], "scope_id")
    previous = _validate_record_id_sequence(
        event["previous_ids"],
        "previous_ids",
        allow_empty=False,
    )
    targets = _validate_record_id_sequence(event["target_ids"], "target_ids", allow_empty=True)
    _validate_lifecycle_shape(event["event_type"], previous, targets)
    for field_name in (
        "canonical_graph_revision_id",
        "ontology_revision_id",
        "lifecycle_policy_id",
        "created_by",
    ):
        _validate_record_id(event[field_name], field_name)
    _validate_record_id_sequence(
        event["review_decision_ids"],
        "review_decision_ids",
        allow_empty=False,
    )
    _validate_iso_timestamp(event["created_at"], "created_at")
    if not isinstance(event.get("source_refs", []), list):
        raise ContractValidationError("source_refs must be a list")
    for source_ref in event.get("source_refs", []):
        SourceRef.from_dict(to_plain(source_ref))
    _validate_record_id_sequence(
        event.get("evidence_snapshot_ids", []),
        "evidence_snapshot_ids",
        allow_empty=True,
    )
    if not isinstance(event.get("metadata", {}), dict):
        raise ContractValidationError("metadata must be an object")
    _validate_no_raw_public_reference(event, "canonical lifecycle event")


def _validate_lifecycle_shape(
    event_type: str, previous_ids: list[str], target_ids: list[str]
) -> None:
    if set(previous_ids) & set(target_ids):
        raise ContractValidationError("lifecycle previous and target ids must be distinct")
    if event_type == "split" and not (len(previous_ids) == 1 and len(target_ids) >= 2):
        raise ContractValidationError(
            "split lifecycle event requires one previous id and two targets"
        )
    if event_type == "merge" and not (len(previous_ids) >= 2 and len(target_ids) == 1):
        raise ContractValidationError(
            "merge lifecycle event requires multiple previous ids and one target"
        )
    if event_type == "archive" and target_ids:
        raise ContractValidationError("archive lifecycle event cannot have target ids")
    if event_type == "deprecate" and target_ids:
        raise ContractValidationError("deprecate lifecycle event cannot have target ids")
    if event_type == "supersede" and not (len(previous_ids) == 1 and len(target_ids) == 1):
        raise ContractValidationError(
            "supersede lifecycle event requires one previous id and one target"
        )
    if event_type == "equivalence" and not (len(previous_ids) == 1 and len(target_ids) == 1):
        raise ContractValidationError(
            "equivalence lifecycle event requires one previous id and one target"
        )


def _reject_conflicting_previous_ids(
    event: CanonicalLifecycleEvent,
    existing_events: Sequence[CanonicalLifecycleEvent],
) -> None:
    previous = set(event.previous_ids)
    for existing in existing_events:
        if existing.record_kind != event.record_kind:
            continue
        if previous & set(existing.previous_ids):
            raise ContractValidationError("canonical lifecycle previous id already has an event")
    _reject_lifecycle_cycles(event, existing_events)


def _reject_lifecycle_cycles(
    event: CanonicalLifecycleEvent,
    existing_events: Sequence[CanonicalLifecycleEvent],
) -> None:
    edges: dict[str, set[str]] = {}
    for existing in existing_events:
        if existing.record_kind != event.record_kind:
            continue
        for previous_id in existing.previous_ids:
            edges.setdefault(previous_id, set()).update(existing.target_ids)
    for previous_id in event.previous_ids:
        edges.setdefault(previous_id, set()).update(event.target_ids)

    blocked_targets = set(event.previous_ids)
    stack = list(event.target_ids)
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        if current in blocked_targets:
            raise ContractValidationError("canonical lifecycle mappings must be acyclic")
        seen.add(current)
        stack.extend(edges.get(current, set()))


def _resolution_status(event_type: str) -> str:
    return {
        "split": "split",
        "merge": "merged",
        "archive": "archived",
        "deprecate": "deprecated",
        "supersede": "superseded",
        "equivalence": "equivalent",
    }[event_type]


def _validate_record_id_sequence(
    value: Sequence[str],
    field_name: str,
    *,
    allow_empty: bool,
) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field_name} must be a sequence")
    values = list(value)
    if not allow_empty and not values:
        raise ContractValidationError(f"{field_name} cannot be empty")
    for item in values:
        _validate_record_id(item, f"{field_name} entry")
    if len(set(values)) != len(values):
        raise ContractValidationError(f"{field_name} entries must be unique")
    return values


def _validate_record_kind(value: Any) -> None:
    if value not in _RECORD_KINDS:
        raise ContractValidationError("record_kind is not supported")


def _validate_event_type(value: Any) -> None:
    if value not in _EVENT_TYPES:
        raise ContractValidationError("event_type is not supported")


def _validate_resolution_status(value: Any) -> None:
    if value not in _RESOLUTION_STATUSES:
        raise ContractValidationError("resolution_status is not supported")


def _validate_record_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or not _SAFE_RECORD_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a stable record id")


def _validate_iso_timestamp(value: Any, field_name: str) -> None:
    from datetime import datetime

    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc


def _validate_no_raw_public_reference(value: Any, field_name: str) -> None:
    if isinstance(value, str):
        for pattern in _RAW_PUBLIC_REFERENCE_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError(f"{field_name} must not contain raw references")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_no_raw_public_reference(str(key), field_name)
            _validate_no_raw_public_reference(item, field_name)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _validate_no_raw_public_reference(item, field_name)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


__all__ = [
    "CanonicalLifecycleEvent",
    "CanonicalLifecycleResolution",
    "CanonicalLifecycleStore",
    "record_canonical_lifecycle_event",
    "resolve_canonical_lifecycle_id",
]
