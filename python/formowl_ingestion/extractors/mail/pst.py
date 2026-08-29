from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
import uuid

from formowl_contract import (
    Observation,
    SourceRef,
    SourceInventory,
    SourceInventoryItem,
    SourceInventoryProcessingState,
    SourceInventoryRawRetentionState,
    assert_no_public_raw_references,
    now_iso,
    sha256_json,
    stable_observation_id,
    stable_resource_contract_hash,
    stable_resource_contract_id,
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
_SAFE_HEADER_NAMES = {
    "message-id",
    "subject",
    "from",
    "to",
    "cc",
    "date",
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
class _ParsedAttachment:
    attachment_id: str
    filename: str
    source_name_fingerprint: str | None = None
    mime_type: str | None = None
    content_hash: str | None = None
    size_bytes: int | None = None
    content_bytes: bytes | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class _ParsedMessage:
    source_local_key: str
    folder_path_hash: str
    folder_label: str
    message_id: str
    subject: str
    normalized_subject: str
    sender: str
    sent_at: str
    headers: dict[str, str]
    body_segments: list[str]
    body_hash: str
    attachments: list[_ParsedAttachment]
    references: list[str] = field(default_factory=list)
    in_reply_to: str | None = None


@dataclass(frozen=True)
class _PstParserConfig:
    max_messages: int | None
    timeout_seconds: int
    max_message_file_bytes: int
    body_segment_max_chars: int
    max_body_segments_per_message: int
    max_attachment_hash_bytes: int
    include_deleted_items: bool
    parser_workers: int


@dataclass(frozen=True)
class _PstAttachmentInventoryIndex:
    item_by_key: Mapping[str, SourceInventoryItem]
    attachment_items: tuple[SourceInventoryItem, ...]
    attachment_items_by_id: Mapping[str, tuple[SourceInventoryItem, ...]]
    attachment_items_by_id_and_ordinal: Mapping[
        tuple[str, int],
        tuple[SourceInventoryItem, ...],
    ]
    attachment_items_by_parent_message_key: Mapping[
        str,
        tuple[SourceInventoryItem, ...],
    ]
    message_key_by_occurrence_id: Mapping[str, str]

    @classmethod
    def create(
        cls,
        source_inventory: SourceInventory,
        *,
        message_key_by_occurrence_id: Mapping[str, str],
    ) -> "_PstAttachmentInventoryIndex":
        item_by_key: dict[str, SourceInventoryItem] = {}
        attachment_items: list[SourceInventoryItem] = []
        by_id: dict[str, list[SourceInventoryItem]] = {}
        by_id_and_ordinal: dict[tuple[str, int], list[SourceInventoryItem]] = {}
        by_parent: dict[str, list[SourceInventoryItem]] = {}
        for item in source_inventory.items:
            source_local_key = str(item.location["source_local_key"])
            item_by_key[source_local_key] = item
            if not item.structure_kind.endswith("attachment_occurrence"):
                continue
            attachment_id = item.location.get("attachment_id")
            attachment_ordinal = item.location.get("attachment_ordinal")
            parent_key = item.location.get("parent_source_local_key")
            if (
                not isinstance(attachment_id, str)
                or not attachment_id
                or not isinstance(attachment_ordinal, int)
                or isinstance(attachment_ordinal, bool)
                or attachment_ordinal < 1
                or not isinstance(parent_key, str)
                or not parent_key
            ):
                raise ValueError("pst_attachment_inventory_identity_incomplete")
            attachment_items.append(item)
            by_id.setdefault(attachment_id, []).append(item)
            by_id_and_ordinal.setdefault((attachment_id, attachment_ordinal), []).append(item)
            by_parent.setdefault(parent_key, []).append(item)

        def ordered(items: Sequence[SourceInventoryItem]) -> tuple[SourceInventoryItem, ...]:
            return tuple(sorted(items, key=lambda item: item.source_inventory_item_id))

        return cls(
            item_by_key=item_by_key,
            attachment_items=ordered(attachment_items),
            attachment_items_by_id={key: ordered(items) for key, items in by_id.items()},
            attachment_items_by_id_and_ordinal={
                key: ordered(items) for key, items in by_id_and_ordinal.items()
            },
            attachment_items_by_parent_message_key={
                key: ordered(items) for key, items in by_parent.items()
            },
            message_key_by_occurrence_id=dict(message_key_by_occurrence_id),
        )


@dataclass(frozen=True)
class _PstAttachmentObservationContext:
    occurrence_id: str
    parent_occurrence_id: str | None
    message: _ParsedMessage


@dataclass(frozen=True)
class _PstClassifiedSourceUnit:
    source_local_key: str
    processing_state: SourceInventoryProcessingState
    content_type: str
    parsed_message: _ParsedMessage | None


@dataclass(frozen=True)
class _BoundedPstExport:
    candidate_paths: tuple[Path, ...]
    stop_reason: str
    overflow_count: int
    parser_completed: bool


@dataclass(frozen=True)
class PstSourceCompletenessPocResult:
    source_inventory: SourceInventory
    observations: tuple[Observation, ...]
    report: dict[str, Any]


@dataclass(frozen=True)
class NativePstAttachmentExport:
    """One source-native attachment/export occurrence from a private manifest."""

    source_local_key: str
    parent_message_source_local_key: str
    pst_attachment_node_id: str
    attachment_content_hash: str
    byte_count: int
    export_disposition: str
    export_occurrence_ordinal: int


@dataclass(frozen=True)
class NativePstMessageExport:
    """One exact source-native RFC822 export and its source lineage."""

    source_local_key: str
    parent_folder_source_local_key: str
    pst_folder_node_id: str
    pst_message_node_id: str
    pst_message_data_node_id: str
    message_content_hash: str
    byte_count: int
    export_path: Path = field(repr=False)
    attachments: tuple[NativePstAttachmentExport, ...] = ()


@dataclass(frozen=True)
class NativePstParsedEvidenceResult:
    """Authorized mail Observations derived from exact native exports."""

    observations: tuple[Observation, ...]
    warning_counts: dict[str, int]
    message_count: int
    header_observation_count: int
    body_segment_observation_count: int
    attachment_observation_count: int


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
        version: str = "0.1.0",
        parser_command: str = "readpst",
        runner: _ParserRunner | None = None,
        scratch_parent: str | Path | None = None,
    ) -> None:
        self._version = version
        self._parser_command = parser_command
        self._runner = runner or _run_parser_command
        self._scratch_parent = Path(scratch_parent) if scratch_parent is not None else None

    def name(self) -> str:
        return "pst_mail_archive_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_PST_MIME_TYPES)

    def extractor_type(self) -> str:
        return "mail_archive"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        config = _parser_config(extraction_input.config)
        if not _looks_like_pst(extraction_input.object_path):
            return ExtractionResult(errors=["pst_parser_input_signature_mismatch"])

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
                return ExtractionResult(errors=["pst_parser_unavailable"])
            except subprocess.TimeoutExpired:
                return ExtractionResult(errors=["pst_parser_timeout"])
            if completed.returncode != 0:
                return ExtractionResult(errors=["pst_parser_failed"])

            parsed_messages, parse_warnings = _parse_exported_messages(
                scratch_path,
                config=config,
            )
        finally:
            shutil.rmtree(scratch_path, ignore_errors=True)

        if not parsed_messages:
            return ExtractionResult(
                warnings=parse_warnings,
                errors=["pst_parser_no_messages"],
            )

        source_inventory = _pst_source_inventory(
            parsed_messages,
            extraction_input=extraction_input,
            parser_name=self.name(),
            parser_version=self.version(),
            config=config,
        )
        observations = _mail_observations_from_messages(
            parsed_messages,
            extraction_input=extraction_input,
            source_inventory=source_inventory,
        )
        warnings = list(parse_warnings)
        if config.max_messages is not None and len(parsed_messages) >= config.max_messages:
            warnings.append("pst_parser_message_limit_reached")
        return ExtractionResult(observations=observations, warnings=warnings)


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


def parse_native_pst_message_exports(
    message_exports: Sequence[NativePstMessageExport],
    *,
    source_inventory: SourceInventory,
    source_asset_id: str,
    source_asset_sha256: str,
    extractor_run_id: str,
    permission_scope: Mapping[str, Any],
    provenance_fingerprint: str,
    created_at: str,
    body_segment_max_chars: int = 4000,
    max_body_segments_per_message: int = 3,
    max_message_file_bytes: int = 8 * 1024 * 1024,
) -> NativePstParsedEvidenceResult:
    """Parse exact native RFC822 exports without deriving identity from paths.

    ``message_exports`` is expected to come from a separately validated private
    source-native manifest. Paths are used only to read bytes; every emitted
    Observation is identified by the manifest's source-local descriptor key and
    is bound to the corresponding existing ``SourceInventoryItem``.

    Native attachment/export occurrences are materialized from the manifest
    lineage, not guessed from MIME filename or ordinal matches. This preserves
    descriptor-only and separate-format exports even when the RFC822 payload
    does not expose them as MIME attachments.
    """

    if source_inventory.source_asset_id != source_asset_id:
        raise ValueError("native_pst_source_inventory_asset_mismatch")
    if source_inventory.source_fingerprint != source_asset_sha256:
        raise ValueError("native_pst_source_inventory_fingerprint_mismatch")
    if source_inventory.permission_fingerprint != sha256_json(permission_scope):
        raise ValueError("native_pst_source_inventory_permission_mismatch")
    for field_name, value in (
        ("source_asset_id", source_asset_id),
        ("source_asset_sha256", source_asset_sha256),
        ("extractor_run_id", extractor_run_id),
        ("provenance_fingerprint", provenance_fingerprint),
        ("created_at", created_at),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"native_pst_{field_name}_missing")
        assert_no_public_raw_references(value, f"native_pst_{field_name}")

    config = _parser_config(
        {
            "max_messages": None,
            "timeout_seconds": 1,
            "max_message_file_bytes": max_message_file_bytes,
            "body_segment_max_chars": body_segment_max_chars,
            "max_body_segments_per_message": max_body_segments_per_message,
            "max_attachment_hash_bytes": 1,
            "include_deleted_items": False,
            "parser_workers": 1,
        }
    )
    item_by_source_key = {
        str(item.location.get("source_local_key")): item
        for item in source_inventory.items
        if isinstance(item.location.get("source_local_key"), str)
    }
    ordered_exports = sorted(message_exports, key=lambda item: item.source_local_key)
    if not ordered_exports:
        raise ValueError("native_pst_message_exports_empty")
    if len({item.source_local_key for item in ordered_exports}) != len(ordered_exports):
        raise ValueError("native_pst_message_source_local_key_duplicate")

    archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {
            "asset_id": source_asset_id,
            "archive_sha256": source_asset_sha256,
        },
    )
    mailbox_id = stable_resource_contract_id(
        "mailbox",
        "PstMailbox",
        {"asset_id": source_asset_id},
    )
    warnings: list[str] = []
    parsed_rows: list[
        tuple[
            NativePstMessageExport,
            _ParsedMessage,
            SourceInventoryItem,
            SourceInventoryItem,
        ]
    ] = []
    for native_export in ordered_exports:
        message_item = item_by_source_key.get(native_export.source_local_key)
        folder_item = item_by_source_key.get(native_export.parent_folder_source_local_key)
        if (
            message_item is None
            or message_item.structure_kind
            not in {"email_message_occurrence", "exported_message_occurrence"}
            or message_item.processing_state != SourceInventoryProcessingState.PARSED
        ):
            raise ValueError("native_pst_message_inventory_binding_missing")
        if (
            folder_item is None
            or folder_item.structure_kind != "mail_folder_descriptor_occurrence"
            or folder_item.processing_state != SourceInventoryProcessingState.PARSED
        ):
            raise ValueError("native_pst_folder_inventory_binding_missing")
        if (
            message_item.location.get("parent_source_local_key")
            != native_export.parent_folder_source_local_key
            or message_item.location.get("message_content_hash")
            != native_export.message_content_hash
        ):
            raise ValueError("native_pst_message_inventory_lineage_drift")
        if not native_export.export_path.is_file():
            raise ValueError("native_pst_message_export_missing")
        if native_export.export_path.stat().st_size != native_export.byte_count:
            raise ValueError("native_pst_message_export_byte_count_drift")
        if native_export.byte_count > config.max_message_file_bytes:
            raise ValueError("native_pst_message_export_too_large")
        raw_message = native_export.export_path.read_bytes()
        if "sha256:" + hashlib.sha256(raw_message).hexdigest() != (
            native_export.message_content_hash
        ):
            raise ValueError("native_pst_message_export_content_hash_drift")
        try:
            email_message = BytesParser(policy=policy.default).parsebytes(raw_message)
        except Exception as exc:
            raise ValueError("native_pst_message_export_parse_failed") from exc
        if not _is_mail_message(email_message):
            raise ValueError("native_pst_message_export_not_rfc822")
        parsed_message = _parsed_message_from_email(
            email_message,
            candidate_path=native_export.export_path,
            export_root=native_export.export_path.parent,
            message_index=1,
            config=config,
            warnings=warnings,
            source_local_key_override=native_export.source_local_key,
            folder_path_hash_override=sha256_json(
                {
                    "source_asset_sha256": source_asset_sha256,
                    "pst_folder_node_id": native_export.pst_folder_node_id,
                }
            ),
            folder_label_override=(
                "native_folder_" + sha256_json(native_export.pst_folder_node_id)[-16:]
            ),
            message_id_fallback_parts=(
                native_export.source_local_key,
                native_export.message_content_hash,
            ),
            include_attachments=False,
        )
        parsed_rows.append(
            (
                native_export,
                parsed_message,
                message_item,
                folder_item,
            )
        )

    folder_observations: dict[str, Observation] = {}
    observations: list[Observation] = []
    for native_export, parsed_message, _, folder_item in parsed_rows:
        folder_key = native_export.parent_folder_source_local_key
        if folder_key in folder_observations:
            continue
        folder_observation = _native_bound_mail_observation(
            source_asset_id=source_asset_id,
            extractor_run_id=extractor_run_id,
            observation_type="mail_folder_occurrence",
            text=parsed_message.folder_label,
            location={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "source_inventory_id": source_inventory.source_inventory_id,
                "source_inventory_item_id": folder_item.source_inventory_item_id,
                "source_local_key": folder_key,
                "folder_path_hash": parsed_message.folder_path_hash,
                "pst_folder_node_id": native_export.pst_folder_node_id,
                "source_provenance_fingerprint": provenance_fingerprint,
            },
            payload={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "source_inventory_id": source_inventory.source_inventory_id,
                "source_inventory_item_id": folder_item.source_inventory_item_id,
                "source_local_key": folder_key,
                "folder_path_hash": parsed_message.folder_path_hash,
                "folder_label": parsed_message.folder_label,
                "source_provenance_fingerprint": provenance_fingerprint,
                "evidence_state": "source_observation",
                "canonical_fact_status": "not_asserted",
            },
            permission_scope=permission_scope,
            created_at=created_at,
        )
        folder_observations[folder_key] = folder_observation
        observations.append(folder_observation)

    header_observation_count = 0
    body_segment_observation_count = 0
    attachment_observation_count = 0
    for native_export, parsed_message, message_item, folder_item in parsed_rows:
        folder_observation = folder_observations[native_export.parent_folder_source_local_key]
        occurrence_id = stable_resource_contract_id(
            "mailocc",
            "PstNativeMessageOccurrence",
            {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "source_local_key": native_export.source_local_key,
                "message_content_hash": native_export.message_content_hash,
            },
        )
        thread_id = _thread_id(parsed_message)
        attachment_hashes = sorted(
            attachment.attachment_content_hash for attachment in native_export.attachments
        )
        message_fingerprint = sha256_json(
            {
                "message_id": parsed_message.message_id,
                "normalized_subject": parsed_message.normalized_subject,
                "sender": parsed_message.sender,
                "sent_at": parsed_message.sent_at,
                "body_hash": parsed_message.body_hash,
                "attachment_hashes": attachment_hashes,
            }
        )
        base_location: dict[str, Any] = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "source_inventory_id": source_inventory.source_inventory_id,
            "source_inventory_item_id": message_item.source_inventory_item_id,
            "parent_inventory_item_id": folder_item.source_inventory_item_id,
            "source_local_key": native_export.source_local_key,
            "parent_source_local_key": native_export.parent_folder_source_local_key,
            "parent_folder_observation_id": folder_observation.observation_id,
            "source_content_hash": native_export.message_content_hash,
            "folder_path_hash": parsed_message.folder_path_hash,
            "message_id": parsed_message.message_id,
            "message_occurrence_id": occurrence_id,
            "thread_id": thread_id,
            "pst_folder_node_id": native_export.pst_folder_node_id,
            "pst_message_node_id": native_export.pst_message_node_id,
            "pst_message_data_node_id": native_export.pst_message_data_node_id,
            "source_provenance_fingerprint": provenance_fingerprint,
        }
        message_payload = {
            **base_location,
            "subject": parsed_message.subject,
            "normalized_subject": parsed_message.normalized_subject,
            "sender": parsed_message.sender,
            "sent_at": parsed_message.sent_at,
            "body_hash": parsed_message.body_hash,
            "message_fingerprint": message_fingerprint,
            "fingerprint_policy": "formowl_mail_fingerprint_v1",
            "evidence_state": "source_observation",
            "canonical_fact_status": "not_asserted",
        }
        observations.append(
            _native_bound_mail_observation(
                source_asset_id=source_asset_id,
                extractor_run_id=extractor_run_id,
                observation_type="email_message",
                text=parsed_message.subject,
                location=base_location,
                payload=message_payload,
                permission_scope=permission_scope,
                created_at=created_at,
            )
        )
        for header_index, (header_name, header_value) in enumerate(
            sorted(parsed_message.headers.items()),
            start=1,
        ):
            header_observation_count += 1
            observations.append(
                _native_bound_mail_observation(
                    source_asset_id=source_asset_id,
                    extractor_run_id=extractor_run_id,
                    observation_type="email_header",
                    text=f"{header_name}: {header_value}",
                    location={
                        **base_location,
                        "header_index": header_index,
                        "header_name": header_name,
                    },
                    payload={
                        **base_location,
                        "header_name": header_name,
                        "header_value": header_value,
                        "message_fingerprint": message_fingerprint,
                        "evidence_state": "source_observation",
                        "canonical_fact_status": "not_asserted",
                    },
                    permission_scope=permission_scope,
                    created_at=created_at,
                )
            )
        for segment_index, body_segment in enumerate(
            parsed_message.body_segments,
            start=1,
        ):
            body_segment_observation_count += 1
            observations.append(
                _native_bound_mail_observation(
                    source_asset_id=source_asset_id,
                    extractor_run_id=extractor_run_id,
                    observation_type="email_body_segment",
                    text=body_segment,
                    location={
                        **base_location,
                        "body_segment_index": segment_index,
                    },
                    payload={
                        **base_location,
                        "body_segment_index": segment_index,
                        "message_fingerprint": message_fingerprint,
                        "evidence_state": "source_observation",
                        "canonical_fact_status": "not_asserted",
                    },
                    permission_scope=permission_scope,
                    created_at=created_at,
                )
            )
        for attachment in sorted(
            native_export.attachments,
            key=lambda item: item.source_local_key,
        ):
            attachment_item = item_by_source_key.get(attachment.source_local_key)
            if (
                attachment_item is None
                or not attachment_item.structure_kind.endswith("occurrence")
                or attachment_item.processing_state != SourceInventoryProcessingState.PARSED
            ):
                raise ValueError("native_pst_attachment_inventory_binding_missing")
            if (
                attachment.parent_message_source_local_key != native_export.source_local_key
                or attachment_item.location.get("parent_source_local_key")
                != native_export.source_local_key
                or attachment_item.location.get("attachment_content_hash")
                != attachment.attachment_content_hash
            ):
                raise ValueError("native_pst_attachment_inventory_lineage_drift")
            attachment_observation_count += 1
            attachment_id = stable_resource_contract_id(
                "mailatt",
                "PstNativeAttachment",
                {
                    "source_local_key": attachment.source_local_key,
                    "attachment_content_hash": attachment.attachment_content_hash,
                    "pst_attachment_node_id": attachment.pst_attachment_node_id,
                },
            )
            opaque_filename = "native_attachment_" + sha256_json(attachment.source_local_key)[-16:]
            observations.append(
                _native_bound_mail_observation(
                    source_asset_id=source_asset_id,
                    extractor_run_id=extractor_run_id,
                    observation_type="email_attachment_occurrence",
                    text=opaque_filename,
                    location={
                        **base_location,
                        "source_inventory_item_id": (attachment_item.source_inventory_item_id),
                        "parent_inventory_item_id": (message_item.source_inventory_item_id),
                        "source_local_key": attachment.source_local_key,
                        "parent_source_local_key": native_export.source_local_key,
                        "source_content_hash": attachment.attachment_content_hash,
                        "pst_attachment_node_id": attachment.pst_attachment_node_id,
                        "export_occurrence_ordinal": (attachment.export_occurrence_ordinal),
                        "export_disposition": attachment.export_disposition,
                        "attachment_index": attachment.export_occurrence_ordinal,
                        "attachment_id": attachment_id,
                    },
                    payload={
                        **base_location,
                        "source_inventory_item_id": (attachment_item.source_inventory_item_id),
                        "parent_inventory_item_id": (message_item.source_inventory_item_id),
                        "source_local_key": attachment.source_local_key,
                        "parent_source_local_key": native_export.source_local_key,
                        "source_content_hash": attachment.attachment_content_hash,
                        "pst_attachment_node_id": attachment.pst_attachment_node_id,
                        "export_occurrence_ordinal": (attachment.export_occurrence_ordinal),
                        "export_disposition": attachment.export_disposition,
                        "attachment_id": attachment_id,
                        "filename": opaque_filename,
                        "mime_type": (
                            "message/rfc822"
                            if attachment.export_disposition == "embedded_message_exported"
                            else "application/octet-stream"
                        ),
                        "content_hash": attachment.attachment_content_hash,
                        "size_bytes": attachment.byte_count,
                        "message_fingerprint": message_fingerprint,
                        "evidence_state": "source_observation",
                        "canonical_fact_status": "not_asserted",
                    },
                    permission_scope=permission_scope,
                    created_at=created_at,
                )
            )

    warning_counts: dict[str, int] = {}
    for warning in warnings:
        warning_counts[warning] = warning_counts.get(warning, 0) + 1
    return NativePstParsedEvidenceResult(
        observations=tuple(observations),
        warning_counts=dict(sorted(warning_counts.items())),
        message_count=len(parsed_rows),
        header_observation_count=header_observation_count,
        body_segment_observation_count=body_segment_observation_count,
        attachment_observation_count=attachment_observation_count,
    )


def _native_bound_mail_observation(
    *,
    source_asset_id: str,
    extractor_run_id: str,
    observation_type: str,
    text: str | None,
    location: Mapping[str, Any],
    payload: Mapping[str, Any],
    permission_scope: Mapping[str, Any],
    created_at: str,
) -> Observation:
    normalized_location = dict(location)
    normalized_payload = dict(payload)
    observation_id = stable_observation_id(
        asset_id=source_asset_id,
        extractor_run_id=extractor_run_id,
        observation_type=observation_type,
        modality="mail",
        location=normalized_location,
        text=text,
        payload=normalized_payload,
    )
    return Observation(
        observation_id=observation_id,
        asset_id=source_asset_id,
        extractor_run_id=extractor_run_id,
        observation_type=observation_type,
        modality="mail",
        text=text,
        location=normalized_location,
        confidence=1.0,
        permission_scope=dict(permission_scope),
        created_at=created_at,
        payload=normalized_payload,
    )


def run_bounded_pst_source_completeness_poc(
    pst_path: str | Path,
    *,
    inventory_path: str | Path,
    source_asset_id: str,
    permission_scope: Mapping[str, Any],
    extractor_run_id: str,
    created_at: str,
    parser_command: str = "readpst",
    scratch_parent: str | Path | None = None,
    max_exported_files: int = 4,
    max_exported_bytes: int = 16 * 1024 * 1024,
    timeout_seconds: int = 30,
    max_message_file_bytes: int = 4 * 1024 * 1024,
) -> PstSourceCompletenessPocResult:
    """Run a bounded, diagnostic-only source-inventory reconciliation slice.

    The parser export is inventoried before Observation materialization. The
    inventory is persisted and loaded back before it is supplied to the
    Observation binding path. Stopping the parser at a cap makes this a partial
    diagnostic and never a source-completeness authority result.
    """

    source_path = Path(pst_path)
    if not _looks_like_pst(source_path):
        raise ValueError("pst_source_signature_mismatch")
    max_exported_files = _positive_int(max_exported_files, "max_exported_files")
    max_exported_bytes = _positive_int(max_exported_bytes, "max_exported_bytes")
    timeout_seconds = _positive_int(timeout_seconds, "timeout_seconds")
    max_message_file_bytes = _positive_int(
        max_message_file_bytes,
        "max_message_file_bytes",
    )
    config = _parser_config(
        {
            "timeout_seconds": timeout_seconds,
            "max_message_file_bytes": max_message_file_bytes,
            "body_segment_max_chars": 4000,
            "max_body_segments_per_message": 3,
            "max_attachment_hash_bytes": max_message_file_bytes,
            "include_deleted_items": False,
            "parser_workers": 1,
        }
    )
    source_fingerprint = _bounded_source_fingerprint(source_path)
    parser_fingerprint = stable_resource_contract_hash(
        "PstBoundedSourceCompletenessProfile",
        {
            "parser_command_fingerprint": sha256_json(parser_command),
            "max_exported_files": max_exported_files,
            "max_exported_bytes": max_exported_bytes,
            "timeout_seconds": timeout_seconds,
            "max_message_file_bytes": max_message_file_bytes,
        },
    )
    scratch_path = _create_scratch_dir(Path(scratch_parent) if scratch_parent is not None else None)
    try:
        bounded_export = _bounded_readpst_export(
            parser_command=parser_command,
            pst_path=source_path,
            output_dir=scratch_path,
            max_exported_files=max_exported_files,
            max_exported_bytes=max_exported_bytes,
            timeout_seconds=timeout_seconds,
        )
        classified_units = _classify_exported_source_units(
            bounded_export.candidate_paths,
            export_root=scratch_path,
            config=config,
        )
        source_inventory = _pst_source_inventory_from_classified_units(
            classified_units,
            source_asset_id=source_asset_id,
            source_fingerprint=source_fingerprint,
            parser_fingerprint=parser_fingerprint,
            permission_scope=permission_scope,
            created_at=created_at,
        )
        persisted_inventory = _persist_source_inventory_round_trip(
            source_inventory,
            Path(inventory_path),
        )
        parsed_messages = [
            unit.parsed_message for unit in classified_units if unit.parsed_message is not None
        ]
        observations = tuple(
            _mail_observations_from_messages(
                parsed_messages,
                extraction_input=_diagnostic_extraction_input(
                    source_path=source_path,
                    source_asset_id=source_asset_id,
                    source_fingerprint=source_fingerprint,
                    permission_scope=permission_scope,
                    extractor_run_id=extractor_run_id,
                    created_at=created_at,
                ),
                source_inventory=persisted_inventory,
            )
        )
        report = reconcile_pst_source_inventory(
            persisted_inventory,
            observations,
            bounded_source_unit_count=len(classified_units),
            bounded_overflow_count=bounded_export.overflow_count,
            parser_stop_reason=bounded_export.stop_reason,
            parser_completed=bounded_export.parser_completed,
            persisted_round_trip_verified=(
                persisted_inventory.to_dict() == source_inventory.to_dict()
            ),
        )
        return PstSourceCompletenessPocResult(
            source_inventory=persisted_inventory,
            observations=observations,
            report=report,
        )
    finally:
        shutil.rmtree(scratch_path, ignore_errors=True)


def _diagnostic_extraction_input(
    *,
    source_path: Path,
    source_asset_id: str,
    source_fingerprint: str,
    permission_scope: Mapping[str, Any],
    extractor_run_id: str,
    created_at: str,
) -> ExtractionInput:
    from formowl_contract import Asset

    return ExtractionInput(
        asset=Asset(
            asset_id=source_asset_id,
            storage_backend_id="storage_diagnostic_private",
            object_uri="formowl://asset/" + source_asset_id,
            content_hash=source_fingerprint,
            file_size=source_path.stat().st_size,
            mime_type="application/vnd.ms-outlook",
            created_at=created_at,
            registered_at=created_at,
            owner_user_id=str(permission_scope.get("owner_user_id", "user_diagnostic")),
            workspace_id=str(permission_scope.get("workspace_id", "workspace_diagnostic")),
            permission_scope=dict(permission_scope),
            lifecycle_state="active",
        ),
        object_path=source_path,
        extractor_run_id=extractor_run_id,
        config={},
        created_at=created_at,
    )


def _bounded_source_fingerprint(path: Path, *, sample_bytes: int = 1024 * 1024) -> str:
    with path.open("rb") as handle:
        prefix = handle.read(sample_bytes)
    return sha256_json(
        {
            "diagnostic_prefix_sha256": "sha256:" + hashlib.sha256(prefix).hexdigest(),
            "size_bytes": path.stat().st_size,
            "sample_bytes": len(prefix),
        }
    )


def _bounded_readpst_export(
    *,
    parser_command: str,
    pst_path: Path,
    output_dir: Path,
    max_exported_files: int,
    max_exported_bytes: int,
    timeout_seconds: int,
) -> _BoundedPstExport:
    command = _readpst_command(
        parser_command,
        pst_path,
        output_dir,
        include_deleted_items=False,
    )
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise ValueError("pst_parser_unavailable") from exc

    started = time.monotonic()
    stop_reason = "completed"
    parser_completed = False
    while True:
        paths = tuple(_iter_exported_files(output_dir))
        exported_bytes = sum(_safe_file_size(path) for path in paths)
        if len(paths) >= max_exported_files:
            stop_reason = "file_cap"
            _terminate_process(process)
            break
        if exported_bytes >= max_exported_bytes:
            stop_reason = "byte_cap"
            _terminate_process(process)
            break
        returncode = process.poll()
        if returncode is not None:
            parser_completed = returncode == 0
            stop_reason = "completed" if parser_completed else "parser_failed"
            break
        if time.monotonic() - started >= timeout_seconds:
            stop_reason = "timeout"
            _terminate_process(process)
            break
        time.sleep(0.05)

    all_paths = tuple(_iter_exported_files(output_dir))
    selected: list[Path] = []
    selected_bytes = 0
    for candidate in all_paths:
        candidate_size = _safe_file_size(candidate)
        if len(selected) >= max_exported_files:
            continue
        if selected and selected_bytes + candidate_size > max_exported_bytes:
            continue
        selected.append(candidate)
        selected_bytes += candidate_size
    return _BoundedPstExport(
        candidate_paths=tuple(selected),
        stop_reason=stop_reason,
        overflow_count=max(0, len(all_paths) - len(selected)),
        parser_completed=parser_completed,
    )


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _classify_exported_source_units(
    candidate_paths: Sequence[Path],
    *,
    export_root: Path,
    config: _PstParserConfig,
) -> tuple[_PstClassifiedSourceUnit, ...]:
    classified: list[_PstClassifiedSourceUnit] = []
    for source_ordinal, candidate in enumerate(candidate_paths, start=1):
        source_local_key = _exported_message_source_local_key(
            candidate,
            export_root=export_root,
            message_index=source_ordinal,
        )
        try:
            size_bytes = candidate.stat().st_size
        except OSError:
            classified.append(
                _PstClassifiedSourceUnit(
                    source_local_key=source_local_key,
                    processing_state=SourceInventoryProcessingState.FAILED,
                    content_type="application/octet-stream",
                    parsed_message=None,
                )
            )
            continue
        if size_bytes > config.max_message_file_bytes:
            classified.append(
                _PstClassifiedSourceUnit(
                    source_local_key=source_local_key,
                    processing_state=(SourceInventoryProcessingState.PRESERVED_UNPARSED),
                    content_type="application/octet-stream",
                    parsed_message=None,
                )
            )
            continue
        try:
            message = BytesParser(policy=policy.default).parsebytes(candidate.read_bytes())
        except Exception:
            classified.append(
                _PstClassifiedSourceUnit(
                    source_local_key=source_local_key,
                    processing_state=SourceInventoryProcessingState.FAILED,
                    content_type="application/octet-stream",
                    parsed_message=None,
                )
            )
            continue
        if not _is_mail_message(message):
            classified.append(
                _PstClassifiedSourceUnit(
                    source_local_key=source_local_key,
                    processing_state=SourceInventoryProcessingState.UNSUPPORTED,
                    content_type=_safe_mail_text(
                        message.get_content_type(),
                        "source_content_type",
                    )
                    or "application/octet-stream",
                    parsed_message=None,
                )
            )
            continue
        warnings: list[str] = []
        parsed_message = _parsed_message_from_email(
            message,
            candidate_path=candidate,
            export_root=export_root,
            message_index=source_ordinal,
            config=config,
            warnings=warnings,
        )
        if parsed_message.source_local_key != source_local_key:
            raise ValueError("pst_source_inventory_key_drift")
        classified.append(
            _PstClassifiedSourceUnit(
                source_local_key=source_local_key,
                processing_state=SourceInventoryProcessingState.PARSED,
                content_type="message/rfc822",
                parsed_message=parsed_message,
            )
        )
    return tuple(classified)


def _pst_source_inventory_from_classified_units(
    units: Sequence[_PstClassifiedSourceUnit],
    *,
    source_asset_id: str,
    source_fingerprint: str,
    parser_fingerprint: str,
    permission_scope: Mapping[str, Any],
    created_at: str,
) -> SourceInventory:
    root_source_local_key = stable_resource_contract_id(
        "pstroot",
        "PstSourceInventoryRoot",
        {
            "source_asset_id": source_asset_id,
            "source_fingerprint": source_fingerprint,
        },
    )
    inventory_items: list[SourceInventoryItem] = []
    item_ordinal = 0
    for unit in units:
        item_ordinal += 1
        structure_kind = (
            "exported_message_occurrence"
            if unit.processing_state == SourceInventoryProcessingState.PARSED
            else "exported_source_unit"
        )
        inventory_items.append(
            SourceInventoryItem.create(
                source_asset_id=source_asset_id,
                structure_kind=structure_kind,
                content_type=unit.content_type,
                ordinal=item_ordinal,
                processing_state=unit.processing_state,
                raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
                source_fingerprint=source_fingerprint,
                parser_fingerprint=parser_fingerprint,
                permission_scope=permission_scope,
                location={
                    "source_local_key": unit.source_local_key,
                    "parent_source_local_key": root_source_local_key,
                },
            )
        )
        if unit.parsed_message is None:
            continue
        for attachment_ordinal, attachment in enumerate(
            unit.parsed_message.attachments,
            start=1,
        ):
            if not attachment.source_name_fingerprint:
                raise ValueError("pst_attachment_source_name_fingerprint_missing")
            attachment_source_local_key = stable_resource_contract_id(
                "pstattsrc",
                "PstAttachmentSourceOccurrence",
                {
                    "parent_source_local_key": unit.source_local_key,
                    "attachment_id": attachment.attachment_id,
                    "attachment_ordinal": attachment_ordinal,
                    "attachment_name_fingerprint": (attachment.source_name_fingerprint),
                },
            )
            item_ordinal += 1
            inventory_items.append(
                SourceInventoryItem.create(
                    source_asset_id=source_asset_id,
                    structure_kind="regular_attachment_occurrence",
                    content_type=attachment.mime_type or "application/octet-stream",
                    ordinal=item_ordinal,
                    processing_state=SourceInventoryProcessingState.PARSED,
                    raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
                    source_fingerprint=source_fingerprint,
                    parser_fingerprint=parser_fingerprint,
                    permission_scope=permission_scope,
                    location={
                        "source_local_key": attachment_source_local_key,
                        "parent_source_local_key": unit.source_local_key,
                        "attachment_id": attachment.attachment_id,
                        "attachment_ordinal": attachment_ordinal,
                        "attachment_name_fingerprint": (attachment.source_name_fingerprint),
                    },
                )
            )
    return SourceInventory.create(
        source_asset_id=source_asset_id,
        items=inventory_items,
        source_fingerprint=source_fingerprint,
        parser_fingerprint=parser_fingerprint,
        created_at=created_at,
        permission_fingerprint=sha256_json(permission_scope),
    )


def _persist_source_inventory_round_trip(
    source_inventory: SourceInventory,
    inventory_path: Path,
) -> SourceInventory:
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        inventory_path.parent.chmod(0o700)
    temporary = inventory_path.with_name(inventory_path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(
        json.dumps(source_inventory.to_dict(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, inventory_path)
    persisted = json.loads(inventory_path.read_text(encoding="utf-8"))
    return SourceInventory.from_dict(persisted)


def reconcile_pst_source_inventory(
    source_inventory: SourceInventory,
    observations: Sequence[Observation],
    *,
    bounded_source_unit_count: int,
    bounded_overflow_count: int,
    parser_stop_reason: str,
    parser_completed: bool,
    persisted_round_trip_verified: bool,
) -> dict[str, Any]:
    processing_state_counts = {state.value: 0 for state in SourceInventoryProcessingState}
    raw_retention_state_counts = {state.value: 0 for state in SourceInventoryRawRetentionState}
    for item in source_inventory.items:
        processing_state_counts[item.processing_state.value] += 1
        raw_retention_state_counts[item.raw_retention_state.value] += 1

    expected_ids = {
        item.source_inventory_item_id
        for item in source_inventory.items
        if item.processing_state == SourceInventoryProcessingState.PARSED
        and item.structure_kind in {"exported_message_occurrence", "regular_attachment_occurrence"}
    }
    referenced_ids: set[str] = set()
    for observation in observations:
        if observation.observation_type not in {
            "email_message",
            "email_attachment_occurrence",
        }:
            continue
        payload = observation.payload or {}
        item_id = payload.get("source_inventory_item_id")
        if isinstance(item_id, str) and item_id:
            referenced_ids.add(item_id)
    matched_ids = expected_ids & referenced_ids
    unexplained_loss_count = len(expected_ids - matched_ids)
    unexpected_reference_count = len(referenced_ids - expected_ids)
    report: dict[str, Any] = {
        "artifact_id": "issue56_source_completeness_diagnostic_v1",
        "status": ("diagnostic_partial" if source_inventory.items else "diagnostic_blocked"),
        "source_inventory_fingerprint": sha256_json(source_inventory.to_dict()),
        "processing_state_counts": processing_state_counts,
        "raw_retention_state_counts": raw_retention_state_counts,
        "inventory_item_count": len(source_inventory.items),
        "bounded_source_unit_count": bounded_source_unit_count,
        "bounded_overflow_count": bounded_overflow_count,
        "expected_observation_binding_count": len(expected_ids),
        "matched_observation_binding_count": len(matched_ids),
        "unexplained_loss_count": unexplained_loss_count,
        "unexpected_observation_reference_count": unexpected_reference_count,
        "parser_stop_status": parser_stop_reason,
        "parser_completed_metric": parser_completed,
        "persisted_round_trip_verified_metric": persisted_round_trip_verified,
        "claim_boundary": {
            "source_complete": False,
            "real_source_authority_gate_passed": False,
            "diagnostic_partial_only": True,
        },
    }
    report["report_fingerprint"] = sha256_json(report)
    assert_no_public_raw_references(report, "issue56_source_completeness_report")
    return report


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
) -> list[str]:
    command = [parser_command, "-S", "-o", str(output_dir)]
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
        max_body_segments_per_message=_positive_int(
            config.get("max_body_segments_per_message", 3),
            "max_body_segments_per_message",
        ),
        max_attachment_hash_bytes=_positive_int(
            config.get("max_attachment_hash_bytes", 5 * 1024 * 1024),
            "max_attachment_hash_bytes",
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
    export_root: Path,
    *,
    config: _PstParserConfig,
) -> tuple[list[_ParsedMessage], list[str]]:
    if config.parser_workers > 1 and config.max_messages is None:
        return _parse_exported_messages_parallel(export_root, config=config)
    parsed: list[_ParsedMessage] = []
    warnings: list[str] = []
    for candidate in _iter_exported_files(export_root):
        if config.max_messages is not None and len(parsed) >= config.max_messages:
            break
        try:
            if candidate.stat().st_size > config.max_message_file_bytes:
                warnings.append("pst_parser_large_message_file_skipped")
                continue
            message = BytesParser(policy=policy.default).parsebytes(candidate.read_bytes())
        except Exception:
            warnings.append("pst_parser_message_file_skipped")
            continue
        if not _is_mail_message(message):
            continue
        parsed_message = _parsed_message_from_email(
            message,
            candidate_path=candidate,
            export_root=export_root,
            message_index=len(parsed) + 1,
            config=config,
            warnings=warnings,
        )
        parsed.append(parsed_message)
    return parsed, warnings


def _parse_exported_messages_parallel(
    export_root: Path,
    *,
    config: _PstParserConfig,
) -> tuple[list[_ParsedMessage], list[str]]:
    candidates = list(_iter_exported_files(export_root))
    parsed: list[_ParsedMessage] = []
    warnings: list[str] = []
    executor_type = ThreadPoolExecutor if os.name == "nt" else ProcessPoolExecutor
    with executor_type(max_workers=config.parser_workers) as executor:
        results = executor.map(
            _parse_exported_message_file_job,
            (
                (candidate, export_root, index + 1, config)
                for index, candidate in enumerate(candidates)
            ),
            chunksize=25,
        )
        for parsed_message, parse_warnings in results:
            warnings.extend(parse_warnings)
            if parsed_message is not None:
                parsed.append(parsed_message)
    return parsed, warnings


def _parse_exported_message_file_job(
    args: tuple[Path, Path, int, _PstParserConfig],
) -> tuple[_ParsedMessage | None, list[str]]:
    candidate, export_root, message_index, config = args
    return _parse_exported_message_file(
        candidate,
        export_root=export_root,
        message_index=message_index,
        config=config,
    )


def _parse_exported_message_file(
    candidate: Path,
    *,
    export_root: Path,
    message_index: int,
    config: _PstParserConfig,
) -> tuple[_ParsedMessage | None, list[str]]:
    warnings: list[str] = []
    try:
        if candidate.stat().st_size > config.max_message_file_bytes:
            return None, ["pst_parser_large_message_file_skipped"]
        message = BytesParser(policy=policy.default).parsebytes(candidate.read_bytes())
    except Exception:
        return None, ["pst_parser_message_file_skipped"]
    if not _is_mail_message(message):
        return None, []
    parsed_message = _parsed_message_from_email(
        message,
        candidate_path=candidate,
        export_root=export_root,
        message_index=message_index,
        config=config,
        warnings=warnings,
    )
    return parsed_message, warnings


def _iter_exported_files(export_root: Path) -> Iterable[Path]:
    stack = [export_root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in reversed(children):
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                yield child


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
    source_local_key_override: str | None = None,
    folder_path_hash_override: str | None = None,
    folder_label_override: str | None = None,
    message_id_fallback_parts: tuple[Any, ...] | None = None,
    include_attachments: bool = True,
) -> _ParsedMessage:
    relative_parent = _safe_relative_parent(candidate_path, export_root)
    source_local_key = source_local_key_override or _exported_message_source_local_key(
        candidate_path,
        export_root=export_root,
        message_index=message_index,
    )
    folder_label = folder_label_override or _folder_label(relative_parent)
    folder_path_hash = folder_path_hash_override or sha256_json(
        str(relative_parent).replace("\\", "/")
    )
    subject = _safe_mail_text(message.get("subject") or "", "subject")
    sender = _safe_mail_text(message.get("from") or "", "sender")
    sent_at = _safe_date(message.get("date") or "")
    raw_body = _plain_body(message)
    body_hash = sha256_json(raw_body)
    body_segments = _safe_body_segments(
        raw_body,
        max_chars=config.body_segment_max_chars,
        max_segments=config.max_body_segments_per_message,
        warnings=warnings,
    )
    message_id = _message_id(
        message,
        fallback_parts=message_id_fallback_parts or (folder_path_hash, message_index, body_hash),
    )
    headers = _safe_headers(message, warnings=warnings)
    references = _safe_header_tokens(message.get("references") or "", "references")
    in_reply_to = _safe_optional_header(message.get("in-reply-to"), "in_reply_to")
    attachments = (
        _attachments(message, config=config, warnings=warnings) if include_attachments else []
    )
    return _ParsedMessage(
        source_local_key=source_local_key,
        folder_path_hash=folder_path_hash,
        folder_label=folder_label,
        message_id=message_id,
        subject=subject,
        normalized_subject=_normalize_subject(subject),
        sender=sender,
        sent_at=sent_at,
        headers=headers,
        body_segments=body_segments,
        body_hash=body_hash,
        attachments=attachments,
        references=references,
        in_reply_to=in_reply_to,
    )


def _safe_relative_parent(candidate_path: Path, export_root: Path) -> Path:
    try:
        relative = candidate_path.parent.relative_to(export_root)
    except ValueError:
        return Path("mailbox")
    return relative if str(relative) not in {"", "."} else Path("mailbox")


def _folder_label(relative_parent: Path) -> str:
    label = " / ".join(part for part in relative_parent.parts if part not in {"", "."})
    return _safe_mail_text(label or "Mailbox", "folder_label")


def _exported_message_source_local_key(
    candidate_path: Path,
    *,
    export_root: Path,
    message_index: int,
) -> str:
    try:
        relative_file = candidate_path.relative_to(export_root)
        relative_file_fingerprint = sha256_json(str(relative_file).replace("\\", "/"))
    except ValueError:
        relative_file_fingerprint = sha256_json({"external_export_candidate": message_index})
    return stable_resource_contract_id(
        "pstmsgsrc",
        "PstExportedMessageSourceOccurrence",
        {
            "relative_file_fingerprint": relative_file_fingerprint,
            "message_index": message_index,
        },
    )


def _message_id(message: EmailMessage, *, fallback_parts: tuple[Any, ...]) -> str:
    value = str(message.get("message-id") or "").strip()
    if value:
        return _safe_mail_text(value, "message_id")
    return stable_resource_contract_id("mailmsg", "PstMessage", {"fallback": fallback_parts})


def _safe_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return _safe_mail_text(text, "date")
    return parsed.isoformat()


def _safe_headers(message: EmailMessage, *, warnings: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in message.items():
        header_name = str(name).strip().lower()
        if header_name not in _SAFE_HEADER_NAMES:
            continue
        safe_name = _safe_header_name(header_name)
        try:
            headers[safe_name] = _safe_mail_text(str(value), f"header_{safe_name}")
        except ValueError:
            warnings.append("pst_parser_header_redacted")
    if "message-id" not in headers and message.get("message-id"):
        headers["message-id"] = _message_id(message, fallback_parts=("header",))
    return headers


def _safe_header_name(name: str) -> str:
    assert_no_public_raw_references(name, "pst_mail_header_name")
    return name


def _safe_header_tokens(value: str, field_name: str) -> list[str]:
    tokens = [item for item in re.split(r"\s+", str(value or "").strip()) if item]
    return [_safe_mail_text(token, field_name) for token in tokens[:25]]


def _safe_optional_header(value: str | None, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    return _safe_mail_text(str(value), field_name)


def _safe_mail_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
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


def _plain_body(message: EmailMessage) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        if disposition == "attachment":
            continue
        content_type = part.get_content_type()
        try:
            content = part.get_content()
        except Exception:
            continue
        if not isinstance(content, str):
            continue
        if content_type == "text/plain":
            plain_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(_html_to_text(content))
    body = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if body:
        return body
    return "\n\n".join(part.strip() for part in html_parts if part.strip())


def _safe_body_segments(
    text: str,
    *,
    max_chars: int,
    max_segments: int,
    warnings: list[str],
) -> list[str]:
    segments: list[str] = []
    for paragraph in _body_paragraphs(text):
        if len(segments) >= max_segments:
            warnings.append("pst_parser_body_segment_limit_reached")
            break
        for chunk in _chunks(paragraph, max_chars):
            if len(segments) >= max_segments:
                warnings.append("pst_parser_body_segment_limit_reached")
                break
            segments.append(_safe_body_segment(chunk, warnings=warnings))
    return segments


def _body_paragraphs(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", normalized) if item.strip()]
    if paragraphs:
        return paragraphs
    single = normalized.strip()
    return [single] if single else []


def _chunks(value: str, size: int) -> Iterable[str]:
    for start in range(0, len(value), size):
        chunk = value[start : start + size].strip()
        if chunk:
            yield chunk


def _safe_body_segment(value: str, *, warnings: list[str]) -> str:
    try:
        assert_no_public_raw_references(value, "pst_mail_body_segment")
    except Exception:
        warnings.append("pst_parser_body_segment_redacted")
        return f"redacted_mail_body_segment {sha256_json(value)}"
    return value


def _attachments(
    message: EmailMessage,
    *,
    config: _PstParserConfig,
    warnings: list[str],
) -> list[_ParsedAttachment]:
    attachments: list[_ParsedAttachment] = []
    for part in message.walk() if message.is_multipart() else []:
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if not filename and disposition != "attachment":
            continue
        attachment_index = len(attachments) + 1
        source_filename = str(filename or f"attachment-{attachment_index}")
        safe_filename = _safe_mail_text(source_filename, "filename")
        source_name_fingerprint = sha256_json(source_filename)
        payload = part.get_payload(decode=True)
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
                source_name_fingerprint=source_name_fingerprint,
                mime_type=_safe_mail_text(part.get_content_type(), "attachment_mime_type"),
                content_hash=content_hash,
                size_bytes=size_bytes,
                content_bytes=payload if content_hash is not None else None,
            )
        )
    return attachments


def _pst_source_inventory(
    messages: Sequence[_ParsedMessage],
    *,
    extraction_input: ExtractionInput,
    parser_name: str,
    parser_version: str,
    config: _PstParserConfig,
) -> SourceInventory:
    source_fingerprint = extraction_input.asset.content_hash
    parser_fingerprint = stable_resource_contract_hash(
        "PstSourceInventoryParserProfile",
        {
            "parser_name": parser_name,
            "parser_version": parser_version,
            "parser_config": {
                "max_messages": config.max_messages,
                "max_message_file_bytes": config.max_message_file_bytes,
                "body_segment_max_chars": config.body_segment_max_chars,
                "max_body_segments_per_message": config.max_body_segments_per_message,
                "max_attachment_hash_bytes": config.max_attachment_hash_bytes,
                "include_deleted_items": config.include_deleted_items,
            },
        },
    )
    root_source_local_key = stable_resource_contract_id(
        "pstroot",
        "PstSourceInventoryRoot",
        {
            "source_asset_id": extraction_input.asset.asset_id,
            "source_fingerprint": source_fingerprint,
        },
    )
    inventory_items: list[SourceInventoryItem] = []
    item_ordinal = 0
    for message in messages:
        item_ordinal += 1
        inventory_items.append(
            SourceInventoryItem.create(
                source_asset_id=extraction_input.asset.asset_id,
                structure_kind="exported_message_occurrence",
                content_type="message/rfc822",
                ordinal=item_ordinal,
                processing_state=SourceInventoryProcessingState.PARSED,
                raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
                source_fingerprint=source_fingerprint,
                parser_fingerprint=parser_fingerprint,
                permission_scope=extraction_input.asset.permission_scope,
                location={
                    "source_local_key": message.source_local_key,
                    "parent_source_local_key": root_source_local_key,
                },
            )
        )
        for attachment_ordinal, attachment in enumerate(message.attachments, start=1):
            if not attachment.source_name_fingerprint:
                raise ValueError("pst_attachment_source_name_fingerprint_missing")
            attachment_source_local_key = stable_resource_contract_id(
                "pstattsrc",
                "PstAttachmentSourceOccurrence",
                {
                    "parent_source_local_key": message.source_local_key,
                    "attachment_id": attachment.attachment_id,
                    "attachment_ordinal": attachment_ordinal,
                    "attachment_name_fingerprint": attachment.source_name_fingerprint,
                },
            )
            item_ordinal += 1
            inventory_items.append(
                SourceInventoryItem.create(
                    source_asset_id=extraction_input.asset.asset_id,
                    structure_kind="regular_attachment_occurrence",
                    content_type=attachment.mime_type or "application/octet-stream",
                    ordinal=item_ordinal,
                    processing_state=SourceInventoryProcessingState.PARSED,
                    raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
                    source_fingerprint=source_fingerprint,
                    parser_fingerprint=parser_fingerprint,
                    permission_scope=extraction_input.asset.permission_scope,
                    location={
                        "source_local_key": attachment_source_local_key,
                        "parent_source_local_key": message.source_local_key,
                        "attachment_id": attachment.attachment_id,
                        "attachment_ordinal": attachment_ordinal,
                        "attachment_name_fingerprint": (attachment.source_name_fingerprint),
                    },
                )
            )
    return SourceInventory.create(
        source_asset_id=extraction_input.asset.asset_id,
        items=inventory_items,
        source_fingerprint=source_fingerprint,
        parser_fingerprint=parser_fingerprint,
        created_at=extraction_input.created_at or now_iso(),
        permission_fingerprint=sha256_json(extraction_input.asset.permission_scope),
    )


def _mail_observations_from_messages(
    messages: Sequence[_ParsedMessage],
    *,
    extraction_input: ExtractionInput,
    source_inventory: SourceInventory,
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
    message_key_by_occurrence_id = {
        _message_occurrence_id(
            message,
            message_index=message_index,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
        ): message.source_local_key
        for message_index, message in enumerate(messages, start=1)
    }
    inventory_index = _PstAttachmentInventoryIndex.create(
        source_inventory,
        message_key_by_occurrence_id=message_key_by_occurrence_id,
    )
    parsed_observations = list(
        _iter_mail_observations(
            messages,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
            source_inventory=source_inventory,
            inventory_index=inventory_index,
            extraction_input=extraction_input,
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


def _iter_mail_observations(
    messages: Sequence[_ParsedMessage],
    *,
    archive_id: str,
    mailbox_id: str,
    source_inventory: SourceInventory,
    inventory_index: _PstAttachmentInventoryIndex,
    extraction_input: ExtractionInput,
) -> Iterable[dict[str, Any]]:
    folder_labels: dict[str, str] = {}
    for message in messages:
        folder_labels.setdefault(message.folder_path_hash, message.folder_label)
    for folder_index, (folder_path_hash, folder_label) in enumerate(
        sorted(folder_labels.items()),
        start=1,
    ):
        yield {
            "observation_type": "mail_folder_occurrence",
            "text": folder_label,
            "location": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "source_inventory_id": source_inventory.source_inventory_id,
                "folder_path_hash": folder_path_hash,
                "folder_index": folder_index,
            },
            "payload": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "source_inventory_id": source_inventory.source_inventory_id,
                "folder_path_hash": folder_path_hash,
                "folder_label": folder_label,
            },
        }

    thread_payloads = _thread_payloads(messages, archive_id=archive_id, mailbox_id=mailbox_id)
    for thread_index, payload in enumerate(thread_payloads, start=1):
        yield {
            "observation_type": "email_thread",
            "text": payload["normalized_subject"],
            "location": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "source_inventory_id": source_inventory.source_inventory_id,
                "thread_id": payload["thread_id"],
                "thread_index": thread_index,
            },
            "payload": {
                **payload,
                "source_inventory_id": source_inventory.source_inventory_id,
            },
        }

    for message_index, message in enumerate(messages, start=1):
        thread_id = _thread_id(message)
        occurrence_id = _message_occurrence_id(
            message,
            message_index=message_index,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
        )
        message_inventory_item = inventory_index.item_by_key.get(message.source_local_key)
        if (
            message_inventory_item is None
            or message_inventory_item.structure_kind != "exported_message_occurrence"
            or message_inventory_item.processing_state != SourceInventoryProcessingState.PARSED
        ):
            raise ValueError("pst_message_inventory_binding_missing")
        attachment_hashes = sorted(
            attachment.content_hash for attachment in message.attachments if attachment.content_hash
        )
        message_fingerprint = sha256_json(
            {
                "message_id": message.message_id,
                "normalized_subject": message.normalized_subject,
                "sender": message.sender,
                "sent_at": message.sent_at,
                "body_hash": message.body_hash,
                "attachment_hashes": attachment_hashes,
            }
        )
        base_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "source_inventory_id": source_inventory.source_inventory_id,
            "source_inventory_item_id": (message_inventory_item.source_inventory_item_id),
            "folder_path_hash": message.folder_path_hash,
            "message_id": message.message_id,
            "message_occurrence_id": occurrence_id,
            "thread_id": thread_id,
        }
        yield {
            "observation_type": "email_message",
            "text": message.subject,
            "location": {**base_location, "message_index": message_index},
            "payload": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "source_inventory_id": source_inventory.source_inventory_id,
                "source_inventory_item_id": (message_inventory_item.source_inventory_item_id),
                "message_id": message.message_id,
                "message_occurrence_id": occurrence_id,
                "thread_id": thread_id,
                "subject": message.subject,
                "normalized_subject": message.normalized_subject,
                "sender": message.sender,
                "sent_at": message.sent_at,
                "body_hash": message.body_hash,
                "message_fingerprint": message_fingerprint,
                "fingerprint_policy": "formowl_mail_fingerprint_v1",
            },
        }
        for header_index, (header_name, header_value) in enumerate(
            sorted(message.headers.items()),
            start=1,
        ):
            yield {
                "observation_type": "email_header",
                "text": f"{header_name}: {header_value}",
                "location": {
                    **base_location,
                    "header_index": header_index,
                    "header_name": header_name,
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    "thread_id": thread_id,
                    "header_name": header_name,
                    "header_value": header_value,
                },
            }
        for segment_index, body_segment in enumerate(message.body_segments, start=1):
            yield {
                "observation_type": "email_body_segment",
                "text": body_segment,
                "location": {
                    **base_location,
                    "body_segment_index": segment_index,
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    "thread_id": thread_id,
                    "body_segment_index": segment_index,
                    "message_fingerprint": message_fingerprint,
                },
            }
        for attachment_index, attachment in enumerate(message.attachments, start=1):
            binding = _pst_attachment_observation_binding(
                attachment,
                attachment_ordinal=attachment_index,
                context=_PstAttachmentObservationContext(
                    occurrence_id=occurrence_id,
                    parent_occurrence_id=None,
                    message=message,
                ),
                source_inventory=source_inventory,
                inventory_index=inventory_index,
            )
            child_asset_id = None
            if (
                extraction_input.attachment_materialization is not None
                and attachment.content_bytes is not None
                and attachment.content_hash is not None
            ):
                child_asset_id = extraction_input.attachment_materialization.materialize(
                    content=attachment.content_bytes,
                    expected_content_hash=attachment.content_hash,
                    mime_type=attachment.mime_type or "application/octet-stream",
                    source_ref=SourceRef(
                        source_system="formowl_mail_attachment",
                        source_type="email_attachment_occurrence",
                        source_id=binding["source_inventory_item_id"],
                        source_instance=binding["source_inventory_id"],
                        source_key=occurrence_id,
                    ),
                )
            child_binding = (
                {"child_asset_id": child_asset_id} if child_asset_id is not None else {}
            )
            yield {
                "observation_type": "email_attachment_occurrence",
                "text": attachment.filename,
                "location": {
                    **base_location,
                    "attachment_index": attachment_index,
                    "attachment_id": attachment.attachment_id,
                    **binding,
                    **child_binding,
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    "thread_id": thread_id,
                    "attachment_id": attachment.attachment_id,
                    **binding,
                    **child_binding,
                    "filename": attachment.filename,
                    "mime_type": attachment.mime_type,
                    "content_hash": attachment.content_hash,
                    "size_bytes": attachment.size_bytes,
                    "message_fingerprint": message_fingerprint,
                },
            }


def _message_occurrence_id(
    message: _ParsedMessage,
    *,
    message_index: int,
    archive_id: str,
    mailbox_id: str,
) -> str:
    return stable_resource_contract_id(
        "mailocc",
        "PstMessageOccurrence",
        {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": message.folder_path_hash,
            "message_id": message.message_id,
            "message_index": message_index,
        },
    )


def _pst_attachment_observation_binding(
    attachment: _ParsedAttachment,
    *,
    attachment_ordinal: int,
    context: Any,
    source_inventory: SourceInventory,
    inventory_index: _PstAttachmentInventoryIndex,
) -> dict[str, str]:
    if not isinstance(attachment_ordinal, int) or isinstance(attachment_ordinal, bool):
        raise ValueError("pst_attachment_ordinal_invalid")
    if attachment_ordinal < 1:
        raise ValueError("pst_attachment_ordinal_invalid")
    parent_source_local_key = getattr(
        getattr(context, "message", None),
        "source_local_key",
        None,
    )
    occurrence_id = getattr(context, "occurrence_id", None)
    if not isinstance(parent_source_local_key, str) or not parent_source_local_key:
        raise ValueError("pst_attachment_parent_source_local_key_missing")
    if not isinstance(occurrence_id, str) or not occurrence_id:
        raise ValueError("pst_attachment_parent_occurrence_missing")
    indexed_parent_key = inventory_index.message_key_by_occurrence_id.get(occurrence_id)
    if indexed_parent_key != parent_source_local_key:
        raise ValueError("pst_attachment_parent_inventory_mismatch")
    if not attachment.source_name_fingerprint:
        raise ValueError("pst_attachment_source_name_fingerprint_missing")

    parent_candidates = inventory_index.attachment_items_by_parent_message_key.get(
        parent_source_local_key,
        (),
    )
    id_candidates = inventory_index.attachment_items_by_id.get(
        attachment.attachment_id,
        (),
    )
    ordinal_candidates = inventory_index.attachment_items_by_id_and_ordinal.get(
        (attachment.attachment_id, attachment_ordinal),
        (),
    )
    parent_ids = {item.source_inventory_item_id for item in parent_candidates}
    id_ids = {item.source_inventory_item_id for item in id_candidates}
    ordinal_ids = {item.source_inventory_item_id for item in ordinal_candidates}
    matches = [
        item
        for item in parent_candidates
        if item.source_inventory_item_id in id_ids
        and item.source_inventory_item_id in ordinal_ids
        and item.source_inventory_item_id in parent_ids
        and item.location.get("parent_source_local_key") == parent_source_local_key
        and item.location.get("attachment_id") == attachment.attachment_id
        and item.location.get("attachment_ordinal") == attachment_ordinal
        and item.location.get("attachment_name_fingerprint") == attachment.source_name_fingerprint
        and isinstance(item.location.get("source_local_key"), str)
        and bool(item.location.get("source_local_key"))
        and item.processing_state == SourceInventoryProcessingState.PARSED
    ]
    if len(matches) != 1:
        raise ValueError("pst_attachment_inventory_binding_not_unique")
    parent_item = inventory_index.item_by_key.get(parent_source_local_key)
    if parent_item is None or parent_item.processing_state != SourceInventoryProcessingState.PARSED:
        raise ValueError("pst_attachment_parent_inventory_item_missing")
    match = matches[0]
    if match.source_asset_id != source_inventory.source_asset_id:
        raise ValueError("pst_attachment_inventory_source_mismatch")
    if match.permission_fingerprint != source_inventory.permission_fingerprint:
        raise ValueError("pst_attachment_inventory_permission_mismatch")
    return {
        "source_inventory_id": source_inventory.source_inventory_id,
        "source_inventory_item_id": match.source_inventory_item_id,
        "attachment_inventory_item_id": match.source_inventory_item_id,
        "parent_inventory_item_id": parent_item.source_inventory_item_id,
    }


def _thread_payloads(
    messages: Sequence[_ParsedMessage],
    *,
    archive_id: str,
    mailbox_id: str,
) -> list[dict[str, Any]]:
    threads: dict[str, dict[str, Any]] = {}
    for message in messages:
        thread_id = _thread_id(message)
        thread = threads.setdefault(
            thread_id,
            {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "thread_id": thread_id,
                "normalized_subject": message.normalized_subject,
                "message_ids": [],
                "participants": [],
                "sent_at_values": [],
                "thread_identity_policy": "formowl_mail_thread_identity_v1",
            },
        )
        thread["message_ids"].append(message.message_id)
        if message.sender and message.sender not in thread["participants"]:
            thread["participants"].append(message.sender)
        if message.sent_at:
            thread["sent_at_values"].append(message.sent_at)
    results: list[dict[str, Any]] = []
    for thread in threads.values():
        sent_at_values = sorted(thread.pop("sent_at_values"))
        if sent_at_values:
            thread["first_sent_at"] = sent_at_values[0]
            thread["last_sent_at"] = sent_at_values[-1]
        thread["message_count"] = len(thread["message_ids"])
        results.append(thread)
    return sorted(results, key=lambda item: item["thread_id"])


def _thread_id(message: _ParsedMessage) -> str:
    if message.references:
        return stable_resource_contract_id(
            "mailthread",
            "PstThread",
            {"references": message.references},
        )
    if message.in_reply_to:
        return stable_resource_contract_id(
            "mailthread",
            "PstThread",
            {"in_reply_to": message.in_reply_to},
        )
    return stable_resource_contract_id(
        "mailthread",
        "PstThread",
        {"normalized_subject": message.normalized_subject or message.message_id},
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
    "NativePstAttachmentExport",
    "NativePstMessageExport",
    "NativePstParsedEvidenceResult",
    "PstMailArchiveExtractor",
    "PstSourceCompletenessPocResult",
    "parse_native_pst_message_exports",
    "reconcile_pst_source_inventory",
    "run_bounded_pst_source_completeness_poc",
]
