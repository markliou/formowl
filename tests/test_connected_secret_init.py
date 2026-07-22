from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import fcntl
from io import StringIO
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from formowl_gateway.runtime import main
from formowl_gateway.secret_init import (
    SecretInitializationError,
    initialize_connected_secrets,
)


_SECRET_NAMES = {
    "postgres-password",
    "database-dsn",
    "state-encryption-key",
    "signing-key-set.json",
    "signing-current.pem",
    "signing-previous.pem",
}


class ConnectedSecretInitializationTests(unittest.TestCase):
    def test_create_and_rerun_are_atomic_minimal_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "secrets"
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                created = initialize_connected_secrets(output_dir)

            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(created["status"], "ok")
            self.assertEqual(created["secret_set_state"], "created")
            self.assertEqual(created["secret_file_count"], 6)
            self.assertEqual(created["created_file_count"], 6)
            self.assertEqual(created["recovered_file_count"], 0)
            self.assertEqual(created["recovered_staging_entry_count"], 0)
            self.assertEqual(created["active_signing_key_count"], 1)
            self.assertEqual(created["standby_signing_slot_count"], 1)
            self.assertFalse(created["google_client_secret_generated"])
            self.assertTrue(created["requires_operator_google_client_secret"])
            self.assertFalse(created["supports_connected_preflight_ready"])
            self.assertRegex(
                str(created["initialization_contract_hash"]),
                r"^sha256:[0-9a-f]{64}$",
            )
            self.assertEqual(stat.S_IMODE(output_dir.stat().st_mode), 0o700)
            self.assertTrue(_SECRET_NAMES <= {path.name for path in output_dir.iterdir()})
            for name in _SECRET_NAMES:
                path = output_dir / name
                self.assertTrue(path.is_file())
                self.assertFalse(path.is_symlink())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)

            password = (output_dir / "postgres-password").read_text(encoding="ascii").strip()
            dsn = (output_dir / "database-dsn").read_text(encoding="ascii").strip()
            state_key = (output_dir / "state-encryption-key").read_text(encoding="ascii").strip()
            manifest = json.loads((output_dir / "signing-key-set.json").read_text(encoding="utf-8"))
            self.assertIn(password, dsn)
            self.assertNotIn(password, json.dumps(created, sort_keys=True))
            self.assertNotIn(dsn, json.dumps(created, sort_keys=True))
            self.assertNotIn(state_key, json.dumps(created, sort_keys=True))
            self.assertEqual(manifest["version"], 1)
            self.assertEqual(len(manifest["keys"]), 1)
            self.assertTrue(manifest["keys"][0]["active"])
            self.assertEqual(
                manifest["keys"][0]["private_key_file"],
                "/run/secrets/formowl_signing_key_current",
            )
            self.assertNotIn("previous", json.dumps(manifest, sort_keys=True))
            self.assertFalse((output_dir / "google-client-secret").exists())
            current = serialization.load_pem_private_key(
                (output_dir / "signing-current.pem").read_bytes(),
                password=None,
            )
            standby = serialization.load_pem_private_key(
                (output_dir / "signing-previous.pem").read_bytes(),
                password=None,
            )
            self.assertIsInstance(current, rsa.RSAPrivateKey)
            self.assertIsInstance(standby, rsa.RSAPrivateKey)
            self.assertGreaterEqual(current.key_size, 2048)
            self.assertGreaterEqual(standby.key_size, 2048)
            self.assertNotEqual(
                current.public_key().public_numbers(),
                standby.public_key().public_numbers(),
            )

            before = {
                name: ((output_dir / name).stat().st_ino, (output_dir / name).read_bytes())
                for name in _SECRET_NAMES
            }
            unchanged = initialize_connected_secrets(output_dir)
            after = {
                name: ((output_dir / name).stat().st_ino, (output_dir / name).read_bytes())
                for name in _SECRET_NAMES
            }
            self.assertEqual(unchanged["secret_set_state"], "unchanged")
            self.assertEqual(unchanged["created_file_count"], 0)
            self.assertEqual(
                unchanged["initialization_contract_hash"],
                created["initialization_contract_hash"],
            )
            self.assertEqual(after, before)

    def test_partial_invalid_and_conflicting_sets_fail_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "partial"
            output_dir.mkdir(mode=0o700)
            sentinel = output_dir / "postgres-password"
            sentinel.write_text("existing-secret-must-remain\n", encoding="utf-8")
            sentinel.chmod(0o400)

            with self.assertRaises(SecretInitializationError) as partial:
                initialize_connected_secrets(output_dir)

            self.assertEqual(partial.exception.code, "secret_recovery_required")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing-secret-must-remain\n")
            self.assertEqual(
                {path.name for path in output_dir.iterdir() if not path.name.startswith(".")},
                {"postgres-password"},
            )
            self.assertNotIn(str(output_dir), str(partial.exception))
            self.assertNotIn("existing-secret-must-remain", str(partial.exception))

            recovered = initialize_connected_secrets(output_dir, recover_partial=True)
            self.assertEqual(recovered["secret_set_state"], "recovered")
            self.assertEqual(recovered["created_file_count"], 6)
            self.assertEqual(recovered["recovered_file_count"], 1)
            self.assertEqual(recovered["recovered_staging_entry_count"], 0)
            self.assertNotEqual(
                (output_dir / "postgres-password").read_text(encoding="ascii"),
                "existing-secret-must-remain\n",
            )
            quarantined_values = [
                path.read_text(encoding="utf-8")
                for recovery in output_dir.glob(".formowl-secret-recovery-*")
                for path in recovery.rglob("postgres-password")
            ]
            self.assertEqual(quarantined_values, ["existing-secret-must-remain\n"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "invalid"
            initialize_connected_secrets(output_dir)
            current = output_dir / "signing-current.pem"
            current.chmod(0o600)

            with self.assertRaises(SecretInitializationError) as permissions:
                initialize_connected_secrets(output_dir)

            self.assertEqual(permissions.exception.code, "secret_permissions_invalid")
            self.assertEqual(stat.S_IMODE(current.stat().st_mode), 0o600)

    def test_injected_publish_failure_removes_every_new_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "rollback"
            real_link = os.link
            call_count = 0

            def fail_second_link(source, destination, *, follow_symlinks=True):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("synthetic private destination detail")
                return real_link(source, destination, follow_symlinks=follow_symlinks)

            with patch("formowl_gateway.secret_init.os.link", side_effect=fail_second_link):
                with self.assertRaises(SecretInitializationError) as failed:
                    initialize_connected_secrets(output_dir)

            self.assertEqual(failed.exception.code, "secret_set_write_failed")
            self.assertFalse(any((output_dir / name).exists() for name in _SECRET_NAMES))
            self.assertFalse(
                any(path.name.startswith(".formowl-secret-init-") for path in output_dir.iterdir())
            )
            self.assertNotIn("destination", str(failed.exception))
            self.assertNotIn(str(output_dir), str(failed.exception))

    def test_cli_bypasses_runtime_secrets_and_never_prints_generated_values_or_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "cli-secrets"
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    ["init-secrets", "--output-dir", str(output_dir)],
                    environ={"FORMOWL_DATABASE_DSN": "plaintext-must-not-be-read"},
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["secret_set_state"], "created")
            self.assertFalse(payload["google_client_secret_generated"])
            self.assertTrue(payload["requires_operator_google_client_secret"])
            self.assertFalse(payload["supports_connected_preflight_ready"])
            self.assertFalse((output_dir / "google-client-secret").exists())
            rendered = stdout.getvalue() + stderr.getvalue()
            for secret in (
                (output_dir / "postgres-password").read_text(encoding="ascii").strip(),
                (output_dir / "database-dsn").read_text(encoding="ascii").strip(),
                (output_dir / "state-encryption-key").read_text(encoding="ascii").strip(),
                "PRIVATE KEY",
                str(output_dir),
                "plaintext-must-not-be-read",
            ):
                self.assertNotIn(secret, rendered)
            self.assertNotRegex(rendered, re.escape(temporary_directory))

    def test_stale_crash_staging_requires_explicit_whole_entry_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "stale"
            output_dir.mkdir(mode=0o700)
            stale = output_dir / ".formowl-secret-init-crashed"
            stale.mkdir(mode=0o700)
            staged_secret = stale / "database-dsn"
            staged_secret.write_text("private-staged-value\n", encoding="utf-8")
            staged_secret.chmod(0o400)

            with self.assertRaises(SecretInitializationError) as required:
                initialize_connected_secrets(output_dir)

            self.assertEqual(required.exception.code, "secret_recovery_required")
            self.assertTrue(stale.exists())
            recovered = initialize_connected_secrets(output_dir, recover_partial=True)
            self.assertEqual(recovered["secret_set_state"], "recovered")
            self.assertEqual(recovered["recovered_file_count"], 0)
            self.assertEqual(recovered["recovered_staging_entry_count"], 1)
            self.assertFalse(stale.exists())
            recovered_staged_values = [
                path.read_text(encoding="utf-8")
                for recovery in output_dir.glob(".formowl-secret-recovery-*")
                for path in recovery.rglob("database-dsn")
            ]
            self.assertEqual(recovered_staged_values, ["private-staged-value\n"])
            self.assertTrue(all((output_dir / name).is_file() for name in _SECRET_NAMES))
            rendered = json.dumps(recovered, sort_keys=True)
            self.assertNotIn("private-staged-value", rendered)
            self.assertNotIn(str(output_dir), rendered)

    def test_recovery_quarantine_failure_restores_original_entries_and_retry_succeeds(
        self,
    ) -> None:
        for failure_point in ("second_rename", "directory_fsync"):
            with self.subTest(failure_point=failure_point):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    output_dir = Path(temporary_directory) / "quarantine-rollback"
                    output_dir.mkdir(mode=0o700)
                    database_dsn = output_dir / "database-dsn"
                    database_dsn.write_bytes(b"private-database-dsn\n")
                    database_dsn.chmod(0o400)
                    postgres_password = output_dir / "postgres-password"
                    postgres_password.write_bytes(b"private-postgres-password\n")
                    postgres_password.chmod(0o400)
                    stale = output_dir / ".formowl-secret-init-crashed"
                    stale.mkdir(mode=0o700)
                    stale_secret = stale / "state-encryption-key"
                    stale_secret.write_bytes(b"private-stale-state-key\n")
                    stale_secret.chmod(0o400)

                    def entry_snapshot(path: Path) -> tuple[str, bytes | None, int | None]:
                        if not os.path.lexists(path):
                            return ("missing", None, None)
                        return (
                            "directory" if path.is_dir() else "file",
                            None if path.is_dir() else path.read_bytes(),
                            stat.S_IMODE(path.stat().st_mode),
                        )

                    original_entries = {
                        path.relative_to(output_dir): entry_snapshot(path)
                        for path in (database_dsn, postgres_password, stale, stale_secret)
                    }
                    real_rename = os.rename
                    real_fsync = os.fsync
                    rename_calls = 0
                    fsync_calls = 0
                    injected_detail = f"private quarantine {failure_point} detail"

                    def controlled_rename(source, destination, *args, **kwargs):
                        nonlocal rename_calls
                        rename_calls += 1
                        if failure_point == "second_rename" and rename_calls == 2:
                            raise OSError(injected_detail)
                        return real_rename(source, destination, *args, **kwargs)

                    def controlled_fsync(descriptor):
                        nonlocal fsync_calls
                        fsync_calls += 1
                        if failure_point == "directory_fsync" and fsync_calls == 1:
                            raise OSError(injected_detail)
                        return real_fsync(descriptor)

                    with (
                        patch(
                            "formowl_gateway.secret_init.os.rename",
                            side_effect=controlled_rename,
                        ),
                        patch(
                            "formowl_gateway.secret_init.os.fsync",
                            side_effect=controlled_fsync,
                        ),
                    ):
                        with self.assertRaises(SecretInitializationError) as failed:
                            initialize_connected_secrets(output_dir, recover_partial=True)

                    self.assertEqual(failed.exception.code, "secret_recovery_failed")
                    self.assertEqual(str(failed.exception), "secret_recovery_failed")
                    for private_detail in (
                        injected_detail,
                        str(output_dir),
                        "private-database-dsn",
                        "private-postgres-password",
                        "private-stale-state-key",
                    ):
                        self.assertNotIn(private_detail, str(failed.exception))
                    restored_entries = {
                        path.relative_to(output_dir): entry_snapshot(path)
                        for path in (database_dsn, postgres_password, stale, stale_secret)
                    }
                    self.assertEqual(restored_entries, original_entries)
                    self.assertFalse(any(output_dir.glob(".formowl-secret-recovery-*")))
                    self.assertEqual(
                        {
                            path.name
                            for path in output_dir.iterdir()
                            if not path.name.startswith(".")
                        },
                        {"database-dsn", "postgres-password"},
                    )
                    self.assertFalse(
                        any(
                            (output_dir / name).exists()
                            for name in _SECRET_NAMES - {"database-dsn", "postgres-password"}
                        )
                    )
                    self.assertEqual(
                        rename_calls,
                        3 if failure_point == "second_rename" else 6,
                    )
                    self.assertEqual(
                        fsync_calls,
                        0 if failure_point == "second_rename" else 1,
                    )

                    recovered = initialize_connected_secrets(
                        output_dir,
                        recover_partial=True,
                    )

                    self.assertEqual(recovered["secret_set_state"], "recovered")
                    self.assertEqual(recovered["recovered_file_count"], 2)
                    self.assertEqual(recovered["recovered_staging_entry_count"], 1)
                    self.assertTrue(all((output_dir / name).is_file() for name in _SECRET_NAMES))

    def test_recovery_rollback_failure_preserves_operator_entries_and_retry_succeeds(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "quarantine-rollback-incomplete"
            output_dir.mkdir(mode=0o700)
            operator_files = {
                "database-dsn": b"private-database-dsn\n",
                "postgres-password": b"private-postgres-password\n",
            }
            for name, value in operator_files.items():
                path = output_dir / name
                path.write_bytes(value)
                path.chmod(0o400)
            stale = output_dir / ".formowl-secret-init-crashed"
            stale.mkdir(mode=0o700)
            stale_secret = stale / "state-encryption-key"
            stale_secret.write_bytes(b"private-stale-state-key\n")
            stale_secret.chmod(0o400)
            operator_files["state-encryption-key"] = b"private-stale-state-key\n"

            real_rename = os.rename
            rename_calls: list[tuple[Path, Path]] = []
            injected_detail = "private rollback rename failure detail"

            def controlled_rename(source, destination, *args, **kwargs):
                rename_calls.append((Path(source), Path(destination)))
                if len(rename_calls) in {2, 3}:
                    raise OSError(injected_detail)
                return real_rename(source, destination, *args, **kwargs)

            stdout = StringIO()
            stderr = StringIO()
            with (
                redirect_stdout(stdout),
                redirect_stderr(stderr),
                patch(
                    "formowl_gateway.secret_init.os.rename",
                    side_effect=controlled_rename,
                ),
                patch("formowl_gateway.secret_init.shutil.rmtree") as recursive_cleanup,
            ):
                with self.assertRaises(SecretInitializationError) as failed:
                    initialize_connected_secrets(output_dir, recover_partial=True)

            self.assertEqual(failed.exception.code, "secret_recovery_failed")
            self.assertEqual(str(failed.exception), "secret_recovery_failed")
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            recursive_cleanup.assert_not_called()
            quarantines = list(output_dir.glob(".formowl-secret-recovery-*"))
            self.assertEqual(len(quarantines), 1)
            quarantine = quarantines[0]
            self.assertTrue(quarantine.is_dir())
            self.assertEqual(stat.S_IMODE(quarantine.stat().st_mode), 0o700)
            self.assertEqual({path.name for path in quarantine.iterdir()}, {"database-dsn"})
            self.assertEqual(
                rename_calls,
                [
                    (output_dir / "database-dsn", quarantine / "database-dsn"),
                    (output_dir / "postgres-password", quarantine / "postgres-password"),
                    (quarantine / "database-dsn", output_dir / "database-dsn"),
                ],
            )
            self.assertFalse((output_dir / "database-dsn").exists())
            self.assertTrue((output_dir / "postgres-password").is_file())
            self.assertTrue(stale.is_dir())
            self.assertTrue(stale_secret.is_file())
            for name, expected_value in operator_files.items():
                matches = [
                    path
                    for path in output_dir.rglob(name)
                    if path.is_file() and path.read_bytes() == expected_value
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].read_bytes(), expected_value)
                self.assertEqual(stat.S_IMODE(matches[0].stat().st_mode), 0o400)
            self.assertEqual(
                {name for name in _SECRET_NAMES if os.path.lexists(output_dir / name)},
                {"postgres-password"},
            )
            self.assertFalse(all(os.path.lexists(output_dir / name) for name in _SECRET_NAMES))
            rendered = "\n".join(
                (
                    str(failed.exception),
                    stdout.getvalue(),
                    stderr.getvalue(),
                )
            )
            for private_detail in (
                injected_detail,
                str(output_dir),
                "private-database-dsn",
                "private-postgres-password",
                "private-stale-state-key",
            ):
                self.assertNotIn(private_detail, rendered)

            recovered = initialize_connected_secrets(output_dir, recover_partial=True)

            self.assertEqual(recovered["secret_set_state"], "recovered")
            self.assertEqual(recovered["created_file_count"], 6)
            self.assertEqual(recovered["recovered_file_count"], 1)
            self.assertEqual(recovered["recovered_staging_entry_count"], 1)
            self.assertTrue(all((output_dir / name).is_file() for name in _SECRET_NAMES))
            self.assertTrue(quarantine.is_dir())
            self.assertEqual(
                (quarantine / "database-dsn").read_bytes(),
                b"private-database-dsn\n",
            )
            self.assertEqual(
                stat.S_IMODE((quarantine / "database-dsn").stat().st_mode),
                0o400,
            )
            preserved_operator_values = {
                (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                for recovery in output_dir.glob(".formowl-secret-recovery-*")
                for path in recovery.rglob("*")
                if path.is_file()
            }
            self.assertTrue(
                {(value, 0o400) for value in operator_files.values()}.issubset(
                    preserved_operator_values
                )
            )

    def test_lock_contention_is_safe_and_retry_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "locked"
            output_dir.mkdir(mode=0o700)
            lock_path = output_dir / ".formowl-secret-init.lock"
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with self.assertRaises(SecretInitializationError) as locked:
                    initialize_connected_secrets(output_dir)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

            self.assertEqual(locked.exception.code, "secret_initialization_locked")
            self.assertEqual(str(locked.exception), "secret_initialization_locked")
            self.assertFalse(any((output_dir / name).exists() for name in _SECRET_NAMES))
            self.assertFalse(
                any(
                    path.name.startswith((".formowl-secret-init-", ".formowl-secret-recovery-"))
                    for path in output_dir.iterdir()
                )
            )
            self.assertNotIn(str(output_dir), str(locked.exception))
            unsafe = SecretInitializationError("private/path/secret")
            self.assertEqual(unsafe.code, "secret_initialization_failed")
            self.assertEqual(str(unsafe), "secret_initialization_failed")
            self.assertNotIn("private", str(unsafe))

            created = initialize_connected_secrets(output_dir)

            self.assertEqual(created["secret_set_state"], "created")
            self.assertTrue(all((output_dir / name).is_file() for name in _SECRET_NAMES))

    def test_invalid_dsn_manifest_and_key_fail_without_overwrite_then_retry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "invalid-complete-set"
            initialize_connected_secrets(output_dir)
            invalid_payloads = {
                "database-dsn": b"postgresql://wrong:wrong@wrong:5432/wrong\n",
                "signing-key-set.json": b'{"keys":[],"version":1}\n',
                "signing-current.pem": b"private-invalid-key-material\n",
            }
            for name, invalid_payload in invalid_payloads.items():
                with self.subTest(name=name):
                    target = output_dir / name
                    original_payload = target.read_bytes()
                    target.chmod(0o600)
                    target.write_bytes(invalid_payload)
                    target.chmod(0o400)
                    invalid_snapshot = {
                        secret_name: (
                            (output_dir / secret_name).stat().st_ino,
                            (output_dir / secret_name).read_bytes(),
                            stat.S_IMODE((output_dir / secret_name).stat().st_mode),
                        )
                        for secret_name in _SECRET_NAMES
                    }

                    with self.assertRaises(SecretInitializationError) as invalid:
                        initialize_connected_secrets(output_dir)

                    self.assertEqual(invalid.exception.code, "secret_set_invalid")
                    self.assertEqual(str(invalid.exception), "secret_set_invalid")
                    self.assertNotIn(str(output_dir), str(invalid.exception))
                    self.assertNotIn("wrong", str(invalid.exception))
                    self.assertEqual(
                        {
                            secret_name: (
                                (output_dir / secret_name).stat().st_ino,
                                (output_dir / secret_name).read_bytes(),
                                stat.S_IMODE((output_dir / secret_name).stat().st_mode),
                            )
                            for secret_name in _SECRET_NAMES
                        },
                        invalid_snapshot,
                    )
                    target.chmod(0o600)
                    target.write_bytes(original_payload)
                    target.chmod(0o400)
                    corrected = initialize_connected_secrets(output_dir)
                    self.assertEqual(corrected["secret_set_state"], "unchanged")

    def test_invalid_postgres_shape_fails_before_creating_secret_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "bad-config"

            with self.assertRaises(SecretInitializationError) as caught:
                initialize_connected_secrets(output_dir, postgres_host="bad host/private")

            self.assertEqual(caught.exception.code, "secret_postgres_config_invalid")
            self.assertFalse(output_dir.exists())
            self.assertNotIn("bad host", str(caught.exception))

    def test_operator_docs_fix_generated_external_and_recovery_boundaries(self) -> None:
        root = Path(__file__).resolve().parents[1]
        secrets_readme = (root / "deploy/connected/secrets/README.md").read_text(encoding="utf-8")
        root_readme = (root / "README.md").read_text(encoding="utf-8")
        runbook = (root / "docs/closed-beta-runbook.md").read_text(encoding="utf-8")
        example_manifest = json.loads(
            (root / "deploy/connected/signing-key-set.example.json").read_text(encoding="utf-8")
        )

        for document in (secrets_readme, root_readme, runbook):
            self.assertIn("init-secrets --output-dir /secrets", document)
            self.assertIn("Google", document)
            self.assertIn("0400", document)
        self.assertIn("--recover-partial", secrets_readme)
        self.assertIn("--recover-partial", runbook)
        self.assertIn("google_client_secret_generated=false", secrets_readme)
        self.assertIn("requires_operator_google_client_secret=true", secrets_readme)
        self.assertIn("supports_connected_preflight_ready=false", secrets_readme)
        self.assertIn("status: ok", runbook)
        self.assertIn("not create the Google OAuth", root_readme)
        self.assertEqual(example_manifest["version"], 1)
        self.assertEqual(len(example_manifest["keys"]), 1)
        self.assertTrue(example_manifest["keys"][0]["active"])
        self.assertNotIn("verify_until", example_manifest["keys"][0])


if __name__ == "__main__":
    unittest.main()
