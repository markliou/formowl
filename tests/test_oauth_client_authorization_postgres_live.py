from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
from uuid import uuid4

import psycopg

import _paths  # noqa: F401
from formowl_auth import ExternalIdentity, OAuthClientAuthorization
from formowl_auth.postgres import PostgreSQLOAuthRepository
from formowl_contract import AuditLog, User
from formowl_graph.storage import PostgresMigration, PostgreSQLMigrationRunner


_DSN_ENV = "FORMOWL_OAUTH_CLIENT_AUTHORIZATION_POSTGRES_DSN"


@unittest.skipUnless(os.environ.get(_DSN_ENV), f"{_DSN_ENV} is required")
class OAuthClientAuthorizationPostgresLiveTests(unittest.TestCase):
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

    def test_identity_user_pair_is_atomic_for_client_authorizations(self) -> None:
        suffix = uuid4().hex
        now = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc).isoformat()
        correct_user = User(
            user_id=f"user_live_correct_{suffix}",
            display_name="Correct Live User",
            email="correct-live@example.test",
            status="active",
            created_at=now,
        )
        correct_identity = ExternalIdentity(
            external_identity_id=f"extid_live_correct_{suffix}",
            provider="google",
            issuer="https://accounts.google.com",
            subject=f"google-live-correct-{suffix}",
            user_id=correct_user.user_id,
            email="correct-live@example.test",
            email_verified=True,
            status="active",
            created_at=now,
            last_authenticated_at=now,
        )
        correct_authorization = OAuthClientAuthorization(
            oauth_client_authorization_id=f"clientauth_live_correct_{suffix}",
            client_id=f"chatgpt_live_correct_{suffix}",
            external_identity_id=correct_identity.external_identity_id,
            user_id=correct_user.user_id,
            granted_scopes=("formowl.use",),
            default_workspace_id=f"workspace_live_correct_{suffix}",
            created_at=now,
        )
        identity_owner = User(
            user_id=f"user_live_identity_owner_{suffix}",
            display_name="Identity Owner",
            email="identity-owner@example.test",
            status="active",
            created_at=now,
        )
        mismatched_user = User(
            user_id=f"user_live_mismatch_{suffix}",
            display_name="Mismatched User",
            email="mismatched-user@example.test",
            status="active",
            created_at=now,
        )
        mismatched_identity = ExternalIdentity(
            external_identity_id=f"extid_live_mismatch_{suffix}",
            provider="google",
            issuer="https://accounts.google.com",
            subject=f"google-live-mismatch-{suffix}",
            user_id=identity_owner.user_id,
            email="identity-owner@example.test",
            email_verified=True,
            status="active",
            created_at=now,
            last_authenticated_at=now,
        )
        mismatched_authorization = OAuthClientAuthorization(
            oauth_client_authorization_id=f"clientauth_live_mismatch_{suffix}",
            client_id=f"chatgpt_live_mismatch_{suffix}",
            external_identity_id=mismatched_identity.external_identity_id,
            user_id=mismatched_user.user_id,
            granted_scopes=("formowl.use",),
            default_workspace_id=f"workspace_live_mismatch_{suffix}",
            created_at=now,
        )
        rollback_audit = AuditLog(
            audit_log_id=f"audit_live_mismatch_{suffix}",
            actor_user_id=identity_owner.user_id,
            actor_type="user",
            action="oauth_client_authorization_pair_probe",
            target_type="oauth_client_authorization",
            target_id=mismatched_authorization.oauth_client_authorization_id,
            session_id=f"session_live_mismatch_{suffix}",
            status="ok",
            reason_code="client_authorization_pair_probe",
            timestamp=now,
            metadata={"event_stage": "client_authorization_pair_probe"},
        )
        repository = PostgreSQLOAuthRepository.connect(self.dsn)
        try:
            with repository.transaction() as unit:
                repository.insert_user(correct_user)
                repository.insert_external_identity(correct_identity)
                repository.insert_client_authorization(correct_authorization)
                unit.commit()
            self.assertEqual(
                repository.get_client_authorization_by_id(
                    correct_authorization.oauth_client_authorization_id
                ),
                correct_authorization,
            )

            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                with repository.transaction() as unit:
                    repository.insert_user(identity_owner)
                    repository.insert_user(mismatched_user)
                    repository.insert_external_identity(mismatched_identity)
                    repository.append_audit_log(rollback_audit)
                    repository.insert_client_authorization(mismatched_authorization)
                    unit.commit()

            with psycopg.connect(self.dsn) as connection:
                constraint_names = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT conname FROM pg_constraint WHERE conname IN (%s, %s)",
                        (
                            "uq_formowl_external_identity_user",
                            "fk_formowl_client_authorization_identity_user",
                        ),
                    ).fetchall()
                }
                self.assertEqual(
                    constraint_names,
                    {
                        "uq_formowl_external_identity_user",
                        "fk_formowl_client_authorization_identity_user",
                    },
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_users WHERE user_id IN (%s, %s)",
                        (identity_owner.user_id, mismatched_user.user_id),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_external_identities "
                        "WHERE external_identity_id = %s",
                        (mismatched_identity.external_identity_id,),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_oauth_client_authorizations "
                        "WHERE oauth_client_authorization_id = %s",
                        (mismatched_authorization.oauth_client_authorization_id,),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_oauth_token_sessions "
                        "WHERE user_id IN (%s, %s)",
                        (identity_owner.user_id, mismatched_user.user_id),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_audit_log WHERE audit_log_id = %s",
                        (rollback_audit.audit_log_id,),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_oauth_client_authorizations "
                        "WHERE oauth_client_authorization_id = %s",
                        (correct_authorization.oauth_client_authorization_id,),
                    ).fetchone()[0],
                    1,
                )
        finally:
            repository.close()
            self._cleanup(
                correct_authorization_id=correct_authorization.oauth_client_authorization_id,
                correct_identity_id=correct_identity.external_identity_id,
                correct_user_id=correct_user.user_id,
                mismatch_audit_id=rollback_audit.audit_log_id,
                mismatch_authorization_id=mismatched_authorization.oauth_client_authorization_id,
                mismatch_identity_id=mismatched_identity.external_identity_id,
                mismatch_user_ids=(identity_owner.user_id, mismatched_user.user_id),
            )

    def test_duplicate_client_identity_pair_rolls_back_all_staged_writes(self) -> None:
        suffix = uuid4().hex
        now = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc).isoformat()
        existing_user = User(
            user_id=f"user_live_duplicate_owner_{suffix}",
            display_name="Duplicate Pair Owner",
            email="duplicate-pair-owner@example.test",
            status="active",
            created_at=now,
        )
        existing_identity = ExternalIdentity(
            external_identity_id=f"extid_live_duplicate_owner_{suffix}",
            provider="google",
            issuer="https://accounts.google.com",
            subject=f"google-live-duplicate-owner-{suffix}",
            user_id=existing_user.user_id,
            email="duplicate-pair-owner@example.test",
            email_verified=True,
            status="active",
            created_at=now,
            last_authenticated_at=now,
        )
        existing_authorization = OAuthClientAuthorization(
            oauth_client_authorization_id=f"clientauth_live_existing_{suffix}",
            client_id=f"chatgpt_live_duplicate_{suffix}",
            external_identity_id=existing_identity.external_identity_id,
            user_id=existing_user.user_id,
            granted_scopes=("formowl.use",),
            default_workspace_id=f"workspace_live_existing_{suffix}",
            created_at=now,
        )
        duplicate_authorization = OAuthClientAuthorization(
            oauth_client_authorization_id=f"clientauth_live_duplicate_{suffix}",
            client_id=existing_authorization.client_id,
            external_identity_id=existing_authorization.external_identity_id,
            user_id=existing_authorization.user_id,
            granted_scopes=("formowl.use",),
            default_workspace_id=f"workspace_live_duplicate_{suffix}",
            created_at=now,
        )
        staged_user = User(
            user_id=f"user_live_duplicate_staged_{suffix}",
            display_name="Staged Duplicate Probe User",
            email="staged-duplicate-probe@example.test",
            status="active",
            created_at=now,
        )
        staged_audit = AuditLog(
            audit_log_id=f"audit_live_duplicate_{suffix}",
            actor_user_id=existing_user.user_id,
            actor_type="user",
            action="oauth_client_authorization_duplicate_probe",
            target_type="oauth_client_authorization",
            target_id=duplicate_authorization.oauth_client_authorization_id,
            session_id=f"session_live_duplicate_{suffix}",
            status="ok",
            reason_code="client_authorization_duplicate_probe",
            timestamp=now,
            metadata={"event_stage": "client_authorization_duplicate_probe"},
        )
        repository = PostgreSQLOAuthRepository.connect(self.dsn)
        try:
            with repository.transaction() as unit:
                repository.insert_user(existing_user)
                repository.insert_external_identity(existing_identity)
                repository.insert_client_authorization(existing_authorization)
                unit.commit()

            self.assertNotEqual(
                duplicate_authorization.oauth_client_authorization_id,
                existing_authorization.oauth_client_authorization_id,
            )
            self.assertEqual(
                (
                    duplicate_authorization.client_id,
                    duplicate_authorization.external_identity_id,
                ),
                (
                    existing_authorization.client_id,
                    existing_authorization.external_identity_id,
                ),
            )
            with self.assertRaises(psycopg.errors.UniqueViolation):
                with repository.transaction() as unit:
                    repository.insert_user(staged_user)
                    repository.append_audit_log(staged_audit)
                    repository.insert_client_authorization(duplicate_authorization)
                    unit.commit()

            self.assertEqual(
                repository.get_client_authorization_by_id(
                    existing_authorization.oauth_client_authorization_id
                ),
                existing_authorization,
            )
            self.assertIsNone(
                repository.get_client_authorization_by_id(
                    duplicate_authorization.oauth_client_authorization_id
                )
            )
            with psycopg.connect(self.dsn) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_oauth_client_authorizations "
                        "WHERE client_id = %s AND external_identity_id = %s",
                        (
                            existing_authorization.client_id,
                            existing_authorization.external_identity_id,
                        ),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_users WHERE user_id = %s",
                        (staged_user.user_id,),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM formowl_audit_log WHERE audit_log_id = %s",
                        (staged_audit.audit_log_id,),
                    ).fetchone()[0],
                    0,
                )
        finally:
            repository.close()
            self._cleanup_duplicate_probe(
                authorization_ids=(
                    existing_authorization.oauth_client_authorization_id,
                    duplicate_authorization.oauth_client_authorization_id,
                ),
                identity_id=existing_identity.external_identity_id,
                user_ids=(existing_user.user_id, staged_user.user_id),
                audit_id=staged_audit.audit_log_id,
            )

    def _cleanup(
        self,
        *,
        correct_authorization_id: str,
        correct_identity_id: str,
        correct_user_id: str,
        mismatch_audit_id: str,
        mismatch_authorization_id: str,
        mismatch_identity_id: str,
        mismatch_user_ids: tuple[str, str],
    ) -> None:
        with psycopg.connect(self.dsn) as connection:
            connection.execute(
                "DELETE FROM formowl_audit_log WHERE audit_log_id = %s",
                (mismatch_audit_id,),
            )
            connection.execute(
                "DELETE FROM formowl_oauth_client_authorizations "
                "WHERE oauth_client_authorization_id IN (%s, %s)",
                (correct_authorization_id, mismatch_authorization_id),
            )
            connection.execute(
                "DELETE FROM formowl_external_identities " "WHERE external_identity_id IN (%s, %s)",
                (correct_identity_id, mismatch_identity_id),
            )
            connection.execute(
                "DELETE FROM formowl_users WHERE user_id IN (%s, %s, %s)",
                (correct_user_id, *mismatch_user_ids),
            )

    def _cleanup_duplicate_probe(
        self,
        *,
        authorization_ids: tuple[str, str],
        identity_id: str,
        user_ids: tuple[str, str],
        audit_id: str,
    ) -> None:
        with psycopg.connect(self.dsn) as connection:
            connection.execute(
                "DELETE FROM formowl_audit_log WHERE audit_log_id = %s",
                (audit_id,),
            )
            connection.execute(
                "DELETE FROM formowl_oauth_client_authorizations "
                "WHERE oauth_client_authorization_id IN (%s, %s)",
                authorization_ids,
            )
            connection.execute(
                "DELETE FROM formowl_external_identities WHERE external_identity_id = %s",
                (identity_id,),
            )
            connection.execute(
                "DELETE FROM formowl_users WHERE user_id IN (%s, %s)",
                user_ids,
            )


if __name__ == "__main__":
    unittest.main()
