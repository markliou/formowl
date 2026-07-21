from __future__ import annotations

import asyncio
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from threading import Event, Thread
import types
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
import oauth_harness


_TARGET_FUNCTION = ("tests.oauth_harness", "sha256_json")
_DUNDER_TARGET_FUNCTION = ("tests.oauth_harness", "_HarnessUploadRecorder.__call__")
_POSTGRES_CONSUME_CODE_TARGET = (
    "formowl_auth.postgres",
    "PostgreSQLOAuthRepository.consume_authorization_code",
)
_POSTGRES_GET_CLIENT_AUTHORIZATION_TARGET = (
    "formowl_auth.postgres",
    "PostgreSQLOAuthRepository.get_client_authorization",
)
_POSTGRES_GET_CLIENT_AUTHORIZATION_BY_ID_TARGET = (
    "formowl_auth.postgres",
    "PostgreSQLOAuthRepository.get_client_authorization_by_id",
)
_POSTGRES_INSERT_AUTHORIZATION_CODE_TARGET = (
    "formowl_auth.postgres",
    "PostgreSQLOAuthRepository.insert_authorization_code",
)
_POSTGRES_INSERT_CLIENT_AUTHORIZATION_TARGET = (
    "formowl_auth.postgres",
    "PostgreSQLOAuthRepository.insert_client_authorization",
)
_REENTRANT_HARNESS_TEST_IDS = (
    (
        "tests.test_oauth_mcp_harness_script.OAuthMcpHarnessScriptTests."
        "test_cli_aggregates_and_binds_lifecycle_reports_without_exposing_paths"
    ),
    (
        "tests.test_oauth_mcp_harness_script.OAuthMcpHarnessScriptTests."
        "test_main_direct_success_atomically_replaces_existing_safe_report"
    ),
    (
        "tests.test_oauth_mcp_harness_script.OAuthMcpHarnessScriptTests."
        "test_run_oauth_mcp_harness_direct_success_is_safe_and_side_effect_free"
    ),
)


def _path_is_within(path: object, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _module_is_under_tests_root(module: object, tests_root: Path) -> bool:
    module_file = getattr(module, "__file__", None)
    if module_file is not None and _path_is_within(module_file, tests_root):
        return True
    module_path = getattr(module, "__path__", None)
    if module_path is None:
        return False
    return any(_path_is_within(path, tests_root) for path in module_path)


def _repository_test_module_snapshot(tests_root: Path) -> dict[str, types.ModuleType]:
    return {
        name: module
        for name, module in sys.modules.items()
        if _module_is_under_tests_root(module, tests_root)
    }


def _restore_repository_test_modules(
    snapshot: dict[str, types.ModuleType],
    tests_root: Path,
) -> None:
    for name, module in tuple(sys.modules.items()):
        if _module_is_under_tests_root(module, tests_root) and name not in snapshot:
            sys.modules.pop(name, None)
    sys.modules.update(snapshot)


def _clean_room_test_alias_names(tests_root: Path) -> set[str]:
    helper_paths = {
        (tests_root / "_paths.py").resolve(),
        (tests_root / "oauth_harness.py").resolve(),
    }
    names: set[str] = set()
    for name, module in sys.modules.items():
        module_file = getattr(module, "__file__", None)
        is_helper_alias = module_file is not None and Path(module_file).resolve() in helper_paths
        if (
            name == "tests"
            or name.startswith("tests.")
            or name in {"_paths", "oauth_harness"}
            or is_helper_alias
        ):
            names.add(name)
    return names


class FixtureOnlyCoverageProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        oauth_harness.sha256_json({"fixture": "class"})

    def test_body_does_not_call_target(self) -> None:
        self.assertTrue(True)


class DirectCoverageProbe(unittest.TestCase):
    def test_body_calls_target(self) -> None:
        value = oauth_harness.sha256_json({"fixture": "direct"})

        self.assertTrue(value.startswith("sha256:"))


class PerTestFixtureCoverageProbe(unittest.TestCase):
    def setUp(self) -> None:
        oauth_harness.sha256_json({"fixture": "setUp"})
        self.addCleanup(oauth_harness.sha256_json, {"fixture": "cleanup"})

    def tearDown(self) -> None:
        oauth_harness.sha256_json({"fixture": "tearDown"})

    def test_body_does_not_call_target(self) -> None:
        self.assertTrue(True)


class SetUpSpawnedThreadCoverageProbe(unittest.TestCase):
    def setUp(self) -> None:
        self.release_worker = Event()
        self.worker_finished = Event()

        def fixture_worker() -> None:
            self.release_worker.wait(timeout=5)
            oauth_harness.sha256_json({"fixture": "setUp-thread"})
            self.worker_finished.set()

        self.fixture_thread = Thread(target=fixture_worker)
        self.fixture_thread.start()
        self.addCleanup(self.fixture_thread.join, 5)

    def test_body_only_releases_setup_thread(self) -> None:
        self.release_worker.set()

        self.assertTrue(self.worker_finished.wait(timeout=5))


class ThreadedDirectCoverageProbe(unittest.TestCase):
    def test_body_calls_target_from_spawned_thread(self) -> None:
        values: list[str] = []
        thread = Thread(
            target=lambda: values.append(oauth_harness.sha256_json({"fixture": "thread"}))
        )

        thread.start()
        thread.join()

        self.assertEqual(len(values), 1)
        self.assertTrue(values[0].startswith("sha256:"))


class AsyncDirectCoverageProbe(unittest.IsolatedAsyncioTestCase):
    async def test_body_calls_target_after_await(self) -> None:
        await asyncio.sleep(0)

        value = oauth_harness.sha256_json({"fixture": "async"})

        self.assertTrue(value.startswith("sha256:"))


class ExplicitDunderCoverageProbe(unittest.TestCase):
    def test_body_calls_explicit_dunder(self) -> None:
        recorder = oauth_harness._HarnessUploadRecorder(clock=oauth_harness.FakeClock().now)

        result = recorder(
            {
                "requester_user_id": "user_probe",
                "workspace_id": "workspace_probe",
                "session_id": "session_probe",
                "intended_asset_type": "pst",
            }
        )

        self.assertEqual(result["status"], "ok")


class OAuthHarnessExecutionTests(unittest.TestCase):
    def test_per_test_fixtures_and_cleanups_do_not_satisfy_direct_body_trace(self) -> None:
        test_ids = (
            (
                "tests.test_oauth_harness_execution.PerTestFixtureCoverageProbe."
                "test_body_does_not_call_target"
            ),
            (
                "tests.test_oauth_harness_execution.SetUpSpawnedThreadCoverageProbe."
                "test_body_only_releases_setup_thread"
            ),
        )
        for test_id in test_ids:
            with self.subTest(test_id=test_id):
                manifest = _execution_manifest(test_id)

                execution = oauth_harness.run_function_harness_test_suite(manifest)
                validation = oauth_harness.validate_function_harness_execution(manifest, execution)

                self.assertTrue(execution["passed"])
                self.assertNotIn(_TARGET_FUNCTION, execution["_coverage_by_test"][test_id])
                self.assertFalse(validation["passed"])
                self.assertEqual(validation["direct_trace_missing_function_count"], 1)

    def test_async_and_spawned_thread_body_calls_remain_direct_traces(self) -> None:
        test_ids = (
            "tests.test_oauth_harness_execution.AsyncDirectCoverageProbe."
            "test_body_calls_target_after_await",
            "tests.test_oauth_harness_execution.ThreadedDirectCoverageProbe."
            "test_body_calls_target_from_spawned_thread",
        )
        for test_id in test_ids:
            with self.subTest(test_id=test_id):
                manifest = _execution_manifest(test_id)

                execution = oauth_harness.run_function_harness_test_suite(manifest)
                validation = oauth_harness.validate_function_harness_execution(manifest, execution)

                self.assertTrue(execution["passed"])
                self.assertIn(_TARGET_FUNCTION, execution["_coverage_by_test"][test_id])
                self.assertTrue(validation["passed"], validation["blockers"])

    def test_class_fixture_calls_do_not_satisfy_per_test_function_correlation(self) -> None:
        test_id = (
            "tests.test_oauth_harness_execution.FixtureOnlyCoverageProbe."
            "test_body_does_not_call_target"
        )
        manifest = _execution_manifest(test_id)

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertNotIn(
            _TARGET_FUNCTION,
            execution["_coverage_by_test"][test_id],
        )
        self.assertFalse(validation["passed"])
        self.assertEqual(validation["checked_pair_count"], 1)
        self.assertTrue(
            all(
                "onboarded function has no passing direct runtime trace" in blocker
                for blocker in validation["blockers"]
            )
        )

    def test_direct_test_calls_satisfy_per_test_function_correlation(self) -> None:
        test_id = "tests.test_oauth_harness_execution.DirectCoverageProbe." "test_body_calls_target"
        manifest = _execution_manifest(test_id)

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertIn(_TARGET_FUNCTION, execution["_coverage_by_test"][test_id])
        self.assertTrue(validation["passed"])
        self.assertEqual(validation["checked_pair_count"], 1)
        self.assertEqual(validation["direct_trace_covered_function_count"], 1)
        self.assertEqual(validation["direct_trace_missing_function_count"], 0)

    def test_category_evidence_need_not_each_repeat_the_direct_body_trace(self) -> None:
        direct_test_id = (
            "tests.test_oauth_harness_execution.DirectCoverageProbe." "test_body_calls_target"
        )
        indirect_test_id = (
            "tests.test_oauth_harness_execution.FixtureOnlyCoverageProbe."
            "test_body_does_not_call_target"
        )
        manifest = _execution_manifest(direct_test_id)
        entry = manifest["functions"][0]
        entry["categories"]["invalid_or_protocol"]["test_ids"] = [indirect_test_id]
        entry["test_ids"] = [direct_test_id, indirect_test_id]

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertIn(_TARGET_FUNCTION, execution["_coverage_by_test"][direct_test_id])
        self.assertNotIn(_TARGET_FUNCTION, execution["_coverage_by_test"][indirect_test_id])
        self.assertTrue(validation["passed"], validation["blockers"])
        self.assertEqual(validation["checked_pair_count"], 2)
        self.assertEqual(validation["direct_trace_covered_function_count"], 1)
        self.assertEqual(validation["direct_trace_missing_function_count"], 0)

    def test_explicit_dunder_call_requires_and_satisfies_direct_trace_correlation(self) -> None:
        test_id = (
            "tests.test_oauth_harness_execution.ExplicitDunderCoverageProbe."
            "test_body_calls_explicit_dunder"
        )
        manifest = _execution_manifest(test_id, target_function=_DUNDER_TARGET_FUNCTION)

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertIn(_DUNDER_TARGET_FUNCTION, execution["_coverage_by_test"][test_id])
        self.assertTrue(validation["passed"])

    def test_postgres_authorization_code_consume_has_direct_passing_trace(self) -> None:
        test_id = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_consume_authorization_code_is_single_use_bound_and_transactional"
        )
        manifest = _execution_manifest(
            test_id,
            target_function=_POSTGRES_CONSUME_CODE_TARGET,
            include_globs=["python/formowl_auth/postgres.py"],
        )

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertIn(
            _POSTGRES_CONSUME_CODE_TARGET,
            execution["_coverage_by_test"][test_id],
        )
        self.assertTrue(validation["passed"])

    def test_postgres_client_authorization_lookup_has_direct_passing_trace(self) -> None:
        test_id = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_get_client_authorization_uses_composite_key_and_returns_revoked_rows"
        )
        manifest = _execution_manifest(
            test_id,
            target_function=_POSTGRES_GET_CLIENT_AUTHORIZATION_TARGET,
            include_globs=["python/formowl_auth/postgres.py"],
        )

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertIn(
            _POSTGRES_GET_CLIENT_AUTHORIZATION_TARGET,
            execution["_coverage_by_test"][test_id],
        )
        self.assertTrue(validation["passed"])

    def test_postgres_client_authorization_id_lookup_has_direct_passing_trace(self) -> None:
        test_id = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_get_client_authorization_by_id_is_parameterized_and_returns_revoked_rows"
        )
        manifest = _execution_manifest(
            test_id,
            target_function=_POSTGRES_GET_CLIENT_AUTHORIZATION_BY_ID_TARGET,
            include_globs=["python/formowl_auth/postgres.py"],
        )

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertIn(
            _POSTGRES_GET_CLIENT_AUTHORIZATION_BY_ID_TARGET,
            execution["_coverage_by_test"][test_id],
        )
        self.assertTrue(validation["passed"])

    def test_postgres_authorization_code_insert_has_direct_passing_trace(self) -> None:
        test_id = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_insert_authorization_code_persists_only_hash_and_rolls_back_on_failure"
        )
        manifest = _execution_manifest(
            test_id,
            target_function=_POSTGRES_INSERT_AUTHORIZATION_CODE_TARGET,
            include_globs=["python/formowl_auth/postgres.py"],
        )

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertIn(
            _POSTGRES_INSERT_AUTHORIZATION_CODE_TARGET,
            execution["_coverage_by_test"][test_id],
        )
        self.assertTrue(validation["passed"])

    def test_postgres_client_authorization_insert_has_direct_passing_trace(self) -> None:
        test_id = (
            "tests.test_oauth_postgres_repository.OAuthPostgresRepositoryTests."
            "test_insert_client_authorization_preserves_bindings_and_rolls_back_unique_failure"
        )
        manifest = _execution_manifest(
            test_id,
            target_function=_POSTGRES_INSERT_CLIENT_AUTHORIZATION_TARGET,
            include_globs=["python/formowl_auth/postgres.py"],
        )

        execution = oauth_harness.run_function_harness_test_suite(manifest)
        validation = oauth_harness.validate_function_harness_execution(manifest, execution)

        self.assertTrue(execution["passed"])
        self.assertIn(
            _POSTGRES_INSERT_CLIENT_AUTHORIZATION_TARGET,
            execution["_coverage_by_test"][test_id],
        )
        self.assertTrue(validation["passed"])

    def test_skip_failure_error_expected_failure_and_unexpected_success_fail_closed(
        self,
    ) -> None:
        def failing(test: unittest.TestCase) -> None:
            test.fail("intentional harness outcome probe")

        def erroring(_test: unittest.TestCase) -> None:
            raise RuntimeError("intentional harness outcome probe")

        def expected_failure(test: unittest.TestCase) -> None:
            test.fail("intentional expected failure")

        def unexpected_success(_test: unittest.TestCase) -> None:
            return None

        probes = (
            ("skip", unittest.skip("intentional skip")(lambda _test: None), "skip_count"),
            ("failure", failing, "failure_count"),
            ("error", erroring, "error_count"),
            (
                "expected_failure",
                unittest.expectedFailure(expected_failure),
                "expected_failure_count",
            ),
            (
                "unexpected_success",
                unittest.expectedFailure(unexpected_success),
                "unexpected_success_count",
            ),
        )

        for name, method, count_key in probes:
            with self.subTest(name=name), _temporary_test_module(name, method) as test_id:
                execution = oauth_harness.run_function_harness_test_suite(
                    _execution_manifest(test_id)
                )

                self.assertFalse(execution["passed"])
                self.assertEqual(execution[count_key], 1)

    def test_unresolvable_exact_test_id_fails_closed(self) -> None:
        test_id = "tests.issue20_missing_probe.Probe.test_case"
        repository_root = Path(oauth_harness.__file__).resolve().parents[1]
        tests_root = repository_root / "tests"
        python_root = repository_root / "python"
        original_sys_path = list(sys.path)
        original_test_modules = _repository_test_module_snapshot(tests_root)
        removed_module_names = _clean_room_test_alias_names(tests_root)

        def resolves_to(entry: str, target: Path) -> bool:
            try:
                return Path(entry or ".").resolve() == target
            except OSError:
                return False

        isolated_sys_path = [
            entry
            for entry in original_sys_path
            if not resolves_to(entry, repository_root)
            and not resolves_to(entry, tests_root)
            and not resolves_to(entry, python_root)
        ]
        try:
            sys.path[:] = isolated_sys_path
            for name in removed_module_names:
                sys.modules.pop(name, None)
            isolated_test_modules = _repository_test_module_snapshot(tests_root)

            execution = oauth_harness.run_function_harness_test_suite(
                _execution_manifest(test_id),
                root=repository_root,
            )

            self.assertFalse(execution["passed"])
            self.assertEqual(execution["requested_test_count"], 1)
            self.assertEqual(execution["resolved_test_count"], 0)
            self.assertGreater(execution["resolution_blocker_count"], 0)
            self.assertEqual(sys.path, isolated_sys_path)
            self.assertEqual(
                _repository_test_module_snapshot(tests_root),
                isolated_test_modules,
            )
        finally:
            sys.path[:] = original_sys_path
            _restore_repository_test_modules(original_test_modules, tests_root)

    def test_repository_root_is_temporary_for_resolution_and_execution(self) -> None:
        test_id = "tests.test_oauth_harness_execution.DirectCoverageProbe." "test_body_calls_target"
        repository_root = Path(oauth_harness.__file__).resolve().parents[1]
        tests_root = repository_root / "tests"
        python_root = repository_root / "python"
        original_sys_path = list(sys.path)
        original_test_modules = _repository_test_module_snapshot(tests_root)
        removed_module_names = _clean_room_test_alias_names(tests_root)

        def resolves_to(entry: str, target: Path) -> bool:
            try:
                return Path(entry or ".").resolve() == target
            except OSError:
                return False

        isolated_sys_path = [
            entry
            for entry in original_sys_path
            if not resolves_to(entry, repository_root)
            and not resolves_to(entry, tests_root)
            and not resolves_to(entry, python_root)
        ]
        try:
            sys.path[:] = isolated_sys_path
            for name in removed_module_names:
                sys.modules.pop(name, None)
            isolated_test_modules = _repository_test_module_snapshot(tests_root)

            execution = oauth_harness.run_function_harness_test_suite(
                _execution_manifest(test_id),
                root=repository_root,
            )

            self.assertEqual(execution["requested_test_count"], 1)
            self.assertEqual(execution["resolved_test_count"], 1)
            self.assertEqual(execution["run_count"], 1)
            self.assertEqual(execution["pass_count"], 1)
            self.assertTrue(execution["passed"])
            self.assertEqual(sys.path, isolated_sys_path)
            self.assertEqual(
                _repository_test_module_snapshot(tests_root),
                isolated_test_modules,
            )
        finally:
            sys.path[:] = original_sys_path
            _restore_repository_test_modules(original_test_modules, tests_root)

    def test_foreign_test_aliases_are_evicted_and_restored_exactly(self) -> None:
        repository_root = Path(oauth_harness.__file__).resolve().parents[1]
        target_test_id = (
            "tests.test_oauth_harness_execution.DirectCoverageProbe." "test_body_calls_target"
        )
        missing_test_id = "tests.issue20_missing_foreign_probe.Probe.test_case"
        sentinel_names = (
            "tests",
            "tests.test_oauth_harness_execution",
            "_paths",
            "oauth_harness",
            "test_oauth_harness_execution",
        )
        original_aliases = {
            name: sys.modules[name] for name in sentinel_names if name in sys.modules
        }
        foreign_parent = types.ModuleType("tests")
        foreign_parent.__path__ = ["/tmp/formowl-foreign-tests"]
        foreign_modules = {
            "tests": foreign_parent,
            "tests.test_oauth_harness_execution": types.ModuleType(
                "tests.test_oauth_harness_execution"
            ),
            "_paths": types.ModuleType("_paths"),
            "oauth_harness": types.ModuleType("oauth_harness"),
            "test_oauth_harness_execution": types.ModuleType("test_oauth_harness_execution"),
        }
        original_load_tests_from_name = unittest.TestLoader.loadTestsFromName

        def guarded_load_tests_from_name(
            loader: unittest.TestLoader,
            name: str,
            module: types.ModuleType | None = None,
        ) -> unittest.TestSuite:
            for alias, sentinel in foreign_modules.items():
                self.assertIsNot(sys.modules.get(alias), sentinel)
            return original_load_tests_from_name(loader, name, module)

        try:
            sys.modules.update(foreign_modules)
            with patch.object(
                unittest.TestLoader,
                "loadTestsFromName",
                guarded_load_tests_from_name,
            ):
                execution = oauth_harness.run_function_harness_test_suite(
                    _execution_manifest(target_test_id),
                    root=repository_root,
                )

                self.assertTrue(execution["passed"])
                self.assertEqual(execution["resolved_test_count"], 1)
                self.assertEqual(execution["run_count"], 1)
                for alias, sentinel in foreign_modules.items():
                    self.assertIs(sys.modules.get(alias), sentinel)

                failed_execution = oauth_harness.run_function_harness_test_suite(
                    _execution_manifest(missing_test_id),
                    root=repository_root,
                )

                self.assertFalse(failed_execution["passed"])
                self.assertEqual(failed_execution["resolved_test_count"], 0)
                for alias, sentinel in foreign_modules.items():
                    self.assertIs(sys.modules.get(alias), sentinel)
        finally:
            for name in sentinel_names:
                if name in original_aliases:
                    sys.modules[name] = original_aliases[name]
                else:
                    sys.modules.pop(name, None)

    def test_stale_repository_script_aliases_are_isolated_for_reentrant_harness_tests(
        self,
    ) -> None:
        repository_root = Path(oauth_harness.__file__).resolve().parents[1]
        script_path = repository_root / "scripts" / "oauth_mcp_harness.py"
        original_sys_path = list(sys.path)
        stale_alias_names = (
            "oauth_mcp_harness",
            "connected_operator_postgres_live_journey",
            "connected_runtime_container_lifecycle_probe",
            "connected_runtime_postgres_live_e2e",
        )
        original_aliases = {
            name: sys.modules[name] for name in stale_alias_names if name in sys.modules
        }
        stale_spec = importlib.util.spec_from_file_location(
            "stale_issue20_oauth_mcp_harness",
            script_path,
        )
        if stale_spec is None or stale_spec.loader is None:
            self.fail("could not load stale issue #20 OAuth MCP harness alias")
        stale_harness_module = importlib.util.module_from_spec(stale_spec)

        try:
            stale_spec.loader.exec_module(stale_harness_module)
            sys.modules["oauth_mcp_harness"] = stale_harness_module
            harness_sys_path = list(sys.path)
            stale_aliases = {
                name: sys.modules[name] for name in stale_alias_names if name in sys.modules
            }
            self.assertEqual(set(stale_aliases), set(stale_alias_names))
            manifest = _execution_manifest(_REENTRANT_HARNESS_TEST_IDS[0])
            manifest["functions"][0]["test_ids"] = list(_REENTRANT_HARNESS_TEST_IDS)

            execution = oauth_harness.run_function_harness_test_suite(
                manifest,
                root=repository_root,
            )

            self.assertTrue(execution["passed"])
            self.assertEqual(execution["requested_test_count"], 3)
            self.assertEqual(execution["resolved_test_count"], 3)
            self.assertEqual(execution["run_count"], 3)
            self.assertEqual(execution["pass_count"], 3)
            self.assertEqual(execution["failure_count"], 0)
            self.assertEqual(execution["error_count"], 0)
            self.assertEqual(sys.path, harness_sys_path)
            for alias, stale_module in stale_aliases.items():
                self.assertIs(sys.modules.get(alias), stale_module)
        finally:
            sys.path[:] = original_sys_path
            for name in stale_alias_names:
                if name in original_aliases:
                    sys.modules[name] = original_aliases[name]
                else:
                    sys.modules.pop(name, None)


class OAuthHarnessManifestSchemaTests(unittest.TestCase):
    def test_authoritative_scope_covers_all_python_and_script_functions(self) -> None:
        self.assertEqual(
            oauth_harness.ISSUE20_FUNCTION_SCOPE_GLOBS,
            ("python/**/*.py", "scripts/**/*.py", "deploy/**/*.py"),
        )

        function_key = ("sample.module", "target")
        test_id = "tests.test_sample.SampleTests.test_target"
        manifest = _minimal_manifest([function_key], test_id)
        manifest["scope"]["include_globs"] = ["python/formowl_auth/**/*.py"]

        with _manifest_world({function_key}, {test_id}):
            validation = oauth_harness.validate_function_harness_manifest(manifest)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any("manifest.scope.include_globs mismatch" in item for item in validation["blockers"])
        )

    def test_explicit_dunder_implementations_are_fingerprinted_but_declarations_are_not(
        self,
    ) -> None:
        fingerprints = oauth_harness._function_fingerprints(
            """
from typing import overload

class Lifecycle:
    def __init__(self):
        self.ready = False

    def __post_init__(self):
        self.ready = True

    def __call__(self, value):
        return value if self.ready else None

    def __enter__(self):
        self.ready = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.ready = False

    async def __aenter__(self):
        self.ready = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.ready = False

    @overload
    def convert(self, value: int) -> int: ...

    def convert(self, value):
        return value

class ProtocolLike:
    def declaration_only(self): ...
"""
        )
        qualnames = [item.qualname for item in fingerprints]

        self.assertEqual(
            qualnames,
            [
                "Lifecycle.__init__",
                "Lifecycle.__post_init__",
                "Lifecycle.__call__",
                "Lifecycle.__enter__",
                "Lifecycle.__exit__",
                "Lifecycle.__aenter__",
                "Lifecycle.__aexit__",
                "Lifecycle.convert",
            ],
        )
        self.assertNotIn("ProtocolLike.declaration_only", qualnames)

    def test_minimal_schema_v2_manifest_is_valid_in_a_controlled_function_world(self) -> None:
        function_key = ("sample.module", "target")
        test_id = "tests.test_sample.SampleTests.test_target"
        manifest = _minimal_manifest([function_key], test_id)

        with _manifest_world({function_key}, {test_id}):
            validation = oauth_harness.validate_function_harness_manifest(manifest)

        self.assertTrue(validation["passed"], validation["blockers"])
        self.assertEqual(validation["onboarded_function_count"], 1)
        self.assertEqual(validation["pending_function_count"], 0)

    def test_manifested_set_must_exactly_equal_changed_set(self) -> None:
        changed_key = ("sample.module", "changed_target")
        unchanged_key = ("sample.module", "unchanged_target")
        test_id = "tests.test_sample.SampleTests.test_target"
        manifest = _minimal_manifest([changed_key, unchanged_key], test_id)

        with (
            patch.object(oauth_harness, "collect_unittest_test_ids", return_value={test_id}),
            patch.object(
                oauth_harness,
                "current_scoped_functions",
                return_value={changed_key, unchanged_key},
            ),
            patch.object(
                oauth_harness,
                "changed_scoped_functions",
                return_value={changed_key},
            ),
            patch.object(
                oauth_harness,
                "changed_scoped_function_bindings",
                return_value={changed_key: _test_source_binding(changed_key)},
            ),
        ):
            validation = oauth_harness.validate_function_harness_manifest(manifest)

        self.assertFalse(validation["passed"])
        self.assertEqual(validation["missing_function_count"], 0)
        self.assertEqual(validation["extra_function_count"], 1)
        self.assertEqual(validation["duplicate_function_count"], 0)
        self.assertTrue(
            any(
                "manifested function is not added or modified" in item
                for item in validation["blockers"]
            )
        )

    def test_source_diff_binding_must_match_recomputed_changed_function(self) -> None:
        function_key = ("sample.module", "target")
        test_id = "tests.test_sample.SampleTests.test_target"
        expected_binding = _test_source_binding(function_key)
        manifest = _minimal_manifest([function_key], test_id)
        manifest["functions"][0]["source_binding"] = dict(expected_binding)

        with (
            patch.object(oauth_harness, "collect_unittest_test_ids", return_value={test_id}),
            patch.object(
                oauth_harness,
                "current_scoped_functions",
                return_value={function_key},
            ),
            patch.object(
                oauth_harness,
                "changed_scoped_functions",
                return_value={function_key},
            ),
            patch.object(
                oauth_harness,
                "changed_scoped_function_bindings",
                return_value={function_key: expected_binding},
                create=True,
            ),
        ):
            valid = oauth_harness.validate_function_harness_manifest(manifest)
            manifest["functions"][0]["source_binding"]["current_ast_sha256"] = "sha256:" + "9" * 64
            tampered = oauth_harness.validate_function_harness_manifest(manifest)

        self.assertTrue(valid["passed"], valid["blockers"])
        self.assertFalse(tampered["passed"])
        self.assertEqual(tampered["source_binding_mismatch_count"], 1)
        self.assertTrue(any("source binding mismatch" in item for item in tampered["blockers"]))

    def test_generator_emits_deterministic_pending_schema_v2_for_exact_changed_set(
        self,
    ) -> None:
        first_key = ("sample.module", "Alpha.__call__")
        second_key = ("sample.module", "zeta")
        bindings = {
            second_key: _test_source_binding(second_key),
            first_key: _test_source_binding(first_key),
        }

        with patch.object(
            oauth_harness,
            "changed_scoped_function_bindings",
            return_value=bindings,
        ):
            first = oauth_harness.generate_function_harness_manifest_skeleton()
            second = oauth_harness.generate_function_harness_manifest_skeleton()

        with (
            patch.object(oauth_harness, "collect_unittest_test_ids", return_value=set()),
            patch.object(
                oauth_harness,
                "current_scoped_functions",
                return_value=set(bindings),
            ),
            patch.object(
                oauth_harness,
                "changed_scoped_function_bindings",
                return_value=bindings,
            ),
        ):
            validation = oauth_harness.validate_function_harness_manifest(first)

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], 2)
        self.assertEqual(first["base_commit"], oauth_harness.ISSUE20_BASE_COMMIT)
        self.assertEqual(
            first["scope"],
            {
                "include_globs": list(oauth_harness.ISSUE20_FUNCTION_SCOPE_GLOBS),
                "exclusion_rules": list(oauth_harness.ISSUE20_FUNCTION_EXCLUSION_RULES),
            },
        )
        self.assertEqual(
            [(entry["module"], entry["qualname"]) for entry in first["functions"]],
            [first_key, second_key],
        )
        for entry in first["functions"]:
            function_key = (entry["module"], entry["qualname"])
            self.assertEqual(entry["status"], "pending")
            self.assertEqual(entry["source_binding"], bindings[function_key])
            self.assertEqual(entry["test_ids"], [])
            self.assertEqual(
                set(entry["categories"]), set(oauth_harness.REQUIRED_HARNESS_CATEGORIES)
            )
            for category, evidence in entry["categories"].items():
                self.assertEqual(evidence["test_ids"], [])
                self.assertIsNone(evidence["not_applicable_reason"])
                self.assertIn(".".join(function_key), evidence["pending_reason"])
                self.assertIn(category.replace("_", " "), evidence["pending_reason"])
        self.assertFalse(validation["passed"])
        self.assertEqual(validation["pending_function_count"], 2)
        self.assertEqual(validation["missing_function_count"], 0)
        self.assertEqual(validation["extra_function_count"], 0)
        self.assertEqual(validation["duplicate_function_count"], 0)
        self.assertEqual(validation["source_binding_mismatch_count"], 0)
        self.assertTrue(
            all(
                blocker.startswith("changed function remains pending: ")
                for blocker in validation["blockers"]
            )
        )

    def test_status_required_and_generic_not_applicable_reason_are_rejected(self) -> None:
        function_key = ("sample.module", "target")
        test_id = "tests.test_sample.SampleTests.test_target"
        manifest = _minimal_manifest([function_key], test_id)
        manifest["functions"][0]["status"] = "required"
        manifest["functions"][0]["categories"]["leak_safety"]["not_applicable_reason"] = (
            "not applicable"
        )

        with _manifest_world({function_key}, {test_id}):
            validation = oauth_harness.validate_function_harness_manifest(manifest)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("status is not supported" in item for item in validation["blockers"]))
        self.assertTrue(any("rejected generic phrase" in item for item in validation["blockers"]))

    def test_pending_entry_cannot_claim_tests_or_not_applicable_evidence(self) -> None:
        function_key = ("sample.module", "target")
        test_id = "tests.test_sample.SampleTests.test_target"
        manifest = _minimal_manifest([function_key], test_id)
        entry = manifest["functions"][0]
        entry["status"] = "pending"
        entry["categories"]["leak_safety"]["not_applicable_reason"] = _not_applicable_reason(
            function_key, "leak_safety"
        )

        with _manifest_world({function_key}, {test_id}):
            validation = oauth_harness.validate_function_harness_manifest(manifest)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any(
                "pending evidence cannot use tests or N/A" in item
                for item in validation["blockers"]
            )
        )
        self.assertTrue(
            any(
                "pending function must not claim executed test evidence" in item
                for item in validation["blockers"]
            )
        )

    def test_live_only_test_cannot_satisfy_local_function_evidence(self) -> None:
        function_key = ("sample.module", "target")
        live_test_id = "tests.test_oauth_owner_bootstrap_postgres_live.LiveTests.test_live_target"
        manifest = _minimal_manifest([function_key], live_test_id)

        with _manifest_world({function_key}, {live_test_id}):
            validation = oauth_harness.validate_function_harness_manifest(manifest)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("live-only test" in item for item in validation["blockers"]))

    def test_one_test_id_cannot_claim_more_than_twelve_changed_functions(self) -> None:
        function_keys = {("sample.module", f"target_{index}") for index in range(13)}
        test_id = "tests.test_sample.SampleTests.test_broad"
        manifest = _minimal_manifest(sorted(function_keys), test_id)

        with _manifest_world(function_keys, {test_id}):
            validation = oauth_harness.validate_function_harness_manifest(manifest)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any(
                "over-broad manifest test id is assigned to 13 functions" in item
                for item in validation["blockers"]
            )
        )


def _execution_manifest(
    test_id: str,
    *,
    target_function: tuple[str, str] = _TARGET_FUNCTION,
    include_globs: list[str] | None = None,
) -> dict[str, object]:
    categories = {
        category: {
            "test_ids": [test_id],
            "not_applicable_reason": None,
            "pending_reason": None,
        }
        for category in oauth_harness.REQUIRED_HARNESS_CATEGORIES
    }
    return {
        "scope": {"include_globs": include_globs or ["tests/oauth_harness.py"]},
        "functions": [
            {
                "module": target_function[0],
                "qualname": target_function[1],
                "status": "onboarded",
                "categories": categories,
                "test_ids": [test_id],
            }
        ],
    }


@contextmanager
def _temporary_test_module(name: str, method):
    module_name = f"issue20_harness_probe_{name}"
    module = types.ModuleType(module_name)
    probe = type("Probe", (unittest.TestCase,), {"test_case": method})
    probe.__module__ = module_name
    module.Probe = probe
    sys.modules[module_name] = module
    try:
        yield f"{module_name}.Probe.test_case"
    finally:
        sys.modules.pop(module_name, None)


@contextmanager
def _manifest_world(
    function_keys: set[tuple[str, str]],
    test_ids: set[str],
):
    bindings = {key: _test_source_binding(key) for key in function_keys}
    with (
        patch.object(oauth_harness, "collect_unittest_test_ids", return_value=test_ids),
        patch.object(oauth_harness, "current_scoped_functions", return_value=function_keys),
        patch.object(oauth_harness, "changed_scoped_functions", return_value=function_keys),
        patch.object(
            oauth_harness,
            "changed_scoped_function_bindings",
            return_value=bindings,
        ),
    ):
        yield


def _minimal_manifest(
    function_keys: list[tuple[str, str]],
    test_id: str,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "issue_number": 20,
        "base_commit": oauth_harness.ISSUE20_BASE_COMMIT,
        "scope": {
            "include_globs": list(oauth_harness.ISSUE20_FUNCTION_SCOPE_GLOBS),
            "exclusion_rules": list(oauth_harness.ISSUE20_FUNCTION_EXCLUSION_RULES),
        },
        "required_categories": list(oauth_harness.REQUIRED_HARNESS_CATEGORIES),
        "functions": [_minimal_entry(function_key, test_id) for function_key in function_keys],
    }


def _minimal_entry(function_key: tuple[str, str], test_id: str) -> dict[str, object]:
    categories = {}
    for category in oauth_harness.REQUIRED_HARNESS_CATEGORIES:
        if category == "success":
            categories[category] = {
                "test_ids": [test_id],
                "not_applicable_reason": None,
                "pending_reason": None,
            }
        else:
            categories[category] = {
                "test_ids": [],
                "not_applicable_reason": _not_applicable_reason(function_key, category),
                "pending_reason": None,
            }
    return {
        "module": function_key[0],
        "qualname": function_key[1],
        "status": "onboarded",
        "source_binding": _test_source_binding(function_key),
        "categories": categories,
        "test_ids": [test_id],
    }


def _not_applicable_reason(function_key: tuple[str, str], category: str) -> str:
    identity = ".".join(function_key)
    reasons = {
        "invalid_or_protocol": (
            f"{identity} receives only validated input and has no caller-controlled input, so "
            "this bounded calculation cannot parse protocol syntax or reject request shapes."
        ),
        "expiry_replay_or_revocation": (
            f"{identity} does not own expiry, replay, or revocation state; the bounded calculation "
            "has no clock, credential lifetime, token session, or reusable authorization input."
        ),
        "rollback_or_no_partial_state": (
            f"{identity} performs no durable write and does not open a transaction; the bounded "
            "calculation mutates no repository, audit ledger, object store, or external service."
        ),
        "audit_lineage": (
            f"{identity} does not emit audit or persist audit records; the bounded calculation has "
            "no actor, request, workspace, token session, or tool-call lineage side effect."
        ),
        "leak_safety": (
            f"{identity} cannot expose a raw path and returns only a fixed public shape; the bounded "
            "calculation receives no secret material, transcript, email address, token, or SQL."
        ),
        "remote_http": (
            f"{identity} is not an HTTP boundary and does not perform HTTP; the bounded calculation "
            "runs below remote transport, authentication challenge, protocol negotiation, and routing."
        ),
    }
    return reasons[category]


def _test_source_binding(function_key: tuple[str, str]) -> dict[str, object]:
    return {
        "source_path": "python/sample/module.py",
        "change_kind": "modified",
        "base_ast_sha256": "sha256:" + "1" * 64,
        "current_ast_sha256": "sha256:" + "2" * 64,
        "diff_sha256": oauth_harness.sha256_json(
            {
                "module": function_key[0],
                "qualname": function_key[1],
                "source_path": "python/sample/module.py",
                "change_kind": "modified",
                "base_ast_sha256": "sha256:" + "1" * 64,
                "current_ast_sha256": "sha256:" + "2" * 64,
            }
        ),
    }


if __name__ == "__main__":
    unittest.main()
