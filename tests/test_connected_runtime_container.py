from __future__ import annotations

import asyncio
from collections.abc import Mapping
import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone, tzinfo
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEV_DOCKERFILE = ROOT / "containers" / "dev" / "Dockerfile"
RUNTIME_DOCKERFILE = ROOT / "containers" / "runtime" / "Dockerfile"
COMPOSE_FILE = ROOT / "compose.yaml"
SECRET_INIT_README = ROOT / "deploy" / "connected" / "secrets" / "README.md"
LIFECYCLE_PROBE = ROOT / "scripts" / "connected_runtime_container_lifecycle_probe.py"
CAPABILITY_PROBE = ROOT / "tests" / "issue20_capability_bounding_set_probe.py"
CAPABILITY_LIVE_RUNNER = ROOT / "tests" / "run_issue20_capability_bounding_set_live_regression.sh"
CAPABILITY_LIVE_ENV = "FORMOWL_RUN_CAPABILITY_BOUNDING_SET_LIVE"
CAPABILITY_RUNTIME_IMAGE_TAG = "formowl-runtime:issue20-capability-bounding-set-live"
CAPABILITY_LAUNCHER_SET = ("CHOWN", "DAC_READ_SEARCH", "SETPCAP", "SETGID", "SETUID")


def _stage_wheel_source(destination: Path) -> None:
    destination.mkdir()
    for filename in ("pyproject.toml", "README.md"):
        shutil.copy2(ROOT / filename, destination / filename)
    shutil.copytree(
        ROOT / "python",
        destination / "python",
        ignore=shutil.ignore_patterns(
            "build",
            "*.egg-info",
            "__pycache__",
            "*.pyc",
        ),
    )


def _load_lifecycle_probe():
    spec = importlib.util.spec_from_file_location(
        "connected_runtime_container_lifecycle_probe",
        LIFECYCLE_PROBE,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load connected runtime lifecycle probe")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConnectedRuntimeContainerTests(unittest.TestCase):
    def test_capability_bounding_set_live_runner_is_read_only_and_socket_gid_bound(
        self,
    ) -> None:
        source = CAPABILITY_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("SOCKET_GID=$(/usr/bin/stat -c '%g' \"$DOCKER_SOCKET\")", source)
        self.assertIn('--group-add "$SOCKET_GID"', source)
        self.assertIn("--read-only", source)
        self.assertIn("--cap-drop ALL", source)
        self.assertIn("--security-opt no-new-privileges:true", source)
        self.assertIn('--volume "$ROOT:$ROOT:ro"', source)
        self.assertIn('--volume "$DOCKER_SOCKET:$DOCKER_SOCKET"', source)
        self.assertIn(
            "--env FORMOWL_RUN_CAPABILITY_BOUNDING_SET_LIVE=1",
            source,
        )
        self.assertIn("formowl-dev:local", source)
        self.assertNotIn("--privileged", source)

    @unittest.skipUnless(
        os.environ.get(CAPABILITY_LIVE_ENV) == "1",
        f"{CAPABILITY_LIVE_ENV}=1 is required",
    )
    def test_capability_bounding_set_container_ab_regression(self) -> None:
        docker = shutil.which("docker")
        self.assertIsNotNone(docker)
        docker_socket = Path("/var/run/docker.sock")
        socket_metadata = docker_socket.stat()
        self.assertTrue(stat.S_ISSOCK(socket_metadata.st_mode))
        self.assertIn(
            socket_metadata.st_gid,
            {os.getgid(), *os.getgroups()},
        )
        self.assertEqual(
            os.environ.get("DOCKER_HOST"),
            "unix:///var/run/docker.sock",
        )

        with tempfile.TemporaryDirectory(
            prefix="formowl-capability-live-",
            dir=tempfile.gettempdir(),
        ) as directory:
            docker_config = Path(directory) / "docker-config"
            docker_config.mkdir(mode=0o700)
            environment = dict(os.environ)
            environment["DOCKER_CONFIG"] = str(docker_config)
            environment["HOME"] = directory
            environment["DOCKER_HOST"] = "unix:///var/run/docker.sock"
            for name in (
                "DOCKER_CONTEXT",
                "DOCKER_CLI_PLUGIN_EXTRA_DIRS",
                "BUILDX_CONFIG",
                "BUILDKIT_HOST",
            ):
                environment.pop(name, None)

            build = subprocess.run(
                [
                    docker,
                    "build",
                    "--file",
                    str(RUNTIME_DOCKERFILE),
                    "--tag",
                    CAPABILITY_RUNTIME_IMAGE_TAG,
                    str(ROOT),
                ],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr[-4000:])
            inspect = subprocess.run(
                [
                    docker,
                    "image",
                    "inspect",
                    "--format={{.Id}}",
                    CAPABILITY_RUNTIME_IMAGE_TAG,
                ],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            image_id = inspect.stdout.strip()
            self.assertRegex(image_id, r"^sha256:[0-9a-f]{64}$")

            common_command = [
                docker,
                "run",
                "--rm",
                "--read-only",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
            ]
            for capability in CAPABILITY_LAUNCHER_SET:
                common_command.extend(["--cap-add", capability])
            common_command.extend(
                [
                    "--security-opt",
                    "no-new-privileges:true",
                    "--tmpfs",
                    "/tmp:size=16m,mode=1777",
                    "--volume",
                    f"{ROOT}:{ROOT}:ro",
                    "--workdir",
                    str(ROOT),
                    "--entrypoint",
                    "/usr/local/bin/python",
                    image_id,
                    str(CAPABILITY_PROBE),
                    "--phase",
                    "launch",
                    "--repository-root",
                    str(ROOT),
                    "--arm",
                ]
            )
            pre_command = [*common_command, "pre_fix_control"]
            post_command = [*common_command, "post_fix"]
            self.assertEqual(pre_command[:-1], post_command[:-1])

            results: dict[str, dict[str, object]] = {}
            for arm, command in (
                ("pre_fix_control", pre_command),
                ("post_fix", post_command),
            ):
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stderr, "")
                lines = completed.stdout.splitlines()
                self.assertEqual(len(lines), 1)
                payload = json.loads(lines[0])
                self.assertEqual(
                    set(payload),
                    {
                        "arm",
                        "artifact_type",
                        "capability_sets",
                        "entrypoint_main_exercised",
                        "gid",
                        "no_new_privs",
                        "status",
                        "supplementary_group_count",
                        "uid",
                    },
                )
                self.assertEqual(payload["arm"], arm)
                self.assertEqual(
                    payload["artifact_type"],
                    "issue20_capability_bounding_set_probe_v1",
                )
                self.assertIs(payload["entrypoint_main_exercised"], True)
                self.assertEqual(payload["status"], "passed")
                self.assertNotIn(str(ROOT), completed.stdout)
                results[arm] = payload

            pre_control = results["pre_fix_control"]
            post_fix = results["post_fix"]
            for payload in (pre_control, post_fix):
                self.assertEqual(payload["uid"], 10001)
                self.assertEqual(payload["gid"], 10001)
                self.assertEqual(payload["supplementary_group_count"], 0)
                self.assertEqual(payload["no_new_privs"], 1)
                self.assertEqual(
                    set(payload["capability_sets"]),
                    {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"},
                )
            self.assertNotEqual(
                int(pre_control["capability_sets"]["CapBnd"], 16),
                0,
            )
            self.assertTrue(
                all(int(value, 16) == 0 for value in post_fix["capability_sets"].values())
            )

    def test_production_auth_import_does_not_emit_installed_source_path_warning(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "python")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        result = subprocess.run(
            [sys.executable, "-c", "import formowl_auth"],
            cwd="/tmp",
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_dev_and_runtime_images_install_declared_project_dependencies(self) -> None:
        dev = DEV_DOCKERFILE.read_text(encoding="utf-8")
        runtime = RUNTIME_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            'python -m pip install --no-cache-dir --no-build-isolation ".[dev]"',
            dev,
        )
        self.assertIn(
            "python -m pip wheel --no-cache-dir --no-build-isolation --wheel-dir /wheels .",
            runtime,
        )
        self.assertIn("python -m pip install --no-cache-dir /wheels/*.whl", runtime)
        self.assertIn('ENTRYPOINT ["formowl-container-entrypoint"]', runtime)
        self.assertIn('CMD ["serve"]', runtime)
        final_stage = runtime.split("FROM python:3.13-slim", 2)[-1]
        self.assertNotIn("PYTHONPATH", final_stage)
        self.assertNotIn("COPY python", final_stage)
        self.assertIn("USER root", final_stage)

    def test_built_wheel_contains_all_migrations_and_connected_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="formowl-wheel-",
            dir=tempfile.gettempdir(),
        ) as directory:
            temporary_root = Path(directory)
            staged_source = temporary_root / "source"
            wheel_directory = temporary_root / "wheelhouse"
            _stage_wheel_source(staged_source)

            self.assertTrue(staged_source.is_relative_to(Path(tempfile.gettempdir())))
            self.assertNotEqual(staged_source, ROOT)
            self.assertFalse((staged_source / "build").exists())
            self.assertEqual(list(staged_source.rglob("*.egg-info")), [])
            self.assertEqual(list(staged_source.rglob("__pycache__")), [])
            self.assertEqual(list(staged_source.rglob("*.pyc")), [])

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-build-isolation",
                    "--no-deps",
                    "--wheel-dir",
                    str(wheel_directory),
                    str(staged_source),
                ],
                cwd="/tmp",
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            wheels = list(wheel_directory.glob("formowl-*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
                self.assertIn("formowl_evidence/issue20.py", names)
                migration_names = {
                    name
                    for name in names
                    if name.startswith("formowl_graph/storage/migrations/")
                    and name.endswith(".sql")
                }
                self.assertEqual(
                    migration_names,
                    {
                        f"formowl_graph/storage/migrations/{index:03d}_{suffix}.sql"
                        for index, suffix in (
                            (1, "metadata_store"),
                            (2, "vector_index"),
                            (3, "ingestion_records"),
                            (4, "mail_evidence"),
                            (5, "oauth_identity"),
                        )
                    },
                )
                entry_points_name = next(
                    name for name in names if name.endswith(".dist-info/entry_points.txt")
                )
                entry_points = archive.read(entry_points_name).decode("utf-8")
                self.assertIn(
                    "formowl-container-entrypoint = formowl_gateway.container_entrypoint:main",
                    entry_points,
                )
                self.assertIn(
                    "formowl-connected-mcp = formowl_gateway.runtime:main",
                    entry_points,
                )

    def test_compose_preserves_legacy_services_and_adds_connected_postgres_stack(self) -> None:
        compose = COMPOSE_FILE.read_text(encoding="utf-8")

        self.assertIn("postgres:", compose)
        self.assertIn(
            "image: ${FORMOWL_POSTGRES_IMAGE:-pgvector/pgvector@sha256:"
            "131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6}",
            compose,
        )
        self.assertIn("image: ${FORMOWL_RUNTIME_IMAGE:-formowl-runtime:local}", compose)
        self.assertIn("connected-migrate:", compose)
        self.assertIn("connected-mcp:", compose)
        self.assertNotIn("connected-init-secrets:", compose)
        self.assertIn("condition: service_completed_successfully", compose)
        self.assertIn("/readyz", compose)
        self.assertIn("/healthz", compose)
        self.assertIn(
            "https://invalid.example.invalid/formowl-discovery-only",
            compose,
        )
        self.assertIn("stop_grace_period: 30s", compose)
        self.assertIn("FORMOWL_OAUTH_SIGNING_KEY_SET_FILE", compose)
        self.assertIn("/run/secrets/formowl_database_dsn", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("project-mcp:", compose)
        self.assertIn("wiki-mcp:", compose)
        self.assertIn('command: ["python", "-m", "formowl_project_mcp"]', compose)
        self.assertIn('command: ["python", "-m", "formowl_wiki_mcp"]', compose)
        self.assertNotIn('entrypoint: ["python", "-m", "formowl_project_mcp"]', compose)
        self.assertNotIn('entrypoint: ["python", "-m", "formowl_wiki_mcp"]', compose)

        bootstrap = SECRET_INIT_README.read_text(encoding="utf-8")
        self.assertIn("docker build -f containers/runtime/Dockerfile", bootstrap)
        self.assertIn("formowl-runtime:local init-secrets --output-dir /secrets", bootstrap)
        self.assertNotIn("docker compose run connected-mcp init-secrets", bootstrap)

    def test_operator_docs_pin_exact_callback_and_discovery_only_boundary(self) -> None:
        documents = {
            relative_path: (ROOT / relative_path).read_text(encoding="utf-8")
            for relative_path in (
                "SPEC.md",
                "README.md",
                "docs/closed-beta-runbook.md",
                "docs/issue20-oauth-evidence-runbook.md",
                "docs/infra-spec.md",
                "docs/mcp-boundaries.md",
                "docs/workflows.md",
            )
        }
        production_callback = "https://chatgpt.com/connector/oauth/{callback_id}"
        discovery_sentinel = "https://invalid.example.invalid/formowl-discovery-only"

        for relative_path, document in documents.items():
            with self.subTest(relative_path=relative_path):
                self.assertIn(production_callback, document)

        for relative_path in (
            "README.md",
            "docs/closed-beta-runbook.md",
            "docs/issue20-oauth-evidence-runbook.md",
            "docs/infra-spec.md",
            "docs/mcp-boundaries.md",
        ):
            document = documents[relative_path]
            self.assertIn(discovery_sentinel, document)
            self.assertIn("discovery_only", document)
            self.assertIn("initialize", document)
            self.assertIn("tools/list", document)
            self.assertIn("/readyz", document)
            self.assertIn("bootstrap", document)
            self.assertIn("audit", document)
            self.assertIn("challenge", document)
            self.assertIn("restart", document)

        for relative_path in (
            "docs/closed-beta-runbook.md",
            "docs/issue20-oauth-evidence-runbook.md",
            "docs/infra-spec.md",
        ):
            self.assertIn("/healthz", documents[relative_path])

        combined = "\n".join(documents.values())
        self.assertIn("stable non-secret", combined)
        self.assertIn("external live blocker", combined)
        self.assertIn("supplies and displays only", combined)
        self.assertNotIn("FORMOWL_CHATGPT_CLIENT_ID=formowl-discovery-only", combined)
        self.assertNotIn("FORMOWL_CHATGPT_CLIENT_ID='formowl-discovery-only'", combined)
        self.assertNotIn("UI-supplied predefined client ID", combined)
        self.assertNotIn("paired `formowl-discovery-only`", combined)

    def test_jsonable_rejects_stringified_mapping_key_collision_safely(self) -> None:
        module = _load_lifecycle_probe()
        integer_value = "unique-integer-value-/tmp/private-jsonable-integer"
        string_value = "unique-string-value-/tmp/private-jsonable-string"
        payload = {
            1: integer_value,
            "1": string_value,
        }
        original_payload = copy.deepcopy(payload)
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._jsonable(payload)
            except module.LifecycleProbeFailure as error:
                failure = error
            else:
                self.fail("jsonable accepted colliding mapping keys")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "jsonable_mapping_key_invalid")
        self.assertIs(actual, result_marker)
        public_text = public_stdout.getvalue() + public_stderr.getvalue()
        for private_detail in (
            "1",
            integer_value,
            string_value,
            "/tmp/private-jsonable-integer",
            "/tmp/private-jsonable-string",
        ):
            self.assertNotIn(private_detail, str(failure))
            self.assertNotIn(private_detail, public_text)
        self.assertTrue(payload == original_payload)
        self.assertTrue(list(payload) == [1, "1"])
        self.assertIs(payload[1], integer_value)
        self.assertIs(payload["1"], string_value)

    def test_jsonable_bounds_mapping_snapshot_failure_without_mutation(self) -> None:
        module = _load_lifecycle_probe()
        private_detail = "unique-mapping-items-/tmp/private-jsonable-mapping"

        class HostileMapping(Mapping[str, object]):
            def __init__(self) -> None:
                self.payload = {"alpha": "stable-value"}
                self.private_detail = private_detail
                self.render_calls = 0

            def __getitem__(self, key: str) -> object:
                return self.payload[key]

            def __iter__(self):
                return iter(self.payload)

            def __len__(self) -> int:
                return len(self.payload)

            def items(self):
                raise RuntimeError(self.private_detail)

            def __str__(self) -> str:
                self.render_calls += 1
                return self.private_detail

            def __repr__(self) -> str:
                self.render_calls += 1
                return self.private_detail

        value = HostileMapping()
        original_state = copy.deepcopy(vars(value))
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._jsonable(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            except Exception:
                raise AssertionError("jsonable leaked a mapping snapshot failure") from None
            else:
                self.fail("jsonable accepted a failed mapping snapshot")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "jsonable_mapping_invalid")
        self.assertIs(actual, result_marker)
        self.assertTrue(vars(value) == original_state)
        self.assertEqual(value.render_calls, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for leaked_detail in (
            private_detail,
            "/tmp/private-jsonable-mapping",
            "stable-value",
        ):
            self.assertNotIn(leaked_detail, str(failure))

        class StableGenericMapping(Mapping[str, object]):
            def __init__(self) -> None:
                self.payload = {
                    "alpha": "mapping-value",
                    "nested": {"count": 3},
                }

            def __getitem__(self, key: str) -> object:
                return self.payload[key]

            def __iter__(self):
                return iter(self.payload)

            def __len__(self) -> int:
                return len(self.payload)

        stable_value = StableGenericMapping()
        original_stable_state = copy.deepcopy(vars(stable_value))
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()
        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            stable_actual = module._jsonable(stable_value)

        self.assertEqual(
            stable_actual,
            {
                "alpha": "mapping-value",
                "nested": {"count": 3},
            },
        )
        self.assertIs(type(stable_actual), dict)
        self.assertTrue(vars(stable_value) == original_stable_state)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")

    def test_jsonable_rejects_unsupported_value_without_stringification(self) -> None:
        module = _load_lifecycle_probe()
        private_detail = "unique-unsupported-value-/tmp/private-jsonable-value"

        class HostileUnsupportedValue:
            def __init__(self) -> None:
                self.stringified = False
                self.private_detail = private_detail

            def __str__(self) -> str:
                self.stringified = True
                return self.private_detail

        value = HostileUnsupportedValue()
        original_state = dict(vars(value))
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._jsonable(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            except Exception:
                raise AssertionError(
                    "jsonable invoked unsafe unsupported value conversion"
                ) from None
            else:
                self.fail("jsonable accepted an unsupported value")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "jsonable_value_invalid")
        self.assertIs(actual, result_marker)
        self.assertFalse(value.stringified)
        self.assertTrue(vars(value) == original_state)
        public_text = public_stdout.getvalue() + public_stderr.getvalue()
        for leaked_detail in (
            private_detail,
            "/tmp/private-jsonable-value",
        ):
            self.assertNotIn(leaked_detail, str(failure))
            self.assertNotIn(leaked_detail, public_text)

    def test_jsonable_rejects_unordered_set_without_partial_result(self) -> None:
        module = _load_lifecycle_probe()
        first_value = "unique-set-value-a-/tmp/private-jsonable-set-a"
        second_value = "unique-set-value-b-/tmp/private-jsonable-set-b"
        value = {
            first_value,
            second_value,
        }
        original_value = set(value)
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        self.assertIs(type(value), set)
        self.assertNotIsInstance(value, (list, tuple))
        self.assertTrue(all(type(item) is str for item in value))

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._jsonable(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            else:
                self.fail("jsonable accepted an unordered set")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "jsonable_set_invalid")
        self.assertIs(actual, result_marker)
        self.assertTrue(value == original_value)
        public_text = public_stdout.getvalue() + public_stderr.getvalue()
        for leaked_detail in (
            first_value,
            second_value,
            "/tmp/private-jsonable-set-a",
            "/tmp/private-jsonable-set-b",
        ):
            self.assertNotIn(leaked_detail, str(failure))
            self.assertNotIn(leaked_detail, public_text)

    def test_jsonable_rejects_non_finite_numbers_and_preserves_finite_float(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        non_finite_cases = (
            ("case_a", float("nan")),
            ("case_b", float("inf")),
            ("case_c", float("-inf")),
        )

        for scenario, value in non_finite_cases:
            with self.subTest(scenario=scenario):
                original_classification = (
                    math.isnan(value),
                    math.isinf(value),
                    math.copysign(1.0, value),
                )
                result_marker = object()
                actual = result_marker
                failure = None
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()

                with (
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    try:
                        actual = module._jsonable(value)
                    except module.LifecycleProbeFailure as error:
                        failure = error
                    else:
                        self.fail("jsonable accepted a non-finite number")

                self.assertIsNotNone(failure)
                self.assertEqual(failure.stage, "inside_serialization")
                self.assertEqual(failure.code, "jsonable_number_invalid")
                self.assertIs(actual, result_marker)
                self.assertEqual(
                    (
                        math.isnan(value),
                        math.isinf(value),
                        math.copysign(1.0, value),
                    ),
                    original_classification,
                )
                public_text = public_stdout.getvalue() + public_stderr.getvalue()
                self.assertNotIn(repr(value), str(failure))
                self.assertNotIn(repr(value), public_text)

        finite_value = 1.25
        original_finite_value = finite_value
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()
        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            actual = module._jsonable(finite_value)

        self.assertIs(type(actual), float)
        self.assertEqual(actual, 1.25)
        self.assertEqual(finite_value, original_finite_value)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")

    def test_jsonable_rejects_naive_datetime_without_rendering(self) -> None:
        module = _load_lifecycle_probe()
        value = datetime(2042, 11, 23, 17, 58, 49, 654321)
        original_components = (
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            value.fold,
        )
        rendered_detail = value.isoformat()
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        self.assertIsNone(value.tzinfo)

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._jsonable(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            else:
                self.fail("jsonable accepted a naive datetime")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "jsonable_datetime_invalid")
        self.assertIs(actual, result_marker)
        self.assertEqual(
            (
                value.year,
                value.month,
                value.day,
                value.hour,
                value.minute,
                value.second,
                value.microsecond,
                value.tzinfo,
                value.fold,
            ),
            original_components,
        )
        public_text = public_stdout.getvalue() + public_stderr.getvalue()
        for leaked_detail in (
            rendered_detail,
            repr(value),
            "2042",
            "654321",
        ):
            self.assertNotIn(leaked_detail, str(failure))
            self.assertNotIn(leaked_detail, public_text)

    def test_jsonable_normalizes_aware_datetime_and_bounds_timezone_failures(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        aware_timezone = timezone(timedelta(hours=8))
        aware_value = datetime(
            2042,
            11,
            23,
            17,
            58,
            49,
            654321,
            tzinfo=aware_timezone,
        )
        original_aware_components = (
            aware_value.year,
            aware_value.month,
            aware_value.day,
            aware_value.hour,
            aware_value.minute,
            aware_value.second,
            aware_value.microsecond,
            aware_value.tzinfo,
            aware_value.fold,
        )
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            actual = module._jsonable(aware_value)

        self.assertIs(type(actual), str)
        self.assertEqual(actual, "2042-11-23T09:58:49.654321+00:00")
        self.assertEqual(
            (
                aware_value.year,
                aware_value.month,
                aware_value.day,
                aware_value.hour,
                aware_value.minute,
                aware_value.second,
                aware_value.microsecond,
                aware_value.tzinfo,
                aware_value.fold,
            ),
            original_aware_components,
        )
        self.assertIs(aware_value.tzinfo, aware_timezone)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")

        class TrackedTimezone(tzinfo):
            def __init__(
                self,
                *,
                offset_error: str | None = None,
            ) -> None:
                self.offset_error = offset_error
                self.utcoffset_calls = 0
                self.dst_calls = 0
                self.tzname_calls = 0
                self.render_calls = 0

            def utcoffset(self, _value: datetime | None) -> timedelta | None:
                self.utcoffset_calls += 1
                if self.offset_error is not None:
                    raise RuntimeError(self.offset_error)
                return None

            def dst(self, _value: datetime | None) -> timedelta | None:
                self.dst_calls += 1
                return None

            def tzname(self, _value: datetime | None) -> str | None:
                self.tzname_calls += 1
                return None

            def __str__(self) -> str:
                self.render_calls += 1
                return self.offset_error or "missing-offset-private-detail"

            def __repr__(self) -> str:
                self.render_calls += 1
                return self.offset_error or "missing-offset-private-detail"

        def assert_bounded_failure(
            value: datetime,
            tracked_timezone: TrackedTimezone,
            *,
            private_details: tuple[str, ...] = (),
        ) -> None:
            original_components = (
                value.year,
                value.month,
                value.day,
                value.hour,
                value.minute,
                value.second,
                value.microsecond,
                value.tzinfo,
                value.fold,
            )
            result_marker = object()
            actual = result_marker
            failure = None
            public_stdout = io.StringIO()
            public_stderr = io.StringIO()
            with (
                redirect_stdout(public_stdout),
                redirect_stderr(public_stderr),
            ):
                try:
                    actual = module._jsonable(value)
                except module.LifecycleProbeFailure as error:
                    failure = error
                except Exception:
                    raise AssertionError("jsonable leaked a timezone conversion failure") from None
                else:
                    self.fail("jsonable accepted an invalid aware datetime")

            self.assertIsNotNone(failure)
            self.assertEqual(failure.stage, "inside_serialization")
            self.assertEqual(failure.code, "jsonable_datetime_invalid")
            self.assertIs(actual, result_marker)
            self.assertEqual(
                (
                    value.year,
                    value.month,
                    value.day,
                    value.hour,
                    value.minute,
                    value.second,
                    value.microsecond,
                    value.tzinfo,
                    value.fold,
                ),
                original_components,
            )
            self.assertIs(value.tzinfo, tracked_timezone)
            self.assertEqual(tracked_timezone.utcoffset_calls, 1)
            self.assertEqual(tracked_timezone.dst_calls, 0)
            self.assertEqual(tracked_timezone.tzname_calls, 0)
            self.assertEqual(tracked_timezone.render_calls, 0)
            public_text = public_stdout.getvalue() + public_stderr.getvalue()
            for private_detail in private_details:
                self.assertNotIn(private_detail, str(failure))
                self.assertNotIn(private_detail, public_text)

        missing_offset_timezone = TrackedTimezone()
        assert_bounded_failure(
            datetime(
                2043,
                1,
                2,
                3,
                4,
                5,
                678901,
                tzinfo=missing_offset_timezone,
            ),
            missing_offset_timezone,
        )

        hostile_detail = "unique-hostile-offset-/tmp/private-jsonable-timezone"
        hostile_timezone = TrackedTimezone(offset_error=hostile_detail)
        assert_bounded_failure(
            datetime(
                2044,
                2,
                3,
                4,
                5,
                6,
                789012,
                tzinfo=hostile_timezone,
            ),
            hostile_timezone,
            private_details=(
                hostile_detail,
                "/tmp/private-jsonable-timezone",
            ),
        )

    def test_jsonable_rejects_conflicting_timezone_offsets_without_output(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        private_detail = "unique-conflicting-offset-/tmp/private-jsonable-timezone"

        class ConflictingOffsetTimezone(tzinfo):
            def __init__(self) -> None:
                self.utcoffset_calls = 0
                self.dst_calls = 0
                self.tzname_calls = 0
                self.render_calls = 0

            def utcoffset(self, _value: datetime | None) -> timedelta:
                self.utcoffset_calls += 1
                if self.utcoffset_calls == 1:
                    return timedelta(hours=8)
                return timedelta(hours=9)

            def dst(self, _value: datetime | None) -> timedelta | None:
                self.dst_calls += 1
                return None

            def tzname(self, _value: datetime | None) -> str | None:
                self.tzname_calls += 1
                return None

            def __str__(self) -> str:
                self.render_calls += 1
                return private_detail

            def __repr__(self) -> str:
                self.render_calls += 1
                return private_detail

        tracked_timezone = ConflictingOffsetTimezone()
        value = datetime(
            2046,
            4,
            5,
            18,
            19,
            20,
            123456,
            tzinfo=tracked_timezone,
        )
        original_components = (
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            value.fold,
        )
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._jsonable(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            except Exception:
                raise AssertionError(
                    "jsonable leaked a conflicting timezone conversion failure"
                ) from None
            else:
                self.fail("jsonable accepted conflicting timezone offsets")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "jsonable_datetime_invalid")
        self.assertIs(actual, result_marker)
        self.assertEqual(
            (
                value.year,
                value.month,
                value.day,
                value.hour,
                value.minute,
                value.second,
                value.microsecond,
                value.tzinfo,
                value.fold,
            ),
            original_components,
        )
        self.assertIs(value.tzinfo, tracked_timezone)
        self.assertEqual(tracked_timezone.utcoffset_calls, 2)
        self.assertEqual(tracked_timezone.dst_calls, 0)
        self.assertEqual(tracked_timezone.tzname_calls, 0)
        self.assertEqual(tracked_timezone.render_calls, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for leaked_detail in (
            private_detail,
            "/tmp/private-jsonable-timezone",
            "2046",
            "123456",
        ):
            self.assertNotIn(leaked_detail, str(failure))

    def test_jsonable_supported_value_matrix_is_exact_and_non_mutating(self) -> None:
        module = _load_lifecycle_probe()
        mapping_value = {
            "alpha": "mapping-value",
            "nested": {
                "count": 3,
                "enabled": True,
            },
        }
        list_value = [
            "list-value",
            4,
            False,
            None,
            1.25,
        ]
        tuple_value = (
            "tuple-value",
            5,
            True,
        )
        aware_value = datetime(
            2045,
            3,
            4,
            18,
            19,
            20,
            123456,
            tzinfo=timezone(timedelta(hours=8)),
        )
        cases = (
            (
                "mapping",
                mapping_value,
                {
                    "alpha": "mapping-value",
                    "nested": {
                        "count": 3,
                        "enabled": True,
                    },
                },
                dict,
            ),
            (
                "list",
                list_value,
                [
                    "list-value",
                    4,
                    False,
                    None,
                    1.25,
                ],
                list,
            ),
            (
                "tuple",
                tuple_value,
                [
                    "tuple-value",
                    5,
                    True,
                ],
                list,
            ),
            ("string", "primitive-string", "primitive-string", str),
            ("integer", 7, 7, int),
            ("boolean", True, True, bool),
            ("none", None, None, type(None)),
            ("finite_float", 1.25, 1.25, float),
            (
                "aware_datetime",
                aware_value,
                "2045-03-04T10:19:20.123456+00:00",
                str,
            ),
        )

        self.assertTrue(all(type(key) is str for key in mapping_value))

        for scenario, value, expected, expected_type in cases:
            with self.subTest(scenario=scenario):
                original_value = copy.deepcopy(value)
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()
                with (
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    actual = module._jsonable(value)

                self.assertIs(type(actual), expected_type)
                self.assertEqual(actual, expected)
                self.assertTrue(value == original_value)
                self.assertEqual(public_stdout.getvalue(), "")
                self.assertEqual(public_stderr.getvalue(), "")
                if scenario in {"mapping", "list", "tuple"}:
                    self.assertIsNot(actual, value)

        self.assertEqual(list(mapping_value), ["alpha", "nested"])

    def test_model_dump_bounds_hostile_attribute_access_without_leak(self) -> None:
        module = _load_lifecycle_probe()
        private_detail = "unique-model-dump-attribute-/tmp/private-model-dump"

        class HostileModelDumpAttribute:
            def __init__(self) -> None:
                self.payload = {"stable": "unchanged"}
                self.private_detail = private_detail
                self.render_calls = 0

            def __getattribute__(self, name: str):
                if name == "model_dump":
                    detail = object.__getattribute__(self, "private_detail")
                    raise RuntimeError(detail)
                return object.__getattribute__(self, name)

            def __str__(self) -> str:
                self.render_calls += 1
                return self.private_detail

            def __repr__(self) -> str:
                self.render_calls += 1
                return self.private_detail

        value = HostileModelDumpAttribute()
        original_state = copy.deepcopy(vars(value))
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._model_dump(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            except Exception:
                raise AssertionError("model_dump leaked an attribute failure") from None
            else:
                self.fail("model_dump accepted hostile attribute access")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "model_dump_invalid")
        self.assertIs(actual, result_marker)
        self.assertTrue(vars(value) == original_state)
        self.assertEqual(value.render_calls, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for leaked_detail in (
            private_detail,
            "/tmp/private-model-dump",
            "unchanged",
        ):
            self.assertNotIn(leaked_detail, str(failure))

    def test_model_dump_bounds_callable_failure_without_leak(self) -> None:
        module = _load_lifecycle_probe()
        private_detail = "unique-model-dump-call-/tmp/private-model-dump-call"

        class HostileModelDumpCallable:
            def __init__(self) -> None:
                self.payload = {"stable": "unchanged"}
                self.private_detail = private_detail
                self.render_calls = 0

            def model_dump(
                self,
                *,
                mode: str,
                by_alias: bool,
                exclude_none: bool,
            ):
                raise RuntimeError(self.private_detail)

            def __str__(self) -> str:
                self.render_calls += 1
                return self.private_detail

            def __repr__(self) -> str:
                self.render_calls += 1
                return self.private_detail

        value = HostileModelDumpCallable()
        original_state = copy.deepcopy(vars(value))
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._model_dump(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            except Exception:
                raise AssertionError("model_dump leaked a callable failure") from None
            else:
                self.fail("model_dump accepted a failed callable")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "model_dump_invalid")
        self.assertIs(actual, result_marker)
        self.assertTrue(vars(value) == original_state)
        self.assertEqual(value.render_calls, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for leaked_detail in (
            private_detail,
            "/tmp/private-model-dump-call",
            "unchanged",
        ):
            self.assertNotIn(leaked_detail, str(failure))

    def test_model_dump_rejects_non_callable_attribute_without_rendering(self) -> None:
        module = _load_lifecycle_probe()
        private_detail = "unique-model-dump-value-/tmp/private-model-dump-value"

        class NonCallableModelDump:
            def __init__(self) -> None:
                self.private_detail = private_detail
                self.render_calls = 0

            def __str__(self) -> str:
                self.render_calls += 1
                return self.private_detail

            def __repr__(self) -> str:
                self.render_calls += 1
                return self.private_detail

        class ValueWithNonCallableModelDump:
            def __init__(self, model_dump: NonCallableModelDump) -> None:
                self.model_dump = model_dump
                self.payload = {"stable": "unchanged"}
                self.render_calls = 0

            def __str__(self) -> str:
                self.render_calls += 1
                return private_detail

            def __repr__(self) -> str:
                self.render_calls += 1
                return private_detail

        non_callable = NonCallableModelDump()
        value = ValueWithNonCallableModelDump(non_callable)
        original_payload = copy.deepcopy(value.payload)
        original_non_callable_state = copy.deepcopy(vars(non_callable))
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._model_dump(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            except Exception:
                raise AssertionError("model_dump leaked a non-callable failure") from None
            else:
                self.fail("model_dump accepted a non-callable attribute")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "model_dump_invalid")
        self.assertIs(actual, result_marker)
        self.assertIs(value.model_dump, non_callable)
        self.assertTrue(value.payload == original_payload)
        self.assertEqual(value.render_calls, 0)
        self.assertTrue(vars(non_callable) == original_non_callable_state)
        self.assertEqual(non_callable.render_calls, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for leaked_detail in (
            private_detail,
            "/tmp/private-model-dump-value",
            "unchanged",
        ):
            self.assertNotIn(leaked_detail, str(failure))

    def test_model_dump_invokes_real_callable_once_with_exact_contract(self) -> None:
        module = _load_lifecycle_probe()
        resolution_events: list[str] = []
        invocation_events: list[dict[str, object]] = []

        class OutputValue:
            def __init__(self) -> None:
                self.payload = {"result": "stable"}
                self.render_calls = 0

            def __str__(self) -> str:
                self.render_calls += 1
                return "private-output-render"

            def __repr__(self) -> str:
                self.render_calls += 1
                return "private-output-render"

        output = OutputValue()

        class ModelDumpCallable:
            def __init__(self) -> None:
                self.payload = {"callable": "stable"}
                self.render_calls = 0

            def __call__(
                self,
                *,
                mode: str,
                by_alias: bool,
                exclude_none: bool,
            ) -> OutputValue:
                invocation_events.append(
                    {
                        "mode": mode,
                        "by_alias": by_alias,
                        "exclude_none": exclude_none,
                    }
                )
                return output

            def __str__(self) -> str:
                self.render_calls += 1
                return "private-callable-render"

            def __repr__(self) -> str:
                self.render_calls += 1
                return "private-callable-render"

        model_dump_callable = ModelDumpCallable()

        class ValueWithModelDump:
            def __init__(self) -> None:
                self.model_dump = model_dump_callable
                self.payload = {"input": "stable"}
                self.render_calls = 0

            def __getattribute__(self, name: str):
                if name == "model_dump":
                    resolution_events.append(name)
                return object.__getattribute__(self, name)

            def __str__(self) -> str:
                self.render_calls += 1
                return "private-input-render"

            def __repr__(self) -> str:
                self.render_calls += 1
                return "private-input-render"

        value = ValueWithModelDump()
        original_input_payload = copy.deepcopy(value.payload)
        original_callable_state = copy.deepcopy(vars(model_dump_callable))
        original_output_state = copy.deepcopy(vars(output))
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            actual = module._model_dump(value)

        self.assertIs(actual, output)
        self.assertEqual(resolution_events, ["model_dump"])
        self.assertEqual(
            invocation_events,
            [
                {
                    "mode": "json",
                    "by_alias": True,
                    "exclude_none": True,
                }
            ],
        )
        self.assertIs(object.__getattribute__(value, "model_dump"), model_dump_callable)
        self.assertTrue(value.payload == original_input_payload)
        self.assertEqual(value.render_calls, 0)
        self.assertTrue(vars(model_dump_callable) == original_callable_state)
        self.assertEqual(model_dump_callable.render_calls, 0)
        self.assertTrue(vars(output) == original_output_state)
        self.assertEqual(output.render_calls, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")

    def test_model_dump_returns_missing_attribute_values_by_identity(self) -> None:
        module = _load_lifecycle_probe()
        private_detail = "unique-model-dump-missing-/tmp/private-model-dump-missing"
        lookup_events: list[str] = []

        class ValueWithoutModelDump:
            def __init__(self) -> None:
                self.payload = {"stable": "unchanged"}
                self.private_detail = private_detail
                self.render_calls = 0

            def __getattribute__(self, name: str):
                if name == "model_dump":
                    lookup_events.append(name)
                    detail = object.__getattribute__(self, "private_detail")
                    raise AttributeError(detail)
                return object.__getattribute__(self, name)

            def __str__(self) -> str:
                self.render_calls += 1
                return self.private_detail

            def __repr__(self) -> str:
                self.render_calls += 1
                return self.private_detail

        ordinary = object()
        value = ValueWithoutModelDump()
        original_state = copy.deepcopy(vars(value))
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            ordinary_result = module._model_dump(ordinary)
            tracked_result = module._model_dump(value)

        self.assertIs(ordinary_result, ordinary)
        self.assertIs(tracked_result, value)
        self.assertEqual(lookup_events, ["model_dump"])
        self.assertTrue(vars(value) == original_state)
        self.assertEqual(value.render_calls, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for leaked_detail in (
            private_detail,
            "/tmp/private-model-dump-missing",
            "unchanged",
        ):
            self.assertNotIn(leaked_detail, public_stdout.getvalue())
            self.assertNotIn(leaked_detail, public_stderr.getvalue())

    def test_model_dump_rejects_present_descriptor_attribute_failure(self) -> None:
        module = _load_lifecycle_probe()
        private_detail = "unique-model-dump-descriptor-/tmp/private-model-dump-descriptor"
        resolution_events: list[str] = []

        class ValueWithFailingDescriptor:
            def __init__(self) -> None:
                self.payload = {"stable": "unchanged"}
                self.private_detail = private_detail
                self.render_calls = 0

            @property
            def model_dump(self):
                resolution_events.append("model_dump")
                raise AttributeError(self.private_detail)

            def __str__(self) -> str:
                self.render_calls += 1
                return self.private_detail

            def __repr__(self) -> str:
                self.render_calls += 1
                return self.private_detail

        value = ValueWithFailingDescriptor()
        original_state = copy.deepcopy(vars(value))
        result_marker = object()
        actual = result_marker
        failure = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._model_dump(value)
            except module.LifecycleProbeFailure as error:
                failure = error
            except Exception:
                raise AssertionError("model_dump leaked a descriptor attribute failure") from None
            else:
                self.fail("model_dump accepted a failed present descriptor")

        self.assertIsNotNone(failure)
        self.assertEqual(failure.stage, "inside_serialization")
        self.assertEqual(failure.code, "model_dump_invalid")
        self.assertIs(actual, result_marker)
        self.assertEqual(resolution_events, ["model_dump"])
        self.assertTrue(vars(value) == original_state)
        self.assertEqual(value.render_calls, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for leaked_detail in (
            private_detail,
            "/tmp/private-model-dump-descriptor",
            "unchanged",
        ):
            self.assertNotIn(leaked_detail, str(failure))
            self.assertNotIn(leaked_detail, public_stdout.getvalue())
            self.assertNotIn(leaked_detail, public_stderr.getvalue())

    def test_lifecycle_probe_uses_real_entrypoint_and_hardened_container_flags(self) -> None:
        module = _load_lifecycle_probe()
        source = LIFECYCLE_PROBE.read_text(encoding="utf-8")
        runtime_image_id = "sha256:" + "a" * 64

        command = module._runtime_run_command(
            image=runtime_image_id,
            network="formowl-runtime-test",
            data_dir=Path("/tmp/formowl-runtime-data"),
            secret_dir=Path("/tmp/formowl-runtime-secrets"),
            command="serve",
            name="formowl-runtime-test",
            detach=True,
        )
        rendered = " ".join(command)

        self.assertEqual(command[:3], ["docker", "run", "--detach"])
        self.assertEqual(command[-2:], [runtime_image_id, "serve"])
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop ALL", rendered)
        for capability in module.LAUNCHER_CAPABILITIES:
            self.assertIn(f"--cap-add {capability}", rendered)
        self.assertIn("--security-opt no-new-privileges:true", rendered)
        self.assertIn("--stop-signal SIGTERM", rendered)
        self.assertIn("--stop-timeout 30", rendered)
        self.assertIn("dst=/data", rendered)
        self.assertIn("dst=/run/secrets/formowl_signing_key_set,readonly", rendered)
        self.assertIn("/run/formowl-secrets:size=1m,mode=0700", rendered)
        self.assertNotIn("formowl_postgres_password", rendered)
        for forbidden in module._FORBIDDEN_PLAINTEXT_SECRET_ENV:
            self.assertNotIn(f"{forbidden}=", rendered)
        self.assertNotIn("DEV_IMAGE", source)
        self.assertNotIn("sys.path.insert", source)
        self.assertNotIn("FORMOWL_LIFECYCLE_BEARER_TOKEN", source)
        self.assertIn("--label", source)
        self.assertIn("--iidfile", source)
        self.assertNotIn('POSTGRES_IMAGE = "pgvector/pgvector:', source)
        self.assertIn("IMPLEMENTATION_CONTRACT_IMAGE_LABEL", source)
        self.assertIn('"pre_secret_bootstrap_mode": "built_runtime_image_docker_run"', source)
        self.assertIn("connected_secret_sources", source)
        self.assertIn("migrate_secret_sources", source)
        self.assertIn("postgres_secret_sources", source)
        self.assertIn("dst=/opt/formowl-lifecycle-probe.py,readonly", source)
        self.assertIn("FORMOWL_LIFECYCLE_BEARER_FILE=/probe/formowl_bearer_token", source)
        self.assertIn("os.O_CREAT | os.O_EXCL | os.O_WRONLY", source)
        self.assertIn("0o400", source)

    def test_lifecycle_probe_seed_failures_and_probe_directory_are_bounded(self) -> None:
        module = _load_lifecycle_probe()

        with self.assertRaises(module.LifecycleProbeFailure) as raised:
            module._inside_seed_step(
                "authorization_start_failed",
                lambda: 1 / 0,
            )
        self.assertEqual(raised.exception.stage, "inside_seed")
        self.assertEqual(raised.exception.code, "authorization_start_failed")

        original = module.LifecycleProbeFailure("inside_seed", "fake_google_nonce_invalid")
        with self.assertRaises(module.LifecycleProbeFailure) as preserved:
            module._inside_seed_step(
                "google_callback_failed",
                lambda: (_ for _ in ()).throw(original),
            )
        self.assertIs(preserved.exception, original)

        with tempfile.TemporaryDirectory(
            prefix="formowl-probe-mode-",
            dir=tempfile.gettempdir(),
        ) as directory:
            probe_dir = Path(directory) / "probe"
            previous_umask = os.umask(0o077)
            try:
                module._prepare_probe_directory(probe_dir)
            finally:
                os.umask(previous_umask)
            self.assertEqual(probe_dir.stat().st_mode & 0o777, 0o733)

    def test_inside_seed_rejects_forged_client_state_before_token_exchange(
        self,
    ) -> None:
        from collections import Counter
        from types import SimpleNamespace

        import formowl_auth
        from formowl_auth.security import hash_oauth_value
        from formowl_gateway.runtime import ConnectedRuntimeConfig

        module = _load_lifecycle_probe()
        google_state = "deterministic-google-state"
        google_nonce = "deterministic-google-nonce"
        forged_client_state = "forged-client-state"
        private_invalid_google_code = "private-invalid-google-code"
        private_wrong_nonce = "private-wrong-nonce"
        events: list[str] = []
        bootstrap_mutations = (
            "owner_bootstrap_upsert",
            "owner_invitation_insert",
        )
        bootstrap_audits = ("oauth_owner_bootstrap_created",)
        authorization_mutations = ("oauth_transaction_insert",)
        authorization_audits = ("oauth_authorization_started",)
        callback_mutations = (
            "user_insert",
            "external_identity_insert",
            "workspace_member_insert",
            "oauth_client_authorization_insert",
            "owner_invitation_accept",
            "owner_bootstrap_complete",
            "authorization_code_insert",
            "oauth_transaction_consume",
        )
        callback_audits = (
            "oauth_external_identity_created",
            "oauth_invitation_accepted",
            "google_authentication_succeeded",
            "oauth_authorization_code_issued",
        )
        token_mutations = (
            "oauth_token_session_insert",
            "authorization_code_consume",
        )
        token_audits = ("oauth_token_session_issued",)
        bootstrap_reads = (
            "pending_owner_invitations_for_update",
            "owner_bootstrap_for_update",
            "owner_invitation",
            "active_workspace_member_count",
        )
        callback_initial_reads = ("oauth_transaction_by_state_hash",)
        callback_success_reads = (
            "oauth_transaction_by_state_hash_for_update",
            "external_identity_by_provider_subject",
            "active_invitations_for_update",
            "owner_bootstrap_by_invitation_for_update",
            "active_workspace_member",
        )
        token_reads = (
            "authorization_code_for_update",
            "user",
            "external_identity",
            "oauth_client_authorization",
            "active_workspace_member_for_update",
        )

        class FakeRepository:
            def __init__(self) -> None:
                self.reset()

            def reset(self) -> None:
                self.closed = False
                self.close_count = 0
                self.committed_batches: list[str] = []
                self.mutations: list[str] = []
                self.audit_actions: list[str] = []
                self.reads: list[str] = []

            def record_reads(self, *reads: str) -> None:
                self.reads.extend(reads)

            def commit_batch(
                self,
                batch: str,
                *,
                mutations: tuple[str, ...],
                audits: tuple[str, ...],
            ) -> None:
                self.committed_batches.append(batch)
                self.mutations.extend(mutations)
                self.audit_actions.extend(audits)

            def state(self) -> dict[str, tuple[str, ...]]:
                return {
                    "committed_batches": tuple(self.committed_batches),
                    "mutations": tuple(self.mutations),
                    "audit_actions": tuple(self.audit_actions),
                    "reads": tuple(self.reads),
                }

            def close(self) -> None:
                events.append("repository_close")
                self.closed = True
                self.close_count += 1

        repository = FakeRepository()
        oauth_config = SimpleNamespace(
            issuer="https://formowl.example.test",
            resource="https://formowl.example.test/mcp",
            chatgpt_client_id="chatgpt-client",
            chatgpt_redirect_uri="https://chatgpt.com/connector/oauth/callback",
            access_token_lifetime_seconds=3600,
            clock_skew_seconds=30,
        )
        runtime_config = SimpleNamespace(
            oauth=oauth_config,
            database_dsn="postgresql://lifecycle.invalid/formowl",
            signing_key_set=object(),
            owner_bootstrap_operator_service_id="operator_service_001",
        )
        oauth_config_before = dict(vars(oauth_config))

        class FakeBridge:
            instance = None
            callback_scenario = "forged_state"

            def __init__(
                self,
                *,
                config,
                repository,
                google_client,
                token_codec,
                random_bytes,
                owner_bootstrap_operator_authorizer,
            ) -> None:
                del token_codec
                events.append("bridge_construct")
                self.config = config
                self.repository = repository
                self.google_client = google_client
                self.random_bytes = random_bytes
                self.owner_bootstrap_operator_authorizer = owner_bootstrap_operator_authorizer
                self.initial_google_state = google_client.last_state
                self.initial_google_nonce = google_client.last_nonce
                self.start_request = None
                self.callback_identity = None
                self.exchange_call_count = 0
                self.pre_callback_repository_state = None
                self.post_callback_repository_state = None
                type(self).instance = self

            def bootstrap_owner_invitation(self, **_kwargs) -> None:
                events.append("owner_bootstrap")
                self.repository.record_reads(*bootstrap_reads)
                self.repository.commit_batch(
                    "owner_bootstrap",
                    mutations=bootstrap_mutations,
                    audits=bootstrap_audits,
                )
                return None

            def start_authorization(self, request, *, now):
                events.append("authorization_start")
                self.start_request = copy.deepcopy(request)
                self.start_now = now
                self.repository.commit_batch(
                    "authorization_start",
                    mutations=authorization_mutations,
                    audits=authorization_audits,
                )
                authorization_url = self.google_client.build_authorization_url(
                    google_state=google_state,
                    google_nonce=google_nonce,
                )
                return {
                    "authorization_url": authorization_url,
                    "transaction_id": "oauthtx_lifecycle",
                }

            async def complete_google_callback(
                self,
                *,
                google_state: str,
                google_code: str,
                now,
            ):
                events.append("google_callback")
                self.callback_google_state = google_state
                self.callback_google_code = google_code
                self.callback_now = now
                self.repository.record_reads(*callback_initial_reads)
                self.pre_callback_repository_state = self.repository.state()
                scenario = type(self).callback_scenario
                authenticate_google_code = (
                    private_invalid_google_code
                    if scenario == "invalid_google_code"
                    else google_code
                )
                if scenario == "missing_remembered_nonce":
                    self.google_client.last_nonce = None
                expected_nonce_hash = hash_oauth_value(
                    "google_nonce",
                    private_wrong_nonce if scenario == "wrong_nonce_hash" else google_nonce,
                )
                self.authenticate_google_code = authenticate_google_code
                self.authenticate_expected_nonce_hash = expected_nonce_hash
                self.callback_identity = await self.google_client.authenticate_code(
                    authenticate_google_code,
                    expected_nonce_hash=expected_nonce_hash,
                    now=now,
                )
                self.repository.record_reads(*callback_success_reads)
                self.repository.commit_batch(
                    "google_callback",
                    mutations=callback_mutations,
                    audits=callback_audits,
                )
                self.post_callback_repository_state = self.repository.state()
                callback_client_state = (
                    forged_client_state
                    if scenario == "forged_state"
                    else "formowl-lifecycle-client-state"
                )
                return {
                    "redirect_uri": (
                        f"{self.config.chatgpt_redirect_uri}"
                        "?code=lifecycle-authorization-code"
                        f"&state={callback_client_state}"
                    ),
                    "user_id": "user_lifecycle",
                }

            def exchange_authorization_code(self, _request, *, now):
                del now
                events.append("token_exchange")
                self.exchange_call_count += 1
                self.repository.record_reads(*token_reads)
                self.repository.commit_batch(
                    "token_exchange",
                    mutations=token_mutations,
                    audits=token_audits,
                )
                return {
                    "access_token": "eyJaaaaaaaa.bbbbbbbbb.ccccccccc",
                }

        nested_event_by_qualname = {
            "_inside_seed_oauth_state.<locals>._SeedGoogleClient.__init__": (
                "seed_google_client_init"
            ),
            "_inside_seed_oauth_state.<locals>._SeedGoogleClient."
            "build_authorization_url": "seed_google_client_build_authorization_url",
            "_inside_seed_oauth_state.<locals>._SeedGoogleClient.authenticate_code": (
                "seed_google_client_authenticate_code"
            ),
        }

        def run_seed_with_nested_trace():
            previous_trace = sys.gettrace()

            def trace_nested_client_calls(frame, event, argument):
                if previous_trace is not None:
                    previous_trace(frame, event, argument)
                if (
                    event == "call"
                    and Path(frame.f_code.co_filename).resolve() == LIFECYCLE_PROBE.resolve()
                ):
                    nested_event = nested_event_by_qualname.get(frame.f_code.co_qualname)
                    if nested_event is not None:
                        events.append(nested_event)
                return trace_nested_client_calls

            sys.settrace(trace_nested_client_calls)
            try:
                return module._inside_seed_oauth_state()
            finally:
                sys.settrace(previous_trace)

        real_write_bearer = module._write_inside_seed_bearer_file

        def write_bearer(token_path, access_token) -> None:
            events.append("bearer_write")
            real_write_bearer(token_path, access_token)

        public_stdout = io.StringIO()
        public_stderr = io.StringIO()
        with tempfile.TemporaryDirectory(
            prefix="formowl-seed-client-state-",
            dir=tempfile.gettempdir(),
        ) as directory:
            token_root = Path(directory)
            with (
                mock.patch.dict(
                    module.os.environ,
                    {"FORMOWL_LIFECYCLE_BEARER_FILE": str(token_root / "initial")},
                ),
                mock.patch.object(
                    ConnectedRuntimeConfig,
                    "from_env_and_secrets",
                    return_value=runtime_config,
                ),
                mock.patch.object(
                    formowl_auth.PostgreSQLOAuthRepository,
                    "connect",
                    return_value=repository,
                ),
                mock.patch.object(formowl_auth, "FormOwlOAuthBridge", FakeBridge),
                mock.patch.object(
                    formowl_auth,
                    "FormOwlTokenCodec",
                    return_value=object(),
                ),
                mock.patch.object(
                    module,
                    "_write_inside_seed_bearer_file",
                    side_effect=write_bearer,
                ) as bearer_writer,
                redirect_stdout(public_stdout),
                redirect_stderr(public_stderr),
            ):
                rejected_expected_events = (
                    "seed_google_client_init",
                    "bridge_construct",
                    "owner_bootstrap",
                    "authorization_start",
                    "seed_google_client_build_authorization_url",
                    "google_callback",
                    "seed_google_client_authenticate_code",
                    "repository_close",
                )
                expected_pre_callback_state = {
                    "committed_batches": (
                        "owner_bootstrap",
                        "authorization_start",
                    ),
                    "mutations": bootstrap_mutations + authorization_mutations,
                    "audit_actions": bootstrap_audits + authorization_audits,
                    "reads": bootstrap_reads + callback_initial_reads,
                }
                expected_post_callback_state = {
                    "committed_batches": (
                        "owner_bootstrap",
                        "authorization_start",
                        "google_callback",
                    ),
                    "mutations": (
                        bootstrap_mutations + authorization_mutations + callback_mutations
                    ),
                    "audit_actions": (bootstrap_audits + authorization_audits + callback_audits),
                    "reads": (bootstrap_reads + callback_initial_reads + callback_success_reads),
                }
                expected_success_state = {
                    "committed_batches": (
                        "owner_bootstrap",
                        "authorization_start",
                        "google_callback",
                        "token_exchange",
                    ),
                    "mutations": (
                        bootstrap_mutations
                        + authorization_mutations
                        + callback_mutations
                        + token_mutations
                    ),
                    "audit_actions": (
                        bootstrap_audits + authorization_audits + callback_audits + token_audits
                    ),
                    "reads": (
                        bootstrap_reads
                        + callback_initial_reads
                        + callback_success_reads
                        + token_reads
                    ),
                }
                valid_nonce_hash = hash_oauth_value("google_nonce", google_nonce)
                wrong_nonce_hash = hash_oauth_value(
                    "google_nonce",
                    private_wrong_nonce,
                )
                rejected_scenarios = (
                    (
                        "invalid_google_code",
                        "fake_google_callback_invalid",
                        private_invalid_google_code,
                        valid_nonce_hash,
                        google_nonce,
                    ),
                    (
                        "missing_remembered_nonce",
                        "fake_google_callback_invalid",
                        "lifecycle-google-code",
                        valid_nonce_hash,
                        None,
                    ),
                    (
                        "wrong_nonce_hash",
                        "fake_google_nonce_invalid",
                        "lifecycle-google-code",
                        wrong_nonce_hash,
                        google_nonce,
                    ),
                )
                for (
                    scenario,
                    expected_code,
                    expected_google_code,
                    expected_nonce_hash,
                    expected_last_nonce,
                ) in rejected_scenarios:
                    with self.subTest(scenario=scenario):
                        token_path = token_root / scenario
                        module.os.environ["FORMOWL_LIFECYCLE_BEARER_FILE"] = str(token_path)
                        events.clear()
                        repository.reset()
                        FakeBridge.callback_scenario = scenario
                        bearer_writer.reset_mock()
                        public_stdout.seek(0)
                        public_stdout.truncate(0)
                        public_stderr.seek(0)
                        public_stderr.truncate(0)
                        result_sentinel = object()
                        rejected_result = result_sentinel

                        with self.assertRaises(module.LifecycleProbeFailure) as rejected:
                            rejected_result = run_seed_with_nested_trace()

                        rejected_bridge = FakeBridge.instance
                        rejected_events = tuple(events)
                        self.assertIs(rejected_result, result_sentinel)
                        self.assertEqual(
                            rejected_events,
                            rejected_expected_events,
                        )
                        self.assertEqual(
                            Counter(rejected_events),
                            Counter(rejected_expected_events),
                        )
                        self.assertTrue(
                            all(count == 1 for count in Counter(rejected_events).values())
                        )
                        self.assertIsNotNone(rejected_bridge)
                        self.assertEqual(rejected.exception.stage, "inside_seed")
                        self.assertEqual(rejected.exception.code, expected_code)
                        self.assertIsNone(rejected_bridge.initial_google_state)
                        self.assertIsNone(rejected_bridge.initial_google_nonce)
                        self.assertEqual(
                            vars(rejected_bridge.google_client),
                            {
                                "last_state": google_state,
                                "last_nonce": expected_last_nonce,
                            },
                        )
                        self.assertEqual(
                            rejected_bridge.callback_google_state,
                            google_state,
                        )
                        self.assertEqual(
                            rejected_bridge.callback_google_code,
                            "lifecycle-google-code",
                        )
                        self.assertEqual(
                            rejected_bridge.authenticate_google_code,
                            expected_google_code,
                        )
                        self.assertEqual(
                            rejected_bridge.authenticate_expected_nonce_hash,
                            expected_nonce_hash,
                        )
                        self.assertEqual(
                            rejected_bridge.start_now,
                            rejected_bridge.callback_now,
                        )
                        self.assertEqual(
                            rejected_bridge.start_request["state"],
                            "formowl-lifecycle-client-state",
                        )
                        self.assertIsNone(rejected_bridge.callback_identity)
                        self.assertEqual(rejected_bridge.exchange_call_count, 0)
                        self.assertEqual(
                            rejected_bridge.pre_callback_repository_state,
                            expected_pre_callback_state,
                        )
                        self.assertIsNone(
                            rejected_bridge.post_callback_repository_state,
                        )
                        self.assertEqual(
                            repository.state(),
                            expected_pre_callback_state,
                        )
                        self.assertNotIn(
                            "oauth_token_session_insert",
                            repository.mutations,
                        )
                        self.assertNotIn(
                            "oauth_token_session_issued",
                            repository.audit_actions,
                        )
                        self.assertTrue(repository.closed)
                        self.assertEqual(repository.close_count, 1)
                        self.assertEqual(bearer_writer.call_count, 0)
                        self.assertFalse(token_path.exists())
                        self.assertEqual(
                            dict(vars(oauth_config)),
                            oauth_config_before,
                        )
                        self.assertEqual(public_stdout.getvalue(), "")
                        self.assertEqual(public_stderr.getvalue(), "")
                        for private_detail in (
                            private_invalid_google_code,
                            private_wrong_nonce,
                        ):
                            self.assertNotIn(
                                private_detail,
                                str(rejected.exception),
                            )
                            self.assertNotIn(
                                private_detail,
                                public_stdout.getvalue(),
                            )
                            self.assertNotIn(
                                private_detail,
                                public_stderr.getvalue(),
                            )

                forged_token_path = token_root / "forged-state"
                module.os.environ["FORMOWL_LIFECYCLE_BEARER_FILE"] = str(forged_token_path)
                events.clear()
                repository.reset()
                FakeBridge.callback_scenario = "forged_state"
                bearer_writer.reset_mock()
                public_stdout.seek(0)
                public_stdout.truncate(0)
                public_stderr.seek(0)
                public_stderr.truncate(0)
                forged_result_sentinel = object()
                forged_result = forged_result_sentinel
                with self.assertRaises(module.LifecycleProbeFailure) as forged:
                    forged_result = run_seed_with_nested_trace()
                forged_bridge = FakeBridge.instance
                forged_events = tuple(events)
                forged_bearer_write_count = bearer_writer.call_count
                forged_repository_closed = repository.closed
                forged_repository_close_count = repository.close_count
                forged_repository_state = repository.state()
                forged_oauth_config = dict(vars(oauth_config))
                forged_stdout = public_stdout.getvalue()
                forged_stderr = public_stderr.getvalue()

                successful_token_path = token_root / "valid"
                module.os.environ["FORMOWL_LIFECYCLE_BEARER_FILE"] = str(successful_token_path)
                events.clear()
                repository.reset()
                FakeBridge.callback_scenario = "valid"
                bearer_writer.reset_mock()
                public_stdout.seek(0)
                public_stdout.truncate(0)
                public_stderr.seek(0)
                public_stderr.truncate(0)
                success = run_seed_with_nested_trace()
                successful_bridge = FakeBridge.instance
                successful_events = tuple(events)
                successful_bearer_write_count = bearer_writer.call_count
                successful_token = successful_token_path.read_text(encoding="ascii")
                successful_token_mode = successful_token_path.stat().st_mode & 0o777
                successful_repository_closed = repository.closed
                successful_repository_close_count = repository.close_count
                successful_repository_state = repository.state()
                successful_stdout = public_stdout.getvalue()
                successful_stderr = public_stderr.getvalue()

            successful_expected_events = (
                "seed_google_client_init",
                "bridge_construct",
                "owner_bootstrap",
                "authorization_start",
                "seed_google_client_build_authorization_url",
                "google_callback",
                "seed_google_client_authenticate_code",
                "token_exchange",
                "bearer_write",
                "repository_close",
            )
            self.assertIs(forged_result, forged_result_sentinel)
            self.assertEqual(forged_events, rejected_expected_events)
            self.assertEqual(
                Counter(forged_events),
                Counter(rejected_expected_events),
            )
            self.assertTrue(all(count == 1 for count in Counter(forged_events).values()))
            self.assertEqual(successful_events, successful_expected_events)
            self.assertEqual(
                Counter(successful_events),
                Counter(successful_expected_events),
            )
            self.assertTrue(all(count == 1 for count in Counter(successful_events).values()))
            self.assertEqual(successful_bearer_write_count, 1)
            self.assertIsNotNone(forged_bridge)
            self.assertEqual(forged.exception.stage, "inside_seed")
            self.assertEqual(
                forged.exception.code,
                "authorization_callback_invalid",
            )
            self.assertIsNone(forged_bridge.initial_google_state)
            self.assertIsNone(forged_bridge.initial_google_nonce)
            self.assertEqual(
                vars(forged_bridge.google_client),
                {
                    "last_state": google_state,
                    "last_nonce": google_nonce,
                },
            )
            self.assertEqual(forged_bridge.callback_google_state, google_state)
            self.assertEqual(
                forged_bridge.callback_google_code,
                "lifecycle-google-code",
            )
            self.assertEqual(
                forged_bridge.authenticate_google_code,
                "lifecycle-google-code",
            )
            self.assertEqual(
                forged_bridge.authenticate_expected_nonce_hash,
                valid_nonce_hash,
            )
            self.assertEqual(forged_bridge.start_now, forged_bridge.callback_now)
            self.assertEqual(
                forged_bridge.start_request["state"],
                "formowl-lifecycle-client-state",
            )
            self.assertEqual(
                forged_bridge.callback_identity.subject,
                "formowl-lifecycle-subject",
            )
            self.assertEqual(forged_bridge.exchange_call_count, 0)
            self.assertEqual(
                forged_bridge.pre_callback_repository_state,
                expected_pre_callback_state,
            )
            self.assertEqual(
                forged_bridge.post_callback_repository_state,
                expected_post_callback_state,
            )
            self.assertEqual(
                forged_repository_state,
                expected_post_callback_state,
            )
            self.assertNotIn(
                "oauth_token_session_insert",
                forged_repository_state["mutations"],
            )
            self.assertNotIn(
                "oauth_token_session_issued",
                forged_repository_state["audit_actions"],
            )
            self.assertEqual(forged_events.count("token_exchange"), 0)
            self.assertEqual(forged_events.count("bearer_write"), 0)
            self.assertEqual(forged_bearer_write_count, 0)
            self.assertTrue(forged_repository_closed)
            self.assertEqual(forged_repository_close_count, 1)
            self.assertFalse(forged_token_path.exists())
            self.assertEqual(forged_oauth_config, oauth_config_before)
            self.assertEqual(forged_stdout, "")
            self.assertEqual(forged_stderr, "")
            self.assertIsNotNone(successful_bridge)
            self.assertIsNone(successful_bridge.initial_google_state)
            self.assertIsNone(successful_bridge.initial_google_nonce)
            self.assertEqual(successful_bridge.google_client.last_state, google_state)
            self.assertEqual(successful_bridge.google_client.last_nonce, google_nonce)
            self.assertEqual(successful_bridge.callback_google_state, google_state)
            self.assertEqual(successful_bridge.start_now, successful_bridge.callback_now)
            self.assertEqual(successful_bridge.exchange_call_count, 1)
            self.assertEqual(
                successful_bridge.pre_callback_repository_state,
                expected_pre_callback_state,
            )
            self.assertEqual(
                successful_bridge.post_callback_repository_state,
                expected_post_callback_state,
            )
            self.assertEqual(
                successful_repository_state,
                expected_success_state,
            )
            self.assertEqual(
                successful_repository_state["mutations"].count("oauth_token_session_insert"),
                1,
            )
            self.assertEqual(
                successful_repository_state["audit_actions"].count("oauth_token_session_issued"),
                1,
            )
            self.assertTrue(successful_repository_closed)
            self.assertEqual(successful_repository_close_count, 1)
            self.assertEqual(
                success,
                {
                    "status": "ok",
                    "seed_count": 1,
                    "seed_state_hash": module._sha256_json(
                        {
                            "bootstrap": True,
                            "oauth_pkce": True,
                            "token_session": True,
                            "file_secret_source": True,
                        }
                    ),
                },
            )
            self.assertEqual(
                successful_token,
                "eyJaaaaaaaa.bbbbbbbbb.ccccccccc",
            )
            self.assertEqual(successful_token_mode, 0o400)
            self.assertEqual(dict(vars(oauth_config)), oauth_config_before)
            self.assertEqual(successful_stdout, "")
            self.assertEqual(successful_stderr, "")
            self.assertNotIn(forged_client_state, str(forged.exception))

    def test_inside_client_sequence_returns_phase_specific_success_after_ordered_cleanup(
        self,
    ) -> None:
        from types import SimpleNamespace

        import httpx
        import mcp
        from mcp.client import streamable_http
        from mcp.shared.version import LATEST_PROTOCOL_VERSION

        module = _load_lifecycle_probe()
        bearer = "eyJaaaaaaaa.bbbbbbbbb.ccccccccc"
        runtime_host = "runtime-lifecycle"
        test_case = self
        phase_cases = (
            (
                "first",
                (
                    ("whoami", {}),
                    (
                        "open_upload_session",
                        {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                        },
                    ),
                    (
                        "open_upload_session",
                        {
                            "intent": "Attempt caller identity forgery.",
                            "intended_asset_type": "pst",
                            "requester_user_id": "user_forged",
                        },
                    ),
                ),
                (False, False, True),
                2,
                1,
            ),
            (
                "restart",
                (("whoami", {}),),
                (False,),
                1,
                0,
            ),
        )

        for phase, expected_calls, error_flags, allowed_count, denied_count in phase_cases:
            with self.subTest(phase=phase):
                events: list[str] = []
                remaining_calls = [
                    (name, copy.deepcopy(arguments)) for name, arguments in expected_calls
                ]
                initialized_payload = {"protocolVersion": "lifecycle-protocol"}
                call_payloads = [
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": f"private-result-{phase}-{index}",
                            }
                        ],
                        "isError": error_flag,
                    }
                    for index, error_flag in enumerate(error_flags)
                ]

                class FakeModel:
                    def __init__(self, label: str, payload: dict[str, object]) -> None:
                        self.label = label
                        self.payload = copy.deepcopy(payload)
                        self.model_dump_call_count = 0

                    def model_dump(self, **kwargs):
                        test_case.assertEqual(
                            kwargs,
                            {
                                "mode": "json",
                                "by_alias": True,
                                "exclude_none": True,
                            },
                        )
                        self.model_dump_call_count += 1
                        events.append(f"model_dump:{self.label}")
                        return copy.deepcopy(self.payload)

                class FakeToolResult(FakeModel):
                    def __init__(
                        self,
                        label: str,
                        payload: dict[str, object],
                        *,
                        error_flag: bool,
                    ) -> None:
                        super().__init__(label, payload)
                        self.isError = error_flag

                initialized = FakeModel("initialize", initialized_payload)
                all_results = tuple(
                    FakeToolResult(
                        f"call:{index}",
                        payload,
                        error_flag=error_flag,
                    )
                    for index, (payload, error_flag) in enumerate(
                        zip(call_payloads, error_flags, strict=True)
                    )
                )
                call_results = list(all_results)

                class FakeAsyncClient:
                    def __init__(self, **kwargs) -> None:
                        events.append("http_client_init")
                        test_case.assertEqual(
                            kwargs,
                            {
                                "headers": {
                                    "Authorization": f"Bearer {bearer}",
                                    "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                                },
                                "follow_redirects": False,
                                "timeout": 15.0,
                                "trust_env": False,
                            },
                        )

                    async def __aenter__(self):
                        events.append("http_client_enter")
                        return self

                    async def __aexit__(self, exc_type, exc, traceback):
                        test_case.assertIsNone(exc_type)
                        test_case.assertIsNone(exc)
                        test_case.assertIsNone(traceback)
                        events.append("http_client_exit")
                        return False

                class FakeStreamContext:
                    async def __aenter__(self):
                        events.append("stream_enter")
                        return ("read_stream", "write_stream")

                    async def __aexit__(self, exc_type, exc, traceback):
                        test_case.assertIsNone(exc_type)
                        test_case.assertIsNone(exc)
                        test_case.assertIsNone(traceback)
                        events.append("stream_exit")
                        return False

                def fake_streamable_http_client(endpoint, *, http_client):
                    events.append("stream_create")
                    test_case.assertEqual(endpoint, f"http://{runtime_host}:8000/mcp")
                    test_case.assertIsInstance(http_client, FakeAsyncClient)
                    return FakeStreamContext()

                class FakeClientSession:
                    def __init__(self, read_stream, write_stream) -> None:
                        events.append("session_init")
                        test_case.assertEqual(read_stream, "read_stream")
                        test_case.assertEqual(write_stream, "write_stream")

                    async def __aenter__(self):
                        events.append("session_enter")
                        return self

                    async def __aexit__(self, exc_type, exc, traceback):
                        test_case.assertIsNone(exc_type)
                        test_case.assertIsNone(exc)
                        test_case.assertIsNone(traceback)
                        events.append("session_exit")
                        return False

                    async def initialize(self):
                        events.append("initialize")
                        return initialized

                    async def list_tools(self):
                        events.append("list_tools")
                        return SimpleNamespace(
                            tools=[
                                SimpleNamespace(name="open_upload_session"),
                                SimpleNamespace(name="whoami"),
                            ]
                        )

                    async def call_tool(self, name, *, arguments):
                        index = len(expected_calls) - len(remaining_calls)
                        events.append(f"call_tool:{index}:{name}")
                        expected_name, expected_arguments = remaining_calls.pop(0)
                        test_case.assertEqual(name, expected_name)
                        test_case.assertEqual(arguments, expected_arguments)
                        return call_results.pop(0)

                fake_token_path = mock.Mock()
                fake_token_path.stat.return_value = SimpleNamespace(st_mode=0o400)
                fake_token_path.read_text.return_value = bearer
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()
                with (
                    mock.patch.dict(
                        module.os.environ,
                        {
                            "FORMOWL_LIFECYCLE_CLIENT_PHASE": phase,
                            "FORMOWL_LIFECYCLE_RUNTIME_HOST": runtime_host,
                        },
                    ),
                    mock.patch.object(module, "Path", return_value=fake_token_path),
                    mock.patch.object(httpx, "AsyncClient", FakeAsyncClient),
                    mock.patch.object(
                        streamable_http,
                        "streamable_http_client",
                        side_effect=fake_streamable_http_client,
                    ),
                    mock.patch.object(mcp, "ClientSession", FakeClientSession),
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    result = asyncio.run(module._inside_client_sequence())

                expected_events = (
                    "http_client_init",
                    "http_client_enter",
                    "stream_create",
                    "stream_enter",
                    "session_init",
                    "session_enter",
                    "initialize",
                    "list_tools",
                    *(
                        f"call_tool:{index}:{name}"
                        for index, (name, _arguments) in enumerate(expected_calls)
                    ),
                    "session_exit",
                    "stream_exit",
                    "http_client_exit",
                    "model_dump:initialize",
                    *(f"model_dump:call:{index}" for index in range(len(error_flags))),
                )
                self.assertEqual(tuple(events), expected_events)
                self.assertEqual(remaining_calls, [])
                self.assertEqual(call_results, [])
                self.assertEqual(initialized.model_dump_call_count, 1)
                self.assertTrue(all(item.model_dump_call_count == 1 for item in all_results))
                self.assertLess(
                    events.index("http_client_exit"),
                    events.index("model_dump:initialize"),
                )
                fake_token_path.stat.assert_called_once_with()
                fake_token_path.read_text.assert_called_once_with(encoding="ascii")
                self.assertEqual(
                    result,
                    {
                        "status": "ok",
                        "phase": phase,
                        "allowed_count": allowed_count,
                        "denied_count": denied_count,
                        "result_shape_hash": module._sha256_json(
                            {
                                "initialize": initialized_payload,
                                "tools": ["open_upload_session", "whoami"],
                                "calls": call_payloads,
                            }
                        ),
                    },
                )
                self.assertEqual(public_stdout.getvalue(), "")
                self.assertEqual(public_stderr.getvalue(), "")
                for payload in call_payloads:
                    private_text = payload["content"][0]["text"]
                    self.assertNotIn(private_text, json.dumps(result, sort_keys=True))

    def test_inside_client_rejects_result_without_exact_error_flag_after_cleanup(
        self,
    ) -> None:
        from collections import Counter
        from types import SimpleNamespace

        import httpx
        import mcp
        from mcp.client import streamable_http

        module = _load_lifecycle_probe()
        bearer = "eyJaaaaaaaa.bbbbbbbbb.ccccccccc"
        private_marker = "post-decoding-safety-marker"
        events: list[str] = []
        missing_error_flag = object()
        test_case = self

        class FakeToolResult:
            def __init__(self, error_flag, *, marker: str | None = None) -> None:
                if error_flag is not missing_error_flag:
                    self.isError = error_flag
                self.marker = marker
                self.model_dump_call_count = 0

            def model_dump(self, **_kwargs):
                self.model_dump_call_count += 1
                return {
                    "content": [] if self.marker is None else [{"text": self.marker}],
                }

        allowed_result = FakeToolResult(False)
        malformed_result = FakeToolResult(
            missing_error_flag,
            marker=private_marker,
        )
        denied_result = FakeToolResult(True)
        call_results = [allowed_result, malformed_result, denied_result]

        class FakeAsyncClient:
            def __init__(self, **kwargs) -> None:
                events.append("http_client_init")
                self.kwargs = copy.deepcopy(kwargs)

            async def __aenter__(self):
                events.append("http_client_enter")
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("http_client_exit")
                return False

        class FakeStreamContext:
            async def __aenter__(self):
                events.append("stream_enter")
                return ("read_stream", "write_stream")

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("stream_exit")
                return False

        def fake_streamable_http_client(endpoint, *, http_client):
            events.append("stream_create")
            self.assertEqual(endpoint, "http://runtime-lifecycle:8000/mcp")
            self.assertIsInstance(http_client, FakeAsyncClient)
            return FakeStreamContext()

        class FakeClientSession:
            def __init__(self, read_stream, write_stream) -> None:
                events.append("session_init")
                test_case.assertEqual(read_stream, "read_stream")
                test_case.assertEqual(write_stream, "write_stream")

            async def __aenter__(self):
                events.append("session_enter")
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("session_exit")
                return False

            async def initialize(self):
                events.append("initialize")
                return SimpleNamespace(
                    model_dump=lambda **_kwargs: {
                        "protocolVersion": "lifecycle-protocol",
                    }
                )

            async def list_tools(self):
                events.append("list_tools")
                return SimpleNamespace(
                    tools=[
                        SimpleNamespace(name="open_upload_session"),
                        SimpleNamespace(name="whoami"),
                    ]
                )

            async def call_tool(self, name, *, arguments):
                del arguments
                events.append(f"call_tool:{name}")
                return call_results.pop(0)

        fake_token_path = mock.Mock()
        fake_token_path.stat.return_value = SimpleNamespace(st_mode=0o400)
        fake_token_path.read_text.return_value = bearer
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()
        result_sentinel = object()
        result = result_sentinel
        expected_events = (
            "http_client_init",
            "http_client_enter",
            "stream_create",
            "stream_enter",
            "session_init",
            "session_enter",
            "initialize",
            "list_tools",
            "call_tool:whoami",
            "call_tool:open_upload_session",
            "call_tool:open_upload_session",
            "session_exit",
            "stream_exit",
            "http_client_exit",
        )

        with (
            mock.patch.dict(
                module.os.environ,
                {
                    "FORMOWL_LIFECYCLE_CLIENT_PHASE": "first",
                    "FORMOWL_LIFECYCLE_RUNTIME_HOST": "runtime-lifecycle",
                },
            ),
            mock.patch.object(module, "Path", return_value=fake_token_path),
            mock.patch.object(httpx, "AsyncClient", FakeAsyncClient),
            mock.patch.object(
                streamable_http,
                "streamable_http_client",
                side_effect=fake_streamable_http_client,
            ),
            mock.patch.object(mcp, "ClientSession", FakeClientSession),
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            result = asyncio.run(module._inside_client_sequence())

        self.assertIs(result, result_sentinel)
        self.assertEqual(raised.exception.stage, "inside_client")
        self.assertEqual(raised.exception.code, "client_tool_result_invalid")
        self.assertEqual(tuple(events), expected_events)
        event_counts = Counter(events)
        self.assertEqual(event_counts, Counter(expected_events))
        for event in (
            "http_client_init",
            "http_client_enter",
            "stream_create",
            "stream_enter",
            "session_init",
            "session_enter",
            "initialize",
            "list_tools",
            "call_tool:whoami",
            "session_exit",
            "stream_exit",
            "http_client_exit",
        ):
            self.assertEqual(event_counts[event], 1)
        self.assertEqual(event_counts["call_tool:open_upload_session"], 2)
        self.assertEqual(call_results, [])
        self.assertEqual(malformed_result.model_dump_call_count, 0)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for private_detail in (bearer, private_marker):
            self.assertNotIn(private_detail, str(raised.exception))
            self.assertNotIn(private_detail, public_stdout.getvalue())
            self.assertNotIn(private_detail, public_stderr.getvalue())

    def test_inside_client_rejects_non_boolean_error_flag_after_cleanup(
        self,
    ) -> None:
        from collections import Counter
        from types import SimpleNamespace

        import httpx
        import mcp
        from mcp.client import streamable_http

        module = _load_lifecycle_probe()
        bearer = "eyJaaaaaaaa.bbbbbbbbb.ccccccccc"
        private_marker = "non-boolean-error-flag-private-marker"
        events: list[str] = []
        test_case = self

        class FakeToolResult:
            def __init__(self, error_flag: object, *, marker: str | None = None) -> None:
                self.isError = error_flag
                self.marker = marker
                self.model_dump_call_count = 0

            def model_dump(self, **_kwargs):
                self.model_dump_call_count += 1
                return {
                    "content": [] if self.marker is None else [{"text": self.marker}],
                }

        allowed_result = FakeToolResult(False)
        malformed_result = FakeToolResult(1, marker=private_marker)
        denied_result = FakeToolResult(True)
        call_results = [allowed_result, malformed_result, denied_result]
        all_results = tuple(call_results)

        class FakeAsyncClient:
            def __init__(self, **kwargs) -> None:
                events.append("http_client_init")
                self.kwargs = copy.deepcopy(kwargs)

            async def __aenter__(self):
                events.append("http_client_enter")
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("http_client_exit")
                return False

        class FakeStreamContext:
            async def __aenter__(self):
                events.append("stream_enter")
                return ("read_stream", "write_stream")

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("stream_exit")
                return False

        def fake_streamable_http_client(endpoint, *, http_client):
            events.append("stream_create")
            self.assertEqual(endpoint, "http://runtime-lifecycle:8000/mcp")
            self.assertIsInstance(http_client, FakeAsyncClient)
            return FakeStreamContext()

        class FakeClientSession:
            def __init__(self, read_stream, write_stream) -> None:
                events.append("session_init")
                test_case.assertEqual(read_stream, "read_stream")
                test_case.assertEqual(write_stream, "write_stream")

            async def __aenter__(self):
                events.append("session_enter")
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("session_exit")
                return False

            async def initialize(self):
                events.append("initialize")
                return SimpleNamespace(
                    model_dump=lambda **_kwargs: {
                        "protocolVersion": "lifecycle-protocol",
                    }
                )

            async def list_tools(self):
                events.append("list_tools")
                return SimpleNamespace(
                    tools=[
                        SimpleNamespace(name="open_upload_session"),
                        SimpleNamespace(name="whoami"),
                    ]
                )

            async def call_tool(self, name, *, arguments):
                del arguments
                events.append(f"call_tool:{name}")
                return call_results.pop(0)

        fake_token_path = mock.Mock()
        fake_token_path.stat.return_value = SimpleNamespace(st_mode=0o400)
        fake_token_path.read_text.return_value = bearer
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()
        result_sentinel = object()
        result = result_sentinel
        expected_events = (
            "http_client_init",
            "http_client_enter",
            "stream_create",
            "stream_enter",
            "session_init",
            "session_enter",
            "initialize",
            "list_tools",
            "call_tool:whoami",
            "call_tool:open_upload_session",
            "call_tool:open_upload_session",
            "session_exit",
            "stream_exit",
            "http_client_exit",
        )

        with (
            mock.patch.dict(
                module.os.environ,
                {
                    "FORMOWL_LIFECYCLE_CLIENT_PHASE": "first",
                    "FORMOWL_LIFECYCLE_RUNTIME_HOST": "runtime-lifecycle",
                },
            ),
            mock.patch.object(module, "Path", return_value=fake_token_path),
            mock.patch.object(httpx, "AsyncClient", FakeAsyncClient),
            mock.patch.object(
                streamable_http,
                "streamable_http_client",
                side_effect=fake_streamable_http_client,
            ),
            mock.patch.object(mcp, "ClientSession", FakeClientSession),
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            result = asyncio.run(module._inside_client_sequence())

        self.assertIs(result, result_sentinel)
        self.assertEqual(raised.exception.stage, "inside_client")
        self.assertEqual(raised.exception.code, "client_tool_result_invalid")
        self.assertEqual(tuple(events), expected_events)
        event_counts = Counter(events)
        self.assertEqual(event_counts, Counter(expected_events))
        for event in (
            "http_client_init",
            "http_client_enter",
            "stream_create",
            "stream_enter",
            "session_init",
            "session_enter",
            "initialize",
            "list_tools",
            "call_tool:whoami",
            "session_exit",
            "stream_exit",
            "http_client_exit",
        ):
            self.assertEqual(event_counts[event], 1)
        self.assertEqual(event_counts["call_tool:open_upload_session"], 2)
        self.assertEqual(call_results, [])
        self.assertTrue(all(result.model_dump_call_count == 0 for result in all_results))
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for private_detail in (bearer, private_marker):
            self.assertNotIn(private_detail, str(raised.exception))
            self.assertNotIn(private_detail, public_stdout.getvalue())
            self.assertNotIn(private_detail, public_stderr.getvalue())

    def test_inside_client_rejects_swapped_first_phase_outcomes_after_cleanup(
        self,
    ) -> None:
        from collections import Counter
        from types import SimpleNamespace

        import httpx
        import mcp
        from mcp.client import streamable_http

        module = _load_lifecycle_probe()
        bearer = "eyJaaaaaaaa.bbbbbbbbb.ccccccccc"
        private_marker = "ordered-outcome-private-marker"
        events: list[str] = []
        test_case = self

        class FakeToolResult:
            def __init__(self, error_flag: bool, marker: str) -> None:
                self.isError = error_flag
                self.marker = marker
                self.model_dump_call_count = 0

            def model_dump(self, **_kwargs):
                self.model_dump_call_count += 1
                return {"content": [{"text": self.marker}]}

        call_results = [
            FakeToolResult(True, f"{private_marker}-first"),
            FakeToolResult(False, f"{private_marker}-second"),
            FakeToolResult(False, f"{private_marker}-third"),
        ]
        all_results = tuple(call_results)

        class FakeAsyncClient:
            def __init__(self, **kwargs) -> None:
                events.append("http_client_init")
                self.kwargs = copy.deepcopy(kwargs)

            async def __aenter__(self):
                events.append("http_client_enter")
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("http_client_exit")
                return False

        class FakeStreamContext:
            async def __aenter__(self):
                events.append("stream_enter")
                return ("read_stream", "write_stream")

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("stream_exit")
                return False

        def fake_streamable_http_client(endpoint, *, http_client):
            events.append("stream_create")
            self.assertEqual(endpoint, "http://runtime-lifecycle:8000/mcp")
            self.assertIsInstance(http_client, FakeAsyncClient)
            return FakeStreamContext()

        class FakeClientSession:
            def __init__(self, read_stream, write_stream) -> None:
                events.append("session_init")
                test_case.assertEqual(read_stream, "read_stream")
                test_case.assertEqual(write_stream, "write_stream")

            async def __aenter__(self):
                events.append("session_enter")
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                events.append("session_exit")
                return False

            async def initialize(self):
                events.append("initialize")
                return SimpleNamespace(
                    model_dump=lambda **_kwargs: {
                        "protocolVersion": "lifecycle-protocol",
                    }
                )

            async def list_tools(self):
                events.append("list_tools")
                return SimpleNamespace(
                    tools=[
                        SimpleNamespace(name="open_upload_session"),
                        SimpleNamespace(name="whoami"),
                    ]
                )

            async def call_tool(self, name, *, arguments):
                del arguments
                events.append(f"call_tool:{name}")
                return call_results.pop(0)

        fake_token_path = mock.Mock()
        fake_token_path.stat.return_value = SimpleNamespace(st_mode=0o400)
        fake_token_path.read_text.return_value = bearer
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()
        result_sentinel = object()
        result = result_sentinel
        expected_events = (
            "http_client_init",
            "http_client_enter",
            "stream_create",
            "stream_enter",
            "session_init",
            "session_enter",
            "initialize",
            "list_tools",
            "call_tool:whoami",
            "call_tool:open_upload_session",
            "call_tool:open_upload_session",
            "session_exit",
            "stream_exit",
            "http_client_exit",
        )

        with (
            mock.patch.dict(
                module.os.environ,
                {
                    "FORMOWL_LIFECYCLE_CLIENT_PHASE": "first",
                    "FORMOWL_LIFECYCLE_RUNTIME_HOST": "runtime-lifecycle",
                },
            ),
            mock.patch.object(module, "Path", return_value=fake_token_path),
            mock.patch.object(httpx, "AsyncClient", FakeAsyncClient),
            mock.patch.object(
                streamable_http,
                "streamable_http_client",
                side_effect=fake_streamable_http_client,
            ),
            mock.patch.object(mcp, "ClientSession", FakeClientSession),
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            result = asyncio.run(module._inside_client_sequence())

        self.assertIs(result, result_sentinel)
        self.assertEqual(raised.exception.stage, "inside_client")
        self.assertEqual(raised.exception.code, "client_tool_results_invalid")
        self.assertEqual(tuple(events), expected_events)
        event_counts = Counter(events)
        self.assertEqual(event_counts, Counter(expected_events))
        for event in (
            "http_client_init",
            "http_client_enter",
            "stream_create",
            "stream_enter",
            "session_init",
            "session_enter",
            "initialize",
            "list_tools",
            "call_tool:whoami",
            "session_exit",
            "stream_exit",
            "http_client_exit",
        ):
            self.assertEqual(event_counts[event], 1)
        self.assertEqual(event_counts["call_tool:open_upload_session"], 2)
        self.assertEqual(call_results, [])
        self.assertTrue(all(result.model_dump_call_count == 0 for result in all_results))
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        for private_detail in (bearer, private_marker):
            self.assertNotIn(private_detail, str(raised.exception))
            self.assertNotIn(private_detail, public_stdout.getvalue())
            self.assertNotIn(private_detail, public_stderr.getvalue())

    def test_inside_persisted_state_returns_valid_current_membership_snapshots_after_cleanup(
        self,
    ) -> None:
        from types import SimpleNamespace

        import formowl_auth
        import formowl_gateway.runtime as runtime_module
        import formowl_ingestion.storage as ingestion_storage_module

        module = _load_lifecycle_probe()
        private_marker = "persisted-success-private-marker"
        user_id = f"user_{private_marker}"
        workspace_id = f"workspace_{private_marker}"
        external_identity_id = f"identity_{private_marker}"
        client_id = f"client_{private_marker}"
        token_session_id = f"token_session_{private_marker}"
        test_case = self
        lineage_fields = frozenset(
            {
                "actor_user_id",
                "workspace_id",
                "external_identity_id",
                "oauth_client_id",
                "oauth_token_session_id",
                "request_id",
                "tool_call_id",
                "reason_code",
            }
        )
        core_rows = {
            "users": [
                {
                    "user_id": user_id,
                    "status": "active",
                }
            ],
            "identities": [
                {
                    "external_identity_id": external_identity_id,
                    "issuer": "https://accounts.google.com",
                    "subject": f"subject_{private_marker}",
                    "user_id": user_id,
                    "status": "active",
                }
            ],
            "memberships": [
                {
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "role": "owner",
                    "removed_at": None,
                }
            ],
            "token_sessions": [
                {
                    "token_session_id": token_session_id,
                    "user_id": user_id,
                    "external_identity_id": external_identity_id,
                    "client_id": client_id,
                    "current_workspace_id": workspace_id,
                    "resource": "https://formowl.example.test/mcp",
                    "scopes": ["formowl.use"],
                    "issued_at": "2026-07-19T00:00:00+00:00",
                    "expires_at": "2026-07-19T01:00:00+00:00",
                    "revoked_at": None,
                }
            ],
            "upload_sessions": [
                {
                    "upload_session_id": f"upload_session_{private_marker}",
                    "actor_user_id": user_id,
                    "workspace_id": workspace_id,
                }
            ],
            "file_audits": [
                {
                    "audit_log_id": f"file_audit_{private_marker}",
                    "action": "upload_session_created",
                    "actor_user_id": user_id,
                    "workspace_id": workspace_id,
                }
            ],
        }
        phase_cases = (
            ("first", 2, 1),
            ("restart", 3, 1),
        )

        for phase, allowed_count, denied_count in phase_cases:
            with self.subTest(phase=phase):
                events: list[str] = []
                lineage_accesses: set[tuple[str, str]] = set()
                hash_inputs: list[object] = []
                audit_rows = [
                    {
                        "action": "mcp_authorization_allowed",
                        "target_id": f"target_allowed_{index}_{private_marker}",
                        "actor_user_id": user_id,
                        "workspace_id": workspace_id,
                        "external_identity_id": external_identity_id,
                        "oauth_client_id": client_id,
                        "oauth_token_session_id": token_session_id,
                        "request_id": f"request_allowed_{index}_{private_marker}",
                        "tool_call_id": f"tool_allowed_{index}_{private_marker}",
                        "reason_code": "authorized",
                        "status": "ok",
                    }
                    for index in range(allowed_count)
                ]
                audit_rows.extend(
                    {
                        "action": "mcp_authorization_denied",
                        "target_id": f"target_denied_{index}_{private_marker}",
                        "actor_user_id": user_id,
                        "workspace_id": workspace_id,
                        "external_identity_id": external_identity_id,
                        "oauth_client_id": client_id,
                        "oauth_token_session_id": token_session_id,
                        "request_id": f"request_denied_{index}_{private_marker}",
                        "tool_call_id": f"tool_denied_{index}_{private_marker}",
                        "reason_code": "request_not_authorized",
                        "status": "permission_denied",
                    }
                    for index in range(denied_count)
                )
                source_rows_before = copy.deepcopy(core_rows)
                source_audits_before = copy.deepcopy(audit_rows)

                class TrackingAuditRow(dict):
                    def __init__(self, label: str, value: dict[str, object]) -> None:
                        super().__init__(copy.deepcopy(value))
                        self.label = label

                    def get(self, key, default=None):
                        if key in lineage_fields:
                            lineage_accesses.add((self.label, key))
                        return super().get(key, default)

                class FakeConnection:
                    def query_all(self, statement):
                        test_case.assertEqual(statement.parameters, {})
                        sql = statement.sql
                        for table_marker, key in (
                            ("FROM formowl_users", "users"),
                            ("FROM formowl_external_identities", "identities"),
                            ("FROM formowl_workspace_members", "memberships"),
                            ("FROM formowl_oauth_token_sessions", "token_sessions"),
                        ):
                            if table_marker in sql:
                                events.append(f"query:{key}")
                                return copy.deepcopy(core_rows[key])
                        if "FROM formowl_audit_log" in sql:
                            events.append("query:mcp_audits")
                            return [
                                TrackingAuditRow(str(index), row)
                                for index, row in enumerate(audit_rows)
                            ]
                        raise AssertionError("unexpected persisted-state query")

                class FakeRepository:
                    def __init__(self) -> None:
                        self.connection = FakeConnection()
                        self.close_count = 0

                    def close(self) -> None:
                        self.close_count += 1
                        events.append("repository_close")

                repository = FakeRepository()

                class FakePostgreSQLOAuthRepository:
                    @classmethod
                    def connect(cls, database_dsn):
                        del cls
                        events.append("repository_connect")
                        test_case.assertIn(private_marker, database_dsn)
                        return repository

                class FakeConnectedRuntimeConfig:
                    @classmethod
                    def from_env_and_secrets(cls, environ):
                        del cls
                        events.append("config_load")
                        test_case.assertIs(environ, module.os.environ)
                        return SimpleNamespace(
                            database_dsn=f"postgresql://{private_marker}",
                            data_dir=f"data-{private_marker}",
                        )

                class FakeUploadSession:
                    def to_dict(self):
                        events.append("upload_session_to_dict")
                        return copy.deepcopy(core_rows["upload_sessions"][0])

                class FakeUploadSessionStore:
                    def __init__(self, data_dir) -> None:
                        events.append("upload_store_init")
                        test_case.assertIn(private_marker, data_dir)

                    def list(self):
                        events.append("upload_store_list")
                        return [FakeUploadSession()]

                class FakeFileAudit:
                    action = "upload_session_created"

                    def to_dict(self):
                        events.append("file_audit_to_dict")
                        return copy.deepcopy(core_rows["file_audits"][0])

                class FakeFileAuditLogStore:
                    def __init__(self, data_dir) -> None:
                        events.append("file_audit_store_init")
                        test_case.assertIn(private_marker, data_dir)

                    def list(self):
                        events.append("file_audit_store_list")
                        return [FakeFileAudit()]

                real_sha256_json = module._sha256_json

                def record_sha256_json(value):
                    hash_inputs.append(copy.deepcopy(value))
                    events.append("hash:core_state" if len(hash_inputs) == 1 else "hash:snapshot")
                    return real_sha256_json(value)

                expected_core_state = copy.deepcopy(core_rows)
                expected_snapshot = {
                    **copy.deepcopy(expected_core_state),
                    "mcp_audits": copy.deepcopy(audit_rows),
                }
                expected_core_json = module._jsonable(expected_core_state)
                expected_snapshot_json = module._jsonable(expected_snapshot)
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()

                with (
                    mock.patch.dict(
                        module.os.environ,
                        {
                            "FORMOWL_LIFECYCLE_STATE_PHASE": phase,
                            "FORMOWL_LIFECYCLE_EXPECTED_ALLOWED_COUNT": str(allowed_count),
                            "FORMOWL_LIFECYCLE_EXPECTED_DENIED_COUNT": str(denied_count),
                        },
                    ),
                    mock.patch.object(
                        formowl_auth,
                        "PostgreSQLOAuthRepository",
                        FakePostgreSQLOAuthRepository,
                    ),
                    mock.patch.object(
                        formowl_auth,
                        "FileAuditLogStore",
                        FakeFileAuditLogStore,
                    ),
                    mock.patch.object(
                        runtime_module,
                        "ConnectedRuntimeConfig",
                        FakeConnectedRuntimeConfig,
                    ),
                    mock.patch.object(
                        ingestion_storage_module,
                        "UploadSessionStore",
                        FakeUploadSessionStore,
                    ),
                    mock.patch.object(
                        module,
                        "_sha256_json",
                        side_effect=record_sha256_json,
                    ),
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    result = module._inside_persisted_state()

                self.assertEqual(
                    result,
                    {
                        "status": "ok",
                        "phase": phase,
                        "counts": {
                            "user_count": 1,
                            "external_identity_count": 1,
                            "token_session_count": 1,
                            "upload_session_count": 1,
                            "file_audit_count": 1,
                            "mcp_allowed_count": allowed_count,
                            "mcp_denied_count": denied_count,
                        },
                        "core_state_hash": real_sha256_json(expected_core_json),
                        "snapshot_hash": real_sha256_json(expected_snapshot_json),
                    },
                )
                self.assertEqual(
                    tuple(events),
                    (
                        "config_load",
                        "repository_connect",
                        "query:users",
                        "query:identities",
                        "query:memberships",
                        "query:token_sessions",
                        "query:mcp_audits",
                        "upload_store_init",
                        "upload_store_list",
                        "upload_session_to_dict",
                        "file_audit_store_init",
                        "file_audit_store_list",
                        "file_audit_to_dict",
                        "hash:core_state",
                        "hash:snapshot",
                        "repository_close",
                    ),
                )
                self.assertEqual(hash_inputs, [expected_core_json, expected_snapshot_json])
                expected_lineage_accesses = {
                    (str(index), field)
                    for index in range(len(audit_rows))
                    for field in lineage_fields
                }
                self.assertEqual(lineage_accesses, expected_lineage_accesses)
                self.assertEqual(repository.close_count, 1)
                self.assertEqual(core_rows, source_rows_before)
                self.assertEqual(audit_rows, source_audits_before)
                self.assertEqual(public_stdout.getvalue(), "")
                self.assertEqual(public_stderr.getvalue(), "")
                rendered_result = json.dumps(result, sort_keys=True)
                self.assertNotIn(private_marker, rendered_result)
                self.assertNotIn(private_marker, public_stdout.getvalue())
                self.assertNotIn(private_marker, public_stderr.getvalue())

    def test_inside_persisted_state_rejects_inactive_current_membership_after_cleanup(
        self,
    ) -> None:
        from types import SimpleNamespace

        import formowl_auth
        import formowl_gateway.runtime as runtime_module
        import formowl_ingestion.storage as ingestion_storage_module

        module = _load_lifecycle_probe()
        private_marker = "inactive-membership-private-marker"
        events: list[str] = []
        test_case = self
        audit_lineage_fields = frozenset(
            {
                "actor_user_id",
                "workspace_id",
                "external_identity_id",
                "oauth_client_id",
                "oauth_token_session_id",
                "request_id",
                "tool_call_id",
                "reason_code",
            }
        )

        class LineageGuardedAuditRow(dict):
            def get(self, key, default=None):
                if key in audit_lineage_fields:
                    events.append(f"unexpected_audit_lineage_access:{key}")
                    raise AssertionError(
                        "audit lineage validation ran before membership validation"
                    )
                return super().get(key, default)

        membership_cases = (
            (
                "removed",
                {
                    "workspace_id": "workspace_primary",
                    "user_id": "user_primary",
                    "role": "owner",
                    "removed_at": private_marker,
                },
            ),
            (
                "user_mismatch",
                {
                    "workspace_id": "workspace_primary",
                    "user_id": f"user_{private_marker}",
                    "role": "owner",
                    "removed_at": None,
                },
            ),
            (
                "workspace_mismatch",
                {
                    "workspace_id": f"workspace_{private_marker}",
                    "user_id": "user_primary",
                    "role": "owner",
                    "removed_at": None,
                },
            ),
        )
        rows = {
            "users": [
                {
                    "user_id": "user_primary",
                    "status": "active",
                }
            ],
            "identities": [
                {
                    "external_identity_id": "identity_primary",
                    "issuer": "https://accounts.google.com",
                    "subject": "subject_primary",
                    "user_id": "user_primary",
                    "status": "active",
                }
            ],
            "memberships": [
                {
                    "workspace_id": "workspace_primary",
                    "user_id": "user_primary",
                    "role": "owner",
                    "removed_at": None,
                }
            ],
            "token_sessions": [
                {
                    "token_session_id": "token_session_primary",
                    "user_id": "user_primary",
                    "external_identity_id": "identity_primary",
                    "client_id": "client_primary",
                    "current_workspace_id": "workspace_primary",
                    "resource": "https://formowl.example.test/mcp",
                    "scopes": ["formowl.use"],
                    "issued_at": "2026-07-19T00:00:00+00:00",
                    "expires_at": "2026-07-19T01:00:00+00:00",
                    "revoked_at": None,
                }
            ],
            "mcp_audits": [
                LineageGuardedAuditRow(
                    {
                        "action": action,
                        "target_id": f"target_{index}",
                        "actor_user_id": "user_primary",
                        "workspace_id": "workspace_primary",
                        "external_identity_id": "identity_primary",
                        "oauth_client_id": "client_primary",
                        "oauth_token_session_id": "token_session_primary",
                        "request_id": f"request_{index}",
                        "tool_call_id": f"tool_call_{index}",
                        "reason_code": reason_code,
                        "status": status,
                    }
                )
                for index, (action, reason_code, status) in enumerate(
                    (
                        ("mcp_authorization_allowed", "authorized", "ok"),
                        ("mcp_authorization_allowed", "authorized", "ok"),
                        (
                            "mcp_authorization_denied",
                            "request_not_authorized",
                            "permission_denied",
                        ),
                    ),
                    start=1,
                )
            ],
        }

        class FakeConnection:
            def query_all(self, statement):
                sql = statement.sql
                for table_marker, key in (
                    ("FROM formowl_users", "users"),
                    ("FROM formowl_external_identities", "identities"),
                    ("FROM formowl_workspace_members", "memberships"),
                    ("FROM formowl_oauth_token_sessions", "token_sessions"),
                    ("FROM formowl_audit_log", "mcp_audits"),
                ):
                    if table_marker in sql:
                        events.append(f"query:{key}")
                        return copy.deepcopy(rows[key])
                raise AssertionError("unexpected persisted-state query")

        class FakeRepository:
            def __init__(self) -> None:
                self.connection = FakeConnection()
                self.close_count = 0

            def close(self) -> None:
                self.close_count += 1
                events.append("repository_close")

        repository = FakeRepository()

        class FakePostgreSQLOAuthRepository:
            @classmethod
            def connect(cls, database_dsn):
                del cls
                events.append("repository_connect")
                test_case.assertIn(private_marker, database_dsn)
                return repository

        class FakeConnectedRuntimeConfig:
            @classmethod
            def from_env_and_secrets(cls, environ):
                del cls
                events.append("config_load")
                test_case.assertIs(environ, module.os.environ)
                return SimpleNamespace(
                    database_dsn=f"postgresql://{private_marker}",
                    data_dir=f"data-{private_marker}",
                )

        class FakeUploadSession:
            def to_dict(self):
                events.append("upload_session_to_dict")
                return {
                    "upload_session_id": "upload_session_primary",
                    "actor_user_id": "user_primary",
                    "workspace_id": "workspace_primary",
                }

        class FakeUploadSessionStore:
            def __init__(self, data_dir) -> None:
                events.append("upload_store_init")
                test_case.assertIn(private_marker, data_dir)

            def list(self):
                events.append("upload_store_list")
                return [FakeUploadSession()]

        class FakeFileAudit:
            action = "upload_session_created"

            def to_dict(self):
                events.append("file_audit_to_dict")
                return {
                    "audit_log_id": "file_audit_primary",
                    "action": self.action,
                    "actor_user_id": "user_primary",
                    "workspace_id": "workspace_primary",
                }

        class FakeFileAuditLogStore:
            def __init__(self, data_dir) -> None:
                events.append("file_audit_store_init")
                test_case.assertIn(private_marker, data_dir)

            def list(self):
                events.append("file_audit_store_list")
                return [FakeFileAudit()]

        expected_events = (
            "config_load",
            "repository_connect",
            "query:users",
            "query:identities",
            "query:memberships",
            "query:token_sessions",
            "query:mcp_audits",
            "upload_store_init",
            "upload_store_list",
            "upload_session_to_dict",
            "file_audit_store_init",
            "file_audit_store_list",
            "file_audit_to_dict",
            "repository_close",
        )

        for case_name, membership in membership_cases:
            with self.subTest(case=case_name):
                events.clear()
                repository.close_count = 0
                rows["memberships"][0] = copy.deepcopy(membership)
                rows_before = copy.deepcopy(rows)
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()
                result_sentinel = object()
                result = result_sentinel

                with (
                    mock.patch.dict(
                        module.os.environ,
                        {
                            "FORMOWL_LIFECYCLE_STATE_PHASE": "first",
                            "FORMOWL_LIFECYCLE_EXPECTED_ALLOWED_COUNT": "2",
                            "FORMOWL_LIFECYCLE_EXPECTED_DENIED_COUNT": "1",
                        },
                    ),
                    mock.patch.object(
                        formowl_auth,
                        "PostgreSQLOAuthRepository",
                        FakePostgreSQLOAuthRepository,
                    ),
                    mock.patch.object(
                        formowl_auth,
                        "FileAuditLogStore",
                        FakeFileAuditLogStore,
                    ),
                    mock.patch.object(
                        runtime_module,
                        "ConnectedRuntimeConfig",
                        FakeConnectedRuntimeConfig,
                    ),
                    mock.patch.object(
                        ingestion_storage_module,
                        "UploadSessionStore",
                        FakeUploadSessionStore,
                    ),
                    mock.patch.object(
                        module,
                        "_sha256_json",
                        side_effect=AssertionError(
                            "persisted-state hashing ran before membership validation"
                        ),
                    ) as sha256_json,
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                    self.assertRaises(module.LifecycleProbeFailure) as raised,
                ):
                    result = module._inside_persisted_state()

                self.assertIs(result, result_sentinel)
                self.assertEqual(raised.exception.stage, "inside_state")
                self.assertEqual(raised.exception.code, "persisted_membership_invalid")
                self.assertEqual(tuple(events), expected_events)
                sha256_json.assert_not_called()
                self.assertEqual(repository.close_count, 1)
                self.assertEqual(rows, rows_before)
                self.assertEqual(public_stdout.getvalue(), "")
                self.assertEqual(public_stderr.getvalue(), "")
                self.assertNotIn(private_marker, str(raised.exception))
                self.assertNotIn(private_marker, public_stdout.getvalue())
                self.assertNotIn(private_marker, public_stderr.getvalue())

    def test_inside_seed_bearer_file_completes_short_writes_at_mode_0400(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        access_token = "sensitive-bearer-token-for-short-write"
        real_write = os.write
        write_sizes: list[int] = []

        def short_write(descriptor, value):
            chunk_size = max(1, len(value) // 2)
            written = real_write(descriptor, bytes(value[:chunk_size]))
            write_sizes.append(written)
            return written

        with tempfile.TemporaryDirectory(
            prefix="formowl-bearer-short-write-",
            dir=tempfile.gettempdir(),
        ) as directory:
            token_path = Path(directory) / "bearer"
            with mock.patch.object(module.os, "write", side_effect=short_write):
                module._write_inside_seed_bearer_file(token_path, access_token)

            self.assertGreater(len(write_sizes), 1)
            self.assertEqual(token_path.read_text(encoding="ascii"), access_token)
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o400)

    def test_inside_seed_bearer_file_failures_clean_up_for_safe_retry(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        access_token = "sensitive-bearer-token-for-failure"
        fault_detail = "sensitive-write-fault-detail"
        real_close = os.close
        real_open = os.open

        with tempfile.TemporaryDirectory(
            prefix="formowl-bearer-failure-",
            dir=tempfile.gettempdir(),
        ) as directory:
            root = Path(directory)
            for failure_name in ("write", "fsync", "close", "stat", "mode"):
                with self.subTest(failure_name=failure_name):
                    token_path = root / failure_name
                    if failure_name == "write":
                        patcher = mock.patch.object(
                            module.os,
                            "write",
                            side_effect=OSError(fault_detail),
                        )
                    elif failure_name == "fsync":
                        patcher = mock.patch.object(
                            module.os,
                            "fsync",
                            side_effect=OSError(fault_detail),
                        )
                    elif failure_name == "close":

                        def close_then_fail(descriptor):
                            real_close(descriptor)
                            raise OSError(fault_detail)

                        patcher = mock.patch.object(
                            module.os,
                            "close",
                            side_effect=close_then_fail,
                        )
                    elif failure_name == "stat":
                        patcher = mock.patch.object(
                            Path,
                            "stat",
                            side_effect=OSError(fault_detail),
                        )
                    else:

                        def open_with_wrong_mode(path, flags, _mode):
                            return real_open(path, flags, 0o600)

                        patcher = mock.patch.object(
                            module.os,
                            "open",
                            side_effect=open_with_wrong_mode,
                        )

                    with (
                        patcher,
                        self.assertRaises(module.LifecycleProbeFailure) as raised,
                    ):
                        module._write_inside_seed_bearer_file(
                            token_path,
                            access_token,
                        )

                    expected_code = {
                        "write": "bearer_file_write_failed",
                        "fsync": "bearer_file_write_failed",
                        "close": "bearer_file_close_failed",
                        "stat": "bearer_file_stat_failed",
                        "mode": "bearer_file_mode_invalid",
                    }[failure_name]
                    self.assertEqual(raised.exception.stage, "inside_seed")
                    self.assertEqual(raised.exception.code, expected_code)
                    self.assertNotIn(access_token, str(raised.exception))
                    self.assertNotIn(fault_detail, str(raised.exception))
                    self.assertFalse(token_path.exists())

                    module._write_inside_seed_bearer_file(
                        token_path,
                        access_token,
                    )
                    self.assertEqual(
                        token_path.read_text(encoding="ascii"),
                        access_token,
                    )
                    self.assertEqual(token_path.stat().st_mode & 0o777, 0o400)

    def test_lifecycle_build_captures_and_inspects_exact_runtime_iid(self) -> None:
        module = _load_lifecycle_probe()
        runtime_image_id = "sha256:" + "a" * 64
        implementation_contract_hash = module._current_issue20_implementation_contract_hash()
        commands: list[list[str]] = []

        with tempfile.TemporaryDirectory(
            prefix="formowl-runtime-iid-",
            dir=tempfile.gettempdir(),
        ) as value:
            iidfile = Path(value) / "runtime.iid"

            def fake_run(command, **_kwargs):
                rendered = list(command)
                commands.append(rendered)
                if rendered[:2] == ["docker", "build"]:
                    Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                        runtime_image_id + "\n",
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(rendered, 0, "", "")
                return subprocess.CompletedProcess(
                    rendered,
                    0,
                    json.dumps(
                        [
                            {
                                "Id": runtime_image_id,
                                "Config": {
                                    "Entrypoint": ["formowl-container-entrypoint"],
                                    "Cmd": ["serve"],
                                    "User": "root",
                                    "WorkingDir": "/home/formowl",
                                    "Labels": {
                                        module.IMPLEMENTATION_CONTRACT_IMAGE_LABEL: (
                                            implementation_contract_hash
                                        )
                                    },
                                },
                            }
                        ]
                    ),
                    "",
                )

            with mock.patch.object(module, "_run_command", side_effect=fake_run):
                actual_image_id, contract = module._build_runtime_image(iidfile)

        self.assertEqual(actual_image_id, runtime_image_id)
        self.assertEqual(contract["runtime_image_id"], runtime_image_id)
        self.assertEqual(commands[0][:2], ["docker", "build"])
        self.assertIn("--iidfile", commands[0])
        self.assertNotIn("--tag", commands[0])
        self.assertEqual(
            commands[1],
            ["docker", "image", "inspect", runtime_image_id],
        )

    def test_lifecycle_invalid_iid_stops_before_inspect_or_runtime_run(self) -> None:
        module = _load_lifecycle_probe()
        for name, iid_value in (
            ("missing", None),
            ("mutable_tag", "formowl-runtime:local"),
            ("short_digest", "sha256:abc"),
        ):
            with self.subTest(name=name):
                commands: list[list[str]] = []
                with tempfile.TemporaryDirectory(
                    prefix="formowl-runtime-invalid-iid-",
                    dir=tempfile.gettempdir(),
                ) as value:
                    iidfile = Path(value) / "runtime.iid"

                    def fake_run(command, **_kwargs):
                        rendered = list(command)
                        commands.append(rendered)
                        if iid_value is not None:
                            Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                                iid_value + "\n",
                                encoding="utf-8",
                            )
                        return subprocess.CompletedProcess(rendered, 0, "", "")

                    with (
                        mock.patch.object(module, "_run_command", side_effect=fake_run),
                        self.assertRaises(module.LifecycleProbeFailure),
                    ):
                        module._build_runtime_image(iidfile)

                self.assertEqual(len(commands), 1)
                self.assertEqual(commands[0][:2], ["docker", "build"])
                self.assertFalse(any(command[:2] == ["docker", "run"] for command in commands))

    def test_write_signing_manifest_rejects_invalid_phase_and_missing_overlap_expiry_before_write(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        private_marker = "unique-private-signing-marker-/tmp/formowl-signing"
        cases = (
            (
                "invalid_phase",
                f"unexpected-{private_marker}",
                "signing_manifest_phase_invalid",
            ),
            (
                "overlap_without_expiry",
                "overlap",
                "overlap_expiry_missing",
            ),
        )

        with tempfile.TemporaryDirectory(
            prefix="formowl-signing-manifest-invalid-",
            dir=tempfile.gettempdir(),
        ) as value:
            secret_dir = Path(value)
            for name, phase, expected_code in cases:
                with self.subTest(name=name):
                    result_marker = object()
                    actual = result_marker
                    failure = None
                    public_stdout = io.StringIO()
                    public_stderr = io.StringIO()
                    before_entries = tuple(secret_dir.iterdir())

                    with (
                        mock.patch.object(
                            module,
                            "_atomic_write",
                            side_effect=AssertionError(
                                "signing manifest validation reached durable write"
                            ),
                        ) as atomic_write,
                        redirect_stdout(public_stdout),
                        redirect_stderr(public_stderr),
                    ):
                        try:
                            actual = module._write_signing_manifest(
                                secret_dir,
                                phase=phase,
                                verify_until=None,
                            )
                        except module.LifecycleProbeFailure as error:
                            failure = error

                    self.assertIs(actual, result_marker)
                    self.assertIs(type(failure), module.LifecycleProbeFailure)
                    self.assertEqual(failure.stage, "secret_reload")
                    self.assertEqual(failure.code, expected_code)
                    atomic_write.assert_not_called()
                    self.assertEqual(tuple(secret_dir.iterdir()), before_entries)
                    public_output = public_stdout.getvalue() + public_stderr.getvalue()
                    self.assertEqual(public_output, "")
                    self.assertNotIn(private_marker, str(failure))
                    self.assertNotIn(private_marker, public_output)

    def test_image_bound_helpers_reject_invalid_image_identity_before_downstream_work(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        private_marker = "unique-private-image-marker-/tmp/formowl-runtime"
        mutable_non_string = ["sha256:" + "a" * 64]
        short_digest = "sha256:abc"
        mutable_tag = f"formowl-runtime:local-{private_marker}"

        with tempfile.TemporaryDirectory(
            prefix="formowl-image-bound-invalid-",
            dir=tempfile.gettempdir(),
        ) as value:
            root = Path(value)
            helper_cases = (
                (
                    "_generate_signing_keys",
                    mutable_non_string,
                    "secret_setup",
                    lambda image: module._generate_signing_keys(image, root / "secrets"),
                ),
                (
                    "_prepare_data_directory",
                    short_digest,
                    "data_setup",
                    lambda image: module._prepare_data_directory(image, root / "data"),
                ),
                (
                    "_restore_data_directory_ownership",
                    mutable_tag,
                    "cleanup",
                    lambda image: module._restore_data_directory_ownership(
                        image,
                        root / "data",
                    ),
                ),
                (
                    "_remove_runtime_image",
                    mutable_non_string,
                    "cleanup",
                    module._remove_runtime_image,
                ),
                (
                    "_runtime_run_command",
                    short_digest,
                    "runtime_command",
                    lambda image: module._runtime_run_command(
                        image=image,
                        network="formowl-network",
                        data_dir=root / "data",
                        secret_dir=root / "secrets",
                        command="serve",
                    ),
                ),
                (
                    "_seed_oauth_state",
                    mutable_tag,
                    "oauth_seed",
                    lambda image: module._seed_oauth_state(
                        image=image,
                        network="formowl-network",
                        data_dir=root / "data",
                        secret_dir=root / "secrets",
                        probe_dir=root / "probe",
                        secret_values=(private_marker,),
                    ),
                ),
                (
                    "_run_official_container_client",
                    short_digest,
                    "first_mcp_client",
                    lambda image: module._run_official_container_client(
                        image=image,
                        network="formowl-network",
                        runtime_name="formowl-runtime",
                        probe_dir=root / "probe",
                        phase="first",
                        secret_values=(private_marker,),
                    ),
                ),
                (
                    "_read_persisted_state",
                    mutable_tag,
                    "first_state",
                    lambda image: module._read_persisted_state(
                        image=image,
                        network="formowl-network",
                        data_dir=root / "data",
                        secret_dir=root / "secrets",
                        phase="first",
                        expected_allowed=1,
                        expected_denied=1,
                        secret_values=(private_marker,),
                    ),
                ),
            )

            for helper_name, invalid_image, expected_stage, invoke in helper_cases:
                with self.subTest(helper=helper_name):
                    original_image = copy.deepcopy(invalid_image)
                    result_marker = object()
                    actual = result_marker
                    failure = None
                    public_stdout = io.StringIO()
                    public_stderr = io.StringIO()
                    before_entries = tuple(root.iterdir())

                    with ExitStack() as stack:
                        downstream_mocks = [
                            stack.enter_context(
                                mock.patch.object(
                                    module,
                                    name,
                                    side_effect=AssertionError(
                                        f"{helper_name} reached downstream helper {name}"
                                    ),
                                )
                            )
                            for name in (
                                "_run_command",
                                "_inside_helper_result",
                                "_launcher_security_args",
                                "_runtime_secret_mount_args",
                                "_runtime_environment",
                            )
                        ]
                        uid_mock = stack.enter_context(
                            mock.patch.object(
                                module.os,
                                "getuid",
                                side_effect=AssertionError(f"{helper_name} resolved host uid"),
                            )
                        )
                        gid_mock = stack.enter_context(
                            mock.patch.object(
                                module.os,
                                "getgid",
                                side_effect=AssertionError(f"{helper_name} resolved host gid"),
                            )
                        )
                        stack.enter_context(redirect_stdout(public_stdout))
                        stack.enter_context(redirect_stderr(public_stderr))
                        try:
                            actual = invoke(invalid_image)
                        except module.LifecycleProbeFailure as error:
                            failure = error

                    self.assertIs(actual, result_marker)
                    self.assertIs(type(failure), module.LifecycleProbeFailure)
                    self.assertEqual(failure.stage, expected_stage)
                    self.assertEqual(failure.code, "runtime_image_id_invalid")
                    self.assertEqual(invalid_image, original_image)
                    for downstream_mock in downstream_mocks:
                        downstream_mock.assert_not_called()
                    uid_mock.assert_not_called()
                    gid_mock.assert_not_called()
                    self.assertEqual(tuple(root.iterdir()), before_entries)
                    public_output = public_stdout.getvalue() + public_stderr.getvalue()
                    self.assertEqual(public_output, "")
                    self.assertNotIn(private_marker, str(failure))
                    self.assertNotIn(private_marker, public_output)
                    self.assertNotIn(str(invalid_image), public_output)

    def test_compose_resolution_is_bound_to_runtime_iid_and_postgres_digest(self) -> None:
        module = _load_lifecycle_probe()
        runtime_image_id = "sha256:" + "a" * 64

        def resolved_payload(
            *,
            connected_image: str = runtime_image_id,
            migrate_image: str = runtime_image_id,
            project_image: str = runtime_image_id,
            wiki_image: str = runtime_image_id,
            postgres_image: str = module.PINNED_POSTGRES_IMAGE,
        ) -> dict[str, object]:
            runtime_secrets = [{"source": name} for name in module._RUNTIME_SECRET_NAMES]
            return {
                "services": {
                    "connected-mcp": {
                        "image": connected_image,
                        "build": {"dockerfile": "containers/runtime/Dockerfile"},
                        "command": ["serve"],
                        "read_only": True,
                        "cap_drop": ["ALL"],
                        "cap_add": list(module.LAUNCHER_CAPABILITIES),
                        "security_opt": ["no-new-privileges:true"],
                        "tmpfs": [
                            "/tmp:size=64m,mode=1777",
                            "/run/formowl-secrets:size=1m,mode=0700",
                        ],
                        "stop_grace_period": "30s",
                        "healthcheck": {
                            "test": [
                                "CMD",
                                "formowl-container-entrypoint",
                                "check",
                                "/readyz",
                            ]
                        },
                        "secrets": runtime_secrets,
                    },
                    "connected-migrate": {
                        "image": migrate_image,
                        "command": ["migrate"],
                        "secrets": runtime_secrets,
                    },
                    "postgres": {
                        "image": postgres_image,
                        "secrets": [{"source": "formowl_postgres_password"}],
                    },
                    "project-mcp": {
                        "image": project_image,
                        "command": ["python", "-m", "formowl_project_mcp"],
                    },
                    "wiki-mcp": {
                        "image": wiki_image,
                        "command": ["python", "-m", "formowl_wiki_mcp"],
                    },
                }
            }

        with tempfile.TemporaryDirectory(
            prefix="formowl-compose-",
            dir=tempfile.gettempdir(),
        ) as value:
            secret_dir = Path(value)
            for name in ("formowl_postgres_password", *module._RUNTIME_SECRET_NAMES):
                path = secret_dir / name
                path.write_text("fixture\n", encoding="utf-8")
                os.chmod(path, 0o400)
            captured_environment: dict[str, str] = {}

            def fake_run(command, *, environ=None, **_kwargs):
                captured_environment.update(environ or {})
                return subprocess.CompletedProcess(
                    list(command),
                    0,
                    json.dumps(resolved_payload()),
                    "",
                )

            with mock.patch.object(module, "_run_command", side_effect=fake_run):
                projection, service_count = module._validate_compose_config(
                    secret_dir,
                    runtime_image_id,
                )

            self.assertEqual(service_count, 5)
            self.assertEqual(captured_environment["FORMOWL_RUNTIME_IMAGE"], runtime_image_id)
            self.assertEqual(
                captured_environment["FORMOWL_POSTGRES_IMAGE"],
                module.PINNED_POSTGRES_IMAGE,
            )
            self.assertEqual(projection["connected_image_id"], runtime_image_id)
            self.assertEqual(projection["migrate_image_id"], runtime_image_id)
            self.assertEqual(projection["project_image_id"], runtime_image_id)
            self.assertEqual(projection["wiki_image_id"], runtime_image_id)
            self.assertEqual(projection["postgres_image"], module.PINNED_POSTGRES_IMAGE)
            self.assertEqual(projection["operator_owned_0400_secret_count"], 7)
            self.assertTrue(projection["secret_owner_distinct_from_runtime"])

            for field, value in (
                ("connected_image", "formowl-runtime:local"),
                ("migrate_image", "sha256:" + "b" * 64),
                ("project_image", "formowl-runtime:local"),
                ("wiki_image", "sha256:" + "b" * 64),
                ("postgres_image", "pgvector/pgvector:0.8.0-pg17"),
            ):
                with self.subTest(field=field):
                    payload = resolved_payload(**{field: value})
                    commands: list[list[str]] = []

                    def fake_drift(command, **_kwargs):
                        commands.append(list(command))
                        return subprocess.CompletedProcess(
                            list(command),
                            0,
                            json.dumps(payload),
                            "",
                        )

                    with (
                        mock.patch.object(module, "_run_command", side_effect=fake_drift),
                        self.assertRaises(module.LifecycleProbeFailure),
                    ):
                        module._validate_compose_config(secret_dir, runtime_image_id)
                    self.assertFalse(any(command[:2] == ["docker", "run"] for command in commands))

            with (
                mock.patch.object(module, "_run_command") as run_command,
                self.assertRaises(module.LifecycleProbeFailure),
            ):
                module._validate_compose_config(secret_dir, "sha256:short")
            run_command.assert_not_called()

    def test_all_lifecycle_runtime_run_paths_use_the_exact_iid(self) -> None:
        module = _load_lifecycle_probe()
        runtime_image_id = "sha256:" + "a" * 64
        commands: list[list[str]] = []
        helper_commands: list[list[str]] = []

        with tempfile.TemporaryDirectory(
            prefix="formowl-runtime-paths-",
            dir=tempfile.gettempdir(),
        ) as value:
            root = Path(value)
            secret_dir = root / "secrets"
            data_dir = root / "data"
            probe_dir = root / "probe"
            secret_dir.mkdir()
            data_dir.mkdir()
            probe_dir.mkdir()

            def fake_run(command, **_kwargs):
                rendered = list(command)
                commands.append(rendered)
                if "key-a.pem" in " ".join(rendered):
                    (secret_dir / "key-a.pem").write_bytes(b"key-a")
                    (secret_dir / "key-b.pem").write_bytes(b"key-b")
                return subprocess.CompletedProcess(rendered, 0, "", "")

            def fake_helper(command, **_kwargs):
                helper_commands.append(list(command))
                return {"status": "ok"}

            token_file = probe_dir / "formowl_bearer_token"
            token_file.write_bytes(b"a" * 64)
            os.chmod(token_file, 0o400)

            with (
                mock.patch.object(module, "_run_command", side_effect=fake_run),
                mock.patch.object(module, "_inside_helper_result", side_effect=fake_helper),
            ):
                module._generate_signing_keys(runtime_image_id, secret_dir)
                module._prepare_data_directory(runtime_image_id, data_dir)
                self.assertTrue(
                    module._restore_data_directory_ownership(runtime_image_id, data_dir)
                )
                module._seed_oauth_state(
                    image=runtime_image_id,
                    network="runtime-network",
                    data_dir=data_dir,
                    secret_dir=secret_dir,
                    probe_dir=probe_dir,
                    secret_values=(),
                )
                module._run_official_container_client(
                    image=runtime_image_id,
                    network="runtime-network",
                    runtime_name="runtime-name",
                    probe_dir=probe_dir,
                    phase="first",
                    secret_values=(),
                )
                module._read_persisted_state(
                    image=runtime_image_id,
                    network="runtime-network",
                    data_dir=data_dir,
                    secret_dir=secret_dir,
                    phase="first",
                    expected_allowed=2,
                    expected_denied=1,
                    secret_values=(),
                )
                self.assertTrue(module._remove_runtime_image(runtime_image_id))

            for runtime_command in ("migrate", "preflight", "serve"):
                command = module._runtime_run_command(
                    image=runtime_image_id,
                    network="runtime-network",
                    data_dir=data_dir,
                    secret_dir=secret_dir,
                    command=runtime_command,
                    detach=runtime_command == "serve",
                )
                self.assertEqual(command[-2:], [runtime_image_id, runtime_command])

        docker_run_commands = [
            command for command in [*commands, *helper_commands] if command[:2] == ["docker", "run"]
        ]
        self.assertEqual(len(docker_run_commands), 6)
        for command in docker_run_commands:
            self.assertIn(runtime_image_id, command)
            self.assertNotIn("formowl-runtime:local", command)
        self.assertIn(
            ["docker", "image", "rm", "--force", runtime_image_id],
            commands,
        )

    def test_actual_compose_journey_runs_migrate_preflight_and_fresh_secret_generations(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        runtime_image_id = "sha256:" + "a" * 64
        compose_calls: list[tuple[str, ...]] = []

        def fake_compose(_project_name, *arguments, **_kwargs):
            compose_calls.append(tuple(arguments))
            if arguments[-1:] == ("connected-migrate",):
                stdout = json.dumps(
                    {
                        "status": "ok",
                        "applied_migration_count": 5,
                        "skipped_migration_count": 0,
                    }
                )
            elif arguments[-2:] == ("connected-mcp", "preflight"):
                stdout = json.dumps({"status": "ready", "checks": {"database": True}})
            else:
                stdout = ""
            return subprocess.CompletedProcess(list(arguments), 0, stdout, "")

        public_jwks = (
            {
                "keys": [
                    {
                        "kid": module.INITIAL_KID,
                        "kty": "RSA",
                        "alg": "RS256",
                        "n": "initial",
                        "e": "AQAB",
                    }
                ]
            },
            {
                "keys": [
                    {
                        "kid": module.INITIAL_KID,
                        "kty": "RSA",
                        "alg": "RS256",
                        "n": "initial",
                        "e": "AQAB",
                    },
                    {
                        "kid": module.ROTATED_KID,
                        "kty": "RSA",
                        "alg": "RS256",
                        "n": "rotated",
                        "e": "AQAB",
                    },
                ]
            },
            {
                "keys": [
                    {
                        "kid": module.ROTATED_KID,
                        "kty": "RSA",
                        "alg": "RS256",
                        "n": "rotated",
                        "e": "AQAB",
                    }
                ]
            },
        )
        snapshots = [
            {
                "content_hash": module._sha256_json({"phase": "initial"}),
                "file_count": 5,
                "instance_hash": module._sha256_json({"instance": 1}),
            },
            {
                "content_hash": module._sha256_json({"phase": "overlap"}),
                "file_count": 6,
                "instance_hash": module._sha256_json({"instance": 2}),
            },
            {
                "content_hash": module._sha256_json({"phase": "retired"}),
                "file_count": 5,
                "instance_hash": module._sha256_json({"instance": 3}),
            },
        ]
        with tempfile.TemporaryDirectory(
            prefix="formowl-compose-live-",
            dir=tempfile.gettempdir(),
        ) as value:
            secret_dir = Path(value)
            for name in (
                "formowl_postgres_password",
                "formowl_google_client_secret",
                "formowl_state_encryption_key",
            ):
                path = secret_dir / name
                path.write_text("fixture", encoding="utf-8")
                os.chmod(path, 0o400)
            with (
                mock.patch.object(module, "_reserve_loopback_port", return_value=43123),
                mock.patch.object(
                    module,
                    "_run_compose_command",
                    side_effect=fake_compose,
                ),
                mock.patch.object(
                    module,
                    "_compose_container_id",
                    side_effect=("a" * 64, "b" * 64, "c" * 64, "d" * 64),
                ),
                mock.patch.object(module, "_wait_for_healthy_container"),
                mock.patch.object(
                    module,
                    "_compose_postgres_secret_contract",
                    return_value={
                        "same_operator_owned_source": True,
                        "secret_mount_read_only": True,
                        "postgres_healthy": True,
                    },
                ),
                mock.patch.object(
                    module,
                    "_wait_for_ready",
                    return_value={"status": "ready", "checks": {"database": True}},
                ),
                mock.patch.object(
                    module,
                    "_runtime_security_contract",
                    side_effect=({"phase": 1}, {"phase": 2}, {"phase": 3}),
                ) as security_contract,
                mock.patch.object(
                    module,
                    "_staged_secret_snapshot",
                    side_effect=snapshots,
                ),
                mock.patch.object(
                    module,
                    "_fetch_public_jwks",
                    side_effect=public_jwks,
                ),
                mock.patch.object(module, "_assert_container_removed") as removed,
                mock.patch.object(
                    module,
                    "_run_command",
                    return_value=subprocess.CompletedProcess([], 0, "", ""),
                ),
            ):
                result = module._run_actual_compose_journey(
                    runtime_image_id=runtime_image_id,
                    secret_dir=secret_dir,
                    password="database-password",
                    key_a=b"key-a",
                    key_b=b"key-b",
                    secret_values=("database-password", str(secret_dir)),
                )

            self.assertEqual(result["runtime_ready_count"], 3)
            self.assertEqual(result["healthcheck_success_count"], 3)
            self.assertEqual(result["retired_container_count"], 2)
            self.assertEqual([item["key_count"] for item in result["jwks_phases"]], [1, 2, 1])
            self.assertIn(
                ("run", "--rm", "--no-deps", "connected-migrate"),
                compose_calls,
            )
            self.assertIn(
                ("run", "--rm", "--no-deps", "connected-mcp", "preflight"),
                compose_calls,
            )
            recreate_calls = [
                call
                for call in compose_calls
                if call[:4] == ("up", "--detach", "--no-deps", "--force-recreate")
            ]
            self.assertEqual(len(recreate_calls), 3)
            self.assertEqual(
                compose_calls[-1],
                ("down", "--volumes", "--remove-orphans", "--timeout", "30"),
            )
            self.assertEqual(removed.call_count, 2)
            self.assertEqual(security_contract.call_count, 3)
            for call in security_contract.call_args_list:
                self.assertTrue(call.kwargs["require_compose_healthcheck"])
            for name in (
                "formowl_database_dsn",
                "formowl_signing_key_current",
                "formowl_signing_key_previous",
                "formowl_signing_key_set",
            ):
                self.assertEqual((secret_dir / name).stat().st_mode & 0o777, 0o400)

    def test_actual_compose_journey_validation_failure_cleans_up_without_partial_success_evidence(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        runtime_image_id = "sha256:" + "a" * 64
        password = "database-password"
        compose_calls: list[tuple[str, ...]] = []

        def fake_compose(_project_name, *arguments, **_kwargs):
            compose_calls.append(tuple(arguments))
            if arguments[-1:] == ("connected-migrate",):
                stdout = json.dumps(
                    {
                        "status": "ok",
                        "applied_migration_count": 4,
                        "skipped_migration_count": 0,
                    }
                )
            else:
                stdout = ""
            return subprocess.CompletedProcess(list(arguments), 0, stdout, "")

        with tempfile.TemporaryDirectory(
            prefix="formowl-compose-validation-failure-",
            dir=tempfile.gettempdir(),
        ) as value:
            secret_dir = Path(value)
            with (
                mock.patch.object(module, "_compose_environment", return_value={}),
                mock.patch.object(module, "_reserve_loopback_port", return_value=43123),
                mock.patch.object(
                    module,
                    "_run_compose_command",
                    side_effect=fake_compose,
                ),
                mock.patch.object(
                    module,
                    "_compose_container_id",
                    return_value="b" * 64,
                ),
                mock.patch.object(module, "_wait_for_healthy_container"),
                mock.patch.object(
                    module,
                    "_compose_postgres_secret_contract",
                    return_value={
                        "same_operator_owned_source": True,
                        "secret_mount_read_only": True,
                        "postgres_healthy": True,
                    },
                ),
                mock.patch.object(module, "_wait_for_ready") as ready,
                mock.patch.object(module, "_runtime_security_contract") as security,
                mock.patch.object(module, "_staged_secret_snapshot") as snapshot,
                mock.patch.object(module, "_fetch_public_jwks") as fetch_jwks,
                mock.patch.object(module, "_run_command") as runtime_logs,
                self.assertRaises(module.LifecycleProbeFailure) as raised,
            ):
                module._run_actual_compose_journey(
                    runtime_image_id=runtime_image_id,
                    secret_dir=secret_dir,
                    password=password,
                    key_a=b"key-a",
                    key_b=b"key-b",
                    secret_values=(password, str(secret_dir)),
                )

        self.assertEqual(raised.exception.stage, "compose_migrate")
        self.assertEqual(raised.exception.code, "compose_migrate_result_invalid")
        self.assertEqual(
            compose_calls,
            [
                ("up", "--detach", "postgres"),
                ("run", "--rm", "--no-deps", "connected-migrate"),
                ("down", "--volumes", "--remove-orphans", "--timeout", "30"),
            ],
        )
        ready.assert_not_called()
        security.assert_not_called()
        snapshot.assert_not_called()
        fetch_jwks.assert_not_called()
        runtime_logs.assert_not_called()
        self.assertNotIn(password, str(raised.exception))
        self.assertNotIn(str(secret_dir), str(raised.exception))

    def test_actual_compose_journey_cleanup_failure_is_generic_and_suppresses_success_evidence(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        runtime_image_id = "sha256:" + "a" * 64
        password = "database-password"
        compose_calls: list[tuple[str, ...]] = []

        def fake_compose(_project_name, *arguments, **_kwargs):
            compose_calls.append(tuple(arguments))
            if arguments[-1:] == ("connected-migrate",):
                stdout = json.dumps(
                    {
                        "status": "ok",
                        "applied_migration_count": 5,
                        "skipped_migration_count": 0,
                    }
                )
            elif arguments[-2:] == ("connected-mcp", "preflight"):
                stdout = json.dumps(
                    {
                        "status": "ready",
                        "checks": {"database": True},
                    }
                )
            else:
                stdout = ""
            returncode = 1 if arguments[:1] == ("down",) else 0
            return subprocess.CompletedProcess(
                list(arguments),
                returncode,
                stdout,
                "",
            )

        snapshots = [
            {
                "content_hash": module._sha256_json({"phase": "initial"}),
                "file_count": 5,
                "instance_hash": module._sha256_json({"instance": 1}),
            },
            {
                "content_hash": module._sha256_json({"phase": "overlap"}),
                "file_count": 6,
                "instance_hash": module._sha256_json({"instance": 2}),
            },
            {
                "content_hash": module._sha256_json({"phase": "retired"}),
                "file_count": 5,
                "instance_hash": module._sha256_json({"instance": 3}),
            },
        ]
        success_result = object()
        not_returned = success_result
        with tempfile.TemporaryDirectory(
            prefix="formowl-compose-cleanup-failure-",
            dir=tempfile.gettempdir(),
        ) as value:
            secret_dir = Path(value)
            with (
                mock.patch.object(module, "_compose_environment", return_value={}),
                mock.patch.object(module, "_reserve_loopback_port", return_value=43123),
                mock.patch.object(
                    module,
                    "_run_compose_command",
                    side_effect=fake_compose,
                ),
                mock.patch.object(
                    module,
                    "_compose_container_id",
                    side_effect=("a" * 64, "b" * 64, "c" * 64, "d" * 64),
                ),
                mock.patch.object(module, "_wait_for_healthy_container"),
                mock.patch.object(
                    module,
                    "_compose_postgres_secret_contract",
                    return_value={
                        "same_operator_owned_source": True,
                        "secret_mount_read_only": True,
                        "postgres_healthy": True,
                    },
                ),
                mock.patch.object(
                    module,
                    "_wait_for_ready",
                    return_value={"status": "ready"},
                ) as ready,
                mock.patch.object(
                    module,
                    "_runtime_security_contract",
                    side_effect=({"phase": 1}, {"phase": 2}, {"phase": 3}),
                ) as security,
                mock.patch.object(
                    module,
                    "_staged_secret_snapshot",
                    side_effect=snapshots,
                ) as snapshot,
                mock.patch.object(
                    module,
                    "_fetch_public_jwks",
                    side_effect=({}, {}, {}),
                ) as fetch_jwks,
                mock.patch.object(
                    module,
                    "_validate_public_jwks",
                    side_effect=(
                        {"key_count": 1},
                        {"key_count": 2},
                        {"key_count": 1},
                    ),
                ) as validate_jwks,
                mock.patch.object(module, "_assert_container_removed") as removed,
                mock.patch.object(
                    module,
                    "_run_command",
                    return_value=subprocess.CompletedProcess([], 0, "", ""),
                ),
                self.assertRaises(module.LifecycleProbeFailure) as raised,
            ):
                success_result = module._run_actual_compose_journey(
                    runtime_image_id=runtime_image_id,
                    secret_dir=secret_dir,
                    password=password,
                    key_a=b"key-a",
                    key_b=b"key-b",
                    secret_values=(password, str(secret_dir)),
                )

        self.assertIs(success_result, not_returned)
        self.assertEqual(raised.exception.stage, "compose_cleanup")
        self.assertEqual(raised.exception.code, "compose_cleanup_failed")
        self.assertEqual(str(raised.exception), "compose_cleanup_failed")
        self.assertNotIn(password, str(raised.exception))
        self.assertNotIn(str(secret_dir), str(raised.exception))
        self.assertEqual(
            compose_calls[-1],
            ("down", "--volumes", "--remove-orphans", "--timeout", "30"),
        )
        self.assertEqual(ready.call_count, 3)
        self.assertEqual(security.call_count, 3)
        self.assertEqual(snapshot.call_count, 3)
        self.assertEqual(fetch_jwks.call_count, 3)
        self.assertEqual(validate_jwks.call_count, 3)
        self.assertEqual(removed.call_count, 2)

    def test_postgres_start_uses_only_the_pinned_digest(self) -> None:
        module = _load_lifecycle_probe()
        commands: list[list[str]] = []

        def fake_run(command, **_kwargs):
            rendered = list(command)
            commands.append(rendered)
            return subprocess.CompletedProcess(rendered, 0, "", "")

        with mock.patch.object(module, "_run_command", side_effect=fake_run):
            module._start_postgres(
                name="postgres-name",
                network="postgres-network",
                secret_dir=Path("/tmp/postgres-secrets"),
            )

        postgres_run = next(command for command in commands if command[:2] == ["docker", "run"])
        self.assertEqual(postgres_run[-1], module.PINNED_POSTGRES_IMAGE)

        with (
            mock.patch.object(module, "POSTGRES_IMAGE", "pgvector/pgvector:0.8.0-pg17"),
            mock.patch.object(module, "_run_command") as run_command,
            self.assertRaises(module.LifecycleProbeFailure),
        ):
            module._start_postgres(
                name="postgres-name",
                network="postgres-network",
                secret_dir=Path("/tmp/postgres-secrets"),
            )
        run_command.assert_not_called()

    def test_runtime_security_contract_requires_all_five_capability_sets_zero(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        container_payload = {
            "Path": "formowl-container-entrypoint",
            "Args": ["serve"],
            "Config": {
                "User": "root",
                "Env": [],
                "StopSignal": "SIGTERM",
                "StopTimeout": module.STOP_GRACE_SECONDS,
            },
            "HostConfig": {
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "CapAdd": list(module.LAUNCHER_CAPABILITIES),
                "SecurityOpt": ["no-new-privileges:true"],
                "Tmpfs": {
                    "/tmp": "size=64m,mode=1777",
                    "/run/formowl-secrets": "size=1m,mode=0700",
                },
            },
            "Mounts": [
                *[
                    {
                        "Destination": f"/run/secrets/{name}",
                        "RW": False,
                    }
                    for name in module._RUNTIME_SECRET_NAMES
                ],
                {"Destination": "/data", "RW": True},
            ],
        }
        baseline_main_identity = {
            "uid": module.RUNTIME_UID,
            "gid": module.RUNTIME_UID,
            "groups": [],
            "cap_inh": 0,
            "cap_prm": 0,
            "cap_eff": 0,
            "cap_bnd": 0,
            "cap_amb": 0,
            "no_new_privs": 1,
        }

        def process_result(main_identity):
            process_identity = {
                "probe_uid": module.RUNTIME_UID,
                "probe_gid": module.RUNTIME_UID,
                "probe_groups": [],
                "root_regain_denied": True,
                "main": main_identity,
            }
            return subprocess.CompletedProcess(
                ["docker", "exec"],
                0,
                json.dumps(process_identity),
                "",
            )

        with (
            mock.patch.object(module, "_container_json", return_value=container_payload),
            mock.patch.object(
                module,
                "_run_command",
                return_value=process_result(baseline_main_identity),
            ) as run_command,
        ):
            contract = module._runtime_security_contract("runtime-name")

        self.assertEqual(contract["process_capability_count"], 0)

        cases = (
            ("missing_cap_bnd", "cap_bnd", None),
            ("missing_cap_amb", "cap_amb", None),
            ("malformed_cap_bnd", "cap_bnd", "not-hex"),
            ("malformed_cap_amb", "cap_amb", []),
            ("nonzero_cap_bnd", "cap_bnd", 1),
            ("nonzero_cap_amb", "cap_amb", 1),
        )
        for name, field, value in cases:
            with self.subTest(name=name):
                main_identity = dict(baseline_main_identity)
                if value is None:
                    main_identity.pop(field)
                else:
                    main_identity[field] = value
                with (
                    mock.patch.object(
                        module,
                        "_container_json",
                        return_value=container_payload,
                    ),
                    mock.patch.object(
                        module,
                        "_run_command",
                        return_value=process_result(main_identity),
                    ),
                    self.assertRaises(module.LifecycleProbeFailure) as raised,
                ):
                    module._runtime_security_contract("runtime-name")
                self.assertEqual(raised.exception.stage, "runtime_security")
                self.assertEqual(
                    raised.exception.code,
                    "runtime_security_contract_invalid",
                )
        process_probe = run_command.call_args.args[0][-1]
        self.assertIn("values['CapBnd']", process_probe)
        self.assertIn("values['CapAmb']", process_probe)

    def test_data_state_hash_is_bound_to_file_content(self) -> None:
        module = _load_lifecycle_probe()

        with tempfile.TemporaryDirectory(
            prefix="formowl-data-state-content-",
            dir=tempfile.gettempdir(),
        ) as directory:
            data_dir = Path(directory) / "data"
            nested = data_dir / "nested"
            nested.mkdir(parents=True)
            state_file = nested / "state.json"
            original = b'{"state":"first"}\n'
            replacement = b'{"state":"other"}\n'
            self.assertEqual(len(original), len(replacement))

            state_file.write_bytes(original)
            first_hash = module._data_state_hash(data_dir)
            self.assertTrue(first_hash.startswith("sha256:"))

            state_file.write_bytes(replacement)
            replacement_hash = module._data_state_hash(data_dir)
            self.assertNotEqual(first_hash, replacement_hash)

            state_file.write_bytes(original)
            self.assertEqual(module._data_state_hash(data_dir), first_hash)

    def test_data_state_hash_rejects_symlinks_without_leaking_paths(self) -> None:
        module = _load_lifecycle_probe()

        with tempfile.TemporaryDirectory(
            prefix="formowl-data-state-symlink-",
            dir=tempfile.gettempdir(),
        ) as directory:
            root = Path(directory)
            data_dir = root / "data"
            data_dir.mkdir()
            outside = root / "sensitive-outside-state"
            outside.write_text("sensitive-state-value", encoding="utf-8")
            (data_dir / "state-link").symlink_to(outside)

            with self.assertRaises(module.LifecycleProbeFailure) as raised:
                module._data_state_hash(data_dir)

        self.assertEqual(raised.exception.stage, "data_restart")
        self.assertEqual(
            raised.exception.code,
            "runtime_data_state_unavailable",
        )
        self.assertNotIn(str(outside), str(raised.exception))
        self.assertNotIn("sensitive-state-value", str(raised.exception))

    def test_assert_container_removed_accepts_only_docker_not_found(self) -> None:
        module = _load_lifecycle_probe()
        container_name = "retired-container"
        original_name = container_name
        private_detail = "/tmp/private-container-detail"

        removed = subprocess.CompletedProcess(
            ["docker", "inspect", container_name],
            1,
            "",
            f"not found {private_detail}",
        )
        with mock.patch.object(module, "_run_command", return_value=removed) as run:
            module._assert_container_removed(container_name)
        run.assert_called_once_with(
            ["docker", "inspect", container_name],
            stage="compose_secret_snapshot",
            error_code="retired_compose_container_probe_failed",
            check=False,
            timeout=15,
        )
        self.assertEqual(container_name, original_name)

        present = subprocess.CompletedProcess(
            ["docker", "inspect", container_name],
            0,
            private_detail,
            "",
        )
        with (
            mock.patch.object(module, "_run_command", return_value=present),
            self.assertRaises(module.LifecycleProbeFailure) as present_failure,
        ):
            module._assert_container_removed(container_name)
        self.assertEqual(present_failure.exception.stage, "compose_secret_snapshot")
        self.assertEqual(
            present_failure.exception.code,
            "retired_compose_container_still_present",
        )
        self.assertNotIn(private_detail, str(present_failure.exception))
        self.assertEqual(container_name, original_name)

        unexpected = subprocess.CompletedProcess(
            ["docker", "inspect", container_name],
            125,
            private_detail,
            f"daemon failure {private_detail}",
        )
        with (
            mock.patch.object(module, "_run_command", return_value=unexpected),
            self.assertRaises(module.LifecycleProbeFailure) as probe_failure,
        ):
            module._assert_container_removed(container_name)
        self.assertEqual(probe_failure.exception.stage, "compose_secret_snapshot")
        self.assertEqual(
            probe_failure.exception.code,
            "retired_compose_container_probe_failed",
        )
        self.assertNotIn(private_detail, str(probe_failure.exception))
        self.assertEqual(container_name, original_name)

    def test_inside_helper_result_rejects_non_standard_json_number(self) -> None:
        module = _load_lifecycle_probe()
        command = ("docker", "run", "--rm", "trusted-helper")
        stage = "helper_probe"
        error_code = "helper_failed"
        secret_values = ("private-helper-secret",)
        private_detail = "opaque-private-helper-detail"
        original_inputs = (command, stage, error_code, secret_values)
        result = subprocess.CompletedProcess(
            list(command),
            0,
            ('{"status":"ok","metric":NaN,' f'"detail":"{private_detail}"}}'),
            "",
        )
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            mock.patch.object(module, "_run_command", return_value=result),
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._inside_helper_result(
                command,
                stage=stage,
                error_code=error_code,
                secret_values=secret_values,
                timeout=17,
            )

        self.assertEqual(raised.exception.stage, stage)
        self.assertEqual(
            raised.exception.code,
            f"{error_code}_output_invalid",
        )
        self.assertNotIn(private_detail, str(raised.exception))
        self.assertNotIn(private_detail, public_stdout.getvalue())
        self.assertNotIn(private_detail, public_stderr.getvalue())
        self.assertEqual((command, stage, error_code, secret_values), original_inputs)

    def test_inside_helper_result_bounds_json_parser_resource_limit_failures(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        integer_digit_limit = sys.get_int_max_str_digits()
        self.assertGreater(integer_digit_limit, 0)
        nested_depth = sys.getrecursionlimit() * 10
        cases = (
            (
                "oversized_integer",
                '{"status":"ok","value":' + ("9" * (integer_digit_limit + 1)) + "}",
                ValueError,
            ),
            (
                "excessive_nesting",
                ("[" * nested_depth) + "0" + ("]" * nested_depth),
                RecursionError,
            ),
        )

        for scenario, stdout, leaked_exception_type in cases:
            with self.subTest(scenario=scenario):
                command = ("docker", "run", "--rm", "trusted-helper")
                stage = "helper_probe"
                error_code = "helper_failed"
                secret_values = ("unrelated-private-helper-secret",)
                result = subprocess.CompletedProcess(list(command), 0, stdout, "")
                original_inputs = (
                    tuple(command),
                    stage,
                    error_code,
                    tuple(secret_values),
                    result.args.copy(),
                    result.returncode,
                    result.stdout,
                    result.stderr,
                )
                result_marker = object()
                actual = result_marker
                failure: BaseException | None = None
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()

                with (
                    mock.patch.object(module, "_run_command", return_value=result),
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    try:
                        actual = module._inside_helper_result(
                            command,
                            stage=stage,
                            error_code=error_code,
                            secret_values=secret_values,
                            timeout=17,
                        )
                    except BaseException as error:
                        failure = error
                    else:
                        self.fail(
                            "inside helper accepted parser resource-limit output: " f"{scenario}"
                        )

                self.assertIs(type(failure), module.LifecycleProbeFailure)
                self.assertNotIsInstance(failure, leaked_exception_type)
                self.assertEqual(failure.stage, stage)
                self.assertEqual(
                    failure.code,
                    f"{error_code}_output_invalid",
                )
                self.assertIs(actual, result_marker)
                self.assertEqual(public_stdout.getvalue(), "")
                self.assertEqual(public_stderr.getvalue(), "")
                self.assertEqual(
                    (
                        tuple(command),
                        stage,
                        error_code,
                        tuple(secret_values),
                        result.args,
                        result.returncode,
                        result.stdout,
                        result.stderr,
                    ),
                    original_inputs,
                )

    def test_inside_helper_result_rejects_json_escaped_unsafe_payload(self) -> None:
        module = _load_lifecycle_probe()
        configured_secret = "configured-private-helper-secret"
        private_path = "/tmp/private-helper-decoded-output"
        cases = (
            (
                "escaped_secret",
                configured_secret,
                configured_secret.replace("s", "\\u0073", 1),
                (configured_secret,),
            ),
            (
                "escaped_raw_path",
                private_path,
                private_path.replace("/", "\\u002f"),
                ("unrelated-private-helper-secret",),
            ),
        )

        for scenario, private_value, escaped_value, secret_values in cases:
            with self.subTest(scenario=scenario):
                command = ("docker", "run", "--rm", "trusted-helper")
                stage = "helper_probe"
                error_code = "helper_failed"
                stdout = '{"status":"ok","detail":"' + escaped_value + '"}'
                self.assertNotIn(private_value, stdout)
                self.assertEqual(json.loads(stdout)["detail"], private_value)
                result = subprocess.CompletedProcess(list(command), 0, stdout, "")
                original_inputs = (
                    tuple(command),
                    stage,
                    error_code,
                    tuple(secret_values),
                    result.args.copy(),
                    result.returncode,
                    result.stdout,
                    result.stderr,
                )
                result_marker = object()
                actual = result_marker
                failure = None
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()

                with (
                    mock.patch.object(module, "_run_command", return_value=result),
                    mock.patch.object(
                        module,
                        "_assert_runtime_output_safe",
                        wraps=module._assert_runtime_output_safe,
                    ) as output_safe,
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    try:
                        actual = module._inside_helper_result(
                            command,
                            stage=stage,
                            error_code=error_code,
                            secret_values=secret_values,
                            timeout=17,
                        )
                    except module.LifecycleProbeFailure as error:
                        failure = error
                    else:
                        self.fail(
                            "inside helper accepted JSON-escaped unsafe payload: " f"{scenario}"
                        )

                self.assertIsNotNone(failure)
                self.assertEqual(failure.stage, "runtime_logs")
                self.assertEqual(failure.code, "runtime_output_leak_detected")
                self.assertIs(actual, result_marker)
                self.assertEqual(output_safe.call_count, 2)
                self.assertEqual(
                    output_safe.call_args_list[0],
                    mock.call(stdout, secret_values=secret_values),
                )
                canonical_payload = json.dumps(
                    {"status": "ok", "detail": private_value},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.assertEqual(
                    output_safe.call_args_list[1],
                    mock.call(canonical_payload, secret_values=secret_values),
                )
                public_text = public_stdout.getvalue() + public_stderr.getvalue()
                for leaked_value in (private_value, stdout, canonical_payload):
                    self.assertNotIn(leaked_value, str(failure))
                    self.assertNotIn(leaked_value, public_text)
                self.assertEqual(
                    (
                        tuple(command),
                        stage,
                        error_code,
                        tuple(secret_values),
                        result.args,
                        result.returncode,
                        result.stdout,
                        result.stderr,
                    ),
                    original_inputs,
                )

    def test_inside_helper_result_delegates_exact_success_contract(self) -> None:
        module = _load_lifecycle_probe()
        command = ("docker", "run", "--rm", "trusted-helper", "--inside-probe")
        stage = "helper_probe"
        error_code = "helper_failed"
        secret_values = ("private-helper-secret",)
        timeout = 17.5
        stdout = '{"status":"ok","result_count":2}'
        canonical_payload = '{"result_count":2,"status":"ok"}'
        result = subprocess.CompletedProcess(list(command), 0, stdout, "")
        original_inputs = (
            tuple(command),
            stage,
            error_code,
            tuple(secret_values),
            timeout,
            result.args.copy(),
            result.stdout,
            result.stderr,
        )
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            mock.patch.object(module, "_run_command", return_value=result) as run_command,
            mock.patch.object(module, "_assert_runtime_output_safe") as output_safe,
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            actual = module._inside_helper_result(
                command,
                stage=stage,
                error_code=error_code,
                secret_values=secret_values,
                timeout=timeout,
            )

        self.assertIs(type(actual), dict)
        self.assertEqual(actual, {"status": "ok", "result_count": 2})
        run_command.assert_called_once_with(
            command,
            stage=stage,
            error_code=error_code,
            timeout=timeout,
        )
        self.assertIs(run_command.call_args.args[0], command)
        self.assertEqual(tuple(run_command.call_args.args[0]), tuple(command))
        self.assertEqual(
            output_safe.call_args_list,
            [
                mock.call(stdout, secret_values=secret_values),
                mock.call(canonical_payload, secret_values=secret_values),
            ],
        )
        for safety_call in output_safe.call_args_list:
            self.assertIs(safety_call.kwargs["secret_values"], secret_values)
        self.assertEqual(public_stdout.getvalue(), "")
        self.assertEqual(public_stderr.getvalue(), "")
        self.assertEqual(
            (
                tuple(command),
                stage,
                error_code,
                tuple(secret_values),
                timeout,
                result.args,
                result.stdout,
                result.stderr,
            ),
            original_inputs,
        )

    def test_inside_helper_result_rejects_malformed_stdout(self) -> None:
        module = _load_lifecycle_probe()
        cases = (
            ("empty", ""),
            ("invalid_json", '{"status":"ok","detail":'),
            (
                "multiple_json_lines",
                '{"status":"ok","first":1}\n{"status":"ok","second":2}',
            ),
            ("non_object_root", '["status","ok"]'),
        )

        for scenario, stdout in cases:
            with self.subTest(scenario=scenario):
                private_path = f"/tmp/private-helper-{scenario}"
                private_detail = f"opaque-private-helper-{scenario}"
                command = ("docker", "run", "--rm", "trusted-helper", private_path)
                stage = "helper_probe"
                error_code = "helper_failed"
                secret_values = ("unrelated-private-helper-secret",)
                stderr = private_detail
                result = subprocess.CompletedProcess(list(command), 0, stdout, stderr)
                original_inputs = (
                    tuple(command),
                    stage,
                    error_code,
                    tuple(secret_values),
                    result.args.copy(),
                    result.returncode,
                    result.stdout,
                    result.stderr,
                )
                result_marker = object()
                actual = result_marker
                failure = None
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()

                with (
                    mock.patch.object(module, "_run_command", return_value=result),
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    try:
                        actual = module._inside_helper_result(
                            command,
                            stage=stage,
                            error_code=error_code,
                            secret_values=secret_values,
                            timeout=17,
                        )
                    except module.LifecycleProbeFailure as error:
                        failure = error
                    else:
                        self.fail(f"inside helper accepted malformed stdout: {scenario}")

                self.assertIsNotNone(failure)
                self.assertEqual(failure.stage, stage)
                self.assertEqual(
                    failure.code,
                    f"{error_code}_output_invalid",
                )
                self.assertIs(actual, result_marker)
                public_text = public_stdout.getvalue() + public_stderr.getvalue()
                for private_value in (
                    private_path,
                    private_detail,
                    stdout,
                    stderr,
                ):
                    if private_value:
                        self.assertNotIn(private_value, str(failure))
                        self.assertNotIn(private_value, public_text)
                self.assertEqual(
                    (
                        tuple(command),
                        stage,
                        error_code,
                        tuple(secret_values),
                        result.args,
                        result.returncode,
                        result.stdout,
                        result.stderr,
                    ),
                    original_inputs,
                )

    def test_inside_helper_result_rejects_non_ok_status(self) -> None:
        module = _load_lifecycle_probe()
        cases = (
            ("missing", {}),
            ("error_string", {"status": "error"}),
            ("other_string", {"status": "pending_review"}),
            ("boolean", {"status": True}),
            ("integer", {"status": 1}),
        )

        for scenario, status_payload in cases:
            with self.subTest(scenario=scenario):
                private_path = f"/tmp/private-helper-{scenario}"
                private_detail = f"opaque-private-helper-{scenario}"
                command = ("docker", "run", "--rm", "trusted-helper", private_path)
                stage = "helper_probe"
                error_code = "helper_failed"
                secret_values = ("unrelated-private-helper-secret",)
                payload = {**status_payload, "detail": private_detail}
                stdout = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                stderr = f"opaque-private-stderr-{scenario}"
                result = subprocess.CompletedProcess(list(command), 0, stdout, stderr)
                original_inputs = (
                    tuple(command),
                    stage,
                    error_code,
                    tuple(secret_values),
                    copy.deepcopy(payload),
                    result.args.copy(),
                    result.returncode,
                    result.stdout,
                    result.stderr,
                )
                result_marker = object()
                actual = result_marker
                failure = None
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()

                with (
                    mock.patch.object(module, "_run_command", return_value=result),
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    try:
                        actual = module._inside_helper_result(
                            command,
                            stage=stage,
                            error_code=error_code,
                            secret_values=secret_values,
                            timeout=17,
                        )
                    except module.LifecycleProbeFailure as error:
                        failure = error
                    else:
                        self.fail(f"inside helper accepted non-ok status: {scenario}")

                self.assertIsNotNone(failure)
                self.assertEqual(failure.stage, stage)
                self.assertEqual(failure.code, error_code)
                self.assertIs(actual, result_marker)
                public_text = public_stdout.getvalue() + public_stderr.getvalue()
                for private_value in (
                    private_path,
                    private_detail,
                    stdout,
                    stderr,
                ):
                    self.assertNotIn(private_value, str(failure))
                    self.assertNotIn(private_value, public_text)
                self.assertEqual(
                    (
                        tuple(command),
                        stage,
                        error_code,
                        tuple(secret_values),
                        payload,
                        result.args,
                        result.returncode,
                        result.stdout,
                        result.stderr,
                    ),
                    original_inputs,
                )

    def test_inside_helper_result_rejects_unsafe_output_before_json(self) -> None:
        module = _load_lifecycle_probe()
        configured_secret = "configured-private-helper-secret"
        private_path = "/tmp/private-helper-output"
        cases = (
            (
                "secret_in_stdout",
                json.dumps(
                    {"status": "ok", "detail": configured_secret},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "",
                (configured_secret,),
                configured_secret,
            ),
            (
                "private_path_in_stderr",
                '{"status":"ok"}',
                f"helper failed at {private_path}",
                ("unrelated-private-helper-secret",),
                private_path,
            ),
        )

        for scenario, stdout, stderr, secret_values, private_value in cases:
            with self.subTest(scenario=scenario):
                command = ("docker", "run", "--rm", "trusted-helper")
                stage = "helper_probe"
                error_code = "helper_failed"
                result = subprocess.CompletedProcess(list(command), 0, stdout, stderr)
                original_inputs = (
                    tuple(command),
                    stage,
                    error_code,
                    tuple(secret_values),
                    result.args.copy(),
                    result.returncode,
                    result.stdout,
                    result.stderr,
                )
                result_marker = object()
                actual = result_marker
                failure = None
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()

                with (
                    mock.patch.object(module, "_run_command", return_value=result),
                    mock.patch.object(module, "_json_line") as json_line,
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    try:
                        actual = module._inside_helper_result(
                            command,
                            stage=stage,
                            error_code=error_code,
                            secret_values=secret_values,
                            timeout=17,
                        )
                    except module.LifecycleProbeFailure as error:
                        failure = error
                    else:
                        self.fail(f"inside helper accepted unsafe output: {scenario}")

                self.assertIsNotNone(failure)
                self.assertEqual(failure.stage, "runtime_logs")
                self.assertEqual(failure.code, "runtime_output_leak_detected")
                self.assertIs(actual, result_marker)
                json_line.assert_not_called()
                public_text = public_stdout.getvalue() + public_stderr.getvalue()
                for leaked_value in (private_value, stdout, stderr):
                    if leaked_value:
                        self.assertNotIn(leaked_value, str(failure))
                        self.assertNotIn(leaked_value, public_text)
                self.assertEqual(
                    (
                        tuple(command),
                        stage,
                        error_code,
                        tuple(secret_values),
                        result.args,
                        result.returncode,
                        result.stdout,
                        result.stderr,
                    ),
                    original_inputs,
                )

    def test_inside_helper_result_propagates_command_failure_unchanged(self) -> None:
        module = _load_lifecycle_probe()
        private_path = "/tmp/private-helper-command-failure"
        command = ("docker", "run", "--rm", "trusted-helper", private_path)
        stage = "helper_probe"
        error_code = "helper_failed"
        secret_values = ("private-helper-secret",)
        timeout = 17.5
        command_failure = module.LifecycleProbeFailure(
            stage,
            f"{error_code}_timeout",
        )
        original_inputs = (
            tuple(command),
            stage,
            error_code,
            tuple(secret_values),
            timeout,
            command_failure.stage,
            command_failure.code,
        )
        result_marker = object()
        actual = result_marker
        raised = None
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            mock.patch.object(
                module,
                "_run_command",
                side_effect=command_failure,
            ) as run_command,
            mock.patch.object(module, "_assert_runtime_output_safe") as output_safe,
            mock.patch.object(module, "_json_line") as json_line,
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
        ):
            try:
                actual = module._inside_helper_result(
                    command,
                    stage=stage,
                    error_code=error_code,
                    secret_values=secret_values,
                    timeout=timeout,
                )
            except module.LifecycleProbeFailure as error:
                raised = error
            else:
                self.fail("inside helper swallowed command failure")

        self.assertIs(raised, command_failure)
        self.assertEqual(raised.stage, stage)
        self.assertEqual(raised.code, f"{error_code}_timeout")
        self.assertIs(actual, result_marker)
        run_command.assert_called_once_with(
            command,
            stage=stage,
            error_code=error_code,
            timeout=timeout,
        )
        self.assertIs(run_command.call_args.args[0], command)
        output_safe.assert_not_called()
        json_line.assert_not_called()
        self.assertNotIn(private_path, str(raised))
        self.assertNotIn(private_path, public_stdout.getvalue())
        self.assertNotIn(private_path, public_stderr.getvalue())
        self.assertEqual(
            (
                tuple(command),
                stage,
                error_code,
                tuple(secret_values),
                timeout,
                command_failure.stage,
                command_failure.code,
            ),
            original_inputs,
        )

    def test_run_command_pins_subprocess_contract_and_bounds_failures(self) -> None:
        module = _load_lifecycle_probe()
        command = ("docker", "version", "--format", "json")
        environment = {"FORMOWL_SAFE_TEST": "1"}
        original_command = tuple(command)
        original_environment = dict(environment)
        success = subprocess.CompletedProcess(list(command), 0, "safe-output", "")

        with mock.patch.object(
            module.subprocess,
            "run",
            return_value=success,
        ) as run:
            actual = module._run_command(
                command,
                stage="command_probe",
                error_code="command_failed",
                timeout=7.5,
                environ=environment,
            )

        self.assertIs(actual, success)
        run.assert_called_once_with(
            list(command),
            cwd=module.ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=7.5,
        )
        self.assertEqual(command, original_command)
        self.assertEqual(environment, original_environment)
        self.assertEqual(
            module._safe_runtime_error_code(
                'ignored\n{"error":"bounded_runtime_error"}\n',
            ),
            "bounded_runtime_error",
        )
        self.assertIsNone(
            module._safe_runtime_error_code(
                '{"error":"../../tmp/private-runtime-detail"}',
                "/tmp/private-runtime-detail",
            )
        )

        private_detail = "/tmp/private-runtime-detail"
        nonzero = subprocess.CompletedProcess(
            list(command),
            17,
            f'{private_detail}\n{{"error":"bounded_runtime_error"}}\n',
            f"sensitive stderr {private_detail}",
        )
        with (
            mock.patch.object(module.subprocess, "run", return_value=nonzero),
            self.assertRaises(module.LifecycleProbeFailure) as nonzero_failure,
        ):
            module._run_command(
                command,
                stage="command_probe",
                error_code="command_failed",
                environ=environment,
            )
        self.assertEqual(nonzero_failure.exception.stage, "command_probe")
        self.assertEqual(nonzero_failure.exception.code, "bounded_runtime_error")
        self.assertNotIn(private_detail, str(nonzero_failure.exception))

        timeout = subprocess.TimeoutExpired(
            list(command),
            1.0,
            output=f"timeout output {private_detail}",
            stderr=f"timeout stderr {private_detail}",
        )
        with (
            mock.patch.object(module.subprocess, "run", side_effect=timeout),
            self.assertRaises(module.LifecycleProbeFailure) as timeout_failure,
        ):
            module._run_command(
                command,
                stage="command_probe",
                error_code="command_failed",
                timeout=1.0,
                environ=environment,
            )
        self.assertEqual(timeout_failure.exception.stage, "command_probe")
        self.assertEqual(timeout_failure.exception.code, "command_failed_timeout")
        self.assertNotIn(private_detail, str(timeout_failure.exception))

        with (
            mock.patch.object(
                module.subprocess,
                "run",
                side_effect=OSError(f"host failure {private_detail}"),
            ),
            self.assertRaises(module.LifecycleProbeFailure) as launch_failure,
        ):
            module._run_command(
                command,
                stage="command_probe",
                error_code="command_failed",
                environ=environment,
            )
        self.assertEqual(launch_failure.exception.stage, "command_probe")
        self.assertEqual(launch_failure.exception.code, "command_failed")
        self.assertNotIn(private_detail, str(launch_failure.exception))

    def test_run_compose_command_pins_argv_env_and_redacts_outputs(self) -> None:
        module = _load_lifecycle_probe()
        command = [
            "docker",
            "compose",
            "--file",
            "trusted-compose.yaml",
            "--project-name",
            "formowl-probe",
            "ps",
            "--quiet",
            "connected-mcp",
        ]
        environment = {
            "FORMOWL_RUNTIME_IMAGE": "sha256:" + "a" * 64,
            "FORMOWL_POSTGRES_IMAGE": module.PINNED_POSTGRES_IMAGE,
        }
        secret_values = ("sensitive-compose-secret",)
        success = subprocess.CompletedProcess(command, 0, "container-id\n", "")

        with (
            mock.patch.object(
                module,
                "_compose_command",
                return_value=command,
            ) as compose_command,
            mock.patch.object(module, "_run_command", return_value=success) as run_command,
        ):
            actual = module._run_compose_command(
                "formowl-probe",
                "ps",
                "--quiet",
                "connected-mcp",
                stage="compose_probe",
                error_code="compose_probe_failed",
                environ=environment,
                secret_values=secret_values,
                timeout=13,
            )

        self.assertIs(actual, success)
        compose_command.assert_called_once_with(
            "formowl-probe",
            "ps",
            "--quiet",
            "connected-mcp",
        )
        run_command.assert_called_once_with(
            command,
            stage="compose_probe",
            error_code="compose_probe_failed",
            check=True,
            timeout=13,
            environ=environment,
        )

        leaked = subprocess.CompletedProcess(
            command,
            0,
            f"container-id\n{secret_values[0]}\n/tmp/private-compose-detail",
            "",
        )
        with (
            mock.patch.object(module, "_compose_command", return_value=command),
            mock.patch.object(module, "_run_command", return_value=leaked),
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._run_compose_command(
                "formowl-probe",
                "ps",
                "--quiet",
                "connected-mcp",
                stage="compose_probe",
                error_code="compose_probe_failed",
                environ=environment,
                secret_values=secret_values,
            )
        self.assertEqual(raised.exception.stage, "runtime_logs")
        self.assertEqual(raised.exception.code, "runtime_output_leak_detected")
        self.assertNotIn(secret_values[0], str(raised.exception))
        self.assertNotIn("/tmp/private-compose-detail", str(raised.exception))

    def test_run_runtime_command_pins_argv_and_bounds_public_output(self) -> None:
        module = _load_lifecycle_probe()
        image = "sha256:" + "a" * 64
        data_dir = Path("/tmp/formowl-runtime-data")
        secret_dir = Path("/tmp/formowl-runtime-secrets")
        command = ["docker", "run", "--rm", image, "preflight"]
        payload = {"status": "ready", "checks": {"database": True}}
        success = subprocess.CompletedProcess(
            command,
            0,
            "diagnostic line\n" + json.dumps(payload) + "\n",
            "",
        )

        with (
            mock.patch.object(
                module,
                "_runtime_run_command",
                return_value=command,
            ) as runtime_command,
            mock.patch.object(module, "_run_command", return_value=success) as run_command,
        ):
            actual = module._run_runtime_command(
                image=image,
                network="formowl-runtime-network",
                data_dir=data_dir,
                secret_dir=secret_dir,
                command="preflight",
                stage="runtime_preflight",
                secret_values=("sensitive-runtime-secret",),
            )

        self.assertEqual(actual, payload)
        runtime_command.assert_called_once_with(
            image=image,
            network="formowl-runtime-network",
            data_dir=data_dir,
            secret_dir=secret_dir,
            command="preflight",
        )
        run_command.assert_called_once_with(
            command,
            stage="runtime_preflight",
            error_code="connected_preflight_failed",
            timeout=120,
        )

        for stdout, expected_stage, expected_code in (
            (
                "sensitive-runtime-secret\n/tmp/private-runtime-output\n" + json.dumps(payload),
                "runtime_logs",
                "runtime_output_leak_detected",
            ),
            (
                "bounded diagnostic without a JSON object",
                "runtime_preflight",
                "connected_preflight_output_invalid",
            ),
        ):
            with self.subTest(expected_code=expected_code):
                result = subprocess.CompletedProcess(command, 0, stdout, "")
                with (
                    mock.patch.object(
                        module,
                        "_runtime_run_command",
                        return_value=command,
                    ),
                    mock.patch.object(module, "_run_command", return_value=result),
                    self.assertRaises(module.LifecycleProbeFailure) as raised,
                ):
                    module._run_runtime_command(
                        image=image,
                        network="formowl-runtime-network",
                        data_dir=data_dir,
                        secret_dir=secret_dir,
                        command="preflight",
                        stage="runtime_preflight",
                        secret_values=("sensitive-runtime-secret",),
                    )
                self.assertEqual(raised.exception.stage, expected_stage)
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("sensitive-runtime-secret", str(raised.exception))
                self.assertNotIn("/tmp/private-runtime-output", str(raised.exception))

    def test_start_runtime_pins_detached_serve_argv_and_propagates_failure(self) -> None:
        module = _load_lifecycle_probe()
        image = "sha256:" + "a" * 64

        with tempfile.TemporaryDirectory(
            prefix="formowl-start-runtime-argv-",
            dir=tempfile.gettempdir(),
        ) as directory:
            root = Path(directory)
            sentinel = root / "must-not-exist"
            data_dir = root / "data;touch must-not-exist"
            secret_dir = root / "secrets$(touch must-not-exist)"
            data_dir.mkdir()
            secret_dir.mkdir()
            (data_dir / "state.json").write_bytes(b"immutable-data-state")
            secret_names = (
                "formowl_database_dsn",
                "formowl_google_client_secret",
                "formowl_state_encryption_key",
                "formowl_signing_key_set",
                "formowl_signing_key_current",
                "formowl_signing_key_previous",
            )
            for secret_name in secret_names:
                (secret_dir / secret_name).write_bytes(b"immutable-secret-state")

            network = f"runtime-network;touch {sentinel}"
            name = f"runtime-name$(touch {sentinel})"
            original_inputs = (image, network, data_dir, secret_dir, name)

            def tree_snapshot() -> list[tuple[str, bool, bytes | None]]:
                return [
                    (
                        str(path.relative_to(root)),
                        path.is_dir(),
                        None if path.is_dir() else path.read_bytes(),
                    )
                    for path in sorted(root.rglob("*"))
                ]

            original_tree = tree_snapshot()
            expected_command = [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                network,
                "--read-only",
                "--tmpfs",
                "/tmp:size=64m,mode=1777",
                "--tmpfs",
                "/run/formowl-secrets:size=1m,mode=0700",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "--cap-add",
                "DAC_READ_SEARCH",
                "--cap-add",
                "SETPCAP",
                "--cap-add",
                "SETGID",
                "--cap-add",
                "SETUID",
                "--security-opt",
                "no-new-privileges:true",
                "--stop-signal",
                "SIGTERM",
                "--stop-timeout",
                "30",
                "--mount",
                f"type=bind,src={data_dir},dst=/data",
            ]
            for secret_name in secret_names:
                expected_command.extend(
                    [
                        "--mount",
                        (
                            f"type=bind,src={secret_dir / secret_name},"
                            f"dst=/run/secrets/{secret_name},readonly"
                        ),
                    ]
                )
            for key, value in (
                ("FORMOWL_AUTH_MODE", "oauth_google"),
                ("FORMOWL_CHATGPT_CLIENT_ID", "chatgpt_lifecycle_probe"),
                (
                    "FORMOWL_CHATGPT_REDIRECT_URI",
                    "https://chatgpt.com/connector/oauth/formowl-lifecycle-probe",
                ),
                ("FORMOWL_CONNECTED_HOST", "0.0.0.0"),
                ("FORMOWL_CONNECTED_PORT", "8000"),
                ("FORMOWL_DATABASE_DSN_FILE", "/run/secrets/formowl_database_dsn"),
                ("FORMOWL_DATA_DIR", "/data"),
                (
                    "FORMOWL_GOOGLE_CLIENT_ID",
                    "formowl-lifecycle.apps.googleusercontent.com",
                ),
                (
                    "FORMOWL_GOOGLE_CLIENT_SECRET_FILE",
                    "/run/secrets/formowl_google_client_secret",
                ),
                (
                    "FORMOWL_GOOGLE_REDIRECT_URI",
                    "http://127.0.0.1:8000/oauth/google/callback",
                ),
                ("FORMOWL_LOG_LEVEL", "warning"),
                ("FORMOWL_MCP_RESOURCE", "http://127.0.0.1:8000/mcp"),
                ("FORMOWL_OAUTH_ALLOW_LOOPBACK_HTTP", "1"),
                ("FORMOWL_OAUTH_ISSUER", "http://127.0.0.1:8000"),
                (
                    "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE",
                    "/run/secrets/formowl_signing_key_set",
                ),
                (
                    "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE",
                    "/run/secrets/formowl_state_encryption_key",
                ),
                (
                    "FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID",
                    "lifecycle-operator",
                ),
                ("FORMOWL_UPLOAD_SESSION_LIFETIME_SECONDS", "3600"),
            ):
                expected_command.extend(["-e", f"{key}={value}"])
            expected_command.extend([image, "serve"])

            success = subprocess.CompletedProcess(expected_command, 0, "", "")
            with mock.patch.object(module, "_run_command", return_value=success) as run:
                self.assertIsNone(
                    module._start_runtime(
                        image=image,
                        network=network,
                        data_dir=data_dir,
                        secret_dir=secret_dir,
                        name=name,
                    )
                )
            run.assert_called_once_with(
                expected_command,
                stage="runtime_start",
                error_code="runtime_container_start_failed",
                timeout=60,
            )

            generic_failure = module.LifecycleProbeFailure(
                "runtime_start",
                "runtime_container_start_failed",
            )
            with (
                mock.patch.object(
                    module,
                    "_run_command",
                    side_effect=generic_failure,
                ) as run,
                self.assertRaises(module.LifecycleProbeFailure) as raised,
            ):
                module._start_runtime(
                    image=image,
                    network=network,
                    data_dir=data_dir,
                    secret_dir=secret_dir,
                    name=name,
                )
            self.assertIs(raised.exception, generic_failure)
            self.assertEqual(raised.exception.stage, "runtime_start")
            self.assertEqual(
                raised.exception.code,
                "runtime_container_start_failed",
            )
            self.assertNotIn(str(sentinel), str(raised.exception))
            self.assertNotIn("touch", str(raised.exception))
            run.assert_called_once_with(
                expected_command,
                stage="runtime_start",
                error_code="runtime_container_start_failed",
                timeout=60,
            )

            self.assertFalse(sentinel.exists())
            self.assertEqual(
                (image, network, data_dir, secret_dir, name),
                original_inputs,
            )
            self.assertEqual(tree_snapshot(), original_tree)

    def test_stop_runtime_rejects_malformed_state_before_logs_or_cleanup(self) -> None:
        module = _load_lifecycle_probe()
        name = "runtime-name-private"
        postgres_name = "postgres-name-private"
        secret_values = ("private-secret-value", "/tmp/private-secret")
        payload = {"State": "hostile-/tmp/private"}
        original_inputs = (name, postgres_name, secret_values)
        original_payload = copy.deepcopy(payload)
        stop_command = [
            "docker",
            "stop",
            "--signal",
            "SIGTERM",
            "--timeout",
            "30",
            name,
        ]
        stop_result = subprocess.CompletedProcess(stop_command, 0, "", "")

        with (
            mock.patch.object(
                module.time,
                "monotonic",
                side_effect=(100.0, 100.5),
            ),
            mock.patch.object(
                module,
                "_run_command",
                return_value=stop_result,
            ) as run,
            mock.patch.object(
                module,
                "_container_json",
                return_value=payload,
            ) as container_json,
            mock.patch.object(
                module,
                "_assert_runtime_output_safe",
            ) as output_safe,
            mock.patch.object(
                module,
                "_wait_for_zero_database_connections",
            ) as wait_for_database,
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._stop_runtime(
                name,
                postgres_name=postgres_name,
                secret_values=secret_values,
            )

        self.assertEqual(raised.exception.stage, "runtime_stop")
        self.assertEqual(
            raised.exception.code,
            "runtime_sigterm_exit_invalid",
        )
        for private_detail in (
            "hostile-/tmp/private",
            name,
            postgres_name,
            *secret_values,
        ):
            self.assertNotIn(private_detail, str(raised.exception))
        run.assert_called_once_with(
            stop_command,
            stage="runtime_stop",
            error_code="runtime_sigterm_failed",
            timeout=40,
        )
        self.assertNotIn(["docker", "logs", name], [call.args[0] for call in run.call_args_list])
        self.assertNotIn(["docker", "rm", name], [call.args[0] for call in run.call_args_list])
        container_json.assert_called_once_with(name)
        output_safe.assert_not_called()
        wait_for_database.assert_not_called()
        self.assertEqual((name, postgres_name, secret_values), original_inputs)
        self.assertEqual(payload, original_payload)

    def test_stop_runtime_rejects_boolean_exit_code_before_logs_or_cleanup(self) -> None:
        module = _load_lifecycle_probe()
        name = "runtime-name-private"
        postgres_name = "postgres-name-private"
        secret_values = ("private-secret-value", "/tmp/private-secret")
        payload = {
            "State": {
                "Running": False,
                "ExitCode": False,
                "OOMKilled": False,
                "Error": "",
            }
        }
        original_inputs = (name, postgres_name, secret_values)
        original_payload = copy.deepcopy(payload)
        stop_command = [
            "docker",
            "stop",
            "--signal",
            "SIGTERM",
            "--timeout",
            "30",
            name,
        ]
        stop_result = subprocess.CompletedProcess(stop_command, 0, "", "")

        with (
            mock.patch.object(
                module.time,
                "monotonic",
                side_effect=(100.0, 100.5),
            ),
            mock.patch.object(
                module,
                "_run_command",
                return_value=stop_result,
            ) as run,
            mock.patch.object(
                module,
                "_container_json",
                return_value=payload,
            ) as container_json,
            mock.patch.object(
                module,
                "_assert_runtime_output_safe",
            ) as output_safe,
            mock.patch.object(
                module,
                "_wait_for_zero_database_connections",
            ) as wait_for_database,
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._stop_runtime(
                name,
                postgres_name=postgres_name,
                secret_values=secret_values,
            )

        self.assertEqual(raised.exception.stage, "runtime_stop")
        self.assertEqual(
            raised.exception.code,
            "runtime_sigterm_exit_invalid",
        )
        for private_detail in (name, postgres_name, *secret_values):
            self.assertNotIn(private_detail, str(raised.exception))
        run.assert_called_once_with(
            stop_command,
            stage="runtime_stop",
            error_code="runtime_sigterm_failed",
            timeout=40,
        )
        self.assertNotIn(["docker", "logs", name], [call.args[0] for call in run.call_args_list])
        self.assertNotIn(["docker", "rm", name], [call.args[0] for call in run.call_args_list])
        container_json.assert_called_once_with(name)
        output_safe.assert_not_called()
        wait_for_database.assert_not_called()
        self.assertEqual((name, postgres_name, secret_values), original_inputs)
        self.assertEqual(payload, original_payload)

    def test_stop_runtime_success_orders_cleanup_and_returns_safe_logs(self) -> None:
        module = _load_lifecycle_probe()
        name = "runtime-success"
        postgres_name = "postgres-success"
        secret_values = ("private-secret-value",)
        payload = {
            "State": {
                "Running": False,
                "ExitCode": 0,
                "OOMKilled": False,
                "Error": "",
            }
        }
        original_inputs = (name, postgres_name, secret_values)
        original_payload = copy.deepcopy(payload)
        stop_command = [
            "docker",
            "stop",
            "--signal",
            "SIGTERM",
            "--timeout",
            "30",
            name,
        ]
        logs_command = ["docker", "logs", name]
        remove_command = ["docker", "rm", name]
        stop_result = subprocess.CompletedProcess(stop_command, 0, "", "")
        logs_result = subprocess.CompletedProcess(
            logs_command,
            0,
            "runtime-started\n\n",
            "runtime-stopped\n",
        )
        remove_result = subprocess.CompletedProcess(remove_command, 0, "", "")
        events: list[tuple[object, ...]] = []

        def run_command(
            command: list[str],
            *,
            stage: str,
            error_code: str,
            timeout: float,
        ) -> subprocess.CompletedProcess[str]:
            events.append(("run", command, stage, error_code, timeout))
            if command == stop_command:
                return stop_result
            if command == logs_command:
                return logs_result
            if command == remove_command:
                return remove_result
            raise AssertionError("unexpected runtime stop command")

        def wait_for_database(value: str) -> None:
            events.append(("database_drain", value))

        with tempfile.TemporaryDirectory(
            prefix="formowl-stop-runtime-success-",
            dir=tempfile.gettempdir(),
        ) as directory:
            root = Path(directory)
            marker = root / "immutable-marker"
            marker.write_bytes(b"immutable-state")
            original_tree = [
                (
                    str(path.relative_to(root)),
                    path.is_dir(),
                    None if path.is_dir() else path.read_bytes(),
                )
                for path in sorted(root.rglob("*"))
            ]
            with (
                mock.patch.object(
                    module.time,
                    "monotonic",
                    side_effect=(100.0, 100.5),
                ),
                mock.patch.object(
                    module,
                    "_run_command",
                    side_effect=run_command,
                ),
                mock.patch.object(
                    module,
                    "_container_json",
                    return_value=payload,
                ) as container_json,
                mock.patch.object(
                    module,
                    "_wait_for_zero_database_connections",
                    side_effect=wait_for_database,
                ) as wait_for_database_mock,
            ):
                combined, line_count = module._stop_runtime(
                    name,
                    postgres_name=postgres_name,
                    secret_values=secret_values,
                )

            self.assertEqual(combined, "runtime-started\n\nruntime-stopped\n")
            self.assertEqual(line_count, 2)
            self.assertEqual(
                events,
                [
                    (
                        "run",
                        stop_command,
                        "runtime_stop",
                        "runtime_sigterm_failed",
                        40,
                    ),
                    (
                        "run",
                        logs_command,
                        "runtime_logs",
                        "runtime_logs_unavailable",
                        30,
                    ),
                    ("database_drain", postgres_name),
                    (
                        "run",
                        remove_command,
                        "runtime_cleanup",
                        "runtime_container_remove_failed",
                        30,
                    ),
                ],
            )
            container_json.assert_called_once_with(name)
            wait_for_database_mock.assert_called_once_with(postgres_name)
            self.assertEqual(
                [
                    (
                        str(path.relative_to(root)),
                        path.is_dir(),
                        None if path.is_dir() else path.read_bytes(),
                    )
                    for path in sorted(root.rglob("*"))
                ],
                original_tree,
            )

        self.assertEqual((name, postgres_name, secret_values), original_inputs)
        self.assertEqual(payload, original_payload)

    def test_stop_runtime_rejects_unsafe_logs_before_database_drain_or_remove(self) -> None:
        module = _load_lifecycle_probe()
        name = "runtime-private-name"
        postgres_name = "postgres-private-name"
        secret_marker = "unique-private-secret-marker"
        private_path = "/tmp/private-runtime-log-marker"
        secret_values = (secret_marker, private_path)
        payload = {
            "State": {
                "Running": False,
                "ExitCode": 0,
                "OOMKilled": False,
                "Error": "",
            }
        }
        original_inputs = (name, postgres_name, secret_values)
        original_payload = copy.deepcopy(payload)
        stop_command = [
            "docker",
            "stop",
            "--signal",
            "SIGTERM",
            "--timeout",
            "30",
            name,
        ]
        logs_command = ["docker", "logs", name]
        stop_result = subprocess.CompletedProcess(stop_command, 0, "", "")
        logs_result = subprocess.CompletedProcess(
            logs_command,
            0,
            f"runtime diagnostic {secret_marker}\n",
            f"{private_path}\n",
        )
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            mock.patch.object(
                module.time,
                "monotonic",
                side_effect=(100.0, 100.5),
            ),
            mock.patch.object(
                module,
                "_run_command",
                side_effect=(stop_result, logs_result),
            ) as run,
            mock.patch.object(
                module,
                "_container_json",
                return_value=payload,
            ) as container_json,
            mock.patch.object(
                module,
                "_wait_for_zero_database_connections",
            ) as wait_for_database,
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._stop_runtime(
                name,
                postgres_name=postgres_name,
                secret_values=secret_values,
            )

        self.assertEqual(raised.exception.stage, "runtime_logs")
        self.assertEqual(
            raised.exception.code,
            "runtime_output_leak_detected",
        )
        public_text = public_stdout.getvalue() + public_stderr.getvalue()
        for private_detail in (
            secret_marker,
            private_path,
            name,
            postgres_name,
        ):
            self.assertNotIn(private_detail, str(raised.exception))
            self.assertNotIn(private_detail, public_text)
        self.assertEqual(
            run.call_args_list,
            [
                mock.call(
                    stop_command,
                    stage="runtime_stop",
                    error_code="runtime_sigterm_failed",
                    timeout=40,
                ),
                mock.call(
                    logs_command,
                    stage="runtime_logs",
                    error_code="runtime_logs_unavailable",
                    timeout=30,
                ),
            ],
        )
        self.assertNotIn(["docker", "rm", name], [call.args[0] for call in run.call_args_list])
        container_json.assert_called_once_with(name)
        wait_for_database.assert_not_called()
        self.assertEqual((name, postgres_name, secret_values), original_inputs)
        self.assertEqual(payload, original_payload)

    def test_wait_for_ready_rejects_malformed_state_before_exec_or_sleep(self) -> None:
        module = _load_lifecycle_probe()
        name = "runtime-ready-private-name"
        payload = {"State": "hostile-/tmp/private"}
        original_name = name
        original_payload = copy.deepcopy(payload)

        with (
            mock.patch.object(
                module,
                "_container_json",
                return_value=payload,
            ) as container_json,
            mock.patch.object(module, "_run_command") as run,
            mock.patch.object(module.time, "sleep") as sleep,
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._wait_for_ready(name)

        self.assertEqual(raised.exception.stage, "runtime_ready")
        self.assertEqual(
            raised.exception.code,
            "runtime_ready_state_invalid",
        )
        for private_detail in (
            "hostile-/tmp/private",
            name,
            "/tmp/private",
        ):
            self.assertNotIn(private_detail, str(raised.exception))
        container_json.assert_called_once_with(name)
        run.assert_not_called()
        sleep.assert_not_called()
        self.assertEqual(name, original_name)
        self.assertEqual(payload, original_payload)

    def test_wait_for_ready_rejects_unexpected_exec_returncode_without_retry(self) -> None:
        module = _load_lifecycle_probe()
        name = "runtime-ready-private-name"
        private_path = "/tmp/private-ready-probe"
        payload = {"State": {"Running": True}}
        original_name = name
        original_payload = copy.deepcopy(payload)
        code = (
            "import json,urllib.request;"
            "r=urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=5);"
            "print(r.read().decode('utf-8'))"
        )
        command = [
            "docker",
            "exec",
            name,
            "formowl-container-entrypoint",
            "python",
            "-c",
            code,
        ]
        result = subprocess.CompletedProcess(
            command,
            125,
            f"hostile stdout {name} {private_path}",
            f"hostile stderr {private_path}",
        )
        original_result = (
            list(result.args),
            result.returncode,
            result.stdout,
            result.stderr,
        )
        public_stdout = io.StringIO()
        public_stderr = io.StringIO()

        with (
            mock.patch.object(
                module,
                "_container_json",
                return_value=payload,
            ) as container_json,
            mock.patch.object(
                module,
                "_run_command",
                return_value=result,
            ) as run,
            mock.patch.object(module.time, "sleep") as sleep,
            redirect_stdout(public_stdout),
            redirect_stderr(public_stderr),
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._wait_for_ready(name)

        self.assertEqual(raised.exception.stage, "runtime_ready")
        self.assertEqual(
            raised.exception.code,
            "runtime_ready_probe_failed",
        )
        public_text = public_stdout.getvalue() + public_stderr.getvalue()
        for private_detail in (
            "hostile stdout",
            "hostile stderr",
            name,
            private_path,
        ):
            self.assertNotIn(private_detail, str(raised.exception))
            self.assertNotIn(private_detail, public_text)
        container_json.assert_called_once_with(name)
        run.assert_called_once_with(
            command,
            stage="runtime_ready",
            error_code="runtime_ready_probe_failed",
            check=False,
            timeout=10,
        )
        sleep.assert_not_called()
        self.assertEqual(name, original_name)
        self.assertEqual(payload, original_payload)
        self.assertEqual(
            (
                list(result.args),
                result.returncode,
                result.stdout,
                result.stderr,
            ),
            original_result,
        )

    def test_wait_for_ready_behavior_matrix_pins_polling_and_failures(self) -> None:
        module = _load_lifecycle_probe()
        name = "runtime-ready-matrix-private"
        private_marker = "unique-ready-private-marker"
        private_path = "/tmp/private-ready-matrix"
        code = (
            "import json,urllib.request;"
            "r=urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=5);"
            "print(r.read().decode('utf-8'))"
        )
        command = [
            "docker",
            "exec",
            name,
            "formowl-container-entrypoint",
            "python",
            "-c",
            code,
        ]
        running = {"State": {"Running": True}}
        exited = {"State": {"Running": False}}
        ready = {
            "status": "ready",
            "checks": {
                "database": True,
                "oauth": True,
            },
        }

        def result(
            returncode: int,
            stdout: str,
            stderr: str = "",
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                list(command),
                returncode,
                stdout,
                stderr,
            )

        retry = result(
            1,
            f"ignored {private_marker}",
            f"ignored {private_path}",
        )
        valid_ready = result(0, json.dumps(ready) + "\n")
        bad_status = result(
            0,
            json.dumps(
                {
                    "status": "starting",
                    "checks": {"database": True},
                }
            ),
        )
        bad_checks = result(
            0,
            json.dumps(
                {
                    "status": "ready",
                    "checks": {
                        "database": 1,
                        "oauth": True,
                    },
                }
            ),
        )
        malformed = result(
            0,
            f"not-json {private_marker} {private_path} {name}",
        )
        scenarios = (
            {
                "name": "immediate_ready",
                "states": [running],
                "results": [valid_ready],
                "expected_result": ready,
                "expected_code": None,
                "inspect_count": 1,
                "exec_count": 1,
                "sleep_count": 0,
            },
            {
                "name": "retry_once_then_ready",
                "states": [running, running],
                "results": [retry, valid_ready],
                "expected_result": ready,
                "expected_code": None,
                "inspect_count": 2,
                "exec_count": 2,
                "sleep_count": 1,
            },
            {
                "name": "exited_before_exec",
                "states": [exited],
                "results": [],
                "expected_result": None,
                "expected_code": "runtime_exited_before_ready",
                "inspect_count": 1,
                "exec_count": 0,
                "sleep_count": 0,
            },
            {
                "name": "invalid_status_and_checks_retry",
                "states": [running, running, running],
                "results": [bad_status, bad_checks, valid_ready],
                "expected_result": ready,
                "expected_code": None,
                "inspect_count": 3,
                "exec_count": 3,
                "sleep_count": 2,
            },
            {
                "name": "malformed_json",
                "states": [running],
                "results": [malformed],
                "expected_result": None,
                "expected_code": "runtime_ready_payload_invalid",
                "inspect_count": 1,
                "exec_count": 1,
                "sleep_count": 0,
            },
            {
                "name": "retry_exhaustion",
                "states": [copy.deepcopy(running) for _ in range(90)],
                "results": [
                    result(
                        1,
                        f"ignored {private_marker}",
                        f"ignored {private_path}",
                    )
                    for _ in range(90)
                ],
                "expected_result": None,
                "expected_code": "runtime_not_ready",
                "inspect_count": 90,
                "exec_count": 90,
                "sleep_count": 90,
            },
        )

        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                states = copy.deepcopy(scenario["states"])
                results = copy.deepcopy(scenario["results"])
                original_states = copy.deepcopy(states)
                original_results = [
                    (
                        list(item.args),
                        item.returncode,
                        item.stdout,
                        item.stderr,
                    )
                    for item in results
                ]
                public_stdout = io.StringIO()
                public_stderr = io.StringIO()
                actual = None
                failure = None
                with (
                    mock.patch.object(
                        module,
                        "_container_json",
                        side_effect=states,
                    ) as container_json,
                    mock.patch.object(
                        module,
                        "_run_command",
                        side_effect=results,
                    ) as run,
                    mock.patch.object(module.time, "sleep") as sleep,
                    redirect_stdout(public_stdout),
                    redirect_stderr(public_stderr),
                ):
                    expected_code = scenario["expected_code"]
                    if expected_code is None:
                        actual = module._wait_for_ready(name)
                    else:
                        with self.assertRaises(module.LifecycleProbeFailure) as raised:
                            module._wait_for_ready(name)
                        failure = raised.exception

                if scenario["expected_code"] is None:
                    self.assertEqual(actual, scenario["expected_result"])
                else:
                    self.assertIsNotNone(failure)
                    self.assertEqual(failure.stage, "runtime_ready")
                    self.assertEqual(failure.code, scenario["expected_code"])
                self.assertEqual(
                    container_json.call_args_list,
                    [mock.call(name)] * scenario["inspect_count"],
                )
                self.assertEqual(
                    run.call_args_list,
                    [
                        mock.call(
                            command,
                            stage="runtime_ready",
                            error_code="runtime_ready_probe_failed",
                            check=False,
                            timeout=10,
                        )
                    ]
                    * scenario["exec_count"],
                )
                self.assertEqual(
                    sleep.call_args_list,
                    [mock.call(1)] * scenario["sleep_count"],
                )
                public_text = public_stdout.getvalue() + public_stderr.getvalue()
                bounded_text = str(failure) if failure is not None else json.dumps(actual)
                for private_detail in (
                    private_marker,
                    private_path,
                    name,
                ):
                    self.assertNotIn(private_detail, public_text)
                    self.assertNotIn(private_detail, bounded_text)
                self.assertEqual(states, original_states)
                self.assertEqual(
                    [
                        (
                            list(item.args),
                            item.returncode,
                            item.stdout,
                            item.stderr,
                        )
                        for item in results
                    ],
                    original_results,
                )

    def test_fetch_public_jwks_pins_exec_and_bounds_payload_failures(self) -> None:
        module = _load_lifecycle_probe()
        private_marker = "unique-jwks-private-marker"
        private_path = "/tmp/private-jwks-payload"
        valid_payload = {
            "keys": [
                {
                    "kid": "current-key",
                    "kty": "RSA",
                    "alg": "RS256",
                    "use": "sig",
                    "n": "modulus",
                    "e": "AQAB",
                }
            ]
        }
        original_valid_payload = copy.deepcopy(valid_payload)

        with tempfile.TemporaryDirectory(
            prefix="formowl-jwks-argv-",
            dir=tempfile.gettempdir(),
        ) as directory:
            sentinel = Path(directory) / "must-not-exist"
            name = f"runtime-jwks;touch {sentinel}"
            original_name = name
            code = (
                "import urllib.request;"
                "r=urllib.request.urlopen("
                "'http://127.0.0.1:8000/.well-known/jwks.json',timeout=5);"
                "print(r.read().decode('utf-8'))"
            )
            command = [
                "docker",
                "exec",
                name,
                "formowl-container-entrypoint",
                "python",
                "-c",
                code,
            ]
            scenarios = (
                (
                    "valid_object",
                    json.dumps(valid_payload, separators=(",", ":")) + "\n",
                    valid_payload,
                    None,
                ),
                (
                    "malformed_json",
                    f"not-json {private_marker} {private_path} {name}\n",
                    None,
                    "jwks_payload_invalid",
                ),
                (
                    "non_object_json",
                    json.dumps(
                        [
                            private_marker,
                            private_path,
                            name,
                        ]
                    )
                    + "\n",
                    None,
                    "jwks_payload_invalid",
                ),
            )

            for scenario, stdout, expected, expected_code in scenarios:
                with self.subTest(scenario=scenario):
                    result = subprocess.CompletedProcess(
                        list(command),
                        0,
                        stdout,
                        f"hostile stderr {private_marker} {private_path} {name}",
                    )
                    original_result = (
                        list(result.args),
                        result.returncode,
                        result.stdout,
                        result.stderr,
                    )
                    public_stdout = io.StringIO()
                    public_stderr = io.StringIO()
                    actual = None
                    failure = None

                    with (
                        mock.patch.object(
                            module,
                            "_run_command",
                            return_value=result,
                        ) as run,
                        redirect_stdout(public_stdout),
                        redirect_stderr(public_stderr),
                    ):
                        if expected_code is None:
                            actual = module._fetch_public_jwks(name)
                        else:
                            with self.assertRaises(module.LifecycleProbeFailure) as raised:
                                module._fetch_public_jwks(name)
                            failure = raised.exception

                    if expected_code is None:
                        self.assertEqual(actual, expected)
                    else:
                        self.assertIsNotNone(failure)
                        self.assertEqual(failure.stage, "jwks_probe")
                        self.assertEqual(failure.code, expected_code)
                    run.assert_called_once_with(
                        command,
                        stage="jwks_probe",
                        error_code="jwks_probe_failed",
                        timeout=15,
                    )
                    public_text = public_stdout.getvalue() + public_stderr.getvalue()
                    bounded_text = (
                        str(failure) if failure is not None else json.dumps(actual, sort_keys=True)
                    )
                    for private_detail in (
                        private_marker,
                        private_path,
                        name,
                        str(sentinel),
                    ):
                        self.assertNotIn(private_detail, public_text)
                        self.assertNotIn(private_detail, bounded_text)
                    self.assertEqual(name, original_name)
                    self.assertEqual(
                        (
                            list(result.args),
                            result.returncode,
                            result.stdout,
                            result.stderr,
                        ),
                        original_result,
                    )
                    self.assertFalse(sentinel.exists())

            propagated = module.LifecycleProbeFailure(
                "jwks_probe",
                "jwks_probe_failed",
            )
            public_stdout = io.StringIO()
            public_stderr = io.StringIO()
            with (
                mock.patch.object(
                    module,
                    "_run_command",
                    side_effect=propagated,
                ) as run,
                redirect_stdout(public_stdout),
                redirect_stderr(public_stderr),
                self.assertRaises(module.LifecycleProbeFailure) as raised,
            ):
                module._fetch_public_jwks(name)

            self.assertIs(raised.exception, propagated)
            run.assert_called_once_with(
                command,
                stage="jwks_probe",
                error_code="jwks_probe_failed",
                timeout=15,
            )
            public_text = public_stdout.getvalue() + public_stderr.getvalue()
            for private_detail in (
                private_marker,
                private_path,
                name,
                str(sentinel),
            ):
                self.assertNotIn(private_detail, public_text)
                self.assertNotIn(private_detail, str(raised.exception))
            self.assertEqual(name, original_name)
            self.assertEqual(valid_payload, original_valid_payload)
            self.assertFalse(sentinel.exists())

    def test_compose_command_is_exact_argv_without_shell_expansion(self) -> None:
        module = _load_lifecycle_probe()

        with tempfile.TemporaryDirectory(
            prefix="formowl-compose-argv-",
            dir=tempfile.gettempdir(),
        ) as directory:
            sentinel = Path(directory) / "must-not-exist"
            project_name = f"formowl-probe;touch {sentinel}"
            service = f"connected-mcp;touch {sentinel}"

            command = module._compose_command(
                project_name,
                "ps",
                "--quiet",
                service,
            )

            self.assertEqual(
                command,
                [
                    "docker",
                    "compose",
                    "--file",
                    str(module.COMPOSE_FILE),
                    "--project-name",
                    project_name,
                    "ps",
                    "--quiet",
                    service,
                ],
            )
            self.assertEqual(command.count(project_name), 1)
            self.assertEqual(command.count(service), 1)
            self.assertFalse(sentinel.exists())

    def test_compose_container_id_requires_one_lowercase_hex_identifier(self) -> None:
        module = _load_lifecycle_probe()
        environment = {"FORMOWL_SAFE_TEST": "1"}
        secret_values = ("sensitive-container-secret",)
        original_environment = dict(environment)
        expected_container_id = "a" * 64
        success = subprocess.CompletedProcess(
            ["docker", "compose", "ps"],
            0,
            f"\n{expected_container_id}\n",
            "",
        )

        with mock.patch.object(
            module,
            "_run_compose_command",
            return_value=success,
        ) as run_compose:
            actual = module._compose_container_id(
                "formowl-probe",
                "connected-mcp",
                environ=environment,
                secret_values=secret_values,
            )

        self.assertEqual(actual, expected_container_id)
        run_compose.assert_called_once_with(
            "formowl-probe",
            "ps",
            "--quiet",
            "connected-mcp",
            stage="compose_live",
            error_code="compose_container_lookup_failed",
            environ=environment,
            secret_values=secret_values,
            timeout=30,
        )
        self.assertEqual(environment, original_environment)

        invalid_outputs = {
            "empty": "",
            "multiple": f"{'a' * 12}\n{'b' * 12}\n",
            "too_short": "a" * 11,
            "uppercase": "A" * 12,
            "non_hex": "g" * 12,
            "private_detail": "/tmp/private-container-id",
        }
        for name, stdout in invalid_outputs.items():
            with self.subTest(name=name):
                result = subprocess.CompletedProcess(
                    ["docker", "compose", "ps"],
                    0,
                    stdout,
                    "",
                )
                with (
                    mock.patch.object(
                        module,
                        "_run_compose_command",
                        return_value=result,
                    ),
                    self.assertRaises(module.LifecycleProbeFailure) as raised,
                ):
                    module._compose_container_id(
                        "formowl-probe",
                        "connected-mcp",
                        environ=environment,
                        secret_values=secret_values,
                    )
                self.assertEqual(raised.exception.stage, "compose_live")
                self.assertEqual(
                    raised.exception.code,
                    "compose_container_lookup_invalid",
                )
                detail = stdout.strip()
                if detail:
                    self.assertNotIn(detail, str(raised.exception))

    def test_reserve_loopback_port_binds_loopback_and_releases_socket(self) -> None:
        module = _load_lifecycle_probe()

        port = module._reserve_loopback_port()
        self.assertGreaterEqual(port, 1)
        self.assertLessEqual(port, 65535)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as rebound:
            rebound.bind(("127.0.0.1", port))

        class RecordingSocket:
            def __init__(self, *, bind_error: OSError | None = None) -> None:
                self.bind_error = bind_error
                self.bound_address: tuple[str, int] | None = None
                self.exited = False

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _traceback):
                self.exited = True

            def bind(self, address):
                self.bound_address = address
                if self.bind_error is not None:
                    raise self.bind_error

            def getsockname(self):
                return ("127.0.0.1", 43123)

        successful_socket = RecordingSocket()
        with mock.patch.object(
            module.socket,
            "socket",
            return_value=successful_socket,
        ) as socket_factory:
            self.assertEqual(module._reserve_loopback_port(), 43123)
        socket_factory.assert_called_once_with(
            module.socket.AF_INET,
            module.socket.SOCK_STREAM,
        )
        self.assertEqual(successful_socket.bound_address, ("127.0.0.1", 0))
        self.assertTrue(successful_socket.exited)

        private_detail = "/tmp/private-loopback-bind"
        failed_socket = RecordingSocket(bind_error=OSError(private_detail))
        with (
            mock.patch.object(
                module.socket,
                "socket",
                return_value=failed_socket,
            ),
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._reserve_loopback_port()
        self.assertEqual(raised.exception.stage, "compose_live")
        self.assertEqual(
            raised.exception.code,
            "compose_publish_port_unavailable",
        )
        self.assertNotIn(private_detail, str(raised.exception))
        self.assertEqual(failed_socket.bound_address, ("127.0.0.1", 0))
        self.assertTrue(failed_socket.exited)

    def test_staged_secret_snapshot_rejects_negative_file_count_without_leaks_or_mutation(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        container_name = "sensitive-runtime-container"
        secret_values = [
            "sensitive-staged-secret",
            "/tmp/private-staged-secret",
        ]
        original_secret_values = list(secret_values)
        payload = {
            "content_hash": module._sha256_json({"content": "safe"}),
            "file_count": -1,
            "inode_hash": module._sha256_json({"inode": "safe"}),
        }
        original_payload = copy.deepcopy(payload)
        result = subprocess.CompletedProcess(
            ["docker", "exec"],
            0,
            json.dumps(payload),
            "",
        )

        with (
            mock.patch.object(module, "_run_command", return_value=result) as run_command,
            mock.patch.object(
                module,
                "_sha256_json",
                wraps=module._sha256_json,
            ) as instance_hash,
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._staged_secret_snapshot(
                container_name,
                secret_values=secret_values,
            )

        self.assertEqual(raised.exception.stage, "compose_secret_snapshot")
        self.assertEqual(
            raised.exception.code,
            "compose_secret_snapshot_invalid",
        )
        rendered_failure = str(raised.exception)
        for forbidden in (*secret_values, container_name):
            self.assertNotIn(forbidden, rendered_failure)
        self.assertEqual(secret_values, original_secret_values)
        self.assertEqual(payload, original_payload)
        self.assertEqual(result.stdout, json.dumps(original_payload))
        instance_hash.assert_not_called()

        run_command.assert_called_once()
        command = run_command.call_args.args[0]
        self.assertEqual(
            command[:6],
            [
                "docker",
                "exec",
                "--user",
                "0:0",
                container_name,
                "python",
            ],
        )
        self.assertEqual(command[6], "-c")
        self.assertIn("root = Path('/run/formowl-secrets')", command[7])
        self.assertEqual(
            run_command.call_args.kwargs,
            {
                "stage": "compose_secret_snapshot",
                "error_code": "compose_secret_snapshot_failed",
                "timeout": 20,
            },
        )

    def test_database_connection_count_rejects_negative_count_without_leaks_or_mutation(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        postgres_name = "sensitive-postgres-container"
        hostile_detail = "/tmp/private-hostile-database-detail"
        result = subprocess.CompletedProcess(
            ["docker", "exec"],
            0,
            "-1\n",
            f"ignored postgres detail {hostile_detail}",
        )
        original_result = (
            list(result.args),
            result.returncode,
            result.stdout,
            result.stderr,
        )

        with (
            mock.patch.object(module, "_run_command", return_value=result) as run_command,
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._database_connection_count(postgres_name)

        self.assertEqual(raised.exception.stage, "database_activity")
        self.assertEqual(
            raised.exception.code,
            "database_activity_probe_invalid",
        )
        rendered_failure = str(raised.exception)
        for forbidden in (postgres_name, hostile_detail, result.stderr):
            self.assertNotIn(forbidden, rendered_failure)
        self.assertEqual(
            (
                result.args,
                result.returncode,
                result.stdout,
                result.stderr,
            ),
            original_result,
        )
        run_command.assert_called_once_with(
            [
                "docker",
                "exec",
                postgres_name,
                "psql",
                "-U",
                "formowl",
                "-d",
                "formowl",
                "-Atqc",
                (
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND backend_type = 'client backend' "
                    "AND pid <> pg_backend_pid()"
                ),
            ],
            stage="database_activity",
            error_code="database_activity_probe_failed",
            timeout=15,
        )

    def test_wait_for_zero_database_connections_polls_boundedly_and_fails_safely(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        postgres_name = "sensitive-postgres-container"
        counts = [2, 1, 0]
        original_counts = list(counts)

        with (
            mock.patch.object(
                module,
                "_database_connection_count",
                side_effect=counts,
            ) as connection_count,
            mock.patch.object(module.time, "sleep") as sleep,
        ):
            self.assertIsNone(module._wait_for_zero_database_connections(postgres_name))

        self.assertEqual(
            connection_count.call_args_list,
            [mock.call(postgres_name)] * 3,
        )
        self.assertEqual(
            sleep.call_args_list,
            [mock.call(0.25)] * 2,
        )
        self.assertEqual(counts, original_counts)

        private_detail = "/tmp/private-database-activity"
        hostile_postgres_name = f"sensitive-postgres::{private_detail}"
        persistent_counts = [1] * 30
        original_persistent_counts = list(persistent_counts)
        with (
            mock.patch.object(
                module,
                "_database_connection_count",
                side_effect=persistent_counts,
            ) as persistent_connection_count,
            mock.patch.object(module.time, "sleep") as persistent_sleep,
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._wait_for_zero_database_connections(hostile_postgres_name)

        self.assertEqual(raised.exception.stage, "database_activity")
        self.assertEqual(
            raised.exception.code,
            "database_connection_not_released",
        )
        rendered_failure = str(raised.exception)
        for forbidden in (hostile_postgres_name, private_detail):
            self.assertNotIn(forbidden, rendered_failure)
        self.assertEqual(
            persistent_connection_count.call_args_list,
            [mock.call(hostile_postgres_name)] * 30,
        )
        self.assertEqual(
            persistent_sleep.call_args_list,
            [mock.call(0.25)] * 30,
        )
        self.assertEqual(persistent_counts, original_persistent_counts)

    def test_compose_postgres_secret_contract_is_exact_and_rejects_malformed_mounts(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        container_name = "sensitive-postgres-container"
        malformed_detail = "/tmp/private-malformed-mount"

        with tempfile.TemporaryDirectory(
            prefix="formowl-postgres-secret-contract-",
            dir=tempfile.gettempdir(),
        ) as directory:
            secret_dir = Path(directory)
            secret_file = secret_dir / "formowl_postgres_password"
            wrong_secret = secret_dir / "wrong-postgres-secret"
            secret_file.write_text("sensitive-secret-value", encoding="utf-8")
            wrong_secret.write_text("sensitive-wrong-secret", encoding="utf-8")
            original_files = {path.name: path.read_bytes() for path in sorted(secret_dir.iterdir())}
            valid_mount = {
                "Destination": "/run/secrets/formowl_postgres_password",
                "Source": str(secret_file),
                "RW": False,
            }
            success_payload = {
                "Mounts": [copy.deepcopy(valid_mount)],
                "State": {"Health": {"Status": "healthy"}},
            }
            original_success_payload = copy.deepcopy(success_payload)
            with mock.patch.object(
                module,
                "_container_json",
                return_value=success_payload,
            ) as container_json:
                contract = module._compose_postgres_secret_contract(
                    container_name,
                    secret_dir=secret_dir,
                )

            expected_contract = {
                "same_operator_owned_source": True,
                "secret_mount_read_only": True,
                "postgres_healthy": True,
            }
            self.assertEqual(contract, expected_contract)
            self.assertEqual(set(contract), set(expected_contract))
            self.assertTrue(all(type(value) is bool for value in contract.values()))
            container_json.assert_called_once_with(container_name)
            self.assertEqual(success_payload, original_success_payload)

            invalid_payloads = {
                "missing_mount": {
                    "Mounts": [],
                    "State": {"Health": {"Status": "healthy"}},
                },
                "duplicate_mount": {
                    "Mounts": [
                        copy.deepcopy(valid_mount),
                        copy.deepcopy(valid_mount),
                    ],
                    "State": {"Health": {"Status": "healthy"}},
                },
                "wrong_source": {
                    "Mounts": [
                        {
                            **valid_mount,
                            "Source": str(wrong_secret),
                        }
                    ],
                    "State": {"Health": {"Status": "healthy"}},
                },
                "writable_mount": {
                    "Mounts": [
                        {
                            **valid_mount,
                            "RW": True,
                        }
                    ],
                    "State": {"Health": {"Status": "healthy"}},
                },
                "unhealthy_state": {
                    "Mounts": [copy.deepcopy(valid_mount)],
                    "State": {"Health": {"Status": "unhealthy"}},
                },
                "non_mapping_mount": {
                    "Mounts": [f"sensitive-mount::{malformed_detail}"],
                    "State": {"Health": {"Status": "healthy"}},
                },
            }
            for name, payload in invalid_payloads.items():
                with self.subTest(name=name):
                    original_payload = copy.deepcopy(payload)
                    with (
                        mock.patch.object(
                            module,
                            "_container_json",
                            return_value=payload,
                        ) as container_json,
                        self.assertRaises(module.LifecycleProbeFailure) as raised,
                    ):
                        module._compose_postgres_secret_contract(
                            container_name,
                            secret_dir=secret_dir,
                        )

                    self.assertEqual(raised.exception.stage, "compose_postgres")
                    self.assertEqual(
                        raised.exception.code,
                        "compose_postgres_secret_contract_invalid",
                    )
                    rendered_failure = str(raised.exception)
                    for forbidden in (
                        container_name,
                        str(secret_dir),
                        str(secret_file),
                        str(wrong_secret),
                        malformed_detail,
                        "sensitive-secret-value",
                        "sensitive-wrong-secret",
                    ):
                        self.assertNotIn(forbidden, rendered_failure)
                    container_json.assert_called_once_with(container_name)
                    self.assertEqual(payload, original_payload)
                    self.assertEqual(
                        {path.name: path.read_bytes() for path in sorted(secret_dir.iterdir())},
                        original_files,
                    )

    def test_container_json_rejects_top_level_object_without_leaks_or_mutation(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        container_name = "sensitive-runtime-container"
        private_detail = "/tmp/private-inspect-detail"
        expected_command = ["docker", "inspect", container_name]
        success_payload = [
            {
                "Id": "a" * 64,
                "State": {"Status": "running"},
            }
        ]
        original_success_payload = copy.deepcopy(success_payload)
        success_result = subprocess.CompletedProcess(
            ["docker", "inspect"],
            0,
            json.dumps(success_payload),
            "",
        )
        original_success_result = (
            list(success_result.args),
            success_result.returncode,
            success_result.stdout,
            success_result.stderr,
        )

        with mock.patch.object(
            module,
            "_run_command",
            return_value=success_result,
        ) as run_command:
            actual = module._container_json(container_name)

        self.assertEqual(actual, success_payload[0])
        self.assertEqual(success_payload, original_success_payload)
        self.assertEqual(
            (
                success_result.args,
                success_result.returncode,
                success_result.stdout,
                success_result.stderr,
            ),
            original_success_result,
        )
        run_command.assert_called_once_with(
            expected_command,
            stage="runtime_inspect",
            error_code="runtime_container_inspect_failed",
        )

        invalid_outputs = {
            "malformed_json": f'{{"Private":"{private_detail}"',
            "top_level_object": json.dumps(
                {
                    "Id": container_name,
                    "Private": private_detail,
                }
            ),
            "empty_list": "[]",
            "multiple_dicts": json.dumps(
                [
                    {"Private": private_detail},
                    {"Id": container_name},
                ]
            ),
            "non_dict_item": json.dumps([f"sensitive-inspect-item::{private_detail}"]),
        }
        original_invalid_outputs = copy.deepcopy(invalid_outputs)
        for name, stdout in invalid_outputs.items():
            with self.subTest(name=name):
                result = subprocess.CompletedProcess(
                    ["docker", "inspect"],
                    0,
                    stdout,
                    f"ignored inspect detail {container_name} {private_detail}",
                )
                original_result = (
                    list(result.args),
                    result.returncode,
                    result.stdout,
                    result.stderr,
                )
                with (
                    mock.patch.object(
                        module,
                        "_run_command",
                        return_value=result,
                    ) as run_command,
                    self.assertRaises(module.LifecycleProbeFailure) as raised,
                ):
                    module._container_json(container_name)

                self.assertEqual(raised.exception.stage, "runtime_inspect")
                self.assertEqual(
                    raised.exception.code,
                    "runtime_container_inspect_failed",
                )
                rendered_failure = str(raised.exception)
                for forbidden in (
                    container_name,
                    private_detail,
                    result.stderr,
                ):
                    self.assertNotIn(forbidden, rendered_failure)
                self.assertEqual(
                    (
                        result.args,
                        result.returncode,
                        result.stdout,
                        result.stderr,
                    ),
                    original_result,
                )
                run_command.assert_called_once_with(
                    expected_command,
                    stage="runtime_inspect",
                    error_code="runtime_container_inspect_failed",
                )
        self.assertEqual(invalid_outputs, original_invalid_outputs)

    def test_wait_for_healthy_container_rejects_malformed_state_without_sleep_or_leaks(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        container_name = "sensitive-runtime-container"
        private_detail = "/tmp/private-health-detail"

        immediate_payload = {
            "State": {
                "Running": True,
                "Health": {
                    "Status": "healthy",
                    "ConsecutiveFailures": 0,
                },
            }
        }
        original_immediate_payload = copy.deepcopy(immediate_payload)
        with (
            mock.patch.object(
                module,
                "_container_json",
                return_value=immediate_payload,
            ) as container_json,
            mock.patch.object(module.time, "sleep") as sleep,
        ):
            health = module._wait_for_healthy_container(
                container_name,
                stage="compose_runtime",
            )

        self.assertEqual(
            health,
            {
                "Status": "healthy",
                "ConsecutiveFailures": 0,
            },
        )
        container_json.assert_called_once_with(container_name)
        sleep.assert_not_called()
        self.assertEqual(immediate_payload, original_immediate_payload)

        starting_payloads = [
            {
                "State": {
                    "Running": True,
                    "Health": {"Status": "starting"},
                }
            },
            {
                "State": {
                    "Running": True,
                    "Health": {"Status": "healthy"},
                }
            },
        ]
        original_starting_payloads = copy.deepcopy(starting_payloads)
        with (
            mock.patch.object(
                module,
                "_container_json",
                side_effect=starting_payloads,
            ) as container_json,
            mock.patch.object(module.time, "sleep") as sleep,
        ):
            health = module._wait_for_healthy_container(
                container_name,
                stage="compose_runtime",
            )

        self.assertEqual(health, {"Status": "healthy"})
        self.assertEqual(
            container_json.call_args_list,
            [mock.call(container_name)] * 2,
        )
        sleep.assert_called_once_with(1)
        self.assertEqual(starting_payloads, original_starting_payloads)

        failure_cases = {
            "running_false": (
                {
                    "State": {
                        "Running": False,
                        "Health": {"Status": "starting"},
                        "Detail": f"running-false-private::{private_detail}",
                    }
                },
                "compose_container_exited_before_healthy",
            ),
            "unhealthy": (
                {
                    "State": {
                        "Running": True,
                        "Health": {
                            "Status": "unhealthy",
                            "Detail": f"unhealthy-private::{private_detail}",
                        },
                    }
                },
                "compose_container_unhealthy",
            ),
            "malformed_state": (
                {"State": f"hostile-state::{private_detail}"},
                "compose_container_health_invalid",
            ),
            "malformed_health": (
                {
                    "State": {
                        "Running": True,
                        "Health": f"hostile-health::{private_detail}",
                    }
                },
                "compose_container_health_invalid",
            ),
        }
        original_failure_cases = copy.deepcopy(failure_cases)
        for name, (payload, expected_code) in failure_cases.items():
            with self.subTest(name=name):
                original_payload = copy.deepcopy(payload)
                with (
                    mock.patch.object(
                        module,
                        "_container_json",
                        return_value=payload,
                    ) as container_json,
                    mock.patch.object(module.time, "sleep") as sleep,
                    self.assertRaises(module.LifecycleProbeFailure) as raised,
                ):
                    module._wait_for_healthy_container(
                        container_name,
                        stage="compose_runtime",
                    )

                self.assertEqual(raised.exception.stage, "compose_runtime")
                self.assertEqual(raised.exception.code, expected_code)
                rendered_failure = str(raised.exception)
                for forbidden in (
                    container_name,
                    private_detail,
                    "running-false-private",
                    "unhealthy-private",
                    "hostile-state",
                    "hostile-health",
                ):
                    self.assertNotIn(forbidden, rendered_failure)
                container_json.assert_called_once_with(container_name)
                sleep.assert_not_called()
                self.assertEqual(payload, original_payload)
        self.assertEqual(failure_cases, original_failure_cases)

        timeout_payloads = [
            {
                "State": {
                    "Running": True,
                    "Health": {
                        "Status": "starting",
                        "Detail": f"timeout-private::{private_detail}",
                    },
                }
            }
            for _ in range(120)
        ]
        original_timeout_payloads = copy.deepcopy(timeout_payloads)
        with (
            mock.patch.object(
                module,
                "_container_json",
                side_effect=timeout_payloads,
            ) as container_json,
            mock.patch.object(module.time, "sleep") as sleep,
            self.assertRaises(module.LifecycleProbeFailure) as raised,
        ):
            module._wait_for_healthy_container(
                container_name,
                stage="compose_runtime",
            )

        self.assertEqual(raised.exception.stage, "compose_runtime")
        self.assertEqual(
            raised.exception.code,
            "compose_container_health_timeout",
        )
        rendered_failure = str(raised.exception)
        for forbidden in (
            container_name,
            private_detail,
            "timeout-private",
        ):
            self.assertNotIn(forbidden, rendered_failure)
        self.assertEqual(
            container_json.call_args_list,
            [mock.call(container_name)] * 120,
        )
        self.assertEqual(
            sleep.call_args_list,
            [mock.call(1)] * 120,
        )
        self.assertEqual(timeout_payloads, original_timeout_payloads)

    def test_atomic_write_failures_preserve_prior_bytes_and_clean_temporary_files(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        previous_output = b'{"authority":"previous"}\n'
        replacement = b'{"authority":"replacement"}\n'
        fault_detail = "sensitive-atomic-fault-/tmp/private-report"
        real_write_bytes = Path.write_bytes

        with tempfile.TemporaryDirectory(
            prefix="formowl-lifecycle-atomic-failure-",
            dir=tempfile.gettempdir(),
        ) as directory:
            root = Path(directory)
            for failure_name in ("write", "chmod", "replace"):
                with self.subTest(failure_name=failure_name):
                    output_path = root / f"{failure_name}.json"
                    output_path.write_bytes(previous_output)
                    uuid_value = mock.Mock()
                    uuid_value.hex = failure_name
                    temporary_path = output_path.with_name(
                        f".{output_path.name}.{failure_name}.tmp"
                    )

                    if failure_name == "write":

                        def fail_write(path: Path, value: bytes) -> int:
                            if path == temporary_path:
                                real_write_bytes(path, value[:5])
                                raise OSError(fault_detail)
                            return real_write_bytes(path, value)

                        patcher = mock.patch.object(Path, "write_bytes", new=fail_write)
                    elif failure_name == "chmod":
                        patcher = mock.patch.object(
                            module.os,
                            "chmod",
                            side_effect=OSError(fault_detail),
                        )
                    else:
                        patcher = mock.patch.object(
                            module.os,
                            "replace",
                            side_effect=OSError(fault_detail),
                        )

                    with (
                        mock.patch.object(module.uuid, "uuid4", return_value=uuid_value),
                        patcher,
                        self.assertRaises(module.LifecycleProbeFailure) as raised,
                    ):
                        module._atomic_write(
                            output_path,
                            replacement,
                            stage="report",
                            error_code="report_output_write_failed",
                            cleanup_error_code="report_output_cleanup_failed",
                        )

                    self.assertEqual(raised.exception.stage, "report")
                    self.assertEqual(
                        raised.exception.code,
                        "report_output_write_failed",
                    )
                    self.assertNotIn(fault_detail, str(raised.exception))
                    self.assertNotIn(str(output_path), str(raised.exception))
                    self.assertEqual(output_path.read_bytes(), previous_output)
                    self.assertFalse(temporary_path.exists())
                    self.assertEqual(
                        list(root.glob(f".{output_path.name}.*.tmp")),
                        [],
                    )

    def test_atomic_write_cleanup_failure_is_generic_and_fails_closed(self) -> None:
        module = _load_lifecycle_probe()
        previous_output = b'{"authority":"previous"}\n'
        replacement = b'{"authority":"replacement"}\n'
        fault_detail = "sensitive-cleanup-fault-/tmp/private-report"

        with tempfile.TemporaryDirectory(
            prefix="formowl-lifecycle-atomic-cleanup-failure-",
            dir=tempfile.gettempdir(),
        ) as directory:
            output_path = Path(directory) / "report.json"
            output_path.write_bytes(previous_output)
            uuid_value = mock.Mock()
            uuid_value.hex = "cleanup"
            temporary_path = output_path.with_name(f".{output_path.name}.cleanup.tmp")
            real_unlink = Path.unlink

            def fail_temporary_unlink(
                path: Path,
                *args,
                **kwargs,
            ) -> None:
                if path == temporary_path:
                    raise OSError(fault_detail)
                real_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(module.uuid, "uuid4", return_value=uuid_value),
                mock.patch.object(
                    module.os,
                    "replace",
                    side_effect=OSError(fault_detail),
                ),
                mock.patch.object(Path, "unlink", new=fail_temporary_unlink),
                self.assertRaises(module.LifecycleProbeFailure) as raised,
            ):
                module._atomic_write(
                    output_path,
                    replacement,
                    stage="report",
                    error_code="report_output_write_failed",
                    cleanup_error_code="report_output_cleanup_failed",
                )

            self.assertEqual(raised.exception.stage, "report")
            self.assertEqual(
                raised.exception.code,
                "report_output_cleanup_failed",
            )
            self.assertNotIn(fault_detail, str(raised.exception))
            self.assertNotIn(str(output_path), str(raised.exception))
            self.assertEqual(output_path.read_bytes(), previous_output)
            self.assertFalse(temporary_path.exists())
            self.assertEqual(
                list(output_path.parent.glob(f".{output_path.name}.*.tmp")),
                [],
            )

    def test_run_probe_success_report_uses_atomic_output_without_clobbering_prior_bytes(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        runtime_image_id = "sha256:" + "a" * 64
        previous_output = b'{"authority":"previous"}\n'
        ready = {"status": "ready", "checks": {"postgres": True}}
        state = {"core_state_hash": "sha256:" + "b" * 64}
        report = {"artifact_id": module.ARTIFACT_ID, "status": "passed"}
        instant = module.datetime(2026, 7, 18, tzinfo=module.timezone.utc)
        clock_values = iter(
            (
                instant,
                instant + module.timedelta(seconds=1),
                instant + module.timedelta(seconds=1),
                instant + module.timedelta(seconds=16),
            )
        )

        class ControlledDatetime(module.datetime):
            @classmethod
            def now(cls, tz=None):
                value = next(clock_values)
                return value if tz is None else value.astimezone(tz)

        def runtime_result(*, command: str, **_kwargs):
            if command == "migrate":
                if runtime_result.migration_count == 0:
                    runtime_result.migration_count += 1
                    return {
                        "status": "ok",
                        "applied_migration_count": module.EXPECTED_MIGRATION_COUNT,
                        "skipped_migration_count": 0,
                    }
                return {
                    "status": "ok",
                    "applied_migration_count": 0,
                    "skipped_migration_count": module.EXPECTED_MIGRATION_COUNT,
                }
            return {"status": "ready", "checks": {"google": True}}

        runtime_result.migration_count = 0

        def atomic_output(path: Path, _value: bytes, **_kwargs) -> None:
            if path == output_path:
                raise module.LifecycleProbeFailure(
                    "report",
                    "report_output_write_failed",
                )

        with tempfile.TemporaryDirectory(
            prefix="formowl-lifecycle-run-probe-output-",
            dir=tempfile.gettempdir(),
        ) as directory:
            output_path = Path(directory) / "report.json"
            output_path.write_bytes(previous_output)
            command_result = subprocess.CompletedProcess([], 0, "", "")
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(module, "datetime", ControlledDatetime))
                stack.enter_context(mock.patch.object(module, "_prepare_probe_directory"))
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_build_runtime_image",
                        return_value=(runtime_image_id, {}),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_generate_signing_keys",
                        return_value=(b"key-a", b"key-b"),
                    )
                )
                stack.enter_context(mock.patch.object(module, "_prepare_data_directory"))
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_atomic_write",
                        side_effect=atomic_output,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_validate_compose_config",
                        return_value=({}, 1),
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_run_command",
                        return_value=command_result,
                    )
                )
                stack.enter_context(mock.patch.object(module, "_start_postgres"))
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_run_runtime_command",
                        side_effect=runtime_result,
                    )
                )
                stack.enter_context(mock.patch.object(module, "_seed_oauth_state", return_value={}))
                stack.enter_context(mock.patch.object(module, "_start_runtime"))
                stack.enter_context(
                    mock.patch.object(module, "_wait_for_ready", return_value=ready)
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_runtime_security_contract",
                        return_value={},
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_database_connection_count",
                        return_value=1,
                    )
                )
                stack.enter_context(
                    mock.patch.object(module, "_fetch_public_jwks", return_value={})
                )
                stack.enter_context(
                    mock.patch.object(module, "_validate_public_jwks", return_value={})
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_run_official_container_client",
                        return_value={},
                    )
                )
                stack.enter_context(
                    mock.patch.object(module, "_stop_runtime", return_value=([], 0))
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_read_persisted_state",
                        return_value=state,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_data_state_hash",
                        return_value="sha256:" + "c" * 64,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_run_actual_compose_journey",
                        return_value={},
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_restore_data_directory_ownership",
                        return_value=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_remove_runtime_image",
                        return_value=True,
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        module,
                        "_build_success_report",
                        return_value=report,
                    )
                )
                raised = stack.enter_context(self.assertRaises(module.LifecycleProbeFailure))
                module.run_probe(output_path)

            self.assertEqual(raised.exception.stage, "report")
            self.assertEqual(
                raised.exception.code,
                "report_output_write_failed",
            )
            self.assertEqual(output_path.read_bytes(), previous_output)

    def test_main_failure_reports_use_atomic_output_and_do_not_leak_write_faults(
        self,
    ) -> None:
        module = _load_lifecycle_probe()
        previous_output = b'{"authority":"previous"}\n'
        fault_detail = "sensitive-main-fault-/tmp/private-report"

        with tempfile.TemporaryDirectory(
            prefix="formowl-lifecycle-main-output-",
            dir=tempfile.gettempdir(),
        ) as directory:
            root = Path(directory)
            cases = (
                (
                    "lifecycle",
                    module.LifecycleProbeFailure(
                        "real_google_preflight",
                        "connected_preflight_not_ready",
                    ),
                    "real_google_preflight",
                    "connected_preflight_not_ready",
                ),
                (
                    "generic",
                    OSError(fault_detail),
                    "orchestration",
                    "lifecycle_probe_failed",
                ),
            )
            for name, run_error, expected_stage, expected_code in cases:
                with self.subTest(name=name):
                    output_path = root / f"{name}.json"
                    output_path.write_bytes(previous_output)
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(module, "run_probe", side_effect=run_error),
                        mock.patch.object(
                            module,
                            "_atomic_write",
                            side_effect=module.LifecycleProbeFailure(
                                "report",
                                "report_output_write_failed",
                            ),
                        ) as atomic_write,
                        redirect_stdout(stdout),
                        redirect_stderr(stderr),
                    ):
                        exit_code = module.main(["--output", str(output_path)])

                    self.assertEqual(exit_code, 1)
                    self.assertEqual(output_path.read_bytes(), previous_output)
                    self.assertEqual(stderr.getvalue(), "")
                    rendered = stdout.getvalue()
                    public_report = json.loads(rendered)
                    self.assertEqual(public_report["status"], "failed")
                    self.assertEqual(public_report["failure_stage"], expected_stage)
                    self.assertEqual(public_report["error_code"], expected_code)
                    self.assertNotIn(fault_detail, rendered)
                    self.assertNotIn(str(output_path), rendered)
                    atomic_write.assert_called_once()

    def test_lifecycle_probe_safe_report_contract_is_bounded(self) -> None:
        module = _load_lifecycle_probe()
        runtime_image_id = "sha256:" + "a" * 64
        evidence = {
            "runtime_image_id": runtime_image_id,
            "image_contract": {
                "runtime_image_id": runtime_image_id,
                "entrypoint": ["formowl-container-entrypoint"],
                "cmd": ["serve"],
                "user": "root",
                "working_dir": "/home/formowl",
                "implementation_contract_hash": (
                    module._current_issue20_implementation_contract_hash()
                ),
            },
            "compose_projection": {
                "connected_command": ["serve"],
                "migrate_command": ["migrate"],
                "read_only": True,
                "connected_image_id": runtime_image_id,
                "migrate_image_id": runtime_image_id,
                "project_image_id": runtime_image_id,
                "wiki_image_id": runtime_image_id,
                "postgres_image": module.PINNED_POSTGRES_IMAGE,
                "operator_owned_0400_secret_count": 7,
            },
            "compose_service_count": 5,
            "initial_migration": {
                "status": "ok",
                "applied_migration_count": 5,
                "skipped_migration_count": 0,
            },
            "restart_migration": {
                "status": "ok",
                "applied_migration_count": 0,
                "skipped_migration_count": 5,
            },
            "oauth_seed": {
                "status": "ok",
                "seed_count": 1,
                "seed_state_hash": module._sha256_json({"seeded": True}),
            },
            "first_client": {
                "status": "ok",
                "allowed_count": 2,
                "denied_count": 1,
                "result_shape_hash": module._sha256_json({"phase": "first"}),
            },
            "restart_client": {
                "status": "ok",
                "allowed_count": 1,
                "denied_count": 0,
                "result_shape_hash": module._sha256_json({"phase": "restart"}),
            },
            "first_state": {
                "status": "ok",
                "counts": {
                    "user_count": 1,
                    "external_identity_count": 1,
                    "token_session_count": 1,
                    "upload_session_count": 1,
                    "file_audit_count": 1,
                    "mcp_allowed_count": 2,
                    "mcp_denied_count": 1,
                },
                "core_state_hash": module._sha256_json({"core": "stable"}),
                "snapshot_hash": module._sha256_json({"snapshot": "first"}),
            },
            "restart_state": {
                "status": "ok",
                "counts": {
                    "user_count": 1,
                    "external_identity_count": 1,
                    "token_session_count": 1,
                    "upload_session_count": 1,
                    "file_audit_count": 1,
                    "mcp_allowed_count": 3,
                    "mcp_denied_count": 1,
                },
                "core_state_hash": module._sha256_json({"core": "stable"}),
                "snapshot_hash": module._sha256_json({"snapshot": "restart"}),
            },
            "migration_applied_count": 5,
            "migration_restart_skipped_count": 5,
            "readiness_shapes": [{"status": "ready", "checks": ["database", "runtime"]}] * 3,
            "jwks_phases": [
                {"key_count": 1, "kid_set_hash": module._sha256_json(["a"])},
                {"key_count": 2, "kid_set_hash": module._sha256_json(["a", "b"])},
                {"key_count": 1, "kid_set_hash": module._sha256_json(["b"])},
            ],
            "security_contract": {"process_uid": 10001, "read_only": True},
            "runtime_log_hashes": [module._sha256_json("")] * 3,
            "runtime_log_line_count": 0,
            "data_state_hash": module._sha256_json(["audit", "ingestion"]),
            "compose_journey": {
                "postgres_secret_contract": {
                    "same_operator_owned_source": True,
                    "secret_mount_read_only": True,
                    "postgres_healthy": True,
                },
                "migration": {
                    "status": "ok",
                    "applied_migration_count": 5,
                    "skipped_migration_count": 0,
                },
                "preflight_check_count": 4,
                "runtime_ready_count": 3,
                "healthcheck_success_count": 3,
                "retired_container_count": 2,
                "runtime_process_uid": 10001,
                "security_contracts": [
                    {
                        "phase": phase,
                        "process_uid": 10001,
                        "process_gid": 10001,
                        "process_supplementary_group_count": 0,
                        "process_capability_count": 0,
                        "process_no_new_privileges": 1,
                        "probe_uid": 10001,
                        "probe_gid": 10001,
                        "probe_supplementary_group_count": 0,
                        "probe_root_regain_denied": True,
                        "health_uses_privilege_drop_launcher": True,
                        "health_status_healthy": True,
                        "successful_healthcheck_count": 1,
                    }
                    for phase in ("initial", "overlap", "retired")
                ],
                "secret_snapshots": [
                    {
                        "content_hash": module._sha256_json({"phase": "initial"}),
                        "file_count": 5,
                        "instance_hash": module._sha256_json({"instance": 1}),
                    },
                    {
                        "content_hash": module._sha256_json({"phase": "overlap"}),
                        "file_count": 6,
                        "instance_hash": module._sha256_json({"instance": 2}),
                    },
                    {
                        "content_hash": module._sha256_json({"phase": "retired"}),
                        "file_count": 5,
                        "instance_hash": module._sha256_json({"instance": 3}),
                    },
                ],
                "jwks_phases": [
                    {"key_count": 1},
                    {"key_count": 2},
                    {"key_count": 1},
                ],
                "runtime_log_hashes": [
                    module._sha256_json({"compose_log": phase})
                    for phase in ("initial", "overlap", "retired")
                ],
            },
        }

        report = module._build_success_report(evidence)
        validation = module.validate_report(report)

        self.assertTrue(validation["passed"], validation["blockers"])
        rendered = str(report).lower()
        for forbidden in (
            "postgresql://",
            "http://",
            "https://",
            "/run/secrets/",
            "/run/formowl-secrets",
            "begin private key",
            "select ",
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertFalse(report["claim_boundary"]["token_overlap_semantics_reverified"])
        self.assertFalse(report["claim_boundary"]["production_readiness"])
        self.assertEqual(report["safe_counts"]["operator_owned_0400_secret_count"], 7)
        self.assertEqual(
            report["safe_hashes"]["implementation_contract_hash"],
            module._current_issue20_implementation_contract_hash(),
        )

        stale_report = copy.deepcopy(report)
        stale_report["safe_hashes"]["implementation_contract_hash"] = "sha256:" + "f" * 64
        stale_validation = module.validate_report(stale_report)
        self.assertFalse(stale_validation["passed"])
        self.assertIn("implementation contract hash is stale", stale_validation["blockers"])

        duplicate_hash_report = copy.deepcopy(report)
        duplicate_hash_report["safe_hashes"]["runtime_image_contract_hash"] = duplicate_hash_report[
            "safe_hashes"
        ]["compose_runtime_wiring_hash"]
        duplicate_validation = module.validate_report(duplicate_hash_report)
        self.assertFalse(duplicate_validation["passed"])
        self.assertIn(
            "safe hashes must be independently bound",
            duplicate_validation["blockers"],
        )

        stale_command_report = copy.deepcopy(report)
        stale_command_report["safe_hashes"]["command_contract_hash"] = module._sha256_json(
            {"postgres_image": "pgvector/pgvector:0.8.0-pg17"}
        )
        stale_command_validation = module.validate_report(stale_command_report)
        self.assertFalse(stale_command_validation["passed"])
        self.assertIn(
            "command contract hash is stale",
            stale_command_validation["blockers"],
        )

    def test_lifecycle_probe_rejects_private_jwk_and_unsafe_failure_detail(self) -> None:
        module = _load_lifecycle_probe()

        with self.assertRaises(module.LifecycleProbeFailure):
            module._validate_public_jwks(
                {
                    "keys": [
                        {
                            "kid": module.INITIAL_KID,
                            "kty": "RSA",
                            "alg": "RS256",
                            "n": "public",
                            "e": "AQAB",
                            "d": "private",
                        }
                    ]
                },
                {module.INITIAL_KID},
            )

        unsafe = {
            "artifact_id": module.ARTIFACT_ID,
            "status": "failed",
            "failure_stage": "preflight",
            "error_code": "https://private.example.test/error",
        }
        validation = module.validate_report(unsafe)
        self.assertFalse(validation["passed"])
        self.assertIn("failure code is not safe", validation["blockers"])


if __name__ == "__main__":
    unittest.main()
