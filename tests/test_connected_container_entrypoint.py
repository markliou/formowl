from __future__ import annotations

from contextlib import ExitStack
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT_PATH = ROOT / "python" / "formowl_gateway" / "container_entrypoint.py"
CAPABILITY_PROBE_PATH = ROOT / "tests" / "issue20_capability_bounding_set_probe.py"


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, ENTRYPOINT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load container entrypoint")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_capability_probe():
    spec = importlib.util.spec_from_file_location(
        "issue20_capability_bounding_set_probe",
        CAPABILITY_PROBE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load capability bounding-set probe")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_secret(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    os.chmod(path, 0o400)


def _write_signing_manifest(source: Path, keys: list[dict[str, object]]) -> None:
    path = source / "formowl_signing_key_set"
    path.unlink(missing_ok=True)
    _write_secret(
        path,
        json.dumps({"version": 1, "keys": keys}, sort_keys=True).encode("utf-8"),
    )


def _configured_secret_fixture(root: Path) -> tuple[Path, Path, dict[str, str]]:
    source = root / "source"
    staged = root / "staged"
    source.mkdir(mode=0o700)
    staged.mkdir(mode=0o700)
    for name, payload in (
        ("formowl_database_dsn", b"postgresql://fixture\n"),
        ("formowl_google_client_secret", b"google-secret\n"),
        ("formowl_state_encryption_key", b"state-key\n"),
        ("formowl_signing_key_current", b"current-key\n"),
        ("formowl_signing_key_previous", b"previous-key\n"),
    ):
        _write_secret(source / name, payload)
    environ = {
        "FORMOWL_DATABASE_DSN_FILE": str(source / "formowl_database_dsn"),
        "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": str(source / "formowl_google_client_secret"),
        "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE": str(source / "formowl_state_encryption_key"),
        "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE": str(source / "formowl_signing_key_set"),
        "FORMOWL_TEST_SENTINEL": "unchanged",
    }
    return source, staged, environ


def _secret_tree_snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in sorted(root.iterdir())
    }


class ConnectedContainerEntrypointTests(unittest.TestCase):
    def test_stages_0400_secrets_and_rewrites_only_allowed_signing_paths(self) -> None:
        module = _load_module("formowl_container_entrypoint_stage")
        with tempfile.TemporaryDirectory(
            prefix="formowl-entrypoint-",
            dir=tempfile.gettempdir(),
        ) as value:
            root = Path(value)
            source = root / "source"
            staged = root / "staged"
            source.mkdir(mode=0o700)
            staged.mkdir(mode=0o700)
            for name, payload in (
                ("formowl_database_dsn", b"postgresql://fixture\n"),
                ("formowl_google_client_secret", b"google-secret\n"),
                ("formowl_state_encryption_key", b"state-key\n"),
                ("formowl_signing_key_current", b"current-key\n"),
                ("formowl_signing_key_previous", b"previous-key\n"),
            ):
                _write_secret(source / name, payload)
            manifest = {
                "version": 1,
                "keys": [
                    {
                        "kid": "current",
                        "private_key_file": str(source / "formowl_signing_key_current"),
                        "active": True,
                    },
                    {
                        "kid": "previous",
                        "private_key_file": str(source / "formowl_signing_key_previous"),
                        "active": False,
                        "verify_until": "2030-01-01T00:00:00+00:00",
                    },
                ],
            }
            _write_secret(
                source / "formowl_signing_key_set",
                json.dumps(manifest).encode("utf-8"),
            )
            environ = {
                "FORMOWL_DATABASE_DSN_FILE": str(source / "formowl_database_dsn"),
                "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": str(source / "formowl_google_client_secret"),
                "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE": str(
                    source / "formowl_state_encryption_key"
                ),
                "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE": str(source / "formowl_signing_key_set"),
            }
            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {
                        source / "formowl_signing_key_current",
                        source / "formowl_signing_key_previous",
                    },
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "chown"),
                mock.patch.object(module.os, "fchown"),
            ):
                staged_count = module.stage_configured_secrets(environ)

            self.assertEqual(staged_count, 4)
            self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o700)
            for path in staged.iterdir():
                self.assertTrue(path.is_file())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)
            rewritten = json.loads(
                Path(environ["FORMOWL_OAUTH_SIGNING_KEY_SET_FILE"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                rewritten,
                {
                    "version": 1,
                    "keys": [
                        {
                            "kid": "current",
                            "private_key_file": str(staged / "formowl_signing_key_0"),
                            "active": True,
                        },
                        {
                            "kid": "previous",
                            "private_key_file": str(staged / "formowl_signing_key_1"),
                            "active": False,
                            "verify_until": "2030-01-01T00:00:00+00:00",
                        },
                    ],
                },
            )
            for path in source.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)

    def test_rejects_symlink_path_escape_unknown_and_duplicate_manifest_keys(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_reject")
        with tempfile.TemporaryDirectory(
            prefix="formowl-entrypoint-reject-",
            dir=tempfile.gettempdir(),
        ) as value:
            root = Path(value)
            source = root / "source"
            staged = root / "staged"
            source.mkdir()
            staged.mkdir()
            outside = root / "outside"
            _write_secret(outside, b"outside")
            (source / "formowl_database_dsn").symlink_to(outside)
            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                self.assertRaises(module.ContainerEntrypointError),
            ):
                module._read_secret(source / "formowl_database_dsn")

            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                self.assertRaisesRegex(
                    module.ContainerEntrypointError,
                    "^container_secret_source_invalid$",
                ),
            ):
                module._expected_source_path(str(outside), "formowl_database_dsn")

            (source / "formowl_database_dsn").unlink()
            _write_secret(source / "formowl_signing_key_current", b"key")
            invalid_manifests = (
                {
                    "version": 1,
                    "keys": [
                        {
                            "kid": "current",
                            "private_key_file": str(source / "formowl_signing_key_current"),
                            "active": True,
                            "unknown": True,
                        }
                    ],
                },
                {
                    "version": 1,
                    "keys": [
                        {
                            "kid": "duplicate",
                            "private_key_file": str(source / "formowl_signing_key_current"),
                            "active": True,
                        },
                        {
                            "kid": "duplicate",
                            "private_key_file": str(source / "formowl_signing_key_current"),
                            "active": False,
                            "verify_until": "2030-01-01T00:00:00+00:00",
                        },
                    ],
                },
            )
            for index, manifest in enumerate(invalid_manifests):
                with self.subTest(index=index):
                    manifest_path = source / "formowl_signing_key_set"
                    manifest_path.unlink(missing_ok=True)
                    _write_secret(manifest_path, json.dumps(manifest).encode("utf-8"))
                    for path in tuple(staged.iterdir()):
                        path.unlink()
                    with (
                        mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                        mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                        mock.patch.object(
                            module,
                            "_ALLOWED_SIGNING_KEY_SOURCES",
                            {source / "formowl_signing_key_current"},
                        ),
                        mock.patch.object(module, "SERVICE_UID", os.getuid()),
                        mock.patch.object(module, "SERVICE_GID", os.getgid()),
                        mock.patch.object(module.os, "chown"),
                        mock.patch.object(module.os, "fchown"),
                        self.assertRaisesRegex(
                            module.ContainerEntrypointError,
                            "^container_signing_manifest_invalid$",
                        ),
                    ):
                        module._prepare_staging_root()
                        module._stage_signing_manifest(manifest_path)

    def test_command_gating_keeps_init_secrets_direct_and_connected_commands_staged(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_commands")
        self.assertFalse(module._requires_connected_secrets(["init-secrets"], {}))
        self.assertTrue(module._requires_connected_secrets(["migrate"], {}))
        self.assertTrue(module._requires_connected_secrets(["preflight"], {}))
        self.assertTrue(module._requires_connected_secrets(["serve"], {}))
        self.assertFalse(module._requires_connected_secrets(["python", "probe.py"], {}))
        self.assertTrue(
            module._requires_connected_secrets(
                ["python", "probe.py"],
                {"FORMOWL_CONTAINER_STAGE_SECRETS": "1"},
            )
        )
        self.assertEqual(
            module._resolved_command(["init-secrets", "--output-dir", "/secrets"]),
            [
                "formowl-connected-mcp",
                "init-secrets",
                "--output-dir",
                "/secrets",
            ],
        )

    def test_staged_file_mode_is_fixed_before_ownership_changes(self) -> None:
        module = _load_module("formowl_container_entrypoint_staged_order")
        events: list[str] = []
        with (
            mock.patch.object(module.os, "open", return_value=17),
            mock.patch.object(
                module.os,
                "fchmod",
                side_effect=lambda *_args: events.append("chmod"),
            ),
            mock.patch.object(
                module.os,
                "fchown",
                side_effect=lambda *_args: events.append("chown"),
            ),
            mock.patch.object(module.os, "write", return_value=7),
            mock.patch.object(module.os, "fsync"),
            mock.patch.object(module.os, "close"),
        ):
            module._write_staged_secret("fixture", b"payload")

        self.assertEqual(events, ["chmod", "chown"])

    def test_partial_staged_secret_write_is_removed(self) -> None:
        module = _load_module("formowl_container_entrypoint_partial_write")
        failure_points = ("partial_write", "fchown", "fsync", "close")

        for failure_point in failure_points:
            with (
                self.subTest(failure_point=failure_point),
                tempfile.TemporaryDirectory(
                    prefix=f"formowl-entrypoint-{failure_point}-",
                    dir=tempfile.gettempdir(),
                ) as value,
            ):
                staged = Path(value)
                private_sentinel = "private-staged-secret-sentinel"
                private_detail = f"{private_sentinel}:{failure_point}:{staged}:google-secret"
                real_close = module.os.close
                close_descriptors: list[int] = []

                def fail_first_close(descriptor: int) -> None:
                    close_descriptors.append(descriptor)
                    if len(close_descriptors) == 1:
                        raise OSError(private_detail)
                    real_close(descriptor)

                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(module, "STAGED_SECRET_ROOT", staged))
                    stack.enter_context(mock.patch.object(module, "SERVICE_UID", os.getuid()))
                    stack.enter_context(mock.patch.object(module, "SERVICE_GID", os.getgid()))
                    if failure_point == "partial_write":
                        stack.enter_context(mock.patch.object(module.os, "fchown"))
                        stack.enter_context(
                            mock.patch.object(
                                module.os,
                                "write",
                                side_effect=(2, OSError(private_detail)),
                            )
                        )
                    elif failure_point == "fchown":
                        stack.enter_context(
                            mock.patch.object(
                                module.os,
                                "fchown",
                                side_effect=OSError(private_detail),
                            )
                        )
                    elif failure_point == "fsync":
                        stack.enter_context(mock.patch.object(module.os, "fchown"))
                        stack.enter_context(
                            mock.patch.object(
                                module.os,
                                "fsync",
                                side_effect=OSError(private_detail),
                            )
                        )
                    else:
                        stack.enter_context(mock.patch.object(module.os, "fchown"))
                        stack.enter_context(
                            mock.patch.object(
                                module.os,
                                "close",
                                side_effect=fail_first_close,
                            )
                        )
                    caught = stack.enter_context(
                        self.assertRaisesRegex(
                            module.ContainerEntrypointError,
                            "^container_secret_stage_failed$",
                        )
                    )
                    module._write_staged_secret("fixture", b"payload")

                public_text = str(caught.exception)
                self.assertEqual(public_text, "container_secret_stage_failed")
                self.assertNotIn(private_sentinel, public_text)
                self.assertNotIn(private_detail, public_text)
                self.assertNotIn(str(staged), public_text)
                self.assertNotIn("google-secret", public_text)
                self.assertEqual(tuple(staged.iterdir()), ())
                if failure_point == "close":
                    self.assertEqual(len(close_descriptors), 2)

                with (
                    mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                    mock.patch.object(module.os, "fchown"),
                ):
                    retry_path = module._write_staged_secret("fixture", b"retry")
                self.assertEqual(retry_path.read_bytes(), b"retry")
                retry_path.unlink()

    def test_public_partial_write_failure_rolls_back_and_retry_succeeds(self) -> None:
        module = _load_module("formowl_container_entrypoint_partial_stage_rollback")
        with tempfile.TemporaryDirectory(
            prefix="formowl-entrypoint-partial-stage-",
            dir=tempfile.gettempdir(),
        ) as value:
            source, staged, environ = _configured_secret_fixture(Path(value))
            _write_signing_manifest(
                source,
                [
                    {
                        "kid": "current",
                        "private_key_file": str(source / "formowl_signing_key_current"),
                        "active": True,
                    }
                ],
            )
            original_environ = dict(environ)
            original_secrets = _secret_tree_snapshot(source)
            real_write = module.os.write
            write_calls = 0

            def fail_after_partial_write(descriptor: int, value: bytes) -> int:
                nonlocal write_calls
                write_calls += 1
                if write_calls == 1:
                    return real_write(descriptor, value[:2])
                raise OSError("private partial write detail")

            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {source / "formowl_signing_key_current"},
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "chown"),
                mock.patch.object(module.os, "fchown"),
                mock.patch.object(
                    module.os,
                    "write",
                    side_effect=fail_after_partial_write,
                ),
                self.assertRaisesRegex(
                    module.ContainerEntrypointError,
                    "^container_secret_stage_failed$",
                ) as caught,
            ):
                module.stage_configured_secrets(environ)

            self.assertEqual(str(caught.exception), "container_secret_stage_failed")
            self.assertEqual(environ, original_environ)
            self.assertEqual(tuple(staged.iterdir()), ())
            self.assertEqual(_secret_tree_snapshot(source), original_secrets)
            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {source / "formowl_signing_key_current"},
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "chown"),
                mock.patch.object(module.os, "fchown"),
            ):
                self.assertEqual(module.stage_configured_secrets(environ), 4)

    def test_source_descriptor_close_failure_is_safe_rollback_and_retry_succeeds(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_source_close_rollback")
        with tempfile.TemporaryDirectory(
            prefix="formowl-entrypoint-source-close-",
            dir=tempfile.gettempdir(),
        ) as value:
            source, staged, environ = _configured_secret_fixture(Path(value))
            _write_signing_manifest(
                source,
                [
                    {
                        "kid": "current",
                        "private_key_file": str(source / "formowl_signing_key_current"),
                        "active": True,
                    }
                ],
            )
            original_environ = tuple(
                (name.encode("utf-8"), item.encode("utf-8")) for name, item in environ.items()
            )
            original_secrets = _secret_tree_snapshot(source)
            private_close_detail = (
                f"private source descriptor close detail: {source}; google-secret"
            )
            real_open = module.os.open
            real_close = module.os.close
            source_descriptors: set[int] = set()
            close_failure_injected = False

            def track_source_descriptor(
                path: str | os.PathLike[str],
                flags: int,
                mode: int = 0o777,
            ) -> int:
                descriptor = real_open(path, flags, mode)
                if Path(path).parent == source:
                    source_descriptors.add(descriptor)
                return descriptor

            def fail_first_source_descriptor_close(descriptor: int) -> None:
                nonlocal close_failure_injected
                if descriptor in source_descriptors and not close_failure_injected:
                    close_failure_injected = True
                    source_descriptors.remove(descriptor)
                    real_close(descriptor)
                    raise OSError(private_close_detail)
                source_descriptors.discard(descriptor)
                real_close(descriptor)

            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {source / "formowl_signing_key_current"},
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "open", side_effect=track_source_descriptor),
                mock.patch.object(
                    module.os,
                    "close",
                    side_effect=fail_first_source_descriptor_close,
                ),
                mock.patch.object(module.os, "chown"),
                mock.patch.object(module.os, "fchown"),
                self.assertRaisesRegex(
                    module.ContainerEntrypointError,
                    "^container_secret_source_unavailable$",
                ) as caught,
            ):
                module.stage_configured_secrets(environ)

            self.assertTrue(close_failure_injected)
            self.assertEqual(caught.exception.code, "container_secret_source_unavailable")
            self.assertEqual(str(caught.exception), "container_secret_source_unavailable")
            self.assertEqual(
                tuple(
                    (name.encode("utf-8"), item.encode("utf-8")) for name, item in environ.items()
                ),
                original_environ,
            )
            self.assertEqual(tuple(staged.iterdir()), ())
            self.assertEqual(_secret_tree_snapshot(source), original_secrets)
            for private_detail in (
                private_close_detail,
                str(source),
                "postgresql://fixture",
                "google-secret",
            ):
                self.assertNotIn(private_detail, str(caught.exception))

            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {source / "formowl_signing_key_current"},
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "chown"),
                mock.patch.object(module.os, "fchown"),
            ):
                self.assertEqual(module.stage_configured_secrets(environ), 4)

    def test_late_invalid_signing_manifest_rolls_back_stage_and_environment(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_manifest_rollback")
        with tempfile.TemporaryDirectory(
            prefix="formowl-entrypoint-manifest-rollback-",
            dir=tempfile.gettempdir(),
        ) as value:
            source, staged, environ = _configured_secret_fixture(Path(value))
            invalid_keys = [
                {
                    "kid": "current",
                    "private_key_file": str(source / "formowl_signing_key_current"),
                    "active": True,
                },
                {
                    "kid": "previous",
                    "private_key_file": str(source / "formowl_signing_key_previous"),
                    "active": True,
                },
            ]
            _write_signing_manifest(source, invalid_keys)
            original_environ = dict(environ)
            original_secrets = _secret_tree_snapshot(source)
            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {
                        source / "formowl_signing_key_current",
                        source / "formowl_signing_key_previous",
                    },
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "chown"),
                mock.patch.object(module.os, "fchown"),
                self.assertRaisesRegex(
                    module.ContainerEntrypointError,
                    "^container_signing_manifest_invalid$",
                ) as caught,
            ):
                module.stage_configured_secrets(environ)

            self.assertEqual(str(caught.exception), "container_signing_manifest_invalid")
            self.assertEqual(environ, original_environ)
            self.assertEqual(tuple(staged.iterdir()), ())
            self.assertEqual(_secret_tree_snapshot(source), original_secrets)
            for private_detail in (
                str(source),
                "postgresql://fixture",
                "google-secret",
                "current-key",
            ):
                self.assertNotIn(private_detail, str(caught.exception))

            corrected_keys = [
                invalid_keys[0],
                {
                    **invalid_keys[1],
                    "active": False,
                    "verify_until": "2030-01-01T00:00:00+00:00",
                },
            ]
            _write_signing_manifest(source, corrected_keys)
            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {
                        source / "formowl_signing_key_current",
                        source / "formowl_signing_key_previous",
                    },
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "chown"),
                mock.patch.object(module.os, "fchown"),
            ):
                self.assertEqual(module.stage_configured_secrets(environ), 4)

    def test_public_final_ownership_failure_rolls_back_and_retry_succeeds(self) -> None:
        module = _load_module("formowl_container_entrypoint_ownership_rollback")
        with tempfile.TemporaryDirectory(
            prefix="formowl-entrypoint-ownership-rollback-",
            dir=tempfile.gettempdir(),
        ) as value:
            source, staged, environ = _configured_secret_fixture(Path(value))
            _write_signing_manifest(
                source,
                [
                    {
                        "kid": "current",
                        "private_key_file": str(source / "formowl_signing_key_current"),
                        "active": True,
                    }
                ],
            )
            original_environ = dict(environ)
            original_secrets = _secret_tree_snapshot(source)
            chown_calls = 0

            def fail_final_ownership(*_args: object) -> None:
                nonlocal chown_calls
                chown_calls += 1
                if chown_calls == 2:
                    raise PermissionError("private ownership detail")

            stderr = io.StringIO()
            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {source / "formowl_signing_key_current"},
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "environ", environ),
                mock.patch.object(module.os, "geteuid", return_value=0),
                mock.patch.object(module.os, "chown", side_effect=fail_final_ownership),
                mock.patch.object(module.os, "fchown"),
                mock.patch.object(module.sys, "stderr", stderr),
            ):
                self.assertEqual(module.main(["serve"]), 1)
                self.assertEqual(
                    stderr.getvalue(),
                    '{"error":"container_secret_stage_failed","status":"error"}\n',
                )
                self.assertEqual(environ, original_environ)
                self.assertEqual(tuple(staged.iterdir()), ())
                self.assertEqual(_secret_tree_snapshot(source), original_secrets)
                self.assertEqual(module.stage_configured_secrets(environ), 4)

            self.assertEqual(environ["FORMOWL_TEST_SENTINEL"], "unchanged")
            for private_detail in (
                str(source),
                "postgresql://fixture",
                "google-secret",
                "private ownership detail",
            ):
                self.assertNotIn(private_detail, stderr.getvalue())
            self.assertNotEqual(environ, original_environ)
            self.assertEqual(_secret_tree_snapshot(source), original_secrets)

    def test_main_root_connected_serve_stages_drops_and_execs_with_rewritten_environment(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_main_success")

        class SuccessfulExec(Exception):
            pass

        with tempfile.TemporaryDirectory(
            prefix="formowl-entrypoint-",
            dir=tempfile.gettempdir(),
        ) as value:
            root = Path(value)
            source, staged, environ = _configured_secret_fixture(root)
            _write_signing_manifest(
                source,
                [
                    {
                        "kid": "current",
                        "private_key_file": str(source / "formowl_signing_key_current"),
                        "active": True,
                    }
                ],
            )
            original_environ = dict(environ)
            original_secrets = _secret_tree_snapshot(source)
            events: list[str] = []
            staged_counts: list[int] = []
            exec_calls: list[tuple[str, list[str], dict[str, str]]] = []
            real_stage_configured_secrets = module.stage_configured_secrets

            def stage_and_record(candidate_environ: dict[str, str]) -> int:
                staged_count = real_stage_configured_secrets(candidate_environ)
                staged_counts.append(staged_count)
                events.append("stage")
                return staged_count

            def drop_and_record() -> None:
                events.append("drop")

            def exec_and_record(
                executable: str,
                arguments: list[str],
                candidate_environ: dict[str, str],
            ) -> None:
                exec_calls.append((executable, list(arguments), candidate_environ))
                events.append("exec")
                raise SuccessfulExec

            stderr = io.StringIO()
            with (
                mock.patch.object(module, "SECRET_SOURCE_ROOT", source),
                mock.patch.object(module, "STAGED_SECRET_ROOT", staged),
                mock.patch.object(
                    module,
                    "_ALLOWED_SIGNING_KEY_SOURCES",
                    {source / "formowl_signing_key_current"},
                ),
                mock.patch.object(module, "SERVICE_UID", os.getuid()),
                mock.patch.object(module, "SERVICE_GID", os.getgid()),
                mock.patch.object(module.os, "environ", environ),
                mock.patch.object(module.os, "geteuid", return_value=0),
                mock.patch.object(module.os, "chown"),
                mock.patch.object(module.os, "fchown"),
                mock.patch.object(
                    module,
                    "stage_configured_secrets",
                    side_effect=stage_and_record,
                ),
                mock.patch.object(module, "_drop_privileges", side_effect=drop_and_record),
                mock.patch.object(module.os, "execvpe", side_effect=exec_and_record),
                mock.patch.object(module.sys, "stderr", stderr),
            ):
                with self.assertRaises(SuccessfulExec):
                    module.main(["serve"])

            expected_secret_paths = {
                "FORMOWL_DATABASE_DSN_FILE": staged / "formowl_database_dsn",
                "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": staged / "formowl_google_client_secret",
                "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE": staged / "formowl_state_encryption_key",
                "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE": staged / "formowl_signing_key_set",
            }
            self.assertEqual(events, ["stage", "drop", "exec"])
            self.assertEqual(staged_counts, [4])
            self.assertEqual(len(exec_calls), 1)
            executable, arguments, exec_environ = exec_calls[0]
            self.assertEqual(executable, "formowl-connected-mcp")
            self.assertEqual(arguments, ["formowl-connected-mcp", "serve"])
            self.assertIs(exec_environ, environ)
            self.assertEqual(set(environ), set(original_environ))
            self.assertEqual(environ["FORMOWL_TEST_SENTINEL"], "unchanged")
            for environment_name, expected_path in expected_secret_paths.items():
                self.assertEqual(environ[environment_name], str(expected_path))
                self.assertEqual(expected_path.parent, staged)

            staged_paths = sorted(staged.iterdir())
            self.assertEqual(
                staged_paths,
                sorted(
                    (
                        staged / "formowl_database_dsn",
                        staged / "formowl_google_client_secret",
                        staged / "formowl_signing_key_0",
                        staged / "formowl_signing_key_set",
                        staged / "formowl_state_encryption_key",
                    )
                ),
            )
            self.assertTrue(
                all(stat.S_IMODE(path.stat().st_mode) == 0o400 for path in staged_paths)
            )
            self.assertEqual(
                (staged / "formowl_database_dsn").read_bytes(),
                b"postgresql://fixture\n",
            )
            self.assertEqual(
                (staged / "formowl_google_client_secret").read_bytes(),
                b"google-secret\n",
            )
            self.assertEqual(
                (staged / "formowl_state_encryption_key").read_bytes(),
                b"state-key\n",
            )
            self.assertEqual(
                (staged / "formowl_signing_key_0").read_bytes(),
                b"current-key\n",
            )
            self.assertEqual(
                json.loads((staged / "formowl_signing_key_set").read_text(encoding="utf-8")),
                {
                    "keys": [
                        {
                            "active": True,
                            "kid": "current",
                            "private_key_file": str(staged / "formowl_signing_key_0"),
                        }
                    ],
                    "version": 1,
                },
            )
            self.assertEqual(_secret_tree_snapshot(source), original_secrets)
            self.assertEqual(stderr.getvalue(), "")

    def test_privilege_drop_verifies_uid_groups_caps_no_new_privs_and_no_regain(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_drop")
        events: list[tuple[object, ...]] = []

        class FakeLibc:
            @staticmethod
            def prctl(*args):
                events.append(("prctl", *args))
                return 0

        status = "\n".join(
            (
                "CapInh:\t0000000000000000",
                "CapPrm:\t0000000000000000",
                "CapEff:\t0000000000000000",
                "CapBnd:\t0000000000000000",
                "CapAmb:\t0000000000000000",
                "NoNewPrivs:\t1",
            )
        )
        capability_limit_path = mock.Mock()
        capability_limit_path.read_text.return_value = "2\n"
        process_status_path = mock.Mock()
        process_status_path.read_text.return_value = status
        with (
            mock.patch.object(module.ctypes, "CDLL", return_value=FakeLibc()),
            mock.patch.object(
                module,
                "_CAP_LAST_CAP_PATH",
                capability_limit_path,
            ),
            mock.patch.object(
                module.os,
                "setgroups",
                side_effect=lambda groups: events.append(("setgroups", groups)),
            ) as setgroups,
            mock.patch.object(
                module.os,
                "setgid",
                side_effect=lambda gid: events.append(("setgid", gid)),
            ) as setgid,
            mock.patch.object(
                module.os,
                "setuid",
                side_effect=lambda uid: events.append(("setuid", uid)),
            ) as setuid,
            mock.patch.object(module.os, "umask") as umask,
            mock.patch.object(module.os, "geteuid", return_value=module.SERVICE_UID),
            mock.patch.object(module.os, "getegid", return_value=module.SERVICE_GID),
            mock.patch.object(module.os, "getgroups", return_value=[]),
            mock.patch.object(module.os, "seteuid", side_effect=PermissionError),
            mock.patch.object(
                module,
                "_PROCESS_STATUS_PATH",
                process_status_path,
            ),
        ):
            module._drop_privileges()

        self.assertEqual(
            events,
            [
                ("prctl", module._PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0),
                ("prctl", module._PR_CAPBSET_DROP, 0, 0, 0, 0),
                ("prctl", module._PR_CAPBSET_DROP, 1, 0, 0, 0),
                ("prctl", module._PR_CAPBSET_DROP, 2, 0, 0, 0),
                ("setgroups", []),
                ("setgid", module.SERVICE_GID),
                ("setuid", module.SERVICE_UID),
            ],
        )
        setgroups.assert_called_once_with([])
        setgid.assert_called_once_with(module.SERVICE_GID)
        setuid.assert_called_once_with(module.SERVICE_UID)
        umask.assert_called_once_with(0o077)

    def test_capability_probe_control_noops_only_bounding_drop_and_fails_closed(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_probe_control")
        probe = _load_capability_probe()
        delegated_calls: list[tuple[int, ...]] = []

        class FakeLibc:
            @staticmethod
            def prctl(*args):
                delegated_calls.append(args)
                return 0

        status = "\n".join(
            (
                "CapInh:\t0000000000000000",
                "CapPrm:\t0000000000000000",
                "CapEff:\t0000000000000000",
                "CapBnd:\t0000000000000001",
                "CapAmb:\t0000000000000000",
                "NoNewPrivs:\t1",
            )
        )
        capability_limit_path = mock.Mock()
        capability_limit_path.read_text.return_value = "2\n"
        process_status_path = mock.Mock()
        process_status_path.read_text.return_value = status
        with (
            mock.patch.object(module.ctypes, "CDLL", return_value=FakeLibc()),
            probe.pre_fix_bounding_drop_control(module) as control,
            mock.patch.object(
                module,
                "_CAP_LAST_CAP_PATH",
                capability_limit_path,
            ),
            mock.patch.object(module.os, "setgroups") as setgroups,
            mock.patch.object(module.os, "setgid") as setgid,
            mock.patch.object(module.os, "setuid") as setuid,
            mock.patch.object(module.os, "umask"),
            mock.patch.object(module.os, "geteuid", return_value=module.SERVICE_UID),
            mock.patch.object(module.os, "getegid", return_value=module.SERVICE_GID),
            mock.patch.object(module.os, "getgroups", return_value=[]),
            mock.patch.object(
                module,
                "_PROCESS_STATUS_PATH",
                process_status_path,
            ),
            self.assertRaises(module.ContainerEntrypointError) as raised,
        ):
            module._drop_privileges()

        self.assertEqual(raised.exception.code, "container_privilege_drop_unverified")
        self.assertEqual(
            delegated_calls,
            [(module._PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)],
        )
        self.assertEqual(control.bounding_drop_calls, [0, 1, 2])
        setgroups.assert_called_once_with([])
        setgid.assert_called_once_with(module.SERVICE_GID)
        setuid.assert_called_once_with(module.SERVICE_UID)

    def test_privilege_drop_bounding_set_failure_is_generic_and_stops_before_uid_drop(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_bounding_failure")
        calls: list[tuple[int, ...]] = []

        class FakeLibc:
            @staticmethod
            def prctl(*args):
                calls.append(args)
                if args[:2] == (module._PR_CAPBSET_DROP, 1):
                    return -1
                return 0

        capability_limit_path = mock.Mock()
        capability_limit_path.read_text.return_value = "2\n"
        with (
            mock.patch.object(module.ctypes, "CDLL", return_value=FakeLibc()),
            mock.patch.object(
                module,
                "_CAP_LAST_CAP_PATH",
                capability_limit_path,
            ),
            mock.patch.object(module.ctypes, "get_errno", return_value=1),
            mock.patch.object(module.os, "setgroups") as setgroups,
            mock.patch.object(module.os, "setgid") as setgid,
            mock.patch.object(module.os, "setuid") as setuid,
            self.assertRaises(module.ContainerEntrypointError) as raised,
        ):
            module._drop_privileges()

        self.assertEqual(raised.exception.code, "container_privilege_drop_failed")
        self.assertEqual(str(raised.exception), "container_privilege_drop_failed")
        self.assertEqual(
            calls,
            [
                (module._PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0),
                (module._PR_CAPBSET_DROP, 0, 0, 0, 0),
                (module._PR_CAPBSET_DROP, 1, 0, 0, 0),
            ],
        )
        setgroups.assert_not_called()
        setgid.assert_not_called()
        setuid.assert_not_called()

    def test_privilege_drop_rejects_nonzero_bounding_or_ambient_capabilities(
        self,
    ) -> None:
        module = _load_module("formowl_container_entrypoint_capability_verification")

        class FakeLibc:
            @staticmethod
            def prctl(*_args):
                return 0

        for capability_field in ("CapBnd", "CapAmb"):
            with self.subTest(capability_field=capability_field):
                status_values = {
                    "CapInh": "0000000000000000",
                    "CapPrm": "0000000000000000",
                    "CapEff": "0000000000000000",
                    "CapBnd": "0000000000000000",
                    "CapAmb": "0000000000000000",
                    "NoNewPrivs": "1",
                }
                status_values[capability_field] = "0000000000000001"
                status = "\n".join(f"{key}:\t{value}" for key, value in status_values.items())
                capability_limit_path = mock.Mock()
                capability_limit_path.read_text.return_value = "2\n"
                process_status_path = mock.Mock()
                process_status_path.read_text.return_value = status
                with (
                    mock.patch.object(module.ctypes, "CDLL", return_value=FakeLibc()),
                    mock.patch.object(
                        module,
                        "_CAP_LAST_CAP_PATH",
                        capability_limit_path,
                    ),
                    mock.patch.object(module.os, "setgroups"),
                    mock.patch.object(module.os, "setgid"),
                    mock.patch.object(module.os, "setuid"),
                    mock.patch.object(module.os, "umask"),
                    mock.patch.object(
                        module.os,
                        "geteuid",
                        return_value=module.SERVICE_UID,
                    ),
                    mock.patch.object(
                        module.os,
                        "getegid",
                        return_value=module.SERVICE_GID,
                    ),
                    mock.patch.object(module.os, "getgroups", return_value=[]),
                    mock.patch.object(
                        module,
                        "_PROCESS_STATUS_PATH",
                        process_status_path,
                    ),
                    self.assertRaises(module.ContainerEntrypointError) as raised,
                ):
                    module._drop_privileges()

                self.assertEqual(
                    raised.exception.code,
                    "container_privilege_drop_unverified",
                )

    def test_public_failure_is_bounded(self) -> None:
        module = _load_module("formowl_container_entrypoint_failure")
        unsafe = module.ContainerEntrypointError("private/path/secret")
        self.assertEqual(unsafe.code, "container_entrypoint_failed")
        self.assertEqual(str(unsafe), "container_entrypoint_failed")
        self.assertNotIn("private", str(unsafe))
        stderr = io.StringIO()
        with (
            mock.patch.object(module.os, "geteuid", return_value=0),
            mock.patch.object(module, "_requires_connected_secrets", return_value=True),
            mock.patch.object(
                module,
                "stage_configured_secrets",
                side_effect=module.ContainerEntrypointError("container_secret_source_unavailable"),
            ),
            mock.patch.object(module.sys, "stderr", stderr),
        ):
            result = module.main(["serve"])

        self.assertEqual(result, 1)
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {"error": "container_secret_source_unavailable", "status": "error"},
        )
        self.assertNotIn("/run/secrets", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
