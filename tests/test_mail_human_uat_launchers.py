from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import _paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _load_launcher_module() -> types.ModuleType:
    """Load the launcher with its expensive runtime dependencies replaced."""

    import formowl_mail  # noqa: F401

    evaluator = types.ModuleType("formowl_evaluator")
    evaluator.load_or_rebuild_may_mail_evidence_bundle = object()

    http = types.ModuleType("formowl_mail.human_uat_http")
    http.MailHumanUatHttpConfig = object()
    http.MailHumanUatService = object()
    http.create_mail_human_uat_http_server = object()

    orchestrator = types.ModuleType("formowl_mail.human_uat_orchestrator")
    orchestrator.CodexAppServerConversationModel = object()
    orchestrator.CodexAppServerStdioTransport = object()
    orchestrator.build_codex_app_server_proxy_command = object()
    orchestrator.load_semantic_ontology_context = object()

    query = types.ModuleType("formowl_mail.query")
    query.MailEvidenceQueryGateway = object()

    module_name = "_mail_human_uat_launcher_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "scripts" / "mail_human_uat.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(
        sys.modules,
        {
            "formowl_evaluator": evaluator,
            "formowl_mail.human_uat_http": http,
            "formowl_mail.human_uat_orchestrator": orchestrator,
            "formowl_mail.query": query,
        },
    ):
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
                    "load_semantic_ontology_context",
                    return_value=ontology_context,
                ) as load_ontology,
                mock.patch.object(launcher, "_require_semantic_dual_runtime_api"),
                mock.patch.object(
                    launcher,
                    "load_or_rebuild_may_mail_evidence_bundle",
                    return_value=bundle,
                ),
                mock.patch.object(launcher, "MailEvidenceQueryGateway", _Gateway),
                mock.patch.object(launcher, "CodexAppServerStdioTransport", _Transport),
                mock.patch.object(
                    launcher,
                    "CodexAppServerConversationModel",
                    _ConversationModel,
                ),
                mock.patch.object(launcher, "MailHumanUatHttpConfig", _Config),
                mock.patch.object(launcher, "MailHumanUatService", _Service),
                mock.patch.object(
                    launcher,
                    "create_mail_human_uat_http_server",
                    return_value=server,
                ),
                mock.patch.object(
                    launcher,
                    "build_codex_app_server_proxy_command",
                    side_effect=lambda *, socket_path: ("proxy", str(socket_path)),
                ),
            ):
                self.assertEqual(launcher.main(), 0)

        load_ontology.assert_called_once_with(ontology)
        self.assertEqual(len(constructed_transports), 2)
        private_transport, web_transport = constructed_transports
        self.assertIs(
            private_transport.kwargs["allow_public_web_search"],
            False,
        )
        self.assertTrue(web_transport.kwargs["allow_public_web_search"])
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
