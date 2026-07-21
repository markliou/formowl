from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401

from formowl_evidence.issue20 import (
    ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS,
    ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS,
    issue20_implementation_contract_hash,
)


IMPLEMENTATION_CONTRACT_FIXTURE_PATHS = (
    "pyproject.toml",
    "compose.yaml",
    "containers/dev/Dockerfile",
    "containers/runtime/Dockerfile",
    *ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS,
    "python/formowl_auth/contract.py",
    "python/formowl_contract/models.py",
    "python/formowl_evidence/issue20.py",
    "python/formowl_gateway/runtime.py",
    "python/formowl_graph/storage/postgres.py",
    "python/formowl_graph/storage/migrations/005_oauth_identity.sql",
    "python/formowl_ingestion/storage/records.py",
    "python/formowl_ingestion/uploads.py",
    "python/formowl_mail/__init__.py",
    "python/formowl_mail/upload_session.py",
    "scripts/connected_runtime_container_lifecycle_probe.py",
    "scripts/connected_runtime_postgres_live_e2e.py",
    "scripts/connected_operator_postgres_live_journey.py",
    "scripts/issue20_containerized_evidence_runner.sh",
    "scripts/issue20_runner_boundary.py",
    "scripts/oauth_mcp_harness.py",
    "tests/oauth_harness.py",
)


def _write_fixture(root: Path) -> None:
    for relative_path in IMPLEMENTATION_CONTRACT_FIXTURE_PATHS:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"contract:{relative_path}\n", encoding="utf-8")


class Issue20ContractHashTests(unittest.TestCase):
    def test_implementation_deploy_contract_paths_are_exact(self) -> None:
        self.assertEqual(
            ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS,
            (
                "deploy/connected/Caddyfile.example",
                "deploy/connected/compose.env.example",
                "deploy/connected/operator_config.py",
                "deploy/connected/secrets/README.md",
                "deploy/connected/signing-key-set.example.json",
            ),
        )
        self.assertEqual(
            tuple(
                pattern
                for pattern in ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS
                if pattern.startswith("deploy/connected/")
            ),
            ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS,
        )

    def test_hash_is_stable_and_changes_with_required_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-issue20-contract-") as value:
            root = Path(value)
            _write_fixture(root)

            first = issue20_implementation_contract_hash(root)
            repeated = issue20_implementation_contract_hash(root)
            (root / "compose.yaml").write_text("contract:changed\n", encoding="utf-8")
            changed = issue20_implementation_contract_hash(root)

        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(repeated, first)
        self.assertRegex(changed, r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(changed, first)

    def test_hash_changes_with_each_required_deploy_input(self) -> None:
        for relative_path in ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS:
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory(
                    prefix="formowl-issue20-contract-deploy-drift-"
                ) as value:
                    root = Path(value)
                    _write_fixture(root)
                    current = issue20_implementation_contract_hash(root)
                    (root / relative_path).write_text(
                        f"contract:changed:{relative_path}\n",
                        encoding="utf-8",
                    )
                    changed = issue20_implementation_contract_hash(root)

                self.assertRegex(changed, r"^sha256:[0-9a-f]{64}$")
                self.assertNotEqual(changed, current)

    def test_hash_fails_closed_when_required_deploy_input_is_missing(self) -> None:
        for relative_path in ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS:
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory(
                    prefix="formowl-issue20-contract-deploy-missing-"
                ) as value:
                    root = Path(value)
                    _write_fixture(root)
                    (root / relative_path).unlink()

                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^issue20_implementation_contract_missing$",
                    ):
                        issue20_implementation_contract_hash(root)

    def test_hash_excludes_ignored_operator_state_and_secret_files(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="formowl-issue20-contract-ignored-operator-"
        ) as value:
            root = Path(value)
            _write_fixture(root)
            operator_state = root / ".formowl/issue20/operator-state.json"
            ignored_secret = root / "deploy/connected/secrets/database-dsn"
            for path in (operator_state, ignored_secret):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ignored:first\n", encoding="utf-8")

            current = issue20_implementation_contract_hash(root)
            operator_state.write_text("ignored:second\n", encoding="utf-8")
            ignored_secret.write_text("ignored:second\n", encoding="utf-8")
            repeated = issue20_implementation_contract_hash(root)

        self.assertEqual(repeated, current)

    def test_hash_rejects_required_file_symlink_without_reading_external_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-issue20-contract-symlink-") as value:
            root = Path(value)
            _write_fixture(root)
            victim = root.parent / f"{root.name}-external-victim"
            victim.write_bytes(b"external-contract-secret")
            compose = root / "compose.yaml"
            compose.unlink()
            compose.symlink_to(victim)
            try:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^issue20_implementation_contract_invalid$",
                ) as caught:
                    issue20_implementation_contract_hash(root)
            finally:
                victim_bytes = victim.read_bytes()
                victim.unlink()

        self.assertEqual(victim_bytes, b"external-contract-secret")
        self.assertNotIn(str(root), str(caught.exception))
        self.assertNotIn(str(victim), str(caught.exception))

    def test_hash_rejects_symlinked_required_directory_path_escape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-issue20-contract-escape-") as value:
            root = Path(value)
            _write_fixture(root)
            external = root.parent / f"{root.name}-external-auth"
            external.mkdir()
            (external / "contract.py").write_bytes(b"external-contract-secret")
            auth_directory = root / "python/formowl_auth"
            (auth_directory / "contract.py").unlink()
            auth_directory.rmdir()
            auth_directory.symlink_to(external, target_is_directory=True)
            try:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^issue20_implementation_contract_invalid$",
                ) as caught:
                    issue20_implementation_contract_hash(root)
            finally:
                external_bytes = (external / "contract.py").read_bytes()
                (external / "contract.py").unlink()
                external.rmdir()

        self.assertEqual(external_bytes, b"external-contract-secret")
        self.assertNotIn(str(root), str(caught.exception))
        self.assertNotIn(str(external), str(caught.exception))

    def test_hash_rejects_non_regular_required_file_without_blocking_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-issue20-contract-fifo-") as value:
            root = Path(value)
            _write_fixture(root)
            compose = root / "compose.yaml"
            compose.unlink()
            os.mkfifo(compose)

            with self.assertRaisesRegex(
                RuntimeError,
                "^issue20_implementation_contract_invalid$",
            ) as caught:
                issue20_implementation_contract_hash(root)

            self.assertTrue(compose.exists())

        self.assertNotIn(str(root), str(caught.exception))
        self.assertNotIn("compose.yaml", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
