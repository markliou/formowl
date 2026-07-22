from __future__ import annotations

import ast
from fnmatch import fnmatchcase
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import _paths  # noqa: F401

from formowl_evidence.issue20 import issue20_implementation_contract_hash


ROOT = Path(__file__).resolve().parents[1]
SECRETS_PREFIX = "deploy/connected/secrets"


def _dockerignore_patterns() -> tuple[str, ...]:
    return tuple(
        line
        for raw_line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    )


def _is_ignored(path: str, patterns: tuple[str, ...]) -> bool:
    ignored = False
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        if pattern.endswith("/**"):
            prefix = pattern.removesuffix("/**")
            matched = path == prefix or path.startswith(f"{prefix}/")
        else:
            normalized_path = path.rstrip("/")
            normalized_pattern = pattern.rstrip("/")
            candidates = (normalized_path,)
            if pattern.endswith("/"):
                parts = normalized_path.split("/")
                candidates = tuple("/".join(parts[:index]) for index in range(1, len(parts) + 1))
            matched = any(
                fnmatchcase(candidate, normalized_pattern)
                or (
                    normalized_pattern.startswith("**/")
                    and fnmatchcase(candidate, normalized_pattern.removeprefix("**/"))
                )
                for candidate in candidates
            )
        if matched:
            ignored = not negated
    return ignored


def _compose_default_secret_paths() -> set[str]:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    return set(
        re.findall(
            r"(?m)^\s*file:\s+\$\{[^:}]+:-\./(deploy/connected/secrets/[^}]+)\}\s*$",
            compose,
        )
    )


def _initializer_secret_filenames() -> set[str]:
    source_path = ROOT / "python/formowl_gateway/secret_init.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_SECRET_FILENAMES"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
            return set(value)
    raise AssertionError("secret initializer filename contract is unavailable")


class DockerBuildContextSecretBoundaryTest(unittest.TestCase):
    def _docker_with_daemon(self) -> str:
        docker = shutil.which("docker")
        if docker is None:
            self.skipTest("docker CLI is unavailable")
        daemon = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if daemon.returncode != 0:
            self.skipTest("docker daemon is unavailable")
        return docker

    def test_local_build_and_lint_artifacts_are_ignored(self) -> None:
        patterns = _dockerignore_patterns()

        self.assertIn(".ruff_cache/", patterns)
        self.assertIn("build/", patterns)

    def test_python_cache_artifacts_are_recursively_ignored(self) -> None:
        patterns = _dockerignore_patterns()

        for pattern in ("**/__pycache__/", "**/*.pyc", "**/*.pyo"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, patterns)
        self.assertNotIn("__pycache__", patterns)
        self.assertNotIn("*.pyc", patterns)

    def test_python_generated_metadata_and_coverage_are_recursively_ignored(self) -> None:
        patterns = _dockerignore_patterns()

        for pattern in ("**/.coverage", "**/.coverage.*", "**/*.egg-info/"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, patterns)

        ignored_artifacts = (
            ".coverage",
            ".coverage.host.12345",
            "python/.coverage",
            "python/package/.coverage.worker",
            "formowl.egg-info/PKG-INFO",
            "python/formowl.egg-info/SOURCES.txt",
            "python/nested/formowl_plugin.egg-info/requires.txt",
        )
        for path in ignored_artifacts:
            with self.subTest(path=path):
                self.assertTrue(_is_ignored(path, patterns))

        ordinary_source = (
            ".coveragerc",
            "pyproject.toml",
            "python/formowl_core/__init__.py",
            "python/formowl_egg_info.py",
        )
        for path in ordinary_source:
            with self.subTest(path=path):
                self.assertFalse(_is_ignored(path, patterns))

    def test_compose_and_initializer_secret_contracts_are_fully_ignored(self) -> None:
        patterns = _dockerignore_patterns()
        initializer_paths = {
            f"{SECRETS_PREFIX}/{filename}" for filename in _initializer_secret_filenames()
        }
        compose_paths = _compose_default_secret_paths()

        self.assertEqual(
            compose_paths,
            initializer_paths | {f"{SECRETS_PREFIX}/google-client-secret"},
        )
        for path in sorted(compose_paths | initializer_paths):
            with self.subTest(path=path):
                self.assertTrue(_is_ignored(path, patterns))

        docker = self._docker_with_daemon()

        with tempfile.TemporaryDirectory(
            prefix="formowl-docker-context-",
        ) as temporary_directory:
            temporary_root = Path(temporary_directory)
            context = temporary_root / "context"
            output = temporary_root / "snapshot"
            dockerfile = temporary_root / "source-snapshot.Dockerfile"
            context.mkdir()
            output.mkdir()
            shutil.copy2(ROOT / ".dockerignore", context / ".dockerignore")
            dockerfile.write_text(
                "\n".join(
                    (
                        "FROM scratch",
                        "ARG SNAPSHOT_UID",
                        "ARG SNAPSHOT_GID",
                        "COPY --chown=${SNAPSHOT_UID}:${SNAPSHOT_GID} . /",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            included_paths = (
                "deploy/connected/Caddyfile.example",
                "deploy/connected/compose.env.example",
                "deploy/connected/signing-key-set.example.json",
                "deploy/connected/secrets/README.md",
                "python/formowl_core/__init__.py",
            )
            excluded_paths = (
                ".formowl/issue20/Caddyfile",
                ".formowl/issue20/compose.env",
                "deploy/connected/Caddyfile",
                "deploy/connected/compose.env",
                "deploy/connected/secrets/google-client-secret",
            )
            for path in included_paths + excluded_paths:
                candidate = context / path
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text(f"fixture:{path}\n", encoding="utf-8")

            result = subprocess.run(
                [
                    docker,
                    "build",
                    "--file",
                    str(dockerfile),
                    "--build-arg",
                    f"SNAPSHOT_UID={os.getuid()}",
                    "--build-arg",
                    f"SNAPSHOT_GID={os.getgid()}",
                    "--output",
                    f"type=local,dest={output}",
                    str(context),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            for path in included_paths:
                with self.subTest(path=path):
                    self.assertTrue((output / path).is_file())
            for path in excluded_paths:
                with self.subTest(path=path):
                    self.assertFalse((output / path).exists())

    def test_real_buildkit_snapshot_preserves_implementation_contract_hash(self) -> None:
        docker = self._docker_with_daemon()

        with tempfile.TemporaryDirectory(
            prefix="formowl-issue20-buildkit-contract-",
        ) as temporary_directory:
            temporary_root = Path(temporary_directory)
            output = temporary_root / "snapshot"
            dockerfile = temporary_root / "source-snapshot.Dockerfile"
            output.mkdir()
            dockerfile.write_text(
                "\n".join(
                    (
                        "FROM scratch",
                        "ARG SNAPSHOT_UID",
                        "ARG SNAPSHOT_GID",
                        "COPY --chown=${SNAPSHOT_UID}:${SNAPSHOT_GID} . /",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["DOCKER_BUILDKIT"] = "1"

            result = subprocess.run(
                [
                    docker,
                    "build",
                    "--file",
                    str(dockerfile),
                    "--build-arg",
                    f"SNAPSHOT_UID={os.getuid()}",
                    "--build-arg",
                    f"SNAPSHOT_GID={os.getgid()}",
                    "--output",
                    f"type=local,dest={output}",
                    str(ROOT),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            current_hash = issue20_implementation_contract_hash(ROOT)
            snapshot_hash = issue20_implementation_contract_hash(output)

        self.assertEqual(snapshot_hash, current_hash)

    def test_lock_partial_staging_and_quarantine_paths_are_fully_ignored(self) -> None:
        patterns = _dockerignore_patterns()
        transient_secret_paths = {
            f"{SECRETS_PREFIX}/.formowl-secret-init.lock",
            f"{SECRETS_PREFIX}/database-dsn.partial",
            f"{SECRETS_PREFIX}/.formowl-secret-init-crashed/database-dsn",
            f"{SECRETS_PREFIX}/.formowl-secret-init-crashed/signing-current.pem",
            f"{SECRETS_PREFIX}/.formowl-secret-recovery-deadbeef/postgres-password",
            (
                f"{SECRETS_PREFIX}/.formowl-secret-recovery-deadbeef/"
                "stale-staging/entry-1/state-encryption-key"
            ),
        }

        for path in sorted(transient_secret_paths):
            with self.subTest(path=path):
                self.assertTrue(_is_ignored(path, patterns))

    def test_only_safe_connected_secret_documentation_is_reincluded(self) -> None:
        patterns = _dockerignore_patterns()
        secret_negations = tuple(
            pattern for pattern in patterns if pattern.startswith(f"!{SECRETS_PREFIX}/")
        )
        operator_paths = (
            "deploy/connected/Caddyfile",
            "deploy/connected/compose.env",
        )
        sample_paths = (
            "deploy/connected/Caddyfile.example",
            "deploy/connected/compose.env.example",
            "deploy/connected/signing-key-set.example.json",
        )

        self.assertIn(f"{SECRETS_PREFIX}/**", patterns)
        self.assertEqual(secret_negations, (f"!{SECRETS_PREFIX}/README.md",))
        self.assertFalse(_is_ignored(f"{SECRETS_PREFIX}/README.md", patterns))
        self.assertFalse(_is_ignored("deploy/connected/signing-key-set.example.json", patterns))
        for path in operator_paths:
            with self.subTest(path=path):
                ignored = subprocess.run(
                    [
                        "git",
                        "-c",
                        f"safe.directory={ROOT}",
                        "check-ignore",
                        "--no-index",
                        "--quiet",
                        path,
                    ],
                    cwd=ROOT,
                    check=False,
                )
                self.assertEqual(ignored.returncode, 0)
        for path in sample_paths:
            with self.subTest(path=path):
                included = subprocess.run(
                    [
                        "git",
                        "-c",
                        f"safe.directory={ROOT}",
                        "check-ignore",
                        "--no-index",
                        "--quiet",
                        path,
                    ],
                    cwd=ROOT,
                    check=False,
                )
                self.assertEqual(included.returncode, 1)


if __name__ == "__main__":
    unittest.main()
