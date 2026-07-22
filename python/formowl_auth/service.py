"""Google-backed FormOwl OAuth 2.1 authorization bridge."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import secrets
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

from formowl_contract import (
    AuditLog,
    ContractValidationError,
    SessionIdentity,
    User,
    WorkspaceMember,
)

from .audit import sanitize_oauth_audit_metadata
from .config import GOOGLE_ISSUER, OAuthBridgeConfig
from .google_oidc import GoogleIdentity, GoogleOidcClient
from .models import (
    ExternalIdentity,
    OAuthAccessDenied,
    OAuthAuthorizationCode,
    OAuthClientAuthorization,
    OAuthInvitation,
    OAuthOwnerBootstrap,
    OAuthPrincipal,
    OAuthTokenSession,
    OAuthTransaction,
)
from .postgres import OAuthRepository
from .provider import ActorContext
from .security import (
    RandomBytes,
    decrypt_client_state,
    encrypt_client_state,
    generate_opaque_value,
    generate_safe_id,
    hash_oauth_value,
    normalize_verified_email,
    pkce_s256_challenge,
)
from .tokens import FormOwlTokenCodec


_SAFE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_TRUSTED_HTTP_DENIAL_REASONS = frozenset(
    {
        "client_authorization_revoked",
        "external_identity_disabled",
        "formowl_user_disabled",
        "token_expired",
        "token_session_expired",
        "token_session_revoked",
    }
)


class FormOwlOAuthBridge:
    def __init__(
        self,
        *,
        config: OAuthBridgeConfig,
        repository: OAuthRepository,
        google_client: GoogleOidcClient,
        token_codec: FormOwlTokenCodec,
        random_bytes: RandomBytes = secrets.token_bytes,
        owner_bootstrap_operator_authorizer: Callable[[str], bool] | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.google_client = google_client
        self.token_codec = token_codec
        self.random_bytes = random_bytes
        self.owner_bootstrap_operator_authorizer = owner_bootstrap_operator_authorizer

    def _require_stateful_oauth(self) -> None:
        """Fail before repository access while the redirect sentinel is active."""

        if self.config.chatgpt_callback_mode == "discovery_only":
            raise OAuthAccessDenied(
                "access_denied",
                "discovery_only",
                403,
            )

    def provision_invitation(
        self,
        *,
        email: str,
        workspace_id: str,
        role: str,
        invited_by_user_id: str,
        operator_service_id: str,
        expires_at: datetime,
        now: datetime,
        intended_user_id: str | None = None,
    ) -> OAuthInvitation:
        self._require_stateful_oauth()
        _require_aware(now)
        _require_aware(expires_at)
        try:
            _safe_id(operator_service_id, "operator_service_id")
            operator_authorized = (
                self.owner_bootstrap_operator_authorizer is not None
                and self.owner_bootstrap_operator_authorizer(operator_service_id) is True
            )
        except Exception:
            operator_authorized = False
        if not operator_authorized:
            try:
                with self.repository.transaction() as unit:
                    self.repository.append_audit_log(
                        self._audit_log(
                            actor_user_id=None,
                            actor_type="external_unauthenticated",
                            action="oauth_invitation_create",
                            target_type="operator_invitation",
                            target_id="operator_invitation",
                            session_id="operator_invitation",
                            timestamp=now,
                            status="denied",
                            reason_code="operator_unauthorized",
                            metadata={"event_stage": "invitation"},
                        )
                    )
                    unit.commit()
            except Exception:
                raise OAuthAccessDenied(
                    "server_error",
                    "invitation_audit_unavailable",
                    500,
                ) from None
            raise OAuthAccessDenied("access_denied", "operator_unauthorized", 403)

        invitation: OAuthInvitation | None = None
        denied: OAuthAccessDenied | None = None
        approval_metadata: dict[str, Any] = {"event_stage": "invitation"}
        try:
            with self.repository.transaction() as unit:
                try:
                    if expires_at <= now:
                        raise OAuthAccessDenied(
                            "invalid_request",
                            "invitation_expiry_invalid",
                            400,
                        )
                    if role not in {"owner", "member", "viewer"}:
                        raise OAuthAccessDenied(
                            "invalid_request",
                            "invitation_role_invalid",
                            400,
                        )
                    try:
                        _safe_id(workspace_id, "workspace_id")
                        _safe_id(invited_by_user_id, "invited_by_user_id")
                        if intended_user_id is not None:
                            _safe_id(intended_user_id, "intended_user_id")
                        normalized_email = normalize_verified_email(email)
                    except Exception:
                        raise OAuthAccessDenied(
                            "invalid_request",
                            "invitation_input_invalid",
                            400,
                        ) from None
                    approval_metadata = {
                        "event_stage": "invitation",
                        "lineage_source": "owner_approval",
                        "approval_user_id": invited_by_user_id,
                    }
                    inviter = self.repository.get_user(invited_by_user_id)
                    membership = self.repository.get_active_workspace_member(
                        invited_by_user_id,
                        workspace_id,
                    )
                    if inviter is None or inviter.status != "active" or membership is None:
                        raise OAuthAccessDenied(
                            "access_denied",
                            "invitation_approval_denied",
                            403,
                        )
                    if membership.role != "owner":
                        raise OAuthAccessDenied(
                            "access_denied",
                            "invitation_owner_required",
                            403,
                        )
                    if intended_user_id is not None:
                        intended_user = self.repository.get_user(intended_user_id)
                        if intended_user is None or intended_user.status != "active":
                            raise OAuthAccessDenied(
                                "invalid_request",
                                "intended_user_invalid",
                                400,
                            )
                    invitation = OAuthInvitation(
                        invitation_id=generate_safe_id("invite", random_bytes=self.random_bytes),
                        normalized_email=normalized_email,
                        workspace_id=workspace_id,
                        role=role,
                        status="pending",
                        expires_at=_iso(expires_at),
                        created_at=_iso(now),
                        intended_user_id=intended_user_id,
                    )
                    self.repository.insert_invitation(invitation)
                except OAuthAccessDenied as error:
                    denied = error
                target_id = (
                    invitation.invitation_id
                    if invitation is not None
                    else workspace_id
                    if isinstance(workspace_id, str) and _SAFE_CODE.fullmatch(workspace_id)
                    else "operator_invitation"
                )
                self.repository.append_audit_log(
                    self._audit_log(
                        actor_user_id=None,
                        actor_type="service",
                        actor_service_id=operator_service_id,
                        action="oauth_invitation_create",
                        target_type=("oauth_invitation" if invitation is not None else "workspace"),
                        target_id=target_id,
                        session_id=target_id,
                        workspace_id=(
                            workspace_id
                            if isinstance(workspace_id, str) and _SAFE_CODE.fullmatch(workspace_id)
                            else None
                        ),
                        timestamp=now,
                        status="denied" if denied is not None else "ok",
                        reason_code=(denied.reason_code if denied else "invitation_created"),
                        metadata=approval_metadata,
                    )
                )
                unit.commit()
        except Exception:
            raise OAuthAccessDenied(
                "server_error",
                "invitation_persistence_unavailable",
                500,
            ) from None
        if denied is not None:
            raise denied
        if invitation is None:
            raise OAuthAccessDenied(
                "server_error",
                "invitation_persistence_unavailable",
                500,
            )
        return invitation

    def bootstrap_owner_invitation(
        self,
        *,
        workspace_id: str,
        email: str,
        expires_at: datetime,
        idempotency_key: str,
        operator_service_id: str,
        now: datetime,
    ) -> OAuthInvitation:
        self._require_stateful_oauth()
        _require_aware(now)
        _require_aware(expires_at)
        _safe_id(workspace_id, "workspace_id")
        _safe_id(operator_service_id, "operator_service_id")
        try:
            operator_authorized = (
                self.owner_bootstrap_operator_authorizer is not None
                and self.owner_bootstrap_operator_authorizer(operator_service_id) is True
            )
        except Exception as exc:
            raise OAuthAccessDenied(
                "access_denied",
                "owner_bootstrap_operator_unauthorized",
                403,
            ) from exc
        if not operator_authorized:
            raise OAuthAccessDenied(
                "access_denied",
                "owner_bootstrap_operator_unauthorized",
                403,
            )
        if expires_at <= now:
            raise OAuthAccessDenied("invalid_request", "owner_bootstrap_expiry_invalid", 400)
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key
            or len(idempotency_key) > 2048
        ):
            raise OAuthAccessDenied(
                "invalid_request",
                "owner_bootstrap_idempotency_invalid",
                400,
            )
        normalized_email = normalize_verified_email(email)
        idempotency_key_hash = hash_oauth_value(
            "owner_bootstrap_idempotency",
            idempotency_key,
        )
        with self.repository.transaction() as unit:
            pending_owner_invitations = self.repository.find_pending_owner_invitations(
                workspace_id,
                now=_iso(now),
                for_update=True,
            )
            if pending_owner_invitations and (
                len(pending_owner_invitations) != 1
                or pending_owner_invitations[0].normalized_email != normalized_email
                or pending_owner_invitations[0].intended_user_id is not None
            ):
                raise OAuthAccessDenied(
                    "access_denied",
                    "owner_bootstrap_invitation_conflict",
                    403,
                )
            invitation_id = (
                pending_owner_invitations[0].invitation_id
                if pending_owner_invitations
                else generate_safe_id("invite", random_bytes=self.random_bytes)
            )
            candidate = OAuthOwnerBootstrap(
                workspace_id=workspace_id,
                normalized_email=normalized_email,
                idempotency_key_hash=idempotency_key_hash,
                invitation_id=invitation_id,
                operator_service_id=operator_service_id,
                status="pending",
                created_at=_iso(now),
            )
            created = self.repository.upsert_owner_bootstrap(candidate)
            bootstrap = self.repository.get_owner_bootstrap(
                workspace_id,
                for_update=True,
            )
            if bootstrap is None:
                raise OAuthAccessDenied(
                    "server_error",
                    "owner_bootstrap_state_invalid",
                    500,
                )
            if (
                bootstrap.normalized_email != normalized_email
                or bootstrap.idempotency_key_hash != idempotency_key_hash
                or bootstrap.operator_service_id != operator_service_id
            ):
                raise OAuthAccessDenied(
                    "access_denied",
                    "owner_bootstrap_conflict",
                    403,
                )
            invitation = self.repository.get_invitation(bootstrap.invitation_id)
            if bootstrap.status == "completed":
                if (
                    invitation is None
                    or invitation.status != "accepted"
                    or invitation.workspace_id != workspace_id
                    or invitation.role != "owner"
                    or invitation.normalized_email != normalized_email
                ):
                    raise OAuthAccessDenied(
                        "server_error",
                        "owner_bootstrap_state_invalid",
                        500,
                    )
                unit.commit()
                return invitation
            if bootstrap.status != "pending":
                raise OAuthAccessDenied(
                    "server_error",
                    "owner_bootstrap_state_invalid",
                    500,
                )
            if self.repository.count_active_workspace_members(workspace_id) != 0:
                raise OAuthAccessDenied(
                    "access_denied",
                    "owner_bootstrap_workspace_not_empty",
                    403,
                )
            if pending_owner_invitations and (
                pending_owner_invitations[0].invitation_id != bootstrap.invitation_id
            ):
                raise OAuthAccessDenied(
                    "access_denied",
                    "owner_bootstrap_invitation_conflict",
                    403,
                )
            if invitation is None:
                if not created:
                    raise OAuthAccessDenied(
                        "server_error",
                        "owner_bootstrap_state_invalid",
                        500,
                    )
                invitation = OAuthInvitation(
                    invitation_id=bootstrap.invitation_id,
                    normalized_email=normalized_email,
                    workspace_id=workspace_id,
                    role="owner",
                    status="pending",
                    expires_at=_iso(expires_at),
                    created_at=_iso(now),
                )
                self.repository.insert_invitation(invitation)
            elif (
                invitation.workspace_id != workspace_id
                or invitation.normalized_email != normalized_email
                or invitation.role != "owner"
                or invitation.status != "pending"
                or invitation.intended_user_id is not None
                or _parse_iso(invitation.expires_at) <= now
            ):
                raise OAuthAccessDenied(
                    "access_denied",
                    "owner_bootstrap_invitation_conflict",
                    403,
                )
            if not created:
                unit.commit()
                return invitation
            self.repository.append_audit_log(
                AuditLog(
                    audit_log_id=generate_safe_id("audit", random_bytes=self.random_bytes),
                    actor_user_id=None,
                    actor_type="service",
                    actor_service_id=operator_service_id,
                    action="oauth_owner_bootstrap_created",
                    target_type="oauth_owner_bootstrap",
                    target_id=invitation.invitation_id,
                    session_id=invitation.invitation_id,
                    workspace_id=workspace_id,
                    status="ok",
                    reason_code="owner_bootstrap_created",
                    timestamp=_iso(now),
                    metadata={"event_stage": "owner_bootstrap"},
                )
            )
            unit.commit()
        return invitation

    def validate_authorization_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        required = (
            "client_id",
            "redirect_uri",
            "response_type",
            "resource",
            "scope",
            "state",
            "code_challenge",
            "code_challenge_method",
        )
        if any(not isinstance(request.get(key), str) or not request.get(key) for key in required):
            raise OAuthAccessDenied("invalid_request", "authorization_parameter_missing", 400)
        if request["client_id"] != self.config.chatgpt_client_id:
            raise OAuthAccessDenied("unauthorized_client", "oauth_client_invalid", 400)
        if request["redirect_uri"] != self.config.chatgpt_redirect_uri:
            raise OAuthAccessDenied("invalid_request", "redirect_uri_invalid", 400)
        if request["response_type"] != "code":
            raise OAuthAccessDenied(
                "unsupported_response_type",
                "response_type_invalid",
                400,
            )
        if request["resource"] != self.config.resource:
            raise OAuthAccessDenied("invalid_target", "resource_invalid", 400)
        scopes = tuple(str(request["scope"]).split(" "))
        if scopes != self.config.scopes:
            raise OAuthAccessDenied("invalid_scope", "scope_invalid", 400)
        if request["code_challenge_method"] != "S256":
            raise OAuthAccessDenied("invalid_request", "pkce_method_invalid", 400)
        if not _CODE_CHALLENGE.fullmatch(str(request["code_challenge"])):
            raise OAuthAccessDenied("invalid_request", "pkce_challenge_invalid", 400)
        if len(str(request["state"])) > 2048:
            raise OAuthAccessDenied("invalid_request", "client_state_invalid", 400)
        return {
            "client_id": str(request["client_id"]),
            "redirect_uri": str(request["redirect_uri"]),
            "response_type": "code",
            "resource": str(request["resource"]),
            "scopes": scopes,
            "client_state": str(request["state"]),
            "code_challenge": str(request["code_challenge"]),
            "code_challenge_method": "S256",
        }

    def start_authorization(
        self,
        request: Mapping[str, Any],
        *,
        now: datetime,
    ) -> dict[str, str]:
        self._require_stateful_oauth()
        _require_aware(now)
        validated = self.validate_authorization_request(request)
        google_state = generate_opaque_value(random_bytes=self.random_bytes)
        google_nonce = generate_opaque_value(random_bytes=self.random_bytes)
        transaction = OAuthTransaction(
            transaction_id=generate_safe_id("oauthtx", random_bytes=self.random_bytes),
            google_state_hash=hash_oauth_value("google_state", google_state),
            encrypted_client_state=encrypt_client_state(
                validated["client_state"],
                self.config.state_encryption_key,
            ),
            google_nonce_hash=hash_oauth_value("google_nonce", google_nonce),
            client_id=validated["client_id"],
            redirect_uri=validated["redirect_uri"],
            resource=validated["resource"],
            scopes=validated["scopes"],
            code_challenge=validated["code_challenge"],
            code_challenge_method=validated["code_challenge_method"],
            created_at=_iso(now),
            expires_at=_iso(
                now + timedelta(seconds=self.config.authorization_transaction_lifetime_seconds)
            ),
        )
        with self.repository.transaction() as unit:
            self.repository.insert_transaction(transaction)
            self.repository.append_audit_log(
                self._audit_log(
                    actor_user_id=None,
                    actor_type="external_unauthenticated",
                    action="oauth_authorization_started",
                    target_type="oauth_transaction",
                    target_id=transaction.transaction_id,
                    session_id=transaction.transaction_id,
                    timestamp=now,
                    status="ok",
                    oauth_client_id=transaction.client_id,
                    reason_code="authorization_started",
                    metadata={
                        "event_stage": "authorization",
                        "provider": "google",
                        "scopes": list(transaction.scopes),
                    },
                )
            )
            unit.commit()
        return {
            "authorization_url": self.google_client.build_authorization_url(
                google_state=google_state,
                google_nonce=google_nonce,
            ),
            "transaction_id": transaction.transaction_id,
        }

    async def complete_google_callback(
        self,
        *,
        google_state: str,
        google_code: str,
        now: datetime,
    ) -> dict[str, str]:
        self._require_stateful_oauth()
        _require_aware(now)
        if not google_state or not google_code:
            raise OAuthAccessDenied("access_denied", "google_callback_incomplete", 400)
        state_hash = hash_oauth_value("google_state", google_state)
        initial = self.repository.get_transaction_by_state_hash(state_hash)
        self._validate_pending_transaction(initial, now=now)
        assert initial is not None
        if (
            initial.client_id != self.config.chatgpt_client_id
            or initial.redirect_uri != self.config.chatgpt_redirect_uri
            or initial.resource != self.config.resource
            or initial.scopes != self.config.scopes
            or initial.code_challenge_method != "S256"
        ):
            raise OAuthAccessDenied(
                "server_error",
                "oauth_transaction_binding_invalid",
                500,
            )
        try:
            client_state = decrypt_client_state(
                initial.encrypted_client_state,
                self.config.state_encryption_key,
            )
        except ContractValidationError as exc:
            raise OAuthAccessDenied(
                "server_error",
                "oauth_client_state_invalid",
                500,
            ) from exc
        identity_claims = await self.google_client.authenticate_code(
            google_code,
            expected_nonce_hash=initial.google_nonce_hash,
            now=now,
        )
        raw_authorization_code = generate_opaque_value(random_bytes=self.random_bytes)
        with self.repository.transaction() as unit:
            transaction = self.repository.get_transaction_by_state_hash(
                state_hash,
                for_update=True,
            )
            self._validate_pending_transaction(transaction, now=now)
            assert transaction is not None
            if (
                (
                    transaction.transaction_id,
                    transaction.google_state_hash,
                    transaction.encrypted_client_state,
                    transaction.google_nonce_hash,
                    transaction.client_id,
                    transaction.redirect_uri,
                    transaction.resource,
                    transaction.scopes,
                    transaction.code_challenge,
                    transaction.code_challenge_method,
                    transaction.created_at,
                    transaction.expires_at,
                )
                != (
                    initial.transaction_id,
                    initial.google_state_hash,
                    initial.encrypted_client_state,
                    initial.google_nonce_hash,
                    initial.client_id,
                    initial.redirect_uri,
                    initial.resource,
                    initial.scopes,
                    initial.code_challenge,
                    initial.code_challenge_method,
                    initial.created_at,
                    initial.expires_at,
                )
                or transaction.client_id != self.config.chatgpt_client_id
                or transaction.redirect_uri != self.config.chatgpt_redirect_uri
                or transaction.resource != self.config.resource
                or transaction.scopes != self.config.scopes
                or transaction.code_challenge_method != "S256"
            ):
                raise OAuthAccessDenied(
                    "server_error",
                    "oauth_transaction_binding_invalid",
                    500,
                )
            user, external_identity, client_authorization = self._resolve_or_bind_identity(
                identity_claims,
                transaction=transaction,
                now=now,
            )
            self.repository.append_audit_log(
                self._audit_log(
                    actor_user_id=user.user_id,
                    action="google_authentication_succeeded",
                    target_type="external_identity",
                    target_id=external_identity.external_identity_id,
                    session_id=transaction.transaction_id,
                    workspace_id=client_authorization.default_workspace_id,
                    timestamp=now,
                    status="ok",
                    external_identity_id=external_identity.external_identity_id,
                    oauth_client_id=transaction.client_id,
                    reason_code="google_authentication_succeeded",
                    metadata={"event_stage": "google_callback", "provider": "google"},
                )
            )
            authorization_code = OAuthAuthorizationCode(
                code_hash=hash_oauth_value("authorization_code", raw_authorization_code),
                transaction_id=transaction.transaction_id,
                user_id=user.user_id,
                external_identity_id=external_identity.external_identity_id,
                client_id=transaction.client_id,
                redirect_uri=transaction.redirect_uri,
                resource=transaction.resource,
                scopes=transaction.scopes,
                code_challenge=transaction.code_challenge,
                created_at=_iso(now),
                expires_at=_iso(
                    now + timedelta(seconds=self.config.authorization_code_lifetime_seconds)
                ),
            )
            self.repository.insert_authorization_code(authorization_code)
            self.repository.consume_transaction(transaction.transaction_id, consumed_at=_iso(now))
            self.repository.append_audit_log(
                self._audit_log(
                    actor_user_id=user.user_id,
                    action="oauth_authorization_code_issued",
                    target_type="oauth_authorization_code",
                    target_id=transaction.transaction_id,
                    session_id=transaction.transaction_id,
                    workspace_id=client_authorization.default_workspace_id,
                    timestamp=now,
                    status="ok",
                    external_identity_id=external_identity.external_identity_id,
                    oauth_client_id=transaction.client_id,
                    reason_code="authorization_code_issued",
                    metadata={"event_stage": "google_callback", "provider": "google"},
                )
            )
            unit.commit()
        callback_query = urlencode({"code": raw_authorization_code, "state": client_state})
        return {
            "redirect_uri": f"{transaction.redirect_uri}?{callback_query}",
            "user_id": user.user_id,
        }

    def complete_google_denial(
        self,
        *,
        google_state: str,
        now: datetime,
    ) -> dict[str, str]:
        self._require_stateful_oauth()
        _require_aware(now)
        if not google_state:
            raise OAuthAccessDenied("access_denied", "google_callback_incomplete", 400)
        state_hash = hash_oauth_value("google_state", google_state)
        initial = self.repository.get_transaction_by_state_hash(state_hash)
        self._validate_pending_transaction(initial, now=now)
        assert initial is not None
        try:
            client_state = decrypt_client_state(
                initial.encrypted_client_state,
                self.config.state_encryption_key,
            )
        except ContractValidationError as exc:
            raise OAuthAccessDenied(
                "server_error",
                "oauth_client_state_invalid",
                500,
            ) from exc
        with self.repository.transaction() as unit:
            transaction = self.repository.get_transaction_by_state_hash(
                state_hash,
                for_update=True,
            )
            self._validate_pending_transaction(transaction, now=now)
            assert transaction is not None
            if transaction.encrypted_client_state != initial.encrypted_client_state:
                raise OAuthAccessDenied(
                    "server_error",
                    "oauth_transaction_changed",
                    500,
                )
            if (
                transaction.transaction_id != initial.transaction_id
                or transaction.google_state_hash != initial.google_state_hash
                or transaction.client_id != initial.client_id
                or transaction.redirect_uri != initial.redirect_uri
                or transaction.resource != initial.resource
                or transaction.scopes != initial.scopes
                or transaction.client_id != self.config.chatgpt_client_id
                or transaction.redirect_uri != self.config.chatgpt_redirect_uri
                or transaction.resource != self.config.resource
                or transaction.scopes != self.config.scopes
            ):
                raise OAuthAccessDenied(
                    "server_error",
                    "oauth_transaction_binding_invalid",
                    500,
                )
            self.repository.fail_transaction(
                transaction.transaction_id,
                failed_at=_iso(now),
            )
            self.repository.append_audit_log(
                self._audit_log(
                    actor_user_id=None,
                    actor_type="external_unauthenticated",
                    action="google_authentication_failed",
                    target_type="oauth_transaction",
                    target_id=transaction.transaction_id,
                    session_id=transaction.transaction_id,
                    timestamp=now,
                    status="permission_denied",
                    oauth_client_id=transaction.client_id,
                    reason_code="google_authorization_denied",
                    metadata={"event_stage": "google_callback", "provider": "google"},
                )
            )
            unit.commit()
        callback_query = urlencode({"error": "access_denied", "state": client_state})
        return {"redirect_uri": f"{transaction.redirect_uri}?{callback_query}"}

    def exchange_authorization_code(
        self,
        request: Mapping[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        _require_aware(now)
        required = ("grant_type", "code", "client_id", "redirect_uri", "code_verifier", "resource")
        if any(not isinstance(request.get(key), str) or not request.get(key) for key in required):
            raise OAuthAccessDenied("invalid_request", "token_parameter_missing", 400)
        if request["grant_type"] != "authorization_code":
            raise OAuthAccessDenied("invalid_grant", "grant_type_invalid", 400)
        if request["client_id"] != self.config.chatgpt_client_id:
            raise OAuthAccessDenied("invalid_grant", "token_client_invalid", 400)
        if request["redirect_uri"] != self.config.chatgpt_redirect_uri:
            raise OAuthAccessDenied("invalid_grant", "token_redirect_invalid", 400)
        if request["resource"] != self.config.resource:
            raise OAuthAccessDenied("invalid_target", "token_resource_invalid", 400)
        if "client_secret" in request:
            raise OAuthAccessDenied("invalid_request", "public_client_secret_forbidden", 400)
        code_hash = hash_oauth_value("authorization_code", str(request["code"]))
        try:
            verifier_challenge = pkce_s256_challenge(str(request["code_verifier"]))
        except ContractValidationError as exc:
            raise OAuthAccessDenied(
                "invalid_grant",
                "pkce_verifier_invalid",
                400,
            ) from exc
        with self.repository.transaction() as unit:
            code = self.repository.get_authorization_code(code_hash, for_update=True)
            self._validate_authorization_code(
                code, request=request, verifier_challenge=verifier_challenge, now=now
            )
            assert code is not None
            user = self._require_active_user(code.user_id)
            identity = self._require_active_identity(code.external_identity_id)
            client_authorization = self.repository.get_client_authorization(
                code.client_id,
                code.external_identity_id,
            )
            self._validate_client_authorization(
                client_authorization,
                code=code,
                identity=identity,
            )
            assert client_authorization is not None
            membership = self.repository.get_active_workspace_member(
                user.user_id,
                client_authorization.default_workspace_id,
                for_update=True,
            )
            if membership is None:
                raise OAuthAccessDenied("access_denied", "workspace_membership_inactive", 403)
            token_session_id = generate_safe_id("oauthsid", random_bytes=self.random_bytes)
            jti = generate_safe_id("jti", random_bytes=self.random_bytes)
            token_session = OAuthTokenSession(
                token_session_id=token_session_id,
                user_id=user.user_id,
                external_identity_id=identity.external_identity_id,
                oauth_client_authorization_id=(client_authorization.oauth_client_authorization_id),
                client_id=code.client_id,
                current_workspace_id=client_authorization.default_workspace_id,
                resource=code.resource,
                scopes=code.scopes,
                token_jti_hash=hash_oauth_value("token_jti", jti),
                issued_at=_iso(now),
                expires_at=_iso(now + timedelta(seconds=self.config.access_token_lifetime_seconds)),
            )
            access_token = self.token_codec.issue_access_token(
                session=token_session,
                jti=jti,
                now=now,
            )
            self.repository.insert_token_session(token_session)
            self.repository.consume_authorization_code(
                code.code_hash,
                consumed_at=_iso(now),
                user_id=code.user_id,
                external_identity_id=code.external_identity_id,
                client_id=code.client_id,
                redirect_uri=code.redirect_uri,
                resource=code.resource,
            )
            self.repository.append_audit_log(
                self._audit_log(
                    actor_user_id=user.user_id,
                    action="oauth_token_session_issued",
                    target_type="oauth_token_session",
                    target_id=token_session_id,
                    session_id=token_session_id,
                    workspace_id=token_session.current_workspace_id,
                    timestamp=now,
                    status="ok",
                    external_identity_id=identity.external_identity_id,
                    oauth_client_id=code.client_id,
                    oauth_token_session_id=token_session_id,
                    reason_code="token_session_issued",
                    metadata={
                        "event_stage": "token_exchange",
                        "scopes": list(code.scopes),
                        "membership_role": membership.role,
                    },
                )
            )
            unit.commit()
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": self.config.access_token_lifetime_seconds,
            "scope": " ".join(code.scopes),
            "resource": code.resource,
        }

    def authenticate_access_token(
        self,
        raw_token: str,
        *,
        required_scope: str,
        resource: str,
        now: datetime,
    ) -> OAuthPrincipal:
        _require_aware(now)
        claims = self.token_codec.verify_access_token(
            raw_token,
            resource=resource,
            required_scope=required_scope,
            now=now,
        )
        token_session = self.repository.get_token_session(str(claims["sid"]))
        if token_session is None:
            raise OAuthAccessDenied("invalid_token", "token_session_missing", 401)
        self._validate_live_token_session(token_session, claims=claims, resource=resource, now=now)
        identity = self._require_active_identity(token_session.external_identity_id)
        user = self._require_active_user(token_session.user_id)
        authorization = self.repository.get_client_authorization_by_id(
            token_session.oauth_client_authorization_id
        )
        self._validate_client_authorization(
            authorization,
            session=token_session,
            identity=identity,
        )
        return OAuthPrincipal(
            user_id=user.user_id,
            external_identity_id=identity.external_identity_id,
            oauth_client_id=token_session.client_id,
            token_session_id=token_session.token_session_id,
            scopes=token_session.scopes,
            resource=token_session.resource,
        )

    def resolve_actor_context(
        self,
        principal: OAuthPrincipal,
        *,
        now: datetime,
    ) -> ActorContext:
        _require_aware(now)
        principal.to_dict()
        session = self.repository.get_token_session(principal.token_session_id)
        if session is None:
            raise OAuthAccessDenied("invalid_token", "token_session_missing", 401)
        self._validate_principal_session(principal, session=session, now=now)
        user = self._require_active_user(principal.user_id)
        identity = self._require_active_identity(principal.external_identity_id)
        authorization = self.repository.get_client_authorization_by_id(
            session.oauth_client_authorization_id
        )
        self._validate_client_authorization(
            authorization,
            session=session,
            identity=identity,
        )
        current_membership = self.repository.get_active_workspace_member(
            user.user_id,
            session.current_workspace_id,
        )
        if current_membership is None:
            raise OAuthAccessDenied("access_denied", "workspace_membership_inactive", 403)
        memberships = self.repository.list_active_workspace_members(user.user_id)
        grants = self.repository.list_active_grants(user.user_id, now=_iso(now))
        return ActorContext(
            user=user,
            session_identity=SessionIdentity(
                session_id=session.token_session_id,
                selected_user_id=user.user_id,
                selected_at=session.issued_at,
                selection_method="google_oidc_oauth",
            ),
            workspace_memberships=memberships,
            active_grants=grants,
            pending_access_requests=[],
            current_workspace_id=current_membership.workspace_id,
            current_workspace_role=current_membership.role,
            external_identity_id=identity.external_identity_id,
            oauth_client_id=principal.oauth_client_id,
            oauth_token_session_id=session.token_session_id,
            auth_mode="google_oidc_oauth",
            production_authentication=True,
            authentication_note="Google OIDC authenticated FormOwl OAuth session",
        )

    def record_mcp_authorization_decision(
        self,
        *,
        principal: OAuthPrincipal | None,
        request_id: str,
        tool_call_id: str,
        tool_name: str,
        workspace_id: str | None,
        allowed: bool,
        reason_code: str,
        now: datetime,
    ) -> AuditLog:
        self._require_stateful_oauth()
        _require_aware(now)
        for name, value in (
            ("request_id", request_id),
            ("tool_call_id", tool_call_id),
            ("tool_name", tool_name),
            ("reason_code", reason_code),
        ):
            _safe_id(value, name)
        if workspace_id is not None:
            _safe_id(workspace_id, "workspace_id")
        audit = self._audit_log(
            actor_user_id=principal.user_id if principal else None,
            actor_type="user" if principal else "external_unauthenticated",
            action="mcp_authorization_allowed" if allowed else "mcp_authorization_denied",
            target_type="mcp_tool",
            target_id=tool_name,
            session_id=principal.token_session_id if principal else request_id,
            workspace_id=workspace_id,
            timestamp=now,
            status="ok" if allowed else "permission_denied",
            external_identity_id=principal.external_identity_id if principal else None,
            oauth_client_id=principal.oauth_client_id if principal else None,
            oauth_token_session_id=principal.token_session_id if principal else None,
            request_id=request_id,
            tool_call_id=tool_call_id,
            reason_code=reason_code,
            metadata={
                "event_stage": "mcp_authorization",
                "workspace_decision": "allowed" if allowed else "denied",
            },
        )
        with self.repository.transaction() as unit:
            self.repository.append_audit_log(audit)
            unit.commit()
        return audit

    def record_oauth_denial(
        self,
        *,
        event: str,
        reason_code: str,
        now: datetime,
        oauth_client_id: str | None = None,
    ) -> AuditLog:
        self._require_stateful_oauth()
        _require_aware(now)
        allowed_events = {
            "authorization": "oauth_authorization_rejected",
            "google_callback": "google_authentication_failed",
            "token_exchange": "oauth_token_exchange_rejected",
        }
        action = allowed_events.get(event)
        if action is None:
            raise ValueError("unsupported OAuth denial event")
        _safe_id(reason_code, "reason_code")
        denial_id = generate_safe_id("oauthdeny", random_bytes=self.random_bytes)
        audit = self._audit_log(
            actor_user_id=None,
            actor_type="external_unauthenticated",
            action=action,
            target_type="oauth_request",
            target_id=denial_id,
            session_id=denial_id,
            timestamp=now,
            status="permission_denied",
            oauth_client_id=oauth_client_id,
            reason_code=reason_code,
            metadata={"event_stage": event},
        )
        with self.repository.transaction() as unit:
            self.repository.append_audit_log(audit)
            unit.commit()
        return audit

    def record_mcp_http_authentication_denial(
        self,
        *,
        raw_token: str | None,
        request_id: str,
        reason_code: str,
        required_scope: str,
        resource: str,
        now: datetime,
    ) -> AuditLog:
        self._require_stateful_oauth()
        _require_aware(now)
        _safe_id(request_id, "request_id")
        _safe_id(reason_code, "reason_code")
        if required_scope not in self.config.scopes or resource != self.config.resource:
            raise ValueError("MCP denial audit target is invalid")
        token_session = self._trusted_http_denial_token_session(
            raw_token=raw_token,
            reason_code=reason_code,
            required_scope=required_scope,
            resource=resource,
            now=now,
        )
        audit = self._audit_log(
            actor_user_id=token_session.user_id if token_session else None,
            action="mcp_http_authentication_denied",
            target_type="mcp_resource",
            target_id="mcp",
            session_id=token_session.token_session_id if token_session else request_id,
            workspace_id=token_session.current_workspace_id if token_session else None,
            timestamp=now,
            status="permission_denied",
            external_identity_id=(token_session.external_identity_id if token_session else None),
            oauth_client_id=token_session.client_id if token_session else None,
            oauth_token_session_id=(token_session.token_session_id if token_session else None),
            request_id=request_id,
            reason_code=reason_code,
            metadata={
                "event_stage": "mcp_http_authentication",
                "lineage_source": (
                    "verified_token_session" if token_session else "untrusted_bearer"
                ),
            },
        )
        with self.repository.transaction() as unit:
            self.repository.append_audit_log(audit)
            unit.commit()
        return audit

    def _trusted_http_denial_token_session(
        self,
        *,
        raw_token: str | None,
        reason_code: str,
        required_scope: str,
        resource: str,
        now: datetime,
    ) -> OAuthTokenSession | None:
        if raw_token is None or reason_code not in _TRUSTED_HTTP_DENIAL_REASONS:
            return None
        try:
            if reason_code == "token_expired":
                claims = self.token_codec.verify_expired_access_token_for_audit(
                    raw_token,
                    resource=resource,
                    required_scope=required_scope,
                    now=now,
                )
            else:
                claims = self.token_codec.verify_access_token(
                    raw_token,
                    resource=resource,
                    required_scope=required_scope,
                    now=now,
                )
            token_session = self.repository.get_token_session(str(claims["sid"]))
            if token_session is None:
                return None
            self._validate_token_session_binding(
                token_session,
                claims=claims,
                resource=resource,
            )
            if not self._http_denial_reason_matches_state(
                reason_code,
                token_session=token_session,
                now=now,
            ):
                return None
        except OAuthAccessDenied:
            return None
        return token_session

    def _http_denial_reason_matches_state(
        self,
        reason_code: str,
        *,
        token_session: OAuthTokenSession,
        now: datetime,
    ) -> bool:
        if reason_code == "token_expired":
            return True
        if reason_code == "token_session_revoked":
            return token_session.revoked_at is not None
        if reason_code == "token_session_expired":
            return token_session.revoked_at is None and _parse_iso(token_session.expires_at) <= now
        if token_session.revoked_at is not None or _parse_iso(token_session.expires_at) <= now:
            return False
        identity = self.repository.get_external_identity(token_session.external_identity_id)
        if reason_code == "external_identity_disabled":
            return identity is None or identity.status != "active"
        if identity is None or identity.status != "active":
            return False
        user = self.repository.get_user(token_session.user_id)
        if reason_code == "formowl_user_disabled":
            return user is None or user.status != "active"
        if user is None or user.status != "active":
            return False
        if reason_code == "client_authorization_revoked":
            authorization = self.repository.get_client_authorization_by_id(
                token_session.oauth_client_authorization_id
            )
            return authorization is None or authorization.revoked_at is not None
        return False

    def revoke_token_session(
        self,
        token_session_id: str,
        *,
        principal: OAuthPrincipal,
        actor_context: ActorContext,
        reason_code: str,
        now: datetime,
    ) -> None:
        self._require_stateful_oauth()
        _require_aware(now)
        _safe_id(token_session_id, "token_session_id")
        _safe_id(reason_code, "reason_code")
        principal.to_dict()
        with self.repository.transaction() as unit:
            fresh_actor_context = self.resolve_actor_context(principal, now=now)
            if type(actor_context) is not ActorContext or actor_context != fresh_actor_context:
                raise OAuthAccessDenied(
                    "access_denied",
                    "token_revocation_principal_invalid",
                    403,
                )
            session = self.repository.get_token_session(token_session_id)
            if session is None:
                raise OAuthAccessDenied("invalid_token", "token_session_missing", 401)
            if session.revoked_at is not None:
                raise OAuthAccessDenied("invalid_token", "token_session_revoked", 401)
            if fresh_actor_context.current_workspace_id != session.current_workspace_id or (
                principal.user_id != session.user_id
                and fresh_actor_context.current_workspace_role != "owner"
            ):
                raise OAuthAccessDenied(
                    "access_denied",
                    "token_revocation_forbidden",
                    403,
                )
            revoked_session = self.repository.revoke_token_session(
                token_session_id,
                revoked_at=_iso(now),
                reason_code=reason_code,
            )
            if revoked_session is None:
                raise OAuthAccessDenied("invalid_token", "token_session_revoked", 401)
            self.repository.append_audit_log(
                self._audit_log(
                    actor_user_id=principal.user_id,
                    action="oauth_token_session_revoked",
                    target_type="oauth_token_session",
                    target_id=token_session_id,
                    session_id=token_session_id,
                    workspace_id=revoked_session.current_workspace_id,
                    timestamp=now,
                    status="ok",
                    external_identity_id=revoked_session.external_identity_id,
                    oauth_client_id=revoked_session.client_id,
                    oauth_token_session_id=token_session_id,
                    reason_code=reason_code,
                    metadata={
                        "event_stage": "revocation",
                        "token_session_status": "revoked",
                    },
                )
            )
            unit.commit()

    def revoke_token_session_as_operator(
        self,
        token_session_id: str,
        *,
        operator_service_id: str,
        reason_code: str,
        now: datetime,
    ) -> None:
        self._require_stateful_oauth()
        _require_aware(now)
        _safe_id(token_session_id, "token_session_id")
        _safe_id(operator_service_id, "operator_service_id")
        _safe_id(reason_code, "reason_code")
        try:
            operator_authorized = (
                self.owner_bootstrap_operator_authorizer is not None
                and self.owner_bootstrap_operator_authorizer(operator_service_id) is True
            )
        except Exception as exc:
            raise OAuthAccessDenied(
                "access_denied",
                "token_revocation_operator_unauthorized",
                403,
            ) from exc
        if not operator_authorized:
            raise OAuthAccessDenied(
                "access_denied",
                "token_revocation_operator_unauthorized",
                403,
            )
        with self.repository.transaction() as unit:
            session = self.repository.get_token_session(token_session_id)
            if session is None:
                raise OAuthAccessDenied("invalid_token", "token_session_missing", 401)
            if session.revoked_at is not None:
                raise OAuthAccessDenied("invalid_token", "token_session_revoked", 401)
            revoked_session = self.repository.revoke_token_session(
                token_session_id,
                revoked_at=_iso(now),
                reason_code=reason_code,
            )
            if revoked_session is None:
                raise OAuthAccessDenied("invalid_token", "token_session_revoked", 401)
            self.repository.append_audit_log(
                AuditLog(
                    audit_log_id=generate_safe_id("audit", random_bytes=self.random_bytes),
                    actor_user_id=None,
                    actor_type="service",
                    actor_service_id=operator_service_id,
                    action="oauth_token_session_revoked",
                    target_type="oauth_token_session",
                    target_id=token_session_id,
                    session_id=token_session_id,
                    workspace_id=revoked_session.current_workspace_id,
                    status="ok",
                    external_identity_id=revoked_session.external_identity_id,
                    oauth_client_id=revoked_session.client_id,
                    oauth_token_session_id=token_session_id,
                    reason_code=reason_code,
                    timestamp=_iso(now),
                    metadata={
                        "event_stage": "revocation",
                        "token_session_status": "revoked",
                    },
                )
            )
            unit.commit()

    def whoami_payload(self, actor_context: ActorContext) -> dict[str, Any]:
        if (
            actor_context.auth_mode != "google_oidc_oauth"
            or actor_context.current_workspace_id is None
            or actor_context.current_workspace_role is None
        ):
            raise OAuthAccessDenied("access_denied", "workspace_membership_inactive", 403)
        return {
            "user_id": actor_context.user.user_id,
            "display_name": actor_context.user.display_name,
            "current_workspace": {
                "workspace_id": actor_context.current_workspace_id,
                "role": actor_context.current_workspace_role,
            },
            "auth_mode": "google_oidc_oauth",
        }

    def _resolve_or_bind_identity(
        self,
        claims: GoogleIdentity,
        *,
        transaction: OAuthTransaction,
        now: datetime,
    ) -> tuple[User, ExternalIdentity, OAuthClientAuthorization]:
        identity = self.repository.find_external_identity(claims.issuer, claims.subject)
        if identity is not None:
            if identity.status != "active":
                raise OAuthAccessDenied("access_denied", "external_identity_disabled", 403)
            user = self._require_active_user(identity.user_id)
            authorization = self.repository.get_client_authorization(
                transaction.client_id,
                identity.external_identity_id,
            )
            if authorization is None or authorization.revoked_at is not None:
                raise OAuthAccessDenied("access_denied", "client_authorization_denied", 403)
            membership = self.repository.get_active_workspace_member(
                user.user_id,
                authorization.default_workspace_id,
            )
            if membership is None:
                raise OAuthAccessDenied("access_denied", "workspace_membership_inactive", 403)
            self.repository.update_external_identity_profile(
                identity.external_identity_id,
                email=claims.email,
                authenticated_at=_iso(now),
            )
            self.repository.update_user_profile(
                user.user_id,
                display_name=claims.display_name,
                email=claims.email,
            )
            identity = ExternalIdentity(
                **{
                    **identity.to_dict(),
                    "email": claims.email,
                    "last_authenticated_at": _iso(now),
                }
            )
            user = User(
                user_id=user.user_id,
                display_name=claims.display_name,
                email=claims.email,
                status=user.status,
                created_at=user.created_at,
            )
            self.repository.append_audit_log(
                self._audit_log(
                    actor_user_id=user.user_id,
                    action="oauth_external_identity_resolved",
                    target_type="external_identity",
                    target_id=identity.external_identity_id,
                    session_id=transaction.transaction_id,
                    workspace_id=authorization.default_workspace_id,
                    timestamp=now,
                    status="ok",
                    external_identity_id=identity.external_identity_id,
                    oauth_client_id=transaction.client_id,
                    reason_code="external_identity_resolved",
                    metadata={
                        "event_stage": "identity_mapping",
                        "identity_status": "resolved",
                    },
                )
            )
            return user, identity, authorization

        invitations = self.repository.find_active_invitations(
            claims.email,
            now=_iso(now),
            for_update=True,
        )
        if len(invitations) != 1:
            reason = "invitation_missing" if not invitations else "invitation_ambiguous"
            raise OAuthAccessDenied("access_denied", reason, 403)
        invitation = invitations[0]
        owner_bootstrap = self.repository.get_owner_bootstrap_by_invitation(
            invitation.invitation_id,
            for_update=True,
        )
        if owner_bootstrap is not None and (
            owner_bootstrap.status != "pending"
            or owner_bootstrap.workspace_id != invitation.workspace_id
            or owner_bootstrap.normalized_email != invitation.normalized_email
            or invitation.role != "owner"
            or invitation.intended_user_id is not None
        ):
            raise OAuthAccessDenied(
                "server_error",
                "owner_bootstrap_state_invalid",
                500,
            )
        if invitation.intended_user_id is not None:
            user = self._require_active_user(invitation.intended_user_id)
            self.repository.update_user_profile(
                user.user_id,
                display_name=claims.display_name,
                email=claims.email,
            )
            user = User(
                user_id=user.user_id,
                display_name=claims.display_name,
                email=claims.email,
                status=user.status,
                created_at=user.created_at,
            )
        else:
            user = User(
                user_id=generate_safe_id("user", random_bytes=self.random_bytes),
                display_name=claims.display_name,
                email=claims.email,
                status="active",
                created_at=_iso(now),
            )
            self.repository.insert_user(user)
        identity = ExternalIdentity(
            external_identity_id=generate_safe_id("extid", random_bytes=self.random_bytes),
            provider="google",
            issuer=claims.issuer,
            subject=claims.subject,
            user_id=user.user_id,
            email=claims.email,
            email_verified=True,
            status="active",
            created_at=_iso(now),
            last_authenticated_at=_iso(now),
        )
        self.repository.insert_external_identity(identity)
        membership = self.repository.get_active_workspace_member(
            user.user_id,
            invitation.workspace_id,
        )
        if membership is None:
            self.repository.insert_workspace_member(
                WorkspaceMember(
                    workspace_id=invitation.workspace_id,
                    user_id=user.user_id,
                    role=invitation.role,
                ),
                created_at=_iso(now),
            )
        elif membership.role != invitation.role:
            raise OAuthAccessDenied("access_denied", "invitation_membership_conflict", 403)
        authorization = OAuthClientAuthorization(
            oauth_client_authorization_id=generate_safe_id(
                "clientauth",
                random_bytes=self.random_bytes,
            ),
            client_id=transaction.client_id,
            external_identity_id=identity.external_identity_id,
            user_id=user.user_id,
            granted_scopes=transaction.scopes,
            default_workspace_id=invitation.workspace_id,
            created_at=_iso(now),
        )
        self.repository.insert_client_authorization(authorization)
        self.repository.mark_invitation_accepted(
            invitation.invitation_id,
            external_identity_id=identity.external_identity_id,
            accepted_at=_iso(now),
        )
        if owner_bootstrap is not None:
            self.repository.complete_owner_bootstrap(
                invitation.invitation_id,
                completed_at=_iso(now),
            )
        self.repository.append_audit_log(
            self._audit_log(
                actor_user_id=user.user_id,
                action="oauth_external_identity_created",
                target_type="external_identity",
                target_id=identity.external_identity_id,
                session_id=transaction.transaction_id,
                workspace_id=invitation.workspace_id,
                timestamp=now,
                status="ok",
                external_identity_id=identity.external_identity_id,
                oauth_client_id=transaction.client_id,
                reason_code="external_identity_created",
                metadata={
                    "event_stage": "identity_mapping",
                    "identity_status": "created",
                },
            )
        )
        self.repository.append_audit_log(
            self._audit_log(
                actor_user_id=user.user_id,
                action="oauth_invitation_accepted",
                target_type="oauth_invitation",
                target_id=invitation.invitation_id,
                session_id=transaction.transaction_id,
                workspace_id=invitation.workspace_id,
                timestamp=now,
                status="ok",
                external_identity_id=identity.external_identity_id,
                oauth_client_id=transaction.client_id,
                reason_code="invitation_accepted",
                metadata={
                    "event_stage": "first_login",
                    "provider": "google",
                    "membership_role": invitation.role,
                },
            )
        )
        return user, identity, authorization

    def _validate_pending_transaction(
        self,
        transaction: OAuthTransaction | None,
        *,
        now: datetime,
    ) -> None:
        if transaction is None:
            raise OAuthAccessDenied("access_denied", "oauth_state_invalid", 400)
        if transaction.status != "pending" or transaction.consumed_at is not None:
            raise OAuthAccessDenied("access_denied", "oauth_state_replayed", 400)
        if _parse_iso(transaction.expires_at) <= now:
            raise OAuthAccessDenied("access_denied", "oauth_transaction_expired", 400)

    def _validate_authorization_code(
        self,
        code: OAuthAuthorizationCode | None,
        *,
        request: Mapping[str, Any],
        verifier_challenge: str,
        now: datetime,
    ) -> None:
        if code is None:
            raise OAuthAccessDenied("invalid_grant", "authorization_code_invalid", 400)
        if code.consumed_at is not None:
            raise OAuthAccessDenied("invalid_grant", "authorization_code_replayed", 400)
        if _parse_iso(code.expires_at) <= now:
            raise OAuthAccessDenied("invalid_grant", "authorization_code_expired", 400)
        if code.client_id != request["client_id"]:
            raise OAuthAccessDenied("invalid_grant", "authorization_code_client_mismatch", 400)
        if code.redirect_uri != request["redirect_uri"]:
            raise OAuthAccessDenied("invalid_grant", "authorization_code_redirect_mismatch", 400)
        if code.resource != request["resource"]:
            raise OAuthAccessDenied("invalid_target", "authorization_code_resource_mismatch", 400)
        if code.code_challenge != verifier_challenge:
            raise OAuthAccessDenied("invalid_grant", "pkce_verifier_mismatch", 400)
        requested_scope = request.get("scope")
        if requested_scope is not None and requested_scope != " ".join(code.scopes):
            raise OAuthAccessDenied("invalid_scope", "authorization_code_scope_mismatch", 400)

    def _validate_client_authorization(
        self,
        authorization: OAuthClientAuthorization | None,
        *,
        code: OAuthAuthorizationCode | None = None,
        session: OAuthTokenSession | None = None,
        identity: ExternalIdentity,
    ) -> None:
        if (code is None) == (session is None):
            raise ValueError("exactly one OAuth authorization binding target is required")
        if session is not None:
            if authorization is None or authorization.revoked_at is not None:
                raise OAuthAccessDenied(
                    "invalid_token",
                    "client_authorization_revoked",
                    401,
                )
            if (
                authorization.oauth_client_authorization_id != session.oauth_client_authorization_id
                or authorization.client_id != session.client_id
                or authorization.user_id != session.user_id
                or authorization.external_identity_id != session.external_identity_id
                or tuple(authorization.granted_scopes) != tuple(session.scopes)
                or authorization.default_workspace_id != session.current_workspace_id
                or identity.external_identity_id != session.external_identity_id
                or identity.user_id != session.user_id
                or identity.provider != "google"
                or identity.issuer != GOOGLE_ISSUER
            ):
                raise OAuthAccessDenied(
                    "invalid_token",
                    "client_authorization_binding_invalid",
                    401,
                )
            return
        assert code is not None
        if authorization is None or authorization.revoked_at is not None:
            raise OAuthAccessDenied("access_denied", "client_authorization_denied", 403)
        if authorization.client_id != code.client_id:
            raise OAuthAccessDenied(
                "invalid_grant",
                "authorization_client_mismatch",
                400,
            )
        if authorization.user_id != code.user_id:
            raise OAuthAccessDenied("invalid_grant", "authorization_user_mismatch", 400)
        if (
            authorization.external_identity_id != code.external_identity_id
            or identity.external_identity_id != code.external_identity_id
            or identity.user_id != code.user_id
            or identity.provider != "google"
            or identity.issuer != GOOGLE_ISSUER
        ):
            raise OAuthAccessDenied(
                "invalid_grant",
                "authorization_identity_mismatch",
                400,
            )
        if tuple(authorization.granted_scopes) != tuple(code.scopes):
            raise OAuthAccessDenied("invalid_scope", "authorization_scope_mismatch", 400)

    def _validate_live_token_session(
        self,
        session: OAuthTokenSession,
        *,
        claims: Mapping[str, Any],
        resource: str,
        now: datetime,
    ) -> None:
        self._validate_token_session_binding(session, claims=claims, resource=resource)
        if session.revoked_at is not None:
            raise OAuthAccessDenied("invalid_token", "token_session_revoked", 401)
        if _parse_iso(session.expires_at) <= now:
            raise OAuthAccessDenied("invalid_token", "token_session_expired", 401)

    def _validate_token_session_binding(
        self,
        session: OAuthTokenSession,
        *,
        claims: Mapping[str, Any],
        resource: str,
    ) -> None:
        if session.resource != resource or session.resource != claims.get("aud"):
            raise OAuthAccessDenied("invalid_target", "token_session_resource_mismatch", 401)
        if (
            session.token_session_id != claims.get("sid")
            or session.user_id != claims.get("sub")
            or session.client_id != claims.get("client_id")
        ):
            raise OAuthAccessDenied("invalid_token", "token_session_binding_invalid", 401)
        if not hash_oauth_value("token_jti", str(claims.get("jti"))) == session.token_jti_hash:
            raise OAuthAccessDenied("invalid_token", "token_jti_mismatch", 401)
        claim_scopes = tuple(str(claims.get("scope", "")).split())
        if claim_scopes != session.scopes:
            raise OAuthAccessDenied("invalid_token", "token_scope_binding_invalid", 401)

    def _validate_principal_session(
        self,
        principal: OAuthPrincipal,
        *,
        session: OAuthTokenSession,
        now: datetime,
    ) -> None:
        if session.revoked_at is not None or _parse_iso(session.expires_at) <= now:
            raise OAuthAccessDenied("invalid_token", "token_session_inactive", 401)
        if (
            session.token_session_id != principal.token_session_id
            or session.user_id != principal.user_id
            or session.external_identity_id != principal.external_identity_id
            or session.client_id != principal.oauth_client_id
            or session.resource != principal.resource
            or session.scopes != principal.scopes
        ):
            raise OAuthAccessDenied("invalid_token", "principal_session_mismatch", 401)

    def _require_active_user(self, user_id: str) -> User:
        user = self.repository.get_user(user_id)
        if user is None or user.status != "active":
            raise OAuthAccessDenied("access_denied", "formowl_user_disabled", 403)
        return user

    def _require_active_identity(self, external_identity_id: str) -> ExternalIdentity:
        identity = self.repository.get_external_identity(external_identity_id)
        if identity is None or identity.status != "active":
            raise OAuthAccessDenied("access_denied", "external_identity_disabled", 403)
        return identity

    def _audit_log(
        self,
        *,
        actor_user_id: str | None,
        action: str,
        target_type: str,
        target_id: str,
        session_id: str,
        timestamp: datetime,
        status: str,
        reason_code: str,
        actor_type: str | None = None,
        actor_service_id: str | None = None,
        workspace_id: str | None = None,
        external_identity_id: str | None = None,
        oauth_client_id: str | None = None,
        oauth_token_session_id: str | None = None,
        request_id: str | None = None,
        tool_call_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditLog:
        return AuditLog(
            audit_log_id=generate_safe_id("audit", random_bytes=self.random_bytes),
            actor_user_id=actor_user_id,
            actor_type=actor_type
            or (
                "user"
                if actor_user_id is not None
                else "service"
                if actor_service_id is not None
                else "external_unauthenticated"
            ),
            actor_service_id=actor_service_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            session_id=session_id,
            timestamp=_iso(timestamp),
            workspace_id=workspace_id,
            status=status,
            external_identity_id=external_identity_id,
            oauth_client_id=oauth_client_id,
            oauth_token_session_id=oauth_token_session_id,
            request_id=request_id,
            tool_call_id=tool_call_id,
            reason_code=reason_code,
            metadata=sanitize_oauth_audit_metadata(metadata),
        )


def _safe_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_CODE.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe identifier")


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")


def _iso(value: datetime) -> str:
    _require_aware(value)
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stored OAuth timestamp must include a timezone")
    return parsed


__all__ = ["FormOwlOAuthBridge"]
