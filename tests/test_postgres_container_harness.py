from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "postgres_container_harness.sh"
ENTRYPOINTS = (
    ROOT / "scripts" / "postgres_transaction_rollback_live_smoke_container.sh",
    ROOT / "scripts" / "pgvector_repository_live_smoke_container.sh",
)


class PostgresContainerHarnessTests(unittest.TestCase):
    def test_entrypoints_delegate_container_lifecycle_to_shared_harness(self) -> None:
        for entrypoint in ENTRYPOINTS:
            script = entrypoint.read_text(encoding="utf-8")
            with self.subTest(entrypoint=entrypoint.name):
                self.assertIn("source /workspace/scripts/postgres_container_harness.sh", script)
                self.assertIn("formowl_postgres_initialize", script)
                self.assertIn("formowl_postgres_apply_migration", script)
                self.assertNotIn("docker-entrypoint.sh postgres", script)
                self.assertNotIn("pg_isready", script)
                self.assertNotIn("trap cleanup EXIT", script)

    def test_required_environment_validation_fails_closed(self) -> None:
        result = subprocess.run(
            [
                "bash",
                "-c",
                f"source {HARNESS}; formowl_postgres_require_env FORMOWL_TEST_REQUIRED",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "FORMOWL_TEST_REQUIRED is required\n")

    def test_pgdata_validation_rejects_paths_outside_formowl_tmp_namespace(self) -> None:
        for pgdata in (
            "",
            "/",
            ".",
            "relative/path",
            "/tmp/postgres",
            "/tmp/formowl-",
            "/tmp/formowl-/",
            "/tmp/formowl-probe/..",
            "/tmp/formowl-probe/../../home",
        ):
            with self.subTest(pgdata=pgdata):
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        f"source {HARNESS}; formowl_postgres_validate_pgdata {pgdata!r}",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    result.stderr,
                    "PGDATA must be a single safe /tmp/formowl-* directory\n",
                )

    def test_initialize_and_cleanup_use_shared_postgres_contract(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="formowl-postgres-harness-", dir="/tmp"
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            pgdata = temporary_path
            log_path = temporary_path / "postgres.log"
            trace_path = temporary_path / "trace.log"
            command = f"""
                set -euo pipefail
                source {HARNESS}
                docker-entrypoint.sh() {{ sleep 30; }}
                pg_isready() {{ printf 'ready:%s\n' "$*" >> {trace_path}; }}
                psql() {{ printf 'query:%s\n' "$*" >> {trace_path}; }}
                pg_ctl() {{
                  printf 'stop:%s\n' "$*" >> {trace_path}
                  kill "$FORMOWL_POSTGRES_PID"
                }}
                formowl_postgres_initialize {pgdata} {log_path}
                test "$PGUSER" = postgres
                test "$POSTGRES_DB" = postgres
                test "$POSTGRES_HOST_AUTH_METHOD" = trust
                test "$PGDATA" = {pgdata}
                formowl_postgres_cleanup
            """

            subprocess.run(["bash", "-c", command], check=True)

            trace = trace_path.read_text(encoding="utf-8")
            self.assertIn("ready:-U postgres -d postgres", trace)
            self.assertIn("query:-v ON_ERROR_STOP=1 -U postgres -d postgres -c SELECT 1", trace)
            self.assertIn(f"stop:-D {pgdata} -m fast -w stop", trace)


if __name__ == "__main__":
    unittest.main()
