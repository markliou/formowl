"""PostgreSQL persistence for FormOwl OAuth identities and sessions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from formowl_contract import AuditLog, Grant, User, WorkspaceMember
from formowl_graph.storage import (
    PostgreSQLMigrationResult,
    PostgreSQLMigrationRunner,
    PostgreSQLUnitOfWork,
    SQLStatement,
    migration_files,
)

from .models import (
    ExternalIdentity,
    OAuthAuthorizationCode,
    OAuthAccessDenied,
    OAuthClientAuthorization,
    OAuthInvitation,
    OAuthOwnerBootstrap,
    OAuthTokenSession,
    OAuthTransaction,
)


class OAuthUnitOfWork(Protocol):
    def __enter__(self) -> "OAuthUnitOfWork": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool: ...

    def commit(self) -> None: ...


class OAuthRepository(Protocol):
    def transaction(self) -> OAuthUnitOfWork: ...

    def insert_user(self, user: User) -> None: ...

    def get_user(self, user_id: str) -> User | None: ...

    def find_users_by_email(self, normalized_email: str) -> list[User]: ...

    def list_workspace_users(self, workspace_id: str) -> list[tuple[User, WorkspaceMember]]: ...

    def update_user_profile(self, user_id: str, *, display_name: str, email: str) -> None: ...

    def insert_workspace_member(self, member: WorkspaceMember, *, created_at: str) -> None: ...

    def get_active_workspace_member(
        self, user_id: str, workspace_id: str, *, for_update: bool = False
    ) -> WorkspaceMember | None: ...

    def get_removed_workspace_member(
        self, user_id: str, workspace_id: str, *, for_update: bool = False
    ) -> WorkspaceMember | None: ...

    def remove_workspace_member(
        self, user_id: str, workspace_id: str, *, removed_at: str
    ) -> None: ...

    def restore_workspace_member(self, user_id: str, workspace_id: str) -> None: ...

    def list_active_workspace_members(self, user_id: str) -> list[WorkspaceMember]: ...

    def list_active_workspace_members_in_workspace(
        self, workspace_id: str, *, for_update: bool = False
    ) -> list[WorkspaceMember]: ...

    def revoke_active_token_sessions_for_membership(
        self,
        user_id: str,
        workspace_id: str,
        *,
        revoked_at: str,
        reason_code: str,
    ) -> None: ...

    def count_active_workspace_members(self, workspace_id: str) -> int: ...

    def list_active_grants(self, user_id: str, *, now: str) -> list[Grant]: ...

    def insert_external_identity(self, identity: ExternalIdentity) -> None: ...

    def find_external_identity(self, issuer: str, subject: str) -> ExternalIdentity | None: ...

    def get_external_identity(self, external_identity_id: str) -> ExternalIdentity | None: ...

    def update_external_identity_profile(
        self, external_identity_id: str, *, email: str, authenticated_at: str
    ) -> None: ...

    def insert_invitation(self, invitation: OAuthInvitation) -> None: ...

    def get_invitation(self, invitation_id: str) -> OAuthInvitation | None: ...

    def find_pending_owner_invitations(
        self, workspace_id: str, *, now: str, for_update: bool = False
    ) -> list[OAuthInvitation]: ...

    def find_active_invitations(
        self, normalized_email: str, *, now: str, for_update: bool = False
    ) -> list[OAuthInvitation]: ...

    def mark_invitation_accepted(
        self,
        invitation_id: str,
        *,
        external_identity_id: str,
        accepted_at: str,
    ) -> None: ...

    def upsert_owner_bootstrap(self, bootstrap: OAuthOwnerBootstrap) -> bool: ...

    def get_owner_bootstrap(
        self, workspace_id: str, *, for_update: bool = False
    ) -> OAuthOwnerBootstrap | None: ...

    def get_owner_bootstrap_by_invitation(
        self, invitation_id: str, *, for_update: bool = False
    ) -> OAuthOwnerBootstrap | None: ...

    def complete_owner_bootstrap(self, invitation_id: str, *, completed_at: str) -> None: ...

    def insert_client_authorization(self, authorization: OAuthClientAuthorization) -> None: ...

    def get_client_authorization(
        self, client_id: str, external_identity_id: str
    ) -> OAuthClientAuthorization | None: ...

    def get_client_authorization_by_id(
        self, oauth_client_authorization_id: str
    ) -> OAuthClientAuthorization | None: ...

    def insert_transaction(self, transaction: OAuthTransaction) -> None: ...

    def get_transaction_by_state_hash(
        self, google_state_hash: str, *, for_update: bool = False
    ) -> OAuthTransaction | None: ...

    def consume_transaction(self, transaction_id: str, *, consumed_at: str) -> None: ...

    def fail_transaction(self, transaction_id: str, *, failed_at: str) -> None: ...

    def insert_authorization_code(self, code: OAuthAuthorizationCode) -> None: ...

    def get_authorization_code(
        self, code_hash: str, *, for_update: bool = False
    ) -> OAuthAuthorizationCode | None: ...

    def consume_authorization_code(
        self,
        code_hash: str,
        *,
        consumed_at: str,
        user_id: str,
        external_identity_id: str,
        client_id: str,
        redirect_uri: str,
        resource: str,
    ) -> None: ...

    def insert_token_session(self, session: OAuthTokenSession) -> None: ...

    def get_token_session(self, token_session_id: str) -> OAuthTokenSession | None: ...

    def list_token_sessions(self, user_id: str, workspace_id: str) -> list[OAuthTokenSession]: ...

    def revoke_token_session(
        self, token_session_id: str, *, revoked_at: str, reason_code: str
    ) -> None: ...

    def list_issue20_live_audit_rows(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        actions: tuple[str, ...],
        row_limit: int,
    ) -> list[dict[str, Any]]: ...

    def append_audit_log(self, audit_log: AuditLog) -> None: ...


class PsycopgOAuthConnection:
    """Concrete adapter for the repository's shared PostgreSQL protocol."""

    def __init__(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        self.connection = connection

    def execute(self, statement: SQLStatement) -> None:
        parameters = statement.parameters if "%(" in statement.sql else None
        if parameters is not None:
            parameters = {
                key: (
                    Jsonb(value)
                    if isinstance(value, dict) and f"%({key})s::jsonb" in statement.sql
                    else value
                )
                for key, value in parameters.items()
            }
        self.connection.execute(statement.sql, parameters)

    def query_one(self, statement: SQLStatement) -> dict[str, Any] | None:
        parameters = statement.parameters if "%(" in statement.sql else None
        row = self.connection.execute(statement.sql, parameters).fetchone()
        return dict(row) if row is not None else None

    def query_all(self, statement: SQLStatement) -> list[dict[str, Any]]:
        parameters = statement.parameters if "%(" in statement.sql else None
        return [dict(row) for row in self.connection.execute(statement.sql, parameters).fetchall()]

    def begin(self) -> None:
        self.connection.execute("BEGIN")

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


class PostgreSQLOAuthRepository:
    def __init__(
        self, connection: Any, *, owned_connection: PsycopgOAuthConnection | None = None
    ) -> None:
        self.connection = connection
        self._owned_connection = owned_connection

    @classmethod
    def connect(
        cls,
        dsn: str,
        *,
        connect_timeout_seconds: int = 10,
        application_name: str = "formowl-oauth",
    ) -> "PostgreSQLOAuthRepository":
        if not isinstance(dsn, str) or not dsn:
            raise ValueError("OAuth database configuration is required")
        if not 1 <= connect_timeout_seconds <= 60:
            raise ValueError("OAuth database connect timeout is invalid")
        try:
            raw = psycopg.connect(
                dsn,
                connect_timeout=connect_timeout_seconds,
                application_name=application_name,
                autocommit=True,
                row_factory=dict_row,
            )
        except psycopg.Error as exc:
            raise RuntimeError("oauth_database_unavailable") from exc
        adapter = PsycopgOAuthConnection(raw)
        return cls(adapter, owned_connection=adapter)

    def close(self) -> None:
        if self._owned_connection is not None:
            self._owned_connection.close()

    def health_check(self) -> bool:
        try:
            row = self.connection.query_one(SQLStatement(sql="SELECT 1 AS healthy"))
        except Exception:
            return False
        return row is not None and row.get("healthy") == 1

    def apply_migrations(self) -> PostgreSQLMigrationResult:
        with self.transaction() as unit:
            result = PostgreSQLMigrationRunner(self.connection).apply_pending(migration_files())
            unit.commit()
        return result

    def transaction(self) -> PostgreSQLUnitOfWork:
        return PostgreSQLUnitOfWork(self.connection)

    def insert_user(self, user: User) -> None:
        payload = user.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_users "
                    "(user_id, display_name, email, status, created_at) "
                    "VALUES (%(user_id)s, %(display_name)s, %(email)s, %(status)s, %(created_at)s)"
                ),
                parameters=payload,
            )
        )

    def get_user(self, user_id: str) -> User | None:
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT user_id, display_name, email, status, created_at "
                    "FROM formowl_users WHERE user_id = %(user_id)s"
                ),
                parameters={"user_id": user_id},
            )
        )
        return _user_from_row(row) if row else None

    def find_users_by_email(self, normalized_email: str) -> list[User]:
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT user_id, display_name, email, status, created_at "
                    "FROM formowl_users WHERE email = %(normalized_email)s "
                    "ORDER BY user_id"
                ),
                parameters={"normalized_email": normalized_email},
            )
        )
        return [_user_from_row(row) for row in rows]

    def list_workspace_users(self, workspace_id: str) -> list[tuple[User, WorkspaceMember]]:
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT u.user_id, u.display_name, u.email, u.status, u.created_at, "
                    "m.workspace_id AS member_workspace_id, m.user_id AS member_user_id, "
                    "m.role AS member_role FROM formowl_workspace_members AS m "
                    "JOIN formowl_users AS u ON u.user_id = m.user_id "
                    "WHERE m.workspace_id = %(workspace_id)s AND m.removed_at IS NULL "
                    "ORDER BY u.user_id"
                ),
                parameters={"workspace_id": workspace_id},
            )
        )
        return [
            (
                _user_from_row(
                    {
                        "user_id": row["user_id"],
                        "display_name": row["display_name"],
                        "email": row.get("email"),
                        "status": row["status"],
                        "created_at": row["created_at"],
                    }
                ),
                WorkspaceMember.from_dict(
                    {
                        "workspace_id": row["member_workspace_id"],
                        "user_id": row["member_user_id"],
                        "role": row["member_role"],
                    }
                ),
            )
            for row in rows
        ]

    def update_user_profile(self, user_id: str, *, display_name: str, email: str) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_users SET display_name = %(display_name)s, email = %(email)s "
                    "WHERE user_id = %(user_id)s"
                ),
                parameters={"user_id": user_id, "display_name": display_name, "email": email},
            )
        )

    def insert_workspace_member(self, member: WorkspaceMember, *, created_at: str) -> None:
        payload = member.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_workspace_members "
                    "(workspace_id, user_id, role, created_at, removed_at) "
                    "VALUES (%(workspace_id)s, %(user_id)s, %(role)s, %(created_at)s, NULL)"
                ),
                parameters={**payload, "created_at": created_at},
            )
        )

    def get_active_workspace_member(
        self, user_id: str, workspace_id: str, *, for_update: bool = False
    ) -> WorkspaceMember | None:
        locking = " FOR UPDATE" if for_update else ""
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT workspace_id, user_id, role FROM formowl_workspace_members "
                    "WHERE user_id = %(user_id)s AND workspace_id = %(workspace_id)s "
                    f"AND removed_at IS NULL{locking}"
                ),
                parameters={"user_id": user_id, "workspace_id": workspace_id},
            )
        )
        return WorkspaceMember.from_dict(row) if row else None

    def get_removed_workspace_member(
        self, user_id: str, workspace_id: str, *, for_update: bool = False
    ) -> WorkspaceMember | None:
        locking = " FOR UPDATE" if for_update else ""
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT workspace_id, user_id, role FROM formowl_workspace_members "
                    "WHERE user_id = %(user_id)s AND workspace_id = %(workspace_id)s "
                    f"AND removed_at IS NOT NULL{locking}"
                ),
                parameters={"user_id": user_id, "workspace_id": workspace_id},
            )
        )
        return WorkspaceMember.from_dict(row) if row else None

    def remove_workspace_member(self, user_id: str, workspace_id: str, *, removed_at: str) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_workspace_members SET removed_at = %(removed_at)s "
                    "WHERE user_id = %(user_id)s AND workspace_id = %(workspace_id)s "
                    "AND removed_at IS NULL"
                ),
                parameters={
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "removed_at": removed_at,
                },
            )
        )

    def restore_workspace_member(self, user_id: str, workspace_id: str) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_workspace_members SET removed_at = NULL "
                    "WHERE user_id = %(user_id)s AND workspace_id = %(workspace_id)s "
                    "AND removed_at IS NOT NULL"
                ),
                parameters={"user_id": user_id, "workspace_id": workspace_id},
            )
        )

    def list_active_workspace_members(self, user_id: str) -> list[WorkspaceMember]:
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT workspace_id, user_id, role FROM formowl_workspace_members "
                    "WHERE user_id = %(user_id)s AND removed_at IS NULL ORDER BY workspace_id"
                ),
                parameters={"user_id": user_id},
            )
        )
        return [WorkspaceMember.from_dict(row) for row in rows]

    def list_active_workspace_members_in_workspace(
        self, workspace_id: str, *, for_update: bool = False
    ) -> list[WorkspaceMember]:
        locking = " FOR UPDATE" if for_update else ""
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT workspace_id, user_id, role FROM formowl_workspace_members "
                    "WHERE workspace_id = %(workspace_id)s AND removed_at IS NULL "
                    f"ORDER BY user_id{locking}"
                ),
                parameters={"workspace_id": workspace_id},
            )
        )
        return [WorkspaceMember.from_dict(row) for row in rows]

    def revoke_active_token_sessions_for_membership(
        self,
        user_id: str,
        workspace_id: str,
        *,
        revoked_at: str,
        reason_code: str,
    ) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_oauth_token_sessions SET revoked_at = %(revoked_at)s, "
                    "revocation_reason = %(reason_code)s WHERE user_id = %(user_id)s "
                    "AND current_workspace_id = %(workspace_id)s AND revoked_at IS NULL"
                ),
                parameters={
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "revoked_at": revoked_at,
                    "reason_code": reason_code,
                },
            )
        )

    def count_active_workspace_members(self, workspace_id: str) -> int:
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT COUNT(*) AS member_count FROM formowl_workspace_members "
                    "WHERE workspace_id = %(workspace_id)s AND removed_at IS NULL"
                ),
                parameters={"workspace_id": workspace_id},
            )
        )
        return int(row["member_count"]) if row is not None else 0

    def list_active_grants(self, user_id: str, *, now: str) -> list[Grant]:
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT grant_id, owner_user_id, grantee_user_id, scope_type, scope_id, "
                    "permission, expires_at, revoked_at FROM formowl_grants "
                    "WHERE grantee_user_id = %(user_id)s AND revoked_at IS NULL "
                    "AND expires_at > %(now)s ORDER BY grant_id"
                ),
                parameters={"user_id": user_id, "now": now},
            )
        )
        return [Grant.from_dict(_iso_row(row)) for row in rows]

    def insert_external_identity(self, identity: ExternalIdentity) -> None:
        payload = identity.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_external_identities "
                    "(external_identity_id, provider, issuer, subject, user_id, email, "
                    "email_verified, status, created_at, last_authenticated_at) VALUES "
                    "(%(external_identity_id)s, %(provider)s, %(issuer)s, %(subject)s, "
                    "%(user_id)s, %(email)s, %(email_verified)s, %(status)s, %(created_at)s, "
                    "%(last_authenticated_at)s)"
                ),
                parameters=payload,
            )
        )

    def find_external_identity(self, issuer: str, subject: str) -> ExternalIdentity | None:
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_external_identities "
                    "WHERE issuer = %(issuer)s AND subject = %(subject)s"
                ),
                parameters={"issuer": issuer, "subject": subject},
            )
        )
        return ExternalIdentity.from_dict(_iso_row(row)) if row else None

    def get_external_identity(self, external_identity_id: str) -> ExternalIdentity | None:
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_external_identities "
                    "WHERE external_identity_id = %(external_identity_id)s"
                ),
                parameters={"external_identity_id": external_identity_id},
            )
        )
        return ExternalIdentity.from_dict(_iso_row(row)) if row else None

    def update_external_identity_profile(
        self, external_identity_id: str, *, email: str, authenticated_at: str
    ) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_external_identities SET email = %(email)s, "
                    "last_authenticated_at = %(authenticated_at)s "
                    "WHERE external_identity_id = %(external_identity_id)s"
                ),
                parameters={
                    "external_identity_id": external_identity_id,
                    "email": email,
                    "authenticated_at": authenticated_at,
                },
            )
        )

    def insert_invitation(self, invitation: OAuthInvitation) -> None:
        payload = invitation.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_oauth_invitations "
                    "(invitation_id, normalized_email, intended_user_id, workspace_id, role, "
                    "status, expires_at, created_at, accepted_at, accepted_external_identity_id) "
                    "VALUES (%(invitation_id)s, %(normalized_email)s, %(intended_user_id)s, "
                    "%(workspace_id)s, %(role)s, %(status)s, %(expires_at)s, %(created_at)s, "
                    "%(accepted_at)s, %(accepted_external_identity_id)s)"
                ),
                parameters={
                    **payload,
                    "intended_user_id": payload.get("intended_user_id"),
                    "accepted_at": payload.get("accepted_at"),
                    "accepted_external_identity_id": payload.get("accepted_external_identity_id"),
                },
            )
        )

    def get_invitation(self, invitation_id: str) -> OAuthInvitation | None:
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_invitations "
                    "WHERE invitation_id = %(invitation_id)s"
                ),
                parameters={"invitation_id": invitation_id},
            )
        )
        return OAuthInvitation.from_dict(_iso_row(row)) if row else None

    def find_pending_owner_invitations(
        self,
        workspace_id: str,
        *,
        now: str,
        for_update: bool = False,
    ) -> list[OAuthInvitation]:
        locking = " FOR UPDATE" if for_update else ""
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_invitations "
                    "WHERE workspace_id = %(workspace_id)s AND role = 'owner' "
                    "AND status = 'pending' AND expires_at > %(now)s "
                    "ORDER BY invitation_id" + locking
                ),
                parameters={"workspace_id": workspace_id, "now": now},
            )
        )
        return [OAuthInvitation.from_dict(_iso_row(row)) for row in rows]

    def find_active_invitations(
        self, normalized_email: str, *, now: str, for_update: bool = False
    ) -> list[OAuthInvitation]:
        locking = " FOR UPDATE" if for_update else ""
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_invitations "
                    "WHERE normalized_email = %(normalized_email)s AND status = 'pending' "
                    "AND expires_at > %(now)s ORDER BY invitation_id" + locking
                ),
                parameters={"normalized_email": normalized_email, "now": now},
            )
        )
        return [OAuthInvitation.from_dict(_iso_row(row)) for row in rows]

    def mark_invitation_accepted(
        self,
        invitation_id: str,
        *,
        external_identity_id: str,
        accepted_at: str,
    ) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_oauth_invitations SET status = 'accepted', "
                    "accepted_at = %(accepted_at)s, "
                    "accepted_external_identity_id = %(external_identity_id)s "
                    "WHERE invitation_id = %(invitation_id)s AND status = 'pending'"
                ),
                parameters={
                    "invitation_id": invitation_id,
                    "external_identity_id": external_identity_id,
                    "accepted_at": accepted_at,
                },
            )
        )

    def upsert_owner_bootstrap(self, bootstrap: OAuthOwnerBootstrap) -> bool:
        payload = bootstrap.to_dict()
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_oauth_owner_bootstraps "
                    "(workspace_id, idempotency_key_hash, normalized_email, invitation_id, "
                    "operator_service_id, status, created_at, completed_at) VALUES "
                    "(%(workspace_id)s, %(idempotency_key_hash)s, %(normalized_email)s, "
                    "%(invitation_id)s, %(operator_service_id)s, %(status)s, %(created_at)s, "
                    "%(completed_at)s) ON CONFLICT (workspace_id) DO NOTHING "
                    "RETURNING workspace_id"
                ),
                parameters={**payload, "completed_at": payload.get("completed_at")},
            )
        )
        return row is not None

    def get_owner_bootstrap(
        self,
        workspace_id: str,
        *,
        for_update: bool = False,
    ) -> OAuthOwnerBootstrap | None:
        locking = " FOR UPDATE" if for_update else ""
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_owner_bootstraps "
                    "WHERE workspace_id = %(workspace_id)s" + locking
                ),
                parameters={"workspace_id": workspace_id},
            )
        )
        return OAuthOwnerBootstrap.from_dict(_iso_row(row)) if row else None

    def get_owner_bootstrap_by_invitation(
        self,
        invitation_id: str,
        *,
        for_update: bool = False,
    ) -> OAuthOwnerBootstrap | None:
        locking = " FOR UPDATE" if for_update else ""
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_owner_bootstraps "
                    "WHERE invitation_id = %(invitation_id)s" + locking
                ),
                parameters={"invitation_id": invitation_id},
            )
        )
        return OAuthOwnerBootstrap.from_dict(_iso_row(row)) if row else None

    def complete_owner_bootstrap(self, invitation_id: str, *, completed_at: str) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_oauth_owner_bootstraps SET status = 'completed', "
                    "completed_at = %(completed_at)s WHERE invitation_id = %(invitation_id)s "
                    "AND status = 'pending' AND completed_at IS NULL"
                ),
                parameters={"invitation_id": invitation_id, "completed_at": completed_at},
            )
        )

    def insert_client_authorization(self, authorization: OAuthClientAuthorization) -> None:
        payload = authorization.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_oauth_client_authorizations "
                    "(oauth_client_authorization_id, client_id, external_identity_id, user_id, "
                    "granted_scopes, default_workspace_id, created_at, revoked_at) VALUES "
                    "(%(oauth_client_authorization_id)s, %(client_id)s, "
                    "%(external_identity_id)s, %(user_id)s, %(granted_scopes)s, "
                    "%(default_workspace_id)s, %(created_at)s, %(revoked_at)s)"
                ),
                parameters={**payload, "revoked_at": payload.get("revoked_at")},
            )
        )

    def get_client_authorization(
        self, client_id: str, external_identity_id: str
    ) -> OAuthClientAuthorization | None:
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_client_authorizations "
                    "WHERE client_id = %(client_id)s "
                    "AND external_identity_id = %(external_identity_id)s"
                ),
                parameters={
                    "client_id": client_id,
                    "external_identity_id": external_identity_id,
                },
            )
        )
        return OAuthClientAuthorization.from_dict(_iso_row(row)) if row else None

    def get_client_authorization_by_id(
        self, oauth_client_authorization_id: str
    ) -> OAuthClientAuthorization | None:
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_client_authorizations "
                    "WHERE oauth_client_authorization_id = %(authorization_id)s"
                ),
                parameters={"authorization_id": oauth_client_authorization_id},
            )
        )
        return OAuthClientAuthorization.from_dict(_iso_row(row)) if row else None

    def insert_transaction(self, transaction: OAuthTransaction) -> None:
        payload = transaction.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_oauth_transactions "
                    "(transaction_id, google_state_hash, encrypted_client_state, "
                    "google_nonce_hash, client_id, redirect_uri, resource, scopes, "
                    "code_challenge, code_challenge_method, created_at, expires_at, status, "
                    "consumed_at) VALUES (%(transaction_id)s, %(google_state_hash)s, "
                    "%(encrypted_client_state)s, %(google_nonce_hash)s, %(client_id)s, "
                    "%(redirect_uri)s, %(resource)s, %(scopes)s, %(code_challenge)s, "
                    "%(code_challenge_method)s, %(created_at)s, %(expires_at)s, %(status)s, "
                    "%(consumed_at)s)"
                ),
                parameters={**payload, "consumed_at": payload.get("consumed_at")},
            )
        )

    def get_transaction_by_state_hash(
        self, google_state_hash: str, *, for_update: bool = False
    ) -> OAuthTransaction | None:
        locking = " FOR UPDATE" if for_update else ""
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_transactions "
                    "WHERE google_state_hash = %(google_state_hash)s" + locking
                ),
                parameters={"google_state_hash": google_state_hash},
            )
        )
        return OAuthTransaction.from_dict(_iso_row(row)) if row else None

    def consume_transaction(self, transaction_id: str, *, consumed_at: str) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_oauth_transactions SET status = 'consumed', "
                    "consumed_at = %(consumed_at)s WHERE transaction_id = %(transaction_id)s "
                    "AND status = 'pending' AND consumed_at IS NULL"
                ),
                parameters={"transaction_id": transaction_id, "consumed_at": consumed_at},
            )
        )

    def fail_transaction(self, transaction_id: str, *, failed_at: str) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_oauth_transactions SET status = 'failed', "
                    "consumed_at = %(failed_at)s WHERE transaction_id = %(transaction_id)s "
                    "AND status = 'pending' AND consumed_at IS NULL"
                ),
                parameters={"transaction_id": transaction_id, "failed_at": failed_at},
            )
        )

    def insert_authorization_code(self, code: OAuthAuthorizationCode) -> None:
        payload = code.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_oauth_authorization_codes "
                    "(code_hash, transaction_id, user_id, external_identity_id, client_id, "
                    "redirect_uri, resource, scopes, code_challenge, created_at, expires_at, "
                    "consumed_at) VALUES (%(code_hash)s, %(transaction_id)s, %(user_id)s, "
                    "%(external_identity_id)s, %(client_id)s, %(redirect_uri)s, %(resource)s, "
                    "%(scopes)s, %(code_challenge)s, %(created_at)s, %(expires_at)s, "
                    "%(consumed_at)s)"
                ),
                parameters={**payload, "consumed_at": payload.get("consumed_at")},
            )
        )

    def get_authorization_code(
        self, code_hash: str, *, for_update: bool = False
    ) -> OAuthAuthorizationCode | None:
        locking = " FOR UPDATE" if for_update else ""
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_authorization_codes "
                    "WHERE code_hash = %(code_hash)s" + locking
                ),
                parameters={"code_hash": code_hash},
            )
        )
        return OAuthAuthorizationCode.from_dict(_iso_row(row)) if row else None

    def consume_authorization_code(
        self,
        code_hash: str,
        *,
        consumed_at: str,
        user_id: str,
        external_identity_id: str,
        client_id: str,
        redirect_uri: str,
        resource: str,
    ) -> None:
        consumed = self.connection.query_one(
            SQLStatement(
                sql=(
                    "UPDATE formowl_oauth_authorization_codes SET consumed_at = %(consumed_at)s "
                    "WHERE code_hash = %(code_hash)s AND consumed_at IS NULL "
                    "AND expires_at > %(consumed_at)s AND user_id = %(user_id)s "
                    "AND external_identity_id = %(external_identity_id)s "
                    "AND client_id = %(client_id)s AND redirect_uri = %(redirect_uri)s "
                    "AND resource = %(resource)s RETURNING code_hash"
                ),
                parameters={
                    "code_hash": code_hash,
                    "consumed_at": consumed_at,
                    "user_id": user_id,
                    "external_identity_id": external_identity_id,
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "resource": resource,
                },
            )
        )
        if consumed is None or consumed.get("code_hash") != code_hash:
            raise OAuthAccessDenied(
                "invalid_grant",
                "authorization_code_not_consumable",
                400,
            )

    def insert_token_session(self, session: OAuthTokenSession) -> None:
        payload = session.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_oauth_token_sessions "
                    "(token_session_id, user_id, external_identity_id, "
                    "oauth_client_authorization_id, client_id, current_workspace_id, resource, "
                    "scopes, token_jti_hash, issued_at, expires_at, revoked_at, "
                    "revocation_reason) VALUES (%(token_session_id)s, %(user_id)s, "
                    "%(external_identity_id)s, %(oauth_client_authorization_id)s, "
                    "%(client_id)s, %(current_workspace_id)s, %(resource)s, %(scopes)s, "
                    "%(token_jti_hash)s, %(issued_at)s, %(expires_at)s, %(revoked_at)s, "
                    "%(revocation_reason)s)"
                ),
                parameters={
                    **payload,
                    "revoked_at": payload.get("revoked_at"),
                    "revocation_reason": payload.get("revocation_reason"),
                },
            )
        )

    def get_token_session(self, token_session_id: str) -> OAuthTokenSession | None:
        row = self.connection.query_one(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_token_sessions "
                    "WHERE token_session_id = %(token_session_id)s"
                ),
                parameters={"token_session_id": token_session_id},
            )
        )
        return OAuthTokenSession.from_dict(_iso_row(row)) if row else None

    def list_token_sessions(self, user_id: str, workspace_id: str) -> list[OAuthTokenSession]:
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT * FROM formowl_oauth_token_sessions "
                    "WHERE user_id = %(user_id)s "
                    "AND current_workspace_id = %(workspace_id)s "
                    "ORDER BY issued_at DESC, token_session_id"
                ),
                parameters={"user_id": user_id, "workspace_id": workspace_id},
            )
        )
        return [OAuthTokenSession.from_dict(_iso_row(row)) for row in rows]

    def revoke_token_session(
        self, token_session_id: str, *, revoked_at: str, reason_code: str
    ) -> None:
        self.connection.execute(
            SQLStatement(
                sql=(
                    "UPDATE formowl_oauth_token_sessions SET revoked_at = %(revoked_at)s, "
                    "revocation_reason = %(reason_code)s WHERE token_session_id = "
                    "%(token_session_id)s AND revoked_at IS NULL"
                ),
                parameters={
                    "token_session_id": token_session_id,
                    "revoked_at": revoked_at,
                    "reason_code": reason_code,
                },
            )
        )

    def list_issue20_live_audit_rows(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        actions: tuple[str, ...],
        row_limit: int,
    ) -> list[dict[str, Any]]:
        if (
            not isinstance(started_at, datetime)
            or started_at.tzinfo is None
            or started_at.utcoffset() is None
            or not isinstance(ended_at, datetime)
            or ended_at.tzinfo is None
            or ended_at.utcoffset() is None
            or ended_at <= started_at
            or not isinstance(actions, tuple)
            or not actions
            or any(not isinstance(action, str) or not action for action in actions)
            or isinstance(row_limit, bool)
            or not isinstance(row_limit, int)
            or not 1 <= row_limit <= 257
        ):
            raise ValueError("Issue #20 audit query is invalid")
        rows = self.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT audit_log_id, actor_user_id, actor_service_id, actor_type, "
                    "action, target_type, target_id, session_id, workspace_id, status, "
                    "external_identity_id, oauth_client_id, oauth_token_session_id, "
                    "request_id, tool_call_id, reason_code, metadata, timestamp "
                    "FROM formowl_audit_log "
                    "WHERE timestamp >= %(started_at)s AND timestamp <= %(ended_at)s "
                    "AND action = ANY(%(actions)s) "
                    "ORDER BY timestamp, audit_log_id LIMIT %(row_limit)s"
                ),
                parameters={
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "actions": list(actions),
                    "row_limit": row_limit,
                },
            )
        )
        return [_iso_row(row) for row in rows]

    def append_audit_log(self, audit_log: AuditLog) -> None:
        payload = audit_log.to_dict()
        self.connection.execute(
            SQLStatement(
                sql=(
                    "INSERT INTO formowl_audit_log "
                    "(audit_log_id, actor_user_id, actor_service_id, actor_type, action, "
                    "target_type, target_id, session_id, workspace_id, status, "
                    "external_identity_id, oauth_client_id, oauth_token_session_id, request_id, "
                    "tool_call_id, reason_code, metadata, timestamp) VALUES "
                    "(%(audit_log_id)s, %(actor_user_id)s, %(actor_service_id)s, "
                    "%(actor_type)s, %(action)s, %(target_type)s, %(target_id)s, "
                    "%(session_id)s, %(workspace_id)s, %(status)s, %(external_identity_id)s, "
                    "%(oauth_client_id)s, %(oauth_token_session_id)s, %(request_id)s, "
                    "%(tool_call_id)s, %(reason_code)s, %(metadata)s::jsonb, %(timestamp)s)"
                ),
                parameters={
                    **payload,
                    "actor_user_id": payload.get("actor_user_id"),
                    "actor_service_id": payload.get("actor_service_id"),
                    "workspace_id": payload.get("workspace_id"),
                    "status": payload.get("status"),
                    "external_identity_id": payload.get("external_identity_id"),
                    "oauth_client_id": payload.get("oauth_client_id"),
                    "oauth_token_session_id": payload.get("oauth_token_session_id"),
                    "request_id": payload.get("request_id"),
                    "tool_call_id": payload.get("tool_call_id"),
                    "reason_code": payload.get("reason_code"),
                    "metadata": payload.get("metadata") or {},
                },
            )
        )


def oauth_migration_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "formowl_graph"
        / "storage"
        / "migrations"
        / "005_oauth_identity.sql"
    )


def _user_from_row(row: dict[str, Any]) -> User:
    return User.from_dict(_iso_row(row))


def _iso_row(row: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        elif isinstance(value, list):
            payload[key] = list(value)
        else:
            payload[key] = value
    return payload


__all__ = [
    "OAuthRepository",
    "OAuthUnitOfWork",
    "PostgreSQLOAuthRepository",
    "PsycopgOAuthConnection",
    "oauth_migration_path",
]
