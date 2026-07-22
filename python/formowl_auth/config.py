"""Deployment configuration for the closed-beta OAuth bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Mapping
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from formowl_contract import ContractValidationError


GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
CHATGPT_DISCOVERY_ONLY_REDIRECT_URI = "https://invalid.example.invalid/formowl-discovery-only"
_FORBIDDEN_CHATGPT_CLIENT_IDS = {
    "formowl-discovery-only",
    "formowl-chatgpt-replace-with-deployment-id",
}
_CHATGPT_CALLBACK_PATH_PREFIX = "/connector/oauth/"
_CHATGPT_CALLBACK_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,256}$")
_CHATGPT_CLIENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


@dataclass(frozen=True)
class OAuthBridgeConfig:
    issuer: str
    resource: str
    chatgpt_client_id: str
    chatgpt_redirect_uri: str
    google_client_id: str
    google_redirect_uri: str
    google_client_secret: str = field(repr=False)
    state_encryption_key: str = field(repr=False)
    allow_loopback_http: bool = False
    chatgpt_callback_mode: str = field(init=False)
    scopes: tuple[str, ...] = ("formowl.use",)
    access_token_lifetime_seconds: int = 3600
    authorization_code_lifetime_seconds: int = 300
    authorization_transaction_lifetime_seconds: int = 600
    clock_skew_seconds: int = 30

    def __post_init__(self) -> None:
        if not isinstance(self.allow_loopback_http, bool):
            raise ContractValidationError("allow_loopback_http must be boolean")
        _validate_endpoint_url(
            self.issuer,
            "issuer",
            allow_loopback_http=self.allow_loopback_http,
        )
        _validate_endpoint_url(
            self.resource,
            "resource",
            allow_loopback_http=self.allow_loopback_http,
        )
        _validate_endpoint_url(
            self.chatgpt_redirect_uri,
            "chatgpt_redirect_uri",
            allow_loopback_http=self.allow_loopback_http,
        )
        _validate_endpoint_url(
            self.google_redirect_uri,
            "google_redirect_uri",
            allow_loopback_http=self.allow_loopback_http,
        )
        if (
            type(self.chatgpt_client_id) is not str
            or _CHATGPT_CLIENT_ID.fullmatch(self.chatgpt_client_id) is None
            or self.chatgpt_client_id in _FORBIDDEN_CHATGPT_CLIENT_IDS
            or not isinstance(self.google_client_id, str)
            or not self.google_client_id
        ):
            raise ContractValidationError("OAuth client ids are required")
        if not self.google_client_secret or not self.state_encryption_key:
            raise ContractValidationError("OAuth secret configuration is required")
        try:
            Fernet(self.state_encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ContractValidationError("OAuth state encryption key is invalid") from exc
        if urlparse(self.issuer).path:
            raise ContractValidationError(
                "OAuth issuer must be a canonical origin without a trailing slash"
            )
        if self.resource != f"{self.issuer}/mcp":
            raise ContractValidationError("OAuth resource must equal the canonical /mcp endpoint")
        if self.google_redirect_uri != f"{self.issuer}/oauth/google/callback":
            raise ContractValidationError(
                "Google redirect URI must equal the canonical callback endpoint"
            )
        if self.chatgpt_redirect_uri != self.chatgpt_redirect_uri.strip():
            raise ContractValidationError("ChatGPT redirect URI must be exact")
        if "*" in self.chatgpt_redirect_uri:
            raise ContractValidationError("wildcard redirect URIs are forbidden")
        parsed_chatgpt_redirect = urlparse(self.chatgpt_redirect_uri)
        callback_segment = (
            parsed_chatgpt_redirect.path[len(_CHATGPT_CALLBACK_PATH_PREFIX) :]
            if parsed_chatgpt_redirect.path.startswith(_CHATGPT_CALLBACK_PATH_PREFIX)
            else ""
        )
        discovery_redirect = self.chatgpt_redirect_uri == CHATGPT_DISCOVERY_ONLY_REDIRECT_URI
        if discovery_redirect:
            callback_mode = "discovery_only"
        elif (
            parsed_chatgpt_redirect.scheme == "https"
            and parsed_chatgpt_redirect.netloc == "chatgpt.com"
            and parsed_chatgpt_redirect.hostname == "chatgpt.com"
            and parsed_chatgpt_redirect.username is None
            and parsed_chatgpt_redirect.password is None
            and not parsed_chatgpt_redirect.params
            and not parsed_chatgpt_redirect.query
            and not parsed_chatgpt_redirect.fragment
            and _CHATGPT_CALLBACK_SEGMENT.fullmatch(callback_segment) is not None
            and callback_segment not in {".", ".."}
        ):
            callback_mode = "production_exact"
        elif (
            self.allow_loopback_http
            and parsed_chatgpt_redirect.scheme == "http"
            and parsed_chatgpt_redirect.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            callback_mode = "loopback_test"
        else:
            raise ContractValidationError(
                "ChatGPT redirect URI must be an exact ChatGPT callback, the reserved "
                "discovery-only sentinel, or explicit development loopback HTTP"
            )
        object.__setattr__(self, "chatgpt_callback_mode", callback_mode)
        if self.scopes != ("formowl.use",):
            raise ContractValidationError("closed beta supports only formowl.use")
        for name, value in (
            ("access_token_lifetime_seconds", self.access_token_lifetime_seconds),
            ("authorization_code_lifetime_seconds", self.authorization_code_lifetime_seconds),
            (
                "authorization_transaction_lifetime_seconds",
                self.authorization_transaction_lifetime_seconds,
            ),
            ("clock_skew_seconds", self.clock_skew_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(f"{name} must be a non-negative integer")
        if not 1 <= self.access_token_lifetime_seconds <= 3600:
            raise ContractValidationError(
                "access token lifetime must be between 1 and 3600 seconds"
            )
        if not 1 <= self.authorization_code_lifetime_seconds <= 300:
            raise ContractValidationError("authorization code lifetime must be at most 300 seconds")
        if not 1 <= self.authorization_transaction_lifetime_seconds <= 600:
            raise ContractValidationError(
                "authorization transaction lifetime must be at most 600 seconds"
            )
        if not 0 <= self.clock_skew_seconds <= 300:
            raise ContractValidationError("OAuth clock skew must be between 0 and 300 seconds")

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "OAuthBridgeConfig":
        required = {
            "issuer": "FORMOWL_OAUTH_ISSUER",
            "resource": "FORMOWL_MCP_RESOURCE",
            "chatgpt_client_id": "FORMOWL_CHATGPT_CLIENT_ID",
            "chatgpt_redirect_uri": "FORMOWL_CHATGPT_REDIRECT_URI",
            "google_client_id": "FORMOWL_GOOGLE_CLIENT_ID",
            "google_client_secret": "FORMOWL_GOOGLE_CLIENT_SECRET",
            "google_redirect_uri": "FORMOWL_GOOGLE_REDIRECT_URI",
            "state_encryption_key": "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY",
        }
        values: dict[str, str] = {}
        missing: list[str] = []
        for field_name, env_name in required.items():
            value = environ.get(env_name)
            if not value:
                missing.append(env_name)
            else:
                values[field_name] = value
        if missing:
            raise ContractValidationError(
                "OAuth configuration is incomplete: " + json.dumps(sorted(missing))
            )
        return cls(
            **values,
            allow_loopback_http=environ.get("FORMOWL_OAUTH_ALLOW_LOOPBACK_HTTP") == "1",
        )

    @property
    def protected_resource_metadata_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/.well-known/oauth-protected-resource"

    @property
    def authorization_server_metadata_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/.well-known/oauth-authorization-server"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.issuer.rstrip('/')}/oauth/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.issuer.rstrip('/')}/oauth/token"

    @property
    def jwks_uri(self) -> str:
        return f"{self.issuer.rstrip('/')}/.well-known/jwks.json"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "issuer": self.issuer,
            "resource": self.resource,
            "chatgpt_client_id_configured": True,
            "chatgpt_redirect_uri": self.chatgpt_redirect_uri,
            "chatgpt_callback_mode": self.chatgpt_callback_mode,
            "google_client_id_configured": True,
            "google_redirect_uri": self.google_redirect_uri,
            "scopes": list(self.scopes),
            "access_token_lifetime_seconds": self.access_token_lifetime_seconds,
            "authorization_code_lifetime_seconds": self.authorization_code_lifetime_seconds,
            "authorization_transaction_lifetime_seconds": (
                self.authorization_transaction_lifetime_seconds
            ),
            "secrets_redacted": True,
            "allow_loopback_http": self.allow_loopback_http,
        }


def assert_connected_auth_mode(*, auth_mode: str, connected: bool) -> None:
    if auth_mode not in {"oauth_google", "manual_trusted_internal"}:
        raise ContractValidationError("unsupported FormOwl authentication mode")
    if connected and auth_mode != "oauth_google":
        raise ContractValidationError(
            "connected FormOwl deployments require Google-backed OAuth authentication"
        )


def _validate_endpoint_url(
    value: str,
    field_name: str,
    *,
    allow_loopback_http: bool,
) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractValidationError(f"OAuth {field_name} must be an exact HTTPS URL")
    parsed = urlparse(value)
    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    secure = parsed.scheme == "https"
    allowed_loopback = (
        allow_loopback_http and parsed.scheme == "http" and parsed.hostname in loopback_hosts
    )
    if (
        not (secure or allowed_loopback)
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ContractValidationError(
            f"OAuth {field_name} must be HTTPS or explicit development loopback HTTP"
        )
    if parsed.params or parsed.query or parsed.fragment:
        raise ContractValidationError(
            f"OAuth {field_name} must not contain params, query, or fragment"
        )


__all__ = [
    "CHATGPT_DISCOVERY_ONLY_REDIRECT_URI",
    "GOOGLE_AUTHORIZATION_ENDPOINT",
    "GOOGLE_DISCOVERY_URL",
    "GOOGLE_ISSUER",
    "GOOGLE_JWKS_URI",
    "GOOGLE_TOKEN_ENDPOINT",
    "OAuthBridgeConfig",
    "assert_connected_auth_mode",
]
