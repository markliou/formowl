from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Sequence

from formowl_contract import (
    CandidateAtom,
    CandidateRelation,
    ContractValidationError,
    Observation,
    SemanticMetadata,
    now_iso,
    stable_candidate_atom_id,
    stable_candidate_relation_id,
    stable_semantic_metadata_id,
)
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore, SemanticMetadataStore

from .evidence import MailEvidenceRecord, build_mail_evidence_pack

_MARKERS = {
    "update": "status_update",
    "status": "status_update",
    "blocker": "blocker",
    "owner": "responsible_party",
    "responsible": "responsible_party",
    "next action": "next_action",
    "action item": "next_action",
    "deadline": "deadline",
    "decision": "decision",
    "risk": "risk",
}
_RAW_REFERENCE = re.compile(
    r"(^|[\s'\"])(/|[A-Za-z]:[\\/]|\\\\|file://|s3://|smb://|nfs://|" r"postgres(?:ql)?://)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MailCandidateBridgeResult:
    semantic_metadata: list[SemanticMetadata] = field(default_factory=list)
    candidate_atoms: list[CandidateAtom] = field(default_factory=list)
    candidate_relations: list[CandidateRelation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def extract_mail_semantics_and_candidates(
    observations: Sequence[Observation],
    *,
    extractor_run_id: str,
    created_at: str | None = None,
) -> MailCandidateBridgeResult:
    _validate_id(extractor_run_id, "extractor_run_id")
    resolved_created_at = created_at or now_iso()
    pack = build_mail_evidence_pack(observations, created_at=resolved_created_at)
    semantic_metadata: list[SemanticMetadata] = []
    candidate_atoms: list[CandidateAtom] = []
    candidate_relations: list[CandidateRelation] = []
    warnings = list(pack.warnings)
    thread_atoms: dict[str, CandidateAtom] = {}

    for record in pack.records:
        if record.thread_id:
            thread_atoms.setdefault(
                record.thread_id,
                _thread_atom(
                    record=record,
                    extractor_run_id=extractor_run_id,
                    created_at=resolved_created_at,
                ),
            )
        for source_observation_id, atom_type, label, source_line in _marked_items(record):
            value = _semantic_value(record=record, atom_type=atom_type, label=label)
            semantic = _semantic_metadata(
                source_observation_id=source_observation_id,
                metadata_type=atom_type,
                value=value,
                extractor_run_id=extractor_run_id,
                created_at=resolved_created_at,
            )
            atom = _candidate_atom(
                source_observation_id=source_observation_id,
                semantic_metadata_id=semantic.semantic_metadata_id,
                atom_type=atom_type,
                label=label,
                record=record,
                source_line=source_line,
                extractor_run_id=extractor_run_id,
                created_at=resolved_created_at,
            )
            semantic_metadata.append(semantic)
            candidate_atoms.append(atom)
            if record.thread_id:
                candidate_relations.append(
                    _candidate_relation_to_thread(
                        source_atom=atom,
                        target_atom=thread_atoms[record.thread_id],
                        source_observation_id=source_observation_id,
                        semantic_metadata_id=semantic.semantic_metadata_id,
                        extractor_run_id=extractor_run_id,
                        created_at=resolved_created_at,
                    )
                )

    candidate_atoms = [*thread_atoms.values(), *candidate_atoms]
    if not semantic_metadata:
        warnings.append("no_mail_semantic_markers")
    return MailCandidateBridgeResult(
        semantic_metadata=semantic_metadata,
        candidate_atoms=candidate_atoms,
        candidate_relations=candidate_relations,
        warnings=warnings,
    )


def extract_and_store_mail_candidates(
    observations: Sequence[Observation],
    *,
    semantic_metadata_store: SemanticMetadataStore,
    candidate_atom_store: CandidateAtomStore,
    candidate_relation_store: CandidateRelationStore,
    extractor_run_id: str,
    created_at: str | None = None,
) -> MailCandidateBridgeResult:
    result = extract_mail_semantics_and_candidates(
        observations,
        extractor_run_id=extractor_run_id,
        created_at=created_at,
    )
    validated_semantics = [
        SemanticMetadata.from_dict(item.to_dict()) for item in result.semantic_metadata
    ]
    validated_atoms = [CandidateAtom.from_dict(item.to_dict()) for item in result.candidate_atoms]
    validated_relations = [
        CandidateRelation.from_dict(item.to_dict()) for item in result.candidate_relations
    ]

    for semantic in validated_semantics:
        semantic_metadata_store.validate_semantic_metadata_id(semantic.semantic_metadata_id)
    for atom in validated_atoms:
        candidate_atom_store.validate_candidate_atom_id(atom.candidate_atom_id)
    for relation in validated_relations:
        candidate_relation_store.validate_candidate_relation_id(relation.candidate_relation_id)

    for semantic in validated_semantics:
        semantic_metadata_store.create(semantic)
    for atom in validated_atoms:
        candidate_atom_store.create(atom)
    for relation in validated_relations:
        candidate_relation_store.create(relation)

    return MailCandidateBridgeResult(
        semantic_metadata=validated_semantics,
        candidate_atoms=validated_atoms,
        candidate_relations=validated_relations,
        warnings=list(result.warnings),
    )


def _marked_items(record: MailEvidenceRecord) -> list[tuple[str, str, str, str]]:
    items: list[tuple[str, str, str, str]] = []
    for segment in record.body_segments:
        for line in segment.text.splitlines():
            marker = _parse_marker_line(line)
            if marker is None:
                continue
            atom_type, label = marker
            _validate_public_label(label)
            items.append((segment.observation_id, atom_type, label, line.strip()))
    return items


def _parse_marker_line(line: str) -> tuple[str, str] | None:
    marker_text, separator, label = line.partition(":")
    if not separator:
        return None
    atom_type = _MARKERS.get(marker_text.strip().lower())
    if atom_type is None:
        return None
    label = label.strip()
    if not label:
        return None
    return atom_type, label


def _semantic_metadata(
    *,
    source_observation_id: str,
    metadata_type: str,
    value: dict[str, str],
    extractor_run_id: str,
    created_at: str,
) -> SemanticMetadata:
    semantic_metadata_id = stable_semantic_metadata_id(
        source_observation_ids=[source_observation_id],
        metadata_type=metadata_type,
        value=value,
        extractor_run_id=extractor_run_id,
    )
    return SemanticMetadata.from_dict(
        {
            "semantic_metadata_id": semantic_metadata_id,
            "source_observation_ids": [source_observation_id],
            "metadata_type": metadata_type,
            "value": value,
            "confidence": 1.0,
            "extractor_run_id": extractor_run_id,
            "requires_review": True,
            "created_at": created_at,
        }
    )


def _candidate_atom(
    *,
    source_observation_id: str,
    semantic_metadata_id: str,
    atom_type: str,
    label: str,
    record: MailEvidenceRecord,
    source_line: str,
    extractor_run_id: str,
    created_at: str,
) -> CandidateAtom:
    properties = {
        "source": "mail",
        "message_id": record.message_id,
        "thread_id": record.thread_id,
        "sender": record.sender,
        "sent_at": record.sent_at,
        "source_line": source_line,
    }
    candidate_atom_id = stable_candidate_atom_id(
        source_observation_ids=[source_observation_id],
        atom_type=atom_type,
        label=label,
        properties=properties,
        extractor_run_id=extractor_run_id,
    )
    return CandidateAtom.from_dict(
        {
            "candidate_atom_id": candidate_atom_id,
            "source_observation_ids": [source_observation_id],
            "source_semantic_metadata_ids": [semantic_metadata_id],
            "atom_type": atom_type,
            "label": label,
            "properties": properties,
            "confidence": 1.0,
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "created_at": created_at,
        }
    )


def _thread_atom(
    *,
    record: MailEvidenceRecord,
    extractor_run_id: str,
    created_at: str,
) -> CandidateAtom:
    source_observation_ids = list(record.observation_ids)
    label = record.normalized_subject or record.subject or record.thread_id or "mail thread"
    properties = {
        "source": "mail",
        "thread_id": record.thread_id,
        "mailbox_id": record.mailbox_id,
        "archive_id": record.archive_id,
    }
    candidate_atom_id = stable_candidate_atom_id(
        source_observation_ids=source_observation_ids,
        atom_type="mail_thread",
        label=label,
        properties=properties,
        extractor_run_id=extractor_run_id,
    )
    return CandidateAtom.from_dict(
        {
            "candidate_atom_id": candidate_atom_id,
            "source_observation_ids": source_observation_ids,
            "atom_type": "mail_thread",
            "label": label,
            "properties": properties,
            "confidence": 1.0,
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "created_at": created_at,
        }
    )


def _candidate_relation_to_thread(
    *,
    source_atom: CandidateAtom,
    target_atom: CandidateAtom,
    source_observation_id: str,
    semantic_metadata_id: str,
    extractor_run_id: str,
    created_at: str,
) -> CandidateRelation:
    properties = {"source": "mail", "relation_basis": "same_thread"}
    relation_id = stable_candidate_relation_id(
        source_candidate_atom_id=source_atom.candidate_atom_id,
        target_candidate_atom_id=target_atom.candidate_atom_id,
        relation_type="mentioned_in_mail_thread",
        source_observation_ids=[source_observation_id],
        properties=properties,
        extractor_run_id=extractor_run_id,
    )
    return CandidateRelation.from_dict(
        {
            "candidate_relation_id": relation_id,
            "source_candidate_atom_id": source_atom.candidate_atom_id,
            "target_candidate_atom_id": target_atom.candidate_atom_id,
            "relation_type": "mentioned_in_mail_thread",
            "source_observation_ids": [source_observation_id],
            "source_semantic_metadata_ids": [semantic_metadata_id],
            "properties": properties,
            "confidence": 1.0,
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "created_at": created_at,
        }
    )


def _semantic_value(record: MailEvidenceRecord, *, atom_type: str, label: str) -> dict[str, str]:
    value = {
        "source": "mail",
        "category": atom_type,
        "label": label,
        "message_id": record.message_id,
    }
    for key, item in (
        ("thread_id", record.thread_id),
        ("sender", record.sender),
        ("sent_at", record.sent_at),
        ("subject", record.subject),
    ):
        if item:
            value[key] = item
    return value


def _validate_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")


def _validate_public_label(value: str) -> None:
    if _RAW_REFERENCE.search(value):
        raise ContractValidationError(
            "mail candidate labels must not contain raw paths or locators"
        )


__all__ = [
    "MailCandidateBridgeResult",
    "extract_and_store_mail_candidates",
    "extract_mail_semantics_and_candidates",
]
