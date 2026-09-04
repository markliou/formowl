"""Thin real-source browser UAT adapter for the normal Issue #56 MCP route."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
import hashlib
import os
import re
import secrets
from threading import RLock
import time
from typing import Any
from urllib.parse import urlencode, urlparse

from starlette.testclient import TestClient

from formowl_contract import assert_no_public_raw_references
from formowl_core import load_issue56_target_mail_tokenizer_profile

from .issue56_diagnostic import mcp_headers, mcp_query_request
from .runtime import ConnectedRuntime, ConnectedRuntimeConfig
from .semantic import validate_public_gateway_payload


_PUBLIC_BASE_URL_ENV = "FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL"
_MAX_BROWSER_AUTH_RECORDS = 64


class Issue56UatQueryService:
    """Adapt one browser prompt to bounded calls on an existing runtime."""

    def __init__(
        self,
        runtime: ConnectedRuntime,
        *,
        public_base_url: str,
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
            responses = [self._call(prompt, bearer=bearer)]
            for follow_up in _follow_up_queries(prompt, responses[0]):
                responses.append(self._call(follow_up, bearer=bearer))
            self.last_mcp_statuses = tuple(
                str(response.get("status", "unknown")) for response in responses
            )
            result = _browser_projection(responses)
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


def _follow_up_queries(prompt: str, data: Mapping[str, Any]) -> tuple[str, ...]:
    if data.get("status") not in {"replan_required", "partial", "incomplete"}:
        return ()
    agent = data.get("query_agent")
    replan = agent.get("external_replan") if isinstance(agent, Mapping) else None
    capability = agent.get("authorized_capability_summary") if isinstance(agent, Mapping) else None
    requested = (
        replan.get("requested_projection_field_hashes") if isinstance(replan, Mapping) else None
    )
    fields = capability.get("projection_fields") if isinstance(capability, Mapping) else None
    if (
        not isinstance(replan, Mapping)
        or not isinstance(capability, Mapping)
        or not isinstance(requested, Sequence)
        or isinstance(requested, (str, bytes))
        or not isinstance(fields, Sequence)
        or isinstance(fields, (str, bytes))
        or capability.get("listing_status") != "complete"
    ):
        return ()
    raw_ambiguous = replan.get("ambiguous_projection_term_hashes", ())
    if not isinstance(raw_ambiguous, Sequence) or isinstance(raw_ambiguous, (str, bytes)):
        return ()
    ambiguous = {value for value in raw_ambiguous if isinstance(value, str)}
    requested = tuple(value for value in requested if value not in ambiguous)
    if not 1 <= len(requested) <= 2:
        return ()
    authorized: dict[str, list[str]] = {}
    for field in fields:
        if (
            isinstance(field, Mapping)
            and field.get("structure_status") == "source_provided"
            and field.get("label_redacted") is False
            and isinstance(field.get("field_hash"), str)
            and isinstance(field.get("field"), str)
        ):
            authorized.setdefault(field["field_hash"], []).append(field["field"])
    labels: list[str] = []
    for field_hash in requested:
        matches = authorized.get(field_hash, ())
        if len(matches) != 1:
            return ()
        labels.append(matches[0])
    prefix = _filter_prefix(prompt, labels)
    if prefix is None:
        return ()
    return tuple(f"{prefix}{label}？" for label in labels)


def _filter_prefix(prompt: str, labels: Sequence[str]) -> str | None:
    label_starts = [
        match.start()
        for label in labels
        for match in re.finditer(re.escape(label), prompt, flags=re.IGNORECASE)
    ]
    if label_starts:
        prefix = prompt[: min(label_starts)]
        if prefix.strip():
            return prefix
    terms = load_issue56_target_mail_tokenizer_profile().analyze_query_grounding(prompt).terms
    boundaries = [
        term
        for index, term in enumerate(terms)
        if term.grammar_role == "particle"
        and index
        and prompt[: term.start].strip()
        and any(later.grammar_role in {"lexical", "operator"} for later in terms[index + 1 :])
    ]
    if not boundaries:
        return None
    return prompt[: boundaries[0].end]


def _browser_projection(responses: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    citations: set[str] = set()
    answers: list[str] = []
    complete = True
    row_number = 0
    for data in responses:
        exact = data.get("exact_inventory")
        if not isinstance(exact, Mapping):
            complete = False
            raw_citations = data.get("citations", ())
            if isinstance(raw_citations, Sequence) and not isinstance(raw_citations, (str, bytes)):
                citations.update(item for item in raw_citations if isinstance(item, str))
            answer = data.get("answer")
            if isinstance(answer, Mapping) and isinstance(answer.get("text"), str):
                answers.append(answer["text"])
            continue
        complete &= exact.get("coverage_status") == "complete"
        for item in exact.get("items", ()):
            if not isinstance(item, Mapping):
                continue
            row_number += 1
            item_citations = {
                reference["citation_hash"]
                for reference in item.get("governed_references", ())
                if isinstance(reference, Mapping)
                and isinstance(reference.get("citation_hash"), str)
            }
            item_values: list[str] = []
            for value in item.get("structured_values", ()):
                if (
                    isinstance(value, Mapping)
                    and isinstance(value.get("field"), str)
                    and isinstance(value.get("value"), str)
                ):
                    item_values.append(f"{value['field']}: {value['value']}")
                    citation = value.get("citation_hash")
                    if isinstance(citation, str):
                        item_citations.add(citation)
            if item_values and item_citations:
                answers.append(f"來源列 {row_number}\n" + "\n".join(item_values))
                citations.update(item_citations)
            elif item_values:
                complete = False
    answer_text = "\n".join(dict.fromkeys(answers))
    if answer_text and citations:
        return {
            "status": "complete" if complete else "partial",
            "answer": answer_text,
            "citations": sorted(citations),
            "clarification": (
                None if complete else "目前只有部分經授權且可引用的來源證據，請縮小問題範圍。"
            ),
        }
    return {
        "status": "clarification_required",
        "answer": "",
        "citations": [],
        "clarification": "請補充要查詢的實體與來源欄位。",
    }


async def create_issue56_uat_query_service(
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
    )
