"""Thin real-source browser UAT adapter for the normal Issue #56 MCP route."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from threading import RLock
import time
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

from starlette.testclient import TestClient

from formowl_contract import assert_no_public_raw_references
from formowl_mail.human_uat_orchestrator import (
    UatConversationModel,
    UatConversationOutcome,
    UatEvidenceToolRequest,
)

from .issue56_diagnostic import (
    _SYNTHETIC_BEARER,
    Issue56DiagnosticConfig,
    Issue56DiagnosticOAuthBridge,
    Issue56DiagnosticState,
    mcp_headers,
    mcp_query_request,
)
from .issue56_sealed_source_loader import (
    build_issue56_production_semantic_retrieval_handler,
)
from .remote import ConnectedMcpApplication, create_connected_mcp_application
from .runtime import ConnectedRuntime, ConnectedRuntimeConfig
from .semantic import SemanticMcpGateway, validate_public_gateway_payload


_PUBLIC_BASE_URL_ENV = "FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL"
_MAX_BROWSER_AUTH_RECORDS = 64
_MAX_MCP_CALLS_PER_TURN = 3


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
        self._conversation_model = conversation_model
        self._lock = RLock()
        self._pending: dict[str, tuple[str, str, float]] = {}
        self._sessions: dict[str, tuple[str, float]] = {}
        self.request_count = 0
        self.last_mcp_statuses: tuple[str, ...] = ()

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
            _bounded_insert(
                self._sessions,
                session_id,
                (bearer, time.monotonic() + max_age),
            )
            return session_id, max_age

    def is_browser_session_authenticated(self, session_id: str | None) -> bool:
        with self._lock:
            return self._browser_bearer(session_id) is not None

    def logout_browser_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)

    def ask(self, prompt: str, *, session_id: str | None) -> Mapping[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        with self._lock:
            bearer = self._browser_bearer(session_id)
            if bearer is None:
                raise PermissionError("auth_required")
            self.request_count = 0
            result, responses = _run_gpt_query_agent(
                self._conversation_model,
                prompt=prompt,
                safety_identifier=_conversation_identifier(session_id),
                mcp_call=lambda query_text: self._call(query_text, bearer=bearer),
            )
            self.last_mcp_statuses = tuple(
                str(response.get("status", "unknown")) for response in responses
            )
            validate_public_gateway_payload(result)
            assert_no_public_raw_references(result, "issue56_uat_browser_result")
            return result

    def _call(self, query_text: str, *, bearer: str) -> Mapping[str, Any]:
        self.request_count += 1
        response = self._client.post(
            "/mcp",
            headers=mcp_headers(bearer=bearer),
            json=mcp_query_request(query_text),
        )
        envelope = response.json()
        result = envelope.get("result") if isinstance(envelope, Mapping) else None
        structured = (
            result.get("structuredContent")
            if isinstance(result, Mapping) and result.get("isError") is not True
            else None
        )
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
    ) -> None:
        if (behavior_log_path is None) != (not record_raw_uat_interactions):
            raise ValueError("raw UAT recording requires both explicit options")
        self._client_context = TestClient(
            application.app,
            raise_server_exceptions=False,
        )
        self._client = self._client_context.__enter__()
        self._conversation_model = conversation_model
        self._lock = RLock()
        self._behavior_log_path = behavior_log_path
        self.request_count = 0
        self.last_mcp_statuses: tuple[str, ...] = ()

    def __enter__(self) -> Issue56TemporaryLanQueryService:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        context = getattr(self, "_client_context", None)
        if context is not None:
            self._client_context = None
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

    def is_browser_session_authenticated(self, session_id: str | None) -> bool:
        del session_id
        return True

    def logout_browser_session(self, session_id: str | None) -> None:
        del session_id

    def ask(self, prompt: str, *, session_id: str | None) -> Mapping[str, Any]:
        del session_id
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        with self._lock:
            started_at = time.perf_counter()
            self.request_count = 0
            result, responses = _run_gpt_query_agent(
                self._conversation_model,
                prompt=prompt,
                safety_identifier="issue56-temporary-lan",
                mcp_call=self._call,
            )
            self.last_mcp_statuses = tuple(
                str(response.get("status", "unknown")) for response in responses
            )
            validate_public_gateway_payload(result)
            assert_no_public_raw_references(result, "issue56_temporary_lan_browser_result")
            if self._behavior_log_path is not None:
                _append_behavior_log(
                    self._behavior_log_path,
                    prompt=prompt,
                    result=result,
                    request_count=self.request_count,
                    statuses=self.last_mcp_statuses,
                    elapsed_ms=(time.perf_counter() - started_at) * 1_000.0,
                )
            return result

    def _call(self, query_text: str) -> Mapping[str, Any]:
        self.request_count += 1
        response = self._client.post(
            "/mcp",
            headers=mcp_headers(bearer=_SYNTHETIC_BEARER),
            json=mcp_query_request(query_text),
        )
        envelope = response.json()
        result = envelope.get("result") if isinstance(envelope, Mapping) else None
        structured = (
            result.get("structuredContent")
            if isinstance(result, Mapping) and result.get("isError") is not True
            else None
        )
        data = structured.get("data") if isinstance(structured, Mapping) else None
        if response.status_code != 200 or not isinstance(data, Mapping):
            return {"status": "mcp_failed", "citations": []}
        validate_public_gateway_payload(data)
        return data


def _append_behavior_log(
    path: Path,
    *,
    prompt: str,
    result: Mapping[str, Any],
    request_count: int,
    statuses: Sequence[str],
    elapsed_ms: float,
) -> None:
    visible_result = {
        key: result.get(key) for key in ("status", "answer", "clarification", "citations")
    }
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "result": visible_result,
        "request_count": request_count,
        "mcp_statuses": list(statuses),
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


def _run_gpt_query_agent(
    conversation_model: UatConversationModel,
    *,
    prompt: str,
    safety_identifier: str,
    mcp_call: Callable[[str], Mapping[str, Any]],
) -> tuple[dict[str, Any], tuple[Mapping[str, Any], ...]]:
    responses: list[Mapping[str, Any]] = []

    def evidence_tool(request: UatEvidenceToolRequest) -> Mapping[str, Any]:
        if len(responses) >= _MAX_MCP_CALLS_PER_TURN:
            raise RuntimeError("UAT Query Agent exceeded the MCP call budget")
        data = mcp_call(request.query_text)
        responses.append(data)
        return data

    outcome = conversation_model.respond(
        history=(),
        user_text=prompt,
        latest_evidence=None,
        safety_identifier=safety_identifier,
        evidence_tool=evidence_tool,
    )
    return _browser_projection(outcome, responses), tuple(responses)


def _conversation_identifier(session_id: str) -> str:
    return "issue56-uat-" + hashlib.sha256(session_id.encode()).hexdigest()[:48]


def _item_references(item: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    citations: set[str] = set()
    lineages: set[str] = set()
    references = item.get("governed_references", ())
    if isinstance(references, Sequence) and not isinstance(references, (str, bytes)):
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            citation = reference.get("citation_hash")
            lineage = reference.get("occurrence_lineage_fingerprint")
            if isinstance(citation, str):
                citations.add(citation)
            if isinstance(lineage, str):
                lineages.add(lineage)
    values = item.get("structured_values", ())
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        for value in values:
            if not isinstance(value, Mapping):
                continue
            citation = value.get("citation_hash")
            lineage = value.get("occurrence_lineage_fingerprint")
            if isinstance(citation, str):
                citations.add(citation)
            if isinstance(lineage, str):
                lineages.add(lineage)
    return citations, lineages


def _response_citations(responses: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    citations: set[str] = set()
    for data in responses:
        raw_citations = data.get("citations", ())
        if isinstance(raw_citations, Sequence) and not isinstance(
            raw_citations,
            (str, bytes),
        ):
            citations.update(value for value in raw_citations if isinstance(value, str))
        exact = data.get("exact_inventory")
        items = exact.get("items", ()) if isinstance(exact, Mapping) else ()
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            for item in items:
                if isinstance(item, Mapping):
                    item_citations, _lineages = _item_references(item)
                    citations.update(item_citations)
    return tuple(sorted(citations))


def _browser_projection(
    outcome: UatConversationOutcome,
    responses: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if outcome.response_kind == "clarification":
        return {
            "status": "clarification_required",
            "answer": "",
            "citations": [],
            "clarification": outcome.answer_text,
        }
    available_citations = set(_response_citations(responses))
    citations = tuple(outcome.citation_ids)
    if not set(citations).issubset(available_citations):
        raise ValueError("GPT cited evidence that was not returned by MCP")
    if responses and not citations:
        return {
            "status": "clarification_required",
            "answer": "",
            "citations": [],
            "clarification": outcome.answer_text,
        }
    return {
        "status": (
            "complete" if not responses or outcome.coverage_status == "complete" else "partial"
        ),
        "answer": outcome.answer_text,
        "citations": list(citations),
        "clarification": (
            outcome.coverage_note if responses and outcome.coverage_status == "incomplete" else None
        ),
    }


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
) -> Issue56TemporaryLanQueryService:
    """Compose one reusable real-source diagnostic app without external services."""

    retrieval_handler = build_issue56_production_semantic_retrieval_handler()
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
        semantic_gateway=SemanticMcpGateway(retrieval_handler=retrieval_handler),
        oauth_route_provider=lambda **_kwargs: (),
        environ={"FORMOWL_AUTH_MODE": "oauth_google"},
    )
    return Issue56TemporaryLanQueryService(
        application,
        conversation_model=conversation_model,
        behavior_log_path=behavior_log_path,
        record_raw_uat_interactions=record_raw_uat_interactions,
    )
