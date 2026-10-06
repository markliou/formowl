"""Private UAT-only MCP for bounded reads from an existing table export.

This module deliberately consumes one frozen JSON snapshot.  It does not
import or invoke PST parsers, extractors, graph retrieval, ontology, review
artifacts, reconciliation artifacts, or answer oracles.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import threading
from time import perf_counter
from typing import Any, Mapping, Sequence
import unicodedata
from urllib.parse import urlparse

from formowl_contract import ContractValidationError, sha256_json

if __package__:
    from ._guards import (
        assert_authorized_evidence_text_safe,
        assert_public_payload_safe,
    )
else:
    # Direct-file deployment deliberately avoids importing formowl_mail and
    # therefore its package initializer.  Python places this file's directory
    # on sys.path, so the fallback remains bound to the sibling guard module.
    from _guards import (  # type: ignore[import-not-found]
        assert_authorized_evidence_text_safe,
        assert_public_payload_safe,
    )

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = "formowl-document-uat"
MCP_TOOL_NAME = "read_authorized_documents"
_SNAPSHOT_ARTIFACT_TYPE = "formowl_diagnostic_current_export_table_snapshot_v2"
_MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
_MAX_HTTP_REQUEST_BYTES = 32 * 1024
_MAX_QUERY_CHARS = 500
_MAX_REQUIRED_TERMS = 12
_MAX_REQUIRED_TERM_CHARS = 120
_MAX_RESULT_ITEMS = 30
_MAX_SEGMENT_CHARS = 1_600
_MAX_TOTAL_CONTENT_CHARS = 48_000
_MAX_SEGMENT_UTF8_BYTES = _MAX_SEGMENT_CHARS * 4
_MAX_TOTAL_CONTENT_UTF8_BYTES = _MAX_TOTAL_CONTENT_CHARS * 4
_ROW_CONTEXT_BEFORE = 1
_ROW_CONTEXT_AFTER = 2
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_AUTHORIZATION_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_ASCII_TERM_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9_.:/-]{1,}(?![A-Za-z0-9])")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]{2,}")
_AUTHORIZATION_BINDING_TYPE = "formowl_document_uat_authorization_binding_v1"
_PUBLIC_PROJECTION_TYPE = "formowl_document_uat_public_metadata_v1"
_STARTUP_FAILURE_MESSAGE = "document UAT MCP startup validation failed"
_DOCUMENT_OS_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9._-])(?:"
    r"/(?:dev|etc|home|mnt|opt|proc|root|run|srv|sys|tmp|var|workspace)(?:/|$)"
    r"[^\s'\"<>]*|"
    r"[A-Za-z]:\\(?:Documents and Settings|ProgramData|Users|Windows)(?:\\|$)"
    r"[^\s'\"<>]*"
    r")",
    re.IGNORECASE,
)
_DOCUMENT_LOCAL_LOCATOR_TOKEN = re.compile(
    r"\b(?:"
    r"(?:https?|wss?)://(?:localhost|0\.0\.0\.0|127(?:\.\d{1,3}){3}|\[::1\])"
    r"(?::\d+)?(?:/|$)|"
    r"(?:local|object-store|object_store)://[^\s'\"<>]+"
    r")",
    re.IGNORECASE,
)
_DOCUMENT_RESPONSE_KEYS = frozenset(
    {
        "answerability",
        "claim_boundary",
        "coverage",
        "displayed_result_count",
        "mcp_response_commitment",
        "notice",
        "projection",
        "query_hash",
        "result_count",
        "results",
        "source_commitment",
        "status",
        "timings_ms",
        "total_result_count",
        "warnings",
    }
)
_DOCUMENT_RESULT_KEYS = frozenset(
    {
        "content",
        "content_char_count",
        "content_sha256",
        "content_utf8_bytes",
        "segment_label",
        "sent_at",
        "snippet",
        "source_kind",
        "source_label",
        "subject",
    }
)
_DOCUMENT_PUBLIC_RESPONSE_KEYS = frozenset(
    (_DOCUMENT_RESPONSE_KEYS - {"mcp_response_commitment"})
    | {"document_payload_projection", "mcp_response_commitment"}
)
_DOCUMENT_PUBLIC_RESULT_KEYS = _DOCUMENT_RESULT_KEYS - {"content", "snippet"}
_STOP_TERMS = frozenset(
    {
        "all",
        "and",
        "answer",
        "document",
        "documents",
        "find",
        "for",
        "from",
        "please",
        "read",
        "show",
        "table",
        "tables",
        "the",
        "what",
        "which",
        "with",
        "內容",
        "回答",
        "文件",
        "資料",
        "表格",
        "請問",
    }
)


@dataclass(frozen=True)
class _TableRow:
    row_ordinal: int
    cells: tuple[tuple[int, str], ...]
    normalized_text: str


@dataclass(frozen=True)
class _AuthorizedTable:
    table_ordinal: int
    headers: tuple[tuple[int, str], ...]
    rows: tuple[_TableRow, ...]
    normalized_text: str


class AuthorizedDocumentSnapshot:
    """Hash-bound, value-bearing table snapshot available only to private UAT."""

    def __init__(
        self,
        *,
        source_commitment: str,
        tables: Sequence[_AuthorizedTable],
    ) -> None:
        if not _SHA256_RE.fullmatch(source_commitment):
            raise ContractValidationError("document snapshot commitment is invalid")
        if not tables:
            raise ContractValidationError("document snapshot contains no tables")
        self.source_commitment = source_commitment
        self.tables = tuple(tables)

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        expected_sha256: str,
        expected_workspace_id: str | None = None,
        expected_actor_user_id: str | None = None,
    ) -> "AuthorizedDocumentSnapshot":
        source = Path(path)
        if (
            not source.is_absolute()
            or source.is_symlink()
            or not source.is_file()
            or not _SHA256_RE.fullmatch(expected_sha256)
        ):
            raise ContractValidationError("document snapshot input is invalid")
        raw = source.read_bytes()
        if not raw or len(raw) > _MAX_SNAPSHOT_BYTES:
            raise ContractValidationError("document snapshot size is invalid")
        actual_sha256 = "sha256:" + hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ContractValidationError("document snapshot hash does not match")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractValidationError("document snapshot JSON is invalid") from exc
        if (expected_workspace_id is None) != (expected_actor_user_id is None):
            raise ContractValidationError("document snapshot authorization binding is invalid")
        if expected_workspace_id is not None and expected_actor_user_id is not None:
            workspace_id, actor_user_id = _snapshot_authorization(payload)
            if workspace_id != _authorization_identifier(
                expected_workspace_id,
                "workspace",
            ) or actor_user_id != _authorization_identifier(expected_actor_user_id, "actor"):
                raise ContractValidationError("document snapshot authorization does not match")
        tables = _parse_snapshot(payload)
        return cls(source_commitment=actual_sha256, tables=tables)


class AuthorizedDocumentMcpService:
    """One-tool MCP service over a frozen authorized document snapshot."""

    def __init__(
        self,
        snapshot: AuthorizedDocumentSnapshot,
        *,
        authorization_binding_commitment: str | None = None,
    ) -> None:
        if not isinstance(snapshot, AuthorizedDocumentSnapshot):
            raise ContractValidationError("document MCP snapshot is invalid")
        if authorization_binding_commitment is None:
            authorization_binding_commitment = sha256_json(
                {
                    "artifact_type": "formowl_document_uat_in_process_binding_v1",
                    "snapshot_sha256": snapshot.source_commitment,
                }
            )
        if not _SHA256_RE.fullmatch(authorization_binding_commitment):
            raise ContractValidationError("document MCP authorization binding is invalid")
        self.snapshot = snapshot
        self.authorization_binding_commitment = authorization_binding_commitment
        self._successful_call_count = 0
        self._lock = threading.Lock()

    @property
    def successful_call_count(self) -> int:
        with self._lock:
            return self._successful_call_count

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "snapshot_sha256": self.snapshot.source_commitment,
            "authorization_binding_sha256": self.authorization_binding_commitment,
            "table_count": len(self.snapshot.tables),
            "tool_count": 1,
            "successful_mcp_call_count": self.successful_call_count,
        }

    def handle_jsonrpc(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, Mapping) or request.get("jsonrpc") != "2.0":
            return _error_response(request.get("id"), -32600, "Invalid Request")
        request_id = request.get("id")
        method = request.get("method")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return _result_response(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": MCP_SERVER_NAME,
                        "version": "0.1.0",
                    },
                },
            )
        if method == "tools/list":
            return _result_response(
                request_id,
                {
                    "tools": [
                        {
                            "name": MCP_TOOL_NAME,
                            "description": (
                                "Read bounded authorized document/table segments "
                                "from one frozen existing export."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query_text": {"type": "string"},
                                    "required_terms": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "maxItems": _MAX_REQUIRED_TERMS,
                                    },
                                    "limit": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "maximum": _MAX_RESULT_ITEMS,
                                    },
                                },
                                "required": ["query_text", "required_terms", "limit"],
                                "additionalProperties": False,
                            },
                        }
                    ]
                },
            )
        if method != "tools/call":
            return _error_response(request_id, -32601, "Method not found")
        params = request.get("params")
        if not isinstance(params, Mapping) or set(params) != {"name", "arguments"}:
            return _tool_error_response(request_id, "invalid_tool_request")
        if params.get("name") != MCP_TOOL_NAME:
            return _tool_error_response(request_id, "unknown_tool")
        arguments = params.get("arguments")
        try:
            query_text, required_terms, limit = _validate_tool_arguments(arguments)
            payload = self._read_documents(
                query_text=query_text,
                required_terms=required_terms,
                limit=limit,
            )
        except (ContractValidationError, ValueError):
            return _tool_error_response(request_id, "request_rejected")
        with self._lock:
            self._successful_call_count += 1
        return _tool_result_response(request_id, payload)

    def _read_documents(
        self,
        *,
        query_text: str,
        required_terms: tuple[str, ...],
        limit: int,
    ) -> dict[str, Any]:
        started = perf_counter()
        terms = _query_terms(query_text, required_terms)
        candidates: list[tuple[int, int, int]] = []
        for table_index, table in enumerate(self.snapshot.tables):
            required_supported = all(term in table.normalized_text for term in required_terms)
            if required_terms and not required_supported:
                continue
            header_text = _normalize_text(" ".join(value for _, value in table.headers))
            for row_index, row in enumerate(table.rows):
                searchable = f"{header_text} {row.normalized_text}".strip()
                hit_count = sum(term in searchable for term in terms)
                required_row_hits = sum(term in searchable for term in required_terms)
                if hit_count or (not terms and row_index == 0):
                    candidates.append(
                        (
                            required_row_hits * 100 + hit_count,
                            table_index,
                            row_index,
                        )
                    )
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        selected: list[tuple[int, int]] = []
        for _score, table_index, row_index in candidates:
            key = (table_index, row_index)
            if key not in selected:
                selected.append(key)
            if len(selected) >= limit:
                break

        results: list[dict[str, Any]] = []
        total_content_chars = 0
        total_content_utf8_bytes = 0
        for table_index, row_index in selected:
            table = self.snapshot.tables[table_index]
            start = max(0, row_index - _ROW_CONTEXT_BEFORE)
            end = min(len(table.rows), row_index + _ROW_CONTEXT_AFTER + 1)
            content = _render_table_segment(table, start=start, end=end)
            remaining_chars = _MAX_TOTAL_CONTENT_CHARS - total_content_chars
            remaining_utf8_bytes = _MAX_TOTAL_CONTENT_UTF8_BYTES - total_content_utf8_bytes
            if remaining_chars <= 0 or remaining_utf8_bytes <= 0:
                break
            content = _bounded_document_content(
                content,
                max_chars=min(_MAX_SEGMENT_CHARS, remaining_chars),
                max_utf8_bytes=min(_MAX_SEGMENT_UTF8_BYTES, remaining_utf8_bytes),
            )
            content_char_count, content_utf8_bytes, content_sha256 = _validated_document_content(
                content,
                context=f"document_uat_mcp_response.results[{len(results)}].content",
            )
            total_content_chars += content_char_count
            total_content_utf8_bytes += content_utf8_bytes
            results.append(
                {
                    "source_label": f"authorized-document-{table.table_ordinal:04d}",
                    "segment_label": (
                        f"table-{table.table_ordinal:04d}-rows-"
                        f"{table.rows[start].row_ordinal:04d}-"
                        f"{table.rows[end - 1].row_ordinal:04d}"
                    ),
                    "subject": f"Authorized document table {table.table_ordinal}",
                    "snippet": content,
                    "content": content,
                    "content_char_count": content_char_count,
                    "content_utf8_bytes": content_utf8_bytes,
                    "content_sha256": content_sha256,
                    "sent_at": None,
                    "source_kind": "authorized_document_export",
                }
            )

        status = "ok" if results else "not_found"
        answerability_status = "sufficient_evidence" if results else "target_not_found"
        response_without_commitment: dict[str, Any] = {
            "status": status,
            "query_hash": sha256_json(query_text),
            "source_commitment": self.snapshot.source_commitment,
            "result_count": len(results),
            "total_result_count": len(candidates),
            "displayed_result_count": len(results),
            "results": results,
            "warnings": [] if results else ["no_authorized_document_segment_matched"],
            "notice": "Authorized document/table segments were read for model synthesis.",
            "coverage": {
                "cardinality_mode": "bounded_document_segments",
                "total_source_item_count": len(candidates),
                "returned_source_item_count": len(results),
                "displayed_source_item_count": len(results),
                "is_exhaustive": len(results) == len(candidates),
                "has_more": len(candidates) > len(results),
            },
            "answerability": {
                "status": answerability_status,
                "reason_codes": (
                    ["authorized_document_segments_available"]
                    if results
                    else ["no_matching_document_segment"]
                ),
            },
            "projection": {
                "output_format": "narrative",
                "primary_fields": ["content"],
                "secondary_fields": ["source_label", "segment_label"],
                "page_size": limit,
                "page_offset": 0,
                "has_more": len(candidates) > len(results),
            },
            "timings_ms": {
                "document_read": round((perf_counter() - started) * 1000.0, 3),
            },
            "claim_boundary": {
                "existing_export_only": True,
                "document_first": True,
                "read_only": True,
                "pst_or_extractor_invoked": False,
                "kg_or_ontology_invoked": False,
                "oracle_or_expected_answer_used": False,
                "canonical_graph_write_performed": False,
                "production_ready": False,
            },
        }
        response = {
            **response_without_commitment,
            "mcp_response_commitment": sha256_json(response_without_commitment),
        }
        return validate_document_uat_payload(response)


def validate_document_uat_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the private, value-bearing document payload before reinjection."""

    if not isinstance(payload, Mapping) or set(payload) != _DOCUMENT_RESPONSE_KEYS:
        raise ContractValidationError("document UAT payload shape is invalid")
    status = payload.get("status")
    if status not in {"ok", "not_found"}:
        raise ContractValidationError("document UAT payload status is invalid")
    _validated_sha256(payload.get("query_hash"), "document UAT query hash")
    _validated_sha256(payload.get("source_commitment"), "document UAT source commitment")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) > _MAX_RESULT_ITEMS:
        raise ContractValidationError("document UAT payload results are invalid")
    result_count = _validated_count(
        payload.get("result_count"),
        "document UAT result count",
        maximum=_MAX_RESULT_ITEMS,
    )
    displayed_result_count = _validated_count(
        payload.get("displayed_result_count"),
        "document UAT displayed result count",
        maximum=_MAX_RESULT_ITEMS,
    )
    total_result_count = _validated_count(
        payload.get("total_result_count"),
        "document UAT total result count",
    )
    if (
        result_count != len(results)
        or displayed_result_count != len(results)
        or total_result_count < result_count
        or (status == "ok") != bool(results)
    ):
        raise ContractValidationError("document UAT payload counts are inconsistent")

    total_content_chars = 0
    total_content_utf8_bytes = 0
    for index, item in enumerate(results):
        if not isinstance(item, Mapping) or set(item) != _DOCUMENT_RESULT_KEYS:
            raise ContractValidationError("document UAT result shape is invalid")
        content = item.get("content")
        if item.get("snippet") != content:
            raise ContractValidationError("document UAT result snippet is invalid")
        content_char_count, content_utf8_bytes, content_sha256 = _validated_document_content(
            content,
            context=f"document_uat_payload.results[{index}].content",
        )
        if (
            item.get("content_char_count") != content_char_count
            or item.get("content_utf8_bytes") != content_utf8_bytes
            or item.get("content_sha256") != content_sha256
        ):
            raise ContractValidationError("document UAT result content metadata is invalid")
        total_content_chars += content_char_count
        total_content_utf8_bytes += content_utf8_bytes
        for field_name in ("source_label", "segment_label", "subject"):
            value = item.get(field_name)
            if not isinstance(value, str) or not value.strip() or len(value) > 300:
                raise ContractValidationError(f"document UAT result {field_name} is invalid")
        if item.get("sent_at") is not None:
            raise ContractValidationError("document UAT result timestamp is invalid")
        if item.get("source_kind") != "authorized_document_export":
            raise ContractValidationError("document UAT result source is invalid")
    if (
        total_content_chars > _MAX_TOTAL_CONTENT_CHARS
        or total_content_utf8_bytes > _MAX_TOTAL_CONTENT_UTF8_BYTES
    ):
        raise ContractValidationError("document UAT payload content budget is invalid")

    warnings = payload.get("warnings")
    expected_warnings = [] if results else ["no_authorized_document_segment_matched"]
    if warnings != expected_warnings:
        raise ContractValidationError("document UAT payload warnings are invalid")
    if payload.get("notice") != (
        "Authorized document/table segments were read for model synthesis."
    ):
        raise ContractValidationError("document UAT payload notice is invalid")
    _validate_document_coverage(
        payload.get("coverage"),
        result_count=result_count,
        total_result_count=total_result_count,
    )
    _validate_document_answerability(payload.get("answerability"), has_results=bool(results))
    _validate_document_projection(
        payload.get("projection"),
        result_limit=_validated_count(
            payload["projection"].get("page_size")
            if isinstance(payload.get("projection"), Mapping)
            else None,
            "document UAT projection page size",
            minimum=1,
            maximum=_MAX_RESULT_ITEMS,
        ),
        has_more=total_result_count > result_count,
        public=False,
    )
    timings = payload.get("timings_ms")
    if (
        not isinstance(timings, Mapping)
        or set(timings) != {"document_read"}
        or not isinstance(timings.get("document_read"), (int, float))
        or isinstance(timings.get("document_read"), bool)
        or timings["document_read"] < 0
    ):
        raise ContractValidationError("document UAT payload timings are invalid")
    _validate_document_claim_boundary(payload.get("claim_boundary"))

    commitment = _validated_sha256(
        payload.get("mcp_response_commitment"),
        "document UAT MCP response commitment",
    )
    without_commitment = dict(payload)
    without_commitment.pop("mcp_response_commitment")
    if sha256_json(without_commitment) != commitment:
        raise ContractValidationError("document UAT MCP response commitment does not match")

    masked = {
        **dict(payload),
        "results": [
            {
                **dict(item),
                "content": "[validated_document_content]",
                "snippet": "[validated_document_content]",
            }
            for item in results
        ],
    }
    assert_public_payload_safe(masked, "document_uat_internal_metadata")
    return dict(payload)


def project_document_uat_payload_public(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove value-bearing fields before state, HTTP, logs, or DOM projection."""

    if (
        isinstance(payload, Mapping)
        and payload.get("document_payload_projection") == _PUBLIC_PROJECTION_TYPE
    ):
        return validate_document_uat_public_projection(payload)
    validated = validate_document_uat_payload(payload)
    public_payload = {
        **validated,
        "document_payload_projection": _PUBLIC_PROJECTION_TYPE,
        "results": [
            {key: value for key, value in item.items() if key in _DOCUMENT_PUBLIC_RESULT_KEYS}
            for item in validated["results"]
        ],
        "projection": {
            **validated["projection"],
            "primary_fields": ["source_label", "segment_label", "content_sha256"],
        },
    }
    return validate_document_uat_public_projection(public_payload)


def validate_document_uat_public_projection(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != _DOCUMENT_PUBLIC_RESPONSE_KEYS:
        raise ContractValidationError("document UAT public projection shape is invalid")
    if payload.get("document_payload_projection") != _PUBLIC_PROJECTION_TYPE:
        raise ContractValidationError("document UAT public projection type is invalid")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) > _MAX_RESULT_ITEMS:
        raise ContractValidationError("document UAT public results are invalid")
    for item in results:
        if not isinstance(item, Mapping) or set(item) != _DOCUMENT_PUBLIC_RESULT_KEYS:
            raise ContractValidationError("document UAT public result shape is invalid")
        _validated_sha256(
            item.get("content_sha256"),
            "document UAT public content commitment",
        )
        _validated_count(
            item.get("content_char_count"),
            "document UAT public content char count",
            minimum=1,
            maximum=_MAX_SEGMENT_CHARS,
        )
        _validated_count(
            item.get("content_utf8_bytes"),
            "document UAT public content UTF-8 byte count",
            minimum=1,
            maximum=_MAX_SEGMENT_UTF8_BYTES,
        )
        if item.get("source_kind") != "authorized_document_export":
            raise ContractValidationError("document UAT public result source is invalid")
    if _contains_document_value_field(payload):
        raise ContractValidationError("document UAT public projection contains document values")
    _validated_sha256(
        payload.get("mcp_response_commitment"),
        "document UAT public MCP response commitment",
    )
    projection = payload.get("projection")
    if not isinstance(projection, Mapping):
        raise ContractValidationError("document UAT public projection metadata is invalid")
    _validate_document_projection(
        projection,
        result_limit=_validated_count(
            projection.get("page_size"),
            "document UAT public projection page size",
            minimum=1,
            maximum=_MAX_RESULT_ITEMS,
        ),
        has_more=bool(projection.get("has_more")),
        public=True,
    )
    assert_public_payload_safe(payload, "document_uat_public_projection")
    return dict(payload)


def _validated_document_content(
    value: Any,
    *,
    context: str,
) -> tuple[int, int, str]:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{context} must be a nonblank string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(f"{context} is not valid UTF-8") from exc
    if (
        len(value) > _MAX_SEGMENT_CHARS
        or len(encoded) > _MAX_SEGMENT_UTF8_BYTES
        or any(ord(character) < 32 and character not in "\t\n\r" for character in value)
    ):
        raise ContractValidationError(f"{context} exceeds the document content budget")
    assert_authorized_evidence_text_safe(value, context)
    if _DOCUMENT_OS_PATH_TOKEN.search(value) or _DOCUMENT_LOCAL_LOCATOR_TOKEN.search(value):
        raise ContractValidationError(f"{context} contains an internal locator")
    return (
        len(value),
        len(encoded),
        "sha256:" + hashlib.sha256(encoded).hexdigest(),
    )


def _bounded_document_content(
    value: str,
    *,
    max_chars: int,
    max_utf8_bytes: int,
) -> str:
    bounded = value[:max_chars]
    while bounded and len(bounded.encode("utf-8")) > max_utf8_bytes:
        bounded = bounded[:-1]
    if not bounded:
        raise ContractValidationError("document UAT bounded content is empty")
    return bounded


def _validate_document_coverage(
    value: Any,
    *,
    result_count: int,
    total_result_count: int,
) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "cardinality_mode",
        "displayed_source_item_count",
        "has_more",
        "is_exhaustive",
        "returned_source_item_count",
        "total_source_item_count",
    }:
        raise ContractValidationError("document UAT coverage shape is invalid")
    if (
        value.get("cardinality_mode") != "bounded_document_segments"
        or value.get("total_source_item_count") != total_result_count
        or value.get("returned_source_item_count") != result_count
        or value.get("displayed_source_item_count") != result_count
        or value.get("has_more") is not (total_result_count > result_count)
        or value.get("is_exhaustive") is not (total_result_count == result_count)
    ):
        raise ContractValidationError("document UAT coverage is invalid")


def _validate_document_answerability(value: Any, *, has_results: bool) -> None:
    if not isinstance(value, Mapping) or set(value) != {"reason_codes", "status"}:
        raise ContractValidationError("document UAT answerability shape is invalid")
    expected_status = "sufficient_evidence" if has_results else "target_not_found"
    expected_reasons = (
        ["authorized_document_segments_available"]
        if has_results
        else ["no_matching_document_segment"]
    )
    if value.get("status") != expected_status or value.get("reason_codes") != expected_reasons:
        raise ContractValidationError("document UAT answerability is invalid")


def _validate_document_projection(
    value: Any,
    *,
    result_limit: int,
    has_more: bool,
    public: bool,
) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "has_more",
        "output_format",
        "page_offset",
        "page_size",
        "primary_fields",
        "secondary_fields",
    }:
        raise ContractValidationError("document UAT projection shape is invalid")
    expected_primary = (
        ["source_label", "segment_label", "content_sha256"] if public else ["content"]
    )
    if (
        value.get("output_format") != "narrative"
        or value.get("primary_fields") != expected_primary
        or value.get("secondary_fields") != ["source_label", "segment_label"]
        or value.get("page_size") != result_limit
        or value.get("page_offset") != 0
        or value.get("has_more") is not has_more
    ):
        raise ContractValidationError("document UAT projection is invalid")


def _validate_document_claim_boundary(value: Any) -> None:
    expected = {
        "canonical_graph_write_performed": False,
        "document_first": True,
        "existing_export_only": True,
        "kg_or_ontology_invoked": False,
        "oracle_or_expected_answer_used": False,
        "production_ready": False,
        "pst_or_extractor_invoked": False,
        "read_only": True,
    }
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise ContractValidationError("document UAT claim boundary is invalid")


def _validated_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{label} is invalid")
    return value


def _validated_count(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ContractValidationError(f"{label} is invalid")
    return value


def _contains_document_value_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in {"content", "snippet"} or _contains_document_value_field(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_document_value_field(item) for item in value)
    return False


def create_authorized_document_mcp_http_server(
    host: str,
    port: int,
    service: AuthorizedDocumentMcpService,
) -> ThreadingHTTPServer:
    if not isinstance(service, AuthorizedDocumentMcpService):
        raise ContractValidationError("document MCP service is invalid")

    class Handler(BaseHTTPRequestHandler):
        server_version = "FormOwlDocumentUATMCP/0.1"

        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path == "/health":
                self._send_json(HTTPStatus.OK, service.health())
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/mcp":
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    _error_response(None, -32601, "Method not found"),
                )
                return
            try:
                content_type = self.headers.get("Content-Type", "")
                content_length = self.headers.get("Content-Length")
                if (
                    content_type.split(";", 1)[0].strip().lower() != "application/json"
                    or content_length is None
                    or not content_length.isdigit()
                    or not 0 < int(content_length) <= _MAX_HTTP_REQUEST_BYTES
                ):
                    raise ContractValidationError("document MCP request is invalid")
                body = self.rfile.read(int(content_length))
                request = json.loads(body.decode("utf-8"))
                if not isinstance(request, Mapping):
                    raise ContractValidationError("document MCP request is invalid")
                response = service.handle_jsonrpc(request)
            except (
                ContractValidationError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    _error_response(None, -32600, "Invalid Request"),
                )
                return
            if response is None:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send_json(HTTPStatus.OK, response)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(
            self,
            status: HTTPStatus,
            payload: Mapping[str, Any],
        ) -> None:
            encoded = json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def _snapshot_authorization(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, Mapping):
        raise ContractValidationError("document snapshot authorization is invalid")
    source = payload.get("source")
    if not isinstance(source, Mapping):
        raise ContractValidationError("document snapshot authorization is unavailable")
    workspace_id = _authorization_identifier(source.get("workspace_id"), "workspace")
    actor_user_id = _authorization_identifier(source.get("owner_user_id"), "actor")
    return workspace_id, actor_user_id


def _authorization_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _AUTHORIZATION_IDENTIFIER_RE.fullmatch(value) is None:
        raise ContractValidationError(f"document UAT {label} binding is invalid")
    return value


def _authorization_binding_commitment(
    *,
    snapshot_sha256: str,
    workspace_id: str,
    actor_user_id: str,
    session_id: str,
) -> str:
    if not _SHA256_RE.fullmatch(snapshot_sha256):
        raise ContractValidationError("document UAT snapshot binding is invalid")
    return sha256_json(
        {
            "artifact_type": _AUTHORIZATION_BINDING_TYPE,
            "snapshot_sha256": snapshot_sha256,
            "workspace_id": _authorization_identifier(workspace_id, "workspace"),
            "actor_user_id": _authorization_identifier(actor_user_id, "actor"),
            "session_id": _authorization_identifier(session_id, "session"),
        }
    )


def _parse_snapshot(payload: Any) -> tuple[_AuthorizedTable, ...]:
    if (
        not isinstance(payload, Mapping)
        or payload.get("artifact_type") != _SNAPSHOT_ARTIFACT_TYPE
        or payload.get("schema_version") != 2
        or not isinstance(payload.get("records"), list)
        or payload.get("record_count") != len(payload["records"])
    ):
        raise ContractValidationError("document snapshot schema is invalid")
    tables: list[_AuthorizedTable] = []
    for table_ordinal, record in enumerate(payload["records"], start=1):
        if not isinstance(record, Mapping):
            raise ContractValidationError("document snapshot record is invalid")
        observation = record.get("structural_observation")
        if not isinstance(observation, Mapping):
            raise ContractValidationError("document snapshot table is invalid")
        raw_columns = observation.get("columns")
        raw_rows = observation.get("rows")
        if not isinstance(raw_columns, list) or not isinstance(raw_rows, list):
            raise ContractValidationError("document snapshot table is invalid")
        headers: list[tuple[int, str]] = []
        for raw_column in raw_columns:
            if not isinstance(raw_column, Mapping):
                raise ContractValidationError("document snapshot column is invalid")
            column_ordinal = _positive_int(
                raw_column.get("column_ordinal"),
                "document snapshot column ordinal",
            )
            header = raw_column.get("original_header")
            if not isinstance(header, str) or not header.strip():
                header = raw_column.get("normalized_header")
            if isinstance(header, str) and header.strip():
                headers.append((column_ordinal, header.strip()))
        rows: list[_TableRow] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, Mapping) or not isinstance(
                raw_row.get("cells"),
                list,
            ):
                raise ContractValidationError("document snapshot row is invalid")
            row_ordinal = _positive_int(
                raw_row.get("row_ordinal"),
                "document snapshot row ordinal",
            )
            cells: list[tuple[int, str]] = []
            for raw_cell in raw_row["cells"]:
                if not isinstance(raw_cell, Mapping):
                    raise ContractValidationError("document snapshot cell is invalid")
                column_ordinal = _positive_int(
                    raw_cell.get("column_ordinal"),
                    "document snapshot cell column",
                )
                state = raw_cell.get("cell_state")
                if state not in {"absent", "blank", "populated"}:
                    raise ContractValidationError("document snapshot cell state is invalid")
                value = raw_cell.get("value")
                if state == "populated":
                    if not isinstance(value, str):
                        raise ContractValidationError("document snapshot cell value is invalid")
                    cells.append((column_ordinal, value))
            normalized_text = _normalize_text(" ".join(value for _, value in cells))
            rows.append(
                _TableRow(
                    row_ordinal=row_ordinal,
                    cells=tuple(cells),
                    normalized_text=normalized_text,
                )
            )
        if rows:
            table_text = _normalize_text(
                " ".join(
                    [
                        *(value for _, value in headers),
                        *(value for row in rows for _, value in row.cells),
                    ]
                )
            )
            tables.append(
                _AuthorizedTable(
                    table_ordinal=table_ordinal,
                    headers=tuple(headers),
                    rows=tuple(rows),
                    normalized_text=table_text,
                )
            )
    if not tables:
        raise ContractValidationError("document snapshot contains no readable tables")
    return tuple(tables)


def _validate_tool_arguments(
    value: Any,
) -> tuple[str, tuple[str, ...], int]:
    if not isinstance(value, Mapping) or set(value) != {
        "query_text",
        "required_terms",
        "limit",
    }:
        raise ContractValidationError("document MCP arguments are invalid")
    query_text = value.get("query_text")
    required_terms = value.get("required_terms")
    limit = value.get("limit")
    if (
        not isinstance(query_text, str)
        or not query_text.strip()
        or len(query_text) > _MAX_QUERY_CHARS
        or not isinstance(required_terms, list)
        or len(required_terms) > _MAX_REQUIRED_TERMS
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= _MAX_RESULT_ITEMS
    ):
        raise ContractValidationError("document MCP arguments are invalid")
    normalized_required: list[str] = []
    for term in required_terms:
        if not isinstance(term, str) or not term.strip() or len(term) > _MAX_REQUIRED_TERM_CHARS:
            raise ContractValidationError("document MCP required term is invalid")
        normalized = _normalize_text(term)
        if not normalized or normalized in normalized_required:
            raise ContractValidationError("document MCP required terms are invalid")
        normalized_required.append(normalized)
    return query_text.strip(), tuple(normalized_required), limit


def _query_terms(
    query_text: str,
    required_terms: Sequence[str],
) -> tuple[str, ...]:
    normalized_query = unicodedata.normalize("NFKC", query_text)
    terms: list[str] = list(required_terms)
    for match in _ASCII_TERM_RE.finditer(normalized_query):
        term = _normalize_text(match.group(0))
        if len(term) >= 2 and term not in _STOP_TERMS and term not in terms:
            terms.append(term)
    for run in _CJK_RUN_RE.findall(normalized_query):
        normalized_run = _normalize_text(run)
        for width in range(min(4, len(normalized_run)), 1, -1):
            for start in range(len(normalized_run) - width + 1):
                term = normalized_run[start : start + width]
                if term not in _STOP_TERMS and term not in terms:
                    terms.append(term)
                if len(terms) >= 64:
                    return tuple(terms)
    return tuple(terms[:64])


def _render_table_segment(
    table: _AuthorizedTable,
    *,
    start: int,
    end: int,
) -> str:
    header_by_column = dict(table.headers)
    lines: list[str] = []
    if header_by_column:
        rendered_headers = [
            f"c{column_ordinal}={value}"
            for column_ordinal, value in sorted(header_by_column.items())
        ]
        lines.append("columns: " + " | ".join(rendered_headers))
    for row in table.rows[start:end]:
        rendered_cells = []
        for column_ordinal, value in row.cells:
            label = header_by_column.get(column_ordinal)
            safe_label = f"c{column_ordinal}"
            if isinstance(label, str) and label.strip():
                safe_label = label.strip()
            rendered_cells.append(f"{safe_label}={value}")
        lines.append(f"row {row.row_ordinal}: " + " | ".join(rendered_cells))
    return "\n".join(lines)


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractValidationError(f"{label} is invalid")
    return value


def _tool_result_response(
    request_id: Any,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    rendered = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
    return _result_response(
        request_id,
        {
            "content": [{"type": "text", "text": rendered}],
            "structuredContent": dict(payload),
        },
    )


def _tool_error_response(request_id: Any, error_code: str) -> dict[str, Any]:
    return _result_response(
        request_id,
        {
            "content": [{"type": "text", "text": error_code}],
            "structuredContent": {
                "status": "error",
                "error_code": error_code,
            },
            "isError": True,
        },
    )


def _result_response(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Serve one read-only document MCP over a hash-bound authorized "
            "existing-export snapshot."
        )
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("FORMOWL_DOCUMENT_UAT_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=os.environ.get("FORMOWL_DOCUMENT_UAT_PORT", "8090"),
    )
    parser.add_argument(
        "--snapshot",
        default=os.environ.get("FORMOWL_DOCUMENT_UAT_SNAPSHOT"),
    )
    parser.add_argument(
        "--expected-sha256",
        default=os.environ.get("FORMOWL_DOCUMENT_UAT_SNAPSHOT_SHA256"),
    )
    parser.add_argument(
        "--workspace-id",
        default=os.environ.get("FORMOWL_DOCUMENT_UAT_WORKSPACE_ID"),
    )
    parser.add_argument(
        "--actor-user-id",
        default=os.environ.get("FORMOWL_DOCUMENT_UAT_ACTOR_USER_ID"),
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("FORMOWL_DOCUMENT_UAT_SESSION_ID"),
    )
    return parser


def _validated_bind_host(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise ContractValidationError("document UAT bind host is invalid")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if value != "localhost":
            raise ContractValidationError("document UAT bind host is invalid") from None
    return value


def _validated_bind_port(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 65535:
        raise ContractValidationError("document UAT bind port is invalid")
    return value


def build_authorized_document_mcp_service(
    *,
    snapshot_path: str | Path,
    expected_sha256: str,
    workspace_id: str,
    actor_user_id: str,
    session_id: str,
) -> AuthorizedDocumentMcpService:
    validated_workspace_id = _authorization_identifier(workspace_id, "workspace")
    validated_actor_user_id = _authorization_identifier(actor_user_id, "actor")
    validated_session_id = _authorization_identifier(session_id, "session")
    snapshot = AuthorizedDocumentSnapshot.load(
        snapshot_path,
        expected_sha256=expected_sha256,
        expected_workspace_id=validated_workspace_id,
        expected_actor_user_id=validated_actor_user_id,
    )
    return AuthorizedDocumentMcpService(
        snapshot,
        authorization_binding_commitment=_authorization_binding_commitment(
            snapshot_sha256=snapshot.source_commitment,
            workspace_id=validated_workspace_id,
            actor_user_id=validated_actor_user_id,
            session_id=validated_session_id,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        host = _validated_bind_host(args.host)
        port = _validated_bind_port(args.port)
        if not isinstance(args.snapshot, str) or not isinstance(
            args.expected_sha256,
            str,
        ):
            raise ContractValidationError("document UAT snapshot arguments are required")
        service = build_authorized_document_mcp_service(
            snapshot_path=args.snapshot,
            expected_sha256=args.expected_sha256,
            workspace_id=args.workspace_id,
            actor_user_id=args.actor_user_id,
            session_id=args.session_id,
        )
        server = create_authorized_document_mcp_http_server(host, port, service)
    except (ContractValidationError, OSError, ValueError):
        print(_STARTUP_FAILURE_MESSAGE, file=sys.stderr)
        return 2
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


__all__ = [
    "AuthorizedDocumentMcpService",
    "AuthorizedDocumentSnapshot",
    "MCP_PROTOCOL_VERSION",
    "MCP_SERVER_NAME",
    "MCP_TOOL_NAME",
    "build_authorized_document_mcp_service",
    "create_authorized_document_mcp_http_server",
    "main",
    "project_document_uat_payload_public",
    "validate_document_uat_payload",
    "validate_document_uat_public_projection",
]


if __name__ == "__main__":
    raise SystemExit(main())
