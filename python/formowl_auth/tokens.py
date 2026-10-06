"""RS256 FormOwl access-token signing and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import json
import re
from typing import Any, Iterable, Mapping

from authlib.jose import JoseError, JsonWebKey, JsonWebToken
from formowl_contract import ContractValidationError

from .models import OAuthAccessDenied, OAuthTokenSession


_JWT = JsonWebToken(["RS256"])
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


@dataclass(frozen=True)
class FormOwlSigningKey:
    kid: str
    private_key_pem: bytes = field(repr=False)
    active: bool = False
    verify_until: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kid, str) or not _SAFE_ID.fullmatch(self.kid):
            raise ContractValidationError("FormOwl signing key kid is invalid")
        if not isinstance(self.private_key_pem, bytes) or not self.private_key_pem:
            raise ContractValidationError("FormOwl signing private key is required")
        if self.verify_until is not None:
            _require_aware(self.verify_until, "verify_until")
        try:
            JsonWebKey.import_key(
                self.private_key_pem,
                {"kid": self.kid, "use": "sig", "alg": "RS256"},
            )
        except (JoseError, ValueError) as exc:
            raise ContractValidationError("FormOwl signing key is invalid") from exc

    def private_key(self) -> Any:
        return JsonWebKey.import_key(
            self.private_key_pem,
            {"kid": self.kid, "use": "sig", "alg": "RS256"},
        )

    def public_jwk(self) -> dict[str, Any]:
        key = self.private_key()
        public = key.as_dict(is_private=False)
        public.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return public


class FormOwlSigningKeySet:
    def __init__(self, keys: Iterable[FormOwlSigningKey]) -> None:
        self._keys = tuple(keys)
        if not self._keys:
            raise ContractValidationError("FormOwl signing key set is empty")
        if len({key.kid for key in self._keys}) != len(self._keys):
            raise ContractValidationError("FormOwl signing key ids must be unique")
        active = [key for key in self._keys if key.active]
        if len(active) != 1:
            raise ContractValidationError("FormOwl requires exactly one active signing key")

    @property
    def active_key(self) -> FormOwlSigningKey:
        return next(key for key in self._keys if key.active)

    def verification_key(self, kid: str, *, now: datetime) -> Any:
        _require_aware(now, "now")
        for key in self._keys:
            if key.kid != kid:
                continue
            if not key.active and (key.verify_until is None or key.verify_until < now):
                break
            return JsonWebKey.import_key(key.public_jwk())
        raise OAuthAccessDenied("invalid_token", "signing_key_unavailable", 401)

    def public_jwks(self, *, now: datetime) -> dict[str, list[dict[str, Any]]]:
        _require_aware(now, "now")
        visible = [
            key.public_jwk()
            for key in self._keys
            if key.active or (key.verify_until is not None and key.verify_until >= now)
        ]
        if not visible:
            raise ContractValidationError("FormOwl JWKS has no verifiable keys")
        for jwk in visible:
            if any(name in jwk for name in ("d", "p", "q", "dp", "dq", "qi")):
                raise ContractValidationError("FormOwl public JWKS contains private key material")
        return {"keys": visible}


class FormOwlTokenCodec:
    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        key_set: FormOwlSigningKeySet,
        lifetime_seconds: int = 3600,
        clock_skew_seconds: int = 30,
    ) -> None:
        if (
            not isinstance(issuer, str)
            or not issuer.strip()
            or not isinstance(client_id, str)
            or not client_id.strip()
        ):
            raise ContractValidationError("FormOwl token issuer and client id are required")
        if (
            isinstance(lifetime_seconds, bool)
            or not isinstance(lifetime_seconds, int)
            or not 1 <= lifetime_seconds <= 3600
        ):
            raise ContractValidationError("FormOwl token lifetime is invalid")
        if (
            isinstance(clock_skew_seconds, bool)
            or not isinstance(clock_skew_seconds, int)
            or not 0 <= clock_skew_seconds <= 300
        ):
            raise ContractValidationError("FormOwl token clock skew is invalid")
        self.issuer = issuer
        self.client_id = client_id
        self.key_set = key_set
        self.lifetime_seconds = lifetime_seconds
        self.clock_skew_seconds = clock_skew_seconds

    def issue_access_token(
        self,
        *,
        session: OAuthTokenSession,
        jti: str,
        now: datetime,
    ) -> str:
        _require_aware(now, "now")
        if not isinstance(jti, str) or len(jti) > 128 or not _SAFE_ID.fullmatch(jti):
            raise ContractValidationError("FormOwl token jti is invalid")
        if session.client_id != self.client_id:
            raise ContractValidationError("FormOwl token session client mismatch")
        issued = int(now.timestamp())
        claims = {
            "iss": self.issuer,
            "sub": session.user_id,
            "aud": session.resource,
            "scope": " ".join(session.scopes),
            "client_id": session.client_id,
            "sid": session.token_session_id,
            "jti": jti,
            "iat": issued,
            "nbf": issued,
            "exp": issued + self.lifetime_seconds,
        }
        header = {"alg": "RS256", "kid": self.key_set.active_key.kid, "typ": "JWT"}
        encoded = _JWT.encode(header, claims, self.key_set.active_key.private_key())
        return encoded.decode("ascii") if isinstance(encoded, bytes) else str(encoded)

    def verify_access_token(
        self,
        raw_token: str,
        *,
        resource: str,
        required_scope: str,
        now: datetime,
    ) -> dict[str, Any]:
        _require_aware(now, "now")
        claims = self._decode_signed_claims(raw_token, now=now)
        self._validate_claims(
            claims,
            resource=resource,
            required_scope=required_scope,
            now=now,
        )
        return claims

    def verify_expired_access_token_for_audit(
        self,
        raw_token: str,
        *,
        resource: str,
        required_scope: str,
        now: datetime,
    ) -> dict[str, Any]:
        """Return claims only when a trusted FormOwl token failed solely by expiry."""

        _require_aware(now, "now")
        claims = self._decode_signed_claims(raw_token, now=now)
        self._validate_claim_structure(
            claims,
            resource=resource,
            required_scope=required_scope,
        )
        try:
            self._validate_claim_time_window(claims, now=now)
        except OAuthAccessDenied as denial:
            if denial.reason_code == "token_expired":
                return claims
            raise
        raise OAuthAccessDenied("invalid_token", "token_not_expired", 401)

    def _decode_signed_claims(self, raw_token: str, *, now: datetime) -> dict[str, Any]:
        header = _unverified_header(raw_token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise OAuthAccessDenied("invalid_token", "token_header_invalid", 401)
        key = self.key_set.verification_key(str(header["kid"]), now=now)
        try:
            claims_object = _JWT.decode(raw_token, key)
            return dict(claims_object)
        except (JoseError, ValueError, TypeError) as exc:
            raise OAuthAccessDenied("invalid_token", "token_signature_invalid", 401) from exc

    def _validate_claims(
        self,
        claims: Mapping[str, Any],
        *,
        resource: str,
        required_scope: str,
        now: datetime,
    ) -> None:
        self._validate_claim_structure(
            claims,
            resource=resource,
            required_scope=required_scope,
        )
        self._validate_claim_time_window(claims, now=now)

    def _validate_claim_structure(
        self,
        claims: Mapping[str, Any],
        *,
        resource: str,
        required_scope: str,
    ) -> None:
        if claims.get("iss") != self.issuer:
            raise OAuthAccessDenied("invalid_token", "token_issuer_invalid", 401)
        if claims.get("aud") != resource:
            raise OAuthAccessDenied("invalid_target", "token_resource_invalid", 401)
        if claims.get("client_id") != self.client_id:
            raise OAuthAccessDenied("invalid_token", "token_client_invalid", 401)
        for field_name in ("sub", "sid", "jti"):
            value = claims.get(field_name)
            if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
                raise OAuthAccessDenied("invalid_token", f"token_{field_name}_invalid", 401)
        issued_at = _numeric_date(claims.get("iat"), "iat")
        not_before = _numeric_date(claims.get("nbf"), "nbf")
        expires_at = _numeric_date(claims.get("exp"), "exp")
        if not issued_at <= not_before < expires_at:
            raise OAuthAccessDenied(
                "invalid_token",
                "token_temporal_order_invalid",
                401,
            )
        if expires_at - issued_at > self.lifetime_seconds:
            raise OAuthAccessDenied(
                "invalid_token",
                "token_lifetime_invalid",
                401,
            )
        scopes = _scope_tuple(claims.get("scope"))
        if required_scope not in scopes:
            raise OAuthAccessDenied("insufficient_scope", "required_scope_missing", 403)

    def _validate_claim_time_window(
        self,
        claims: Mapping[str, Any],
        *,
        now: datetime,
    ) -> None:
        now_epoch = int(now.timestamp())
        issued_at = _numeric_date(claims.get("iat"), "iat")
        not_before = _numeric_date(claims.get("nbf"), "nbf")
        expires_at = _numeric_date(claims.get("exp"), "exp")
        if issued_at > now_epoch + self.clock_skew_seconds:
            raise OAuthAccessDenied("invalid_token", "token_issued_in_future", 401)
        if not_before > now_epoch + self.clock_skew_seconds:
            raise OAuthAccessDenied("invalid_token", "token_not_yet_valid", 401)
        if expires_at <= now_epoch - self.clock_skew_seconds:
            raise OAuthAccessDenied("invalid_token", "token_expired", 401)


def _unverified_header(raw_token: str) -> dict[str, Any]:
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > 16384:
        raise OAuthAccessDenied("invalid_token", "token_shape_invalid", 401)
    parts = raw_token.split(".")
    if len(parts) != 3:
        raise OAuthAccessDenied("invalid_token", "token_shape_invalid", 401)
    try:
        padding = "=" * (-len(parts[0]) % 4)
        decoded = base64.b64decode(
            (parts[0] + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        header = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise OAuthAccessDenied("invalid_token", "token_header_invalid", 401) from exc
    if not isinstance(header, dict):
        raise OAuthAccessDenied("invalid_token", "token_header_invalid", 401)
    return header


def _numeric_date(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OAuthAccessDenied("invalid_token", f"token_{field_name}_invalid", 401)
    return value


def _scope_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        raise OAuthAccessDenied("invalid_token", "token_scope_invalid", 401)
    if any(character.isspace() and character != " " for character in value):
        raise OAuthAccessDenied("invalid_token", "token_scope_invalid", 401)
    scopes = tuple(value.split())
    if len(scopes) != len(set(scopes)):
        raise OAuthAccessDenied("invalid_token", "token_scope_invalid", 401)
    return scopes


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    value.astimezone(timezone.utc)


__all__ = [
    "FormOwlSigningKey",
    "FormOwlSigningKeySet",
    "FormOwlTokenCodec",
]
