"""Identity, access, and audit helpers for Phase 0 FormOwl workflows."""

from .audit import (
    FileAuditLogStore,
    record_actor_selection,
    record_asset_registration,
    record_asset_reference_upload,
    record_chatgpt_session_capture,
    record_evidence_fetch,
    record_ingestion_job_creation,
    record_permission_denied,
    record_upload_session_file_received,
    record_upload_session_creation,
    sanitize_oauth_audit_metadata,
    write_audit_log,
    write_oauth_audit_event,
)
from .config import (
    CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
    OAuthBridgeConfig,
    assert_connected_auth_mode,
)
from .google_oidc import GoogleIdentity, GoogleOidcClient
from .http import create_oauth_asgi_app, oauth_routes
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
from .postgres import OAuthRepository, PostgreSQLOAuthRepository
from .provider import ActorContext, ManualTrustedInternalAuthProvider
from .service import FormOwlOAuthBridge
from .tokens import FormOwlSigningKey, FormOwlSigningKeySet, FormOwlTokenCodec

__all__ = [
    "ActorContext",
    "CHATGPT_DISCOVERY_ONLY_REDIRECT_URI",
    "FileAuditLogStore",
    "ExternalIdentity",
    "FormOwlOAuthBridge",
    "FormOwlSigningKey",
    "FormOwlSigningKeySet",
    "FormOwlTokenCodec",
    "GoogleIdentity",
    "GoogleOidcClient",
    "ManualTrustedInternalAuthProvider",
    "OAuthAccessDenied",
    "OAuthAuthorizationCode",
    "OAuthBridgeConfig",
    "OAuthClientAuthorization",
    "OAuthInvitation",
    "OAuthOwnerBootstrap",
    "OAuthPrincipal",
    "OAuthRepository",
    "OAuthTokenSession",
    "OAuthTransaction",
    "PostgreSQLOAuthRepository",
    "assert_connected_auth_mode",
    "create_oauth_asgi_app",
    "oauth_routes",
    "record_actor_selection",
    "record_asset_registration",
    "record_asset_reference_upload",
    "record_chatgpt_session_capture",
    "record_evidence_fetch",
    "record_ingestion_job_creation",
    "record_permission_denied",
    "record_upload_session_file_received",
    "record_upload_session_creation",
    "sanitize_oauth_audit_metadata",
    "write_audit_log",
    "write_oauth_audit_event",
]
