from __future__ import annotations

import base64
import binascii
import json
import math
import os
import re
import secrets
import threading
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from formowl_contract import (
    ContractValidationError,
    assert_no_public_raw_references,
    now_iso,
    sha256_json,
    validate_semantic_request,
)

from ._guards import (
    assert_authorized_evidence_payload_safe,
    assert_public_payload_safe,
    redact_authorized_evidence_text,
    safe_public_string,
)
from .document_uat_mcp import (
    project_document_uat_payload_public,
    validate_document_uat_payload,
)

if TYPE_CHECKING:
    from .bundle import MailEvidenceBundle
    from .human_uat_orchestrator import UatConversationOutcome
    from .human_uat_upload import UatUploadedResourcePart


_MAX_REQUEST_BYTES = 64 * 1024
_MAX_PROMPT_CHARS = 8_000
_PRE_AUTH_COOKIE = "formowl_uat_pre_auth"
_SESSION_COOKIE = "formowl_uat_session"
_TEMPORARY_BASIC_USERNAME = b"formowl-uat"
_TEMPORARY_BASIC_CHALLENGE = 'Basic realm="FormOwl temporary UAT", charset="UTF-8"'
_QUERY_FAILURE_PHASES = frozenset(
    {
        "runtime_init",
        "provider_model",
        "provider_timeout",
        "mcp_client",
        "mcp_timeout",
        "projection",
        "session_state",
        "unknown",
    }
)
_QUERY_FAILURE_CLASSES = _QUERY_FAILURE_PHASES
_SAFE_QUERY_EXCEPTION_CLASSES = frozenset({"ContractValidationError", "TypeError", "ValueError"})
_SAFE_PROVIDER_PHASES = frozenset(
    {
        "provider_model",
        "provider_request",
        "mcp_client",
        "finalization",
        "turn_budget",
    }
)
_SAFE_PROVIDER_STOP_REASONS = frozenset(
    {
        "budget_exhausted",
        "citation_validation_failed",
        "answer_public_safety_failed",
        "coverage_validation_failed",
        "invalid_arguments",
        "mcp_unavailable",
        "no_evidence",
        "no_progress",
        "provider_incomplete",
        "provider_timeout",
        "public_term_unavailable",
    }
)
_SAFE_PROVIDER_STATUSES = frozenset({"cancelled", "completed", "failed", "incomplete"})
_SAFE_CODEX_ERROR_INFO_KINDS = frozenset(
    {
        "contextWindowExceeded",
        "sessionBudgetExceeded",
        "usageLimitExceeded",
        "rateLimitExceeded",
        "serverOverloaded",
        "cyberPolicy",
        "misalignmentPolicyViolation",
        "internalServerError",
        "unauthorized",
        "badRequest",
        "threadRollbackFailed",
        "sandboxError",
        "other",
        "httpConnectionFailed",
        "responseStreamConnectionFailed",
        "responseStreamDisconnected",
        "responseTooManyFailedAttempts",
        "activeTurnNotSteerable",
    }
)
_SAFE_PROVIDER_INCOMPLETE_REASONS = frozenset({"content_filter", "max_output_tokens"})
_SAFE_PROVIDER_ERROR_CODES = frozenset(
    {
        "context_length_exceeded",
        "insufficient_quota",
        "invalid_api_key",
        "invalid_parameter",
        "model_not_found",
        "rate_limit_exceeded",
        "server_error",
        "unsupported_parameter",
    }
)
_SAFE_PROVIDER_ERROR_TYPES = frozenset(
    {
        "api_error",
        "authentication_error",
        "conflict_error",
        "invalid_request_error",
        "not_found_error",
        "permission_error",
        "rate_limit_error",
        "server_error",
        "unprocessable_entity_error",
    }
)
_SAFE_PROVIDER_ERROR_PARAMS = frozenset(
    {
        "model",
        "tools",
        "tool_choice",
        "text.format",
        "reasoning",
        "max_output_tokens",
        "stream",
        "store",
        "safety_identifier",
    }
)
_SAFE_PROVIDER_ERROR_MESSAGE_CLASSES = frozenset(
    {
        "timeout",
        "rate_limit",
        "capacity_unavailable",
        "invalid_parameter",
        "unknown",
    }
)
_SAFE_PROVIDER_BODY_SHAPES = frozenset(
    {
        "empty",
        "gzip_bytes",
        "invalid_json",
        "invalid_utf8",
        "json_non_object",
        "json_object",
        "sse",
        "too_large",
    }
)
_SAFE_PROVIDER_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/problem+json",
        "text/event-stream",
        "text/html",
        "text/plain",
        "other",
    }
)
_SAFE_PROVIDER_CONTENT_ENCODINGS = frozenset({"br", "deflate", "gzip", "identity", "other"})
_MAX_SAFE_PROVIDER_BODY_BYTES = 4 * 1024 * 1024 + 1
_SAFE_MCP_FAILURE_REASONS = frozenset(
    {
        "http_status",
        "jsonrpc_result_error",
        "missing_structured_payload",
        "missing_data_mapping",
        "authorization_audit_failed",
        "authentication_required",
        "forbidden_tool",
        "handler_not_configured",
        "invalid_tool_arguments",
        "required_grant_unavailable",
        "tool_execution_failed",
        "tool_policy_unavailable",
        "unknown_tool",
        "unsafe_tool_payload",
        "workspace_role_forbidden",
    }
)
_SAFE_MCP_TOOL_NAMES = frozenset(
    {
        "query_effective_graph",
        "query_effective_graph_view",
        "query_mail_evidence",
        "whoami",
    }
)
_SAFE_MCP_SELECTOR_KINDS = frozenset(
    {
        "none",
        "mail_import_session_id",
        "mail_evidence_bundle_id",
        "multiple",
    }
)
_SAFE_MCP_RESPONSE_STAGES = frozenset(
    {
        "request_built",
        "http_response",
        "jsonrpc_error",
        "structured_payload",
        "payload_validation",
        "payload_validated",
        "timeout",
        "exception",
    }
)
_PUBLIC_QUERY_STATUSES = frozenset({"complete", "partial", "clarification_required", "error"})
_PUBLIC_QUERY_ERROR_CODES = frozenset({"mcp_timeout", "query_failed"})
_PUBLIC_QUERY_FAILURE_ANSWER = "查詢失敗，請稍後再試。"


class MailHumanUatQueryService(Protocol):
    secure_cookie: bool

    def ensure_browser_session(
        self,
        session_id: str | None,
    ) -> tuple[str, int] | None: ...

    def begin_browser_authorization(self) -> tuple[str, str, int]: ...

    def complete_browser_authorization(
        self,
        *,
        state: str,
        code: str,
        browser_nonce: str | None,
    ) -> tuple[str, int]: ...

    def is_browser_session_authenticated(self, session_id: str | None) -> bool: ...

    def logout_browser_session(self, session_id: str | None) -> None: ...

    def read_browser_conversation(
        self,
        session_id: str | None,
    ) -> Mapping[str, Any]: ...

    def reset_browser_conversation(
        self,
        session_id: str | None,
    ) -> tuple[str, int]: ...

    def ask(
        self,
        prompt: str,
        *,
        session_id: str | None,
    ) -> Mapping[str, Any]: ...


def create_mail_human_uat_http_server(
    host: str,
    port: int,
    query_service: MailHumanUatQueryService,
    *,
    temporary_access_code: str | None = None,
) -> ThreadingHTTPServer:
    """Select the existing handler from the explicit service type, never input data."""

    if isinstance(query_service, MailHumanUatService):
        if temporary_access_code is not None:
            raise ValueError("shared UAT service does not accept temporary access codes")
        return _create_shared_mail_human_uat_http_server(host, port, query_service)

    if temporary_access_code is not None and (
        not isinstance(temporary_access_code, str) or not temporary_access_code
    ):
        raise ValueError("temporary access code must be non-empty text")
    return ThreadingHTTPServer(
        (host, port),
        _build_mail_human_uat_http_handler(
            query_service,
            temporary_access_code=temporary_access_code,
        ),
    )


def _build_mail_human_uat_http_handler(
    query_service: MailHumanUatQueryService,
    *,
    temporary_access_code: str | None,
) -> type[BaseHTTPRequestHandler]:
    from .human_uat_orchestrator import (
        diagnostic_comparability,
    )

    expected_basic_password = (
        temporary_access_code.encode("utf-8") if temporary_access_code is not None else None
    )

    class MailHumanUatHttpHandler(BaseHTTPRequestHandler):
        server_version = "FormOwlMailHumanUAT/0.1"

        def do_GET(self) -> None:  # noqa: N802
            if not self._basic_access_allowed():
                self._send_basic_auth_required()
                return
            parsed = urlparse(self.path)
            route = parsed.path
            if route == "/":
                try:
                    session_id, set_cookies = self._prepared_browser_session()
                except Exception:
                    self._send_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "browser_session_failed",
                    )
                    return
                authenticated = query_service.is_browser_session_authenticated(session_id)
                self._send_html(
                    HTTPStatus.OK,
                    _render_page(authenticated),
                    set_cookies=set_cookies,
                )
                return
            if route == "/auth/start":
                try:
                    location, browser_nonce, max_age = query_service.begin_browser_authorization()
                except Exception:
                    self._send_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "auth_start_failed",
                    )
                    return
                self._send_redirect(
                    HTTPStatus.FOUND,
                    location,
                    set_cookies=(
                        _browser_cookie(
                            _PRE_AUTH_COOKIE,
                            browser_nonce,
                            max_age=max_age,
                            secure=query_service.secure_cookie,
                        ),
                    ),
                )
                return
            if route == "/auth/callback":
                try:
                    parameters = parse_qs(
                        parsed.query,
                        keep_blank_values=True,
                        strict_parsing=True,
                    )
                    if set(parameters) != {"state", "code"} or any(
                        len(values) != 1 or not values[0] for values in parameters.values()
                    ):
                        raise ValueError("invalid callback")
                    session_id, max_age = query_service.complete_browser_authorization(
                        state=parameters["state"][0],
                        code=parameters["code"][0],
                        browser_nonce=self._cookie_value(_PRE_AUTH_COOKIE),
                    )
                except (ValueError, TypeError):
                    self._send_error(
                        HTTPStatus.BAD_REQUEST,
                        "auth_callback_rejected",
                    )
                    return
                except Exception:
                    self._send_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "auth_callback_failed",
                    )
                    return
                self._send_redirect(
                    HTTPStatus.SEE_OTHER,
                    "/",
                    set_cookies=(
                        _browser_cookie(
                            _PRE_AUTH_COOKIE,
                            "",
                            max_age=0,
                            secure=query_service.secure_cookie,
                        ),
                        _browser_cookie(
                            _SESSION_COOKIE,
                            session_id,
                            max_age=max_age,
                            secure=query_service.secure_cookie,
                        ),
                    ),
                )
                return
            if route == "/api/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "mail_human_uat_http",
                        "query_service_connected": True,
                    },
                )
                return
            if route == "/api/transcript":
                session_id = self._session_id()
                if not query_service.is_browser_session_authenticated(session_id):
                    self._send_error(HTTPStatus.UNAUTHORIZED, "auth_required")
                    return
                try:
                    conversation = _normalize_browser_conversation(
                        query_service.read_browser_conversation(session_id)
                    )
                except PermissionError:
                    self._send_error(HTTPStatus.UNAUTHORIZED, "auth_required")
                    return
                except Exception:
                    self._send_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "transcript_failed",
                    )
                    return
                self._send_json(HTTPStatus.OK, conversation)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")

        def do_POST(self) -> None:  # noqa: N802
            if not self._basic_access_allowed():
                self._send_basic_auth_required()
                return
            route = urlparse(self.path).path
            if route not in {
                "/api/chat",
                "/api/conversation/reset",
                "/auth/logout",
            }:
                self._send_error(HTTPStatus.NOT_FOUND, "route_not_found")
                return
            if not self._same_origin_allowed():
                self._send_error(HTTPStatus.FORBIDDEN, "same_origin_required")
                return
            session_id = self._session_id()
            if route == "/auth/logout":
                query_service.logout_browser_session(session_id)
                self._send_redirect(
                    HTTPStatus.SEE_OTHER,
                    "/",
                    set_cookies=(
                        _browser_cookie(
                            _SESSION_COOKIE,
                            "",
                            max_age=0,
                            secure=query_service.secure_cookie,
                        ),
                    ),
                )
                return
            if not query_service.is_browser_session_authenticated(session_id):
                self._send_error(HTTPStatus.UNAUTHORIZED, "auth_required")
                return
            if route == "/api/conversation/reset":
                try:
                    new_session_id, max_age = query_service.reset_browser_conversation(session_id)
                    _validate_new_browser_session(new_session_id, max_age)
                except PermissionError:
                    self._send_error(HTTPStatus.UNAUTHORIZED, "auth_required")
                    return
                except Exception:
                    self._send_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "conversation_reset_failed",
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "reset",
                        "turns": [],
                        "turn_count": 0,
                        "retention": "temporary_bounded",
                    },
                    set_cookies=(
                        _browser_cookie(
                            _SESSION_COOKIE,
                            new_session_id,
                            max_age=max_age,
                            secure=query_service.secure_cookie,
                        ),
                    ),
                )
                return
            try:
                payload = self._read_json()
                prompt = payload.get("prompt")
                if (
                    not isinstance(prompt, str)
                    or not prompt.strip()
                    or len(prompt) > _MAX_PROMPT_CHARS
                ):
                    raise ValueError("invalid prompt")
            except PermissionError:
                self._send_error(HTTPStatus.UNAUTHORIZED, "auth_required")
                return
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
                self._send_error(HTTPStatus.BAD_REQUEST, "request_rejected")
                return
            try:
                response = _normalize_query_response(
                    query_service.ask(prompt, session_id=session_id)
                )
            except PermissionError:
                self._send_error(HTTPStatus.UNAUTHORIZED, "auth_required")
                return
            except Exception as exc:
                diagnostic = _safe_query_failure_diagnostic(query_service, exc)
                self._send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    (
                        "mcp_timeout"
                        if diagnostic["failure_class"] == "mcp_timeout"
                        else "query_failed"
                    ),
                    diagnostic=diagnostic,
                )
                return
            self._send_json(HTTPStatus.OK, response)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _basic_access_allowed(self) -> bool:
            if expected_basic_password is None:
                return True
            authorization_values = self.headers.get_all("Authorization")
            if not authorization_values or len(authorization_values) != 1:
                return False
            scheme, separator, encoded_credentials = authorization_values[0].partition(" ")
            if scheme.casefold() != "basic" or not separator or not encoded_credentials:
                return False
            try:
                decoded_credentials = base64.b64decode(
                    encoded_credentials,
                    validate=True,
                )
            except (binascii.Error, ValueError):
                return False
            if b":" not in decoded_credentials:
                return False
            username, password = decoded_credentials.split(b":", 1)
            username_matches = secrets.compare_digest(
                username,
                _TEMPORARY_BASIC_USERNAME,
            )
            password_matches = secrets.compare_digest(
                password,
                expected_basic_password,
            )
            return username_matches and password_matches

        def _send_basic_auth_required(self) -> None:
            payload = {
                "status": "error",
                "error_code": "temporary_access_required",
                "http_status_code": int(HTTPStatus.UNAUTHORIZED),
            }
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self._send_common_headers("application/json; charset=utf-8")
            self.send_header("WWW-Authenticate", _TEMPORARY_BASIC_CHALLENGE)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _same_origin_allowed(self) -> bool:
            origins = self.headers.get_all("Origin")
            hosts = self.headers.get_all("Host")
            if not origins or len(origins) != 1 or not hosts or len(hosts) != 1:
                return False
            origin = urlparse(origins[0].strip())
            return (
                origin.scheme.lower() in {"http", "https"}
                and origin.netloc.casefold() == hosts[0].strip().casefold()
                and not origin.path
                and not origin.params
                and not origin.query
                and not origin.fragment
                and not origin.username
                and not origin.password
            )

        def _read_json(self) -> dict[str, Any]:
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != (
                "application/json"
            ):
                raise ValueError("invalid content type")
            value = self.headers.get("Content-Length")
            if value is None or not value.isdigit():
                raise ValueError("missing content length")
            length = int(value)
            if length <= 0 or length > _MAX_REQUEST_BYTES:
                raise ValueError("invalid content length")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete body")
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("invalid payload")
            return payload

        def _send_error(
            self,
            status: HTTPStatus,
            error_code: str,
            *,
            diagnostic: Mapping[str, Any] | None = None,
        ) -> None:
            payload: dict[str, Any] = {
                "status": "error",
                "error_code": error_code,
                "http_status_code": int(status),
            }
            if diagnostic is not None:
                payload["diagnostic"] = dict(diagnostic)
            if error_code in _PUBLIC_QUERY_ERROR_CODES:
                payload.setdefault("diagnostic", {})["diagnostic_comparability"] = (
                    diagnostic_comparability(payload["diagnostic"])
                )
                payload["response"] = _browser_error_response()
            self._send_json(
                status,
                payload,
            )

        def _prepared_browser_session(
            self,
        ) -> tuple[str | None, tuple[str, ...]]:
            session_id = self._session_id()
            ensure_session = getattr(query_service, "ensure_browser_session", None)
            if not callable(ensure_session):
                return session_id, ()
            created = ensure_session(session_id)
            if created is None:
                return session_id, ()
            created_session_id, max_age = created
            if (
                not isinstance(created_session_id, str)
                or not created_session_id
                or isinstance(max_age, bool)
                or not isinstance(max_age, int)
                or max_age <= 0
            ):
                raise ValueError("invalid browser session")
            return (
                created_session_id,
                (
                    _browser_cookie(
                        _SESSION_COOKIE,
                        created_session_id,
                        max_age=max_age,
                        secure=query_service.secure_cookie,
                    ),
                ),
            )

        def _session_id(self) -> str | None:
            return self._cookie_value(_SESSION_COOKIE)

        def _cookie_value(self, name: str) -> str | None:
            raw_cookie = self.headers.get("Cookie")
            if not raw_cookie:
                return None
            try:
                cookie = SimpleCookie()
                cookie.load(raw_cookie)
            except Exception:
                return None
            value = cookie.get(name)
            return value.value if value is not None and value.value else None

        def _send_html(
            self,
            status: HTTPStatus,
            body: str,
            *,
            set_cookies: Sequence[str] = (),
        ) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self._send_common_headers("text/html; charset=utf-8")
            for set_cookie in set_cookies:
                self.send_header("Set-Cookie", set_cookie)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(
            self,
            status: HTTPStatus,
            payload: Mapping[str, Any],
            *,
            set_cookies: Sequence[str] = (),
        ) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self._send_common_headers("application/json; charset=utf-8")
            for set_cookie in set_cookies:
                self.send_header("Set-Cookie", set_cookie)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_redirect(
            self,
            status: HTTPStatus,
            location: str,
            *,
            set_cookies: Sequence[str] = (),
        ) -> None:
            self.send_response(status)
            self._send_common_headers("text/plain; charset=utf-8")
            self.send_header("Location", location)
            for set_cookie in set_cookies:
                self.send_header("Set-Cookie", set_cookie)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_common_headers(self, content_type: str) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            )

    return MailHumanUatHttpHandler


def _safe_query_failure_diagnostic(
    query_service: MailHumanUatQueryService,
    exc: Exception,
) -> dict[str, Any]:
    from .human_uat_orchestrator import (
        diagnostic_comparability,
    )

    phase = getattr(query_service, "last_failure_phase", "unknown")
    if phase not in _QUERY_FAILURE_PHASES:
        phase = "unknown"
    if isinstance(exc, TimeoutError):
        failure_class = "provider_timeout"
    else:
        failure_class = getattr(query_service, "last_failure_class", phase)
        if failure_class not in _QUERY_FAILURE_CLASSES:
            failure_class = phase
    request_count = getattr(query_service, "request_count", 0)
    if (
        isinstance(request_count, bool)
        or not isinstance(request_count, int)
        or request_count < 0
        or request_count > 3
    ):
        request_count = 0
    diagnostic = {
        "failure_class": failure_class,
        "phase": phase,
        "request_count": request_count,
    }
    exception_class = type(exc).__name__
    if exception_class in _SAFE_QUERY_EXCEPTION_CLASSES:
        diagnostic["exception_class"] = exception_class
    provider_diagnostic = _safe_provider_diagnostic(getattr(exc, "provider_diagnostic", None))
    if provider_diagnostic is not None:
        diagnostic.update(provider_diagnostic)
    diagnostic.pop("source_binding_fingerprint", None)
    diagnostic["diagnostic_comparability"] = diagnostic_comparability(diagnostic)
    return diagnostic


def _browser_cookie(
    name: str,
    value: str,
    *,
    max_age: int,
    secure: bool,
) -> str:
    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]["httponly"] = True
    cookie[name]["samesite"] = "Lax"
    cookie[name]["path"] = "/"
    cookie[name]["max-age"] = str(max_age)
    if secure:
        cookie[name]["secure"] = True
    return cookie.output(header="").strip()


def _normalize_query_response(value: Mapping[str, Any]) -> dict[str, Any]:
    from .human_uat_orchestrator import (
        diagnostic_comparability,
    )

    if not isinstance(value, Mapping):
        raise TypeError("query response must be a mapping")
    status = _optional_text(value.get("status"), default="complete")
    if status not in _PUBLIC_QUERY_STATUSES:
        raise ValueError("query response status is not public")
    answer = _optional_text(value.get("answer"), default="")
    clarification_value = value.get("clarification")
    clarification = (
        None if clarification_value is None else _optional_text(clarification_value, default="")
    )
    citations = _normalize_citations(value.get("citations", ()))
    normalized = {
        "status": status,
        "answer": answer,
        "citations": citations,
        "citation_count": len(citations),
        "clarification": clarification,
    }
    normalized["diagnostic"] = _safe_provider_diagnostic(value.get("diagnostic")) or {
        "diagnostic_comparability": diagnostic_comparability(None),
    }
    assert_no_public_raw_references(normalized, "issue56_uat_http_response")
    return normalized


def _browser_error_response() -> dict[str, Any]:
    """Return the fixed safe response used for failed browser query turns."""

    return _normalize_query_response(
        {
            "status": "error",
            "answer": _PUBLIC_QUERY_FAILURE_ANSWER,
            "citations": (),
            "clarification": None,
        }
    )


def _safe_provider_diagnostic(value: Any) -> dict[str, Any] | None:
    from .human_uat_orchestrator import (
        _MAX_PROVIDER_ATTEMPT_DIAGNOSTICS,
        _MAX_PROVIDER_REQUESTS_PER_TURN,
        safe_diagnostic_comparability,
        safe_provider_loop_diagnostics,
        safe_provider_transport_diagnostics,
    )

    if not isinstance(value, Mapping):
        return None
    safe: dict[str, Any] = safe_provider_transport_diagnostics(value)
    reason_code = value.get("reason_code")
    if (
        isinstance(reason_code, str)
        and 0 < len(reason_code) <= 96
        and all(character.isalnum() or character in {"_", "-"} for character in reason_code)
    ):
        safe["reason_code"] = reason_code
    http_status = value.get("http_status")
    if (
        isinstance(http_status, int)
        and not isinstance(http_status, bool)
        and 100 <= http_status <= 599
    ):
        safe["http_status"] = http_status
    for key, allowlist in (
        ("provider_status", _SAFE_PROVIDER_STATUSES),
        ("incomplete_reason", _SAFE_PROVIDER_INCOMPLETE_REASONS),
        ("provider_error_code", _SAFE_PROVIDER_ERROR_CODES),
        ("provider_error_type", _SAFE_PROVIDER_ERROR_TYPES),
        ("provider_error_param", _SAFE_PROVIDER_ERROR_PARAMS),
        ("provider_error_message_class", _SAFE_PROVIDER_ERROR_MESSAGE_CLASSES),
        ("codex_error_kind", _SAFE_CODEX_ERROR_INFO_KINDS),
    ):
        token = value.get(key)
        if isinstance(token, str) and token in allowlist:
            safe[key] = token
    for key in (
        "provider_status_sha256",
        "incomplete_reason_sha256",
        "provider_error_code_sha256",
        "provider_error_type_sha256",
        "provider_error_param_sha256",
        "response_content_type_sha256",
        "response_content_encoding_sha256",
    ):
        token = value.get(key)
        if (
            isinstance(token, str)
            and len(token) == 71
            and token.startswith("sha256:")
            and all(character in "0123456789abcdef" for character in token[7:])
        ):
            safe[key] = token
    for key in ("reasoning_item_present", "reasoning_encrypted_content_present"):
        flag = value.get(key)
        if isinstance(flag, bool):
            safe[key] = flag
    body_bytes = value.get("response_body_bytes")
    if (
        isinstance(body_bytes, int)
        and not isinstance(body_bytes, bool)
        and 0 <= body_bytes <= _MAX_SAFE_PROVIDER_BODY_BYTES
    ):
        safe["response_body_bytes"] = body_bytes
    body_shape = value.get("response_body_shape")
    if isinstance(body_shape, str) and body_shape in _SAFE_PROVIDER_BODY_SHAPES:
        safe["response_body_shape"] = body_shape
    content_type = value.get("response_content_type")
    if isinstance(content_type, str) and content_type in _SAFE_PROVIDER_CONTENT_TYPES:
        safe["response_content_type"] = content_type
    content_encoding = value.get("response_content_encoding")
    if isinstance(content_encoding, str) and content_encoding in _SAFE_PROVIDER_CONTENT_ENCODINGS:
        safe["response_content_encoding"] = content_encoding
    declared_bytes = value.get("response_declared_body_bytes")
    if (
        isinstance(declared_bytes, int)
        and not isinstance(declared_bytes, bool)
        and 0 <= declared_bytes <= _MAX_SAFE_PROVIDER_BODY_BYTES
    ):
        safe["response_declared_body_bytes"] = declared_bytes
    declared_match = value.get("response_declared_length_matches")
    if isinstance(declared_match, bool):
        safe["response_declared_length_matches"] = declared_match
    transfer_chunked = value.get("response_transfer_chunked")
    if isinstance(transfer_chunked, bool):
        safe["response_transfer_chunked"] = transfer_chunked
    stop_reason = value.get("stop_reason")
    if stop_reason is None or (
        isinstance(stop_reason, str) and stop_reason in _SAFE_PROVIDER_STOP_REASONS
    ):
        safe["stop_reason"] = stop_reason
    formowl_attempts = value.get("formowl_attempts")
    if (
        isinstance(formowl_attempts, int)
        and not isinstance(formowl_attempts, bool)
        and 0 <= formowl_attempts <= 3
    ):
        safe["formowl_attempts"] = formowl_attempts
    formowl_halted = value.get("formowl_halted")
    if isinstance(formowl_halted, bool):
        safe["formowl_halted"] = formowl_halted
    final_repair_attempted = value.get("final_repair_attempted")
    if isinstance(final_repair_attempted, bool):
        safe["final_repair_attempted"] = final_repair_attempted
    attempt_count = value.get("provider_attempt_count")
    if (
        isinstance(attempt_count, int)
        and not isinstance(attempt_count, bool)
        and 0 <= attempt_count <= _MAX_PROVIDER_REQUESTS_PER_TURN
    ):
        safe["provider_attempt_count"] = attempt_count
    phase = value.get("phase")
    if isinstance(phase, str) and phase in _SAFE_PROVIDER_PHASES:
        safe["phase"] = phase
    raw_timings = value.get("provider_phase_timings")
    if isinstance(raw_timings, Sequence) and not isinstance(raw_timings, (str, bytes)):
        timings: list[dict[str, Any]] = []
        for raw_timing in raw_timings[-_MAX_PROVIDER_ATTEMPT_DIAGNOSTICS:]:
            if not isinstance(raw_timing, Mapping):
                continue
            timing_phase = raw_timing.get("phase")
            elapsed_ms = raw_timing.get("elapsed_ms")
            if (
                not isinstance(timing_phase, str)
                or timing_phase not in _SAFE_PROVIDER_PHASES
                or isinstance(elapsed_ms, bool)
                or not isinstance(elapsed_ms, (int, float))
                or not math.isfinite(float(elapsed_ms))
                or not 0 <= float(elapsed_ms) <= 120_000
            ):
                continue
            timings.append(
                {
                    "phase": timing_phase,
                    "elapsed_ms": round(float(elapsed_ms), 3),
                }
            )
        if timings:
            safe["provider_phase_timings"] = timings
    mcp = _safe_mcp_diagnostic(value.get("mcp"))
    if mcp is not None:
        safe["mcp"] = mcp
    loop = safe_provider_loop_diagnostics(value)
    if "provider_attempts" in value or "provider_attempt_count" in value:
        safe.pop("http_status", None)
    provider_attempts = loop.get("provider_attempts")
    if isinstance(provider_attempts, Sequence) and provider_attempts:
        safe["provider_phase_timings"] = [
            {
                "phase": "provider_request",
                "elapsed_ms": item["elapsed_ms"],
            }
            for item in provider_attempts
        ]
    for key in (
        "request_shape",
        "http_status",
        "tool_choice",
        "outcome",
        "valid_attempt",
        "provider_attempt_count",
        "provider_attempts",
        "provider_attempts_valid",
        "pre_mcp_recovery",
        "mcp_citation_stages",
        "finalization_validation",
        "answer_projection_result",
    ):
        if key in loop:
            safe[key] = loop[key]
    safe["diagnostic_comparability"] = safe_diagnostic_comparability(
        value.get("diagnostic_comparability"),
        safe,
    )
    # Only the service's in-process startup capability survives this projection;
    # hashes/status reconstructed from HTTP or JSON never recreate authority.
    source = safe["diagnostic_comparability"].get("source_binding_fingerprint")
    if source is not None:
        safe["source_binding_fingerprint"] = source
    return safe or None


def _safe_mcp_diagnostic(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    call_count = value.get("call_count")
    elapsed_ms = value.get("elapsed_ms")
    statuses = value.get("status")
    timeout = value.get("timeout")
    if (
        not isinstance(call_count, int)
        or isinstance(call_count, bool)
        or not 0 <= call_count <= 3
        or isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, (int, float))
        or not math.isfinite(float(elapsed_ms))
        or not 0 <= float(elapsed_ms) <= 120_000
        or not isinstance(statuses, Sequence)
        or isinstance(statuses, (str, bytes))
        or len(statuses) > 3
        or not isinstance(timeout, bool)
    ):
        return None
    safe_statuses = [
        status
        for status in statuses
        if (
            isinstance(status, str)
            and 0 < len(status) <= 64
            and all(character.isalnum() or character in {"_", "-"} for character in status)
        )
    ]
    if len(safe_statuses) != len(statuses):
        return None
    safe: dict[str, Any] = {
        "call_count": call_count,
        "elapsed_ms": round(float(elapsed_ms), 3),
        "status": safe_statuses,
        "timeout": timeout,
    }
    request_shape = _safe_mcp_request_shape(value.get("request_shape"))
    if request_shape is not None:
        safe["request_shape"] = request_shape
    request_discriminator = _safe_mcp_request_discriminator(value.get("request_discriminator"))
    if request_discriminator is not None:
        safe["request_discriminator"] = request_discriminator
    response_stage = value.get("response_stage")
    if isinstance(response_stage, str) and response_stage in _SAFE_MCP_RESPONSE_STAGES:
        safe["response_stage"] = response_stage
    exception_class = _safe_mcp_exception_name(value.get("exception_class"))
    if exception_class is not None:
        safe["exception_class"] = exception_class
    failure_reason = value.get("failure_reason")
    if isinstance(failure_reason, str) and failure_reason in _SAFE_MCP_FAILURE_REASONS:
        safe["failure_reason"] = failure_reason
    return safe


def _safe_mcp_request_shape(value: Any) -> dict[str, bool] | None:
    if not isinstance(value, Mapping):
        return None
    keys = (
        "request_contract_present",
        "table_query_present",
        "exact_field_present",
        "exact_inventory_kind_present",
        "page_size_present",
        "cursor_present",
    )
    if any(not isinstance(value.get(key), bool) for key in keys):
        return None
    return {key: value[key] for key in keys}


def _safe_mcp_request_discriminator(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    tool_name = value.get("tool_name")
    selector_kind = value.get("selector_kind")
    selector_present = value.get("selector_present")
    selector_hash = value.get("selector_hash")
    selector_count = value.get("selector_count")
    limit = value.get("limit")
    if (
        not isinstance(tool_name, str)
        or tool_name not in _SAFE_MCP_TOOL_NAMES
        or not isinstance(selector_kind, str)
        or selector_kind not in _SAFE_MCP_SELECTOR_KINDS
        or not isinstance(selector_present, bool)
        or (
            selector_hash is not None
            and (
                not isinstance(selector_hash, str)
                or len(selector_hash) != 71
                or not selector_hash.startswith("sha256:")
                or any(character not in "0123456789abcdef" for character in selector_hash[7:])
            )
        )
        or not isinstance(selector_count, int)
        or isinstance(selector_count, bool)
        or not 0 <= selector_count <= 2
        or (
            limit is not None
            and (not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100)
        )
    ):
        return None
    safe: dict[str, Any] = {
        "tool_name": tool_name,
        "selector_kind": selector_kind,
        "selector_present": selector_present,
        "selector_count": selector_count,
    }
    if selector_hash is not None:
        safe["selector_hash"] = selector_hash
    if limit is not None:
        safe["limit"] = limit
    return safe


def _safe_mcp_exception_name(value: Any) -> str | None:
    if value is None:
        return None
    if (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and all(character.isalnum() or character in {"_", "-"} for character in value)
    ):
        return value
    return None


def _normalize_browser_conversation(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("browser conversation must be a mapping")
    raw_turns = value.get("turns", ())
    if isinstance(raw_turns, (str, bytes)) or not isinstance(raw_turns, Sequence):
        raise TypeError("browser conversation turns must be a sequence")
    turns: list[dict[str, Any]] = []
    for raw_turn in raw_turns:
        if not isinstance(raw_turn, Mapping):
            raise TypeError("browser conversation turn must be a mapping")
        prompt = _optional_text(raw_turn.get("prompt"), default="")
        response = raw_turn.get("response")
        if not isinstance(response, Mapping):
            raise TypeError("browser conversation response must be a mapping")
        turns.append(
            {
                "prompt": prompt,
                "response": _normalize_query_response(response),
            }
        )
    return {
        "turns": turns,
        "turn_count": len(turns),
        "retention": "temporary_bounded",
    }


def _validate_new_browser_session(session_id: Any, max_age: Any) -> None:
    if (
        not isinstance(session_id, str)
        or not session_id
        or isinstance(max_age, bool)
        or not isinstance(max_age, int)
        or max_age <= 0
    ):
        raise ValueError("invalid browser session")


def _normalize_citations(value: Any) -> list[str]:
    citation_values = value
    if isinstance(citation_values, (str, bytes)) or not isinstance(citation_values, Sequence):
        raise TypeError("citations must be a sequence")
    citations: list[str] = []
    for citation in citation_values:
        if isinstance(citation, str):
            label = citation
        elif isinstance(citation, Mapping):
            label = citation.get("label")
            if not isinstance(label, str):
                raise TypeError("citation label must be text")
        else:
            raise TypeError("citation must be text or a mapping")
        if label.strip():
            citations.append(label)
    return citations


def _optional_text(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise TypeError("response text must be a string")
    return value


_PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FormOwl UAT</title>
  <style>
    :root {
      color-scheme: light; --ink: #171717; --muted: #6b7280; --line: #dedede;
      --user: #eef5ff; --assistant: #fff; --warn: #fff8dc; --error: #fff0ee;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; background: #fafafa; color: var(--ink);
      font-family: ui-sans-serif, system-ui, "Noto Sans TC", sans-serif;
    }
    main { width: min(860px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0; }
    h1 { margin: 0 0 8px; }
    .muted { color: var(--muted); }
    #auth-controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    #logout-form { margin: 0; padding: 0; border: 0; background: transparent; }
    #chat-form {
      margin-top: 24px; padding: 20px; border: 1px solid var(--line);
      border-radius: 16px; background: white;
    }
    #conversation-transcript {
      display: grid; gap: 14px; margin-top: 24px;
    }
    .turn {
      padding: 16px; border: 1px solid var(--line); border-radius: 16px;
      background: var(--assistant);
    }
    .turn[data-role="user"] {
      margin-left: min(14%, 88px); background: var(--user);
    }
    .turn[data-role="assistant"] { margin-right: min(8%, 48px); }
    .turn[data-status="partial"], .turn[data-status="clarification_required"] {
      background: var(--warn);
    }
    .turn[data-status="error"] { background: var(--error); }
    .turn-heading {
      display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px;
    }
    .turn-content, .turn-clarification { white-space: pre-wrap; overflow-wrap: anywhere; }
    .turn-status { color: var(--muted); font-size: .9rem; }
    .turn-citations { margin: 12px 0 0; padding-left: 24px; overflow-wrap: anywhere; }
    #empty-conversation {
      margin-top: 24px; padding: 20px; border: 1px dashed var(--line);
      border-radius: 16px; text-align: center;
    }
    textarea {
      width: 100%; min-height: 112px; padding: 12px; border: 1px solid var(--line);
      border-radius: 10px; resize: vertical; font: inherit;
    }
    button {
      margin-top: 12px; padding: 10px 18px; border: 0; border-radius: 999px;
      background: var(--ink); color: white; font: inherit; cursor: pointer;
    }
    button.secondary { margin-top: 0; background: #e5e7eb; color: var(--ink); }
    button:disabled { opacity: .45; cursor: wait; }
    [hidden] { display: none !important; }
    #loading-state { margin-top: 16px; }
    #error-text { color: #b42318; }
    .sr-only {
      position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
      overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
    }
  </style>
</head>
<body>
  <main>
    <h1>FormOwl</h1>
    <div id="health-status" class="muted" role="status">檢查服務中…</div>
    <nav id="auth-controls" data-authenticated="__AUTHENTICATED__">
      <a id="login-link" href="/auth/start" __LOGIN_HIDDEN__>登入</a>
      <button id="new-conversation-button" class="secondary" type="button"
        __NEW_CONVERSATION_HIDDEN__>新對話</button>
      <form id="logout-form" action="/auth/logout" method="post" __LOGOUT_HIDDEN__>
        <button type="submit">登出</button>
      </form>
    </nav>
    <p id="retention-note" class="muted" __CHAT_HIDDEN__>
      此測試對話紀錄與模型上下文皆為暫時且有限保留，不是永久或無限記憶；
      逾時、容量淘汰或服務重啟後可能消失。
    </p>
    <div id="empty-conversation" class="muted" __CHAT_HIDDEN__>
      尚無對話。你可以從下方開始詢問。
    </div>
    <section id="conversation-transcript" aria-label="對話紀錄"
      aria-live="polite"></section>
    <form id="chat-form" __CHAT_HIDDEN__>
      <label for="prompt-input"><strong>問題</strong></label>
      <textarea id="prompt-input" name="prompt" required></textarea>
      <button id="send-button" type="submit">送出</button>
    </form>
    <div id="loading-state" role="status" aria-live="polite" hidden>FormOwl 查詢中…</div>
    <p id="error-text" role="alert" hidden></p>
  </main>
  <script>
    const form = document.getElementById("chat-form");
    const input = document.getElementById("prompt-input");
    const send = document.getElementById("send-button");
    const transcript = document.getElementById("conversation-transcript");
    const emptyConversation = document.getElementById("empty-conversation");
    const newConversation = document.getElementById("new-conversation-button");
    const loading = document.getElementById("loading-state");
    const errorText = document.getElementById("error-text");
    const authenticated =
      document.getElementById("auth-controls").dataset.authenticated === "true";
    const PUBLIC_ERROR_MESSAGES = Object.freeze({
      auth_required: "登入狀態已失效，請重新登入。",
      temporary_access_required: "此測試入口需要臨時存取碼。",
      request_rejected: "問題格式不符合要求，請重新輸入。",
      same_origin_required: "請從目前頁面重新送出要求。",
      mcp_timeout: "查詢逾時；請稍後再試。",
      query_failed: "查詢未完成；請稍後再試。",
      projection_failed: "查詢結果無法安全顯示；請稍後再試。",
      transcript_failed: "無法載入目前對話，請重新整理後再試。",
      conversation_reset_failed: "無法開始新對話，原本的對話仍保留。",
      browser_session_failed: "無法建立瀏覽器工作階段，請重新整理後再試。",
      auth_start_failed: "無法開始登入流程，請稍後再試。",
      auth_callback_rejected: "登入回呼未通過安全驗證。",
      auth_callback_failed: "登入未完成，請稍後再試。",
      route_not_found: "找不到要求的頁面。",
    });
    const PUBLIC_FAILURE_MESSAGES = Object.freeze({
      runtime_init: "查詢服務尚未準備好，請稍後再試。",
      provider_model: "查詢服務未完成回應，請稍後再試。",
      provider_timeout: "查詢逾時；請稍後再試。",
      mcp_client: "來源查詢未完成，請稍後再試。",
      mcp_timeout: "來源查詢逾時；請稍後再試。",
      projection: "查詢結果無法安全顯示，請稍後再試。",
      session_state: "對話狀態未能保存，請重新整理後再試。",
      unknown: "查詢未完成；請稍後再試。",
    });
    const PUBLIC_RESPONSE_STATUSES = new Set([
      "complete",
      "partial",
      "clarification_required",
      "error",
    ]);

    function isRecord(value) {
      return value !== null && typeof value === "object" && !Array.isArray(value);
    }

    function publicErrorMessage(payload, fallback) {
      if (!isRecord(payload)) return fallback;
      const errorCode = payload.error_code;
      if (
        typeof errorCode === "string" &&
        Object.prototype.hasOwnProperty.call(PUBLIC_ERROR_MESSAGES, errorCode)
      ) {
        return PUBLIC_ERROR_MESSAGES[errorCode];
      }
      const diagnostic = payload.diagnostic;
      const failureClass = isRecord(diagnostic) ? diagnostic.failure_class : null;
      if (
        typeof failureClass === "string" &&
        Object.prototype.hasOwnProperty.call(PUBLIC_FAILURE_MESSAGES, failureClass)
      ) {
        return PUBLIC_FAILURE_MESSAGES[failureClass];
      }
      return fallback;
    }

    function makePublicError(message, status) {
      const error = new Error(message);
      error.publicMessage = message;
      if (typeof status === "number") error.httpStatus = status;
      return error;
    }

    async function readJsonResponse(response, fallback) {
      let payload = null;
      try {
        payload = await response.json();
      } catch (_) {
        payload = null;
      }
      if (!response.ok) {
        const error = makePublicError(
          publicErrorMessage(payload, fallback),
          response.status
        );
        if (isRecord(payload) && isRecord(payload.response)) {
          error.publicResponse = responseForDisplay(payload.response);
        }
        throw error;
      }
      if (!isRecord(payload)) {
        throw makePublicError(fallback);
      }
      return payload;
    }

    function responseForDisplay(payload) {
      const status =
        isRecord(payload) && PUBLIC_RESPONSE_STATUSES.has(payload.status)
          ? payload.status
          : "error";
      const answer =
        isRecord(payload) && typeof payload.answer === "string"
          ? payload.answer
          : "";
      const citations =
        isRecord(payload) && Array.isArray(payload.citations)
          ? payload.citations.filter((citation) => typeof citation === "string")
          : [];
      let clarification =
        isRecord(payload) && typeof payload.clarification === "string"
          ? payload.clarification
          : "";
      if (!clarification && status === "partial") {
        clarification = "目前僅取得部分可引用資料，請補充範圍後再查詢。";
      } else if (!clarification && status === "clarification_required") {
        clarification = "請補充查詢範圍或識別資訊後再試。";
      } else if (!answer && status === "error") {
        clarification = "查詢未完成；請稍後再試。";
      }
      return {
        content: answer || (status === "error" ? "查詢未完成。" : ""),
        status,
        citations,
        clarification: clarification || null,
      };
    }

    function setBusy(busy) {
      send.disabled = busy;
      input.disabled = busy;
      newConversation.disabled = busy;
      loading.hidden = !busy;
    }

    function statusLabel(status) {
      const labels = {
        pending: "查詢中…",
        complete: "完成",
        partial: "部分結果",
        clarification_required: "需要釐清",
        error: "失敗"
      };
      return labels[status] || status;
    }

    function populateTurn(article, turn) {
      const role = turn.role === "user" ? "user" : "assistant";
      const status = typeof turn.status === "string" ? turn.status : "complete";
      article.dataset.role = role;
      article.dataset.status = status;
      article.replaceChildren();

      const heading = document.createElement("div");
      heading.className = "turn-heading";
      const speaker = document.createElement("strong");
      speaker.textContent = role === "user" ? "你" : "FormOwl";
      heading.appendChild(speaker);
      if (role === "assistant") {
        const state = document.createElement("span");
        state.className = "turn-status";
        state.textContent = statusLabel(status);
        heading.appendChild(state);
      }
      article.appendChild(heading);

      const content = document.createElement("div");
      content.className = "turn-content";
      content.textContent = typeof turn.content === "string" ? turn.content : "";
      article.appendChild(content);

      if (typeof turn.clarification === "string" && turn.clarification) {
        const clarification = document.createElement("div");
        clarification.className = "turn-clarification";
        clarification.textContent = `需要釐清：${turn.clarification}`;
        article.appendChild(clarification);
      }

      const citations = Array.isArray(turn.citations) ? turn.citations : [];
      if (citations.length) {
        const summary = document.createElement("strong");
        summary.textContent = `引用 ${citations.length} 則`;
        article.appendChild(summary);
        const list = document.createElement("ul");
        list.className = "turn-citations";
        for (const citation of citations) {
          const item = document.createElement("li");
          item.textContent = citation;
          list.appendChild(item);
        }
        article.appendChild(list);
      }
      return article;
    }

    function appendTurn(turn) {
      const article = document.createElement("article");
      article.className = "turn";
      transcript.appendChild(populateTurn(article, turn));
      emptyConversation.hidden = true;
      article.scrollIntoView({ block: "nearest" });
      return article;
    }

    function renderTranscript(turns) {
      transcript.replaceChildren();
      const safeTurns = Array.isArray(turns) ? turns : [];
      for (const turn of safeTurns) {
        if (!turn || typeof turn.prompt !== "string" || !turn.response) continue;
        appendTurn({
          role: "user",
          content: turn.prompt,
          status: "complete",
          citations: []
        });
        appendTurn({
          role: "assistant",
          ...responseForDisplay(turn.response)
        });
      }
      emptyConversation.hidden = safeTurns.length !== 0;
    }

    async function loadTranscript() {
      let response;
      try {
        response = await fetch("/api/transcript", { cache: "no-store" });
      } catch (_) {
        throw makePublicError(PUBLIC_ERROR_MESSAGES.transcript_failed);
      }
      const payload = await readJsonResponse(
        response,
        PUBLIC_ERROR_MESSAGES.transcript_failed
      );
      renderTranscript(payload.turns);
      return payload;
    }

    function showPageError(message) {
      errorText.textContent = message;
      errorText.hidden = false;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const prompt = input.value.trim();
      if (!prompt.trim()) return;
      errorText.hidden = true;
      input.value = "";
      appendTurn({
        role: "user",
        content: prompt,
        status: "complete",
        citations: []
      });
      const pendingTurn = appendTurn({
        role: "assistant",
        content: "",
        status: "pending",
        citations: []
      });
      setBusy(true);
      try {
        let response;
        try {
          response = await fetch("/api/chat", {
            method: "POST",
            cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt })
          });
        } catch (_) {
          throw makePublicError(PUBLIC_ERROR_MESSAGES.query_failed);
        }
        const payload = await readJsonResponse(
          response,
          PUBLIC_ERROR_MESSAGES.query_failed
        );
        populateTurn(pendingTurn, {
          role: "assistant",
          ...responseForDisplay(payload)
        });
        try {
          await loadTranscript();
        } catch (_) {
          pendingTurn.scrollIntoView({ block: "nearest" });
        }
      } catch (error) {
        const message =
          error && typeof error.publicMessage === "string"
            ? error.publicMessage
            : PUBLIC_ERROR_MESSAGES.query_failed;
        const publicResponse =
          error && isRecord(error.publicResponse)
            ? error.publicResponse
            : responseForDisplay({
                status: "error",
                answer: "查詢失敗，請稍後再試。",
                citations: []
              });
        populateTurn(pendingTurn, {
          role: "assistant",
          ...publicResponse
        });
        showPageError(message);
        try {
          await loadTranscript();
        } catch (_) {
          pendingTurn.scrollIntoView({ block: "nearest" });
        }
      } finally {
        setBusy(false);
        input.focus();
      }
    });

    newConversation.addEventListener("click", async () => {
      errorText.hidden = true;
      setBusy(true);
      try {
        let response;
        try {
          response = await fetch("/api/conversation/reset", {
            method: "POST",
            cache: "no-store"
          });
        } catch (_) {
          throw makePublicError(PUBLIC_ERROR_MESSAGES.conversation_reset_failed);
        }
        const payload = await readJsonResponse(
          response,
          PUBLIC_ERROR_MESSAGES.conversation_reset_failed
        );
        renderTranscript(payload.turns);
        input.value = "";
      } catch (error) {
        showPageError(
          error && typeof error.publicMessage === "string"
            ? error.publicMessage
            : PUBLIC_ERROR_MESSAGES.conversation_reset_failed
        );
      } finally {
        setBusy(false);
        input.focus();
      }
    });

    if (authenticated) {
      setBusy(true);
      loadTranscript()
        .then(() => {
          setBusy(false);
          input.focus();
        })
        .catch((error) => {
          loading.hidden = true;
          showPageError(
            error && typeof error.publicMessage === "string"
              ? error.publicMessage
              : PUBLIC_ERROR_MESSAGES.transcript_failed
          );
      });
    }

    fetch("/api/health", { cache: "no-store" })
      .then((response) => readJsonResponse(response, "服務未就緒"))
      .then((payload) => {
        document.getElementById("health-status").textContent =
          payload.status === "ok" ? "服務已連線" : "服務未就緒";
      })
      .catch(() => {
        document.getElementById("health-status").textContent = "服務未就緒";
      });
  </script>
</body>
</html>
"""


def _render_page(authenticated: bool) -> str:
    return (
        _PAGE.replace("__AUTHENTICATED__", "true" if authenticated else "false")
        .replace("__LOGIN_HIDDEN__", "hidden" if authenticated else "")
        .replace("__LOGOUT_HIDDEN__", "" if authenticated else "hidden")
        .replace(
            "__NEW_CONVERSATION_HIDDEN__",
            "" if authenticated else "hidden",
        )
        .replace("__CHAT_HIDDEN__", "" if authenticated else "hidden")
    )


_SHARED_MAX_REQUEST_BYTES = 32 * 1024


_MAX_UPLOAD_REQUEST_BYTES = 520 * 1024 * 1024


_MAX_UPLOAD_FILE_BYTES = 500 * 1024 * 1024


_MAX_UPLOAD_FILES = 20


_MAX_QUERY_CHARS = 500


_MAX_NOTE_CHARS = 1000


_MAX_CHAT_HISTORY_MESSAGES = 16


_DEFAULT_RESULT_LIMIT = 50


_MAX_RESULT_LIMIT = 100


_DEFAULT_DIAGNOSTIC_MCP_TIMEOUT_SECONDS = 15.0


_MAX_DIAGNOSTIC_MCP_TIMEOUT_SECONDS = 30.0


_MAX_DIAGNOSTIC_MCP_RESPONSE_BYTES = 2 * 1024 * 1024


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


_CHAT_KEYS = {
    "query_text",
    "visitor_id",
    "session_id",
    "sequence",
    "source",
}


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


_LEGACY_RUNTIME_LOCK = threading.Lock()


_LEGACY_RUNTIME_LOADED = False


class UatUploadRequestTooLarge(ValueError):
    """Document-first-safe placeholder replaced by the legacy upload runtime."""


class UatConversationModel(Protocol):
    """Structural conversation boundary used by both UAT runtime modes."""

    model_name: str

    def respond(
        self,
        *,
        history: Sequence[Any],
        user_text: str,
        latest_evidence: Mapping[str, Any] | None,
        safety_identifier: str,
        evidence_tool: Callable[..., Mapping[str, Any]],
    ) -> Any: ...

    def discard_conversation(self, safety_identifier: str) -> None: ...


@dataclass(frozen=True)
class _NormalizedEvidenceToolRequest:
    query_text: str
    required_terms: tuple[str, ...]
    sort: str
    limit: int


def _load_legacy_runtime() -> None:
    """Load graph, query, upload, and PST-backed dependencies only on demand."""

    global EvidenceRequirement
    global MailEvidenceQueryGateway
    global PrivateUatMailUploadStore
    global ProjectionSpec
    global TaskAnchor
    global TaskFrame
    global UatConversationMessage
    global UatUploadRequestTooLarge
    global _LEGACY_RUNTIME_LOADED
    global parse_uat_resource_multipart
    global parse_uat_stored_resource
    global parse_uat_uploaded_resource
    global revise_task_frame

    if _LEGACY_RUNTIME_LOADED:
        return
    with _LEGACY_RUNTIME_LOCK:
        if _LEGACY_RUNTIME_LOADED:
            return
        from formowl_graph import (
            EvidenceRequirement as _EvidenceRequirement,
        )
        from formowl_graph import (
            ProjectionSpec as _ProjectionSpec,
        )
        from formowl_graph import (
            TaskAnchor as _TaskAnchor,
        )
        from formowl_graph import (
            TaskFrame as _TaskFrame,
        )
        from formowl_graph import (
            revise_task_frame as _revise_task_frame,
        )

        from .human_uat_orchestrator import (
            UatConversationMessage as _UatConversationMessage,
        )
        from .human_uat_upload import (
            PrivateUatMailUploadStore as _PrivateUatMailUploadStore,
        )
        from .human_uat_upload import (
            UatUploadRequestTooLarge as _UatUploadRequestTooLarge,
        )
        from .human_uat_upload import (
            parse_uat_resource_multipart as _parse_uat_resource_multipart,
        )
        from .human_uat_upload import (
            parse_uat_stored_resource as _parse_uat_stored_resource,
        )
        from .human_uat_upload import (
            parse_uat_uploaded_resource as _parse_uat_uploaded_resource,
        )
        from .query import MailEvidenceQueryGateway as _MailEvidenceQueryGateway

        EvidenceRequirement = _EvidenceRequirement
        MailEvidenceQueryGateway = _MailEvidenceQueryGateway
        PrivateUatMailUploadStore = _PrivateUatMailUploadStore
        ProjectionSpec = _ProjectionSpec
        TaskAnchor = _TaskAnchor
        TaskFrame = _TaskFrame
        UatConversationMessage = _UatConversationMessage
        UatUploadRequestTooLarge = _UatUploadRequestTooLarge
        parse_uat_resource_multipart = _parse_uat_resource_multipart
        parse_uat_stored_resource = _parse_uat_stored_resource
        parse_uat_uploaded_resource = _parse_uat_uploaded_resource
        revise_task_frame = _revise_task_frame
        _LEGACY_RUNTIME_LOADED = True


@dataclass(frozen=True)
class MailHumanUatHttpConfig:
    bundle: MailEvidenceBundle | None
    state_dir: str | Path
    conversation_model: UatConversationModel | None = None
    diagnostic_mcp_url: str | None = None
    document_mcp_url: str | None = None
    diagnostic_mcp_timeout_seconds: float = _DEFAULT_DIAGNOSTIC_MCP_TIMEOUT_SECONDS
    fixed_now: str | None = None
    max_request_bytes: int = _SHARED_MAX_REQUEST_BYTES
    max_upload_request_bytes: int = _MAX_UPLOAD_REQUEST_BYTES
    max_upload_file_bytes: int = _MAX_UPLOAD_FILE_BYTES
    max_upload_files: int = _MAX_UPLOAD_FILES
    event_retention_days: int = _DEFAULT_EVENT_RETENTION_DAYS
    max_event_store_bytes: int = _DEFAULT_MAX_EVENT_STORE_BYTES


class DiagnosticMcpClient(Protocol):
    """Narrow UAT boundary for one governed diagnostic MCP invocation."""

    def query_effective_graph_view(
        self,
        *,
        query_text: str,
        semantic_request: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class DocumentMcpClient(Protocol):
    """Narrow read-only boundary for one authorized document MCP invocation."""

    def read_authorized_documents(
        self,
        *,
        request: _NormalizedEvidenceToolRequest,
    ) -> Mapping[str, Any]: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects so the configured diagnostic MCP is the only target."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> Request | None:
        return None


class FormOwlDiagnosticMcpHttpClient:
    """Bounded JSON-RPC client for the diagnostic FormOwl MCP boundary."""

    def __init__(
        self,
        endpoint_url: str,
        *,
        timeout_seconds: float = _DEFAULT_DIAGNOSTIC_MCP_TIMEOUT_SECONDS,
    ) -> None:
        self._endpoint_url = _validated_diagnostic_mcp_url(endpoint_url)
        self._timeout_seconds = _validated_diagnostic_mcp_timeout(timeout_seconds)
        self._opener = build_opener(_NoRedirectHandler())

    def query_effective_graph_view(
        self,
        *,
        query_text: str,
        semantic_request: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        normalized_request = validate_semantic_request(semantic_request)
        if (
            not isinstance(query_text, str)
            or not query_text.strip()
            or len(query_text) > _MAX_QUERY_CHARS
        ):
            raise ContractValidationError("diagnostic MCP query text is invalid")
        request_id = f"uat_semantic_{secrets.token_hex(12)}"
        request_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": "query_effective_graph_view",
                "arguments": {
                    # The source text is retained only for the diagnostic MCP
                    # audit boundary. Execution is solely semantic_request.
                    "query_text": query_text,
                    "semantic_request": normalized_request,
                },
            },
        }
        request_body = json.dumps(
            request_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self._endpoint_url,
            data=request_body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                status_code = response.getcode()
                if status_code != HTTPStatus.OK:
                    raise RuntimeError("diagnostic MCP returned an unexpected HTTP status")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    if (
                        not content_length.isdigit()
                        or int(content_length) > _MAX_DIAGNOSTIC_MCP_RESPONSE_BYTES
                    ):
                        raise RuntimeError("diagnostic MCP response is invalid")
                body = response.read(_MAX_DIAGNOSTIC_MCP_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError("diagnostic MCP request failed") from exc
        if len(body) > _MAX_DIAGNOSTIC_MCP_RESPONSE_BYTES:
            raise RuntimeError("diagnostic MCP response is too large")
        try:
            response_payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("diagnostic MCP response is invalid") from exc
        if not isinstance(response_payload, Mapping):
            raise RuntimeError("diagnostic MCP response is invalid")
        if response_payload.get("jsonrpc") != "2.0" or response_payload.get("id") != request_id:
            raise RuntimeError("diagnostic MCP response is invalid")
        if "error" in response_payload:
            raise RuntimeError("diagnostic MCP reported a transport error")
        result = response_payload.get("result")
        if not isinstance(result, Mapping) or result.get("isError") is True:
            raise RuntimeError("diagnostic MCP reported a tool error")
        structured_content = result.get("structuredContent")
        if not isinstance(structured_content, Mapping):
            raise RuntimeError("diagnostic MCP structured result is invalid")
        return dict(structured_content)


class FormOwlDocumentMcpHttpClient:
    """Bounded client for the packet-local authorized-document MCP."""

    def __init__(
        self,
        endpoint_url: str,
        *,
        timeout_seconds: float = _DEFAULT_DIAGNOSTIC_MCP_TIMEOUT_SECONDS,
    ) -> None:
        self._endpoint_url = _validated_diagnostic_mcp_url(endpoint_url)
        self._timeout_seconds = _validated_diagnostic_mcp_timeout(timeout_seconds)
        self._opener = build_opener(_NoRedirectHandler())

    def read_authorized_documents(
        self,
        *,
        request: Any,
    ) -> Mapping[str, Any]:
        normalized_request = _validated_evidence_tool_request(request)
        request_id = f"uat_document_{secrets.token_hex(12)}"
        request_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": "read_authorized_documents",
                "arguments": {
                    "query_text": normalized_request.query_text,
                    "required_terms": list(normalized_request.required_terms),
                    "limit": min(normalized_request.limit, 30),
                },
            },
        }
        request_body = json.dumps(
            request_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        http_request = Request(
            self._endpoint_url,
            data=request_body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with self._opener.open(
                http_request,
                timeout=self._timeout_seconds,
            ) as response:
                if response.getcode() != HTTPStatus.OK:
                    raise RuntimeError("document MCP returned an unexpected HTTP status")
                body = response.read(_MAX_DIAGNOSTIC_MCP_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError("document MCP request failed") from exc
        if len(body) > _MAX_DIAGNOSTIC_MCP_RESPONSE_BYTES:
            raise RuntimeError("document MCP response is too large")
        try:
            response_payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("document MCP response is invalid") from exc
        if (
            not isinstance(response_payload, Mapping)
            or response_payload.get("jsonrpc") != "2.0"
            or response_payload.get("id") != request_id
            or "error" in response_payload
        ):
            raise RuntimeError("document MCP response is invalid")
        result = response_payload.get("result")
        if not isinstance(result, Mapping) or result.get("isError") is True:
            raise RuntimeError("document MCP reported a tool error")
        structured_content = result.get("structuredContent")
        if not isinstance(structured_content, Mapping):
            raise RuntimeError("document MCP structured result is invalid")
        return _validated_document_mcp_payload(structured_content)


@dataclass
class _UatConversationState:
    history: list[Any]
    latest_evidence: dict[str, Any] | None = None


class MailHumanUatService:
    """Shared human UAT facade over the governed mail evidence query gateway."""

    def __init__(
        self,
        config: MailHumanUatHttpConfig,
        *,
        base_gateway: MailEvidenceQueryGateway | None = None,
        diagnostic_mcp_client: DiagnosticMcpClient | None = None,
        document_mcp_client: DocumentMcpClient | None = None,
    ) -> None:
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
        _validated_diagnostic_mcp_timeout(config.diagnostic_mcp_timeout_seconds)
        if config.diagnostic_mcp_url is not None:
            _validated_diagnostic_mcp_url(config.diagnostic_mcp_url)
        if config.document_mcp_url is not None:
            _validated_diagnostic_mcp_url(config.document_mcp_url)
        if config.diagnostic_mcp_url is not None and config.document_mcp_url is not None:
            raise ContractValidationError("UAT MCP modes are mutually exclusive")
        self._document_first = (
            config.document_mcp_url is not None or document_mcp_client is not None
        )
        if self._document_first:
            if config.bundle is not None or base_gateway is not None:
                raise ContractValidationError("document-first UAT must not load mail evidence")
        else:
            _load_legacy_runtime()
            if (
                config.bundle is None
                or not config.bundle.messages
                or not config.bundle.body_segments
            ):
                raise ContractValidationError("UAT mail evidence bundle must contain messages")
            safe_public_string(config.bundle.mail_evidence_bundle_id, "mail_evidence_bundle_id")
            config.bundle.mail_import_session.to_dict()
        self.config = config
        self._diagnostic_mcp_client = diagnostic_mcp_client or (
            FormOwlDiagnosticMcpHttpClient(
                config.diagnostic_mcp_url,
                timeout_seconds=config.diagnostic_mcp_timeout_seconds,
            )
            if config.diagnostic_mcp_url is not None
            else None
        )
        self._document_mcp_client = document_mcp_client or (
            FormOwlDocumentMcpHttpClient(
                config.document_mcp_url,
                timeout_seconds=config.diagnostic_mcp_timeout_seconds,
            )
            if config.document_mcp_url is not None
            else None
        )
        if self._document_first:
            self._base_gateway = None
            self._base_message_by_source_item = {}
        else:
            assert config.bundle is not None
            resolved_base_gateway = base_gateway or MailEvidenceQueryGateway([config.bundle])
            if resolved_base_gateway.mail_evidence_bundle_ids != (
                config.bundle.mail_evidence_bundle_id,
            ):
                raise ContractValidationError("UAT base gateway does not match its bundle")
            self._base_gateway = resolved_base_gateway
            base_session_id = config.bundle.mail_import_session.mail_import_session_id
            self._base_message_by_source_item = {
                (base_session_id, message.email_message_id): message
                for message in config.bundle.messages
            }
        self._event_store = _PrivateUatEventStore(
            config.state_dir,
            retention_days=config.event_retention_days,
            max_bytes=config.max_event_store_bytes,
            fixed_now=config.fixed_now,
        )
        self._known_query_ids: set[str] = set()
        self._verdict_counts: Counter[str] = Counter()
        self._interaction_counts: Counter[str] = Counter()
        self._anonymous_visitor_ids: set[str] = set()
        self._anonymous_session_ids: set[str] = set()
        self._task_frames_by_conversation_id: dict[str, TaskFrame] = {}
        self._conversation_states_by_conversation_id: dict[str, _UatConversationState] = {}
        self._conversation_turn_locks: dict[str, threading.Lock] = {}
        self._query_count = 0
        self._chat_count = 0
        self._formowl_tool_call_count = 0
        self._formowl_mcp_attempted_call_count = 0
        self._formowl_mcp_successful_call_count = 0
        self._latest_mcp_response_commitment: str | None = None
        self._latest_tool_result_reinject_commitment: str | None = None
        self._latest_final_response_commitment: str | None = None
        self._feedback_count = 0
        self._lock = threading.RLock()
        self.started_at = _timestamp(config.fixed_now)
        if self._document_first:
            self._uploaded_content_hashes = set()
            self._uploaded_resource_count = 0
            self._uploaded_bundles = []
            self._uploaded_warnings = Counter()
            self._uploaded_message_ids = frozenset()
            self._all_bundles = ()
            return
        self._upload_store = PrivateUatMailUploadStore(
            config.state_dir,
            max_file_bytes=config.max_upload_file_bytes,
        )
        assert config.bundle is not None
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
            "surface": ("document_first_human_uat" if self._document_first else "mail_human_uat"),
            "chatgpt_bypassed": True,
            "authentication_required": False,
            "shared_uat": True,
            "behavior_capture_enabled": True,
            "behavior_capture_scope": "submitted_questions_and_bounded_interactions",
            "behavior_capture_retention_days": self.config.event_retention_days,
            "conversation_orchestrator_enabled": self.config.conversation_model is not None,
            "conversation_model": (
                self.config.conversation_model.model_name
                if self.config.conversation_model is not None
                else None
            ),
            "upload_required": False,
            "upload_supported": not self._document_first,
            "uploaded_file_count": uploaded_file_count,
            "read_only_business_systems": True,
            "index_build_mode": (
                "authorized_document_snapshot"
                if self._document_first
                else self._base_gateway.index_build_mode
            ),
            "index_worker_count": (
                0 if self._document_first else self._base_gateway.index_worker_count
            ),
            "index_build_elapsed_ms": (
                0.0 if self._document_first else self._base_gateway.index_build_elapsed_ms
            ),
            "document_first": self._document_first,
        }
        assert_public_payload_safe(payload, "mail_human_uat_health")
        return payload

    def chat(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        _expect_exact_keys(payload, _CHAT_KEYS, required={"query_text"})
        user_text = _validated_text(
            payload.get("query_text"),
            "query_text",
            max_chars=_MAX_QUERY_CHARS,
        )
        source = payload.get("source", "api")
        if source not in _QUERY_SOURCES:
            raise ContractValidationError("chat source is invalid")
        # Persistent Codex threads must always be bound to one browser-created
        # visitor/session pair. Falling back to a shared anonymous identifier
        # would mix unrelated testers' conversation history.
        tracking = _validated_tracking_fields(payload, required=True)
        model = self.config.conversation_model
        if model is None:
            raise RuntimeError("UAT conversation orchestrator is not configured")

        query_id = f"uatquery_{secrets.token_hex(12)}"
        submitted_at = _timestamp(self.config.fixed_now)
        self._event_store.append(
            {
                "event_type": "chat",
                "created_at": submitted_at,
                "query_id": query_id,
                "query_text": user_text,
                "query_hash": sha256_json(user_text),
                "source": source,
                **tracking,
            }
        )
        with self._lock:
            self._known_query_ids.add(query_id)
            self._chat_count += 1
            self._remember_tracking(tracking)

        conversation_id = _conversation_safety_identifier(tracking)
        turn_lock = self._conversation_turn_lock(conversation_id)
        with turn_lock:
            with self._lock:
                state = self._conversation_states_by_conversation_id.get(conversation_id)
                history = tuple(state.history) if state is not None else ()
                latest_evidence = (
                    dict(state.latest_evidence)
                    if state is not None and state.latest_evidence is not None
                    else None
                )
                model_history = () if self._document_first else history

            tool_request_count = 0
            semantic_mcp_call_count = 0
            turn_attempted_mcp_call_count = 0
            turn_successful_mcp_call_count = 0

            def call_formowl_tool(
                request: Any,
                *,
                timeout_seconds: float | None = None,
            ) -> Mapping[str, Any]:
                nonlocal semantic_mcp_call_count, tool_request_count
                nonlocal turn_attempted_mcp_call_count
                nonlocal turn_successful_mcp_call_count
                tool_request_count += 1
                with self._lock:
                    self._formowl_mcp_attempted_call_count += 1
                turn_attempted_mcp_call_count += 1
                if isinstance(request, Mapping):
                    if self._document_first:
                        raise ContractValidationError(
                            "document-first UAT accepts only document tool requests"
                        )
                    if semantic_mcp_call_count:
                        raise ContractValidationError(
                            "a semantic UAT query may call FormOwl MCP only once"
                        )
                    if tool_request_count != 1:
                        raise ContractValidationError(
                            "semantic UAT queries may not mix tool request types"
                        )
                    semantic_mcp_call_count += 1
                    result = self._execute_semantic_mcp_query(
                        query_text=user_text,
                        semantic_request=request,
                        tracking=tracking,
                        parent_query_id=query_id,
                    )
                else:
                    normalized_request = _validated_evidence_tool_request(request)
                    if self._document_first:
                        client = self._document_mcp_client
                        if client is None:
                            raise ContractValidationError(
                                "document-first UAT requires a document MCP client"
                            )
                        result = _validated_document_mcp_payload(
                            client.read_authorized_documents(
                                request=normalized_request,
                            ),
                        )
                    else:
                        result = self._execute_evidence_query(
                            query_text=normalized_request.query_text,
                            limit=normalized_request.limit,
                            sort=normalized_request.sort,
                            source="orchestrator",
                            tracking=tracking,
                            required_terms=normalized_request.required_terms,
                            preserve_session_task=False,
                            parent_query_id=query_id,
                        )
                with self._lock:
                    self._formowl_mcp_successful_call_count += 1
                    self._formowl_tool_call_count += 1
                turn_successful_mcp_call_count += 1
                return result

            failure_stage = "model_response"
            try:
                chat_orchestration_started = perf_counter()
                outcome = model.respond(
                    history=model_history,
                    user_text=user_text,
                    latest_evidence=latest_evidence,
                    safety_identifier=conversation_id,
                    evidence_tool=call_formowl_tool,
                )
                if self._document_first and (
                    outcome.fallback_reason is not None
                    or not isinstance(outcome.answer_text, str)
                    or not outcome.answer_text.strip()
                ):
                    raise RuntimeError("document-first UAT requires a valid Codex synthesis")
                if self._document_first and outcome.tool_request is not None:
                    if (
                        outcome.mcp_attempted_call_count != turn_attempted_mcp_call_count
                        or outcome.mcp_successful_call_count != turn_successful_mcp_call_count
                    ):
                        raise RuntimeError("document-first MCP call counts are inconsistent")
                chat_orchestration_ms = (perf_counter() - chat_orchestration_started) * 1000.0
                failure_stage = "response_assembly"
                response = self._chat_response(
                    query_id=query_id,
                    user_text=user_text,
                    outcome=outcome,
                    latest_evidence=latest_evidence,
                    chat_orchestration_ms=chat_orchestration_ms,
                )
                failure_stage = "semantic_telemetry_persistence"
                self._append_semantic_stage_telemetry(
                    outcome.semantic_telemetry,
                    created_at=response["generated_at"],
                )
                failure_stage = "result_persistence"
                self._event_store.append(
                    {
                        "event_type": "chat_result",
                        "created_at": response["generated_at"],
                        "query_id": query_id,
                        "orchestration_action": response["orchestration"]["action"],
                        "model": outcome.model_name,
                        "formowl_tool_called": outcome.tool_request is not None,
                        **_tool_request_event_metadata(outcome.tool_request),
                        "tool_result_count": response["result_count"],
                        "assistant_response_hash": sha256_json(outcome.answer_text),
                        "answer_fallback_used": outcome.fallback_reason is not None,
                        "fallback_reason": outcome.fallback_reason,
                        **tracking,
                    }
                )

                failure_stage = "conversation_state_commit"
                with self._lock:
                    if outcome.mcp_successful_call_count:
                        self._latest_mcp_response_commitment = outcome.mcp_response_commitment
                        self._latest_tool_result_reinject_commitment = (
                            outcome.tool_result_reinject_commitment
                        )
                        self._latest_final_response_commitment = outcome.final_response_commitment
                    state = self._conversation_states_by_conversation_id.setdefault(
                        conversation_id,
                        _UatConversationState(history=[]),
                    )
                    if not self._document_first:
                        state.history.extend(
                            (
                                UatConversationMessage(role="user", content=user_text),
                                UatConversationMessage(
                                    role="assistant",
                                    content=outcome.answer_text,
                                ),
                            )
                        )
                        del state.history[:-_MAX_CHAT_HISTORY_MESSAGES]
                    if outcome.tool_result is not None and not self._document_first:
                        state.latest_evidence = dict(outcome.tool_result)
            except Exception as exc:
                try:
                    model.discard_conversation(conversation_id)
                except Exception:
                    pass
                try:
                    self._event_store.append(
                        {
                            "event_type": "chat_error",
                            "created_at": _timestamp(self.config.fixed_now),
                            "query_id": query_id,
                            "model": model.model_name,
                            "failure_stage": failure_stage,
                            "failure_type": type(exc).__name__,
                        }
                    )
                except Exception:
                    pass
                raise
        return response

    def _append_semantic_stage_telemetry(
        self,
        records: Sequence[Any],
        *,
        created_at: str,
    ) -> None:
        """Persist only hash-and-count semantic diagnostics, never turn content."""

        for record in records:
            to_dict = getattr(record, "to_dict", None)
            if not callable(to_dict):
                raise ContractValidationError("semantic telemetry record is invalid")
            payload = to_dict()
            if not isinstance(payload, Mapping) or set(payload) != {
                "stage",
                "reason_code",
                "input_hash",
                "attempt_count",
                "public_term_count",
                "completed_web_search_count",
            }:
                raise ContractValidationError("semantic telemetry payload is invalid")
            self._event_store.append(
                {
                    "event_type": "semantic_stage_telemetry",
                    "created_at": created_at,
                    **dict(payload),
                }
            )

    def query(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self._document_first:
            raise ContractValidationError("document-first UAT exposes chat only")
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
        return self._execute_evidence_query(
            query_text=query_text,
            limit=limit,
            sort=sort,
            source=source,
            tracking=tracking,
        )

    def _execute_semantic_mcp_query(
        self,
        *,
        query_text: str,
        semantic_request: Mapping[str, Any],
        tracking: Mapping[str, Any],
        parent_query_id: str,
    ) -> dict[str, Any]:
        """Execute one typed semantic request through the FormOwl MCP boundary."""

        normalized_request = validate_semantic_request(semantic_request)
        client = self._diagnostic_mcp_client
        if client is None:
            raise ContractValidationError("semantic UAT requires a diagnostic MCP client")
        started = perf_counter()
        mcp_payload = client.query_effective_graph_view(
            query_text=query_text,
            semantic_request=normalized_request,
        )
        response = _semantic_mcp_payload_to_uat_response(
            payload=mcp_payload,
            semantic_request=normalized_request,
            query_id=parent_query_id,
            query_text=query_text,
            fixed_now=self.config.fixed_now,
            timings_ms={
                "formowl_orchestration": round((perf_counter() - started) * 1000.0, 3),
            },
        )
        self._event_store.append(
            {
                "event_type": "semantic_mcp_result",
                "created_at": response["generated_at"],
                "query_id": parent_query_id,
                "semantic_request_hash": sha256_json(normalized_request),
                "mcp_tool_name": "query_effective_graph_view",
                "mcp_call_count": 1,
                "mcp_status": response["status"],
                "result_count": response["result_count"],
                "answerability_status": response["answerability"]["status"],
                "timings_ms": response["timings_ms"],
                **tracking,
            }
        )
        return response

    def _execute_evidence_query(
        self,
        *,
        query_text: str,
        limit: int,
        sort: str,
        source: str,
        tracking: Mapping[str, Any],
        required_terms: Sequence[str] = (),
        preserve_session_task: bool = True,
        parent_query_id: str | None = None,
    ) -> dict[str, Any]:
        formowl_orchestration_started = perf_counter()
        normalized_required_terms = _normalized_required_terms(required_terms)
        conversation_id = None
        if (
            preserve_session_task
            and isinstance(tracking.get("visitor_id"), str)
            and isinstance(tracking.get("session_id"), str)
        ):
            conversation_id = _conversation_safety_identifier(tracking)
        with self._lock:
            prior_task_frame = (
                self._task_frames_by_conversation_id.get(conversation_id)
                if conversation_id is not None
                else None
            )
        task_frame, changed_dimensions = _resolve_task_frame(
            query_text,
            page_size=limit,
            prior=prior_task_frame,
        )
        if conversation_id is not None:
            with self._lock:
                self._task_frames_by_conversation_id[conversation_id] = task_frame
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
                "parent_query_id": parent_query_id,
                "required_term_hashes": [sha256_json(term) for term in normalized_required_terms],
                **tracking,
            }
        )
        with self._lock:
            self._known_query_ids.add(query_id)
            self._query_count += 1
            self._remember_tracking(tracking)

        bundle = self.config.bundle
        actor = bundle.mail_import_session
        with self._lock:
            all_bundles = self._all_bundles
        retrieval_candidate_limit = max(
            1,
            sum(_logical_source_count(candidate_bundle) for candidate_bundle in all_bundles),
        )
        base_execution = self._base_gateway.execute_mail_evidence_query(
            query_text=task_frame.retrieval_query_text,
            requester_user_id=actor.owner_user_id,
            workspace_id=actor.workspace_id,
            session_id="session_mail_human_uat",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=retrieval_candidate_limit,
            now=self.config.fixed_now,
            required_terms=normalized_required_terms,
            snippet_filter_groups=(),
            collapse_source_items=True,
        )
        with self._lock:
            upload_gateway = self._upload_gateway
            message_by_source_item = self._message_by_source_item
            uploaded_message_ids = self._uploaded_message_ids
            uploaded_bundle_ids = self._uploaded_bundle_ids
            uploaded_file_count = self._uploaded_resource_count
        gateway_executions = [base_execution]
        if upload_gateway is not None:
            gateway_executions.extend(
                upload_gateway.execute_mail_evidence_query(
                    query_text=task_frame.retrieval_query_text,
                    requester_user_id=actor.owner_user_id,
                    workspace_id=actor.workspace_id,
                    session_id="session_mail_human_uat",
                    mail_evidence_bundle_id=bundle_id,
                    limit=retrieval_candidate_limit,
                    now=self.config.fixed_now,
                    required_terms=normalized_required_terms,
                    snippet_filter_groups=(),
                    collapse_source_items=True,
                )
                for bundle_id in uploaded_bundle_ids
            )
        gateway_results = [execution.result.to_dict() for execution in gateway_executions]
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

        citations_by_source = {
            (
                citation.get("mail_import_session_id"),
                citation["source_observation_id"],
            ): citation
            for citation in citations
        }
        results: list[dict[str, Any]] = []
        for snippet in evidence_snippets:
            email_message_id = str(snippet.get("email_message_id", ""))
            source_item_key = (
                str(snippet.get("mail_import_session_id", "")),
                email_message_id,
            )
            message = message_by_source_item.get(source_item_key)
            subject = str(snippet.get("subject") or "（無主旨）")
            snippet_text = str(snippet.get("snippet", ""))
            matched_terms = [
                term for term in snippet.get("matched_terms", []) if isinstance(term, str) and term
            ]
            supporting_evidence: list[dict[str, Any]] = []
            for support in snippet.get("supporting_evidence", ()):
                if not isinstance(support, Mapping):
                    continue
                matched_required_terms = [
                    term
                    for term in support.get("matched_required_terms", ())
                    if isinstance(term, str) and term
                ]
                support_citation = support.get("citation")
                if not isinstance(support_citation, Mapping):
                    support_citation = citations_by_source.get(
                        (
                            support.get("mail_import_session_id"),
                            str(support.get("source_observation_id", "")),
                        )
                    )
                supporting_evidence.append(
                    {
                        "snippet": _context_window(
                            str(support.get("snippet", "")),
                            needles=tuple(matched_required_terms),
                        ),
                        "matched_required_terms": matched_required_terms,
                        "citation": _public_citation(support_citation),
                        "content_redacted": bool(support.get("content_redacted", False)),
                    }
                )
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
                    citations_by_source.get(
                        (
                            snippet.get("mail_import_session_id"),
                            str(snippet.get("source_observation_id", "")),
                        )
                    )
                ),
                "content_redacted": bool(snippet.get("content_redacted", False)),
                "source_kind": (
                    "uploaded_uat" if email_message_id in uploaded_message_ids else "preloaded"
                ),
                "_source_item_id": source_item_key,
            }
            if supporting_evidence:
                result["supporting_evidence"] = supporting_evidence
                result["supporting_citations"] = [
                    item["citation"]
                    for item in supporting_evidence
                    if item.get("citation") is not None
                ]
            results.append(result)

        results = _deduplicate_results(results)
        ranking_started = perf_counter()
        if sort == "recent":
            results.sort(
                key=lambda item: (
                    _timestamp_sort_key(item.get("sent_at")),
                    int(item["score"]),
                    len(item.get("matched_terms", ())),
                    str(item.get("citation", {}).get("source_observation_id", "")),
                ),
                reverse=True,
            )
        else:
            results.sort(
                key=lambda item: (
                    int(item["score"]),
                    len(item.get("matched_terms", ())),
                    _timestamp_sort_key(item.get("sent_at")),
                    str(item.get("citation", {}).get("source_observation_id", "")),
                ),
                reverse=True,
            )
        uat_ranking_ms = (perf_counter() - ranking_started) * 1000.0
        total_result_count = len(results)
        displayed_results = results[:limit]
        for result in displayed_results:
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
        has_visible_gateway_result = any(
            gateway_result["status"] == "ok" for gateway_result in gateway_results
        )
        if normalized_required_terms and not displayed_results and has_visible_gateway_result:
            warnings.append("required_terms_no_exact_match")
        if not displayed_results and "no_visible_mail_evidence_matched" not in warnings:
            warnings.append("no_visible_mail_evidence_matched")
        display_has_more = total_result_count > len(displayed_results)
        response_status = "ok" if has_visible_gateway_result else gateway_results[0]["status"]
        if displayed_results:
            answerability_status = "sufficient_evidence"
            answerability_reason_codes = ["evidence_requirement_satisfied"]
        elif response_status == "permission_denied":
            answerability_status = "permission_denied"
            answerability_reason_codes = ["permission_denied"]
        elif response_status == "not_found":
            answerability_status = "source_not_found"
            answerability_reason_codes = ["source_not_found"]
        else:
            answerability_status = "target_not_found"
            answerability_reason_codes = ["no_matching_target"]
        timings_ms = {
            "posting_retrieval": round(
                sum(execution.timings_ms["posting_retrieval"] for execution in gateway_executions),
                3,
            ),
            "exact_verification": round(
                sum(execution.timings_ms["exact_verification"] for execution in gateway_executions),
                3,
            ),
            "ranking": round(
                uat_ranking_ms
                + sum(execution.timings_ms["ranking"] for execution in gateway_executions),
                3,
            ),
            "formowl_orchestration": round(
                (perf_counter() - formowl_orchestration_started) * 1000.0,
                3,
            ),
        }
        response = {
            "status": response_status,
            "query_id": query_id,
            "query_hash": query_hash,
            "generated_at": generated_at,
            "sort": sort,
            "result_count": len(displayed_results),
            "total_result_count": total_result_count,
            "displayed_result_count": len(displayed_results),
            "results": displayed_results,
            "warnings": sorted(set(warnings)),
            "notice": "答案優先；來源內容可按需查看。",
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
                "has_more": False,
            },
            "answerability": {
                "status": answerability_status,
                "reason_codes": answerability_reason_codes,
            },
            "projection": {
                "output_format": task_frame.projection.output_format,
                "primary_fields": list(task_frame.projection.primary_fields),
                "secondary_fields": list(task_frame.projection.secondary_fields),
                "page_size": task_frame.projection.page_size,
                "page_offset": task_frame.projection.page_offset,
                "has_more": display_has_more,
            },
            "timings_ms": timings_ms,
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
        assert_authorized_evidence_payload_safe(
            response,
            "mail_human_uat_query_response",
        )
        self._event_store.append(
            {
                "event_type": "query_result",
                "created_at": generated_at,
                "query_id": query_id,
                "result_count": len(displayed_results),
                "total_result_count": total_result_count,
                "has_more": display_has_more,
                "answerability_status": answerability_status,
                "citation_ids": [
                    item["citation"]["citation_id"]
                    for item in displayed_results
                    if item.get("citation")
                ],
                "has_uploaded_result": any(
                    item["source_kind"] == "uploaded_uat" for item in displayed_results
                ),
                "timings_ms": timings_ms,
            }
        )
        return response

    def _conversation_turn_lock(self, conversation_id: str) -> threading.Lock:
        with self._lock:
            return self._conversation_turn_locks.setdefault(
                conversation_id,
                threading.Lock(),
            )

    def _chat_response(
        self,
        *,
        query_id: str,
        user_text: str,
        outcome: UatConversationOutcome,
        latest_evidence: Mapping[str, Any] | None,
        chat_orchestration_ms: float,
    ) -> dict[str, Any]:
        if outcome.tool_request is not None:
            if outcome.response_kind != "answer":
                raise RuntimeError("UAT tool calls must end in an answer")
            evidence = dict(outcome.tool_result or {})
            if (
                isinstance(outcome.tool_request, Mapping)
                and evidence.get("status") == "clarification_required"
            ):
                action = "clarify"
            else:
                action = "call_formowl_tool"
        elif outcome.response_kind == "render_prior_evidence":
            if latest_evidence is None:
                raise RuntimeError("UAT model requested missing prior evidence")
            action = "render_prior_evidence"
            evidence = dict(latest_evidence)
        elif outcome.response_kind == "clarification":
            action = "clarify"
            evidence = {}
        else:
            action = "answer_without_tool"
            evidence = {}

        if self._document_first and evidence:
            evidence = project_document_uat_payload_public(evidence)
        results = evidence.get("results", [])
        if not isinstance(results, list):
            raise RuntimeError("UAT evidence results are invalid")
        results = [dict(item) for item in results if isinstance(item, Mapping)]
        answer_items = evidence.get("answer_items", [])
        if self._document_first and "answer_items" in evidence:
            raise RuntimeError("document MCP must not return answer items")
        if not isinstance(answer_items, list) or any(
            not isinstance(item, str) or not item.strip() for item in answer_items
        ):
            raise RuntimeError("UAT answer items are invalid")
        answer_items = list(answer_items)
        projection = evidence.get("projection", {})
        projection = dict(projection) if isinstance(projection, Mapping) else {}
        result_count = evidence.get("result_count", len(results))
        total_result_count = evidence.get("total_result_count", len(results))
        displayed_result_count = evidence.get("displayed_result_count", len(results))
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (result_count, total_result_count, displayed_result_count)
        ):
            raise RuntimeError("UAT evidence result counts are invalid")
        if evidence:
            projection["output_format"] = (
                _requested_projection_format(user_text)
                or projection.get("output_format")
                or "narrative"
            )
        timings_ms = dict(evidence.get("timings_ms", {}))
        timings_ms["chat_orchestration"] = round(chat_orchestration_ms, 3)
        warnings = list(evidence.get("warnings", []))
        if outcome.fallback_reason is not None:
            warnings.append("codex_answer_fallback_used")
        answer_text = outcome.answer_text
        if isinstance(outcome.tool_request, Mapping):
            answer_text = _semantic_mcp_assistant_text(
                status=str(evidence.get("status", "")),
                fallback=answer_text,
            )
        assistant_text, assistant_redaction_count = redact_authorized_evidence_text(answer_text)
        if assistant_redaction_count:
            warnings.append("unsafe_mail_evidence_content_redacted")
        generated_at = _timestamp(self.config.fixed_now)
        response = {
            "status": str(evidence.get("status", "ok")),
            **(
                {"document_payload_projection": evidence["document_payload_projection"]}
                if self._document_first and evidence
                else {}
            ),
            "query_id": query_id,
            "query_hash": sha256_json(user_text),
            "generated_at": generated_at,
            "assistant_text": assistant_text,
            "sort": evidence.get("sort"),
            "result_count": result_count,
            "total_result_count": total_result_count,
            "displayed_result_count": displayed_result_count,
            "results": results,
            "answer_items": answer_items,
            "warnings": sorted(set(warnings)),
            "notice": evidence.get("notice"),
            "task_frame": dict(evidence.get("task_frame", {})),
            "coverage": dict(evidence.get("coverage", {})),
            "answerability": dict(evidence.get("answerability", {})),
            "projection": projection,
            "timings_ms": timings_ms,
            "orchestration": {
                "action": action,
                "response_kind": outcome.response_kind,
                "model": outcome.model_name,
                "formowl_tool_called": outcome.tool_request is not None,
                "answer_fallback_used": outcome.fallback_reason is not None,
                "tool_name": _tool_request_event_metadata(outcome.tool_request)["tool_name"],
                "mcp_attempted_call_count": outcome.mcp_attempted_call_count,
                "mcp_successful_call_count": outcome.mcp_successful_call_count,
                "mcp_response_commitment": outcome.mcp_response_commitment,
                "tool_result_reinject_commitment": (outcome.tool_result_reinject_commitment),
                "final_response_commitment": outcome.final_response_commitment,
            },
            "claim_boundary": dict(evidence.get("claim_boundary", {})),
        }
        assert_authorized_evidence_payload_safe(
            response,
            "mail_human_uat_chat_response",
        )
        return response

    def upload_mail_files(
        self,
        files: Sequence[UatUploadedResourcePart],
    ) -> dict[str, Any]:
        if self._document_first:
            raise ContractValidationError("document-first UAT does not accept uploads")
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
        message_by_source_item = dict(self._base_message_by_source_item)
        uploaded_message_ids: set[str] = set()
        for bundle in resolved_bundles:
            session_id = bundle.mail_import_session.mail_import_session_id
            for message in bundle.messages:
                message_by_source_item[(session_id, message.email_message_id)] = message
                uploaded_message_ids.add(message.email_message_id)
        self._message_by_source_item = message_by_source_item
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
                conversation_id = _conversation_safety_identifier(tracking)
                self._task_frames_by_conversation_id.pop(conversation_id, None)
                self._conversation_states_by_conversation_id.pop(
                    conversation_id,
                    None,
                )
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
                "chat_count": self._chat_count,
                "formowl_tool_call_count": self._formowl_tool_call_count,
                "mcp_attempted_call_count": self._formowl_mcp_attempted_call_count,
                "mcp_successful_call_count": self._formowl_mcp_successful_call_count,
                "mcp_response_commitment": self._latest_mcp_response_commitment,
                "tool_result_reinject_commitment": (self._latest_tool_result_reinject_commitment),
                "final_response_commitment": self._latest_final_response_commitment,
                "feedback_count": self._feedback_count,
                "interaction_count": sum(self._interaction_counts.values()),
                "interaction_counts": dict(sorted(self._interaction_counts.items())),
                "anonymous_visitor_count": len(self._anonymous_visitor_ids),
                "anonymous_session_count": len(self._anonymous_session_ids),
                "verdict_counts": {
                    verdict: self._verdict_counts.get(verdict, 0) for verdict in sorted(_VERDICTS)
                },
                "upload_supported": not self._document_first,
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
                "/api/chat",
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
                    if service._document_first:
                        service.upload_mail_files(())
                    files = self._read_upload_files()
                    response = service.upload_mail_files(files)
                    self._send_json(HTTPStatus.CREATED, response)
                    return
                payload = self._read_json_body()
                if route == "/api/chat":
                    response = service.chat(payload)
                elif route == "/api/query":
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


def _create_shared_mail_human_uat_http_server(
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


def _validated_diagnostic_mcp_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ContractValidationError("diagnostic MCP URL is invalid")
    parsed = urlparse(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ContractValidationError("diagnostic MCP URL is invalid")
    return value.strip()


def _validated_diagnostic_mcp_timeout(value: float) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
        or value > _MAX_DIAGNOSTIC_MCP_TIMEOUT_SECONDS
    ):
        raise ContractValidationError("diagnostic MCP timeout is invalid")
    return float(value)


def _validated_document_mcp_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("document_payload_projection") is not None:
        raise ContractValidationError("document MCP payload is invalid")
    return validate_document_uat_payload(payload)


def _validated_evidence_tool_request(value: Any) -> _NormalizedEvidenceToolRequest:
    if isinstance(value, Mapping):
        raise ContractValidationError("UAT evidence tool request is invalid")
    try:
        query_text = value.query_text
        required_terms = value.required_terms
        sort = value.sort
        limit = value.limit
    except AttributeError as exc:
        raise ContractValidationError("UAT evidence tool request is invalid") from exc
    if (
        not isinstance(query_text, str)
        or not query_text.strip()
        or len(query_text) > _MAX_QUERY_CHARS
    ):
        raise ContractValidationError("UAT evidence tool query is invalid")
    if sort not in _SORT_OPTIONS:
        raise ContractValidationError("UAT evidence tool sort is invalid")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
        or limit > _MAX_RESULT_LIMIT
    ):
        raise ContractValidationError("UAT evidence tool limit is invalid")
    if (
        not isinstance(required_terms, Sequence)
        or isinstance(required_terms, (str, bytes, bytearray))
        or len(required_terms) > 12
    ):
        raise ContractValidationError("UAT evidence required terms are invalid")
    normalized_terms: list[str] = []
    seen_terms: set[str] = set()
    for term in required_terms:
        if not isinstance(term, str) or not term.strip() or len(term) > 120:
            raise ContractValidationError("UAT evidence required term is invalid")
        folded = term.casefold()
        if folded in seen_terms:
            raise ContractValidationError("UAT evidence required terms must be unique")
        seen_terms.add(folded)
        normalized_terms.append(term)
    return _NormalizedEvidenceToolRequest(
        query_text=query_text,
        required_terms=tuple(normalized_terms),
        sort=sort,
        limit=limit,
    )


def _tool_request_event_metadata(
    tool_request: Any,
) -> dict[str, Any]:
    if tool_request is None:
        return {
            "tool_name": None,
            "tool_query_hash": None,
            "required_term_hashes": [],
            "semantic_request_hash": None,
        }
    if isinstance(tool_request, Mapping):
        normalized = validate_semantic_request(tool_request)
        return {
            "tool_name": "query_effective_graph_view",
            "tool_query_hash": None,
            "required_term_hashes": [],
            "semantic_request_hash": sha256_json(normalized),
        }
    normalized = _validated_evidence_tool_request(tool_request)
    return {
        "tool_name": "search_formowl_evidence",
        "tool_query_hash": sha256_json(normalized.query_text),
        "required_term_hashes": [sha256_json(term) for term in normalized.required_terms],
        "semantic_request_hash": None,
    }


def _semantic_mcp_payload_to_uat_response(
    *,
    payload: Mapping[str, Any],
    semantic_request: Mapping[str, Any],
    query_id: str,
    query_text: str,
    fixed_now: str | None,
    timings_ms: Mapping[str, float],
) -> dict[str, Any]:
    """Project a safe complete-set MCP result without source/citation walls."""

    normalized_request = validate_semantic_request(semantic_request)
    if not isinstance(payload, Mapping):
        raise ContractValidationError("diagnostic MCP semantic result is invalid")
    status = payload.get("status")
    if status not in {"ok", "clarification_required", "insufficient", "permission_denied"}:
        raise ContractValidationError("diagnostic MCP semantic status is invalid")
    complete_projection = payload.get("complete_projection")
    if not isinstance(complete_projection, Mapping):
        raise ContractValidationError("diagnostic MCP semantic projection is invalid")
    projection_state = complete_projection.get("state")
    values = complete_projection.get("values")
    if projection_state not in {
        "complete",
        "not_available",
        "result_budget_exceeded",
        "projection_unavailable",
    } or not isinstance(values, list):
        raise ContractValidationError("diagnostic MCP semantic projection is invalid")
    if status == "ok" and projection_state != "complete":
        raise ContractValidationError("diagnostic MCP semantic projection is incomplete")
    if status != "ok" and values:
        raise ContractValidationError("diagnostic MCP semantic projection is invalid")

    answer_items: list[str] = []
    answer_item_redacted = False
    for item in values:
        if not isinstance(item, Mapping) or set(item) != {"values"}:
            raise ContractValidationError("diagnostic MCP semantic result item is invalid")
        item_values = item["values"]
        if (
            not isinstance(item_values, list)
            or not item_values
            or any(
                not isinstance(value, str) or not value.strip() or len(value) > _MAX_QUERY_CHARS
                for value in item_values
            )
        ):
            raise ContractValidationError("diagnostic MCP semantic result item is invalid")
        rendered_value, redaction_count = redact_authorized_evidence_text("／".join(item_values))
        answer_items.append(rendered_value)
        answer_item_redacted = answer_item_redacted or bool(redaction_count)

    display_pagination = payload.get("display_pagination")
    if not isinstance(display_pagination, Mapping):
        raise ContractValidationError("diagnostic MCP semantic pagination is invalid")
    page_size = display_pagination.get("page_size")
    page_number = display_pagination.get("page_number")
    displayed_count = display_pagination.get("displayed_count")
    has_more = display_pagination.get("has_more")
    if (
        page_size != normalized_request["page_size"]
        or page_number != normalized_request["page_number"]
        or not isinstance(displayed_count, int)
        or isinstance(displayed_count, bool)
        or displayed_count < 0
        or displayed_count != len(answer_items)
        or not isinstance(has_more, bool)
    ):
        raise ContractValidationError("diagnostic MCP semantic pagination is invalid")
    if status == "ok" and has_more:
        raise ContractValidationError("semantic all-matching response must be complete")

    if status == "ok":
        answerability_status = "sufficient_evidence"
        reason_codes = ["evidence_requirement_satisfied"]
        warnings: list[str] = []
        notice = "已完成完整符合條件集合；來源可依需求另外要求。"
    elif status == "clarification_required":
        answerability_status = "clarification_required"
        reason_codes = ["semantic_grounding_ambiguous"]
        warnings = ["semantic_clarification_required"]
        notice = "需要更明確的條件後才能安全查詢。"
    elif status == "permission_denied":
        answerability_status = "permission_denied"
        reason_codes = ["permission_denied"]
        warnings = ["semantic_permission_denied"]
        notice = "目前沒有足夠權限查詢這個範圍。"
    else:
        answerability_status = "insufficient_evidence"
        reason_codes = ["insufficient_complete_scope"]
        warnings = ["semantic_insufficient_evidence"]
        notice = "目前無法確認完整的可查詢範圍，因此不會提供不完整答案。"

    generated_at = _timestamp(fixed_now)
    response = {
        "status": status,
        "query_id": query_id,
        "query_hash": sha256_json(query_text),
        "generated_at": generated_at,
        "sort": None,
        "result_count": len(answer_items),
        "total_result_count": len(answer_items),
        "displayed_result_count": len(answer_items),
        # These are answer values, not evidence-source rows.  The browser
        # renders them immediately as a readable answer list.
        "answer_items": answer_items,
        "results": [],
        "warnings": sorted(
            {
                *warnings,
                *({"unsafe_mail_evidence_content_redacted"} if answer_item_redacted else set()),
            }
        ),
        "notice": notice,
        "task_frame": {},
        "coverage": {
            "cardinality_mode": normalized_request["cardinality"],
            "total_source_item_count": len(answer_items),
            "returned_source_item_count": len(answer_items),
            "displayed_source_item_count": len(answer_items),
            "is_exhaustive": status == "ok",
            "has_more": False,
            "result_representation": "unique_projection_values",
        },
        "answerability": {
            "status": answerability_status,
            "reason_codes": reason_codes,
        },
        "projection": {
            "output_format": "list",
            "primary_fields": ["projection_values"],
            "secondary_fields": [],
            "page_size": page_size,
            "page_offset": (page_number - 1) * page_size,
            "has_more": has_more,
        },
        "timings_ms": dict(timings_ms),
        "claim_boundary": {
            "chatgpt_bypassed": True,
            "mail_upload_performed": False,
            "uploaded_mail_available": False,
            "read_only_mail_evidence": True,
            "project_or_wiki_write_performed": False,
            "canonical_graph_write_performed": False,
            "autonomous_business_decision": False,
            "production_ready": False,
        },
    }
    assert_authorized_evidence_payload_safe(
        response,
        "mail_human_uat_semantic_mcp_response",
    )
    return response


def _semantic_mcp_assistant_text(*, status: str, fallback: str) -> str:
    if status == "clarification_required":
        return "這個條件仍有歧義；請指定要查的項目、欄位或值。"
    if status == "permission_denied":
        return "我沒有足夠權限查詢這個範圍。"
    if status == "insufficient":
        return "目前無法確認完整的可查詢範圍，因此不會提供不完整答案。"
    return fallback


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


def _normalized_required_terms(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or len(values) > 12:
        raise ContractValidationError("required terms are invalid")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise ContractValidationError("required term is invalid")
        safe_public_string(value, "required_term")
        term = unicodedata.normalize("NFKC", value).casefold().strip()
        if not term or term in normalized:
            raise ContractValidationError("required terms must be unique")
        normalized.append(term)
    return tuple(normalized)


def _conversation_safety_identifier(tracking: Mapping[str, Any]) -> str:
    visitor_id = tracking.get("visitor_id")
    session_id = tracking.get("session_id")
    if (
        not isinstance(visitor_id, str)
        or not _VISITOR_ID_RE.fullmatch(visitor_id)
        or not isinstance(session_id, str)
        or not _SESSION_ID_RE.fullmatch(session_id)
    ):
        raise ContractValidationError("anonymous UAT tracking ids are invalid")
    digest = sha256_json(
        {
            "visitor_id": visitor_id,
            "session_id": session_id,
        }
    ).removeprefix("sha256:")
    return f"formowl_uat_{digest[:48]}"


def _logical_source_count(bundle: MailEvidenceBundle) -> int:
    """Count logical mail sources, never parser body segments."""

    return len({message.email_message_id for message in bundle.messages})


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
      display: none; width: min(1120px, calc(100% - 48px)); margin: 0 auto;
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
    .assistant-text {
      min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
    }
    .semantic-answer-list {
      display: grid; gap: 8px; margin: 14px 0 0; padding: 0; list-style: none;
    }
    .semantic-answer-item {
      display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px;
      align-items: start; border: 1px solid var(--line); border-radius: 12px;
      background: #fbfcfa; padding: 11px 13px; line-height: 1.6;
      overflow-wrap: anywhere; word-break: break-word;
    }
    .semantic-answer-order {
      color: var(--muted); font-variant-numeric: tabular-nums; font-weight: 800;
    }
    .sources-disclosure {
      display: inline-flex; align-items: center; gap: 6px; margin-top: 14px;
      padding: 7px 11px; border: 1px solid var(--line); border-radius: 999px;
      background: #fff; color: var(--muted); font-size: 13px;
    }
    .sources-disclosure:hover {
      background: var(--soft); color: var(--ink);
    }
    .sources-disclosure[aria-expanded="true"] { color: var(--ink); }
    .sources-panel { margin-top: 12px; }
    .sources-panel[hidden] { display: none; }
    .evidence-list { display: grid; gap: 10px; margin-top: 16px; }
    .evidence {
      border: 1px solid var(--line); border-radius: 14px; padding: 14px 15px;
      background: #fff;
    }
    .evidence h3 {
      margin: 0; font-size: 14px; line-height: 1.5;
      overflow-wrap: anywhere; word-break: break-word;
    }
    .evidence-meta {
      margin: 5px 0 8px; color: var(--muted); font-size: 12px;
      overflow-wrap: anywhere; word-break: break-word;
    }
    .evidence-content {
      margin: 0 0 12px; line-height: 1.65; white-space: pre-wrap;
      overflow-wrap: anywhere; word-break: break-word;
    }
    .source-order {
      display: inline-flex; min-width: 22px; height: 22px; margin-right: 8px;
      align-items: center; justify-content: center; border-radius: 999px;
      background: var(--soft); color: #555; font-size: 11px; font-weight: 700;
    }
    .supporting-content {
      margin: 9px 0 0; padding: 9px 11px; border-left: 3px solid var(--line);
      background: #fafafa; color: #444; font-size: 13px; white-space: pre-wrap;
      overflow-wrap: anywhere; word-break: break-word;
    }
    .evidence-table-wrap {
      width: 100%; margin-top: 16px; overflow: visible;
      border: 1px solid var(--line); border-radius: 14px; background: #fff;
    }
    .evidence-table {
      width: 100%; min-width: 0; border-collapse: collapse; table-layout: fixed;
    }
    .evidence-table th, .evidence-table td {
      padding: 11px 12px; border-bottom: 1px solid var(--line);
      text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;
    }
    .evidence-table th {
      background: #f7f7f7; color: #555; font-size: 12px; font-weight: 650;
    }
    .evidence-table td {
      font-size: 13px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere;
    }
    .evidence-table td::before { display: none; }
    .evidence-table th:first-child, .evidence-table td:first-child { width: 7%; }
    .evidence-table th:nth-child(2), .evidence-table td:nth-child(2) { width: 55%; }
    .evidence-table th:nth-child(3), .evidence-table td:nth-child(3) { width: 23%; }
    .evidence-table th:nth-child(4), .evidence-table td:nth-child(4) { width: 15%; }
    .evidence-table tbody tr:last-child td { border-bottom: 0; }
    .supporting-list {
      margin: 10px 0 0; padding: 9px 11px 9px 27px; border-left: 3px solid #c9d8d3;
      background: #fafafa; color: #444; overflow-wrap: anywhere; word-break: break-word;
    }
    .supporting-list li + li { margin-top: 6px; }
    .metadata-label { color: var(--muted); font-size: 12px; font-weight: 650; }
    .badge {
      display: inline-block; margin-left: 7px; padding: 2px 7px; border-radius: 999px;
      background: #e8f6f1; color: #08745a; font-size: 10px; font-weight: 650;
    }
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
    body.has-conversation.sources-reading .topbar {
      position: static; left: auto; right: auto; top: auto; z-index: auto;
      backdrop-filter: none;
    }
    body.has-conversation.sources-reading .conversation {
      padding-top: 32px; padding-bottom: 30px;
    }
    body.has-conversation.sources-reading .composer-dock {
      position: static; left: auto; right: auto; top: auto; bottom: auto; z-index: auto;
      transform: none; padding: 0 20px 24px; background: #fff;
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
      body.has-conversation .conversation {
        padding-bottom: calc(240px + env(safe-area-inset-bottom));
      }
      body.has-conversation .composer-dock {
        padding: 10px 10px calc(8px + env(safe-area-inset-bottom));
      }
      body.has-conversation.sources-reading .conversation {
        padding-top: 20px; padding-bottom: 28px;
      }
      body.has-conversation.sources-reading .composer-dock {
        padding: 0 10px calc(12px + env(safe-area-inset-bottom));
      }
      body.has-conversation .composer-note { display: none; }
      .landing-title h1 { font-size: 24px; }
      .message.user .bubble { max-width: 86%; }
      .test-badge { display: none; }
    }
    @media (max-width: 720px) {
      .conversation { width: min(100% - 20px, 768px); }
      .evidence-table-wrap {
        border: 0; background: transparent;
      }
      .evidence-table {
        display: block; table-layout: auto;
      }
      .evidence-table thead {
        position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
        overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
      }
      .evidence-table tbody { display: grid; gap: 12px; }
      .evidence-table tr {
        display: block; border: 1px solid var(--line); border-radius: 14px;
        background: #fff; box-shadow: 0 4px 16px rgba(0, 0, 0, .04);
      }
      .evidence-table td,
      .evidence-table th {
        display: block; width: 100% !important; border-bottom: 1px solid var(--line);
      }
      .evidence-table td {
        padding: 11px 12px; white-space: pre-wrap;
      }
      .evidence-table td::before {
        content: attr(data-label); display: block; margin-bottom: 4px;
        color: var(--muted); font-size: 11px; font-weight: 700; line-height: 1.4;
      }
      .evidence-table td:last-child { border-bottom: 0; }
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
    let sessionId = storedTrackingId(
      window.sessionStorage,
      "formowl_uat_session_id",
      "uatsession_"
    );
    let expandedSourcePanelCount = 0;
    let sourceDisclosureSequence = 0;

    function updateSourceReadingMode(isExpanded) {
      expandedSourcePanelCount = Math.max(
        0,
        expandedSourcePanelCount + (isExpanded ? 1 : -1)
      );
      body.classList.toggle("sources-reading", expandedSourcePanelCount > 0);
    }

    function resetSourceReadingMode() {
      expandedSourcePanelCount = 0;
      body.classList.remove("sources-reading");
    }

    function rotateSessionId() {
      const created = randomTrackingId("uatsession_");
      sessionId = created;
      try {
        window.sessionStorage.setItem("formowl_uat_session_id", created);
        window.sessionStorage.setItem(
          "formowl_uat_session_id_created_at",
          String(Date.now())
        );
        window.sessionStorage.setItem("formowl_uat_event_sequence", "0");
      } catch (_) {}
    }

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

    function formatEvidenceTime(value) {
      if (value === null || value === undefined || value === "") return "時間未提供";
      if (typeof value !== "string" || !value.trim()) return "時間格式無法判讀";
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) return "時間格式無法判讀";
      try {
        return new Intl.DateTimeFormat("zh-TW", {
          year: "numeric",
          month: "numeric",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZone: "Asia/Taipei",
        }).format(parsed).replace(/[\u2000-\u200b\u202f\u205f\u3000]/giu, " ");
      } catch (_) {
        return "時間格式無法判讀";
      }
    }

    function renderAssistantResult(payload, holder) {
      holder.replaceChildren();
      const results = Array.isArray(payload.results) ? payload.results : [];
      const answerItems = Array.isArray(payload.answer_items)
        ? payload.answer_items.filter((item) => typeof item === "string" && item.trim())
        : [];
      if (payload.assistant_text) {
        const answer = document.createElement("div");
        answer.className = "assistant-text";
        answer.textContent = payload.assistant_text;
        holder.appendChild(answer);
      }
      if (answerItems.length) {
        const list = document.createElement("ol");
        list.className = "semantic-answer-list";
        list.setAttribute("aria-label", "查詢結果");
        for (const [index, value] of answerItems.entries()) {
          const item = document.createElement("li");
          item.className = "semantic-answer-item";
          const order = document.createElement("span");
          order.className = "semantic-answer-order";
          order.textContent = String(index + 1);
          const content = document.createElement("span");
          content.textContent = value;
          item.append(order, content);
          list.appendChild(item);
        }
        holder.appendChild(list);
      }

      if (!results.length) {
        if (
          payload.orchestration
          && payload.orchestration.action === "call_formowl_tool"
          && !answerItems.length
        ) {
          const actions = document.createElement("div");
          actions.className = "feedback-row";
          const upload = document.createElement("button");
          upload.type = "button";
          upload.title = "加入新資料";
          upload.textContent = "＋";
          upload.addEventListener("click", () => openUpload("no_result"));
          actions.appendChild(upload);
          holder.appendChild(actions);
        }
        addFeedbackControls(holder, payload.query_id);
        scrollToLatest();
        return;
      }

      const totalCount = Number.isInteger(payload.total_result_count)
        ? payload.total_result_count
        : results.length;
      const displayedCount = Number.isInteger(payload.displayed_result_count)
        ? payload.displayed_result_count
        : results.length;
      const sourceCount = results.length;
      sourceDisclosureSequence += 1;
      const sourcesToggleId = `sources-disclosure-${sourceDisclosureSequence}`;
      const sourcesPanelId = `sources-panel-${sourceDisclosureSequence}`;
      const sourcesToggle = document.createElement("button");
      sourcesToggle.type = "button";
      sourcesToggle.className = "sources-disclosure";
      sourcesToggle.id = sourcesToggleId;
      sourcesToggle.setAttribute("aria-expanded", "false");
      sourcesToggle.setAttribute("aria-controls", sourcesPanelId);
      sourcesToggle.textContent = `查看來源（${sourceCount}）`;
      const sourcesPanel = document.createElement("div");
      sourcesPanel.className = "sources-panel";
      sourcesPanel.id = sourcesPanelId;
      sourcesPanel.setAttribute("role", "region");
      sourcesPanel.setAttribute("aria-labelledby", sourcesToggleId);
      sourcesPanel.hidden = true;
      let sourcesExpanded = false;
      let sourcesRendered = false;
      const resultSummary = (item) => {
        if (typeof item.snippet === "string") return item.snippet;
        if (item.source_kind !== "authorized_document_export") return "";
        return [item.source_label, item.segment_label, item.content_sha256]
          .filter((value) => typeof value === "string" && value)
          .join(" · ");
      };

      const renderSources = () => {
        if (sourcesRendered) return;
        const title = document.createElement("div");
        title.className = "assistant-title";
        title.textContent =
          `共找到 ${totalCount} 筆相關來源內容，目前顯示 ${displayedCount} 筆。`;
        sourcesPanel.appendChild(title);

        const explanation = document.createElement("div");
        explanation.className = "assistant-text";
        explanation.textContent = "答案優先；來源內容可按需查看。";
        sourcesPanel.appendChild(explanation);

        if (payload.projection && payload.projection.output_format === "table") {
          const tableWrap = document.createElement("div");
          tableWrap.className = "evidence-table-wrap";
          const table = document.createElement("table");
          table.className = "evidence-table";
          const head = document.createElement("thead");
          const headRow = document.createElement("tr");
          for (const label of ["順序", "內容", "主旨", "時間"]) {
            const cell = document.createElement("th");
            cell.setAttribute("scope", "col");
            cell.textContent = label;
            headRow.appendChild(cell);
          }
          head.appendChild(headRow);
          const body = document.createElement("tbody");
          for (const [index, item] of results.entries()) {
            const row = document.createElement("tr");
            const order = document.createElement("td");
            order.setAttribute("data-label", "順序");
            order.textContent = String(index + 1);
            const content = document.createElement("td");
            content.setAttribute("data-label", "內容");
            content.textContent = resultSummary(item);
            if (Array.isArray(item.supporting_evidence)) {
              const supportList = document.createElement("ul");
              supportList.className = "supporting-list";
              for (const support of item.supporting_evidence) {
                const supportItem = document.createElement("li");
                const supportSnippet = support && typeof support.snippet === "string"
                  ? support.snippet
                  : "";
                supportItem.textContent = `同一來源的補充內容：${supportSnippet}`;
                supportList.appendChild(supportItem);
              }
              content.appendChild(supportList);
            }
            const subject = document.createElement("td");
            subject.setAttribute("data-label", "主旨");
            subject.textContent =
              typeof item.subject === "string" ? item.subject : "（無主旨）";
            if (item.source_kind === "uploaded_uat") {
              const badge = document.createElement("span");
              badge.className = "badge";
              badge.textContent = "測試上傳";
              subject.appendChild(badge);
            }
            const time = document.createElement("td");
            time.setAttribute("data-label", "時間");
            time.textContent = formatEvidenceTime(item.sent_at);
            row.append(order, content, subject, time);
            body.appendChild(row);
          }
          table.append(head, body);
          tableWrap.appendChild(table);
          sourcesPanel.appendChild(tableWrap);
        } else {
          const list = document.createElement("div");
          list.className = "evidence-list";
          for (const [index, item] of results.entries()) {
            const card = document.createElement("article");
            card.className = "evidence";
            const snippet = document.createElement("p");
            snippet.className = "evidence-content";
            const order = document.createElement("span");
            order.className = "source-order";
            order.textContent = String(index + 1);
            const contentText = document.createElement("span");
            contentText.textContent = resultSummary(item);
            snippet.append(order, contentText);
            const subject = document.createElement("h3");
            const subjectLabel = document.createElement("span");
            subjectLabel.className = "metadata-label";
            subjectLabel.textContent = "主旨：";
            const subjectText = document.createElement("span");
            subjectText.textContent = typeof item.subject === "string"
              ? item.subject
              : "（無主旨）";
            subject.append(subjectLabel, subjectText);
            if (item.source_kind === "uploaded_uat") {
              const badge = document.createElement("span");
              badge.className = "badge";
              badge.textContent = "測試上傳";
              subject.appendChild(badge);
            }
            const meta = document.createElement("div");
            meta.className = "evidence-meta";
            meta.textContent = `郵件時間：${formatEvidenceTime(item.sent_at)}`;
            card.append(snippet, subject, meta);
            if (Array.isArray(item.supporting_evidence)) {
              for (const support of item.supporting_evidence) {
                const supportText = document.createElement("p");
                supportText.className = "supporting-content";
                const supportSnippet = support && typeof support.snippet === "string"
                  ? support.snippet
                  : "";
                supportText.textContent = `同一來源的補充內容：${supportSnippet}`;
                card.appendChild(supportText);
              }
            }
            list.appendChild(card);
          }
          sourcesPanel.appendChild(list);
        }
        sourcesRendered = true;
      };

      sourcesToggle.addEventListener("click", () => {
        sourcesExpanded = !sourcesExpanded;
        if (sourcesExpanded) {
          renderSources();
          sourcesPanel.hidden = false;
          sourcesToggle.setAttribute("aria-expanded", "true");
          sourcesToggle.textContent = `收合來源（${sourceCount}）`;
          updateSourceReadingMode(true);
        } else {
          sourcesPanel.hidden = true;
          sourcesToggle.setAttribute("aria-expanded", "false");
          sourcesToggle.textContent = `查看來源（${sourceCount}）`;
          updateSourceReadingMode(false);
        }
      });
      holder.append(sourcesToggle, sourcesPanel);
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
      loading.textContent = "正在思考…";
      bubble.appendChild(loading);
      scrollToLatest();
      try {
        const payload = await api("/api/chat", {
          method: "POST",
          body: JSON.stringify({
            query_text: query,
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
        error.textContent = "回覆暫時失敗，請稍後再試。";
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
      track("new_chat", {});
      rotateSessionId();
      conversation.replaceChildren();
      conversationStarted = false;
      body.classList.remove("has-conversation");
      resetSourceReadingMode();
      closeMobileSidebar();
      byId("current-chat-title").textContent = "新對話";
      byId("chat-input").focus();
    }

    function trackShellControl(control, message, resetConversation = false) {
      track("shell_control", { control });
      if (resetConversation) {
        track("new_chat", {});
        rotateSessionId();
        conversation.replaceChildren();
        conversationStarted = false;
        body.classList.remove("has-conversation");
        resetSourceReadingMode();
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
    "DiagnosticMcpClient",
    "FormOwlDiagnosticMcpHttpClient",
    "MailHumanUatHttpConfig",
    "MailHumanUatService",
    "build_mail_human_uat_http_handler",
    "create_mail_human_uat_http_server",
    "render_mail_human_uat_page",
    "render_mail_human_uat_upload_page",
]
