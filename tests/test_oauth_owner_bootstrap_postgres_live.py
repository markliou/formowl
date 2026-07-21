from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from pathlib import Path
from threading import Barrier
import unittest
from uuid import uuid4

import psycopg

import _paths  # noqa: F401
from formowl_auth import FormOwlOAuthBridge, OAuthAccessDenied
from formowl_auth.postgres import PostgreSQLOAuthRepository
from formowl_graph.storage import PostgresMigration, PostgreSQLMigrationRunner
from oauth_harness import DeterministicRng, FakeClock, generate_ephemeral_formowl_signing_key
from test_oauth_bridge_service import BridgeFixture


_DSN_ENV = "FORMOWL_OAUTH_BOOTSTRAP_POSTGRES_DSN"


@unittest.skipUnless(os.environ.get(_DSN_ENV), f"{_DSN_ENV} is required")
class OAuthOwnerBootstrapPostgresLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dsn = os.environ[_DSN_ENV]
        cls.signing_key = generate_ephemeral_formowl_signing_key(kid="owner-bootstrap-live-key")
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

    def _bootstrap(
        self,
        *,
        barrier: Barrier,
        seed: str,
        workspace_id: str,
        email: str,
        idempotency_key: str,
        operator_service_id: str,
    ) -> tuple[str, str]:
        template = BridgeFixture(self.signing_key, seed=f"template-{seed}")
        repository = PostgreSQLOAuthRepository.connect(self.dsn)
        bridge = FormOwlOAuthBridge(
            config=template.config,
            repository=repository,
            google_client=template.google_client,  # type: ignore[arg-type]
            token_codec=template.bridge.token_codec,
            random_bytes=DeterministicRng(seed).bytes,
            owner_bootstrap_operator_authorizer=lambda service_id: service_id
            in {"operator_service_001", "operator_service_002"},
        )
        clock = FakeClock()
        try:
            barrier.wait(timeout=10)
            invitation = bridge.bootstrap_owner_invitation(
                workspace_id=workspace_id,
                email=email,
                expires_at=clock.now() + timedelta(hours=1),
                idempotency_key=idempotency_key,
                operator_service_id=operator_service_id,
                now=clock.now(),
            )
            return "ok", invitation.invitation_id
        except OAuthAccessDenied as denial:
            return "denied", denial.reason_code
        finally:
            repository.close()

    @staticmethod
    def _unique_workspace_id(label: str) -> str:
        # This UUID is only a non-secret test namespace. It prevents a prior
        # successful run from satisfying a later concurrency assertion.
        return f"workspace_live_{label}_{uuid4().hex}"

    def _global_user_count(self) -> int:
        with psycopg.connect(self.dsn) as connection:
            row = connection.execute("SELECT count(*) FROM formowl_users").fetchone()
        if row is None:
            raise AssertionError("user count query returned no row")
        return int(row[0])

    def _workspace_counts(
        self,
        workspace_id: str,
        *,
        baseline_user_count: int,
    ) -> tuple[int, int, int, int, int]:
        with psycopg.connect(self.dsn) as connection:
            bootstrap_count = connection.execute(
                "SELECT count(*) FROM formowl_oauth_owner_bootstraps WHERE workspace_id = %s",
                (workspace_id,),
            ).fetchone()[0]
            invitation_count = connection.execute(
                "SELECT count(*) FROM formowl_oauth_invitations WHERE workspace_id = %s",
                (workspace_id,),
            ).fetchone()[0]
            audit_count = connection.execute(
                "SELECT count(*) FROM formowl_audit_log "
                "WHERE workspace_id = %s AND action = 'oauth_owner_bootstrap_created'",
                (workspace_id,),
            ).fetchone()[0]
            user_count = connection.execute("SELECT count(*) FROM formowl_users").fetchone()[0]
            member_count = connection.execute(
                "SELECT count(*) FROM formowl_workspace_members WHERE workspace_id = %s",
                (workspace_id,),
            ).fetchone()[0]
        return (
            int(bootstrap_count),
            int(invitation_count),
            int(audit_count),
            int(user_count) - baseline_user_count,
            int(member_count),
        )

    def _cleanup_workspace(self, workspace_id: str) -> None:
        with psycopg.connect(self.dsn) as connection:
            user_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT user_id FROM formowl_workspace_members WHERE workspace_id = %s",
                    (workspace_id,),
                ).fetchall()
            ]
            connection.execute(
                "DELETE FROM formowl_audit_log WHERE workspace_id = %s",
                (workspace_id,),
            )
            connection.execute(
                "DELETE FROM formowl_oauth_owner_bootstraps WHERE workspace_id = %s",
                (workspace_id,),
            )
            connection.execute(
                "DELETE FROM formowl_oauth_invitations WHERE workspace_id = %s",
                (workspace_id,),
            )
            connection.execute(
                "DELETE FROM formowl_workspace_members WHERE workspace_id = %s",
                (workspace_id,),
            )
            for user_id in user_ids:
                connection.execute(
                    "DELETE FROM formowl_users WHERE user_id = %s",
                    (user_id,),
                )

    def _workspace_audit(self, workspace_id: str) -> tuple[str, dict[str, str]]:
        with psycopg.connect(self.dsn) as connection:
            row = connection.execute(
                "SELECT actor_service_id, metadata FROM formowl_audit_log "
                "WHERE workspace_id = %s AND action = 'oauth_owner_bootstrap_created'",
                (workspace_id,),
            ).fetchone()
        if row is None:
            raise AssertionError("owner bootstrap audit is missing")
        return str(row[0]), dict(row[1])

    def test_concurrent_identical_bootstrap_returns_one_invitation_and_one_audit(self) -> None:
        workspace_id = self._unique_workspace_id("identical")
        baseline_user_count = self._global_user_count()
        self.assertEqual(
            self._workspace_counts(
                workspace_id,
                baseline_user_count=baseline_user_count,
            ),
            (0, 0, 0, 0, 0),
        )
        try:
            barrier = Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        self._bootstrap,
                        barrier=barrier,
                        seed=f"identical-{index}",
                        workspace_id=workspace_id,
                        email="identical@example.test",
                        idempotency_key="identical-key",
                        operator_service_id="operator_service_001",
                    )
                    for index in range(2)
                ]
            results = [future.result(timeout=15) for future in futures]

            self.assertEqual([status for status, _value in results], ["ok", "ok"])
            self.assertEqual(len({value for _status, value in results}), 1)
            self.assertEqual(
                self._workspace_counts(
                    workspace_id,
                    baseline_user_count=baseline_user_count,
                ),
                (1, 1, 1, 0, 0),
            )
            self.assertEqual(
                self._workspace_audit(workspace_id),
                ("operator_service_001", {"event_stage": "owner_bootstrap"}),
            )
        finally:
            self._cleanup_workspace(workspace_id)
        self.assertEqual(
            self._workspace_counts(
                workspace_id,
                baseline_user_count=baseline_user_count,
            ),
            (0, 0, 0, 0, 0),
        )

    def test_concurrent_conflicting_bootstrap_has_exactly_one_winner(self) -> None:
        workspace_id = self._unique_workspace_id("conflict")
        baseline_user_count = self._global_user_count()
        self.assertEqual(
            self._workspace_counts(
                workspace_id,
                baseline_user_count=baseline_user_count,
            ),
            (0, 0, 0, 0, 0),
        )
        try:
            barrier = Barrier(2)
            requests = (
                ("conflict-a", "first@example.test", "first-key", "operator_service_001"),
                ("conflict-b", "second@example.test", "second-key", "operator_service_002"),
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        self._bootstrap,
                        barrier=barrier,
                        seed=seed,
                        workspace_id=workspace_id,
                        email=email,
                        idempotency_key=idempotency_key,
                        operator_service_id=operator_service_id,
                    )
                    for seed, email, idempotency_key, operator_service_id in requests
                ]
            results = [future.result(timeout=15) for future in futures]

            self.assertEqual(sum(status == "ok" for status, _value in results), 1)
            self.assertEqual(sum(status == "denied" for status, _value in results), 1)
            denial_reason = next(value for status, value in results if status == "denied")
            self.assertIn(
                denial_reason,
                {"owner_bootstrap_conflict", "owner_bootstrap_invitation_conflict"},
            )
            self.assertEqual(
                self._workspace_counts(
                    workspace_id,
                    baseline_user_count=baseline_user_count,
                ),
                (1, 1, 1, 0, 0),
            )
            actor_service_id, metadata = self._workspace_audit(workspace_id)
            self.assertIn(actor_service_id, {"operator_service_001", "operator_service_002"})
            self.assertEqual(metadata, {"event_stage": "owner_bootstrap"})
            self.assertNotIn("example.test", str(metadata))
            self.assertNotIn("first-key", str(metadata))
            self.assertNotIn("second-key", str(metadata))
        finally:
            self._cleanup_workspace(workspace_id)
        self.assertEqual(
            self._workspace_counts(
                workspace_id,
                baseline_user_count=baseline_user_count,
            ),
            (0, 0, 0, 0, 0),
        )


if __name__ == "__main__":
    unittest.main()
