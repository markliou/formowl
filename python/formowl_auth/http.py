"""ASGI routes for the narrow FormOwl OAuth authorization bridge."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from .config import OAuthBridgeConfig
from .google_oidc import GoogleOidcClient
from .models import OAuthAccessDenied
from .service import FormOwlOAuthBridge


Clock = Callable[[], datetime]

_NO_REFERRER_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
_TOKEN_HEADERS = {
    **_NO_REFERRER_HEADERS,
    "Pragma": "no-cache",
}
_TOKEN_REQUEST_BODY_LIMIT = 16_384


def protected_resource_metadata(config: OAuthBridgeConfig) -> dict[str, Any]:
    return {
        "resource": config.resource,
        "authorization_servers": [config.issuer],
        "scopes_supported": list(config.scopes),
        "bearer_methods_supported": ["header"],
    }


def authorization_server_metadata(config: OAuthBridgeConfig) -> dict[str, Any]:
    return {
        "issuer": config.issuer,
        "authorization_endpoint": config.authorization_endpoint,
        "token_endpoint": config.token_endpoint,
        "jwks_uri": config.jwks_uri,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": list(config.scopes),
        "token_endpoint_auth_methods_supported": ["none"],
    }


def oauth_routes(
    *,
    bridge: FormOwlOAuthBridge,
    config: OAuthBridgeConfig,
    google_client: GoogleOidcClient,
    clock: Clock | None = None,
) -> list[BaseRoute]:
    if bridge.config != config or bridge.google_client is not google_client:
        raise ValueError("OAuth route dependencies must share one bridge configuration")
    resolved_clock = clock or (lambda: datetime.now(timezone.utc))

    async def protected_resource_endpoint(_request: Request) -> Response:
        return JSONResponse(
            protected_resource_metadata(config),
            headers={"Referrer-Policy": "no-referrer"},
        )

    async def authorization_server_endpoint(_request: Request) -> Response:
        return JSONResponse(
            authorization_server_metadata(config),
            headers={"Referrer-Policy": "no-referrer"},
        )

    async def jwks_endpoint(_request: Request) -> Response:
        now = _aware_now(resolved_clock)
        return JSONResponse(
            bridge.token_codec.key_set.public_jwks(now=now),
            headers={"Referrer-Policy": "no-referrer"},
        )

    async def authorize_endpoint(request: Request) -> Response:
        parameters: dict[str, str] = {}
        try:
            parameters = _unique_query_parameters(request)
            result = bridge.start_authorization(parameters, now=_aware_now(resolved_clock))
        except OAuthAccessDenied as denial:
            _record_denial_safely(
                bridge,
                event="authorization",
                denial=denial,
                now=_aware_now(resolved_clock),
                oauth_client_id=(
                    config.chatgpt_client_id
                    if parameters.get("client_id") == config.chatgpt_client_id
                    else None
                ),
            )
            return _authorization_error_response(
                parameters,
                denial=denial,
                config=config,
            )
        return RedirectResponse(
            result["authorization_url"],
            status_code=302,
            headers=_NO_REFERRER_HEADERS,
        )

    async def google_callback_endpoint(request: Request) -> Response:
        try:
            parameters = _unique_query_parameters(request)
        except OAuthAccessDenied as denial:
            _record_denial_safely(
                bridge,
                event="google_callback",
                denial=denial,
                now=_aware_now(resolved_clock),
                oauth_client_id=config.chatgpt_client_id,
            )
            return _oauth_error_response(denial, headers=_NO_REFERRER_HEADERS)
        if "error" in parameters:
            state = parameters.get("state")
            if not parameters["error"] or not state or "code" in parameters:
                denial = OAuthAccessDenied(
                    "invalid_request",
                    "google_callback_ambiguous",
                    400,
                )
                _record_denial_safely(
                    bridge,
                    event="google_callback",
                    denial=denial,
                    now=_aware_now(resolved_clock),
                    oauth_client_id=config.chatgpt_client_id,
                )
                return _oauth_error_response(
                    denial,
                    headers=_NO_REFERRER_HEADERS,
                )
            try:
                result = bridge.complete_google_denial(
                    google_state=state,
                    now=_aware_now(resolved_clock),
                )
            except OAuthAccessDenied as denial:
                _record_denial_safely(
                    bridge,
                    event="google_callback",
                    denial=denial,
                    now=_aware_now(resolved_clock),
                    oauth_client_id=config.chatgpt_client_id,
                )
                return _oauth_error_response(denial, headers=_NO_REFERRER_HEADERS)
            except Exception:
                return _oauth_error_response(
                    OAuthAccessDenied(
                        "server_error",
                        "google_denial_persistence_failed",
                        500,
                    ),
                    headers=_NO_REFERRER_HEADERS,
                )
            redirect_uri = result.get("redirect_uri")
            if not isinstance(redirect_uri, str) or not _is_exact_callback(
                redirect_uri,
                config.chatgpt_redirect_uri,
            ):
                return _oauth_error_response(
                    OAuthAccessDenied("server_error", "callback_redirect_invalid", 500),
                    headers=_NO_REFERRER_HEADERS,
                )
            try:
                redirect_query = parse_qs(
                    urlparse(redirect_uri).query,
                    keep_blank_values=True,
                    strict_parsing=True,
                )
            except ValueError:
                redirect_query = {}
            if (
                redirect_query.get("error") != ["access_denied"]
                or len(redirect_query.get("state", [])) != 1
                or not redirect_query["state"][0]
                or set(redirect_query) != {"error", "state"}
                or urlparse(redirect_uri).fragment
            ):
                return _oauth_error_response(
                    OAuthAccessDenied("server_error", "callback_redirect_invalid", 500),
                    headers=_NO_REFERRER_HEADERS,
                )
            return RedirectResponse(
                redirect_uri,
                status_code=302,
                headers=_NO_REFERRER_HEADERS,
            )
        state = parameters.get("state")
        code = parameters.get("code")
        try:
            result = await bridge.complete_google_callback(
                google_state=state or "",
                google_code=code or "",
                now=_aware_now(resolved_clock),
            )
        except OAuthAccessDenied as denial:
            _record_denial_safely(
                bridge,
                event="google_callback",
                denial=denial,
                now=_aware_now(resolved_clock),
                oauth_client_id=config.chatgpt_client_id,
            )
            return _oauth_error_response(denial, headers=_NO_REFERRER_HEADERS)
        redirect_uri = result["redirect_uri"]
        if not _is_exact_callback(redirect_uri, config.chatgpt_redirect_uri):
            return _oauth_error_response(
                OAuthAccessDenied("server_error", "callback_redirect_invalid", 500),
                headers=_NO_REFERRER_HEADERS,
            )
        try:
            redirect_query = parse_qs(
                urlparse(redirect_uri).query,
                keep_blank_values=True,
                strict_parsing=True,
            )
        except ValueError:
            redirect_query = {}
        if (
            len(redirect_query.get("code", [])) != 1
            or not redirect_query["code"][0]
            or len(redirect_query.get("state", [])) != 1
            or not redirect_query["state"][0]
            or set(redirect_query) != {"code", "state"}
            or urlparse(redirect_uri).fragment
        ):
            return _oauth_error_response(
                OAuthAccessDenied("server_error", "callback_redirect_invalid", 500),
                headers=_NO_REFERRER_HEADERS,
            )
        return RedirectResponse(
            redirect_uri,
            status_code=302,
            headers=_NO_REFERRER_HEADERS,
        )

    async def token_endpoint(request: Request) -> Response:
        parameters: dict[str, str] = {}
        try:
            parameters = await _token_form(request)
            result = bridge.exchange_authorization_code(
                parameters,
                now=_aware_now(resolved_clock),
            )
        except OAuthAccessDenied as denial:
            _record_denial_safely(
                bridge,
                event="token_exchange",
                denial=denial,
                now=_aware_now(resolved_clock),
                oauth_client_id=(
                    config.chatgpt_client_id
                    if parameters.get("client_id") == config.chatgpt_client_id
                    else None
                ),
            )
            return _oauth_error_response(denial, headers=_TOKEN_HEADERS)
        return JSONResponse(result, headers=_TOKEN_HEADERS)

    return [
        Route(
            "/.well-known/oauth-protected-resource",
            protected_resource_endpoint,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            authorization_server_endpoint,
            methods=["GET"],
        ),
        Route("/oauth/authorize", authorize_endpoint, methods=["GET"]),
        Route("/oauth/google/callback", google_callback_endpoint, methods=["GET"]),
        Route("/oauth/token", token_endpoint, methods=["POST"]),
        Route("/.well-known/jwks.json", jwks_endpoint, methods=["GET"]),
    ]


def create_oauth_asgi_app(
    *,
    bridge: FormOwlOAuthBridge,
    config: OAuthBridgeConfig,
    google_client: GoogleOidcClient,
    clock: Clock | None = None,
) -> Starlette:
    return Starlette(
        routes=oauth_routes(
            bridge=bridge,
            config=config,
            google_client=google_client,
            clock=clock,
        )
    )


def _authorization_error_response(
    parameters: dict[str, str],
    *,
    denial: OAuthAccessDenied,
    config: OAuthBridgeConfig,
) -> Response:
    if config.chatgpt_callback_mode == "discovery_only":
        return _oauth_error_response(denial, headers=_NO_REFERRER_HEADERS)
    trusted_redirect = (
        parameters.get("client_id") == config.chatgpt_client_id
        and parameters.get("redirect_uri") == config.chatgpt_redirect_uri
    )
    if not trusted_redirect:
        return _oauth_error_response(denial, headers=_NO_REFERRER_HEADERS)
    query: dict[str, str] = {"error": denial.error}
    state = parameters.get("state")
    if isinstance(state, str) and state and len(state) <= 2048:
        query["state"] = state
    return RedirectResponse(
        _append_query(config.chatgpt_redirect_uri, query),
        status_code=302,
        headers=_NO_REFERRER_HEADERS,
    )


def _unique_query_parameters(request: Request) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key in values:
            raise OAuthAccessDenied("invalid_request", "oauth_parameter_duplicated", 400)
        values[key] = value
    return values


async def _token_form(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise OAuthAccessDenied("invalid_request", "token_content_type_invalid", 400)
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isascii() and content_length.isdigit():
        normalized_length = content_length.lstrip("0") or "0"
        body_limit = str(_TOKEN_REQUEST_BODY_LIMIT)
        if len(normalized_length) > len(body_limit) or (
            len(normalized_length) == len(body_limit) and normalized_length > body_limit
        ):
            raise OAuthAccessDenied("invalid_request", "token_request_too_large", 400)
    buffered_body = bytearray()
    async for chunk in request.stream():
        if len(buffered_body) + len(chunk) > _TOKEN_REQUEST_BODY_LIMIT:
            raise OAuthAccessDenied("invalid_request", "token_request_too_large", 400)
        buffered_body.extend(chunk)
    body = bytes(buffered_body)
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OAuthAccessDenied("invalid_request", "token_form_invalid", 400) from exc
    try:
        values = parse_qs(decoded, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise OAuthAccessDenied("invalid_request", "token_form_invalid", 400) from exc
    if any(len(items) != 1 for items in values.values()):
        raise OAuthAccessDenied("invalid_request", "token_parameter_duplicated", 400)
    return {key: items[0] for key, items in values.items()}


def _oauth_error_response(
    denial: OAuthAccessDenied,
    *,
    headers: dict[str, str],
) -> JSONResponse:
    return JSONResponse(
        {"error": denial.error},
        status_code=denial.http_status,
        headers=headers,
    )


def _append_query(uri: str, values: dict[str, str]) -> str:
    parsed = urlparse(uri)
    query = urlencode(values)
    return urlunparse(parsed._replace(query=query))


def _is_exact_callback(value: str, callback: str) -> bool:
    parsed_value = urlparse(value)
    parsed_callback = urlparse(callback)
    return (
        parsed_value.scheme,
        parsed_value.netloc,
        parsed_value.path,
        parsed_value.params,
    ) == (
        parsed_callback.scheme,
        parsed_callback.netloc,
        parsed_callback.path,
        parsed_callback.params,
    )


def _aware_now(clock: Clock) -> datetime:
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise RuntimeError("OAuth ASGI clock must return a timezone-aware datetime")
    return now


def _record_denial_safely(
    bridge: FormOwlOAuthBridge,
    *,
    event: str,
    denial: OAuthAccessDenied,
    now: datetime,
    oauth_client_id: str | None,
) -> None:
    try:
        bridge.record_oauth_denial(
            event=event,
            reason_code=denial.reason_code,
            now=now,
            oauth_client_id=oauth_client_id,
        )
    except Exception:
        # OAuth error handling must remain safe even when audit persistence is
        # unavailable.  The original denial is returned without backend detail.
        return


__all__ = [
    "authorization_server_metadata",
    "create_oauth_asgi_app",
    "oauth_routes",
    "protected_resource_metadata",
]
