"""Internal OAuth identity and session records for the FormOwl bridge.

These records deliberately remain inside :mod:`formowl_auth`.  They contain
authorization-server state and are not portable MCP payload contracts.  The
shared ``User``, ``WorkspaceMember``, ``Grant``, and ``AuditLog`` contracts
remain the authorization foundation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Literal, Mapping

from formowl_auth.security import normalize_verified_email
from formowl_contract import ContractValidationError


ExternalIdentityStatus = Literal["active", "disabled"]
InvitationStatus = Literal["pending", "accepted", "revoked", "expired"]
OwnerBootstrapStatus = Literal["pending", "completed"]
OAuthTransactionStatus = Literal["pending", "consumed", "failed"]

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SAFE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_CODE_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_OAUTH_ERRORS = {
    "access_denied",
    "invalid_request",
    "invalid_target",
    "invalid_token",
    "insufficient_scope",
    "invalid_grant",
    "invalid_scope",
    "server_error",
    "unauthorized_client",
    "unsupported_response_type",
}
_EXTERNAL_IDENTITY_FIELDS = frozenset(
    {
        "external_identity_id",
        "provider",
        "issuer",
        "subject",
        "user_id",
        "email",
        "email_verified",
        "status",
        "created_at",
        "last_authenticated_at",
    }
)
_OAUTH_INVITATION_FIELDS = frozenset(
    {
        "invitation_id",
        "normalized_email",
        "workspace_id",
        "role",
        "status",
        "expires_at",
        "created_at",
        "intended_user_id",
        "accepted_at",
        "accepted_external_identity_id",
    }
)
_OAUTH_CLIENT_AUTHORIZATION_FIELDS = frozenset(
    {
        "oauth_client_authorization_id",
        "client_id",
        "external_identity_id",
        "user_id",
        "granted_scopes",
        "default_workspace_id",
        "created_at",
        "revoked_at",
    }
)
_OAUTH_TRANSACTION_FIELDS = frozenset(
    {
        "transaction_id",
        "google_state_hash",
        "encrypted_client_state",
        "google_nonce_hash",
        "client_id",
        "redirect_uri",
        "resource",
        "scopes",
        "code_challenge",
        "code_challenge_method",
        "created_at",
        "expires_at",
        "status",
        "consumed_at",
    }
)
_OAUTH_AUTHORIZATION_CODE_FIELDS = frozenset(
    {
        "code_hash",
        "transaction_id",
        "user_id",
        "external_identity_id",
        "client_id",
        "redirect_uri",
        "resource",
        "scopes",
        "code_challenge",
        "created_at",
        "expires_at",
        "consumed_at",
    }
)
_OAUTH_TOKEN_SESSION_FIELDS = frozenset(
    {
        "token_session_id",
        "user_id",
        "external_identity_id",
        "oauth_client_authorization_id",
        "client_id",
        "current_workspace_id",
        "resource",
        "scopes",
        "token_jti_hash",
        "issued_at",
        "expires_at",
        "revoked_at",
        "revocation_reason",
    }
)


@dataclass(frozen=True)
class ExternalIdentity:
    external_identity_id: str
    provider: str
    issuer: str
    subject: str
    user_id: str
    email: str
    email_verified: bool
    status: ExternalIdentityStatus
    created_at: str
    last_authenticated_at: str

    def to_dict(self) -> dict[str, Any]:
        # Validate the scalar record directly instead of letting a generic
        # dataclass serializer invoke copy hooks on invalid runtime values.
        payload = {
            "external_identity_id": self.external_identity_id,
            "provider": self.provider,
            "issuer": self.issuer,
            "subject": self.subject,
            "user_id": self.user_id,
            "email": self.email,
            "email_verified": self.email_verified,
            "status": self.status,
            "created_at": self.created_at,
            "last_authenticated_at": self.last_authenticated_at,
        }
        if (
            any(
                type(value) is not str
                for field, value in payload.items()
                if field != "email_verified"
            )
            or type(payload["email_verified"]) is not bool
        ):
            raise ContractValidationError("ExternalIdentity is invalid")
        try:
            if normalize_verified_email(payload["email"]) != payload["email"]:
                raise ContractValidationError("ExternalIdentity.email must be normalized")
            return _validate_external_identity(payload)
        except ContractValidationError:
            raise ContractValidationError("ExternalIdentity is invalid") from None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExternalIdentity":
        payload = _validate_external_identity(value)
        return cls(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True)
class OAuthInvitation:
    invitation_id: str
    normalized_email: str
    workspace_id: str
    role: str
    status: InvitationStatus
    expires_at: str
    created_at: str
    intended_user_id: str | None = None
    accepted_at: str | None = None
    accepted_external_identity_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        string_values = (
            self.invitation_id,
            self.normalized_email,
            self.workspace_id,
            self.role,
            self.status,
            self.expires_at,
            self.created_at,
        )
        optional_string_values = (
            self.intended_user_id,
            self.accepted_at,
            self.accepted_external_identity_id,
        )
        if any(type(value) is not str for value in string_values) or any(
            value is not None and type(value) is not str for value in optional_string_values
        ):
            raise ContractValidationError("OAuthInvitation is invalid")
        payload = {
            "invitation_id": self.invitation_id,
            "normalized_email": self.normalized_email,
            "workspace_id": self.workspace_id,
            "role": self.role,
            "status": self.status,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "intended_user_id": self.intended_user_id,
            "accepted_at": self.accepted_at,
            "accepted_external_identity_id": self.accepted_external_identity_id,
        }
        _validate_invitation(payload)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OAuthInvitation":
        payload = _validate_invitation(value)
        return cls(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True)
class OAuthOwnerBootstrap:
    workspace_id: str
    normalized_email: str
    idempotency_key_hash: str
    invitation_id: str
    operator_service_id: str
    status: OwnerBootstrapStatus
    created_at: str
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        string_values = (
            self.workspace_id,
            self.normalized_email,
            self.idempotency_key_hash,
            self.invitation_id,
            self.operator_service_id,
            self.status,
            self.created_at,
        )
        if any(type(value) is not str for value in string_values) or (
            self.completed_at is not None and type(self.completed_at) is not str
        ):
            raise ContractValidationError("OAuthOwnerBootstrap is invalid")
        payload = {
            "workspace_id": self.workspace_id,
            "normalized_email": self.normalized_email,
            "idempotency_key_hash": self.idempotency_key_hash,
            "invitation_id": self.invitation_id,
            "operator_service_id": self.operator_service_id,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }
        _validate_owner_bootstrap(payload)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OAuthOwnerBootstrap":
        payload = _validate_owner_bootstrap(value)
        return cls(**payload)  # type: ignore[arg-type]


@dataclass(frozen=True)
class OAuthClientAuthorization:
    oauth_client_authorization_id: str
    client_id: str
    external_identity_id: str
    user_id: str
    granted_scopes: tuple[str, ...]
    default_workspace_id: str
    created_at: str
    revoked_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        string_values = (
            self.oauth_client_authorization_id,
            self.client_id,
            self.external_identity_id,
            self.user_id,
            self.default_workspace_id,
            self.created_at,
        )
        if (
            any(type(value) is not str for value in string_values)
            or (self.revoked_at is not None and type(self.revoked_at) is not str)
            or type(self.granted_scopes) is not tuple
            or any(type(scope) is not str for scope in self.granted_scopes)
        ):
            raise ContractValidationError("OAuthClientAuthorization is invalid")
        payload = {
            "oauth_client_authorization_id": self.oauth_client_authorization_id,
            "client_id": self.client_id,
            "external_identity_id": self.external_identity_id,
            "user_id": self.user_id,
            "granted_scopes": list(self.granted_scopes),
            "default_workspace_id": self.default_workspace_id,
            "created_at": self.created_at,
            "revoked_at": self.revoked_at,
        }
        _validate_client_authorization(payload)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OAuthClientAuthorization":
        payload = _validate_client_authorization(value)
        return cls(
            oauth_client_authorization_id=payload["oauth_client_authorization_id"],
            client_id=payload["client_id"],
            external_identity_id=payload["external_identity_id"],
            user_id=payload["user_id"],
            granted_scopes=tuple(payload["granted_scopes"]),
            default_workspace_id=payload["default_workspace_id"],
            created_at=payload["created_at"],
            revoked_at=payload.get("revoked_at"),
        )


@dataclass(frozen=True)
class OAuthTransaction:
    transaction_id: str
    google_state_hash: str
    encrypted_client_state: str
    google_nonce_hash: str
    client_id: str
    redirect_uri: str
    resource: str
    scopes: tuple[str, ...]
    code_challenge: str
    code_challenge_method: str
    created_at: str
    expires_at: str
    status: OAuthTransactionStatus = "pending"
    consumed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        string_values = (
            self.transaction_id,
            self.google_state_hash,
            self.encrypted_client_state,
            self.google_nonce_hash,
            self.client_id,
            self.redirect_uri,
            self.resource,
            self.code_challenge,
            self.code_challenge_method,
            self.created_at,
            self.expires_at,
            self.status,
        )
        if (
            any(type(value) is not str for value in string_values)
            or (self.consumed_at is not None and type(self.consumed_at) is not str)
            or type(self.scopes) is not tuple
            or any(type(scope) is not str for scope in self.scopes)
        ):
            raise ContractValidationError("OAuthTransaction is invalid")
        payload = {
            "transaction_id": self.transaction_id,
            "google_state_hash": self.google_state_hash,
            "encrypted_client_state": self.encrypted_client_state,
            "google_nonce_hash": self.google_nonce_hash,
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "resource": self.resource,
            "scopes": list(self.scopes),
            "code_challenge": self.code_challenge,
            "code_challenge_method": self.code_challenge_method,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "consumed_at": self.consumed_at,
        }
        _validate_transaction(payload)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OAuthTransaction":
        payload = _validate_transaction(value)
        return cls(
            transaction_id=payload["transaction_id"],
            google_state_hash=payload["google_state_hash"],
            encrypted_client_state=payload["encrypted_client_state"],
            google_nonce_hash=payload["google_nonce_hash"],
            client_id=payload["client_id"],
            redirect_uri=payload["redirect_uri"],
            resource=payload["resource"],
            scopes=tuple(payload["scopes"]),
            code_challenge=payload["code_challenge"],
            code_challenge_method=payload["code_challenge_method"],
            created_at=payload["created_at"],
            expires_at=payload["expires_at"],
            status=payload["status"],
            consumed_at=payload.get("consumed_at"),
        )


@dataclass(frozen=True)
class OAuthAuthorizationCode:
    code_hash: str
    transaction_id: str
    user_id: str
    external_identity_id: str
    client_id: str
    redirect_uri: str
    resource: str
    scopes: tuple[str, ...]
    code_challenge: str
    created_at: str
    expires_at: str
    consumed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        string_values = (
            self.code_hash,
            self.transaction_id,
            self.user_id,
            self.external_identity_id,
            self.client_id,
            self.redirect_uri,
            self.resource,
            self.code_challenge,
            self.created_at,
            self.expires_at,
        )
        if (
            any(type(value) is not str for value in string_values)
            or (self.consumed_at is not None and type(self.consumed_at) is not str)
            or type(self.scopes) is not tuple
            or any(type(scope) is not str for scope in self.scopes)
        ):
            raise ContractValidationError("OAuthAuthorizationCode is invalid")
        payload = {
            "code_hash": self.code_hash,
            "transaction_id": self.transaction_id,
            "user_id": self.user_id,
            "external_identity_id": self.external_identity_id,
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "resource": self.resource,
            "scopes": list(self.scopes),
            "code_challenge": self.code_challenge,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
        }
        _validate_authorization_code(payload)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OAuthAuthorizationCode":
        payload = _validate_authorization_code(value)
        return cls(
            code_hash=payload["code_hash"],
            transaction_id=payload["transaction_id"],
            user_id=payload["user_id"],
            external_identity_id=payload["external_identity_id"],
            client_id=payload["client_id"],
            redirect_uri=payload["redirect_uri"],
            resource=payload["resource"],
            scopes=tuple(payload["scopes"]),
            code_challenge=payload["code_challenge"],
            created_at=payload["created_at"],
            expires_at=payload["expires_at"],
            consumed_at=payload.get("consumed_at"),
        )


@dataclass(frozen=True)
class OAuthTokenSession:
    token_session_id: str
    user_id: str
    external_identity_id: str
    oauth_client_authorization_id: str
    client_id: str
    current_workspace_id: str
    resource: str
    scopes: tuple[str, ...]
    token_jti_hash: str
    issued_at: str
    expires_at: str
    revoked_at: str | None = None
    revocation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        string_values = (
            self.token_session_id,
            self.user_id,
            self.external_identity_id,
            self.oauth_client_authorization_id,
            self.client_id,
            self.current_workspace_id,
            self.resource,
            self.token_jti_hash,
            self.issued_at,
            self.expires_at,
        )
        optional_string_values = (
            self.revoked_at,
            self.revocation_reason,
        )
        if (
            any(type(value) is not str for value in string_values)
            or any(value is not None and type(value) is not str for value in optional_string_values)
            or type(self.scopes) is not tuple
            or any(type(scope) is not str for scope in self.scopes)
        ):
            raise ContractValidationError("OAuthTokenSession is invalid")
        payload = {
            "token_session_id": self.token_session_id,
            "user_id": self.user_id,
            "external_identity_id": self.external_identity_id,
            "oauth_client_authorization_id": self.oauth_client_authorization_id,
            "client_id": self.client_id,
            "current_workspace_id": self.current_workspace_id,
            "resource": self.resource,
            "scopes": list(self.scopes),
            "token_jti_hash": self.token_jti_hash,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "revocation_reason": self.revocation_reason,
        }
        _validate_token_session(payload)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OAuthTokenSession":
        payload = _validate_token_session(value)
        return cls(
            token_session_id=payload["token_session_id"],
            user_id=payload["user_id"],
            external_identity_id=payload["external_identity_id"],
            oauth_client_authorization_id=payload["oauth_client_authorization_id"],
            client_id=payload["client_id"],
            current_workspace_id=payload["current_workspace_id"],
            resource=payload["resource"],
            scopes=tuple(payload["scopes"]),
            token_jti_hash=payload["token_jti_hash"],
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
            revoked_at=payload.get("revoked_at"),
            revocation_reason=payload.get("revocation_reason"),
        )


@dataclass(frozen=True)
class OAuthPrincipal:
    user_id: str
    external_identity_id: str
    oauth_client_id: str
    token_session_id: str
    scopes: tuple[str, ...]
    resource: str

    def to_dict(self) -> dict[str, Any]:
        string_values = (
            self.user_id,
            self.external_identity_id,
            self.oauth_client_id,
            self.token_session_id,
            self.resource,
        )
        if (
            any(type(value) is not str for value in string_values)
            or type(self.scopes) is not tuple
            or any(type(scope) is not str for scope in self.scopes)
        ):
            raise ContractValidationError("OAuthPrincipal is invalid")
        payload = {
            "user_id": self.user_id,
            "external_identity_id": self.external_identity_id,
            "oauth_client_id": self.oauth_client_id,
            "token_session_id": self.token_session_id,
            "scopes": list(self.scopes),
            "resource": self.resource,
        }
        _required_safe_ids(
            payload,
            ("user_id", "external_identity_id", "oauth_client_id", "token_session_id"),
            "OAuthPrincipal",
        )
        _validate_scopes(payload["scopes"], "OAuthPrincipal.scopes")
        _required_string(payload, "resource", "OAuthPrincipal")
        return payload


class OAuthAccessDenied(Exception):
    """Typed, safe OAuth denial suitable for the MCP gateway boundary."""

    def __init__(self, error: str, reason_code: str, http_status: int) -> None:
        if type(error) is not str or error not in _OAUTH_ERRORS:
            raise ValueError("unsupported OAuth error code")
        if type(reason_code) is not str or not _SAFE_REASON.fullmatch(reason_code):
            raise ValueError("reason_code must be a safe machine code")
        if type(http_status) is not int or http_status not in {400, 401, 403, 500}:
            raise ValueError("unsupported OAuth denial HTTP status")
        self.error = error
        self.reason_code = reason_code
        self.http_status = http_status
        super().__init__(reason_code)

    def to_safe_dict(self) -> dict[str, Any]:
        if type(self.error) is not str or self.error not in _OAUTH_ERRORS:
            raise ValueError("unsupported OAuth error code")
        if type(self.reason_code) is not str or not _SAFE_REASON.fullmatch(self.reason_code):
            raise ValueError("reason_code must be a safe machine code")
        if type(self.http_status) is not int or self.http_status not in {
            400,
            401,
            403,
            500,
        }:
            raise ValueError("unsupported OAuth denial HTTP status")
        return {
            "error": self.error,
            "reason_code": self.reason_code,
            "http_status": self.http_status,
        }


def _validate_external_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "ExternalIdentity")
    if any(not isinstance(key, str) or key not in _EXTERNAL_IDENTITY_FIELDS for key in payload):
        raise ContractValidationError("ExternalIdentity contains unsupported fields")
    _required_safe_ids(
        payload,
        ("external_identity_id", "user_id"),
        "ExternalIdentity",
    )
    for field in (
        "provider",
        "issuer",
        "subject",
        "email",
        "status",
        "created_at",
        "last_authenticated_at",
    ):
        _required_string(payload, field, "ExternalIdentity")
    if payload["provider"] != "google":
        raise ContractValidationError("ExternalIdentity.provider must be google")
    if payload["status"] not in {"active", "disabled"}:
        raise ContractValidationError("ExternalIdentity.status is not supported")
    if payload.get("email_verified") is not True:
        raise ContractValidationError("ExternalIdentity.email_verified must be true")
    _validate_timestamp(payload["created_at"], "ExternalIdentity.created_at")
    _validate_timestamp(payload["last_authenticated_at"], "ExternalIdentity.last_authenticated_at")
    return payload


def _validate_invitation(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "OAuthInvitation")
    if any(not isinstance(key, str) or key not in _OAUTH_INVITATION_FIELDS for key in payload):
        raise ContractValidationError("OAuthInvitation contains unsupported fields")
    _required_safe_ids(payload, ("invitation_id", "workspace_id"), "OAuthInvitation")
    for field in ("normalized_email", "role", "status", "expires_at", "created_at"):
        _required_string(payload, field, "OAuthInvitation")
    if payload["normalized_email"] != str(payload["normalized_email"]).casefold():
        raise ContractValidationError("OAuthInvitation.normalized_email must be normalized")
    if payload["role"] not in {"owner", "member", "viewer"}:
        raise ContractValidationError("OAuthInvitation.role is not supported")
    if payload["status"] not in {"pending", "accepted", "revoked", "expired"}:
        raise ContractValidationError("OAuthInvitation.status is not supported")
    _optional_safe_ids(
        payload,
        ("intended_user_id", "accepted_external_identity_id"),
        "OAuthInvitation",
    )
    _optional_timestamps(payload, ("accepted_at",), "OAuthInvitation")
    _validate_timestamp(payload["expires_at"], "OAuthInvitation.expires_at")
    _validate_timestamp(payload["created_at"], "OAuthInvitation.created_at")
    return payload


def _validate_owner_bootstrap(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "OAuthOwnerBootstrap")
    allowed_fields = {
        "workspace_id",
        "normalized_email",
        "idempotency_key_hash",
        "invitation_id",
        "operator_service_id",
        "status",
        "created_at",
        "completed_at",
    }
    if any(not isinstance(key, str) or key not in allowed_fields for key in payload):
        raise ContractValidationError("OAuthOwnerBootstrap contains unsupported fields")
    _required_safe_ids(
        payload,
        ("workspace_id", "invitation_id", "operator_service_id"),
        "OAuthOwnerBootstrap",
    )
    for field in (
        "normalized_email",
        "idempotency_key_hash",
        "status",
        "created_at",
    ):
        _required_string(payload, field, "OAuthOwnerBootstrap")
    if payload["normalized_email"] != str(payload["normalized_email"]).casefold():
        raise ContractValidationError("OAuthOwnerBootstrap.normalized_email must be normalized")
    _validate_hash(
        payload["idempotency_key_hash"],
        "OAuthOwnerBootstrap.idempotency_key_hash",
    )
    if payload["status"] not in {"pending", "completed"}:
        raise ContractValidationError("OAuthOwnerBootstrap.status is not supported")
    _validate_timestamp(payload["created_at"], "OAuthOwnerBootstrap.created_at")
    _optional_timestamps(payload, ("completed_at",), "OAuthOwnerBootstrap")
    if payload["status"] == "pending" and payload.get("completed_at") is not None:
        raise ContractValidationError("pending OAuthOwnerBootstrap cannot be completed")
    if payload["status"] == "completed" and payload.get("completed_at") is None:
        raise ContractValidationError("completed OAuthOwnerBootstrap requires completed_at")
    return payload


def _validate_client_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "OAuthClientAuthorization")
    if any(
        not isinstance(key, str) or key not in _OAUTH_CLIENT_AUTHORIZATION_FIELDS for key in payload
    ):
        raise ContractValidationError("OAuthClientAuthorization contains unsupported fields")
    _required_safe_ids(
        payload,
        (
            "oauth_client_authorization_id",
            "client_id",
            "external_identity_id",
            "user_id",
            "default_workspace_id",
        ),
        "OAuthClientAuthorization",
    )
    _validate_scopes(payload.get("granted_scopes"), "OAuthClientAuthorization.granted_scopes")
    _required_string(payload, "created_at", "OAuthClientAuthorization")
    _validate_timestamp(payload["created_at"], "OAuthClientAuthorization.created_at")
    _optional_timestamps(payload, ("revoked_at",), "OAuthClientAuthorization")
    return payload


def _validate_transaction(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "OAuthTransaction")
    if any(not isinstance(key, str) or key not in _OAUTH_TRANSACTION_FIELDS for key in payload):
        raise ContractValidationError("OAuthTransaction contains unsupported fields")
    _required_safe_ids(payload, ("transaction_id", "client_id"), "OAuthTransaction")
    for field in (
        "google_state_hash",
        "encrypted_client_state",
        "google_nonce_hash",
        "redirect_uri",
        "resource",
        "code_challenge",
        "code_challenge_method",
        "created_at",
        "expires_at",
        "status",
    ):
        _required_string(payload, field, "OAuthTransaction")
    _validate_hash(payload["google_state_hash"], "OAuthTransaction.google_state_hash")
    _validate_hash(payload["google_nonce_hash"], "OAuthTransaction.google_nonce_hash")
    _validate_code_challenge(payload["code_challenge"], "OAuthTransaction.code_challenge")
    if payload["code_challenge_method"] != "S256":
        raise ContractValidationError("OAuthTransaction.code_challenge_method must be S256")
    if payload["status"] not in {"pending", "consumed", "failed"}:
        raise ContractValidationError("OAuthTransaction.status is not supported")
    _validate_scopes(payload.get("scopes"), "OAuthTransaction.scopes")
    _validate_timestamp(payload["created_at"], "OAuthTransaction.created_at")
    _validate_timestamp(payload["expires_at"], "OAuthTransaction.expires_at")
    _optional_timestamps(payload, ("consumed_at",), "OAuthTransaction")
    return payload


def _validate_authorization_code(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "OAuthAuthorizationCode")
    if any(
        not isinstance(key, str) or key not in _OAUTH_AUTHORIZATION_CODE_FIELDS for key in payload
    ):
        raise ContractValidationError("OAuthAuthorizationCode contains unsupported fields")
    _validate_hash(payload.get("code_hash"), "OAuthAuthorizationCode.code_hash")
    _required_safe_ids(
        payload,
        ("transaction_id", "user_id", "external_identity_id", "client_id"),
        "OAuthAuthorizationCode",
    )
    for field in ("redirect_uri", "resource", "created_at", "expires_at"):
        _required_string(payload, field, "OAuthAuthorizationCode")
    _validate_code_challenge(payload.get("code_challenge"), "OAuthAuthorizationCode.code_challenge")
    _validate_scopes(payload.get("scopes"), "OAuthAuthorizationCode.scopes")
    _validate_timestamp(payload["created_at"], "OAuthAuthorizationCode.created_at")
    _validate_timestamp(payload["expires_at"], "OAuthAuthorizationCode.expires_at")
    _optional_timestamps(payload, ("consumed_at",), "OAuthAuthorizationCode")
    return payload


def _validate_token_session(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "OAuthTokenSession")
    if any(not isinstance(key, str) or key not in _OAUTH_TOKEN_SESSION_FIELDS for key in payload):
        raise ContractValidationError("OAuthTokenSession contains unsupported fields")
    _required_safe_ids(
        payload,
        (
            "token_session_id",
            "user_id",
            "external_identity_id",
            "oauth_client_authorization_id",
            "client_id",
            "current_workspace_id",
        ),
        "OAuthTokenSession",
    )
    _required_string(payload, "resource", "OAuthTokenSession")
    _validate_scopes(payload.get("scopes"), "OAuthTokenSession.scopes")
    _validate_hash(payload.get("token_jti_hash"), "OAuthTokenSession.token_jti_hash")
    _required_string(payload, "issued_at", "OAuthTokenSession")
    _required_string(payload, "expires_at", "OAuthTokenSession")
    _validate_timestamp(payload["issued_at"], "OAuthTokenSession.issued_at")
    _validate_timestamp(payload["expires_at"], "OAuthTokenSession.expires_at")
    _optional_timestamps(payload, ("revoked_at",), "OAuthTokenSession")
    if payload.get("revocation_reason") is not None:
        reason = payload["revocation_reason"]
        if not isinstance(reason, str) or not _SAFE_REASON.fullmatch(reason):
            raise ContractValidationError("OAuthTokenSession.revocation_reason is invalid")
    return payload


def _mapping(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if type(name) is not str or not name:
        raise ContractValidationError("OAuth record name is invalid")
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{name} must be an object")
    try:
        return dict(value)
    except Exception:
        raise ContractValidationError(f"{name} must be an object") from None


def _required_string(payload: dict[str, Any], field: str, name: str) -> None:
    if (
        type(payload) is not dict
        or any(type(key) is not str for key in payload)
        or type(field) is not str
        or not field
        or type(name) is not str
        or not name
    ):
        raise ContractValidationError("OAuth record validation input is invalid")
    value = payload.get(field)
    if type(value) is not str or not value:
        raise ContractValidationError(f"{name}.{field} is required")


def _required_safe_ids(payload: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    if (
        type(payload) is not dict
        or any(type(key) is not str for key in payload)
        or type(fields) is not tuple
        or any(type(field) is not str or not field for field in fields)
        or type(name) is not str
        or not name
    ):
        raise ContractValidationError("OAuth record validation input is invalid")
    for field in fields:
        _required_string(payload, field, name)
        if not _SAFE_ID.fullmatch(payload[field]):
            raise ContractValidationError(f"{name}.{field} must be a safe id")


def _optional_safe_ids(payload: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    if (
        type(payload) is not dict
        or any(type(key) is not str for key in payload)
        or type(fields) is not tuple
        or any(type(field) is not str or not field for field in fields)
        or type(name) is not str
        or not name
    ):
        raise ContractValidationError("OAuth record validation input is invalid")
    for field in fields:
        value = payload.get(field)
        if value is not None and (type(value) is not str or not _SAFE_ID.fullmatch(value)):
            raise ContractValidationError(f"{name}.{field} must be a safe id")


def _validate_hash(value: Any, name: str) -> None:
    if type(name) is not str or not name:
        raise ContractValidationError("OAuth record validation input is invalid")
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ContractValidationError(f"{name} must be a SHA-256 hash")


def _validate_code_challenge(value: Any, name: str) -> None:
    if type(name) is not str or not name:
        raise ContractValidationError("OAuth record validation input is invalid")
    if type(value) is not str or not _CODE_CHALLENGE.fullmatch(value):
        raise ContractValidationError(f"{name} is invalid")


def _validate_scopes(value: Any, name: str) -> None:
    if not isinstance(value, (list, tuple)) or not value:
        raise ContractValidationError(f"{name} must be a non-empty list")
    # Reject JSON objects and arrays before any hashing-based duplicate check.
    for scope in value:
        if not isinstance(scope, str) or not _SAFE_SCOPE.fullmatch(scope):
            raise ContractValidationError(f"{name} contains an invalid scope")
    if len(set(value)) != len(value):
        raise ContractValidationError(f"{name} must not contain duplicates")


def _validate_timestamp(value: Any, name: str) -> None:
    if type(name) is not str or not name:
        raise ContractValidationError("OAuth record validation input is invalid")
    if type(value) is not str or not value:
        raise ContractValidationError(f"{name} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractValidationError(f"{name} must be ISO-8601") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError(f"{name} must include a timezone")


def _optional_timestamps(payload: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    if (
        type(payload) is not dict
        or any(type(key) is not str for key in payload)
        or type(fields) is not tuple
        or any(type(field) is not str or not field for field in fields)
        or type(name) is not str
        or not name
    ):
        raise ContractValidationError("OAuth record validation input is invalid")
    for field in fields:
        value = payload.get(field)
        if value is not None:
            _validate_timestamp(value, f"{name}.{field}")


__all__ = [
    "ExternalIdentity",
    "OAuthAccessDenied",
    "OAuthAuthorizationCode",
    "OAuthClientAuthorization",
    "OAuthInvitation",
    "OAuthOwnerBootstrap",
    "OAuthPrincipal",
    "OAuthTokenSession",
    "OAuthTransaction",
]
