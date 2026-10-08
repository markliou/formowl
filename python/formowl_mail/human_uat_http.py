from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import secrets
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from formowl_contract import assert_no_public_raw_references
from formowl_mail.human_uat_orchestrator import (
    _MAX_PROVIDER_ATTEMPT_DIAGNOSTICS,
    _MAX_PROVIDER_REQUESTS_PER_TURN,
    diagnostic_comparability,
    safe_diagnostic_comparability,
    safe_provider_loop_diagnostics,
)

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
_SAFE_QUERY_EXCEPTION_CLASSES = frozenset(
    {"ContractValidationError", "TypeError", "ValueError"}
)
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
    """Create the minimal same-origin browser UAT surface."""

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
    provider_diagnostic = _safe_provider_diagnostic(
        getattr(exc, "provider_diagnostic", None)
    )
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
    if not isinstance(value, Mapping):
        return None
    safe: dict[str, Any] = {}
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
        "mcp_citation_stages",
        "finalization_validation",
    ):
        if key in loop:
            safe[key] = loop[key]
    safe["diagnostic_comparability"] = safe_diagnostic_comparability(
        value.get("diagnostic_comparability"), safe,
    )
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
    request_discriminator = _safe_mcp_request_discriminator(
        value.get("request_discriminator")
    )
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
            and (
                not isinstance(limit, int)
                or isinstance(limit, bool)
                or not 1 <= limit <= 100
            )
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
