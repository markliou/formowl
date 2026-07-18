from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
from typing import Any, Mapping
from urllib.parse import urlparse

from formowl_contract import ContractValidationError, now_iso, sha256_json

from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle
from .query import MailEvidenceQueryGateway, _redact_mail_public_text

_ACCESS_CODE_HEADER = "X-FormOwl-UAT-Code"
_MAX_REQUEST_BYTES = 32 * 1024
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
    access_code: str
    state_dir: str | Path
    fixed_now: str | None = None
    max_request_bytes: int = _MAX_REQUEST_BYTES


class MailHumanUatService:
    """Read-only human UAT facade over the governed mail evidence query gateway."""

    def __init__(self, config: MailHumanUatHttpConfig) -> None:
        if not isinstance(config.access_code, str) or len(config.access_code) < 12:
            raise ContractValidationError("UAT access code must be at least 12 characters")
        if (
            not isinstance(config.max_request_bytes, int)
            or isinstance(config.max_request_bytes, bool)
            or config.max_request_bytes <= 0
        ):
            raise ContractValidationError("UAT max request bytes must be positive")
        if not config.bundle.messages or not config.bundle.body_segments:
            raise ContractValidationError("UAT mail evidence bundle must contain messages")
        safe_public_string(config.bundle.mail_evidence_bundle_id, "mail_evidence_bundle_id")
        config.bundle.mail_import_session.to_dict()
        self.config = config
        self._gateway = MailEvidenceQueryGateway([config.bundle])
        self._message_by_id = {
            message.email_message_id: message for message in config.bundle.messages
        }
        self._segments_by_message_id: dict[str, list[Any]] = {}
        for segment in config.bundle.body_segments:
            self._segments_by_message_id.setdefault(segment.email_message_id, []).append(segment)
        self._event_store = _PrivateUatEventStore(config.state_dir)
        self._known_query_ids: set[str] = set()
        self._verdict_counts: Counter[str] = Counter()
        self._query_count = 0
        self._feedback_count = 0
        self._lock = threading.Lock()
        self.started_at = _timestamp(config.fixed_now)

    def access_allowed(self, supplied_code: str | None) -> bool:
        if not isinstance(supplied_code, str):
            return False
        return hmac.compare_digest(supplied_code, self.config.access_code)

    def health(self) -> dict[str, Any]:
        payload = {
            "status": "ready",
            "surface": "mail_human_uat",
            "chatgpt_bypassed": True,
            "upload_required": False,
            "read_only": True,
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
        gateway_result = self._gateway.query_mail_evidence(
            query_text=expanded_query,
            requester_user_id=actor.owner_user_id,
            workspace_id=actor.workspace_id,
            session_id="session_mail_human_uat",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=_RETRIEVAL_CANDIDATE_LIMIT,
            now=self.config.fixed_now,
        ).to_dict()

        citations_by_observation = {
            citation["source_observation_id"]: citation for citation in gateway_result["citations"]
        }
        results: list[dict[str, Any]] = []
        for snippet in gateway_result["evidence_snippets"]:
            rendered = " ".join(
                value
                for value in (snippet.get("subject"), snippet.get("snippet"))
                if isinstance(value, str)
            )
            if not _matches_filter_groups(rendered, filter_groups):
                continue
            message = self._message_by_id.get(str(snippet.get("email_message_id", "")))
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
            }
            (
                result["_subject_business_matches"],
                result["_snippet_business_matches"],
            ) = _business_match_counts(subject, snippet_text, filter_groups)
            results.append(result)

        if gateway_result["status"] == "ok":
            results.extend(
                self._exact_subject_results(
                    query_text=query_text,
                    filter_groups=filter_groups,
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
        warnings = list(gateway_result["warnings"])
        if results:
            warnings = [
                warning for warning in warnings if warning != "no_visible_mail_evidence_matched"
            ]
            if any(result["content_redacted"] for result in results):
                warnings.append("unsafe_mail_evidence_content_redacted")
        if filter_groups and gateway_result["evidence_snippets"] and not results:
            warnings.append("business_filter_no_exact_match")
        if not results and "no_visible_mail_evidence_matched" not in warnings:
            warnings.append("no_visible_mail_evidence_matched")
        response = {
            "status": gateway_result["status"],
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
    ) -> list[dict[str, Any]]:
        lowered_query = query_text.casefold()
        exact_terms = [term for term in _EXACT_BUSINESS_FILTERS if term.casefold() in lowered_query]
        if not exact_terms:
            return []
        bundle = self.config.bundle
        results: list[dict[str, Any]] = []
        filter_needles = tuple(term for group in filter_groups for term in group)
        matching_messages = [
            message
            for message in bundle.messages
            if all(term.casefold() in (message.subject or "").casefold() for term in exact_terms)
        ]
        matching_messages.sort(
            key=lambda message: _timestamp_sort_key(message.sent_at),
            reverse=True,
        )
        for message in matching_messages:
            subject = message.subject or ""
            for segment in self._segments_by_message_id.get(message.email_message_id, []):
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
                "read_only": True,
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
                self._send_html(HTTPStatus.OK, render_mail_human_uat_page())
                return
            if route == "/api/health":
                self._send_json(HTTPStatus.OK, service.health())
                return
            if route == "/api/session-summary":
                if not self._authorized():
                    return
                self._send_json(HTTPStatus.OK, service.session_summary())
                return
            if route == "/favicon.ico":
                self._send_empty(HTTPStatus.NO_CONTENT)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")

        def do_POST(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route not in {"/api/query", "/api/feedback"}:
                self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")
                return
            if not self._authorized():
                return
            try:
                payload = self._read_json_body()
                if route == "/api/query":
                    response = service.query(payload)
                else:
                    response = service.record_feedback(payload)
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

        def _authorized(self) -> bool:
            if service.access_allowed(self.headers.get(_ACCESS_CODE_HEADER)):
                return True
            self._send_error(
                HTTPStatus.UNAUTHORIZED,
                "access_denied",
                extra_headers={"WWW-Authenticate": 'FormOwlUAT realm="mail"'},
            )
            return False

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

        def _send_html(self, status: HTTPStatus, html: str) -> None:
            encoded = html.encode("utf-8")
            self.send_response(status)
            self._send_security_headers(content_type="text/html; charset=utf-8")
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
            self._send_security_headers(content_type="application/json; charset=utf-8")
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_empty(self, status: HTTPStatus) -> None:
            self.send_response(status)
            self._send_security_headers(content_type="text/plain; charset=utf-8")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_security_headers(self, *, content_type: str) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; "
                "style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; "
                "connect-src 'self'; "
                "img-src 'self' data:; "
                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            )

    return MailHumanUatHttpHandler


def create_mail_human_uat_http_server(
    host: str,
    port: int,
    service: MailHumanUatService,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), build_mail_human_uat_http_handler(service))


def render_mail_human_uat_page() -> str:
    return _UAT_HTML


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


_UAT_HTML = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FormOwl 郵件證據 UAT</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17312b;
      --muted: #66756f;
      --paper: #fffdf7;
      --panel: #ffffff;
      --line: #d8e0dc;
      --brand: #136f63;
      --brand-dark: #0c4e46;
      --accent: #f3b61f;
      --danger: #9b2c2c;
      --shadow: 0 16px 40px rgba(27, 60, 52, 0.10);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% 5%, rgba(243, 182, 31, .16), transparent 30%),
        linear-gradient(145deg, #f7fbf7 0%, var(--paper) 55%, #eef6f3 100%);
      font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
    }
    .shell { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 34px 0 70px; }
    header {
      display: flex; justify-content: space-between; gap: 24px; align-items: flex-start;
      margin-bottom: 22px;
    }
    .eyebrow { color: var(--brand); font-weight: 800; letter-spacing: .14em; font-size: 12px; }
    h1 { margin: 7px 0 8px; font-size: clamp(30px, 5vw, 48px); line-height: 1.05; }
    .subtitle { margin: 0; color: var(--muted); max-width: 720px; line-height: 1.7; }
    .status-pill {
      border: 1px solid var(--line); background: rgba(255,255,255,.75); border-radius: 999px;
      padding: 9px 13px; font-weight: 700; white-space: nowrap;
    }
    .grid { display: grid; grid-template-columns: 1.05fr .95fr; gap: 18px; }
    .panel {
      background: rgba(255,255,255,.94); border: 1px solid rgba(216,224,220,.9);
      border-radius: 22px; box-shadow: var(--shadow); padding: 22px;
    }
    .panel h2 { margin: 0 0 14px; font-size: 20px; }
    label { display: block; font-size: 14px; font-weight: 800; margin-bottom: 8px; }
    input, textarea, select, button { font: inherit; }
    input, textarea, select {
      width: 100%; border: 1px solid #bdcac5; border-radius: 13px; background: #fff;
      color: var(--ink); padding: 12px 14px; outline: none;
    }
    input:focus, textarea:focus, select:focus {
      border-color: var(--brand); box-shadow: 0 0 0 3px rgba(19,111,99,.12);
    }
    textarea { min-height: 116px; resize: vertical; line-height: 1.55; }
    button {
      border: 0; border-radius: 13px; padding: 12px 17px; cursor: pointer; font-weight: 800;
      background: var(--brand); color: white; transition: transform .12s, background .12s;
    }
    button:hover { background: var(--brand-dark); transform: translateY(-1px); }
    button:disabled { cursor: wait; opacity: .55; transform: none; }
    button.secondary { background: #edf4f1; color: var(--brand-dark); }
    button.secondary:hover { background: #dcebe6; }
    .row { display: grid; grid-template-columns: 1fr 160px; gap: 12px; margin: 12px 0; }
    .actions { display: flex; justify-content: flex-end; gap: 10px; }
    .quick-list { display: flex; flex-wrap: wrap; gap: 8px; }
    .quick-list button { padding: 9px 11px; font-size: 13px; }
    .notice {
      margin-top: 14px; border-left: 4px solid var(--accent); background: #fff8db;
      padding: 12px 14px; border-radius: 10px; color: #624f17; line-height: 1.55;
    }
    .facts { display: grid; gap: 11px; margin: 0; }
    .fact { display: grid; grid-template-columns: 110px 1fr; gap: 12px; font-size: 14px; }
    .fact b { color: var(--brand-dark); }
    .results { margin-top: 20px; display: grid; gap: 14px; }
    .result-card {
      background: var(--panel); border: 1px solid var(--line); border-radius: 18px;
      padding: 18px; box-shadow: 0 8px 24px rgba(27,60,52,.06);
    }
    .result-card h3 { margin: 0; font-size: 17px; line-height: 1.45; }
    .meta { color: var(--muted); margin: 7px 0 11px; font-size: 13px; }
    .snippet { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; margin: 0; }
    .terms { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
    .term { background: #edf4f1; color: var(--brand-dark); padding: 4px 8px; border-radius: 999px; font-size: 12px; }
    .citation { margin-top: 12px; color: var(--muted); font-family: ui-monospace, monospace; font-size: 11px; }
    .empty { text-align: center; padding: 34px 12px; color: var(--muted); }
    .feedback { margin-top: 18px; display: none; }
    .feedback.visible { display: block; }
    .feedback-grid { display: grid; grid-template-columns: 220px 1fr auto; gap: 10px; align-items: end; }
    .toast { min-height: 24px; margin-top: 10px; color: var(--brand-dark); font-weight: 700; }
    .toast.error { color: var(--danger); }
    .gate {
      position: fixed; inset: 0; z-index: 20; background: rgba(10,35,31,.72);
      backdrop-filter: blur(9px); display: grid; place-items: center; padding: 20px;
    }
    .gate.hidden { display: none; }
    .gate-card {
      width: min(440px, 100%); background: white; border-radius: 24px; padding: 28px;
      box-shadow: 0 30px 80px rgba(0,0,0,.3);
    }
    .gate-card h2 { margin-top: 0; }
    .gate-card p { color: var(--muted); line-height: 1.6; }
    .gate-actions { margin-top: 12px; display: flex; gap: 9px; }
    .gate-actions input { flex: 1; }
    @media (max-width: 820px) {
      header { display: block; }
      .status-pill { display: inline-block; margin-top: 14px; }
      .grid, .row, .feedback-grid { grid-template-columns: 1fr; }
      .actions { justify-content: stretch; }
      .actions button { width: 100%; }
    }
  </style>
</head>
<body>
  <div class="gate" id="gate">
    <div class="gate-card">
      <div class="eyebrow">PRIVATE UAT</div>
      <h2>輸入測試存取碼</h2>
      <p>這是 May 的臨時只讀測試介面。存取碼只保留在目前瀏覽器分頁，不會放進網址。</p>
      <div class="gate-actions">
        <input id="access-code" type="password" autocomplete="current-password" placeholder="UAT access code">
        <button id="unlock" type="button">進入</button>
      </div>
      <div class="toast" id="gate-message"></div>
    </div>
  </div>

  <main class="shell">
    <header>
      <div>
        <div class="eyebrow">FORMOWL · MAIL EVIDENCE</div>
        <h1>郵件證據功能測試</h1>
        <p class="subtitle">直接透過網頁查詢已預載的 May 測試資料，不經 ChatGPT，不需再次上傳信件。</p>
      </div>
      <div class="status-pill" id="server-status">檢查服務中…</div>
    </header>

    <section class="grid">
      <div class="panel">
        <h2>輸入測試問題</h2>
        <label for="query">問題、PO、料號或關鍵字</label>
        <textarea id="query" placeholder="例如：最近一次文顥的量產時間？"></textarea>
        <div class="row">
          <div>
            <label for="sort">結果排序</label>
            <select id="sort">
              <option value="relevance">相關度優先</option>
              <option value="recent">最新郵件優先</option>
            </select>
          </div>
          <div>
            <label for="limit">顯示筆數</label>
            <select id="limit">
              <option value="5">5 筆</option>
              <option value="8" selected>8 筆</option>
              <option value="12">12 筆</option>
              <option value="20">20 筆</option>
            </select>
          </div>
        </div>
        <div class="actions">
          <button id="search" type="button">查詢郵件證據</button>
        </div>
        <div class="toast" id="query-message"></div>
        <div class="notice">排程不代表已完成量產；Pull-in、交期與數量請依證據內容再次確認。本介面不會回寫郵件、專案或知識圖譜。</div>
      </div>

      <aside class="panel">
        <h2>快速測試情境</h2>
        <div class="quick-list">
          <button class="secondary quick" data-sort="recent" data-query="最近一次文顥的量產時間">文顥最近排程</button>
          <button class="secondary quick" data-sort="recent" data-query="有哪些料件需要 pull-in">Pull-in 料件</button>
          <button class="secondary quick" data-sort="relevance" data-query="PO 470002154">查 PO</button>
          <button class="secondary quick" data-sort="recent" data-query="料號 SP.Z6H02G003 的最新進度">查料號</button>
        </div>
        <hr style="border:0;border-top:1px solid var(--line);margin:20px 0">
        <div class="facts">
          <div class="fact"><b>資料來源</b><span>預先解析的 May 測試郵件證據</span></div>
          <div class="fact"><b>寫入行為</b><span>無；只有私人 UAT 回饋紀錄</span></div>
          <div class="fact"><b>身分</b><span>由 server 固定綁定，瀏覽器不能指定</span></div>
          <div class="fact"><b>適用範圍</b><span>內網／VPN 臨時功能測試</span></div>
        </div>
      </aside>
    </section>

    <section class="results" id="results"></section>

    <section class="panel feedback" id="feedback">
      <h2>這次結果如何？</h2>
      <div class="feedback-grid">
        <div>
          <label for="verdict">判定</label>
          <select id="verdict">
            <option value="correct">正確</option>
            <option value="partially_correct">部分正確</option>
            <option value="incorrect">錯誤</option>
            <option value="no_result">找不到資料</option>
            <option value="citation_issue">引用／證據有問題</option>
          </select>
        </div>
        <div>
          <label for="feedback-note">補充說明（選填）</label>
          <input id="feedback-note" maxlength="1000" placeholder="例如：排程日期正確，但料號少了一筆">
        </div>
        <button id="send-feedback" type="button">送出回饋</button>
      </div>
      <div class="toast" id="feedback-message"></div>
    </section>
  </main>

  <script>
    const keyName = "formowl-mail-uat-code";
    let accessCode = sessionStorage.getItem(keyName) || "";
    let currentQueryId = "";
    const byId = (id) => document.getElementById(id);

    function setToast(id, text, isError = false) {
      const node = byId(id);
      node.textContent = text;
      node.classList.toggle("error", isError);
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "X-FormOwl-UAT-Code": accessCode,
          ...(options.headers || {})
        }
      });
      let payload = {};
      try { payload = await response.json(); } catch (_) {}
      if (!response.ok) {
        const error = new Error(payload.error_code || "request_failed");
        error.status = response.status;
        throw error;
      }
      return payload;
    }

    async function unlock() {
      const code = byId("access-code").value.trim();
      if (!code) {
        setToast("gate-message", "請輸入存取碼。", true);
        return;
      }
      accessCode = code;
      try {
        await api("/api/session-summary", { method: "GET", headers: {} });
        sessionStorage.setItem(keyName, accessCode);
        byId("gate").classList.add("hidden");
        setToast("gate-message", "");
      } catch (_) {
        accessCode = "";
        sessionStorage.removeItem(keyName);
        setToast("gate-message", "存取碼不正確，請再試一次。", true);
      }
    }

    function appendText(parent, tag, text, className = "") {
      const node = document.createElement(tag);
      node.textContent = text;
      if (className) node.className = className;
      parent.appendChild(node);
      return node;
    }

    function renderResults(payload) {
      const root = byId("results");
      root.replaceChildren();
      currentQueryId = payload.query_id;
      byId("feedback").classList.add("visible");
      byId("feedback-note").value = "";
      setToast("feedback-message", "");

      if (!payload.results.length) {
        const panel = document.createElement("div");
        panel.className = "panel empty";
        panel.textContent = "沒有找到符合的郵件證據。請改用 PO、料號、供應商或 pull-in 等較明確關鍵字。";
        root.appendChild(panel);
        return;
      }

      const summary = document.createElement("div");
      summary.className = "panel";
      appendText(summary, "h2", `找到 ${payload.result_count} 筆證據`);
      appendText(summary, "p", payload.notice, "subtitle");
      root.appendChild(summary);

      for (const item of payload.results) {
        const card = document.createElement("article");
        card.className = "result-card";
        appendText(card, "h3", item.subject);
        appendText(card, "div", item.sent_at ? `郵件時間：${item.sent_at}` : "郵件時間：未提供", "meta");
        appendText(card, "p", item.snippet, "snippet");
        if (item.matched_terms.length) {
          const terms = document.createElement("div");
          terms.className = "terms";
          for (const term of item.matched_terms) appendText(terms, "span", term, "term");
          card.appendChild(terms);
        }
        if (item.citation) {
          appendText(
            card,
            "div",
            `證據：${item.citation.citation_id} · ${item.citation.source_observation_id}`,
            "citation"
          );
        }
        root.appendChild(card);
      }
    }

    async function search() {
      const queryText = byId("query").value.trim();
      if (!queryText) {
        setToast("query-message", "請先輸入問題或關鍵字。", true);
        return;
      }
      const button = byId("search");
      button.disabled = true;
      setToast("query-message", "查詢中，常見詞可能需要數秒…");
      try {
        const payload = await api("/api/query", {
          method: "POST",
          body: JSON.stringify({
            query_text: queryText,
            sort: byId("sort").value,
            limit: Number(byId("limit").value)
          })
        });
        renderResults(payload);
        setToast("query-message", `完成：顯示 ${payload.result_count} 筆證據。`);
      } catch (error) {
        if (error.status === 401) {
          sessionStorage.removeItem(keyName);
          byId("gate").classList.remove("hidden");
        }
        setToast("query-message", "查詢失敗，請確認存取碼或稍後重試。", true);
      } finally {
        button.disabled = false;
      }
    }

    async function sendFeedback() {
      if (!currentQueryId) return;
      const button = byId("send-feedback");
      button.disabled = true;
      try {
        await api("/api/feedback", {
          method: "POST",
          body: JSON.stringify({
            query_id: currentQueryId,
            verdict: byId("verdict").value,
            note: byId("feedback-note").value
          })
        });
        setToast("feedback-message", "回饋已記錄，謝謝。");
      } catch (_) {
        setToast("feedback-message", "回饋未送出，請稍後重試。", true);
      } finally {
        button.disabled = false;
      }
    }

    byId("unlock").addEventListener("click", unlock);
    byId("access-code").addEventListener("keydown", (event) => {
      if (event.key === "Enter") unlock();
    });
    byId("search").addEventListener("click", search);
    byId("send-feedback").addEventListener("click", sendFeedback);
    for (const button of document.querySelectorAll(".quick")) {
      button.addEventListener("click", () => {
        byId("query").value = button.dataset.query;
        byId("sort").value = button.dataset.sort;
        search();
      });
    }

    fetch("/api/health", { cache: "no-store" })
      .then((response) => response.json())
      .then((payload) => {
        byId("server-status").textContent = payload.status === "ready" ? "服務已就緒" : "服務準備中";
      })
      .catch(() => { byId("server-status").textContent = "服務未連線"; });

    if (accessCode) {
      api("/api/session-summary", { method: "GET", headers: {} })
        .then(() => byId("gate").classList.add("hidden"))
        .catch(() => {
          accessCode = "";
          sessionStorage.removeItem(keyName);
        });
    }
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
]
