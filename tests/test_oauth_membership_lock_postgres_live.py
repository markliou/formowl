from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from threading import Event
import time
from unittest.mock import patch
import unittest
from uuid import uuid4

from cryptography.fernet import Fernet
import psycopg

import _paths  # noqa: F401
from formowl_auth import (
    ExternalIdentity,
    FormOwlOAuthBridge,
    FormOwlSigningKeySet,
    FormOwlTokenCodec,
    OAuthAuthorizationCode,
    OAuthBridgeConfig,
    OAuthClientAuthorization,
    OAuthTransaction,
)
from formowl_auth.models import OAuthAccessDenied
from formowl_auth.postgres import PostgreSQLOAuthRepository
from formowl_auth.security import hash_oauth_value, pkce_s256_challenge
from formowl_contract import User, WorkspaceMember
from formowl_gateway.operator import OperatorDirectory
from formowl_graph.storage import PostgresMigration, PostgreSQLMigrationRunner, SQLStatement
from oauth_harness import DeterministicRng, generate_ephemeral_formowl_signing_key


_DSN_ENV = "FORMOWL_OAUTH_MEMBERSHIP_LOCK_POSTGRES_DSN"
_VERIFIER = "v" * 43


@unittest.skipUnless(os.environ.get(_DSN_ENV), f"{_DSN_ENV} is required")
class OAuthMembershipLockPostgresLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dsn = os.environ[_DSN_ENV]
        repository = PostgreSQLOAuthRepository.connect(cls.dsn)
        root = Path(__file__).resolve().parents[1]
        migrations = (
            PostgresMigration.from_file(
                root / "python/formowl_graph/storage/migrations/001_metadata_store.sql"
            ),
            PostgresMigration.from_file(
                root / "python/formowl_graph/storage/migrations/005_oauth_identity.sql"
            ),
        )
        try:
            with repository.transaction() as unit:
                PostgreSQLMigrationRunner(repository.connection).migration_replay(migrations)
                unit.commit()
        finally:
            repository.close()

    def test_exchange_first_is_revoked_before_membership_removal_commits(self) -> None:
        state = self._seed_exchange_state("exchange_first")
        exchange_repository = PostgreSQLOAuthRepository.connect(self.dsn)
        removal_repository = PostgreSQLOAuthRepository.connect(self.dsn)
        bridge = self._bridge(exchange_repository, state)
        membership_locked = Event()
        release_exchange = Event()
        original_get_membership = exchange_repository.get_active_workspace_member
        removal_pid = self._backend_pid(removal_repository)

        def hold_exchange_membership_lock(
            user_id: str,
            workspace_id: str,
            *,
            for_update: bool = False,
        ):
            membership = original_get_membership(
                user_id,
                workspace_id,
                for_update=for_update,
            )
            if not for_update:
                raise AssertionError("token exchange did not request the membership row lock")
            membership_locked.set()
            if not release_exchange.wait(timeout=5):
                raise AssertionError("membership-lock exchange release was not signaled")
            return membership

        directory = OperatorDirectory(
            repository=removal_repository,
            expected_operator_service_id="operator_service_001",
        )
        try:
            with (
                patch.object(
                    exchange_repository,
                    "get_active_workspace_member",
                    side_effect=hold_exchange_membership_lock,
                ),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                exchange_future = executor.submit(
                    bridge.exchange_authorization_code,
                    self._token_request(state),
                    now=state["now"],
                )
                self.assertTrue(membership_locked.wait(timeout=5))
                removal_future = executor.submit(
                    directory.remove_workspace_member,
                    user_id=state["member_user_id"],
                    workspace_id=state["workspace_id"],
                    operator_service_id="operator_service_001",
                    now=state["now"] + timedelta(minutes=1),
                )
                self._wait_until_blocked(removal_pid)
                self.assertFalse(removal_future.done())
                release_exchange.set()
                token = exchange_future.result(timeout=5)
                removed = removal_future.result(timeout=5)

            self.assertTrue(removed["membership_removed"])
            sessions = removal_repository.list_token_sessions(
                state["member_user_id"],
                state["workspace_id"],
            )
            self.assertEqual(len(sessions), 1)
            self.assertIsNotNone(sessions[0].revoked_at)
            self.assertEqual(
                sessions[0].revocation_reason,
                "workspace_membership_removed",
            )
            directory.restore_workspace_member(
                user_id=state["member_user_id"],
                workspace_id=state["workspace_id"],
                operator_service_id="operator_service_001",
                now=state["now"] + timedelta(minutes=2),
            )
            with self.assertRaises(OAuthAccessDenied) as caught:
                bridge.authenticate_access_token(
                    str(token["access_token"]),
                    required_scope="formowl.use",
                    resource=state["resource"],
                    now=state["now"] + timedelta(minutes=2),
                )
            self.assertEqual(caught.exception.reason_code, "token_session_revoked")
        finally:
            release_exchange.set()
            exchange_repository.close()
            removal_repository.close()
            self._cleanup(state)

    def test_removal_first_denies_exchange_without_session_or_code_consumption(self) -> None:
        state = self._seed_exchange_state("removal_first")
        exchange_repository = PostgreSQLOAuthRepository.connect(self.dsn)
        removal_repository = PostgreSQLOAuthRepository.connect(self.dsn)
        bridge = self._bridge(exchange_repository, state)
        membership_locked = Event()
        release_removal = Event()
        original_list_members = removal_repository.list_active_workspace_members_in_workspace
        exchange_pid = self._backend_pid(exchange_repository)

        def hold_removal_membership_lock(
            workspace_id: str,
            *,
            for_update: bool = False,
        ):
            members = original_list_members(
                workspace_id,
                for_update=for_update,
            )
            if not for_update:
                raise AssertionError("membership removal did not request membership row locks")
            membership_locked.set()
            if not release_removal.wait(timeout=5):
                raise AssertionError("membership-lock removal release was not signaled")
            return members

        directory = OperatorDirectory(
            repository=removal_repository,
            expected_operator_service_id="operator_service_001",
        )
        try:
            with (
                patch.object(
                    removal_repository,
                    "list_active_workspace_members_in_workspace",
                    side_effect=hold_removal_membership_lock,
                ),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                removal_future = executor.submit(
                    directory.remove_workspace_member,
                    user_id=state["member_user_id"],
                    workspace_id=state["workspace_id"],
                    operator_service_id="operator_service_001",
                    now=state["now"] + timedelta(minutes=1),
                )
                self.assertTrue(membership_locked.wait(timeout=5))
                exchange_future = executor.submit(
                    bridge.exchange_authorization_code,
                    self._token_request(state),
                    now=state["now"],
                )
                self._wait_until_blocked(exchange_pid)
                self.assertFalse(exchange_future.done())
                release_removal.set()
                removed = removal_future.result(timeout=5)
                with self.assertRaises(OAuthAccessDenied) as caught:
                    exchange_future.result(timeout=5)

            self.assertTrue(removed["membership_removed"])
            self.assertEqual(
                caught.exception.reason_code,
                "workspace_membership_inactive",
            )
            self.assertEqual(
                exchange_repository.list_token_sessions(
                    state["member_user_id"],
                    state["workspace_id"],
                ),
                [],
            )
            stored_code = exchange_repository.get_authorization_code(state["code_hash"])
            self.assertIsNotNone(stored_code)
            self.assertIsNone(stored_code.consumed_at)
            directory.restore_workspace_member(
                user_id=state["member_user_id"],
                workspace_id=state["workspace_id"],
                operator_service_id="operator_service_001",
                now=state["now"] + timedelta(minutes=2),
            )
            self.assertEqual(
                exchange_repository.list_token_sessions(
                    state["member_user_id"],
                    state["workspace_id"],
                ),
                [],
            )
        finally:
            release_removal.set()
            exchange_repository.close()
            removal_repository.close()
            self._cleanup(state)

    def _seed_exchange_state(self, label: str) -> dict[str, object]:
        suffix = uuid4().hex
        now = datetime(2026, 7, 14, 4, 0, tzinfo=timezone.utc)
        workspace_id = f"workspace_lock_{label}_{suffix}"
        owner_user_id = f"user_lock_owner_{label}_{suffix}"
        member_user_id = f"user_lock_member_{label}_{suffix}"
        external_identity_id = f"extid_lock_{label}_{suffix}"
        client_id = f"chatgpt_lock_{label}_{suffix}"
        authorization_id = f"clientauth_lock_{label}_{suffix}"
        transaction_id = f"oauthtx_lock_{label}_{suffix}"
        raw_code = f"code-{label}-{suffix}"
        code_hash = hash_oauth_value("authorization_code", raw_code)
        resource = "https://auth.example.test/mcp"
        redirect_uri = "https://chatgpt.com/connector/oauth/membership-lock-live"
        repository = PostgreSQLOAuthRepository.connect(self.dsn)
        try:
            with repository.transaction() as unit:
                repository.insert_user(
                    User(
                        user_id=owner_user_id,
                        display_name="Membership Lock Owner",
                        email=f"membership-lock-owner-{suffix}@example.test",
                        status="active",
                        created_at=now.isoformat(),
                    )
                )
                repository.insert_user(
                    User(
                        user_id=member_user_id,
                        display_name="Membership Lock Member",
                        email=f"membership-lock-member-{suffix}@example.test",
                        status="active",
                        created_at=now.isoformat(),
                    )
                )
                repository.insert_workspace_member(
                    WorkspaceMember(
                        workspace_id=workspace_id,
                        user_id=owner_user_id,
                        role="owner",
                    ),
                    created_at=now.isoformat(),
                )
                repository.insert_workspace_member(
                    WorkspaceMember(
                        workspace_id=workspace_id,
                        user_id=member_user_id,
                        role="member",
                    ),
                    created_at=now.isoformat(),
                )
                repository.insert_external_identity(
                    ExternalIdentity(
                        external_identity_id=external_identity_id,
                        provider="google",
                        issuer="https://accounts.google.com",
                        subject=f"google-lock-{label}-{suffix}",
                        user_id=member_user_id,
                        email=f"membership-lock-{label}@example.test",
                        email_verified=True,
                        status="active",
                        created_at=now.isoformat(),
                        last_authenticated_at=now.isoformat(),
                    )
                )
                repository.insert_client_authorization(
                    OAuthClientAuthorization(
                        oauth_client_authorization_id=authorization_id,
                        client_id=client_id,
                        external_identity_id=external_identity_id,
                        user_id=member_user_id,
                        granted_scopes=("formowl.use",),
                        default_workspace_id=workspace_id,
                        created_at=now.isoformat(),
                    )
                )
                repository.insert_transaction(
                    OAuthTransaction(
                        transaction_id=transaction_id,
                        google_state_hash=hash_oauth_value(
                            "google_state",
                            f"state-{label}-{suffix}",
                        ),
                        encrypted_client_state=f"encrypted-{label}-{suffix}",
                        google_nonce_hash=hash_oauth_value(
                            "google_nonce",
                            f"nonce-{label}-{suffix}",
                        ),
                        client_id=client_id,
                        redirect_uri=redirect_uri,
                        resource=resource,
                        scopes=("formowl.use",),
                        code_challenge=pkce_s256_challenge(_VERIFIER),
                        code_challenge_method="S256",
                        created_at=now.isoformat(),
                        expires_at=(now + timedelta(minutes=10)).isoformat(),
                        status="consumed",
                        consumed_at=now.isoformat(),
                    )
                )
                repository.insert_authorization_code(
                    OAuthAuthorizationCode(
                        code_hash=code_hash,
                        transaction_id=transaction_id,
                        user_id=member_user_id,
                        external_identity_id=external_identity_id,
                        client_id=client_id,
                        redirect_uri=redirect_uri,
                        resource=resource,
                        scopes=("formowl.use",),
                        code_challenge=pkce_s256_challenge(_VERIFIER),
                        created_at=now.isoformat(),
                        expires_at=(now + timedelta(minutes=5)).isoformat(),
                    )
                )
                unit.commit()
        finally:
            repository.close()
        return {
            "suffix": suffix,
            "now": now,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "member_user_id": member_user_id,
            "external_identity_id": external_identity_id,
            "client_id": client_id,
            "authorization_id": authorization_id,
            "transaction_id": transaction_id,
            "raw_code": raw_code,
            "code_hash": code_hash,
            "resource": resource,
            "redirect_uri": redirect_uri,
        }

    def _bridge(
        self,
        repository: PostgreSQLOAuthRepository,
        state: dict[str, object],
    ) -> FormOwlOAuthBridge:
        config = OAuthBridgeConfig(
            issuer="https://auth.example.test",
            resource="https://auth.example.test/mcp",
            chatgpt_client_id=str(state["client_id"]),
            chatgpt_redirect_uri=str(state["redirect_uri"]),
            google_client_id="google-client",
            google_client_secret="google-secret",
            google_redirect_uri="https://auth.example.test/oauth/google/callback",
            state_encryption_key=Fernet.generate_key().decode("ascii"),
        )
        return FormOwlOAuthBridge(
            config=config,
            repository=repository,
            google_client=object(),  # type: ignore[arg-type]
            token_codec=FormOwlTokenCodec(
                issuer=config.issuer,
                client_id=config.chatgpt_client_id,
                key_set=FormOwlSigningKeySet(
                    [
                        generate_ephemeral_formowl_signing_key(
                            kid=f"membership-lock-{state['suffix']}"
                        )
                    ]
                ),
            ),
            random_bytes=DeterministicRng(f"membership-lock-{state['suffix']}").bytes,
        )

    def _token_request(self, state: dict[str, object]) -> dict[str, str]:
        return {
            "grant_type": "authorization_code",
            "code": str(state["raw_code"]),
            "client_id": str(state["client_id"]),
            "redirect_uri": str(state["redirect_uri"]),
            "code_verifier": _VERIFIER,
            "resource": str(state["resource"]),
        }

    def _backend_pid(self, repository: PostgreSQLOAuthRepository) -> int:
        row = repository.connection.query_one(
            SQLStatement(sql="SELECT pg_backend_pid() AS backend_pid")
        )
        if row is None or not isinstance(row.get("backend_pid"), int):
            raise AssertionError("PostgreSQL backend pid was unavailable")
        return int(row["backend_pid"])

    def _wait_until_blocked(self, backend_pid: int) -> None:
        deadline = time.monotonic() + 5
        poll = Event()
        with psycopg.connect(self.dsn, autocommit=True) as monitor:
            while time.monotonic() < deadline:
                blocked_count = monitor.execute(
                    "SELECT cardinality(pg_blocking_pids(%s))",
                    (backend_pid,),
                ).fetchone()[0]
                if blocked_count:
                    return
                poll.wait(timeout=0.01)
        raise AssertionError("PostgreSQL membership lock wait was not observed")

    def _cleanup(self, state: dict[str, object]) -> None:
        with psycopg.connect(self.dsn) as connection:
            connection.execute(
                "DELETE FROM formowl_audit_log WHERE actor_user_id IN (%s, %s) "
                "OR target_id = %s OR workspace_id = %s",
                (
                    state["owner_user_id"],
                    state["member_user_id"],
                    state["transaction_id"],
                    state["workspace_id"],
                ),
            )
            connection.execute(
                "DELETE FROM formowl_oauth_token_sessions "
                "WHERE user_id = %s AND current_workspace_id = %s",
                (state["member_user_id"], state["workspace_id"]),
            )
            connection.execute(
                "DELETE FROM formowl_oauth_authorization_codes WHERE code_hash = %s",
                (state["code_hash"],),
            )
            connection.execute(
                "DELETE FROM formowl_oauth_transactions WHERE transaction_id = %s",
                (state["transaction_id"],),
            )
            connection.execute(
                "DELETE FROM formowl_oauth_client_authorizations "
                "WHERE oauth_client_authorization_id = %s",
                (state["authorization_id"],),
            )
            connection.execute(
                "DELETE FROM formowl_external_identities " "WHERE external_identity_id = %s",
                (state["external_identity_id"],),
            )
            connection.execute(
                "DELETE FROM formowl_workspace_members WHERE workspace_id = %s",
                (state["workspace_id"],),
            )
            connection.execute(
                "DELETE FROM formowl_users WHERE user_id IN (%s, %s)",
                (state["owner_user_id"], state["member_user_id"]),
            )


if __name__ == "__main__":
    unittest.main()
