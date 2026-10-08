"""Thin real-source browser UAT adapter for the normal Issue #56 MCP route."""

from __future__ import annotations

import base64
from copy import deepcopy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import secrets
import stat
import sys
from threading import Lock, RLock, Thread
import time
import traceback
from typing import Any, Callable
import unicodedata
from urllib.parse import urlencode, urlparse

from starlette.testclient import TestClient

from formowl_contract import ContractValidationError, assert_no_public_raw_references, sha256_json
from formowl_mail.human_uat_orchestrator import (
    UatConversationMessage,
    UatConversationModel,
    UatConversationOutcome,
    UatEvidenceToolRequest,
    _MAX_PROVIDER_ATTEMPT_DIAGNOSTICS,
    _MAX_PROVIDER_REQUESTS_PER_TURN,
    _UatTurnRequestContractBinder,
    _MAX_UAT_TURN_SECONDS,
    _evidence_results_are_incomplete,
    _explicit_source_families,
    compact_evidence_for_model,
    evidence_citation_ids,
    diagnostic_comparability,
    safe_diagnostic_comparability,
    safe_provider_loop_diagnostics,
)
from formowl_mail.semantic_plan import deterministic_query_class, requires_workspace_evidence
from formowl_retrieval.gateway import source_evidence_deadline_scope

from .issue56_diagnostic import (
    _SYNTHETIC_BEARER,
    Issue56DiagnosticConfig,
    Issue56DiagnosticOAuthBridge,
    Issue56DiagnosticState,
    mcp_headers,
    mcp_query_request,
)
from .issue56_sealed_source_loader import (
    build_issue56_production_semantic_handlers,
)
from .remote import (
    ConnectedMcpApplication,
    _SAFE_DIAGNOSTIC_EXCEPTION_CLASSES,
    build_remote_tool_descriptors,
    create_connected_mcp_application,
)
from .runtime import ConnectedRuntime, ConnectedRuntimeConfig
from .semantic import SemanticMcpGateway, validate_public_gateway_payload


_PUBLIC_BASE_URL_ENV = "FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL"
_MAX_BROWSER_AUTH_RECORDS = 64
_MAX_MCP_CALLS_PER_TURN = 3
_MAX_CONVERSATION_HISTORY_MESSAGES = 8
_MAX_CONVERSATION_MESSAGE_CHARS = 8_000
_MAX_CONVERSATION_TURNS = 64
_MAX_RETAINED_EVIDENCE_ITEMS = 8
_MAX_PRESERVED_PROJECTION_ROWS = 100
_MAX_PRESERVED_PROJECTION_CHARS = 11_000
_MAX_TRACE_SUBQUERIES = 8
_TEMPORARY_LAN_SESSION_LIFETIME_SECONDS = 60 * 60
_FAILED_TURN_ANSWER = "查詢失敗，請稍後再試。"
_UAT_MCP_NOT_AUTHORIZED_FOR_CONVERSATION = "uat_mcp_not_authorized_for_conversation"
_MCP_FAILURE_STATUSES = frozenset({"error", "mcp_failed"})
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
_SAFE_MAIL_RECHECK_STATUSES = frozenset(
    {"pending_review", "ok", "not_found", "permission_denied", "error"}
)
_SAFE_MAIL_RECHECK_WARNING_CODES = frozenset(
    {
        "mail_evidence_source_fallback_skipped_exact",
        "mail_evidence_source_fallback_skipped_replan",
        "mail_evidence_source_fallback_unavailable",
        "mail_evidence_source_fallback_used",
        "mail_evidence_source_fallback_incomplete",
        "mail_evidence_source_fallback_complete_no_match",
        "mail_evidence_source_fallback_complete_coverage_incomplete",
        "mail_evidence_coverage_incomplete",
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
_SAFE_MCP_RESULT_ERROR_REASONS = frozenset(
    {
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
_SAFE_MCP_RESULT_ERROR_MESSAGES = {
    "The FormOwl tool arguments were rejected.": "invalid_tool_arguments",
    "The FormOwl tool could not complete the request.": "tool_execution_failed",
}
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
_SAFE_PROVIDER_FAILURE_REASONS = frozenset(
    {
        "encoded_response_body",
        "empty_response_body",
        "incomplete_status",
        "invalid_function_call_shape",
        "invalid_json_or_shape",
        "invalid_json_response",
        "invalid_output_item_shape",
        "invalid_output_shape",
        "invalid_top_level_shape",
        "invalid_utf8_response",
        "http_error",
        "provider_pre_mcp_failure",
        "provider_error",
        "response_too_large",
        "terminal_status",
        "transport_error",
        "transport_timeout",
        "unexpected_sse_response",
        "provider_incomplete",
        "provider_timeout",
        "provider_unavailable",
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


class _UatMcpTimeout(RuntimeError):
    """Bounded MCP call exceeded the current browser turn budget."""


@dataclass
class _ConversationState:
    expires_at: float
    history: tuple[UatConversationMessage, ...] = ()
    latest_evidence: Mapping[str, Any] | None = None
    turns: tuple[Mapping[str, Any], ...] = ()


class Issue56UatQueryService:
    """Adapt one browser prompt to bounded calls on an existing runtime."""

    def __init__(
        self,
        runtime: ConnectedRuntime,
        *,
        public_base_url: str,
        conversation_model: UatConversationModel,
    ) -> None:
        callback_url, secure_cookie = _browser_callback_url(
            runtime.config,
            public_base_url,
        )
        self._oauth = runtime.config.oauth
        self._callback_url = callback_url
        self.secure_cookie = secure_cookie
        self._client_context = TestClient(
            runtime.application.app,
            raise_server_exceptions=False,
        )
        self._client = self._client_context.__enter__()
        self._application = runtime.application
        self._conversation_model = conversation_model
        (
            self._formowl_tool_descriptor,
            self._authorized_capability_summary,
        ) = _query_agent_runtime_context(runtime.application)
        self._lock = RLock()
        self._pending: dict[str, tuple[str, str, float]] = {}
        self._sessions: dict[str, tuple[str, _ConversationState, float]] = {}
        self.request_count = 0
        self.last_mcp_statuses: tuple[str, ...] = ()
        self.last_failure_class: str | None = None
        self.last_failure_phase = "unknown"

    def __enter__(self) -> Issue56UatQueryService:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        context = getattr(self, "_client_context", None)
        if context is not None:
            self._client_context = None
            self._pending.clear()
            self._sessions.clear()
            context.__exit__(None, None, None)
            self._conversation_model.close()

    def begin_browser_authorization(self) -> tuple[str, str, int]:
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        state = secrets.token_urlsafe(32)
        browser_nonce = secrets.token_urlsafe(32)
        max_age = self._oauth.authorization_transaction_lifetime_seconds
        with self._lock:
            self._prune_browser_auth()
            _bounded_insert(
                self._pending,
                state,
                (
                    browser_nonce,
                    verifier,
                    time.monotonic() + max_age,
                ),
            )
        authorization_url = (
            self._oauth.authorization_endpoint
            + "?"
            + urlencode(
                {
                    "client_id": self._oauth.chatgpt_client_id,
                    "redirect_uri": self._callback_url,
                    "response_type": "code",
                    "resource": self._oauth.resource,
                    "scope": " ".join(self._oauth.scopes),
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        return authorization_url, browser_nonce, max_age

    def complete_browser_authorization(
        self,
        *,
        state: str,
        code: str,
        browser_nonce: str | None,
    ) -> tuple[str, int]:
        if not state or not code or not browser_nonce:
            raise ValueError("browser_oauth_callback_invalid")
        with self._lock:
            self._prune_browser_auth()
            pending = self._pending.get(state)
            if pending is None:
                raise ValueError("browser_oauth_state_invalid")
            expected_nonce, verifier, expires_at = pending
            if not secrets.compare_digest(expected_nonce, browser_nonce):
                raise ValueError("browser_oauth_nonce_invalid")
            if expires_at <= time.monotonic():
                self._pending.pop(state, None)
                raise ValueError("browser_oauth_state_expired")
            self._pending.pop(state, None)
            response = self._client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self._oauth.chatgpt_client_id,
                    "redirect_uri": self._callback_url,
                    "code_verifier": verifier,
                    "resource": self._oauth.resource,
                },
            )
            payload = response.json()
            bearer = payload.get("access_token") if isinstance(payload, Mapping) else None
            expires_in = payload.get("expires_in") if isinstance(payload, Mapping) else None
            if (
                response.status_code != 200
                or not isinstance(bearer, str)
                or not bearer
                or isinstance(expires_in, bool)
                or not isinstance(expires_in, int)
                or expires_in <= 0
            ):
                raise ValueError("browser_oauth_token_exchange_failed")
            max_age = min(expires_in, self._oauth.access_token_lifetime_seconds)
            session_id = secrets.token_urlsafe(32)
            expires_at = time.monotonic() + max_age
            _bounded_insert(
                self._sessions,
                session_id,
                (bearer, _ConversationState(expires_at=expires_at), expires_at),
            )
            return session_id, max_age

    def ensure_browser_session(self, session_id: str | None) -> tuple[str, int] | None:
        del session_id
        return None

    def is_browser_session_authenticated(self, session_id: str | None) -> bool:
        with self._lock:
            return self._browser_bearer(session_id) is not None

    def read_browser_conversation(self, session_id: str | None) -> Mapping[str, Any]:
        with self._lock:
            if self._browser_bearer(session_id) is None or session_id is None:
                raise PermissionError("auth_required")
            return _conversation_projection(self._sessions[session_id][1])

    def reset_browser_conversation(self, session_id: str | None) -> tuple[str, int]:
        with self._lock:
            bearer = self._browser_bearer(session_id)
            if bearer is None or session_id is None:
                raise PermissionError("auth_required")
            _old_bearer, _old_state, expires_at = self._sessions.pop(session_id)
            remaining_seconds = max(1, int(expires_at - time.monotonic()))
            new_session_id = secrets.token_urlsafe(32)
            self._sessions[new_session_id] = (
                bearer,
                _ConversationState(expires_at=expires_at),
                expires_at,
            )
        self._conversation_model.discard_conversation(_conversation_identifier(session_id))
        return new_session_id, remaining_seconds

    def logout_browser_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)
        self._conversation_model.discard_conversation(_conversation_identifier(session_id))

    def ask(self, prompt: str, *, session_id: str | None) -> Mapping[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        with self._lock:
            bearer = self._browser_bearer(session_id)
            if bearer is None:
                raise PermissionError("auth_required")
            assert session_id is not None
            state = self._sessions[session_id][1]
            previous_history = state.history
            previous_evidence = state.latest_evidence
            previous_turns = state.turns
            self.request_count = 0
            self.last_failure_class = None
            self.last_failure_phase = "provider_model"
            turn_deadline = time.monotonic() + _MAX_UAT_TURN_SECONDS
            conversation_identifier = _conversation_identifier(session_id)
            try:
                (
                    turn_tool_descriptor,
                    turn_capability_summary,
                ) = _query_agent_runtime_context(
                    self._application,
                    user_text=prompt,
                )
                result, responses, outcome = _run_gpt_query_agent(
                    self._conversation_model,
                    prompt=prompt,
                    history=state.history,
                    latest_evidence=state.latest_evidence,
                    safety_identifier=conversation_identifier,
                    formowl_tool_descriptor=turn_tool_descriptor,
                    authorized_capability_summary=turn_capability_summary,
                    mcp_call=lambda request: self._call(
                        request,
                        bearer=bearer,
                        deadline_monotonic=turn_deadline,
                    ),
                )
                result = _classify_mcp_failure_result(result, responses, ())
                result = _with_mcp_diagnostic(result, ())
                self.last_mcp_statuses = tuple(
                    str(response.get("status", "unknown")) for response in responses
                )
                try:
                    validate_public_gateway_payload(result)
                    assert_no_public_raw_references(result, "issue56_uat_browser_result")
                except ContractValidationError as exc:
                    result = _safe_current_turn_projection_after_validation_failure(
                        outcome,
                        responses,
                        original_result=result,
                        original_error=exc,
                        boundary="issue56_uat_browser_result",
                    )
                _advance_conversation_state(
                    state,
                    prompt=prompt,
                    result=result,
                    outcome=outcome,
                    responses=responses,
                )
                return result
            except _UatMcpTimeout:
                self.last_failure_class = "mcp_timeout"
                self.last_failure_phase = "mcp_timeout"
                _record_failed_conversation_turn(
                    state,
                    prompt=prompt,
                    previous_history=previous_history,
                    previous_evidence=previous_evidence,
                    previous_turns=previous_turns,
                )
                self._conversation_model.discard_conversation(conversation_identifier)
                raise
            except Exception:
                _record_failed_conversation_turn(
                    state,
                    prompt=prompt,
                    previous_history=previous_history,
                    previous_evidence=previous_evidence,
                    previous_turns=previous_turns,
                )
                self._conversation_model.discard_conversation(conversation_identifier)
                raise

    def _call(
        self,
        request: UatEvidenceToolRequest,
        *,
        bearer: str,
        deadline_monotonic: float | None = None,
    ) -> Mapping[str, Any]:
        self.request_count += 1
        remaining = (
            deadline_monotonic - time.monotonic()
            if deadline_monotonic is not None
            else _MAX_UAT_TURN_SECONDS
        )
        if remaining <= 0:
            raise _UatMcpTimeout()
        result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def run_mcp_request() -> None:
            client: Any = self._client
            close_client = False
            try:
                application = getattr(self, "_application", None)
                app = getattr(application, "app", None)
                if app is not None:
                    client = TestClient(
                        app,
                        raise_server_exceptions=False,
                    )
                    close_client = True
                result_queue.put(
                    (
                        True,
                        client.post(
                            "/mcp",
                            headers=mcp_headers(bearer=bearer),
                            json=_mcp_query_request(request),
                        ),
                    )
                )
            except BaseException as exc:
                result_queue.put((False, exc))
            finally:
                if close_client:
                    client.close()

        Thread(target=run_mcp_request, daemon=True).start()
        try:
            succeeded, response_or_error = result_queue.get(timeout=remaining)
        except queue.Empty:
            raise _UatMcpTimeout() from None
        if not succeeded:
            raise response_or_error
        response = response_or_error
        envelope = response.json()
        result = envelope.get("result") if isinstance(envelope, Mapping) else None
        structured = (
            _extract_mcp_structured_payload(result) if isinstance(result, Mapping) else None
        )
        if isinstance(result, Mapping) and result.get("isError") is True:
            return {"status": "mcp_failed", "citations": []}
        data = structured.get("data") if isinstance(structured, Mapping) else None
        if response.status_code != 200 or not isinstance(data, Mapping):
            return {"status": "mcp_failed", "citations": []}
        validate_public_gateway_payload(data)
        return data

    def _browser_bearer(self, session_id: str | None) -> str | None:
        self._prune_browser_auth()
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        return session[0] if session is not None else None

    def _prune_browser_auth(self) -> None:
        now = time.monotonic()
        for values in (self._pending, self._sessions):
            for key, value in tuple(values.items()):
                expires_at = value[-1]
                if expires_at <= now:
                    values.pop(key, None)


class Issue56TemporaryLanQueryService:
    """Serve the fixed diagnostic identity without external OAuth or storage."""

    secure_cookie = False

    def __init__(
        self,
        application: ConnectedMcpApplication,
        *,
        conversation_model: UatConversationModel,
        behavior_log_path: Path | None = None,
        record_raw_uat_interactions: bool = False,
        _source_binding_fingerprint: str | None = None,
    ) -> None:
        if (behavior_log_path is None) != (not record_raw_uat_interactions):
            raise ValueError("raw UAT recording requires both explicit options")
        self._client_context = TestClient(
            application.app,
            raise_server_exceptions=False,
        )
        self._client = self._client_context.__enter__()
        self._application = application
        self._conversation_model = conversation_model
        # Composition supplies only a frozen digest after normal source validation.
        self._source_binding_fingerprint = _source_binding_fingerprint
        (
            self._formowl_tool_descriptor,
            self._authorized_capability_summary,
        ) = _query_agent_runtime_context(application)
        self._lock = RLock()
        self._query_lock = Lock()
        self._behavior_log_path = behavior_log_path
        self._record_raw_uat_interactions = record_raw_uat_interactions
        self._sessions: dict[str, _ConversationState] = {}
        self.request_count = 0
        self.last_mcp_statuses: tuple[str, ...] = ()
        self.last_failure_class: str | None = None
        self.last_failure_phase = "unknown"
        self._active_turn_deadline: float | None = None

    def __enter__(self) -> Issue56TemporaryLanQueryService:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        context = getattr(self, "_client_context", None)
        if context is not None:
            self._client_context = None
            self._sessions.clear()
            context.__exit__(None, None, None)
            self._conversation_model.close()

    def begin_browser_authorization(self) -> tuple[str, str, int]:
        raise RuntimeError("temporary LAN diagnostic has no browser OAuth")

    def complete_browser_authorization(
        self,
        *,
        state: str,
        code: str,
        browser_nonce: str | None,
    ) -> tuple[str, int]:
        del state, code, browser_nonce
        raise RuntimeError("temporary LAN diagnostic has no browser OAuth")

    def ensure_browser_session(self, session_id: str | None) -> tuple[str, int] | None:
        evicted_session_ids: list[str] = []
        with self._lock:
            self._prune_browser_sessions()
            if session_id in self._sessions:
                return None
            while len(self._sessions) >= _MAX_BROWSER_AUTH_RECORDS:
                evicted_session_id = next(iter(self._sessions))
                evicted_session_ids.append(evicted_session_id)
                self._sessions.pop(evicted_session_id, None)
            session_id = secrets.token_urlsafe(32)
            self._sessions[session_id] = _ConversationState(
                expires_at=(time.monotonic() + _TEMPORARY_LAN_SESSION_LIFETIME_SECONDS),
            )
        for evicted_session_id in evicted_session_ids:
            self._conversation_model.discard_conversation(
                _conversation_identifier(evicted_session_id)
            )
        return session_id, _TEMPORARY_LAN_SESSION_LIFETIME_SECONDS

    def is_browser_session_authenticated(self, session_id: str | None) -> bool:
        with self._lock:
            self._prune_browser_sessions()
            return session_id in self._sessions

    def read_browser_conversation(self, session_id: str | None) -> Mapping[str, Any]:
        with self._lock:
            self._prune_browser_sessions()
            state = self._sessions.get(session_id)
            if state is None or session_id is None:
                raise PermissionError("browser_session_required")
            return _conversation_projection(state)

    def reset_browser_conversation(self, session_id: str | None) -> tuple[str, int]:
        with self._lock:
            self._prune_browser_sessions()
            if session_id is None or self._sessions.pop(session_id, None) is None:
                raise PermissionError("browser_session_required")
            new_session_id = secrets.token_urlsafe(32)
            self._sessions[new_session_id] = _ConversationState(
                expires_at=(time.monotonic() + _TEMPORARY_LAN_SESSION_LIFETIME_SECONDS),
            )
        self._conversation_model.discard_conversation(_conversation_identifier(session_id))
        return new_session_id, _TEMPORARY_LAN_SESSION_LIFETIME_SECONDS

    def logout_browser_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            removed = self._sessions.pop(session_id, None)
        if removed is not None:
            self._conversation_model.discard_conversation(_conversation_identifier(session_id))

    def ask(self, prompt: str, *, session_id: str | None) -> Mapping[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        with self._query_lock:
            with self._lock:
                self._prune_browser_sessions()
                state = self._sessions.get(session_id)
                if state is None or session_id is None:
                    raise PermissionError("browser_session_required")
                previous_history = state.history
                previous_evidence = state.latest_evidence
                previous_turns = state.turns
                started_at = time.perf_counter()
                self.request_count = 0
                self.last_mcp_statuses = ()
                self.last_failure_phase = "provider_model"
                self.last_failure_class = None
                self._last_private_mcp_owner_trace = None
                self._active_turn_deadline = time.monotonic() + _MAX_UAT_TURN_SECONDS
            call_traces: list[dict[str, Any]] = []
            result: Mapping[str, Any] | None = None
            failure_sha256: str | None = None
            outcome: UatConversationOutcome | None = None
            conversation_identifier = _conversation_identifier(session_id)
            browser_request_sha256 = _browser_request_fingerprint(session_id, prompt)
            try:
                (
                    turn_tool_descriptor,
                    turn_capability_summary,
                ) = _query_agent_runtime_context(
                    self._application,
                    user_text=prompt,
                )
                result, responses, outcome = _run_gpt_query_agent(
                    self._conversation_model,
                    prompt=prompt,
                    history=previous_history,
                    latest_evidence=previous_evidence,
                    safety_identifier=conversation_identifier,
                    formowl_tool_descriptor=turn_tool_descriptor,
                    authorized_capability_summary=turn_capability_summary,
                    mcp_call=lambda request: self._call(
                        request,
                        trace_sink=call_traces,
                        browser_request_sha256=browser_request_sha256,
                    ),
                )
                result = _classify_mcp_failure_result(result, responses, call_traces)
                result = _with_mcp_diagnostic(
                    result, call_traces,
                    source_binding_fingerprint=self._source_binding_fingerprint,
                )
                self.last_mcp_statuses = tuple(
                    str(response.get("status", "unknown")) for response in responses
                )
                self.last_failure_phase = "projection"
                try:
                    validate_public_gateway_payload(result)
                    assert_no_public_raw_references(
                        result,
                        "issue56_temporary_lan_browser_result",
                    )
                except ContractValidationError as exc:
                    result = _safe_current_turn_projection_after_validation_failure(
                        outcome,
                        responses,
                        original_result=result,
                        original_error=exc,
                        boundary="issue56_temporary_lan_browser_result",
                    )
                self.last_failure_phase = "session_state"
                with self._lock:
                    if self._sessions.get(session_id) is state:
                        _advance_conversation_state(
                            state,
                            prompt=prompt,
                            result=result,
                            outcome=outcome,
                            responses=responses,
                        )
                self.last_failure_phase = "unknown"
                return result
            except Exception as exc:
                failure_sha256 = _failure_sha256(exc)
                _emit_private_uat_failure_trace(exc, self.last_failure_phase, result)
                if isinstance(exc, _UatMcpTimeout):
                    self.last_failure_class = "mcp_timeout"
                elif isinstance(exc, TimeoutError):
                    self.last_failure_class = "provider_timeout"
                elif self.last_failure_phase in {
                    "provider_model",
                    "mcp_client",
                    "projection",
                    "session_state",
                }:
                    self.last_failure_class = self.last_failure_phase
                else:
                    self.last_failure_class = "runtime_init"
                with self._lock:
                    if self._sessions.get(session_id) is state:
                        _record_failed_conversation_turn(
                            state,
                            prompt=prompt,
                            previous_history=previous_history,
                            previous_evidence=previous_evidence,
                            previous_turns=previous_turns,
                        )
                self._conversation_model.discard_conversation(conversation_identifier)
                raise
            finally:
                self._active_turn_deadline = None
                if not self.last_mcp_statuses and call_traces:
                    self.last_mcp_statuses = tuple(
                        str(trace.get("status", "unknown")) for trace in call_traces
                    )
                _emit_private_uat_terminal_trace(
                    "turn", started_at=started_at, outcome=outcome, result=result,
                    mcp_call_count=self.request_count,
                    failure_class=self.last_failure_class if failure_sha256 is not None else None,
                )
                if self._behavior_log_path is not None:
                    _append_behavior_log(
                        self._behavior_log_path,
                        prompt=prompt,
                        result=result,
                        request_count=self.request_count,
                        statuses=self.last_mcp_statuses,
                        call_traces=call_traces,
                        failure_sha256=failure_sha256,
                        provider_diagnostic=_diagnostic_with_mcp(
                            outcome.provider_diagnostic if outcome is not None else None,
                            call_traces,
                            source_binding_fingerprint=self._source_binding_fingerprint,
                        ),
                        elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
                    )

    def _call(
        self,
        request: UatEvidenceToolRequest,
        *,
        trace_sink: list[dict[str, Any]],
        browser_request_sha256: str | None = None,
    ) -> Mapping[str, Any]:
        previous_phase = self.last_failure_phase
        self.last_failure_phase = "mcp_client"
        self.request_count += 1
        call_index = self.request_count
        started_at = time.perf_counter()
        response_status: int | None = None
        data: Mapping[str, Any] = {"status": "mcp_failed", "citations": []}
        failure_sha256: str | None = None
        request_shape = _mcp_request_shape(request)
        request_discriminator = _mcp_request_discriminator(request)
        response_stage = "request_built"
        exception_class: str | None = None
        exception_owner: dict[str, Any] | None = None
        failure_reason: str | None = None
        mcp_exception = False
        mcp_timeout = False
        turn_deadline = self._active_turn_deadline
        try:
            remaining = (
                turn_deadline - time.monotonic()
                if turn_deadline is not None
                else 0.0
            )
            if remaining <= 0:
                raise _UatMcpTimeout()
            result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

            def run_mcp_request() -> None:
                client: Any = self._client
                close_client = False
                try:
                    application = getattr(self, "_application", None)
                    app = getattr(application, "app", None)
                    if app is not None:
                        # The browser request can already be running on a
                        # ThreadingHTTPServer worker.  Do not reuse the
                        # TestClient/portal created by another thread for the
                        # bounded nested call; retain the application
                        # lifespan while giving this worker an isolated
                        # transport context.
                        client = TestClient(
                            app,
                            raise_server_exceptions=False,
                        )
                        close_client = True
                    # Capture the turn binding before dispatch. A later turn
                    # must not lend its deadline to this in-flight request.
                    with source_evidence_deadline_scope(turn_deadline):
                        response = client.post(
                                "/mcp",
                                headers=mcp_headers(bearer=_SYNTHETIC_BEARER),
                                json=_mcp_query_request(request),
                        )
                    result_queue.put((True, response))
                except BaseException as exc:
                    result_queue.put((False, exc))
                finally:
                    if close_client:
                        client.close()

            Thread(target=run_mcp_request, daemon=True).start()
            try:
                succeeded, response_or_error = result_queue.get(timeout=remaining)
            except queue.Empty:
                raise _UatMcpTimeout() from None
            if not succeeded:
                raise response_or_error
            response = response_or_error
            response_stage = "http_response"
            response_status = response.status_code
            if response.status_code != 200:
                failure_reason = "http_status"
                failure_sha256 = _failure_sha256(RuntimeError("mcp_failure:http_status"))
                return data
            envelope = response.json()
            result = envelope.get("result") if isinstance(envelope, Mapping) else None
            if not isinstance(result, Mapping):
                failure_reason = "missing_structured_payload"
                failure_sha256 = _failure_sha256(
                    RuntimeError("mcp_failure:missing_structured_payload")
                )
                return data
            structured = _extract_mcp_structured_payload(result)
            if result.get("isError") is True:
                response_stage = "jsonrpc_error"
                meta = result.get("_meta")
                diagnostic = meta.get("formowl_diagnostic") if isinstance(meta, Mapping) else None
                if isinstance(diagnostic, Mapping):
                    stage = diagnostic.get("response_stage")
                    if isinstance(stage, str) and stage in {"exception", "payload_validation"}:
                        response_stage = stage
                    name = diagnostic.get("exception_class")
                    if isinstance(name, str) and (
                        name in _SAFE_DIAGNOSTIC_EXCEPTION_CLASSES or name == "mcp_exception"
                    ):
                        exception_class = name
                    exception_owner = _safe_mcp_exception_owner(diagnostic.get("exception_owner"))
                failure_reason = _mcp_result_error_reason(result, structured)
                if failure_reason is None:
                    failure_reason = "jsonrpc_result_error"
                failure_sha256 = _failure_sha256(RuntimeError(f"mcp_failure:{failure_reason}"))
                return data
            if not isinstance(structured, Mapping):
                response_stage = "structured_payload"
                failure_reason = "missing_structured_payload"
                failure_sha256 = _failure_sha256(
                    RuntimeError("mcp_failure:missing_structured_payload")
                )
                return data
            candidate = structured.get("data")
            if not isinstance(candidate, Mapping):
                response_stage = "structured_payload"
                failure_reason = "missing_data_mapping"
                failure_sha256 = _failure_sha256(RuntimeError("mcp_failure:missing_data_mapping"))
                return data
            response_stage = "payload_validation"
            validate_public_gateway_payload(candidate)
            data = candidate
            response_stage = "payload_validated"
            return data
        except _UatMcpTimeout as exc:
            mcp_exception = True
            mcp_timeout = True
            response_stage = "timeout"
            exception_class = "mcp_timeout"
            failure_sha256 = _failure_sha256(exc)
            raise
        except Exception as exc:
            mcp_exception = True
            response_stage = "exception"
            exception_class = _safe_mcp_exception_class(exc)
            exception_owner = exception_owner or _safe_exception_owner_from_exception(exc)
            failure_sha256 = _failure_sha256(exc)
            raise
        finally:
            self.last_failure_phase = "mcp_client" if mcp_exception else previous_phase
            trace = _build_call_trace(
                query_text=request.query_text,
                table_query=request.table_query,
                request_shape=request_shape,
                request_discriminator=request_discriminator,
                data=data,
                response_status=response_status,
                failure_sha256=failure_sha256,
                exception_class=exception_class,
                failure_reason=failure_reason,
                response_stage=response_stage,
                elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
                timeout=mcp_timeout,
                exception_owner=exception_owner,
                include_query_text=self._record_raw_uat_interactions,
            )
            if _is_browser_request_fingerprint(browser_request_sha256):
                trace["browser_request_sha256"] = browser_request_sha256
                trace["mcp_call_index"] = call_index
            trace_sink.append(trace)
            # Keep the gateway's safe owner frame available only on the
            # service object for private diagnostics.  Public projections use
            # _safe_mcp_call_diagnostic and intentionally omit this field.
            self._last_private_mcp_owner_trace = _private_mcp_owner_trace(trace)
            _emit_private_mcp_owner_trace(
                trace,
                validated_response=data if response_stage == "payload_validated" else None,
            )

    def _prune_browser_sessions(self) -> None:
        now = time.monotonic()
        for key, state in tuple(self._sessions.items()):
            if state.expires_at <= now:
                self._sessions.pop(key, None)


def _append_behavior_log(
    path: Path,
    *,
    prompt: str,
    result: Mapping[str, Any] | None,
    request_count: int,
    statuses: Sequence[str],
    call_traces: Sequence[Mapping[str, Any]],
    failure_sha256: str | None,
    provider_diagnostic: Mapping[str, Any] | None,
    elapsed_ms: float,
) -> None:
    visible_result = (
        {key: result.get(key) for key in ("status", "answer", "clarification", "citations")}
        if result is not None
        else None
    )
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "result": visible_result,
        "request_count": request_count,
        "mcp_statuses": list(statuses),
        "calls": [dict(trace) for trace in call_traces],
        "failure_sha256": failure_sha256,
        "provider_diagnostic": (
            dict(provider_diagnostic) if provider_diagnostic is not None else None
        ),
        "elapsed_ms": round(elapsed_ms, 3),
    }
    assert_no_public_raw_references(record, "issue56_temporary_lan_behavior_log")
    encoded = (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("behavior log must be a regular file")
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


def _bounded_insert(
    values: dict[str, Any],
    key: str,
    value: Any,
) -> None:
    while len(values) >= _MAX_BROWSER_AUTH_RECORDS:
        values.pop(next(iter(values)))
    values[key] = value


def _browser_callback_url(
    config: ConnectedRuntimeConfig,
    public_base_url: str,
) -> tuple[str, bool]:
    if not isinstance(public_base_url, str):
        raise RuntimeError("issue56_uat_public_base_url_invalid")
    parsed = urlparse(public_base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("issue56_uat_public_base_url_invalid")
    callback_url = f"{parsed.scheme}://{parsed.netloc}/auth/callback"
    if callback_url != config.oauth.chatgpt_redirect_uri:
        raise RuntimeError("issue56_uat_callback_mismatch")
    return callback_url, parsed.scheme == "https"


def _query_agent_runtime_context(
    application: ConnectedMcpApplication | Any,
    *,
    user_text: str | None = None,
) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
    dispatcher = getattr(application, "dispatcher", None)
    if dispatcher is None:
        descriptors = build_remote_tool_descriptors(
            required_scope="formowl.use",
            enabled_tool_names={"whoami", "query_effective_graph_view"},
        )
        descriptor = next(item for item in descriptors if item.name == "query_effective_graph_view")
        return descriptor.model_dump(by_alias=True, exclude_none=True), None

    descriptors = build_remote_tool_descriptors(
        required_scope=dispatcher.required_scope,
        enabled_tool_names=dispatcher.enabled_tool_names,
    )
    is_explicit_workspace_request = user_text is not None and requires_workspace_evidence(user_text)
    preferred_tool_name = (
        "query_mail_evidence"
        if (is_explicit_workspace_request and "mail" in _explicit_source_families(user_text))
        else "query_effective_graph_view"
    )
    descriptor = next(
        (item for item in descriptors if item.name == preferred_tool_name),
        None,
    )
    if descriptor is None:
        descriptor = next(
            (
                item
                for item in descriptors
                if item.name in {"query_effective_graph_view", "query_mail_evidence"}
            ),
            None,
        )
    if descriptor is None:
        raise RuntimeError("issue56_uat_query_tool_unavailable")
    semantic_gateway = dispatcher.semantic_gateway
    handler_attribute = (
        "retrieval_handler"
        if descriptor.name == "query_effective_graph_view"
        else "mail_evidence_handler"
    )
    handler = getattr(semantic_gateway, handler_attribute, None)
    capability_summary = getattr(
        handler,
        "authorized_capability_summary",
        None,
    )
    if descriptor.name == "query_effective_graph_view" and not isinstance(
        capability_summary,
        Mapping,
    ):
        raise RuntimeError("issue56_uat_authorized_capabilities_unavailable")
    if descriptor.name == "query_mail_evidence" and not isinstance(
        capability_summary,
        Mapping,
    ):
        capability_summary = None
    try:
        validate_public_gateway_payload(capability_summary)
    except ContractValidationError:
        # The descriptor remains usable without an invalid optional capability
        # hint.  Tool execution still enforces authorization and contracts.
        capability_summary = None
    tool_descriptor = descriptor.model_dump(by_alias=True, exclude_none=True)
    if descriptor.name == "query_mail_evidence":
        input_schema = dict(tool_descriptor["inputSchema"])
        input_schema["required"] = sorted(
            set(input_schema.get("required", ())) | {"required_terms"}
        )
        tool_descriptor["inputSchema"] = input_schema
    elif (
        descriptor.name == "query_effective_graph_view"
        and isinstance(user_text, str)
        and requires_workspace_evidence(user_text)
        and deterministic_query_class(user_text) == "evidence_lookup"
    ):
        input_schema = dict(tool_descriptor["inputSchema"])
        input_schema["required"] = sorted(
            set(input_schema.get("required", ())) | {"required_terms"}
        )
        tool_descriptor["inputSchema"] = input_schema
    return (
        tool_descriptor,
        None if capability_summary is None else dict(capability_summary),
    )


def _mcp_query_request(request: UatEvidenceToolRequest) -> dict[str, Any]:
    if request.tool_name == "query_mail_evidence":
        payload = mcp_query_request(request.query_text)
        payload["params"]["name"] = request.tool_name
        arguments = payload["params"]["arguments"]
        for key in (
            "mail_import_session_id",
            "mail_evidence_bundle_id",
            "required_terms",
            "limit",
        ):
            value = getattr(request, key)
            if value is not None:
                arguments[key] = list(value) if key == "required_terms" else value
        if request.request_contract is not None:
            arguments["request_contract"] = dict(request.request_contract)
        return payload
    payload = mcp_query_request(
        request.query_text,
        table_query=request.table_query,
    )
    payload["params"]["name"] = request.tool_name
    arguments = payload["params"]["arguments"]
    for key in ("exact_inventory_kind", "exact_field", "page_size", "cursor"):
        value = getattr(request, key)
        if value is not None:
            arguments[key] = value
    if request.request_contract is not None:
        arguments["request_contract"] = dict(request.request_contract)
    if request.required_terms is not None:
        arguments["required_terms"] = list(request.required_terms)
    return payload


def _run_gpt_query_agent(
    conversation_model: UatConversationModel,
    *,
    prompt: str,
    history: Sequence[UatConversationMessage],
    latest_evidence: Mapping[str, Any] | None,
    safety_identifier: str,
    formowl_tool_descriptor: Mapping[str, Any] | None,
    authorized_capability_summary: Mapping[str, Any] | None,
    mcp_call: Callable[[UatEvidenceToolRequest], Mapping[str, Any]],
) -> tuple[
    dict[str, Any],
    tuple[Mapping[str, Any], ...],
    UatConversationOutcome,
]:
    responses: list[Mapping[str, Any]] = []
    request_contract_binder = _UatTurnRequestContractBinder(
        user_text=prompt,
        authorized_capability_summary=authorized_capability_summary,
    )
    prior_evidence_present = latest_evidence is not None
    prior_evidence_citeable = prior_evidence_present and bool(
        evidence_citation_ids(latest_evidence)
    )

    def evidence_tool(request: UatEvidenceToolRequest) -> Mapping[str, Any]:
        if not requires_workspace_evidence(
            prompt,
            query_class=request_contract_binder._query_class,
            prior_evidence_citeable=prior_evidence_citeable,
            prior_evidence_present=prior_evidence_present,
        ):
            raise RuntimeError(_UAT_MCP_NOT_AUTHORIZED_FOR_CONVERSATION)
        if len(responses) >= _MAX_MCP_CALLS_PER_TURN:
            raise RuntimeError("UAT Query Agent exceeded the MCP call budget")
        if request.tool_name in {"query_effective_graph_view", "query_mail_evidence"}:
            bound_contract = request_contract_binder.bind(
                request.request_contract,
                table_query=(
                    request.table_query
                    if request.tool_name == "query_effective_graph_view"
                    else None
                ),
            )
            if bound_contract != request.request_contract:
                request = replace(request, request_contract=bound_contract)
        if request.tool_name in {"query_mail_evidence", "query_effective_graph_view"}:
            bound_terms = request_contract_binder.bind_required_terms(
                list(request.required_terms) if request.required_terms is not None else None,
                allow_missing=request.tool_name == "query_effective_graph_view",
            )
            if bound_terms is not None and bound_terms != request.required_terms:
                request = replace(request, required_terms=bound_terms)
        data = mcp_call(request)
        responses.append(data)
        return data

    provider_started_at = time.perf_counter()
    outcome = conversation_model.respond(
        history=history,
        user_text=prompt,
        latest_evidence=latest_evidence,
        safety_identifier=safety_identifier,
        evidence_tool=evidence_tool,
        formowl_tool_descriptor=formowl_tool_descriptor,
        authorized_capability_summary=authorized_capability_summary,
    )
    _emit_private_uat_terminal_trace(
        "provider", started_at=provider_started_at, outcome=outcome,
        mcp_call_count=len(responses),
    )
    return (
        _browser_projection(
            outcome,
            responses,
            latest_evidence=latest_evidence,
        ),
        tuple(responses),
        outcome,
    )


def _safe_provider_diagnostic(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
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
        and 0 <= formowl_attempts <= _MAX_MCP_CALLS_PER_TURN
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
                or not 0 <= float(elapsed_ms) <= _MAX_UAT_TURN_SECONDS * 1000
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
        fragment = loop.get(key)
        if fragment is None:
            continue
        try:
            assert_no_public_raw_references(
                fragment,
                f"issue56_uat_{key}_diagnostic",
            )
        except ContractValidationError:
            # A provider diagnostic is untrusted input at this boundary.  Do
            # not let an older or malformed loop projector reintroduce raw
            # request/input structure into the browser payload.
            continue
        safe[key] = fragment
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
        or not 0 <= call_count <= _MAX_MCP_CALLS_PER_TURN
        or isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, (int, float))
        or not math.isfinite(float(elapsed_ms))
        or not 0 <= float(elapsed_ms) <= _MAX_UAT_TURN_SECONDS * 1000
        or not isinstance(statuses, Sequence)
        or isinstance(statuses, (str, bytes))
        or len(statuses) > _MAX_MCP_CALLS_PER_TURN
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
    response_stage = _safe_mcp_response_stage(value.get("response_stage"))
    if response_stage is not None:
        safe["response_stage"] = response_stage
    exception_class = _safe_mcp_exception_name(value.get("exception_class"))
    if exception_class is not None:
        safe["exception_class"] = exception_class
    failure_reason = _safe_mcp_failure_reason(value.get("failure_reason"))
    if failure_reason is not None:
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
    query_text_char_count = value.get("query_text_char_count")
    required_term_count = value.get("required_term_count")
    required_terms_fingerprint = value.get("required_terms_fingerprint")
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
        or (
            query_text_char_count is not None
            and (
                type(query_text_char_count) is not int
                or not 1 <= query_text_char_count <= 1_000_000
            )
        )
        or (
            (required_term_count is None) != (required_terms_fingerprint is None)
        )
        or (
            required_term_count is not None
            and (
                type(required_term_count) is not int
                or not 1 <= required_term_count <= 8
                or not _is_browser_request_fingerprint(required_terms_fingerprint)
            )
        )
    ):
        return None
    safe = {
        "tool_name": tool_name,
        "selector_kind": selector_kind,
        "selector_present": selector_present,
        "selector_count": selector_count,
    }
    if selector_hash is not None:
        safe["selector_hash"] = selector_hash
    if limit is not None:
        safe["limit"] = limit
    if query_text_char_count is not None:
        safe["query_text_char_count"] = query_text_char_count
    if required_term_count is not None:
        safe["required_term_count"] = required_term_count
        safe["required_terms_fingerprint"] = required_terms_fingerprint
    return safe


def _mcp_request_discriminator(request: UatEvidenceToolRequest) -> dict[str, Any]:
    selectors = (
        ("mail_import_session_id", request.mail_import_session_id),
        ("mail_evidence_bundle_id", request.mail_evidence_bundle_id),
    )
    present = tuple(
        (kind, value) for kind, value in selectors if isinstance(value, str) and value.strip()
    )
    selector_kind = present[0][0] if len(present) == 1 else ("none" if not present else "multiple")
    safe: dict[str, Any] = {
        "tool_name": (
            request.tool_name if request.tool_name in _SAFE_MCP_TOOL_NAMES else "unknown_tool"
        ),
        "selector_kind": selector_kind,
        "selector_present": bool(present),
        "selector_count": len(present),
    }
    if len(present) == 1:
        safe["selector_hash"] = (
            "sha256:" + hashlib.sha256(present[0][1].encode("utf-8")).hexdigest()
        )
    if request.limit is not None:
        safe["limit"] = request.limit
    safe["query_text_char_count"] = len(request.query_text)
    if request.required_terms is not None:
        canonical_terms = sorted(
            unicodedata.normalize("NFKC", term.strip()).casefold()
            for term in request.required_terms
        )
        safe["required_term_count"] = len(canonical_terms)
        safe["required_terms_fingerprint"] = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    canonical_terms,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
    return safe


def _safe_mcp_response_stage(value: Any) -> str | None:
    if isinstance(value, str) and value in _SAFE_MCP_RESPONSE_STAGES:
        return value
    return None


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


def _safe_mcp_failure_reason(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if (
        value
        in {
            "http_status",
            "jsonrpc_result_error",
            "missing_structured_payload",
            "missing_data_mapping",
        }
        or value in _SAFE_MCP_RESULT_ERROR_REASONS
    ):
        return value
    return None


def _extract_mcp_structured_payload(result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    structured = result.get("structuredContent")
    if isinstance(structured, Mapping):
        return structured
    content = result.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return None
    for item in content:
        if not isinstance(item, Mapping):
            continue
        json_content = item.get("json")
        if isinstance(json_content, Mapping):
            return json_content
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            decoded = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(decoded, Mapping):
            return decoded
    return None


def _mcp_result_error_reason(
    result: Mapping[str, Any],
    structured: Mapping[str, Any] | None,
) -> str | None:
    candidates: list[Any] = []
    if structured is not None:
        candidates.extend(
            (
                structured.get("reason_code"),
                structured.get("error_code"),
            )
        )
        data = structured.get("data")
        if isinstance(data, Mapping):
            candidates.extend((data.get("reason_code"), data.get("error_code")))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate in _SAFE_MCP_RESULT_ERROR_REASONS:
            return candidate
    content = result.get("content")
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        for item in content:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if text in _SAFE_MCP_RESULT_ERROR_MESSAGES:
                return _SAFE_MCP_RESULT_ERROR_MESSAGES[text]
    return None


def _safe_mcp_call_diagnostic(
    call_traces: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    statuses: list[str] = []
    elapsed_ms = 0.0
    timeout = False
    request_shape: dict[str, bool] | None = None
    request_discriminator: dict[str, Any] | None = None
    response_stage: str | None = None
    exception_class: str | None = None
    failure_reason: str | None = None
    for trace in call_traces[:_MAX_MCP_CALLS_PER_TURN]:
        status = trace.get("status")
        if (
            isinstance(status, str)
            and 0 < len(status) <= 64
            and all(character.isalnum() or character in {"_", "-"} for character in status)
        ):
            statuses.append(status)
        timings = trace.get("timings_ms")
        call_elapsed = timings.get("mcp_call") if isinstance(timings, Mapping) else None
        if (
            isinstance(call_elapsed, (int, float))
            and not isinstance(call_elapsed, bool)
            and math.isfinite(float(call_elapsed))
            and 0 <= float(call_elapsed) <= _MAX_UAT_TURN_SECONDS * 1000
        ):
            elapsed_ms += float(call_elapsed)
        timeout = timeout or trace.get("timeout") is True
        safe_shape = _safe_mcp_request_shape(trace.get("request_shape"))
        if safe_shape is not None:
            request_shape = safe_shape
        safe_discriminator = _safe_mcp_request_discriminator(trace.get("request_discriminator"))
        if safe_discriminator is not None:
            request_discriminator = safe_discriminator
        safe_stage = _safe_mcp_response_stage(trace.get("response_stage"))
        if safe_stage is not None:
            response_stage = safe_stage
        safe_exception = _safe_mcp_exception_name(trace.get("exception_class"))
        if safe_exception is not None:
            exception_class = safe_exception
        safe_failure_reason = _safe_mcp_failure_reason(trace.get("failure_reason"))
        if safe_failure_reason is not None:
            failure_reason = safe_failure_reason
    diagnostic: dict[str, Any] = {
        "call_count": min(len(call_traces), _MAX_MCP_CALLS_PER_TURN),
        "elapsed_ms": round(min(elapsed_ms, _MAX_UAT_TURN_SECONDS * 1000), 3),
        "status": statuses,
        "timeout": timeout,
    }
    if request_shape is not None:
        diagnostic["request_shape"] = request_shape
    if request_discriminator is not None:
        diagnostic["request_discriminator"] = request_discriminator
    if response_stage is not None:
        diagnostic["response_stage"] = response_stage
    if exception_class is not None:
        diagnostic["exception_class"] = exception_class
    if failure_reason is not None:
        diagnostic["failure_reason"] = failure_reason
    return diagnostic


def _diagnostic_with_mcp(
    provider_diagnostic: Mapping[str, Any] | None,
    call_traces: Sequence[Mapping[str, Any]],
    *,
    source_binding_fingerprint: str | None = None,
) -> dict[str, Any]:
    safe = _safe_provider_diagnostic(provider_diagnostic) or {}
    safe["mcp"] = _safe_mcp_call_diagnostic(call_traces)
    # Provider/public metadata never establishes service identity or source proof.
    safe.pop("source_binding_fingerprint", None)
    safe["diagnostic_comparability"] = diagnostic_comparability(
        safe, source_binding_fingerprint=source_binding_fingerprint,
    )
    source = safe["diagnostic_comparability"].get("source_binding_fingerprint")
    if source is not None:
        safe["source_binding_fingerprint"] = source
    return safe


def _with_mcp_diagnostic(
    result: Mapping[str, Any],
    call_traces: Sequence[Mapping[str, Any]],
    *,
    source_binding_fingerprint: str | None = None,
) -> dict[str, Any]:
    projected = dict(result)
    projected["diagnostic"] = _diagnostic_with_mcp(
        projected.get("diagnostic"), call_traces,
        source_binding_fingerprint=source_binding_fingerprint,
    )
    return projected


def _classify_mcp_failure_result(
    result: Mapping[str, Any],
    responses: Sequence[Mapping[str, Any]],
    call_traces: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Keep MCP failures distinct from valid empty/no-match evidence."""

    has_failure_status = any(
        isinstance(response, Mapping) and response.get("status") in _MCP_FAILURE_STATUSES
        for response in responses
    )
    has_failed_trace = any(
        isinstance(trace, Mapping)
        and (trace.get("status") in _MCP_FAILURE_STATUSES or trace.get("timeout") is True)
        for trace in call_traces
    )
    if not has_failure_status and not has_failed_trace:
        return dict(result)

    projected = dict(result)
    if not _response_citations((projected,)):
        projected.update(
            {
                "status": "error",
                "answer": _FAILED_TURN_ANSWER,
                "citations": [],
                "clarification": None,
            }
        )
    if call_traces:
        diagnostic = _safe_provider_diagnostic(projected.get("diagnostic")) or {}
        diagnostic["mcp"] = _safe_mcp_call_diagnostic(call_traces)
        projected["diagnostic"] = diagnostic
    return projected


def _conversation_identifier(session_id: str) -> str:
    return "issue56-uat-" + hashlib.sha256(session_id.encode()).hexdigest()[:48]


def _browser_request_fingerprint(session_id: str, prompt: str) -> str:
    # Join a fresh browser's request to the existing private Docker log window.
    # The random HttpOnly session is a salt; neither it nor the prompt is logged.
    # Repeated identical turns in one session also require the run timestamps.
    material = json.dumps([session_id, prompt], ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _is_browser_request_fingerprint(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _response_citations(responses: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return evidence_citation_ids(responses)


def _governed_mail_evidence_records(
    response: Mapping[str, Any],
    *,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    snippets = response.get("evidence_snippets")
    citations = response.get("citations")
    if (
        not isinstance(snippets, Sequence)
        or isinstance(snippets, (str, bytes))
        or not isinstance(citations, Sequence)
        or isinstance(citations, (str, bytes))
    ):
        return ()

    identity_fields = (
        "mail_import_session_id",
        "source_observation_id",
        "email_message_id",
        "message_occurrence_id",
    )
    citation_records: list[tuple[str, dict[str, str], str | None]] = []
    for citation in citations:
        if not isinstance(citation, Mapping):
            continue
        citation_id = citation.get("citation_id")
        if not isinstance(citation_id, str) or not citation_id.strip():
            citation_id = citation.get("citation_hash")
        if not isinstance(citation_id, str) or not citation_id.strip():
            continue
        identity = {
            field: value.strip()
            for field in identity_fields
            if isinstance(value := citation.get(field), str) and value.strip()
        }
        source_type = citation.get("source_type")
        if source_type is not None and (
            not isinstance(source_type, str) or not source_type.strip()
        ):
            continue
        citation_records.append((citation_id, identity, source_type))

    records: list[dict[str, Any]] = []
    for snippet in snippets:
        if len(records) >= max(0, limit):
            break
        if not isinstance(snippet, Mapping):
            continue
        snippet_text = snippet.get("snippet")
        if not isinstance(snippet_text, str) or not snippet_text.strip():
            continue
        identity = {
            field: value.strip()
            for field in identity_fields
            if isinstance(value := snippet.get(field), str) and value.strip()
        }
        source_type = snippet.get("source_type")
        if source_type is not None and (
            not isinstance(source_type, str) or not source_type.strip()
        ):
            continue
        for citation_id, citation_identity, citation_source_type in citation_records:
            shared_identity_fields = set(identity).intersection(citation_identity)
            if not shared_identity_fields or any(
                identity[field] != citation_identity[field] for field in shared_identity_fields
            ):
                continue
            if (
                source_type is not None
                and citation_source_type is not None
                and source_type != citation_source_type
            ):
                continue
            safe_record = {
                "snippet": snippet_text,
                "citation_id": citation_id,
            }
            try:
                assert_no_public_raw_references(
                    safe_record,
                    "issue56_governed_mail_evidence_record",
                )
            except ContractValidationError:
                continue
            records.append(safe_record)
            break
    return tuple(records)


def _governed_graph_evidence_records(
    response: Mapping[str, Any],
    *,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    """Keep only top-level graph snippets linked to this response's citations."""

    evidence = response.get("evidence")
    citations = response.get("citations")
    if (
        not isinstance(evidence, Sequence)
        or isinstance(evidence, (str, bytes))
        or not isinstance(citations, Sequence)
        or isinstance(citations, (str, bytes))
    ):
        return ()

    governed_citations: set[str] = set()
    for citation in citations:
        if isinstance(citation, str) and citation.strip():
            governed_citations.add(citation)
        elif isinstance(citation, Mapping):
            citation_hash = citation.get("citation_hash")
            if isinstance(citation_hash, str) and citation_hash.strip():
                governed_citations.add(citation_hash)

    records: list[dict[str, Any]] = []
    for item in evidence:
        if len(records) >= max(0, limit):
            break
        if not isinstance(item, Mapping):
            continue
        snippet = item.get("snippet")
        citation_hash = item.get("citation_hash")
        if (
            not isinstance(snippet, str)
            or not snippet.strip()
            or not isinstance(citation_hash, str)
            or not citation_hash.strip()
            or citation_hash not in governed_citations
        ):
            continue
        safe_record = {
            "snippet": snippet,
            "citation_id": citation_hash,
        }
        try:
            assert_no_public_raw_references(
                safe_record,
                "issue56_governed_graph_evidence_record",
            )
        except ContractValidationError:
            continue
        records.append(safe_record)
    return tuple(records)


def _preserved_current_turn_projection(
    outcome: UatConversationOutcome,
    responses: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    rows: dict[str, dict[str, Any]] = {}
    preserved_evidence_count = 0
    for response in responses:
        response_citations = set(_response_citations((response,)))
        if not response_citations:
            continue
        mail_records = _governed_mail_evidence_records(
            response,
            limit=_MAX_RETAINED_EVIDENCE_ITEMS - preserved_evidence_count,
        )
        for mail_record in mail_records:
            citation = mail_record["citation_id"]
            snippet = mail_record["snippet"]
            row_key = (
                "mail_snippet:" + hashlib.sha256((citation + "\0" + snippet).encode()).hexdigest()
            )
            rows.setdefault(
                row_key,
                {
                    "item_hash": None,
                    "values": [],
                    "snippet": snippet,
                    "citations": [citation],
                },
            )
            preserved_evidence_count += 1
        graph_records = _governed_graph_evidence_records(
            response,
            limit=_MAX_RETAINED_EVIDENCE_ITEMS - preserved_evidence_count,
        )
        for graph_record in graph_records:
            citation = graph_record["citation_id"]
            snippet = graph_record["snippet"]
            row_key = (
                "graph_snippet:" + hashlib.sha256((citation + "\0" + snippet).encode()).hexdigest()
            )
            rows.setdefault(
                row_key,
                {
                    "item_hash": None,
                    "values": [],
                    "snippet": snippet,
                    "citations": [citation],
                },
            )
            preserved_evidence_count += 1
        exact = response.get("exact_inventory")
        items = exact.get("items", ()) if isinstance(exact, Mapping) else ()
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            item_hash = item.get("item_hash")
            item_hash = item_hash if isinstance(item_hash, str) and item_hash else None
            raw_values = item.get("structured_values")
            has_structured_values = (
                isinstance(raw_values, Sequence)
                and not isinstance(raw_values, (str, bytes))
                and bool(raw_values)
            )
            values: list[tuple[str, str, str]] = []
            if has_structured_values:
                if item.get("structure_status") != "source_provided":
                    continue
                for value in raw_values:
                    if not isinstance(value, Mapping):
                        continue
                    field = value.get("field")
                    cell = value.get("value")
                    citation = value.get("citation_hash")
                    if (
                        isinstance(field, str)
                        and field.strip()
                        and isinstance(cell, str)
                        and isinstance(citation, str)
                        and citation in response_citations
                    ):
                        values.append((field, cell, citation))
                if not values:
                    continue
            item_citations = [
                citation
                for citation in evidence_citation_ids(item)
                if citation in response_citations
            ]
            if not values or not item_citations:
                continue
            row_key = (
                item_hash
                or "values:"
                + hashlib.sha256(
                    json.dumps(
                        values,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
            )
            row = rows.setdefault(
                row_key,
                {
                    "item_hash": item_hash,
                    "values": [],
                    "snippet": None,
                    "citations": [],
                },
            )
            for value in values:
                if value not in row["values"]:
                    row["values"].append(value)
            for citation in item_citations:
                if citation not in row["citations"]:
                    row["citations"].append(citation)
        query_agent = response.get("query_agent")
        context_bundle = (
            query_agent.get("context_bundle") if isinstance(query_agent, Mapping) else None
        )
        successful_subqueries = (
            context_bundle.get("successful_subqueries", ())
            if isinstance(context_bundle, Mapping)
            else ()
        )
        if not isinstance(successful_subqueries, Sequence) or isinstance(
            successful_subqueries,
            (str, bytes),
        ):
            continue
        for subquery in successful_subqueries:
            evidence = subquery.get("evidence", ()) if isinstance(subquery, Mapping) else ()
            if not isinstance(evidence, Sequence) or isinstance(
                evidence,
                (str, bytes),
            ):
                continue
            for item in evidence:
                if not isinstance(item, Mapping):
                    continue
                snippet = item.get("snippet")
                citation = item.get("citation_hash")
                if (
                    not isinstance(snippet, str)
                    or not snippet.strip()
                    or not isinstance(citation, str)
                    or citation not in response_citations
                ):
                    continue
                row_key = (
                    "snippet:" + hashlib.sha256((citation + "\0" + snippet).encode()).hexdigest()
                )
                rows.setdefault(
                    row_key,
                    {
                        "item_hash": None,
                        "values": [],
                        "snippet": snippet,
                        "citations": [citation],
                    },
                )

    if not rows:
        return None

    lines = ["模型最終答案未完成；以下直接顯示本回合授權來源已回傳且可引用的" "部分資料。"]
    citations: list[str] = []
    shown = 0
    for row in rows.values():
        if shown >= _MAX_PRESERVED_PROJECTION_ROWS:
            break
        if row["values"]:
            rendered_values = [
                f"{field}：{value if value else '（空白）'} [{citation}]"
                for field, value, citation in row["values"]
            ]
            line = f"{shown + 1}. " + "；".join(rendered_values)
        else:
            line = f"{shown + 1}. 來源摘錄：{row['snippet']} " f"[{row['citations'][0]}]"
        if len("\n".join((*lines, line))) > _MAX_PRESERVED_PROJECTION_CHARS:
            break
        lines.append(line)
        shown += 1
        for citation in row["citations"]:
            if citation not in citations:
                citations.append(citation)
    if not shown or not citations:
        return None
    coverage_limit = (
        f"涵蓋限制：本畫面直接呈現 {shown} 筆本回合可引用資料，" "未證明已完整涵蓋原始要求。"
    )
    if shown < len(rows):
        coverage_limit += f" 另有 {len(rows) - shown} 筆已回傳資料未在此畫面展開。"
    stop_reason = "\n".join(
        dict.fromkeys(
            value.strip() for value in (outcome.answer_text, outcome.coverage_note) if value.strip()
        )
    )
    return {
        "status": "partial",
        "answer": "\n".join(lines),
        "citations": citations,
        "clarification": f"{stop_reason}\n{coverage_limit}",
    }


def _browser_projection(
    outcome: UatConversationOutcome,
    responses: Sequence[Mapping[str, Any]],
    *,
    latest_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    safe_diagnostic = _safe_provider_diagnostic(outcome.provider_diagnostic)
    if safe_diagnostic is not None:
        # Provider outcomes never establish a validated source context.
        safe_diagnostic.pop("source_binding_fingerprint", None)
        safe_diagnostic["diagnostic_comparability"] = diagnostic_comparability(safe_diagnostic)

    def project(payload: dict[str, Any]) -> dict[str, Any]:
        if safe_diagnostic is not None:
            payload["diagnostic"] = safe_diagnostic
        return payload

    if (
        outcome.response_kind == "clarification"
        and safe_diagnostic is not None
        and safe_diagnostic.get("reason_code") in _SAFE_PROVIDER_FAILURE_REASONS
    ):
        preserved = _preserved_current_turn_projection(outcome, responses)
        if preserved is not None:
            return project(preserved)
        return project(
            {
                "status": "error",
                "answer": outcome.answer_text,
                "citations": [],
                "clarification": None,
            }
        )
    if outcome.response_kind == "clarification":
        preserved = _preserved_current_turn_projection(outcome, responses)
        if preserved is not None:
            return project(preserved)
        return project(
            {
                "status": "clarification_required",
                "answer": "",
                "citations": [],
                "clarification": outcome.answer_text,
            }
        )
    current_responses = list(responses)
    citation_evidence = list(current_responses)
    if latest_evidence is not None and (
        outcome.citation_ids or outcome.response_kind == "render_prior_evidence"
    ):
        citation_evidence.append(latest_evidence)
    if not citation_evidence and outcome.response_kind == "render_prior_evidence":
        if latest_evidence is None:
            raise ValueError("GPT requested unavailable prior evidence")
    available_citations = set(_response_citations(citation_evidence))
    citations = tuple(outcome.citation_ids)
    if not set(citations).issubset(available_citations):
        raise ValueError("GPT cited evidence that was not returned by MCP")
    if citation_evidence and not citations:
        preserved = _preserved_current_turn_projection(outcome, current_responses)
        if preserved is not None:
            return project(preserved)
        return project(
            {
                "status": "clarification_required",
                "answer": "",
                "citations": [],
                "clarification": outcome.answer_text,
            }
        )
    coverage_responses = [result for result in current_responses if evidence_citation_ids(result)]
    if not coverage_responses and current_responses:
        coverage_responses.append(current_responses[-1])
    elif not current_responses and latest_evidence is not None and citations:
        coverage_responses.append(latest_evidence)
    evidence_used = bool(coverage_responses)
    if (
        evidence_used
        and outcome.coverage_status == "complete"
        and _evidence_results_are_incomplete(coverage_responses)
    ):
        raise ValueError("GPT source-backed answer hid incomplete coverage")
    return project(
        {
            "status": (
                "complete"
                if not evidence_used or outcome.coverage_status == "complete"
                else "partial"
            ),
            "answer": outcome.answer_text,
            "citations": list(citations),
            "clarification": (
                outcome.coverage_note
                if evidence_used and outcome.coverage_status == "incomplete"
                else None
            ),
        }
    )


def _safe_current_turn_projection_after_validation_failure(
    outcome: UatConversationOutcome,
    responses: Sequence[Mapping[str, Any]],
    *,
    original_result: Mapping[str, Any],
    original_error: ContractValidationError,
    boundary: str,
) -> dict[str, Any]:
    """Recover only a validated current-turn evidence projection.

    Provider answer text and coverage notes are untrusted at the public
    boundary.  If they invalidate the ordinary projection, discard them
    before asking the existing governed-evidence projector to render the
    current turn.  A missing or invalid current-turn binding remains an
    error; prior evidence is intentionally not used here.
    """

    safe_outcome = replace(
        outcome,
        response_kind="clarification",
        answer_text="模型最終答案未完成。",
        citation_ids=(),
        coverage_status="incomplete",
        coverage_note="本回合僅保留已驗證且可引用的部分資料；答案仍不完整。",
        tool_requests=(),
        tool_results=(),
    )
    if _preserved_current_turn_projection(safe_outcome, responses) is None:
        raise original_error
    fallback = _browser_projection(
        safe_outcome,
        responses,
        latest_evidence=None,
    )
    fallback.pop("diagnostic", None)
    safe_diagnostic = _safe_provider_diagnostic(original_result.get("diagnostic"))
    if safe_diagnostic is not None:
        finalization = safe_diagnostic.get("finalization_validation")
        if isinstance(finalization, list):
            safe_diagnostic["finalization_validation"] = [
                {
                    **validation,
                    **(
                        {
                            "validation_result": "parse_rejected",
                        }
                        if validation.get("validation_result") == "passed"
                        else {}
                    ),
                }
                for validation in finalization
                if isinstance(validation, Mapping)
            ]
        fallback["diagnostic"] = safe_diagnostic
    validate_public_gateway_payload(fallback)
    assert_no_public_raw_references(fallback, boundary)
    _emit_private_uat_failure_trace(original_error, "projection", original_result)
    return fallback


def _advance_conversation_state(
    state: _ConversationState,
    *,
    prompt: str,
    result: Mapping[str, Any],
    outcome: UatConversationOutcome,
    responses: Sequence[Mapping[str, Any]],
) -> None:
    diagnostic = result.get("diagnostic")
    mcp_diagnostic = diagnostic.get("mcp") if isinstance(diagnostic, Mapping) else None
    if (
        result.get("status") == "error"
        and not responses
        and isinstance(mcp_diagnostic, Mapping)
        and mcp_diagnostic.get("call_count") == 0
    ):
        state.turns = (
            *state.turns,
            {
                "prompt": prompt,
                "response": _stored_browser_response(result),
            },
        )[-_MAX_CONVERSATION_TURNS:]
        return

    projected_answer = result.get("answer")
    assistant_content = (
        projected_answer
        if isinstance(projected_answer, str) and projected_answer.strip()
        else outcome.answer_text
    )
    state.history = (
        *state.history,
        UatConversationMessage(role="user", content=prompt),
        UatConversationMessage(
            role="assistant",
            content=assistant_content[:_MAX_CONVERSATION_MESSAGE_CHARS],
        ),
    )[-_MAX_CONVERSATION_HISTORY_MESSAGES:]
    state.turns = (
        *state.turns,
        {
            "prompt": prompt,
            "response": _stored_browser_response(result),
        },
    )[-_MAX_CONVERSATION_TURNS:]
    if responses:
        prior_sources: tuple[Mapping[str, Any], ...] = ()
        if state.latest_evidence is not None:
            prior_results = state.latest_evidence.get("results", ())
            if isinstance(prior_results, Sequence) and not isinstance(
                prior_results,
                (str, bytes),
            ):
                prior_sources = tuple(
                    result for result in prior_results if isinstance(result, Mapping)
                )
        evidence_sources = (
            *prior_sources,
            *responses,
        )
        retained_evidence = _retained_authorized_evidence(
            outcome,
            evidence_sources,
            prevalidated_response_count=len(prior_sources),
        )
        if retained_evidence is not None:
            state.latest_evidence = retained_evidence


def _stored_browser_response(result: Mapping[str, Any]) -> dict[str, Any]:
    citations = result.get("citations", ())
    stored = {
        "status": result.get("status"),
        "answer": result.get("answer"),
        "citations": (
            [citation for citation in citations if isinstance(citation, str)]
            if isinstance(citations, Sequence) and not isinstance(citations, (str, bytes))
            else []
        ),
        "clarification": result.get("clarification"),
    }
    diagnostic = _safe_provider_diagnostic(result.get("diagnostic"))
    if diagnostic is not None:
        stored["diagnostic"] = diagnostic
    return stored


def _conversation_projection(state: _ConversationState) -> dict[str, Any]:
    return {
        "turns": [
            {
                "prompt": turn["prompt"],
                "response": dict(turn["response"]),
            }
            for turn in state.turns
        ],
    }


def _record_failed_conversation_turn(
    state: _ConversationState,
    *,
    prompt: str,
    previous_history: tuple[UatConversationMessage, ...],
    previous_evidence: Mapping[str, Any] | None,
    previous_turns: tuple[Mapping[str, Any], ...],
) -> None:
    state.history = previous_history
    state.latest_evidence = previous_evidence
    state.turns = (
        *previous_turns,
        {
            "prompt": prompt,
            "response": {
                "status": "error",
                "answer": _FAILED_TURN_ANSWER,
                "citations": [],
                "clarification": None,
                "diagnostic": {
                    "diagnostic_comparability": diagnostic_comparability(None),
                },
            },
        },
    )[-_MAX_CONVERSATION_TURNS:]


def _retained_authorized_evidence(
    outcome: UatConversationOutcome,
    responses: Sequence[Mapping[str, Any]],
    *,
    prevalidated_response_count: int = 0,
) -> Mapping[str, Any] | None:
    prevalidated_response_count = max(
        0,
        min(prevalidated_response_count, len(responses)),
    )
    prior_citations = evidence_citation_ids(
        responses[:prevalidated_response_count],
    )
    required_citations = tuple(
        dict.fromkeys((*prior_citations, *outcome.citation_ids)),
    )
    if not required_citations:
        required_citations = evidence_citation_ids(responses)
    if not required_citations:
        return None
    required_set = set(required_citations)
    retained_payloads: list[dict[str, Any]] = []
    available_citations: set[str] = set()
    for response_index, response in enumerate(responses):
        compact = compact_evidence_for_model(
            response,
            item_limit=_MAX_RETAINED_EVIDENCE_ITEMS,
        )
        if response_index < prevalidated_response_count:
            # A retained envelope has already removed mail selectors and
            # identity fields.  Revalidate only its bounded snippet-to-
            # citation link instead of routing it through the raw MCP
            # identity matcher a second time.
            mail_records = _prevalidated_mail_evidence_records(
                response,
                limit=_MAX_RETAINED_EVIDENCE_ITEMS,
            )
        else:
            mail_records = _governed_mail_evidence_records(
                response,
                limit=_MAX_RETAINED_EVIDENCE_ITEMS,
            )
        if mail_records:
            compact["evidence_snippets"] = list(mail_records)
            compact["citations"] = [
                {"citation_id": record["citation_id"]} for record in mail_records
            ]
        else:
            compact.pop("evidence_snippets", None)
        response_citations = set(_response_citations((compact,)))
        exact = compact.get("exact_inventory")
        items = exact.get("items", ()) if isinstance(exact, Mapping) else ()
        results = compact.get("results", ())
        evidence_snippets = compact.get("evidence_snippets")
        query_agent = compact.get("query_agent")
        context_bundle = (
            query_agent.get("context_bundle") if isinstance(query_agent, Mapping) else None
        )
        has_items = (
            isinstance(items, Sequence) and not isinstance(items, (str, bytes)) and bool(items)
        )
        has_results = (
            isinstance(results, Sequence)
            and not isinstance(results, (str, bytes))
            and bool(results)
        )
        has_mail_snippets = (
            isinstance(evidence_snippets, Sequence)
            and not isinstance(evidence_snippets, (str, bytes))
            and bool(evidence_snippets)
        )
        supported_citations = required_set.intersection(response_citations)
        if not supported_citations or not (
            compact.get("answer") or has_items or has_results or has_mail_snippets or context_bundle
        ):
            continue
        retained_payloads.append(compact)
        available_citations.update(supported_citations)
        if len(retained_payloads) >= _MAX_RETAINED_EVIDENCE_ITEMS:
            break
    if not retained_payloads:
        return None

    return {
        "status": "partial",
        "coverage": {
            "status": "incomplete",
            "coverage_status": "incomplete",
        },
        "citations": [
            citation for citation in required_citations if citation in available_citations
        ],
        "results": retained_payloads,
    }


def _prevalidated_mail_evidence_records(
    response: Mapping[str, Any],
    *,
    limit: int,
) -> tuple[dict[str, str], ...]:
    """Re-check already-redacted mail snippets when carrying state forward."""

    snippets = response.get("evidence_snippets")
    citations = response.get("citations")
    if (
        not isinstance(snippets, Sequence)
        or isinstance(snippets, (str, bytes))
        or not isinstance(citations, Sequence)
        or isinstance(citations, (str, bytes))
    ):
        return ()
    citation_ids: set[str] = set()
    for citation in citations:
        if isinstance(citation, str) and citation.strip():
            citation_ids.add(citation)
        elif isinstance(citation, Mapping):
            citation_id = citation.get("citation_id")
            if not isinstance(citation_id, str) or not citation_id.strip():
                citation_id = citation.get("citation_hash")
            if isinstance(citation_id, str) and citation_id.strip():
                citation_ids.add(citation_id)
    if not citation_ids:
        return ()

    records: list[dict[str, str]] = []
    for snippet in snippets:
        if len(records) >= max(0, limit):
            break
        if not isinstance(snippet, Mapping):
            continue
        snippet_text = snippet.get("snippet")
        citation_id = snippet.get("citation_id")
        if (
            not isinstance(snippet_text, str)
            or not snippet_text.strip()
            or not isinstance(citation_id, str)
            or not citation_id.strip()
            or citation_id not in citation_ids
        ):
            continue
        safe_record = {
            "snippet": snippet_text,
            "citation_id": citation_id,
        }
        try:
            assert_no_public_raw_references(
                safe_record,
                "issue56_prevalidated_mail_evidence_record",
            )
        except ContractValidationError:
            continue
        records.append(safe_record)
    return tuple(records)


def _failure_sha256(exc: Exception) -> str:
    material = f"{type(exc).__name__}:{exc}".encode("utf-8", errors="replace")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _mcp_request_shape(request: UatEvidenceToolRequest) -> dict[str, bool]:
    return {
        "request_contract_present": request.request_contract is not None,
        "table_query_present": request.table_query is not None,
        "exact_field_present": request.exact_field is not None,
        "exact_inventory_kind_present": request.exact_inventory_kind is not None,
        "page_size_present": request.page_size is not None,
        "cursor_present": request.cursor is not None,
    }


def _safe_mcp_exception_class(exc: Exception) -> str:
    exception_class = type(exc).__name__
    if 0 < len(exception_class) <= 64 and all(
        character.isalnum() or character in {"_", "-"} for character in exception_class
    ):
        return exception_class
    return "mcp_exception"


def _safe_mcp_exception_owner(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    module = value.get("module")
    symbol = value.get("symbol")
    line = value.get("line")
    if (
        not isinstance(module, str)
        or not module.startswith("formowl_")
        or not 0 < len(module) <= 128
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_."
            for character in module
        )
        or not isinstance(symbol, str)
        or not 0 < len(symbol) <= 128
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.<>$-"
            for character in symbol
        )
        or type(line) is not int
        or not 1 <= line <= 1_000_000
    ):
        return None
    return {"module": module, "symbol": symbol, "line": line}


def _safe_exception_owner_from_exception(
    exception: BaseException,
) -> dict[str, Any] | None:
    owner: dict[str, Any] | None = None
    for frame, line in traceback.walk_tb(exception.__traceback__):
        module = frame.f_globals.get("__name__")
        symbol = frame.f_code.co_qualname
        candidate = _safe_mcp_exception_owner(
            {
                "module": module,
                "symbol": symbol,
                "line": line,
            }
        )
        if candidate is not None:
            owner = candidate
    return owner


def _private_mcp_owner_trace(
    trace: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Retain safe gateway owner metadata outside the public result."""

    owner = _safe_mcp_exception_owner(trace.get("exception_owner"))
    if owner is None:
        return None
    private: dict[str, Any] = {"exception_owner": owner}
    request_hash = trace.get("browser_request_sha256")
    call_index = trace.get("mcp_call_index")
    if (
        _is_browser_request_fingerprint(request_hash)
        and type(call_index) is int
        and 1 <= call_index <= _MAX_MCP_CALLS_PER_TURN
    ):
        private["browser_request_sha256"] = request_hash
        private["mcp_call_index"] = call_index
    exception_class = _safe_mcp_exception_name(trace.get("exception_class"))
    if exception_class is not None:
        private["exception_class"] = exception_class
    response_stage = _safe_mcp_response_stage(trace.get("response_stage"))
    if response_stage is not None:
        private["response_stage"] = response_stage
    failure_reason = _safe_mcp_failure_reason(trace.get("failure_reason"))
    if failure_reason is not None:
        private["failure_reason"] = failure_reason
    request_discriminator = _safe_mcp_request_discriminator(trace.get("request_discriminator"))
    if request_discriminator is not None:
        private["request_discriminator"] = request_discriminator
    request_shape = _safe_mcp_request_shape(trace.get("request_shape"))
    if request_shape is not None:
        private["request_shape"] = request_shape
    return private


def _private_mail_recheck_trace(
    trace: Mapping[str, Any],
    validated_response: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Project only safe, allowlisted mail-recheck diagnostics."""

    if (
        validated_response is None
        or trace.get("response_stage") != "payload_validated"
    ):
        return None
    request_discriminator = _safe_mcp_request_discriminator(
        trace.get("request_discriminator")
    )
    if (
        request_discriminator is None
        or request_discriminator.get("tool_name") != "query_mail_evidence"
    ):
        return None
    status = validated_response.get("status")
    warnings = validated_response.get("warnings")
    if (
        not isinstance(status, str)
        or status not in _SAFE_MAIL_RECHECK_STATUSES
        or not isinstance(warnings, Sequence)
        or isinstance(warnings, (str, bytes))
    ):
        return None
    safe_warnings = sorted(
        {
            warning
            for warning in warnings
            if isinstance(warning, str)
            and warning in _SAFE_MAIL_RECHECK_WARNING_CODES
        }
    )
    browser_request_sha256 = trace.get("browser_request_sha256")
    call_index = trace.get("mcp_call_index")
    query_hash = trace.get("query_hash")
    citation_count = trace.get("citation_count")
    selector_hash = request_discriminator.get("selector_hash")
    query_text_char_count = request_discriminator.get("query_text_char_count")
    required_term_count = request_discriminator.get("required_term_count")
    required_terms_fingerprint = request_discriminator.get("required_terms_fingerprint")
    if (
        not safe_warnings
        or not _is_browser_request_fingerprint(browser_request_sha256)
        or type(call_index) is not int
        or not 1 <= call_index <= _MAX_MCP_CALLS_PER_TURN
        or not _is_browser_request_fingerprint(query_hash)
        or type(citation_count) is not int
        or citation_count < 0
        or not _is_browser_request_fingerprint(selector_hash)
        or type(query_text_char_count) is not int
    ):
        return None
    safe = {
        "status": status,
        "citation_count": citation_count,
        "browser_request_sha256": browser_request_sha256,
        "mcp_call_index": call_index,
        "query_hash": query_hash,
        "selector_hash": selector_hash,
        "query_text_char_count": query_text_char_count,
        "recheck_warnings": safe_warnings,
    }
    if required_term_count is not None:
        safe["required_term_count"] = required_term_count
        safe["required_terms_fingerprint"] = required_terms_fingerprint
    return safe


def _private_graph_recheck_trace(
    trace: Mapping[str, Any],
    validated_response: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Expose existing graph recovery diagnostics, never evidence or raw IDs."""

    discriminator = _safe_mcp_request_discriminator(trace.get("request_discriminator"))
    if (
        validated_response is None or trace.get("response_stage") != "payload_validated"
        or discriminator is None
        or discriminator["tool_name"] != "query_effective_graph_view"
        or not _is_browser_request_fingerprint(trace.get("browser_request_sha256"))
        or not _is_browser_request_fingerprint(trace.get("query_hash"))
        or type(trace.get("mcp_call_index")) is not int
        or not 1 <= trace["mcp_call_index"] <= _MAX_MCP_CALLS_PER_TURN
        or type(trace.get("citation_count")) is not int
        or trace["citation_count"] < 0
    ):
        return None
    agent = validated_response.get("query_agent")
    context = agent.get("context_bundle") if isinstance(agent, Mapping) else None
    recovery = context.get("source_recovery") if isinstance(context, Mapping) else None
    safe = {
        key: trace[key] for key in (
            "browser_request_sha256", "mcp_call_index", "query_hash", "citation_count",
        )
    }
    for key in (
        "query_text_char_count",
        "required_term_count",
        "required_terms_fingerprint",
    ):
        if key in discriminator:
            safe[key] = discriminator[key]
    safe["recovery_present"] = isinstance(recovery, Mapping)
    safe_statuses = {
        "ok", "not_found", "no_answer", "partial", "incomplete", "pending_review",
        "replan_required", "unsupported", "permission_denied", "error",
    }
    status = validated_response.get("status")
    if isinstance(status, str) and status in safe_statuses:
        safe["status"] = status
    if not isinstance(recovery, Mapping):
        return safe
    for key in ("initial_status", "status"):
        value = recovery.get(key)
        if isinstance(value, str) and value in safe_statuses:
            safe[f"recovery_{key}"] = value
    if type(recovery.get("attempted")) is bool:
        safe["attempted"] = recovery["attempted"]
    families = recovery.get("source_families")
    if isinstance(families, (list, tuple)):
        safe["source_families"] = sorted({
            family for family in families
            if isinstance(family, str) and family in {"mail", "document_text"}
        })
    warnings = recovery.get("warnings")
    if isinstance(warnings, (list, tuple)):
        safe["recheck_warnings"] = sorted({
            warning for warning in warnings if isinstance(warning, str) and warning in {
                "used", "incomplete", "complete_no_match", "complete_coverage_incomplete",
                "unavailable", "skipped_exact", "skipped_replan", "skipped_invalid_plan",
                "skipped_zero_limit",
            }
        })
    scan = recovery.get("scan")
    if isinstance(scan, Mapping):
        count, complete, reason = (
            scan.get("scanned_observation_count"), scan.get("complete"), scan.get("stop_reason"),
        )
        if type(count) is int and 0 <= count <= 8192:
            safe["scanned_observation_count"] = count
        if type(complete) is bool:
            safe["scan_complete"] = complete
        if reason is None or (
            isinstance(reason, str)
            and reason in {"deadline", "observation_limit", "callback", "source_reference_unavailable"}
        ):
            safe["scan_stop_reason"] = reason
    for key in ("recovery_fingerprint", "source_authority_fingerprint", "source_session_binding_fingerprint"):
        if _is_browser_request_fingerprint(recovery.get(key)):
            safe[key] = recovery[key]
    return safe


def _emit_private_uat_terminal_trace(
    phase: str,
    *,
    started_at: float,
    outcome: UatConversationOutcome | None = None,
    result: Mapping[str, Any] | None = None,
    mcp_call_count: int = 0,
    failure_class: str | None = None,
) -> None:
    """Best-effort metadata only; independent of raw logging and HTTP delivery."""
    try:
        if phase not in {"provider", "turn"}:
            return
        status = (
            outcome.response_kind if phase == "provider" and outcome is not None
            else result.get("status") if result is not None else "error"
        )
        if phase == "turn" and failure_class is not None:
            status = "error"
        payload: dict[str, Any] = {
            "event": f"issue56_private_uat_{phase}_terminal_trace",
            "status": status if isinstance(status, str) and status in {
                "answer", "clarification", "render_prior_evidence", "ok", "complete",
                "partial", "clarification_required", "error",
            } else "unknown",
        }
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        # A terminal event may occur after the turn budget; do not hide overruns.
        if math.isfinite(elapsed_ms) and elapsed_ms >= 0:
            payload["elapsed_ms"] = round(elapsed_ms, 3)
        if (
            isinstance(mcp_call_count, int) and not isinstance(mcp_call_count, bool)
            and 0 <= mcp_call_count <= _MAX_MCP_CALLS_PER_TURN
        ):
            payload["mcp_call_count"] = mcp_call_count
        if isinstance(failure_class, str) and failure_class in {
            "mcp_timeout", "provider_timeout", "provider_model", "mcp_client",
            "projection", "session_state", "runtime_init",
        }:
            payload["failure_class"] = failure_class
        safe = _safe_provider_diagnostic(
            outcome.provider_diagnostic if outcome is not None else None,
        ) or {}
        diagnostic = {
            key: safe[key] for key in (
                "provider_status", "provider_attempt_count", "provider_attempts_valid",
                "provider_phase_timings", "mcp_citation_stages", "finalization_validation",
                "stop_reason",
            ) if key in safe
        }
        if safe.get("reason_code") in _SAFE_PROVIDER_FAILURE_REASONS | {"turn_budget_exhausted"}:
            diagnostic["reason_code"] = safe["reason_code"]
        if "provider_attempts" in safe:
            diagnostic["provider_attempts"] = [
                {key: attempt[key] for key in (
                    "attempt", "elapsed_ms", "outcome", "response_status",
                    "function_call_count", "valid_attempt",
                ) if key in attempt}
                for attempt in safe["provider_attempts"]
            ]
        payload["provider_diagnostic"] = diagnostic
        assert_no_public_raw_references(payload, "issue56_private_uat_terminal_trace")
        print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)
    except Exception:
        # Diagnostics must never replace a result or the original exception.
        pass


def _emit_private_uat_failure_trace(
    exception: Exception, phase: str, result: Mapping[str, Any] | None,
) -> None:
    """Keep projection failures diagnosable without retaining provider text."""
    rejected_fields = []
    if isinstance(result, Mapping):
        for field in ("answer", "clarification", "diagnostic"):
            try:
                validate_public_gateway_payload({field: result.get(field)})
                assert_no_public_raw_references({field: result.get(field)})
            except ContractValidationError:
                rejected_fields.append(field)
    payload = {
        "event": "issue56_private_uat_failure_trace",
        "phase": phase if phase in {
            "provider_model", "mcp_client", "projection", "session_state", "runtime_init",
        } else "unknown",
        "exception_class": _safe_mcp_exception_class(exception),
        "exception_owner": _safe_exception_owner_from_exception(exception),
        "rejected_fields": rejected_fields,
    }
    assert_no_public_raw_references(payload, "issue56_private_uat_failure_trace")
    print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)


def _emit_private_mcp_owner_trace(
    trace: Mapping[str, Any],
    *,
    validated_response: Mapping[str, Any] | None = None,
) -> None:
    """Emit allowlisted MCP failure and source-recheck metadata to private stderr."""

    private = _private_mcp_owner_trace(trace)
    if private is not None:
        payload = {
            "event": "issue56_private_mcp_owner_trace",
            **private,
        }
        assert_no_public_raw_references(payload, "issue56_private_mcp_owner_trace")
        print(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )
    mail_recheck = _private_mail_recheck_trace(trace, validated_response)
    if mail_recheck is not None:
        payload = {
            "event": "issue56_private_mail_recheck_trace",
            **mail_recheck,
        }
        assert_no_public_raw_references(payload, "issue56_private_mail_recheck_trace")
        print(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )
    graph_recheck = _private_graph_recheck_trace(trace, validated_response)
    if graph_recheck is not None:
        payload = {"event": "issue56_private_graph_recheck_trace", **graph_recheck}
        assert_no_public_raw_references(payload, "issue56_private_graph_recheck_trace")
        print(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )


def _build_call_trace(
    *,
    query_text: str,
    table_query: Mapping[str, Any] | None,
    request_shape: Mapping[str, bool],
    request_discriminator: Mapping[str, Any],
    data: Mapping[str, Any],
    response_status: int | None,
    failure_sha256: str | None,
    exception_class: str | None,
    failure_reason: str | None,
    response_stage: str,
    elapsed_ms: float,
    timeout: bool,
    exception_owner: Mapping[str, Any] | None,
    include_query_text: bool,
) -> dict[str, Any]:
    exact = data.get("exact_inventory")
    items = exact.get("items", ()) if isinstance(exact, Mapping) else ()
    item_count = (
        len(items) if isinstance(items, Sequence) and not isinstance(items, (str, bytes)) else 0
    )
    returned_count = exact.get("returned_count") if isinstance(exact, Mapping) else None
    results = data.get("results", ())
    result_count = (
        int(returned_count)
        if isinstance(returned_count, int) and not isinstance(returned_count, bool)
        else (
            len(results)
            if isinstance(results, Sequence) and not isinstance(results, (str, bytes))
            else item_count
        )
    )
    query_agent = data.get("query_agent")
    raw_subqueries = query_agent.get("subqueries", ()) if isinstance(query_agent, Mapping) else ()
    subquery_traces: list[dict[str, Any]] = []
    if isinstance(raw_subqueries, Sequence) and not isinstance(
        raw_subqueries,
        (str, bytes),
    ):
        for subquery in raw_subqueries[:_MAX_TRACE_SUBQUERIES]:
            if not isinstance(subquery, Mapping):
                continue
            subquery_traces.append(
                {
                    "validation_status": subquery.get("validation_status"),
                    "coverage_status": subquery.get("coverage_status"),
                    "rejection_sha256": subquery.get("rejection_fingerprint"),
                }
            )
    trace = {
        "query_hash": "sha256:" + hashlib.sha256(query_text.encode("utf-8")).hexdigest(),
        "query_length": len(query_text),
        "status": data.get("status", "unknown"),
        "http_status": response_status,
        "result_count": result_count,
        "citation_count": len(_response_citations((data,))),
        "item_count": item_count,
        "subqueries": subquery_traces,
        "failure_sha256": failure_sha256,
        "exception_class": exception_class,
        "failure_reason": failure_reason,
        "request_shape": dict(request_shape),
        "request_discriminator": dict(request_discriminator),
        "response_stage": response_stage,
        "timeout": timeout,
        "timings_ms": {
            "mcp_call": round(max(0.0, elapsed_ms), 3),
        },
    }
    safe_owner = _safe_mcp_exception_owner(exception_owner)
    if safe_owner is not None:
        trace["exception_owner"] = safe_owner
    if table_query is not None:
        trace["table_query_hash"] = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    table_query,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
    if include_query_text:
        trace["query_text"] = query_text
    return trace


async def create_issue56_uat_query_service(
    conversation_model: UatConversationModel,
    environment: Mapping[str, str] | None = None,
    *,
    public_base_url: str | None = None,
    http_client: Any | None = None,
) -> Issue56UatQueryService:
    """Compose the existing zero-argument production runtime."""

    resolved = dict(os.environ if environment is None else environment)
    resolved_public_base_url = public_base_url or resolved.get(_PUBLIC_BASE_URL_ENV)
    if not resolved_public_base_url:
        raise RuntimeError("issue56_uat_public_base_url_required")
    config = ConnectedRuntimeConfig.from_env_and_secrets(resolved)
    _browser_callback_url(config, resolved_public_base_url)
    runtime = await ConnectedRuntime.compose(config, http_client=http_client)
    return Issue56UatQueryService(
        runtime,
        public_base_url=resolved_public_base_url,
        conversation_model=conversation_model,
    )


def create_issue56_temporary_lan_query_service(
    conversation_model: UatConversationModel,
    *,
    behavior_log_path: Path | None = None,
    record_raw_uat_interactions: bool = False,
    ingestion_revision: Any | None = None,
    query_agent_planner: Any | None = None,
) -> Issue56TemporaryLanQueryService:
    """Compose one reusable real-source diagnostic app without external services.

    ``query_agent_planner`` is an explicit diagnostic seam for a pinned,
    already-validated adaptive plan.  It is passed to the existing production
    handler only when supplied; the shared source recheck still receives the
    underlying execution status and independently rejects replan, exact,
    unsupported, denied, and error outcomes.
    """

    retrieval_handler, mail_evidence_handler = build_issue56_production_semantic_handlers(
        **(
            {
                **(
                    {"ingestion_revision": ingestion_revision}
                    if ingestion_revision is not None
                    else {}
                ),
                **(
                    {"query_agent_planner": query_agent_planner}
                    if query_agent_planner is not None
                    else {}
                ),
            }
        )
    )
    # Only the explicitly supplied revision has a validated binding seam here.
    # Do not reopen the source or guess from handlers, disk, or provider fields.
    source_binding_fingerprint = None
    if ingestion_revision is not None:
        safe_binding = deepcopy(dict(ingestion_revision.safe_binding))
        source_binding_fingerprint = sha256_json(safe_binding)
    config = Issue56DiagnosticConfig()
    state = Issue56DiagnosticState()
    google_client = object()
    bridge = Issue56DiagnosticOAuthBridge(
        config=config,
        google_client=google_client,
        state=state,
    )
    application = create_connected_mcp_application(
        bridge=bridge,
        config=config,
        google_client=google_client,
        semantic_gateway=SemanticMcpGateway(
            retrieval_handler=retrieval_handler,
            mail_evidence_handler=mail_evidence_handler,
        ),
        oauth_route_provider=lambda **_kwargs: (),
        environ={"FORMOWL_AUTH_MODE": "oauth_google"},
    )
    return Issue56TemporaryLanQueryService(
        application,
        conversation_model=conversation_model,
        behavior_log_path=behavior_log_path,
        record_raw_uat_interactions=record_raw_uat_interactions,
        _source_binding_fingerprint=source_binding_fingerprint,
    )
