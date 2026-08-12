from __future__ import annotations

from dataclasses import dataclass, field, replace
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import base64
import binascii
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
from html.parser import HTMLParser
import io
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence
import unicodedata
import uuid
import quopri
import weakref
import zipfile
from xml.etree import ElementTree as ET

from formowl_contract import (
    ContractValidationError,
    Observation,
    SourceInventory,
    SourceInventoryItem,
    StructuralCell,
    StructuralColumn,
    StructuralObservation,
    StructuralRow,
    assert_no_public_raw_references,
    now_iso,
    sha256_json,
    stable_observation_id,
    stable_resource_contract_id,
    to_plain,
)

from ...extraction import ExtractionInput, ExtractionResult
from .fixture import _normalize_subject

_PST_MIME_TYPES = [
    "application/vnd.ms-outlook",
    "application/vnd.ms-outlook-pst",
    "application/vnd.ms-pst",
    "application/x-pst",
]
_PST_HEADER = b"!BDN"
_PST_MESSAGE_LIMIT_FAILURE_CODE = "pst_parser_message_limit_reached"
_PST_EXPORT_SYMLINK_FAILURE_CODE = "pst_export_symlink_unsupported"
_PST_EXPORT_PATH_ESCAPE_FAILURE_CODE = "pst_export_path_escape"
PST_READPST_PARALLEL_JOBS = frozenset({1, 2, 4})
_SAFE_HEADER_NAMES = {
    "message-id",
    "subject",
    "from",
    "to",
    "cc",
    "date",
    "received",
    "in-reply-to",
    "references",
}


@dataclass(frozen=True)
class _ParserCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


_ParserRunner = Callable[[Sequence[str], int], _ParserCommandResult]


@dataclass(frozen=True)
class PstReadpstMessageSelector:
    """One fail-closed historical-message selector for an exported PST message.

    The selector intentionally binds parser-stable fields that existed in the
    prior mail observation model.  It never carries a source path or body
    text, and multiplicity is explicit so duplicate messages cannot silently
    collapse into one selected export file.
    """

    selector_id: str
    message_id: str
    folder_path_hash: str
    body_hash: str
    expected_occurrence_count: int = 1

    def __post_init__(self) -> None:
        for field_name in (
            "selector_id",
            "message_id",
            "folder_path_hash",
            "body_hash",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"PST selector {field_name} is invalid")
        if (
            not isinstance(self.expected_occurrence_count, int)
            or isinstance(self.expected_occurrence_count, bool)
            or self.expected_occurrence_count < 1
        ):
            raise ContractValidationError("PST selector occurrence count is invalid")


@dataclass(frozen=True)
class PstReadpstSelectionResult:
    """Safe accounting from one exported-message selection scan."""

    selected_message_paths: tuple[str, ...]
    scanned_message_count: int
    matched_occurrence_count: int
    unmatched_selector_count: int
    overmatched_selector_count: int
    warnings: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.unmatched_selector_count == 0 and self.overmatched_selector_count == 0


@dataclass(frozen=True)
class PstReadpstExportResult:
    """Result of exactly one ``readpst`` archive traversal into a checkpoint."""

    export_root: Path
    invoked_readpst: bool


@dataclass(frozen=True)
class _ExportedTraversalUnit:
    source_local_key: str
    parent_source_local_key: str
    path: Path | None
    structure_kind: str
    failure_code: str | None = None
    canonical_relative_components: tuple[bytes, ...] | None = None


@dataclass(frozen=True)
class _ExportedTraversal:
    export_root: Path
    units: tuple[_ExportedTraversalUnit, ...]

    @property
    def failures(self) -> tuple[_ExportedTraversalUnit, ...]:
        return tuple(unit for unit in self.units if unit.failure_code is not None)

    @property
    def error_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(unit.failure_code for unit in self.failures))


_TraversalProvider = Callable[[Path], _ExportedTraversal]


@dataclass(frozen=True)
class _ParsedAttachment:
    attachment_id: str
    filename: str
    mime_type: str | None = None
    content_hash: str | None = None
    size_bytes: int | None = None
    extracted_text_segments: list[str] = field(default_factory=list)
    text_extraction_state: str = "not_text"
    processing_state: str = "parsed"
    failure_code: str | None = None
    embedded_message: EmailMessage | None = None
    source_local_key: str | None = None
    source_kind: str = "mime"
    text: str | None = field(default=None, repr=False, compare=False)
    source_name_fingerprint: str | None = None
    source_char_count: int | None = None
    stored_char_count: int = 0


@dataclass(frozen=True)
class _AttachmentClassification:
    processing_state: str
    text_extraction_state: str
    payload: bytes | None
    text: str | None
    extracted_text_segments: list[str]
    failure_code: str | None = None
    embedded_message: EmailMessage | None = None


@dataclass(frozen=True)
class _MimePartMetadata:
    content_type: str
    content_disposition: str | None
    filename: str | None
    is_multipart: bool
    children: tuple[EmailMessage, ...]
    failure_fields: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return bool(self.failure_fields)


@dataclass(frozen=True)
class _ParsedBodySegment:
    text: str
    char_start: int
    char_end: int
    content_publicly_unsafe: bool = False
    segment_index: int = 0


@dataclass(frozen=True)
class _BodyLeafClassification:
    content_type: str
    processing_state: str
    text: str | None
    failure_code: str | None = None


@dataclass(frozen=True)
class _ChronologyOccurrence:
    kind: str
    header_ordinal: int
    physical_ordinal: int
    kind_ordinal: int
    raw_value_fingerprint: str
    parse_status: str
    timezone_status: str
    normalized_instant: str | None
    safe_error_code: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "header_ordinal": self.header_ordinal,
            "physical_ordinal": self.physical_ordinal,
            "kind_ordinal": self.kind_ordinal,
            "raw_value_fingerprint": self.raw_value_fingerprint,
            "parse_status": self.parse_status,
            "timezone_status": self.timezone_status,
            "normalized_instant": self.normalized_instant,
            "safe_error_code": self.safe_error_code,
        }


@dataclass(frozen=True)
class _MessageChronology:
    date_state: str
    occurrences: tuple[_ChronologyOccurrence, ...]
    date_occurrences: tuple[_ChronologyOccurrence, ...]
    received_occurrences: tuple[_ChronologyOccurrence, ...]
    authored_sent_at: str | None
    parser_defect: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "date_state": self.date_state,
            "occurrences": [item.to_payload() for item in self.occurrences],
            "date_occurrences": [item.to_payload() for item in self.date_occurrences],
            "received_occurrences": [item.to_payload() for item in self.received_occurrences],
            "authored_sent_at": self.authored_sent_at,
            "parser_defect": self.parser_defect,
        }


@dataclass(frozen=True)
class _ReplyHeaderOccurrence:
    kind: str
    header_ordinal: int
    occurrence_ordinal: int
    raw_value_fingerprint: str
    parse_status: str
    token_fingerprints: tuple[str, ...]
    tokens: tuple[str, ...] = field(default=(), repr=False, compare=False)
    safe_error_code: str | None = None

    @property
    def token_count(self) -> int:
        return len(self.token_fingerprints)

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "header_ordinal": self.header_ordinal,
            "occurrence_ordinal": self.occurrence_ordinal,
            "raw_value_fingerprint": self.raw_value_fingerprint,
            "parse_status": self.parse_status,
            "identifier_fingerprints": list(self.token_fingerprints),
            "identifier_count": len(self.token_fingerprints),
            "safe_error_code": self.safe_error_code,
        }


@dataclass(frozen=True)
class _ReplyResolution:
    header_kind: str
    header_ordinal: int | None
    occurrence_ordinal: int | None
    identifier_ordinal: int | None
    identifier_fingerprint: str | None
    raw_value_fingerprint: str | None
    parse_state: str
    parse_complete: bool
    resolution_state: str
    reason_code: str
    resolver_scope: tuple[str, str]
    parse_reason_code: str | None = None
    resolution_reason_code: str | None = None
    blocking_header_kind: str | None = None
    blocking_header_ordinal: int | None = None
    blocking_reason_code: str | None = None
    source_message_id_fingerprint: str | None = None
    target_logical_message_key: str | None = None
    target_occurrence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        parse_states = {"missing", "empty", "malformed", "overflow", "multiple", "parsed"}
        resolution_states = {"resolved", "rejected", "heuristic"}
        reason_codes = {
            "source_message_id_missing",
            "source_message_id_valid",
            "parsed",
            "multiple_headers",
            "empty",
            "malformed",
            "multiple_identifiers",
            "overflow",
            "ancestry_references_multiple_headers",
            "ancestry_in_reply_to_multiple_headers",
            "ancestry_reference_empty",
            "ancestry_in_reply_to_multiple_identifiers",
            "ancestry_headers_disagree",
            "target_absent_current_scope",
            "target_duplicate_conflict",
            "target_self_reference",
            "target_cycle",
            "target_resolved_unique_same_scope",
            "no_authoritative_ancestry_header",
            "ancestry_resolution_blocked_by_source_message_id",
            "ancestry_resolution_blocked_by_incomplete_companion_header",
        }
        resolution_reason_codes = {
            "ancestry_resolution_blocked_by_source_message_id",
            "ancestry_resolution_blocked_by_incomplete_companion_header",
            "ancestry_headers_disagree",
            "target_absent_current_scope",
            "target_duplicate_conflict",
            "target_self_reference",
            "target_cycle",
            "target_resolved_unique_same_scope",
        }
        if self.parse_reason_code is None:
            object.__setattr__(self, "parse_reason_code", self.reason_code)
        if self.parse_state not in parse_states or self.resolution_state not in resolution_states:
            raise ContractValidationError("PST reply resolution state is invalid")
        if self.reason_code not in reason_codes:
            raise ContractValidationError("PST reply resolution reason is invalid")
        if self.parse_reason_code not in reason_codes:
            raise ContractValidationError("PST reply parse reason is invalid")
        if self.resolution_reason_code not in resolution_reason_codes | {None}:
            raise ContractValidationError("PST reply resolution reason is invalid")
        _pst_exact_bool(self.parse_complete, "reply resolution parse completeness")
        if self.parse_complete != (self.parse_state == "parsed"):
            raise ContractValidationError("PST reply resolution completeness is invalid")
        if self.identifier_fingerprint is None and self.identifier_ordinal is not None:
            raise ContractValidationError("PST reply resolution identifier is invalid")
        if self.identifier_fingerprint is not None and (
            self.identifier_ordinal is None or self.identifier_ordinal < 1
        ):
            raise ContractValidationError("PST reply resolution identifier is invalid")
        if len(self.resolver_scope) != 2 or not all(self.resolver_scope):
            raise ContractValidationError("PST reply resolution scope is invalid")
        blocking_resolution_reasons = {
            "ancestry_resolution_blocked_by_source_message_id",
            "ancestry_resolution_blocked_by_incomplete_companion_header",
            "ancestry_headers_disagree",
        }
        if self.resolution_reason_code not in blocking_resolution_reasons and any(
            value is not None
            for value in (
                self.blocking_header_kind,
                self.blocking_header_ordinal,
                self.blocking_reason_code,
            )
        ):
            raise ContractValidationError("PST reply resolution blocker is invalid")
        if self.resolution_reason_code in blocking_resolution_reasons and (
            self.blocking_header_kind is None or self.blocking_reason_code is None
        ):
            raise ContractValidationError("PST reply resolution blocker is incomplete")

    def to_payload(self) -> dict[str, Any]:
        return {
            "header_kind": self.header_kind,
            "header_ordinal": self.header_ordinal,
            "occurrence_ordinal": self.occurrence_ordinal,
            "identifier_ordinal": self.identifier_ordinal,
            "identifier_fingerprint": self.identifier_fingerprint,
            "raw_value_fingerprint": self.raw_value_fingerprint,
            "parse_state": self.parse_state,
            "parse_complete": self.parse_complete,
            "resolution_state": self.resolution_state,
            "reason_code": self.reason_code,
            "parse_reason_code": self.parse_reason_code,
            "resolution_reason_code": self.resolution_reason_code,
            "blocking_header_kind": self.blocking_header_kind,
            "blocking_header_ordinal": self.blocking_header_ordinal,
            "blocking_reason_code": self.blocking_reason_code,
            "resolver_scope": {
                "archive_id": self.resolver_scope[0],
                "mailbox_id": self.resolver_scope[1],
            },
            "source_message_id_fingerprint": self.source_message_id_fingerprint,
            "target_logical_message_key": self.target_logical_message_key,
            "target_occurrence_ids": list(self.target_occurrence_ids),
        }


@dataclass(frozen=True)
class _SafeHeaderOccurrence:
    header_name: str
    header_ordinal: int
    header_value: str | None = None
    raw_value_fingerprint: str | None = None
    chronology: _ChronologyOccurrence | None = None
    reply: _ReplyHeaderOccurrence | None = None


@dataclass(frozen=True)
class _ParsedMessage:
    folder_path_hash: str
    folder_label: str
    message_id: str
    subject: str
    normalized_subject: str
    sender: str
    sent_at: str | None
    headers: tuple[_SafeHeaderOccurrence, ...]
    chronology: _MessageChronology
    body_segments: list[_ParsedBodySegment]
    body_hash: str
    source_body_char_count: int | None
    stored_body_char_count: int
    body_evidence_state: str
    body_projection_state: str
    body_projection_fingerprint: str
    header_projection_count: int
    header_projection_fingerprint: str
    body_failure_codes: tuple[str, ...]
    body_redacted_segment_count: int
    unresolved_attachment_count: int
    attachments: list[_ParsedAttachment]
    reply_headers: tuple[_ReplyHeaderOccurrence, ...] = ()
    references: list[str] = field(default_factory=list)
    in_reply_to: str | None = None
    embedded_messages: tuple["_ParsedMessage", ...] = ()
    embedded_attachment_ordinal: int | None = None
    source_local_key: str | None = None
    raw_message: EmailMessage | None = field(default=None, repr=False, compare=False)


def _attachment_is_unresolved(attachment: _ParsedAttachment) -> bool:
    """Return the canonical message-summary unresolved attachment predicate."""

    return attachment.text_extraction_state in {"unsupported", "failed", "too_large"}


@dataclass(frozen=True)
class _MailMessageContext:
    message: _ParsedMessage
    archive_id: str
    mailbox_id: str
    message_fingerprint: str
    occurrence_id: str
    occurrence_lineage: tuple[str, ...]
    duplicate_ordinal: int
    parent_occurrence_id: str | None = None
    parent_attachment_id: str | None = None


@dataclass(frozen=True)
class _PstAttachmentInventoryIndex:
    item_by_key: Mapping[str, SourceInventoryItem]
    attachment_items: tuple[SourceInventoryItem, ...]
    attachment_items_by_id: Mapping[Any, tuple[SourceInventoryItem, ...]]
    attachment_items_by_id_and_ordinal: Mapping[
        tuple[Any, Any],
        tuple[SourceInventoryItem, ...],
    ]
    attachment_items_by_parent_message_key: Mapping[str, tuple[SourceInventoryItem, ...]]
    message_key_by_occurrence_id: Mapping[str, str]


@dataclass
class _PstExtractionLookupContext:
    """Call-local indexes shared by PST parsing and inventory construction."""

    traversal: _ExportedTraversal
    parent_units_by_components: Mapping[
        tuple[bytes, ...],
        tuple[_ExportedTraversalUnit, ...],
    ]
    parsed_messages_by_source_key: dict[str, _ParsedMessage] = field(default_factory=dict)
    parsed_message_positions_by_source_key: dict[str, int] = field(default_factory=dict)
    sidecar_parent_candidates_by_source_key: dict[
        str,
        tuple[_ExportedTraversalUnit, ...] | None,
    ] = field(default_factory=dict)
    _bound_parsed_messages: Sequence[_ParsedMessage] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @classmethod
    def for_traversal(cls, traversal: _ExportedTraversal) -> "_PstExtractionLookupContext":
        candidates_by_components: dict[
            tuple[bytes, ...],
            list[_ExportedTraversalUnit],
        ] = {}
        for unit in traversal.units:
            components = unit.canonical_relative_components
            if unit.path is None or components is None:
                continue
            candidates_by_components.setdefault(components, []).append(unit)
        return cls(
            traversal=traversal,
            parent_units_by_components={
                components: tuple(candidates)
                for components, candidates in candidates_by_components.items()
            },
        )

    def bind_parsed_messages(self, parsed_messages: Sequence[_ParsedMessage]) -> None:
        if self._bound_parsed_messages is parsed_messages:
            return
        self.parsed_messages_by_source_key.clear()
        self.parsed_message_positions_by_source_key.clear()
        for position, message in enumerate(parsed_messages):
            source_local_key = message.source_local_key
            if source_local_key is None:
                continue
            self.parsed_messages_by_source_key[source_local_key] = message
            self.parsed_message_positions_by_source_key[source_local_key] = position
        self._bound_parsed_messages = parsed_messages

    def sidecar_parent_candidates(
        self,
        unit: _ExportedTraversalUnit,
        *,
        parent_components: tuple[bytes, ...] | None,
    ) -> tuple[_ExportedTraversalUnit, ...] | None:
        source_local_key = unit.source_local_key
        if source_local_key in self.sidecar_parent_candidates_by_source_key:
            return self.sidecar_parent_candidates_by_source_key[source_local_key]
        if parent_components is None:
            candidates = None
        else:
            candidates = self.parent_units_by_components.get(parent_components, ())
        self.sidecar_parent_candidates_by_source_key[source_local_key] = candidates
        return candidates


def _pst_lookup_context_for_traversal(
    traversal: _ExportedTraversal,
    lookup_context: _PstExtractionLookupContext | None = None,
) -> _PstExtractionLookupContext:
    if lookup_context is None:
        return _PstExtractionLookupContext.for_traversal(traversal)
    if lookup_context.traversal is not traversal:
        raise ContractValidationError("PST lookup context traversal binding is invalid")
    return lookup_context


@dataclass(frozen=True)
class _PstParserConfig:
    max_messages: int | None
    timeout_seconds: int
    max_message_file_bytes: int
    body_segment_max_chars: int
    max_body_segments_per_message: int | None
    max_attachment_hash_bytes: int
    max_attachment_text_bytes: int
    preserve_private_body_text: bool
    include_deleted_items: bool
    parser_workers: int


PST_INVENTORY_CARRIER_OBSERVATION_TYPE = "pst_source_inventory_carrier"
PST_INVENTORY_CARRIER_MODALITY = "mail"
PST_INVENTORY_CARRIER_VERSION = 1
PST_SOURCE_UNIT_OBSERVATION_TYPE = "pst_source_unit"
PST_SOURCE_UNIT_OBSERVATION_VERSION = 2
_PST_INVENTORY_POLICY_ID = "formowl_pst_source_inventory_v1"
_PST_INVENTORY_POLICY_VERSION = 37
_PST_TRAVERSAL_BINDING_POLICY = "formowl_pst_traversal_binding_v2"
_PST_STRUCTURAL_CELL_OCCUPANCY_POLICY = "formowl_pst_structural_cell_occupancy_v3"
_PST_STRUCTURAL_CELL_NORMALIZATION_POLICY = "formowl_pst_structural_cell_normalization_casefold_v1"
_PST_MAX_EMBEDDED_MESSAGE_DEPTH = 4
_PST_REPLY_HEADER_MAX_TOKENS = 64
_PST_EXPORTER_MODE = "readpst_separate"
_PST_MESSAGE_FINGERPRINT_POLICY = "formowl_mail_fingerprint_v1"
_PST_MESSAGE_OCCURRENCE_IDENTITY_POLICY = "formowl_pst_message_occurrence_content_v2"
_PST_REPLY_RESOLUTION_POLICY = "formowl_mail_reply_resolution_evidence_v1"
_PST_FOLDER_LABEL_BINDING_POLICY = "formowl_pst_folder_label_binding_v1"
_PST_BODY_PROJECTION_POLICY = "formowl_pst_body_projection_v1"
_PST_BODY_PROJECTION_STATES = frozenset(
    {"bodyless_empty", "decoded_empty", "complete", "partial", "failed", "truncated", "redacted"}
)
_PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE = "pst_source_unit_text_unencodable"
_PST_TEXT_UNENCODABLE_FAILURE_CODE = "text_unencodable"
_PST_HEADER_PROJECTION_POLICY = "formowl_pst_header_projection_v2"
_PST_TEXT_DECODING_POLICY = "explicit_declared_charset_no_guessing_v2"
_PST_MIME_METADATA_ACCESS_POLICY = "bounded_safe_mime_metadata_snapshot_v1"
_PST_MIME_METADATA_FAILURE_CODE = "mime_metadata_access_failed"
_PST_MIME_CONTENT_ACCESS_FAILURE_CODE = "mime_content_access_failed"
_PST_XLSX_MIME_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel.sheet.macroenabled.12",
    }
)
_PST_XLSX_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_PST_XLSX_MAX_ARCHIVE_ENTRIES = 512
_PST_XLSX_MAX_WORKSHEETS = 128
_PST_XLSX_MAX_CELLS = 200_000
_PST_XLSX_MAX_COLUMNS = 1_024
_PST_XLSX_CELL_REFERENCE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
_PST_XLSX_RANGE_REFERENCE = re.compile(
    r"^([A-Z]+[1-9][0-9]*):([A-Z]+[1-9][0-9]*)$"
)
_PST_READPST_SIDECAR_CHARSET_POLICY = "no_charset_authority_fail_charset_unknown_v1"
_PST_SEMANTIC_UNAVAILABILITY_CODES = frozenset(
    {
        "charset_unknown",
        "charset_decode_failed",
        "content_decode_failed",
        "transfer_decode_failed",
        _PST_MIME_METADATA_FAILURE_CODE,
        _PST_MIME_CONTENT_ACCESS_FAILURE_CODE,
        _PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE,
        _PST_TEXT_UNENCODABLE_FAILURE_CODE,
        "pst_source_unit_text_unencodable",
        "pst_sidecar_attachment_charset_unknown",
        "pst_sidecar_attachment_decode_failed",
        "embedded_message_parse_failed",
        "embedded_message_transfer_decode_failed",
    }
)
_PST_ORDINAL_MINIMUMS = {
    "table_ordinal": 1,
    "attachment_ordinal": 1,
    "mime_ordinal": 0,
    "current_depth": 0,
    "quoted_depth": 0,
}
_PST_STRUCTURAL_CURRENT_DEPTH = 0
_PST_SOURCE_UNIT_MESSAGE = "message"
_PST_SOURCE_UNIT_ATTACHMENT = "attachment"
_PST_SOURCE_UNIT_SIDECAR = "sidecar"
_PST_SOURCE_UNIT_UNKNOWN = "unknown"
_PST_TRAVERSAL_BINDING_MISSING = object()
_PST_TRAVERSAL_BINDING_REGISTRY: dict[int, tuple[weakref.ReferenceType[Any], object]] = {}


class _PstTextEncodingError(ContractValidationError):
    """Closed extractor error for text that cannot be persisted as UTF-8."""

    code = _PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE


def _pst_strict_utf8_bytes(value: str) -> bytes:
    """Encode untrusted text without replacement or surrogate escaping."""

    if not isinstance(value, str):
        raise ContractValidationError("PST UTF-8 value is not text")
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        raise _PstTextEncodingError(_PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE) from None


def _pst_utf8_byte_count(value: str) -> int:
    return len(_pst_strict_utf8_bytes(value))


def _pst_assert_utf8_safe(value: Any) -> None:
    """Reject untrusted strings that would make a persisted JSON record invalid."""

    if isinstance(value, str):
        _pst_strict_utf8_bytes(value)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _pst_assert_utf8_safe(key)
            _pst_assert_utf8_safe(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _pst_assert_utf8_safe(item)


def _pst_safe_text(value: Any) -> str | None:
    """Return persistable text, never a surrogate-containing approximation."""

    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = str(value)
        except Exception:
            return None
    try:
        _pst_strict_utf8_bytes(text)
    except _PstTextEncodingError:
        return None
    return text


def _pst_opaque_text_commitment(value: Any) -> str:
    """Return a deterministic private-value commitment without serializing it."""

    if isinstance(value, str):
        try:
            encoded = value.encode("utf-8", "strict")
        except UnicodeEncodeError:
            try:
                encoded = value.encode("utf-8", "surrogateescape")
            except UnicodeEncodeError:
                encoded = (
                    "codepoints:" + ",".join(f"{ord(character):06x}" for character in value)
                ).encode("ascii")
    else:
        encoded = f"non_text:{type(value).__module__}.{type(value).__qualname__}".encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pst_raw_value_fingerprint(value: Any) -> str:
    """Fingerprint a raw field without allowing invalid text into JSON."""

    text = _pst_safe_text(value)
    if text is not None:
        return sha256_json(text)
    return sha256_json(
        {
            "policy": "opaque_unencodable_text_commitment_v1",
            "commitment": _pst_opaque_text_commitment(value),
        }
    )


def _pst_opaque_text_marker(value: Any, field_name: str) -> str:
    """Return a deterministic safe projection for unencodable source text."""

    return (
        f"opaque_{field_name}_" f"{_pst_raw_value_fingerprint(value).removeprefix('sha256:')[-16:]}"
    )


def _pst_safe_header_name(value: Any) -> str | None:
    text = _pst_safe_text(value)
    if text is None:
        return None
    return text.strip().casefold()


def _pst_raw_header_items(message: EmailMessage) -> tuple[tuple[Any, Any], ...]:
    """Read the parser's original header occurrences without propagating access errors."""

    try:
        return tuple(message.raw_items())
    except Exception:
        return ()


def _pst_first_raw_header_value(message: EmailMessage, header_name: str) -> Any | None:
    for name, value in _pst_raw_header_items(message):
        if _pst_safe_header_name(name) == header_name:
            return value
    return None


@dataclass(frozen=True)
class PstExtractionResult(ExtractionResult):
    """Typed PST result carrying the WP1 inventory and structural evidence.

    The generic extraction runner persists ``observations`` as usual.  The
    The reserved carrier observation uses the mail modality required by the
    existing adapter contract, but its reserved observation type keeps parser
    inventory out of ordinary mail evidence projection.
    """

    source_inventory: SourceInventory | None = None
    structural_observations: tuple[StructuralObservation, ...] = ()
    traversal_binding: "PstTraversalBinding | None" = None


@dataclass(frozen=True, init=False)
class PstTraversalBinding:
    """Trusted run-level physical traversal authority for PST rehydration.

    This record is supplied by the trusted job/run owner, not reconstructed
    from a reloaded carrier or observation stream.  WP2 uses it to bind the
    immutable source-unit identity and physical order before accepting any
    persisted inventory or derived observation IDs.
    """

    asset_id: str
    extractor_run_id: str
    source_fingerprint: str
    source_inventory_id: str
    parser_fingerprint: str
    entries: tuple[tuple[str, str, str | None, int, tuple[str, ...]], ...]
    folder_label_bindings: tuple[tuple[str, str, tuple[str, ...]], ...]
    embedded_message_bindings: tuple[tuple[str, str, str, str, int, str, str, str], ...]
    partial_inventory_state: bool
    commitment: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise ContractValidationError("PST traversal binding is runtime-issued")

    def __copy__(self) -> "PstTraversalBinding":
        _pst_assert_issued_traversal_binding(self)
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> "PstTraversalBinding":
        _pst_assert_issued_traversal_binding(self)
        memo[id(self)] = self
        return self

    def __reduce__(self) -> Any:
        raise TypeError("PST traversal binding is runtime-only")

    def __reduce_ex__(self, protocol: int) -> Any:
        del protocol
        raise TypeError("PST traversal binding is runtime-only")


def _pst_traversal_entries(
    inventory: SourceInventory,
) -> tuple[tuple[str, str, str | None, int, tuple[str, ...]], ...]:
    return tuple(
        (
            item.source_inventory_item_id,
            str(item.location["source_local_key"]),
            item.location.get("parent_source_local_key"),
            item.ordinal,
            tuple(item.source_observation_ids),
        )
        for item in sorted(inventory.items, key=lambda item: item.ordinal)
    )


def _pst_traversal_commitment(
    *,
    asset_id: str,
    extractor_run_id: str,
    source_fingerprint: str,
    source_inventory_id: str,
    parser_fingerprint: str,
    entries: Sequence[tuple[str, str, str | None, int, tuple[str, ...]]],
    folder_label_bindings: Sequence[tuple[str, str, tuple[str, ...]]] = (),
    embedded_message_bindings: Sequence[tuple[str, str, str, str, int, str, str, str]] = (),
    partial_inventory_state: bool = False,
) -> str:
    if type(partial_inventory_state) is not bool:
        raise ContractValidationError("PST partial inventory state is invalid")
    return sha256_json(
        {
            "policy": _PST_TRAVERSAL_BINDING_POLICY,
            "asset_id": asset_id,
            "extractor_run_id": extractor_run_id,
            "source_fingerprint": source_fingerprint,
            "source_inventory_id": source_inventory_id,
            "parser_fingerprint": parser_fingerprint,
            "entries": [
                {
                    "source_inventory_item_id": item_id,
                    "source_local_key": source_local_key,
                    "parent_source_local_key": parent_key,
                    "ordinal": ordinal,
                    "source_observation_ids": list(source_ids),
                }
                for item_id, source_local_key, parent_key, ordinal, source_ids in entries
            ],
            "folder_label_bindings": [
                {
                    "policy": _PST_FOLDER_LABEL_BINDING_POLICY,
                    "folder_path_hash": folder_path_hash,
                    "folder_label": folder_label,
                    "source_inventory_item_ids": list(source_inventory_item_ids),
                }
                for folder_path_hash, folder_label, source_inventory_item_ids in folder_label_bindings
            ],
            "embedded_message_bindings": [
                {
                    "parent_attachment_inventory_item_id": parent_attachment_item_id,
                    "attached_message_inventory_item_id": attached_message_item_id,
                    "parent_message_occurrence_id": parent_message_occurrence_id,
                    "parent_attachment_id": parent_attachment_id,
                    "embedded_attachment_ordinal": embedded_attachment_ordinal,
                    "message_occurrence_id": message_occurrence_id,
                    "message_fingerprint": message_fingerprint,
                    "message_id": message_id,
                }
                for (
                    parent_attachment_item_id,
                    attached_message_item_id,
                    parent_message_occurrence_id,
                    parent_attachment_id,
                    embedded_attachment_ordinal,
                    message_occurrence_id,
                    message_fingerprint,
                    message_id,
                ) in embedded_message_bindings
            ],
            "partial_inventory_state": partial_inventory_state,
        }
    )


def _pst_folder_label_bindings_from_observations(
    inventory: SourceInventory,
    observations: Sequence[Observation],
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Capture extraction-time folder labels with their physical message roots."""

    top_level_bindings = _pst_top_level_message_inventory_bindings(inventory)
    source_ids_by_folder: dict[str, set[str]] = {}
    for observation in observations:
        if observation.observation_type != "email_message":
            continue
        payload = observation.payload
        if (
            not isinstance(payload, Mapping)
            or payload.get("parent_message_occurrence_id") is not None
        ):
            continue
        source_local_key = payload.get("message_source_local_key")
        source_inventory_item_id = payload.get("message_source_inventory_item_id")
        folder_path_hash = observation.location.get("folder_path_hash")
        if (
            type(source_local_key) is not str
            or not source_local_key
            or type(source_inventory_item_id) is not str
            or not source_inventory_item_id
            or type(folder_path_hash) is not str
            or not folder_path_hash
        ):
            raise ContractValidationError("PST folder label source binding is invalid")
        inventory_item = top_level_bindings.get(source_local_key)
        if (
            inventory_item is None
            or inventory_item.source_inventory_item_id != source_inventory_item_id
        ):
            raise ContractValidationError("PST folder label inventory binding is invalid")
        source_ids_by_folder.setdefault(folder_path_hash, set()).add(source_inventory_item_id)

    labels_by_folder: dict[str, str] = {}
    for observation in observations:
        if observation.observation_type != "mail_folder_occurrence":
            continue
        payload = observation.payload
        if not isinstance(payload, Mapping):
            raise ContractValidationError("PST folder label payload is invalid")
        folder_path_hash = payload.get("folder_path_hash")
        folder_label = payload.get("folder_label")
        if (
            type(folder_path_hash) is not str
            or not folder_path_hash
            or type(folder_label) is not str
            or not folder_label
            or observation.location.get("folder_path_hash") != folder_path_hash
            or observation.text != folder_label
        ):
            raise ContractValidationError("PST folder label observation is invalid")
        previous = labels_by_folder.setdefault(folder_path_hash, folder_label)
        if previous != folder_label:
            raise ContractValidationError("PST folder labels are inconsistent")

    if set(labels_by_folder) != set(source_ids_by_folder):
        raise ContractValidationError("PST folder label inventory coverage is invalid")
    return tuple(
        (
            folder_path_hash,
            labels_by_folder[folder_path_hash],
            tuple(sorted(source_ids_by_folder[folder_path_hash])),
        )
        for folder_path_hash in sorted(labels_by_folder)
    )


def _pst_embedded_message_bindings_from_observations(
    inventory: SourceInventory,
    observations: Sequence[Observation],
) -> tuple[tuple[str, str, str, str, int, str, str, str], ...]:
    """Issue the canonical child-message binding for every attached message.

    The attached-message inventory item is deliberately not trusted to
    describe its own message content.  At extraction time, bind that item to
    the parent attachment occurrence and the parser-produced child
    ``message_fingerprint``.  The resulting tuple is carried only by the
    extraction-issued traversal authority.
    """

    items_by_id = {item.source_inventory_item_id: item for item in inventory.items}
    items_by_key: dict[str, SourceInventoryItem] = {}
    for item in inventory.items:
        source_local_key = item.location.get("source_local_key")
        if type(source_local_key) is not str or not source_local_key:
            raise ContractValidationError("PST embedded message inventory key is invalid")
        if source_local_key in items_by_key:
            raise ContractValidationError("PST embedded message inventory key is duplicated")
        items_by_key[source_local_key] = item

    attachment_observations: dict[tuple[str, str, int], Observation] = {}
    for observation in observations:
        if observation.observation_type != "email_attachment_occurrence":
            continue
        payload = _pst_observation_payload(observation)
        parent_occurrence_id = payload.get("message_occurrence_id")
        attachment_id = payload.get("attachment_id")
        attachment_ordinal = payload.get("attachment_ordinal")
        inventory_item_id = payload.get("attachment_inventory_item_id")
        inventory_source_local_key = payload.get("attachment_inventory_source_local_key")
        if (
            type(parent_occurrence_id) is not str
            or not parent_occurrence_id
            or type(attachment_id) is not str
            or not attachment_id
            or type(attachment_ordinal) is not int
            or isinstance(attachment_ordinal, bool)
            or attachment_ordinal < 1
            or type(inventory_item_id) is not str
            or not inventory_item_id
            or type(inventory_source_local_key) is not str
            or not inventory_source_local_key
        ):
            raise ContractValidationError("PST embedded parent attachment binding is invalid")
        item = items_by_id.get(inventory_item_id)
        if (
            item is None
            or item.structure_kind
            not in {"regular_attachment_occurrence", "inline_attachment_occurrence"}
            or item.location.get("source_local_key") != inventory_source_local_key
            or item.location.get("attachment_id") != attachment_id
            or item.location.get("attachment_ordinal") != attachment_ordinal
        ):
            raise ContractValidationError("PST embedded parent attachment inventory is invalid")
        key = (parent_occurrence_id, attachment_id, attachment_ordinal)
        if key in attachment_observations:
            raise ContractValidationError("PST embedded parent attachment is duplicated")
        attachment_observations[key] = observation

    bindings: list[tuple[str, str, str, str, int, str, str, str]] = []
    seen_attached_item_ids: set[str] = set()
    for observation in observations:
        if observation.observation_type != "email_message":
            continue
        payload = _pst_observation_payload(observation)
        parent_occurrence_id = payload.get("parent_message_occurrence_id")
        if parent_occurrence_id is None:
            continue
        parent_attachment_id = payload.get("parent_attachment_id")
        embedded_attachment_ordinal = payload.get("embedded_attachment_ordinal")
        message_occurrence_id = payload.get("message_occurrence_id")
        message_id = payload.get("message_id")
        message_fingerprint = payload.get("message_fingerprint")
        if (
            type(parent_occurrence_id) is not str
            or not parent_occurrence_id
            or type(parent_attachment_id) is not str
            or not parent_attachment_id
            or type(embedded_attachment_ordinal) is not int
            or isinstance(embedded_attachment_ordinal, bool)
            or embedded_attachment_ordinal < 1
            or type(message_occurrence_id) is not str
            or not message_occurrence_id
            or type(message_id) is not str
            or not message_id
            or type(message_fingerprint) is not str
            or not message_fingerprint
        ):
            raise ContractValidationError("PST embedded message fingerprint binding is invalid")
        parent_attachment = attachment_observations.get(
            (
                parent_occurrence_id,
                parent_attachment_id,
                embedded_attachment_ordinal,
            )
        )
        if parent_attachment is None:
            raise ContractValidationError("PST embedded parent attachment is missing")
        parent_payload = _pst_observation_payload(parent_attachment)
        parent_attachment_item_id = parent_payload["attachment_inventory_item_id"]
        parent_attachment_source_key = parent_payload["attachment_inventory_source_local_key"]
        attached_message_source_key = f"{parent_attachment_source_key}:message"
        attached_message_item = items_by_key.get(attached_message_source_key)
        if (
            attached_message_item is None
            or attached_message_item.structure_kind != "attached_message_occurrence"
            or attached_message_item.location.get("parent_source_local_key")
            != parent_attachment_source_key
        ):
            raise ContractValidationError("PST attached message inventory is missing")
        attached_message_item_id = attached_message_item.source_inventory_item_id
        if attached_message_item_id in seen_attached_item_ids:
            raise ContractValidationError("PST attached message inventory is duplicated")
        seen_attached_item_ids.add(attached_message_item_id)
        bindings.append(
            (
                parent_attachment_item_id,
                attached_message_item_id,
                parent_occurrence_id,
                parent_attachment_id,
                embedded_attachment_ordinal,
                message_occurrence_id,
                message_fingerprint,
                message_id,
            )
        )

    expected_attached_item_ids = {
        item.source_inventory_item_id
        for item in inventory.items
        if item.structure_kind == "attached_message_occurrence"
    }
    if seen_attached_item_ids != expected_attached_item_ids:
        raise ContractValidationError("PST attached message inventory coverage is invalid")
    return tuple(sorted(bindings, key=lambda binding: binding[1]))


def _issue_pst_traversal_binding(
    inventory: SourceInventory,
    *,
    asset_id: str,
    extractor_run_id: str,
    source_fingerprint: str,
    folder_label_bindings: Sequence[tuple[str, str, tuple[str, ...]]] = (),
    embedded_message_bindings: Sequence[tuple[str, str, str, str, int, str, str, str]] = (),
    partial_inventory_state: bool = False,
) -> PstTraversalBinding:
    """Issue a run-level binding only at extraction time."""

    entries = _pst_traversal_entries(inventory)
    commitment = _pst_traversal_commitment(
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        source_fingerprint=source_fingerprint,
        source_inventory_id=inventory.source_inventory_id,
        parser_fingerprint=inventory.parser_fingerprint,
        entries=entries,
        folder_label_bindings=folder_label_bindings,
        embedded_message_bindings=embedded_message_bindings,
        partial_inventory_state=partial_inventory_state,
    )
    binding = object.__new__(PstTraversalBinding)
    object.__setattr__(binding, "asset_id", asset_id)
    object.__setattr__(binding, "extractor_run_id", extractor_run_id)
    object.__setattr__(binding, "source_fingerprint", source_fingerprint)
    object.__setattr__(binding, "source_inventory_id", inventory.source_inventory_id)
    object.__setattr__(binding, "parser_fingerprint", inventory.parser_fingerprint)
    object.__setattr__(binding, "entries", entries)
    object.__setattr__(binding, "folder_label_bindings", tuple(folder_label_bindings))
    object.__setattr__(
        binding,
        "embedded_message_bindings",
        tuple(embedded_message_bindings),
    )
    object.__setattr__(binding, "partial_inventory_state", partial_inventory_state)
    object.__setattr__(binding, "commitment", commitment)
    capability = object()
    object.__setattr__(binding, "_capability", capability)
    binding_id = id(binding)

    def _forget_binding(
        reference: weakref.ReferenceType[Any],
        *,
        binding_id: int = binding_id,
    ) -> None:
        current = _PST_TRAVERSAL_BINDING_REGISTRY.get(binding_id)
        if current is not None and current[0] is reference:
            _PST_TRAVERSAL_BINDING_REGISTRY.pop(binding_id, None)

    _PST_TRAVERSAL_BINDING_REGISTRY[binding_id] = (
        weakref.ref(binding, _forget_binding),
        capability,
    )
    return binding


def _pst_assert_issued_traversal_binding(
    binding: PstTraversalBinding,
) -> None:
    if type(binding) is not PstTraversalBinding:
        raise ContractValidationError("PST trusted traversal binding is invalid")
    if not all(
        hasattr(binding, field_name)
        for field_name in (
            "entries",
            "folder_label_bindings",
            "embedded_message_bindings",
            "partial_inventory_state",
            "commitment",
        )
    ):
        raise ContractValidationError("PST trusted traversal binding is incomplete")
    registered = _PST_TRAVERSAL_BINDING_REGISTRY.get(id(binding))
    if registered is None or registered[0]() is not binding:
        raise ContractValidationError("PST traversal binding capability is not issued")
    capability = getattr(binding, "_capability", _PST_TRAVERSAL_BINDING_MISSING)
    if registered[1] is not capability:
        raise ContractValidationError("PST traversal binding capability is invalid")


class PstMailArchiveExtractor:
    """Server-side PST adapter that emits FormOwl mail observations.

    The adapter shells out to a configured PST parser command and then parses
    exported RFC822 messages with the Python standard library. Parser paths and
    scratch directories remain internal to the extractor and are never copied
    into observations.
    """

    def __init__(
        self,
        *,
        version: str = "0.2.0",
        parser_command: str = "readpst",
        runner: _ParserRunner | None = None,
        scratch_parent: str | Path | None = None,
        traversal_provider: _TraversalProvider | None = None,
    ) -> None:
        self._version = version
        self._parser_command = parser_command
        self._runner = runner or _run_parser_command
        self._scratch_parent = Path(scratch_parent) if scratch_parent is not None else None
        self._traversal_provider = traversal_provider or _snapshot_export_tree

    def name(self) -> str:
        return "pst_mail_archive_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_PST_MIME_TYPES)

    def extractor_type(self) -> str:
        return "mail_archive"

    def extract(self, extraction_input: ExtractionInput) -> PstExtractionResult:
        extraction_input = replace(
            extraction_input,
            created_at=_pst_canonical_extraction_timestamp(
                extraction_input.created_at,
                allow_missing=True,
            ),
        )
        config = _parser_config(extraction_input.config)
        parser_fingerprint = _pst_parser_fingerprint(
            self,
            config=config,
        )
        if not _looks_like_pst(extraction_input.object_path):
            return _pst_result_with_inventory(
                extraction_input,
                parser_fingerprint=parser_fingerprint,
                processing_state="failed",
                errors=["pst_parser_input_signature_mismatch"],
            )

        scratch_path = _create_scratch_dir(self._scratch_parent)
        try:
            command = _readpst_command(
                self._parser_command,
                extraction_input.object_path,
                scratch_path,
                include_deleted_items=config.include_deleted_items,
            )
            try:
                completed = self._runner(command, config.timeout_seconds)
            except FileNotFoundError:
                return _pst_result_with_inventory(
                    extraction_input,
                    parser_fingerprint=parser_fingerprint,
                    processing_state="failed",
                    errors=["pst_parser_unavailable"],
                )
            except subprocess.TimeoutExpired:
                return _pst_result_with_partial_inventory(
                    scratch_path,
                    extraction_input,
                    parser_fingerprint=parser_fingerprint,
                    processing_state="failed",
                    config=config,
                    errors=["pst_parser_timeout"],
                    traversal_provider=self._traversal_provider,
                )
            if completed.returncode != 0:
                return _pst_result_with_partial_inventory(
                    scratch_path,
                    extraction_input,
                    parser_fingerprint=parser_fingerprint,
                    processing_state="failed",
                    config=config,
                    errors=["pst_parser_failed"],
                    traversal_provider=self._traversal_provider,
                )

            traversal = _safe_traversal_snapshot(
                self._traversal_provider,
                scratch_path,
            )
            try:
                _validate_traversal_source_unit_bindings(traversal)
            except _PstTextEncodingError:
                return _pst_result_with_inventory(
                    extraction_input,
                    parser_fingerprint=parser_fingerprint,
                    processing_state="failed",
                    errors=[_PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE],
                )
            except _PstPathCanonicalizationError:
                return _pst_result_with_inventory(
                    extraction_input,
                    parser_fingerprint=parser_fingerprint,
                    processing_state="failed",
                    errors=["pst_export_component_unencodable"],
                )
            except ContractValidationError:
                return _pst_result_with_inventory(
                    extraction_input,
                    parser_fingerprint=parser_fingerprint,
                    processing_state="failed",
                    errors=["pst_source_unit_identity_collision"],
                )
            lookup_context = _PstExtractionLookupContext.for_traversal(traversal)
            parsed_messages, parse_warnings, source_unit_classifications = _parse_exported_messages(
                traversal,
                config=config,
                lookup_context=lookup_context,
            )
            build_errors: list[str] = []
            source_inventory, structural_observations = _build_pst_inventory(
                traversal.export_root,
                extraction_input=extraction_input,
                parsed_messages=parsed_messages,
                config=config,
                parser_fingerprint=parser_fingerprint,
                warnings=parse_warnings,
                traversal=traversal,
                source_unit_classifications=source_unit_classifications,
                build_errors=build_errors,
                lookup_context=lookup_context,
            )
        finally:
            shutil.rmtree(scratch_path, ignore_errors=True)

        if not parsed_messages:
            return _pst_result(
                extraction_input,
                source_inventory=source_inventory,
                structural_observations=structural_observations,
                warnings=parse_warnings,
                errors=_dedupe_safe_error_codes(
                    ("pst_parser_no_messages",),
                    traversal.error_codes,
                    build_errors,
                ),
            )

        observations = _mail_observations_from_messages(
            parsed_messages,
            extraction_input=extraction_input,
            source_inventory=source_inventory,
        )
        warnings = list(parse_warnings)
        if _message_limit_reached(source_unit_classifications):
            _append_warning_once(warnings, _PST_MESSAGE_LIMIT_FAILURE_CODE)
        return _pst_result(
            extraction_input,
            source_inventory=source_inventory,
            structural_observations=structural_observations,
            mail_observations=observations,
            warnings=warnings,
            errors=_dedupe_safe_error_codes(
                traversal.error_codes,
                build_errors,
            ),
        )


def extract_selected_readpst_export(
    *,
    extraction_input: ExtractionInput,
    export_root: str | Path,
    selected_message_paths: Sequence[str | Path],
    adapter: PstMailArchiveExtractor | None = None,
) -> PstExtractionResult:
    """Parse explicitly selected messages from an existing ``readpst -S`` export.

    This bounded recovery path never invokes ``readpst`` and never enumerates
    the export root.  It validates only the requested regular message files
    and their direct directory lineage, then reuses the normal PST message,
    inventory, structural-observation, and source-unit persistence pipeline.

    The resulting archive inventory is intentionally marked
    ``preserved_unparsed``: the selected messages are useful supplemental
    evidence, not a claim that the full PST export was reprocessed.
    """

    active_adapter = adapter or PstMailArchiveExtractor()
    if not isinstance(active_adapter, PstMailArchiveExtractor):
        raise ContractValidationError("selected readpst export requires a PST extractor")
    normalized_input = replace(
        extraction_input,
        created_at=_pst_canonical_extraction_timestamp(
            extraction_input.created_at,
            allow_missing=True,
        ),
    )
    config = _parser_config(normalized_input.config)
    parser_fingerprint = _pst_parser_fingerprint(active_adapter, config=config)
    traversal = _selected_readpst_export_traversal(
        export_root,
        selected_message_paths=selected_message_paths,
    )
    _validate_traversal_source_unit_bindings(traversal)
    lookup_context = _PstExtractionLookupContext.for_traversal(traversal)
    parsed_messages, warnings, source_unit_classifications = _parse_exported_messages(
        traversal,
        config=config,
        lookup_context=lookup_context,
    )
    build_errors: list[str] = []
    source_inventory, structural_observations = _build_pst_inventory(
        traversal.export_root,
        extraction_input=normalized_input,
        parsed_messages=parsed_messages,
        config=config,
        parser_fingerprint=parser_fingerprint,
        warnings=warnings,
        traversal=traversal,
        source_unit_classifications=source_unit_classifications,
        archive_processing_state="preserved_unparsed",
        build_errors=build_errors,
        lookup_context=lookup_context,
    )
    if not parsed_messages:
        return _pst_result(
            normalized_input,
            source_inventory=source_inventory,
            structural_observations=structural_observations,
            warnings=(*warnings, "pst_selected_export_subset"),
            errors=_dedupe_safe_error_codes(
                ("pst_parser_no_messages",),
                build_errors,
            ),
        )
    observations = _mail_observations_from_messages(
        parsed_messages,
        extraction_input=normalized_input,
        source_inventory=source_inventory,
    )
    if _message_limit_reached(source_unit_classifications):
        _append_warning_once(warnings, _PST_MESSAGE_LIMIT_FAILURE_CODE)
    _append_warning_once(warnings, "pst_selected_export_subset")
    return _pst_result(
        normalized_input,
        source_inventory=source_inventory,
        structural_observations=structural_observations,
        mail_observations=observations,
        allow_partial_inventory=True,
        warnings=warnings,
        errors=_dedupe_safe_error_codes(build_errors),
    )


def extract_readpst_export(
    *,
    extraction_input: ExtractionInput,
    export_root: str | Path,
    adapter: PstMailArchiveExtractor | None = None,
) -> PstExtractionResult:
    """Materialize one complete existing ``readpst -S`` export exactly once.

    This is the fast path only when a trusted archive asset/hash binding proves
    that the export is the complete intended source universe.  It never invokes
    ``readpst`` itself; callers checkpoint that raw-PST traversal separately.
    Directory traversal is canonical and message parsing occurs once before
    inventory/structural observations and the normal bundle are constructed.
    """

    active_adapter = adapter or PstMailArchiveExtractor()
    if not isinstance(active_adapter, PstMailArchiveExtractor):
        raise ContractValidationError("readpst export materialization requires a PST extractor")
    normalized_input = replace(
        extraction_input,
        created_at=_pst_canonical_extraction_timestamp(
            extraction_input.created_at,
            allow_missing=True,
        ),
    )
    config = _parser_config(normalized_input.config)
    parser_fingerprint = _pst_parser_fingerprint(active_adapter, config=config)
    traversal = _safe_traversal_snapshot(_snapshot_export_tree, Path(export_root))
    _validate_traversal_source_unit_bindings(traversal)
    lookup_context = _PstExtractionLookupContext.for_traversal(traversal)
    parsed_messages, warnings, source_unit_classifications = _parse_exported_messages(
        traversal,
        config=config,
        lookup_context=lookup_context,
    )
    build_errors: list[str] = []
    source_inventory, structural_observations = _build_pst_inventory(
        traversal.export_root,
        extraction_input=normalized_input,
        parsed_messages=parsed_messages,
        config=config,
        parser_fingerprint=parser_fingerprint,
        warnings=warnings,
        traversal=traversal,
        source_unit_classifications=source_unit_classifications,
        build_errors=build_errors,
        lookup_context=lookup_context,
    )
    if not parsed_messages:
        return _pst_result(
            normalized_input,
            source_inventory=source_inventory,
            structural_observations=structural_observations,
            warnings=warnings,
            errors=_dedupe_safe_error_codes(
                ("pst_parser_no_messages",),
                traversal.error_codes,
                build_errors,
            ),
        )
    observations = _mail_observations_from_messages(
        parsed_messages,
        extraction_input=normalized_input,
        source_inventory=source_inventory,
    )
    if _message_limit_reached(source_unit_classifications):
        _append_warning_once(warnings, _PST_MESSAGE_LIMIT_FAILURE_CODE)
    return _pst_result(
        normalized_input,
        source_inventory=source_inventory,
        structural_observations=structural_observations,
        mail_observations=observations,
        warnings=warnings,
        errors=_dedupe_safe_error_codes(traversal.error_codes, build_errors),
    )


def export_pst_to_readpst_directory(
    *,
    pst_path: str | Path,
    export_root: str | Path,
    timeout_seconds: int,
    include_deleted_items: bool = False,
    parser_command: str = "readpst",
    parallel_jobs: int = 1,
    runner: _ParserRunner | None = None,
) -> PstReadpstExportResult:
    """Run ``readpst`` once into a caller-owned, empty checkpoint directory.

    ``readpst`` does not expose a message-occurrence selector.  This primitive
    therefore isolates its unavoidable complete archive traversal from the
    later selective materialization.  It intentionally does not delete the
    output: the bridge owner writes a completion checkpoint only after this
    function succeeds, enabling restart without a second PST traversal.
    """

    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
        raise ContractValidationError("PST export timeout is invalid")
    if timeout_seconds < 1:
        raise ContractValidationError("PST export timeout is invalid")
    if parallel_jobs not in PST_READPST_PARALLEL_JOBS:
        raise ContractValidationError("PST export parallel jobs are invalid")
    source = Path(pst_path)
    if not _looks_like_pst(source):
        raise ContractValidationError("PST export input signature is invalid")
    root = Path(export_root)
    if root.is_symlink():
        raise ContractValidationError("PST export checkpoint directory is invalid")
    created = False
    try:
        root.mkdir(parents=True, mode=0o700)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise ContractValidationError("PST export checkpoint directory is invalid") from exc
    if root.is_symlink() or not root.is_dir():
        raise ContractValidationError("PST export checkpoint directory is invalid")
    if any(root.iterdir()):
        raise ContractValidationError("PST export checkpoint directory is not empty")
    if created and os.name != "nt":
        os.chmod(root, 0o700)
    active_runner = runner or _run_parser_command
    command = _readpst_command(
        parser_command,
        source,
        root,
        include_deleted_items=include_deleted_items,
        parallel_jobs=parallel_jobs,
    )
    try:
        completed = active_runner(command, timeout_seconds)
    except FileNotFoundError as exc:
        raise RuntimeError("pst_parser_unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("pst_parser_timeout") from exc
    if completed.returncode != 0:
        raise RuntimeError("pst_parser_failed")
    return PstReadpstExportResult(export_root=root, invoked_readpst=True)


def select_readpst_export_messages(
    *,
    export_root: str | Path,
    selectors: Sequence[PstReadpstMessageSelector],
    extractor_config: Mapping[str, Any] | None = None,
) -> PstReadpstSelectionResult:
    """Find selected messages through one bounded-memory scan of an export.

    This scans the *existing* export once and retains only matching relative
    message paths.  It does not retain bodies, all parsed messages, or a
    whole-export index.  A selector match is exact on message id, canonical
    folder hash, and canonical body hash.  The explicit expected multiplicity
    prevents both missing historical occurrences and accidental duplicate
    matches from becoming a falsely complete structural bundle.
    """

    normalized_selectors = _normalized_readpst_message_selectors(selectors)
    config = _parser_config(dict(extractor_config or {}))
    traversal = _safe_traversal_snapshot(_snapshot_export_tree, Path(export_root))
    _validate_traversal_source_unit_bindings(traversal)
    selector_by_key = {
        _readpst_selector_key(
            message_id=selector.message_id,
            folder_path_hash=selector.folder_path_hash,
            body_hash=selector.body_hash,
        ): selector
        for selector in normalized_selectors
    }
    matched_by_selector_id: dict[str, int] = {
        selector.selector_id: 0 for selector in normalized_selectors
    }
    selected_paths: set[str] = set()
    warnings: list[str] = list(traversal.error_codes)
    scanned_message_count = 0

    for unit in traversal.units:
        if _exported_source_unit_kind(unit) != _PST_SOURCE_UNIT_MESSAGE:
            continue
        candidate = unit.path
        if candidate is None:
            continue
        scanned_message_count += 1
        classifications: dict[str, _PstSourceUnitClassification] = {}
        classification = _source_unit_classification_for_unit(
            unit,
            config=config,
            warnings=warnings,
            source_unit_classifications=classifications,
        )
        warnings.extend(_source_unit_parser_warnings(classification))
        message = classification.message
        if message is None:
            continue
        parsed = _parsed_message_from_email(
            message,
            candidate_path=candidate,
            export_root=traversal.export_root,
            message_index=scanned_message_count,
            config=config,
            warnings=warnings,
            source_local_key=unit.source_local_key,
            folder_components=(
                unit.canonical_relative_components[:-1]
                if unit.canonical_relative_components is not None
                else None
            ),
        )
        if _parsed_message_matches_selector(
            parsed,
            selector_by_key=selector_by_key,
            matched_by_selector_id=matched_by_selector_id,
        ):
            selected_paths.add(candidate.relative_to(traversal.export_root).as_posix())

    unmatched_selector_count = sum(
        matched_by_selector_id[selector.selector_id] < selector.expected_occurrence_count
        for selector in normalized_selectors
    )
    overmatched_selector_count = sum(
        matched_by_selector_id[selector.selector_id] > selector.expected_occurrence_count
        for selector in normalized_selectors
    )
    return PstReadpstSelectionResult(
        selected_message_paths=tuple(sorted(selected_paths)),
        scanned_message_count=scanned_message_count,
        matched_occurrence_count=sum(matched_by_selector_id.values()),
        unmatched_selector_count=unmatched_selector_count,
        overmatched_selector_count=overmatched_selector_count,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _normalized_readpst_message_selectors(
    selectors: Sequence[PstReadpstMessageSelector],
) -> tuple[PstReadpstMessageSelector, ...]:
    normalized = tuple(selectors)
    if not normalized:
        raise ContractValidationError("PST export selection requires selectors")
    if any(not isinstance(item, PstReadpstMessageSelector) for item in normalized):
        raise ContractValidationError("PST export selector is invalid")
    selector_ids = [item.selector_id for item in normalized]
    if len(selector_ids) != len(set(selector_ids)):
        raise ContractValidationError("PST export selector ids are not unique")
    keys = [
        _readpst_selector_key(
            message_id=item.message_id,
            folder_path_hash=item.folder_path_hash,
            body_hash=item.body_hash,
        )
        for item in normalized
    ]
    if len(keys) != len(set(keys)):
        raise ContractValidationError("PST export selectors overlap")
    return tuple(sorted(normalized, key=lambda item: item.selector_id))


def _readpst_selector_key(
    *,
    message_id: str,
    folder_path_hash: str,
    body_hash: str,
) -> str:
    return sha256_json(
        {
            "message_id": message_id,
            "folder_path_hash": folder_path_hash,
            "body_hash": body_hash,
        }
    )


def _parsed_message_matches_selector(
    message: _ParsedMessage,
    *,
    selector_by_key: Mapping[str, PstReadpstMessageSelector],
    matched_by_selector_id: dict[str, int],
) -> bool:
    """Match a full embedded-message tree without retaining parsed export state."""

    matched = False
    pending = [message]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop()
        candidate_identity = id(candidate)
        if candidate_identity in seen:
            continue
        seen.add(candidate_identity)
        pending.extend(reversed(candidate.embedded_messages))
        key = _readpst_selector_key(
            message_id=candidate.message_id,
            folder_path_hash=candidate.folder_path_hash,
            body_hash=candidate.body_hash,
        )
        selector = selector_by_key.get(key)
        if selector is None:
            continue
        matched_by_selector_id[selector.selector_id] += 1
        matched = True
    return matched


def _pst_parser_fingerprint(
    adapter: PstMailArchiveExtractor,
    *,
    config: _PstParserConfig,
) -> str:
    """Return the closed, path-free identity of one PST extraction policy."""

    parser_command_name = Path(adapter._parser_command).name or "parser"
    return sha256_json(
        {
            "policy_id": _PST_INVENTORY_POLICY_ID,
            "policy_version": _PST_INVENTORY_POLICY_VERSION,
            "adapter_name": adapter.name(),
            "adapter_version": adapter.version(),
            "parser_command_identity": hashlib.sha256(
                _pst_strict_utf8_bytes(parser_command_name)
            ).hexdigest(),
            "parser_export_policy": {
                "mode": _PST_EXPORTER_MODE,
                "source_unit_grammar": {
                    "message": "decimal_basename_or_eml_compatibility_v1",
                    "attachment": ("decimal_message_hyphen_nonempty_filename_v1"),
                    "sidecar": "decimal_basename_size_or_type_v1",
                    "unknown": "closed_unsupported",
                    "limit_policy": "message_units_only_no_io_after_quota_v1",
                    "sidecar_evidence": ("linked_decimal_item_count_strict_text_attachment_v1"),
                },
                "preserve_deleted": config.include_deleted_items,
                "preserve_mime_alternatives": True,
                "preserve_html_tables": True,
                "preserve_quote_lineage": True,
                "embedded_message_nesting_limit": _PST_MAX_EMBEDDED_MESSAGE_DEPTH,
                "source_order": {
                    "component_total_order": (
                        "nfc_casefold_utf8_then_nfc_exact_utf8_then_fixed_raw_bytes_v2"
                    ),
                    "relative_identity": "exact_fixed_utf8_surrogateescape_bytes_v2",
                    "invalid_utf8_order": "opaque_raw_bytes_after_valid_utf8_v1",
                    "collision_policy": "fail_closed_before_evidence",
                    "inventory_position": "source_unit_binding_fingerprint_v1",
                    "rehydration_authority": ("trusted_job_expected_source_observation_order_v1"),
                },
                "source_unit_observation": {
                    "version": PST_SOURCE_UNIT_OBSERVATION_VERSION,
                    "traversal_binding": _PST_TRAVERSAL_BINDING_POLICY,
                },
                "folder_identity": {
                    "policy": _PST_FOLDER_IDENTITY_POLICY,
                    "label": "strict_utf8_nfc_or_opaque_fingerprint_v1",
                },
                "structural_transaction": {
                    "structural_inventory_kinds": sorted(_PST_STRUCTURAL_INVENTORY_KINDS),
                    "failure_code": _PST_STRUCTURAL_BUILD_FAILURE_CODE,
                    "bijection": "parsed_item_exactly_one_structural_observation_v1",
                    "cell_occupancy": _PST_STRUCTURAL_CELL_OCCUPANCY_POLICY,
                },
                "body_leaf_decode_policy": {
                    "transfer": "strict_base64_quoted_printable_and_known_cte_v1",
                    "charset": _PST_TEXT_DECODING_POLICY,
                    "recovery": "none_without_explicit_source_codec_evidence_v1",
                    "failure_projection": "shared_inventory_body_and_structure_v1",
                },
                "body_projection_policy": {
                    "policy": _PST_BODY_PROJECTION_POLICY,
                    "state": "bodyless_decoded_partial_failed_truncated_redacted_v1",
                    "fingerprint": (
                        "ordered_safe_segments_ranges_message_state_counts_failures_v1"
                    ),
                },
                "header_projection_policy": {
                    "policy": _PST_HEADER_PROJECTION_POLICY,
                    "unencodable_field": "opaque_commitment_and_unresolved_semantics_v1",
                    "top_level_carrier": "mime_valid_authorized_without_header_heuristic_v1",
                    "ordered_occurrence_fingerprint": "safe_header_variant_payload_v2",
                    "strict_projection_index": "continuous_safe_header_order_v1",
                },
                "mime_metadata_access_policy": {
                    "policy": _PST_MIME_METADATA_ACCESS_POLICY,
                    "failure_code": _PST_MIME_METADATA_FAILURE_CODE,
                    "fallback": "generic_content_type_disposition_and_filename_v1",
                    "exception_boundary": "exception_only_per_accessor_v1",
                },
                "readpst_sidecar_policy": {
                    "media_inference": "closed_filename_extension_v1",
                    "charset": _PST_TEXT_DECODING_POLICY,
                    "charset_authority": _PST_READPST_SIDECAR_CHARSET_POLICY,
                    "embedded_message_from_sidecar": "never",
                    "mapping": "exact_same_directory_decimal_parent_v1",
                    "rehydration": "attachment_inventory_semantic_bijection_v1",
                },
                "chronology_policy": {
                    "date_authority": "exactly_one_offset_aware_parse_without_defect",
                    "duplicate_date_state": "fail_closed",
                    "received_role": "independent_transport_order",
                    "timezone_policy": "explicit_numeric_offset_only",
                    "grammar": "rfc_5322_full_consumption_v1",
                    "received_tail": "top_level_semicolon_full_consumption_v1",
                    "received_domain_literal": "rfc_domain_literal_v1",
                    "domain_literal_quoted_pair": "rfc_vchar_wsp_no_folding_v1",
                },
                "reply_ancestry_policy": {
                    "headers": ("message-id", "references", "in-reply-to"),
                    "grammar": "rfc_msg_id_cfws_full_consumption_v1",
                    "max_tokens": _PST_REPLY_HEADER_MAX_TOKENS,
                    "resolution_policy": _PST_REPLY_RESOLUTION_POLICY,
                    "scope": "archive_mailbox_message_fingerprint_v1",
                    "subject_fallback": "heuristic_only",
                    "version_lineage": "never_populated",
                },
            },
            "limits": {
                "max_messages": config.max_messages,
                "max_message_file_bytes": config.max_message_file_bytes,
                "body_segment_max_chars": config.body_segment_max_chars,
                "max_body_segments_per_message": config.max_body_segments_per_message,
                "max_attachment_hash_bytes": config.max_attachment_hash_bytes,
                "max_attachment_text_bytes": config.max_attachment_text_bytes,
            },
            "preserve_private_body_text": config.preserve_private_body_text,
        }
    )


def _permission_scope_payload(permission_scope: Any) -> dict[str, Any]:
    if hasattr(permission_scope, "to_dict"):
        return dict(permission_scope.to_dict())
    if isinstance(permission_scope, Mapping):
        return dict(permission_scope)
    raise ContractValidationError("PST permission scope is not serializable")


def _pst_source_observation_id(
    *,
    extraction_input: ExtractionInput,
    source_local_key: str,
    traversal_binding_fingerprint: str | None = None,
    source_binding_fingerprint: str | None = None,
) -> str:
    return _pst_source_observation_id_from_fields(
        asset_id=extraction_input.asset.asset_id,
        extractor_run_id=extraction_input.extractor_run_id,
        source_local_key=source_local_key,
        traversal_binding_fingerprint=traversal_binding_fingerprint,
        source_binding_fingerprint=source_binding_fingerprint,
    )


def _pst_source_observation_id_from_fields(
    *,
    asset_id: str,
    extractor_run_id: str,
    source_local_key: str,
    traversal_binding_fingerprint: str | None = None,
    source_binding_fingerprint: str | None = None,
) -> str:
    identity: dict[str, Any] = {
        "asset_id": asset_id,
        "extractor_run_id": extractor_run_id,
        "source_local_key": source_local_key,
    }
    if traversal_binding_fingerprint is not None:
        identity["traversal_binding_fingerprint"] = traversal_binding_fingerprint
    if source_binding_fingerprint is not None:
        identity["source_binding_fingerprint"] = source_binding_fingerprint
    return stable_resource_contract_id(
        "pst-source-observation",
        "PstSourceObservation",
        identity,
    )


def _pst_archive_inventory(
    extraction_input: ExtractionInput,
    *,
    parser_fingerprint: str,
    processing_state: str,
) -> SourceInventory:
    source_local_key = "archive"
    item = _pst_inventory_item(
        extraction_input,
        parser_fingerprint=parser_fingerprint,
        source_local_key=source_local_key,
        ordinal=0,
        structure_kind="archive",
        content_type=extraction_input.asset.mime_type,
        processing_state=processing_state,
        parent_source_local_key=None,
    )
    return SourceInventory.create(
        source_asset_id=extraction_input.asset.asset_id,
        source_fingerprint=extraction_input.asset.content_hash,
        parser_fingerprint=parser_fingerprint,
        items=[item],
        created_at=extraction_input.created_at or now_iso(),
    )


def _pst_result_with_inventory(
    extraction_input: ExtractionInput,
    *,
    parser_fingerprint: str,
    processing_state: str,
    errors: Sequence[str],
) -> PstExtractionResult:
    inventory = _pst_archive_inventory(
        extraction_input,
        parser_fingerprint=parser_fingerprint,
        processing_state=processing_state,
    )
    return _pst_result(
        extraction_input,
        source_inventory=inventory,
        structural_observations=(),
        errors=errors,
    )


def _pst_result_with_partial_inventory(
    export_root: Path,
    extraction_input: ExtractionInput,
    *,
    parser_fingerprint: str,
    processing_state: str,
    config: _PstParserConfig,
    errors: Sequence[str],
    traversal_provider: _TraversalProvider,
) -> PstExtractionResult:
    warnings: list[str] = []
    build_errors: list[str] = []
    source_unit_classifications: dict[str, _PstSourceUnitClassification] = {}
    traversal = _safe_traversal_snapshot(traversal_provider, export_root)
    try:
        _validate_traversal_source_unit_bindings(traversal)
    except _PstTextEncodingError:
        return _pst_result_with_inventory(
            extraction_input,
            parser_fingerprint=parser_fingerprint,
            processing_state="failed",
            errors=(*errors, _PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE),
        )
    except _PstPathCanonicalizationError:
        return _pst_result_with_inventory(
            extraction_input,
            parser_fingerprint=parser_fingerprint,
            processing_state="failed",
            errors=(*errors, "pst_export_component_unencodable"),
        )
    except ContractValidationError:
        return _pst_result_with_inventory(
            extraction_input,
            parser_fingerprint=parser_fingerprint,
            processing_state="failed",
            errors=(*errors, "pst_source_unit_identity_collision"),
        )
    lookup_context = _PstExtractionLookupContext.for_traversal(traversal)
    try:
        (
            parsed_messages,
            warnings,
            source_unit_classifications,
        ) = _parse_exported_messages(
            traversal,
            config=config,
            lookup_context=lookup_context,
        )
    except Exception:
        parsed_messages = []
        build_errors.append("pst_parser_inventory_build_failed")
    try:
        inventory, structural = _build_pst_inventory(
            export_root,
            extraction_input=extraction_input,
            parsed_messages=parsed_messages,
            config=config,
            parser_fingerprint=parser_fingerprint,
            warnings=warnings,
            traversal=traversal,
            source_unit_classifications=source_unit_classifications,
            archive_processing_state=processing_state,
            build_errors=build_errors,
            lookup_context=lookup_context,
        )
    except Exception:
        build_errors.append("pst_parser_inventory_build_failed")
        inventory, structural = _build_pst_inventory_fallback(
            extraction_input,
            parser_fingerprint=parser_fingerprint,
            config=config,
            warnings=warnings,
            traversal=traversal,
            parsed_messages=parsed_messages,
            source_unit_classifications=source_unit_classifications,
            build_errors=build_errors,
            lookup_context=lookup_context,
        )
    mail_observations: Sequence[Observation] = ()
    if parsed_messages:
        try:
            mail_observations = _mail_observations_from_messages(
                parsed_messages,
                extraction_input=extraction_input,
                source_inventory=inventory,
            )
        except Exception:
            build_errors.append("pst_parser_inventory_build_failed")
    return _pst_result(
        extraction_input,
        source_inventory=inventory,
        structural_observations=structural,
        mail_observations=mail_observations,
        allow_partial_inventory=True,
        warnings=warnings,
        errors=_dedupe_safe_error_codes(
            errors,
            traversal.error_codes,
            build_errors,
        ),
    )


def _dedupe_safe_error_codes(*groups: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(code for group in groups for code in group if code))


def _pst_result(
    extraction_input: ExtractionInput,
    *,
    source_inventory: SourceInventory,
    structural_observations: Sequence[StructuralObservation],
    mail_observations: Sequence[Observation] = (),
    allow_partial_inventory: bool = False,
    warnings: Sequence[str] = (),
    errors: Sequence[str] = (),
) -> PstExtractionResult:
    inventory_source_observation_ids = {
        source_observation_id
        for item in source_inventory.items
        for source_observation_id in item.source_observation_ids
    }
    structural_source_observation_ids = {
        structural.source_observation_id for structural in structural_observations
    }
    if not structural_source_observation_ids.issubset(inventory_source_observation_ids):
        raise ContractValidationError(
            "PST structural observation references an unbound source observation"
        )
    source_unit_observations = _pst_source_unit_observations(
        extraction_input,
        source_inventory=source_inventory,
    )
    carrier = _pst_inventory_carrier_observation(
        extraction_input,
        source_inventory=source_inventory,
        structural_observations=tuple(structural_observations),
    )
    if allow_partial_inventory and not mail_observations:
        embedded_message_bindings = ()
    else:
        embedded_message_bindings = _pst_embedded_message_bindings_from_observations(
            source_inventory,
            mail_observations,
        )
    partial_inventory_state = (
        allow_partial_inventory
        and not mail_observations
        and _pst_has_retained_partial_children(source_inventory)
    )
    traversal_binding = _issue_pst_traversal_binding(
        source_inventory,
        asset_id=extraction_input.asset.asset_id,
        extractor_run_id=extraction_input.extractor_run_id,
        source_fingerprint=extraction_input.asset.content_hash,
        folder_label_bindings=_pst_folder_label_bindings_from_observations(
            source_inventory,
            mail_observations,
        ),
        embedded_message_bindings=embedded_message_bindings,
        partial_inventory_state=partial_inventory_state,
    )
    return PstExtractionResult(
        observations=[*mail_observations, *source_unit_observations, carrier],
        warnings=list(warnings),
        errors=list(errors),
        source_inventory=source_inventory,
        structural_observations=tuple(structural_observations),
        traversal_binding=traversal_binding,
    )


def _pst_source_unit_observations(
    extraction_input: ExtractionInput,
    *,
    source_inventory: SourceInventory,
) -> tuple[Observation, ...]:
    """Emit one reserved Observation for every inventory source reference."""

    created_at = extraction_input.created_at or now_iso()
    archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {
            "asset_id": extraction_input.asset.asset_id,
            "archive_sha256": extraction_input.asset.content_hash,
        },
    )
    mailbox_id = stable_resource_contract_id(
        "mailbox",
        "PstMailbox",
        {"asset_id": extraction_input.asset.asset_id},
    )
    observations: list[Observation] = []
    seen_source_observation_ids: set[str] = set()
    for item in source_inventory.items:
        source_local_key = item.location.get("source_local_key")
        if not isinstance(source_local_key, str) or not source_local_key:
            raise ContractValidationError("PST source inventory item lacks a source-local key")
        for source_observation_id in sorted(item.source_observation_ids):
            if source_observation_id in seen_source_observation_ids:
                raise ContractValidationError(
                    "PST source observation is referenced by multiple inventory items"
                )
            seen_source_observation_ids.add(source_observation_id)
            parent_source_local_key = item.location.get("parent_source_local_key")
            traversal_binding = _pst_traversal_binding_fingerprint(
                source_local_key=source_local_key,
                parent_source_local_key=parent_source_local_key,
                ordinal=item.ordinal,
            )
            location = {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "source_inventory_item_id": item.source_inventory_item_id,
                "source_local_key": source_local_key,
                "source_observation_type": PST_SOURCE_UNIT_OBSERVATION_TYPE,
                "source_observation_version": PST_SOURCE_UNIT_OBSERVATION_VERSION,
                "source_traversal_binding_policy": _PST_TRAVERSAL_BINDING_POLICY,
                "source_traversal_ordinal": item.ordinal,
                "source_traversal_binding_fingerprint": traversal_binding,
            }
            payload = {
                "source_observation_type": PST_SOURCE_UNIT_OBSERVATION_TYPE,
                "source_observation_version": PST_SOURCE_UNIT_OBSERVATION_VERSION,
                "source_observation_id": source_observation_id,
                "source_inventory_id": source_inventory.source_inventory_id,
                "source_inventory_item_id": item.source_inventory_item_id,
                "source_local_key": source_local_key,
                "source_fingerprint": item.source_fingerprint,
                "parser_fingerprint": item.parser_fingerprint,
                "processing_state": item.processing_state,
                "raw_retention_state": item.raw_retention_state,
                "source_traversal_binding_policy": _PST_TRAVERSAL_BINDING_POLICY,
                "source_traversal_ordinal": item.ordinal,
                "source_traversal_binding_fingerprint": traversal_binding,
            }
            assert_no_public_raw_references(payload, "pst_source_unit_observation")
            observations.append(
                Observation(
                    observation_id=source_observation_id,
                    asset_id=extraction_input.asset.asset_id,
                    extractor_run_id=extraction_input.extractor_run_id,
                    observation_type=PST_SOURCE_UNIT_OBSERVATION_TYPE,
                    modality=PST_INVENTORY_CARRIER_MODALITY,
                    location=location,
                    confidence=1.0,
                    permission_scope=extraction_input.asset.permission_scope,
                    created_at=created_at,
                    payload=payload,
                )
            )
    return tuple(observations)


def _pst_inventory_carrier_observation(
    extraction_input: ExtractionInput,
    *,
    source_inventory: SourceInventory,
    structural_observations: tuple[StructuralObservation, ...],
) -> Observation:
    created_at = extraction_input.created_at or now_iso()
    archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {
            "asset_id": extraction_input.asset.asset_id,
            "archive_sha256": extraction_input.asset.content_hash,
        },
    )
    mailbox_id = stable_resource_contract_id(
        "mailbox",
        "PstMailbox",
        {"asset_id": extraction_input.asset.asset_id},
    )
    payload = {
        "carrier_type": PST_INVENTORY_CARRIER_OBSERVATION_TYPE,
        "carrier_version": PST_INVENTORY_CARRIER_VERSION,
        "source_inventory": source_inventory.to_persistence_dict(),
        "structural_observations": [
            observation.to_persistence_dict() for observation in structural_observations
        ],
    }
    _validate_pst_inventory_carrier_private_payload(payload)
    location = {
        "archive_id": archive_id,
        "mailbox_id": mailbox_id,
        "carrier_type": PST_INVENTORY_CARRIER_OBSERVATION_TYPE,
        "carrier_version": PST_INVENTORY_CARRIER_VERSION,
    }
    observation_id = stable_observation_id(
        asset_id=extraction_input.asset.asset_id,
        extractor_run_id=extraction_input.extractor_run_id,
        observation_type=PST_INVENTORY_CARRIER_OBSERVATION_TYPE,
        modality=PST_INVENTORY_CARRIER_MODALITY,
        location=location,
        text=None,
        payload=payload,
    )
    return Observation(
        observation_id=observation_id,
        asset_id=extraction_input.asset.asset_id,
        extractor_run_id=extraction_input.extractor_run_id,
        observation_type=PST_INVENTORY_CARRIER_OBSERVATION_TYPE,
        modality=PST_INVENTORY_CARRIER_MODALITY,
        location=location,
        confidence=1.0,
        permission_scope=extraction_input.asset.permission_scope,
        created_at=created_at,
        payload=payload,
    )


def _validate_pst_inventory_carrier_private_payload(payload: Mapping[str, Any]) -> None:
    """Validate the closed private carrier envelope without treating evidence as public.

    Structural rows deliberately retain private evidence values for governed
    persistence and deterministic rehydration.  Public callers must use the
    structural and mail-bundle public projection boundaries instead of this
    internal carrier.
    """

    if not isinstance(payload, Mapping):
        raise ContractValidationError("PST carrier private payload is invalid")
    if set(payload) != {
        "carrier_type",
        "carrier_version",
        "source_inventory",
        "structural_observations",
    }:
        raise ContractValidationError("PST carrier private payload shape is not closed")
    if payload["carrier_type"] != PST_INVENTORY_CARRIER_OBSERVATION_TYPE:
        raise ContractValidationError("PST carrier private payload type is invalid")
    if payload["carrier_version"] != PST_INVENTORY_CARRIER_VERSION:
        raise ContractValidationError("PST carrier private payload version is invalid")
    if not isinstance(payload["source_inventory"], Mapping) or not isinstance(
        payload["structural_observations"], list
    ):
        raise ContractValidationError("PST carrier private payload members are invalid")


def _pst_inventory_item(
    extraction_input: ExtractionInput,
    *,
    parser_fingerprint: str,
    source_local_key: str,
    ordinal: int,
    structure_kind: str,
    content_type: str,
    processing_state: str,
    parent_source_local_key: str | None,
    source_observation_id: str | None = None,
    extra_location: Mapping[str, Any] | None = None,
) -> SourceInventoryItem:
    location: dict[str, Any] = {
        "source_local_key": source_local_key,
        "source_local_key_policy": _PST_INVENTORY_POLICY_ID,
    }
    if parent_source_local_key is not None:
        location["parent_source_local_key"] = parent_source_local_key
    if extra_location:
        location.update(dict(extra_location))
    return SourceInventoryItem.create(
        source_asset_id=extraction_input.asset.asset_id,
        structure_kind=structure_kind,
        content_type=content_type or "application/octet-stream",
        ordinal=ordinal,
        processing_state=processing_state,
        raw_retention_state="retained",
        source_fingerprint=extraction_input.asset.content_hash,
        parser_fingerprint=parser_fingerprint,
        permission_scope=_permission_scope_payload(extraction_input.asset.permission_scope),
        location=location,
        source_observation_ids=([] if source_observation_id is None else [source_observation_id]),
    )


def _inventory_from_specs(
    specs: Sequence[_PstInventorySpec],
    *,
    extraction_input: ExtractionInput,
    parser_fingerprint: str,
) -> SourceInventory:
    items = [
        _pst_inventory_item(
            extraction_input,
            parser_fingerprint=parser_fingerprint,
            source_local_key=spec.source_local_key,
            ordinal=spec.ordinal,
            structure_kind=spec.structure_kind,
            content_type=spec.content_type,
            processing_state=spec.processing_state,
            parent_source_local_key=spec.parent_source_local_key,
            source_observation_id=spec.source_observation_id,
            extra_location=spec.location,
        )
        for spec in specs
    ]
    return SourceInventory.create(
        source_asset_id=extraction_input.asset.asset_id,
        source_fingerprint=extraction_input.asset.content_hash,
        parser_fingerprint=parser_fingerprint,
        items=items,
        created_at=extraction_input.created_at or now_iso(),
    )


def _validate_pst_structural_bijection(
    inventory: SourceInventory,
    structural_observations: Sequence[StructuralObservation],
    *,
    trusted_source_traversal_ordinals: Mapping[str, int] | None = None,
) -> None:
    item_by_id = {item.source_inventory_item_id: item for item in inventory.items}
    item_by_key = {
        str(item.location["source_local_key"]): item
        for item in inventory.items
        if isinstance(item.location.get("source_local_key"), str)
    }
    expected_items = {
        item.source_inventory_item_id
        for item in inventory.items
        if item.structure_kind in _PST_STRUCTURAL_INVENTORY_KINDS
        and item.processing_state == "parsed"
    }
    observed_items: dict[str, StructuralObservation] = {}
    for structural in structural_observations:
        if structural.structure_kind not in _PST_STRUCTURAL_INVENTORY_KINDS:
            raise ContractValidationError("PST structural observation kind is not canonical")
        for field_name in ("current_depth", "quoted_depth", "table_ordinal", "mime_ordinal"):
            _pst_exact_ordinal(getattr(structural, field_name), field_name)
        if structural.attachment_ordinal is not None:
            _pst_exact_ordinal(structural.attachment_ordinal, "attachment_ordinal")
        item = item_by_id.get(structural.source_inventory_item_id)
        if item is None:
            raise ContractValidationError("PST structural observation has orphan membership")
        if structural.current_depth != _PST_STRUCTURAL_CURRENT_DEPTH:
            raise ContractValidationError("PST structural current depth is not canonical")
        if structural.version_lineage != ():
            raise ContractValidationError("PST structural version lineage is not canonical")
        expected_quoted_depth = _pst_structural_quoted_depth_from_inventory(
            item,
            item_by_key=item_by_key,
        )
        inventory_quoted_depth = _pst_exact_int(
            item.location.get("quoted_depth"),
            "inventory structural quoted depth",
            minimum=0,
        )
        if (
            inventory_quoted_depth != expected_quoted_depth
            or structural.quoted_depth != expected_quoted_depth
        ):
            raise ContractValidationError("PST structural quoted depth is not topology-bound")
        if (
            item.structure_kind not in _PST_STRUCTURAL_INVENTORY_KINDS
            or item.processing_state != "parsed"
        ):
            raise ContractValidationError("PST structural item state does not permit evidence")
        inventory_table_ordinal = _pst_exact_ordinal(
            item.location.get("table_ordinal"),
            "table_ordinal",
        )
        if structural.table_ordinal != inventory_table_ordinal:
            raise ContractValidationError("PST structural table ordinal is not inventory-bound")
        inventory_mime_ordinal = _pst_exact_ordinal(
            item.location.get("mime_ordinal"),
            "mime_ordinal",
        )
        if structural.mime_ordinal != inventory_mime_ordinal:
            raise ContractValidationError("PST structural MIME ordinal is not inventory-bound")
        for field_name in ("table_ordinal", "mime_ordinal", "attachment_ordinal"):
            if item.location.get(field_name) is not None:
                _pst_exact_ordinal(item.location[field_name], field_name)
        if structural.source_inventory_item_id in observed_items:
            raise ContractValidationError("PST structural item has duplicate observations")
        observed_items[structural.source_inventory_item_id] = structural
    if set(observed_items) != expected_items:
        raise ContractValidationError("PST structural inventory/observation bijection failed")
    expected_order_items = [
        item
        for item in inventory.items
        if item.structure_kind in _PST_STRUCTURAL_INVENTORY_KINDS
        and item.processing_state == "parsed"
    ]
    order_values: dict[str, int] = {}
    for item in expected_order_items:
        ordinal = (
            item.ordinal
            if trusted_source_traversal_ordinals is None
            else trusted_source_traversal_ordinals.get(item.source_inventory_item_id)
        )
        order_values[item.source_inventory_item_id] = _pst_exact_int(
            ordinal,
            "trusted structural traversal ordinal",
            minimum=0,
        )
    if len(order_values) != len(set(order_values.values())):
        raise ContractValidationError("PST structural inventory order is ambiguous")
    expected_order = [
        item.source_inventory_item_id
        for item in sorted(
            expected_order_items,
            key=lambda candidate: order_values[candidate.source_inventory_item_id],
        )
    ]
    observed_order = [structural.source_inventory_item_id for structural in structural_observations]
    if observed_order != expected_order:
        raise ContractValidationError("PST structural observation order is not canonical")


def _pst_structural_quoted_depth_from_inventory(
    item: SourceInventoryItem,
    *,
    item_by_key: Mapping[str, SourceInventoryItem],
) -> int:
    """Derive a table's quote depth from its immutable inventory topology."""

    if item.structure_kind not in _PST_STRUCTURAL_INVENTORY_KINDS:
        raise ContractValidationError("PST structural quote-depth item kind is invalid")
    source_local_key = item.location.get("source_local_key")
    if type(source_local_key) is not str or not source_local_key:
        raise ContractValidationError("PST structural quote-depth source key is invalid")
    parent_key = item.location.get("parent_source_local_key")
    if type(parent_key) is not str or not parent_key:
        raise ContractValidationError("PST structural quote-depth parent is missing")

    quote_depths: list[int] = []
    seen: set[str] = {source_local_key}
    while True:
        if parent_key in seen:
            raise ContractValidationError("PST structural quote topology is cyclic")
        seen.add(parent_key)
        parent = item_by_key.get(parent_key)
        if parent is None:
            raise ContractValidationError("PST structural quote parent is missing")
        if parent.structure_kind != "quote_forwarded_structure":
            break
        quote_depth = _pst_exact_int(
            parent.location.get("quote_depth"),
            "inventory quote depth",
            minimum=1,
        )
        quote_depths.append(quote_depth)
        parent_key = parent.location.get("parent_source_local_key")
        if type(parent_key) is not str or not parent_key:
            raise ContractValidationError("PST structural quote parent is missing")

    if not quote_depths:
        return 0
    expected_depths = set(range(1, len(quote_depths) + 1))
    if set(quote_depths) != expected_depths or quote_depths[0] != len(quote_depths):
        raise ContractValidationError("PST structural quote topology is invalid")
    return len(quote_depths)


def _pst_structural_cell_occupancy_fingerprint(
    rows: Sequence[Mapping[str, Any]],
    *,
    column_count: int,
    columns: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
) -> str:
    """Fingerprint one table's topology and canonical cell content.

    The digest is a trusted extraction binding, not a replacement for the
    structural validator.  In particular, populated values are included so a
    carrier cannot replace structural evidence while keeping the topology
    self-consistent.  Blank and absent cells explicitly bind both value fields
    to ``None``.
    """

    if type(column_count) is not int or isinstance(column_count, bool) or column_count < 0:
        raise ContractValidationError("PST structural column count is invalid")
    canonical_columns = []
    for expected_column_ordinal, column in enumerate(columns):
        column_mapping = _require_mapping(column, "PST structural column")
        canonical_columns.append(
            {
                "column_ordinal": column_mapping.get("column_ordinal"),
                "original_header": column_mapping.get("original_header"),
                "normalized_header": column_mapping.get("normalized_header"),
            }
        )
        if column_mapping.get("column_ordinal") != expected_column_ordinal:
            raise ContractValidationError("PST structural column projection is not ordered")
    canonical_relationships = []
    for relationship in relationships:
        canonical_relationships.append(
            dict(_require_mapping(relationship, "PST structural header relationship"))
        )
    canonical_rows = []
    for expected_row_ordinal, row in enumerate(rows):
        if isinstance(row, Mapping):
            row_mapping = row
            row_ordinal = row_mapping.get("row_ordinal")
            raw_cells = row_mapping.get("cells")
            if type(raw_cells) is not list:
                raise ContractValidationError("PST structural row cells are invalid")
        else:
            row_ordinal = expected_row_ordinal
            if type(row) is not list:
                raise ContractValidationError("PST structural row cells are invalid")
            raw_cells = row
        canonical_cells = []
        for cell in raw_cells:
            cell_mapping = _require_mapping(cell, "PST structural cell")
            canonical_cells.append(
                {
                    "column_ordinal": cell_mapping.get("column_ordinal"),
                    "cell_state": cell_mapping.get("cell_state"),
                    "row_span": cell_mapping.get("row_span"),
                    "column_span": cell_mapping.get("column_span"),
                    "value": cell_mapping.get("value"),
                    "normalized_value": cell_mapping.get("normalized_value"),
                }
            )
        canonical_rows.append(
            {
                "row_ordinal": row_ordinal,
                "cells": canonical_cells,
            }
        )
    projection = {
        "policy": _PST_STRUCTURAL_CELL_OCCUPANCY_POLICY,
        "normalization_policy": _PST_STRUCTURAL_CELL_NORMALIZATION_POLICY,
        "column_count": column_count,
        "columns": canonical_columns,
        "header_relationships": canonical_relationships,
        "rows": canonical_rows,
    }
    _pst_assert_utf8_safe(projection)
    return sha256_json(projection)


def _pst_structural_column_projection(table: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    headers = _require_mapping(table.get("headers"), "PST structural table headers")
    max_column = _pst_exact_int(
        table.get("max_column"),
        "PST structural table column count",
        minimum=0,
    )
    columns = []
    for column_ordinal in range(max_column):
        original_header = headers.get(column_ordinal)
        if original_header is not None and type(original_header) is not str:
            raise ContractValidationError("PST structural original header is invalid")
        columns.append(
            {
                "column_ordinal": column_ordinal,
                "original_header": original_header,
                "normalized_header": (original_header.casefold() if original_header else None),
            }
        )
    return tuple(columns)


def _pst_canonical_structural_observation_id(
    structural: Mapping[str, Any],
) -> str:
    """Derive a structural ID through the same WP1 canonical constructor."""

    values = {key: value for key, value in structural.items() if key != "structural_observation_id"}
    return StructuralObservation.create(**values).structural_observation_id


def _pst_validate_structural_header_relationships(
    relationships: Any,
    *,
    rows: Any,
    columns: Any,
    expected_cell_occupancy_fingerprint: str | None = None,
) -> None:
    """Validate canonical table header relationships before WP1 reconstruction."""

    if type(relationships) is not list:
        raise ContractValidationError("PST structural header relationships must be a list")
    if type(rows) is not list or type(columns) is not list:
        raise ContractValidationError("PST structural table topology is invalid")
    relationship_keys = {
        "header_row_ordinal",
        "header_column_ordinal",
        "column_ordinal",
        "header_text",
        "relationship",
        "scope",
        "row_span",
        "column_span",
    }
    row_cells: dict[int, dict[int, Mapping[str, Any]]] = {}
    for expected_row_ordinal, row_entry in enumerate(rows):
        row = _require_mapping(row_entry, "PST structural row")
        row_ordinal = _pst_exact_int(
            row.get("row_ordinal"),
            "structural row ordinal",
            minimum=0,
        )
        if row_ordinal != expected_row_ordinal:
            raise ContractValidationError("PST structural row position is invalid")
        if row_ordinal in row_cells:
            raise ContractValidationError("PST structural rows are duplicated")
        cells = row.get("cells")
        if type(cells) is not list:
            raise ContractValidationError("PST structural row cells are invalid")
        cells_by_column: dict[int, Mapping[str, Any]] = {}
        for expected_column_ordinal, cell_entry in enumerate(cells):
            cell = _require_mapping(cell_entry, "PST structural cell")
            column_ordinal = _pst_exact_int(
                cell.get("column_ordinal"),
                "structural cell column ordinal",
                minimum=0,
            )
            if column_ordinal != expected_column_ordinal:
                raise ContractValidationError("PST structural cell position is invalid")
            if column_ordinal in cells_by_column:
                raise ContractValidationError("PST structural cells are duplicated")
            cell_row_ordinal = _pst_exact_int(
                cell.get("row_ordinal"),
                "structural cell row ordinal",
                minimum=0,
            )
            if cell_row_ordinal != row_ordinal:
                raise ContractValidationError("PST structural cell row binding is invalid")
            _pst_exact_int(cell.get("row_span"), "structural cell row span", minimum=1)
            _pst_exact_int(cell.get("column_span"), "structural cell column span", minimum=1)
            cell_state = cell.get("cell_state")
            value = cell.get("value")
            normalized_value = cell.get("normalized_value")
            if type(cell_state) is not str or cell_state not in {"populated", "blank", "absent"}:
                raise ContractValidationError("PST structural cell state is invalid")
            if value is not None and type(value) is not str:
                raise ContractValidationError("PST structural cell value is invalid")
            if normalized_value is not None and type(normalized_value) is not str:
                raise ContractValidationError("PST structural cell normalized value is invalid")
            if cell_state == "populated":
                if value is None or not value or normalized_value != value.casefold():
                    raise ContractValidationError("PST populated cell projection is invalid")
            elif value is not None or normalized_value is not None:
                raise ContractValidationError("PST blank or absent cell projection is invalid")
            cells_by_column[column_ordinal] = cell
        row_cells[row_ordinal] = cells_by_column
    column_ordinals: set[int] = set()
    columns_by_ordinal: dict[int, Mapping[str, Any]] = {}
    column_keys = {"column_ordinal"}
    for expected_column_ordinal, column_entry in enumerate(columns):
        column = _require_mapping(column_entry, "PST structural column")
        _pst_require_exact_keys(
            column,
            column_keys,
            "PST structural column",
            optional={"original_header", "normalized_header"},
        )
        column_ordinal = _pst_exact_int(
            column.get("column_ordinal"),
            "structural column ordinal",
            minimum=0,
        )
        if column_ordinal != expected_column_ordinal:
            raise ContractValidationError("PST structural column position is invalid")
        if column_ordinal in column_ordinals:
            raise ContractValidationError("PST structural columns are duplicated")
        original_header = column.get("original_header")
        normalized_header = column.get("normalized_header")
        if original_header is not None and type(original_header) is not str:
            raise ContractValidationError("PST structural original header is invalid")
        if normalized_header is not None and type(normalized_header) is not str:
            raise ContractValidationError("PST structural normalized header is invalid")
        expected_normalized_header = original_header.casefold() if original_header else None
        if normalized_header != expected_normalized_header:
            raise ContractValidationError("PST structural header normalization is invalid")
        column_ordinals.add(column_ordinal)
        columns_by_ordinal[column_ordinal] = column
    canonical_column_ordinals = tuple(range(len(columns)))
    for cells_by_column in row_cells.values():
        if tuple(cells_by_column) != canonical_column_ordinals:
            raise ContractValidationError("PST structural row cell coverage is incomplete")
    coverage_owners: dict[tuple[int, int], tuple[int, int]] = {}
    row_count = len(rows)
    column_count = len(columns)
    for row_ordinal, cells_by_column in row_cells.items():
        for column_ordinal, cell in cells_by_column.items():
            cell_state = cell["cell_state"]
            row_span = cell["row_span"]
            column_span = cell["column_span"]
            if cell_state == "absent":
                if row_span != 1 or column_span != 1:
                    raise ContractValidationError("PST absent cell span is invalid")
                continue
            anchor = (row_ordinal, column_ordinal)
            for covered_row in range(row_ordinal, row_ordinal + row_span):
                for covered_column in range(
                    column_ordinal,
                    column_ordinal + column_span,
                ):
                    if covered_row >= row_count or covered_column >= column_count:
                        continue
                    previous_anchor = coverage_owners.get((covered_row, covered_column))
                    if previous_anchor is not None and previous_anchor != anchor:
                        raise ContractValidationError("PST structural cell span coverage overlaps")
                    coverage_owners[(covered_row, covered_column)] = anchor
    for row_ordinal, cells_by_column in row_cells.items():
        for column_ordinal, cell in cells_by_column.items():
            owner = coverage_owners.get((row_ordinal, column_ordinal))
            if cell["cell_state"] != "absent" and owner not in {
                None,
                (row_ordinal, column_ordinal),
            }:
                raise ContractValidationError("PST span-covered structural cell must be absent")
    if expected_cell_occupancy_fingerprint is not None:
        if type(expected_cell_occupancy_fingerprint) is not str:
            raise ContractValidationError("PST structural occupancy binding is invalid")
        actual_cell_occupancy_fingerprint = _pst_structural_cell_occupancy_fingerprint(
            rows,
            column_count=column_count,
            columns=columns,
            relationships=relationships,
        )
        if actual_cell_occupancy_fingerprint != expected_cell_occupancy_fingerprint:
            raise ContractValidationError("PST structural cell occupancy is not canonical")

    relationship_for_scope = {
        "col": "column_header",
        "colgroup": "column_group_header",
        "row": "row_header",
        "rowgroup": "row_group_header",
    }
    allowed_relationships = set(relationship_for_scope.values())
    allowed_scopes = {*relationship_for_scope, "inferred"}
    for relationship_entry in relationships:
        relationship = _require_mapping(
            relationship_entry,
            "PST structural header relationship",
        )
        _pst_require_exact_keys(
            relationship,
            relationship_keys,
            "PST structural header relationship",
        )
        header_row_ordinal = _pst_exact_int(
            relationship["header_row_ordinal"],
            "header relationship row ordinal",
            minimum=0,
        )
        header_column_ordinal = _pst_exact_int(
            relationship["header_column_ordinal"],
            "header relationship header column ordinal",
            minimum=0,
        )
        column_ordinal = _pst_exact_int(
            relationship["column_ordinal"],
            "header relationship column ordinal",
            minimum=0,
        )
        row_span = _pst_exact_int(
            relationship["row_span"],
            "header relationship row span",
            minimum=1,
        )
        column_span = _pst_exact_int(
            relationship["column_span"],
            "header relationship column span",
            minimum=1,
        )
        if (
            type(relationship["header_text"]) is not str
            or type(relationship["relationship"]) is not str
            or relationship["relationship"] not in allowed_relationships
            or type(relationship["scope"]) is not str
            or relationship["scope"] not in allowed_scopes
        ):
            raise ContractValidationError("PST structural header relationship marker is invalid")
        if header_row_ordinal not in row_cells:
            raise ContractValidationError("PST structural header row is out of range")
        header_cell = row_cells[header_row_ordinal].get(header_column_ordinal)
        if header_cell is None or column_ordinal not in column_ordinals:
            raise ContractValidationError("PST structural header relationship target is invalid")
        if (
            relationship["header_text"] != header_cell.get("value")
            or row_span != header_cell.get("row_span")
            or column_span != header_cell.get("column_span")
            or header_cell.get("cell_state") != "populated"
        ):
            raise ContractValidationError(
                "PST structural header relationship is not bound to its cell"
            )
        if (
            relationship["scope"] in relationship_for_scope
            and relationship["relationship"] != relationship_for_scope[relationship["scope"]]
        ):
            raise ContractValidationError("PST structural header relationship scope is invalid")
        if relationship["relationship"] in {"column_header", "column_group_header"}:
            if not (header_column_ordinal <= column_ordinal < header_column_ordinal + column_span):
                raise ContractValidationError(
                    "PST structural header relationship column coverage is invalid"
                )
        elif column_ordinal != header_column_ordinal:
            raise ContractValidationError(
                "PST structural row header relationship column is invalid"
            )
    expected_column_headers: dict[int, list[str]] = {}
    for relationship in relationships:
        if relationship["relationship"] in {"column_header", "column_group_header"}:
            expected_column_headers.setdefault(relationship["column_ordinal"], []).append(
                relationship["header_text"]
            )
    for column_ordinal, column in columns_by_ordinal.items():
        header_values = expected_column_headers.get(column_ordinal, [])
        expected_original_header = " | ".join(header_values) or None
        expected_normalized_header = (
            expected_original_header.casefold() if expected_original_header else None
        )
        if (
            column.get("original_header") != expected_original_header
            or column.get("normalized_header") != expected_normalized_header
        ):
            raise ContractValidationError("PST structural column header binding is invalid")


def _validate_pst_message_limit_topology(
    inventory: SourceInventory,
    *,
    item_by_key: Mapping[str, SourceInventoryItem],
) -> None:
    """Reject evidence children beneath a source file excluded by max_messages."""

    limited_keys = {
        str(item.location["source_local_key"])
        for item in inventory.items
        if (
            item.structure_kind == "exported_file"
            and item.processing_state == "preserved_unparsed"
            and item.location.get("source_unit_failure_code") == _PST_MESSAGE_LIMIT_FAILURE_CODE
        )
    }
    for item in inventory.items:
        source_local_key = item.location.get("source_local_key")
        if not isinstance(source_local_key, str) or source_local_key in limited_keys:
            continue
        seen: set[str] = set()
        parent_key = item.location.get("parent_source_local_key")
        while isinstance(parent_key, str) and parent_key:
            if parent_key in seen:
                raise ContractValidationError("PST inventory parent topology is cyclic")
            seen.add(parent_key)
            if parent_key in limited_keys:
                raise ContractValidationError("PST message-limit source unit has derived evidence")
            parent_item = item_by_key.get(parent_key)
            if parent_item is None:
                break
            parent_key = parent_item.location.get("parent_source_local_key")


def _finalize_pst_inventory_specs(
    specs: list[_PstInventorySpec],
    structural_specs: Sequence[Mapping[str, Any]],
    *,
    extraction_input: ExtractionInput,
    parser_fingerprint: str,
    build_errors: list[str],
) -> tuple[SourceInventory, tuple[StructuralObservation, ...]]:
    spec_by_key: dict[str, _PstInventorySpec] = {}
    for spec in specs:
        if spec.source_local_key in spec_by_key:
            raise ContractValidationError(_PST_STRUCTURAL_TRANSACTION_FAILURE_CODE)
        spec_by_key[spec.source_local_key] = spec
    structural_spec_by_key = {
        str(structural_spec["source_local_key"]): structural_spec
        for structural_spec in structural_specs
    }
    for spec in specs:
        binding = _pst_traversal_binding_fingerprint(
            source_local_key=spec.source_local_key,
            parent_source_local_key=spec.parent_source_local_key,
            ordinal=spec.ordinal,
        )
        source_binding_fingerprint = None
        structural_spec = structural_spec_by_key.get(spec.source_local_key)
        if spec.structure_kind in _PST_STRUCTURAL_INVENTORY_KINDS:
            if structural_spec is None:
                raise ContractValidationError(_PST_STRUCTURAL_TRANSACTION_FAILURE_CODE)
            try:
                table = _require_mapping(structural_spec.get("table"), "PST structural table")
                columns = _pst_structural_column_projection(table)
                source_binding_fingerprint = _pst_structural_cell_occupancy_fingerprint(
                    _require_list(table, "rows"),
                    column_count=table.get("max_column"),
                    columns=columns,
                    relationships=_require_list(table, "header_relationships"),
                )
            except _PstTextEncodingError:
                spec.processing_state = "failed"
                spec.location = {
                    **dict(spec.location),
                    "structural_failure_code": _PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE,
                }
                build_errors.append(_PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE)
            else:
                spec.location = {
                    **dict(spec.location),
                    "cell_occupancy_fingerprint": source_binding_fingerprint,
                }
        spec.source_observation_id = _pst_source_observation_id(
            extraction_input=extraction_input,
            source_local_key=spec.source_local_key,
            traversal_binding_fingerprint=binding,
            source_binding_fingerprint=source_binding_fingerprint,
        )
    structural_specs = [
        {
            **dict(structural_spec),
            "source_observation_id": spec_by_key[
                str(structural_spec["source_local_key"])
            ].source_observation_id,
        }
        for structural_spec in structural_specs
    ]
    for structural_spec in structural_specs:
        source_local_key = str(structural_spec.get("source_local_key", ""))
        spec = spec_by_key.get(source_local_key)
        if spec is None or spec.structure_kind not in _PST_STRUCTURAL_INVENTORY_KINDS:
            raise ContractValidationError(_PST_STRUCTURAL_TRANSACTION_FAILURE_CODE)

    while True:
        inventory = _inventory_from_specs(
            specs,
            extraction_input=extraction_input,
            parser_fingerprint=parser_fingerprint,
        )
        item_by_key = {str(item.location["source_local_key"]): item for item in inventory.items}
        structural_observations: list[StructuralObservation] = []
        conversion_failed = False
        for structural_spec in structural_specs:
            spec = spec_by_key[str(structural_spec["source_local_key"])]
            if spec.processing_state != "parsed":
                continue
            try:
                structural_observations.append(
                    _structural_observation_from_spec(
                        structural_spec,
                        item_by_key=item_by_key,
                        extraction_input=extraction_input,
                        parser_fingerprint=parser_fingerprint,
                    )
                )
            except Exception:
                spec.processing_state = "failed"
                spec.location = {
                    **dict(spec.location),
                    "structural_failure_code": _PST_STRUCTURAL_BUILD_FAILURE_CODE,
                }
                specs[0].processing_state = "failed"
                build_errors.append(_PST_STRUCTURAL_BUILD_FAILURE_CODE)
                conversion_failed = True
        if conversion_failed:
            continue
        try:
            _validate_pst_message_limit_topology(inventory, item_by_key=item_by_key)
            _validate_pst_structural_bijection(inventory, structural_observations)
        except ContractValidationError:
            raise ContractValidationError(_PST_STRUCTURAL_TRANSACTION_FAILURE_CODE) from None
        return inventory, tuple(structural_observations)


@dataclass
class _PstInventorySpec:
    source_local_key: str
    ordinal: int
    structure_kind: str
    content_type: str
    processing_state: str
    parent_source_local_key: str | None
    source_observation_id: str
    location: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _PstSourceUnitClassification:
    """One closed classification for an exported source unit.

    The media type is derived from the exporter/source identity, while the
    processing result is derived independently from size, I/O, and envelope
    validation.  Inventory builders and fallbacks must consume this same
    result so a failed ``.eml`` cannot become an octet-stream merely because
    no message object was produced.
    """

    source_local_key: str
    source_size_bytes: int | None
    source_content_fingerprint: str | None
    content_type: str
    processing_state: str
    message: EmailMessage | None
    reason_code: str | None = None
    attachment_classification: _AttachmentClassification | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    attachment_filename: str | None = None
    attachment_mime_type: str | None = None
    linked_attachment_id: str | None = None
    attachment_name_fingerprint: str | None = None

    @property
    def binding(self) -> tuple[Any, ...]:
        return (
            self.source_local_key,
            self.source_size_bytes,
            self.source_content_fingerprint,
            self.content_type,
            self.processing_state,
            self.reason_code,
        )


def _readpst_source_unit_location(
    unit: _ExportedTraversalUnit,
    *,
    traversal: _ExportedTraversal,
    source_unit_classifications: Mapping[str, _PstSourceUnitClassification],
    lookup_context: _PstExtractionLookupContext | None = None,
) -> dict[str, Any]:
    lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    source_unit_kind = _exported_source_unit_kind(unit)
    if source_unit_kind != _PST_SOURCE_UNIT_ATTACHMENT:
        return {}
    location: dict[str, Any] = {"source_unit_kind": source_unit_kind}

    name = _source_unit_basename_bytes(
        canonical_relative_components=unit.canonical_relative_components,
    )
    if name is None:
        raise ContractValidationError("PST attachment sidecar lacks a basename")
    item_count_bytes, separator, attachment_name = name.partition(b"-")
    if not separator or not item_count_bytes.isdigit() or not attachment_name:
        raise ContractValidationError("PST attachment sidecar naming is invalid")
    item_count = int(item_count_bytes.decode("ascii"))
    location["source_unit_parent_item_count"] = item_count
    location["source_unit_attachment_state"] = "attachment_sidecar"

    components = unit.canonical_relative_components
    if components is None:
        location["source_unit_attachment_state"] = "missing_parent"
        return location
    parent_components = (*components[:-1], item_count_bytes)
    parent_candidates = lookup_context.sidecar_parent_candidates(
        unit,
        parent_components=parent_components,
    )
    if parent_candidates is None:
        parent_candidates = ()
    if len(parent_candidates) != 1:
        location["source_unit_attachment_state"] = (
            "missing_parent" if not parent_candidates else "duplicate_parent"
        )
        return location

    parent = parent_candidates[0]
    location["source_unit_parent_source_local_key"] = parent.source_local_key
    if _exported_source_unit_kind(parent) != _PST_SOURCE_UNIT_MESSAGE:
        location["source_unit_attachment_state"] = "invalid_parent"
        return location
    parent_classification = source_unit_classifications.get(parent.source_local_key)
    if parent_classification is None:
        location["source_unit_attachment_state"] = "parent_unclassified"
    elif parent_classification.reason_code == _PST_MESSAGE_LIMIT_FAILURE_CODE:
        location["source_unit_attachment_state"] = "parent_limit_reached"
    elif parent_classification.processing_state == "parsed":
        location["source_unit_attachment_state"] = "linked"
    elif parent_classification.processing_state == "preserved_unparsed":
        location["source_unit_attachment_state"] = "parent_preserved_unparsed"
    else:
        location["source_unit_attachment_state"] = "parent_failed"
    if parent_classification is not None:
        location["source_unit_parent_processing_state"] = parent_classification.processing_state
    mapping_failure_codes = {
        "missing_parent": "pst_sidecar_parent_missing",
        "duplicate_parent": "pst_sidecar_parent_ambiguous",
        "invalid_parent": "pst_sidecar_parent_invalid",
        "parent_unclassified": "pst_sidecar_parent_unclassified",
        "parent_limit_reached": "pst_sidecar_parent_message_limit",
        "parent_preserved_unparsed": "pst_sidecar_parent_unavailable",
        "parent_failed": "pst_sidecar_parent_unavailable",
    }
    mapping_state = location.get("source_unit_attachment_state")
    if mapping_state in mapping_failure_codes:
        location["source_unit_attachment_mapping_failure_code"] = mapping_failure_codes[
            mapping_state
        ]
    return location


def _source_unit_location(
    classification: _PstSourceUnitClassification,
    *,
    unit: _ExportedTraversalUnit | None = None,
    traversal: _ExportedTraversal | None = None,
    source_unit_classifications: Mapping[str, _PstSourceUnitClassification] | None = None,
    lookup_context: _PstExtractionLookupContext | None = None,
) -> dict[str, Any]:
    if classification.reason_code is None:
        location: dict[str, Any] = {}
    else:
        location = {"source_unit_failure_code": classification.reason_code}
    if unit is not None and traversal is not None:
        location["source_unit_kind"] = _exported_source_unit_kind(unit)
        location.update(
            _readpst_source_unit_location(
                unit,
                traversal=traversal,
                source_unit_classifications=source_unit_classifications or {},
                lookup_context=lookup_context,
            )
        )
        if unit.failure_code is not None:
            location["traversal_failure_code"] = unit.failure_code
            location["traversal_unit"] = unit.structure_kind
        # Every regular export file, not only attachment sidecars, contributes
        # its raw-byte identity to the private inventory.  The bridge later
        # binds an existing-export materialization to this complete traversal
        # without exposing a path or raw bytes.  A source that could not be
        # read remains explicitly non-parsed and therefore has no digest.
        if classification.source_size_bytes is not None:
            location["source_unit_size_bytes"] = classification.source_size_bytes
        if classification.source_content_fingerprint is not None:
            location["source_unit_content_fingerprint"] = classification.source_content_fingerprint
        if _exported_source_unit_kind(unit) == _PST_SOURCE_UNIT_ATTACHMENT:
            if classification.attachment_mime_type is not None:
                location["source_unit_attachment_media_type"] = classification.attachment_mime_type
            location["source_unit_attachment_processing_state"] = classification.processing_state
            if classification.attachment_classification is not None:
                location["source_unit_attachment_text_extraction_state"] = (
                    classification.attachment_classification.text_extraction_state
                )
                location["source_unit_attachment_stored_char_count"] = sum(
                    len(segment)
                    for segment in classification.attachment_classification.extracted_text_segments
                )
                location["source_unit_attachment_stored_byte_count"] = sum(
                    _pst_utf8_byte_count(segment)
                    for segment in classification.attachment_classification.extracted_text_segments
                )
                location["source_unit_attachment_text_segments_fingerprint"] = sha256_json(
                    list(classification.attachment_classification.extracted_text_segments)
                )
                location["source_unit_attachment_source_char_count"] = (
                    len(classification.attachment_classification.text)
                    if classification.attachment_classification.processing_state == "parsed"
                    and isinstance(classification.attachment_classification.text, str)
                    else None
                )
            if classification.reason_code is not None:
                location["source_unit_attachment_failure_code"] = classification.reason_code
            if classification.attachment_name_fingerprint is not None:
                location["source_unit_attachment_name_fingerprint"] = (
                    classification.attachment_name_fingerprint
                )
            if classification.linked_attachment_id is not None:
                location["source_unit_linked_attachment_id"] = classification.linked_attachment_id
    return location


def _build_pst_inventory_fallback(
    extraction_input: ExtractionInput,
    *,
    parser_fingerprint: str,
    config: _PstParserConfig,
    warnings: list[str],
    traversal: _ExportedTraversal,
    parsed_messages: Sequence[_ParsedMessage],
    source_unit_classifications: dict[str, _PstSourceUnitClassification],
    build_errors: list[str],
    lookup_context: _PstExtractionLookupContext | None = None,
) -> tuple[SourceInventory, tuple[StructuralObservation, ...]]:
    """Preserve discovered file/message units after a later build failure."""

    lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    lookup_context.bind_parsed_messages(parsed_messages)
    specs: list[_PstInventorySpec] = [
        _PstInventorySpec(
            source_local_key="archive",
            ordinal=0,
            structure_kind="archive",
            content_type=extraction_input.asset.mime_type,
            processing_state="failed",
            parent_source_local_key=None,
            source_observation_id=_pst_source_observation_id(
                extraction_input=extraction_input,
                source_local_key="archive",
            ),
        )
    ]
    structural_specs: list[dict[str, Any]] = []
    message_occurrence_ids = _pst_top_level_message_occurrence_ids(
        parsed_messages,
        extraction_input=extraction_input,
    )
    ordinal = 1
    for unit in traversal.units:
        if unit.failure_code is not None:
            if _exported_source_unit_kind(unit) == _PST_SOURCE_UNIT_ATTACHMENT:
                ordinal = _append_pst_fallback_file_spec(
                    unit,
                    specs=specs,
                    structural_specs=structural_specs,
                    extraction_input=extraction_input,
                    config=config,
                    warnings=warnings,
                    source_unit_classifications=source_unit_classifications,
                    traversal=traversal,
                    parsed_messages=parsed_messages,
                    message_occurrence_ids=message_occurrence_ids,
                    next_ordinal=ordinal,
                    lookup_context=lookup_context,
                )
            else:
                specs.append(
                    _PstInventorySpec(
                        source_local_key=unit.source_local_key,
                        ordinal=ordinal,
                        structure_kind=unit.structure_kind,
                        content_type="application/octet-stream",
                        processing_state="failed",
                        parent_source_local_key=unit.parent_source_local_key,
                        source_observation_id=_pst_source_observation_id(
                            extraction_input=extraction_input,
                            source_local_key=unit.source_local_key,
                        ),
                        location={
                            "traversal_failure_code": unit.failure_code,
                            "traversal_unit": unit.structure_kind,
                        },
                    )
                )
                ordinal += 1
            continue
        if unit.structure_kind == "exported_directory":
            ordinal = _append_pst_directory_inventory_spec(
                unit,
                specs=specs,
                extraction_input=extraction_input,
                next_ordinal=ordinal,
            )
            continue
        classification = _source_unit_classification_for_unit(
            unit,
            config=config,
            warnings=warnings,
            source_unit_classifications=source_unit_classifications,
        )
        message = classification.message
        specs.append(
            _PstInventorySpec(
                source_local_key=unit.source_local_key,
                ordinal=ordinal,
                structure_kind="exported_file",
                content_type=classification.content_type,
                processing_state=classification.processing_state,
                parent_source_local_key=unit.parent_source_local_key,
                source_observation_id=_pst_source_observation_id(
                    extraction_input=extraction_input,
                    source_local_key=unit.source_local_key,
                ),
                location=_source_unit_location(
                    classification,
                    unit=unit,
                    traversal=traversal,
                    source_unit_classifications=source_unit_classifications,
                    lookup_context=lookup_context,
                ),
            )
        )
        ordinal += 1
        if _exported_source_unit_kind(unit) == _PST_SOURCE_UNIT_ATTACHMENT:
            location = _source_unit_location(
                classification,
                unit=unit,
                traversal=traversal,
                source_unit_classifications=source_unit_classifications,
                lookup_context=lookup_context,
            )
            parent_key = location.get("source_unit_parent_source_local_key")
            parent = lookup_context.parsed_messages_by_source_key.get(parent_key)
            if parent is not None:
                ordinal = _append_readpst_sidecar_specs(
                    parent,
                    specs=specs,
                    structural_specs=structural_specs,
                    extraction_input=extraction_input,
                    parent_message_key=f"{parent_key}:message",
                    next_ordinal=ordinal,
                    sidecar_source_local_key=unit.source_local_key,
                )
            continue
        if message is None:
            continue
        parsed_message = lookup_context.parsed_messages_by_source_key.get(unit.source_local_key)
        if parsed_message is None:
            continue
        message_key = f"{unit.source_local_key}:message"
        specs.append(
            _PstInventorySpec(
                source_local_key=message_key,
                ordinal=ordinal,
                structure_kind="exported_message_occurrence",
                content_type="message/rfc822",
                processing_state="parsed",
                parent_source_local_key=unit.source_local_key,
                source_observation_id=_pst_source_observation_id(
                    extraction_input=extraction_input,
                    source_local_key=message_key,
                ),
                location={
                    "message_fingerprint": _message_fingerprint(parsed_message),
                    "message_occurrence_id": message_occurrence_ids[unit.source_local_key],
                },
            )
        )
        ordinal += 1
        ordinal = _append_chronology_specs(
            specs,
            extraction_input=extraction_input,
            message=message,
            parent_source_local_key=message_key,
            next_ordinal=ordinal,
        )
        try:
            mime_specs, table_specs = _mime_inventory_specs(
                message,
                extraction_input=extraction_input,
                config=config,
                parent_source_local_key=message_key,
                next_ordinal=ordinal,
                warnings=warnings,
            )
        except Exception:
            build_errors.append("pst_parser_inventory_build_failed")
            continue
        specs.extend(mime_specs)
        structural_specs.extend(table_specs)
        ordinal += len(mime_specs)
    return _finalize_pst_inventory_specs(
        specs,
        structural_specs,
        extraction_input=extraction_input,
        parser_fingerprint=parser_fingerprint,
        build_errors=build_errors,
    )


def _build_pst_inventory(
    export_root: Path,
    *,
    extraction_input: ExtractionInput,
    parsed_messages: Sequence[_ParsedMessage],
    config: _PstParserConfig,
    parser_fingerprint: str,
    warnings: list[str],
    traversal: _ExportedTraversal | None = None,
    source_unit_classifications: dict[str, _PstSourceUnitClassification] | None = None,
    archive_processing_state: str | None = None,
    build_errors: list[str] | None = None,
    lookup_context: _PstExtractionLookupContext | None = None,
) -> tuple[SourceInventory, tuple[StructuralObservation, ...]]:
    """Build WP1 records from the complete exported tree before it is deleted."""

    traversal = traversal or _safe_traversal_snapshot(_snapshot_export_tree, export_root)
    lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    lookup_context.bind_parsed_messages(parsed_messages)
    if source_unit_classifications is None:
        source_unit_classifications = {}
    build_errors = build_errors if build_errors is not None else []
    specs: list[_PstInventorySpec] = [
        _PstInventorySpec(
            source_local_key="archive",
            ordinal=0,
            structure_kind="archive",
            content_type=extraction_input.asset.mime_type,
            processing_state=archive_processing_state
            or (
                "failed"
                if traversal.failures
                else (
                    "preserved_unparsed"
                    if _message_limit_reached(source_unit_classifications)
                    or _readpst_sidecar_mapping_incomplete(
                        traversal,
                        source_unit_classifications=source_unit_classifications,
                        lookup_context=lookup_context,
                    )
                    else ("parsed" if parsed_messages else "preserved_unparsed")
                )
            ),
            parent_source_local_key=None,
            source_observation_id=_pst_source_observation_id(
                extraction_input=extraction_input,
                source_local_key="archive",
            ),
        )
    ]
    structural_specs: list[dict[str, Any]] = []
    message_occurrence_ids = _pst_top_level_message_occurrence_ids(
        parsed_messages,
        extraction_input=extraction_input,
    )
    ordinal = 1
    for unit in traversal.units:
        try:
            if unit.failure_code is not None:
                if _exported_source_unit_kind(unit) == _PST_SOURCE_UNIT_ATTACHMENT:
                    ordinal = _append_pst_fallback_file_spec(
                        unit,
                        specs=specs,
                        structural_specs=structural_specs,
                        extraction_input=extraction_input,
                        config=config,
                        warnings=warnings,
                        source_unit_classifications=source_unit_classifications,
                        traversal=traversal,
                        parsed_messages=parsed_messages,
                        message_occurrence_ids=message_occurrence_ids,
                        next_ordinal=ordinal,
                        lookup_context=lookup_context,
                    )
                else:
                    specs.append(
                        _PstInventorySpec(
                            source_local_key=unit.source_local_key,
                            ordinal=ordinal,
                            structure_kind=unit.structure_kind,
                            content_type="application/octet-stream",
                            processing_state="failed",
                            parent_source_local_key=unit.parent_source_local_key,
                            source_observation_id=_pst_source_observation_id(
                                extraction_input=extraction_input,
                                source_local_key=unit.source_local_key,
                            ),
                            location={
                                "traversal_failure_code": unit.failure_code,
                                "traversal_unit": unit.structure_kind,
                            },
                        )
                    )
                    ordinal += 1
                continue
            ordinal = _append_pst_file_inventory_specs(
                unit,
                specs=specs,
                structural_specs=structural_specs,
                extraction_input=extraction_input,
                config=config,
                warnings=warnings,
                source_unit_classifications=source_unit_classifications,
                traversal=traversal,
                parsed_messages=parsed_messages,
                message_occurrence_ids=message_occurrence_ids,
                next_ordinal=ordinal,
                lookup_context=lookup_context,
            )
        except Exception:
            build_errors.append("pst_parser_inventory_build_failed")
            specs[0].processing_state = "failed"
            ordinal = max(
                ordinal,
                max((spec.ordinal for spec in specs), default=-1) + 1,
            )
            if not any(spec.source_local_key == unit.source_local_key for spec in specs):
                ordinal = _append_pst_fallback_file_spec(
                    unit,
                    specs=specs,
                    structural_specs=structural_specs,
                    extraction_input=extraction_input,
                    config=config,
                    warnings=warnings,
                    source_unit_classifications=source_unit_classifications,
                    traversal=traversal,
                    parsed_messages=parsed_messages,
                    message_occurrence_ids=message_occurrence_ids,
                    next_ordinal=ordinal,
                    lookup_context=lookup_context,
                )

    return _finalize_pst_inventory_specs(
        specs,
        structural_specs,
        extraction_input=extraction_input,
        parser_fingerprint=parser_fingerprint,
        build_errors=build_errors,
    )


def _append_pst_file_inventory_specs(
    unit: _ExportedTraversalUnit,
    *,
    specs: list[_PstInventorySpec],
    structural_specs: list[dict[str, Any]],
    extraction_input: ExtractionInput,
    config: _PstParserConfig,
    warnings: list[str],
    source_unit_classifications: dict[str, _PstSourceUnitClassification],
    traversal: _ExportedTraversal,
    next_ordinal: int,
    parsed_messages: Sequence[_ParsedMessage] = (),
    message_occurrence_ids: Mapping[str, str] | None = None,
    lookup_context: _PstExtractionLookupContext | None = None,
) -> int:
    if lookup_context is None:
        lookup_context = _pst_lookup_context_for_traversal(traversal)
        lookup_context.bind_parsed_messages(parsed_messages)
    else:
        lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    if unit.structure_kind == "exported_directory":
        return _append_pst_directory_inventory_spec(
            unit,
            specs=specs,
            extraction_input=extraction_input,
            next_ordinal=next_ordinal,
        )
    candidate = unit.path
    if candidate is None:
        raise ContractValidationError("PST traversal unit has no path or failure")
    file_key = unit.source_local_key
    classification = _source_unit_classification_for_unit(
        unit,
        config=config,
        warnings=warnings,
        source_unit_classifications=source_unit_classifications,
    )
    file_observation_id = _pst_source_observation_id(
        extraction_input=extraction_input,
        source_local_key=file_key,
    )
    specs.append(
        _PstInventorySpec(
            source_local_key=file_key,
            ordinal=next_ordinal,
            structure_kind="exported_file",
            content_type=classification.content_type,
            processing_state=classification.processing_state,
            parent_source_local_key=unit.parent_source_local_key,
            source_observation_id=file_observation_id,
            location=_source_unit_location(
                classification,
                unit=unit,
                traversal=traversal,
                source_unit_classifications=source_unit_classifications,
                lookup_context=lookup_context,
            ),
        )
    )
    next_ordinal += 1
    if _exported_source_unit_kind(unit) == _PST_SOURCE_UNIT_ATTACHMENT:
        location = _source_unit_location(
            classification,
            unit=unit,
            traversal=traversal,
            source_unit_classifications=source_unit_classifications,
            lookup_context=lookup_context,
        )
        parent_key = location.get("source_unit_parent_source_local_key")
        parent = lookup_context.parsed_messages_by_source_key.get(parent_key)
        if parent is not None:
            return _append_readpst_sidecar_specs(
                parent,
                specs=specs,
                structural_specs=structural_specs,
                extraction_input=extraction_input,
                parent_message_key=f"{parent_key}:message",
                next_ordinal=next_ordinal,
                sidecar_source_local_key=file_key,
            )
    message = classification.message
    if message is None:
        return next_ordinal
    parsed_message = lookup_context.parsed_messages_by_source_key.get(file_key)
    if parsed_message is None:
        return next_ordinal
    if message_occurrence_ids is None:
        message_occurrence_ids = _pst_top_level_message_occurrence_ids(
            parsed_messages,
            extraction_input=extraction_input,
        )
    message_key = f"{file_key}:message"
    message_observation_id = _pst_source_observation_id(
        extraction_input=extraction_input,
        source_local_key=message_key,
    )
    specs.append(
        _PstInventorySpec(
            source_local_key=message_key,
            ordinal=next_ordinal,
            structure_kind="exported_message_occurrence",
            content_type="message/rfc822",
            processing_state="parsed",
            parent_source_local_key=file_key,
            source_observation_id=message_observation_id,
            location={
                "message_fingerprint": _message_fingerprint(parsed_message),
                "message_occurrence_id": message_occurrence_ids[file_key],
            },
        )
    )
    next_ordinal += 1
    next_ordinal = _append_chronology_specs(
        specs,
        extraction_input=extraction_input,
        message=message,
        parent_source_local_key=message_key,
        next_ordinal=next_ordinal,
    )
    mime_specs, table_specs = _mime_inventory_specs(
        message,
        extraction_input=extraction_input,
        config=config,
        parent_source_local_key=message_key,
        next_ordinal=next_ordinal,
        warnings=warnings,
    )
    specs.extend(mime_specs)
    structural_specs.extend(table_specs)
    return next_ordinal + len(mime_specs)


def _append_pst_directory_inventory_spec(
    unit: _ExportedTraversalUnit,
    *,
    specs: list[_PstInventorySpec],
    extraction_input: ExtractionInput,
    next_ordinal: int,
) -> int:
    """Retain one readable exported directory in the physical inventory."""

    if unit.path is None or unit.structure_kind != "exported_directory":
        raise ContractValidationError("PST readable directory traversal unit is invalid")
    specs.append(
        _PstInventorySpec(
            source_local_key=unit.source_local_key,
            ordinal=next_ordinal,
            structure_kind="exported_directory",
            content_type="application/octet-stream",
            processing_state="parsed",
            parent_source_local_key=unit.parent_source_local_key,
            source_observation_id=_pst_source_observation_id(
                extraction_input=extraction_input,
                source_local_key=unit.source_local_key,
            ),
        )
    )
    return next_ordinal + 1


def _append_readpst_sidecar_specs(
    message: _ParsedMessage | EmailMessage,
    *,
    specs: list[_PstInventorySpec],
    structural_specs: list[dict[str, Any]],
    extraction_input: ExtractionInput,
    parent_message_key: str,
    next_ordinal: int,
    sidecar_source_local_key: str | None = None,
) -> int:
    """Project already-classified linked sidecars into inventory and tables."""

    if not isinstance(message, _ParsedMessage):
        return next_ordinal
    ordinal = next_ordinal
    chronology = message.chronology
    sender_fingerprint = sha256_json(_safe_mail_text(message.sender, "sender"))
    for attachment_index, attachment in enumerate(message.attachments, start=1):
        if attachment.source_kind != "readpst_sidecar" or attachment.source_local_key is None:
            continue
        if (
            sidecar_source_local_key is not None
            and attachment.source_local_key != sidecar_source_local_key
        ):
            continue
        attachment_key = f"{attachment.source_local_key}:attachment"
        source_observation_id = _pst_source_observation_id(
            extraction_input=extraction_input,
            source_local_key=attachment_key,
        )
        specs.append(
            _PstInventorySpec(
                source_local_key=attachment_key,
                ordinal=ordinal,
                structure_kind="regular_attachment_occurrence",
                content_type=attachment.mime_type or "application/octet-stream",
                processing_state=attachment.processing_state,
                parent_source_local_key=parent_message_key,
                source_observation_id=source_observation_id,
                location={
                    "attachment_ordinal": attachment_index,
                    "attachment_source": "readpst_sidecar",
                    "sidecar_source_local_key": attachment.source_local_key,
                    "sidecar_content_fingerprint": (
                        attachment.content_hash.removeprefix("sha256:")
                        if attachment.content_hash is not None
                        else None
                    ),
                    "sidecar_name_fingerprint": attachment.source_name_fingerprint,
                    "attachment_failure_code": attachment.failure_code,
                    **_parsed_attachment_identity_fields(attachment),
                },
            )
        )
        ordinal += 1
        if attachment.processing_state != "parsed" or attachment.mime_type != "text/html":
            continue
        text = attachment.text
        if not isinstance(text, str):
            continue
        events = _extract_html_structure_events(text)
        for event in events:
            if event["kind"] == "quote":
                quote_ordinal = int(event["quote_ordinal"])
                quote_key = f"{attachment_key}:quote:{quote_ordinal}"
                parent_quote_ordinal = event["parent_quote_ordinal"]
                quote_parent_key = (
                    f"{attachment_key}:quote:{parent_quote_ordinal}"
                    if parent_quote_ordinal is not None
                    else attachment_key
                )
                specs.append(
                    _PstInventorySpec(
                        source_local_key=quote_key,
                        ordinal=ordinal,
                        structure_kind="quote_forwarded_structure",
                        content_type="text/html",
                        processing_state="parsed",
                        parent_source_local_key=quote_parent_key,
                        source_observation_id=_pst_source_observation_id(
                            extraction_input=extraction_input,
                            source_local_key=quote_key,
                        ),
                        location={
                            "quote_ordinal": quote_ordinal,
                            "quote_depth": int(event["quote_depth"]),
                            "attachment_ordinal": attachment_index,
                        },
                    )
                )
                ordinal += 1
                continue
            table = event["table"]
            table_ordinal = int(event["table_ordinal"])
            table_key = f"{attachment_key}:table:{table_ordinal}"
            parent_quote_ordinal = event["quote_ordinal"]
            table_parent_key = (
                f"{attachment_key}:quote:{parent_quote_ordinal}"
                if parent_quote_ordinal is not None
                else attachment_key
            )
            table_observation_id = _pst_source_observation_id(
                extraction_input=extraction_input,
                source_local_key=table_key,
            )
            specs.append(
                _PstInventorySpec(
                    source_local_key=table_key,
                    ordinal=ordinal,
                    structure_kind="html_table",
                    content_type="text/html",
                    processing_state="parsed",
                    parent_source_local_key=table_parent_key,
                    source_observation_id=table_observation_id,
                    location={
                        "table_ordinal": table_ordinal,
                        "mime_ordinal": 0,
                        "attachment_ordinal": attachment_index,
                        "quoted_depth": table["quoted_depth"],
                        "attachment_source": "readpst_sidecar",
                    },
                )
            )
            ordinal += 1
            structural_specs.append(
                {
                    "source_local_key": table_key,
                    "source_observation_id": table_observation_id,
                    "table": table,
                    "table_ordinal": table_ordinal,
                    "mime_ordinal": 0,
                    "attachment_ordinal": attachment_index,
                    "quoted_depth": table["quoted_depth"],
                    "message_lineage_id": parent_message_key,
                    "occurrence_lineage": (parent_message_key,),
                    "sender_fingerprint": sender_fingerprint,
                    "observed_at": chronology.authored_sent_at,
                    "date_state": chronology.date_state,
                }
            )
    return ordinal


def _append_pst_fallback_file_spec(
    unit: _ExportedTraversalUnit,
    *,
    specs: list[_PstInventorySpec],
    structural_specs: list[dict[str, Any]],
    extraction_input: ExtractionInput,
    config: _PstParserConfig,
    warnings: list[str],
    source_unit_classifications: dict[str, _PstSourceUnitClassification],
    traversal: _ExportedTraversal,
    next_ordinal: int,
    parsed_messages: Sequence[_ParsedMessage] = (),
    message_occurrence_ids: Mapping[str, str] | None = None,
    lookup_context: _PstExtractionLookupContext | None = None,
) -> int:
    if lookup_context is None:
        lookup_context = _pst_lookup_context_for_traversal(traversal)
        lookup_context.bind_parsed_messages(parsed_messages)
    else:
        lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    classification = _source_unit_classification_for_unit(
        unit,
        config=config,
        warnings=warnings,
        source_unit_classifications=source_unit_classifications,
    )
    specs.append(
        _PstInventorySpec(
            source_local_key=unit.source_local_key,
            ordinal=next_ordinal,
            structure_kind="exported_file",
            content_type=classification.content_type,
            processing_state=classification.processing_state,
            parent_source_local_key=unit.parent_source_local_key,
            source_observation_id=_pst_source_observation_id(
                extraction_input=extraction_input,
                source_local_key=unit.source_local_key,
            ),
            location=_source_unit_location(
                classification,
                unit=unit,
                traversal=traversal,
                source_unit_classifications=source_unit_classifications,
                lookup_context=lookup_context,
            ),
        )
    )
    next_ordinal += 1
    if _exported_source_unit_kind(unit) == _PST_SOURCE_UNIT_ATTACHMENT:
        location = _source_unit_location(
            classification,
            unit=unit,
            traversal=traversal,
            source_unit_classifications=source_unit_classifications,
            lookup_context=lookup_context,
        )
        parent_key = location.get("source_unit_parent_source_local_key")
        parent = lookup_context.parsed_messages_by_source_key.get(parent_key)
        if parent is not None:
            return _append_readpst_sidecar_specs(
                parent,
                specs=specs,
                structural_specs=structural_specs,
                extraction_input=extraction_input,
                parent_message_key=f"{parent_key}:message",
                next_ordinal=next_ordinal,
                sidecar_source_local_key=unit.source_local_key,
            )
    message = classification.message
    if message is None:
        return next_ordinal
    parsed_message = lookup_context.parsed_messages_by_source_key.get(unit.source_local_key)
    if parsed_message is None:
        return next_ordinal
    if message_occurrence_ids is None:
        message_occurrence_ids = _pst_top_level_message_occurrence_ids(
            parsed_messages,
            extraction_input=extraction_input,
        )
    message_key = f"{unit.source_local_key}:message"
    specs.append(
        _PstInventorySpec(
            source_local_key=message_key,
            ordinal=next_ordinal,
            structure_kind="exported_message_occurrence",
            content_type="message/rfc822",
            processing_state="parsed",
            parent_source_local_key=unit.source_local_key,
            source_observation_id=_pst_source_observation_id(
                extraction_input=extraction_input,
                source_local_key=message_key,
            ),
            location={
                "message_fingerprint": _message_fingerprint(parsed_message),
                "message_occurrence_id": message_occurrence_ids[unit.source_local_key],
            },
        )
    )
    next_ordinal += 1
    next_ordinal = _append_chronology_specs(
        specs,
        extraction_input=extraction_input,
        message=message,
        parent_source_local_key=message_key,
        next_ordinal=next_ordinal,
    )
    mime_specs, table_specs = _mime_inventory_specs(
        message,
        extraction_input=extraction_input,
        config=config,
        parent_source_local_key=message_key,
        next_ordinal=next_ordinal,
        warnings=warnings,
    )
    specs.extend(mime_specs)
    structural_specs.extend(table_specs)
    return next_ordinal + len(mime_specs)


def _export_file_key(candidate: Path, export_root: Path) -> str:
    relative_bytes = _canonical_relative_identity_bytes(candidate, export_root)
    return hashlib.sha256(relative_bytes).hexdigest()[:24]


class _PstPathCanonicalizationError(ContractValidationError):
    """Closed internal error for an unencodable filesystem component."""

    code = "pst_export_component_unencodable"


def _canonical_component_bytes(component: str) -> bytes:
    if not isinstance(component, str):
        raise _PstPathCanonicalizationError("pst_export_component_unencodable")
    try:
        return component.encode("utf-8", "surrogateescape")
    except UnicodeError:
        raise _PstPathCanonicalizationError("pst_export_component_unencodable") from None


def _component_total_order_key(component: str) -> tuple[bytes, bytes, bytes]:
    """Return the one locale-independent total order for path components."""

    raw_bytes = _canonical_component_bytes(component)
    try:
        unicode_view = raw_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError:
        opaque_prefix = b"\x01"
        opaque_bytes = opaque_prefix + raw_bytes
        return opaque_bytes, opaque_bytes, raw_bytes
    try:
        normalized = unicodedata.normalize("NFC", unicode_view)
        primary = unicodedata.normalize("NFC", normalized.casefold())
        exact_bytes = b"\x00" + normalized.encode("utf-8")
        primary_bytes = b"\x00" + primary.encode("utf-8")
    except (UnicodeError, ValueError):
        raise _PstPathCanonicalizationError("pst_export_component_unencodable") from None
    return primary_bytes, exact_bytes, raw_bytes


def _canonical_relative_identity_bytes(path: Path, export_root: Path) -> bytes:
    return b"/".join(_canonical_relative_components(path, export_root))


def _canonical_relative_components(path: Path, export_root: Path) -> tuple[bytes, ...]:
    try:
        relative = path.relative_to(export_root)
    except ValueError:
        components = (path.name,)
    else:
        components = relative.parts
    return tuple(_canonical_component_bytes(component) for component in components)


def _record_source_unit_classification(
    source_unit_classifications: dict[str, _PstSourceUnitClassification],
    classification: _PstSourceUnitClassification,
) -> None:
    _validate_source_unit_classification(classification)
    existing = source_unit_classifications.get(classification.source_local_key)
    if existing is not None:
        raise ContractValidationError("PST source-unit classification collision")
    source_unit_classifications[classification.source_local_key] = classification


def _mark_source_unit_text_unencodable(
    classification: _PstSourceUnitClassification,
) -> _PstSourceUnitClassification:
    attachment_classification = classification.attachment_classification
    if attachment_classification is not None:
        attachment_classification = replace(
            attachment_classification,
            processing_state="preserved_unparsed",
            text_extraction_state="failed",
            payload=None,
            text=None,
            extracted_text_segments=[],
            failure_code=_PST_TEXT_UNENCODABLE_FAILURE_CODE,
            embedded_message=None,
        )
    return replace(
        classification,
        processing_state="preserved_unparsed",
        message=None,
        reason_code=_PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE,
        attachment_classification=attachment_classification,
    )


def _validate_source_unit_classification(
    classification: _PstSourceUnitClassification,
) -> None:
    if not isinstance(classification, _PstSourceUnitClassification):
        raise ContractValidationError("PST source-unit classification is invalid")
    if not classification.source_local_key:
        raise ContractValidationError("PST source-unit classification lacks identity")
    if classification.source_size_bytes is not None and classification.source_size_bytes < 0:
        raise ContractValidationError("PST source-unit classification size is invalid")
    if classification.source_content_fingerprint is not None and not re.fullmatch(
        r"[0-9a-f]{64}",
        classification.source_content_fingerprint,
    ):
        raise ContractValidationError("PST source-unit classification fingerprint is invalid")
    if classification.processing_state not in {
        "failed",
        "parsed",
        "preserved_unparsed",
        "unsupported",
    }:
        raise ContractValidationError("PST source-unit classification state is invalid")
    if classification.content_type not in {
        "application/octet-stream",
        "message/rfc822",
    }:
        raise ContractValidationError("PST source-unit classification content type is invalid")
    requires_content_binding = (
        classification.processing_state in {"parsed", "unsupported"}
        or classification.reason_code == "pst_source_unit_parse_failed"
    )
    if requires_content_binding and (
        classification.source_size_bytes is None
        or classification.source_content_fingerprint is None
    ):
        raise ContractValidationError("PST source-unit classification binding is incomplete")
    if (
        classification.processing_state == "preserved_unparsed"
        and classification.source_size_bytes is None
        and classification.reason_code != _PST_MESSAGE_LIMIT_FAILURE_CODE
    ):
        raise ContractValidationError("PST source-unit classification size binding is missing")
    if classification.reason_code == _PST_MESSAGE_LIMIT_FAILURE_CODE and (
        classification.content_type != "message/rfc822"
        or classification.message is not None
        or classification.processing_state != "preserved_unparsed"
    ):
        raise ContractValidationError("PST message-limit classification is invalid")
    if classification.message is not None:
        if classification.processing_state != "parsed":
            raise ContractValidationError("PST source-unit classification message/state mismatch")
        if classification.content_type != "message/rfc822":
            raise ContractValidationError("PST source-unit classification message/media mismatch")


def _source_unit_classification_for_unit(
    unit: _ExportedTraversalUnit,
    *,
    config: _PstParserConfig,
    warnings: list[str],
    source_unit_classifications: dict[str, _PstSourceUnitClassification],
) -> _PstSourceUnitClassification:
    source_local_key = unit.source_local_key
    if not isinstance(source_local_key, str) or not source_local_key:
        raise ContractValidationError("PST source unit lacks a source-local key")
    _pst_strict_utf8_bytes(source_local_key)
    cached = source_unit_classifications.get(source_local_key)
    if cached is not None:
        _validate_source_unit_classification(cached)
        if cached.source_local_key != source_local_key:
            raise ContractValidationError("PST source-unit classification identity mismatch")
        try:
            _pst_assert_utf8_safe(
                {
                    "attachment_filename": cached.attachment_filename,
                    "attachment_mime_type": cached.attachment_mime_type,
                    "attachment_name_fingerprint": cached.attachment_name_fingerprint,
                    "attachment_classification": (
                        {
                            "text": cached.attachment_classification.text,
                            "extracted_text_segments": (
                                cached.attachment_classification.extracted_text_segments
                            ),
                            "failure_code": cached.attachment_classification.failure_code,
                        }
                        if cached.attachment_classification is not None
                        else None
                    ),
                }
            )
        except _PstTextEncodingError:
            cached = _mark_source_unit_text_unencodable(cached)
            source_unit_classifications[source_local_key] = cached
        return cached
    source_unit_kind = _exported_source_unit_kind(unit)
    if unit.path is None:
        attachment_classification = None
        attachment_filename = None
        attachment_mime_type = None
        attachment_name_fingerprint = None
        if source_unit_kind == _PST_SOURCE_UNIT_ATTACHMENT:
            basename = (
                _source_unit_basename_bytes(
                    canonical_relative_components=unit.canonical_relative_components,
                )
                or b""
            )
            attachment_mime_type = _readpst_sidecar_mime_type(basename)
            attachment_name_fingerprint = _readpst_sidecar_name_fingerprint(basename)
            safe_name_fingerprint = hashlib.sha256(
                _pst_strict_utf8_bytes(source_local_key)
            ).hexdigest()
            attachment_filename = (
                f"readpst-attachment-{safe_name_fingerprint[:16]}."
                f"{'html' if attachment_mime_type == 'text/html' else 'txt' if attachment_mime_type == 'text/plain' else 'eml' if attachment_mime_type == 'message/rfc822' else 'bin'}"
            )
            attachment_classification = _AttachmentClassification(
                processing_state="failed",
                text_extraction_state="failed",
                payload=None,
                text=None,
                extracted_text_segments=[],
                failure_code="read_failed",
            )
        classification = _PstSourceUnitClassification(
            source_local_key=source_local_key,
            source_size_bytes=None,
            source_content_fingerprint=None,
            content_type=(
                "message/rfc822"
                if source_unit_kind == _PST_SOURCE_UNIT_MESSAGE
                else "application/octet-stream"
            ),
            processing_state="failed",
            message=None,
            reason_code=unit.failure_code or "pst_source_unit_read_failed",
            attachment_classification=attachment_classification,
            attachment_filename=attachment_filename,
            attachment_mime_type=attachment_mime_type,
            attachment_name_fingerprint=attachment_name_fingerprint,
        )
    else:
        classification = _inventory_parse_file(
            unit.path,
            source_local_key=source_local_key,
            source_unit_kind=source_unit_kind,
            config=config,
            warnings=warnings,
        )
        try:
            _pst_assert_utf8_safe(
                {
                    "attachment_filename": classification.attachment_filename,
                    "attachment_mime_type": classification.attachment_mime_type,
                    "attachment_name_fingerprint": classification.attachment_name_fingerprint,
                    "attachment_classification": (
                        {
                            "text": classification.attachment_classification.text,
                            "extracted_text_segments": (
                                classification.attachment_classification.extracted_text_segments
                            ),
                            "failure_code": classification.attachment_classification.failure_code,
                        }
                        if classification.attachment_classification is not None
                        else None
                    ),
                }
            )
        except _PstTextEncodingError:
            classification = _mark_source_unit_text_unencodable(classification)
    _record_source_unit_classification(source_unit_classifications, classification)
    return classification


def _message_limit_classification(
    unit: _ExportedTraversalUnit,
) -> _PstSourceUnitClassification:
    """Return the no-I/O classification for an .eml excluded by max_messages."""

    return _PstSourceUnitClassification(
        source_local_key=unit.source_local_key,
        source_size_bytes=None,
        source_content_fingerprint=None,
        content_type="message/rfc822",
        processing_state="preserved_unparsed",
        message=None,
        reason_code=_PST_MESSAGE_LIMIT_FAILURE_CODE,
    )


def _message_limit_reached(
    source_unit_classifications: Mapping[str, _PstSourceUnitClassification],
) -> bool:
    return any(
        classification.reason_code == _PST_MESSAGE_LIMIT_FAILURE_CODE
        for classification in source_unit_classifications.values()
    )


def _readpst_sidecar_mapping_incomplete(
    traversal: _ExportedTraversal,
    *,
    source_unit_classifications: Mapping[str, _PstSourceUnitClassification],
    lookup_context: _PstExtractionLookupContext | None = None,
) -> bool:
    lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    for unit in traversal.units:
        if _exported_source_unit_kind(unit) != _PST_SOURCE_UNIT_ATTACHMENT:
            continue
        classification = source_unit_classifications.get(unit.source_local_key)
        if classification is None:
            return True
        location = _readpst_source_unit_location(
            unit,
            traversal=traversal,
            source_unit_classifications=source_unit_classifications,
            lookup_context=lookup_context,
        )
        if location.get("source_unit_attachment_state") != "linked":
            return True
    return False


def _source_unit_basename_bytes(
    *,
    path: Path | None = None,
    canonical_relative_components: tuple[bytes, ...] | None = None,
) -> bytes | None:
    if canonical_relative_components:
        return canonical_relative_components[-1]
    if path is None:
        return None
    return _canonical_component_bytes(path.name)


def _classify_readpst_separate_basename(name: bytes) -> str:
    """Classify one readpst ``-S`` leaf without reading its payload."""

    lowered = name.lower()
    item_count, separator, attachment_name = name.partition(b"-")
    if separator and item_count.isdigit() and attachment_name:
        return _PST_SOURCE_UNIT_ATTACHMENT
    if re.fullmatch(rb"[0-9]+\.(?:size|type)", lowered):
        return _PST_SOURCE_UNIT_SIDECAR
    if re.fullmatch(rb"[0-9]+", name) or lowered.endswith(b".eml"):
        return _PST_SOURCE_UNIT_MESSAGE
    return _PST_SOURCE_UNIT_UNKNOWN


def _exported_source_unit_kind(unit: _ExportedTraversalUnit) -> str:
    if unit.structure_kind == "exported_directory":
        return _PST_SOURCE_UNIT_UNKNOWN
    name = _source_unit_basename_bytes(
        path=unit.path,
        canonical_relative_components=unit.canonical_relative_components,
    )
    if name is None:
        return _PST_SOURCE_UNIT_UNKNOWN
    if _PST_EXPORTER_MODE != "readpst_separate":
        raise ContractValidationError("PST exporter mode is unsupported")
    return _classify_readpst_separate_basename(name)


def _source_unit_kind_for_path(candidate: Path) -> str:
    name = _source_unit_basename_bytes(path=candidate)
    if name is None:
        return _PST_SOURCE_UNIT_UNKNOWN
    return _classify_readpst_separate_basename(name)


def _readpst_sidecar_mime_type(name: bytes) -> str:
    """Infer only the closed text formats supported for readpst sidecars."""

    try:
        decoded = name.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return "application/octet-stream"
    suffix = decoded.rsplit(".", 1)[-1].casefold() if "." in decoded else ""
    if suffix in {"html", "htm", "xhtml"}:
        return "text/html"
    if suffix in {"txt", "text"}:
        return "text/plain"
    if suffix == "eml":
        return "message/rfc822"
    return "application/octet-stream"


def _readpst_sidecar_name_fingerprint(name: bytes) -> str:
    _item_count, separator, attachment_name = name.partition(b"-")
    value = attachment_name if separator else name
    try:
        return sha256_json(value.decode("utf-8", "strict"))
    except UnicodeDecodeError:
        return sha256_json(value.hex())


def _safe_readpst_sidecar_filename(
    *,
    content_fingerprint: str,
    mime_type: str,
) -> str:
    """Use an opaque, deterministic attachment label instead of an export name."""

    suffix = {
        "text/html": "html",
        "text/plain": "txt",
        "message/rfc822": "eml",
    }.get(mime_type, "bin")
    return f"readpst-attachment-{content_fingerprint[:16]}.{suffix}"


def _classify_readpst_sidecar_bytes(
    raw_bytes: bytes,
    *,
    mime_type: str,
    config: _PstParserConfig,
    warnings: list[str],
) -> _AttachmentClassification:
    if mime_type not in {"text/plain", "text/html"}:
        return _AttachmentClassification(
            processing_state="unsupported",
            text_extraction_state="unsupported",
            payload=raw_bytes,
            text=None,
            extracted_text_segments=[],
        )
    _append_warning_once(warnings, "pst_parser_attachment_charset_unknown")
    return _AttachmentClassification(
        processing_state="preserved_unparsed",
        text_extraction_state="failed",
        payload=raw_bytes if config.preserve_private_body_text else None,
        text=None,
        extracted_text_segments=[],
        failure_code="charset_unknown",
    )


def _inventory_parse_file(
    candidate: Path,
    *,
    source_local_key: str | None = None,
    source_unit_kind: str | None = None,
    config: _PstParserConfig,
    warnings: list[str],
) -> _PstSourceUnitClassification:
    source_local_key = source_local_key or f"file:{candidate.name}"
    source_unit_kind = source_unit_kind or _source_unit_kind_for_path(candidate)
    source_content_type = (
        "message/rfc822"
        if source_unit_kind == _PST_SOURCE_UNIT_MESSAGE
        else "application/octet-stream"
    )
    try:
        size = candidate.stat().st_size
    except Exception:
        if source_unit_kind == _PST_SOURCE_UNIT_ATTACHMENT:
            basename = _source_unit_basename_bytes(path=candidate) or b""
            failed = _AttachmentClassification(
                processing_state="failed",
                text_extraction_state="failed",
                payload=None,
                text=None,
                extracted_text_segments=[],
                failure_code="read_failed",
            )
            return _PstSourceUnitClassification(
                source_local_key=source_local_key,
                source_size_bytes=None,
                source_content_fingerprint=None,
                content_type=source_content_type,
                processing_state="failed",
                message=None,
                reason_code="pst_source_unit_read_failed",
                attachment_classification=failed,
                attachment_filename=(f"readpst-attachment-{source_local_key.rsplit(':', 1)[-1]}"),
                attachment_mime_type=_readpst_sidecar_mime_type(basename),
                attachment_name_fingerprint=_readpst_sidecar_name_fingerprint(basename),
            )
        return _PstSourceUnitClassification(
            source_local_key=source_local_key,
            source_size_bytes=None,
            source_content_fingerprint=None,
            content_type=source_content_type,
            processing_state="failed",
            message=None,
            reason_code="pst_source_unit_read_failed",
        )
    if source_unit_kind == _PST_SOURCE_UNIT_ATTACHMENT:
        basename = _source_unit_basename_bytes(path=candidate) or b""
        mime_type = _readpst_sidecar_mime_type(basename)
        name_fingerprint = _readpst_sidecar_name_fingerprint(basename)
        if size > config.max_message_file_bytes:
            oversized = _AttachmentClassification(
                processing_state="preserved_unparsed",
                text_extraction_state="too_large",
                payload=None,
                text=None,
                extracted_text_segments=[],
            )
            return _PstSourceUnitClassification(
                source_local_key=source_local_key,
                source_size_bytes=size,
                source_content_fingerprint=None,
                content_type=source_content_type,
                processing_state="preserved_unparsed",
                message=None,
                reason_code="pst_source_unit_size_limit",
                attachment_classification=oversized,
                attachment_filename=f"readpst-attachment-{source_local_key.rsplit(':', 1)[-1]}",
                attachment_mime_type=mime_type,
                attachment_name_fingerprint=name_fingerprint,
            )
        if mime_type in {"text/plain", "text/html"} and size > config.max_attachment_text_bytes:
            _append_warning_once(warnings, "pst_parser_attachment_text_limit_reached")
            oversized = _AttachmentClassification(
                processing_state="preserved_unparsed",
                text_extraction_state="too_large",
                payload=None,
                text=None,
                extracted_text_segments=[],
            )
            return _PstSourceUnitClassification(
                source_local_key=source_local_key,
                source_size_bytes=size,
                source_content_fingerprint=None,
                content_type=source_content_type,
                processing_state="preserved_unparsed",
                message=None,
                reason_code="pst_sidecar_attachment_text_limit",
                attachment_classification=oversized,
                attachment_filename=f"readpst-attachment-{source_local_key.rsplit(':', 1)[-1]}",
                attachment_mime_type=mime_type,
                attachment_name_fingerprint=name_fingerprint,
            )
        try:
            raw_bytes = candidate.read_bytes()
        except Exception:
            failed = _AttachmentClassification(
                processing_state="failed",
                text_extraction_state="failed",
                payload=None,
                text=None,
                extracted_text_segments=[],
                failure_code="read_failed",
            )
            return _PstSourceUnitClassification(
                source_local_key=source_local_key,
                source_size_bytes=size,
                source_content_fingerprint=None,
                content_type=source_content_type,
                processing_state="failed",
                message=None,
                reason_code="pst_source_unit_read_failed",
                attachment_classification=failed,
                attachment_filename=(f"readpst-attachment-{source_local_key.rsplit(':', 1)[-1]}"),
                attachment_mime_type=mime_type,
                attachment_name_fingerprint=name_fingerprint,
            )
        content_fingerprint = hashlib.sha256(raw_bytes).hexdigest()
        attachment_classification = _classify_readpst_sidecar_bytes(
            raw_bytes,
            mime_type=mime_type,
            config=config,
            warnings=warnings,
        )
        if attachment_classification.processing_state == "failed":
            reason_code = "pst_sidecar_attachment_decode_failed"
        elif attachment_classification.processing_state == "preserved_unparsed":
            reason_code = (
                "pst_sidecar_attachment_charset_unknown"
                if attachment_classification.failure_code == "charset_unknown"
                else "pst_sidecar_attachment_text_limit"
            )
        elif attachment_classification.processing_state == "unsupported":
            reason_code = "pst_source_unit_unsupported"
        else:
            reason_code = None
        return _PstSourceUnitClassification(
            source_local_key=source_local_key,
            source_size_bytes=size,
            source_content_fingerprint=content_fingerprint,
            content_type=source_content_type,
            processing_state=attachment_classification.processing_state,
            message=None,
            reason_code=reason_code,
            attachment_classification=attachment_classification,
            attachment_filename=_safe_readpst_sidecar_filename(
                content_fingerprint=content_fingerprint,
                mime_type=mime_type,
            ),
            attachment_mime_type=mime_type,
            attachment_name_fingerprint=name_fingerprint,
        )
    if source_unit_kind != _PST_SOURCE_UNIT_MESSAGE:
        if size > config.max_message_file_bytes:
            return _PstSourceUnitClassification(
                source_local_key=source_local_key,
                source_size_bytes=size,
                source_content_fingerprint=None,
                content_type=source_content_type,
                processing_state="preserved_unparsed",
                message=None,
                reason_code="pst_source_unit_size_limit",
            )
        try:
            raw_bytes = candidate.read_bytes()
        except Exception:
            return _PstSourceUnitClassification(
                source_local_key=source_local_key,
                source_size_bytes=size,
                source_content_fingerprint=None,
                content_type=source_content_type,
                processing_state="failed",
                message=None,
                reason_code="pst_source_unit_read_failed",
            )
        return _PstSourceUnitClassification(
            source_local_key=source_local_key,
            source_size_bytes=size,
            source_content_fingerprint=hashlib.sha256(raw_bytes).hexdigest(),
            content_type=source_content_type,
            processing_state="unsupported",
            message=None,
            reason_code="pst_source_unit_unsupported",
        )
    if size > config.max_message_file_bytes:
        return _PstSourceUnitClassification(
            source_local_key=source_local_key,
            source_size_bytes=size,
            source_content_fingerprint=None,
            content_type=source_content_type,
            processing_state="preserved_unparsed",
            message=None,
            reason_code="pst_source_unit_size_limit",
        )
    try:
        raw_bytes = candidate.read_bytes()
    except Exception:
        return _PstSourceUnitClassification(
            source_local_key=source_local_key,
            source_size_bytes=size,
            source_content_fingerprint=None,
            content_type=source_content_type,
            processing_state="failed",
            message=None,
            reason_code="pst_source_unit_read_failed",
        )
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    except Exception:
        return _PstSourceUnitClassification(
            source_local_key=source_local_key,
            source_size_bytes=size,
            source_content_fingerprint=hashlib.sha256(raw_bytes).hexdigest(),
            content_type=source_content_type,
            processing_state="failed",
            message=None,
            reason_code="pst_source_unit_parse_failed",
        )
    return _PstSourceUnitClassification(
        source_local_key=source_local_key,
        source_size_bytes=size,
        source_content_fingerprint=hashlib.sha256(raw_bytes).hexdigest(),
        content_type="message/rfc822",
        processing_state="parsed",
        message=message,
    )


def _source_unit_parser_warnings(
    classification: _PstSourceUnitClassification,
) -> tuple[str, ...]:
    if classification.reason_code == "pst_source_unit_size_limit":
        return ("pst_parser_large_message_file_skipped",)
    if classification.reason_code in {
        "pst_source_unit_read_failed",
        "pst_source_unit_parse_failed",
    }:
        return ("pst_parser_message_file_skipped",)
    if classification.reason_code == _PST_SOURCE_UNIT_TEXT_UNENCODABLE_CODE:
        return ("pst_parser_source_unit_text_unencodable",)
    return ()


def _interpret_chronology(
    message: EmailMessage,
    *,
    warnings: list[str] | None = None,
) -> _MessageChronology:
    chronology_occurrences: list[_ChronologyOccurrence] = []
    kind_ordinals = {"date": 0, "received": 0}
    physical_ordinal = 0
    parser_defect = bool(getattr(message, "defects", ()))
    for header_ordinal, (header_name, value) in enumerate(
        _pst_raw_header_items(message),
        start=1,
    ):
        kind = _pst_safe_header_name(header_name)
        if kind not in kind_ordinals:
            continue
        kind_ordinals[kind] += 1
        physical_ordinal += 1
        safe_value = _pst_safe_text(value)
        if safe_value is None:
            occurrence = _ChronologyOccurrence(
                kind=kind,
                header_ordinal=header_ordinal,
                physical_ordinal=physical_ordinal,
                kind_ordinal=kind_ordinals[kind],
                raw_value_fingerprint=_pst_raw_value_fingerprint(value),
                parse_status="malformed",
                timezone_status="unavailable",
                normalized_instant=None,
                safe_error_code=f"pst_chronology_{kind}_unencodable",
            )
            if warnings is not None:
                _append_warning_once(warnings, occurrence.safe_error_code)
            chronology_occurrences.append(occurrence)
            continue
        occurrence = _interpret_chronology_occurrence(
            kind,
            safe_value,
            header_ordinal=header_ordinal,
            physical_ordinal=physical_ordinal,
            kind_ordinal=kind_ordinals[kind],
            parser_defect=parser_defect,
            warnings=warnings,
        )
        chronology_occurrences.append(occurrence)

    date_occurrences = tuple(
        occurrence for occurrence in chronology_occurrences if occurrence.kind == "date"
    )
    received_occurrences = tuple(
        occurrence for occurrence in chronology_occurrences if occurrence.kind == "received"
    )
    date_state, authored_sent_at = _derive_chronology_date_summary(
        date_occurrences,
        parser_defect=parser_defect,
    )
    return _MessageChronology(
        date_state=date_state,
        occurrences=tuple(chronology_occurrences),
        date_occurrences=date_occurrences,
        received_occurrences=received_occurrences,
        authored_sent_at=authored_sent_at,
        parser_defect=parser_defect,
    )


def _derive_chronology_date_summary(
    date_occurrences: Sequence[_ChronologyOccurrence],
    *,
    parser_defect: bool,
) -> tuple[str, str | None]:
    """Derive authored Date authority only from typed chronology truth."""

    valid_dates = [
        occurrence.normalized_instant
        for occurrence in date_occurrences
        if occurrence.normalized_instant is not None
        and occurrence.parse_status == "parsed"
        and occurrence.timezone_status == "offset_aware"
    ]
    if not date_occurrences:
        date_state = "missing"
    elif len(date_occurrences) == 1 and len(valid_dates) == 1 and not parser_defect:
        date_state = "authoritative"
    elif (
        len(valid_dates) == len(date_occurrences)
        and len({_utc_comparison_key(value).isoformat() for value in valid_dates}) == 1
    ):
        date_state = "multiple_equivalent"
    elif (
        len(valid_dates) == len(date_occurrences)
        and len({_utc_comparison_key(value).isoformat() for value in valid_dates}) > 1
    ):
        date_state = "conflicting"
    else:
        date_state = "unresolved"
    authored_sent_at = (
        date_occurrences[0].normalized_instant if date_state == "authoritative" else None
    )
    return date_state, authored_sent_at


def _interpret_chronology_occurrence(
    kind: str,
    value: str,
    *,
    header_ordinal: int,
    physical_ordinal: int,
    kind_ordinal: int,
    parser_defect: bool,
    warnings: list[str] | None,
) -> _ChronologyOccurrence:
    raw_source_value = value
    raw_value = raw_source_value.strip()
    fingerprint = sha256_json(raw_source_value)
    prefix = f"pst_chronology_{kind}"
    if not raw_value:
        parse_status = "empty"
        timezone_status = "unavailable"
        normalized_instant = None
        safe_error_code = f"{prefix}_empty"
    else:
        parse_value = _received_chronology_tail(raw_value) if kind == "received" else raw_value
        parsed, parse_status, timezone_status, normalized_instant, timezone_error = (
            _parse_strict_chronology_value(parse_value)
        )
        if parse_status == "malformed":
            parse_status = "malformed"
            timezone_status = "unavailable"
            normalized_instant = None
            safe_error_code = f"{prefix}_malformed"
        elif parser_defect:
            parse_status = "parser_defect"
            timezone_status = "unavailable"
            normalized_instant = None
            safe_error_code = f"{prefix}_parser_defect"
        else:
            parse_status = "parsed"
            safe_error_code = timezone_error
    if warnings is not None and safe_error_code is not None:
        _append_warning_once(warnings, safe_error_code)
    return _ChronologyOccurrence(
        kind=kind,
        header_ordinal=header_ordinal,
        physical_ordinal=physical_ordinal,
        kind_ordinal=kind_ordinal,
        raw_value_fingerprint=fingerprint,
        parse_status=parse_status,
        timezone_status=timezone_status,
        normalized_instant=normalized_instant,
        safe_error_code=safe_error_code,
    )


_CHRONOLOGY_DATE_RE = re.compile(
    r"^(?:(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*,\s*)?"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(?P<year>\d{2,4})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2}))?"
    r"(?:\s+(?P<zone>[+-]\d{4}|[A-Za-z]{1,5}))?$",
    re.IGNORECASE,
)
_CHRONOLOGY_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _strip_rfc_chronology_comments(value: str) -> str | None:
    """Remove RFC CFWS comments while rejecting unsafe syntax."""

    output: list[str] = []
    comment_depth = 0
    escaped = False
    quoted = False
    index = 0
    while index < len(value):
        character = value[index]
        if comment_depth:
            if escaped:
                if character in "\r\n" or ord(character) < 32:
                    return None
                escaped = False
                index += 1
                continue
            if character == "\\":
                escaped = True
                index += 1
                continue
            if character == "(":
                comment_depth += 1
                index += 1
                continue
            if character == ")":
                comment_depth -= 1
                if comment_depth == 0:
                    output.append(" ")
                index += 1
                continue
            if character == "\r":
                if index + 2 >= len(value) or value[index + 1] != "\n":
                    return None
                if value[index + 2] not in " \t":
                    return None
                index += 3
                continue
            if character == "\n" or ord(character) < 32 and character != "\t":
                return None
            index += 1
            continue

        if quoted:
            if character == "\\":
                output.append(character)
                if index + 1 >= len(value):
                    return None
                output.append(value[index + 1])
                index += 1
            elif character == '"':
                quoted = False
                output.append(character)
            elif character == "\r":
                if index + 2 >= len(value) or value[index + 1] != "\n":
                    return None
                if value[index + 2] not in " \t":
                    return None
                output.append(" ")
                index += 2
            elif character == "\n" or ord(character) < 32 and character != "\t":
                return None
            else:
                output.append(character)
        elif character == "(":
            comment_depth = 1
            output.append(" ")
        elif character == '"':
            quoted = True
            output.append(character)
        elif character == "\\":
            return None
        elif character == "\r":
            if index + 2 >= len(value) or value[index + 1] != "\n":
                return None
            if value[index + 2] not in " \t":
                return None
            output.append(" ")
            index += 2
        elif character == "\n" or ord(character) < 32 and character != "\t":
            return None
        elif character in " \t":
            if not output or output[-1] != " ":
                output.append(" ")
        else:
            output.append(character)
        index += 1

    if comment_depth or escaped or quoted:
        return None
    return re.sub(r" +", " ", "".join(output)).strip()


def _received_chronology_tail(value: str) -> str | None:
    """Return the sole top-level semicolon-delimited Received date tail."""

    comment_depth = 0
    escaped = False
    quoted = False
    domain_literal = False
    domain_escaped = False
    separator_indices: list[int] = []
    index = 0
    while index < len(value):
        character = value[index]
        if comment_depth:
            if escaped:
                if character in "\r\n":
                    return None
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "(":
                comment_depth += 1
            elif character == ")":
                comment_depth -= 1
            index += 1
            continue
        if domain_literal:
            if domain_escaped:
                if character not in " \t" and not 33 <= ord(character) <= 126:
                    return None
                domain_escaped = False
            elif character == "\\":
                domain_escaped = True
                index += 1
                continue
            elif character == "[":
                return None
            elif character == "]":
                domain_literal = False
                index += 1
                continue
            elif character == "\r":
                if index + 2 >= len(value) or value[index + 1] != "\n":
                    return None
                if value[index + 2] not in " \t":
                    return None
                index += 3
                continue
            elif character == "\n" or ord(character) < 32 and character != "\t":
                return None
            index += 1
            continue
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            index += 1
            continue
        if character == "(":
            comment_depth = 1
        elif character == ")":
            return None
        elif character == '"':
            quoted = True
        elif character == "[":
            domain_literal = True
        elif character == "\\":
            return None
        elif character == "\r":
            if index + 2 >= len(value) or value[index + 1] != "\n":
                return None
            if value[index + 2] not in " \t":
                return None
            index += 2
        elif character == "\n" or ord(character) < 32 and character != "\t":
            return None
        elif character == ";":
            separator_indices.append(index)
        index += 1
    if (
        comment_depth
        or escaped
        or quoted
        or domain_literal
        or domain_escaped
        or len(separator_indices) != 1
    ):
        return None
    separator_index = separator_indices[0]
    prefix = _strip_rfc_chronology_comments(value[:separator_index])
    if prefix is None:
        prefix = value[:separator_index].strip()
    tail = _strip_rfc_chronology_comments(value[separator_index + 1 :])
    if not prefix or not tail:
        return None
    return tail


def _parse_strict_chronology_value(
    value: str | None,
) -> tuple[datetime | None, str, str, str | None, str | None]:
    """Parse a complete Date/Received date value without permissive prefix parsing."""

    if value is None:
        return None, "malformed", "unavailable", None, None
    normalized = _strip_rfc_chronology_comments(value)
    if not normalized:
        return None, "malformed", "unavailable", None, None
    match = _CHRONOLOGY_DATE_RE.fullmatch(normalized)
    if match is None:
        return None, "malformed", "unavailable", None, None
    try:
        year_text = match.group("year")
        year = int(year_text)
        if len(year_text) == 2:
            year += 2000 if year < 69 else 1900
        month = _CHRONOLOGY_MONTHS[match.group("month").casefold()]
        day = int(match.group("day"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        second = int(match.group("second") or "0")
        zone = match.group("zone")
        if zone is None:
            datetime(year, month, day, hour, minute, second)
            return None, "parsed", "missing", None, "pst_chronology_timezone_missing"
        if zone[0] not in "+-":
            if not (
                len(zone) == 1 and zone.casefold() in "abcdefghiklmnopqrstuvwxyz"
            ) and zone.casefold() not in {
                "ut",
                "gmt",
                "est",
                "edt",
                "cst",
                "cdt",
                "mst",
                "mdt",
                "pst",
                "pdt",
            }:
                return None, "malformed", "unavailable", None, None
            datetime(year, month, day, hour, minute, second)
            return (
                None,
                "parsed",
                "ambiguous_named_zone",
                None,
                ("pst_chronology_timezone_ambiguous"),
            )
        offset_hours = int(zone[1:3])
        offset_minutes = int(zone[3:5])
        if offset_hours > 23 or offset_minutes > 59:
            return None, "parsed", "invalid", None, "pst_chronology_timezone_invalid"
        if zone == "-0000":
            datetime(year, month, day, hour, minute, second)
            return None, "parsed", "unknown", None, "pst_chronology_timezone_unknown"
        parsed = datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=timezone(
                timedelta(
                    minutes=(offset_hours * 60 + offset_minutes) * (1 if zone[0] == "+" else -1)
                )
            ),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, "malformed", "unavailable", None, None
    return parsed, "parsed", "offset_aware", parsed.isoformat(), None


def _append_chronology_specs(
    specs: list[_PstInventorySpec],
    *,
    extraction_input: ExtractionInput,
    message: EmailMessage,
    parent_source_local_key: str,
    next_ordinal: int,
) -> int:
    chronology = _interpret_chronology(message)
    ordinal = next_ordinal
    occurrences = sorted(
        (*chronology.date_occurrences, *chronology.received_occurrences),
        key=lambda occurrence: occurrence.physical_ordinal,
    )
    for occurrence in occurrences:
        key = (
            f"{parent_source_local_key}:chronology:" f"{occurrence.kind}:{occurrence.kind_ordinal}"
        )
        specs.append(
            _PstInventorySpec(
                source_local_key=key,
                ordinal=ordinal,
                structure_kind=f"chronology_{occurrence.kind}_variant",
                content_type="text/header",
                processing_state="parsed",
                parent_source_local_key=parent_source_local_key,
                source_observation_id=_pst_source_observation_id(
                    extraction_input=extraction_input,
                    source_local_key=key,
                ),
                location={
                    "chronology_kind": occurrence.kind,
                    "chronology_ordinal": occurrence.kind_ordinal,
                    "physical_ordinal": occurrence.physical_ordinal,
                    "header_ordinal": occurrence.header_ordinal,
                    "raw_value_fingerprint": occurrence.raw_value_fingerprint,
                    "parse_status": occurrence.parse_status,
                    "timezone_status": occurrence.timezone_status,
                    "chronology_value": occurrence.normalized_instant,
                    "normalized_instant": occurrence.normalized_instant,
                    "safe_error_code": occurrence.safe_error_code,
                    "date_state": chronology.date_state,
                },
            )
        )
        ordinal += 1
    return ordinal


def _attachment_identity_fields(
    part: EmailMessage,
    classification: _AttachmentClassification,
    *,
    attachment_ordinal: int,
    config: _PstParserConfig,
    metadata: _MimePartMetadata | None = None,
) -> dict[str, Any]:
    """Return the closed attachment facts shared by MIME and mail projection."""

    metadata = metadata or _mime_part_metadata(part)
    filename = _mime_attachment_filename(metadata, attachment_ordinal=attachment_ordinal)
    payload = classification.payload
    size_bytes = len(payload) if isinstance(payload, bytes) else None
    content_hash: str | None = None
    if isinstance(payload, bytes) and len(payload) <= config.max_attachment_hash_bytes:
        content_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
    return {
        "attachment_id": stable_resource_contract_id(
            "mailatt",
            "PstAttachment",
            {
                "filename": filename,
                "content_hash": content_hash,
                "size_bytes": size_bytes,
                "attachment_index": attachment_ordinal,
            },
        ),
        "attachment_filename": filename,
        "attachment_name_fingerprint": _mime_attachment_name_fingerprint(metadata),
        "attachment_content_fingerprint": (
            content_hash.removeprefix("sha256:") if content_hash is not None else None
        ),
        "attachment_size_bytes": size_bytes,
        "attachment_source_byte_count": size_bytes,
        "attachment_processing_state": classification.processing_state,
        "attachment_text_extraction_state": classification.text_extraction_state,
        "attachment_failure_code": classification.failure_code,
        "attachment_source_char_count": (
            len(classification.text)
            if classification.processing_state == "parsed" and isinstance(classification.text, str)
            else None
        ),
        "attachment_stored_char_count": sum(
            len(segment) for segment in classification.extracted_text_segments
        ),
        "attachment_stored_byte_count": sum(
            len(segment.encode("utf-8")) for segment in classification.extracted_text_segments
        ),
        "attachment_text_segments_fingerprint": sha256_json(
            list(classification.extracted_text_segments)
        ),
    }


def _parsed_attachment_identity_fields(attachment: _ParsedAttachment) -> dict[str, Any]:
    """Return the same safe fields for an already classified attachment."""

    return {
        "attachment_id": attachment.attachment_id,
        "attachment_filename": attachment.filename,
        "attachment_name_fingerprint": attachment.source_name_fingerprint,
        "attachment_content_fingerprint": (
            attachment.content_hash.removeprefix("sha256:")
            if attachment.content_hash is not None
            else None
        ),
        "attachment_size_bytes": attachment.size_bytes,
        "attachment_source_byte_count": attachment.size_bytes,
        "attachment_processing_state": attachment.processing_state,
        "attachment_text_extraction_state": attachment.text_extraction_state,
        "attachment_failure_code": attachment.failure_code,
        "attachment_source_char_count": attachment.source_char_count,
        "attachment_stored_char_count": attachment.stored_char_count,
        "attachment_stored_byte_count": sum(
            len(segment.encode("utf-8")) for segment in attachment.extracted_text_segments
        ),
        "attachment_text_segments_fingerprint": sha256_json(
            list(attachment.extracted_text_segments)
        ),
    }


def _mime_inventory_specs(
    message: EmailMessage,
    *,
    extraction_input: ExtractionInput,
    config: _PstParserConfig,
    parent_source_local_key: str,
    next_ordinal: int,
    warnings: list[str],
) -> tuple[list[_PstInventorySpec], list[dict[str, Any]]]:
    specs: list[_PstInventorySpec] = []
    table_specs: list[dict[str, Any]] = []
    next_inventory_ordinal = next_ordinal

    def walk_message(
        message_context: EmailMessage,
        *,
        message_parent_key: str,
        message_lineage_key: str,
        occurrence_lineage: tuple[str, ...],
        inherited_attachment_ordinal: int | None = None,
        embedded_message_depth: int = 0,
    ) -> None:
        chronology = _interpret_chronology(message_context)
        metadata_cache: dict[int, _MimePartMetadata] = {}
        body_classifications: dict[int, _BodyLeafClassification] = {}
        for body_part in _iter_outer_content_parts(
            message_context,
            metadata_cache=metadata_cache,
        ):
            classification = _classify_body_leaf(
                body_part,
                warnings=warnings,
                metadata=_mime_part_metadata(body_part, cache=metadata_cache),
            )
            if classification is not None:
                body_classifications[id(body_part)] = classification
        next_mime_ordinal = 0
        next_attachment_ordinal = 0

        def visit(
            part: EmailMessage,
            *,
            parent_key: str,
            parent_is_alternative: bool,
        ) -> None:
            nonlocal next_attachment_ordinal, next_inventory_ordinal, next_mime_ordinal
            mime_ordinal = next_mime_ordinal
            next_mime_ordinal += 1
            key = f"{message_parent_key}:mime:{mime_ordinal}"
            metadata = _mime_part_metadata(part, cache=metadata_cache)
            content_type = metadata.content_type
            is_attachment = _is_attachment_part(part, metadata=metadata)
            attachment_ordinal = None
            if is_attachment:
                next_attachment_ordinal += 1
                attachment_ordinal = next_attachment_ordinal
            attachment_classification = None
            attachment_identity: dict[str, Any] = {}
            mime_content_failure_code: str | None = None
            if is_attachment:
                structure_kind = (
                    "inline_attachment_occurrence"
                    if metadata.content_disposition == "inline"
                    else "regular_attachment_occurrence"
                )
                classification_warnings: list[str] = []
                attachment_classification = _classify_attachment_part(
                    part,
                    config=config,
                    warnings=classification_warnings,
                    embedded_message_depth=embedded_message_depth,
                    metadata=metadata,
                )
                for warning in classification_warnings:
                    _append_warning_once(warnings, warning)
                state = attachment_classification.processing_state
                attachment_identity = _attachment_identity_fields(
                    part,
                    attachment_classification,
                    attachment_ordinal=attachment_ordinal,
                    config=config,
                    metadata=metadata,
                )
            elif metadata.is_multipart:
                structure_kind = "mime_container"
                state = "preserved_unparsed" if metadata.failed else "parsed"
            else:
                structure_kind = (
                    "mime_alternative"
                    if parent_is_alternative and content_type in {"text/plain", "text/html"}
                    else "mime_leaf"
                )
                body_classification = body_classifications.get(id(part))
                if body_classification is not None:
                    state = body_classification.processing_state
                else:
                    try:
                        part.get_content()
                    except Exception:
                        state = "preserved_unparsed"
                        mime_content_failure_code = _PST_MIME_CONTENT_ACCESS_FAILURE_CODE
                    else:
                        state = "parsed"
            source_observation_id = _pst_source_observation_id(
                extraction_input=extraction_input,
                source_local_key=key,
            )
            location = {
                "mime_ordinal": mime_ordinal,
                "content_disposition": metadata.content_disposition,
                "filename_present": metadata.filename is not None,
            }
            if metadata.failed:
                location["mime_metadata_failure_code"] = _PST_MIME_METADATA_FAILURE_CODE
            if mime_content_failure_code is not None:
                location["mime_content_access_failure_code"] = mime_content_failure_code
            if attachment_ordinal is not None:
                location["attachment_ordinal"] = attachment_ordinal
                location.update(attachment_identity)
            if (
                attachment_classification is not None
                and attachment_classification.failure_code is not None
            ):
                location["attachment_failure_code"] = attachment_classification.failure_code
            body_classification = body_classifications.get(id(part))
            if body_classification is not None and body_classification.failure_code is not None:
                location["body_failure_code"] = body_classification.failure_code
            specs.append(
                _PstInventorySpec(
                    source_local_key=key,
                    ordinal=next_inventory_ordinal,
                    structure_kind=structure_kind,
                    content_type=content_type,
                    processing_state=state,
                    parent_source_local_key=parent_key,
                    source_observation_id=source_observation_id,
                    location=location,
                )
            )
            next_inventory_ordinal += 1
            if attachment_classification is not None:
                textual_content = (
                    attachment_classification.text
                    if attachment_classification.processing_state == "parsed"
                    else ""
                )
            elif body_classification is not None:
                textual_content = (
                    body_classification.text
                    if body_classification.processing_state == "parsed"
                    else ""
                )
            else:
                try:
                    textual_content = part.get_content() if not metadata.is_multipart else ""
                except Exception:
                    textual_content = ""
            html_events: list[dict[str, Any]] = []
            if content_type == "text/html" and not metadata.is_multipart:
                if attachment_classification is not None:
                    html = attachment_classification.text or ""
                elif body_classification is not None:
                    html = body_classification.text or ""
                else:
                    try:
                        html = part.get_content()
                    except Exception:
                        html = ""
                if isinstance(html, str) and (
                    (
                        attachment_classification is None
                        and (
                            body_classification is None
                            or body_classification.processing_state == "parsed"
                        )
                    )
                    or (
                        attachment_classification is not None
                        and attachment_classification.processing_state == "parsed"
                    )
                ):
                    html_events = _extract_html_structure_events(html)
            if html_events:
                for event in html_events:
                    if event["kind"] == "quote":
                        quote_ordinal = int(event["quote_ordinal"])
                        quote_key = f"{key}:quote:{quote_ordinal}"
                        parent_quote_ordinal = event["parent_quote_ordinal"]
                        quote_parent_key = (
                            f"{key}:quote:{parent_quote_ordinal}"
                            if parent_quote_ordinal is not None
                            else key
                        )
                        specs.append(
                            _PstInventorySpec(
                                source_local_key=quote_key,
                                ordinal=next_inventory_ordinal,
                                structure_kind="quote_forwarded_structure",
                                content_type=content_type,
                                processing_state="parsed",
                                parent_source_local_key=quote_parent_key,
                                source_observation_id=_pst_source_observation_id(
                                    extraction_input=extraction_input,
                                    source_local_key=quote_key,
                                ),
                                location={
                                    "quote_ordinal": quote_ordinal,
                                    "quote_depth": int(event["quote_depth"]),
                                },
                            )
                        )
                        next_inventory_ordinal += 1
                        continue
                    table_index = int(event["table_ordinal"])
                    table = event["table"]
                    table_key = f"{key}:table:{table_index}"
                    parent_quote_ordinal = event["quote_ordinal"]
                    table_parent_key = (
                        f"{key}:quote:{parent_quote_ordinal}"
                        if parent_quote_ordinal is not None
                        else key
                    )
                    table_observation_id = _pst_source_observation_id(
                        extraction_input=extraction_input,
                        source_local_key=table_key,
                    )
                    table_location = {
                        "table_ordinal": table_index,
                        "mime_ordinal": mime_ordinal,
                        "quoted_depth": table["quoted_depth"],
                    }
                    effective_attachment_ordinal = (
                        attachment_ordinal
                        if attachment_ordinal is not None
                        else inherited_attachment_ordinal
                    )
                    if effective_attachment_ordinal is not None:
                        table_location["attachment_ordinal"] = effective_attachment_ordinal
                    specs.append(
                        _PstInventorySpec(
                            source_local_key=table_key,
                            ordinal=next_inventory_ordinal,
                            structure_kind="html_table",
                            content_type="text/html",
                            processing_state="parsed",
                            parent_source_local_key=table_parent_key,
                            source_observation_id=table_observation_id,
                            location=table_location,
                        )
                    )
                    next_inventory_ordinal += 1
                    table_specs.append(
                        {
                            "source_local_key": table_key,
                            "source_observation_id": table_observation_id,
                            "table": table,
                            "table_ordinal": table_index,
                            "mime_ordinal": mime_ordinal,
                            "attachment_ordinal": (
                                attachment_ordinal
                                if attachment_ordinal is not None
                                else inherited_attachment_ordinal
                            ),
                            "quoted_depth": table["quoted_depth"],
                            "message_lineage_id": message_lineage_key,
                            "occurrence_lineage": occurrence_lineage,
                            "sender_fingerprint": sha256_json(
                                _safe_mail_text(
                                    message_context.get("from") or "",
                                    "sender",
                                )
                            ),
                            "observed_at": chronology.authored_sent_at,
                            "date_state": chronology.date_state,
                        }
                    )
            else:
                for quote_ordinal, quote_depth in enumerate(
                    _plain_quote_occurrences(textual_content),
                    start=1,
                ):
                    quote_key = f"{key}:quote:{quote_ordinal}"
                    specs.append(
                        _PstInventorySpec(
                            source_local_key=quote_key,
                            ordinal=next_inventory_ordinal,
                            structure_kind="quote_forwarded_structure",
                            content_type=content_type,
                            processing_state="parsed",
                            parent_source_local_key=key,
                            source_observation_id=_pst_source_observation_id(
                                extraction_input=extraction_input,
                                source_local_key=quote_key,
                            ),
                            location={
                                "quote_ordinal": quote_ordinal,
                                "quote_depth": quote_depth,
                            },
                        )
                    )
                    next_inventory_ordinal += 1
            if (
                is_attachment
                and content_type == "message/rfc822"
                and attachment_classification is not None
                and attachment_classification.embedded_message is not None
            ):
                child_message_key = f"{key}:message"
                specs.append(
                    _PstInventorySpec(
                        source_local_key=child_message_key,
                        ordinal=next_inventory_ordinal,
                        structure_kind="attached_message_occurrence",
                        content_type="message/rfc822",
                        processing_state="parsed",
                        parent_source_local_key=key,
                        source_observation_id=_pst_source_observation_id(
                            extraction_input=extraction_input,
                            source_local_key=child_message_key,
                        ),
                    )
                )
                next_inventory_ordinal += 1
                child_message = attachment_classification.embedded_message
                next_inventory_ordinal = _append_chronology_specs(
                    specs,
                    extraction_input=extraction_input,
                    message=child_message,
                    parent_source_local_key=child_message_key,
                    next_ordinal=next_inventory_ordinal,
                )
                walk_message(
                    child_message,
                    message_parent_key=child_message_key,
                    message_lineage_key=child_message_key,
                    occurrence_lineage=(
                        *occurrence_lineage,
                        key,
                        child_message_key,
                    ),
                    inherited_attachment_ordinal=attachment_ordinal,
                    embedded_message_depth=embedded_message_depth + 1,
                )
                return
            if metadata.is_multipart:
                child_is_alternative = content_type == "multipart/alternative"
                for child in metadata.children:
                    visit(
                        child,
                        parent_key=key,
                        parent_is_alternative=child_is_alternative,
                    )

        visit(message_context, parent_key=message_parent_key, parent_is_alternative=False)

    walk_message(
        message,
        message_parent_key=parent_source_local_key,
        message_lineage_key=parent_source_local_key,
        occurrence_lineage=(parent_source_local_key,),
    )
    return specs, table_specs


def _mime_part_metadata(
    part: EmailMessage,
    *,
    cache: dict[int, _MimePartMetadata] | None = None,
) -> _MimePartMetadata:
    cache_key = id(part)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    failures: list[str] = []
    try:
        raw_content_type = part.get_content_type()
    except Exception:
        raw_content_type = None
        failures.append("get_content_type")
    content_type = _pst_safe_text(raw_content_type)
    if content_type is None or not content_type.strip():
        content_type = "application/octet-stream"
        if "get_content_type" not in failures:
            failures.append("get_content_type")
    else:
        content_type = content_type.strip()

    try:
        raw_disposition = part.get_content_disposition()
    except Exception:
        raw_disposition = None
        failures.append("get_content_disposition")
    if raw_disposition is None:
        content_disposition = None
    else:
        content_disposition = _pst_safe_text(raw_disposition)
        if content_disposition is None:
            failures.append("get_content_disposition")
        else:
            content_disposition = content_disposition.strip().lower() or None

    try:
        raw_filename = part.get_filename()
    except Exception:
        raw_filename = None
        failures.append("get_filename")
    if raw_filename is None:
        filename = None
    else:
        filename = _pst_safe_text(raw_filename)
        if filename is None:
            failures.append("get_filename")

    try:
        is_multipart = bool(part.is_multipart())
    except Exception:
        is_multipart = False
        failures.append("is_multipart")

    children: tuple[EmailMessage, ...] = ()
    if is_multipart:
        try:
            children = tuple(part.iter_parts())
        except Exception:
            failures.append("iter_parts")

    metadata = _MimePartMetadata(
        content_type=content_type,
        content_disposition=content_disposition,
        filename=filename,
        is_multipart=is_multipart,
        children=children,
        failure_fields=tuple(dict.fromkeys(failures)),
    )
    if cache is not None:
        cache[cache_key] = metadata
    return metadata


def _mime_attachment_filename(
    metadata: _MimePartMetadata,
    *,
    attachment_ordinal: int,
) -> str:
    if metadata.filename is not None:
        return _safe_mail_text(metadata.filename, "filename")
    if "get_filename" in metadata.failure_fields:
        return f"opaque_attachment_{attachment_ordinal}"
    return f"attachment-{attachment_ordinal}"


def _mime_attachment_name_fingerprint(metadata: _MimePartMetadata) -> str:
    if "get_filename" in metadata.failure_fields:
        return sha256_json(
            {
                "policy": _PST_MIME_METADATA_ACCESS_POLICY,
                "field": "filename",
                "state": "unresolved",
            }
        )
    return _pst_raw_value_fingerprint(metadata.filename or "")


def _is_attachment_part(
    part: EmailMessage,
    *,
    metadata: _MimePartMetadata | None = None,
) -> bool:
    metadata = metadata or _mime_part_metadata(part)
    return metadata.content_type == "message/rfc822" or (
        not metadata.is_multipart
        and (
            metadata.failed
            or metadata.content_disposition in {"attachment", "inline"}
            or metadata.filename is not None
        )
    )


def _iter_outer_content_parts(
    message: EmailMessage,
    *,
    metadata_cache: dict[int, _MimePartMetadata] | None = None,
) -> Iterable[EmailMessage]:
    def visit(part: EmailMessage) -> Iterable[EmailMessage]:
        metadata = _mime_part_metadata(part, cache=metadata_cache)
        if part is not message and metadata.content_type == "message/rfc822":
            return
        if metadata.is_multipart:
            for child in metadata.children:
                yield from visit(child)
        else:
            yield part

    yield from visit(message)


def _iter_outer_attachment_parts(
    message: EmailMessage,
    *,
    metadata_cache: dict[int, _MimePartMetadata] | None = None,
) -> Iterable[EmailMessage]:
    def visit(part: EmailMessage, *, is_root: bool = False) -> Iterable[EmailMessage]:
        metadata = _mime_part_metadata(part, cache=metadata_cache)
        if not is_root and _is_attachment_part(part, metadata=metadata):
            yield part
            return
        if metadata.is_multipart:
            for child in metadata.children:
                yield from visit(child)

    yield from visit(message, is_root=True)


def _attachment_mime_supported(content_type: str) -> bool:
    return content_type.startswith("text/") or content_type in {
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "message/rfc822",
    }


def _plain_quote_occurrences(value: Any) -> tuple[int, ...]:
    if not isinstance(value, str):
        return ()
    occurrences: list[int] = []
    current_depth = 0
    for line in value.splitlines():
        match = re.match(r"^\s*(>+)", line)
        if match:
            current_depth = max(current_depth, len(match.group(1)))
            continue
        if current_depth:
            occurrences.append(current_depth)
            current_depth = 0
    if current_depth:
        occurrences.append(current_depth)
    return tuple(occurrences)


class _PstTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self.structure_events: list[dict[str, Any]] = []
        self._table: dict[str, Any] | None = None
        self._table_event: dict[str, Any] | None = None
        self._row: dict[str, Any] | None = None
        self._cell: dict[str, Any] | None = None
        self._quote_depth = 0
        self._quote_stack: list[int] = []
        self._quote_ordinal = 0
        self._table_ordinal = 0

    def _flush_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row["cells"].append(self._cell)
        self._cell = None

    def _flush_row(self) -> None:
        self._flush_cell()
        if self._row is not None and self._table is not None:
            self._table["rows"].append(self._row)
        self._row = None

    def _flush_table(self) -> None:
        self._flush_row()
        if self._table is not None:
            table = _finalize_html_table(self._table)
            self.tables.append(table)
            if self._table_event is not None:
                self._table_event["table"] = table
        self._table = None
        self._table_event = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = dict(attrs)
        if tag == "blockquote":
            self._quote_ordinal += 1
            self._quote_depth += 1
            quote_ordinal = self._quote_ordinal
            self.structure_events.append(
                {
                    "kind": "quote",
                    "quote_ordinal": quote_ordinal,
                    "quote_depth": self._quote_depth,
                    "parent_quote_ordinal": (self._quote_stack[-1] if self._quote_stack else None),
                }
            )
            self._quote_stack.append(quote_ordinal)
        elif tag == "table":
            self._flush_table()
            self._table_ordinal += 1
            self._table = {
                "rows": [],
                "quoted_depth": self._quote_depth,
                "attributes": attributes,
            }
            self._table_event = {
                "kind": "html_table",
                "table_ordinal": self._table_ordinal,
                "quote_ordinal": (self._quote_stack[-1] if self._quote_stack else None),
                "table": None,
            }
            self.structure_events.append(self._table_event)
        elif tag == "tr" and self._table is not None:
            self._flush_row()
            self._row = {"cells": []}
        elif tag in {"th", "td"} and self._row is not None:
            self._flush_cell()
            self._cell = {
                "header": tag == "th",
                "scope": ((attributes.get("scope") or "").strip().lower() or None),
                "row_span": _html_span(attributes.get("rowspan")),
                "column_span": _html_span(attributes.get("colspan")),
                "parts": [],
            }

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"}:
            self._flush_cell()
        elif tag == "tr":
            self._flush_row()
        elif tag == "table":
            self._flush_table()
        elif tag == "blockquote":
            if self._quote_stack:
                self._quote_stack.pop()
                self._quote_depth = max(0, self._quote_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["parts"].append(data)

    def close(self) -> None:
        super().close()
        self._flush_table()


def _html_span(value: str | None) -> int:
    try:
        result = int(value or "1")
    except ValueError:
        return 1
    return max(1, result)


def _extract_html_tables(value: str) -> list[dict[str, Any]]:
    parser = _PstTableParser()
    parser.feed(value)
    parser.close()
    return parser.tables


def _extract_html_structure_events(value: str) -> list[dict[str, Any]]:
    parser = _PstTableParser()
    parser.feed(value)
    parser.close()
    return parser.structure_events


def extract_xlsx_mime_attachment_tables(
    payload: bytes,
    *,
    max_uncompressed_bytes: int = 5 * 1024 * 1024,
) -> tuple[dict[str, Any], ...]:
    """Extract bounded structural tables from one already-decoded XLSX MIME payload.

    This helper is deliberately independent from the normal PST parser
    fingerprint and materialization route.  The diagnostic XLSX augmentation
    owns its separate implementation binding, so adding this capability does
    not silently reinterpret existing aggregate shards.
    """

    if (
        not isinstance(payload, bytes)
        or not payload
        or not isinstance(max_uncompressed_bytes, int)
        or isinstance(max_uncompressed_bytes, bool)
        or max_uncompressed_bytes < 1
    ):
        raise ContractValidationError("PST XLSX structural payload is invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = tuple(archive.infolist())
            names = tuple(entry.filename for entry in entries)
            if (
                not entries
                or len(entries) > _PST_XLSX_MAX_ARCHIVE_ENTRIES
                or len(set(names)) != len(names)
                or any(
                    entry.is_dir()
                    or entry.flag_bits & 0x1
                    or entry.file_size < 0
                    or entry.file_size > max_uncompressed_bytes
                    for entry in entries
                )
                or sum(entry.file_size for entry in entries) > max_uncompressed_bytes
            ):
                raise ValueError("unsafe XLSX archive")
            worksheet_names = tuple(
                sorted(
                    name
                    for name in names
                    if name.startswith("xl/worksheets/")
                    and name.endswith(".xml")
                    and "/" not in name[len("xl/worksheets/") :]
                )
            )
            if not worksheet_names or len(worksheet_names) > _PST_XLSX_MAX_WORKSHEETS:
                raise ValueError("XLSX worksheets are invalid")
            shared_strings = _xlsx_shared_strings(archive, names=names)
            tables: list[dict[str, Any]] = []
            for sheet_ordinal, worksheet_name in enumerate(worksheet_names, start=1):
                table = _xlsx_worksheet_table(
                    archive.read(worksheet_name),
                    shared_strings=shared_strings,
                )
                if table is not None:
                    table["sheet_ordinal"] = sheet_ordinal
                    tables.append(table)
            return tuple(tables)
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        ET.ParseError,
        UnicodeError,
    ) as error:
        raise ContractValidationError("PST XLSX structural payload is invalid") from error


def _xlsx_shared_strings(
    archive: zipfile.ZipFile,
    *,
    names: Sequence[str],
) -> tuple[str, ...]:
    name = "xl/sharedStrings.xml"
    if name not in names:
        return ()
    root = ET.fromstring(archive.read(name))
    strings: list[str] = []
    for entry in root.findall(f"{{{_PST_XLSX_NAMESPACE}}}si"):
        value = _xlsx_normalized_text("".join(entry.itertext()))
        strings.append(value)
    return tuple(strings)


def _xlsx_worksheet_table(
    payload: bytes,
    *,
    shared_strings: Sequence[str],
) -> dict[str, Any] | None:
    root = ET.fromstring(payload)
    cell_values: dict[tuple[int, int], str] = {}
    seen_cell_coordinates: set[tuple[int, int]] = set()
    max_row = -1
    max_column = -1
    for row in root.findall(f".//{{{_PST_XLSX_NAMESPACE}}}row"):
        for cell in row.findall(f"{{{_PST_XLSX_NAMESPACE}}}c"):
            reference = cell.attrib.get("r")
            row_ordinal, column_ordinal = _xlsx_cell_coordinates(reference)
            key = row_ordinal, column_ordinal
            if key in seen_cell_coordinates:
                raise ValueError("XLSX cell is duplicated")
            seen_cell_coordinates.add(key)
            value = _xlsx_cell_value(cell, shared_strings=shared_strings)
            if value is None:
                continue
            cell_values[key] = value
            max_row = max(max_row, row_ordinal)
            max_column = max(max_column, column_ordinal)
            if (
                len(cell_values) > _PST_XLSX_MAX_CELLS
                or max_column + 1 > _PST_XLSX_MAX_COLUMNS
            ):
                raise ValueError("XLSX worksheet exceeds structural bounds")
    spans = _xlsx_merge_spans(root)
    for (row_ordinal, column_ordinal), (row_span, column_span) in spans.items():
        max_row = max(max_row, row_ordinal + row_span - 1)
        max_column = max(max_column, column_ordinal + column_span - 1)
    if max_row < 0 or max_column < 0:
        return None
    if (
        max_row + 1 > _PST_XLSX_MAX_CELLS
        or max_column + 1 > _PST_XLSX_MAX_COLUMNS
        or (max_row + 1) * (max_column + 1) > _PST_XLSX_MAX_CELLS
    ):
        raise ValueError("XLSX worksheet exceeds structural bounds")
    covered_cells: set[tuple[int, int]] = set()
    for (row_ordinal, column_ordinal), (row_span, column_span) in spans.items():
        for covered_row in range(row_ordinal, row_ordinal + row_span):
            for covered_column in range(column_ordinal, column_ordinal + column_span):
                coordinate = covered_row, covered_column
                if coordinate in covered_cells:
                    raise ValueError("XLSX merged cells overlap")
                covered_cells.add(coordinate)
                if (
                    coordinate != (row_ordinal, column_ordinal)
                    and cell_values.get(coordinate) is not None
                ):
                    raise ValueError("XLSX merged cell has a non-anchor value")

    rows: list[list[dict[str, Any]]] = []
    for row_ordinal in range(max_row + 1):
        row_cells: list[dict[str, Any]] = []
        for column_ordinal in range(max_column + 1):
            span = spans.get((row_ordinal, column_ordinal))
            if span is not None:
                row_span, column_span = span
            elif (row_ordinal, column_ordinal) in covered_cells:
                row_span, column_span = 1, 1
            else:
                row_span, column_span = 1, 1
            value = cell_values.get((row_ordinal, column_ordinal))
            if (row_ordinal, column_ordinal) in covered_cells and span is None:
                state = "absent"
                value = None
            elif (row_ordinal, column_ordinal) not in cell_values:
                state = "absent"
            elif value:
                state = "populated"
            else:
                state = "blank"
            row_cells.append(
                {
                    "cell_state": state,
                    "row_ordinal": row_ordinal,
                    "column_ordinal": column_ordinal,
                    "row_span": row_span,
                    "column_span": column_span,
                    "value": value if state == "populated" else None,
                    "normalized_value": value.casefold() if state == "populated" else None,
                }
            )
        rows.append(row_cells)

    header_row_ordinal = _xlsx_header_row_ordinal(rows)
    relationships: list[dict[str, Any]] = []
    if header_row_ordinal is not None:
        for cell in rows[header_row_ordinal]:
            if cell["cell_state"] != "populated":
                continue
            for column_ordinal in range(
                cell["column_ordinal"],
                cell["column_ordinal"] + cell["column_span"],
            ):
                relationships.append(
                    {
                        "header_row_ordinal": header_row_ordinal,
                        "header_column_ordinal": cell["column_ordinal"],
                        "column_ordinal": column_ordinal,
                        "header_text": cell["value"],
                        "relationship": "column_header",
                        "scope": "inferred",
                        "row_span": cell["row_span"],
                        "column_span": cell["column_span"],
                    }
                )
    headers: dict[int, list[str]] = {}
    for relationship in relationships:
        headers.setdefault(relationship["column_ordinal"], []).append(
            relationship["header_text"]
        )
    return {
        "rows": rows,
        "max_column": max_column + 1,
        "headers": {
            column_ordinal: " | ".join(values)
            for column_ordinal, values in sorted(headers.items())
        },
        "header_relationships": relationships,
        "quoted_depth": 0,
    }


def _xlsx_cell_coordinates(reference: object) -> tuple[int, int]:
    if not isinstance(reference, str):
        raise ValueError("XLSX cell reference is missing")
    match = _PST_XLSX_CELL_REFERENCE.fullmatch(reference.upper())
    if match is None:
        raise ValueError("XLSX cell reference is invalid")
    column_label, row_label = match.groups()
    column_ordinal = 0
    for character in column_label:
        column_ordinal = column_ordinal * 26 + ord(character) - ord("A") + 1
    return int(row_label) - 1, column_ordinal - 1


def _xlsx_cell_value(cell: ET.Element, *, shared_strings: Sequence[str]) -> str | None:
    cell_type = cell.attrib.get("t", "n")
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{_PST_XLSX_NAMESPACE}}}is")
        return _xlsx_normalized_text("".join(inline.itertext())) if inline is not None else None
    value_node = cell.find(f"{{{_PST_XLSX_NAMESPACE}}}v")
    raw_value = value_node.text if value_node is not None and value_node.text is not None else ""
    if cell_type == "s":
        if not raw_value or not raw_value.isdecimal():
            raise ValueError("XLSX shared string reference is invalid")
        index = int(raw_value)
        if index >= len(shared_strings):
            raise ValueError("XLSX shared string reference is out of range")
        return shared_strings[index] or None
    if cell_type not in {"n", "b", "str", "e", "d"}:
        raise ValueError("XLSX cell type is invalid")
    return _xlsx_normalized_text(raw_value) or None


def _xlsx_merge_spans(root: ET.Element) -> dict[tuple[int, int], tuple[int, int]]:
    spans: dict[tuple[int, int], tuple[int, int]] = {}
    for merge in root.findall(f".//{{{_PST_XLSX_NAMESPACE}}}mergeCell"):
        reference = merge.attrib.get("ref")
        if not isinstance(reference, str):
            raise ValueError("XLSX merge reference is invalid")
        match = _PST_XLSX_RANGE_REFERENCE.fullmatch(reference.upper())
        if match is None:
            raise ValueError("XLSX merge reference is invalid")
        start_row, start_column = _xlsx_cell_coordinates(match.group(1))
        end_row, end_column = _xlsx_cell_coordinates(match.group(2))
        if end_row < start_row or end_column < start_column:
            raise ValueError("XLSX merge reference is invalid")
        key = start_row, start_column
        if key in spans:
            raise ValueError("XLSX merge reference is duplicated")
        spans[key] = end_row - start_row + 1, end_column - start_column + 1
    return spans


def _xlsx_header_row_ordinal(rows: Sequence[Sequence[Mapping[str, Any]]]) -> int | None:
    populated = [
        (row_ordinal, sum(cell.get("cell_state") == "populated" for cell in row))
        for row_ordinal, row in enumerate(rows)
    ]
    dense = [item for item in populated if item[1] >= 2]
    if dense:
        return dense[0][0]
    return next((row_ordinal for row_ordinal, count in populated if count), None)


def _xlsx_normalized_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("XLSX text value is invalid")
    normalized = " ".join(value.split())
    _pst_assert_utf8_safe(normalized)
    return normalized


def _finalize_html_table(table: dict[str, Any]) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    occupied: dict[tuple[int, int], bool] = {}
    header_cells: list[dict[str, Any]] = []
    max_column = 0
    for row_ordinal, raw_row in enumerate(table["rows"]):
        row_cells: list[dict[str, Any]] = []
        column_ordinal = 0
        for raw_cell in raw_row["cells"]:
            while occupied.get((row_ordinal, column_ordinal), False):
                column_ordinal += 1
            text = " ".join("".join(raw_cell["parts"]).split())
            raw_cell["row_ordinal"] = row_ordinal
            raw_cell["column_ordinal"] = column_ordinal
            raw_cell["text"] = text
            if raw_cell["header"] and text:
                header_cells.append(raw_cell)
            cell = {
                "cell_state": "populated" if text else "blank",
                "row_ordinal": row_ordinal,
                "column_ordinal": column_ordinal,
                "row_span": raw_cell["row_span"],
                "column_span": raw_cell["column_span"],
                "value": text or None,
                "normalized_value": text.casefold() if text else None,
                "is_header": raw_cell["header"],
            }
            row_cells.append(cell)
            for row_index in range(
                row_ordinal,
                row_ordinal + raw_cell["row_span"],
            ):
                for column_index in range(
                    column_ordinal,
                    column_ordinal + raw_cell["column_span"],
                ):
                    occupied[(row_index, column_index)] = True
            column_ordinal += raw_cell["column_span"]
            max_column = max(max_column, column_ordinal)
        rows.append(row_cells)
    for row_ordinal, row_cells in enumerate(rows):
        present_columns = {cell["column_ordinal"] for cell in row_cells}
        for column_ordinal in range(max_column):
            if column_ordinal not in present_columns:
                state = "absent" if occupied.get((row_ordinal, column_ordinal)) else "absent"
                row_cells.append(
                    {
                        "cell_state": state,
                        "row_ordinal": row_ordinal,
                        "column_ordinal": column_ordinal,
                        "row_span": 1,
                        "column_span": 1,
                        "value": None,
                        "normalized_value": None,
                        "is_header": False,
                    }
                )
        row_cells.sort(key=lambda cell: cell["column_ordinal"])
    first_data_row = next(
        (
            row_ordinal
            for row_ordinal, raw_row in enumerate(table["rows"])
            if any(not cell["header"] for cell in raw_row["cells"])
        ),
        len(table["rows"]),
    )
    relationships: list[dict[str, Any]] = []
    for header_cell in header_cells:
        scope = header_cell["scope"]
        if scope == "col":
            relationship = "column_header"
        elif scope == "colgroup":
            relationship = "column_group_header"
        elif scope == "row":
            relationship = "row_header"
        elif scope == "rowgroup":
            relationship = "row_group_header"
        elif header_cell["row_ordinal"] == 0 or header_cell["row_ordinal"] < first_data_row:
            relationship = "column_header"
        else:
            relationship = "row_header"
        covered_columns = (
            range(
                header_cell["column_ordinal"],
                header_cell["column_ordinal"] + header_cell["column_span"],
            )
            if relationship in {"column_header", "column_group_header"}
            else (header_cell["column_ordinal"],)
        )
        for covered_column in covered_columns:
            relationships.append(
                {
                    "header_row_ordinal": header_cell["row_ordinal"],
                    "header_column_ordinal": header_cell["column_ordinal"],
                    "column_ordinal": covered_column,
                    "header_text": header_cell["text"],
                    "relationship": relationship,
                    "scope": scope or "inferred",
                    "row_span": header_cell["row_span"],
                    "column_span": header_cell["column_span"],
                }
            )
    column_headers: dict[int, list[str]] = {}
    for relationship in relationships:
        if relationship["relationship"] in {"column_header", "column_group_header"}:
            column_headers.setdefault(relationship["column_ordinal"], []).append(
                relationship["header_text"]
            )
    headers = {
        column_ordinal: " | ".join(header_values)
        for column_ordinal, header_values in sorted(column_headers.items())
    }
    return {
        "rows": rows,
        "max_column": max_column,
        "headers": headers,
        "header_relationships": relationships,
        "quoted_depth": table["quoted_depth"],
    }


def _structural_observation_from_spec(
    spec: Mapping[str, Any],
    *,
    item_by_key: Mapping[str, SourceInventoryItem],
    extraction_input: ExtractionInput,
    parser_fingerprint: str,
) -> StructuralObservation:
    item = item_by_key.get(str(spec["source_local_key"]))
    if item is None:
        raise ContractValidationError("PST structural table has no inventory item")
    parent_observation_id = _pst_parent_source_observation_id(
        item,
        item_by_key=item_by_key,
    )
    table = spec["table"]
    columns = tuple(
        StructuralColumn(**column) for column in _pst_structural_column_projection(table)
    )
    rows = tuple(
        StructuralRow(
            row_ordinal=row_ordinal,
            cells=tuple(
                StructuralCell(
                    cell_state=cell["cell_state"],
                    row_ordinal=row_ordinal,
                    column_ordinal=cell["column_ordinal"],
                    row_span=cell["row_span"],
                    column_span=cell["column_span"],
                    value=cell["value"],
                    normalized_value=cell["normalized_value"],
                )
                for cell in row_cells
            ),
        )
        for row_ordinal, row_cells in enumerate(table["rows"])
    )
    return StructuralObservation.create(
        source_inventory_item_id=item.source_inventory_item_id,
        source_asset_id=extraction_input.asset.asset_id,
        source_observation_id=spec["source_observation_id"],
        structure_kind="html_table",
        columns=columns,
        rows=rows,
        header_relationships=table["header_relationships"],
        source_fingerprint=extraction_input.asset.content_hash,
        parser_fingerprint=parser_fingerprint,
        occurrence_lineage=tuple(spec["occurrence_lineage"]),
        message_lineage_id=str(spec["message_lineage_id"]),
        parent_observation_id=parent_observation_id,
        current_depth=0 if not table["quoted_depth"] else 0,
        quoted_depth=int(table["quoted_depth"]),
        table_ordinal=int(spec["table_ordinal"]),
        mime_ordinal=int(spec["mime_ordinal"]),
        attachment_ordinal=(
            int(spec["attachment_ordinal"]) if spec.get("attachment_ordinal") is not None else None
        ),
        sender_fingerprint=spec.get("sender_fingerprint"),
        observed_at=spec.get("observed_at"),
        version_lineage=(),
    )


def _pst_parent_source_observation_id(
    item: SourceInventoryItem,
    *,
    item_by_key: Mapping[str, SourceInventoryItem],
) -> str:
    parent_source_local_key = item.location.get("parent_source_local_key")
    if not isinstance(parent_source_local_key, str) or not parent_source_local_key:
        raise ContractValidationError("PST structural table lacks an inventory parent key")
    parent_item = item_by_key.get(parent_source_local_key)
    if parent_item is None:
        raise ContractValidationError("PST structural table parent item is missing")
    parent_source_observation_ids = tuple(parent_item.source_observation_ids)
    if len(parent_source_observation_ids) != 1:
        raise ContractValidationError(
            "PST structural table parent must have exactly one source observation"
        )
    return parent_source_observation_ids[0]


def rehydrate_pst_inventory_carrier(
    observation: Observation | Mapping[str, Any],
    *,
    asset_id: str,
    extractor_run_id: str,
    permission_scope: Mapping[str, Any],
    expected_source_fingerprint: str | None = None,
    expected_traversal_binding: PstTraversalBinding,
) -> tuple[SourceInventory, tuple[StructuralObservation, ...]]:
    """Rehydrate one carrier against trusted run-level traversal metadata."""

    payload = observation.to_dict() if isinstance(observation, Observation) else dict(observation)
    expected_observation_keys = {
        "observation_id",
        "extractor_run_id",
        "observation_type",
        "modality",
        "location",
        "confidence",
        "permission_scope",
        "created_at",
        "asset_id",
        "payload",
    }
    if set(payload) != expected_observation_keys:
        raise ContractValidationError("PST carrier observation has unexpected fields")
    _pst_canonical_confidence(payload.get("confidence"))
    carrier_created_at = _pst_canonical_extraction_timestamp(payload.get("created_at"))
    carrier = Observation.from_dict(payload)
    _pst_canonical_confidence(carrier.confidence)
    if carrier.created_at != carrier_created_at:
        raise ContractValidationError("PST carrier timestamp is not canonical")
    if (
        carrier.asset_id != asset_id
        or carrier.extractor_run_id != extractor_run_id
        or carrier.observation_type != PST_INVENTORY_CARRIER_OBSERVATION_TYPE
        or carrier.modality != PST_INVENTORY_CARRIER_MODALITY
        or _permission_scope_payload(carrier.permission_scope) != dict(permission_scope)
    ):
        raise ContractValidationError("PST carrier provenance does not match extraction")
    if not isinstance(carrier.payload, Mapping):
        raise ContractValidationError("PST carrier payload is required")
    carrier_location = _require_mapping(carrier.location, "pst carrier location")
    carrier_payload = dict(carrier.payload)
    if set(carrier_payload) != {
        "carrier_type",
        "carrier_version",
        "source_inventory",
        "structural_observations",
    }:
        raise ContractValidationError("PST carrier payload shape is not closed")
    _pst_validate_inventory_carrier_markers(carrier_location, carrier_payload)
    if not isinstance(carrier_payload["structural_observations"], list):
        raise ContractValidationError("PST carrier marker is invalid")
    inventory_payload = _require_mapping(
        carrier_payload["source_inventory"],
        "pst source inventory",
    )
    _assert_exact_keys(
        inventory_payload,
        {
            "source_inventory_id",
            "source_asset_id",
            "source_fingerprint",
            "parser_fingerprint",
            "items",
            "created_at",
        },
        "pst source inventory",
    )
    for entry in _require_list(inventory_payload, "items"):
        item = _require_mapping(entry, "pst source inventory item")
        _assert_exact_keys(
            item,
            {
                "source_inventory_item_id",
                "source_asset_id",
                "structure_kind",
                "content_type",
                "ordinal",
                "processing_state",
                "raw_retention_state",
                "source_fingerprint",
                "parser_fingerprint",
                "permission_scope",
                "source_inventory_id",
                "intentional_exclusion_proof",
                "parent_inventory_item_id",
                "location",
                "version_lineage",
                "source_observation_ids",
            },
            "pst source inventory item",
        )
    inventory = SourceInventory.from_persistence_dict(inventory_payload)
    if expected_source_fingerprint is not None and (
        inventory.source_fingerprint != expected_source_fingerprint
    ):
        raise ContractValidationError("PST carrier source fingerprint mismatch")
    if inventory.source_asset_id != asset_id:
        raise ContractValidationError("PST carrier inventory asset mismatch")
    expected_archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {
            "asset_id": asset_id,
            "archive_sha256": inventory.source_fingerprint,
        },
    )
    expected_mailbox_id = stable_resource_contract_id(
        "mailbox",
        "PstMailbox",
        {"asset_id": asset_id},
    )
    if (
        type(carrier_location["archive_id"]) is not str
        or carrier_location["archive_id"] != expected_archive_id
        or type(carrier_location["mailbox_id"]) is not str
        or carrier_location["mailbox_id"] != expected_mailbox_id
    ):
        raise ContractValidationError("PST carrier location binding is invalid")
    trusted_source_traversal_ordinals = _pst_trusted_source_traversal_ordinals(
        inventory,
        trusted_traversal_binding=expected_traversal_binding,
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        expected_source_fingerprint=expected_source_fingerprint,
    )
    _pst_validate_inventory_positional_binding(
        inventory,
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        trusted_source_traversal_ordinals=trusted_source_traversal_ordinals,
    )
    inventory_created_at = _pst_canonical_extraction_timestamp(inventory.created_at)
    if inventory.created_at != inventory_created_at or carrier_created_at != inventory_created_at:
        raise ContractValidationError("PST carrier timestamp binding is invalid")
    item_by_id = {item.source_inventory_item_id: item for item in inventory.items}
    structural_payloads = []
    for entry in carrier_payload["structural_observations"]:
        structural = _require_mapping(entry, "pst structural observation")
        _assert_exact_keys(
            structural,
            {
                "structural_observation_id",
                "source_inventory_item_id",
                "source_asset_id",
                "source_observation_id",
                "structure_kind",
                "columns",
                "rows",
                "header_relationships",
                "source_fingerprint",
                "parser_fingerprint",
                "occurrence_lineage",
                "message_lineage_id",
                "parent_observation_id",
                "current_depth",
                "quoted_depth",
                "table_ordinal",
                "mime_ordinal",
                "attachment_ordinal",
                "sender_fingerprint",
                "observed_at",
                "version_lineage",
            },
            "pst structural observation",
        )
        structural_item = item_by_id.get(structural["source_inventory_item_id"])
        if (
            structural_item is None
            or structural_item.structure_kind not in _PST_STRUCTURAL_INVENTORY_KINDS
            or structural_item.processing_state != "parsed"
        ):
            raise ContractValidationError("PST structural observation inventory binding is invalid")
        _pst_validate_structural_header_relationships(
            structural["header_relationships"],
            rows=structural["rows"],
            columns=structural["columns"],
            expected_cell_occupancy_fingerprint=structural_item.location.get(
                "cell_occupancy_fingerprint"
            ),
        )
        structural_payloads.append(structural)
    observations = tuple(
        StructuralObservation.from_persistence_dict(structural)
        for structural in structural_payloads
    )
    for structural_payload, structural_observation in zip(
        structural_payloads,
        observations,
        strict=True,
    ):
        expected_structural_observation_id = _pst_canonical_structural_observation_id(
            structural_payload
        )
        if structural_observation.structural_observation_id != expected_structural_observation_id:
            raise ContractValidationError("PST structural observation id is not canonical")
        if (
            structural_observation.to_persistence_dict()["header_relationships"]
            != structural_payload["header_relationships"]
        ):
            raise ContractValidationError(
                "PST structural header relationship projection is not canonical"
            )
    item_by_key: dict[str, SourceInventoryItem] = {}
    for item in inventory.items:
        source_local_key = item.location.get("source_local_key")
        if not isinstance(source_local_key, str) or not source_local_key:
            raise ContractValidationError("PST structural inventory item lacks a source-local key")
        if source_local_key in item_by_key:
            raise ContractValidationError(
                "PST structural inventory has duplicate source-local keys"
            )
        item_by_key[source_local_key] = item
    _validate_pst_sidecar_inventory_topology(
        {
            key: item
            for key, item in item_by_key.items()
            if item.structure_kind == "exported_file"
            and item.location.get("source_unit_kind") == "attachment"
        },
        {
            key: item
            for key, item in item_by_key.items()
            if item.structure_kind == "regular_attachment_occurrence"
            and item.location.get("attachment_source") == "readpst_sidecar"
        },
    )
    _validate_pst_message_limit_topology(inventory, item_by_key=item_by_key)
    _validate_pst_structural_bijection(
        inventory,
        observations,
        trusted_source_traversal_ordinals=trusted_source_traversal_ordinals,
    )
    observation_ids: set[str] = set()
    for structural in observations:
        if structural.structural_observation_id in observation_ids:
            raise ContractValidationError("PST carrier contains duplicate structural observations")
        observation_ids.add(structural.structural_observation_id)
        item = item_by_id.get(structural.source_inventory_item_id)
        if item is None:
            raise ContractValidationError("PST structural observation has orphan membership")
        if structural.source_observation_id not in item.source_observation_ids:
            raise ContractValidationError(
                "PST structural observation source is not inventory-bound"
            )
        if (
            structural.source_asset_id != inventory.source_asset_id
            or structural.source_fingerprint != inventory.source_fingerprint
            or structural.parser_fingerprint != inventory.parser_fingerprint
        ):
            raise ContractValidationError("PST structural observation binding mismatch")
        expected_parent_observation_id = _pst_parent_source_observation_id(
            item,
            item_by_key=item_by_key,
        )
        if structural.parent_observation_id != expected_parent_observation_id:
            raise ContractValidationError("PST structural observation parent binding mismatch")
    canonical_payload = {
        **payload,
        "payload": {
            **carrier_payload,
            "source_inventory": inventory.to_persistence_dict(),
            "structural_observations": [
                structural.to_persistence_dict() for structural in observations
            ],
        },
    }
    expected_id = stable_observation_id(
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        observation_type=PST_INVENTORY_CARRIER_OBSERVATION_TYPE,
        modality=PST_INVENTORY_CARRIER_MODALITY,
        location=carrier.location,
        text=carrier.text,
        payload=canonical_payload["payload"],
    )
    if carrier.observation_id != expected_id:
        raise ContractValidationError("PST carrier observation id does not match payload")
    return inventory, observations


def rehydrate_pst_source_unit_observations(
    observations: Sequence[Observation | Mapping[str, Any]],
    *,
    inventory: SourceInventory,
    asset_id: str,
    extractor_run_id: str,
    permission_scope: Mapping[str, Any],
    expected_source_fingerprint: str | None = None,
    expected_traversal_binding: PstTraversalBinding,
) -> tuple[Observation, ...]:
    """Validate source units against inventory and trusted traversal metadata."""

    if inventory.source_asset_id != asset_id:
        raise ContractValidationError("PST source-unit inventory asset mismatch")
    if expected_source_fingerprint is not None and (
        inventory.source_fingerprint != expected_source_fingerprint
    ):
        raise ContractValidationError("PST source-unit source fingerprint mismatch")
    trusted_source_traversal_ordinals = _pst_trusted_source_traversal_ordinals(
        inventory,
        trusted_traversal_binding=expected_traversal_binding,
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        expected_source_fingerprint=expected_source_fingerprint,
    )
    _pst_validate_inventory_positional_binding(
        inventory,
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        trusted_source_traversal_ordinals=trusted_source_traversal_ordinals,
    )
    inventory_created_at = _pst_canonical_extraction_timestamp(inventory.created_at)
    if inventory.created_at != inventory_created_at:
        raise ContractValidationError("PST source-unit inventory timestamp is invalid")
    expected_permission_scope = _permission_scope_payload(permission_scope)
    expected_by_id: dict[str, tuple[SourceInventoryItem, str]] = {}
    for item in inventory.items:
        source_local_key = item.location.get("source_local_key")
        if not isinstance(source_local_key, str) or not source_local_key:
            raise ContractValidationError("PST source inventory item lacks a source-local key")
        if (
            item.source_asset_id != asset_id
            or item.source_fingerprint != inventory.source_fingerprint
            or item.parser_fingerprint != inventory.parser_fingerprint
            or _permission_scope_payload(item.permission_scope) != expected_permission_scope
        ):
            raise ContractValidationError("PST source-unit inventory binding mismatch")
        for source_observation_id in sorted(item.source_observation_ids):
            if source_observation_id in expected_by_id:
                raise ContractValidationError("PST source observation is referenced more than once")
            expected_by_id[source_observation_id] = (item, source_local_key)

    source_unit_records = [
        observation
        for observation in observations
        if (
            observation.observation_type
            if isinstance(observation, Observation)
            else observation.get("observation_type")
        )
        == PST_SOURCE_UNIT_OBSERVATION_TYPE
    ]
    if len(source_unit_records) != len(expected_by_id):
        raise ContractValidationError("PST source-unit observation count does not match inventory")

    archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {
            "asset_id": asset_id,
            "archive_sha256": inventory.source_fingerprint,
        },
    )
    mailbox_id = stable_resource_contract_id(
        "mailbox",
        "PstMailbox",
        {"asset_id": asset_id},
    )
    validated_by_id: dict[str, Observation] = {}
    seen_ids: set[str] = set()
    for raw_observation in source_unit_records:
        payload = (
            raw_observation.to_dict()
            if isinstance(raw_observation, Observation)
            else dict(raw_observation)
        )
        expected_observation_keys = {
            "observation_id",
            "extractor_run_id",
            "observation_type",
            "modality",
            "location",
            "confidence",
            "permission_scope",
            "created_at",
            "asset_id",
            "payload",
        }
        if set(payload) != expected_observation_keys:
            raise ContractValidationError("PST source-unit observation has unexpected fields")
        _pst_canonical_confidence(payload.get("confidence"))
        source_created_at = _pst_canonical_extraction_timestamp(payload.get("created_at"))
        source_observation = Observation.from_dict(payload)
        _pst_canonical_confidence(source_observation.confidence)
        if (
            source_observation.created_at != source_created_at
            or source_created_at != inventory_created_at
        ):
            raise ContractValidationError("PST source-unit timestamp binding is invalid")
        if (
            source_observation.asset_id != asset_id
            or source_observation.extractor_run_id != extractor_run_id
            or source_observation.observation_type != PST_SOURCE_UNIT_OBSERVATION_TYPE
            or source_observation.modality != PST_INVENTORY_CARRIER_MODALITY
            or _permission_scope_payload(source_observation.permission_scope)
            != expected_permission_scope
        ):
            raise ContractValidationError("PST source-unit observation provenance mismatch")
        if source_observation.observation_id in seen_ids:
            raise ContractValidationError("PST source-unit observation is duplicated")
        seen_ids.add(source_observation.observation_id)
        expected_item_and_key = expected_by_id.get(source_observation.observation_id)
        if expected_item_and_key is None:
            raise ContractValidationError("PST source-unit observation is not inventory-referenced")
        item, source_local_key = expected_item_and_key
        parent_source_local_key = item.location.get("parent_source_local_key")
        expected_traversal_ordinal = (
            item.ordinal
            if trusted_source_traversal_ordinals is None
            else trusted_source_traversal_ordinals[item.source_inventory_item_id]
        )
        traversal_binding = _pst_traversal_binding_fingerprint(
            source_local_key=source_local_key,
            parent_source_local_key=parent_source_local_key,
            ordinal=expected_traversal_ordinal,
        )
        expected_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "source_inventory_item_id": item.source_inventory_item_id,
            "source_local_key": source_local_key,
            "source_observation_type": PST_SOURCE_UNIT_OBSERVATION_TYPE,
            "source_observation_version": PST_SOURCE_UNIT_OBSERVATION_VERSION,
            "source_traversal_binding_policy": _PST_TRAVERSAL_BINDING_POLICY,
            "source_traversal_ordinal": expected_traversal_ordinal,
            "source_traversal_binding_fingerprint": traversal_binding,
        }
        source_location = _require_mapping(
            source_observation.location,
            "pst source-unit location",
        )
        _pst_require_exact_keys(
            source_location,
            set(expected_location),
            "PST source-unit location",
        )
        if not isinstance(source_observation.payload, Mapping):
            raise ContractValidationError("PST source-unit observation payload is required")
        source_payload = dict(source_observation.payload)
        _pst_require_exact_keys(
            source_payload,
            {
                "source_observation_type",
                "source_observation_version",
                "source_observation_id",
                "source_inventory_id",
                "source_inventory_item_id",
                "source_local_key",
                "source_fingerprint",
                "parser_fingerprint",
                "processing_state",
                "raw_retention_state",
                "source_traversal_binding_policy",
                "source_traversal_ordinal",
                "source_traversal_binding_fingerprint",
            },
            "PST source-unit observation payload",
        )
        _pst_validate_source_unit_markers(
            source_location,
            source_payload,
            expected_traversal_ordinal=expected_traversal_ordinal,
        )
        if source_location != expected_location:
            raise ContractValidationError("PST source-unit observation location mismatch")
        expected_source_payload = {
            "source_observation_type": PST_SOURCE_UNIT_OBSERVATION_TYPE,
            "source_observation_version": PST_SOURCE_UNIT_OBSERVATION_VERSION,
            "source_observation_id": source_observation.observation_id,
            "source_inventory_id": inventory.source_inventory_id,
            "source_inventory_item_id": item.source_inventory_item_id,
            "source_local_key": source_local_key,
            "source_fingerprint": item.source_fingerprint,
            "parser_fingerprint": item.parser_fingerprint,
            "processing_state": item.processing_state,
            "raw_retention_state": item.raw_retention_state,
            "source_traversal_binding_policy": _PST_TRAVERSAL_BINDING_POLICY,
            "source_traversal_ordinal": expected_traversal_ordinal,
            "source_traversal_binding_fingerprint": traversal_binding,
        }
        if source_payload != expected_source_payload:
            raise ContractValidationError("PST source-unit observation binding mismatch")
        expected_id = _pst_source_observation_id_from_fields(
            asset_id=asset_id,
            extractor_run_id=extractor_run_id,
            source_local_key=source_local_key,
            traversal_binding_fingerprint=traversal_binding,
            source_binding_fingerprint=(
                item.location.get("cell_occupancy_fingerprint")
                if item.structure_kind in _PST_STRUCTURAL_INVENTORY_KINDS
                else None
            ),
        )
        if source_observation.observation_id != expected_id:
            raise ContractValidationError("PST source-unit observation id mismatch")
        assert_no_public_raw_references(payload, "pst_source_unit_observation")
        validated_by_id[source_observation.observation_id] = source_observation
    if seen_ids != set(expected_by_id):
        raise ContractValidationError("PST inventory contains an unobserved source reference")
    return tuple(validated_by_id[source_id] for source_id in expected_by_id)


def rehydrate_pst_inventory_carriers(
    observations: Sequence[Observation | Mapping[str, Any]],
    *,
    asset_id: str,
    extractor_run_id: str,
    permission_scope: Mapping[str, Any],
    expected_source_fingerprint: str | None = None,
    expected_traversal_binding: PstTraversalBinding,
) -> tuple[SourceInventory, tuple[StructuralObservation, ...]]:
    carriers = [
        observation
        for observation in observations
        if (
            (
                observation.observation_type
                if isinstance(observation, Observation)
                else observation.get("observation_type")
            )
            == PST_INVENTORY_CARRIER_OBSERVATION_TYPE
        )
    ]
    if len(carriers) != 1:
        raise ContractValidationError("PST extraction must contain exactly one inventory carrier")
    inventory, structural = rehydrate_pst_inventory_carrier(
        carriers[0],
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        permission_scope=permission_scope,
        expected_source_fingerprint=expected_source_fingerprint,
        expected_traversal_binding=expected_traversal_binding,
    )
    rehydrate_pst_source_unit_observations(
        observations,
        inventory=inventory,
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        permission_scope=permission_scope,
        expected_source_fingerprint=expected_source_fingerprint,
        expected_traversal_binding=expected_traversal_binding,
    )
    return inventory, structural


_PST_ORDINARY_OBSERVATION_TYPES = frozenset(
    {
        "mail_folder_occurrence",
        "email_thread",
        "email_message",
        "email_header",
        "email_body_segment",
        "email_attachment_occurrence",
        "email_attachment_text_segment",
    }
)


def rehydrate_pst_observation_stream(
    observations: Sequence[Observation | Mapping[str, Any]],
    *,
    asset_id: str,
    extractor_run_id: str,
    permission_scope: Mapping[str, Any],
    expected_source_fingerprint: str,
    expected_observation_ids: Sequence[str],
    expected_traversal_binding: PstTraversalBinding,
) -> tuple[Observation, ...]:
    """Validate and canonically order a persisted PST observation stream.

    This is the WP2 source-specific rehydration boundary.  It accepts a
    complete PST stream or the one extraction-issued child-preserving partial
    state, delegates the reserved carrier and source-unit records to their
    existing WP1-backed validators, and independently replays the
    already-emitted mail observation truth (including reply resolution) before
    returning the trusted job order.  The required
    ``expected_traversal_binding`` must come from trusted job/run metadata
    captured at extraction time; it must never be rebuilt from the reloaded
    carrier or observation stream.  WP5 must call this helper after reloading
    observations and before query or bundle projection, using
    ``finished_job.observation_ids`` as ``expected_observation_ids`` and the
    corresponding trusted traversal binding.
    The helper intentionally does not alter generic Observation validators or
    stores.
    """

    if not isinstance(expected_source_fingerprint, str) or not expected_source_fingerprint:
        raise ContractValidationError("PST source fingerprint expectation is required")
    if not isinstance(expected_traversal_binding, PstTraversalBinding):
        raise ContractValidationError("PST trusted traversal binding is required")
    _pst_assert_issued_traversal_binding(expected_traversal_binding)
    if isinstance(expected_observation_ids, (str, bytes)) or not isinstance(
        expected_observation_ids, Sequence
    ):
        raise ContractValidationError("PST expected observation ids must be a sequence")
    trusted_ids = tuple(expected_observation_ids)
    if not trusted_ids or any(not isinstance(value, str) or not value for value in trusted_ids):
        raise ContractValidationError("PST expected observation ids are invalid")
    if len(set(trusted_ids)) != len(trusted_ids):
        raise ContractValidationError("PST expected observation ids contain duplicates")
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise ContractValidationError("PST observations must be a sequence")
    if len(observations) != len(trusted_ids):
        raise ContractValidationError("PST observation stream count does not match trusted ids")

    expected_scope = _permission_scope_payload(permission_scope)
    normalized: list[Observation] = []
    seen_ids: set[str] = set()
    allowed_envelope_keys = {
        "observation_id",
        "extractor_run_id",
        "observation_type",
        "modality",
        "location",
        "confidence",
        "permission_scope",
        "created_at",
        "asset_id",
        "evidence_snapshot_id",
        "text",
        "caption",
        "payload",
        "extracted_value",
    }
    for raw_observation in observations:
        if isinstance(raw_observation, Observation):
            raw_payload = raw_observation.to_dict()
            observation = Observation.from_dict(raw_payload)
        elif isinstance(raw_observation, Mapping):
            raw_payload = dict(raw_observation)
            if set(raw_payload) - allowed_envelope_keys:
                raise ContractValidationError("PST observation envelope contains unknown fields")
            observation = Observation.from_dict(raw_payload)
            if observation.to_dict() != raw_payload:
                raise ContractValidationError("PST observation envelope is not canonical")
        else:
            raise ContractValidationError("PST observation is invalid")
        if observation.observation_type in _PST_ORDINARY_OBSERVATION_TYPES and any(
            field_name in raw_payload
            for field_name in ("evidence_snapshot_id", "caption", "extracted_value")
        ):
            raise ContractValidationError("PST ordinary observation envelope is not canonical")
        _pst_canonical_confidence(raw_payload.get("confidence"))
        _pst_canonical_confidence(observation.confidence)
        if observation.observation_id in seen_ids:
            raise ContractValidationError("PST observation stream contains duplicate ids")
        seen_ids.add(observation.observation_id)
        if (
            observation.asset_id != asset_id
            or observation.extractor_run_id != extractor_run_id
            or observation.modality != PST_INVENTORY_CARRIER_MODALITY
            or _permission_scope_payload(observation.permission_scope) != expected_scope
        ):
            raise ContractValidationError("PST observation provenance does not match extraction")
        if observation.observation_type not in {
            *_PST_ORDINARY_OBSERVATION_TYPES,
            PST_INVENTORY_CARRIER_OBSERVATION_TYPE,
            PST_SOURCE_UNIT_OBSERVATION_TYPE,
        }:
            raise ContractValidationError("PST observation type is outside the closed stream")
        if not isinstance(observation.location, Mapping) or not isinstance(
            observation.payload, Mapping
        ):
            raise ContractValidationError("PST observation location and payload are required")
        payload = observation.to_dict()
        if observation.observation_type != PST_SOURCE_UNIT_OBSERVATION_TYPE:
            expected_id = stable_observation_id(
                asset_id=asset_id,
                extractor_run_id=extractor_run_id,
                observation_type=observation.observation_type,
                modality=observation.modality,
                location=observation.location,
                evidence_snapshot_id=observation.evidence_snapshot_id,
                text=observation.text,
                caption=observation.caption,
                payload=observation.payload,
                extracted_value=observation.extracted_value,
            )
            if observation.observation_id != expected_id:
                raise ContractValidationError("PST observation id does not match canonical payload")
        # The inventory carrier is persistence-only private evidence.  Its
        # closed shape, provenance, stable id, and structural bindings are
        # validated by ``rehydrate_pst_inventory_carrier`` below.  Applying a
        # public-payload guard here would reject legitimate private table cell
        # values before the only authorized public projections can redact them.
        if observation.observation_type != PST_INVENTORY_CARRIER_OBSERVATION_TYPE:
            assert_no_public_raw_references(payload, "pst_observation_stream")
        normalized.append(observation)

    if set(normalized_observation.observation_id for normalized_observation in normalized) != set(
        trusted_ids
    ):
        raise ContractValidationError("PST observation ids do not match trusted job ids")
    carrier_records = [
        observation
        for observation in normalized
        if observation.observation_type == PST_INVENTORY_CARRIER_OBSERVATION_TYPE
    ]
    if len(carrier_records) != 1:
        raise ContractValidationError("PST observation stream must contain exactly one carrier")
    inventory, structural = rehydrate_pst_inventory_carrier(
        carrier_records[0],
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        permission_scope=expected_scope,
        expected_source_fingerprint=expected_source_fingerprint,
        expected_traversal_binding=expected_traversal_binding,
    )
    expected_created_at = _pst_canonical_extraction_timestamp(inventory.created_at)
    for observation in normalized:
        _pst_validate_observation_timestamp(
            observation,
            expected_created_at=expected_created_at,
        )
    rehydrate_pst_source_unit_observations(
        normalized,
        inventory=inventory,
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        permission_scope=expected_scope,
        expected_source_fingerprint=expected_source_fingerprint,
        expected_traversal_binding=expected_traversal_binding,
    )
    _validate_pst_mail_observation_graph(
        normalized,
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        permission_scope=expected_scope,
        expected_source_fingerprint=expected_source_fingerprint,
        inventory=inventory,
        structural_observations=structural,
        expected_traversal_binding=expected_traversal_binding,
    )
    by_id = {observation.observation_id: observation for observation in normalized}
    return tuple(by_id[observation_id] for observation_id in trusted_ids)


def _validate_pst_mail_observation_graph(
    observations: Sequence[Observation],
    *,
    asset_id: str,
    extractor_run_id: str,
    permission_scope: Mapping[str, Any],
    expected_source_fingerprint: str,
    inventory: SourceInventory,
    structural_observations: Sequence[StructuralObservation],
    expected_traversal_binding: PstTraversalBinding | None = None,
) -> None:
    del permission_scope
    _validate_pst_structural_bijection(inventory, structural_observations)
    archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {"asset_id": asset_id, "archive_sha256": expected_source_fingerprint},
    )
    mailbox_id = stable_resource_contract_id("mailbox", "PstMailbox", {"asset_id": asset_id})
    ordinary = [
        observation
        for observation in observations
        if observation.observation_type in _PST_ORDINARY_OBSERVATION_TYPES
    ]
    if not ordinary and (
        expected_traversal_binding is not None
        and expected_traversal_binding.partial_inventory_state is True
    ):
        _validate_pst_partial_inventory_state(
            inventory,
            structural_observations=structural_observations,
            expected_traversal_binding=expected_traversal_binding,
        )
        return
    trusted_folder_labels = _pst_trusted_folder_label_map(
        inventory,
        trusted_traversal_binding=expected_traversal_binding,
    )
    folders = [
        observation
        for observation in ordinary
        if observation.observation_type == "mail_folder_occurrence"
    ]
    folder_paths: dict[str, str] = {}
    folder_indices: dict[str, int] = {}
    for observation in folders:
        location = observation.location
        payload = _pst_observation_payload(observation)
        _pst_require_exact_keys(
            location,
            {"archive_id", "mailbox_id", "folder_path_hash", "folder_index"},
            "PST folder location",
        )
        _pst_require_exact_keys(
            payload,
            {"archive_id", "mailbox_id", "folder_path_hash", "folder_label"},
            "PST folder payload",
        )
        _pst_require_archive_binding(
            location, payload, archive_id=archive_id, mailbox_id=mailbox_id
        )
        folder_index = _pst_exact_int(
            location["folder_index"],
            "folder index",
            minimum=1,
        )
        if location["folder_path_hash"] != payload["folder_path_hash"]:
            raise ContractValidationError("PST folder binding mismatch")
        expected_folder_label = trusted_folder_labels.get(str(location["folder_path_hash"]))
        if (
            expected_folder_label is None
            or type(payload["folder_label"]) is not str
            or payload["folder_label"] != expected_folder_label
            or type(observation.text) is not str
            or observation.text != expected_folder_label
        ):
            raise ContractValidationError("PST folder text binding mismatch")
        if location["folder_path_hash"] in folder_paths:
            raise ContractValidationError("PST folder occurrence is duplicated")
        folder_paths[str(location["folder_path_hash"])] = str(payload["folder_label"])
        folder_indices[str(location["folder_path_hash"])] = folder_index
    if folder_indices != _pst_canonical_index_map(folder_paths):
        raise ContractValidationError("PST folder indexes are not canonical")
    if set(folder_paths) != set(trusted_folder_labels):
        raise ContractValidationError("PST folder inventory binding is incomplete")

    message_observations = [
        observation for observation in ordinary if observation.observation_type == "email_message"
    ]
    top_level_message_inventory = _pst_top_level_message_inventory_bindings(inventory)
    source_traversal_ordinals = None
    if expected_traversal_binding is not None:
        source_traversal_ordinals = _pst_trusted_source_traversal_ordinals(
            inventory,
            trusted_traversal_binding=expected_traversal_binding,
            asset_id=asset_id,
            extractor_run_id=extractor_run_id,
            expected_source_fingerprint=expected_source_fingerprint,
        )
    canonical_top_level_occurrences = _pst_canonical_top_level_message_occurrences(
        message_observations,
        inventory_bindings=top_level_message_inventory,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
        source_traversal_ordinals=source_traversal_ordinals,
    )
    inventory_items_by_id = {item.source_inventory_item_id: item for item in inventory.items}
    inventory_items_by_key = {
        str(item.location["source_local_key"]): item
        for item in inventory.items
        if isinstance(item.location.get("source_local_key"), str)
    }
    if expected_traversal_binding is None:
        raise ContractValidationError("PST trusted traversal binding is required")
    if source_traversal_ordinals is None:
        raise ContractValidationError("PST trusted traversal order is required")
    trusted_embedded_message_bindings = expected_traversal_binding.embedded_message_bindings
    trusted_embedded_message_occurrences = _pst_trusted_embedded_message_occurrences(
        inventory,
        trusted_traversal_binding=expected_traversal_binding,
        source_traversal_ordinals=source_traversal_ordinals,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
    )
    observed_embedded_message_bindings: list[tuple[str, str, str, str, int, str, str, str]] = []
    observed_top_level_source_keys: set[str] = set()
    observed_top_level_inventory_item_ids: set[str] = set()
    message_by_occurrence: dict[str, Observation] = {}
    message_indices: dict[str, int] = {}
    contexts: list[_MailMessageContext] = []
    attachment_observations = [
        observation
        for observation in ordinary
        if observation.observation_type == "email_attachment_occurrence"
    ]
    body_observations = [
        observation
        for observation in ordinary
        if observation.observation_type == "email_body_segment"
    ]
    header_observations = [
        observation for observation in ordinary if observation.observation_type == "email_header"
    ]
    body_by_occurrence: dict[str, list[Observation]] = {}
    for observation in body_observations:
        payload = _pst_observation_payload(observation)
        occurrence_id = payload.get("message_occurrence_id")
        if isinstance(occurrence_id, str) and occurrence_id:
            body_by_occurrence.setdefault(occurrence_id, []).append(observation)
    attachments_by_occurrence: dict[str, list[Observation]] = {}
    for observation in attachment_observations:
        payload = _pst_observation_payload(observation)
        occurrence_id = _pst_message_observation_binding(
            observation,
            payload,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
        )
        attachments_by_occurrence.setdefault(occurrence_id, []).append(observation)
    header_observations_by_occurrence = _pst_header_observations_by_occurrence(header_observations)

    for observation in message_observations:
        payload = _pst_observation_payload(observation)
        message_index = _pst_exact_int(
            observation.location.get("message_index"),
            "message index",
            minimum=1,
        )
        parent_occurrence_id = payload.get("parent_message_occurrence_id")
        message_source_local_key = payload.get("message_source_local_key")
        if parent_occurrence_id is None:
            if (
                type(message_source_local_key) is not str
                or not message_source_local_key
                or message_source_local_key in observed_top_level_source_keys
            ):
                raise ContractValidationError("PST top-level message source binding is invalid")
            message_source_inventory_item_id = payload.get("message_source_inventory_item_id")
            if (
                type(message_source_inventory_item_id) is not str
                or not message_source_inventory_item_id
            ):
                raise ContractValidationError("PST top-level message inventory binding is invalid")
            inventory_item = top_level_message_inventory.get(message_source_local_key)
            if (
                inventory_item is None
                or inventory_item.source_inventory_item_id != message_source_inventory_item_id
                or inventory_item.location.get("message_occurrence_id")
                != payload.get("message_occurrence_id")
                or inventory_item.location.get("message_fingerprint")
                != payload.get("message_fingerprint")
            ):
                raise ContractValidationError("PST top-level message source binding is invalid")
            expected_duplicate_ordinal, expected_occurrence_id = (
                canonical_top_level_occurrences.get(message_source_inventory_item_id, (None, None))
            )
            if (
                expected_duplicate_ordinal is None
                or expected_occurrence_id is None
                or payload.get("duplicate_ordinal") != expected_duplicate_ordinal
                or payload.get("message_occurrence_id") != expected_occurrence_id
                or inventory_item.location.get("message_occurrence_id") != expected_occurrence_id
            ):
                raise ContractValidationError(
                    "PST top-level message occurrence identity is invalid"
                )
            observed_top_level_source_keys.add(message_source_local_key)
            observed_top_level_inventory_item_ids.add(message_source_inventory_item_id)
        elif message_source_local_key is not None or "message_source_inventory_item_id" in payload:
            raise ContractValidationError("PST embedded message source binding is invalid")
        message = _pst_rehydrate_message(
            observation,
            payload,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
            folder_paths=folder_paths,
            attachments=attachments_by_occurrence.get(
                str(payload.get("message_occurrence_id")),
                [],
            ),
            body_observations=body_by_occurrence.get(
                str(payload.get("message_occurrence_id")),
                [],
            ),
            header_observations=header_observations_by_occurrence.get(
                payload.get("message_occurrence_id"),
                [],
            ),
        )
        occurrence_id = message.message_occurrence_id
        if occurrence_id in message_by_occurrence:
            raise ContractValidationError("PST message occurrence is duplicated")
        if message.context.parent_occurrence_id is not None:
            parent_occurrence_id = message.context.parent_occurrence_id
            parent_attachment_id = message.context.parent_attachment_id
            embedded_attachment_ordinal = message.context.message.embedded_attachment_ordinal
            if parent_attachment_id is None or embedded_attachment_ordinal is None:
                raise ContractValidationError("PST embedded message parent binding is incomplete")
            embedded_attachment_ordinal = _pst_exact_int(
                embedded_attachment_ordinal,
                "embedded message attachment ordinal",
                minimum=1,
            )
            parent_attachment_candidates = [
                attachment
                for attachment in attachments_by_occurrence.get(parent_occurrence_id, [])
                if _pst_observation_payload(attachment).get("attachment_id") == parent_attachment_id
                and _pst_observation_payload(attachment).get("attachment_ordinal")
                == embedded_attachment_ordinal
            ]
            if len(parent_attachment_candidates) != 1:
                raise ContractValidationError("PST embedded parent attachment binding is invalid")
            parent_attachment_payload = _pst_observation_payload(parent_attachment_candidates[0])
            parent_attachment_item_id = parent_attachment_payload.get(
                "attachment_inventory_item_id"
            )
            parent_attachment_source_key = parent_attachment_payload.get(
                "attachment_inventory_source_local_key"
            )
            if (
                type(parent_attachment_item_id) is not str
                or not parent_attachment_item_id
                or type(parent_attachment_source_key) is not str
                or not parent_attachment_source_key
            ):
                raise ContractValidationError("PST embedded parent attachment inventory is invalid")
            parent_attachment_item = inventory_items_by_id.get(parent_attachment_item_id)
            if (
                parent_attachment_item is None
                or parent_attachment_item.location.get("source_local_key")
                != parent_attachment_source_key
                or parent_attachment_item.location.get("attachment_id") != parent_attachment_id
                or parent_attachment_item.location.get("attachment_ordinal")
                != embedded_attachment_ordinal
            ):
                raise ContractValidationError("PST embedded parent attachment inventory is invalid")
            attached_message_item = inventory_items_by_key.get(
                f"{parent_attachment_source_key}:message"
            )
            if (
                attached_message_item is None
                or attached_message_item.structure_kind != "attached_message_occurrence"
                or attached_message_item.location.get("parent_source_local_key")
                != parent_attachment_source_key
            ):
                raise ContractValidationError("PST attached message inventory is invalid")
            expected_embedded_message = trusted_embedded_message_occurrences.get(
                attached_message_item.source_inventory_item_id
            )
            if expected_embedded_message is None:
                raise ContractValidationError("PST embedded message occurrence is untrusted")
            (
                expected_duplicate_ordinal,
                expected_occurrence_id,
                expected_message_id,
                expected_message_fingerprint,
            ) = expected_embedded_message
            if (
                message.context.duplicate_ordinal != expected_duplicate_ordinal
                or occurrence_id != expected_occurrence_id
                or message.context.message.message_id != expected_message_id
                or message.context.message_fingerprint != expected_message_fingerprint
            ):
                raise ContractValidationError(
                    "PST embedded message occurrence identity is not canonical"
                )
            observed_embedded_message_bindings.append(
                (
                    parent_attachment_item_id,
                    attached_message_item.source_inventory_item_id,
                    parent_occurrence_id,
                    parent_attachment_id,
                    embedded_attachment_ordinal,
                    occurrence_id,
                    message.context.message_fingerprint,
                    message.context.message.message_id,
                )
            )
        message_by_occurrence[occurrence_id] = observation
        message_indices[occurrence_id] = message_index
        contexts.append(message.context)

    expected_top_level_inventory_item_ids = {
        item.source_inventory_item_id for item in top_level_message_inventory.values()
    }
    if (
        observed_top_level_source_keys != set(top_level_message_inventory)
        or observed_top_level_inventory_item_ids != expected_top_level_inventory_item_ids
        or set(canonical_top_level_occurrences) != expected_top_level_inventory_item_ids
    ):
        raise ContractValidationError("PST top-level message inventory bijection failed")
    if tuple(sorted(observed_embedded_message_bindings, key=lambda binding: binding[1])) != tuple(
        trusted_embedded_message_bindings
    ):
        raise ContractValidationError("PST embedded message fingerprint binding is invalid")

    structural_message_contexts = _pst_structural_message_contexts(
        inventory,
        contexts=contexts,
    )
    structural_items_by_id = {item.source_inventory_item_id: item for item in inventory.items}
    for structural in structural_observations:
        item = structural_items_by_id.get(structural.source_inventory_item_id)
        if item is None:
            raise ContractValidationError("PST structural message inventory is missing")
        message_item = _pst_structural_message_item(
            item,
            item_by_key=inventory_items_by_key,
        )
        message_key = str(message_item.location["source_local_key"])
        binding = structural_message_contexts.get(message_key)
        if binding is None:
            raise ContractValidationError("PST structural message context is missing")
        _message_item, context, expected_occurrence_lineage = binding
        expected_sender_fingerprint = sha256_json(_safe_mail_text(context.message.sender, "sender"))
        if (
            structural.message_lineage_id != message_key
            or tuple(structural.occurrence_lineage) != expected_occurrence_lineage
            or structural.sender_fingerprint != expected_sender_fingerprint
            or structural.observed_at != context.message.chronology.authored_sent_at
        ):
            raise ContractValidationError("PST structural message lineage binding is invalid")

    context_by_occurrence = {context.occurrence_id: context for context in contexts}
    _validate_pst_child_lineage(contexts)
    message_location_ancestry_fields = {
        "occurrence_lineage",
        "parent_message_occurrence_id",
        "parent_attachment_id",
        "embedded_attachment_ordinal",
    }
    for observation in message_observations:
        payload = _pst_observation_payload(observation)
        occurrence_id = str(payload["message_occurrence_id"])
        context = context_by_occurrence.get(occurrence_id)
        if context is None:
            raise ContractValidationError("PST message location context is missing")
        _pst_require_exact_keys(
            observation.location,
            {
                "archive_id",
                "mailbox_id",
                "folder_path_hash",
                "message_id",
                "message_occurrence_id",
                "thread_id",
                "message_index",
            },
            "PST message location",
            optional=message_location_ancestry_fields,
        )
        if (
            observation.location["folder_path_hash"] != context.message.folder_path_hash
            or observation.location["message_id"] != context.message.message_id
            or observation.location["message_occurrence_id"] != context.occurrence_id
        ):
            raise ContractValidationError("PST message location binding is invalid")
        present_ancestry_fields = {
            field_name
            for field_name in message_location_ancestry_fields
            if field_name in observation.location
        }
        if context.parent_occurrence_id is None:
            if present_ancestry_fields:
                raise ContractValidationError("PST top-level message ancestry is invalid")
        else:
            expected_ancestry = {
                "occurrence_lineage": list(context.occurrence_lineage),
                "parent_message_occurrence_id": context.parent_occurrence_id,
                "parent_attachment_id": context.parent_attachment_id,
                "embedded_attachment_ordinal": context.message.embedded_attachment_ordinal,
            }
            if present_ancestry_fields != message_location_ancestry_fields:
                raise ContractValidationError("PST embedded message ancestry schema is invalid")
            _pst_exact_int(
                observation.location["embedded_attachment_ordinal"],
                "embedded message location ordinal",
                minimum=1,
            )
            if any(
                observation.location[field_name] != expected_value
                for field_name, expected_value in expected_ancestry.items()
            ):
                raise ContractValidationError("PST embedded message ancestry binding is invalid")
    ordered_contexts = _pst_canonical_message_context_order(
        contexts,
        source_inventory=inventory,
        source_traversal_ordinals=source_traversal_ordinals,
    )
    expected_message_indices = {
        context.occurrence_id: index for index, context in enumerate(ordered_contexts, start=1)
    }
    if message_indices != expected_message_indices:
        raise ContractValidationError("PST message indexes are not canonical")

    thread_observations = [
        observation for observation in ordinary if observation.observation_type == "email_thread"
    ]
    persisted_threads: dict[str, dict[str, Any]] = {}
    thread_indices: dict[str, int] = {}
    for observation in thread_observations:
        payload = _pst_observation_payload(observation)
        _pst_require_exact_keys(
            observation.location,
            {"archive_id", "mailbox_id", "thread_id", "thread_index"},
            "PST thread location",
        )
        _pst_require_thread_payload(payload)
        _pst_require_archive_binding(
            observation.location,
            payload,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
        )
        thread_index = _pst_exact_int(
            observation.location["thread_index"],
            "thread index",
            minimum=1,
        )
        thread_id = payload["thread_id"]
        if observation.location["thread_id"] != thread_id or thread_id in persisted_threads:
            raise ContractValidationError("PST thread identity is invalid")
        if observation.text != payload["normalized_subject"]:
            raise ContractValidationError("PST thread text binding mismatch")
        _pst_validate_thread_boolean_mirrors(payload)
        _pst_validate_thread_reply_resolution_records(payload)
        _pst_validate_thread_unresolved_reply_headers(payload)
        _pst_validate_thread_resolved_edges(payload)
        _pst_validate_thread_chronology_ordinals(payload)
        _pst_exact_int(payload["message_count"], "thread message count", minimum=1)
        persisted_threads[str(thread_id)] = payload
        thread_indices[str(thread_id)] = thread_index

    attachment_text_observations = [
        observation
        for observation in ordinary
        if observation.observation_type == "email_attachment_text_segment"
    ]
    (
        expected_threads,
        expected_thread_ids,
        expected_resolutions,
    ) = _thread_payloads(
        contexts,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
    )
    expected_thread_map = {str(payload["thread_id"]): payload for payload in expected_threads}
    if set(expected_thread_map) != set(persisted_threads):
        raise ContractValidationError("PST thread membership is incomplete")
    if thread_indices != _pst_canonical_index_map(expected_thread_map):
        raise ContractValidationError("PST thread indexes are not canonical")
    for thread_id, payload in persisted_threads.items():
        expected_message_count = _pst_exact_int(
            len(expected_thread_map[thread_id]["occurrence_membership"]),
            "canonical thread message count",
            minimum=1,
        )
        if payload["message_count"] != expected_message_count:
            raise ContractValidationError("PST thread message count is not canonical")
        if payload != to_plain(expected_thread_map[thread_id]):
            raise ContractValidationError("PST thread payload is not canonical")
    for occurrence_id, context in context_by_occurrence.items():
        message_observation = message_by_occurrence[occurrence_id]
        message_payload = _pst_observation_payload(message_observation)
        if message_payload["thread_id"] != expected_thread_ids[occurrence_id]:
            raise ContractValidationError("PST message thread binding is invalid")
        expected_resolution_payload = [
            resolution.to_payload() for resolution in expected_resolutions[occurrence_id]
        ]
        if message_payload["reply_resolutions"] != to_plain(expected_resolution_payload):
            raise ContractValidationError("PST message reply resolution is not canonical")
        if message_payload["reply_resolution_fingerprint"] != _reply_resolution_fingerprint(
            expected_resolution_payload
        ):
            raise ContractValidationError("PST message reply fingerprint is invalid")
    _validate_pst_projection_observations(
        body_observations,
        header_observations,
        attachment_observations,
        attachment_text_observations,
        context_by_occurrence=context_by_occurrence,
        expected_thread_ids=expected_thread_ids,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
    )
    _validate_pst_sidecar_attachment_graph(
        inventory,
        attachment_observations,
        context_by_occurrence=context_by_occurrence,
        attachment_text_observations=attachment_text_observations,
        structural_observations=structural_observations,
    )
    if any(payload.get("version_lineage") != [] for payload in persisted_threads.values()):
        raise ContractValidationError("PST reply stream must not contain version lineage")


def _validate_pst_sidecar_attachment_graph(
    inventory: SourceInventory,
    attachment_observations: Sequence[Observation],
    *,
    context_by_occurrence: Mapping[str, _MailMessageContext],
    attachment_text_observations: Sequence[Observation] = (),
    structural_observations: Sequence[StructuralObservation] = (),
) -> None:
    """Require attachment observations, inventory, text, and tables to agree."""

    items_by_key = {
        str(item.location["source_local_key"]): item
        for item in inventory.items
        if isinstance(item.location.get("source_local_key"), str)
    }
    sidecar_files = {
        key: item
        for key, item in items_by_key.items()
        if item.structure_kind == "exported_file"
        and item.location.get("source_unit_kind") == "attachment"
    }
    sidecar_occurrence_items = {
        str(item.location["source_local_key"]): item
        for item in inventory.items
        if item.structure_kind in {"regular_attachment_occurrence", "inline_attachment_occurrence"}
        and item.location.get("attachment_source") == "readpst_sidecar"
    }
    _validate_pst_sidecar_inventory_topology(
        sidecar_files,
        sidecar_occurrence_items,
    )
    attachment_items = {
        str(item.location["source_local_key"]): item
        for item in inventory.items
        if item.structure_kind in {"regular_attachment_occurrence", "inline_attachment_occurrence"}
    }
    observations_by_attachment_key: dict[str, Observation] = {}
    observations_by_sidecar_key: dict[str, list[Observation]] = {}
    observations_by_attachment_id: dict[tuple[str, str], Observation] = {}
    observations_by_attachment_id_value: dict[str, list[Observation]] = {}
    observations_by_message_occurrence: dict[str, list[Observation]] = {}
    for observation in attachment_observations:
        payload = _pst_observation_payload(observation)
        required_binding = {
            "attachment_inventory_item_id",
            "attachment_inventory_source_local_key",
            "attachment_source_inventory_item_id",
            "attachment_source_inventory_source_local_key",
            "attachment_parent_message_source_local_key",
            "attachment_source_media_type",
            "attachment_source_processing_state",
            "attachment_source_name_fingerprint",
            "attachment_filename",
            "attachment_name_fingerprint",
            "attachment_processing_state",
            "attachment_text_extraction_state",
        }
        if not required_binding.issubset(payload):
            raise ContractValidationError("PST attachment semantic binding is incomplete")
        item_key = payload["attachment_inventory_source_local_key"]
        if not isinstance(item_key, str) or item_key not in attachment_items:
            raise ContractValidationError("PST attachment inventory item is orphaned")
        item = attachment_items[item_key]
        if payload["attachment_inventory_item_id"] != item.source_inventory_item_id:
            raise ContractValidationError("PST attachment inventory item id is invalid")
        if (
            payload.get("message_occurrence_identity_policy")
            != _PST_MESSAGE_OCCURRENCE_IDENTITY_POLICY
        ):
            raise ContractValidationError(
                "PST attachment message occurrence identity policy is invalid"
            )
        if payload["attachment_id"] != item.location.get("attachment_id"):
            raise ContractValidationError("PST attachment inventory attachment id is invalid")
        payload_attachment_ordinal = _pst_exact_int(
            payload.get("attachment_ordinal"),
            "attachment ordinal",
            minimum=1,
        )
        inventory_attachment_ordinal = _pst_exact_int(
            item.location.get("attachment_ordinal"),
            "attachment inventory ordinal",
            minimum=1,
        )
        if payload_attachment_ordinal != inventory_attachment_ordinal:
            raise ContractValidationError("PST attachment inventory ordinal is invalid")
        for field_name in (
            "attachment_filename",
            "attachment_name_fingerprint",
            "attachment_content_fingerprint",
            "attachment_size_bytes",
            "attachment_source_byte_count",
            "attachment_text_extraction_state",
            "attachment_failure_code",
            "attachment_source_char_count",
            "attachment_stored_char_count",
            "attachment_stored_byte_count",
            "attachment_text_segments_fingerprint",
        ):
            if payload.get(field_name) != item.location.get(field_name):
                raise ContractValidationError(
                    f"PST attachment inventory {field_name} binding is invalid"
                )
        if payload["attachment_processing_state"] != item.processing_state:
            raise ContractValidationError("PST attachment processing state binding is invalid")
        if payload["filename"] != payload["attachment_filename"]:
            raise ContractValidationError("PST attachment filename binding is invalid")
        if observation.text != payload["attachment_filename"]:
            raise ContractValidationError("PST attachment envelope text is invalid")
        sidecar_location_fields = (
            "attachment_source",
            "attachment_source_local_key",
            "attachment_processing_state",
            "attachment_source_name_fingerprint",
        )
        present_sidecar_location_fields = {
            field_name
            for field_name in sidecar_location_fields
            if field_name in observation.location
        }
        if payload.get("attachment_source") == "readpst_sidecar":
            if present_sidecar_location_fields != set(sidecar_location_fields):
                raise ContractValidationError("PST sidecar attachment location schema is invalid")
            for field_name in sidecar_location_fields:
                if observation.location.get(field_name) != payload.get(field_name):
                    raise ContractValidationError(
                        "PST sidecar attachment location binding is invalid"
                    )
        elif present_sidecar_location_fields:
            raise ContractValidationError("PST MIME attachment location schema is invalid")
        if payload["mime_type"] != item.content_type:
            raise ContractValidationError("PST attachment media type binding is invalid")
        expected_content_hash = (
            f"sha256:{payload['attachment_content_fingerprint']}"
            if payload.get("attachment_content_fingerprint") is not None
            else None
        )
        if payload.get("content_hash") != expected_content_hash:
            raise ContractValidationError("PST attachment content hash binding is invalid")
        if payload.get("size_bytes") != payload.get("attachment_size_bytes"):
            raise ContractValidationError("PST attachment size binding is invalid")
        parent_message_key = _pst_inventory_parent_message_key(item, item_by_key=items_by_key)
        if payload["attachment_parent_message_source_local_key"] != parent_message_key:
            raise ContractValidationError("PST attachment parent message binding is invalid")
        source_key = payload["attachment_source_inventory_source_local_key"]
        if not isinstance(source_key, str) or source_key not in items_by_key:
            raise ContractValidationError("PST attachment source inventory is orphaned")
        source_item = items_by_key[source_key]
        if payload["attachment_source_inventory_item_id"] != source_item.source_inventory_item_id:
            raise ContractValidationError("PST attachment source inventory id is invalid")
        source_location = source_item.location
        if payload["attachment_source_media_type"] != source_location.get(
            "source_unit_attachment_media_type",
            item.content_type,
        ):
            raise ContractValidationError("PST attachment source media binding is invalid")
        inventory_text_state = item.location.get("attachment_text_extraction_state")
        source_text_state = source_location.get(
            "source_unit_attachment_text_extraction_state",
            source_location.get("attachment_text_extraction_state"),
        )
        if not isinstance(inventory_text_state, str) or not inventory_text_state:
            raise ContractValidationError("PST attachment text state is missing")
        if source_text_state != inventory_text_state:
            raise ContractValidationError("PST attachment source text state binding is invalid")
        if payload.get("text_extraction_state") != inventory_text_state:
            raise ContractValidationError("PST attachment text state binding is invalid")
        if payload.get("attachment_text_extraction_state") != inventory_text_state:
            raise ContractValidationError("PST attachment text state mirror is invalid")
        if payload["attachment_source_processing_state"] != source_location.get(
            "source_unit_attachment_processing_state",
            item.processing_state,
        ):
            raise ContractValidationError("PST attachment source processing binding is invalid")
        if payload.get("attachment_source_failure_code") != source_location.get(
            "source_unit_attachment_failure_code",
            item.location.get("attachment_failure_code"),
        ):
            raise ContractValidationError("PST attachment source failure binding is invalid")
        if payload.get("attachment_source_content_fingerprint") != source_location.get(
            "source_unit_content_fingerprint",
            item.location.get("attachment_content_fingerprint"),
        ):
            raise ContractValidationError("PST attachment source content binding is invalid")
        if payload.get("attachment_source_size_bytes") != source_location.get(
            "source_unit_size_bytes",
            item.location.get("attachment_size_bytes"),
        ):
            raise ContractValidationError("PST attachment source size binding is invalid")
        if payload.get("attachment_source_byte_count") != source_location.get(
            "source_unit_size_bytes",
            item.location.get("attachment_source_byte_count"),
        ):
            raise ContractValidationError("PST attachment source byte binding is invalid")
        if payload.get("attachment_source_stored_byte_count") != source_location.get(
            "source_unit_attachment_stored_byte_count",
            item.location.get("attachment_stored_byte_count"),
        ):
            raise ContractValidationError("PST attachment stored byte binding is invalid")
        if payload["attachment_source_name_fingerprint"] != source_location.get(
            "source_unit_attachment_name_fingerprint",
            item.location.get("attachment_name_fingerprint"),
        ):
            raise ContractValidationError("PST attachment source name binding is invalid")
        if item_key in observations_by_attachment_key:
            raise ContractValidationError("PST attachment inventory occurrence is duplicated")
        observations_by_attachment_key[item_key] = observation
        attachment_id = str(payload["attachment_id"])
        message_occurrence_id = str(payload["message_occurrence_id"])
        attachment_key_for_observation = (message_occurrence_id, attachment_id)
        if attachment_key_for_observation in observations_by_attachment_id:
            raise ContractValidationError("PST attachment occurrence id is duplicated")
        observations_by_attachment_id[attachment_key_for_observation] = observation
        observations_by_attachment_id_value.setdefault(attachment_id, []).append(observation)
        observations_by_message_occurrence.setdefault(message_occurrence_id, []).append(observation)
        parent_context = context_by_occurrence.get(message_occurrence_id)
        if parent_context is None:
            raise ContractValidationError("PST attachment parent message is missing")
        if payload.get("message_fingerprint") != parent_context.message_fingerprint:
            raise ContractValidationError("PST attachment message fingerprint is not parent-bound")
        attachment_duplicate_ordinal = _pst_exact_int(
            payload.get("duplicate_ordinal"),
            "attachment duplicate ordinal",
            minimum=1,
        )
        if attachment_duplicate_ordinal != parent_context.duplicate_ordinal:
            raise ContractValidationError("PST attachment duplicate ordinal is not parent-bound")
        sidecar_key = payload.get("attachment_source_local_key")
        if payload.get("attachment_source") == "readpst_sidecar":
            if not isinstance(sidecar_key, str) or sidecar_key not in sidecar_files:
                raise ContractValidationError("PST sidecar attachment source is orphaned")
            observations_by_sidecar_key.setdefault(sidecar_key, []).append(observation)
            context = context_by_occurrence.get(str(payload["message_occurrence_id"]))
            if context is None or context.message.source_local_key is None:
                raise ContractValidationError("PST sidecar attachment parent is missing")
            expected_parent = f"{context.message.source_local_key}:message"
            occurrence_key = f"{sidecar_key}:attachment"
            occurrence_item = sidecar_occurrence_items.get(occurrence_key)
            linked_id = sidecar_files[sidecar_key].location.get("source_unit_linked_attachment_id")
            if linked_id is not None:
                if linked_id != attachment_id or occurrence_item is not None:
                    raise ContractValidationError("PST sidecar MIME deduplication is invalid")
            elif occurrence_item is None:
                raise ContractValidationError("PST sidecar attachment inventory is missing")
            elif occurrence_item.location.get("parent_source_local_key") != expected_parent:
                raise ContractValidationError("PST sidecar attachment parent is invalid")
            elif payload_attachment_ordinal != _pst_exact_int(
                occurrence_item.location.get("attachment_ordinal"),
                "sidecar attachment ordinal",
                minimum=1,
            ):
                raise ContractValidationError("PST sidecar attachment ordinal is invalid")
            elif payload.get("attachment_source_name_fingerprint") != occurrence_item.location.get(
                "sidecar_name_fingerprint"
            ):
                raise ContractValidationError("PST sidecar attachment name binding is invalid")
            elif (
                occurrence_item.location.get("sidecar_content_fingerprint") is not None
                and payload.get("content_hash") is not None
                and payload["content_hash"].removeprefix("sha256:")
                != occurrence_item.location["sidecar_content_fingerprint"]
            ):
                raise ContractValidationError("PST sidecar attachment content binding is invalid")
        _validate_pst_attachment_text_state(
            payload,
            item=item,
            source_location=source_location,
        )
    for message_attachments in observations_by_message_occurrence.values():
        ordinals = [
            _pst_observation_payload(observation).get("attachment_ordinal")
            for observation in message_attachments
        ]
        for ordinal in ordinals:
            _pst_exact_ordinal(ordinal, "attachment_ordinal")
        if sorted(ordinals) != list(range(1, len(ordinals) + 1)):
            raise ContractValidationError("PST attachment ordinal sequence is invalid")
    if set(attachment_items) != set(observations_by_attachment_key):
        raise ContractValidationError("PST attachment inventory/observation bijection failed")

    text_by_attachment: dict[tuple[str, str], list[Observation]] = {}
    for observation in attachment_text_observations:
        payload = _pst_observation_payload(observation)
        attachment_id = str(payload.get("attachment_id", ""))
        message_occurrence_id = str(payload.get("message_occurrence_id", ""))
        attachment_key_for_observation = (message_occurrence_id, attachment_id)
        attachment_observation = observations_by_attachment_id.get(attachment_key_for_observation)
        if attachment_observation is None:
            raise ContractValidationError("PST attachment text has orphan occurrence")
        attachment_payload = _pst_observation_payload(attachment_observation)
        for field_name in (
            "attachment_inventory_item_id",
            "attachment_inventory_source_local_key",
            "attachment_source_inventory_item_id",
            "attachment_source_inventory_source_local_key",
            "attachment_parent_message_source_local_key",
            "attachment_source_media_type",
            "attachment_source_processing_state",
            "attachment_source_failure_code",
            "attachment_source_content_fingerprint",
            "attachment_source_size_bytes",
            "attachment_source_byte_count",
            "attachment_source_stored_byte_count",
            "attachment_source_name_fingerprint",
            "attachment_filename",
            "attachment_name_fingerprint",
            "attachment_content_fingerprint",
            "attachment_size_bytes",
            "attachment_source_byte_count",
            "attachment_processing_state",
            "attachment_text_extraction_state",
            "attachment_source_char_count",
            "attachment_stored_char_count",
            "attachment_stored_byte_count",
            "attachment_text_segments_fingerprint",
        ):
            if payload.get(field_name) != attachment_payload.get(field_name):
                raise ContractValidationError("PST attachment text binding is invalid")
        if payload.get("text_extraction_state") != attachment_payload.get("text_extraction_state"):
            raise ContractValidationError("PST attachment text state segment binding is invalid")
        if payload.get("attachment_id") != attachment_payload.get("attachment_id"):
            raise ContractValidationError("PST attachment text identity is invalid")
        if payload.get("attachment_ordinal") != attachment_payload.get("attachment_ordinal"):
            raise ContractValidationError("PST attachment text ordinal is invalid")
        if payload.get("attachment_text_segment_index") != observation.location.get(
            "attachment_text_segment_index"
        ):
            raise ContractValidationError("PST attachment text segment index is invalid")
        _validate_pst_attachment_text_segment_projection(
            observation,
            parent_observation=attachment_observation,
        )
        text_by_attachment.setdefault(attachment_key_for_observation, []).append(observation)
    for (
        attachment_key_for_observation,
        attachment_observation,
    ) in observations_by_attachment_id.items():
        attachment_id = attachment_key_for_observation[1]
        attachment_payload = _pst_observation_payload(attachment_observation)
        parent_count = _pst_exact_int(
            attachment_payload.get("extracted_text_segment_count"),
            "attachment text segment count",
        )
        segments = list(text_by_attachment.get(attachment_key_for_observation, []))
        if len(segments) != parent_count:
            raise ContractValidationError("PST attachment text segment count is invalid")
        if attachment_payload["attachment_processing_state"] != "parsed" and segments:
            raise ContractValidationError("PST nonparsed attachment has text evidence")
        indices: list[int] = []
        for item in segments:
            segment_payload = _pst_observation_payload(item)
            segment_count = segment_payload.get("attachment_text_segment_count")
            segment_count = _pst_exact_int(
                segment_count,
                "attachment text segment total",
            )
            if segment_count != parent_count:
                raise ContractValidationError("PST attachment text segment total is invalid")
            segment_index = segment_payload.get("attachment_text_segment_index")
            location_index = item.location.get("attachment_text_segment_index")
            segment_index = _pst_exact_int(
                segment_index,
                "attachment text segment index",
                minimum=1,
            )
            location_index = _pst_exact_int(
                location_index,
                "attachment text segment location index",
                minimum=1,
            )
            if segment_index != location_index:
                raise ContractValidationError("PST attachment text segment index is invalid")
            indices.append(segment_index)
        segments.sort(
            key=lambda item: _pst_observation_payload(item)["attachment_text_segment_index"]
        )
        if len(set(indices)) != len(indices) or sorted(indices) != list(range(1, parent_count + 1)):
            raise ContractValidationError("PST attachment text segment order is invalid")
        if any(not isinstance(item.text, str) for item in segments):
            raise ContractValidationError("PST attachment text segment value is invalid")
        segment_texts = [item.text for item in segments]
        if sha256_json(segment_texts) != attachment_payload["attachment_text_segments_fingerprint"]:
            raise ContractValidationError("PST attachment text content binding is invalid")
        if (
            sum(len(text) for text in segment_texts)
            != attachment_payload["attachment_stored_char_count"]
        ):
            raise ContractValidationError("PST attachment stored character count is invalid")
        if (
            sum(len(text.encode("utf-8")) for text in segment_texts)
            != attachment_payload["attachment_stored_byte_count"]
        ):
            raise ContractValidationError("PST attachment stored byte count is invalid")
        if (
            attachment_payload["attachment_source_stored_byte_count"]
            != attachment_payload["attachment_stored_byte_count"]
        ):
            raise ContractValidationError("PST attachment source/stored byte mirror is invalid")
        for index, item in enumerate(segments, start=1):
            payload = _pst_observation_payload(item)
            if payload.get("attachment_text_segment_fingerprint") != sha256_json(item.text or ""):
                raise ContractValidationError("PST attachment text fingerprint is invalid")
            if payload.get("attachment_text_segment_index") != index:
                raise ContractValidationError("PST attachment text segment order is invalid")

    structural_by_item_id = {
        structural.source_inventory_item_id: structural for structural in structural_observations
    }
    for attachment_key, attachment_item in attachment_items.items():
        attachment_payload = _pst_observation_payload(
            observations_by_attachment_key[attachment_key]
        )
        table_items = [
            item
            for item in inventory.items
            if item.structure_kind == "html_table"
            and _pst_inventory_descends_from(
                item,
                ancestor_key=attachment_key,
                item_by_key=items_by_key,
            )
        ]
        embedded_message_attachment = attachment_item.content_type == "message/rfc822"
        if not embedded_message_attachment and (
            attachment_item.processing_state != "parsed"
            or attachment_item.content_type != "text/html"
        ):
            if table_items:
                raise ContractValidationError(
                    "PST non-HTML attachment has structural table evidence"
                )
            continue
        for table_item in table_items:
            structural = structural_by_item_id.get(table_item.source_inventory_item_id)
            if structural is None:
                raise ContractValidationError("PST attachment table observation is missing")
            if structural.source_observation_id not in table_item.source_observation_ids:
                raise ContractValidationError("PST attachment table source is invalid")
            _pst_exact_ordinal(structural.table_ordinal, "table_ordinal")
            _pst_exact_ordinal(structural.mime_ordinal, "mime_ordinal")
            if structural.attachment_ordinal is not None:
                _pst_exact_ordinal(structural.attachment_ordinal, "attachment_ordinal")
            _pst_exact_ordinal(table_item.location.get("table_ordinal"), "table_ordinal")
            _pst_exact_ordinal(table_item.location.get("mime_ordinal"), "mime_ordinal")
            if table_item.location.get("attachment_ordinal") is not None:
                _pst_exact_ordinal(
                    table_item.location.get("attachment_ordinal"),
                    "attachment_ordinal",
                )
            if structural.table_ordinal != table_item.location.get("table_ordinal"):
                raise ContractValidationError("PST attachment table ordinal is invalid")
            if structural.mime_ordinal != table_item.location.get("mime_ordinal"):
                raise ContractValidationError("PST attachment table MIME ordinal is invalid")
            if structural.attachment_ordinal != table_item.location.get("attachment_ordinal"):
                raise ContractValidationError("PST attachment table attachment ordinal is invalid")
            if structural.attachment_ordinal != attachment_payload["attachment_ordinal"]:
                raise ContractValidationError("PST attachment table ordinal is invalid")
    expected_structural_attachment_ids = {
        item.source_inventory_item_id
        for item in inventory.items
        if item.structure_kind == "html_table"
        and any(
            _pst_inventory_descends_from(
                item,
                ancestor_key=attachment_key,
                item_by_key=items_by_key,
            )
            for attachment_key in attachment_items
        )
    }
    observed_structural_attachment_ids = {
        structural.source_inventory_item_id
        for structural in structural_observations
        if structural.attachment_ordinal is not None
    }
    if observed_structural_attachment_ids != expected_structural_attachment_ids:
        raise ContractValidationError("PST attachment structural binding is incomplete")
    for sidecar_key, item in sidecar_files.items():
        mapping_state = item.location.get("source_unit_attachment_state")
        if mapping_state != "linked":
            if sidecar_key in observations_by_sidecar_key:
                raise ContractValidationError("PST unmapped sidecar has ordinary evidence")
            continue
        linked_id = item.location.get("source_unit_linked_attachment_id")
        occurrence_key = f"{sidecar_key}:attachment"
        occurrence_item = sidecar_occurrence_items.get(occurrence_key)
        if linked_id is None and occurrence_item is None:
            raise ContractValidationError("PST linked sidecar occurrence is missing")
        if linked_id is not None and linked_id not in observations_by_attachment_id_value:
            raise ContractValidationError("PST linked sidecar MIME attachment is missing")
        if linked_id is None and len(observations_by_sidecar_key.get(sidecar_key, ())) != 1:
            raise ContractValidationError("PST sidecar attachment occurrence is not bijective")


def _validate_pst_attachment_text_state(
    payload: Mapping[str, Any],
    *,
    item: SourceInventoryItem,
    source_location: Mapping[str, Any],
) -> None:
    """Validate the closed text-state/count mirror for one attachment."""

    required_fields = {
        "text_extraction_state",
        "extracted_text_segment_count",
        "attachment_processing_state",
        "attachment_text_extraction_state",
        "attachment_stored_char_count",
        "attachment_stored_byte_count",
        "attachment_source_stored_byte_count",
    }
    if not required_fields.issubset(payload):
        raise ContractValidationError("PST attachment text mirror is incomplete")

    inventory_location = item.location
    expected_text_state = inventory_location.get("attachment_text_extraction_state")
    if payload["text_extraction_state"] != expected_text_state:
        raise ContractValidationError("PST attachment text state is not inventory-bound")
    if payload["attachment_text_extraction_state"] != expected_text_state:
        raise ContractValidationError("PST attachment text state mirror is not canonical")
    expected_processing_state = item.processing_state
    if payload["attachment_processing_state"] != expected_processing_state:
        raise ContractValidationError("PST attachment processing state is not canonical")
    if payload.get("attachment_failure_code") != inventory_location.get("attachment_failure_code"):
        raise ContractValidationError("PST attachment failure binding is not canonical")

    source_text_state = source_location.get(
        "source_unit_attachment_text_extraction_state",
        source_location.get("attachment_text_extraction_state"),
    )
    if source_text_state != expected_text_state:
        raise ContractValidationError("PST attachment source text state is not canonical")
    if (
        source_location.get(
            "source_unit_attachment_stored_char_count",
            inventory_location.get("attachment_stored_char_count"),
        )
        != payload["attachment_stored_char_count"]
    ):
        raise ContractValidationError("PST attachment source character count is not canonical")
    if (
        source_location.get(
            "source_unit_attachment_stored_byte_count",
            inventory_location.get("attachment_stored_byte_count"),
        )
        != payload["attachment_stored_byte_count"]
    ):
        raise ContractValidationError("PST attachment source byte count is not canonical")

    processing_state = payload["attachment_processing_state"]
    text_state = payload["text_extraction_state"]
    content_type = item.content_type
    text_capable = content_type.startswith("text/") or content_type in {
        "application/json",
        "application/xml",
        "application/xhtml+xml",
    }
    parsed_text_states = {"complete", "partial", "truncated", "redacted"}
    if processing_state == "parsed":
        if content_type == "message/rfc822":
            if text_state != "not_text":
                raise ContractValidationError("PST embedded attachment text state is invalid")
        elif text_capable:
            if text_state not in parsed_text_states:
                raise ContractValidationError("PST parsed attachment text state is invalid")
        else:
            raise ContractValidationError("PST parsed attachment media state is invalid")
    elif processing_state == "failed":
        if text_state != "failed" or not payload["attachment_failure_code"]:
            raise ContractValidationError("PST failed attachment text state is invalid")
    elif processing_state == "preserved_unparsed":
        if text_state not in {"too_large", "failed"} or (
            text_state == "failed" and not payload.get("attachment_failure_code")
        ):
            raise ContractValidationError("PST preserved attachment text state is invalid")
    elif processing_state == "unsupported":
        if text_state != "unsupported":
            raise ContractValidationError("PST unsupported attachment text state is invalid")
    else:
        raise ContractValidationError("PST attachment processing state is invalid")

    count = _pst_exact_int(
        payload["extracted_text_segment_count"],
        "attachment text segment count",
    )
    numeric_fields = (
        "size_bytes",
        "attachment_size_bytes",
        "attachment_source_byte_count",
        "attachment_source_size_bytes",
        "attachment_source_char_count",
        "attachment_stored_char_count",
        "attachment_stored_byte_count",
        "attachment_source_stored_byte_count",
    )
    for field_name in numeric_fields:
        value = payload.get(field_name)
        if value is not None:
            _pst_exact_int(value, f"attachment {field_name}")
    if processing_state == "parsed" and text_state in parsed_text_states:
        _pst_exact_int(
            payload.get("attachment_source_char_count"),
            "parsed attachment source character count",
        )
    if processing_state != "parsed" or text_state == "not_text":
        if count != 0:
            raise ContractValidationError("PST non-text attachment has text segments")
        if payload.get("attachment_source_char_count") is not None:
            raise ContractValidationError("PST nonparsed attachment has source characters")
        if payload["attachment_stored_char_count"] != 0:
            raise ContractValidationError("PST nonparsed attachment has stored characters")
        if payload["attachment_stored_byte_count"] != 0:
            raise ContractValidationError("PST nonparsed attachment has stored bytes")
    elif payload.get("attachment_source_char_count") == 0:
        if count != 0 or text_state != "complete":
            raise ContractValidationError("PST decoded-empty attachment state is invalid")
    elif count == 0:
        raise ContractValidationError("PST populated attachment text has no segments")


def _validate_pst_attachment_text_segment_projection(
    observation: Observation,
    *,
    parent_observation: Observation,
) -> None:
    """Require one text segment to equal its canonical parent projection."""

    payload = _pst_observation_payload(observation)
    parent_payload = _pst_observation_payload(parent_observation)
    parent_index = parent_payload.get("attachment_index")
    parent_ordinal = parent_payload.get("attachment_ordinal")
    parent_index = _pst_exact_int(parent_index, "parent attachment index", minimum=1)
    parent_ordinal = _pst_exact_int(parent_ordinal, "parent attachment ordinal", minimum=1)
    if parent_index != parent_ordinal:
        raise ContractValidationError("PST parent attachment index is invalid")
    segment_attachment_index = payload.get("attachment_index")
    location_attachment_index = observation.location.get("attachment_index")
    segment_attachment_index = _pst_exact_int(
        segment_attachment_index,
        "attachment text segment attachment index",
        minimum=1,
    )
    location_attachment_index = _pst_exact_int(
        location_attachment_index,
        "attachment text segment location attachment index",
        minimum=1,
    )
    if segment_attachment_index != parent_index or location_attachment_index != parent_index:
        raise ContractValidationError("PST attachment text segment attachment index is invalid")
    segment_index = payload.get("attachment_text_segment_index")
    location_index = observation.location.get("attachment_text_segment_index")
    segment_index = _pst_exact_int(
        segment_index,
        "PST attachment text segment index",
        minimum=1,
    )
    location_index = _pst_exact_int(
        location_index,
        "PST attachment text segment location index",
        minimum=1,
    )
    if location_index != segment_index:
        raise ContractValidationError("PST attachment text segment index is invalid")

    expected_location = {
        field_name: parent_observation.location[field_name]
        for field_name in (
            "archive_id",
            "mailbox_id",
            "folder_path_hash",
            "message_id",
            "message_occurrence_id",
            "thread_id",
            "occurrence_lineage",
            "parent_message_occurrence_id",
            "parent_attachment_id",
            "embedded_attachment_ordinal",
        )
        if field_name in parent_observation.location
    }
    expected_location.update(
        {
            "attachment_index": parent_index,
            "attachment_id": parent_payload.get("attachment_id"),
            "attachment_text_segment_index": segment_index,
        }
    )

    expected_payload: dict[str, Any] = {}
    payload_mirror_fields = (
        "archive_id",
        "mailbox_id",
        "message_id",
        "message_occurrence_id",
        "occurrence_lineage",
        "parent_message_occurrence_id",
        "parent_attachment_id",
        "embedded_attachment_ordinal",
        "message_occurrence_identity_policy",
        "duplicate_ordinal",
        "thread_id",
        "attachment_id",
        "attachment_ordinal",
        "text_extraction_state",
        "attachment_failure_code",
        "attachment_source",
        "attachment_source_local_key",
        "attachment_processing_state",
        "attachment_source_name_fingerprint",
        "attachment_filename",
        "attachment_name_fingerprint",
        "attachment_content_fingerprint",
        "attachment_size_bytes",
        "attachment_source_byte_count",
        "attachment_source_processing_state",
        "attachment_text_extraction_state",
        "attachment_source_char_count",
        "attachment_stored_char_count",
        "attachment_stored_byte_count",
        "attachment_text_segments_fingerprint",
        "attachment_inventory_item_id",
        "attachment_inventory_source_local_key",
        "attachment_source_inventory_item_id",
        "attachment_source_inventory_source_local_key",
        "attachment_parent_message_source_local_key",
        "attachment_source_media_type",
        "attachment_source_failure_code",
        "attachment_source_content_fingerprint",
        "attachment_source_size_bytes",
        "attachment_source_stored_byte_count",
        "attachment_source_name_fingerprint",
        "message_fingerprint",
    )
    for field_name in payload_mirror_fields:
        if field_name in parent_payload:
            expected_payload[field_name] = parent_payload[field_name]
    expected_payload.update(
        {
            "attachment_index": parent_index,
            "attachment_text_segment_index": segment_index,
            "attachment_text_segment_count": parent_payload.get("extracted_text_segment_count"),
            "attachment_text_segment_fingerprint": sha256_json(observation.text or ""),
        }
    )
    if sha256_json(dict(observation.location)) != sha256_json(expected_location):
        raise ContractValidationError("PST attachment text segment location is not canonical")
    if sha256_json(payload) != sha256_json(expected_payload):
        raise ContractValidationError("PST attachment text segment payload is not canonical")


def _pst_inventory_descends_from(
    item: SourceInventoryItem,
    *,
    ancestor_key: str,
    item_by_key: Mapping[str, SourceInventoryItem],
) -> bool:
    current = item
    seen: set[str] = set()
    while True:
        key = current.location.get("source_local_key")
        if key == ancestor_key:
            return True
        if not isinstance(key, str) or key in seen:
            raise ContractValidationError("PST inventory parent topology is invalid")
        seen.add(key)
        parent_key = current.location.get("parent_source_local_key")
        if not isinstance(parent_key, str) or not parent_key:
            return False
        parent = item_by_key.get(parent_key)
        if parent is None:
            raise ContractValidationError("PST inventory parent is missing")
        current = parent


def _validate_pst_sidecar_inventory_topology(
    sidecar_files: Mapping[str, SourceInventoryItem],
    sidecar_occurrence_items: Mapping[str, SourceInventoryItem],
) -> None:
    """Validate sidecar source/occurrence identity before ordinary rehydration."""

    for sidecar_key, item in sidecar_files.items():
        mapping_state = item.location.get("source_unit_attachment_state")
        occurrence_key = f"{sidecar_key}:attachment"
        occurrence_item = sidecar_occurrence_items.get(occurrence_key)
        linked_id = item.location.get("source_unit_linked_attachment_id")
        if mapping_state != "linked":
            if occurrence_item is not None or linked_id is not None:
                raise ContractValidationError("PST unmapped sidecar has derived evidence")
            continue
        if linked_id is not None:
            if occurrence_item is not None:
                raise ContractValidationError("PST sidecar has duplicate attachment bindings")
            continue
        if occurrence_item is None:
            raise ContractValidationError("PST linked sidecar occurrence is missing")
        location = occurrence_item.location
        if location.get("sidecar_source_local_key") != sidecar_key:
            raise ContractValidationError("PST sidecar source binding is invalid")
        if location.get("attachment_source") != "readpst_sidecar":
            raise ContractValidationError("PST sidecar source kind is invalid")
        if location.get("sidecar_name_fingerprint") != item.location.get(
            "source_unit_attachment_name_fingerprint"
        ):
            raise ContractValidationError("PST sidecar name binding is invalid")
        if (
            item.location.get("source_unit_content_fingerprint") is not None
            and location.get("sidecar_content_fingerprint") is not None
            and item.location["source_unit_content_fingerprint"]
            != location["sidecar_content_fingerprint"]
        ):
            raise ContractValidationError("PST sidecar content binding is invalid")


def _pst_observation_payload(observation: Observation) -> dict[str, Any]:
    if not isinstance(observation.payload, Mapping):
        raise ContractValidationError("PST observation payload is required")
    return dict(observation.payload)


def _pst_header_observations_by_occurrence(
    observations: Sequence[Observation],
) -> dict[str, list[Observation]]:
    """Index header observations once while retaining persisted source order."""

    indexed: dict[str, list[Observation]] = {}
    for observation in observations:
        occurrence_id = _pst_observation_payload(observation).get("message_occurrence_id")
        if isinstance(occurrence_id, str):
            indexed.setdefault(occurrence_id, []).append(observation)
    return indexed


def _pst_require_exact_keys(
    value: Mapping[str, Any],
    required: set[str],
    field_name: str,
    *,
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    if not required.issubset(value) or set(value) - allowed:
        raise ContractValidationError(f"{field_name} shape is not closed")


def _pst_exact_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    """Validate a persisted PST ordinal/count without Python coercion.

    ``bool`` is intentionally rejected even though it is an ``int`` subclass.
    This helper is the single authority for projection ordinals, indexes, and
    counts at the source-specific rehydration boundary.
    """

    if type(value) is not int or value < minimum:
        raise ContractValidationError(f"PST {field_name} is invalid")
    return value


def _pst_validate_inventory_carrier_markers(
    location: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    """Validate the reserved carrier marker in both canonical locations."""

    _pst_require_exact_keys(
        location,
        {"archive_id", "mailbox_id", "carrier_type", "carrier_version"},
        "PST carrier location",
    )
    carrier_type_values = (location["carrier_type"], payload["carrier_type"])
    if any(
        type(value) is not str or value != PST_INVENTORY_CARRIER_OBSERVATION_TYPE
        for value in carrier_type_values
    ):
        raise ContractValidationError("PST carrier type marker is invalid")
    carrier_version_values = (
        _pst_exact_int(location["carrier_version"], "carrier location version"),
        _pst_exact_int(payload["carrier_version"], "carrier payload version"),
    )
    if any(value != PST_INVENTORY_CARRIER_VERSION for value in carrier_version_values):
        raise ContractValidationError("PST carrier version marker is invalid")
    if location["carrier_type"] != payload["carrier_type"] or (
        type(location["carrier_version"]) is not type(payload["carrier_version"])
        or location["carrier_version"] != payload["carrier_version"]
    ):
        raise ContractValidationError("PST carrier marker binding is invalid")


def _pst_validate_source_unit_markers(
    location: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    expected_traversal_ordinal: int,
) -> None:
    """Validate source-unit type/version/policy markers without coercion."""

    marker_types = (location["source_observation_type"], payload["source_observation_type"])
    if any(
        type(value) is not str or value != PST_SOURCE_UNIT_OBSERVATION_TYPE
        for value in marker_types
    ):
        raise ContractValidationError("PST source-unit type marker is invalid")
    marker_versions = (
        _pst_exact_int(location["source_observation_version"], "source location version"),
        _pst_exact_int(payload["source_observation_version"], "source payload version"),
    )
    if any(value != PST_SOURCE_UNIT_OBSERVATION_VERSION for value in marker_versions):
        raise ContractValidationError("PST source-unit version marker is invalid")
    marker_policies = (
        location["source_traversal_binding_policy"],
        payload["source_traversal_binding_policy"],
    )
    if any(
        type(value) is not str or value != _PST_TRAVERSAL_BINDING_POLICY
        for value in marker_policies
    ):
        raise ContractValidationError("PST source-unit policy marker is invalid")
    location_ordinal = _pst_exact_int(
        location["source_traversal_ordinal"],
        "source location traversal ordinal",
        minimum=0,
    )
    payload_ordinal = _pst_exact_int(
        payload["source_traversal_ordinal"],
        "source payload traversal ordinal",
        minimum=0,
    )
    trusted_ordinal = _pst_exact_int(
        expected_traversal_ordinal,
        "trusted source traversal ordinal",
        minimum=0,
    )
    if location_ordinal != trusted_ordinal or payload_ordinal != trusted_ordinal:
        raise ContractValidationError("PST source-unit traversal ordinal is not trusted")
    if (
        location["source_observation_type"] != payload["source_observation_type"]
        or type(location["source_observation_version"])
        is not type(payload["source_observation_version"])
        or location["source_observation_version"] != payload["source_observation_version"]
        or location["source_traversal_binding_policy"] != payload["source_traversal_binding_policy"]
        or location_ordinal != payload_ordinal
    ):
        raise ContractValidationError("PST source-unit marker binding is invalid")


def _pst_exact_bool(value: Any, field_name: str) -> bool:
    """Validate a persisted PST boolean without integer/string coercion."""

    if type(value) is not bool:
        raise ContractValidationError(f"PST {field_name} is invalid")
    return value


def _pst_canonical_confidence(value: Any) -> float:
    """Validate the single confidence authority emitted by the PST extractor."""

    if type(value) is not float or value != 1.0:
        raise ContractValidationError("PST observation confidence is invalid")
    return value


def _pst_canonical_extraction_timestamp(
    value: Any,
    *,
    allow_missing: bool = False,
) -> str:
    """Normalize one extraction timestamp to an aware UTC ISO string."""

    if value is None and allow_missing:
        value = now_iso()
    if type(value) is not str or not value:
        raise ContractValidationError("PST extraction timestamp is invalid")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ContractValidationError("PST extraction timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError("PST extraction timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _pst_validate_observation_timestamp(
    observation: Observation,
    *,
    expected_created_at: str,
) -> None:
    normalized = _pst_canonical_extraction_timestamp(observation.created_at)
    if observation.created_at != normalized or normalized != expected_created_at:
        raise ContractValidationError("PST observation timestamp is not canonical")


def _pst_exact_ordinal(value: Any, field_name: str) -> int:
    """Validate a persisted PST ordinal using its field-specific base."""

    try:
        minimum = _PST_ORDINAL_MINIMUMS[field_name]
    except KeyError as exc:
        raise ContractValidationError("PST ordinal policy is invalid") from exc
    return _pst_exact_int(value, field_name, minimum=minimum)


def _pst_require_archive_binding(
    location: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    archive_id: str,
    mailbox_id: str,
) -> None:
    for value in (location, payload):
        if value.get("archive_id") != archive_id or value.get("mailbox_id") != mailbox_id:
            raise ContractValidationError("PST observation archive binding is invalid")


def _pst_message_observation_binding(
    observation: Observation,
    payload: Mapping[str, Any],
    *,
    archive_id: str,
    mailbox_id: str,
) -> str:
    _pst_require_archive_binding(
        observation.location, payload, archive_id=archive_id, mailbox_id=mailbox_id
    )
    occurrence_id = payload.get("message_occurrence_id")
    if not isinstance(occurrence_id, str) or not occurrence_id:
        raise ContractValidationError("PST message occurrence binding is invalid")
    if observation.location.get("message_occurrence_id") != occurrence_id:
        raise ContractValidationError("PST message occurrence location is invalid")
    return occurrence_id


def _pst_top_level_message_inventory_bindings(
    inventory: SourceInventory,
) -> dict[str, SourceInventoryItem]:
    """Return the one parsed message child for each top-level source unit."""

    items_by_key: dict[str, SourceInventoryItem] = {}
    for item in inventory.items:
        source_local_key = item.location.get("source_local_key")
        if not isinstance(source_local_key, str) or not source_local_key:
            raise ContractValidationError("PST inventory source-local key is invalid")
        if source_local_key in items_by_key:
            raise ContractValidationError("PST inventory source-local key is duplicated")
        items_by_key[source_local_key] = item

    bindings: dict[str, SourceInventoryItem] = {}
    for item in inventory.items:
        if item.structure_kind != "exported_message_occurrence":
            continue
        source_local_key = item.location["source_local_key"]
        parent_source_local_key = item.location.get("parent_source_local_key")
        message_fingerprint = item.location.get("message_fingerprint")
        message_occurrence_id = item.location.get("message_occurrence_id")
        if (
            not isinstance(parent_source_local_key, str)
            or not parent_source_local_key
            or source_local_key != f"{parent_source_local_key}:message"
            or item.content_type != "message/rfc822"
            or item.processing_state != "parsed"
            or type(message_fingerprint) is not str
            or not message_fingerprint
            or type(message_occurrence_id) is not str
            or not message_occurrence_id
        ):
            raise ContractValidationError("PST message inventory binding is invalid")
        parent_item = items_by_key.get(parent_source_local_key)
        if (
            parent_item is None
            or parent_item.structure_kind != "exported_file"
            or parent_item.content_type != "message/rfc822"
            or parent_item.processing_state != "parsed"
        ):
            raise ContractValidationError("PST message inventory parent is invalid")
        if parent_source_local_key in bindings:
            raise ContractValidationError("PST message inventory binding is duplicated")
        bindings[parent_source_local_key] = item
    return bindings


def _pst_canonical_top_level_message_occurrences(
    observations: Sequence[Observation],
    *,
    inventory_bindings: Mapping[str, SourceInventoryItem],
    archive_id: str,
    mailbox_id: str,
    source_traversal_ordinals: Mapping[str, int] | None = None,
) -> dict[str, tuple[int, str]]:
    """Derive top-level occurrence IDs from canonical source topology."""

    entries: list[tuple[SourceInventoryItem, Observation, Mapping[str, Any]]] = []
    seen_inventory_item_ids: set[str] = set()
    for observation in observations:
        payload = _pst_observation_payload(observation)
        if payload.get("parent_message_occurrence_id") is not None:
            continue
        source_local_key = payload.get("message_source_local_key")
        source_inventory_item_id = payload.get("message_source_inventory_item_id")
        if (
            type(source_local_key) is not str
            or not source_local_key
            or type(source_inventory_item_id) is not str
            or not source_inventory_item_id
        ):
            raise ContractValidationError("PST top-level message inventory binding is invalid")
        inventory_item = inventory_bindings.get(source_local_key)
        if (
            inventory_item is None
            or inventory_item.source_inventory_item_id != source_inventory_item_id
            or inventory_item.location.get("parent_source_local_key") != source_local_key
            or source_inventory_item_id in seen_inventory_item_ids
        ):
            raise ContractValidationError("PST top-level message inventory binding is invalid")
        folder_path_hash = observation.location.get("folder_path_hash")
        message_id = payload.get("message_id")
        message_fingerprint = payload.get("message_fingerprint")
        if (
            type(folder_path_hash) is not str
            or not folder_path_hash
            or type(message_id) is not str
            or not message_id
            or type(message_fingerprint) is not str
            or not message_fingerprint
        ):
            raise ContractValidationError("PST top-level message occurrence identity is invalid")
        seen_inventory_item_ids.add(source_inventory_item_id)
        entries.append((inventory_item, observation, payload))

    entries.sort(
        key=lambda entry: (
            _pst_exact_int(
                (
                    entry[0].ordinal
                    if source_traversal_ordinals is None
                    else source_traversal_ordinals.get(entry[0].source_inventory_item_id)
                ),
                "message traversal ordinal",
                minimum=1,
            ),
            str(entry[0].location["source_local_key"]),
        )
    )
    duplicate_ordinals: dict[tuple[str, str, str], int] = {}
    expected: dict[str, tuple[int, str]] = {}
    for inventory_item, observation, payload in entries:
        identity_key = (
            str(observation.location["folder_path_hash"]),
            str(payload["message_id"]),
            str(payload["message_fingerprint"]),
        )
        duplicate_ordinal = duplicate_ordinals.get(identity_key, 0) + 1
        duplicate_ordinals[identity_key] = duplicate_ordinal
        expected[inventory_item.source_inventory_item_id] = (
            duplicate_ordinal,
            _pst_message_occurrence_id_from_fields(
                archive_id=archive_id,
                mailbox_id=mailbox_id,
                folder_path_hash=identity_key[0],
                message_id=identity_key[1],
                message_fingerprint=identity_key[2],
                duplicate_ordinal=duplicate_ordinal,
            ),
        )
    return expected


def _pst_canonical_index_map(values: Mapping[str, Any] | Iterable[str]) -> dict[str, int]:
    keys = list(values)
    if any(type(key) is not str or not key for key in keys):
        raise ContractValidationError("PST positional index keys are invalid")
    if len(keys) != len(set(keys)):
        raise ContractValidationError("PST positional index keys are duplicated")
    return {key: index for index, key in enumerate(sorted(keys), start=1)}


def _pst_traversal_binding_fingerprint(
    *,
    source_local_key: str,
    parent_source_local_key: str | None,
    ordinal: int,
) -> str:
    if type(source_local_key) is not str or not source_local_key:
        raise ContractValidationError("PST traversal binding source identity is invalid")
    if parent_source_local_key is not None and (
        type(parent_source_local_key) is not str or not parent_source_local_key
    ):
        raise ContractValidationError("PST traversal binding parent identity is invalid")
    if type(ordinal) is not int or isinstance(ordinal, bool) or ordinal < 0:
        raise ContractValidationError("PST traversal binding ordinal is invalid")
    return sha256_json(
        {
            "policy": _PST_TRAVERSAL_BINDING_POLICY,
            "source_local_key": source_local_key,
            "parent_source_local_key": parent_source_local_key,
            "ordinal": ordinal,
        }
    )


def _pst_trusted_source_traversal_ordinals(
    inventory: SourceInventory,
    *,
    trusted_traversal_binding: PstTraversalBinding,
    asset_id: str,
    extractor_run_id: str,
    expected_source_fingerprint: str | None,
) -> dict[str, int]:
    """Validate and return the trusted run-level traversal ordinal map."""

    binding = trusted_traversal_binding
    _pst_assert_issued_traversal_binding(binding)
    if (
        binding.asset_id != asset_id
        or binding.extractor_run_id != extractor_run_id
        or binding.source_fingerprint
        != (expected_source_fingerprint or inventory.source_fingerprint)
        or binding.source_inventory_id != inventory.source_inventory_id
        or binding.parser_fingerprint != inventory.parser_fingerprint
    ):
        raise ContractValidationError("PST trusted traversal binding provenance mismatch")

    expected_entries = _pst_traversal_entries(inventory)
    if binding.entries != expected_entries:
        raise ContractValidationError("PST trusted traversal binding does not match inventory")
    embedded_message_bindings = binding.embedded_message_bindings
    partial_inventory_state = binding.partial_inventory_state
    if type(partial_inventory_state) is not bool:
        raise ContractValidationError("PST partial inventory state is invalid")
    if type(embedded_message_bindings) is not tuple:
        raise ContractValidationError("PST embedded message binding authority is invalid")
    for entry in embedded_message_bindings:
        if type(entry) is not tuple or len(entry) != 8:
            raise ContractValidationError("PST embedded message binding authority is invalid")
        (
            parent_attachment_item_id,
            attached_message_item_id,
            parent_occurrence_id,
            parent_attachment_id,
            embedded_attachment_ordinal,
            message_occurrence_id,
            message_fingerprint,
            message_id,
        ) = entry
        if (
            not all(
                type(value) is str and bool(value)
                for value in (
                    parent_attachment_item_id,
                    attached_message_item_id,
                    parent_occurrence_id,
                    parent_attachment_id,
                    message_occurrence_id,
                    message_fingerprint,
                    message_id,
                )
            )
            or type(embedded_attachment_ordinal) is not int
            or isinstance(embedded_attachment_ordinal, bool)
            or embedded_attachment_ordinal < 1
        ):
            raise ContractValidationError("PST embedded message binding authority is invalid")
    expected_commitment = _pst_traversal_commitment(
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        source_fingerprint=expected_source_fingerprint or inventory.source_fingerprint,
        source_inventory_id=inventory.source_inventory_id,
        parser_fingerprint=inventory.parser_fingerprint,
        entries=expected_entries,
        folder_label_bindings=binding.folder_label_bindings,
        embedded_message_bindings=embedded_message_bindings,
        partial_inventory_state=partial_inventory_state,
    )
    if binding.commitment != expected_commitment:
        raise ContractValidationError("PST trusted traversal commitment is invalid")
    return {
        source_inventory_item_id: ordinal
        for source_inventory_item_id, _source_local_key, _parent_key, ordinal, _source_ids in binding.entries
    }


def _pst_trusted_embedded_message_occurrences(
    inventory: SourceInventory,
    *,
    trusted_traversal_binding: PstTraversalBinding,
    source_traversal_ordinals: Mapping[str, int],
    archive_id: str,
    mailbox_id: str,
) -> dict[str, tuple[int, str, str, str]]:
    """Derive embedded duplicate ordinals from trusted physical sibling order."""

    del inventory
    ordered_bindings = sorted(
        trusted_traversal_binding.embedded_message_bindings,
        key=lambda entry: (
            source_traversal_ordinals.get(entry[1], -1),
            entry[1],
        ),
    )
    seen_attached_item_ids: set[str] = set()
    duplicate_ordinals: dict[tuple[str, str, str], int] = {}
    expected: dict[str, tuple[int, str, str, str]] = {}
    for entry in ordered_bindings:
        (
            parent_attachment_item_id,
            attached_message_item_id,
            parent_occurrence_id,
            parent_attachment_id,
            embedded_attachment_ordinal,
            message_occurrence_id,
            message_fingerprint,
            message_id,
        ) = entry
        if (
            attached_message_item_id in seen_attached_item_ids
            or attached_message_item_id not in source_traversal_ordinals
        ):
            raise ContractValidationError("PST embedded message sibling order is invalid")
        seen_attached_item_ids.add(attached_message_item_id)
        identity_key = (parent_occurrence_id, message_id, message_fingerprint)
        duplicate_ordinal = duplicate_ordinals.get(identity_key, 0) + 1
        duplicate_ordinals[identity_key] = duplicate_ordinal
        expected_occurrence_id = _pst_message_occurrence_id_from_fields(
            archive_id=archive_id,
            mailbox_id=mailbox_id,
            folder_path_hash="",
            parent_occurrence_id=parent_occurrence_id,
            parent_attachment_id=parent_attachment_id,
            embedded_attachment_ordinal=embedded_attachment_ordinal,
            message_id=message_id,
            message_fingerprint=message_fingerprint,
            duplicate_ordinal=duplicate_ordinal,
        )
        if message_occurrence_id != expected_occurrence_id:
            raise ContractValidationError("PST embedded message occurrence authority is invalid")
        expected[attached_message_item_id] = (
            duplicate_ordinal,
            expected_occurrence_id,
            message_id,
            message_fingerprint,
        )
    return expected


def _pst_trusted_folder_label_map(
    inventory: SourceInventory,
    *,
    trusted_traversal_binding: PstTraversalBinding | None,
) -> dict[str, str]:
    """Return labels issued with the trusted physical message roots."""

    if trusted_traversal_binding is None:
        return {}
    _pst_assert_issued_traversal_binding(trusted_traversal_binding)
    top_level_item_ids = {
        item.source_inventory_item_id
        for item in _pst_top_level_message_inventory_bindings(inventory).values()
    }
    labels: dict[str, str] = {}
    seen_source_item_ids: set[str] = set()
    bindings = trusted_traversal_binding.folder_label_bindings
    if type(bindings) is not tuple:
        raise ContractValidationError("PST trusted folder labels are invalid")
    for entry in bindings:
        if type(entry) is not tuple or len(entry) != 3:
            raise ContractValidationError("PST trusted folder label binding is invalid")
        folder_path_hash, folder_label, source_inventory_item_ids = entry
        if (
            type(folder_path_hash) is not str
            or not folder_path_hash
            or type(folder_label) is not str
            or not folder_label
            or type(source_inventory_item_ids) is not tuple
            or not source_inventory_item_ids
            or any(type(item_id) is not str or not item_id for item_id in source_inventory_item_ids)
            or tuple(sorted(source_inventory_item_ids)) != source_inventory_item_ids
            or len(set(source_inventory_item_ids)) != len(source_inventory_item_ids)
        ):
            raise ContractValidationError("PST trusted folder label binding is invalid")
        if folder_path_hash in labels:
            raise ContractValidationError("PST trusted folder labels are duplicated")
        if any(item_id not in top_level_item_ids for item_id in source_inventory_item_ids):
            raise ContractValidationError("PST trusted folder label inventory binding is invalid")
        if seen_source_item_ids.intersection(source_inventory_item_ids):
            raise ContractValidationError(
                "PST trusted folder label inventory binding is duplicated"
            )
        labels[folder_path_hash] = folder_label
        seen_source_item_ids.update(source_inventory_item_ids)
    return labels


def _pst_validate_inventory_positional_binding(
    inventory: SourceInventory,
    *,
    asset_id: str | None = None,
    extractor_run_id: str | None = None,
    trusted_source_traversal_ordinals: Mapping[str, int] | None = None,
) -> None:
    """Validate the positional fields needed by source-unit cross-binding."""

    for item in inventory.items:
        source_local_key = item.location.get("source_local_key")
        if type(source_local_key) is not str or not source_local_key:
            raise ContractValidationError("PST inventory source identity is invalid")
        if type(item.ordinal) is not int or isinstance(item.ordinal, bool) or item.ordinal < 0:
            raise ContractValidationError("PST inventory traversal ordinal is invalid")
        expected_ordinal = item.ordinal
        if trusted_source_traversal_ordinals is not None:
            expected_ordinal = trusted_source_traversal_ordinals.get(item.source_inventory_item_id)
            if expected_ordinal is None or item.ordinal != expected_ordinal:
                raise ContractValidationError("PST inventory traversal order is not trusted")
        if item.structure_kind == "archive":
            valid_source_reference_counts = {0, 1}
        else:
            valid_source_reference_counts = {1}
        if len(item.source_observation_ids) not in valid_source_reference_counts:
            raise ContractValidationError("PST inventory source observation binding is invalid")
        if asset_id is not None or extractor_run_id is not None:
            if (
                not isinstance(asset_id, str)
                or not asset_id
                or not isinstance(extractor_run_id, str)
                or not extractor_run_id
            ):
                raise ContractValidationError(
                    "PST inventory source observation authority is invalid"
                )
            parent_source_local_key = item.location.get("parent_source_local_key")
            traversal_binding = _pst_traversal_binding_fingerprint(
                source_local_key=source_local_key,
                parent_source_local_key=parent_source_local_key,
                ordinal=expected_ordinal,
            )
            source_binding_fingerprint = item.location.get("cell_occupancy_fingerprint")
            if item.structure_kind in _PST_STRUCTURAL_INVENTORY_KINDS and (
                type(source_binding_fingerprint) is not str or not source_binding_fingerprint
            ):
                raise ContractValidationError("PST structural occupancy authority is missing")
            if item.structure_kind not in _PST_STRUCTURAL_INVENTORY_KINDS and (
                source_binding_fingerprint is not None
            ):
                raise ContractValidationError("PST nonstructural occupancy authority is invalid")
            expected_source_observation_id = _pst_source_observation_id_from_fields(
                asset_id=asset_id,
                extractor_run_id=extractor_run_id,
                source_local_key=source_local_key,
                traversal_binding_fingerprint=traversal_binding,
                source_binding_fingerprint=source_binding_fingerprint,
            )
            if item.structure_kind == "archive" and not item.source_observation_ids:
                continue
            if item.source_observation_ids != (expected_source_observation_id,):
                raise ContractValidationError(
                    "PST inventory source observation authority is invalid"
                )


def _pst_source_traversal_ordinals_from_stream(
    observations: Sequence[Observation],
) -> dict[str, int]:
    """Return the source-unit traversal order independently of the carrier."""

    ordinals: dict[str, int] = {}
    for observation in observations:
        if observation.observation_type != PST_SOURCE_UNIT_OBSERVATION_TYPE:
            continue
        payload = _pst_observation_payload(observation)
        source_inventory_item_id = payload.get("source_inventory_item_id")
        ordinal = payload.get("source_traversal_ordinal")
        if type(source_inventory_item_id) is not str or not source_inventory_item_id:
            raise ContractValidationError("PST source traversal identity is invalid")
        if type(ordinal) is not int or isinstance(ordinal, bool) or ordinal < 0:
            raise ContractValidationError("PST source traversal ordinal is invalid")
        if source_inventory_item_id in ordinals:
            raise ContractValidationError("PST source traversal identity is duplicated")
        ordinals[source_inventory_item_id] = ordinal
    return ordinals


def _pst_canonical_message_context_order(
    contexts: Sequence[_MailMessageContext],
    *,
    source_inventory: SourceInventory | None,
    source_traversal_ordinals: Mapping[str, int] | None = None,
) -> tuple[_MailMessageContext, ...]:
    """Derive the shared depth-first physical order for message observations."""

    if source_inventory is None:
        return tuple(contexts)
    top_level_bindings = _pst_top_level_message_inventory_bindings(source_inventory)
    context_by_occurrence = {context.occurrence_id: context for context in contexts}
    key_by_occurrence: dict[str, tuple[int, ...]] = {}
    seen_order_keys: set[tuple[int, ...]] = set()
    active: set[str] = set()

    def order_key(context: _MailMessageContext) -> tuple[int, ...]:
        cached = key_by_occurrence.get(context.occurrence_id)
        if cached is not None:
            return cached
        if context.occurrence_id in active:
            raise ContractValidationError("PST message lineage contains a cycle")
        active.add(context.occurrence_id)
        if context.parent_occurrence_id is None:
            source_local_key = context.message.source_local_key
            item = top_level_bindings.get(source_local_key)
            if item is None:
                raise ContractValidationError("PST message inventory order binding is missing")
            traversal_ordinal = (
                item.ordinal
                if source_traversal_ordinals is None
                else source_traversal_ordinals.get(item.source_inventory_item_id)
            )
            key = (
                _pst_exact_int(
                    traversal_ordinal,
                    "message traversal ordinal",
                    minimum=1,
                ),
            )
        else:
            parent = context_by_occurrence.get(context.parent_occurrence_id)
            if parent is None:
                raise ContractValidationError("PST message order parent is missing")
            attachment_ordinal = _pst_exact_int(
                context.message.embedded_attachment_ordinal,
                "embedded attachment ordinal",
                minimum=1,
            )
            key = order_key(parent) + (attachment_ordinal,)
        active.remove(context.occurrence_id)
        if key in seen_order_keys:
            raise ContractValidationError("PST message physical order is duplicated")
        seen_order_keys.add(key)
        key_by_occurrence[context.occurrence_id] = key
        return key

    keyed = [(order_key(context), context) for context in contexts]
    return tuple(context for _key, context in sorted(keyed, key=lambda item: item[0]))


def _pst_rehydrate_body_segments(
    body_observations: Sequence[Observation],
    *,
    parent_observation: Observation,
    parent_payload: Mapping[str, Any],
) -> list[_ParsedBodySegment]:
    """Rebuild and validate the canonical message body projection."""

    body_projection_policy = parent_payload.get("body_projection_policy")
    if body_projection_policy != _PST_BODY_PROJECTION_POLICY:
        raise ContractValidationError("PST body projection policy is invalid")
    projection_state = parent_payload.get("body_projection_state")
    if projection_state not in _PST_BODY_PROJECTION_STATES:
        raise ContractValidationError("PST body projection state is invalid")
    evidence_state = parent_payload.get("body_evidence_state")
    if evidence_state not in {"complete", "partial", "failed", "truncated", "redacted"}:
        raise ContractValidationError("PST body evidence state is invalid")
    source_count = parent_payload.get("source_body_char_count")
    stored_count = parent_payload.get("stored_body_char_count")
    segment_count = parent_payload.get("body_segment_count")
    redacted_count = parent_payload.get("body_redacted_segment_count")
    failure_codes = parent_payload.get("body_failure_codes")
    for value, field_name in (
        (source_count, "source body character count"),
        (stored_count, "stored body character count"),
        (segment_count, "body segment count"),
        (redacted_count, "body redacted segment count"),
    ):
        if value is not None:
            _pst_exact_int(value, field_name)
    _pst_exact_int(stored_count, "stored body character count")
    _pst_exact_int(segment_count, "body segment count")
    _pst_exact_int(redacted_count, "body redacted segment count")
    if not isinstance(failure_codes, list) or any(
        not isinstance(code, str) or not code for code in failure_codes
    ):
        raise ContractValidationError("PST body failure codes are invalid")
    if len(set(failure_codes)) != len(failure_codes):
        raise ContractValidationError("PST body failure codes are duplicated")
    expected_state = {
        "bodyless_empty": "complete",
        "decoded_empty": "complete",
        "complete": "complete",
        "partial": "partial",
        "failed": "failed",
        "truncated": "truncated",
        "redacted": "redacted",
    }[projection_state]
    if evidence_state != expected_state:
        raise ContractValidationError("PST body projection/evidence state is invalid")
    if projection_state in {"bodyless_empty", "decoded_empty"}:
        if source_count != 0 or stored_count != 0 or segment_count != 0 or failure_codes:
            raise ContractValidationError("PST empty body projection is invalid")
    elif projection_state == "failed":
        if source_count is not None or stored_count != 0 or segment_count != 0 or not failure_codes:
            raise ContractValidationError("PST failed body projection is invalid")
    elif projection_state == "partial":
        if source_count is not None or not failure_codes:
            raise ContractValidationError("PST partial body projection is invalid")
    elif projection_state in {"complete", "truncated", "redacted"}:
        if source_count is None or failure_codes:
            raise ContractValidationError("PST complete body projection is invalid")
        if projection_state in {"truncated", "redacted"} and segment_count == 0:
            raise ContractValidationError("PST nonempty body projection is invalid")
        if projection_state == "redacted" and redacted_count == 0:
            raise ContractValidationError("PST redacted body projection is invalid")
    if projection_state != "redacted" and redacted_count != 0:
        raise ContractValidationError("PST body redaction count is invalid")

    segments: list[_ParsedBodySegment] = []
    for observation in body_observations:
        payload = _pst_observation_payload(observation)
        _pst_require_exact_keys(
            observation.location,
            {
                "archive_id",
                "mailbox_id",
                "folder_path_hash",
                "message_id",
                "message_occurrence_id",
                "thread_id",
                "body_segment_index",
                "char_start",
                "char_end",
                "body_projection_policy",
                "body_projection_fingerprint",
            },
            "PST body location",
            optional={
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
            },
        )
        _pst_require_exact_keys(
            payload,
            {
                "archive_id",
                "mailbox_id",
                "message_id",
                "message_occurrence_id",
                "message_occurrence_identity_policy",
                "duplicate_ordinal",
                "thread_id",
                "body_segment_index",
                "body_segment_count",
                "body_hash",
                "source_body_char_count",
                "stored_body_char_count",
                "body_evidence_state",
                "body_projection_policy",
                "body_projection_state",
                "body_projection_fingerprint",
                "body_failure_codes",
                "body_redacted_segment_count",
                "content_publicly_unsafe",
                "message_fingerprint",
            },
            "PST body payload",
            optional={
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
            },
        )
        if not isinstance(observation.text, str):
            raise ContractValidationError("PST body segment text is invalid")
        if any(
            payload.get(field_name) != parent_payload.get(field_name)
            for field_name in (
                "archive_id",
                "mailbox_id",
                "message_id",
                "message_occurrence_id",
                "message_occurrence_identity_policy",
                "duplicate_ordinal",
                "thread_id",
                "body_segment_count",
                "body_hash",
                "source_body_char_count",
                "stored_body_char_count",
                "body_evidence_state",
                "body_projection_policy",
                "body_projection_state",
                "body_projection_fingerprint",
                "body_failure_codes",
                "body_redacted_segment_count",
            )
        ):
            raise ContractValidationError("PST body segment parent projection binding is invalid")
        payload_segment_count = payload.get("body_segment_count")
        payload_segment_count = _pst_exact_int(
            payload_segment_count,
            "body segment count",
        )
        if payload_segment_count != segment_count:
            raise ContractValidationError("PST body segment count is invalid")
        relation_fields = (
            "occurrence_lineage",
            "parent_message_occurrence_id",
            "parent_attachment_id",
            "embedded_attachment_ordinal",
        )
        if {field_name for field_name in relation_fields if field_name in payload} != {
            field_name for field_name in relation_fields if field_name in parent_payload
        } or any(
            payload.get(field_name) != parent_payload.get(field_name)
            for field_name in relation_fields
        ):
            raise ContractValidationError("PST body segment lineage binding is invalid")
        index = payload.get("body_segment_index")
        location_index = observation.location.get("body_segment_index")
        start = observation.location.get("char_start")
        end = observation.location.get("char_end")
        index = _pst_exact_int(index, "body segment index", minimum=1)
        location_index = _pst_exact_int(
            location_index,
            "body segment location index",
            minimum=1,
        )
        start = _pst_exact_int(start, "body segment start")
        end = _pst_exact_int(end, "body segment end")
        if location_index != index or end <= start:
            raise ContractValidationError("PST body segment range is invalid")
        if observation.location.get(
            "body_projection_policy"
        ) != body_projection_policy or observation.location.get(
            "body_projection_fingerprint"
        ) != parent_payload.get("body_projection_fingerprint"):
            raise ContractValidationError("PST body segment location projection binding is invalid")
        expected_location = {
            key: value
            for key, value in parent_observation.location.items()
            if key != "message_index"
        }
        expected_location.update(
            {
                "body_segment_index": index,
                "char_start": start,
                "char_end": end,
                "body_projection_policy": body_projection_policy,
                "body_projection_fingerprint": parent_payload["body_projection_fingerprint"],
            }
        )
        if dict(observation.location) != expected_location:
            raise ContractValidationError("PST body segment location is not canonical")
        unsafe = _pst_exact_bool(
            payload.get("content_publicly_unsafe"),
            "body segment safety marker",
        )
        if end - start != len(observation.text) and not (unsafe and projection_state == "redacted"):
            raise ContractValidationError("PST body segment range/text binding is invalid")
        segments.append(
            _ParsedBodySegment(
                text=observation.text,
                char_start=start,
                char_end=end,
                content_publicly_unsafe=unsafe,
                segment_index=index,
            )
        )

    if len(segments) != segment_count:
        raise ContractValidationError("PST body segment count does not match parent")
    segments.sort(key=lambda item: item.char_start)
    if len({item.char_start for item in segments}) != len(segments):
        raise ContractValidationError("PST body segment ranges are duplicated")
    if sorted(
        _pst_observation_payload(observation).get("body_segment_index")
        for observation in body_observations
    ) != list(range(1, segment_count + 1)):
        raise ContractValidationError("PST body segment indexes are not contiguous")
    if any(
        segment.segment_index != expected_index
        for expected_index, segment in enumerate(segments, start=1)
    ):
        raise ContractValidationError("PST body segment index/range order is invalid")
    previous_end = 0
    for segment in segments:
        if segment.char_start != previous_end:
            raise ContractValidationError("PST body segment ranges contain a gap or overlap")
        previous_end = segment.char_end
    if sum(len(segment.text) for segment in segments) != stored_count:
        raise ContractValidationError("PST stored body character count is invalid")
    if source_count is not None and previous_end != source_count:
        raise ContractValidationError("PST source body character count is invalid")
    if projection_state in {"bodyless_empty", "decoded_empty", "failed"} and segments:
        raise ContractValidationError("PST empty or failed body has segment evidence")
    if projection_state == "redacted" and redacted_count != sum(
        segment.content_publicly_unsafe for segment in segments
    ):
        raise ContractValidationError("PST body redaction count is invalid")
    computed = _body_projection_fingerprint(
        body_segments=segments,
        body_projection_state=projection_state,
        body_evidence_state=evidence_state,
        source_body_char_count=source_count,
        stored_body_char_count=stored_count,
        body_failure_codes=failure_codes,
        body_redacted_segment_count=redacted_count,
    )
    if computed != parent_payload.get("body_projection_fingerprint"):
        raise ContractValidationError("PST body projection fingerprint is invalid")
    if parent_observation.location.get("message_occurrence_id") != parent_payload.get(
        "message_occurrence_id"
    ):
        raise ContractValidationError("PST body parent occurrence binding is invalid")
    return segments


def _pst_rehydrate_message(
    observation: Observation,
    payload: Mapping[str, Any],
    *,
    archive_id: str,
    mailbox_id: str,
    folder_paths: Mapping[str, str],
    attachments: Sequence[Observation],
    body_observations: Sequence[Observation],
    header_observations: Sequence[Observation],
) -> "_PstRehydratedMessage":
    required = {
        "archive_id",
        "mailbox_id",
        "message_id",
        "message_occurrence_id",
        "message_occurrence_identity_policy",
        "duplicate_ordinal",
        "thread_id",
        "subject",
        "normalized_subject",
        "sender",
        "date_state",
        "chronology",
        "body_hash",
        "source_body_char_count",
        "stored_body_char_count",
        "body_segment_count",
        "body_evidence_state",
        "body_projection_policy",
        "body_projection_state",
        "body_projection_fingerprint",
        "header_projection_policy",
        "header_projection_count",
        "header_projection_fingerprint",
        "body_failure_codes",
        "body_redacted_segment_count",
        "unresolved_attachment_count",
        "reply_headers",
        "reply_resolutions",
        "reply_resolution_policy",
        "reply_resolution_fingerprint",
        "message_fingerprint",
        "fingerprint_policy",
    }
    optional = {
        "sent_at",
        "occurrence_lineage",
        "message_source_local_key",
        "message_source_inventory_item_id",
        "parent_message_occurrence_id",
        "parent_attachment_id",
        "embedded_attachment_ordinal",
    }
    _pst_require_exact_keys(payload, required, "PST message payload", optional=optional)
    _pst_message_observation_binding(
        observation,
        payload,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
    )
    if (
        type(payload["fingerprint_policy"]) is not str
        or payload["fingerprint_policy"] != _PST_MESSAGE_FINGERPRINT_POLICY
    ):
        raise ContractValidationError("PST message fingerprint policy is invalid")
    if (
        type(payload["reply_resolution_policy"]) is not str
        or payload["reply_resolution_policy"] != _PST_REPLY_RESOLUTION_POLICY
    ):
        raise ContractValidationError("PST reply resolution policy is invalid")
    body_segments = _pst_rehydrate_body_segments(
        body_observations,
        parent_observation=observation,
        parent_payload=payload,
    )
    location = observation.location
    if location.get("archive_id") != archive_id or location.get("mailbox_id") != mailbox_id:
        raise ContractValidationError("PST message location is invalid")
    folder_path_hash = location.get("folder_path_hash")
    if not isinstance(folder_path_hash, str) or folder_path_hash not in folder_paths:
        raise ContractValidationError("PST message folder binding is invalid")
    if (
        location.get("message_id") != payload["message_id"]
        or location.get("thread_id") != payload["thread_id"]
        or observation.text != payload["subject"]
    ):
        raise ContractValidationError("PST message identity binding is invalid")
    if type(payload["subject"]) is not str or type(payload["normalized_subject"]) is not str:
        raise ContractValidationError("PST message subject summary is invalid")
    if payload["message_occurrence_identity_policy"] != _PST_MESSAGE_OCCURRENCE_IDENTITY_POLICY:
        raise ContractValidationError("PST message identity policy is invalid")
    if not isinstance(payload["reply_headers"], list) or not isinstance(
        payload["reply_resolutions"], list
    ):
        raise ContractValidationError("PST message reply payload is invalid")
    if not isinstance(payload["chronology"], Mapping):
        raise ContractValidationError("PST message chronology is invalid")
    chronology = _pst_rehydrate_chronology(payload["chronology"])
    if payload["date_state"] != chronology.date_state:
        raise ContractValidationError("PST message date state is not bound to chronology")
    if payload.get("sent_at") != chronology.authored_sent_at:
        raise ContractValidationError("PST authored time is not bound to chronology")
    reply_headers = tuple(_pst_rehydrate_reply_header(item) for item in payload["reply_headers"])
    resolutions = tuple(
        _pst_rehydrate_reply_resolution(item) for item in payload["reply_resolutions"]
    )
    _pst_validate_reply_records(
        reply_headers,
        resolutions,
        source_message_id_fingerprint=_pst_source_message_id_fingerprint(reply_headers),
        resolver_scope=(archive_id, mailbox_id),
    )
    headers, header_projection_count, header_projection_fingerprint = _pst_rehydrate_headers(
        header_observations,
        parent_observation=observation,
        parent_payload=payload,
        chronology=chronology,
        reply_headers=reply_headers,
        reply_resolutions=resolutions,
    )
    if payload["header_projection_count"] != header_projection_count:
        raise ContractValidationError("PST header projection count is invalid")
    if payload["header_projection_fingerprint"] != header_projection_fingerprint:
        raise ContractValidationError("PST header projection fingerprint is invalid")
    occurrence_id = str(payload["message_occurrence_id"])
    occurrence_lineage = tuple(payload.get("occurrence_lineage", [occurrence_id]))
    if not occurrence_lineage or occurrence_lineage[-1] != occurrence_id:
        raise ContractValidationError("PST message occurrence lineage is invalid")
    embedded_attachment_ordinal = payload.get("embedded_attachment_ordinal")
    if "parent_message_occurrence_id" in payload:
        parent_occurrence = payload["parent_message_occurrence_id"]
        parent_attachment_id = payload.get("parent_attachment_id")
        if not isinstance(parent_occurrence, str) or not isinstance(parent_attachment_id, str):
            raise ContractValidationError("PST embedded message relation is invalid")
        embedded_attachment_ordinal = _pst_exact_int(
            embedded_attachment_ordinal,
            "embedded attachment ordinal",
            minimum=1,
        )
    elif any(key in payload for key in ("parent_attachment_id", "embedded_attachment_ordinal")):
        raise ContractValidationError("PST message relation is incomplete")
    else:
        parent_occurrence = None
        parent_attachment_id = None
        embedded_attachment_ordinal = None
    attachment_hashes: list[str] = []
    parsed_attachments: list[_ParsedAttachment] = []
    for attachment in sorted(
        attachments,
        key=lambda item: _pst_exact_int(
            item.location.get("attachment_index"),
            "attachment location index",
            minimum=1,
        ),
    ):
        attachment_payload = _pst_observation_payload(attachment)
        content_hash = attachment_payload.get("content_hash")
        if isinstance(content_hash, str):
            attachment_hashes.append(content_hash)
        parsed_attachments.append(
            _ParsedAttachment(
                attachment_id=str(attachment_payload["attachment_id"]),
                filename=str(attachment_payload["filename"]),
                mime_type=attachment_payload.get("mime_type"),
                content_hash=content_hash,
                size_bytes=attachment_payload.get("size_bytes"),
                text_extraction_state=str(
                    attachment_payload.get("text_extraction_state", "not_text")
                ),
                processing_state=str(
                    attachment_payload.get("attachment_processing_state", "parsed")
                ),
                failure_code=attachment_payload.get("attachment_failure_code"),
                source_local_key=attachment_payload.get("attachment_source_local_key"),
                source_kind=str(attachment_payload.get("attachment_source", "mime")),
                source_name_fingerprint=attachment_payload.get(
                    "attachment_source_name_fingerprint"
                ),
                source_char_count=attachment_payload.get("attachment_source_char_count"),
                stored_char_count=_pst_exact_int(
                    attachment_payload.get("attachment_stored_char_count", 0),
                    "attachment stored character count",
                ),
            )
        )
    unresolved_attachment_count = payload["unresolved_attachment_count"]
    unresolved_attachment_count = _pst_exact_int(
        unresolved_attachment_count,
        "unresolved attachment count",
    )
    canonical_unresolved_attachment_count = sum(
        _attachment_is_unresolved(attachment) for attachment in parsed_attachments
    )
    if unresolved_attachment_count != canonical_unresolved_attachment_count:
        raise ContractValidationError("PST unresolved attachment count is not canonical")
    synthetic = _ParsedMessage(
        folder_path_hash=str(folder_path_hash),
        folder_label=folder_paths[str(folder_path_hash)],
        message_id=str(payload["message_id"]),
        subject=str(payload["subject"]),
        normalized_subject=str(payload["normalized_subject"]),
        sender=str(payload["sender"]),
        sent_at=payload.get("sent_at"),
        headers=headers,
        chronology=chronology,
        body_segments=body_segments,
        body_hash=str(payload["body_hash"]),
        source_body_char_count=payload["source_body_char_count"],
        stored_body_char_count=_pst_exact_int(
            payload["stored_body_char_count"],
            "stored body character count",
        ),
        body_evidence_state=str(payload["body_evidence_state"]),
        body_projection_state=str(payload["body_projection_state"]),
        body_projection_fingerprint=str(payload["body_projection_fingerprint"]),
        header_projection_count=header_projection_count,
        header_projection_fingerprint=header_projection_fingerprint,
        body_failure_codes=tuple(payload["body_failure_codes"]),
        body_redacted_segment_count=_pst_exact_int(
            payload["body_redacted_segment_count"],
            "body redacted segment count",
        ),
        unresolved_attachment_count=canonical_unresolved_attachment_count,
        attachments=parsed_attachments,
        reply_headers=reply_headers,
        embedded_attachment_ordinal=embedded_attachment_ordinal,
        source_local_key=payload.get("message_source_local_key"),
    )
    message_fingerprint = _message_fingerprint(synthetic)
    if payload["message_fingerprint"] != message_fingerprint:
        raise ContractValidationError("PST message fingerprint is invalid")
    for body_observation in body_observations:
        body_payload = _pst_observation_payload(body_observation)
        if body_payload.get("message_fingerprint") != message_fingerprint:
            raise ContractValidationError("PST body message fingerprint is invalid")
    context = _MailMessageContext(
        message=synthetic,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
        message_fingerprint=message_fingerprint,
        occurrence_id=occurrence_id,
        occurrence_lineage=occurrence_lineage,
        duplicate_ordinal=_pst_exact_int(
            payload["duplicate_ordinal"],
            "duplicate ordinal",
            minimum=1,
        ),
        parent_occurrence_id=parent_occurrence,
        parent_attachment_id=parent_attachment_id,
    )
    return _PstRehydratedMessage(message_occurrence_id=occurrence_id, context=context)


@dataclass(frozen=True)
class _PstRehydratedMessage:
    message_occurrence_id: str
    context: _MailMessageContext


def _pst_rehydrate_chronology(payload: Mapping[str, Any]) -> _MessageChronology:
    _pst_require_exact_keys(
        payload,
        {
            "date_state",
            "occurrences",
            "date_occurrences",
            "received_occurrences",
            "parser_defect",
        },
        "PST chronology payload",
        optional={"authored_sent_at"},
    )
    if not all(
        isinstance(payload[key], list)
        for key in ("occurrences", "date_occurrences", "received_occurrences")
    ):
        raise ContractValidationError("PST chronology occurrences are invalid")
    parser_defect = _pst_exact_bool(
        payload["parser_defect"],
        "chronology parser defect",
    )
    occurrences = tuple(
        _pst_rehydrate_chronology_occurrence(item) for item in payload["occurrences"]
    )
    dates = tuple(
        _pst_rehydrate_chronology_occurrence(item) for item in payload["date_occurrences"]
    )
    received = tuple(
        _pst_rehydrate_chronology_occurrence(item) for item in payload["received_occurrences"]
    )
    if tuple(occurrences) != tuple(sorted(occurrences, key=lambda item: item.physical_ordinal)):
        raise ContractValidationError("PST chronology order is invalid")
    if tuple(item for item in occurrences if item.kind == "date") != dates:
        raise ContractValidationError("PST chronology date projection is invalid")
    if tuple(item for item in occurrences if item.kind == "received") != received:
        raise ContractValidationError("PST chronology received projection is invalid")
    date_state, authored_sent_at = _derive_chronology_date_summary(
        dates,
        parser_defect=parser_defect,
    )
    if payload["date_state"] != date_state:
        raise ContractValidationError("PST chronology date state is not canonical")
    if payload.get("authored_sent_at") != authored_sent_at:
        raise ContractValidationError("PST chronology authored time is not canonical")
    return _MessageChronology(
        date_state=date_state,
        occurrences=occurrences,
        date_occurrences=dates,
        received_occurrences=received,
        authored_sent_at=authored_sent_at,
        parser_defect=parser_defect,
    )


def _pst_rehydrate_chronology_occurrence(payload: Mapping[str, Any]) -> _ChronologyOccurrence:
    _pst_require_exact_keys(
        payload,
        {
            "kind",
            "header_ordinal",
            "physical_ordinal",
            "kind_ordinal",
            "raw_value_fingerprint",
            "parse_status",
            "timezone_status",
        },
        "PST chronology occurrence",
        optional={"normalized_instant", "safe_error_code"},
    )
    return _ChronologyOccurrence(
        kind=str(payload["kind"]),
        header_ordinal=_pst_exact_int(
            payload["header_ordinal"],
            "chronology header ordinal",
            minimum=1,
        ),
        physical_ordinal=_pst_exact_int(
            payload["physical_ordinal"],
            "chronology physical ordinal",
            minimum=1,
        ),
        kind_ordinal=_pst_exact_int(
            payload["kind_ordinal"],
            "chronology kind ordinal",
            minimum=1,
        ),
        raw_value_fingerprint=str(payload["raw_value_fingerprint"]),
        parse_status=str(payload["parse_status"]),
        timezone_status=str(payload["timezone_status"]),
        normalized_instant=payload.get("normalized_instant"),
        safe_error_code=payload.get("safe_error_code"),
    )


def _pst_rehydrate_reply_header(payload: Mapping[str, Any]) -> _ReplyHeaderOccurrence:
    _pst_require_exact_keys(
        payload,
        {
            "kind",
            "header_ordinal",
            "occurrence_ordinal",
            "raw_value_fingerprint",
            "parse_status",
            "identifier_fingerprints",
            "identifier_count",
        },
        "PST reply header",
        optional={"safe_error_code"},
    )
    fingerprints = payload["identifier_fingerprints"]
    identifier_count = _pst_exact_int(
        payload["identifier_count"],
        "reply header identifier count",
    )
    if not isinstance(fingerprints, list) or identifier_count != len(fingerprints):
        raise ContractValidationError("PST reply header identifiers are invalid")
    return _ReplyHeaderOccurrence(
        kind=str(payload["kind"]),
        header_ordinal=_pst_exact_int(
            payload["header_ordinal"],
            "reply header ordinal",
            minimum=1,
        ),
        occurrence_ordinal=_pst_exact_int(
            payload["occurrence_ordinal"],
            "reply occurrence ordinal",
            minimum=1,
        ),
        raw_value_fingerprint=str(payload["raw_value_fingerprint"]),
        parse_status=str(payload["parse_status"]),
        token_fingerprints=tuple(str(value) for value in fingerprints),
        safe_error_code=payload.get("safe_error_code"),
    )


def _pst_rehydrate_reply_resolution(payload: Mapping[str, Any]) -> _ReplyResolution:
    _pst_require_exact_keys(
        payload,
        {
            "header_kind",
            "parse_state",
            "parse_complete",
            "resolution_state",
            "reason_code",
            "resolver_scope",
            "target_occurrence_ids",
        },
        "PST reply resolution",
        optional={
            "header_ordinal",
            "occurrence_ordinal",
            "identifier_ordinal",
            "identifier_fingerprint",
            "raw_value_fingerprint",
            "parse_reason_code",
            "resolution_reason_code",
            "blocking_header_kind",
            "blocking_header_ordinal",
            "blocking_reason_code",
            "source_message_id_fingerprint",
            "target_logical_message_key",
        },
    )
    scope = payload["resolver_scope"]
    if not isinstance(scope, Mapping):
        raise ContractValidationError("PST reply resolution scope is invalid")
    _pst_require_exact_keys(scope, {"archive_id", "mailbox_id"}, "PST reply resolution scope")
    target_occurrences = payload["target_occurrence_ids"]
    if not isinstance(target_occurrences, list):
        raise ContractValidationError("PST reply resolution targets are invalid")
    for field_name, minimum in (
        ("header_ordinal", 1),
        ("occurrence_ordinal", 1),
        ("identifier_ordinal", 1),
        ("blocking_header_ordinal", 1),
    ):
        if payload.get(field_name) is not None:
            _pst_exact_int(
                payload[field_name],
                f"reply resolution {field_name}",
                minimum=minimum,
            )
    parse_complete = _pst_exact_bool(
        payload["parse_complete"],
        "reply resolution parse completeness",
    )
    return _ReplyResolution(
        header_kind=str(payload["header_kind"]),
        header_ordinal=payload.get("header_ordinal"),
        occurrence_ordinal=payload.get("occurrence_ordinal"),
        identifier_ordinal=payload.get("identifier_ordinal"),
        identifier_fingerprint=payload.get("identifier_fingerprint"),
        raw_value_fingerprint=payload.get("raw_value_fingerprint"),
        parse_state=str(payload["parse_state"]),
        parse_complete=parse_complete,
        resolution_state=str(payload["resolution_state"]),
        reason_code=str(payload["reason_code"]),
        resolver_scope=(str(scope["archive_id"]), str(scope["mailbox_id"])),
        parse_reason_code=payload.get("parse_reason_code"),
        resolution_reason_code=payload.get("resolution_reason_code"),
        blocking_header_kind=payload.get("blocking_header_kind"),
        blocking_header_ordinal=payload.get("blocking_header_ordinal"),
        blocking_reason_code=payload.get("blocking_reason_code"),
        source_message_id_fingerprint=payload.get("source_message_id_fingerprint"),
        target_logical_message_key=payload.get("target_logical_message_key"),
        target_occurrence_ids=tuple(str(value) for value in target_occurrences),
    )


def _pst_rehydrate_headers(
    observations: Sequence[Observation],
    *,
    parent_observation: Observation,
    parent_payload: Mapping[str, Any],
    chronology: _MessageChronology,
    reply_headers: Sequence[_ReplyHeaderOccurrence],
    reply_resolutions: Sequence[_ReplyResolution],
) -> tuple[tuple[_SafeHeaderOccurrence, ...], int, str]:
    """Rebuild the ordered, typed header projection from persisted observations."""

    projection_count = _pst_exact_int(
        parent_payload.get("header_projection_count"),
        "header projection count",
    )
    if parent_payload.get("header_projection_policy") != _PST_HEADER_PROJECTION_POLICY:
        raise ContractValidationError("PST header projection policy is invalid")
    occurrence_id = parent_payload.get("message_occurrence_id")
    if not isinstance(occurrence_id, str) or not occurrence_id:
        raise ContractValidationError("PST header message occurrence is invalid")
    expected_lineage = parent_payload.get("occurrence_lineage")
    expected_message_fingerprint = parent_payload.get("message_fingerprint")
    if not isinstance(expected_message_fingerprint, str) or not expected_message_fingerprint:
        raise ContractValidationError("PST header message fingerprint is invalid")

    reply_by_key = {
        (header.kind, header.header_ordinal, header.occurrence_ordinal): header
        for header in reply_headers
    }
    chronology_by_ordinal = {
        occurrence.header_ordinal: occurrence for occurrence in chronology.occurrences
    }
    reply_resolution_kind = {
        "message-id": "message_id",
        "references": "references",
        "in-reply-to": "in_reply_to",
    }
    projection: list[tuple[int, _SafeHeaderOccurrence]] = []
    seen_projection_indices: set[int] = set()
    seen_header_ordinals: set[int] = set()
    for observation in observations:
        payload = _pst_observation_payload(observation)
        _pst_require_exact_keys(
            observation.location,
            {
                "archive_id",
                "mailbox_id",
                "folder_path_hash",
                "message_id",
                "message_occurrence_id",
                "thread_id",
                "header_index",
                "header_name",
                "header_projection_policy",
                "header_projection_count",
                "header_projection_index",
                "header_projection_fingerprint",
            },
            "PST header location",
            optional={
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
                "chronology_physical_ordinal",
            },
        )
        _pst_require_exact_keys(
            payload,
            {
                "archive_id",
                "mailbox_id",
                "message_id",
                "message_occurrence_id",
                "message_occurrence_identity_policy",
                "duplicate_ordinal",
                "thread_id",
                "header_name",
                "header_ordinal",
                "header_projection_policy",
                "header_projection_count",
                "header_projection_index",
                "header_projection_fingerprint",
                "header_variant",
                "raw_value_fingerprint",
                "message_fingerprint",
            },
            "PST header payload",
            optional={
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
                "header_value",
                "chronology",
                "reply",
                "reply_resolution_fingerprint",
            },
        )
        bound_occurrence = _pst_message_observation_binding(
            observation,
            payload,
            archive_id=str(parent_payload["archive_id"]),
            mailbox_id=str(parent_payload["mailbox_id"]),
        )
        if bound_occurrence != occurrence_id:
            raise ContractValidationError("PST header occurrence binding is invalid")
        for value, field_name in (
            (payload["header_projection_count"], "header projection count"),
            (payload["header_projection_index"], "header projection index"),
            (payload["header_ordinal"], "header ordinal"),
            (observation.location["header_projection_count"], "header location count"),
            (observation.location["header_projection_index"], "header location index"),
            (observation.location["header_index"], "header location ordinal"),
        ):
            _pst_exact_int(value, field_name, minimum=1)
        projection_index = payload["header_projection_index"]
        header_ordinal = payload["header_ordinal"]
        if projection_index in seen_projection_indices or header_ordinal in seen_header_ordinals:
            raise ContractValidationError("PST header occurrence is duplicated")
        seen_projection_indices.add(projection_index)
        seen_header_ordinals.add(header_ordinal)
        if (
            payload["archive_id"] != parent_payload["archive_id"]
            or payload["mailbox_id"] != parent_payload["mailbox_id"]
            or payload["message_id"] != parent_payload["message_id"]
            or payload["thread_id"] != parent_payload["thread_id"]
            or payload["duplicate_ordinal"] != parent_payload["duplicate_ordinal"]
            or payload["message_occurrence_identity_policy"]
            != parent_payload["message_occurrence_identity_policy"]
            or payload["header_projection_policy"] != _PST_HEADER_PROJECTION_POLICY
            or payload["header_projection_count"] != projection_count
            or payload["header_projection_fingerprint"]
            != parent_payload["header_projection_fingerprint"]
            or payload["message_fingerprint"] != expected_message_fingerprint
            or observation.location["folder_path_hash"]
            != parent_observation.location["folder_path_hash"]
            or observation.location["message_id"] != parent_payload["message_id"]
            or observation.location["thread_id"] != parent_payload["thread_id"]
        ):
            raise ContractValidationError("PST header parent mirror is invalid")
        if (
            observation.location["header_index"] != header_ordinal
            or observation.location["header_name"] != payload["header_name"]
            or observation.location["header_projection_count"] != projection_count
            or observation.location["header_projection_index"] != projection_index
            or observation.location["header_projection_policy"] != _PST_HEADER_PROJECTION_POLICY
            or observation.location["header_projection_fingerprint"]
            != parent_payload["header_projection_fingerprint"]
        ):
            raise ContractValidationError("PST header location projection is invalid")
        if payload.get("occurrence_lineage") != expected_lineage:
            raise ContractValidationError("PST header lineage mirror is invalid")
        if observation.location.get("occurrence_lineage") != parent_observation.location.get(
            "occurrence_lineage"
        ):
            raise ContractValidationError("PST header location lineage mirror is invalid")
        for field_name in (
            "parent_message_occurrence_id",
            "parent_attachment_id",
            "embedded_attachment_ordinal",
        ):
            if payload.get(field_name) != parent_payload.get(field_name):
                raise ContractValidationError("PST header embedded relation is invalid")
            if observation.location.get(field_name) != parent_observation.location.get(field_name):
                raise ContractValidationError("PST header location relation is invalid")
        if observation.location.get("chronology_physical_ordinal") is not None:
            _pst_exact_int(
                observation.location["chronology_physical_ordinal"],
                "header chronology location ordinal",
                minimum=1,
            )

        header_name = payload["header_name"]
        if not isinstance(header_name, str) or header_name != header_name.casefold():
            raise ContractValidationError("PST header name is invalid")
        variant = payload["header_variant"]
        variant_keys = {
            "ordinary": {"header_value"},
            "chronology": {"chronology"},
            "reply": {"reply", "reply_resolution_fingerprint"},
        }
        if variant not in variant_keys:
            raise ContractValidationError("PST header variant is invalid")
        present_variant_keys = {
            key for key in ("header_value", "chronology", "reply") if key in payload
        }
        if present_variant_keys != variant_keys[variant] - {"reply_resolution_fingerprint"}:
            raise ContractValidationError("PST header variant shape is invalid")
        if variant != "reply" and "reply_resolution_fingerprint" in payload:
            raise ContractValidationError("PST header variant shape is invalid")
        if variant == "reply" and (
            not isinstance(payload.get("reply_resolution_fingerprint"), str)
            or not payload["reply_resolution_fingerprint"]
        ):
            raise ContractValidationError("PST reply resolution fingerprint is invalid")
        raw_value_fingerprint = payload["raw_value_fingerprint"]
        if not isinstance(raw_value_fingerprint, str) or not raw_value_fingerprint:
            raise ContractValidationError("PST header raw fingerprint is invalid")

        if variant == "ordinary":
            header_value = payload["header_value"]
            if header_value is not None and not isinstance(header_value, str):
                raise ContractValidationError("PST ordinary header value is invalid")
            if observation.text != f"{header_name}: {header_value or ''}":
                raise ContractValidationError("PST ordinary header text is invalid")
            if header_name in {"date", "received", "message-id", "references", "in-reply-to"}:
                raise ContractValidationError("PST ordinary header projection is invalid")
            safe_header = _SafeHeaderOccurrence(
                header_name=header_name,
                header_ordinal=header_ordinal,
                header_value=header_value,
                raw_value_fingerprint=raw_value_fingerprint,
            )
        elif variant == "chronology":
            chronology_payload = payload["chronology"]
            if not isinstance(chronology_payload, Mapping):
                raise ContractValidationError("PST chronology header is invalid")
            for field_name in ("header_ordinal", "physical_ordinal", "kind_ordinal"):
                _pst_exact_int(
                    chronology_payload.get(field_name),
                    f"chronology header {field_name}",
                    minimum=1,
                )
            parsed_occurrence = _pst_rehydrate_chronology_occurrence(chronology_payload)
            expected_occurrence = chronology_by_ordinal.get(header_ordinal)
            if expected_occurrence is None or parsed_occurrence != expected_occurrence:
                raise ContractValidationError("PST chronology header binding is invalid")
            if (
                header_name != parsed_occurrence.kind
                or raw_value_fingerprint != parsed_occurrence.raw_value_fingerprint
                or observation.location.get("chronology_physical_ordinal")
                != parsed_occurrence.physical_ordinal
                or observation.text
                != f"{header_name}: "
                f"[{parsed_occurrence.parse_status}/{parsed_occurrence.timezone_status}]"
            ):
                raise ContractValidationError("PST chronology header projection is invalid")
            safe_header = _SafeHeaderOccurrence(
                header_name=header_name,
                header_ordinal=header_ordinal,
                raw_value_fingerprint=raw_value_fingerprint,
                chronology=parsed_occurrence,
            )
        else:
            reply_payload = payload["reply"]
            if not isinstance(reply_payload, Mapping):
                raise ContractValidationError("PST reply header is invalid")
            for field_name in ("header_ordinal", "occurrence_ordinal"):
                _pst_exact_int(
                    reply_payload.get(field_name),
                    f"reply header {field_name}",
                    minimum=1,
                )
            _pst_exact_int(
                reply_payload.get("identifier_count"),
                "reply header identifier count",
            )
            parsed_reply = _pst_rehydrate_reply_header(reply_payload)
            expected_reply = reply_by_key.get(
                (parsed_reply.kind, header_ordinal, parsed_reply.occurrence_ordinal)
            )
            if expected_reply is None or parsed_reply != expected_reply:
                raise ContractValidationError("PST reply header binding is invalid")
            if (
                header_name
                != next(
                    name
                    for name, kind in reply_resolution_kind.items()
                    if kind == parsed_reply.kind
                )
                or raw_value_fingerprint != parsed_reply.raw_value_fingerprint
                or observation.location.get("chronology_physical_ordinal") is not None
                or observation.text
                != f"{header_name}: " f"[{parsed_reply.parse_status}/{parsed_reply.token_count}]"
            ):
                raise ContractValidationError("PST reply header projection is invalid")
            matching_resolutions = [
                resolution.to_payload()
                for resolution in reply_resolutions
                if resolution.header_kind == parsed_reply.kind
                and resolution.header_ordinal == header_ordinal
                and resolution.occurrence_ordinal == parsed_reply.occurrence_ordinal
            ]
            if payload["reply_resolution_fingerprint"] != _reply_resolution_fingerprint(
                matching_resolutions
            ):
                raise ContractValidationError("PST reply header resolution binding is invalid")
            safe_header = _SafeHeaderOccurrence(
                header_name=header_name,
                header_ordinal=header_ordinal,
                raw_value_fingerprint=raw_value_fingerprint,
                reply=parsed_reply,
            )
        projection.append((projection_index, safe_header))

    if len(projection) != projection_count or set(seen_projection_indices) != set(
        range(1, projection_count + 1)
    ):
        raise ContractValidationError("PST header projection index set is invalid")
    headers = tuple(header for _, header in sorted(projection, key=lambda item: item[0]))
    subject_headers = [header for header in headers if header.header_name == "subject"]
    if not subject_headers:
        canonical_subject = ""
    else:
        canonical_subject = subject_headers[0].header_value
        if type(canonical_subject) is not str:
            raise ContractValidationError("PST subject header value is unavailable")
    if parent_payload.get("subject") != canonical_subject or parent_payload.get(
        "normalized_subject"
    ) != _normalize_subject(canonical_subject):
        raise ContractValidationError("PST header subject summary is invalid")
    sender_headers = [
        header
        for header in headers
        if header.header_name == "from" and header.header_value is not None
    ]
    if sender_headers and sender_headers[0].header_value != parent_payload.get("sender"):
        raise ContractValidationError("PST header sender summary is invalid")
    computed_fingerprint = _header_projection_fingerprint(headers)
    return headers, projection_count, computed_fingerprint


def _pst_source_message_id_fingerprint(
    reply_headers: Sequence[_ReplyHeaderOccurrence],
) -> str | None:
    source = tuple(item for item in reply_headers if item.kind == "message_id")
    if (
        len(source) != 1
        or source[0].parse_status != "parsed"
        or len(source[0].token_fingerprints) != 1
    ):
        return None
    return source[0].token_fingerprints[0]


def _pst_validate_reply_records(
    headers: Sequence[_ReplyHeaderOccurrence],
    resolutions: Sequence[_ReplyResolution],
    *,
    source_message_id_fingerprint: str | None,
    resolver_scope: tuple[str, str],
) -> None:
    if not resolutions:
        raise ContractValidationError("PST reply resolutions are required")
    if any(record.resolver_scope != resolver_scope for record in resolutions):
        raise ContractValidationError("PST reply resolution scope is invalid")
    if any(
        record.source_message_id_fingerprint != source_message_id_fingerprint
        for record in resolutions
    ):
        raise ContractValidationError("PST reply source binding is invalid")
    header_map = {
        (header.kind, header.header_ordinal, header.occurrence_ordinal): header
        for header in headers
    }
    expected: list[tuple[str, int | None, int | None, int | None, str | None, str | None]] = []
    source_headers = [header for header in headers if header.kind == "message_id"]
    if not source_headers:
        expected.append(("message_id", None, None, None, None, None))
    else:
        for header in source_headers:
            for ordinal, fingerprint in enumerate(header.token_fingerprints, start=1):
                expected.append(
                    (
                        "message_id",
                        header.header_ordinal,
                        header.occurrence_ordinal,
                        ordinal,
                        fingerprint,
                        header.raw_value_fingerprint,
                    )
                )
            if not header.token_fingerprints:
                expected.append(
                    (
                        "message_id",
                        header.header_ordinal,
                        header.occurrence_ordinal,
                        None,
                        None,
                        header.raw_value_fingerprint,
                    )
                )
    ancestry_headers = [
        header for header in headers if header.kind in {"references", "in_reply_to"}
    ]
    if not ancestry_headers:
        expected.append(("ancestry", None, None, None, None, None))
    else:
        for header in ancestry_headers:
            if header.token_fingerprints:
                expected.extend(
                    (
                        header.kind,
                        header.header_ordinal,
                        header.occurrence_ordinal,
                        ordinal,
                        fingerprint,
                        header.raw_value_fingerprint,
                    )
                    for ordinal, fingerprint in enumerate(header.token_fingerprints, start=1)
                )
            else:
                expected.append(
                    (
                        header.kind,
                        header.header_ordinal,
                        header.occurrence_ordinal,
                        None,
                        None,
                        header.raw_value_fingerprint,
                    )
                )
    actual = [
        (
            record.header_kind,
            record.header_ordinal,
            record.occurrence_ordinal,
            record.identifier_ordinal,
            record.identifier_fingerprint,
            record.raw_value_fingerprint,
        )
        for record in resolutions
    ]
    if actual != expected:
        raise ContractValidationError("PST reply resolution occurrence binding is invalid")
    for record in resolutions:
        if record.header_kind in {"references", "in_reply_to"}:
            header = header_map.get(
                (record.header_kind, record.header_ordinal, record.occurrence_ordinal)
            )
            if header is None:
                raise ContractValidationError("PST reply resolution header is orphaned")
            if record.parse_state != header.parse_status:
                raise ContractValidationError("PST reply parse state is not canonical")
            if record.parse_complete != (header.parse_status == "parsed"):
                raise ContractValidationError("PST reply parse completeness is invalid")


def _validate_pst_child_lineage(contexts: Sequence[_MailMessageContext]) -> None:
    context_by_occurrence: dict[str, _MailMessageContext] = {}
    for context in contexts:
        context_by_occurrence.setdefault(context.occurrence_id, context)
    occurrence_ids = set(context_by_occurrence)
    for context in contexts:
        if context.parent_occurrence_id is None:
            if len(context.occurrence_lineage) != 1:
                raise ContractValidationError("PST top-level occurrence lineage is invalid")
            continue
        if context.parent_occurrence_id not in occurrence_ids:
            raise ContractValidationError("PST child occurrence parent is missing")
        parent = context_by_occurrence[context.parent_occurrence_id]
        if context.occurrence_lineage != (*parent.occurrence_lineage, context.occurrence_id):
            raise ContractValidationError("PST child occurrence lineage is invalid")
        if (
            context.parent_attachment_id is None
            or context.message.embedded_attachment_ordinal is None
        ):
            raise ContractValidationError("PST child attachment relation is incomplete")
        attachment_index = context.message.embedded_attachment_ordinal
        if (
            attachment_index > len(parent.message.attachments)
            or parent.message.attachments[attachment_index - 1].attachment_id
            != context.parent_attachment_id
        ):
            raise ContractValidationError("PST child attachment parent is invalid")


def _validate_pst_partial_inventory_state(
    inventory: SourceInventory,
    *,
    structural_observations: Sequence[StructuralObservation],
    expected_traversal_binding: PstTraversalBinding | None,
) -> None:
    """Accept only the extraction-issued child-preserving partial state."""

    del structural_observations
    if expected_traversal_binding is None:
        raise ContractValidationError("PST trusted traversal binding is required")
    _pst_assert_issued_traversal_binding(expected_traversal_binding)
    if expected_traversal_binding.partial_inventory_state is not True:
        raise ContractValidationError("PST partial inventory state is not trusted")
    if expected_traversal_binding.embedded_message_bindings != ():
        raise ContractValidationError("PST partial inventory message bindings are invalid")

    if not _pst_has_retained_partial_children(inventory):
        raise ContractValidationError("PST partial inventory message preservation is invalid")


def _pst_has_retained_partial_children(inventory: SourceInventory) -> bool:
    archive_items = [item for item in inventory.items if item.structure_kind == "archive"]
    message_items = [
        item
        for item in inventory.items
        if item.structure_kind in {"exported_message_occurrence", "attached_message_occurrence"}
    ]
    return (
        len(archive_items) == 1
        and type(archive_items[0].processing_state) is str
        and archive_items[0].processing_state == "failed"
        and bool(message_items)
        and any(item.processing_state == "parsed" for item in message_items)
    )


def _pst_require_thread_payload(payload: Mapping[str, Any]) -> None:
    _pst_require_exact_keys(
        payload,
        {
            "archive_id",
            "mailbox_id",
            "thread_id",
            "normalized_subject",
            "message_ids",
            "logical_message_keys",
            "occurrence_membership",
            "resolved_reply_edges",
            "unresolved_reply_states",
            "reply_resolutions",
            "reply_resolution_fingerprint",
            "reply_ancestry_state",
            "thread_identity_policy",
            "reply_resolution_policy",
            "version_lineage",
            "participants",
            "chronology",
            "message_count",
        },
        "PST thread payload",
        optional={
            "thread_root_id",
            "first_sent_at",
            "last_sent_at",
            "chronology_completeness",
            "subject_grouping",
        },
    )


def _pst_validate_thread_boolean_mirrors(payload: Mapping[str, Any]) -> None:
    """Validate persisted boolean mirrors before canonical thread comparison."""

    chronology = payload.get("chronology")
    if not isinstance(chronology, list):
        raise ContractValidationError("PST thread chronology is invalid")
    for occurrence in chronology:
        if not isinstance(occurrence, Mapping) or "parser_defect" not in occurrence:
            raise ContractValidationError("PST thread chronology mirror is invalid")
        _pst_exact_bool(
            occurrence["parser_defect"],
            "thread chronology parser defect",
        )

    def validate_resolution_groups(
        groups: Any,
        field_name: str,
    ) -> None:
        if not isinstance(groups, list):
            raise ContractValidationError(f"PST thread {field_name} is invalid")
        for group in groups:
            if not isinstance(group, Mapping):
                raise ContractValidationError(f"PST thread {field_name} group is invalid")
            resolutions = group.get("resolutions")
            if not isinstance(resolutions, list):
                raise ContractValidationError(f"PST thread {field_name} resolutions are invalid")
            for resolution in resolutions:
                if not isinstance(resolution, Mapping) or "parse_complete" not in resolution:
                    raise ContractValidationError(f"PST thread {field_name} mirror is invalid")
                _pst_exact_bool(
                    resolution["parse_complete"],
                    "thread reply resolution parse completeness",
                )

    def validate_resolution_records(records: Any, field_name: str) -> None:
        if not isinstance(records, list):
            raise ContractValidationError(f"PST thread {field_name} are invalid")
        for resolution in records:
            if not isinstance(resolution, Mapping) or "parse_complete" not in resolution:
                raise ContractValidationError(f"PST thread {field_name} mirror is invalid")
            _pst_exact_bool(
                resolution["parse_complete"],
                "thread reply resolution parse completeness",
            )

    validate_resolution_groups(payload.get("reply_resolutions"), "reply resolutions")
    unresolved_states = payload.get("unresolved_reply_states")
    if not isinstance(unresolved_states, list):
        raise ContractValidationError("PST thread unresolved reply states are invalid")
    for state in unresolved_states:
        if not isinstance(state, Mapping):
            raise ContractValidationError("PST thread unresolved reply state is invalid")
        if "reply_resolutions" in state:
            validate_resolution_records(
                state["reply_resolutions"],
                "unresolved reply resolutions",
            )


def _pst_validate_thread_chronology_ordinals(payload: Mapping[str, Any]) -> None:
    chronology = payload.get("chronology")
    if not isinstance(chronology, list):
        raise ContractValidationError("PST thread chronology is invalid")
    for message_chronology in chronology:
        if not isinstance(message_chronology, Mapping):
            raise ContractValidationError("PST thread chronology entry is invalid")
        for occurrence_group in (
            "occurrences",
            "date_occurrences",
            "received_occurrences",
        ):
            occurrences = message_chronology.get(occurrence_group)
            if not isinstance(occurrences, list):
                raise ContractValidationError("PST thread chronology occurrence group is invalid")
            for occurrence in occurrences:
                if not isinstance(occurrence, Mapping):
                    raise ContractValidationError("PST thread chronology occurrence is invalid")
                for field_name in (
                    "header_ordinal",
                    "physical_ordinal",
                    "kind_ordinal",
                ):
                    _pst_exact_int(
                        occurrence.get(field_name),
                        f"thread chronology {field_name}",
                        minimum=1,
                    )


def _pst_validate_thread_reply_resolution_records(payload: Mapping[str, Any]) -> None:
    def validate_records(records: Any, field_name: str) -> None:
        if not isinstance(records, list):
            raise ContractValidationError(f"PST thread {field_name} are invalid")
        for resolution in records:
            if not isinstance(resolution, Mapping):
                raise ContractValidationError(f"PST thread {field_name} record is invalid")
            _pst_rehydrate_reply_resolution(resolution)

    groups = payload.get("reply_resolutions")
    if not isinstance(groups, list):
        raise ContractValidationError("PST thread reply resolutions are invalid")
    for group in groups:
        if not isinstance(group, Mapping):
            raise ContractValidationError("PST thread reply resolution group is invalid")
        validate_records(group.get("resolutions"), "reply resolutions")

    unresolved_states = payload.get("unresolved_reply_states")
    if not isinstance(unresolved_states, list):
        raise ContractValidationError("PST thread unresolved reply states are invalid")
    for state in unresolved_states:
        if not isinstance(state, Mapping):
            raise ContractValidationError("PST thread unresolved reply state is invalid")
        if "reply_resolutions" in state:
            validate_records(
                state["reply_resolutions"],
                "unresolved reply resolutions",
            )


def _pst_validate_thread_resolved_edges(payload: Mapping[str, Any]) -> None:
    edges = payload.get("resolved_reply_edges")
    if not isinstance(edges, list):
        raise ContractValidationError("PST thread resolved reply edges are invalid")
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise ContractValidationError("PST thread resolved reply edge is invalid")
        _pst_require_exact_keys(
            edge,
            {
                "from_occurrence_id",
                "from_logical_message_key",
                "to_logical_message_key",
                "target_occurrence_ids",
                "relation",
                "header_ordinal",
                "target_message_id_fingerprint",
            },
            "PST thread resolved reply edge",
        )
        _pst_exact_int(
            edge["header_ordinal"],
            "thread resolved reply edge header ordinal",
            minimum=1,
        )
        for field_name in (
            "from_occurrence_id",
            "from_logical_message_key",
            "to_logical_message_key",
            "relation",
            "target_message_id_fingerprint",
        ):
            if type(edge[field_name]) is not str or not edge[field_name]:
                raise ContractValidationError(
                    "PST thread resolved reply edge string field is invalid"
                )
        target_occurrence_ids = edge["target_occurrence_ids"]
        if (
            not isinstance(target_occurrence_ids, list)
            or not target_occurrence_ids
            or any(type(value) is not str or not value for value in target_occurrence_ids)
        ):
            raise ContractValidationError("PST thread resolved reply edge targets are invalid")


def _pst_validate_thread_unresolved_reply_headers(payload: Mapping[str, Any]) -> None:
    unresolved_states = payload.get("unresolved_reply_states")
    if not isinstance(unresolved_states, list):
        raise ContractValidationError("PST thread unresolved reply states are invalid")
    for state in unresolved_states:
        if not isinstance(state, Mapping):
            raise ContractValidationError("PST thread unresolved reply state is invalid")
        reply_headers = state.get("reply_headers")
        if not isinstance(reply_headers, list):
            raise ContractValidationError("PST thread unresolved reply headers are invalid")
        for header in reply_headers:
            if not isinstance(header, Mapping):
                raise ContractValidationError("PST thread unresolved reply header is invalid")
            _pst_rehydrate_reply_header(header)


def _validate_pst_projection_observations(
    body_observations: Sequence[Observation],
    header_observations: Sequence[Observation],
    attachment_observations: Sequence[Observation],
    attachment_text_observations: Sequence[Observation],
    *,
    context_by_occurrence: Mapping[str, _MailMessageContext],
    expected_thread_ids: Mapping[str, str],
    archive_id: str,
    mailbox_id: str,
) -> None:
    for observation in (
        *body_observations,
        *header_observations,
        *attachment_observations,
        *attachment_text_observations,
    ):
        payload = _pst_observation_payload(observation)
        occurrence_id = _pst_message_observation_binding(
            observation,
            payload,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
        )
        context = context_by_occurrence.get(occurrence_id)
        if context is None:
            raise ContractValidationError("PST projection observation has an orphan message")
        if payload.get("message_id") != context.message.message_id:
            raise ContractValidationError("PST projection message binding is invalid")
        if payload.get("thread_id") != expected_thread_ids[occurrence_id]:
            raise ContractValidationError("PST projection thread binding is invalid")
        occurrence_lineage = payload.get("occurrence_lineage")
        expected_lineage = (
            list(context.occurrence_lineage) if len(context.occurrence_lineage) > 1 else None
        )
        if occurrence_lineage != expected_lineage:
            raise ContractValidationError("PST projection occurrence lineage is invalid")
        if observation.location.get("message_occurrence_id") != occurrence_id:
            raise ContractValidationError("PST projection occurrence location is invalid")
        if observation.observation_type == "email_attachment_occurrence" and (
            observation.location.get("folder_path_hash") != context.message.folder_path_hash
            or observation.location.get("message_id") != context.message.message_id
            or observation.location.get("thread_id") != expected_thread_ids[occurrence_id]
        ):
            raise ContractValidationError("PST attachment parent location is invalid")
        if observation.observation_type == "email_attachment_occurrence":
            embedded_location_fields = {
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
            }
            present_embedded_location_fields = {
                field_name
                for field_name in embedded_location_fields
                if field_name in observation.location
            }
            if context.parent_occurrence_id is None:
                if present_embedded_location_fields:
                    raise ContractValidationError("PST top-level attachment ancestry is invalid")
            else:
                expected_embedded_location = {
                    "occurrence_lineage": list(context.occurrence_lineage),
                    "parent_message_occurrence_id": context.parent_occurrence_id,
                    "parent_attachment_id": context.parent_attachment_id,
                    "embedded_attachment_ordinal": context.message.embedded_attachment_ordinal,
                }
                if present_embedded_location_fields != embedded_location_fields:
                    raise ContractValidationError(
                        "PST embedded attachment ancestry schema is invalid"
                    )
                _pst_exact_int(
                    observation.location["embedded_attachment_ordinal"],
                    "embedded attachment location ordinal",
                    minimum=1,
                )
                if any(
                    observation.location[field_name] != expected_value
                    for field_name, expected_value in expected_embedded_location.items()
                ):
                    raise ContractValidationError(
                        "PST embedded attachment ancestry binding is invalid"
                    )
    for observation in body_observations:
        payload = _pst_observation_payload(observation)
        _pst_exact_int(payload.get("duplicate_ordinal"), "body duplicate ordinal", minimum=1)
        _pst_exact_int(payload.get("body_segment_index"), "body segment index", minimum=1)
        _pst_exact_int(payload.get("body_segment_count"), "body segment count")
        _pst_exact_int(payload.get("stored_body_char_count"), "stored body character count")
        _pst_exact_int(payload.get("body_redacted_segment_count"), "body redacted segment count")
        if payload.get("source_body_char_count") is not None:
            _pst_exact_int(payload["source_body_char_count"], "source body character count")
        _pst_exact_int(
            observation.location.get("body_segment_index"),
            "body location segment index",
            minimum=1,
        )
        _pst_exact_int(observation.location.get("char_start"), "body location start")
        _pst_exact_int(observation.location.get("char_end"), "body location end")
        _pst_require_exact_keys(
            payload,
            {
                "archive_id",
                "mailbox_id",
                "message_id",
                "message_occurrence_id",
                "message_occurrence_identity_policy",
                "duplicate_ordinal",
                "thread_id",
                "body_segment_index",
                "body_segment_count",
                "body_hash",
                "stored_body_char_count",
                "body_evidence_state",
                "body_projection_policy",
                "body_projection_state",
                "body_projection_fingerprint",
                "body_failure_codes",
                "body_redacted_segment_count",
                "content_publicly_unsafe",
                "message_fingerprint",
            },
            "PST body payload",
            optional={
                "source_body_char_count",
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
            },
        )
        if (
            observation.location["body_segment_index"] != payload["body_segment_index"]
            or observation.location.get("body_projection_policy")
            != payload["body_projection_policy"]
            or observation.location.get("body_projection_fingerprint")
            != payload["body_projection_fingerprint"]
            or observation.location.get("char_start") is None
            or observation.location.get("char_end") is None
        ):
            raise ContractValidationError("PST body segment index is invalid")
    for observation in header_observations:
        payload = _pst_observation_payload(observation)
        _pst_exact_int(payload.get("duplicate_ordinal"), "header duplicate ordinal", minimum=1)
        _pst_exact_int(payload.get("header_ordinal"), "header ordinal", minimum=1)
        _pst_exact_int(
            payload.get("header_projection_count"),
            "header projection count",
        )
        _pst_exact_int(
            payload.get("header_projection_index"),
            "header projection index",
            minimum=1,
        )
        _pst_exact_int(
            observation.location.get("header_index"),
            "header location ordinal",
            minimum=1,
        )
        _pst_exact_int(
            observation.location.get("header_projection_count"),
            "header location count",
        )
        _pst_exact_int(
            observation.location.get("header_projection_index"),
            "header location index",
            minimum=1,
        )
        if observation.location.get("header_index") != payload.get("header_ordinal"):
            raise ContractValidationError("PST header ordinal is invalid")
        if observation.location.get("header_name") != payload.get("header_name"):
            raise ContractValidationError("PST header name is invalid")
        if not (
            {"reply"} <= set(payload)
            or {"chronology"} <= set(payload)
            or {"header_value"} <= set(payload)
        ):
            raise ContractValidationError("PST header payload variant is invalid")
    for observation in attachment_observations:
        payload = _pst_observation_payload(observation)
        _pst_require_exact_keys(
            observation.location,
            {
                "archive_id",
                "mailbox_id",
                "folder_path_hash",
                "message_id",
                "message_occurrence_id",
                "thread_id",
                "attachment_index",
                "attachment_ordinal",
                "attachment_id",
            },
            "PST attachment location",
            optional={
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
                "attachment_source",
                "attachment_source_local_key",
                "attachment_processing_state",
                "attachment_source_name_fingerprint",
            },
        )
        _pst_exact_int(
            payload.get("duplicate_ordinal"),
            "attachment duplicate ordinal",
            minimum=1,
        )
        _pst_exact_int(
            payload.get("extracted_text_segment_count"),
            "attachment text segment count",
        )
        for field_name in (
            "attachment_index",
            "attachment_ordinal",
        ):
            if payload.get(field_name) is not None:
                _pst_exact_int(payload[field_name], field_name, minimum=1)
        location_attachment_index = _pst_exact_int(
            observation.location.get("attachment_index"),
            "attachment location index",
            minimum=1,
        )
        location_attachment_ordinal = _pst_exact_int(
            observation.location.get("attachment_ordinal"),
            "attachment location ordinal",
            minimum=1,
        )
        if location_attachment_index != payload.get("attachment_index"):
            raise ContractValidationError("PST attachment location index is invalid")
        if location_attachment_ordinal != payload.get("attachment_ordinal"):
            raise ContractValidationError("PST attachment location ordinal is invalid")
        for field_name in (
            "size_bytes",
            "attachment_size_bytes",
            "attachment_source_byte_count",
            "attachment_source_size_bytes",
            "attachment_source_char_count",
            "attachment_stored_char_count",
            "attachment_stored_byte_count",
            "attachment_source_stored_byte_count",
        ):
            if payload.get(field_name) is not None:
                _pst_exact_int(payload[field_name], field_name)
        _pst_require_exact_keys(
            payload,
            {
                "archive_id",
                "mailbox_id",
                "message_id",
                "message_occurrence_id",
                "message_occurrence_identity_policy",
                "duplicate_ordinal",
                "thread_id",
                "attachment_id",
                "filename",
                "text_extraction_state",
                "extracted_text_segment_count",
                "message_fingerprint",
            },
            "PST attachment payload",
            optional={
                "mime_type",
                "content_hash",
                "size_bytes",
                "attachment_failure_code",
                "attachment_index",
                "attachment_ordinal",
                "attachment_processing_state",
                "attachment_source",
                "attachment_source_local_key",
                "attachment_source_name_fingerprint",
                "attachment_filename",
                "attachment_name_fingerprint",
                "attachment_content_fingerprint",
                "attachment_size_bytes",
                "attachment_source_byte_count",
                "attachment_processing_state",
                "attachment_text_extraction_state",
                "attachment_source_char_count",
                "attachment_stored_char_count",
                "attachment_stored_byte_count",
                "attachment_text_segments_fingerprint",
                "attachment_inventory_item_id",
                "attachment_inventory_source_local_key",
                "attachment_source_inventory_item_id",
                "attachment_source_inventory_source_local_key",
                "attachment_parent_message_source_local_key",
                "attachment_source_media_type",
                "attachment_source_processing_state",
                "attachment_source_failure_code",
                "attachment_source_content_fingerprint",
                "attachment_source_size_bytes",
                "attachment_source_byte_count",
                "attachment_source_stored_byte_count",
                "attachment_source_name_fingerprint",
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
            },
        )
        if observation.location.get("attachment_id") != payload["attachment_id"]:
            raise ContractValidationError("PST attachment identity is invalid")
    for observation in attachment_text_observations:
        payload = _pst_observation_payload(observation)
        _pst_exact_int(
            payload.get("duplicate_ordinal"),
            "attachment text duplicate ordinal",
            minimum=1,
        )
        _pst_exact_int(
            payload.get("attachment_index"),
            "attachment text attachment index",
            minimum=1,
        )
        _pst_exact_int(
            payload.get("attachment_text_segment_index"),
            "attachment text segment index",
            minimum=1,
        )
        _pst_exact_int(
            payload.get("attachment_text_segment_count"),
            "attachment text segment count",
        )
        if payload.get("attachment_ordinal") is not None:
            _pst_exact_int(
                payload["attachment_ordinal"],
                "attachment text attachment ordinal",
                minimum=1,
            )
        _pst_exact_int(
            observation.location.get("attachment_index"),
            "attachment text location attachment index",
            minimum=1,
        )
        _pst_exact_int(
            observation.location.get("attachment_text_segment_index"),
            "attachment text location segment index",
            minimum=1,
        )
        _pst_require_exact_keys(
            payload,
            {
                "archive_id",
                "mailbox_id",
                "message_id",
                "message_occurrence_id",
                "message_occurrence_identity_policy",
                "duplicate_ordinal",
                "thread_id",
                "attachment_id",
                "attachment_index",
                "attachment_text_segment_index",
                "attachment_text_segment_count",
                "text_extraction_state",
                "message_fingerprint",
            },
            "PST attachment text payload",
            optional={
                "attachment_failure_code",
                "attachment_ordinal",
                "attachment_processing_state",
                "attachment_source",
                "attachment_source_local_key",
                "attachment_source_name_fingerprint",
                "attachment_filename",
                "attachment_name_fingerprint",
                "attachment_content_fingerprint",
                "attachment_size_bytes",
                "attachment_source_byte_count",
                "attachment_processing_state",
                "attachment_text_extraction_state",
                "attachment_source_char_count",
                "attachment_stored_char_count",
                "attachment_stored_byte_count",
                "attachment_text_segments_fingerprint",
                "attachment_inventory_item_id",
                "attachment_inventory_source_local_key",
                "attachment_source_inventory_item_id",
                "attachment_source_inventory_source_local_key",
                "attachment_parent_message_source_local_key",
                "attachment_source_media_type",
                "attachment_source_processing_state",
                "attachment_source_failure_code",
                "attachment_source_content_fingerprint",
                "attachment_source_size_bytes",
                "attachment_source_byte_count",
                "attachment_source_stored_byte_count",
                "attachment_source_name_fingerprint",
                "attachment_text_segment_fingerprint",
                "occurrence_lineage",
                "parent_message_occurrence_id",
                "parent_attachment_id",
                "embedded_attachment_ordinal",
            },
        )
        if observation.location.get("attachment_id") != payload["attachment_id"]:
            raise ContractValidationError("PST attachment text identity is invalid")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be an object")
    return value


def _require_list(value: Mapping[str, Any], field_name: str) -> list[Any]:
    result = value.get(field_name)
    if not isinstance(result, list):
        raise ContractValidationError(f"{field_name} must be a list")
    return result


def _assert_exact_keys(
    value: Mapping[str, Any],
    allowed: set[str],
    field_name: str,
) -> None:
    if set(value) - allowed:
        raise ContractValidationError(f"{field_name} contains unknown fields")


def _run_parser_command(command: Sequence[str], timeout_seconds: int) -> _ParserCommandResult:
    completed = subprocess.run(
        list(command),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
    )
    return _ParserCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _create_scratch_dir(scratch_parent: Path | None) -> Path:
    parent = scratch_parent or Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        candidate = parent / f"formowl-pst-export-{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
            if os.name != "nt":
                candidate.chmod(0o700)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("pst parser scratch allocation failed")


def _readpst_command(
    parser_command: str,
    pst_path: Path,
    output_dir: Path,
    *,
    include_deleted_items: bool,
    parallel_jobs: int = 1,
) -> list[str]:
    if parallel_jobs not in PST_READPST_PARALLEL_JOBS:
        raise ContractValidationError("PST export parallel jobs are invalid")
    command = [parser_command, "-S", "-o", str(output_dir)]
    if parallel_jobs > 1:
        command.extend(["-j", str(parallel_jobs)])
    if include_deleted_items:
        command.append("-D")
    command.append(str(pst_path))
    return command


def _looks_like_pst(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == _PST_HEADER
    except OSError:
        return False


def _parser_config(config: Mapping[str, Any]) -> _PstParserConfig:
    return _PstParserConfig(
        max_messages=_optional_positive_int(config.get("max_messages"), "max_messages"),
        timeout_seconds=_positive_int(config.get("timeout_seconds", 900), "timeout_seconds"),
        max_message_file_bytes=_positive_int(
            config.get("max_message_file_bytes", 25 * 1024 * 1024),
            "max_message_file_bytes",
        ),
        body_segment_max_chars=_positive_int(
            config.get("body_segment_max_chars", 4000),
            "body_segment_max_chars",
        ),
        max_body_segments_per_message=_optional_positive_int(
            config.get("max_body_segments_per_message"),
            "max_body_segments_per_message",
        ),
        max_attachment_hash_bytes=_positive_int(
            config.get("max_attachment_hash_bytes", 5 * 1024 * 1024),
            "max_attachment_hash_bytes",
        ),
        max_attachment_text_bytes=_positive_int(
            config.get("max_attachment_text_bytes", 5 * 1024 * 1024),
            "max_attachment_text_bytes",
        ),
        preserve_private_body_text=_bool_config(
            config.get("preserve_private_body_text", True),
            "preserve_private_body_text",
        ),
        include_deleted_items=_bool_config(
            config.get("include_deleted_items", False),
            "include_deleted_items",
        ),
        parser_workers=_positive_int(config.get("parser_workers", 1), "parser_workers"),
    )


def _positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _bool_config(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _parse_exported_messages(
    traversal: _ExportedTraversal,
    *,
    config: _PstParserConfig,
    lookup_context: _PstExtractionLookupContext | None = None,
) -> tuple[
    list[_ParsedMessage],
    list[str],
    dict[str, _PstSourceUnitClassification],
]:
    lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    if config.parser_workers > 1 and config.max_messages is None:
        return _parse_exported_messages_parallel(
            traversal,
            config=config,
            lookup_context=lookup_context,
        )
    parsed: list[_ParsedMessage] = []
    warnings: list[str] = []
    source_unit_classifications: dict[str, _PstSourceUnitClassification] = {}
    message_unit_count = 0
    warnings.extend(traversal.error_codes)
    for unit in traversal.units:
        candidate = unit.path
        if candidate is None:
            continue
        if unit.structure_kind == "exported_directory":
            continue
        source_unit_kind = _exported_source_unit_kind(unit)
        if (
            source_unit_kind == _PST_SOURCE_UNIT_MESSAGE
            and config.max_messages is not None
            and message_unit_count >= config.max_messages
        ):
            _record_source_unit_classification(
                source_unit_classifications,
                _message_limit_classification(unit),
            )
            _append_warning_once(warnings, _PST_MESSAGE_LIMIT_FAILURE_CODE)
            continue
        if source_unit_kind == _PST_SOURCE_UNIT_MESSAGE:
            message_unit_count += 1
        classification = _source_unit_classification_for_unit(
            unit,
            config=config,
            warnings=warnings,
            source_unit_classifications=source_unit_classifications,
        )
        warnings.extend(_source_unit_parser_warnings(classification))
        message = classification.message
        if message is None:
            continue
        parsed_message = _parsed_message_from_email(
            message,
            candidate_path=candidate,
            export_root=traversal.export_root,
            message_index=len(parsed) + 1,
            config=config,
            warnings=warnings,
            source_local_key=unit.source_local_key,
            folder_components=(
                unit.canonical_relative_components[:-1]
                if unit.canonical_relative_components is not None
                else None
            ),
        )
        parsed.append(parsed_message)
    lookup_context.bind_parsed_messages(parsed)
    _integrate_readpst_sidecars(
        parsed,
        traversal=traversal,
        config=config,
        warnings=warnings,
        source_unit_classifications=source_unit_classifications,
        lookup_context=lookup_context,
    )
    return parsed, warnings, source_unit_classifications


def _parse_exported_messages_parallel(
    traversal: _ExportedTraversal,
    *,
    config: _PstParserConfig,
    lookup_context: _PstExtractionLookupContext | None = None,
) -> tuple[
    list[_ParsedMessage],
    list[str],
    dict[str, _PstSourceUnitClassification],
]:
    lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    candidates = [
        (unit.path, unit.source_local_key, _exported_source_unit_kind(unit))
        for unit in traversal.units
        if unit.path is not None and _exported_source_unit_kind(unit) == _PST_SOURCE_UNIT_MESSAGE
    ]
    candidate_by_key = {
        source_local_key: candidate for candidate, source_local_key, _source_unit_kind in candidates
    }
    folder_components_by_key = {
        unit.source_local_key: unit.canonical_relative_components
        for unit in traversal.units
        if unit.path is not None
    }
    parsed: list[_ParsedMessage] = []
    warnings: list[str] = list(traversal.error_codes)
    source_unit_classifications: dict[str, _PstSourceUnitClassification] = {}
    executor_type = ThreadPoolExecutor if os.name == "nt" else ProcessPoolExecutor
    with executor_type(max_workers=config.parser_workers) as executor:
        results = executor.map(
            _parse_exported_message_file_job,
            (
                (candidate, source_local_key, source_unit_kind, config)
                for candidate, source_local_key, source_unit_kind in candidates
            ),
            chunksize=25,
        )
        for classification, parse_warnings in results:
            warnings.extend(parse_warnings)
            _record_source_unit_classification(
                source_unit_classifications,
                classification,
            )
            message = classification.message
            if message is not None:
                candidate = candidate_by_key.get(classification.source_local_key)
                if candidate is None:
                    raise ContractValidationError(
                        "PST source-unit classification has no matching candidate"
                    )
                parsed_message = _parsed_message_from_email(
                    message,
                    candidate_path=candidate,
                    export_root=traversal.export_root,
                    message_index=len(parsed) + 1,
                    config=config,
                    warnings=warnings,
                    source_local_key=classification.source_local_key,
                    folder_components=(
                        folder_components_by_key[classification.source_local_key][:-1]
                        if folder_components_by_key.get(classification.source_local_key) is not None
                        else None
                    ),
                )
                parsed.append(parsed_message)
    lookup_context.bind_parsed_messages(parsed)
    _integrate_readpst_sidecars(
        parsed,
        traversal=traversal,
        config=config,
        warnings=warnings,
        source_unit_classifications=source_unit_classifications,
        lookup_context=lookup_context,
    )
    return parsed, warnings, source_unit_classifications


def _integrate_readpst_sidecars(
    parsed_messages: list[_ParsedMessage],
    *,
    traversal: _ExportedTraversal,
    config: _PstParserConfig,
    warnings: list[str],
    source_unit_classifications: dict[str, _PstSourceUnitClassification],
    lookup_context: _PstExtractionLookupContext | None = None,
) -> None:
    """Attach readable readpst sidecars to their parsed parent occurrence.

    The sidecar source remains an inventory unit.  Only a resolved parent
    message may authorize the ordinary attachment projection; the filename
    never authorizes a child message or version relation.
    """

    lookup_context = _pst_lookup_context_for_traversal(traversal, lookup_context)
    lookup_context.bind_parsed_messages(parsed_messages)
    for unit in traversal.units:
        if _exported_source_unit_kind(unit) != _PST_SOURCE_UNIT_ATTACHMENT:
            continue
        classification = _source_unit_classification_for_unit(
            unit,
            config=config,
            warnings=warnings,
            source_unit_classifications=source_unit_classifications,
        )
        location = _readpst_source_unit_location(
            unit,
            traversal=traversal,
            source_unit_classifications=source_unit_classifications,
            lookup_context=lookup_context,
        )
        if location.get("source_unit_attachment_state") != "linked":
            continue
        parent_source_key = location.get("source_unit_parent_source_local_key")
        parent = lookup_context.parsed_messages_by_source_key.get(parent_source_key)
        attachment_classification = classification.attachment_classification
        if parent is None or attachment_classification is None:
            continue
        content_hash = (
            "sha256:" + classification.source_content_fingerprint
            if classification.source_content_fingerprint is not None
            else None
        )
        duplicate = next(
            (
                attachment
                for attachment in parent.attachments
                if (
                    content_hash is not None
                    and attachment.content_hash == content_hash
                    and attachment.source_name_fingerprint
                    == classification.attachment_name_fingerprint
                )
            ),
            None,
        )
        if duplicate is not None:
            source_unit_classifications[unit.source_local_key] = replace(
                classification,
                linked_attachment_id=duplicate.attachment_id,
            )
            continue
        attachment_index = len(parent.attachments) + 1
        attachment_id = stable_resource_contract_id(
            "mailatt",
            "PstAttachment",
            {
                "filename": classification.attachment_filename,
                "content_hash": content_hash,
                "size_bytes": classification.source_size_bytes,
                "attachment_index": attachment_index,
                "source_local_key": unit.source_local_key,
                "source_kind": "readpst_sidecar",
            },
        )
        sidecar_attachment = _ParsedAttachment(
            attachment_id=attachment_id,
            filename=classification.attachment_filename or f"readpst-attachment-{attachment_index}",
            mime_type=classification.attachment_mime_type,
            content_hash=content_hash,
            size_bytes=classification.source_size_bytes,
            extracted_text_segments=attachment_classification.extracted_text_segments,
            text_extraction_state=attachment_classification.text_extraction_state,
            processing_state=attachment_classification.processing_state,
            failure_code=attachment_classification.failure_code,
            source_local_key=unit.source_local_key,
            source_kind="readpst_sidecar",
            text=attachment_classification.text,
            source_name_fingerprint=classification.attachment_name_fingerprint,
            source_char_count=(
                len(attachment_classification.text)
                if attachment_classification.processing_state == "parsed"
                and isinstance(attachment_classification.text, str)
                else None
            ),
            stored_char_count=sum(
                len(segment) for segment in attachment_classification.extracted_text_segments
            ),
        )
        updated = replace(
            parent,
            attachments=[*parent.attachments, sidecar_attachment],
            unresolved_attachment_count=sum(
                _attachment_is_unresolved(attachment)
                for attachment in (*parent.attachments, sidecar_attachment)
            ),
        )
        index = lookup_context.parsed_message_positions_by_source_key.get(parent_source_key)
        if index is None:
            continue
        parsed_messages[index] = updated
        lookup_context.parsed_messages_by_source_key[parent_source_key] = updated


def _parse_exported_message_file_job(
    args: tuple[Path, str, str, _PstParserConfig],
) -> tuple[_PstSourceUnitClassification, list[str]]:
    candidate, source_local_key, source_unit_kind, config = args
    return _parse_exported_message_file(
        candidate,
        source_local_key=source_local_key,
        source_unit_kind=source_unit_kind,
        config=config,
    )


def _parse_exported_message_file(
    candidate: Path,
    *,
    source_local_key: str,
    source_unit_kind: str,
    config: _PstParserConfig,
) -> tuple[_PstSourceUnitClassification, list[str]]:
    warnings: list[str] = []
    classification = _inventory_parse_file(
        candidate,
        source_local_key=source_local_key,
        source_unit_kind=source_unit_kind,
        config=config,
        warnings=warnings,
    )
    return classification, _source_unit_parser_warnings(classification)


def _export_directory_key(directory: Path, export_root: Path) -> str:
    relative_bytes = _canonical_relative_identity_bytes(directory, export_root)
    return f"directory:{hashlib.sha256(relative_bytes).hexdigest()[:24]}"


def _export_symlink_key(link: Path, export_root: Path) -> str:
    relative_bytes = _canonical_relative_identity_bytes(link, export_root)
    return f"symlink:{hashlib.sha256(relative_bytes).hexdigest()[:24]}"


def _failed_export_traversal(
    export_root: Path,
    failure_code: str,
    *,
    source_local_key: str = "export_root",
) -> _ExportedTraversal:
    return _ExportedTraversal(
        export_root=export_root,
        units=(
            _ExportedTraversalUnit(
                source_local_key=source_local_key,
                parent_source_local_key="archive",
                path=None,
                structure_kind="exported_directory",
                failure_code=failure_code,
                canonical_relative_components=(),
            ),
        ),
    )


def _safe_traversal_snapshot(
    provider: _TraversalProvider,
    export_root: Path,
) -> _ExportedTraversal:
    try:
        traversal = provider(export_root)
        traversal = _canonicalize_traversal_components(traversal)
    except _PstPathCanonicalizationError:
        return _failed_export_traversal(
            export_root,
            _PstPathCanonicalizationError.code,
        )
    except OSError:
        return _failed_export_traversal(export_root, "pst_export_root_unreadable")
    except Exception:
        return _failed_export_traversal(export_root, "pst_export_traversal_failed")
    if not isinstance(traversal, _ExportedTraversal):
        return _failed_export_traversal(export_root, "pst_export_traversal_failed")
    return traversal


def _canonicalize_traversal_components(
    traversal: _ExportedTraversal,
) -> _ExportedTraversal:
    units: list[_ExportedTraversalUnit] = []
    for unit in traversal.units:
        components = unit.canonical_relative_components
        if unit.path is not None:
            expected = _canonical_relative_components(unit.path, traversal.export_root)
            if components is None:
                components = expected
            elif components != expected:
                raise ContractValidationError("PST traversal path identity mismatch")
        elif components is not None and (
            not isinstance(components, tuple)
            or any(not isinstance(component, bytes) for component in components)
        ):
            raise ContractValidationError("PST traversal component identity is invalid")
        units.append(replace(unit, canonical_relative_components=components))
    return _ExportedTraversal(
        export_root=traversal.export_root,
        units=tuple(units),
    )


def _validate_traversal_source_unit_bindings(
    traversal: _ExportedTraversal,
) -> None:
    seen_source_local_keys: set[str] = set()
    for unit in traversal.units:
        source_local_key = unit.source_local_key
        if not isinstance(source_local_key, str) or not source_local_key:
            raise ContractValidationError("PST traversal unit lacks a source-local key")
        _pst_strict_utf8_bytes(source_local_key)
        parent_source_local_key = unit.parent_source_local_key
        if not isinstance(parent_source_local_key, str) or not parent_source_local_key:
            raise ContractValidationError("PST traversal unit lacks a parent source-local key")
        _pst_strict_utf8_bytes(parent_source_local_key)
        if source_local_key in seen_source_local_keys:
            raise ContractValidationError("PST traversal source-unit identity collision")
        seen_source_local_keys.add(source_local_key)
        if unit.path is None:
            continue
        try:
            unit.path.relative_to(traversal.export_root)
        except ValueError as exc:
            raise ContractValidationError("PST traversal path escapes export root") from exc
        try:
            mode = unit.path.lstat().st_mode
        except OSError as exc:
            raise ContractValidationError("PST traversal path is unavailable") from exc
        if stat.S_ISLNK(mode):
            raise ContractValidationError("PST traversal symlink is unsupported")
        expected_components = _canonical_relative_components(unit.path, traversal.export_root)
        if unit.canonical_relative_components != expected_components:
            raise ContractValidationError("PST traversal path identity mismatch")
        if unit.structure_kind == "exported_directory":
            if not stat.S_ISDIR(mode):
                raise ContractValidationError("PST traversal directory identity is invalid")
            expected_source_local_key = _export_directory_key(unit.path, traversal.export_root)
        elif unit.structure_kind == "exported_file":
            if not stat.S_ISREG(mode):
                raise ContractValidationError("PST traversal file identity is invalid")
            expected_source_local_key = f"file:{_export_file_key(unit.path, traversal.export_root)}"
        else:
            raise ContractValidationError("PST traversal unit kind is invalid")
        if source_local_key != expected_source_local_key:
            raise ContractValidationError("PST traversal source-unit binding mismatch")


def _selected_readpst_export_traversal(
    export_root: str | Path,
    *,
    selected_message_paths: Sequence[str | Path],
) -> _ExportedTraversal:
    """Build a validated traversal for explicit existing readpst message paths.

    Unlike :func:`_snapshot_export_tree`, this helper does not list the export
    tree.  It touches only the configured message paths and each selected
    path's parent directory chain so a bounded recovery cannot accidentally
    turn into an archive-wide import.
    """

    if not selected_message_paths:
        raise ContractValidationError("selected readpst export requires at least one message path")
    root = Path(os.path.abspath(os.fspath(export_root)))
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        raise ContractValidationError("selected readpst export root is unavailable") from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise ContractValidationError("selected readpst export root is invalid")

    selected: set[Path] = set()
    for raw_path in selected_message_paths:
        if not isinstance(raw_path, (str, Path)):
            raise ContractValidationError("selected readpst message path is invalid")
        candidate_input = Path(raw_path)
        candidate = Path(
            os.path.abspath(
                os.fspath(
                    candidate_input if candidate_input.is_absolute() else root / candidate_input
                )
            )
        )
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ContractValidationError(
                "selected readpst message path escapes export root"
            ) from exc
        _validate_selected_readpst_path_lineage(candidate, export_root=root)
        if _source_unit_kind_for_path(candidate) != _PST_SOURCE_UNIT_MESSAGE:
            raise ContractValidationError("selected readpst path is not an exported message")
        selected.add(candidate)

    directories: set[Path] = set()
    for candidate in selected:
        current = candidate.parent
        while current != root:
            directories.add(current)
            current = current.parent

    def path_order_key(path: Path) -> tuple[Any, ...]:
        return tuple(
            _component_total_order_key(component) for component in path.relative_to(root).parts
        )

    units: list[_ExportedTraversalUnit] = []
    for directory in sorted(
        directories,
        key=lambda item: (len(_canonical_relative_components(item, root)), path_order_key(item)),
    ):
        parent = directory.parent
        units.append(
            _ExportedTraversalUnit(
                source_local_key=_export_directory_key(directory, root),
                parent_source_local_key=(
                    "archive" if parent == root else _export_directory_key(parent, root)
                ),
                path=directory,
                structure_kind="exported_directory",
                canonical_relative_components=_canonical_relative_components(directory, root),
            )
        )
    for candidate in sorted(selected, key=path_order_key):
        parent = candidate.parent
        units.append(
            _ExportedTraversalUnit(
                source_local_key=f"file:{_export_file_key(candidate, root)}",
                parent_source_local_key=(
                    "archive" if parent == root else _export_directory_key(parent, root)
                ),
                path=candidate,
                structure_kind="exported_file",
                canonical_relative_components=_canonical_relative_components(candidate, root),
            )
        )
    return _ExportedTraversal(export_root=root, units=tuple(units))


def _validate_selected_readpst_path_lineage(candidate: Path, *, export_root: Path) -> None:
    """Reject missing, symlinked, or non-regular selected export paths."""

    current = candidate
    while True:
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ContractValidationError("selected readpst message path is unavailable") from exc
        if stat.S_ISLNK(mode):
            raise ContractValidationError("selected readpst message path uses a symlink")
        if current == candidate and not stat.S_ISREG(mode):
            raise ContractValidationError("selected readpst message path is not a regular file")
        if current == export_root:
            if not stat.S_ISDIR(mode):
                raise ContractValidationError("selected readpst export root is invalid")
            return
        current = current.parent


def _snapshot_export_tree(export_root: Path) -> _ExportedTraversal:
    units: list[_ExportedTraversalUnit] = []

    def append_failure(
        path: Path,
        *,
        parent_source_local_key: str,
        failure_code: str,
        source_local_key: str,
    ) -> None:
        units.append(
            _ExportedTraversalUnit(
                source_local_key=source_local_key,
                parent_source_local_key=parent_source_local_key,
                path=None,
                structure_kind="exported_directory",
                failure_code=failure_code,
                canonical_relative_components=_canonical_relative_components(
                    path,
                    export_root,
                ),
            )
        )

    def visit(current: Path, *, parent_source_local_key: str, is_root: bool = False) -> None:
        try:
            current_mode = current.lstat().st_mode
        except OSError:
            append_failure(
                current,
                parent_source_local_key=parent_source_local_key,
                failure_code=(
                    "pst_export_root_unreadable" if is_root else "pst_export_subtree_unreadable"
                ),
                source_local_key="export_root"
                if is_root
                else _export_directory_key(current, export_root),
            )
            return
        if stat.S_ISLNK(current_mode):
            append_failure(
                current,
                parent_source_local_key=parent_source_local_key,
                failure_code=_PST_EXPORT_SYMLINK_FAILURE_CODE,
                source_local_key=_export_symlink_key(current, export_root),
            )
            return
        if not stat.S_ISDIR(current_mode):
            append_failure(
                current,
                parent_source_local_key=parent_source_local_key,
                failure_code=_PST_EXPORT_PATH_ESCAPE_FAILURE_CODE,
                source_local_key=_export_symlink_key(current, export_root),
            )
            return
        try:
            children = sorted(
                current.iterdir(),
                key=lambda item: _component_total_order_key(item.name),
            )
        except OSError:
            append_failure(
                current,
                parent_source_local_key=parent_source_local_key,
                failure_code=(
                    "pst_export_root_unreadable" if is_root else "pst_export_subtree_unreadable"
                ),
                source_local_key="export_root"
                if is_root
                else _export_directory_key(current, export_root),
            )
            return

        current_source_local_key = "archive"
        if not is_root:
            current_source_local_key = _export_directory_key(current, export_root)
            units.append(
                _ExportedTraversalUnit(
                    source_local_key=current_source_local_key,
                    parent_source_local_key=parent_source_local_key,
                    path=current,
                    structure_kind="exported_directory",
                    canonical_relative_components=_canonical_relative_components(
                        current,
                        export_root,
                    ),
                )
            )

        for child in children:
            try:
                child.relative_to(export_root)
            except ValueError:
                append_failure(
                    child,
                    parent_source_local_key=current_source_local_key,
                    failure_code=_PST_EXPORT_PATH_ESCAPE_FAILURE_CODE,
                    source_local_key=_export_symlink_key(child, export_root),
                )
                continue
            try:
                mode = child.lstat().st_mode
            except OSError:
                append_failure(
                    child,
                    parent_source_local_key=current_source_local_key,
                    failure_code="pst_export_subtree_unreadable",
                    source_local_key=_export_directory_key(child, export_root),
                )
                continue
            if stat.S_ISLNK(mode):
                append_failure(
                    child,
                    parent_source_local_key=current_source_local_key,
                    failure_code=_PST_EXPORT_SYMLINK_FAILURE_CODE,
                    source_local_key=_export_symlink_key(child, export_root),
                )
                continue
            if stat.S_ISDIR(mode):
                visit(
                    child,
                    parent_source_local_key=current_source_local_key,
                )
            elif stat.S_ISREG(mode):
                units.append(
                    _ExportedTraversalUnit(
                        source_local_key=f"file:{_export_file_key(child, export_root)}",
                        parent_source_local_key=current_source_local_key,
                        path=child,
                        structure_kind="exported_file",
                        canonical_relative_components=_canonical_relative_components(
                            child,
                            export_root,
                        ),
                    )
                )

    visit(export_root, parent_source_local_key="archive", is_root=True)
    return _ExportedTraversal(export_root=export_root, units=tuple(units))


def _is_mail_message(message: EmailMessage) -> bool:
    return any(
        message.get(header_name) is not None
        for header_name in ("subject", "from", "to", "date", "message-id")
    )


def _parsed_message_from_email(
    message: EmailMessage,
    *,
    candidate_path: Path,
    export_root: Path,
    message_index: int,
    config: _PstParserConfig,
    warnings: list[str],
    embedded_message_depth: int = 0,
    embedded_attachment_ordinal: int | None = None,
    source_local_key: str | None = None,
    folder_components: tuple[bytes, ...] | None = None,
) -> _ParsedMessage:
    if folder_components is None:
        raise ContractValidationError("PST folder component identity is missing")
    folder_path_hash, folder_label = _folder_identity(folder_components)
    subject = _safe_mail_text(_pst_first_raw_header_value(message, "subject"), "subject")
    sender = _safe_mail_text(_pst_first_raw_header_value(message, "from"), "sender")
    chronology = _interpret_chronology(message, warnings=warnings)
    sent_at = chronology.authored_sent_at
    body_classifications = _body_leaf_classifications(message, warnings=warnings)
    (
        raw_body,
        body_hash,
        source_body_char_count,
        body_summary_state,
        body_projection_state,
        body_failure_codes,
    ) = _body_projection(
        body_classifications,
        warnings=warnings,
    )
    if body_summary_state == "failed":
        body_segments: list[_ParsedBodySegment] = []
        body_evidence_state = "failed"
        body_redacted_segment_count = 0
    else:
        (
            body_segments,
            segment_state,
            body_redacted_segment_count,
        ) = _safe_body_segments(
            raw_body,
            max_chars=config.body_segment_max_chars,
            max_segments=config.max_body_segments_per_message,
            preserve_private_text=config.preserve_private_body_text,
            warnings=warnings,
        )
        body_evidence_state = (
            body_summary_state if body_summary_state == "partial" else segment_state
        )
    stored_body_char_count = sum(len(segment.text) for segment in body_segments)
    body_projection_fingerprint = _body_projection_fingerprint(
        body_segments=body_segments,
        body_projection_state=(
            body_projection_state
            if body_projection_state in {"bodyless_empty", "decoded_empty", "partial", "failed"}
            else body_evidence_state
        ),
        body_evidence_state=body_evidence_state,
        source_body_char_count=source_body_char_count,
        stored_body_char_count=stored_body_char_count,
        body_failure_codes=body_failure_codes,
        body_redacted_segment_count=body_redacted_segment_count,
    )
    normalized_subject = _normalize_subject(subject)
    message_id = _message_id(
        message,
        fallback_parts=(
            folder_path_hash,
            normalized_subject,
            sender,
            sent_at,
            body_hash,
        ),
    )
    reply_headers = _reply_header_occurrences(message, warnings=warnings)
    headers = _safe_headers(
        message,
        chronology=chronology,
        reply_headers=reply_headers,
        warnings=warnings,
    )
    header_projection_count = len(headers)
    header_projection_fingerprint = _header_projection_fingerprint(headers)
    references = [
        token
        for occurrence in reply_headers
        if occurrence.kind == "references" and occurrence.parse_status == "parsed"
        for token in occurrence.tokens
    ]
    in_reply_to_values = [
        token
        for occurrence in reply_headers
        if occurrence.kind == "in_reply_to" and occurrence.parse_status == "parsed"
        for token in occurrence.tokens
    ]
    in_reply_to = in_reply_to_values[0] if len(in_reply_to_values) == 1 else None
    attachments = _attachments(
        message,
        config=config,
        warnings=warnings,
        embedded_message_depth=embedded_message_depth,
    )
    unresolved_attachment_count = sum(
        _attachment_is_unresolved(attachment) for attachment in attachments
    )
    embedded_messages = tuple(
        _parsed_message_from_email(
            attachment.embedded_message,
            candidate_path=candidate_path,
            export_root=export_root,
            message_index=message_index,
            config=config,
            warnings=warnings,
            embedded_message_depth=embedded_message_depth + 1,
            embedded_attachment_ordinal=attachment_index,
            folder_components=folder_components,
        )
        for attachment_index, attachment in enumerate(attachments, start=1)
        if attachment.embedded_message is not None
    )
    return _ParsedMessage(
        folder_path_hash=folder_path_hash,
        folder_label=folder_label,
        message_id=message_id,
        subject=subject,
        normalized_subject=normalized_subject,
        sender=sender,
        sent_at=sent_at,
        headers=headers,
        chronology=chronology,
        body_segments=body_segments,
        body_hash=body_hash,
        source_body_char_count=source_body_char_count,
        stored_body_char_count=stored_body_char_count,
        body_evidence_state=body_evidence_state,
        body_projection_state=(
            body_projection_state
            if body_projection_state in {"bodyless_empty", "decoded_empty", "partial", "failed"}
            else body_evidence_state
        ),
        body_projection_fingerprint=body_projection_fingerprint,
        header_projection_count=header_projection_count,
        header_projection_fingerprint=header_projection_fingerprint,
        body_failure_codes=body_failure_codes,
        body_redacted_segment_count=body_redacted_segment_count,
        unresolved_attachment_count=unresolved_attachment_count,
        attachments=attachments,
        reply_headers=reply_headers,
        references=references,
        in_reply_to=in_reply_to,
        embedded_messages=embedded_messages,
        embedded_attachment_ordinal=embedded_attachment_ordinal,
        source_local_key=source_local_key,
        raw_message=message,
    )


_PST_FOLDER_IDENTITY_POLICY = "formowl_pst_folder_identity_v2"
_PST_STRUCTURAL_INVENTORY_KINDS = frozenset({"html_table"})
_PST_STRUCTURAL_BUILD_FAILURE_CODE = "pst_structural_observation_build_failed"
_PST_STRUCTURAL_TRANSACTION_FAILURE_CODE = "pst_structural_transaction_failed"


def _folder_identity(folder_components: tuple[bytes, ...]) -> tuple[str, str]:
    if not isinstance(folder_components, tuple) or any(
        not isinstance(component, bytes) for component in folder_components
    ):
        raise ContractValidationError("PST folder component identity is invalid")
    folder_path_hash = sha256_json(
        {
            "policy": _PST_FOLDER_IDENTITY_POLICY,
            "components": [component.hex() for component in folder_components],
        }
    )
    label_components: list[str] = []
    for component in folder_components:
        try:
            label_component = unicodedata.normalize(
                "NFC",
                component.decode("utf-8", "strict"),
            )
        except UnicodeDecodeError:
            label_component = f"<opaque:{hashlib.sha256(component).hexdigest()[:16]}>"
        label_components.append(_safe_mail_text(label_component, "folder_label_component"))
    label = " / ".join(label_components) or "Mailbox"
    return folder_path_hash, _safe_mail_text(label, "folder_label")


def _message_id(message: EmailMessage, *, fallback_parts: tuple[Any, ...]) -> str:
    raw_value = _pst_first_raw_header_value(message, "message-id")
    value = (_pst_safe_text(raw_value) or "").strip()
    if value:
        return _safe_mail_text(value, "message_id")
    return stable_resource_contract_id("mailmsg", "PstMessage", {"fallback": fallback_parts})


def _safe_headers(
    message: EmailMessage,
    *,
    chronology: _MessageChronology,
    reply_headers: Sequence[_ReplyHeaderOccurrence] = (),
    warnings: list[str],
) -> tuple[_SafeHeaderOccurrence, ...]:
    chronology_by_header_ordinal = {
        occurrence.header_ordinal: occurrence
        for occurrence in (*chronology.date_occurrences, *chronology.received_occurrences)
    }
    reply_by_header_ordinal = {
        occurrence.header_ordinal: occurrence for occurrence in reply_headers
    }
    headers: list[_SafeHeaderOccurrence] = []
    for header_ordinal, (name, value) in enumerate(_pst_raw_header_items(message), start=1):
        header_name = _pst_safe_header_name(name)
        if header_name not in _SAFE_HEADER_NAMES:
            continue
        safe_name = _safe_header_name(header_name)
        occurrence = chronology_by_header_ordinal.get(header_ordinal)
        if occurrence is not None:
            headers.append(
                _SafeHeaderOccurrence(
                    header_name=safe_name,
                    header_ordinal=header_ordinal,
                    raw_value_fingerprint=occurrence.raw_value_fingerprint,
                    chronology=occurrence,
                )
            )
            continue
        reply = reply_by_header_ordinal.get(header_ordinal)
        if reply is not None:
            headers.append(
                _SafeHeaderOccurrence(
                    header_name=safe_name,
                    header_ordinal=header_ordinal,
                    raw_value_fingerprint=reply.raw_value_fingerprint,
                    reply=reply,
                )
            )
            continue
        raw_value = _pst_safe_text(value)
        if raw_value is None:
            _append_warning_once(warnings, "pst_parser_header_redacted")
            safe_value = _pst_opaque_text_marker(value, f"header_{safe_name}")
        else:
            safe_value = _safe_mail_text(raw_value, f"header_{safe_name}")
        headers.append(
            _SafeHeaderOccurrence(
                header_name=safe_name,
                header_ordinal=header_ordinal,
                header_value=safe_value,
                raw_value_fingerprint=_pst_raw_value_fingerprint(value),
            )
        )
    raw_message_id = _pst_first_raw_header_value(message, "message-id")
    if not any(header.header_name == "message-id" for header in headers) and raw_message_id:
        headers.append(
            _SafeHeaderOccurrence(
                header_name="message-id",
                header_ordinal=len(headers) + 1,
                header_value=_message_id(message, fallback_parts=("header",)),
                raw_value_fingerprint=_pst_raw_value_fingerprint(raw_message_id),
            )
        )
    return tuple(headers)


def _header_projection_fingerprint(
    headers: Sequence[_SafeHeaderOccurrence],
) -> str:
    """Return the canonical digest for the ordered safe header projection."""

    projection: list[dict[str, Any]] = []
    for projection_index, header in enumerate(headers, start=1):
        if header.chronology is not None:
            variant = "chronology"
            variant_payload: dict[str, Any] = {
                "chronology": header.chronology.to_payload(),
            }
        elif header.reply is not None:
            variant = "reply"
            variant_payload = {"reply": header.reply.to_payload()}
        else:
            variant = "ordinary"
            variant_payload = {"header_value": header.header_value}
        projection.append(
            {
                "header_projection_index": projection_index,
                "header_name": header.header_name,
                "header_ordinal": header.header_ordinal,
                "header_variant": variant,
                "raw_value_fingerprint": header.raw_value_fingerprint,
                **variant_payload,
            }
        )
    return sha256_json(
        {
            "policy": _PST_HEADER_PROJECTION_POLICY,
            "headers": projection,
        }
    )


def _safe_header_name(name: str) -> str:
    assert_no_public_raw_references(name, "pst_mail_header_name")
    return name


def _reply_header_occurrences(
    message: EmailMessage,
    *,
    warnings: list[str],
) -> tuple[_ReplyHeaderOccurrence, ...]:
    kind_ordinals = {"message-id": 0, "references": 0, "in-reply-to": 0}
    occurrences: list[_ReplyHeaderOccurrence] = []
    for header_ordinal, (name, value) in enumerate(_pst_raw_header_items(message), start=1):
        header_name = _pst_safe_header_name(name)
        if header_name not in kind_ordinals:
            continue
        kind_ordinals[header_name] += 1
        safe_value = _pst_safe_text(value)
        if safe_value is None:
            tokens = []
            parse_status = "malformed"
            error_code = f"pst_reply_{header_name.replace('-', '_')}_unencodable"
        else:
            tokens, parse_status, error_code = _parse_reply_header_value(
                safe_value,
                header_name=header_name,
            )
        token_fingerprints = tuple(sha256_json(token) for token in tokens)
        occurrence = _ReplyHeaderOccurrence(
            kind={
                "message-id": "message_id",
                "references": "references",
                "in-reply-to": "in_reply_to",
            }[header_name],
            header_ordinal=header_ordinal,
            occurrence_ordinal=kind_ordinals[header_name],
            raw_value_fingerprint=_pst_raw_value_fingerprint(value),
            parse_status=parse_status,
            token_fingerprints=token_fingerprints,
            tokens=tuple(tokens),
            safe_error_code=error_code,
        )
        occurrences.append(occurrence)
        if error_code is not None:
            _append_warning_once(warnings, error_code)
    return tuple(occurrences)


def _parse_reply_header_value(
    value: str,
    *,
    header_name: str,
) -> tuple[list[str], str, str | None]:
    """Parse msg-id occurrences with bounded, full-input consumption.

    The private token list is used only by the in-process resolver.  Public
    header and thread payloads contain only hashes and closed parse states.
    """

    if not value.strip():
        return [], "empty", f"pst_reply_{header_name.replace('-', '_')}_empty"
    unfolded = re.sub(r"(?:\r\n|\r|\n)[ \t]+", " ", value)
    if any(character in unfolded for character in "\r\n"):
        return [], "malformed", f"pst_reply_{header_name.replace('-', '_')}_malformed"
    tokens: list[str] = []
    index = 0
    length = len(unfolded)
    while index < length:
        index = _skip_reply_cfws(unfolded, index)
        if index > length:
            return [], "malformed", f"pst_reply_{header_name.replace('-', '_')}_malformed"
        if index >= length:
            break
        if unfolded[index] != "<":
            return [], "malformed", f"pst_reply_{header_name.replace('-', '_')}_malformed"
        start = index
        index += 1
        quoted = False
        escaped = False
        closed = False
        while index < length:
            character = unfolded[index]
            if escaped:
                if ord(character) < 32 or ord(character) == 127:
                    return [], "malformed", f"pst_reply_{header_name.replace('-', '_')}_malformed"
                escaped = False
                index += 1
                continue
            if character == "\\" and quoted:
                escaped = True
                index += 1
                continue
            if character == '"':
                quoted = not quoted
                index += 1
                continue
            if character == ">" and not quoted:
                closed = True
                index += 1
                break
            if ord(character) < 32 or ord(character) == 127:
                return [], "malformed", f"pst_reply_{header_name.replace('-', '_')}_malformed"
            if character.isspace() and not quoted:
                return [], "malformed", f"pst_reply_{header_name.replace('-', '_')}_malformed"
            index += 1
        if not closed or quoted or escaped:
            return [], "malformed", f"pst_reply_{header_name.replace('-', '_')}_malformed"
        token = unfolded[start:index]
        inner = token[1:-1]
        if not inner or "@" not in inner:
            return [], "malformed", f"pst_reply_{header_name.replace('-', '_')}_malformed"
        tokens.append(token)
        if len(tokens) > _PST_REPLY_HEADER_MAX_TOKENS:
            return (
                [],
                "overflow",
                f"pst_reply_{header_name.replace('-', '_')}_overflow",
            )
    if not tokens:
        return [], "empty", f"pst_reply_{header_name.replace('-', '_')}_empty"
    if header_name == "message-id" and len(tokens) != 1:
        return (
            tokens,
            "multiple",
            f"pst_reply_{header_name.replace('-', '_')}_multiple",
        )
    return tokens, "parsed", None


def _skip_reply_cfws(value: str, index: int) -> int:
    length = len(value)
    while index < length:
        if value[index] in " \t":
            index += 1
            continue
        if value[index] != "(":
            return index
        depth = 1
        index += 1
        escaped = False
        while index < length and depth:
            character = value[index]
            if escaped:
                if ord(character) < 32 or ord(character) == 127:
                    return length + 1
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif character in "\r\n":
                return length + 1
            index += 1
        if depth or escaped:
            return length + 1
    return index


def _safe_mail_text(value: Any, field_name: str) -> str:
    text = _pst_safe_text(value)
    if text is None:
        return _pst_opaque_text_marker(value, field_name)
    text = text.strip()
    if not text:
        return ""
    if field_name == "filename" and _looks_like_unsafe_attachment_filename(text):
        return f"redacted_{field_name}_{sha256_json(text)[-16:]}"
    try:
        assert_no_public_raw_references(text, f"pst_mail_{field_name}")
    except Exception:
        return f"redacted_{field_name}_{sha256_json(text)[-16:]}"
    return text


def _looks_like_unsafe_attachment_filename(value: str) -> bool:
    text = str(value or "")
    lowered = text.lower()
    return bool(
        re.search(r"^[a-z]:", text, re.IGNORECASE)
        or "/" in text
        or "\\" in text
        or "archive.pst" in lowered
        or "pst-exm" in lowered
    )


def _body_leaf_classifications(
    message: EmailMessage,
    *,
    warnings: list[str],
) -> tuple[_BodyLeafClassification, ...]:
    classifications: list[_BodyLeafClassification] = []
    metadata_cache: dict[int, _MimePartMetadata] = {}
    for part in _iter_outer_content_parts(message, metadata_cache=metadata_cache):
        classification = _classify_body_leaf(
            part,
            warnings=warnings,
            metadata=_mime_part_metadata(part, cache=metadata_cache),
        )
        if classification is not None:
            classifications.append(classification)
    return tuple(classifications)


def _body_projection_fingerprint(
    *,
    body_segments: Sequence[_ParsedBodySegment],
    body_projection_state: str,
    body_evidence_state: str,
    source_body_char_count: int | None,
    stored_body_char_count: int,
    body_failure_codes: Sequence[str],
    body_redacted_segment_count: int,
) -> str:
    if body_projection_state not in _PST_BODY_PROJECTION_STATES:
        raise ContractValidationError("PST body projection state is invalid")
    return sha256_json(
        {
            "policy": _PST_BODY_PROJECTION_POLICY,
            "body_projection_state": body_projection_state,
            "body_evidence_state": body_evidence_state,
            "source_body_char_count": source_body_char_count,
            "stored_body_char_count": stored_body_char_count,
            "body_failure_codes": list(body_failure_codes),
            "body_redacted_segment_count": body_redacted_segment_count,
            "body_segments": [
                {
                    "segment_index": segment.segment_index,
                    "text": segment.text,
                    "char_start": segment.char_start,
                    "char_end": segment.char_end,
                    "content_publicly_unsafe": segment.content_publicly_unsafe,
                }
                for segment in body_segments
            ],
        }
    )


def _body_projection(
    classifications: Sequence[_BodyLeafClassification],
    *,
    warnings: list[str],
) -> tuple[str, str, int | None, str, str, tuple[str, ...]]:
    applicable = tuple(classifications)
    parsed = tuple(
        classification
        for classification in applicable
        if classification.processing_state == "parsed"
    )
    failures = tuple(
        dict.fromkeys(
            classification.failure_code
            for classification in applicable
            if classification.failure_code is not None
        )
    )
    if not applicable:
        summary_state = "complete"
        projection_state = "bodyless_empty"
    elif not parsed:
        summary_state = "failed"
        projection_state = "failed"
        _append_warning_once(warnings, "pst_parser_message_body_failed")
    elif failures:
        summary_state = "partial"
        projection_state = "partial"
        _append_warning_once(warnings, "pst_parser_message_body_partial")
    else:
        summary_state = "complete"
        projection_state = "complete"

    plain_parts = [
        classification.text or ""
        for classification in parsed
        if classification.content_type == "text/plain"
    ]
    html_parts = [
        _html_to_text(classification.text or "")
        for classification in parsed
        if classification.content_type == "text/html"
    ]
    body = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if not body:
        body = "\n\n".join(part.strip() for part in html_parts if part.strip())

    if summary_state == "complete" and not body and applicable:
        projection_state = "decoded_empty"

    if summary_state == "complete":
        body_hash = sha256_json(body)
        source_body_char_count: int | None = len(body)
    else:
        body_hash = sha256_json(
            {
                "body_evidence_state": summary_state,
                "decoded_body_text": body,
                "applicable_leaf_count": len(applicable),
                "failure_codes": list(failures),
            }
        )
        source_body_char_count = None
    return body, body_hash, source_body_char_count, summary_state, projection_state, failures


def _classify_body_leaf(
    part: EmailMessage,
    *,
    warnings: list[str],
    metadata: _MimePartMetadata | None = None,
) -> _BodyLeafClassification | None:
    metadata = metadata or _mime_part_metadata(part)
    content_type = metadata.content_type
    if content_type not in {"text/plain", "text/html"}:
        return None
    if metadata.is_multipart or _is_attachment_part(part, metadata=metadata):
        return None
    if metadata.failed:
        return _failed_body_leaf(
            content_type,
            _PST_MIME_METADATA_FAILURE_CODE,
            warnings=warnings,
        )

    payload, failure_code = _strict_body_transfer_decode(part, warnings=warnings)
    if failure_code is not None:
        return _failed_body_leaf(content_type, failure_code, warnings=warnings)
    assert payload is not None

    text, failure_code, recovered = _strict_body_charset_decode(part, payload)
    if failure_code is not None:
        return _failed_body_leaf(content_type, failure_code, warnings=warnings)
    if not isinstance(text, str):
        return _failed_body_leaf(content_type, "content_decode_failed", warnings=warnings)
    if recovered:
        _append_warning_once(warnings, "pst_parser_body_charset_recovered")
    try:
        _pst_strict_utf8_bytes(text)
    except _PstTextEncodingError:
        return _failed_body_leaf(
            content_type,
            _PST_TEXT_UNENCODABLE_FAILURE_CODE,
            warnings=warnings,
        )
    return _BodyLeafClassification(
        content_type=content_type,
        processing_state="parsed",
        text=text,
    )


def _failed_body_leaf(
    content_type: str,
    failure_code: str,
    *,
    warnings: list[str],
) -> _BodyLeafClassification:
    _append_warning_once(warnings, f"pst_parser_body_{failure_code}")
    state = "preserved_unparsed" if failure_code in _PST_SEMANTIC_UNAVAILABILITY_CODES else "failed"
    return _BodyLeafClassification(
        content_type=content_type,
        processing_state=state,
        text=None,
        failure_code=failure_code,
    )


def _strict_body_transfer_decode(
    part: EmailMessage,
    *,
    warnings: list[str],
) -> tuple[bytes | None, str | None]:
    try:
        defects = tuple(getattr(part, "defects", ()))
        transfer_encoding = str(part.get("Content-Transfer-Encoding") or "").strip().lower()
    except Exception:
        return None, "content_decode_failed"
    raw_payload, recovered_access = _mime_raw_payload(part)
    if raw_payload is _PST_TRAVERSAL_BINDING_MISSING:
        return None, "content_decode_failed"
    if recovered_access:
        _append_warning_once(warnings, "pst_parser_body_content_access_recovered")

    if isinstance(raw_payload, list):
        return None, "transfer_decode_failed"
    if raw_payload is None:
        return None, "payload_missing"
    if defects:
        defect_names = {type(defect).__name__.casefold() for defect in defects}
        if any("base64" in name or "transfer" in name for name in defect_names):
            return None, "transfer_decode_failed"
        return None, "content_decode_failed"

    if isinstance(raw_payload, bytes):
        try:
            raw_text = raw_payload.decode("ascii")
        except UnicodeDecodeError:
            raw_text = None
    elif isinstance(raw_payload, str):
        raw_text = raw_payload
    else:
        return None, "content_decode_failed"

    try:
        if transfer_encoding == "base64":
            if raw_text is None:
                return None, "transfer_decode_failed"
            compact = re.sub(r"[ \t\r\n]+", "", raw_text)
            if not re.fullmatch(
                r"(?:[A-Za-z0-9+/]{4})*" r"(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?",
                compact,
            ):
                return None, "transfer_decode_failed"
            return base64.b64decode(compact, validate=True), None
        if transfer_encoding == "quoted-printable":
            if raw_text is None:
                return None, "transfer_decode_failed"
            index = 0
            while index < len(raw_text):
                if raw_text[index] != "=":
                    index += 1
                    continue
                if (
                    index + 2 < len(raw_text)
                    and raw_text[index + 1] in "0123456789abcdefABCDEF"
                    and raw_text[index + 2] in "0123456789abcdefABCDEF"
                ):
                    index += 3
                    continue
                if raw_text.startswith("\r\n", index + 1):
                    index += 3
                    continue
                if raw_text.startswith("\n", index + 1):
                    index += 2
                    continue
                return None, "transfer_decode_failed"
            return quopri.decodestring(raw_text), None
        if transfer_encoding not in {"", "7bit", "8bit", "binary"}:
            return None, "transfer_decode_failed"
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None
        if not isinstance(payload, bytes):
            if isinstance(raw_payload, bytes):
                payload = raw_payload
            elif isinstance(raw_payload, str):
                try:
                    payload = raw_payload.encode("utf-8", "surrogateescape")
                except UnicodeEncodeError:
                    return None, "transfer_decode_failed"
            else:
                return None, "transfer_decode_failed"
        if not isinstance(payload, bytes):
            return None, "transfer_decode_failed"
        if recovered_access:
            # The raw fallback above is the only payload authority after an accessor fault.
            _append_warning_once(warnings, "pst_parser_body_content_access_recovered")
        if transfer_encoding == "7bit" and any(byte > 0x7F for byte in payload):
            return None, "transfer_decode_failed"
        return payload, None
    except (binascii.Error, UnicodeError, ValueError):
        return None, "transfer_decode_failed"
    except Exception:
        return None, "content_decode_failed"


def _strict_body_charset_decode(
    part: EmailMessage,
    payload: bytes,
) -> tuple[str | None, str | None, bool]:
    try:
        charset = part.get_content_charset()
    except Exception:
        return None, "content_decode_failed", False
    if charset is None:
        return None, "charset_unknown", False
    safe_charset = _pst_safe_text(charset)
    if safe_charset is None or not safe_charset.strip():
        return None, "charset_unknown", False
    return _decode_text_payload(payload, declared_charset=safe_charset.strip())


def _decode_text_payload(
    payload: bytes,
    *,
    declared_charset: str,
) -> tuple[str | None, str | None, bool]:
    """Decode text only through the source-declared codec, without byte guessing."""

    try:
        text = payload.decode(declared_charset, errors="strict")
        _pst_strict_utf8_bytes(text)
    except LookupError:
        return None, "charset_unknown", False
    except UnicodeDecodeError:
        return None, "charset_decode_failed", False
    except _PstTextEncodingError:
        return None, _PST_TEXT_UNENCODABLE_FAILURE_CODE, False
    except Exception:
        return None, "content_decode_failed", False
    return text, None, False


def _mime_raw_payload(part: EmailMessage) -> tuple[Any, bool]:
    """Read MIME bytes with a bounded fallback for recoverable accessor faults."""

    try:
        return part.get_payload(decode=False), False
    except Exception:
        raw_payload = getattr(part, "_payload", _PST_TRAVERSAL_BINDING_MISSING)
        if isinstance(raw_payload, (bytes, str, list, tuple, EmailMessage)) or raw_payload is None:
            return raw_payload, True
        return _PST_TRAVERSAL_BINDING_MISSING, False


def _safe_body_segments(
    text: str,
    *,
    max_chars: int,
    max_segments: int | None,
    preserve_private_text: bool,
    warnings: list[str],
) -> tuple[list[_ParsedBodySegment], str, int]:
    segments: list[_ParsedBodySegment] = []
    redacted_segment_count = 0
    for start in range(0, len(text), max_chars):
        if max_segments is not None and len(segments) >= max_segments:
            warnings.append("pst_parser_body_segment_limit_reached")
            return segments, "truncated", redacted_segment_count
        chunk = text[start : start + max_chars]
        safe_text, publicly_unsafe = _safe_body_segment(
            chunk,
            preserve_private_text=preserve_private_text,
            warnings=warnings,
        )
        if publicly_unsafe and not preserve_private_text:
            redacted_segment_count += 1
        segments.append(
            _ParsedBodySegment(
                text=safe_text,
                char_start=start,
                char_end=start + len(chunk),
                content_publicly_unsafe=publicly_unsafe,
                segment_index=len(segments) + 1,
            )
        )
    if not text:
        return [], "complete", 0
    if redacted_segment_count:
        return segments, "redacted", redacted_segment_count
    return segments, "complete", 0


def _safe_body_segment(
    value: str,
    *,
    preserve_private_text: bool,
    warnings: list[str],
) -> tuple[str, bool]:
    try:
        assert_no_public_raw_references(value, "pst_mail_body_segment")
    except Exception:
        if preserve_private_text:
            warnings.append("pst_parser_body_segment_contains_publicly_unsafe_text")
            return value, True
        warnings.append("pst_parser_body_segment_redacted")
        return f"redacted_mail_body_segment {sha256_json(value)}", True
    return value, False


def _attachments(
    message: EmailMessage,
    *,
    config: _PstParserConfig,
    warnings: list[str],
    embedded_message_depth: int = 0,
) -> list[_ParsedAttachment]:
    attachments: list[_ParsedAttachment] = []
    metadata_cache: dict[int, _MimePartMetadata] = {}
    for part in _iter_outer_attachment_parts(message, metadata_cache=metadata_cache):
        metadata = _mime_part_metadata(part, cache=metadata_cache)
        attachment_index = len(attachments) + 1
        safe_filename = _mime_attachment_filename(
            metadata,
            attachment_ordinal=attachment_index,
        )
        classification = _classify_attachment_part(
            part,
            config=config,
            warnings=warnings,
            embedded_message_depth=embedded_message_depth,
            metadata=metadata,
        )
        payload = classification.payload
        size_bytes = len(payload) if isinstance(payload, bytes) else None
        content_hash = None
        if isinstance(payload, bytes) and len(payload) <= config.max_attachment_hash_bytes:
            content_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
        elif isinstance(payload, bytes):
            warnings.append("pst_parser_large_attachment_hash_skipped")
        attachment_id = stable_resource_contract_id(
            "mailatt",
            "PstAttachment",
            {
                "filename": safe_filename,
                "content_hash": content_hash,
                "size_bytes": size_bytes,
                "attachment_index": attachment_index,
            },
        )
        attachments.append(
            _ParsedAttachment(
                attachment_id=attachment_id,
                filename=safe_filename,
                mime_type=_safe_mail_text(metadata.content_type, "attachment_mime_type"),
                content_hash=content_hash,
                size_bytes=size_bytes,
                extracted_text_segments=classification.extracted_text_segments,
                text_extraction_state=classification.text_extraction_state,
                processing_state=classification.processing_state,
                failure_code=classification.failure_code,
                embedded_message=classification.embedded_message,
                source_name_fingerprint=_mime_attachment_name_fingerprint(metadata),
                source_char_count=(
                    len(classification.text)
                    if classification.processing_state == "parsed"
                    and isinstance(classification.text, str)
                    else None
                ),
                stored_char_count=sum(
                    len(segment) for segment in classification.extracted_text_segments
                ),
            )
        )
    return attachments


def _append_warning_once(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _classify_attachment_part(
    part: EmailMessage,
    *,
    config: _PstParserConfig,
    warnings: list[str],
    embedded_message_depth: int,
    metadata: _MimePartMetadata | None = None,
) -> _AttachmentClassification:
    metadata = metadata or _mime_part_metadata(part)
    if metadata.failed:
        _append_warning_once(
            warnings,
            f"pst_parser_attachment_{_PST_MIME_METADATA_FAILURE_CODE}",
        )
        state = (
            "preserved_unparsed"
            if _PST_MIME_METADATA_FAILURE_CODE in _PST_SEMANTIC_UNAVAILABILITY_CODES
            else "failed"
        )
        return _AttachmentClassification(
            processing_state=state,
            text_extraction_state="failed",
            payload=None,
            text=None,
            extracted_text_segments=[],
            failure_code=_PST_MIME_METADATA_FAILURE_CODE,
        )
    if metadata.content_type == "message/rfc822":
        return _classify_embedded_message_part(
            part,
            config=config,
            warnings=warnings,
            embedded_message_depth=embedded_message_depth,
        )
    payload, failure_code = _decode_attachment_payload(part, warnings=warnings)
    if failure_code is not None:
        _append_warning_once(warnings, f"pst_parser_attachment_{failure_code}")
        raw_payload, _ = _mime_raw_payload(part)
        retained_payload = raw_payload if isinstance(raw_payload, bytes) else None
        state = (
            "preserved_unparsed" if failure_code in _PST_SEMANTIC_UNAVAILABILITY_CODES else "failed"
        )
        return _AttachmentClassification(
            processing_state=state,
            text_extraction_state="failed",
            payload=retained_payload,
            text=None,
            extracted_text_segments=[],
            failure_code=failure_code,
        )
    assert payload is not None
    if not _attachment_mime_supported(metadata.content_type):
        return _AttachmentClassification(
            processing_state="unsupported",
            text_extraction_state="unsupported",
            payload=payload,
            text=None,
            extracted_text_segments=[],
        )
    if len(payload) > config.max_attachment_text_bytes:
        _append_warning_once(warnings, "pst_parser_attachment_text_limit_reached")
        return _AttachmentClassification(
            processing_state="preserved_unparsed",
            text_extraction_state="too_large",
            payload=payload,
            text=None,
            extracted_text_segments=[],
        )
    text, failure_code, recovered = _strict_body_charset_decode(part, payload)
    if failure_code is not None:
        _append_warning_once(warnings, f"pst_parser_attachment_{failure_code}")
        state = (
            "preserved_unparsed" if failure_code in _PST_SEMANTIC_UNAVAILABILITY_CODES else "failed"
        )
        return _AttachmentClassification(
            processing_state=state,
            text_extraction_state="failed",
            payload=payload,
            text=None,
            extracted_text_segments=[],
            failure_code=failure_code,
        )
    assert text is not None
    if recovered:
        _append_warning_once(warnings, "pst_parser_attachment_charset_recovered")
    if not text:
        return _AttachmentClassification(
            processing_state="parsed",
            text_extraction_state="complete",
            payload=payload,
            text=text,
            extracted_text_segments=[],
        )
    parsed, state, _ = _safe_body_segments(
        text,
        max_chars=config.body_segment_max_chars,
        max_segments=None,
        preserve_private_text=config.preserve_private_body_text,
        warnings=warnings,
    )
    return _AttachmentClassification(
        processing_state="parsed",
        text_extraction_state=state,
        payload=payload,
        text=text,
        extracted_text_segments=[segment.text for segment in parsed],
    )


def _classify_embedded_message_part(
    part: EmailMessage,
    *,
    config: _PstParserConfig,
    warnings: list[str],
    embedded_message_depth: int,
) -> _AttachmentClassification:
    if embedded_message_depth >= _PST_MAX_EMBEDDED_MESSAGE_DEPTH:
        failure_code = "embedded_message_nesting_limit"
        _append_warning_once(warnings, f"pst_parser_attachment_{failure_code}")
        return _AttachmentClassification(
            processing_state="failed",
            text_extraction_state="failed",
            payload=None,
            text=None,
            extracted_text_segments=[],
            failure_code=failure_code,
        )
    raw_payload, recovered_access = _mime_raw_payload(part)
    if raw_payload is _PST_TRAVERSAL_BINDING_MISSING:
        return _failed_embedded_message_classification(
            "embedded_message_parse_failed",
            warnings=warnings,
        )
    if recovered_access:
        _append_warning_once(warnings, "pst_parser_attachment_content_access_recovered")
    try:
        transfer_encoding = str(part.get("Content-Transfer-Encoding") or "").strip().lower()
    except Exception:
        return _failed_embedded_message_classification(
            "embedded_message_parse_failed",
            warnings=warnings,
        )
    if isinstance(raw_payload, (list, tuple, EmailMessage)):
        if transfer_encoding not in {"", "7bit", "8bit", "binary"}:
            return _failed_embedded_message_classification(
                "embedded_message_transfer_decode_failed",
                warnings=warnings,
            )
        children = (raw_payload,) if isinstance(raw_payload, EmailMessage) else tuple(raw_payload)
        if len(children) != 1 or not isinstance(children[0], EmailMessage):
            return _failed_embedded_message_classification(
                "embedded_message_parse_failed",
                warnings=warnings,
            )
        child = children[0]
        if not _is_mail_message(child):
            return _failed_embedded_message_classification(
                "embedded_message_parse_failed",
                warnings=warnings,
            )
        try:
            serialized_child = child.as_bytes(policy=policy.default)
        except Exception:
            return _failed_embedded_message_classification(
                "embedded_message_serialize_failed",
                warnings=warnings,
            )
    else:
        serialized_child, failure_code = _decode_attachment_payload(part, warnings=warnings)
        if failure_code is not None or serialized_child is None:
            return _failed_embedded_message_classification(
                "embedded_message_transfer_decode_failed"
                if failure_code == "transfer_decode_failed"
                else "embedded_message_parse_failed",
                warnings=warnings,
            )
        child = None
    if len(serialized_child) > config.max_attachment_text_bytes:
        _append_warning_once(warnings, "pst_parser_attachment_text_limit_reached")
        return _AttachmentClassification(
            processing_state="preserved_unparsed",
            text_extraction_state="too_large",
            payload=serialized_child,
            text=None,
            extracted_text_segments=[],
        )
    try:
        reparsed_child = BytesParser(policy=policy.default).parsebytes(serialized_child)
    except Exception:
        return _failed_embedded_message_classification(
            "embedded_message_parse_failed",
            warnings=warnings,
        )
    if not _is_mail_message(reparsed_child):
        return _failed_embedded_message_classification(
            "embedded_message_parse_failed",
            warnings=warnings,
        )
    defects = tuple(getattr(reparsed_child, "defects", ()))
    if child is not None:
        defects = (*getattr(child, "defects", ()), *defects)
    if _embedded_message_has_transfer_defect(defects):
        return _failed_embedded_message_classification(
            "embedded_message_transfer_decode_failed",
            warnings=warnings,
        )
    if defects:
        _append_warning_once(warnings, "pst_parser_embedded_message_recoverable_defect")
    return _AttachmentClassification(
        processing_state="parsed",
        text_extraction_state="not_text",
        payload=serialized_child,
        text=None,
        extracted_text_segments=[],
        embedded_message=reparsed_child,
    )


def _failed_embedded_message_classification(
    failure_code: str,
    *,
    warnings: list[str],
    payload: bytes | None = None,
) -> _AttachmentClassification:
    _append_warning_once(warnings, f"pst_parser_attachment_{failure_code}")
    state = "preserved_unparsed" if failure_code in _PST_SEMANTIC_UNAVAILABILITY_CODES else "failed"
    return _AttachmentClassification(
        processing_state=state,
        text_extraction_state="failed",
        payload=payload,
        text=None,
        extracted_text_segments=[],
        failure_code=failure_code,
    )


def _embedded_message_has_transfer_defect(defects: Sequence[Any]) -> bool:
    return any(
        "base64" in type(defect).__name__.casefold()
        or "transfer" in type(defect).__name__.casefold()
        for defect in defects
    )


def _decode_attachment_payload(
    part: EmailMessage,
    *,
    warnings: list[str],
) -> tuple[bytes | None, str | None]:
    raw_payload, recovered_access = _mime_raw_payload(part)
    if raw_payload is _PST_TRAVERSAL_BINDING_MISSING:
        return None, "content_decode_failed"
    if recovered_access:
        _append_warning_once(warnings, "pst_parser_attachment_content_access_recovered")
    if isinstance(raw_payload, list):
        return None, "transfer_decode_failed"
    if raw_payload is None:
        return None, "payload_missing"
    if isinstance(raw_payload, bytes):
        try:
            raw_text = raw_payload.decode("ascii")
        except UnicodeDecodeError:
            raw_text = None
    elif isinstance(raw_payload, str):
        raw_text = raw_payload
    else:
        return None, "transfer_decode_failed"
    try:
        transfer_encoding = str(part.get("Content-Transfer-Encoding") or "").strip().lower()
    except Exception:
        return None, "content_decode_failed"
    try:
        if transfer_encoding == "base64":
            if raw_text is None:
                return None, "transfer_decode_failed"
            compact = re.sub(r"\s+", "", raw_text)
            payload = base64.b64decode(compact, validate=True)
        elif transfer_encoding == "quoted-printable":
            if raw_text is None:
                return None, "transfer_decode_failed"
            if re.search(r"=(?![0-9A-Fa-f]{2}|\r?\n)", raw_text):
                raise ValueError("invalid quoted-printable escape")
            payload = quopri.decodestring(raw_text)
        elif transfer_encoding in {"", "7bit", "8bit", "binary"}:
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                payload = None
            if not isinstance(payload, bytes):
                if isinstance(raw_payload, bytes):
                    payload = raw_payload
                else:
                    payload = raw_payload.encode("utf-8", "surrogateescape")
            if transfer_encoding == "7bit" and any(byte > 0x7F for byte in payload):
                return None, "transfer_decode_failed"
        else:
            return None, "transfer_decode_failed"
    except (ValueError, binascii.Error, UnicodeEncodeError):
        return None, "transfer_decode_failed"
    if not isinstance(payload, bytes):
        return None, "transfer_decode_failed"
    return payload, None


def _mail_observations_from_messages(
    messages: Sequence[_ParsedMessage],
    *,
    extraction_input: ExtractionInput,
    source_inventory: SourceInventory | None = None,
) -> list[Observation]:
    created_at = extraction_input.created_at or now_iso()
    archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {
            "asset_id": extraction_input.asset.asset_id,
            "archive_sha256": extraction_input.asset.content_hash,
        },
    )
    mailbox_id = stable_resource_contract_id(
        "mailbox",
        "PstMailbox",
        {"asset_id": extraction_input.asset.asset_id},
    )
    contexts = _mail_message_contexts(
        messages,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
    )
    parsed_observations = list(
        _iter_mail_observations(
            contexts,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
            source_inventory=source_inventory,
        )
    )
    observations: list[Observation] = []
    for parsed in parsed_observations:
        observation_id = stable_observation_id(
            asset_id=extraction_input.asset.asset_id,
            extractor_run_id=extraction_input.extractor_run_id,
            observation_type=parsed["observation_type"],
            modality="mail",
            location=parsed["location"],
            text=parsed.get("text"),
            payload=parsed["payload"],
        )
        observations.append(
            Observation(
                observation_id=observation_id,
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type=parsed["observation_type"],
                modality="mail",
                text=parsed.get("text"),
                location=parsed["location"],
                confidence=1.0,
                permission_scope=extraction_input.asset.permission_scope,
                created_at=created_at,
                payload=parsed["payload"],
            )
        )
    return observations


def _mail_message_contexts(
    messages: Sequence[_ParsedMessage],
    *,
    archive_id: str,
    mailbox_id: str,
) -> tuple[_MailMessageContext, ...]:
    contexts: list[_MailMessageContext] = []
    top_level_duplicates: dict[tuple[str, str, str], int] = {}
    child_duplicates: dict[tuple[str, str, str], int] = {}

    def visit(
        message: _ParsedMessage,
        *,
        parent: _MailMessageContext | None,
    ) -> None:
        message_fingerprint = _message_fingerprint(message)
        parent_attachment_id = None
        if parent is not None and message.embedded_attachment_ordinal is not None:
            parent_attachment = parent.message.attachments[message.embedded_attachment_ordinal - 1]
            parent_attachment_id = parent_attachment.attachment_id
        if parent is None:
            duplicate_key = (
                message.folder_path_hash,
                message.message_id,
                message_fingerprint,
            )
            duplicate_ordinal = top_level_duplicates.get(duplicate_key, 0) + 1
            top_level_duplicates[duplicate_key] = duplicate_ordinal
        else:
            duplicate_key = (
                parent.occurrence_id,
                message.message_id,
                message_fingerprint,
            )
            duplicate_ordinal = child_duplicates.get(duplicate_key, 0) + 1
            child_duplicates[duplicate_key] = duplicate_ordinal
        occurrence_id = _pst_message_occurrence_id(
            message,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
            message_fingerprint=message_fingerprint,
            duplicate_ordinal=duplicate_ordinal,
            parent_occurrence_id=parent.occurrence_id if parent is not None else None,
            parent_attachment_id=parent_attachment_id,
        )
        occurrence_lineage = (
            (occurrence_id,) if parent is None else (*parent.occurrence_lineage, occurrence_id)
        )
        context = _MailMessageContext(
            message=message,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
            message_fingerprint=message_fingerprint,
            occurrence_id=occurrence_id,
            occurrence_lineage=occurrence_lineage,
            duplicate_ordinal=duplicate_ordinal,
            parent_occurrence_id=parent.occurrence_id if parent is not None else None,
            parent_attachment_id=parent_attachment_id,
        )
        contexts.append(context)
        for child in message.embedded_messages:
            visit(child, parent=context)

    for message in messages:
        visit(message, parent=None)
    return tuple(contexts)


def _pst_message_occurrence_id(
    message: _ParsedMessage,
    *,
    archive_id: str,
    mailbox_id: str,
    message_fingerprint: str,
    duplicate_ordinal: int,
    parent_occurrence_id: str | None = None,
    parent_attachment_id: str | None = None,
) -> str:
    return _pst_message_occurrence_id_from_fields(
        archive_id=archive_id,
        mailbox_id=mailbox_id,
        folder_path_hash=message.folder_path_hash,
        message_id=message.message_id,
        message_fingerprint=message_fingerprint,
        duplicate_ordinal=duplicate_ordinal,
        parent_occurrence_id=parent_occurrence_id,
        parent_attachment_id=parent_attachment_id,
        embedded_attachment_ordinal=message.embedded_attachment_ordinal,
    )


def _pst_message_occurrence_id_from_fields(
    *,
    archive_id: str,
    mailbox_id: str,
    folder_path_hash: str,
    message_id: str,
    message_fingerprint: str,
    duplicate_ordinal: int,
    parent_occurrence_id: str | None = None,
    parent_attachment_id: str | None = None,
    embedded_attachment_ordinal: int | None = None,
) -> str:
    if parent_occurrence_id is None:
        identity = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": folder_path_hash,
            "message_id": message_id,
            "message_fingerprint": message_fingerprint,
            "duplicate_ordinal": duplicate_ordinal,
        }
    else:
        identity = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "parent_occurrence_id": parent_occurrence_id,
            "parent_attachment_id": parent_attachment_id,
            "embedded_attachment_ordinal": embedded_attachment_ordinal,
            "message_id": message_id,
            "message_fingerprint": message_fingerprint,
            "duplicate_ordinal": duplicate_ordinal,
        }
    return stable_resource_contract_id("mailocc", "PstMessageOccurrence", identity)


def _pst_top_level_message_occurrence_ids(
    messages: Sequence[_ParsedMessage],
    *,
    extraction_input: ExtractionInput,
) -> dict[str, str]:
    """Bind each parsed top-level source key to its physical mail occurrence."""

    archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {
            "asset_id": extraction_input.asset.asset_id,
            "archive_sha256": extraction_input.asset.content_hash,
        },
    )
    mailbox_id = stable_resource_contract_id(
        "mailbox",
        "PstMailbox",
        {"asset_id": extraction_input.asset.asset_id},
    )
    bindings: dict[str, str] = {}
    for context in _mail_message_contexts(
        messages,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
    ):
        if context.parent_occurrence_id is not None:
            continue
        source_local_key = context.message.source_local_key
        if (
            not isinstance(source_local_key, str)
            or not source_local_key
            or source_local_key in bindings
        ):
            raise ContractValidationError("PST top-level message occurrence binding is invalid")
        bindings[source_local_key] = context.occurrence_id
    return bindings


def _pst_inventory_parent_message_key(
    item: SourceInventoryItem,
    *,
    item_by_key: Mapping[str, SourceInventoryItem],
) -> str:
    current = item
    seen: set[str] = set()
    while True:
        key = current.location.get("source_local_key")
        if not isinstance(key, str) or not key:
            raise ContractValidationError("PST attachment inventory key is invalid")
        if key in seen:
            raise ContractValidationError("PST attachment inventory parent topology is cyclic")
        seen.add(key)
        if current.structure_kind in {"exported_message_occurrence", "attached_message_occurrence"}:
            return key
        parent_key = current.location.get("parent_source_local_key")
        if not isinstance(parent_key, str) or not parent_key:
            raise ContractValidationError("PST attachment inventory message parent is missing")
        current = item_by_key.get(parent_key)
        if current is None:
            raise ContractValidationError("PST attachment inventory parent is missing")


def _pst_structural_message_item(
    item: SourceInventoryItem,
    *,
    item_by_key: Mapping[str, SourceInventoryItem],
) -> SourceInventoryItem:
    current = item
    seen: set[str] = set()
    while current.structure_kind not in {
        "exported_message_occurrence",
        "attached_message_occurrence",
    }:
        key = current.location.get("source_local_key")
        if not isinstance(key, str) or not key or key in seen:
            raise ContractValidationError("PST structural message ancestry is invalid")
        seen.add(key)
        parent_key = current.location.get("parent_source_local_key")
        if not isinstance(parent_key, str) or not parent_key:
            raise ContractValidationError("PST structural message ancestry is missing")
        current = item_by_key.get(parent_key)
        if current is None:
            raise ContractValidationError("PST structural message ancestry is missing")
    return current


def _pst_structural_message_lineage(
    item: SourceInventoryItem,
    *,
    item_by_key: Mapping[str, SourceInventoryItem],
) -> tuple[str, ...]:
    key = item.location.get("source_local_key")
    if not isinstance(key, str) or not key:
        raise ContractValidationError("PST structural message key is invalid")
    if item.structure_kind == "exported_message_occurrence":
        return (key,)
    if item.structure_kind != "attached_message_occurrence":
        raise ContractValidationError("PST structural message item is invalid")
    parent_attachment_key = item.location.get("parent_source_local_key")
    if not isinstance(parent_attachment_key, str) or not parent_attachment_key:
        raise ContractValidationError("PST embedded message ancestry is missing")
    parent_attachment = item_by_key.get(parent_attachment_key)
    if parent_attachment is None:
        raise ContractValidationError("PST embedded message ancestry is missing")
    parent_message = _pst_structural_message_item(
        parent_attachment,
        item_by_key=item_by_key,
    )
    return (
        *_pst_structural_message_lineage(parent_message, item_by_key=item_by_key),
        parent_attachment_key,
        key,
    )


def _pst_structural_message_contexts(
    inventory: SourceInventory,
    *,
    contexts: Sequence[_MailMessageContext],
) -> dict[str, tuple[SourceInventoryItem, _MailMessageContext, tuple[str, ...]]]:
    item_by_key = {
        str(item.location["source_local_key"]): item
        for item in inventory.items
        if isinstance(item.location.get("source_local_key"), str)
    }
    context_by_message_key: dict[str, _MailMessageContext] = {}
    top_level_contexts_by_source_key: dict[str, list[_MailMessageContext]] = {}
    embedded_contexts_by_binding: dict[
        tuple[str | None, str | None, int | None],
        list[_MailMessageContext],
    ] = {}
    for context in contexts:
        if context.parent_occurrence_id is None:
            source_local_key = context.message.source_local_key
            if isinstance(source_local_key, str):
                top_level_contexts_by_source_key.setdefault(source_local_key, []).append(context)
            continue
        binding = (
            context.parent_occurrence_id,
            context.parent_attachment_id,
            context.message.embedded_attachment_ordinal,
        )
        embedded_contexts_by_binding.setdefault(binding, []).append(context)
    resolving: set[str] = set()

    def resolve(message_key: str) -> _MailMessageContext:
        cached = context_by_message_key.get(message_key)
        if cached is not None:
            return cached
        if message_key in resolving:
            raise ContractValidationError("PST structural message ancestry is cyclic")
        item = item_by_key.get(message_key)
        if item is None or item.structure_kind not in {
            "exported_message_occurrence",
            "attached_message_occurrence",
        }:
            raise ContractValidationError("PST structural message inventory binding is invalid")
        resolving.add(message_key)
        if item.structure_kind == "exported_message_occurrence":
            source_local_key = item.location.get("parent_source_local_key")
            if not isinstance(source_local_key, str) or not source_local_key:
                raise ContractValidationError("PST top-level message inventory binding is invalid")
            candidates = top_level_contexts_by_source_key.get(source_local_key, [])
        else:
            parent_attachment_key = item.location.get("parent_source_local_key")
            parent_attachment = item_by_key.get(str(parent_attachment_key))
            if parent_attachment is None:
                raise ContractValidationError("PST embedded message inventory binding is invalid")
            parent_message = _pst_structural_message_item(
                parent_attachment,
                item_by_key=item_by_key,
            )
            parent_context = resolve(str(parent_message.location["source_local_key"]))
            attachment_id = parent_attachment.location.get("attachment_id")
            attachment_ordinal = _pst_exact_int(
                parent_attachment.location.get("attachment_ordinal"),
                "embedded parent attachment ordinal",
                minimum=1,
            )
            candidates = embedded_contexts_by_binding.get(
                (parent_context.occurrence_id, attachment_id, attachment_ordinal),
                [],
            )
        resolving.remove(message_key)
        if len(candidates) != 1:
            raise ContractValidationError("PST structural message context is not unique")
        context_by_message_key[message_key] = candidates[0]
        return candidates[0]

    result = {}
    for item in inventory.items:
        if item.structure_kind not in {
            "exported_message_occurrence",
            "attached_message_occurrence",
        }:
            continue
        key = str(item.location["source_local_key"])
        result[key] = (
            item,
            resolve(key),
            _pst_structural_message_lineage(item, item_by_key=item_by_key),
        )
    return result


def _pst_attachment_inventory_index(
    source_inventory: SourceInventory,
    *,
    contexts: Sequence[_MailMessageContext] = (),
) -> _PstAttachmentInventoryIndex:
    item_by_key: dict[str, SourceInventoryItem] = {}
    attachment_items: list[SourceInventoryItem] = []
    attachment_items_by_id: dict[Any, list[SourceInventoryItem]] = {}
    attachment_items_by_id_and_ordinal: dict[
        tuple[Any, Any],
        list[SourceInventoryItem],
    ] = {}
    attachment_items_by_parent_message_key: dict[str, list[SourceInventoryItem]] = {}
    attachment_kinds = {"regular_attachment_occurrence", "inline_attachment_occurrence"}

    for item in source_inventory.items:
        source_local_key = item.location.get("source_local_key")
        if isinstance(source_local_key, str):
            item_by_key[str(item.location["source_local_key"])] = item
        if item.structure_kind not in attachment_kinds:
            continue
        attachment_items.append(item)
        attachment_id = item.location.get("attachment_id")
        try:
            hash(attachment_id)
        except TypeError:
            continue
        attachment_items_by_id.setdefault(attachment_id, []).append(item)
        attachment_ordinal = item.location.get("attachment_ordinal")
        try:
            hash(attachment_ordinal)
        except TypeError:
            continue
        attachment_items_by_id_and_ordinal.setdefault(
            (attachment_id, attachment_ordinal),
            [],
        ).append(item)

    for item in attachment_items:
        parent_message_key = _pst_inventory_parent_message_key(item, item_by_key=item_by_key)
        attachment_items_by_parent_message_key.setdefault(parent_message_key, []).append(item)

    message_key_by_occurrence_id: dict[str, str] = {}
    if contexts:
        for message_key, (_, context, _) in _pst_structural_message_contexts(
            source_inventory,
            contexts=contexts,
        ).items():
            existing = message_key_by_occurrence_id.setdefault(
                context.occurrence_id,
                message_key,
            )
            if existing != message_key:
                raise ContractValidationError(
                    "PST structural message occurrence context is not unique"
                )

    return _PstAttachmentInventoryIndex(
        item_by_key=item_by_key,
        attachment_items=tuple(attachment_items),
        attachment_items_by_id={key: tuple(items) for key, items in attachment_items_by_id.items()},
        attachment_items_by_id_and_ordinal={
            key: tuple(items) for key, items in attachment_items_by_id_and_ordinal.items()
        },
        attachment_items_by_parent_message_key={
            key: tuple(items) for key, items in attachment_items_by_parent_message_key.items()
        },
        message_key_by_occurrence_id=message_key_by_occurrence_id,
    )


def _pst_attachment_observation_binding(
    attachment: _ParsedAttachment,
    *,
    attachment_ordinal: int,
    context: _MailMessageContext,
    source_inventory: SourceInventory | None,
    inventory_index: _PstAttachmentInventoryIndex | None = None,
) -> dict[str, Any]:
    if source_inventory is None:
        return {}
    if inventory_index is None:
        inventory_index = _pst_attachment_inventory_index(
            source_inventory,
            contexts=(context,),
        )
    item_by_key = inventory_index.item_by_key
    parent_message_key = inventory_index.message_key_by_occurrence_id.get(context.occurrence_id)
    if parent_message_key is None:
        raise ContractValidationError("PST attachment parent occurrence context is missing")
    parent_candidates = inventory_index.attachment_items_by_parent_message_key.get(
        parent_message_key,
        (),
    )
    candidates = [
        item
        for item in parent_candidates
        if item.location.get("attachment_id") == attachment.attachment_id
        and item.location.get("attachment_ordinal") == attachment_ordinal
    ]
    source_item: SourceInventoryItem | None = None
    source_key: str | None = None
    if attachment.source_kind == "readpst_sidecar":
        source_key = attachment.source_local_key
        if not isinstance(source_key, str) or not source_key:
            raise ContractValidationError("PST sidecar attachment source key is missing")
        source_item = item_by_key.get(source_key)
        if source_item is None or source_item.structure_kind != "exported_file":
            raise ContractValidationError("PST sidecar attachment source inventory is missing")
        linked_id = source_item.location.get("source_unit_linked_attachment_id")
        if linked_id is not None:
            candidates = [
                item
                for item in parent_candidates
                if item.location.get("attachment_id") == linked_id
                and item.location.get("attachment_ordinal") == attachment_ordinal
            ]
        else:
            occurrence_key = f"{source_key}:attachment"
            candidates = [item_by_key[occurrence_key]] if occurrence_key in item_by_key else []
            candidates = [
                item
                for item in candidates
                if _pst_inventory_parent_message_key(item, item_by_key=item_by_key)
                == parent_message_key
            ]

    if len(candidates) != 1:
        raise ContractValidationError("PST attachment inventory occurrence is not unique")
    item = candidates[0]
    item_key = str(item.location["source_local_key"])
    if _pst_inventory_parent_message_key(item, item_by_key=item_by_key) != parent_message_key:
        raise ContractValidationError("PST attachment inventory parent message is invalid")
    if source_item is None:
        source_item = item
        source_key = item_key
    source_location = source_item.location
    source_media_type = source_location.get(
        "source_unit_attachment_media_type",
        item.content_type,
    )
    source_processing_state = source_location.get(
        "source_unit_attachment_processing_state",
        item.processing_state,
    )
    source_failure_code = source_location.get(
        "source_unit_attachment_failure_code",
        item.location.get("attachment_failure_code"),
    )
    source_content_fingerprint = source_location.get(
        "source_unit_content_fingerprint",
        item.location.get("attachment_content_fingerprint"),
    )
    source_size_bytes = source_location.get(
        "source_unit_size_bytes",
        item.location.get("attachment_size_bytes"),
    )
    source_byte_count = source_location.get(
        "source_unit_size_bytes",
        item.location.get("attachment_source_byte_count"),
    )
    source_stored_byte_count = source_location.get(
        "source_unit_attachment_stored_byte_count",
        item.location.get("attachment_stored_byte_count"),
    )
    source_name_fingerprint = source_location.get(
        "source_unit_attachment_name_fingerprint",
        item.location.get("attachment_name_fingerprint"),
    )
    return {
        "attachment_inventory_item_id": item.source_inventory_item_id,
        "attachment_inventory_source_local_key": item_key,
        "attachment_source_inventory_item_id": source_item.source_inventory_item_id,
        "attachment_source_inventory_source_local_key": source_key,
        "attachment_parent_message_source_local_key": parent_message_key,
        "attachment_source_media_type": source_media_type,
        "attachment_source_processing_state": source_processing_state,
        "attachment_source_failure_code": source_failure_code,
        "attachment_source_content_fingerprint": source_content_fingerprint,
        "attachment_source_size_bytes": source_size_bytes,
        "attachment_source_byte_count": source_byte_count,
        "attachment_source_stored_byte_count": source_stored_byte_count,
        "attachment_source_name_fingerprint": source_name_fingerprint,
    }


def _iter_mail_observations(
    contexts: Sequence[_MailMessageContext],
    *,
    archive_id: str,
    mailbox_id: str,
    source_inventory: SourceInventory | None = None,
) -> Iterable[dict[str, Any]]:
    contexts = _pst_canonical_message_context_order(
        contexts,
        source_inventory=source_inventory,
    )
    messages = [context.message for context in contexts]
    top_level_message_inventory = (
        _pst_top_level_message_inventory_bindings(source_inventory)
        if source_inventory is not None
        else {}
    )
    attachment_inventory_index = (
        _pst_attachment_inventory_index(source_inventory, contexts=contexts)
        if source_inventory is not None
        else None
    )
    folder_labels: dict[str, str] = {}
    for message in messages:
        folder_labels.setdefault(message.folder_path_hash, message.folder_label)
    folder_indices = _pst_canonical_index_map(folder_labels)
    for folder_path_hash in sorted(folder_labels):
        folder_label = folder_labels[folder_path_hash]
        folder_index = folder_indices[folder_path_hash]
        yield {
            "observation_type": "mail_folder_occurrence",
            "text": folder_label,
            "location": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_index": folder_index,
            },
            "payload": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_label": folder_label,
            },
        }

    (
        thread_payloads,
        thread_ids_by_occurrence,
        reply_resolutions_by_occurrence,
    ) = _thread_payloads(
        contexts,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
    )
    thread_indices = _pst_canonical_index_map(
        {str(payload["thread_id"]): payload for payload in thread_payloads}
    )
    for payload in thread_payloads:
        thread_index = thread_indices[str(payload["thread_id"])]
        yield {
            "observation_type": "email_thread",
            "text": payload["normalized_subject"],
            "location": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "thread_id": payload["thread_id"],
                "thread_index": thread_index,
            },
            "payload": payload,
        }

    for message_index, context in enumerate(contexts, start=1):
        message = context.message
        thread_id = thread_ids_by_occurrence[context.occurrence_id]
        message_fingerprint = _message_fingerprint(message)
        occurrence_id = context.occurrence_id
        duplicate_ordinal = context.duplicate_ordinal
        occurrence_lineage = (
            {"occurrence_lineage": list(context.occurrence_lineage)}
            if len(context.occurrence_lineage) > 1
            else {}
        )
        embedded_relation = (
            {
                "parent_message_occurrence_id": context.parent_occurrence_id,
                "parent_attachment_id": context.parent_attachment_id,
                "embedded_attachment_ordinal": message.embedded_attachment_ordinal,
            }
            if context.parent_occurrence_id is not None
            else {}
        )
        source_binding: dict[str, Any] = {}
        if context.parent_occurrence_id is None and message.source_local_key is not None:
            source_binding["message_source_local_key"] = message.source_local_key
            if source_inventory is not None:
                inventory_item = top_level_message_inventory.get(message.source_local_key)
                if (
                    inventory_item is None
                    or inventory_item.location.get("message_occurrence_id") != occurrence_id
                ):
                    raise ContractValidationError(
                        "PST top-level message occurrence binding is invalid"
                    )
                source_binding["message_source_inventory_item_id"] = (
                    inventory_item.source_inventory_item_id
                )
        base_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": message.folder_path_hash,
            "message_id": message.message_id,
            "message_occurrence_id": occurrence_id,
            "thread_id": thread_id,
            **occurrence_lineage,
            **embedded_relation,
        }
        yield {
            "observation_type": "email_message",
            "text": message.subject,
            "location": {**base_location, "message_index": message_index},
            "payload": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "message_id": message.message_id,
                "message_occurrence_id": occurrence_id,
                **occurrence_lineage,
                **source_binding,
                **embedded_relation,
                "message_occurrence_identity_policy": ("formowl_pst_message_occurrence_content_v2"),
                "duplicate_ordinal": duplicate_ordinal,
                "thread_id": thread_id,
                "subject": message.subject,
                "normalized_subject": message.normalized_subject,
                "sender": message.sender,
                "sent_at": message.sent_at,
                "date_state": message.chronology.date_state,
                "chronology": message.chronology.to_payload(),
                "body_hash": message.body_hash,
                "source_body_char_count": message.source_body_char_count,
                "stored_body_char_count": message.stored_body_char_count,
                "body_segment_count": len(message.body_segments),
                "body_evidence_state": message.body_evidence_state,
                "body_projection_policy": _PST_BODY_PROJECTION_POLICY,
                "body_projection_state": message.body_projection_state,
                "body_projection_fingerprint": message.body_projection_fingerprint,
                "header_projection_policy": _PST_HEADER_PROJECTION_POLICY,
                "header_projection_count": message.header_projection_count,
                "header_projection_fingerprint": message.header_projection_fingerprint,
                "body_failure_codes": list(message.body_failure_codes),
                "body_redacted_segment_count": message.body_redacted_segment_count,
                "unresolved_attachment_count": message.unresolved_attachment_count,
                "reply_headers": [header.to_payload() for header in message.reply_headers],
                "reply_resolutions": [
                    resolution.to_payload()
                    for resolution in reply_resolutions_by_occurrence[occurrence_id]
                ],
                "reply_resolution_policy": _PST_REPLY_RESOLUTION_POLICY,
                "reply_resolution_fingerprint": _reply_resolution_fingerprint(
                    [
                        resolution.to_payload()
                        for resolution in reply_resolutions_by_occurrence[occurrence_id]
                    ]
                ),
                "message_fingerprint": message_fingerprint,
                "fingerprint_policy": _PST_MESSAGE_FINGERPRINT_POLICY,
            },
        }
        for header_projection_index, header in enumerate(message.headers, start=1):
            chronology = header.chronology
            if chronology is not None:
                header_text = (
                    f"{header.header_name}: "
                    f"[{chronology.parse_status}/{chronology.timezone_status}]"
                )
                chronology_payload = chronology.to_payload()
                chronology_payload["header_ordinal"] = header.header_ordinal
                header_payload = {
                    "raw_value_fingerprint": chronology.raw_value_fingerprint,
                    "header_variant": "chronology",
                    "chronology": chronology_payload,
                }
            elif header.reply is not None:
                header_text = (
                    f"{header.header_name}: "
                    f"[{header.reply.parse_status}/{header.reply.token_count}]"
                )
                header_resolution_payload = [
                    resolution.to_payload()
                    for resolution in reply_resolutions_by_occurrence[occurrence_id]
                    if resolution.header_kind
                    == {
                        "message-id": "message_id",
                        "references": "references",
                        "in-reply-to": "in_reply_to",
                    }.get(header.header_name)
                    and resolution.header_ordinal == header.header_ordinal
                    and resolution.occurrence_ordinal == header.reply.occurrence_ordinal
                ]
                header_payload = {
                    "raw_value_fingerprint": header.reply.raw_value_fingerprint,
                    "header_variant": "reply",
                    "reply": header.reply.to_payload(),
                    "reply_resolution_fingerprint": _reply_resolution_fingerprint(
                        header_resolution_payload
                    ),
                }
            else:
                header_text = f"{header.header_name}: {header.header_value or ''}"
                header_payload = {
                    "header_variant": "ordinary",
                    "header_value": header.header_value,
                    "raw_value_fingerprint": header.raw_value_fingerprint,
                }
            yield {
                "observation_type": "email_header",
                "text": header_text,
                "location": {
                    **base_location,
                    "header_index": header.header_ordinal,
                    "header_name": header.header_name,
                    "header_projection_index": header_projection_index,
                    "header_projection_count": message.header_projection_count,
                    "header_projection_policy": _PST_HEADER_PROJECTION_POLICY,
                    "header_projection_fingerprint": message.header_projection_fingerprint,
                    "chronology_physical_ordinal": (
                        chronology.physical_ordinal if chronology is not None else None
                    ),
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    **occurrence_lineage,
                    **embedded_relation,
                    "message_occurrence_identity_policy": (
                        "formowl_pst_message_occurrence_content_v2"
                    ),
                    "duplicate_ordinal": duplicate_ordinal,
                    "thread_id": thread_id,
                    "header_name": header.header_name,
                    "header_ordinal": header.header_ordinal,
                    "header_projection_policy": _PST_HEADER_PROJECTION_POLICY,
                    "header_projection_count": message.header_projection_count,
                    "header_projection_index": header_projection_index,
                    "header_projection_fingerprint": message.header_projection_fingerprint,
                    **header_payload,
                    "message_fingerprint": message_fingerprint,
                },
            }
        for segment_index, body_segment in enumerate(message.body_segments, start=1):
            yield {
                "observation_type": "email_body_segment",
                "text": body_segment.text,
                "location": {
                    **base_location,
                    "body_segment_index": segment_index,
                    "char_start": body_segment.char_start,
                    "char_end": body_segment.char_end,
                    "body_projection_policy": _PST_BODY_PROJECTION_POLICY,
                    "body_projection_fingerprint": message.body_projection_fingerprint,
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    **occurrence_lineage,
                    **embedded_relation,
                    "message_occurrence_identity_policy": (
                        "formowl_pst_message_occurrence_content_v2"
                    ),
                    "duplicate_ordinal": duplicate_ordinal,
                    "thread_id": thread_id,
                    "body_segment_index": segment_index,
                    "body_segment_count": len(message.body_segments),
                    "body_hash": message.body_hash,
                    "source_body_char_count": message.source_body_char_count,
                    "stored_body_char_count": message.stored_body_char_count,
                    "body_evidence_state": message.body_evidence_state,
                    "body_projection_policy": _PST_BODY_PROJECTION_POLICY,
                    "body_projection_state": message.body_projection_state,
                    "body_projection_fingerprint": message.body_projection_fingerprint,
                    "body_failure_codes": list(message.body_failure_codes),
                    "body_redacted_segment_count": message.body_redacted_segment_count,
                    "content_publicly_unsafe": body_segment.content_publicly_unsafe,
                    "message_fingerprint": message_fingerprint,
                },
            }
        for attachment_index, attachment in enumerate(message.attachments, start=1):
            attachment_binding = _pst_attachment_observation_binding(
                attachment,
                attachment_ordinal=attachment_index,
                context=context,
                source_inventory=source_inventory,
                inventory_index=attachment_inventory_index,
            )
            attachment_source = (
                {
                    "attachment_source": attachment.source_kind,
                    "attachment_source_local_key": attachment.source_local_key,
                    "attachment_processing_state": attachment.processing_state,
                    "attachment_source_name_fingerprint": attachment.source_name_fingerprint,
                }
                if attachment.source_kind != "mime"
                else {}
            )
            yield {
                "observation_type": "email_attachment_occurrence",
                "text": attachment.filename,
                "location": {
                    **base_location,
                    "attachment_index": attachment_index,
                    "attachment_ordinal": attachment_index,
                    "attachment_id": attachment.attachment_id,
                    **attachment_source,
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    **occurrence_lineage,
                    **embedded_relation,
                    "message_occurrence_identity_policy": (
                        "formowl_pst_message_occurrence_content_v2"
                    ),
                    "duplicate_ordinal": duplicate_ordinal,
                    "thread_id": thread_id,
                    "attachment_id": attachment.attachment_id,
                    "attachment_index": attachment_index,
                    "attachment_ordinal": attachment_index,
                    "filename": attachment.filename,
                    "mime_type": attachment.mime_type,
                    "content_hash": attachment.content_hash,
                    "size_bytes": attachment.size_bytes,
                    "text_extraction_state": attachment.text_extraction_state,
                    "attachment_failure_code": attachment.failure_code,
                    **attachment_source,
                    "extracted_text_segment_count": len(attachment.extracted_text_segments),
                    **_parsed_attachment_identity_fields(attachment),
                    **attachment_binding,
                    "message_fingerprint": message_fingerprint,
                },
            }
            for attachment_text_index, attachment_text in enumerate(
                attachment.extracted_text_segments,
                start=1,
            ):
                yield {
                    "observation_type": "email_attachment_text_segment",
                    "text": attachment_text,
                    "location": {
                        **base_location,
                        "attachment_index": attachment_index,
                        "attachment_id": attachment.attachment_id,
                        "attachment_text_segment_index": attachment_text_index,
                    },
                    "payload": {
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message.message_id,
                        "message_occurrence_id": occurrence_id,
                        **occurrence_lineage,
                        **embedded_relation,
                        "message_occurrence_identity_policy": (
                            "formowl_pst_message_occurrence_content_v2"
                        ),
                        "duplicate_ordinal": duplicate_ordinal,
                        "thread_id": thread_id,
                        "attachment_id": attachment.attachment_id,
                        "attachment_index": attachment_index,
                        "attachment_ordinal": attachment_index,
                        "attachment_text_segment_index": attachment_text_index,
                        "attachment_text_segment_count": len(attachment.extracted_text_segments),
                        "text_extraction_state": attachment.text_extraction_state,
                        "attachment_failure_code": attachment.failure_code,
                        **attachment_source,
                        **_parsed_attachment_identity_fields(attachment),
                        **attachment_binding,
                        "attachment_text_segment_fingerprint": sha256_json(attachment_text),
                        "message_fingerprint": message_fingerprint,
                    },
                }


def _message_fingerprint(message: _ParsedMessage) -> str:
    attachment_hashes = sorted(
        attachment.content_hash for attachment in message.attachments if attachment.content_hash
    )
    sidecar_bindings = [
        {
            "source_local_key": attachment.source_local_key,
            "processing_state": attachment.processing_state,
            "failure_code": attachment.failure_code,
            "content_hash": attachment.content_hash,
            "size_bytes": attachment.size_bytes,
            "name_fingerprint": attachment.source_name_fingerprint,
        }
        for attachment in message.attachments
        if attachment.source_kind == "readpst_sidecar"
    ]
    sidecar_bindings.sort(key=sha256_json)
    return sha256_json(
        {
            "message_id": message.message_id,
            "fingerprint_policy": _PST_MESSAGE_FINGERPRINT_POLICY,
            "normalized_subject": message.normalized_subject,
            "sender": message.sender,
            "sent_at": message.sent_at,
            "chronology": message.chronology.to_payload(),
            "body_hash": message.body_hash,
            "body_projection_policy": _PST_BODY_PROJECTION_POLICY,
            "body_projection_state": message.body_projection_state,
            "body_projection_fingerprint": message.body_projection_fingerprint,
            "header_projection_policy": _PST_HEADER_PROJECTION_POLICY,
            "header_projection_count": message.header_projection_count,
            "header_projection_fingerprint": message.header_projection_fingerprint,
            "attachment_hashes": attachment_hashes,
            "sidecar_bindings": sidecar_bindings,
            "reply_headers": [occurrence.to_payload() for occurrence in message.reply_headers],
        }
    )


def _reply_resolution_fingerprint(
    resolution_payload: Sequence[Mapping[str, Any]],
) -> str:
    return sha256_json(
        {
            "policy": _PST_REPLY_RESOLUTION_POLICY,
            "resolutions": list(resolution_payload),
        }
    )


def _reply_resolution_groups_payload(
    members: Sequence[_MailMessageContext],
    resolutions_by_occurrence: Mapping[str, Sequence[_ReplyResolution]],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for member in sorted(members, key=lambda item: item.occurrence_id):
        resolutions = [
            resolution.to_payload()
            for resolution in resolutions_by_occurrence[member.occurrence_id]
        ]
        groups.append(
            {
                "message_occurrence_id": member.occurrence_id,
                "resolutions": resolutions,
                "resolution_fingerprint": _reply_resolution_fingerprint(resolutions),
            }
        )
    return groups


def _thread_payloads(
    contexts: Sequence[_MailMessageContext],
    *,
    archive_id: str,
    mailbox_id: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, str],
    dict[str, tuple[_ReplyResolution, ...]],
]:
    """Resolve reply ancestry without collapsing physical message contexts."""

    ordered_contexts = tuple(sorted(contexts, key=lambda item: item.occurrence_id))
    scope = {"archive_id": archive_id, "mailbox_id": mailbox_id}
    id_fingerprints: dict[str, str | None] = {}
    logical_keys: dict[str, str] = {}
    target_index: dict[tuple[str, str], dict[str, set[str]]] = {}

    for context in ordered_contexts:
        message_id_fingerprint, _ = _message_id_fingerprint(context.message)
        id_fingerprints[context.occurrence_id] = message_id_fingerprint
        logical_identity = {
            **scope,
            "message_id_fingerprint": message_id_fingerprint,
            "message_fingerprint": context.message_fingerprint,
        }
        if message_id_fingerprint is None:
            logical_identity["occurrence_id"] = context.occurrence_id
        logical_keys[context.occurrence_id] = stable_resource_contract_id(
            "mail-logical-message",
            "PstLogicalMessage",
            logical_identity,
        )
        if message_id_fingerprint is not None:
            target_index.setdefault(
                (archive_id, mailbox_id, message_id_fingerprint),
                {},
            ).setdefault(context.message_fingerprint, set()).add(context.occurrence_id)

    resolver_scope = (archive_id, mailbox_id)
    resolution_records_by_occurrence = {
        context.occurrence_id: _initial_reply_resolutions(
            context.message,
            resolver_scope=resolver_scope,
        )
        for context in ordered_contexts
    }
    candidate_states: dict[str, str] = {}
    candidate_edges: list[dict[str, Any]] = []
    target_details_by_occurrence: dict[str, dict[str, dict[str, Any]]] = {}
    for context in ordered_contexts:
        occurrence_id = context.occurrence_id
        reply_headers = context.message.reply_headers
        references = tuple(item for item in reply_headers if item.kind == "references")
        in_reply_to = tuple(item for item in reply_headers if item.kind == "in_reply_to")
        if not references and not in_reply_to:
            candidate_states[occurrence_id] = "none"
            continue
        if len(references) > 1 or len(in_reply_to) > 1:
            candidate_states[occurrence_id] = "ambiguous"
            continue
        if id_fingerprints[occurrence_id] is None:
            candidate_states[occurrence_id] = "unresolved"
            continue
        ancestry_headers = (*references, *in_reply_to)
        if any(item.parse_status != "parsed" for item in ancestry_headers):
            candidate_states[occurrence_id] = (
                "ambiguous"
                if any(item.parse_status in {"multiple", "overflow"} for item in ancestry_headers)
                else "unresolved"
            )
            continue
        if (
            references
            and in_reply_to
            and references[0].token_fingerprints[-1] != in_reply_to[0].token_fingerprints[0]
        ):
            candidate_states[occurrence_id] = "ambiguous"
            continue
        candidates: list[tuple[str, str, int]] = []
        for header in references:
            candidates.extend(
                (token_fingerprint, "references", header.occurrence_ordinal)
                for token_fingerprint in header.token_fingerprints
            )
        for header in in_reply_to:
            if len(header.token_fingerprints) != 1:
                candidate_states[occurrence_id] = "ambiguous"
                break
            candidates.append(
                (header.token_fingerprints[0], "in_reply_to", header.occurrence_ordinal)
            )
        if occurrence_id in candidate_states:
            continue
        target_logical_keys: dict[str, tuple[str, list[str]]] = {}
        target_details = target_details_by_occurrence.setdefault(occurrence_id, {})
        unresolved = False
        ambiguous = False
        for token_fingerprint, relation, header_ordinal in candidates:
            groups = target_index.get((archive_id, mailbox_id, token_fingerprint))
            if not groups:
                target_details[token_fingerprint] = {"status": "absent"}
                unresolved = True
                continue
            if len(groups) != 1:
                target_details[token_fingerprint] = {"status": "duplicate"}
                ambiguous = True
                continue
            target_message_fingerprints = tuple(groups)
            if len(target_message_fingerprints) != 1:
                target_details[token_fingerprint] = {"status": "duplicate"}
                ambiguous = True
                continue
            target_occurrences = groups[target_message_fingerprints[0]]
            target_logical_key_set = {
                logical_keys[target_occurrence] for target_occurrence in target_occurrences
            }
            if len(target_logical_key_set) != 1:
                target_details[token_fingerprint] = {"status": "duplicate"}
                ambiguous = True
                continue
            target_logical_key = next(iter(target_logical_key_set))
            target_status = (
                "self" if target_logical_key == logical_keys[occurrence_id] else "resolved"
            )
            candidates_for_edge = sorted(
                target_occurrence
                for target_occurrence in target_occurrences
                if logical_keys[target_occurrence] == target_logical_key
            )
            target_details[token_fingerprint] = {
                "status": target_status,
                "target_logical_message_key": target_logical_key,
                "target_occurrence_ids": candidates_for_edge,
            }
            target_logical_keys[token_fingerprint] = (
                target_logical_key,
                candidates_for_edge,
            )
        if unresolved:
            candidate_states[occurrence_id] = "unresolved"
        elif ambiguous:
            candidate_states[occurrence_id] = "ambiguous"
        else:
            candidate_states[occurrence_id] = "resolved"
            direct_header = (
                in_reply_to[0] if in_reply_to else (references[0] if references else None)
            )
            if direct_header is not None:
                direct_token_fingerprint = direct_header.token_fingerprints[-1]
                target_logical_key, target_occurrence_ids = target_logical_keys[
                    direct_token_fingerprint
                ]
                candidate_edges.append(
                    {
                        "from_occurrence_id": occurrence_id,
                        "from_logical_message_key": logical_keys[occurrence_id],
                        "to_logical_message_key": target_logical_key,
                        "target_occurrence_ids": target_occurrence_ids,
                        "relation": ("in_reply_to" if in_reply_to else "references"),
                        "header_ordinal": direct_header.header_ordinal,
                        "target_message_id_fingerprint": direct_token_fingerprint,
                    }
                )

    adjacency: dict[str, set[str]] = {}
    for edge in candidate_edges:
        if candidate_states.get(edge["from_occurrence_id"]) == "resolved":
            adjacency.setdefault(edge["from_logical_message_key"], set()).add(
                edge["to_logical_message_key"]
            )
    cycle_nodes = _reply_cycle_nodes(adjacency)
    for context in ordered_contexts:
        if (
            candidate_states.get(context.occurrence_id) == "resolved"
            and logical_keys[context.occurrence_id] in cycle_nodes
        ):
            candidate_states[context.occurrence_id] = "cyclic"
            for detail in target_details_by_occurrence.get(context.occurrence_id, {}).values():
                if detail.get("status") == "resolved":
                    detail["status"] = "cycle"

    for context in ordered_contexts:
        resolution_records_by_occurrence[context.occurrence_id] = _finalize_reply_resolutions(
            context.message,
            resolver_scope=resolver_scope,
            logical_message_key=logical_keys[context.occurrence_id],
            source_message_id_fingerprint=id_fingerprints[context.occurrence_id],
            candidate_state=candidate_states.get(context.occurrence_id, "none"),
            target_details=target_details_by_occurrence.get(context.occurrence_id, {}),
            resolutions=resolution_records_by_occurrence[context.occurrence_id],
        )

    resolved_edges = [
        edge
        for edge in candidate_edges
        if candidate_states.get(edge["from_occurrence_id"]) == "resolved"
        and edge["from_logical_message_key"] not in cycle_nodes
        and edge["to_logical_message_key"] not in cycle_nodes
    ]
    component_groups: dict[str, set[str]] = {}
    component_nodes: dict[str, set[str]] = {}
    for edge in resolved_edges:
        component_nodes.setdefault(edge["from_logical_message_key"], set()).add(
            edge["from_logical_message_key"]
        )
        component_nodes.setdefault(edge["to_logical_message_key"], set()).add(
            edge["to_logical_message_key"]
        )
    components = _reply_components(component_nodes, resolved_edges)
    for component in components:
        for node in component:
            component_groups[node] = component

    thread_ids_by_occurrence: dict[str, str] = {}
    thread_members: dict[str, list[_MailMessageContext]] = {}
    thread_modes: dict[str, str] = {}
    contexts_by_logical_key: dict[str, list[_MailMessageContext]] = {}
    for context in ordered_contexts:
        contexts_by_logical_key.setdefault(logical_keys[context.occurrence_id], []).append(context)
    heuristic_contexts_by_key: dict[str, list[_MailMessageContext]] = {}
    for context in ordered_contexts:
        node = logical_keys[context.occurrence_id]
        if component_groups.get(node) is not None:
            continue
        if candidate_states.get(context.occurrence_id) in {
            "ambiguous",
            "unresolved",
            "cyclic",
        }:
            continue
        heuristic_key = context.message.normalized_subject or node
        heuristic_contexts_by_key.setdefault(heuristic_key, []).append(context)

    component_group_keys_by_node: dict[str, tuple[str, ...]] = {}
    component_thread_ids: dict[tuple[str, ...], str] = {}
    for component in components:
        group_key = tuple(sorted(component))
        component_contexts = tuple(
            sorted(
                (
                    component_context
                    for component_node in group_key
                    for component_context in contexts_by_logical_key.get(component_node, ())
                ),
                key=lambda item: item.occurrence_id,
            )
        )
        component_resolution_payloads = _reply_resolution_groups_payload(
            component_contexts,
            resolution_records_by_occurrence,
        )
        component_thread_ids[group_key] = stable_resource_contract_id(
            "mailthread",
            "PstReplyThread",
            {
                **scope,
                "logical_message_keys": list(group_key),
                "reply_resolutions": component_resolution_payloads,
            },
        )
        for node in group_key:
            component_group_keys_by_node[node] = group_key

    heuristic_thread_ids: dict[str, str] = {}
    for heuristic_key, heuristic_contexts in heuristic_contexts_by_key.items():
        resolution_payloads = _reply_resolution_groups_payload(
            heuristic_contexts,
            resolution_records_by_occurrence,
        )
        heuristic_thread_ids[heuristic_key] = stable_resource_contract_id(
            "mailthread",
            "PstSubjectHeuristicThread",
            {
                **scope,
                "normalized_subject": heuristic_key,
                "reply_resolutions": resolution_payloads,
            },
        )

    for context in ordered_contexts:
        occurrence_id = context.occurrence_id
        node = logical_keys[occurrence_id]
        component_group_key = component_group_keys_by_node.get(node)
        if component_group_key is not None:
            thread_id = component_thread_ids[component_group_key]
            mode = "resolved"
        elif candidate_states.get(occurrence_id) in {"ambiguous", "unresolved", "cyclic"}:
            resolution_payloads = _reply_resolution_groups_payload(
                [context],
                resolution_records_by_occurrence,
            )
            thread_id = stable_resource_contract_id(
                "mailthread",
                "PstReplyUnresolvedThread",
                {
                    **scope,
                    "logical_message_key": node,
                    "occurrence_id": occurrence_id,
                    "state": candidate_states[occurrence_id],
                    "reply_resolutions": resolution_payloads,
                },
            )
            mode = candidate_states[occurrence_id]
        else:
            heuristic_key = context.message.normalized_subject or node
            thread_id = heuristic_thread_ids[heuristic_key]
            mode = "heuristic"
        thread_ids_by_occurrence[occurrence_id] = thread_id
        thread_members.setdefault(thread_id, []).append(context)
        thread_modes[thread_id] = mode

    resolved_edges_by_occurrence: dict[str, list[dict[str, Any]]] = {}
    for edge in resolved_edges:
        resolved_edges_by_occurrence.setdefault(edge["from_occurrence_id"], []).append(edge)

    payloads: list[dict[str, Any]] = []
    for thread_id, members in thread_members.items():
        member_occurrences = {member.occurrence_id for member in members}
        logical_message_keys = sorted({logical_keys[item] for item in member_occurrences})
        edges = [
            {key: value for key, value in edge.items() if key != "target_occurrence_ids"}
            | {"target_occurrence_ids": list(edge["target_occurrence_ids"])}
            for member in members
            for edge in resolved_edges_by_occurrence.get(member.occurrence_id, ())
        ]
        edges.sort(
            key=lambda edge: (
                edge["from_logical_message_key"],
                edge["to_logical_message_key"],
                edge["relation"],
                edge["header_ordinal"],
            )
        )
        unresolved_states = [
            {
                "message_occurrence_id": member.occurrence_id,
                "logical_message_key": logical_keys[member.occurrence_id],
                "state": candidate_states.get(member.occurrence_id, "none"),
                "reply_headers": [
                    header.to_payload()
                    for header in member.message.reply_headers
                    if header.kind in {"references", "in_reply_to"}
                ],
                "reply_resolutions": [
                    resolution.to_payload()
                    for resolution in resolution_records_by_occurrence[member.occurrence_id]
                ],
                "reply_resolution_fingerprint": _reply_resolution_fingerprint(
                    [
                        resolution.to_payload()
                        for resolution in resolution_records_by_occurrence[member.occurrence_id]
                    ]
                ),
            }
            for member in sorted(members, key=lambda item: item.occurrence_id)
            if candidate_states.get(member.occurrence_id) in {"ambiguous", "unresolved", "cyclic"}
        ]
        component = component_groups.get(logical_message_keys[0]) if logical_message_keys else None
        root_nodes = (
            sorted(set(component) - {edge["from_logical_message_key"] for edge in edges})
            if component is not None
            else []
        )
        payloads.append(
            _build_thread_payload(
                thread_id,
                members,
                archive_id=archive_id,
                mailbox_id=mailbox_id,
                logical_message_keys=logical_message_keys,
                logical_message_key_by_occurrence=logical_keys,
                edges=edges,
                unresolved_states=unresolved_states,
                reply_resolutions_by_occurrence=resolution_records_by_occurrence,
                mode=thread_modes[thread_id],
                root_id=root_nodes[0] if len(root_nodes) == 1 else None,
            )
        )
    return (
        sorted(payloads, key=lambda item: item["thread_id"]),
        thread_ids_by_occurrence,
        resolution_records_by_occurrence,
    )


def _message_id_fingerprint(message: _ParsedMessage) -> tuple[str | None, str]:
    occurrences = [item for item in message.reply_headers if item.kind == "message_id"]
    if not occurrences:
        return None, "missing"
    if len(occurrences) != 1:
        return None, "ambiguous"
    occurrence = occurrences[0]
    if occurrence.parse_status != "parsed" or len(occurrence.token_fingerprints) != 1:
        return None, occurrence.parse_status
    return occurrence.token_fingerprints[0], "parsed"


def _reply_resolution_record(
    *,
    header_kind: str,
    header_ordinal: int | None,
    occurrence_ordinal: int | None,
    identifier_ordinal: int | None,
    identifier_fingerprint: str | None,
    raw_value_fingerprint: str | None,
    parse_state: str,
    parse_complete: bool,
    resolution_state: str,
    reason_code: str,
    resolver_scope: tuple[str, str],
    source_message_id_fingerprint: str | None = None,
    target_logical_message_key: str | None = None,
    target_occurrence_ids: Sequence[str] = (),
) -> _ReplyResolution:
    return _ReplyResolution(
        header_kind=header_kind,
        header_ordinal=header_ordinal,
        occurrence_ordinal=occurrence_ordinal,
        identifier_ordinal=identifier_ordinal,
        identifier_fingerprint=identifier_fingerprint,
        raw_value_fingerprint=raw_value_fingerprint,
        parse_state=parse_state,
        parse_complete=parse_complete,
        resolution_state=resolution_state,
        reason_code=reason_code,
        resolver_scope=resolver_scope,
        source_message_id_fingerprint=source_message_id_fingerprint,
        target_logical_message_key=target_logical_message_key,
        target_occurrence_ids=tuple(target_occurrence_ids),
    )


def _header_resolution_records(
    occurrence: _ReplyHeaderOccurrence,
    *,
    header_kind: str,
    reason_code: str,
    resolver_scope: tuple[str, str],
    resolution_state: str = "rejected",
) -> list[_ReplyResolution]:
    identifiers = occurrence.token_fingerprints
    if not identifiers:
        return [
            _reply_resolution_record(
                header_kind=header_kind,
                header_ordinal=occurrence.header_ordinal,
                occurrence_ordinal=occurrence.occurrence_ordinal,
                identifier_ordinal=None,
                identifier_fingerprint=None,
                raw_value_fingerprint=occurrence.raw_value_fingerprint,
                parse_state=occurrence.parse_status,
                parse_complete=occurrence.parse_status == "parsed",
                resolution_state=resolution_state,
                reason_code=reason_code,
                resolver_scope=resolver_scope,
            )
        ]
    return [
        _reply_resolution_record(
            header_kind=header_kind,
            header_ordinal=occurrence.header_ordinal,
            occurrence_ordinal=occurrence.occurrence_ordinal,
            identifier_ordinal=index,
            identifier_fingerprint=identifier_fingerprint,
            raw_value_fingerprint=occurrence.raw_value_fingerprint,
            parse_state=occurrence.parse_status,
            parse_complete=occurrence.parse_status == "parsed",
            resolution_state=resolution_state,
            reason_code=reason_code,
            resolver_scope=resolver_scope,
        )
        for index, identifier_fingerprint in enumerate(identifiers, start=1)
    ]


def _initial_reply_resolutions(
    message: _ParsedMessage,
    *,
    resolver_scope: tuple[str, str],
) -> tuple[_ReplyResolution, ...]:
    records: list[_ReplyResolution] = []
    source_occurrences = tuple(
        occurrence for occurrence in message.reply_headers if occurrence.kind == "message_id"
    )
    if not source_occurrences:
        records.append(
            _reply_resolution_record(
                header_kind="message_id",
                header_ordinal=None,
                occurrence_ordinal=None,
                identifier_ordinal=None,
                identifier_fingerprint=None,
                raw_value_fingerprint=None,
                parse_state="missing",
                parse_complete=False,
                resolution_state="rejected",
                reason_code="source_message_id_missing",
                resolver_scope=resolver_scope,
            )
        )
    elif len(source_occurrences) > 1:
        for occurrence in source_occurrences:
            records.extend(
                _header_resolution_records(
                    occurrence,
                    header_kind="message_id",
                    reason_code="multiple_headers",
                    resolver_scope=resolver_scope,
                )
            )
    else:
        occurrence = source_occurrences[0]
        if occurrence.parse_status == "parsed" and occurrence.token_count == 1:
            records.extend(
                _header_resolution_records(
                    occurrence,
                    header_kind="message_id",
                    reason_code="source_message_id_valid",
                    resolver_scope=resolver_scope,
                    resolution_state="resolved",
                )
            )
        else:
            reason_code = {
                "empty": "empty",
                "malformed": "malformed",
                "overflow": "overflow",
                "multiple": "multiple_identifiers",
            }.get(occurrence.parse_status, "malformed")
            records.extend(
                _header_resolution_records(
                    occurrence,
                    header_kind="message_id",
                    reason_code=reason_code,
                    resolver_scope=resolver_scope,
                )
            )

    references = tuple(
        occurrence for occurrence in message.reply_headers if occurrence.kind == "references"
    )
    in_reply_to = tuple(
        occurrence for occurrence in message.reply_headers if occurrence.kind == "in_reply_to"
    )
    if not references and not in_reply_to:
        records.append(
            _reply_resolution_record(
                header_kind="ancestry",
                header_ordinal=None,
                occurrence_ordinal=None,
                identifier_ordinal=None,
                identifier_fingerprint=None,
                raw_value_fingerprint=None,
                parse_state="missing",
                parse_complete=False,
                resolution_state="heuristic",
                reason_code="no_authoritative_ancestry_header",
                resolver_scope=resolver_scope,
            )
        )
        return tuple(records)

    for occurrence in references:
        if len(references) > 1:
            reason_code = "ancestry_references_multiple_headers"
        elif occurrence.parse_status == "empty":
            reason_code = "ancestry_reference_empty"
        elif occurrence.parse_status in {"malformed", "overflow"}:
            reason_code = occurrence.parse_status
        else:
            reason_code = "parsed"
        records.extend(
            _header_resolution_records(
                occurrence,
                header_kind="references",
                reason_code=reason_code,
                resolver_scope=resolver_scope,
            )
        )
    for occurrence in in_reply_to:
        if len(in_reply_to) > 1:
            reason_code = "ancestry_in_reply_to_multiple_headers"
        elif occurrence.parse_status == "empty":
            reason_code = "ancestry_reference_empty"
        elif occurrence.parse_status in {"malformed", "overflow"}:
            reason_code = occurrence.parse_status
        elif occurrence.token_count != 1:
            reason_code = "ancestry_in_reply_to_multiple_identifiers"
        else:
            reason_code = "parsed"
        records.extend(
            _header_resolution_records(
                occurrence,
                header_kind="in_reply_to",
                reason_code=reason_code,
                resolver_scope=resolver_scope,
            )
        )
    return tuple(records)


def _reply_parse_reason(occurrence: _ReplyHeaderOccurrence, *, header_kind: str) -> str:
    if occurrence.parse_status == "empty":
        return "ancestry_reference_empty"
    if occurrence.parse_status in {"malformed", "overflow"}:
        return occurrence.parse_status
    if header_kind == "in_reply_to" and occurrence.token_count != 1:
        return "ancestry_in_reply_to_multiple_identifiers"
    return "parsed"


def _source_resolution_blocker(
    resolutions: Sequence[_ReplyResolution],
) -> tuple[str, int | None, str]:
    source_records = [record for record in resolutions if record.header_kind == "message_id"]
    if not source_records:
        return "message_id", None, "source_message_id_missing"
    first = min(
        source_records,
        key=lambda record: (
            record.header_ordinal is None,
            record.header_ordinal or 0,
            record.occurrence_ordinal or 0,
        ),
    )
    return (
        "message_id",
        first.header_ordinal,
        first.parse_reason_code or first.reason_code,
    )


def _ancestry_resolution_blocker(
    references: Sequence[_ReplyHeaderOccurrence],
    in_reply_to: Sequence[_ReplyHeaderOccurrence],
) -> tuple[str, int, str] | None:
    candidates: list[tuple[_ReplyHeaderOccurrence, str, int]] = []
    if len(references) > 1:
        candidates.extend(
            (occurrence, "ancestry_references_multiple_headers", 0) for occurrence in references
        )
    if len(in_reply_to) > 1:
        candidates.extend(
            (occurrence, "ancestry_in_reply_to_multiple_headers", 0) for occurrence in in_reply_to
        )
    for occurrence in (*references, *in_reply_to):
        reason = _reply_parse_reason(occurrence, header_kind=occurrence.kind)
        if reason != "parsed":
            candidates.append((occurrence, reason, 1))
    if not candidates:
        return None
    occurrence, reason, _ = min(
        candidates,
        key=lambda item: (item[2], item[0].header_ordinal, item[0].occurrence_ordinal),
    )
    return occurrence.kind, occurrence.header_ordinal, reason


def _finalize_reply_resolutions(
    message: _ParsedMessage,
    *,
    resolver_scope: tuple[str, str],
    logical_message_key: str,
    source_message_id_fingerprint: str | None,
    candidate_state: str,
    target_details: Mapping[str, Mapping[str, Any]],
    resolutions: Sequence[_ReplyResolution],
) -> tuple[_ReplyResolution, ...]:
    references = tuple(
        occurrence for occurrence in message.reply_headers if occurrence.kind == "references"
    )
    in_reply_to = tuple(
        occurrence for occurrence in message.reply_headers if occurrence.kind == "in_reply_to"
    )
    disagreement = bool(
        references
        and in_reply_to
        and references[0].token_fingerprints
        and in_reply_to[0].token_fingerprints
        and references[0].token_fingerprints[-1] != in_reply_to[0].token_fingerprints[0]
    )
    source_blocker = (
        _source_resolution_blocker(resolutions) if source_message_id_fingerprint is None else None
    )
    companion_blocker = _ancestry_resolution_blocker(references, in_reply_to)
    finalized: list[_ReplyResolution] = []
    for resolution in resolutions:
        resolution = replace(
            resolution,
            source_message_id_fingerprint=source_message_id_fingerprint,
        )
        if resolution.header_kind not in {"references", "in_reply_to"}:
            finalized.append(resolution)
            continue
        if source_blocker is not None:
            blocking_kind, blocking_ordinal, blocking_reason = source_blocker
            finalized.append(
                replace(
                    resolution,
                    resolution_state="rejected",
                    reason_code=(
                        resolution.reason_code
                        if resolution.parse_state != "parsed"
                        else "ancestry_resolution_blocked_by_source_message_id"
                    ),
                    resolution_reason_code="ancestry_resolution_blocked_by_source_message_id",
                    blocking_header_kind=blocking_kind,
                    blocking_header_ordinal=blocking_ordinal,
                    blocking_reason_code=blocking_reason,
                )
            )
            continue
        if companion_blocker is not None:
            blocking_kind, blocking_ordinal, blocking_reason = companion_blocker
            finalized.append(
                replace(
                    resolution,
                    resolution_state="rejected",
                    reason_code=(
                        resolution.reason_code
                        if resolution.parse_state != "parsed"
                        else "ancestry_resolution_blocked_by_incomplete_companion_header"
                    ),
                    resolution_reason_code=(
                        "ancestry_resolution_blocked_by_incomplete_companion_header"
                    ),
                    blocking_header_kind=blocking_kind,
                    blocking_header_ordinal=blocking_ordinal,
                    blocking_reason_code=blocking_reason,
                )
            )
            continue
        if disagreement:
            finalized.append(
                replace(
                    resolution,
                    resolution_state="rejected",
                    reason_code="ancestry_headers_disagree",
                    resolution_reason_code="ancestry_headers_disagree",
                    blocking_header_kind=resolution.header_kind,
                    blocking_header_ordinal=resolution.header_ordinal,
                    blocking_reason_code="ancestry_headers_disagree",
                )
            )
            continue
        detail = target_details.get(resolution.identifier_fingerprint or "")
        if detail is None:
            finalized.append(
                replace(
                    resolution,
                    resolution_state="rejected",
                    reason_code=(
                        resolution.reason_code
                        if resolution.parse_state != "parsed"
                        else "ancestry_resolution_blocked_by_incomplete_companion_header"
                    ),
                    resolution_reason_code=(
                        "ancestry_resolution_blocked_by_incomplete_companion_header"
                    ),
                    blocking_header_kind=resolution.header_kind,
                    blocking_header_ordinal=resolution.header_ordinal,
                    blocking_reason_code=resolution.reason_code,
                )
            )
            continue
        detail_status = detail.get("status")
        reason_code = {
            "absent": "target_absent_current_scope",
            "duplicate": "target_duplicate_conflict",
            "self": "target_self_reference",
            "cycle": "target_cycle",
            "resolved": "target_resolved_unique_same_scope",
        }.get(detail_status, "no_authoritative_ancestry_header")
        finalized.append(
            replace(
                resolution,
                resolution_state="resolved" if detail_status == "resolved" else "rejected",
                reason_code=reason_code,
                resolution_reason_code=reason_code,
                target_logical_message_key=detail.get("target_logical_message_key"),
                target_occurrence_ids=tuple(detail.get("target_occurrence_ids", ())),
            )
        )
    return tuple(finalized)


def _reply_cycle_nodes(adjacency: Mapping[str, set[str]]) -> set[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node: str, path: tuple[str, ...]) -> None:
        if node in visiting:
            if node in path:
                cycle_nodes.update(path[path.index(node) :])
            return
        if node in visited:
            return
        visiting.add(node)
        for target in sorted(adjacency.get(node, ())):
            visit(target, (*path, node))
        visiting.remove(node)
        visited.add(node)

    for node in sorted(adjacency):
        visit(node, ())
    return cycle_nodes


def _reply_components(
    node_sets: Mapping[str, set[str]],
    edges: Sequence[Mapping[str, Any]],
) -> list[set[str]]:
    nodes = set(node_sets)
    for edge in edges:
        nodes.add(str(edge["from_logical_message_key"]))
        nodes.add(str(edge["to_logical_message_key"]))
    adjacency: dict[str, set[str]] = {node: set() for node in nodes}
    for edge in edges:
        source = str(edge["from_logical_message_key"])
        target = str(edge["to_logical_message_key"])
        adjacency[source].add(target)
        adjacency[target].add(source)
    components: list[set[str]] = []
    unseen = set(nodes)
    while unseen:
        start = min(unseen)
        stack = [start]
        component: set[str] = set()
        while stack:
            node = stack.pop()
            if node not in unseen:
                continue
            unseen.remove(node)
            component.add(node)
            stack.extend(sorted(adjacency[node] & unseen))
        if any(adjacency[node] for node in component):
            components.append(component)
    return components


def _build_thread_payload(
    thread_id: str,
    members: Sequence[_MailMessageContext],
    *,
    archive_id: str,
    mailbox_id: str,
    logical_message_keys: Sequence[str],
    logical_message_key_by_occurrence: Mapping[str, str],
    edges: Sequence[Mapping[str, Any]],
    unresolved_states: Sequence[Mapping[str, Any]],
    reply_resolutions_by_occurrence: Mapping[str, Sequence[_ReplyResolution]],
    mode: str,
    root_id: str | None,
) -> dict[str, Any]:
    ordered_members = sorted(members, key=lambda item: item.occurrence_id)
    chronology_payloads = [member.message.chronology.to_payload() for member in ordered_members]
    chronology_states = [member.message.chronology.date_state for member in ordered_members]
    sent_at_values = [
        member.message.sent_at for member in ordered_members if member.message.sent_at
    ]
    reply_resolution_groups = _reply_resolution_groups_payload(
        ordered_members,
        reply_resolutions_by_occurrence,
    )
    payload: dict[str, Any] = {
        "archive_id": archive_id,
        "mailbox_id": mailbox_id,
        "thread_id": thread_id,
        "thread_root_id": root_id,
        "normalized_subject": ordered_members[0].message.normalized_subject
        if ordered_members
        else "",
        "message_ids": [member.message.message_id for member in ordered_members],
        "logical_message_keys": list(logical_message_keys),
        "occurrence_membership": [
            {
                "logical_message_key": logical_message_key_by_occurrence[member.occurrence_id],
                "message_occurrence_id": member.occurrence_id,
            }
            for member in ordered_members
        ],
        "resolved_reply_edges": list(edges),
        "unresolved_reply_states": list(unresolved_states),
        "reply_resolutions": reply_resolution_groups,
        "reply_resolution_fingerprint": _reply_resolution_fingerprint(reply_resolution_groups),
        "reply_ancestry_state": mode,
        "thread_identity_policy": "formowl_mail_thread_identity_scoped_reply_v3",
        "reply_resolution_policy": _PST_REPLY_RESOLUTION_POLICY,
        "version_lineage": [],
        "participants": [],
        "chronology": chronology_payloads,
        "message_count": len(ordered_members),
    }
    for member in ordered_members:
        if member.message.sender and member.message.sender not in payload["participants"]:
            payload["participants"].append(member.message.sender)
    if mode == "heuristic":
        payload["subject_grouping"] = {
            "mode": "heuristic",
            "authority": "not_reply_ancestry",
        }
    elif mode in {"ambiguous", "unresolved", "cyclic"}:
        payload["subject_grouping"] = {"mode": "not_used"}
    if chronology_states and all(state == "authoritative" for state in chronology_states):
        ordered_sent_at = sorted(sent_at_values, key=_utc_comparison_key)
        if ordered_sent_at:
            payload["first_sent_at"] = ordered_sent_at[0]
            payload["last_sent_at"] = ordered_sent_at[-1]
    else:
        payload["chronology_completeness"] = "incomplete"
    return payload


def _utc_comparison_key(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError("PST chronology comparison requires an aware instant")
    return parsed.astimezone(timezone.utc)


def _thread_id(message: _ParsedMessage) -> str:
    return stable_resource_contract_id(
        "mailthread",
        "PstLegacyThreadFallback",
        {"message_fingerprint": _message_fingerprint(message)},
    )


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self._parts)


def _html_to_text(value: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(value)
    return parser.text()


__all__ = [
    "PST_INVENTORY_CARRIER_MODALITY",
    "PST_INVENTORY_CARRIER_OBSERVATION_TYPE",
    "PST_INVENTORY_CARRIER_VERSION",
    "PST_SOURCE_UNIT_OBSERVATION_TYPE",
    "PST_SOURCE_UNIT_OBSERVATION_VERSION",
    "PstMailArchiveExtractor",
    "PstExtractionResult",
    "PstTraversalBinding",
    "rehydrate_pst_inventory_carrier",
    "rehydrate_pst_inventory_carriers",
    "rehydrate_pst_observation_stream",
    "rehydrate_pst_source_unit_observations",
]
