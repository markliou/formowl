"""Google OIDC upstream client with fixed trusted endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import base64
import json
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode
import warnings

from authlib.deprecate import AuthlibDeprecationWarning

# Authlib 1.x emits this warning at import time with the installed source path.
# Keep production stderr path-free while the bounded joserfc migration is deferred.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", AuthlibDeprecationWarning)
    from authlib.jose import JoseError, JsonWebKey, JsonWebToken
import httpx

from .config import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_DISCOVERY_URL,
    GOOGLE_ISSUER,
    GOOGLE_JWKS_URI,
    GOOGLE_TOKEN_ENDPOINT,
    OAuthBridgeConfig,
)
from .models import OAuthAccessDenied
from .security import normalize_verified_email, oauth_hash_matches


_GOOGLE_JWT = JsonWebToken(["RS256"])
_TRUSTED_GOOGLE_ID_TOKEN_ISSUERS = (
    GOOGLE_ISSUER,
    "accounts.google.com",
)


class AsyncHttpClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...

    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


@dataclass(frozen=True)
class GoogleIdentity:
    issuer: str
    subject: str
    email: str
    email_verified: bool
    display_name: str


class GoogleOidcClient:
    def __init__(self, *, config: OAuthBridgeConfig, http_client: AsyncHttpClient) -> None:
        self.config = config
        self.http_client = http_client
        self._provider_metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None

    def build_authorization_url(self, *, google_state: str, google_nonce: str) -> str:
        if not google_state or not google_nonce:
            raise OAuthAccessDenied("invalid_request", "google_correlation_missing", 400)
        query = urlencode(
            {
                "client_id": self.config.google_client_id,
                "redirect_uri": self.config.google_redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": google_state,
                "nonce": google_nonce,
                "prompt": "select_account",
            }
        )
        return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}"

    async def load_provider_metadata(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._provider_metadata is not None and not refresh:
            return dict(self._provider_metadata)
        response = await self._safe_get(GOOGLE_DISCOVERY_URL)
        metadata = _json_object(response, "google_discovery_invalid")
        expected = {
            "issuer": GOOGLE_ISSUER,
            "authorization_endpoint": GOOGLE_AUTHORIZATION_ENDPOINT,
            "token_endpoint": GOOGLE_TOKEN_ENDPOINT,
            "jwks_uri": GOOGLE_JWKS_URI,
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise OAuthAccessDenied("server_error", "google_discovery_untrusted", 500)
        algorithms = metadata.get("id_token_signing_alg_values_supported", ["RS256"])
        if not isinstance(algorithms, list) or "RS256" not in algorithms:
            raise OAuthAccessDenied("server_error", "google_rs256_unavailable", 500)
        self._provider_metadata = dict(metadata)
        return dict(metadata)

    async def load_jwks(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._jwks is not None and not refresh:
            return dict(self._jwks)
        metadata = await self.load_provider_metadata(refresh=refresh)
        if metadata["jwks_uri"] != GOOGLE_JWKS_URI:
            raise OAuthAccessDenied("server_error", "google_jwks_uri_untrusted", 500)
        response = await self._safe_get(GOOGLE_JWKS_URI)
        jwks = _json_object(response, "google_jwks_invalid")
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not keys:
            raise OAuthAccessDenied("server_error", "google_jwks_invalid", 500)
        for key in keys:
            if not isinstance(key, dict) or key.get("kty") != "RSA" or not key.get("kid"):
                raise OAuthAccessDenied("server_error", "google_jwks_invalid", 500)
        self._jwks = {"keys": [dict(key) for key in keys]}
        return dict(self._jwks)

    async def exchange_code(self, google_code: str) -> str:
        if not isinstance(google_code, str) or not google_code:
            raise OAuthAccessDenied("access_denied", "google_code_missing", 400)
        try:
            response = await self.http_client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": google_code,
                    "client_id": self.config.google_client_id,
                    "client_secret": self.config.google_client_secret,
                    "redirect_uri": self.config.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
                timeout=10.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise OAuthAccessDenied("server_error", "google_token_unavailable", 500) from exc
        if response.status_code != 200:
            raise OAuthAccessDenied("access_denied", "google_code_exchange_failed", 400)
        payload = _json_object(response, "google_token_response_invalid")
        id_token = payload.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise OAuthAccessDenied("access_denied", "google_id_token_missing", 400)
        # Google access_token and refresh_token values, if present, are
        # intentionally discarded at this boundary.
        return id_token

    async def validate_id_token(
        self,
        id_token: str,
        *,
        expected_nonce_hash: str,
        now: datetime,
    ) -> GoogleIdentity:
        _require_aware(now)
        header = _unverified_header(id_token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise OAuthAccessDenied("access_denied", "google_token_header_invalid", 400)
        jwks = await self.load_jwks()
        key = _select_jwk(jwks, str(header["kid"]))
        if key is None:
            jwks = await self.load_jwks(refresh=True)
            key = _select_jwk(jwks, str(header["kid"]))
        if key is None:
            raise OAuthAccessDenied("access_denied", "google_signing_key_unknown", 400)
        try:
            claims = dict(_GOOGLE_JWT.decode(id_token, JsonWebKey.import_key(key)))
        except (JoseError, ValueError, TypeError) as exc:
            raise OAuthAccessDenied("access_denied", "google_signature_invalid", 400) from exc
        _validate_google_claims(
            claims,
            google_client_id=self.config.google_client_id,
            expected_nonce_hash=expected_nonce_hash,
            now=now,
            clock_skew_seconds=self.config.clock_skew_seconds,
        )
        return GoogleIdentity(
            issuer=GOOGLE_ISSUER,
            subject=str(claims["sub"]),
            email=normalize_verified_email(str(claims["email"])),
            email_verified=True,
            display_name=_safe_display_name(claims.get("name")),
        )

    async def authenticate_code(
        self,
        google_code: str,
        *,
        expected_nonce_hash: str,
        now: datetime,
    ) -> GoogleIdentity:
        id_token = await self.exchange_code(google_code)
        return await self.validate_id_token(
            id_token,
            expected_nonce_hash=expected_nonce_hash,
            now=now,
        )

    async def _safe_get(self, url: str) -> httpx.Response:
        try:
            response = await self.http_client.get(
                url,
                headers={"Accept": "application/json"},
                timeout=10.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise OAuthAccessDenied("server_error", "google_metadata_unavailable", 500) from exc
        if response.status_code != 200:
            raise OAuthAccessDenied("server_error", "google_metadata_unavailable", 500)
        return response


def _validate_google_claims(
    claims: Mapping[str, Any],
    *,
    google_client_id: str,
    expected_nonce_hash: str,
    now: datetime,
    clock_skew_seconds: int,
) -> None:
    issuer = claims.get("iss")
    if not isinstance(issuer, str) or issuer not in _TRUSTED_GOOGLE_ID_TOKEN_ISSUERS:
        raise OAuthAccessDenied("access_denied", "google_issuer_invalid", 400)
    audience = claims.get("aud")
    if isinstance(audience, str):
        audience_valid = audience == google_client_id
        multiple_audiences = False
    elif isinstance(audience, list) and all(isinstance(item, str) for item in audience):
        audience_valid = google_client_id in audience
        multiple_audiences = len(audience) > 1
    else:
        audience_valid = False
        multiple_audiences = False
    if not audience_valid:
        raise OAuthAccessDenied("access_denied", "google_audience_invalid", 400)
    authorized_party = claims.get("azp")
    if (
        multiple_audiences or authorized_party is not None
    ) and authorized_party != google_client_id:
        raise OAuthAccessDenied("access_denied", "google_authorized_party_invalid", 400)
    now_epoch = int(now.timestamp())
    expiry = _numeric_date(claims.get("exp"), "google_exp_invalid")
    issued_at = _numeric_date(claims.get("iat"), "google_iat_invalid")
    not_before = _numeric_date(claims.get("nbf", issued_at), "google_nbf_invalid")
    if expiry <= now_epoch - clock_skew_seconds:
        raise OAuthAccessDenied("access_denied", "google_token_expired", 400)
    if expiry <= issued_at or not_before > expiry:
        raise OAuthAccessDenied(
            "access_denied",
            "google_temporal_order_invalid",
            400,
        )
    if not_before > now_epoch + clock_skew_seconds:
        raise OAuthAccessDenied("access_denied", "google_token_not_yet_valid", 400)
    if issued_at > now_epoch + clock_skew_seconds:
        raise OAuthAccessDenied("access_denied", "google_token_issued_in_future", 400)
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not oauth_hash_matches(
        "google_nonce", nonce, expected_nonce_hash
    ):
        raise OAuthAccessDenied("access_denied", "google_nonce_invalid", 400)
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise OAuthAccessDenied("access_denied", "google_subject_invalid", 400)
    if claims.get("email_verified") is not True:
        raise OAuthAccessDenied("access_denied", "google_email_unverified", 400)
    normalize_verified_email(claims.get("email"))


def _select_jwk(jwks: Mapping[str, Any], kid: str) -> dict[str, Any] | None:
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        return None
    matches = [key for key in keys if isinstance(key, dict) and key.get("kid") == kid]
    if len(matches) != 1:
        return None
    key = dict(matches[0])
    if key.get("kty") != "RSA" or key.get("alg", "RS256") != "RS256":
        return None
    return key


def _unverified_header(token: str) -> dict[str, Any]:
    if not isinstance(token, str) or not token or len(token) > 16384:
        raise OAuthAccessDenied("access_denied", "google_token_shape_invalid", 400)
    parts = token.split(".")
    if len(parts) != 3:
        raise OAuthAccessDenied("access_denied", "google_token_shape_invalid", 400)
    try:
        padding = "=" * (-len(parts[0]) % 4)
        decoded = base64.urlsafe_b64decode((parts[0] + padding).encode("ascii"))
        header = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise OAuthAccessDenied("access_denied", "google_token_header_invalid", 400) from exc
    if not isinstance(header, dict):
        raise OAuthAccessDenied("access_denied", "google_token_header_invalid", 400)
    return header


def _numeric_date(value: Any, reason_code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OAuthAccessDenied("access_denied", reason_code, 400)
    return value


def _json_object(response: httpx.Response, reason_code: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise OAuthAccessDenied("server_error", reason_code, 500) from exc
    if not isinstance(payload, dict):
        raise OAuthAccessDenied("server_error", reason_code, 500)
    return payload


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")


def _safe_display_name(value: Any) -> str:
    if not isinstance(value, str):
        return "FormOwl User"
    normalized = " ".join(value.split())
    if (
        not normalized
        or len(normalized) > 120
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        return "FormOwl User"
    return normalized


__all__ = ["AsyncHttpClient", "GoogleIdentity", "GoogleOidcClient"]
