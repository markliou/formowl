from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from formowl_graph import (
    EvidenceRequirement,
    ProjectionSpec,
    TaskAnchor,
    TaskFrame,
    revise_task_frame,
)

from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle
from .human_uat_upload import (
    PrivateUatMailUploadStore,
    UatUploadRequestTooLarge,
    UatUploadedResourcePart,
    parse_uat_resource_multipart,
    parse_uat_stored_resource,
    parse_uat_uploaded_resource,
)
from .query import MailEvidenceQueryGateway, _redact_mail_public_text

_MAX_REQUEST_BYTES = 32 * 1024
_MAX_UPLOAD_REQUEST_BYTES = 520 * 1024 * 1024
_MAX_UPLOAD_FILE_BYTES = 500 * 1024 * 1024
_MAX_UPLOAD_FILES = 20
_MAX_QUERY_CHARS = 500
_MAX_NOTE_CHARS = 1000
_DEFAULT_RESULT_LIMIT = 50
_MAX_RESULT_LIMIT = 100
_MAX_EVENT_SEQUENCE = (2**53) - 1
_DEFAULT_EVENT_RETENTION_DAYS = 30
_DEFAULT_MAX_EVENT_STORE_BYTES = 16 * 1024 * 1024
_QUERY_ID_RE = re.compile(r"^uatquery_[0-9a-f]{24}$")
_VISITOR_ID_RE = re.compile(r"^uatvisitor_[0-9a-f]{32}$")
_SESSION_ID_RE = re.compile(r"^uatsession_[0-9a-f]{32}$")
_EXPLICIT_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?=[A-Za-z0-9_.-]{4,}(?![A-Za-z0-9_.-]))"
    r"(?=[A-Za-z0-9_.-]*\d)[A-Za-z0-9_.-]+",
)
_PROJECTION_FORMAT_TERMS = {
    "table": ("表格", "table", "tabular"),
    "list": ("條列", "清單", "列表", "list", "bullet"),
    "timeline": ("時間軸", "時序", "timeline"),
    "narrative": ("敘述", "摘要", "narrative", "summary"),
}
_FOLLOW_UP_MARKERS = (
    "應該是",
    "只看",
    "只想",
    "不要",
    "改成",
    "補充",
    "另外",
    "同一",
    "這個",
    "那個",
    "來自",
)
_VERDICTS = {
    "correct",
    "partially_correct",
    "incorrect",
    "no_result",
    "citation_issue",
}
_SORT_OPTIONS = {"relevance", "recent"}
_QUERY_SOURCES = {"api", "composer"}
_QUERY_KEYS = {
    "query_text",
    "limit",
    "sort",
    "visitor_id",
    "session_id",
    "sequence",
    "source",
}
_FEEDBACK_KEYS = {
    "query_id",
    "verdict",
    "note",
    "visitor_id",
    "session_id",
    "sequence",
}
_INTERACTION_KEYS = {
    "visitor_id",
    "session_id",
    "sequence",
    "action",
    "details",
}
_INTERACTION_ACTIONS = {
    "page_view",
    "sidebar_toggle",
    "new_chat",
    "shell_control",
    "upload_open",
    "upload_close",
    "upload_files_selected",
    "upload_validation_error",
    "upload_submit",
    "upload_complete",
    "query_result",
    "query_error",
}
_SHELL_CONTROLS = {
    "brand_home",
    "search_conversations",
    "current_history",
    "model_selector",
    "tools_menu",
    "profile_card",
    "profile_avatar",
}
_UPLOAD_OPEN_SOURCES = {"composer", "landing", "no_result"}
_UPLOAD_CLOSE_SOURCES = {"button", "backdrop", "iframe_cancel"}
_UPLOAD_VALIDATION_REASONS = {"file_count", "file_type", "file_size", "total_size"}
_UPLOAD_SIZE_BUCKETS = {"under_5mb", "5_to_25mb", "25_to_60mb", "60_to_500mb"}
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
    event_retention_days: int = _DEFAULT_EVENT_RETENTION_DAYS
    max_event_store_bytes: int = _DEFAULT_MAX_EVENT_STORE_BYTES


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
            ("event_retention_days", config.event_retention_days),
            ("max_event_store_bytes", config.max_event_store_bytes),
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
        self._event_store = _PrivateUatEventStore(
            config.state_dir,
            retention_days=config.event_retention_days,
            max_bytes=config.max_event_store_bytes,
            fixed_now=config.fixed_now,
        )
        self._upload_store = PrivateUatMailUploadStore(
            config.state_dir,
            max_file_bytes=config.max_upload_file_bytes,
        )
        self._known_query_ids: set[str] = set()
        self._verdict_counts: Counter[str] = Counter()
        self._interaction_counts: Counter[str] = Counter()
        self._anonymous_visitor_ids: set[str] = set()
        self._anonymous_session_ids: set[str] = set()
        self._task_frames_by_session_id: dict[str, TaskFrame] = {}
        self._query_count = 0
        self._feedback_count = 0
        self._lock = threading.RLock()
        self.started_at = _timestamp(config.fixed_now)
        actor = config.bundle.mail_import_session
        stored_resources = self._upload_store.load()
        loaded_uploads = [
            parse_uat_stored_resource(
                stored,
                owner_user_id=actor.owner_user_id,
                workspace_id=actor.workspace_id,
                created_at=self.started_at,
                scratch_parent=self._upload_store.root,
            )
            for stored in stored_resources
        ]
        self._uploaded_content_hashes = {parsed.content_hash for parsed in loaded_uploads}
        self._uploaded_resource_count = len(loaded_uploads)
        self._uploaded_bundles = [bundle for parsed in loaded_uploads for bundle in parsed.bundles]
        self._uploaded_warnings = Counter(
            warning for parsed in loaded_uploads for warning in parsed.warnings
        )
        self._install_uploaded_index(self._uploaded_bundles)

    def health(self) -> dict[str, Any]:
        with self._lock:
            uploaded_file_count = self._uploaded_resource_count
        payload = {
            "status": "ready",
            "surface": "mail_human_uat",
            "chatgpt_bypassed": True,
            "authentication_required": False,
            "shared_uat": True,
            "behavior_capture_enabled": True,
            "behavior_capture_scope": "submitted_questions_and_bounded_interactions",
            "behavior_capture_retention_days": self.config.event_retention_days,
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
        limit = payload.get("limit", _DEFAULT_RESULT_LIMIT)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > _MAX_RESULT_LIMIT
        ):
            raise ContractValidationError("limit must be between 1 and 100")
        sort = payload.get("sort", "relevance")
        if sort not in _SORT_OPTIONS:
            raise ContractValidationError("sort must be relevance or recent")
        source = payload.get("source", "api")
        if source not in _QUERY_SOURCES:
            raise ContractValidationError("query source is invalid")
        tracking = _validated_tracking_fields(payload)
        session_id = tracking.get("session_id")
        with self._lock:
            prior_task_frame = (
                self._task_frames_by_session_id.get(session_id)
                if isinstance(session_id, str)
                else None
            )
        task_frame, changed_dimensions = _resolve_task_frame(
            query_text,
            page_size=limit,
            prior=prior_task_frame,
        )
        if isinstance(session_id, str):
            with self._lock:
                self._task_frames_by_session_id[session_id] = task_frame
        query_id = f"uatquery_{secrets.token_hex(12)}"
        submitted_at = _timestamp(self.config.fixed_now)
        query_hash = sha256_json(query_text)
        self._event_store.append(
            {
                "event_type": "query",
                "created_at": submitted_at,
                "query_id": query_id,
                "query_text": query_text,
                "query_hash": query_hash,
                "effective_query_hash": sha256_json(task_frame.retrieval_query_text),
                "task_frame_id": task_frame.task_frame_id,
                "task_frame_revision": task_frame.revision,
                "task_frame_changed_dimensions": list(changed_dimensions),
                "projection_format": task_frame.projection.output_format,
                "sort": sort,
                "source": source,
                **tracking,
            }
        )
        with self._lock:
            self._known_query_ids.add(query_id)
            self._query_count += 1
            self._remember_tracking(tracking)

        expanded_query, filter_groups = _expand_business_query(task_frame.retrieval_query_text)
        bundle = self.config.bundle
        actor = bundle.mail_import_session
        with self._lock:
            all_bundles = self._all_bundles
        retrieval_candidate_limit = max(
            1,
            sum(len(candidate_bundle.body_segments) for candidate_bundle in all_bundles),
        )
        base_result = self._base_gateway.query_mail_evidence(
            query_text=expanded_query,
            requester_user_id=actor.owner_user_id,
            workspace_id=actor.workspace_id,
            session_id="session_mail_human_uat",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=retrieval_candidate_limit,
            now=self.config.fixed_now,
        ).to_dict()
        with self._lock:
            upload_gateway = self._upload_gateway
            message_by_id = self._message_by_id
            uploaded_message_ids = self._uploaded_message_ids
            uploaded_bundle_ids = self._uploaded_bundle_ids
            uploaded_file_count = self._uploaded_resource_count
        gateway_results = [base_result]
        if upload_gateway is not None:
            gateway_results.extend(
                upload_gateway.query_mail_evidence(
                    query_text=expanded_query,
                    requester_user_id=actor.owner_user_id,
                    workspace_id=actor.workspace_id,
                    session_id="session_mail_human_uat",
                    mail_evidence_bundle_id=bundle_id,
                    limit=retrieval_candidate_limit,
                    now=self.config.fixed_now,
                ).to_dict()
                for bundle_id in uploaded_bundle_ids
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
                    needles=(
                        *matched_terms,
                        *_query_needles(task_frame.retrieval_query_text),
                    ),
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
                "_source_item_id": email_message_id,
            }
            (
                result["_subject_business_matches"],
                result["_snippet_business_matches"],
            ) = _business_match_counts(subject, snippet_text, filter_groups)
            results.append(result)

        if any(gateway_result["status"] == "ok" for gateway_result in gateway_results):
            results.extend(
                self._exact_subject_results(
                    query_text=task_frame.retrieval_query_text,
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
        total_result_count = len(results)
        displayed_results = results[:limit]
        for result in displayed_results:
            result.pop("_subject_business_matches", None)
            result.pop("_snippet_business_matches", None)
            result.pop("_source_item_id", None)

        generated_at = _timestamp(self.config.fixed_now)
        warnings = [
            warning for gateway_result in gateway_results for warning in gateway_result["warnings"]
        ]
        if displayed_results:
            warnings = [
                warning for warning in warnings if warning != "no_visible_mail_evidence_matched"
            ]
            if any(result["content_redacted"] for result in results):
                warnings.append("unsafe_mail_evidence_content_redacted")
        if filter_groups and evidence_snippets and not displayed_results:
            warnings.append("business_filter_no_exact_match")
        if not displayed_results and "no_visible_mail_evidence_matched" not in warnings:
            warnings.append("no_visible_mail_evidence_matched")
        has_more = total_result_count > len(displayed_results)
        answerability_status = "sufficient_evidence" if displayed_results else "target_not_found"
        response = {
            "status": (
                "ok"
                if any(gateway_result["status"] == "ok" for gateway_result in gateway_results)
                else gateway_results[0]["status"]
            ),
            "query_id": query_id,
            "query_hash": query_hash,
            "generated_at": generated_at,
            "sort": sort,
            "result_count": len(displayed_results),
            "total_result_count": total_result_count,
            "displayed_result_count": len(displayed_results),
            "results": displayed_results,
            "warnings": sorted(set(warnings)),
            "notice": "以下先呈現來源內容；主旨與時間僅作為次要脈絡。",
            "task_frame": {
                "task_frame_id": task_frame.task_frame_id,
                "revision": task_frame.revision,
                "changed_dimensions": list(changed_dimensions),
            },
            "coverage": {
                "cardinality_mode": (task_frame.evidence_requirement.cardinality_mode),
                "total_source_item_count": total_result_count,
                "returned_source_item_count": total_result_count,
                "displayed_source_item_count": len(displayed_results),
                "is_exhaustive": True,
                "has_more": has_more,
            },
            "answerability": {
                "status": answerability_status,
                "reason_codes": (
                    ["evidence_requirement_satisfied"]
                    if displayed_results
                    else ["no_matching_target"]
                ),
            },
            "projection": {
                "output_format": task_frame.projection.output_format,
                "primary_fields": list(task_frame.projection.primary_fields),
                "secondary_fields": list(task_frame.projection.secondary_fields),
                "page_size": task_frame.projection.page_size,
                "page_offset": task_frame.projection.page_offset,
            },
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
                "event_type": "query_result",
                "created_at": generated_at,
                "query_id": query_id,
                "result_count": len(displayed_results),
                "total_result_count": total_result_count,
                "has_more": has_more,
                "answerability_status": answerability_status,
                "citation_ids": [
                    item["citation"]["citation_id"]
                    for item in displayed_results
                    if item.get("citation")
                ],
                "has_uploaded_result": any(
                    item["source_kind"] == "uploaded_uat" for item in displayed_results
                ),
            }
        )
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
                    "_source_item_id": message.email_message_id,
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
        files: Sequence[UatUploadedResourcePart],
    ) -> dict[str, Any]:
        if not files or len(files) > self.config.max_upload_files:
            raise ContractValidationError("UAT upload file count is invalid")
        actor = self.config.bundle.mail_import_session
        created_at = _timestamp(self.config.fixed_now)
        parsed_by_hash = {}
        duplicate_in_request_count = 0
        for uploaded_file in files:
            parsed = parse_uat_uploaded_resource(
                uploaded_file,
                owner_user_id=actor.owner_user_id,
                workspace_id=actor.workspace_id,
                created_at=created_at,
                scratch_parent=self._upload_store.root,
            )
            if parsed.content_hash in parsed_by_hash:
                duplicate_in_request_count += 1
                continue
            parsed_by_hash[parsed.content_hash] = (parsed, uploaded_file.content)

        created_resources: list[tuple[str, str]] = []
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
                *(bundle for parsed, _ in new_items for bundle in parsed.bundles),
            ]
            prospective_gateway = (
                MailEvidenceQueryGateway(prospective_bundles) if prospective_bundles else None
            )
            warnings = sorted({warning for parsed, _ in new_items for warning in parsed.warnings})
            try:
                for parsed, content in new_items:
                    if self._upload_store.store(
                        parsed.content_hash,
                        parsed.source_format,
                        content,
                    ):
                        created_resources.append((parsed.content_hash, parsed.source_format))
                self._event_store.append(
                    {
                        "event_type": "mail_upload",
                        "created_at": created_at,
                        "accepted_file_count": len(new_items),
                        "duplicate_file_count": duplicate_count,
                        "content_hashes": [parsed.content_hash for parsed, _ in new_items],
                        "source_formats": sorted({parsed.source_format for parsed, _ in new_items}),
                        "indexed_item_count": sum(parsed.message_count for parsed, _ in new_items),
                        "warnings": warnings,
                    }
                )
            except Exception:
                for content_hash, source_format in created_resources:
                    self._upload_store.remove(content_hash, source_format)
                raise

            self._uploaded_content_hashes.update(parsed.content_hash for parsed, _ in new_items)
            self._uploaded_resource_count += len(new_items)
            self._uploaded_bundles = prospective_bundles
            for parsed, _ in new_items:
                self._uploaded_warnings.update(parsed.warnings)
            self._install_uploaded_index(
                prospective_bundles,
                gateway=prospective_gateway,
            )
            total_uploaded_file_count = self._uploaded_resource_count
            total_uploaded_message_count = len(self._uploaded_message_ids)

        uploaded_message_count = sum(parsed.message_count for parsed, _ in new_items)
        response = {
            "status": "uploaded",
            "accepted_file_count": len(new_items),
            "duplicate_file_count": duplicate_count,
            "uploaded_message_count": uploaded_message_count,
            "indexed_item_count": uploaded_message_count,
            "total_uploaded_file_count": total_uploaded_file_count,
            "total_uploaded_message_count": total_uploaded_message_count,
            "warnings": warnings,
            "notice": (
                "新資料已加入共享 UAT 索引，可立即回到聊天查詢。"
                "EML 內嵌附件內容仍不會自動建立搜尋索引。"
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
        self._uploaded_bundle_ids = tuple(
            bundle.mail_evidence_bundle_id for bundle in resolved_bundles
        )
        self._all_bundles = (self.config.bundle, *resolved_bundles)

    def record_interaction(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        _expect_exact_keys(
            payload,
            _INTERACTION_KEYS,
            required={"visitor_id", "session_id", "sequence", "action", "details"},
        )
        tracking = _validated_tracking_fields(payload, required=True)
        action = payload.get("action")
        if action not in _INTERACTION_ACTIONS:
            raise ContractValidationError("interaction action is invalid")
        details = _validated_interaction_details(str(action), payload.get("details"))
        created_at = _timestamp(self.config.fixed_now)
        self._event_store.append(
            {
                "event_type": "interaction",
                "created_at": created_at,
                "action": action,
                "details": details,
                **tracking,
            }
        )
        with self._lock:
            self._interaction_counts[str(action)] += 1
            self._remember_tracking(tracking)
            if action == "new_chat":
                self._task_frames_by_session_id.pop(tracking["session_id"], None)
        response = {
            "status": "recorded",
            "action": action,
            "created_at": created_at,
        }
        assert_public_payload_safe(response, "mail_human_uat_interaction_response")
        return response

    def record_feedback(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        _expect_exact_keys(payload, _FEEDBACK_KEYS, required={"query_id", "verdict"})
        tracking = _validated_tracking_fields(payload)
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
                **tracking,
            }
        )
        with self._lock:
            self._feedback_count += 1
            self._verdict_counts[str(verdict)] += 1
            self._remember_tracking(tracking)
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
                "interaction_count": sum(self._interaction_counts.values()),
                "interaction_counts": dict(sorted(self._interaction_counts.items())),
                "anonymous_visitor_count": len(self._anonymous_visitor_ids),
                "anonymous_session_count": len(self._anonymous_session_ids),
                "verdict_counts": {
                    verdict: self._verdict_counts.get(verdict, 0) for verdict in sorted(_VERDICTS)
                },
                "upload_supported": True,
                "uploaded_file_count": self._uploaded_resource_count,
                "uploaded_message_count": len(self._uploaded_message_ids),
                "upload_warning_counts": dict(sorted(self._uploaded_warnings.items())),
                "read_only_business_systems": True,
                "upload_required": False,
            }
        assert_public_payload_safe(response, "mail_human_uat_session_summary")
        return response

    def _remember_tracking(self, tracking: Mapping[str, Any]) -> None:
        visitor_id = tracking.get("visitor_id")
        session_id = tracking.get("session_id")
        if visitor_id:
            self._anonymous_visitor_ids.add(visitor_id)
        if session_id:
            self._anonymous_session_ids.add(session_id)


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
            if route not in {
                "/api/query",
                "/api/feedback",
                "/api/interaction",
                "/api/upload",
            }:
                self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")
                return
            if not self._same_origin_post_allowed():
                self._send_error(HTTPStatus.FORBIDDEN, "same_origin_required")
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
                elif route == "/api/feedback":
                    response = service.record_feedback(payload)
                else:
                    response = service.record_interaction(payload)
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

        def _same_origin_post_allowed(self) -> bool:
            origins = self.headers.get_all("Origin")
            hosts = self.headers.get_all("Host")
            fetch_sites = self.headers.get_all("Sec-Fetch-Site")
            if not origins or len(origins) != 1 or not hosts or len(hosts) != 1:
                return False
            if fetch_sites and (
                len(fetch_sites) != 1 or fetch_sites[0].strip().lower() != "same-origin"
            ):
                return False
            origin = urlparse(origins[0].strip())
            return (
                origin.scheme.lower() in {"http", "https"}
                and bool(origin.netloc)
                and origin.netloc.casefold() == hosts[0].strip().casefold()
                and not origin.path
                and not origin.params
                and not origin.query
                and not origin.fragment
                and not origin.username
                and not origin.password
            )

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

        def _read_upload_files(self) -> list[UatUploadedResourcePart]:
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
            return parse_uat_resource_multipart(
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
    def __init__(
        self,
        state_dir: str | Path,
        *,
        retention_days: int,
        max_bytes: int,
        fixed_now: str | None,
    ) -> None:
        self.root = Path(state_dir)
        if self.root.is_symlink():
            raise ContractValidationError("UAT state directory must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / "mail-human-uat-events.private.jsonl"
        if self.path.is_symlink():
            raise ContractValidationError("UAT event store must not be a symlink")
        self._lock = threading.Lock()
        self.retention_days = retention_days
        self.max_bytes = max_bytes
        reference_time = _event_datetime(_timestamp(fixed_now))
        with self._lock:
            self._compact_locked(reference_time=reference_time, reserve_bytes=0)
        self._last_compaction_date = reference_time.date()

    def append(self, payload: Mapping[str, Any]) -> None:
        encoded = (
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise OSError("private UAT event exceeds store limit")
        reference_time = _event_datetime(str(payload.get("created_at", "")))
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        with self._lock:
            current_size = self.path.stat().st_size if self.path.exists() else 0
            if (
                self._last_compaction_date != reference_time.date()
                or current_size + len(encoded) > self.max_bytes
            ):
                self._compact_locked(
                    reference_time=reference_time,
                    reserve_bytes=len(encoded),
                )
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
            self._last_compaction_date = reference_time.date()

    def _compact_locked(
        self,
        *,
        reference_time: datetime,
        reserve_bytes: int,
    ) -> None:
        if reserve_bytes < 0 or reserve_bytes > self.max_bytes:
            raise OSError("private UAT event reserve is invalid")
        cutoff = reference_time - timedelta(days=self.retention_days)
        source_lines = self._bounded_source_lines()
        retained: list[bytes] = []
        for line in source_lines:
            try:
                event = json.loads(line.decode("utf-8"))
                created_at = _event_datetime(str(event.get("created_at", "")))
            except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if created_at < cutoff:
                continue
            retained.append(line.rstrip(b"\r\n") + b"\n")

        available = self.max_bytes - reserve_bytes
        newest: list[bytes] = []
        total = 0
        for line in reversed(retained):
            if total + len(line) > available:
                break
            newest.append(line)
            total += len(line)
        compacted = b"".join(reversed(newest))
        self._replace_locked(compacted)

    def _bounded_source_lines(self) -> list[bytes]:
        if not self.path.exists():
            return []
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags)
        try:
            size = os.fstat(descriptor).st_size
            read_limit = self.max_bytes * 2
            truncated = size > read_limit
            if truncated:
                os.lseek(descriptor, size - read_limit, os.SEEK_SET)
            chunks: list[bytes] = []
            remaining = read_limit
            while remaining > 0:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
        finally:
            os.close(descriptor)
        lines = payload.splitlines(keepends=True)
        if truncated and lines:
            lines = lines[1:]
        return lines

    def _replace_locked(self, payload: bytes) -> None:
        temporary_path = self.root / f".mail-human-uat-events-{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary_path, flags, 0o600)
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("private UAT event compaction failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
        except Exception:
            os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)
        try:
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise


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


def _validated_tracking_fields(
    payload: Mapping[str, Any],
    *,
    required: bool = False,
) -> dict[str, Any]:
    visitor_id = payload.get("visitor_id")
    session_id = payload.get("session_id")
    sequence = payload.get("sequence")
    if visitor_id is None and session_id is None and sequence is None and not required:
        return {}
    if (
        not isinstance(visitor_id, str)
        or not _VISITOR_ID_RE.fullmatch(visitor_id)
        or not isinstance(session_id, str)
        or not _SESSION_ID_RE.fullmatch(session_id)
        or not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 1
        or sequence > _MAX_EVENT_SEQUENCE
    ):
        raise ContractValidationError("anonymous UAT tracking ids are invalid")
    return {
        "visitor_id": visitor_id,
        "session_id": session_id,
        "sequence": sequence,
    }


def _validated_interaction_details(action: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError("interaction details must be an object")
    details = dict(value)
    if action == "page_view":
        _expect_exact_keys(details, {"viewport"}, required={"viewport"})
        if details["viewport"] not in {"desktop", "mobile"}:
            raise ContractValidationError("interaction viewport is invalid")
    elif action == "sidebar_toggle":
        _expect_exact_keys(details, {"state"}, required={"state"})
        if details["state"] not in {"open", "closed"}:
            raise ContractValidationError("interaction sidebar state is invalid")
    elif action in {"new_chat", "query_error"}:
        _expect_exact_keys(details, set(), required=set())
    elif action == "shell_control":
        _expect_exact_keys(details, {"control"}, required={"control"})
        if details["control"] not in _SHELL_CONTROLS:
            raise ContractValidationError("interaction shell control is invalid")
    elif action == "upload_open":
        _expect_exact_keys(details, {"source"}, required={"source"})
        if details["source"] not in _UPLOAD_OPEN_SOURCES:
            raise ContractValidationError("interaction upload source is invalid")
    elif action == "upload_close":
        _expect_exact_keys(details, {"source"}, required={"source"})
        if details["source"] not in _UPLOAD_CLOSE_SOURCES:
            raise ContractValidationError("interaction upload close source is invalid")
    elif action == "upload_files_selected":
        _expect_exact_keys(
            details,
            {"file_count", "size_bucket"},
            required={"file_count", "size_bucket"},
        )
        _validated_interaction_count(details["file_count"], "file_count", maximum=20)
        if details["size_bucket"] not in _UPLOAD_SIZE_BUCKETS:
            raise ContractValidationError("interaction upload size bucket is invalid")
    elif action == "upload_validation_error":
        _expect_exact_keys(details, {"reason"}, required={"reason"})
        if details["reason"] not in _UPLOAD_VALIDATION_REASONS:
            raise ContractValidationError("interaction upload validation reason is invalid")
    elif action == "upload_submit":
        _expect_exact_keys(details, {"file_count"}, required={"file_count"})
        _validated_interaction_count(details["file_count"], "file_count", maximum=20)
    elif action == "upload_complete":
        _expect_exact_keys(
            details,
            {"accepted_file_count", "duplicate_file_count"},
            required={"accepted_file_count", "duplicate_file_count"},
        )
        accepted = _validated_interaction_count(
            details["accepted_file_count"],
            "accepted_file_count",
            maximum=20,
            minimum=0,
        )
        duplicate = _validated_interaction_count(
            details["duplicate_file_count"],
            "duplicate_file_count",
            maximum=20,
            minimum=0,
        )
        if accepted + duplicate > 20:
            raise ContractValidationError("interaction upload counts are invalid")
    elif action == "query_result":
        _expect_exact_keys(
            details,
            {"result_count", "has_uploaded_result"},
            required={"result_count", "has_uploaded_result"},
        )
        _validated_interaction_count(
            details["result_count"],
            "result_count",
            maximum=_MAX_RESULT_LIMIT,
            minimum=0,
        )
        if not isinstance(details["has_uploaded_result"], bool):
            raise ContractValidationError("interaction query result flag is invalid")
    else:
        raise ContractValidationError("interaction action is invalid")
    return details


def _validated_interaction_count(
    value: Any,
    field_name: str,
    *,
    maximum: int,
    minimum: int = 1,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
        raise ContractValidationError(f"interaction {field_name} is invalid")
    return value


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


def _resolve_task_frame(
    query_text: str,
    *,
    page_size: int,
    prior: TaskFrame | None,
) -> tuple[TaskFrame, tuple[str, ...]]:
    projection_format = _requested_projection_format(query_text)
    projection = ProjectionSpec(
        output_format=projection_format or "narrative",
        primary_fields=("content",),
        secondary_fields=("subject", "sent_at"),
        page_size=page_size,
    )
    if prior is None:
        return _new_task_frame(query_text, projection=projection), (
            "task",
            "evidence_requirement",
            "projection",
        )

    if projection_format is not None and not _explicit_identifiers(query_text):
        revision = revise_task_frame(
            prior,
            query_text,
            projection=projection,
        )
        return revision.task_frame, revision.changed_dimensions

    if _should_refine_task(prior, query_text):
        follow_up_anchor = TaskAnchor(
            anchor_id=f"follow_up_{prior.revision + 1}",
            anchor_type="refinement",
            value=query_text,
        )
        revision = revise_task_frame(
            prior,
            query_text,
            anchor_updates=(follow_up_anchor,),
            projection=ProjectionSpec(
                output_format=projection_format or prior.projection.output_format,
                primary_fields=("content",),
                secondary_fields=("subject", "sent_at"),
                page_size=page_size,
            ),
            retrieval_query_text=f"{prior.retrieval_query_text} {query_text}",
        )
        return revision.task_frame, revision.changed_dimensions

    return _new_task_frame(query_text, projection=projection), (
        "task",
        "evidence_requirement",
        "projection",
    )


def _new_task_frame(query_text: str, *, projection: ProjectionSpec) -> TaskFrame:
    task_frame_id = (
        "task_frame_"
        + sha256_json(
            {
                "query_text": query_text,
                "projection": projection.output_format,
                "page_size": projection.page_size,
            }
        ).removeprefix("sha256:")[:24]
    )
    return TaskFrame(
        task_frame_id=task_frame_id,
        revision=1,
        retrieval_query_text=query_text,
        latest_utterance=query_text,
        anchors=(
            TaskAnchor(
                anchor_id="initial_request",
                anchor_type="user_request",
                value=query_text,
            ),
        ),
        hard_constraints=(),
        evidence_requirement=EvidenceRequirement(
            requirement_id=f"evidence_requirement_{task_frame_id[-12:]}",
            cardinality_mode="all_matching",
        ),
        projection=projection,
    )


def _requested_projection_format(query_text: str) -> str | None:
    normalized = query_text.casefold()
    for output_format, terms in _PROJECTION_FORMAT_TERMS.items():
        if any(term in normalized for term in terms):
            return output_format
    return None


def _explicit_identifiers(query_text: str) -> frozenset[str]:
    return frozenset(
        match.group(0).casefold() for match in _EXPLICIT_IDENTIFIER_RE.finditer(query_text)
    )


def _should_refine_task(prior: TaskFrame, query_text: str) -> bool:
    current_identifiers = _explicit_identifiers(query_text)
    prior_identifiers = _explicit_identifiers(prior.retrieval_query_text)
    if current_identifiers:
        return current_identifiers.issubset(prior_identifiers)
    normalized = query_text.casefold()
    if any(marker in normalized for marker in _FOLLOW_UP_MARKERS):
        return True
    return len(query_text.strip()) <= 24


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
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    for result in results:
        source_item_id = result.get("_source_item_id")
        key = (
            ("source_item", source_item_id)
            if source_item_id
            else (
                "rendered",
                result.get("subject"),
                result.get("sent_at"),
                result.get("snippet"),
            )
        )
        current = selected.get(key)
        if current is None or (
            int(result["score"]),
            len(str(result.get("snippet", ""))),
        ) > (
            int(current["score"]),
            len(str(current.get("snippet", ""))),
        ):
            selected[key] = result
    return list(selected.values())


def _timestamp(value: str | None) -> str:
    if value is not None:
        return value
    return now_iso()


def _event_datetime(value: str) -> datetime:
    if not value:
        raise ValueError("private UAT event timestamp is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("private UAT event timestamp is invalid")
    return parsed.astimezone(timezone.utc)


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
  <title>FormOwl</title>
  <style>
    :root {
      color-scheme: light;
      --sidebar-width: 260px;
      --sidebar: #f9f9f9;
      --canvas: #ffffff;
      --soft: #f4f4f4;
      --hover: #ececec;
      --line: #e5e5e5;
      --ink: #0d0d0d;
      --muted: #676767;
      --brand: #10a37f;
      --danger: #b42318;
      --shadow: 0 8px 28px rgba(0, 0, 0, .08);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      min-height: 100vh; overflow-x: hidden; color: var(--ink); background: var(--canvas);
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI",
        "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
    }
    button, textarea { font: inherit; }
    button { color: inherit; cursor: pointer; }
    button:focus-visible {
      outline: 2px solid #595959; outline-offset: 2px;
    }
    .sidebar {
      position: fixed; inset: 0 auto 0 0; z-index: 30; width: var(--sidebar-width);
      background: var(--sidebar); padding: 8px 8px 12px; display: flex; flex-direction: column;
      transition: transform .18s ease;
    }
    .sidebar-top { display: flex; align-items: center; justify-content: space-between; height: 44px; }
    .brand-button, .sidebar-toggle, .nav-button, .history-item, .profile-card {
      border: 0; background: transparent;
    }
    .brand-button {
      display: flex; align-items: center; gap: 9px; padding: 7px 8px; border-radius: 9px;
      font-weight: 600;
    }
    .brand-button:hover, .sidebar-toggle:hover, .nav-button:hover,
    .history-item:hover, .profile-card:hover { background: var(--hover); }
    .logo {
      width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center;
      background: var(--ink); color: white; font-size: 13px; font-weight: 700;
    }
    .sidebar-toggle, .mobile-menu {
      width: 36px; height: 36px; border: 0; border-radius: 9px; background: transparent;
      display: grid; place-items: center;
    }
    .sidebar-toggle:hover, .mobile-menu:hover { background: var(--hover); }
    .nav { margin-top: 8px; display: grid; gap: 2px; }
    .nav-button {
      width: 100%; min-height: 40px; padding: 8px 10px; border-radius: 9px;
      display: flex; align-items: center; gap: 11px; text-align: left;
    }
    .nav-icon { width: 20px; height: 20px; display: grid; place-items: center; flex: none; }
    .history { min-height: 0; overflow-y: auto; margin-top: 22px; flex: 1; }
    .history-label {
      padding: 0 10px 7px; color: var(--muted); font-size: 12px; font-weight: 600;
    }
    .history-item {
      width: 100%; padding: 9px 10px; border-radius: 9px; overflow: hidden;
      text-align: left; text-overflow: ellipsis; white-space: nowrap; font-size: 14px;
    }
    .profile-card {
      width: 100%; padding: 9px 8px; border-radius: 9px; display: flex; align-items: center;
      gap: 10px; text-align: left;
    }
    .profile-avatar {
      width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
      background: #d9d9d9; font-size: 12px; font-weight: 700;
    }
    .profile-copy { min-width: 0; }
    .profile-title { font-size: 13px; font-weight: 600; }
    .profile-subtitle { color: var(--muted); font-size: 11px; margin-top: 2px; }
    .main { min-height: 100vh; margin-left: var(--sidebar-width); transition: margin-left .18s ease; }
    .topbar {
      position: fixed; top: 0; right: 0; left: var(--sidebar-width); z-index: 20;
      height: 56px; padding: 0 14px; display: flex; align-items: center;
      justify-content: space-between; background: rgba(255,255,255,.92);
      backdrop-filter: blur(12px); transition: left .18s ease;
    }
    .topbar-left, .topbar-right { display: flex; align-items: center; gap: 8px; }
    .mobile-menu { display: none; }
    .model-selector {
      border: 0; background: transparent; border-radius: 9px; padding: 8px 10px;
      font-size: 17px; font-weight: 600;
    }
    .model-selector:hover { background: var(--soft); }
    .model-selector span { color: var(--muted); font-size: 12px; margin-left: 5px; }
    .test-badge {
      display: flex; align-items: center; gap: 7px; padding: 7px 10px;
      border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 12px;
    }
    .status-dot { width: 7px; height: 7px; border-radius: 50%; background: #d9a400; }
    .test-badge.ready .status-dot { background: var(--brand); }
    .top-avatar {
      width: 32px; height: 32px; border: 0; border-radius: 50%; background: #ededed;
      display: grid; place-items: center; font-size: 12px; font-weight: 700;
    }
    .conversation {
      display: none; width: min(768px, calc(100% - 40px)); margin: 0 auto;
      padding: 88px 0 190px;
    }
    body.has-conversation .conversation { display: block; }
    .message { margin-bottom: 34px; }
    .message.assistant {
      display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 14px;
    }
    .message.user { display: flex; justify-content: flex-end; }
    .message.user .avatar { display: none; }
    .avatar {
      width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center;
      background: var(--ink); color: white; font-size: 11px; font-weight: 700;
    }
    .bubble { min-width: 0; line-height: 1.65; font-size: 15px; }
    .message.user .bubble {
      max-width: min(72%, 620px); padding: 10px 16px; border-radius: 20px;
      background: var(--soft); white-space: pre-wrap;
    }
    .assistant-title { margin-bottom: 7px; font-weight: 650; }
    .assistant-text { white-space: pre-wrap; }
    .evidence-list { display: grid; gap: 10px; margin-top: 16px; }
    .evidence {
      border: 1px solid var(--line); border-radius: 14px; padding: 14px 15px;
      background: #fff;
    }
    .evidence h3 { margin: 0; font-size: 14px; line-height: 1.5; }
    .evidence-meta { margin: 5px 0 8px; color: var(--muted); font-size: 12px; }
    .evidence-content {
      margin: 0 0 12px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere;
    }
    .evidence-table-wrap {
      width: 100%; margin-top: 16px; overflow-x: auto;
      border: 1px solid var(--line); border-radius: 14px; background: #fff;
    }
    .evidence-table {
      width: 100%; min-width: 720px; border-collapse: collapse; table-layout: fixed;
    }
    .evidence-table th, .evidence-table td {
      padding: 11px 12px; border-bottom: 1px solid var(--line);
      text-align: left; vertical-align: top; overflow-wrap: anywhere;
    }
    .evidence-table th {
      background: #f7f7f7; color: #555; font-size: 12px; font-weight: 650;
    }
    .evidence-table td { font-size: 13px; line-height: 1.55; white-space: pre-wrap; }
    .evidence-table th:first-child, .evidence-table td:first-child { width: 48%; }
    .evidence-table th:nth-child(2), .evidence-table td:nth-child(2) { width: 23%; }
    .evidence-table th:nth-child(3), .evidence-table td:nth-child(3) { width: 17%; }
    .evidence-table th:nth-child(4), .evidence-table td:nth-child(4) { width: 12%; }
    .evidence-table tbody tr:last-child td { border-bottom: 0; }
    .table-citation { color: #777; font-size: 11px; }
    .badge {
      display: inline-block; margin-left: 7px; padding: 2px 7px; border-radius: 999px;
      background: #e8f6f1; color: #08745a; font-size: 10px; font-weight: 650;
    }
    .citation { margin-top: 9px; color: #8a8a8a; font-size: 10px; overflow-wrap: anywhere; }
    .feedback-row { display: flex; align-items: center; gap: 3px; margin-top: 12px; }
    .feedback-row span { color: var(--muted); font-size: 12px; margin-right: 4px; }
    .feedback-row button {
      width: 30px; height: 30px; border: 0; border-radius: 8px; background: transparent;
    }
    .feedback-row button:hover { background: var(--soft); }
    .composer-dock {
      position: fixed; left: var(--sidebar-width); right: 0; top: 50%; z-index: 15;
      transform: translateY(-48%); padding: 0 20px; transition: left .18s ease;
    }
    .composer-panel { width: min(768px, 100%); margin: 0 auto; }
    .landing-title { text-align: center; margin-bottom: 26px; }
    .landing-logo {
      width: 42px; height: 42px; margin: 0 auto 18px; border-radius: 50%;
      display: grid; place-items: center; background: var(--ink); color: white;
      font-size: 16px; font-weight: 700;
    }
    .landing-title h1 { margin: 0; font-size: 28px; font-weight: 600; letter-spacing: -.02em; }
    .prompt-box {
      border: 1px solid #d7d7d7; border-radius: 26px; background: white;
      box-shadow: var(--shadow); padding: 10px 12px 9px;
    }
    .prompt-box:focus-within {
      border-color: #9b9b9b; box-shadow: 0 0 0 2px rgba(13, 13, 13, .08), var(--shadow);
    }
    .prompt-box textarea {
      width: 100%; min-height: 48px; max-height: 180px; padding: 8px 8px 4px;
      border: 0; outline: 0; resize: none; color: var(--ink); line-height: 1.45;
      background: transparent; font-size: 16px;
    }
    .prompt-toolbar { display: flex; align-items: center; justify-content: space-between; }
    .prompt-left, .prompt-right { display: flex; align-items: center; gap: 6px; }
    .round-action {
      width: 34px; height: 34px; border: 0; border-radius: 50%; display: grid;
      place-items: center; background: transparent;
    }
    .round-action:hover { background: var(--soft); }
    .tool-label {
      border: 0; border-radius: 999px; background: transparent; padding: 7px 9px;
      color: var(--muted); font-size: 13px;
    }
    .tool-label:hover { background: var(--soft); }
    .send {
      width: 34px; height: 34px; border: 0; border-radius: 50%; display: grid;
      place-items: center; background: var(--ink); color: white;
    }
    .send:disabled { opacity: .35; cursor: default; }
    .composer-note {
      margin-top: 10px; color: var(--muted); text-align: center; font-size: 11px;
    }
    body.has-conversation .composer-dock {
      top: auto; bottom: 0; transform: none; padding: 18px 20px 12px;
      background: linear-gradient(transparent, rgba(255,255,255,.96) 24%, #fff 54%);
    }
    body.has-conversation .landing-title { display: none; }
    body.has-conversation .prompt-box { box-shadow: 0 2px 14px rgba(0,0,0,.08); }
    .modal {
      position: fixed; inset: 0; z-index: 50; display: grid; place-items: center;
      padding: 22px; background: rgba(0,0,0,.5); backdrop-filter: blur(3px);
    }
    .modal.hidden { display: none; }
    .modal-card {
      width: min(720px, 100%); height: min(650px, calc(100vh - 44px));
      overflow: hidden; display: grid; grid-template-rows: 54px 1fr;
      border-radius: 18px; background: white; box-shadow: 0 24px 80px rgba(0,0,0,.3);
    }
    .modal-head {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 17px; border-bottom: 1px solid var(--line);
    }
    .modal-head strong { font-size: 14px; }
    .close {
      width: 34px; height: 34px; border: 0; border-radius: 9px;
      background: transparent; font-size: 20px;
    }
    .close:hover { background: var(--soft); }
    iframe { width: 100%; height: 100%; border: 0; background: #f7f7f7; }
    .error-text { color: var(--danger); }
    .shell-toast {
      position: fixed; top: 68px; left: calc((100% + var(--sidebar-width)) / 2);
      z-index: 45; max-width: min(420px, calc(100% - 32px)); padding: 10px 14px;
      border: 1px solid var(--line); border-radius: 12px; background: #fff;
      box-shadow: var(--shadow); color: #444; font-size: 13px; text-align: center;
      opacity: 0; pointer-events: none; transform: translate(-50%, -8px);
      transition: opacity .16s ease, transform .16s ease;
    }
    .shell-toast.visible { opacity: 1; transform: translate(-50%, 0); }
    .sidebar-overlay { display: none; }
    body.sidebar-collapsed .sidebar { transform: translateX(-100%); }
    body.sidebar-collapsed .main { margin-left: 0; }
    body.sidebar-collapsed .topbar,
    body.sidebar-collapsed .composer-dock { left: 0; }
    body.sidebar-collapsed .shell-toast { left: 50%; }
    body.sidebar-collapsed .mobile-menu { display: grid; }
    @media (max-width: 800px) {
      .sidebar { transform: translateX(-100%); box-shadow: 8px 0 30px rgba(0,0,0,.12); }
      .main { margin-left: 0; }
      .topbar, .composer-dock { left: 0; }
      .shell-toast { left: 50%; }
      .mobile-menu { display: grid; }
      body.mobile-sidebar-open .sidebar { transform: translateX(0); }
      body.mobile-sidebar-open .sidebar-overlay {
        position: fixed; inset: 0; z-index: 25; display: block; border: 0;
        background: rgba(0,0,0,.22);
      }
      .composer-dock { padding: 0 12px; }
      .conversation { width: min(100% - 26px, 768px); padding-top: 76px; }
      .landing-title h1 { font-size: 24px; }
      .message.user .bubble { max-width: 86%; }
      .test-badge { display: none; }
    }
  </style>
</head>
<body>
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-top">
      <button class="brand-button" id="brand-home" type="button" aria-label="FormOwl 首頁">
        <span class="logo">F</span><span>FormOwl</span>
      </button>
      <button class="sidebar-toggle" id="sidebar-toggle" type="button" aria-label="收合側邊欄">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="4" width="17" height="16" rx="3" stroke="currentColor" stroke-width="1.7"/>
          <path d="M9 4v16" stroke="currentColor" stroke-width="1.7"/>
        </svg>
      </button>
    </div>
    <nav class="nav" aria-label="主要功能">
      <button class="nav-button" id="new-chat" type="button">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 20H5a1 1 0 0 1-1-1v-7a8 8 0 0 1 8-8h7a1 1 0 0 1 1 1v7a8 8 0 0 1-8 8Z" stroke="currentColor" stroke-width="1.7"/>
            <path d="M12 8v6M9 11h6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
          </svg>
        </span>
        <span>新對話</span>
      </button>
      <button class="nav-button" id="search-conversations" type="button" aria-label="搜尋對話">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="11" cy="11" r="6" stroke="currentColor" stroke-width="1.7"/>
            <path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
          </svg>
        </span>
        <span>搜尋對話</span>
      </button>
    </nav>
    <div class="history">
      <div class="history-label">今天</div>
      <button class="history-item" id="current-chat-title" type="button">新對話</button>
    </div>
    <button class="profile-card" id="profile-card" type="button">
      <span class="profile-avatar">U</span>
      <span class="profile-copy">
        <span class="profile-title">功能測試</span>
        <span class="profile-subtitle" id="upload-count">讀取郵件中…</span>
      </span>
    </button>
  </aside>
  <button class="sidebar-overlay" id="sidebar-overlay" type="button" aria-label="關閉側邊欄"></button>

  <main class="main">
    <header class="topbar">
      <div class="topbar-left">
        <button class="mobile-menu" id="mobile-menu" type="button" aria-label="開啟側邊欄">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="3.5" y="4" width="17" height="16" rx="3" stroke="currentColor" stroke-width="1.7"/>
            <path d="M9 4v16" stroke="currentColor" stroke-width="1.7"/>
          </svg>
        </button>
        <button class="model-selector" id="model-selector" type="button">FormOwl <span>▾</span></button>
      </div>
      <div class="topbar-right">
        <div class="test-badge" id="server-status">
          <span class="status-dot"></span><span class="status-copy" id="status-copy">連線中</span>
        </div>
        <button class="top-avatar" id="top-avatar" type="button" aria-label="測試使用者">U</button>
      </div>
    </header>

    <section class="conversation" id="conversation" aria-live="polite"></section>

    <div class="composer-dock">
      <div class="composer-panel">
        <div class="landing-title" id="landing-title">
          <div class="landing-logo">F</div>
          <h1>有什麼可以幫忙的？</h1>
        </div>
        <div class="prompt-box">
          <textarea id="chat-input" rows="1" placeholder="詢問郵件或上傳資料"></textarea>
          <div class="prompt-toolbar">
            <div class="prompt-left">
              <button class="round-action" id="open-upload" type="button" title="上傳資料" aria-label="上傳資料">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                </svg>
              </button>
              <button class="tool-label" id="tools-control" type="button">工具</button>
            </div>
            <div class="prompt-right">
              <button class="send" id="send" type="button" title="送出" aria-label="送出">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M12 19V5M6 11l6-6 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
        <div class="composer-note">測試期間會記錄已送出的問題與按鈕操作以改善體驗；不記錄輸入中的文字，紀錄最多保留 30 天。</div>
      </div>
    </div>
  </main>

  <div class="modal hidden" id="upload-modal" role="dialog" aria-modal="true" aria-label="上傳資料">
    <div class="modal-card">
      <div class="modal-head">
        <strong>加入資料</strong>
        <button class="close" id="close-upload" type="button" aria-label="關閉">×</button>
      </div>
      <iframe id="upload-frame" src="/upload" title="FormOwl 資料上傳"></iframe>
    </div>
  </div>
  <div class="shell-toast" id="shell-toast" role="status" aria-live="polite"></div>

  <script>
    const byId = (id) => document.getElementById(id);
    const conversation = byId("conversation");
    const body = document.body;
    let busy = false;
    let conversationStarted = false;
    let toastTimer = null;

    function randomTrackingId(prefix) {
      const bytes = new Uint8Array(16);
      if (window.crypto && window.crypto.getRandomValues) {
        window.crypto.getRandomValues(bytes);
      } else {
        for (let index = 0; index < bytes.length; index += 1) {
          bytes[index] = Math.floor(Math.random() * 256);
        }
      }
      return prefix + Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    }

    function storedTrackingId(storage, key, prefix, maxAgeMs = null) {
      try {
        const existing = storage.getItem(key);
        const createdAt = Number(storage.getItem(`${key}_created_at`) || "0");
        const isFresh = maxAgeMs === null
          || (Number.isFinite(createdAt) && createdAt > 0 && Date.now() - createdAt <= maxAgeMs);
        if (
          existing
          && existing.startsWith(prefix)
          && existing.length === prefix.length + 32
          && /^[0-9a-f]{32}$/.test(existing.slice(prefix.length))
          && isFresh
        ) return existing;
        const created = randomTrackingId(prefix);
        storage.setItem(key, created);
        storage.setItem(`${key}_created_at`, String(Date.now()));
        return created;
      } catch (_) {
        return randomTrackingId(prefix);
      }
    }

    const visitorId = storedTrackingId(
      window.localStorage,
      "formowl_uat_visitor_id",
      "uatvisitor_",
      30 * 24 * 60 * 60 * 1000
    );
    const sessionId = storedTrackingId(
      window.sessionStorage,
      "formowl_uat_session_id",
      "uatsession_"
    );

    function nextEventSequence() {
      const key = "formowl_uat_event_sequence";
      try {
        const current = Number(window.sessionStorage.getItem(key) || "0");
        const next = Number.isSafeInteger(current) && current >= 0 ? current + 1 : 1;
        window.sessionStorage.setItem(key, String(next));
        return next;
      } catch (_) {
        return Date.now();
      }
    }

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

    function track(action, details = {}) {
      return fetch("/api/interaction", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          visitor_id: visitorId,
          session_id: sessionId,
          sequence: nextEventSequence(),
          action,
          details
        })
      }).catch(() => {});
    }

    function scrollToLatest() {
      window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    }

    function showShellToast(message) {
      const toast = byId("shell-toast");
      toast.textContent = message;
      toast.classList.add("visible");
      if (toastTimer) window.clearTimeout(toastTimer);
      toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 2200);
    }

    function activateConversation(query) {
      if (!conversationStarted) {
        conversationStarted = true;
        body.classList.add("has-conversation");
        const title = query.length > 28 ? query.slice(0, 28) + "…" : query;
        byId("current-chat-title").textContent = title || "新對話";
      }
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

    function openUpload(source) {
      byId("upload-modal").classList.remove("hidden");
      byId("upload-frame").focus();
      track("upload_open", { source });
    }

    function closeUpload(source) {
      if (byId("upload-modal").classList.contains("hidden")) return;
      byId("upload-modal").classList.add("hidden");
      track("upload_close", { source });
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
      for (const [text, verdict, title] of [
        ["↑", "correct", "有幫助"],
        ["◐", "partially_correct", "部分有幫助"],
        ["↓", "incorrect", "沒有幫助"]
      ]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = text;
        button.title = title;
        button.setAttribute("aria-label", title);
        button.addEventListener("click", async () => {
          try {
            await api("/api/feedback", {
              method: "POST",
              body: JSON.stringify({
                query_id: queryId,
                verdict,
                note: "",
                visitor_id: visitorId,
                session_id: sessionId,
                sequence: nextEventSequence()
              })
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
      const totalCount = Number.isInteger(payload.total_result_count)
        ? payload.total_result_count
        : payload.results.length;
      const displayedCount = Number.isInteger(payload.displayed_result_count)
        ? payload.displayed_result_count
        : payload.results.length;
      const title = document.createElement("div");
      title.className = "assistant-title";
      title.textContent = payload.results.length
        ? `共找到 ${totalCount} 筆相關來源內容，目前顯示 ${displayedCount} 筆。`
        : "目前沒有找到符合的來源內容。";
      holder.appendChild(title);

      const explanation = document.createElement("div");
      explanation.className = "assistant-text";
      explanation.textContent = payload.results.length
        ? payload.notice
        : "你可以改用更明確的名稱、編號、日期或內容關鍵字，或先加入新的測試資料。";
      holder.appendChild(explanation);

      if (!payload.results.length) {
        const actions = document.createElement("div");
        actions.className = "feedback-row";
        const upload = document.createElement("button");
        upload.type = "button";
        upload.title = "加入新資料";
        upload.textContent = "＋";
        upload.addEventListener("click", () => openUpload("no_result"));
        actions.appendChild(upload);
        holder.appendChild(actions);
      } else if (payload.projection && payload.projection.output_format === "table") {
        const tableWrap = document.createElement("div");
        tableWrap.className = "evidence-table-wrap";
        const table = document.createElement("table");
        table.className = "evidence-table";
        const head = document.createElement("thead");
        const headRow = document.createElement("tr");
        for (const label of ["內容", "主旨", "時間", "證據"]) {
          const cell = document.createElement("th");
          cell.textContent = label;
          headRow.appendChild(cell);
        }
        head.appendChild(headRow);
        const body = document.createElement("tbody");
        for (const item of payload.results) {
          const row = document.createElement("tr");
          const content = document.createElement("td");
          content.textContent = item.snippet;
          const subject = document.createElement("td");
          subject.textContent = item.subject;
          if (item.source_kind === "uploaded_uat") {
            const badge = document.createElement("span");
            badge.className = "badge";
            badge.textContent = "測試上傳";
            subject.appendChild(badge);
          }
          const time = document.createElement("td");
          time.textContent = item.sent_at || "未提供";
          const citation = document.createElement("td");
          citation.className = "table-citation";
          citation.textContent = item.citation ? item.citation.citation_id : "—";
          row.append(content, subject, time, citation);
          body.appendChild(row);
        }
        table.append(head, body);
        tableWrap.appendChild(table);
        holder.appendChild(tableWrap);
      } else {
        const list = document.createElement("div");
        list.className = "evidence-list";
        for (const item of payload.results) {
          const card = document.createElement("article");
          card.className = "evidence";
          const snippet = document.createElement("p");
          snippet.className = "evidence-content";
          snippet.textContent = item.snippet;
          const subject = document.createElement("h3");
          subject.textContent = item.subject;
          if (item.source_kind === "uploaded_uat") {
            const badge = document.createElement("span");
            badge.className = "badge";
            badge.textContent = "測試上傳";
            subject.appendChild(badge);
          }
          const meta = document.createElement("div");
          meta.className = "evidence-meta";
          meta.textContent = item.sent_at ? `郵件時間：${item.sent_at}` : "郵件時間：未提供";
          card.append(snippet, subject, meta);
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

    async function ask(queryText, source = "composer") {
      const query = queryText.trim();
      if (!query || busy) return;
      busy = true;
      activateConversation(query);
      byId("send").disabled = true;
      byId("chat-input").value = "";
      appendTextMessage("user", query);
      const { bubble } = createMessage("assistant");
      const loading = document.createElement("div");
      loading.className = "assistant-text";
      loading.textContent = "正在查詢資料內容…";
      bubble.appendChild(loading);
      scrollToLatest();
      try {
        const payload = await api("/api/query", {
          method: "POST",
          body: JSON.stringify({
            query_text: query,
            sort: querySort(query),
            limit: 50,
            visitor_id: visitorId,
            session_id: sessionId,
            sequence: nextEventSequence(),
            source
          })
        });
        renderAssistantResult(payload, bubble);
        track("query_result", {
          result_count: payload.result_count,
          has_uploaded_result: payload.results.some(
            (item) => item.source_kind === "uploaded_uat"
          )
        });
      } catch (_) {
        bubble.replaceChildren();
        const error = document.createElement("div");
        error.className = "error-text";
        error.textContent = "查詢暫時失敗，請稍後再試。";
        bubble.appendChild(error);
        track("query_error", {});
      } finally {
        busy = false;
        byId("send").disabled = false;
        byId("chat-input").focus();
      }
    }

    function toggleSidebar() {
      let state;
      if (window.innerWidth <= 800) {
        body.classList.toggle("mobile-sidebar-open");
        state = body.classList.contains("mobile-sidebar-open") ? "open" : "closed";
      } else {
        body.classList.toggle("sidebar-collapsed");
        state = body.classList.contains("sidebar-collapsed") ? "closed" : "open";
      }
      track("sidebar_toggle", { state });
    }

    function closeMobileSidebar() {
      body.classList.remove("mobile-sidebar-open");
    }

    function startNewChat() {
      conversation.replaceChildren();
      conversationStarted = false;
      body.classList.remove("has-conversation");
      closeMobileSidebar();
      byId("current-chat-title").textContent = "新對話";
      byId("chat-input").focus();
      track("new_chat", {});
    }

    function trackShellControl(control, message, resetConversation = false) {
      track("shell_control", { control });
      if (resetConversation) {
        conversation.replaceChildren();
        conversationStarted = false;
        body.classList.remove("has-conversation");
        byId("current-chat-title").textContent = "新對話";
        byId("chat-input").focus();
      }
      closeMobileSidebar();
      showShellToast(message);
    }

    async function refreshSummary() {
      try {
        const summary = await api("/api/session-summary", { method: "GET" });
        byId("upload-count").textContent = `${summary.uploaded_file_count} 個測試檔案`;
      } catch (_) {
        byId("upload-count").textContent = "資料狀態無法讀取";
      }
    }

    byId("send").addEventListener("click", () => ask(byId("chat-input").value, "composer"));
    byId("chat-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        ask(event.currentTarget.value, "composer");
      }
    });
    byId("open-upload").addEventListener("click", () => openUpload("composer"));
    byId("close-upload").addEventListener("click", () => closeUpload("button"));
    byId("upload-modal").addEventListener("click", (event) => {
      if (event.target === byId("upload-modal")) closeUpload("backdrop");
    });
    byId("new-chat").addEventListener("click", startNewChat);
    byId("brand-home").addEventListener("click", () => {
      trackShellControl("brand_home", "已回到新對話。", true);
    });
    byId("search-conversations").addEventListener("click", () => {
      trackShellControl("search_conversations", "測試版目前只保留這個瀏覽器頁面的對話。");
    });
    byId("current-chat-title").addEventListener("click", () => {
      trackShellControl("current_history", "你正在查看目前的對話。");
    });
    byId("model-selector").addEventListener("click", () => {
      trackShellControl("model_selector", "目前固定使用 FormOwl 郵件測試模型。");
    });
    byId("tools-control").addEventListener("click", () => {
      trackShellControl("tools_menu", "目前可用工具是資料上傳與證據查詢。");
    });
    byId("profile-card").addEventListener("click", () => {
      trackShellControl("profile_card", "這個共享測試版目前沒有個人帳號設定。");
    });
    byId("top-avatar").addEventListener("click", () => {
      trackShellControl("profile_avatar", "這個共享測試版目前沒有個人帳號設定。");
    });
    byId("sidebar-toggle").addEventListener("click", toggleSidebar);
    byId("mobile-menu").addEventListener("click", toggleSidebar);
    byId("sidebar-overlay").addEventListener("click", toggleSidebar);
    window.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!byId("upload-modal").classList.contains("hidden")) {
        closeUpload("button");
      } else if (body.classList.contains("mobile-sidebar-open")) {
        toggleSidebar();
      }
    });
    window.addEventListener("message", (event) => {
      if (
        event.origin !== window.location.origin
        || event.source !== byId("upload-frame").contentWindow
        || !event.data
      ) return;
      if (event.data.type === "formowl-upload-complete") {
        byId("upload-modal").classList.add("hidden");
        const accepted = Number(event.data.accepted_file_count || 0);
        const duplicate = Number(event.data.duplicate_file_count || 0);
        const indexed = Number(event.data.indexed_item_count || 0);
        track("upload_complete", {
          accepted_file_count: accepted,
          duplicate_file_count: duplicate
        });
        activateConversation("已加入新的資料");
        appendTextMessage(
          "assistant",
          accepted
            ? `已加入 ${accepted} 個檔案，建立 ${indexed} 個可搜尋項目。現在可以直接提問。`
            : "這些資料先前已加入，現在可以直接查詢。"
        );
        refreshSummary();
      } else if (event.data.type === "formowl-upload-close") {
        closeUpload("iframe_cancel");
      }
    });

    fetch("/api/health", { cache: "no-store" })
      .then((response) => response.json())
      .then((payload) => {
        const status = byId("server-status");
        byId("status-copy").textContent =
          payload.status === "ready" ? "FormOwl 測試版" : "服務準備中";
        status.classList.toggle("ready", payload.status === "ready");
      })
      .catch(() => {
        byId("status-copy").textContent = "服務未連線";
      });
    track("page_view", { viewport: window.innerWidth <= 800 ? "mobile" : "desktop" });
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
  <title>加入資料</title>
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
    input[type=file] {
      position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
      overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
    }
    .choose {
      display: inline-block; margin-top: 15px; border: 1px solid var(--line);
      background: white; color: var(--brand-dark); border-radius: 11px; padding: 9px 13px;
      cursor: pointer; font-weight: 800;
    }
    input[type=file]:focus-visible + .choose {
      outline: 2px solid var(--brand-dark); outline-offset: 3px;
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
    <h1>加入新的測試資料</h1>
    <p class="lead">加入郵件、郵件封存檔或相關參考資料，完成後即可回到聊天直接提問。</p>
    <section class="drop" id="drop">
      <div class="drop-icon">＋</div>
      <strong>將檔案拖到這裡</strong>
      <span>或從電腦選擇一個或多個檔案</span>
      <input id="mail-files" type="file" accept=".eml,.pst,.pdf,.txt,message/rfc822,application/pdf,text/plain,application/vnd.ms-outlook" multiple>
      <label class="choose" for="mail-files">選擇檔案</label>
    </section>
    <section class="files" id="files"></section>
    <div class="limits">目前可處理 EML、PST、PDF、TXT。每次最多 20 個檔案；PST 單檔最多 500 MB，其他格式單檔最多 25 MB，合計最多 500 MB。文字型 PDF 會擷取文字；掃描型 PDF 暫不做 OCR。EML 內嵌附件內容不會自動建立搜尋索引，但可將 PDF、TXT 附件另行上傳。</div>
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
    const supportedExtensions = new Set([".eml", ".pst", ".pdf", ".txt"]);
    const maxStandardFileBytes = 25 * 1024 * 1024;
    const maxPstFileBytes = 500 * 1024 * 1024;
    const maxTotalBytes = 500 * 1024 * 1024;
    let selectedFiles = [];

    function randomTrackingId(prefix) {
      const bytes = new Uint8Array(16);
      if (window.crypto && window.crypto.getRandomValues) {
        window.crypto.getRandomValues(bytes);
      } else {
        for (let index = 0; index < bytes.length; index += 1) {
          bytes[index] = Math.floor(Math.random() * 256);
        }
      }
      return prefix + Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    }

    function storedTrackingId(storage, key, prefix, maxAgeMs = null) {
      try {
        const existing = storage.getItem(key);
        const createdAt = Number(storage.getItem(`${key}_created_at`) || "0");
        const isFresh = maxAgeMs === null
          || (Number.isFinite(createdAt) && createdAt > 0 && Date.now() - createdAt <= maxAgeMs);
        if (
          existing
          && existing.startsWith(prefix)
          && existing.length === prefix.length + 32
          && /^[0-9a-f]{32}$/.test(existing.slice(prefix.length))
          && isFresh
        ) return existing;
        const created = randomTrackingId(prefix);
        storage.setItem(key, created);
        storage.setItem(`${key}_created_at`, String(Date.now()));
        return created;
      } catch (_) {
        return randomTrackingId(prefix);
      }
    }

    const visitorId = storedTrackingId(
      window.localStorage,
      "formowl_uat_visitor_id",
      "uatvisitor_",
      30 * 24 * 60 * 60 * 1000
    );
    const sessionId = storedTrackingId(
      window.sessionStorage,
      "formowl_uat_session_id",
      "uatsession_"
    );

    function nextEventSequence() {
      const key = "formowl_uat_event_sequence";
      try {
        const current = Number(window.sessionStorage.getItem(key) || "0");
        const next = Number.isSafeInteger(current) && current >= 0 ? current + 1 : 1;
        window.sessionStorage.setItem(key, String(next));
        return next;
      } catch (_) {
        return Date.now();
      }
    }

    function track(action, details = {}) {
      return fetch("/api/interaction", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          visitor_id: visitorId,
          session_id: sessionId,
          sequence: nextEventSequence(),
          action,
          details
        })
      }).catch(() => {});
    }

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
      setMessage(selectedFiles.length ? `已選擇 ${selectedFiles.length} 個檔案。` : "");
    }

    function extensionOf(filename) {
      const lowered = filename.toLowerCase();
      const dot = lowered.lastIndexOf(".");
      return dot >= 0 ? lowered.slice(dot) : "";
    }

    function selectFiles(files) {
      selectedFiles = Array.from(files || []);
      if (selectedFiles.length > 20) {
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage("一次最多選擇 20 個檔案。", true);
        track("upload_validation_error", { reason: "file_count" });
        return;
      }
      if (selectedFiles.some((file) => !supportedExtensions.has(extensionOf(file.name)))) {
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage("目前可處理 EML、PST、PDF、TXT。", true);
        track("upload_validation_error", { reason: "file_type" });
        return;
      }
      if (selectedFiles.some((file) => {
        const limit = extensionOf(file.name) === ".pst"
          ? maxPstFileBytes
          : maxStandardFileBytes;
        return file.size > limit;
      })) {
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage("PST 單檔不可超過 500 MB，其他格式單檔不可超過 25 MB。", true);
        track("upload_validation_error", { reason: "file_size" });
        return;
      }
      const totalBytes = selectedFiles.reduce((total, file) => total + file.size, 0);
      if (totalBytes > maxTotalBytes) {
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage("這次選擇的檔案合計不可超過 500 MB。", true);
        track("upload_validation_error", { reason: "total_size" });
        return;
      }
      renderFiles();
      if (selectedFiles.length) {
        const sizeBucket = totalBytes < 5 * 1024 * 1024
          ? "under_5mb"
          : (
            totalBytes <= 25 * 1024 * 1024
              ? "5_to_25mb"
              : (totalBytes <= 60 * 1024 * 1024 ? "25_to_60mb" : "60_to_500mb")
          );
        track("upload_files_selected", {
          file_count: selectedFiles.length,
          size_bucket: sizeBucket
        });
      }
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
        setMessage("請先選擇檔案。", true);
        return;
      }
      const form = new FormData();
      for (const file of selectedFiles) form.append("mail_files", file, file.name);
      uploadButton.disabled = true;
      setMessage(`正在解析 ${selectedFiles.length} 個檔案…`);
      track("upload_submit", { file_count: selectedFiles.length });
      try {
        const response = await fetch("/api/upload", {
          method: "POST",
          cache: "no-store",
          body: form
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error_code || "request_failed");
        selectedFiles = [];
        input.value = "";
        renderFiles();
        setMessage(
          `完成：新增 ${payload.accepted_file_count} 個檔案，建立 ${payload.indexed_item_count} 個可搜尋項目。`
        );
        window.parent.postMessage(
          {
            type: "formowl-upload-complete",
            accepted_file_count: payload.accepted_file_count,
            duplicate_file_count: payload.duplicate_file_count,
            indexed_item_count: payload.indexed_item_count
          },
          window.location.origin
        );
      } catch (_) {
        setMessage("上傳失敗；請確認檔案格式有效、含可擷取內容，且大小未超過限制。", true);
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
