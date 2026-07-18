from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from formowl_contract import ContractValidationError, now_iso, sha256_json

from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle
from .human_uat_upload import (
    PrivateUatMailUploadStore,
    UatUploadRequestTooLarge,
    UatUploadedMailPart,
    parse_uat_eml_multipart,
    parse_uat_uploaded_eml,
    upload_import_session_id,
)
from .query import MailEvidenceQueryGateway, _redact_mail_public_text

_MAX_REQUEST_BYTES = 32 * 1024
_MAX_UPLOAD_REQUEST_BYTES = 64 * 1024 * 1024
_MAX_UPLOAD_FILE_BYTES = 25 * 1024 * 1024
_MAX_UPLOAD_FILES = 20
_MAX_QUERY_CHARS = 500
_MAX_NOTE_CHARS = 1000
_MAX_RESULT_LIMIT = 20
_RETRIEVAL_CANDIDATE_LIMIT = 200
_QUERY_ID_RE = re.compile(r"^uatquery_[0-9a-f]{24}$")
_VERDICTS = {
    "correct",
    "partially_correct",
    "incorrect",
    "no_result",
    "citation_issue",
}
_SORT_OPTIONS = {"relevance", "recent"}
_QUERY_KEYS = {"query_text", "limit", "sort"}
_FEEDBACK_KEYS = {"query_id", "verdict", "note"}
_BUSINESS_ALIASES = (
    (
        ("量產", "打件", "生產排程", "投產"),
        ("SMT", "production", "schedule"),
        ("量產", "打件", "SMT", "production"),
    ),
    (
        ("pull-in", "pull in", "pullin", "拉料", "催料", "提前交貨"),
        ("pull-in", "pull", "delivery"),
        ("pull-in", "pull in", "pullin", "拉料", "催料"),
    ),
    (
        ("交期", "到料", "到貨", "交貨"),
        ("delivery", "ETA", "due"),
        ("交期", "到料", "到貨", "交貨", "delivery", "ETA"),
    ),
)
_EXACT_BUSINESS_FILTERS = ("文顥",)


@dataclass(frozen=True)
class MailHumanUatHttpConfig:
    bundle: MailEvidenceBundle
    state_dir: str | Path
    fixed_now: str | None = None
    max_request_bytes: int = _MAX_REQUEST_BYTES
    max_upload_request_bytes: int = _MAX_UPLOAD_REQUEST_BYTES
    max_upload_file_bytes: int = _MAX_UPLOAD_FILE_BYTES
    max_upload_files: int = _MAX_UPLOAD_FILES


class MailHumanUatService:
    """Shared human UAT facade over the governed mail evidence query gateway."""

    def __init__(self, config: MailHumanUatHttpConfig) -> None:
        if (
            not isinstance(config.max_request_bytes, int)
            or isinstance(config.max_request_bytes, bool)
            or config.max_request_bytes <= 0
        ):
            raise ContractValidationError("UAT max request bytes must be positive")
        for field_name, value in (
            ("max_upload_request_bytes", config.max_upload_request_bytes),
            ("max_upload_file_bytes", config.max_upload_file_bytes),
            ("max_upload_files", config.max_upload_files),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ContractValidationError(f"UAT {field_name} must be positive")
        if config.max_upload_file_bytes > config.max_upload_request_bytes:
            raise ContractValidationError("UAT max upload file bytes must not exceed request bytes")
        if not config.bundle.messages or not config.bundle.body_segments:
            raise ContractValidationError("UAT mail evidence bundle must contain messages")
        safe_public_string(config.bundle.mail_evidence_bundle_id, "mail_evidence_bundle_id")
        config.bundle.mail_import_session.to_dict()
        self.config = config
        self._base_gateway = MailEvidenceQueryGateway([config.bundle])
        self._base_message_by_id = {
            message.email_message_id: message for message in config.bundle.messages
        }
        self._event_store = _PrivateUatEventStore(config.state_dir)
        self._upload_store = PrivateUatMailUploadStore(
            config.state_dir,
            max_file_bytes=config.max_upload_file_bytes,
        )
        self._known_query_ids: set[str] = set()
        self._verdict_counts: Counter[str] = Counter()
        self._query_count = 0
        self._feedback_count = 0
        self._lock = threading.RLock()
        self.started_at = _timestamp(config.fixed_now)
        actor = config.bundle.mail_import_session
        loaded_uploads = [
            parse_uat_uploaded_eml(
                content,
                owner_user_id=actor.owner_user_id,
                workspace_id=actor.workspace_id,
                created_at=self.started_at,
            )
            for _, content in self._upload_store.load()
        ]
        self._uploaded_content_hashes = {parsed.content_hash for parsed in loaded_uploads}
        self._uploaded_bundles = [parsed.bundle for parsed in loaded_uploads]
        self._uploaded_warnings = Counter(
            warning for parsed in loaded_uploads for warning in parsed.warnings
        )
        self._install_uploaded_index(self._uploaded_bundles)

    def health(self) -> dict[str, Any]:
        with self._lock:
            uploaded_file_count = len(self._uploaded_bundles)
        payload = {
            "status": "ready",
            "surface": "mail_human_uat",
            "chatgpt_bypassed": True,
            "authentication_required": False,
            "shared_uat": True,
            "upload_required": False,
            "upload_supported": True,
            "uploaded_file_count": uploaded_file_count,
            "read_only_business_systems": True,
        }
        assert_public_payload_safe(payload, "mail_human_uat_health")
        return payload

    def query(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        _expect_exact_keys(payload, _QUERY_KEYS, required={"query_text"})
        query_text = _validated_text(
            payload.get("query_text"),
            "query_text",
            max_chars=_MAX_QUERY_CHARS,
        )
        limit = payload.get("limit", 8)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > _MAX_RESULT_LIMIT
        ):
            raise ContractValidationError("limit must be between 1 and 20")
        sort = payload.get("sort", "relevance")
        if sort not in _SORT_OPTIONS:
            raise ContractValidationError("sort must be relevance or recent")

        expanded_query, filter_groups = _expand_business_query(query_text)
        bundle = self.config.bundle
        actor = bundle.mail_import_session
        base_result = self._base_gateway.query_mail_evidence(
            query_text=expanded_query,
            requester_user_id=actor.owner_user_id,
            workspace_id=actor.workspace_id,
            session_id="session_mail_human_uat",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=_RETRIEVAL_CANDIDATE_LIMIT,
            now=self.config.fixed_now,
        ).to_dict()
        with self._lock:
            upload_gateway = self._upload_gateway
            message_by_id = self._message_by_id
            all_bundles = self._all_bundles
            uploaded_message_ids = self._uploaded_message_ids
            uploaded_file_count = len(self._uploaded_bundles)
        gateway_results = [base_result]
        if upload_gateway is not None:
            gateway_results.append(
                upload_gateway.query_mail_evidence(
                    query_text=expanded_query,
                    requester_user_id=actor.owner_user_id,
                    workspace_id=actor.workspace_id,
                    session_id="session_mail_human_uat",
                    mail_import_session_id=upload_import_session_id(),
                    limit=_RETRIEVAL_CANDIDATE_LIMIT,
                    now=self.config.fixed_now,
                ).to_dict()
            )
        evidence_snippets = [
            snippet
            for gateway_result in gateway_results
            for snippet in gateway_result["evidence_snippets"]
        ]
        citations = [
            citation
            for gateway_result in gateway_results
            for citation in gateway_result["citations"]
        ]

        citations_by_observation = {
            citation["source_observation_id"]: citation for citation in citations
        }
        results: list[dict[str, Any]] = []
        for snippet in evidence_snippets:
            rendered = " ".join(
                value
                for value in (snippet.get("subject"), snippet.get("snippet"))
                if isinstance(value, str)
            )
            if not _matches_filter_groups(rendered, filter_groups):
                continue
            email_message_id = str(snippet.get("email_message_id", ""))
            message = message_by_id.get(email_message_id)
            subject = str(snippet.get("subject") or "（無主旨）")
            snippet_text = str(snippet.get("snippet", ""))
            matched_terms = [
                term for term in snippet.get("matched_terms", []) if isinstance(term, str) and term
            ]
            result = {
                "subject": subject,
                "snippet": _context_window(
                    snippet_text,
                    needles=(*matched_terms, *_query_needles(query_text)),
                ),
                "sent_at": message.sent_at if message is not None else None,
                "score": int(snippet.get("score", 0)),
                "matched_terms": matched_terms,
                "citation": _public_citation(
                    citations_by_observation.get(str(snippet.get("source_observation_id", "")))
                ),
                "content_redacted": bool(snippet.get("content_redacted", False)),
                "source_kind": (
                    "uploaded_uat" if email_message_id in uploaded_message_ids else "preloaded"
                ),
            }
            (
                result["_subject_business_matches"],
                result["_snippet_business_matches"],
            ) = _business_match_counts(subject, snippet_text, filter_groups)
            results.append(result)

        if any(gateway_result["status"] == "ok" for gateway_result in gateway_results):
            results.extend(
                self._exact_subject_results(
                    query_text=query_text,
                    filter_groups=filter_groups,
                    bundles=all_bundles,
                    uploaded_message_ids=uploaded_message_ids,
                )
            )
        results = _deduplicate_results(results)
        if sort == "recent":
            results.sort(
                key=lambda item: (
                    int(item["_subject_business_matches"]),
                    _timestamp_sort_key(item.get("sent_at")),
                    int(item["score"]),
                    int(item["_snippet_business_matches"]),
                ),
                reverse=True,
            )
        else:
            results.sort(
                key=lambda item: (
                    int(item["_subject_business_matches"]),
                    int(item["score"]),
                    int(item["_snippet_business_matches"]),
                    _timestamp_sort_key(item.get("sent_at")),
                ),
                reverse=True,
            )
        results = results[:limit]
        for result in results:
            result.pop("_subject_business_matches", None)
            result.pop("_snippet_business_matches", None)

        query_id = f"uatquery_{secrets.token_hex(12)}"
        generated_at = _timestamp(self.config.fixed_now)
        warnings = [
            warning for gateway_result in gateway_results for warning in gateway_result["warnings"]
        ]
        if results:
            warnings = [
                warning for warning in warnings if warning != "no_visible_mail_evidence_matched"
            ]
            if any(result["content_redacted"] for result in results):
                warnings.append("unsafe_mail_evidence_content_redacted")
        if filter_groups and evidence_snippets and not results:
            warnings.append("business_filter_no_exact_match")
        if not results and "no_visible_mail_evidence_matched" not in warnings:
            warnings.append("no_visible_mail_evidence_matched")
        response = {
            "status": (
                "ok"
                if any(gateway_result["status"] == "ok" for gateway_result in gateway_results)
                else gateway_results[0]["status"]
            ),
            "query_id": query_id,
            "query_hash": sha256_json(query_text),
            "generated_at": generated_at,
            "sort": sort,
            "result_count": len(results),
            "results": results,
            "warnings": sorted(set(warnings)),
            "notice": (
                "這是郵件證據的只讀測試結果；排程不等於已完成量產，"
                "Pull-in 與交期仍須以原始郵件內容確認。"
            ),
            "claim_boundary": {
                "chatgpt_bypassed": True,
                "mail_upload_performed": False,
                "uploaded_mail_available": uploaded_file_count > 0,
                "read_only_mail_evidence": True,
                "project_or_wiki_write_performed": False,
                "canonical_graph_write_performed": False,
                "autonomous_business_decision": False,
                "production_ready": False,
            },
        }
        assert_public_payload_safe(response, "mail_human_uat_query_response")
        self._event_store.append(
            {
                "event_type": "query",
                "created_at": generated_at,
                "query_id": query_id,
                "query_text": query_text,
                "query_hash": response["query_hash"],
                "sort": sort,
                "result_count": len(results),
                "citation_ids": [
                    item["citation"]["citation_id"] for item in results if item.get("citation")
                ],
            }
        )
        with self._lock:
            self._known_query_ids.add(query_id)
            self._query_count += 1
        return response

    def _exact_subject_results(
        self,
        *,
        query_text: str,
        filter_groups: tuple[tuple[str, ...], ...],
        bundles: tuple[MailEvidenceBundle, ...],
        uploaded_message_ids: frozenset[str],
    ) -> list[dict[str, Any]]:
        lowered_query = query_text.casefold()
        exact_terms = [term for term in _EXACT_BUSINESS_FILTERS if term.casefold() in lowered_query]
        if not exact_terms:
            return []
        results: list[dict[str, Any]] = []
        filter_needles = tuple(term for group in filter_groups for term in group)
        matching_messages = []
        segments_by_message_id: dict[str, list[Any]] = {}
        bundle_by_message_id: dict[str, MailEvidenceBundle] = {}
        for bundle in bundles:
            for message in bundle.messages:
                bundle_by_message_id[message.email_message_id] = bundle
                if all(
                    term.casefold() in (message.subject or "").casefold() for term in exact_terms
                ):
                    matching_messages.append(message)
            for segment in bundle.body_segments:
                segments_by_message_id.setdefault(segment.email_message_id, []).append(segment)
        matching_messages.sort(
            key=lambda message: _timestamp_sort_key(message.sent_at),
            reverse=True,
        )
        for message in matching_messages:
            subject = message.subject or ""
            bundle = bundle_by_message_id[message.email_message_id]
            for segment in segments_by_message_id.get(message.email_message_id, []):
                rendered = f"{subject} {segment.text}"
                if not _matches_filter_groups(rendered, filter_groups):
                    continue
                safe_subject, subject_redactions = _redact_mail_public_text(subject)
                safe_snippet, snippet_redactions = _redact_mail_public_text(segment.text)
                rendered_lowered = rendered.casefold()
                matched_terms = sorted(
                    {
                        term
                        for group in filter_groups
                        for term in group
                        if term.casefold() in rendered_lowered
                    }
                )[:12]
                result = {
                    "subject": safe_subject or "（無主旨）",
                    "snippet": _context_window(
                        safe_snippet,
                        needles=(
                            *matched_terms,
                            *filter_needles,
                            *_query_needles(query_text),
                        ),
                    ),
                    "sent_at": message.sent_at,
                    "score": len(matched_terms),
                    "matched_terms": matched_terms,
                    "citation": {
                        "citation_id": "mailcitation_"
                        + sha256_json(
                            {
                                "mail_import_session_id": (
                                    bundle.mail_import_session.mail_import_session_id
                                ),
                                "source_observation_id": segment.source_observation_id,
                            }
                        )[-24:],
                        "source_observation_id": segment.source_observation_id,
                    },
                    "content_redacted": bool(subject_redactions or snippet_redactions),
                    "source_kind": (
                        "uploaded_uat"
                        if message.email_message_id in uploaded_message_ids
                        else "preloaded"
                    ),
                }
                (
                    result["_subject_business_matches"],
                    result["_snippet_business_matches"],
                ) = _business_match_counts(
                    safe_subject,
                    safe_snippet,
                    filter_groups,
                )
                results.append(result)
                if len(results) >= 500:
                    return results
        return results

    def upload_mail_files(
        self,
        files: Sequence[UatUploadedMailPart],
    ) -> dict[str, Any]:
        if not files or len(files) > self.config.max_upload_files:
            raise ContractValidationError("UAT upload file count is invalid")
        actor = self.config.bundle.mail_import_session
        created_at = _timestamp(self.config.fixed_now)
        parsed_by_hash = {}
        duplicate_in_request_count = 0
        for uploaded_file in files:
            parsed = parse_uat_uploaded_eml(
                uploaded_file.content,
                owner_user_id=actor.owner_user_id,
                workspace_id=actor.workspace_id,
                created_at=created_at,
            )
            if parsed.content_hash in parsed_by_hash:
                duplicate_in_request_count += 1
                continue
            parsed_by_hash[parsed.content_hash] = (parsed, uploaded_file.content)

        created_hashes: list[str] = []
        with self._lock:
            existing_hashes = set(self._uploaded_content_hashes)
            new_items = [
                item
                for content_hash, item in parsed_by_hash.items()
                if content_hash not in existing_hashes
            ]
            duplicate_count = duplicate_in_request_count + len(parsed_by_hash) - len(new_items)
            prospective_bundles = [
                *self._uploaded_bundles,
                *(parsed.bundle for parsed, _ in new_items),
            ]
            prospective_gateway = (
                MailEvidenceQueryGateway(prospective_bundles) if prospective_bundles else None
            )
            warnings = sorted({warning for parsed, _ in new_items for warning in parsed.warnings})
            try:
                for parsed, content in new_items:
                    if self._upload_store.store(parsed.content_hash, content):
                        created_hashes.append(parsed.content_hash)
                self._event_store.append(
                    {
                        "event_type": "mail_upload",
                        "created_at": created_at,
                        "accepted_file_count": len(new_items),
                        "duplicate_file_count": duplicate_count,
                        "content_hashes": [parsed.content_hash for parsed, _ in new_items],
                        "warnings": warnings,
                    }
                )
            except Exception:
                for content_hash in created_hashes:
                    self._upload_store.remove(content_hash)
                raise

            self._uploaded_content_hashes.update(parsed.content_hash for parsed, _ in new_items)
            self._uploaded_bundles = prospective_bundles
            for parsed, _ in new_items:
                self._uploaded_warnings.update(parsed.warnings)
            self._install_uploaded_index(
                prospective_bundles,
                gateway=prospective_gateway,
            )
            total_uploaded_file_count = len(self._uploaded_bundles)
            total_uploaded_message_count = len(self._uploaded_message_ids)

        response = {
            "status": "uploaded",
            "accepted_file_count": len(new_items),
            "duplicate_file_count": duplicate_count,
            "uploaded_message_count": len(new_items),
            "total_uploaded_file_count": total_uploaded_file_count,
            "total_uploaded_message_count": total_uploaded_message_count,
            "warnings": warnings,
            "notice": (
                "新郵件已加入共享 UAT 索引，可立即回到聊天查詢。" "附件內容目前不會建立搜尋索引。"
            ),
            "claim_boundary": {
                "chatgpt_bypassed": True,
                "mail_upload_performed": bool(new_items),
                "private_uat_storage_written": bool(new_items),
                "project_or_wiki_write_performed": False,
                "canonical_graph_write_performed": False,
                "autonomous_business_decision": False,
                "production_ready": False,
            },
        }
        assert_public_payload_safe(response, "mail_human_uat_upload_response")
        return response

    def _install_uploaded_index(
        self,
        bundles: Sequence[MailEvidenceBundle],
        *,
        gateway: MailEvidenceQueryGateway | None = None,
    ) -> None:
        resolved_bundles = list(bundles)
        self._upload_gateway = (
            gateway
            if gateway is not None
            else (MailEvidenceQueryGateway(resolved_bundles) if resolved_bundles else None)
        )
        message_by_id = dict(self._base_message_by_id)
        uploaded_message_ids: set[str] = set()
        for bundle in resolved_bundles:
            for message in bundle.messages:
                message_by_id[message.email_message_id] = message
                uploaded_message_ids.add(message.email_message_id)
        self._message_by_id = message_by_id
        self._uploaded_message_ids = frozenset(uploaded_message_ids)
        self._all_bundles = (self.config.bundle, *resolved_bundles)

    def record_feedback(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        _expect_exact_keys(payload, _FEEDBACK_KEYS, required={"query_id", "verdict"})
        query_id = _validated_text(payload.get("query_id"), "query_id", max_chars=64)
        if not _QUERY_ID_RE.fullmatch(query_id):
            raise ContractValidationError("query_id is invalid")
        verdict = payload.get("verdict")
        if verdict not in _VERDICTS:
            raise ContractValidationError("verdict is invalid")
        note_value = payload.get("note", "")
        if note_value is None:
            note_value = ""
        if not isinstance(note_value, str) or len(note_value) > _MAX_NOTE_CHARS:
            raise ContractValidationError("note is invalid")
        note = note_value.strip()
        if note:
            safe_public_string(note, "feedback_note")
        with self._lock:
            if query_id not in self._known_query_ids:
                raise ContractValidationError("query_id is not available in this UAT session")
        feedback_id = f"uatfeedback_{secrets.token_hex(12)}"
        created_at = _timestamp(self.config.fixed_now)
        self._event_store.append(
            {
                "event_type": "feedback",
                "created_at": created_at,
                "feedback_id": feedback_id,
                "query_id": query_id,
                "verdict": verdict,
                "note": note,
            }
        )
        with self._lock:
            self._feedback_count += 1
            self._verdict_counts[str(verdict)] += 1
        response = {
            "status": "recorded",
            "feedback_id": feedback_id,
            "query_id": query_id,
            "verdict": verdict,
            "created_at": created_at,
        }
        assert_public_payload_safe(response, "mail_human_uat_feedback_response")
        return response

    def session_summary(self) -> dict[str, Any]:
        with self._lock:
            response = {
                "status": "ready",
                "started_at": self.started_at,
                "query_count": self._query_count,
                "feedback_count": self._feedback_count,
                "verdict_counts": {
                    verdict: self._verdict_counts.get(verdict, 0) for verdict in sorted(_VERDICTS)
                },
                "upload_supported": True,
                "uploaded_file_count": len(self._uploaded_bundles),
                "uploaded_message_count": len(self._uploaded_message_ids),
                "upload_warning_counts": dict(sorted(self._uploaded_warnings.items())),
                "read_only_business_systems": True,
                "upload_required": False,
            }
        assert_public_payload_safe(response, "mail_human_uat_session_summary")
        return response


def build_mail_human_uat_http_handler(
    service: MailHumanUatService,
) -> type[BaseHTTPRequestHandler]:
    class MailHumanUatHttpHandler(BaseHTTPRequestHandler):
        server_version = "FormOwlMailHumanUAT/0.1"

        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route == "/":
                self._send_html(
                    HTTPStatus.OK,
                    render_mail_human_uat_page(),
                    allow_same_origin_embedding=False,
                )
                return
            if route == "/upload":
                self._send_html(
                    HTTPStatus.OK,
                    render_mail_human_uat_upload_page(),
                    allow_same_origin_embedding=True,
                )
                return
            if route == "/api/health":
                self._send_json(HTTPStatus.OK, service.health())
                return
            if route == "/api/session-summary":
                self._send_json(HTTPStatus.OK, service.session_summary())
                return
            if route == "/favicon.ico":
                self._send_empty(HTTPStatus.NO_CONTENT)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")

        def do_POST(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route not in {"/api/query", "/api/feedback", "/api/upload"}:
                self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")
                return
            try:
                if route == "/api/upload":
                    files = self._read_upload_files()
                    response = service.upload_mail_files(files)
                    self._send_json(HTTPStatus.CREATED, response)
                    return
                payload = self._read_json_body()
                if route == "/api/query":
                    response = service.query(payload)
                else:
                    response = service.record_feedback(payload)
            except UatUploadRequestTooLarge:
                self._send_error(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "upload_request_too_large",
                )
                return
            except (ContractValidationError, ValueError, json.JSONDecodeError):
                self._send_error(HTTPStatus.BAD_REQUEST, "request_rejected")
                return
            except Exception:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "request_failed")
                return
            self._send_json(HTTPStatus.OK, response)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send_error(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _read_json_body(self) -> dict[str, Any]:
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise ContractValidationError("request content type must be application/json")
            content_length_value = self.headers.get("Content-Length")
            if content_length_value is None or not content_length_value.isdigit():
                raise ContractValidationError("request content length is required")
            content_length = int(content_length_value)
            if content_length <= 0 or content_length > service.config.max_request_bytes:
                raise ContractValidationError("request body size is invalid")
            body = self.rfile.read(content_length)
            if len(body) != content_length:
                raise ContractValidationError("request body is incomplete")
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, dict):
                raise ContractValidationError("request body must be a JSON object")
            return value

        def _read_upload_files(self) -> list[UatUploadedMailPart]:
            content_lengths = self.headers.get_all("Content-Length")
            if not content_lengths or len(content_lengths) != 1:
                raise ContractValidationError("exactly one upload content length is required")
            content_length_value = self.headers.get("Content-Length")
            if content_length_value is None or not content_length_value.isdigit():
                raise ContractValidationError("upload content length is required")
            content_length = int(content_length_value)
            if content_length <= 0 or content_length > service.config.max_upload_request_bytes:
                raise UatUploadRequestTooLarge("upload request size is invalid")
            body = self.rfile.read(content_length)
            if len(body) != content_length:
                raise ContractValidationError("upload request body is incomplete")
            return parse_uat_eml_multipart(
                self.headers.get("Content-Type", ""),
                body,
                max_files=service.config.max_upload_files,
                max_file_bytes=service.config.max_upload_file_bytes,
            )

        def _send_error(
            self,
            status: HTTPStatus,
            error_code: str,
            *,
            extra_headers: Mapping[str, str] | None = None,
        ) -> None:
            payload = {
                "status": "error",
                "error_code": error_code,
                "http_status_code": int(status),
            }
            assert_public_payload_safe(payload, "mail_human_uat_http_error")
            self._send_json(status, payload, extra_headers=extra_headers)

        def _send_html(
            self,
            status: HTTPStatus,
            html: str,
            *,
            allow_same_origin_embedding: bool,
        ) -> None:
            encoded = html.encode("utf-8")
            self.send_response(status)
            self._send_security_headers(
                content_type="text/html; charset=utf-8",
                allow_same_origin_embedding=allow_same_origin_embedding,
            )
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(
            self,
            status: HTTPStatus,
            payload: Mapping[str, Any],
            *,
            extra_headers: Mapping[str, str] | None = None,
        ) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self._send_security_headers(
                content_type="application/json; charset=utf-8",
                allow_same_origin_embedding=False,
            )
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_empty(self, status: HTTPStatus) -> None:
            self.send_response(status)
            self._send_security_headers(
                content_type="text/plain; charset=utf-8",
                allow_same_origin_embedding=False,
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_security_headers(
            self,
            *,
            content_type: str,
            allow_same_origin_embedding: bool,
        ) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "X-Frame-Options",
                "SAMEORIGIN" if allow_same_origin_embedding else "DENY",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; "
                "style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; "
                "connect-src 'self'; "
                "img-src 'self' data:; "
                "frame-src 'self'; "
                "base-uri 'none'; form-action 'self'; "
                "frame-ancestors " + ("'self'" if allow_same_origin_embedding else "'none'"),
            )

    return MailHumanUatHttpHandler


def create_mail_human_uat_http_server(
    host: str,
    port: int,
    service: MailHumanUatService,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), build_mail_human_uat_http_handler(service))


def render_mail_human_uat_page() -> str:
    return _CHAT_UAT_HTML


def render_mail_human_uat_upload_page() -> str:
    return _UPLOAD_IFRAME_HTML


class _PrivateUatEventStore:
    def __init__(self, state_dir: str | Path) -> None:
        self.root = Path(state_dir)
        if self.root.is_symlink():
            raise ContractValidationError("UAT state directory must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / "mail-human-uat-events.private.jsonl"
        if self.path.is_symlink():
            raise ContractValidationError("UAT event store must not be a symlink")
        self._lock = threading.Lock()

    def append(self, payload: Mapping[str, Any]) -> None:
        encoded = (
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        with self._lock:
            descriptor = os.open(self.path, flags, 0o600)
            try:
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("private UAT event write failed")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.chmod(self.path, 0o600)


def _expect_exact_keys(
    payload: Mapping[str, Any],
    allowed: set[str],
    *,
    required: set[str],
) -> None:
    keys = set(payload)
    if keys - allowed or required - keys:
        raise ContractValidationError("request fields are invalid")


def _validated_text(value: Any, field_name: str, *, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_chars:
        raise ContractValidationError(f"{field_name} is invalid")
    resolved = value.strip()
    safe_public_string(resolved, field_name)
    return resolved


def _expand_business_query(query_text: str) -> tuple[str, tuple[tuple[str, ...], ...]]:
    lowered = query_text.casefold()
    expansions: list[str] = []
    filters: list[tuple[str, ...]] = []
    for triggers, aliases, result_terms in _BUSINESS_ALIASES:
        if any(trigger.casefold() in lowered for trigger in triggers):
            expansions.extend(aliases)
            filters.append(result_terms)
    for term in _EXACT_BUSINESS_FILTERS:
        if term.casefold() in lowered:
            filters.append((term,))
    expanded = " ".join([query_text, *expansions]).strip()
    return expanded, tuple(filters)


def _matches_filter_groups(rendered: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    lowered = rendered.casefold()
    return all(any(term.casefold() in lowered for term in group) for group in groups)


def _business_match_counts(
    subject: str,
    snippet: str,
    groups: tuple[tuple[str, ...], ...],
) -> tuple[int, int]:
    subject_lowered = subject.casefold()
    snippet_lowered = snippet.casefold()
    subject_matches = sum(
        any(term.casefold() in subject_lowered for term in group) for group in groups
    )
    snippet_matches = sum(
        any(term.casefold() in snippet_lowered for term in group) for group in groups
    )
    return subject_matches, snippet_matches


def _query_needles(query_text: str) -> tuple[str, ...]:
    values = re.findall(r"[A-Za-z0-9_@.-]{2,}|[\u3400-\u9fff]{2,}", query_text)
    return tuple(values[:12])


def _context_window(text: str, *, needles: tuple[str, ...], max_chars: int = 1600) -> str:
    if len(text) <= max_chars:
        return text
    lowered = text.casefold()
    positions = [
        position
        for needle in needles
        if needle and (position := lowered.find(needle.casefold())) >= 0
    ]
    center = min(positions) if positions else 0
    start = max(0, center - 280)
    end = min(len(text), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    return ("… " if start else "") + text[start:end] + (" …" if end < len(text) else "")


def _public_citation(citation: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if citation is None:
        return None
    payload = {
        "citation_id": citation.get("citation_id"),
        "source_observation_id": citation.get("source_observation_id"),
    }
    assert_public_payload_safe(payload, "mail_human_uat_citation")
    return payload


def _deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for result in results:
        key = (
            result.get("subject"),
            result.get("sent_at"),
            result.get("snippet"),
        )
        current = selected.get(key)
        if current is None or int(result["score"]) > int(current["score"]):
            selected[key] = result
    return list(selected.values())


def _timestamp(value: str | None) -> str:
    if value is not None:
        return value
    return now_iso()


def _timestamp_sort_key(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return float("-inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


_CHAT_UAT_HTML = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FormOwl 對話測試</title>
  <style>
    :root {
      color-scheme: light;
      --sidebar: #171b20;
      --sidebar-soft: #242a31;
      --canvas: #f7f7f5;
      --panel: #ffffff;
      --line: #deded9;
      --ink: #242723;
      --muted: #73766f;
      --brand: #147d64;
      --brand-dark: #0e5f4c;
      --user: #e7f3ee;
      --danger: #a43b3b;
      --shadow: 0 18px 50px rgba(25, 35, 31, .14);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      color: var(--ink);
      background: var(--canvas);
      font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
    }
    button, textarea { font: inherit; }
    button { cursor: pointer; }
    .app { min-height: 100vh; display: grid; grid-template-columns: 260px 1fr; }
    .sidebar {
      position: sticky; top: 0; height: 100vh; padding: 22px 17px;
      background: var(--sidebar); color: #f2f4f2; display: flex; flex-direction: column;
    }
    .brand { display: flex; align-items: center; gap: 11px; padding: 3px 8px 20px; }
    .brand-mark {
      width: 35px; height: 35px; border-radius: 11px; display: grid; place-items: center;
      background: linear-gradient(135deg, #27a780, #116852); font-weight: 900;
    }
    .brand-title { font-weight: 800; }
    .brand-subtitle { color: #9ba59f; font-size: 12px; margin-top: 2px; }
    .new-chat {
      width: 100%; border: 1px solid #3c444c; border-radius: 12px; padding: 11px 13px;
      color: white; background: var(--sidebar-soft); text-align: left; font-weight: 700;
    }
    .sidebar-section { margin-top: 24px; padding: 0 8px; }
    .sidebar-label {
      color: #87918b; font-size: 11px; font-weight: 800; letter-spacing: .12em;
      text-transform: uppercase; margin-bottom: 11px;
    }
    .side-fact { color: #c7cec9; font-size: 13px; line-height: 1.55; margin: 8px 0; }
    .side-fact b { color: white; }
    .sidebar-bottom { margin-top: auto; color: #89938d; font-size: 12px; line-height: 1.55; padding: 8px; }
    .workspace { min-width: 0; min-height: 100vh; display: flex; flex-direction: column; }
    .topbar {
      height: 58px; padding: 0 24px; border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.88); backdrop-filter: blur(12px);
      display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0;
      z-index: 5;
    }
    .topbar strong { font-size: 14px; }
    .status { color: var(--muted); font-size: 12px; }
    .status::before {
      content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 50%;
      background: #e5a31a; margin-right: 7px;
    }
    .status.ready::before { background: #22a06b; }
    .conversation {
      width: min(860px, calc(100% - 32px)); margin: 0 auto; flex: 1;
      padding: 42px 0 170px;
    }
    .message { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 13px; margin: 0 0 30px; }
    .avatar {
      width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center;
      font-weight: 900; font-size: 13px; background: var(--brand); color: white;
    }
    .message.user .avatar { background: #4e5964; }
    .bubble { min-width: 0; line-height: 1.7; }
    .message.user .bubble {
      justify-self: start; background: var(--user); padding: 12px 16px; border-radius: 16px;
      max-width: 90%; white-space: pre-wrap;
    }
    .assistant-title { font-weight: 800; margin-bottom: 7px; }
    .assistant-text { white-space: pre-wrap; }
    .quick-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
    .chip {
      border: 1px solid var(--line); background: white; color: #3d453f;
      border-radius: 999px; padding: 8px 12px; font-size: 13px;
    }
    .chip:hover { border-color: var(--brand); color: var(--brand-dark); }
    .evidence-list { display: grid; gap: 10px; margin-top: 15px; }
    .evidence {
      border: 1px solid var(--line); border-radius: 15px; padding: 14px 15px;
      background: var(--panel);
    }
    .evidence h3 { margin: 0; font-size: 14px; line-height: 1.5; }
    .evidence-meta { color: var(--muted); font-size: 12px; margin: 5px 0 9px; }
    .evidence p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
    .badge {
      display: inline-block; margin-left: 7px; border-radius: 999px; padding: 2px 7px;
      background: #fff0bf; color: #725a12; font-size: 10px; font-weight: 800;
    }
    .citation { color: var(--muted); font-family: ui-monospace, monospace; font-size: 10px; margin-top: 10px; }
    .feedback-row { display: flex; gap: 7px; margin-top: 13px; align-items: center; }
    .feedback-row span { color: var(--muted); font-size: 12px; }
    .feedback-row button {
      border: 1px solid var(--line); background: white; border-radius: 9px; padding: 6px 9px;
      color: var(--muted);
    }
    .feedback-row button:hover { border-color: var(--brand); color: var(--brand); }
    .composer-wrap {
      position: fixed; left: 260px; right: 0; bottom: 0; z-index: 6;
      padding: 18px 20px 24px; background: linear-gradient(transparent, var(--canvas) 28%);
    }
    .composer {
      width: min(860px, 100%); margin: 0 auto; border: 1px solid #cfcfca;
      border-radius: 19px; background: white; box-shadow: var(--shadow);
      display: grid; grid-template-columns: auto 1fr auto; align-items: end; gap: 8px;
      padding: 9px 10px;
    }
    .composer textarea {
      border: 0; outline: 0; resize: none; min-height: 42px; max-height: 150px;
      padding: 10px 6px; line-height: 1.5; color: var(--ink);
    }
    .icon-button, .send {
      width: 42px; height: 42px; border: 0; border-radius: 13px; display: grid;
      place-items: center; font-weight: 900;
    }
    .icon-button { background: #f0f1ee; color: #4d554f; font-size: 20px; }
    .icon-button:hover { background: #e3e9e5; color: var(--brand); }
    .send { background: var(--brand); color: white; }
    .send:hover { background: var(--brand-dark); }
    .send:disabled { opacity: .5; cursor: wait; }
    .composer-note { text-align: center; color: var(--muted); font-size: 11px; margin-top: 8px; }
    .modal {
      position: fixed; inset: 0; z-index: 20; background: rgba(20, 24, 22, .60);
      display: grid; place-items: center; padding: 22px; backdrop-filter: blur(7px);
    }
    .modal.hidden { display: none; }
    .modal-card {
      width: min(720px, 100%); height: min(650px, calc(100vh - 44px)); background: white;
      border-radius: 22px; box-shadow: 0 28px 90px rgba(0,0,0,.3); overflow: hidden;
      display: grid; grid-template-rows: 54px 1fr;
    }
    .modal-head {
      display: flex; align-items: center; justify-content: space-between; padding: 0 17px;
      border-bottom: 1px solid var(--line);
    }
    .modal-head strong { font-size: 14px; }
    .close {
      border: 0; background: #f0f1ee; width: 34px; height: 34px; border-radius: 10px;
      font-size: 20px; line-height: 1;
    }
    iframe { width: 100%; height: 100%; border: 0; background: #f7f7f5; }
    .error-text { color: var(--danger); }
    @media (max-width: 760px) {
      .app { grid-template-columns: 1fr; }
      .sidebar { display: none; }
      .composer-wrap { left: 0; }
      .conversation { padding-top: 26px; }
      .topbar { padding: 0 16px; }
      .message { grid-template-columns: 30px minmax(0, 1fr); gap: 10px; }
      .avatar { width: 30px; height: 30px; border-radius: 9px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">F</div>
        <div>
          <div class="brand-title">FormOwl</div>
          <div class="brand-subtitle">Shared mail UAT</div>
        </div>
      </div>
      <button class="new-chat" id="new-chat" type="button">＋ 新對話</button>
      <div class="sidebar-section">
        <div class="sidebar-label">共同測試空間</div>
        <div class="side-fact">共享上傳：<b id="upload-count">讀取中…</b></div>
        <div class="side-fact">不經 ChatGPT；不回寫郵件、專案或正式知識圖譜。</div>
      </div>
      <div class="sidebar-bottom">內網／VPN 功能測試介面<br>目前支援 EML，附件內容不建立索引。</div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <strong>FormOwl 郵件助手</strong>
        <div class="status" id="server-status">連線中</div>
      </header>
      <section class="conversation" id="conversation">
        <article class="message assistant">
          <div class="avatar">F</div>
          <div class="bubble">
            <div class="assistant-title">你好，我是 FormOwl 測試助手。</div>
            <div class="assistant-text">直接問我量產時間、Pull-in 料件、PO、料號或供應商進度。需要加入新郵件時，按下方的迴紋針，我會開啟郵件上傳視窗。</div>
            <div class="quick-actions">
              <button class="chip quick" data-query="最近一次文顥的量產時間" type="button">文顥最近排程</button>
              <button class="chip quick" data-query="有哪些料件需要 pull-in" type="button">Pull-in 料件</button>
              <button class="chip quick" data-query="PO 470002154" type="button">查 PO</button>
              <button class="chip" id="welcome-upload" type="button">📎 上傳新郵件</button>
            </div>
          </div>
        </article>
      </section>
      <div class="composer-wrap">
        <div class="composer">
          <button class="icon-button" id="open-upload" type="button" title="上傳 EML">📎</button>
          <textarea id="chat-input" rows="1" placeholder="傳訊息給 FormOwl…"></textarea>
          <button class="send" id="send" type="button" title="送出">↑</button>
        </div>
        <div class="composer-note">FormOwl 可能只找到部分郵件證據；排程、交期與數量仍請依原信確認。</div>
      </div>
    </main>
  </div>

  <div class="modal hidden" id="upload-modal" role="dialog" aria-modal="true" aria-label="上傳郵件">
    <div class="modal-card">
      <div class="modal-head">
        <strong>加入新的測試郵件</strong>
        <button class="close" id="close-upload" type="button" aria-label="關閉">×</button>
      </div>
      <iframe id="upload-frame" src="/upload" title="FormOwl 郵件上傳"></iframe>
    </div>
  </div>

  <script>
    const byId = (id) => document.getElementById(id);
    const conversation = byId("conversation");
    let busy = false;

    async function api(path, options = {}) {
      const headers = { ...(options.headers || {}) };
      if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
      }
      const response = await fetch(path, { ...options, cache: "no-store", headers });
      let payload = {};
      try { payload = await response.json(); } catch (_) {}
      if (!response.ok) {
        const error = new Error(payload.error_code || "request_failed");
        error.status = response.status;
        throw error;
      }
      return payload;
    }

    function scrollToLatest() {
      window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    }

    function createMessage(role) {
      const article = document.createElement("article");
      article.className = `message ${role}`;
      const avatar = document.createElement("div");
      avatar.className = "avatar";
      avatar.textContent = role === "user" ? "你" : "F";
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      article.append(avatar, bubble);
      conversation.appendChild(article);
      return { article, bubble };
    }

    function appendTextMessage(role, text, className = "") {
      const { bubble } = createMessage(role);
      const node = document.createElement("div");
      node.className = className || "assistant-text";
      node.textContent = text;
      bubble.appendChild(node);
      scrollToLatest();
      return bubble;
    }

    function openUpload() {
      byId("upload-modal").classList.remove("hidden");
      byId("upload-frame").focus();
    }

    function closeUpload() {
      byId("upload-modal").classList.add("hidden");
    }

    function querySort(query) {
      const normalized = query.toLowerCase();
      const recentTerms = ["最近", "最新", "近期", "目前", "現在", "latest", "recent"];
      return recentTerms.some((term) => normalized.includes(term)) ? "recent" : "relevance";
    }

    function addFeedbackControls(parent, queryId) {
      const row = document.createElement("div");
      row.className = "feedback-row";
      const label = document.createElement("span");
      label.textContent = "這個回答有幫助嗎？";
      row.appendChild(label);
      for (const [text, verdict] of [["有", "correct"], ["部分", "partially_correct"], ["沒有", "incorrect"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = text;
        button.addEventListener("click", async () => {
          try {
            await api("/api/feedback", {
              method: "POST",
              body: JSON.stringify({ query_id: queryId, verdict, note: "" })
            });
            row.replaceChildren();
            const saved = document.createElement("span");
            saved.textContent = "已記錄，謝謝。";
            row.appendChild(saved);
          } catch (_) {
            label.textContent = "回饋暫時無法記錄。";
            label.className = "error-text";
          }
        });
        row.appendChild(button);
      }
      parent.appendChild(row);
    }

    function renderAssistantResult(payload, holder) {
      holder.replaceChildren();
      const title = document.createElement("div");
      title.className = "assistant-title";
      title.textContent = payload.results.length
        ? `我找到 ${payload.result_count} 筆相關郵件證據。`
        : "目前沒有找到符合的郵件證據。";
      holder.appendChild(title);

      const explanation = document.createElement("div");
      explanation.className = "assistant-text";
      explanation.textContent = payload.results.length
        ? payload.notice
        : "你可以換用 PO、料號、供應商等明確關鍵字，或先上傳新的 EML 郵件。";
      holder.appendChild(explanation);

      if (!payload.results.length) {
        const actions = document.createElement("div");
        actions.className = "quick-actions";
        const upload = document.createElement("button");
        upload.type = "button";
        upload.className = "chip";
        upload.textContent = "📎 上傳新郵件";
        upload.addEventListener("click", openUpload);
        actions.appendChild(upload);
        holder.appendChild(actions);
      } else {
        const list = document.createElement("div");
        list.className = "evidence-list";
        for (const item of payload.results) {
          const card = document.createElement("article");
          card.className = "evidence";
          const subject = document.createElement("h3");
          subject.textContent = item.subject;
          if (item.source_kind === "uploaded_uat") {
            const badge = document.createElement("span");
            badge.className = "badge";
            badge.textContent = "共同測試上傳";
            subject.appendChild(badge);
          }
          const meta = document.createElement("div");
          meta.className = "evidence-meta";
          meta.textContent = item.sent_at ? `郵件時間：${item.sent_at}` : "郵件時間：未提供";
          const snippet = document.createElement("p");
          snippet.textContent = item.snippet;
          card.append(subject, meta, snippet);
          if (item.citation) {
            const citation = document.createElement("div");
            citation.className = "citation";
            citation.textContent = `證據：${item.citation.citation_id} · ${item.citation.source_observation_id}`;
            card.appendChild(citation);
          }
          list.appendChild(card);
        }
        holder.appendChild(list);
      }
      addFeedbackControls(holder, payload.query_id);
      scrollToLatest();
    }

    async function ask(queryText) {
      const query = queryText.trim();
      if (!query || busy) return;
      busy = true;
      byId("send").disabled = true;
      byId("chat-input").value = "";
      appendTextMessage("user", query);
      const { bubble } = createMessage("assistant");
      const loading = document.createElement("div");
      loading.className = "assistant-text";
      loading.textContent = "正在查詢郵件證據…";
      bubble.appendChild(loading);
      scrollToLatest();
      try {
        const payload = await api("/api/query", {
          method: "POST",
          body: JSON.stringify({ query_text: query, sort: querySort(query), limit: 8 })
        });
        renderAssistantResult(payload, bubble);
      } catch (_) {
        bubble.replaceChildren();
        const error = document.createElement("div");
        error.className = "error-text";
        error.textContent = "查詢暫時失敗，請稍後再試。";
        bubble.appendChild(error);
      } finally {
        busy = false;
        byId("send").disabled = false;
        byId("chat-input").focus();
      }
    }

    async function refreshSummary() {
      try {
        const summary = await api("/api/session-summary", { method: "GET" });
        byId("upload-count").textContent = `${summary.uploaded_file_count} 封 EML`;
      } catch (_) {
        byId("upload-count").textContent = "暫時無法讀取";
      }
    }

    byId("send").addEventListener("click", () => ask(byId("chat-input").value));
    byId("chat-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        ask(event.currentTarget.value);
      }
    });
    byId("open-upload").addEventListener("click", openUpload);
    byId("welcome-upload").addEventListener("click", openUpload);
    byId("close-upload").addEventListener("click", closeUpload);
    byId("upload-modal").addEventListener("click", (event) => {
      if (event.target === byId("upload-modal")) closeUpload();
    });
    byId("new-chat").addEventListener("click", () => {
      const messages = conversation.querySelectorAll(".message");
      for (let index = 1; index < messages.length; index += 1) messages[index].remove();
      byId("chat-input").focus();
    });
    for (const button of document.querySelectorAll(".quick")) {
      button.addEventListener("click", () => ask(button.dataset.query || ""));
    }
    window.addEventListener("message", (event) => {
      if (
        event.origin !== window.location.origin
        || event.source !== byId("upload-frame").contentWindow
        || !event.data
      ) return;
      if (event.data.type === "formowl-upload-complete") {
        closeUpload();
        const count = Number(event.data.accepted_file_count || 0);
        appendTextMessage(
          "assistant",
          count
            ? `已加入 ${count} 封新郵件。現在可以直接問我這些郵件的內容。`
            : "這些郵件先前已上傳，現在可以直接查詢。"
        );
        refreshSummary();
      } else if (event.data.type === "formowl-upload-close") {
        closeUpload();
      }
    });

    fetch("/api/health", { cache: "no-store" })
      .then((response) => response.json())
      .then((payload) => {
        byId("server-status").textContent = payload.status === "ready" ? "服務已就緒" : "服務準備中";
        byId("server-status").classList.toggle("ready", payload.status === "ready");
      })
      .catch(() => { byId("server-status").textContent = "服務未連線"; });
    refreshSummary();
  </script>
</body>
</html>
"""

_UPLOAD_IFRAME_HTML = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>加入郵件</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #242723;
      --muted: #73766f;
      --line: #deded9;
      --brand: #147d64;
      --brand-dark: #0e5f4c;
      --danger: #a43b3b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; background: #f7f7f5; color: var(--ink);
      font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
    }
    button, input { font: inherit; }
    .shell { padding: 28px; }
    h1 { margin: 0 0 8px; font-size: 24px; }
    .lead { color: var(--muted); line-height: 1.65; margin: 0 0 22px; }
    .drop {
      border: 2px dashed #b8c3bd; border-radius: 19px; background: white; padding: 34px 20px;
      text-align: center; transition: border .15s, background .15s;
    }
    .drop.dragging { border-color: var(--brand); background: #eef8f4; }
    .drop-icon {
      width: 50px; height: 50px; margin: 0 auto 13px; border-radius: 16px;
      display: grid; place-items: center; background: #e7f3ee; color: var(--brand);
      font-size: 25px; font-weight: 900;
    }
    .drop strong { display: block; margin-bottom: 6px; }
    .drop span { color: var(--muted); font-size: 13px; }
    input[type=file] { display: none; }
    .choose {
      display: inline-block; margin-top: 15px; border: 1px solid var(--line);
      background: white; color: var(--brand-dark); border-radius: 11px; padding: 9px 13px;
      cursor: pointer; font-weight: 800;
    }
    .files { display: grid; gap: 8px; margin: 16px 0 0; }
    .file {
      border: 1px solid var(--line); border-radius: 11px; background: white; padding: 10px 12px;
      display: flex; justify-content: space-between; gap: 10px; font-size: 13px;
    }
    .file span:last-child { color: var(--muted); white-space: nowrap; }
    .actions { display: flex; justify-content: flex-end; gap: 9px; margin-top: 20px; }
    button {
      border: 0; border-radius: 12px; padding: 11px 16px; cursor: pointer; font-weight: 800;
    }
    .cancel { background: #e9ebe8; color: #4e554f; }
    .upload { background: var(--brand); color: white; }
    .upload:hover { background: var(--brand-dark); }
    button:disabled { opacity: .5; cursor: wait; }
    .message { min-height: 24px; margin-top: 12px; color: var(--brand-dark); font-weight: 700; }
    .message.error { color: var(--danger); }
    .limits {
      margin-top: 18px; border-left: 4px solid #e8b541; background: #fff8df;
      border-radius: 9px; padding: 11px 13px; color: #695519; font-size: 12px; line-height: 1.6;
    }
    @media (max-width: 560px) {
      .shell { padding: 20px; }
      .actions { display: grid; grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <h1>加入新的測試郵件</h1>
    <p class="lead">選擇 EML 後，FormOwl 會立即解析並加入這個共同測試空間。完成後可回到聊天直接詢問。</p>
    <section class="drop" id="drop">
      <div class="drop-icon">＋</div>
      <strong>將 EML 拖到這裡</strong>
      <span>或從電腦選擇一封或多封郵件</span>
      <label class="choose" for="mail-files">選擇 EML</label>
      <input id="mail-files" type="file" accept=".eml,message/rfc822" multiple>
    </section>
    <section class="files" id="files"></section>
    <div class="limits">每次最多 20 封、單封最多 25 MB，合計最多 60 MB。目前只支援 EML；MSG 請先另存為 EML。附件會保留在原郵件中，但附件檔案內容不建立搜尋索引。</div>
    <div class="message" id="message"></div>
    <div class="actions">
      <button class="cancel" id="cancel" type="button">取消</button>
      <button class="upload" id="upload" type="button">上傳並加入聊天</button>
    </div>
  </main>
  <script>
    const input = document.getElementById("mail-files");
    const drop = document.getElementById("drop");
    const list = document.getElementById("files");
    const message = document.getElementById("message");
    const uploadButton = document.getElementById("upload");
    const maxFileBytes = 25 * 1024 * 1024;
    const maxTotalBytes = 60 * 1024 * 1024;
    let selectedFiles = [];

    function setMessage(text, error = false) {
      message.textContent = text;
      message.classList.toggle("error", error);
    }

    function renderFiles() {
      list.replaceChildren();
      for (const file of selectedFiles) {
        const row = document.createElement("div");
        row.className = "file";
        const name = document.createElement("span");
        name.textContent = file.name;
        const size = document.createElement("span");
        size.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB`;
        row.append(name, size);
        list.appendChild(row);
      }
      setMessage(selectedFiles.length ? `已選擇 ${selectedFiles.length} 封郵件。` : "");
    }

    function selectFiles(files) {
      selectedFiles = Array.from(files || []);
      if (selectedFiles.length > 20) {
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage("一次最多選擇 20 封郵件。", true);
        return;
      }
      if (selectedFiles.some((file) => !file.name.toLowerCase().endsWith(".eml"))) {
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage("目前只接受 .eml 郵件。", true);
        return;
      }
      if (selectedFiles.some((file) => file.size > maxFileBytes)) {
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage("單封郵件不可超過 25 MB。", true);
        return;
      }
      if (selectedFiles.reduce((total, file) => total + file.size, 0) > maxTotalBytes) {
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage("這次選擇的郵件合計不可超過 60 MB。", true);
        return;
      }
      renderFiles();
    }

    input.addEventListener("change", () => selectFiles(input.files));
    for (const eventName of ["dragenter", "dragover"]) {
      drop.addEventListener(eventName, (event) => {
        event.preventDefault();
        drop.classList.add("dragging");
      });
    }
    for (const eventName of ["dragleave", "drop"]) {
      drop.addEventListener(eventName, (event) => {
        event.preventDefault();
        drop.classList.remove("dragging");
      });
    }
    drop.addEventListener("drop", (event) => selectFiles(event.dataTransfer.files));
    document.getElementById("cancel").addEventListener("click", () => {
      window.parent.postMessage({ type: "formowl-upload-close" }, window.location.origin);
    });
    uploadButton.addEventListener("click", async () => {
      if (!selectedFiles.length) {
        setMessage("請先選擇 EML 郵件。", true);
        return;
      }
      const form = new FormData();
      for (const file of selectedFiles) form.append("mail_files", file, file.name);
      uploadButton.disabled = true;
      setMessage(`正在解析 ${selectedFiles.length} 封郵件…`);
      try {
        const response = await fetch("/api/upload", {
          method: "POST",
          cache: "no-store",
          body: form
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error_code || "request_failed");
        setMessage(`完成：新增 ${payload.accepted_file_count} 封郵件。`);
        window.parent.postMessage(
          {
            type: "formowl-upload-complete",
            accepted_file_count: payload.accepted_file_count,
            duplicate_file_count: payload.duplicate_file_count
          },
          window.location.origin
        );
      } catch (_) {
        setMessage("上傳失敗；請確認檔案是有效的 EML，且大小未超過限制。", true);
      } finally {
        uploadButton.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


__all__ = [
    "MailHumanUatHttpConfig",
    "MailHumanUatService",
    "build_mail_human_uat_http_handler",
    "create_mail_human_uat_http_server",
    "render_mail_human_uat_page",
    "render_mail_human_uat_upload_page",
]
