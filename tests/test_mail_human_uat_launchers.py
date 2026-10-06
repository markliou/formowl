from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

import _paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _load_launcher_module() -> types.ModuleType:
    """Load the launcher without importing any FormOwl runtime dependency."""

    module_name = "_mail_human_uat_launcher_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "scripts" / "mail_human_uat.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_engine_module() -> types.ModuleType:
    module_name = "_mail_human_uat_codex_engine_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "scripts" / "mail_human_uat_codex_engine.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _launcher_args(**overrides: Path) -> argparse.Namespace:
    values: dict[str, Path] = {
        "private_codex_runtime_state_dir": Path("/private-codex-state"),
        "web_codex_runtime_state_dir": Path("/web-codex-state"),
        "private_codex_socket": Path("/run/formowl/private.sock"),
        "web_codex_socket": Path("/run/formowl/web.sock"),
        "state_dir": Path("/uat-state"),
        "corpus_root": Path("/private-corpus"),
        "bundle_cache": Path("/private-cache/bundle.json"),
        "private_manifest": Path("/private-corpus/manifest.json"),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class MailHumanUatLauncherTests(unittest.TestCase):
    def test_document_first_launcher_wires_one_private_sidecar_and_one_mcp(
        self,
    ) -> None:
        launcher = _load_launcher_module()
        observed: dict[str, object] = {}

        class _Transport:
            def __init__(self, **kwargs):
                observed["transport"] = kwargs

        class _ConversationModel:
            model_name = "codex:test"

            def __init__(self, transport, **kwargs):
                observed["conversation"] = (transport, kwargs)
                self.closed = False

            def close(self):
                self.closed = True

        class _Config:
            def __init__(self, **kwargs):
                observed["config"] = kwargs

        class _Service:
            def __init__(self, config):
                observed["service"] = config

        class _Server:
            server_address = ("127.0.0.1", 8088)

            def serve_forever(self):
                raise KeyboardInterrupt()

            def server_close(self):
                observed["server_closed"] = True

        dependencies = types.SimpleNamespace(
            CodexAppServerStdioTransport=_Transport,
            CodexAppServerConversationModel=_ConversationModel,
            MailHumanUatHttpConfig=_Config,
            MailHumanUatService=_Service,
            create_mail_human_uat_http_server=lambda *_args: _Server(),
            build_codex_app_server_proxy_command=(
                lambda *, socket_path: ("proxy", str(socket_path))
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                mock.patch.object(
                    launcher.sys,
                    "argv",
                    [
                        "mail_human_uat.py",
                        "--document-first",
                        "--document-mcp-url",
                        "http://127.0.0.1:8091/mcp",
                        "--state-dir",
                        str(root / "uat-state"),
                        "--private-codex-socket",
                        str(root / "run" / "private.sock"),
                        "--private-codex-runtime-state-dir",
                        str(root / "private-codex-state"),
                    ],
                ),
                mock.patch.object(
                    launcher,
                    "_load_document_first_dependencies",
                    return_value=dependencies,
                ),
                mock.patch.object(
                    launcher,
                    "_load_legacy_dependencies",
                    side_effect=AssertionError("document-first must not load legacy runtime"),
                ),
            ):
                self.assertEqual(launcher.main(), 0)

        self.assertFalse(observed["transport"]["allow_public_web_search"])
        self.assertEqual(
            observed["transport"]["runtime_workspace"],
            root / "private-codex-state" / "codex-workspace",
        )
        self.assertEqual(observed["config"]["bundle"], None)
        self.assertEqual(
            observed["config"]["document_mcp_url"],
            "http://127.0.0.1:8091/mcp",
        )
        self.assertNotIn("diagnostic_mcp_url", observed["config"])
        self.assertTrue(observed["server_closed"])

    def test_launcher_help_fresh_subprocess_imports_no_formowl_runtime(self) -> None:
        script = textwrap.dedent(
            f"""
            import builtins
            import runpy
            import sys

            forbidden = (
                "formowl_evaluator",
                "formowl_graph",
                "formowl_mail.evidence",
                "formowl_mail.human_uat_orchestrator",
                "formowl_mail.human_uat_upload",
                "formowl_mail.public_search_adapter",
                "formowl_mail.query",
                "formowl_ingestion.extractors.mail.pst",
            )
            original_import = builtins.__import__

            def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name in forbidden or name.startswith(
                    tuple(prefix + "." for prefix in forbidden)
                ):
                    raise AssertionError("forbidden launcher import: " + name)
                return original_import(name, globals, locals, fromlist, level)

            builtins.__import__ = guarded_import
            sys.argv = ["mail_human_uat.py", "--help"]
            try:
                runpy.run_path(
                    {str(ROOT / "scripts" / "mail_human_uat.py")!r},
                    run_name="__main__",
                )
            except SystemExit as exc:
                if exc.code not in (None, 0):
                    raise
            loaded = sorted(
                name
                for name in sys.modules
                if name in forbidden
                or name.startswith(tuple(prefix + "." for prefix in forbidden))
            )
            if loaded:
                raise AssertionError("forbidden launcher modules loaded: " + repr(loaded))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--document-first", completed.stdout)
        self.assertIn("--document-mcp-url", completed.stdout)

    def test_document_first_http_runtime_fresh_subprocess_imports_no_legacy_stack(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temporary = Path(temp_dir)
            state_dir = temporary / "state"
            script = textwrap.dedent(
                f"""
                import builtins
                import importlib.util
                import sys

                forbidden = (
                    "formowl_evaluator",
                    "formowl_graph",
                    "formowl_mail.evidence",
                    "formowl_mail.human_uat_orchestrator",
                    "formowl_mail.human_uat_upload",
                    "formowl_mail.public_search_adapter",
                    "formowl_mail.query",
                    "formowl_ingestion.extractors.mail.pst",
                )
                original_import = builtins.__import__

                def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
                    if name in forbidden or name.startswith(
                        tuple(prefix + "." for prefix in forbidden)
                    ):
                        raise AssertionError("forbidden document-first import: " + name)
                    return original_import(name, globals, locals, fromlist, level)

                builtins.__import__ = guarded_import
                launcher_spec = importlib.util.spec_from_file_location(
                    "_document_first_import_audit_launcher",
                    {str(ROOT / "scripts" / "mail_human_uat.py")!r},
                )
                if launcher_spec is None or launcher_spec.loader is None:
                    raise AssertionError("launcher import spec is unavailable")
                launcher = importlib.util.module_from_spec(launcher_spec)
                launcher_spec.loader.exec_module(launcher)
                launcher._install_document_first_package_namespace()
                from formowl_mail.human_uat_http import (
                    MailHumanUatHttpConfig,
                    MailHumanUatService,
                )

                class DocumentClient:
                    def read_authorized_documents(self, *, request):
                        raise AssertionError("import audit must not call the MCP")

                service = MailHumanUatService(
                    MailHumanUatHttpConfig(
                        bundle=None,
                        state_dir={str(state_dir)!r},
                    ),
                    document_mcp_client=DocumentClient(),
                )
                health = service.health()
                if health["surface"] != "document_first_human_uat":
                    raise AssertionError("document-first service did not initialize")
                loaded = sorted(
                    name
                    for name in sys.modules
                    if name in forbidden
                    or name.startswith(tuple(prefix + "." for prefix in forbidden))
                )
                if loaded:
                    raise AssertionError(
                        "forbidden document-first modules loaded: " + repr(loaded)
                    )
                """
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(ROOT / "python"),
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_document_first_dependency_loader_uses_minimal_namespace_without_legacy_modules(
        self,
    ) -> None:
        script = textwrap.dedent(
            f"""
            import importlib.util
            import sys

            launcher_spec = importlib.util.spec_from_file_location(
                "_document_first_dependency_import_audit",
                {str(ROOT / "scripts" / "mail_human_uat.py")!r},
            )
            if launcher_spec is None or launcher_spec.loader is None:
                raise AssertionError("launcher import spec is unavailable")
            launcher = importlib.util.module_from_spec(launcher_spec)
            launcher_spec.loader.exec_module(launcher)
            dependencies = launcher._load_document_first_dependencies()
            if not hasattr(dependencies, "CodexAppServerConversationModel"):
                raise AssertionError("document-first dependencies did not load")
            package = sys.modules.get("formowl_mail")
            if package is None or getattr(package, "__file__", None) is not None:
                raise AssertionError("document-first executed a package initializer")
            forbidden = (
                "formowl_mail.bundle",
                "formowl_mail.evidence",
                "formowl_mail.human_uat_upload",
                "formowl_mail.public_search_adapter",
                "formowl_mail.query",
            )
            loaded = sorted(name for name in forbidden if name in sys.modules)
            if loaded:
                raise AssertionError(
                    "document-first loaded legacy modules: " + repr(loaded)
                )
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(ROOT / "python"),
            },
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_dual_runtime_isolation_derives_distinct_attested_workspaces(self) -> None:
        launcher = _load_launcher_module()

        (
            private_workspace,
            web_workspace,
            web_proxy_home,
            web_proxy_workspace,
        ) = launcher._validate_dual_runtime_isolation(_launcher_args())

        self.assertEqual(private_workspace, Path("/private-codex-state/codex-workspace"))
        self.assertEqual(web_workspace, Path("/web-codex-state/codex-workspace"))
        self.assertEqual(
            web_proxy_home,
            Path("/web-codex-state/web-codex-proxy-home"),
        )
        self.assertEqual(
            web_proxy_workspace,
            Path("/web-codex-state/web-codex-proxy-workspace"),
        )
        self.assertNotEqual(private_workspace, web_workspace)
        for web_path in (web_workspace, web_proxy_home, web_proxy_workspace):
            for protected_path in (
                Path("/private-corpus"),
                Path("/private-cache/bundle.json"),
                Path("/private-corpus/manifest.json"),
                Path("/uat-state"),
                Path("/private-codex-state"),
                Path("/uat-state/codex-proxy-home"),
                Path("/uat-state/codex-proxy-workspace"),
            ):
                self.assertFalse(launcher._paths_overlap(web_path, protected_path))

    def test_dual_runtime_isolation_rejects_same_socket_and_public_private_overlap(
        self,
    ) -> None:
        launcher = _load_launcher_module()

        with self.assertRaisesRegex(ValueError, "socket paths must differ"):
            launcher._validate_dual_runtime_isolation(
                _launcher_args(web_codex_socket=Path("/run/formowl/private.sock"))
            )
        with self.assertRaisesRegex(ValueError, "must not overlap corpus root"):
            launcher._validate_dual_runtime_isolation(
                _launcher_args(web_codex_runtime_state_dir=Path("/private-corpus/web"))
            )

    def test_launcher_wires_distinct_private_and_web_transports_with_ontology(
        self,
    ) -> None:
        launcher = _load_launcher_module()
        constructed_transports: list[object] = []
        observed: dict[str, object] = {}

        class _Transport:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.closed = False
                constructed_transports.append(self)

            def close(self):
                self.closed = True

        class _ConversationModel:
            model_name = "codex:test"

            def __init__(self, private_transport, **kwargs):
                self.private_transport = private_transport
                self.kwargs = kwargs
                self.closed = False
                observed["conversation"] = self

            def close(self):
                self.closed = True
                self.private_transport.close()
                self.kwargs["web_grounding_transport"].close()

        class _Gateway:
            index_build_mode = "synthetic"
            index_worker_count = 1
            index_build_elapsed_ms = 1

            def __init__(self, bundles, *, index_worker_count):
                observed["gateway"] = (tuple(bundles), index_worker_count)

        class _Config:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                observed["config"] = self

        class _Service:
            def __init__(self, config, *, base_gateway):
                observed["service"] = (config, base_gateway)

        class _Server:
            server_address = ("127.0.0.1", 8088)

            def __init__(self):
                self.closed = False

            def serve_forever(self):
                raise KeyboardInterrupt()

            def server_close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = root / "private-corpus"
            corpus.mkdir()
            manifest = corpus / "manifest.json"
            manifest.write_text(json.dumps({}), encoding="utf-8")
            ontology = root / "public-ontology.json"
            ontology.write_text("{}", encoding="utf-8")
            server = _Server()
            bundle = types.SimpleNamespace(messages=())
            ontology_context = object()
            load_ontology = mock.Mock(return_value=ontology_context)
            dependencies = types.SimpleNamespace(
                CodexAppServerStdioTransport=_Transport,
                CodexAppServerConversationModel=_ConversationModel,
                MailEvidenceQueryGateway=_Gateway,
                MailHumanUatHttpConfig=_Config,
                MailHumanUatService=_Service,
                build_codex_app_server_proxy_command=(
                    lambda *, socket_path: ("proxy", str(socket_path))
                ),
                create_mail_human_uat_http_server=lambda *_args: server,
                load_or_rebuild_may_mail_evidence_bundle=lambda *_args, **_kwargs: bundle,
                load_semantic_ontology_context=load_ontology,
            )

            with (
                mock.patch.object(
                    launcher.sys,
                    "argv",
                    [
                        "mail_human_uat.py",
                        "--corpus-root",
                        str(corpus),
                        "--private-manifest",
                        str(manifest),
                        "--bundle-cache",
                        str(root / "private-cache" / "bundle.json"),
                        "--state-dir",
                        str(root / "uat-state"),
                        "--private-codex-socket",
                        str(root / "run" / "private.sock"),
                        "--web-codex-socket",
                        str(root / "run" / "web.sock"),
                        "--private-codex-runtime-state-dir",
                        str(root / "private-codex-state"),
                        "--web-codex-runtime-state-dir",
                        str(root / "web-codex-state"),
                        "--semantic-ontology",
                        str(ontology),
                        "--diagnostic-mcp-url",
                        "http://127.0.0.1:8090/mcp",
                    ],
                ),
                mock.patch.object(
                    launcher,
                    "_load_legacy_dependencies",
                    return_value=dependencies,
                ),
                mock.patch.object(
                    launcher,
                    "_load_document_first_dependencies",
                    side_effect=AssertionError("legacy mode must not load document-only deps"),
                ),
                mock.patch.object(launcher, "_require_semantic_dual_runtime_api"),
            ):
                self.assertEqual(launcher.main(), 0)

        load_ontology.assert_called_once_with(ontology)
        self.assertEqual(len(constructed_transports), 2)
        private_transport, web_transport = constructed_transports
        self.assertIs(
            private_transport.kwargs["allow_public_web_search"],
            False,
        )
        self.assertIs(
            web_transport.kwargs["allow_public_web_search"],
            True,
        )
        self.assertEqual(
            private_transport.kwargs["cwd"],
            root / "uat-state" / "codex-proxy-workspace",
        )
        self.assertEqual(
            private_transport.kwargs["codex_home"],
            root / "uat-state" / "codex-proxy-home",
        )
        self.assertEqual(
            web_transport.kwargs["cwd"],
            root / "web-codex-state" / "web-codex-proxy-workspace",
        )
        self.assertEqual(
            web_transport.kwargs["codex_home"],
            root / "web-codex-state" / "web-codex-proxy-home",
        )
        self.assertNotEqual(
            private_transport.kwargs["runtime_workspace"],
            web_transport.kwargs["runtime_workspace"],
        )
        for web_proxy_path in (
            web_transport.kwargs["cwd"],
            web_transport.kwargs["codex_home"],
            web_transport.kwargs["runtime_workspace"],
        ):
            for protected_path in (
                corpus,
                manifest,
                root / "private-cache" / "bundle.json",
                root / "uat-state",
                root / "private-codex-state",
                private_transport.kwargs["cwd"],
                private_transport.kwargs["codex_home"],
            ):
                self.assertFalse(launcher._paths_overlap(web_proxy_path, protected_path))
        conversation = observed["conversation"]
        self.assertIs(conversation.private_transport, private_transport)
        self.assertIs(conversation.kwargs["web_grounding_transport"], web_transport)
        self.assertIs(conversation.kwargs["ontology_context"], ontology_context)
        self.assertEqual(
            observed["config"].kwargs["diagnostic_mcp_url"],
            "http://127.0.0.1:8090/mcp",
        )
        self.assertTrue(private_transport.closed)
        self.assertTrue(web_transport.closed)
        self.assertTrue(conversation.closed)
        self.assertTrue(server.closed)

    def test_engine_roles_bind_web_search_to_only_the_public_runtime(self) -> None:
        engine = _load_engine_module()

        self.assertFalse(engine._role_allows_public_web_search("private-planner"))
        self.assertTrue(engine._role_allows_public_web_search("public-web-grounder"))
        with self.assertRaisesRegex(ValueError, "runtime role is invalid"):
            engine._role_allows_public_web_search("unknown")

    def test_engine_serve_passes_role_specific_web_capability_to_runtime(self) -> None:
        engine = _load_engine_module()
        state = Path("/isolated-web-state")
        socket = Path("/run/formowl/web.sock")
        paths = types.SimpleNamespace(codex_home=Path("/isolated-web-state/codex-home"))
        observed: dict[str, object] = {}

        class _ExecIntercepted(Exception):
            pass

        def intercept_execvpe(command, args, environment):
            observed["command"] = command
            observed["args"] = tuple(args)
            observed["environment"] = dict(environment)
            raise _ExecIntercepted()

        with (
            mock.patch.object(
                engine.sys,
                "argv",
                [
                    "mail_human_uat_codex_engine.py",
                    "serve",
                    "--state-dir",
                    str(state),
                    "--runtime-role",
                    "public-web-grounder",
                    "--socket-path",
                    str(socket),
                ],
            ),
            mock.patch.object(engine.os, "geteuid", return_value=65532),
            mock.patch.object(engine, "_require_dual_runtime_api"),
            mock.patch.object(
                engine,
                "validate_codex_runtime_state",
                return_value=paths,
            ) as validate,
            mock.patch.object(engine, "_prepare_socket_path", return_value=socket),
            mock.patch.object(
                engine,
                "build_hardened_codex_app_server_command",
                return_value=("codex", "app-server"),
            ) as build,
            mock.patch.object(
                engine,
                "build_codex_runtime_environment",
                return_value={"CODEX_HOME": str(paths.codex_home)},
            ),
            mock.patch.object(engine.os, "execvpe", side_effect=intercept_execvpe),
        ):
            with self.assertRaises(_ExecIntercepted):
                engine.main()

        validate.assert_called_once_with(state, allow_public_web_search=True)
        build.assert_called_once_with(
            "codex",
            listen_url=f"unix://{socket}",
            allow_public_web_search=True,
        )
        self.assertEqual(observed["args"], ("codex", "app-server"))


if __name__ == "__main__":
    unittest.main()
