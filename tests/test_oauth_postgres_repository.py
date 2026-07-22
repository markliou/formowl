from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import unittest

import psycopg
from psycopg.types.json import Jsonb

import _paths  # noqa: F401
from formowl_auth import (
    ExternalIdentity,
    OAuthAuthorizationCode,
    OAuthClientAuthorization,
    OAuthInvitation,
    OAuthOwnerBootstrap,
    OAuthTokenSession,
    OAuthTransaction,
)
from formowl_auth.models import OAuthAccessDenied
from formowl_auth.security import hash_oauth_value
from formowl_auth.postgres import (
    PostgreSQLOAuthRepository,
    PsycopgOAuthConnection,
    oauth_migration_path,
)
from formowl_contract import AuditLog, Grant, User, WorkspaceMember
from formowl_graph.storage import SQLStatement, migration_files


class FakeCursor:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeRawPsycopgConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []
        self.next_rows: list[dict[str, object]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def execute(self, sql: str, parameters=None) -> FakeCursor:
        self.executions.append((sql, parameters))
        return FakeCursor(self.next_rows)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


class RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[SQLStatement] = []
        self.operation_kinds: list[str] = []
        self.query_one_results: list[dict[str, object] | None] = []
        self.query_all_results: list[list[dict[str, object]]] = []
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_queries = False

    def execute(self, statement: SQLStatement) -> None:
        self.operation_kinds.append("execute")
        self.statements.append(statement)

    def query_one(self, statement: SQLStatement):
        self.operation_kinds.append("query_one")
        self.statements.append(statement)
        if self.fail_queries:
            raise RuntimeError("database detail must remain internal")
        if self.query_one_results:
            return self.query_one_results.pop(0)
        return None

    def query_all(self, statement: SQLStatement):
        self.operation_kinds.append("query_all")
        self.statements.append(statement)
        if self.fail_queries:
            raise RuntimeError("database detail must remain internal")
        if self.query_all_results:
            return self.query_all_results.pop(0)
        return []

    def begin(self) -> None:
        self.operation_kinds.append("begin")
        self.begin_count += 1

    def commit(self) -> None:
        self.operation_kinds.append("commit")
        self.commit_count += 1

    def rollback(self) -> None:
        self.operation_kinds.append("rollback")
        self.rollback_count += 1


class FailingMigrationConnection(RecordingConnection):
    def __init__(self) -> None:
        super().__init__()
        self.durable_effects = ["preexisting_durable_state"]
        self.pending_effects: list[str] = []
        self.rolled_back_effects: tuple[str, ...] = ()
        self._migration_statement_count = 0
        self._in_transaction = False

    def execute(self, statement: SQLStatement) -> None:
        super().execute(statement)
        if "statement_index" in statement.parameters:
            self._migration_statement_count += 1
            if self._migration_statement_count == 2:
                raise RuntimeError("migration_apply_failed")
            effect = (
                f"migration:{statement.parameters['migration_id']}:"
                f"{statement.parameters['statement_index']}"
            )
        elif "lock_key" in statement.parameters:
            effect = "migration_advisory_lock"
        else:
            effect = "migration_ledger_or_schema"
        if self._in_transaction:
            self.pending_effects.append(effect)
        else:
            self.durable_effects.append(effect)

    def begin(self) -> None:
        super().begin()
        self._in_transaction = True
        self.pending_effects = []

    def commit(self) -> None:
        super().commit()
        self.durable_effects.extend(self.pending_effects)
        self.pending_effects = []
        self._in_transaction = False

    def rollback(self) -> None:
        super().rollback()
        self.rolled_back_effects = tuple(self.pending_effects)
        self.pending_effects = []
        self._in_transaction = False


class OAuthPostgresRepositoryTests(unittest.TestCase):
    def test_transaction_and_code_crud_map_rows_and_bind_every_value(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        created_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        expires_at = datetime(2026, 7, 12, 4, 5, tzinfo=timezone.utc)
        consumed_at = "2026-07-12T04:01:00+00:00"
        transaction = OAuthTransaction(
            transaction_id="oauthtx_crud_001",
            google_state_hash=hash_oauth_value("google_state", "private-google-state"),
            encrypted_client_state="encrypted-client-state",
            google_nonce_hash=hash_oauth_value("google_nonce", "private-google-nonce"),
            client_id="chatgpt_client",
            redirect_uri="https://chatgpt.example.test/oauth/callback",
            resource="https://formowl.example.test/mcp",
            scopes=("formowl.use",),
            code_challenge="A" * 43,
            code_challenge_method="S256",
            created_at=created_at.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        code = OAuthAuthorizationCode(
            code_hash=hash_oauth_value("authorization_code", "private-authorization-code"),
            transaction_id=transaction.transaction_id,
            user_id="user_crud_001",
            external_identity_id="extid_crud_001",
            client_id=transaction.client_id,
            redirect_uri=transaction.redirect_uri,
            resource=transaction.resource,
            scopes=transaction.scopes,
            code_challenge=transaction.code_challenge,
            created_at=created_at.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        connection.query_one_results.extend(
            [
                {
                    **transaction.to_dict(),
                    "scopes": list(transaction.scopes),
                    "created_at": created_at,
                    "expires_at": expires_at,
                },
                {
                    **code.to_dict(),
                    "scopes": list(code.scopes),
                    "created_at": created_at,
                    "expires_at": expires_at,
                },
                {"code_hash": code.code_hash},
            ]
        )

        repository.insert_transaction(transaction)
        stored_transaction = repository.get_transaction_by_state_hash(
            transaction.google_state_hash,
            for_update=True,
        )
        repository.consume_transaction(
            transaction.transaction_id,
            consumed_at=consumed_at,
        )
        repository.insert_authorization_code(code)
        stored_code = repository.get_authorization_code(code.code_hash, for_update=True)
        repository.consume_authorization_code(
            code.code_hash,
            consumed_at=consumed_at,
            user_id=code.user_id,
            external_identity_id=code.external_identity_id,
            client_id=code.client_id,
            redirect_uri=code.redirect_uri,
            resource=code.resource,
        )

        self.assertEqual(stored_transaction, transaction)
        self.assertEqual(stored_code, code)
        insert_transaction, get_transaction, consume_transaction = connection.statements[:3]
        insert_code, get_code, consume_code = connection.statements[3:]
        self.assertEqual(
            insert_transaction.parameters,
            {**transaction.to_dict(), "consumed_at": None},
        )
        self.assertEqual(
            get_transaction.parameters,
            {"google_state_hash": transaction.google_state_hash},
        )
        self.assertTrue(get_transaction.sql.endswith(" FOR UPDATE"))
        self.assertEqual(
            consume_transaction.parameters,
            {
                "transaction_id": transaction.transaction_id,
                "consumed_at": consumed_at,
            },
        )
        self.assertIn("status = 'pending'", consume_transaction.sql)
        self.assertIn("consumed_at IS NULL", consume_transaction.sql)
        self.assertEqual(insert_code.parameters, {**code.to_dict(), "consumed_at": None})
        self.assertEqual(get_code.parameters, {"code_hash": code.code_hash})
        self.assertTrue(get_code.sql.endswith(" FOR UPDATE"))
        self.assertEqual(consume_code.parameters["code_hash"], code.code_hash)
        for statement in connection.statements:
            for value in statement.parameters.values():
                if isinstance(value, str):
                    self.assertNotIn(value, statement.sql)

    def test_invitation_and_identity_crud_map_rows_and_bind_every_value(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        created_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        authenticated_at = datetime(2026, 7, 12, 4, 30, tzinfo=timezone.utc)
        expires_at = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)
        user = User(
            user_id="user_crud_001",
            display_name="CRUD User",
            email="crud@example.test",
            status="active",
            created_at=created_at.isoformat(),
        )
        identity = ExternalIdentity(
            external_identity_id="extid_crud_001",
            provider="google",
            issuer="https://accounts.google.com",
            subject="google-subject-crud-001",
            user_id=user.user_id,
            email=user.email,
            email_verified=True,
            status="active",
            created_at=created_at.isoformat(),
            last_authenticated_at=authenticated_at.isoformat(),
        )
        invitation = OAuthInvitation(
            invitation_id="invite_crud_001",
            normalized_email=user.email,
            intended_user_id=user.user_id,
            workspace_id="workspace_crud_001",
            role="member",
            status="pending",
            expires_at=expires_at.isoformat(),
            created_at=created_at.isoformat(),
        )
        user_row = {**user.to_dict(), "created_at": created_at}
        identity_row = {
            **identity.to_dict(),
            "created_at": created_at,
            "last_authenticated_at": authenticated_at,
        }
        invitation_row = {
            **invitation.to_dict(),
            "created_at": created_at,
            "expires_at": expires_at,
        }
        connection.query_one_results.extend([user_row, identity_row, identity_row])
        connection.query_all_results.extend([[user_row], [invitation_row]])

        repository.insert_user(user)
        stored_user = repository.get_user(user.user_id)
        users = repository.find_users_by_email(user.email)
        repository.update_user_profile(
            user.user_id,
            display_name="Updated CRUD User",
            email="updated-crud@example.test",
        )
        repository.insert_external_identity(identity)
        found_identity = repository.find_external_identity(identity.issuer, identity.subject)
        stored_identity = repository.get_external_identity(identity.external_identity_id)
        repository.update_external_identity_profile(
            identity.external_identity_id,
            email="updated-crud@example.test",
            authenticated_at=authenticated_at.isoformat(),
        )
        repository.insert_invitation(invitation)
        invitations = repository.find_active_invitations(
            invitation.normalized_email,
            now=created_at.isoformat(),
            for_update=True,
        )
        repository.mark_invitation_accepted(
            invitation.invitation_id,
            external_identity_id=identity.external_identity_id,
            accepted_at=authenticated_at.isoformat(),
        )

        self.assertEqual(stored_user, user)
        self.assertEqual(users, [user])
        self.assertEqual(found_identity, identity)
        self.assertEqual(stored_identity, identity)
        self.assertEqual(invitations, [invitation])
        (
            insert_user,
            get_user,
            find_users,
            update_user,
            insert_identity,
            find_identity,
            get_identity,
            update_identity,
        ) = connection.statements[:8]
        self.assertEqual(insert_user.parameters, user.to_dict())
        self.assertEqual(get_user.parameters, {"user_id": user.user_id})
        self.assertEqual(find_users.parameters, {"normalized_email": user.email})
        self.assertEqual(
            update_user.parameters,
            {
                "user_id": user.user_id,
                "display_name": "Updated CRUD User",
                "email": "updated-crud@example.test",
            },
        )
        self.assertEqual(insert_identity.parameters, identity.to_dict())
        self.assertEqual(
            find_identity.parameters,
            {"issuer": identity.issuer, "subject": identity.subject},
        )
        self.assertEqual(
            get_identity.parameters,
            {"external_identity_id": identity.external_identity_id},
        )
        self.assertEqual(
            update_identity.parameters,
            {
                "external_identity_id": identity.external_identity_id,
                "email": "updated-crud@example.test",
                "authenticated_at": authenticated_at.isoformat(),
            },
        )
        insert_invitation, find_invitations, accept_invitation = connection.statements[-3:]
        self.assertEqual(
            insert_invitation.parameters,
            {
                **invitation.to_dict(),
                "intended_user_id": invitation.intended_user_id,
                "accepted_at": None,
                "accepted_external_identity_id": None,
            },
        )
        self.assertEqual(
            find_invitations.parameters,
            {
                "normalized_email": invitation.normalized_email,
                "now": created_at.isoformat(),
            },
        )
        self.assertIn("status = 'pending'", find_invitations.sql)
        self.assertIn("expires_at > %(now)s", find_invitations.sql)
        self.assertTrue(find_invitations.sql.endswith(" FOR UPDATE"))
        self.assertEqual(
            accept_invitation.parameters,
            {
                "invitation_id": invitation.invitation_id,
                "external_identity_id": identity.external_identity_id,
                "accepted_at": authenticated_at.isoformat(),
            },
        )
        self.assertIn("status = 'pending'", accept_invitation.sql)
        for statement in connection.statements:
            for value in statement.parameters.values():
                if isinstance(value, str):
                    self.assertNotIn(value, statement.sql)

    def test_identity_reads_pin_keyed_sql_and_not_found_without_side_effects(
        self,
    ) -> None:
        lookup_cases = (
            (
                "get_user",
                ("user_missing'; DROP TABLE formowl_users; --",),
                "SELECT user_id, display_name, email, status, created_at "
                "FROM formowl_users WHERE user_id = %(user_id)s",
                "user_id = %(user_id)s",
                {"user_id": "user_missing'; DROP TABLE formowl_users; --"},
                None,
                "query_one",
            ),
            (
                "find_users_by_email",
                ("missing+lookup@example.test",),
                "SELECT user_id, display_name, email, status, created_at "
                "FROM formowl_users WHERE email = %(normalized_email)s ORDER BY user_id",
                "email = %(normalized_email)s",
                {"normalized_email": "missing+lookup@example.test"},
                [],
                "query_all",
            ),
            (
                "find_external_identity",
                (
                    "https://accounts.google.com",
                    "subject_missing'; DROP TABLE formowl_external_identities; --",
                ),
                "SELECT * FROM formowl_external_identities "
                "WHERE issuer = %(issuer)s AND subject = %(subject)s",
                "issuer = %(issuer)s AND subject = %(subject)s",
                {
                    "issuer": "https://accounts.google.com",
                    "subject": ("subject_missing'; DROP TABLE formowl_external_identities; --"),
                },
                None,
                "query_one",
            ),
            (
                "get_external_identity",
                ("extid_missing'; DROP TABLE formowl_external_identities; --",),
                "SELECT * FROM formowl_external_identities "
                "WHERE external_identity_id = %(external_identity_id)s",
                "external_identity_id = %(external_identity_id)s",
                {
                    "external_identity_id": (
                        "extid_missing'; DROP TABLE formowl_external_identities; --"
                    )
                },
                None,
                "query_one",
            ),
        )

        def assert_keyed_statement(
            statement: SQLStatement,
            *,
            expected_sql: str,
            expected_parameters: dict[str, object],
        ) -> None:
            self.assertEqual(statement.sql, expected_sql)
            self.assertEqual(statement.parameters, expected_parameters)

        for (
            method_name,
            arguments,
            expected_sql,
            predicate,
            expected_parameters,
            expected_result,
            operation_kind,
        ) in lookup_cases:
            with self.subTest(method_name=method_name):
                connection = RecordingConnection()
                repository = PostgreSQLOAuthRepository(connection)

                result = getattr(repository, method_name)(*arguments)

                self.assertEqual(result, expected_result)
                self.assertEqual(connection.operation_kinds, [operation_kind])
                self.assertEqual(len(connection.statements), 1)
                self.assertEqual(
                    (
                        connection.begin_count,
                        connection.commit_count,
                        connection.rollback_count,
                    ),
                    (0, 0, 0),
                )
                statement = connection.statements[0]
                assert_keyed_statement(
                    statement,
                    expected_sql=expected_sql,
                    expected_parameters=expected_parameters,
                )
                for value in expected_parameters.values():
                    self.assertNotIn(str(value), statement.sql)

                mutated_sql = statement.sql.replace(f" WHERE {predicate}", "")
                self.assertNotEqual(mutated_sql, statement.sql)
                with self.assertRaises(AssertionError):
                    assert_keyed_statement(
                        SQLStatement(
                            sql=mutated_sql,
                            parameters=dict(statement.parameters),
                        ),
                        expected_sql=expected_sql,
                        expected_parameters=expected_parameters,
                    )

    def test_membership_and_grant_crud_map_rows_and_bind_every_value(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        created_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        expires_at = datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)
        user = User(
            user_id="user_membership_001",
            display_name="Membership User",
            email="membership@example.test",
            status="active",
            created_at=created_at.isoformat(),
        )
        member = WorkspaceMember(
            workspace_id="workspace_membership_001",
            user_id=user.user_id,
            role="member",
        )
        grant = Grant(
            grant_id="grant_membership_001",
            owner_user_id="user_owner_001",
            grantee_user_id=user.user_id,
            scope_type="asset",
            scope_id="asset_membership_001",
            permission="evidence_snippet",
            expires_at=expires_at.isoformat(),
        )
        member_row = member.to_dict()
        user_row = {**user.to_dict(), "created_at": created_at}
        connection.query_one_results.extend([member_row, member_row])
        connection.query_all_results.extend(
            [
                [member_row],
                [member_row],
                [
                    {
                        **user_row,
                        "member_workspace_id": member.workspace_id,
                        "member_user_id": member.user_id,
                        "member_role": member.role,
                    }
                ],
                [{**grant.to_dict(), "expires_at": expires_at}],
            ]
        )

        repository.insert_workspace_member(member, created_at=created_at.isoformat())
        active = repository.get_active_workspace_member(
            member.user_id,
            member.workspace_id,
            for_update=True,
        )
        removed = repository.get_removed_workspace_member(
            member.user_id,
            member.workspace_id,
            for_update=True,
        )
        user_memberships = repository.list_active_workspace_members(member.user_id)
        workspace_memberships = repository.list_active_workspace_members_in_workspace(
            member.workspace_id,
            for_update=True,
        )
        workspace_users = repository.list_workspace_users(member.workspace_id)
        grants = repository.list_active_grants(
            member.user_id,
            now=created_at.isoformat(),
        )

        self.assertEqual(active, member)
        self.assertEqual(removed, member)
        self.assertEqual(user_memberships, [member])
        self.assertEqual(workspace_memberships, [member])
        self.assertEqual(workspace_users, [(user, member)])
        self.assertEqual(grants, [grant])
        (
            insert_member,
            get_active_member,
            get_removed_member,
            list_user_memberships,
            list_workspace_memberships,
            list_workspace_users,
            list_grants,
        ) = connection.statements
        self.assertEqual(
            insert_member.parameters,
            {**member.to_dict(), "created_at": created_at.isoformat()},
        )
        self.assertEqual(
            get_active_member.parameters,
            {"user_id": member.user_id, "workspace_id": member.workspace_id},
        )
        self.assertIn("removed_at IS NULL", get_active_member.sql)
        self.assertTrue(get_active_member.sql.endswith(" FOR UPDATE"))
        self.assertEqual(
            get_removed_member.parameters,
            {"user_id": member.user_id, "workspace_id": member.workspace_id},
        )
        self.assertIn("removed_at IS NOT NULL", get_removed_member.sql)
        self.assertTrue(get_removed_member.sql.endswith(" FOR UPDATE"))
        self.assertEqual(list_user_memberships.parameters, {"user_id": member.user_id})
        self.assertIn("removed_at IS NULL", list_user_memberships.sql)
        self.assertEqual(
            list_workspace_memberships.parameters,
            {"workspace_id": member.workspace_id},
        )
        self.assertIn("removed_at IS NULL", list_workspace_memberships.sql)
        self.assertTrue(list_workspace_memberships.sql.endswith(" FOR UPDATE"))
        self.assertEqual(
            list_workspace_users.parameters,
            {"workspace_id": member.workspace_id},
        )
        self.assertIn("m.removed_at IS NULL", list_workspace_users.sql)
        self.assertEqual(
            list_grants.parameters,
            {"user_id": member.user_id, "now": created_at.isoformat()},
        )
        self.assertIn("revoked_at IS NULL", list_grants.sql)
        self.assertIn("expires_at > %(now)s", list_grants.sql)
        for statement in connection.statements:
            for value in statement.parameters.values():
                if isinstance(value, str) and len(value) >= 8:
                    self.assertNotIn(value, statement.sql)

    def test_client_authorization_and_token_crud_map_rows_and_bind_every_value(
        self,
    ) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        issued_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        expires_at = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)
        revoked_at = "2026-07-12T04:30:00+00:00"
        authorization = OAuthClientAuthorization(
            oauth_client_authorization_id="clientauth_crud_001",
            client_id="chatgpt_client",
            external_identity_id="extid_crud_001",
            user_id="user_crud_001",
            granted_scopes=("formowl.use",),
            default_workspace_id="workspace_crud_001",
            created_at=issued_at.isoformat(),
        )
        session = OAuthTokenSession(
            token_session_id="oauthsid_crud_001",
            user_id=authorization.user_id,
            external_identity_id=authorization.external_identity_id,
            oauth_client_authorization_id=authorization.oauth_client_authorization_id,
            client_id=authorization.client_id,
            current_workspace_id=authorization.default_workspace_id,
            resource="https://formowl.example.test/mcp",
            scopes=authorization.granted_scopes,
            token_jti_hash=hash_oauth_value("token_jti", "private-token-jti"),
            issued_at=issued_at.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        authorization_row = {
            **authorization.to_dict(),
            "granted_scopes": list(authorization.granted_scopes),
            "created_at": issued_at,
        }
        session_row = {
            **session.to_dict(),
            "scopes": list(session.scopes),
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        revoked_session = replace(
            session,
            revoked_at=revoked_at,
            revocation_reason="operator_revoked",
        )
        revoked_session_row = {
            **revoked_session.to_dict(),
            "scopes": list(revoked_session.scopes),
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revoked_at": datetime.fromisoformat(revoked_at),
        }
        connection.query_one_results.extend(
            [
                authorization_row,
                authorization_row,
                session_row,
                revoked_session_row,
                None,
            ]
        )
        connection.query_all_results.append([session_row])

        repository.insert_client_authorization(authorization)
        found_authorization = repository.get_client_authorization(
            authorization.client_id,
            authorization.external_identity_id,
        )
        found_authorization_by_id = repository.get_client_authorization_by_id(
            authorization.oauth_client_authorization_id
        )
        repository.insert_token_session(session)
        found_session = repository.get_token_session(session.token_session_id)
        sessions = repository.list_token_sessions(
            session.user_id,
            session.current_workspace_id,
        )
        transitioned_session = repository.revoke_token_session(
            session.token_session_id,
            revoked_at=revoked_at,
            reason_code="operator_revoked",
        )
        competing_session = repository.revoke_token_session(
            session.token_session_id,
            revoked_at="2026-07-12T04:31:00+00:00",
            reason_code="competing_different_reason",
        )

        self.assertEqual(found_authorization, authorization)
        self.assertEqual(found_authorization_by_id, authorization)
        self.assertEqual(found_session, session)
        self.assertEqual(sessions, [session])
        self.assertEqual(transitioned_session, revoked_session)
        self.assertIsNone(competing_session)
        (
            insert_authorization,
            get_authorization,
            get_authorization_by_id,
            insert_session,
            get_session,
            list_sessions,
            revoke,
            competing_revoke,
        ) = connection.statements
        self.assertEqual(
            " ".join(insert_authorization.sql.split()),
            "INSERT INTO formowl_oauth_client_authorizations "
            "(oauth_client_authorization_id, client_id, external_identity_id, user_id, "
            "granted_scopes, default_workspace_id, created_at, revoked_at) VALUES "
            "(%(oauth_client_authorization_id)s, %(client_id)s, "
            "%(external_identity_id)s, %(user_id)s, %(granted_scopes)s, "
            "%(default_workspace_id)s, %(created_at)s, %(revoked_at)s)",
        )
        self.assertEqual(
            insert_authorization.parameters,
            {**authorization.to_dict(), "revoked_at": None},
        )
        self.assertEqual(
            " ".join(get_authorization.sql.split()),
            "SELECT * FROM formowl_oauth_client_authorizations "
            "WHERE client_id = %(client_id)s "
            "AND external_identity_id = %(external_identity_id)s",
        )
        self.assertEqual(
            get_authorization.parameters,
            {
                "client_id": authorization.client_id,
                "external_identity_id": authorization.external_identity_id,
            },
        )
        self.assertNotIn("revoked_at IS NULL", get_authorization.sql)
        self.assertEqual(
            " ".join(get_authorization_by_id.sql.split()),
            "SELECT * FROM formowl_oauth_client_authorizations "
            "WHERE oauth_client_authorization_id = %(authorization_id)s",
        )
        self.assertEqual(
            get_authorization_by_id.parameters,
            {"authorization_id": authorization.oauth_client_authorization_id},
        )
        self.assertNotIn("revoked_at IS NULL", get_authorization_by_id.sql)
        self.assertEqual(
            " ".join(insert_session.sql.split()),
            "INSERT INTO formowl_oauth_token_sessions "
            "(token_session_id, user_id, external_identity_id, "
            "oauth_client_authorization_id, client_id, current_workspace_id, resource, "
            "scopes, token_jti_hash, issued_at, expires_at, revoked_at, "
            "revocation_reason) VALUES (%(token_session_id)s, %(user_id)s, "
            "%(external_identity_id)s, %(oauth_client_authorization_id)s, "
            "%(client_id)s, %(current_workspace_id)s, %(resource)s, %(scopes)s, "
            "%(token_jti_hash)s, %(issued_at)s, %(expires_at)s, %(revoked_at)s, "
            "%(revocation_reason)s)",
        )
        self.assertEqual(
            insert_session.parameters,
            {
                **session.to_dict(),
                "revoked_at": None,
                "revocation_reason": None,
            },
        )
        self.assertEqual(
            " ".join(get_session.sql.split()),
            "SELECT * FROM formowl_oauth_token_sessions "
            "WHERE token_session_id = %(token_session_id)s",
        )
        self.assertEqual(
            get_session.parameters,
            {"token_session_id": session.token_session_id},
        )
        self.assertNotIn("revoked_at IS NULL", get_session.sql)
        self.assertEqual(
            " ".join(list_sessions.sql.split()),
            "SELECT * FROM formowl_oauth_token_sessions "
            "WHERE user_id = %(user_id)s "
            "AND current_workspace_id = %(workspace_id)s "
            "ORDER BY issued_at DESC, token_session_id",
        )
        self.assertEqual(
            list_sessions.parameters,
            {
                "user_id": session.user_id,
                "workspace_id": session.current_workspace_id,
            },
        )
        self.assertNotIn("revoked_at IS NULL", list_sessions.sql)
        self.assertEqual(
            " ".join(revoke.sql.split()),
            "UPDATE formowl_oauth_token_sessions SET revoked_at = %(revoked_at)s, "
            "revocation_reason = %(reason_code)s WHERE token_session_id = "
            "%(token_session_id)s AND revoked_at IS NULL RETURNING *",
        )
        self.assertEqual(
            revoke.parameters,
            {
                "token_session_id": session.token_session_id,
                "revoked_at": revoked_at,
                "reason_code": "operator_revoked",
            },
        )
        self.assertEqual(competing_revoke.sql, revoke.sql)
        self.assertEqual(
            competing_revoke.parameters,
            {
                "token_session_id": session.token_session_id,
                "revoked_at": "2026-07-12T04:31:00+00:00",
                "reason_code": "competing_different_reason",
            },
        )
        self.assertEqual(
            connection.operation_kinds[-2:],
            ["query_one", "query_one"],
        )
        for statement in connection.statements:
            for value in statement.parameters.values():
                if isinstance(value, str):
                    self.assertNotIn(value, statement.sql)

    def test_token_session_reads_preserve_revoked_and_expired_rows_without_side_effects(
        self,
    ) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        issued_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        expires_at = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)
        revoked_at = datetime(2026, 7, 12, 4, 30, tzinfo=timezone.utc)
        evaluation_time = datetime(2026, 7, 12, 6, 0, tzinfo=timezone.utc)
        revocation_reason = "operator_revoked_compromised_session"
        expected_session = OAuthTokenSession(
            token_session_id="oauthsid_lifecycle_001",
            user_id="user_lifecycle_001",
            external_identity_id="extid_lifecycle_001",
            oauth_client_authorization_id="clientauth_lifecycle_001",
            client_id="chatgpt_client",
            current_workspace_id="workspace_lifecycle_001",
            resource="https://formowl.example.test/mcp",
            scopes=("formowl.use",),
            token_jti_hash=hash_oauth_value("token_jti", "lifecycle-token-jti"),
            issued_at=issued_at.isoformat(),
            expires_at=expires_at.isoformat(),
            revoked_at=revoked_at.isoformat(),
            revocation_reason=revocation_reason,
        )
        lifecycle_row = {
            **expected_session.to_dict(),
            "scopes": list(expected_session.scopes),
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revoked_at": revoked_at,
        }
        connection.query_one_results.append(dict(lifecycle_row))
        connection.query_all_results.append([dict(lifecycle_row)])
        hostile_session_id = "oauthsid_missing'; DROP TABLE formowl_oauth_token_sessions; --"
        hostile_user_id = "user_missing' OR '1'='1"
        hostile_workspace_id = "workspace_missing'; SELECT pg_sleep(9); --"

        found_session = repository.get_token_session(hostile_session_id)
        sessions = repository.list_token_sessions(
            hostile_user_id,
            hostile_workspace_id,
        )

        self.assertLess(expires_at, evaluation_time)
        self.assertEqual(found_session, expected_session)
        self.assertEqual(sessions, [expected_session])
        self.assertIsInstance(found_session, OAuthTokenSession)
        self.assertEqual(len(sessions), 1)
        expected_lifecycle = {
            "expires_at": expires_at.isoformat(),
            "revoked_at": revoked_at.isoformat(),
            "revocation_reason": revocation_reason,
        }

        def assert_lifecycle_payload(payload: dict[str, object]) -> None:
            self.assertEqual(
                {field: payload[field] for field in expected_lifecycle},
                expected_lifecycle,
            )

        assert_lifecycle_payload(found_session.to_dict())
        assert_lifecycle_payload(sessions[0].to_dict())
        for field in expected_lifecycle:
            with self.subTest(lifecycle_field_null=field):
                mutated = found_session.to_dict()
                mutated[field] = None
                with self.assertRaises(AssertionError):
                    assert_lifecycle_payload(mutated)
            with self.subTest(lifecycle_field_deleted=field):
                mutated = found_session.to_dict()
                del mutated[field]
                with self.assertRaises(KeyError):
                    assert_lifecycle_payload(mutated)

        self.assertEqual(connection.operation_kinds, ["query_one", "query_all"])
        self.assertEqual(
            (connection.begin_count, connection.commit_count, connection.rollback_count),
            (0, 0, 0),
        )
        self.assertEqual(len(connection.statements), 2)
        get_session, list_sessions = connection.statements
        self.assertEqual(
            " ".join(get_session.sql.split()),
            "SELECT * FROM formowl_oauth_token_sessions "
            "WHERE token_session_id = %(token_session_id)s",
        )
        self.assertEqual(
            get_session.parameters,
            {"token_session_id": hostile_session_id},
        )
        self.assertEqual(
            " ".join(list_sessions.sql.split()),
            "SELECT * FROM formowl_oauth_token_sessions "
            "WHERE user_id = %(user_id)s "
            "AND current_workspace_id = %(workspace_id)s "
            "ORDER BY issued_at DESC, token_session_id",
        )
        self.assertEqual(
            list_sessions.parameters,
            {
                "user_id": hostile_user_id,
                "workspace_id": hostile_workspace_id,
            },
        )
        for statement in connection.statements:
            self.assertTrue(statement.sql.startswith("SELECT "))
            self.assertNotIn("formowl_audit_log", statement.sql)
            self.assertNotIn("revoked_at IS NULL", statement.sql)
            self.assertNotIn("expires_at >", statement.sql)
            for value in statement.parameters.values():
                self.assertNotIn(value, statement.sql)

    def test_psycopg_adapter_uses_parameters_and_maps_rows(self) -> None:
        raw = FakeRawPsycopgConnection()
        adapter = PsycopgOAuthConnection(raw)  # type: ignore[arg-type]

        adapter.execute(SQLStatement(sql="UPDATE t SET value = %(value)s", parameters={"value": 1}))
        adapter.execute(
            SQLStatement(
                sql="INSERT INTO t (value) VALUES (%(metadata)s::jsonb)",
                parameters={"metadata": {"event_stage": "owner_bootstrap"}},
            )
        )
        adapter.execute(SQLStatement(sql="CREATE TABLE t (value integer)"))
        raw.next_rows = [{"value": 7}]
        one = adapter.query_one(
            SQLStatement(sql="SELECT %(value)s AS value", parameters={"value": 7})
        )
        all_rows = adapter.query_all(SQLStatement(sql="SELECT value FROM t"))
        adapter.begin()
        adapter.commit()
        adapter.rollback()
        adapter.close()

        self.assertEqual(raw.executions[0][1], {"value": 1})
        json_parameters = raw.executions[1][1]
        self.assertIsInstance(json_parameters["metadata"], Jsonb)
        self.assertEqual(
            json_parameters["metadata"].obj,
            {"event_stage": "owner_bootstrap"},
        )
        self.assertNotIn("owner_bootstrap", raw.executions[1][0])
        self.assertIsNone(raw.executions[2][1])
        self.assertEqual(raw.executions[3][1], {"value": 7})
        self.assertIsNone(raw.executions[4][1])
        self.assertEqual(raw.executions[5], ("BEGIN", None))
        self.assertEqual(one, {"value": 7})
        self.assertEqual(all_rows, [{"value": 7}])
        self.assertEqual(raw.commit_count, 1)
        self.assertEqual(raw.rollback_count, 1)
        self.assertEqual(raw.close_count, 1)

    def test_repository_keeps_untrusted_values_parameterized_and_uses_row_locks(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        malicious = "subject'; DROP TABLE formowl_users; --"

        repository.find_external_identity("https://accounts.google.com", malicious)
        identity_statement = connection.statements[-1]
        self.assertNotIn(malicious, identity_statement.sql)
        self.assertEqual(identity_statement.parameters["subject"], malicious)

        repository.get_transaction_by_state_hash("sha256:" + "a" * 64, for_update=True)
        self.assertTrue(connection.statements[-1].sql.endswith(" FOR UPDATE"))
        repository.get_authorization_code("sha256:" + "b" * 64, for_update=True)
        self.assertTrue(connection.statements[-1].sql.endswith(" FOR UPDATE"))
        repository.find_active_invitations(
            "person@example.test",
            now="2026-07-12T04:00:00+00:00",
            for_update=True,
        )
        self.assertTrue(connection.statements[-1].sql.endswith(" FOR UPDATE"))
        rendered_sql = "\n".join(statement.sql for statement in connection.statements)
        self.assertNotIn("person@example.test", rendered_sql)
        self.assertNotIn("sha256:" + "a" * 64, rendered_sql)

    def test_operator_directory_reads_are_parameterized_and_map_only_domain_records(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        created_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        expires_at = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)
        user_row = {
            "user_id": "user_operator_001",
            "display_name": "Operator Lookup User",
            "email": "operator@example.test",
            "status": "active",
            "created_at": created_at,
        }
        session_row = {
            "token_session_id": "oauthsid_operator_001",
            "user_id": "user_operator_001",
            "external_identity_id": "extid_operator_001",
            "oauth_client_authorization_id": "clientauth_operator_001",
            "client_id": "chatgpt_client",
            "current_workspace_id": "workspace_operator_001",
            "resource": "https://formowl.example.test/mcp",
            "scopes": ["formowl.use"],
            "token_jti_hash": "sha256:" + "e" * 64,
            "issued_at": created_at,
            "expires_at": expires_at,
            "revoked_at": None,
            "revocation_reason": None,
        }
        connection.query_all_results.extend(
            [
                [user_row],
                [
                    {
                        **user_row,
                        "member_workspace_id": "workspace_operator_001",
                        "member_user_id": "user_operator_001",
                        "member_role": "owner",
                    }
                ],
                [session_row],
            ]
        )

        users = repository.find_users_by_email("operator@example.test")
        workspace_users = repository.list_workspace_users("workspace_operator_001")
        sessions = repository.list_token_sessions(
            "user_operator_001",
            "workspace_operator_001",
        )

        expected_user = User.from_dict({**user_row, "created_at": created_at.isoformat()})
        self.assertEqual(users, [expected_user])
        self.assertEqual(workspace_users[0][0], expected_user)
        self.assertEqual(workspace_users[0][1].user_id, expected_user.user_id)
        self.assertEqual(workspace_users[0][1].workspace_id, "workspace_operator_001")
        self.assertEqual(workspace_users[0][1].role, "owner")
        self.assertEqual(
            sessions,
            [
                OAuthTokenSession.from_dict(
                    {
                        **session_row,
                        "issued_at": created_at.isoformat(),
                        "expires_at": expires_at.isoformat(),
                    }
                )
            ],
        )
        email_statement, workspace_statement, session_statement = connection.statements[-3:]
        self.assertEqual(
            email_statement.parameters,
            {"normalized_email": "operator@example.test"},
        )
        self.assertEqual(
            workspace_statement.parameters,
            {"workspace_id": "workspace_operator_001"},
        )
        self.assertEqual(
            session_statement.parameters,
            {
                "user_id": "user_operator_001",
                "workspace_id": "workspace_operator_001",
            },
        )
        rendered_sql = "\n".join(statement.sql for statement in connection.statements[-3:])
        for value in (
            "operator@example.test",
            "user_operator_001",
            "workspace_operator_001",
            "sha256:" + "e" * 64,
        ):
            self.assertNotIn(value, rendered_sql)

    def test_membership_lifecycle_queries_lock_rows_and_mutations_are_parameterized(
        self,
    ) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        member_row = {
            "workspace_id": "workspace_001",
            "user_id": "user_member_001",
            "role": "member",
        }
        connection.query_one_results.extend([member_row, member_row])
        connection.query_all_results.append(
            [
                member_row,
                {
                    "workspace_id": "workspace_001",
                    "user_id": "user_owner_001",
                    "role": "owner",
                },
            ]
        )

        active = repository.get_active_workspace_member(
            "user_member_001",
            "workspace_001",
            for_update=True,
        )
        removed = repository.get_removed_workspace_member(
            "user_member_001",
            "workspace_001",
            for_update=True,
        )
        members = repository.list_active_workspace_members_in_workspace(
            "workspace_001",
            for_update=True,
        )

        self.assertEqual(active, WorkspaceMember.from_dict(member_row))
        self.assertEqual(removed, WorkspaceMember.from_dict(member_row))
        self.assertEqual(
            [member.user_id for member in members], ["user_member_001", "user_owner_001"]
        )
        active_statement, removed_statement, list_statement = connection.statements[-3:]
        self.assertIn("removed_at IS NULL", active_statement.sql)
        self.assertTrue(active_statement.sql.endswith(" FOR UPDATE"))
        self.assertIn("removed_at IS NOT NULL", removed_statement.sql)
        self.assertTrue(removed_statement.sql.endswith(" FOR UPDATE"))
        self.assertIn("removed_at IS NULL", list_statement.sql)
        self.assertTrue(list_statement.sql.endswith(" FOR UPDATE"))
        self.assertEqual(
            active_statement.parameters,
            {"user_id": "user_member_001", "workspace_id": "workspace_001"},
        )
        self.assertEqual(removed_statement.parameters, active_statement.parameters)
        self.assertEqual(list_statement.parameters, {"workspace_id": "workspace_001"})

        hostile_user_id = "user'; DROP TABLE formowl_users; --"
        hostile_workspace_id = "workspace'; DROP TABLE formowl_workspace_members; --"
        removed_at = "2026-07-12T08:00:00+00:00"
        repository.remove_workspace_member(
            hostile_user_id,
            hostile_workspace_id,
            removed_at=removed_at,
        )
        repository.revoke_active_token_sessions_for_membership(
            hostile_user_id,
            hostile_workspace_id,
            revoked_at=removed_at,
            reason_code="workspace_membership_removed",
        )
        repository.restore_workspace_member(hostile_user_id, hostile_workspace_id)

        remove_statement, revoke_statement, restore_statement = connection.statements[-3:]
        self.assertIn("SET removed_at = %(removed_at)s", remove_statement.sql)
        self.assertIn("removed_at IS NULL", remove_statement.sql)
        self.assertEqual(
            remove_statement.parameters,
            {
                "user_id": hostile_user_id,
                "workspace_id": hostile_workspace_id,
                "removed_at": removed_at,
            },
        )
        self.assertIn("formowl_oauth_token_sessions", revoke_statement.sql)
        self.assertIn("current_workspace_id = %(workspace_id)s", revoke_statement.sql)
        self.assertIn("revoked_at IS NULL", revoke_statement.sql)
        self.assertEqual(
            revoke_statement.parameters,
            {
                "user_id": hostile_user_id,
                "workspace_id": hostile_workspace_id,
                "revoked_at": removed_at,
                "reason_code": "workspace_membership_removed",
            },
        )
        self.assertIn("SET removed_at = NULL", restore_statement.sql)
        self.assertIn("removed_at IS NOT NULL", restore_statement.sql)
        self.assertEqual(
            restore_statement.parameters,
            {"user_id": hostile_user_id, "workspace_id": hostile_workspace_id},
        )
        for statement in (remove_statement, revoke_statement, restore_statement):
            self.assertNotIn(hostile_user_id, statement.sql)
            self.assertNotIn(hostile_workspace_id, statement.sql)
            self.assertNotIn(removed_at, statement.sql)

    def test_fail_transaction_is_parameterized_and_only_consumes_pending_state(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        transaction_id = "oauthtx_001'; DROP TABLE formowl_oauth_transactions; --"
        failed_at = "2026-07-12T04:00:00+00:00"

        repository.fail_transaction(transaction_id, failed_at=failed_at)

        statement = connection.statements[-1]
        self.assertEqual(
            statement.parameters,
            {"transaction_id": transaction_id, "failed_at": failed_at},
        )
        self.assertNotIn(transaction_id, statement.sql)
        self.assertNotIn(failed_at, statement.sql)
        self.assertIn("SET status = 'failed'", statement.sql)
        self.assertIn("consumed_at = %(failed_at)s", statement.sql)
        self.assertIn("WHERE transaction_id = %(transaction_id)s", statement.sql)
        self.assertIn("status = 'pending'", statement.sql)
        self.assertIn("consumed_at IS NULL", statement.sql)

    def test_consume_authorization_code_is_single_use_bound_and_transactional(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        raw_code = "private-one-time-authorization-code"
        code_hash = hash_oauth_value("authorization_code", raw_code)
        consumed_at = "2026-07-12T04:00:00+00:00"
        binding = {
            "user_id": "user_001",
            "external_identity_id": "extid_001",
            "client_id": "chatgpt-client",
            "redirect_uri": "https://chatgpt.example.test/oauth/callback",
            "resource": "https://formowl.example.test/mcp",
        }
        connection.query_one_results.append({"code_hash": code_hash})

        with repository.transaction() as unit:
            repository.consume_authorization_code(
                code_hash,
                consumed_at=consumed_at,
                **binding,
            )
            unit.commit()

        statement = connection.statements[-1]
        self.assertIn("consumed_at IS NULL", statement.sql)
        self.assertIn("expires_at > %(consumed_at)s", statement.sql)
        self.assertIn("user_id = %(user_id)s", statement.sql)
        self.assertIn("external_identity_id = %(external_identity_id)s", statement.sql)
        self.assertIn("client_id = %(client_id)s", statement.sql)
        self.assertIn("redirect_uri = %(redirect_uri)s", statement.sql)
        self.assertIn("resource = %(resource)s", statement.sql)
        self.assertTrue(statement.sql.endswith("RETURNING code_hash"))
        self.assertEqual(
            statement.parameters,
            {"code_hash": code_hash, "consumed_at": consumed_at, **binding},
        )
        self.assertNotIn(raw_code, statement.sql + str(statement.parameters))
        self.assertFalse(any("formowl_audit_log" in item.sql for item in connection.statements))
        self.assertEqual((connection.begin_count, connection.commit_count), (1, 1))
        self.assertEqual(connection.rollback_count, 0)

        rejection_cases = (
            ("replay", consumed_at, {}),
            ("expired", "2026-07-12T06:00:00+00:00", {}),
            ("user_mismatch", consumed_at, {"user_id": "user_other"}),
            (
                "identity_mismatch",
                consumed_at,
                {"external_identity_id": "extid_other"},
            ),
            ("client_mismatch", consumed_at, {"client_id": "other-client"}),
            (
                "redirect_mismatch",
                consumed_at,
                {"redirect_uri": "https://chatgpt.example.test/oauth/other"},
            ),
            (
                "resource_mismatch",
                consumed_at,
                {"resource": "https://formowl.example.test/other"},
            ),
        )
        for name, attempted_at, overrides in rejection_cases:
            with self.subTest(name=name):
                connection.query_one_results.append(None)
                commit_before = connection.commit_count
                rollback_before = connection.rollback_count
                statement_count_before = len(connection.statements)
                attempted_binding = {**binding, **overrides}

                with self.assertRaises(OAuthAccessDenied) as caught:
                    with repository.transaction():
                        repository.consume_authorization_code(
                            code_hash,
                            consumed_at=attempted_at,
                            **attempted_binding,
                        )

                self.assertEqual(caught.exception.error, "invalid_grant")
                self.assertEqual(
                    caught.exception.reason_code,
                    "authorization_code_not_consumable",
                )
                self.assertEqual(connection.commit_count, commit_before)
                self.assertEqual(connection.rollback_count, rollback_before + 1)
                self.assertEqual(len(connection.statements), statement_count_before + 1)
                rejected_statement = connection.statements[-1]
                self.assertEqual(
                    rejected_statement.parameters,
                    {
                        "code_hash": code_hash,
                        "consumed_at": attempted_at,
                        **attempted_binding,
                    },
                )
                self.assertNotIn(
                    raw_code, rejected_statement.sql + str(rejected_statement.parameters)
                )
                self.assertFalse(
                    any("formowl_audit_log" in item.sql for item in connection.statements)
                )

    def test_get_client_authorization_uses_composite_key_and_returns_revoked_rows(
        self,
    ) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        created_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        revoked_at = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)
        client_id = "chatgpt_client"
        external_identity_id = "extid_001"
        expected = OAuthClientAuthorization(
            oauth_client_authorization_id="clientauth_revoked_001",
            client_id=client_id,
            external_identity_id=external_identity_id,
            user_id="user_001",
            granted_scopes=("formowl.use",),
            default_workspace_id="workspace_001",
            created_at=created_at.isoformat(),
            revoked_at=revoked_at.isoformat(),
        )
        connection.query_one_results.append(
            {
                **expected.to_dict(),
                "granted_scopes": list(expected.granted_scopes),
                "created_at": created_at,
                "revoked_at": revoked_at,
            }
        )

        found = repository.get_client_authorization(client_id, external_identity_id)

        self.assertEqual(found, expected)
        self.assertEqual(found.revoked_at, revoked_at.isoformat())
        found_statement = connection.statements[-1]
        normalized_sql = " ".join(found_statement.sql.split())
        self.assertIn(
            "WHERE client_id = %(client_id)s "
            "AND external_identity_id = %(external_identity_id)s",
            normalized_sql,
        )
        self.assertNotIn("revoked_at IS NULL", normalized_sql)
        self.assertEqual(
            found_statement.parameters,
            {
                "client_id": client_id,
                "external_identity_id": external_identity_id,
            },
        )
        self.assertNotIn(client_id, found_statement.sql)
        self.assertNotIn(external_identity_id, found_statement.sql)

        missing_client_id = "missing-client'; SELECT pg_sleep(1); --"
        missing_external_identity_id = "missing-extid'; SELECT pg_sleep(1); --"
        connection.query_one_results.append(None)

        self.assertIsNone(
            repository.get_client_authorization(
                missing_client_id,
                missing_external_identity_id,
            )
        )
        missing_statement = connection.statements[-1]
        self.assertEqual(
            missing_statement.parameters,
            {
                "client_id": missing_client_id,
                "external_identity_id": missing_external_identity_id,
            },
        )
        self.assertNotIn(missing_client_id, missing_statement.sql)
        self.assertNotIn(missing_external_identity_id, missing_statement.sql)
        self.assertEqual(len(connection.statements), 2)
        self.assertTrue(
            all(statement.sql.lstrip().startswith("SELECT ") for statement in connection.statements)
        )
        self.assertFalse(
            any("formowl_audit_log" in statement.sql for statement in connection.statements)
        )
        self.assertEqual(
            (connection.begin_count, connection.commit_count, connection.rollback_count),
            (0, 0, 0),
        )

    def test_get_client_authorization_by_id_is_parameterized_and_returns_revoked_rows(
        self,
    ) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        created_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        revoked_at = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)
        authorization_id = "clientauth_revoked_001"
        expected = OAuthClientAuthorization(
            oauth_client_authorization_id=authorization_id,
            client_id="chatgpt_client",
            external_identity_id="extid_001",
            user_id="user_001",
            granted_scopes=("formowl.use",),
            default_workspace_id="workspace_001",
            created_at=created_at.isoformat(),
            revoked_at=revoked_at.isoformat(),
        )
        connection.query_one_results.append(
            {
                **expected.to_dict(),
                "granted_scopes": list(expected.granted_scopes),
                "created_at": created_at,
                "revoked_at": revoked_at,
            }
        )

        found = repository.get_client_authorization_by_id(authorization_id)

        self.assertEqual(found, expected)
        self.assertEqual(found.revoked_at, revoked_at.isoformat())
        found_statement = connection.statements[-1]
        self.assertEqual(
            " ".join(found_statement.sql.split()),
            "SELECT * FROM formowl_oauth_client_authorizations "
            "WHERE oauth_client_authorization_id = %(authorization_id)s",
        )
        self.assertNotIn("revoked_at IS NULL", found_statement.sql)
        self.assertEqual(
            found_statement.parameters,
            {"authorization_id": authorization_id},
        )
        self.assertNotIn(authorization_id, found_statement.sql)

        missing_authorization_id = "missing-auth'; SELECT pg_sleep(1); --"
        connection.query_one_results.append(None)

        self.assertIsNone(repository.get_client_authorization_by_id(missing_authorization_id))
        missing_statement = connection.statements[-1]
        self.assertEqual(
            missing_statement.parameters,
            {"authorization_id": missing_authorization_id},
        )
        self.assertNotIn(missing_authorization_id, missing_statement.sql)
        self.assertEqual(len(connection.statements), 2)
        self.assertTrue(
            all(statement.sql.lstrip().startswith("SELECT ") for statement in connection.statements)
        )
        self.assertFalse(
            any("formowl_audit_log" in statement.sql for statement in connection.statements)
        )
        self.assertEqual(
            (connection.begin_count, connection.commit_count, connection.rollback_count),
            (0, 0, 0),
        )

    def test_insert_authorization_code_persists_only_hash_and_rolls_back_on_failure(
        self,
    ) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        raw_code = "private-raw-authorization-code"
        redirect_uri = "https://chatgpt.example.test/oauth/callback?value=';DROP_TABLE--"
        code = OAuthAuthorizationCode(
            code_hash=hash_oauth_value("authorization_code", raw_code),
            transaction_id="oauthtx_001",
            user_id="user_001",
            external_identity_id="extid_001",
            client_id="chatgpt_client",
            redirect_uri=redirect_uri,
            resource="https://formowl.example.test/mcp",
            scopes=("formowl.use",),
            code_challenge="A" * 43,
            created_at="2026-07-12T04:00:00+00:00",
            expires_at="2026-07-12T04:05:00+00:00",
        )

        repository.insert_authorization_code(code)

        self.assertEqual(len(connection.statements), 1)
        statement = connection.statements[0]
        normalized_sql = " ".join(statement.sql.split())
        self.assertEqual(
            normalized_sql,
            "INSERT INTO formowl_oauth_authorization_codes "
            "(code_hash, transaction_id, user_id, external_identity_id, client_id, "
            "redirect_uri, resource, scopes, code_challenge, created_at, expires_at, "
            "consumed_at) VALUES (%(code_hash)s, %(transaction_id)s, %(user_id)s, "
            "%(external_identity_id)s, %(client_id)s, %(redirect_uri)s, %(resource)s, "
            "%(scopes)s, %(code_challenge)s, %(created_at)s, %(expires_at)s, "
            "%(consumed_at)s)",
        )
        expected_parameters = {**code.to_dict(), "consumed_at": None}
        self.assertEqual(statement.parameters, expected_parameters)
        self.assertEqual(statement.parameters["code_hash"], code.code_hash)
        self.assertIsNone(statement.parameters["consumed_at"])
        self.assertNotIn("raw_code", statement.parameters)
        self.assertNotIn(raw_code, statement.sql + str(statement.parameters))
        self.assertNotIn(redirect_uri, statement.sql)
        for field in (
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
        ):
            with self.subTest(field=field):
                self.assertEqual(statement.parameters[field], expected_parameters[field])

        failing_connection = RecordingConnection()
        failing_repository = PostgreSQLOAuthRepository(failing_connection)

        def fail_insert(failing_statement: SQLStatement) -> None:
            failing_connection.statements.append(failing_statement)
            raise RuntimeError("database detail must remain internal")

        with patch.object(failing_connection, "execute", side_effect=fail_insert):
            with self.assertRaises(RuntimeError):
                with failing_repository.transaction() as unit:
                    failing_repository.insert_authorization_code(code)
                    unit.commit()

        self.assertEqual(
            (
                failing_connection.begin_count,
                failing_connection.commit_count,
                failing_connection.rollback_count,
            ),
            (1, 0, 1),
        )
        self.assertEqual(len(failing_connection.statements), 1)
        failed_sql = failing_connection.statements[0].sql
        self.assertIn("formowl_oauth_authorization_codes", failed_sql)
        self.assertNotIn("formowl_oauth_token_sessions", failed_sql)
        self.assertNotIn("formowl_audit_log", failed_sql)
        self.assertNotIn(raw_code, failed_sql + str(failing_connection.statements[0].parameters))

    def test_insert_client_authorization_preserves_bindings_and_rolls_back_unique_failure(
        self,
    ) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        authorization = OAuthClientAuthorization(
            oauth_client_authorization_id="clientauth_001",
            client_id="chatgpt_client",
            external_identity_id="extid_001",
            user_id="user_001",
            granted_scopes=("formowl.use",),
            default_workspace_id="workspace_001",
            created_at="2026-07-12T04:00:00+00:00",
        )

        repository.insert_client_authorization(authorization)

        statement = connection.statements[-1]
        self.assertEqual(
            " ".join(statement.sql.split()),
            "INSERT INTO formowl_oauth_client_authorizations "
            "(oauth_client_authorization_id, client_id, external_identity_id, user_id, "
            "granted_scopes, default_workspace_id, created_at, revoked_at) VALUES "
            "(%(oauth_client_authorization_id)s, %(client_id)s, "
            "%(external_identity_id)s, %(user_id)s, %(granted_scopes)s, "
            "%(default_workspace_id)s, %(created_at)s, %(revoked_at)s)",
        )
        expected_parameters = {**authorization.to_dict(), "revoked_at": None}
        self.assertEqual(statement.parameters, expected_parameters)
        self.assertIsNone(statement.parameters["revoked_at"])
        for field in (
            "oauth_client_authorization_id",
            "client_id",
            "external_identity_id",
            "user_id",
            "granted_scopes",
            "default_workspace_id",
            "created_at",
        ):
            with self.subTest(field=field):
                self.assertEqual(statement.parameters[field], expected_parameters[field])
                self.assertNotIn(str(expected_parameters[field]), statement.sql)

        revoked_at = "2026-07-12T05:00:00+00:00"
        revoked_authorization = OAuthClientAuthorization(
            oauth_client_authorization_id="clientauth_revoked_002",
            client_id="other_client",
            external_identity_id="extid_002",
            user_id="user_002",
            granted_scopes=("formowl.use",),
            default_workspace_id="workspace_002",
            created_at="2026-07-12T04:30:00+00:00",
            revoked_at=revoked_at,
        )

        repository.insert_client_authorization(revoked_authorization)

        self.assertEqual(connection.statements[-1].parameters["revoked_at"], revoked_at)

        hostile_payload = {
            **authorization.to_dict(),
            "oauth_client_authorization_id": "clientauth'; DROP TABLE authorizations; --",
            "client_id": "client'; SELECT pg_sleep(1); --",
            "external_identity_id": "extid'; DROP TABLE identities; --",
            "user_id": "user'; DROP TABLE users; --",
            "default_workspace_id": "workspace'; DROP TABLE workspaces; --",
        }
        hostile_authorization = Mock()
        hostile_authorization.to_dict.return_value = hostile_payload
        hostile_connection = RecordingConnection()

        PostgreSQLOAuthRepository(hostile_connection).insert_client_authorization(
            hostile_authorization
        )

        hostile_statement = hostile_connection.statements[-1]
        self.assertEqual(
            hostile_statement.parameters,
            {**hostile_payload, "revoked_at": None},
        )
        for value in hostile_payload.values():
            if isinstance(value, str):
                self.assertNotIn(value, hostile_statement.sql)

        failing_connection = RecordingConnection()
        failing_repository = PostgreSQLOAuthRepository(failing_connection)

        def fail_unique(failing_statement: SQLStatement) -> None:
            failing_connection.statements.append(failing_statement)
            raise psycopg.errors.UniqueViolation("duplicate client and external identity")

        with patch.object(failing_connection, "execute", side_effect=fail_unique):
            with self.assertRaises(psycopg.errors.UniqueViolation):
                with failing_repository.transaction() as unit:
                    failing_repository.insert_client_authorization(authorization)
                    unit.commit()

        self.assertEqual(
            (
                failing_connection.begin_count,
                failing_connection.commit_count,
                failing_connection.rollback_count,
            ),
            (1, 0, 1),
        )
        self.assertEqual(len(failing_connection.statements), 1)
        failed_sql = failing_connection.statements[0].sql
        self.assertIn("formowl_oauth_client_authorizations", failed_sql)
        self.assertNotIn("formowl_external_identities", failed_sql)
        self.assertNotIn("formowl_oauth_token_sessions", failed_sql)
        self.assertNotIn("formowl_audit_log", failed_sql)
        migration_sql = " ".join(oauth_migration_path().read_text(encoding="utf-8").split())
        self.assertIn("UNIQUE (client_id, external_identity_id)", migration_sql)
        self.assertIn(
            "CONSTRAINT uq_formowl_external_identity_user "
            "UNIQUE (external_identity_id, user_id)",
            migration_sql,
        )
        self.assertIn(
            "CONSTRAINT fk_formowl_client_authorization_identity_user "
            "FOREIGN KEY (external_identity_id, user_id)",
            migration_sql,
        )

    def test_owner_bootstrap_sql_uses_unique_upsert_row_locks_and_parameters(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        now = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        later = datetime(2026, 7, 12, 5, 0, tzinfo=timezone.utc)
        bootstrap = OAuthOwnerBootstrap(
            workspace_id="workspace_001",
            normalized_email="person@example.test",
            idempotency_key_hash=hash_oauth_value(
                "owner_bootstrap_idempotency",
                "private-key",
            ),
            invitation_id="invite_bootstrap_001",
            operator_service_id="operator_service_001",
            status="pending",
            created_at=now.isoformat(),
        )
        connection.query_one_results.append({"workspace_id": "workspace_001"})

        self.assertTrue(repository.upsert_owner_bootstrap(bootstrap))

        upsert = connection.statements[-1]
        self.assertIn("ON CONFLICT (workspace_id) DO NOTHING", upsert.sql)
        self.assertIn("RETURNING workspace_id", upsert.sql)
        self.assertEqual(upsert.parameters["workspace_id"], "workspace_001")
        self.assertEqual(
            upsert.parameters["idempotency_key_hash"],
            bootstrap.idempotency_key_hash,
        )
        self.assertNotIn("private-key", upsert.sql + str(upsert.parameters))
        connection.query_one_results.append(None)
        self.assertFalse(repository.upsert_owner_bootstrap(bootstrap))

        bootstrap_row = {
            **bootstrap.to_dict(),
            "created_at": now,
            "completed_at": None,
        }
        connection.query_one_results.append(bootstrap_row)
        self.assertEqual(
            repository.get_owner_bootstrap("workspace_001", for_update=True),
            bootstrap,
        )
        self.assertTrue(connection.statements[-1].sql.endswith(" FOR UPDATE"))

        connection.query_one_results.append(bootstrap_row)
        self.assertEqual(
            repository.get_owner_bootstrap_by_invitation(
                "invite_bootstrap_001",
                for_update=True,
            ),
            bootstrap,
        )
        self.assertTrue(connection.statements[-1].sql.endswith(" FOR UPDATE"))

        connection.query_one_results.append({"member_count": 0})
        self.assertEqual(repository.count_active_workspace_members("workspace_001"), 0)
        self.assertEqual(
            connection.statements[-1].parameters,
            {"workspace_id": "workspace_001"},
        )

        invitation = OAuthInvitation(
            invitation_id="invite_bootstrap_001",
            normalized_email="person@example.test",
            workspace_id="workspace_001",
            role="owner",
            status="pending",
            expires_at=later.isoformat(),
            created_at=now.isoformat(),
        )
        invitation_row = {
            **invitation.to_dict(),
            "expires_at": later,
            "created_at": now,
        }
        connection.query_one_results.append(invitation_row)
        self.assertEqual(repository.get_invitation(invitation.invitation_id), invitation)

        connection.query_all_results.append([invitation_row])
        self.assertEqual(
            repository.find_pending_owner_invitations(
                "workspace_001",
                now=now.isoformat(),
                for_update=True,
            ),
            [invitation],
        )
        pending = connection.statements[-1]
        self.assertTrue(pending.sql.endswith(" FOR UPDATE"))
        self.assertEqual(
            pending.parameters,
            {"workspace_id": "workspace_001", "now": now.isoformat()},
        )

        repository.complete_owner_bootstrap(
            "invite_bootstrap_001",
            completed_at=now.isoformat(),
        )
        completed = connection.statements[-1]
        self.assertIn("status = 'completed'", completed.sql)
        self.assertIn("status = 'pending'", completed.sql)
        self.assertEqual(
            completed.parameters,
            {
                "invitation_id": "invite_bootstrap_001",
                "completed_at": now.isoformat(),
            },
        )

        service_audit = AuditLog(
            audit_log_id="audit_bootstrap_001",
            actor_user_id=None,
            actor_type="service",
            actor_service_id="operator_service_001",
            action="oauth_owner_bootstrap_created",
            target_type="oauth_owner_bootstrap",
            target_id="invite_bootstrap_001",
            session_id="invite_bootstrap_001",
            workspace_id="workspace_001",
            status="ok",
            reason_code="owner_bootstrap_created",
            timestamp=now.isoformat(),
            metadata={"event_stage": "owner_bootstrap"},
        )
        repository.append_audit_log(service_audit)
        audit_statement = connection.statements[-1]
        self.assertIn("actor_service_id", audit_statement.sql)
        self.assertEqual(
            audit_statement.parameters["actor_service_id"],
            "operator_service_001",
        )

    def test_repository_maps_timestamps_and_writes_audit_metadata_as_a_parameter(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        now = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
        connection.query_one_results.append(
            {
                "external_identity_id": "extid_001",
                "provider": "google",
                "issuer": "https://accounts.google.com",
                "subject": "google-subject-001",
                "user_id": "user_001",
                "email": "person@example.test",
                "email_verified": True,
                "status": "active",
                "created_at": now,
                "last_authenticated_at": now,
            }
        )

        identity = repository.get_external_identity("extid_001")
        self.assertIsInstance(identity, ExternalIdentity)
        self.assertEqual(identity.created_at, now.isoformat())

        audit = AuditLog(
            audit_log_id="audit_001",
            actor_user_id=None,
            actor_type="external_unauthenticated",
            action="oauth_authorization_rejected",
            target_type="oauth_request",
            target_id="oauthdeny_001",
            session_id="oauthdeny_001",
            timestamp=now.isoformat(),
            status="permission_denied",
            oauth_client_id="chatgpt-client",
            reason_code="oauth_parameter_duplicated",
            metadata={"event_stage": "authorization"},
        )
        repository.append_audit_log(audit)
        statement = connection.statements[-1]
        self.assertIn("%(metadata)s::jsonb", statement.sql)
        self.assertEqual(statement.parameters["metadata"], {"event_stage": "authorization"})
        self.assertNotIn("oauth_parameter_duplicated", statement.sql)

        trusted_denial = AuditLog(
            audit_log_id="audit_mcp_expired_001",
            actor_user_id="user_001",
            actor_type="user",
            action="mcp_http_authentication_denied",
            target_type="mcp_resource",
            target_id="mcp",
            session_id="oauthsid_001",
            workspace_id="workspace_001",
            status="permission_denied",
            external_identity_id="extid_001",
            oauth_client_id="chatgpt-client",
            oauth_token_session_id="oauthsid_001",
            request_id="mcp_req_expired_001",
            reason_code="token_expired",
            timestamp=now.isoformat(),
            metadata={
                "event_stage": "mcp_http_authentication",
                "lineage_source": "verified_token_session",
            },
        )
        repository.append_audit_log(trusted_denial)
        trusted_statement = connection.statements[-1]
        self.assertEqual(trusted_statement.parameters["actor_user_id"], "user_001")
        self.assertEqual(trusted_statement.parameters["workspace_id"], "workspace_001")
        self.assertEqual(trusted_statement.parameters["external_identity_id"], "extid_001")
        self.assertEqual(trusted_statement.parameters["oauth_client_id"], "chatgpt-client")
        self.assertEqual(
            trusted_statement.parameters["oauth_token_session_id"],
            "oauthsid_001",
        )
        self.assertEqual(
            trusted_statement.parameters["request_id"],
            "mcp_req_expired_001",
        )
        self.assertNotIn("access_token", str(trusted_statement.parameters))

    def test_transaction_commit_and_rollback_are_explicit(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        user = User(
            user_id="user_001",
            display_name="Safe User",
            email="person@example.test",
            status="active",
            created_at="2026-07-12T04:00:00+00:00",
        )

        with repository.transaction() as unit:
            repository.insert_user(user)
            unit.commit()
        self.assertEqual((connection.begin_count, connection.commit_count), (1, 1))
        self.assertEqual(connection.rollback_count, 0)

        with self.assertRaises(RuntimeError):
            with repository.transaction():
                repository.insert_user(user)
                raise RuntimeError("injected write failure")
        self.assertEqual(connection.begin_count, 2)
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 1)

    def test_apply_migrations_rolls_back_partial_state_on_failure(self) -> None:
        connection = FailingMigrationConnection()
        repository = PostgreSQLOAuthRepository(connection)

        with self.assertRaises(RuntimeError) as caught:
            repository.apply_migrations()

        self.assertEqual(str(caught.exception), "migration_apply_failed")
        self.assertEqual(connection.begin_count, 1)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(connection.commit_count, 0)
        self.assertIn("migration_advisory_lock", connection.rolled_back_effects)
        self.assertIn("migration_ledger_or_schema", connection.rolled_back_effects)
        self.assertTrue(
            any(effect.startswith("migration:") for effect in connection.rolled_back_effects)
        )
        self.assertEqual(connection.pending_effects, [])
        self.assertEqual(connection.durable_effects, ["preexisting_durable_state"])
        for forbidden in ("postgresql://", "CREATE ", "ALTER ", "/private/"):
            self.assertNotIn(forbidden, str(caught.exception))

    def test_health_migration_and_migration_path_cover_oauth_schema(self) -> None:
        connection = RecordingConnection()
        repository = PostgreSQLOAuthRepository(connection)
        connection.query_one_results.append({"healthy": 1})
        self.assertTrue(repository.health_check())
        connection.fail_queries = True
        self.assertFalse(repository.health_check())
        connection.fail_queries = False

        applied = repository.apply_migrations()
        self.assertGreater(applied.applied_statement_count, 0)
        self.assertEqual(applied.latest_migration_version, 5)
        self.assertEqual(applied.skipped_migration_ids, ())
        self.assertEqual(connection.begin_count, 1)
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        migration_sql = oauth_migration_path().read_text(encoding="utf-8")
        self.assertIn("formowl_external_identities", migration_sql)
        self.assertIn("formowl_oauth_token_sessions", migration_sql)
        self.assertIn("formowl_oauth_owner_bootstraps", migration_sql)
        self.assertIn("actor_service_id", migration_sql)
        self.assertIn("chk_formowl_audit_actor_identity", migration_sql)
        self.assertIn("formowl_audit_log", migration_sql)
        self.assertTrue(
            any(migration.filename == "005_oauth_identity.sql" for migration in migration_files())
        )
        replayed_sql = "\n".join(statement.sql for statement in connection.statements)
        self.assertIn("formowl_external_identities", replayed_sql)

    def test_connect_factory_owns_connection_and_returns_safe_failure(self) -> None:
        raw = FakeRawPsycopgConnection()
        with patch("formowl_auth.postgres.psycopg.connect", return_value=raw) as connect:
            repository = PostgreSQLOAuthRepository.connect(
                "postgresql://user:secret@example.test/formowl",
                connect_timeout_seconds=7,
            )
            repository.close()

        connect.assert_called_once_with(
            "postgresql://user:secret@example.test/formowl",
            connect_timeout=7,
            application_name="formowl-oauth",
            autocommit=True,
            row_factory=connect.call_args.kwargs["row_factory"],
        )
        self.assertEqual(raw.close_count, 1)

        with patch(
            "formowl_auth.postgres.psycopg.connect",
            side_effect=psycopg.OperationalError(
                "postgresql://user:secret@example.test/formowl is unavailable"
            ),
        ):
            with self.assertRaises(RuntimeError) as caught:
                PostgreSQLOAuthRepository.connect("postgresql://user:secret@example.test/formowl")
        self.assertEqual(str(caught.exception), "oauth_database_unavailable")
        self.assertNotIn("secret", str(caught.exception))

        for dsn, timeout in (("", 10), ("postgresql://example.test/formowl", 0)):
            with self.subTest(dsn=dsn, timeout=timeout):
                with self.assertRaises(ValueError):
                    PostgreSQLOAuthRepository.connect(
                        dsn,
                        connect_timeout_seconds=timeout,
                    )


if __name__ == "__main__":
    unittest.main()
