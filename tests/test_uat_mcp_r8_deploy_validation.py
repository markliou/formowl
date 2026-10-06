from __future__ import annotations

import ast
from contextlib import redirect_stderr, redirect_stdout
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DEPLOY_SCRIPT = _REPOSITORY_ROOT / "docs" / "recovery" / "2026-08-10" / "uat-mcp-r8-deploy.sh"
_PACKAGE_INIT_SHIM = (
    _REPOSITORY_ROOT / "docs" / "recovery" / "2026-08-10" / "document-uat-formowl-mail-init.py"
)
_PRODUCTION_MAIL_INIT_RELATIVE = "python/formowl_mail/__init__.py"
_READONLY_PROBE_IMAGE_ENV = "FORMOWL_UAT_READONLY_PROBE_IMAGE"
_CONTAINER_STATE_PATH = "/formowl/runtime/codex-state"
_CONTAINER_SOCKET_PATH = "/formowl/run/codex/app-server.sock"
_CONTAINER_ENGINE_PATH = "/opt/formowl/scripts/mail_human_uat_codex_engine.py"
_CONTAINER_PYTHON_ROOT = "/opt/formowl/python"
_ENGINE_CONTAINER_OVERLAY_FILES = (
    "python/formowl_contract/__init__.py",
    "python/formowl_contract/structured_intent.py",
    "python/formowl_mail/_guards.py",
    "python/formowl_mail/document_uat_mcp.py",
    "python/formowl_mail/human_uat_orchestrator.py",
    "scripts/mail_human_uat_codex_engine.py",
)
_WORKTREE_FIXTURE_FILES = (
    "python/formowl_contract/__init__.py",
    "python/formowl_contract/structured_intent.py",
    "python/formowl_mail/_guards.py",
    "python/formowl_mail/document_uat_mcp.py",
    "python/formowl_mail/human_uat_http.py",
    "python/formowl_mail/human_uat_orchestrator.py",
    "scripts/mail_human_uat.py",
    "scripts/mail_human_uat_codex_engine.py",
)


def _engine_container_mount_args() -> list[str]:
    args = [
        "--mount",
        (
            f"type=bind,src={_PACKAGE_INIT_SHIM},"
            "dst=/opt/formowl/python/formowl_mail/__init__.py,readonly"
        ),
    ]
    for relative_path in _ENGINE_CONTAINER_OVERLAY_FILES:
        source = _REPOSITORY_ROOT / relative_path
        if relative_path.startswith("python/"):
            destination = f"/opt/formowl/python/{relative_path.removeprefix('python/')}"
        else:
            destination = f"/opt/formowl/scripts/{relative_path.removeprefix('scripts/')}"
        args.extend(
            [
                "--mount",
                f"type=bind,src={source},dst={destination},readonly",
            ]
        )
    return args


def _metadata_snapshot(root: Path) -> dict[str, tuple[int, int, int, int, int, int]]:
    result: dict[str, tuple[int, int, int, int, int, int]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        metadata = path.lstat()
        name = "." if path == root else str(path.relative_to(root))
        result[name] = (
            stat.S_IMODE(metadata.st_mode),
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
    return result


def _load_codex_engine_module() -> types.ModuleType:
    module_name = "_uat_mcp_r8_codex_engine_test"
    python_root = _REPOSITORY_ROOT / "python"
    package_root = python_root / "formowl_mail"
    package_spec = importlib.util.spec_from_file_location(
        "formowl_mail",
        _PACKAGE_INIT_SHIM,
        submodule_search_locations=[str(package_root)],
    )
    assert package_spec is not None and package_spec.loader is not None
    saved_modules = {
        name: loaded
        for name, loaded in sys.modules.items()
        if name == "formowl_mail" or name.startswith("formowl_mail.")
    }
    original_path = list(sys.path)
    for name in saved_modules:
        sys.modules.pop(name, None)
    try:
        sys.path.insert(0, str(python_root))
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["formowl_mail"] = package
        package_spec.loader.exec_module(package)
        spec = importlib.util.spec_from_file_location(
            module_name,
            _REPOSITORY_ROOT / "scripts" / "mail_human_uat_codex_engine.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = original_path
        for imported_name in tuple(sys.modules):
            if imported_name == "formowl_mail" or imported_name.startswith("formowl_mail."):
                sys.modules.pop(imported_name, None)
        sys.modules.update(saved_modules)


def _dry_run(
    *,
    command: object | None = None,
    launcher_replacements: tuple[tuple[str, str], ...] = (),
    omitted_worktree_file: str | None = None,
    omit_package_init_shim: bool = False,
    run_as_unprivileged: bool = True,
    web_bind_address: str | None = None,
    host_port: str | None = None,
    mcp_host_port: str | None = None,
    assigned_ipv4_addresses: tuple[str, ...] | None = None,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        root.chmod(0o755)
        deploy_script = root / "uat-mcp-r8-deploy.sh"
        shutil.copyfile(_DEPLOY_SCRIPT, deploy_script)
        deploy_script.chmod(0o755)
        if not omit_package_init_shim:
            package_init_shim = root / _PACKAGE_INIT_SHIM.name
            shutil.copyfile(_PACKAGE_INIT_SHIM, package_init_shim)
            package_init_shim.chmod(0o644)
        private_root = root / "private"
        bridge_root = root / "bridge"
        runtime_root = root / "runtime"
        worktree_root = root / "worktree"
        for path in (
            private_root,
            bridge_root,
            runtime_root,
            worktree_root,
        ):
            path.mkdir(mode=0o755)
        for relative_path in _WORKTREE_FIXTURE_FILES:
            if relative_path == omitted_worktree_file:
                continue
            source = _REPOSITORY_ROOT / relative_path
            destination = worktree_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            content = source.read_text(encoding="utf-8")
            if relative_path == "scripts/mail_human_uat.py":
                for old, new in launcher_replacements:
                    content = content.replace(old, new)
            destination.write_text(content, encoding="utf-8")
            destination.chmod(0o644)
        auth_cache = root / "auth-cache.json"
        auth_cache.write_text("{}\n", encoding="utf-8")
        auth_cache.chmod(0o644)
        document_command = root / "document-command.json"
        document_command.write_text(
            json.dumps(
                command
                if command is not None
                else [
                    "python3",
                    "/opt/formowl/python/formowl_mail/document_uat_mcp.py",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8090",
                    "--snapshot",
                    "/formowl/bridge/authorized-document-snapshot.json",
                    "--expected-sha256",
                    "sha256:" + ("0" * 64),
                    "--workspace-id",
                    "workspace-test",
                    "--actor-user-id",
                    "actor-test",
                    "--session-id",
                    "session-test",
                ]
            ),
            encoding="utf-8",
        )
        document_command.chmod(0o644)
        invocation = [
            "bash",
            str(deploy_script),
            "dry-run",
            "--image",
            "formowl-test:latest",
            "--private-root",
            str(private_root),
            "--bridge-root",
            str(bridge_root),
            "--worktree-root",
            str(worktree_root),
            "--auth-cache",
            str(auth_cache),
            "--runtime-root",
            str(runtime_root),
            "--document-mcp-command-json",
            str(document_command),
        ]
        if web_bind_address is not None:
            invocation.extend(["--web-bind-address", web_bind_address])
        if host_port is not None:
            invocation.extend(["--host-port", host_port])
        if mcp_host_port is not None:
            invocation.extend(["--mcp-host-port", mcp_host_port])
        environment = None
        if assigned_ipv4_addresses is not None:
            fake_bin = root / "fake-bin"
            fake_bin.mkdir(mode=0o755)
            ip_command = fake_bin / "ip"
            address_lines = "".join(
                f"{index}: eth{index}    inet {address} scope global eth{index}\n"
                for index, address in enumerate(assigned_ipv4_addresses, start=1)
            )
            ip_command.write_text(
                "#!/bin/sh\n"
                '[ "$*" = "-o -4 address show" ] || exit 64\n'
                "cat <<'EOF'\n"
                f"{address_lines}"
                "EOF\n",
                encoding="utf-8",
            )
            ip_command.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            }
        privilege_args: dict[str, object] = {}
        if run_as_unprivileged and os.geteuid() == 0:
            privilege_args = {
                "extra_groups": (),
                "group": 65534,
                "user": 65534,
            }
        return subprocess.run(
            invocation,
            check=False,
            capture_output=True,
            env=environment,
            text=True,
            **privilege_args,
        )


class UatMcpR8DocumentFirstDeployValidationTests(unittest.TestCase):
    def test_document_first_dry_run_declares_exact_three_component_topology(self) -> None:
        result = _dry_run()

        self.assertEqual(result.returncode, 0, result.stderr)
        expected_lines = {
            "FORMOWL_DOCUMENT_UAT_CONFIG_VALID",
            "containers=document-mcp,codex-sidecar,uat-web",
            "codex_sidecar_count=1",
            "document_mcp_count=1",
            "document_mcp_access=read-only",
            "codex_to_mcp_route=single",
            "ontology_runtime=disabled",
            "public_search_runtime=disabled",
            "public_search_network=none",
            "second_codex_runtime=disabled",
            "pst_parser_invocation=none",
            "uat_mode=document-first",
            "uat_codex_socket_option=--private-codex-socket",
            "uat_document_mcp_option=--document-mcp-url",
            "uat_mail_bundle=disabled",
            "uat_upload=disabled",
            "model_readiness_probe=authenticated_model_only_no_mcp",
            "model_readiness_state_validation=readonly_no_metadata_mutation",
            "model_readiness_proxy_state=ephemeral_tmpfs",
            "document_mcp_overlay=formowl_mail/document_uat_mcp.py",
            "document_mcp_guard_overlay=formowl_mail/_guards.py",
            "formowl_mail_package_init=recovery-no-eager-import-shim",
            ("document_mcp_entrypoint=" "/opt/formowl/python/formowl_mail/document_uat_mcp.py"),
            "web_publish_bind_address=127.0.0.1",
            "web_publish_endpoint=127.0.0.1:8088",
            "document_mcp_publish_bind_address=127.0.0.1",
            "document_mcp_publish_endpoint=127.0.0.1:8091",
            "codex_publish=none",
            "cdp_publish=none",
        }
        self.assertTrue(expected_lines.issubset(set(result.stdout.splitlines())))

    def test_web_publish_bind_is_explicit_and_other_runtime_surfaces_remain_loopback(self) -> None:
        result = _dry_run(
            web_bind_address="192.168.71.211",
            host_port="8089",
            mcp_host_port="8093",
            assigned_ipv4_addresses=("192.168.71.211/24",),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output_lines = set(result.stdout.splitlines())
        self.assertIn("web_publish_bind_address=192.168.71.211", output_lines)
        self.assertIn("web_publish_endpoint=192.168.71.211:8089", output_lines)
        self.assertIn("document_mcp_publish_bind_address=127.0.0.1", output_lines)
        self.assertIn("document_mcp_publish_endpoint=127.0.0.1:8093", output_lines)
        self.assertIn("codex_publish=none", output_lines)
        self.assertIn("cdp_publish=none", output_lines)

        script = _DEPLOY_SCRIPT.read_text(encoding="utf-8")
        document_mcp_body = script[
            script.index("start_document_mcp() {") : script.index("\nstart_uat_http() {")
        ]
        uat_http_body = script[
            script.index("start_uat_http() {") : script.index("\nwait_for_running_container() {")
        ]
        sidecar_body = script[
            script.index("start_sidecar() {") : script.index("\nstart_document_mcp() {")
        ]

        self.assertIn(
            '--publish "127.0.0.1:${MCP_HOST_PORT}:8090"',
            document_mcp_body,
        )
        self.assertIn(
            '--publish "${WEB_BIND_ADDRESS}:${HOST_PORT}:8088"',
            uat_http_body,
        )
        self.assertNotIn("--publish", sidecar_body)
        self.assertNotIn("9222", script)

    def test_nonloopback_web_bind_must_be_exactly_assigned_before_start_mutations(self) -> None:
        assigned_addresses = ("127.0.0.1/8", "192.168.71.211/24")

        for address in ("192.168.71.212", "10.255.255.254"):
            with self.subTest(address=address):
                result = _dry_run(
                    web_bind_address=address,
                    assigned_ipv4_addresses=assigned_addresses,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "web bind address is not assigned to a host IPv4 interface",
                    result.stderr,
                )

        script = _DEPLOY_SCRIPT.read_text(encoding="utf-8")
        validation_body = script[
            script.index("validate_configuration() {") : script.index("\nprint_dry_run() {")
        ]
        start_case = script[
            script.index("    start)\n", script.index("main() {")) : script.index(
                "\n      ;;",
                script.index("    start)\n", script.index("main() {")),
            )
        ]

        self.assertIn(
            'require_web_bind_address_assigned "$WEB_BIND_ADDRESS"',
            validation_body,
        )
        self.assertIn("validate_configuration\n      start", start_case)

    def test_web_publish_bind_rejects_wildcard_non_ipv4_and_public_addresses(self) -> None:
        invalid_addresses = (
            "0.0.0.0",
            "::",
            "formowl.local",
            "8.8.8.8",
        )

        for address in invalid_addresses:
            with self.subTest(address=address):
                result = _dry_run(web_bind_address=address)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("web bind address", result.stderr)

    def test_launcher_uses_document_first_arguments_and_no_legacy_dependencies(self) -> None:
        script = _DEPLOY_SCRIPT.read_text(encoding="utf-8")
        shim_mount = '"${UAT_PACKAGE_INIT_SHIM_MOUNT_ARGS[@]}"'
        overlay_body = script[
            script.index("readonly WORKTREE_PYTHON_OVERLAY_FILES=(") : script.index(
                "\n)",
                script.index("readonly WORKTREE_PYTHON_OVERLAY_FILES=("),
            )
        ]
        overlay_files = tuple(
            line.strip().removeprefix('"').removesuffix('"')
            for line in overlay_body.splitlines()[1:]
            if line.strip()
        )
        init_sidecar_body = script[
            script.index("init_sidecar_state() {") : script.index("\nstart_sidecar() {")
        ]
        sidecar_body = script[
            script.index("start_sidecar() {") : script.index("\nstart_document_mcp() {")
        ]
        document_mcp_body = script[
            script.index("start_document_mcp() {") : script.index("\nstart_uat_http() {")
        ]
        uat_http_body = script[
            script.index("start_uat_http() {") : script.index("\nwait_for_running_container() {")
        ]
        readiness_probe_body = script[
            script.index("run_model_readiness_probe() {") : script.index(
                "\nwait_for_http_health() {"
            )
        ]

        self.assertIn("--document-first", script)
        self.assertIn("--document-mcp-url", script)
        self.assertIn("--private-codex-socket", script)
        self.assertIn("--private-codex-runtime-state-dir", script)
        self.assertNotIn("--semantic-ontology", script)
        self.assertNotIn("--public-search-socket", script)
        self.assertNotIn("--web-codex-socket", script)
        self.assertNotIn("--web-codex-runtime-state-dir", script)
        self.assertNotIn("--corpus-root", script)
        self.assertNotIn("--private-manifest", script)
        self.assertNotIn("--bundle-cache", script)
        self.assertNotIn("tokenizer", script.casefold())
        self.assertNotIn("answer_item", script)
        self.assertNotIn("fingerprint", script)
        self.assertNotIn("oracle", script.casefold())
        self.assertNotIn("diagnostic_mcp", script)
        self.assertNotIn("--diagnostic-command-json", script)
        self.assertNotIn("--runtime-tools-root", script)
        self.assertNotIn(
            "${WORKTREE_PYTHON_HOST}/formowl_mail/__init__.py",
            script,
        )
        self.assertIn(
            (
                "type=bind,src=${FORMOWL_MAIL_INIT_SHIM_HOST},"
                "dst=${FORMOWL_MAIL_INIT_CONTAINER_PATH},readonly"
            ),
            script,
        )
        self.assertEqual(
            overlay_files,
            (
                "formowl_contract/__init__.py",
                "formowl_contract/structured_intent.py",
                "formowl_mail/_guards.py",
                "formowl_mail/document_uat_mcp.py",
                "formowl_mail/human_uat_http.py",
                "formowl_mail/human_uat_orchestrator.py",
            ),
        )
        self.assertNotIn("formowl_mail/public_search_adapter.py", overlay_files)
        self.assertIn(shim_mount, init_sidecar_body)
        self.assertIn(shim_mount, sidecar_body)
        self.assertIn(shim_mount, readiness_probe_body)
        self.assertNotIn(shim_mount, document_mcp_body)
        self.assertNotIn(shim_mount, uat_http_body)
        self.assertEqual(script.count(shim_mount), 3)
        self.assertNotIn("--index-workers", uat_http_body)
        self.assertNotIn("PUBLIC_SEARCH_NETWORK=", script)
        self.assertNotIn("start_public_search", script)
        self.assertIn(
            '"type=bind,src=${WORKTREE_PYTHON_HOST}/${relative_path},'
            'dst=${WORKTREE_PYTHON_CONTAINER_PATH}/${relative_path},readonly"',
            script,
        )
        self.assertIn(
            "src=${CODEX_STATE_HOST},dst=${CODEX_STATE_CONTAINER_PATH},readonly",
            script,
        )
        self.assertEqual(script.count("start_sidecar\n"), 1)
        self.assertEqual(script.count("start_document_mcp\n"), 1)
        self.assertEqual(script.count("start_uat_http\n"), 1)
        shim_source = _PACKAGE_INIT_SHIM.read_text(encoding="utf-8")
        ast.parse(shim_source)
        self.assertNotIn("from .", shim_source)
        self.assertNotIn("sys.modules", shim_source)
        self.assertNotIn("MailEvidenceBundle", shim_source)
        self.assertNotIn("MailEvidenceQueryGateway", shim_source)
        self.assertNotIn("__all__", shim_source)
        self.assertNotIn(
            _PRODUCTION_MAIL_INIT_RELATIVE,
            _WORKTREE_FIXTURE_FILES,
        )
        self.assertNotIn(
            "${WORKTREE_ROOT}/python/formowl_mail/__init__.py",
            script,
        )

    def test_authenticated_model_probe_failed_turn_emits_no_ready_marker(self) -> None:
        engine = _load_codex_engine_module()
        paths = types.SimpleNamespace(
            codex_home=Path("/isolated-state/codex-home"),
            workspace=Path("/isolated-state/codex-workspace"),
        )
        observed: dict[str, object] = {}

        class _FailingTransport:
            def __init__(self, **kwargs):
                observed["transport"] = kwargs
                observed["closed"] = False
                observed["deleted"] = []

            def start_thread(self, **kwargs):
                observed["thread"] = kwargs
                return types.SimpleNamespace(thread_id="readiness-thread")

            def run_turn(self, **kwargs):
                observed["turn"] = kwargs
                raise RuntimeError("Codex app-server turn failed")

            def delete_thread(self, thread_id, **kwargs):
                observed["deleted"].append((thread_id, kwargs))

            def close(self):
                observed["closed"] = True

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                engine.sys,
                "argv",
                [
                    "mail_human_uat_codex_engine.py",
                    "probe",
                    "--state-dir",
                    "/isolated-state",
                    "--runtime-role",
                    "private-planner",
                    "--socket-path",
                    "/run/formowl/app-server.sock",
                ],
            ),
            mock.patch.object(engine.os, "geteuid", return_value=65532),
            mock.patch.object(engine, "_require_dual_runtime_api"),
            mock.patch.object(
                engine,
                "_validate_codex_runtime_state_readonly",
                return_value=paths,
            ),
            mock.patch.object(
                engine,
                "build_codex_app_server_proxy_command",
                return_value=("python3", "proxy.py"),
            ),
            mock.patch.object(
                engine,
                "CodexAppServerStdioTransport",
                _FailingTransport,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as raised:
                engine.main()

        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn(engine._MODEL_READINESS_MARKER, stdout.getvalue())
        self.assertEqual(observed["thread"]["dynamic_tools"], ())
        self.assertEqual(observed["turn"]["additional_context"], {})
        self.assertEqual(observed["deleted"][0][0], "readiness-thread")
        self.assertTrue(observed["closed"])

    def test_probe_uses_real_readonly_state_bind_without_metadata_mutation(self) -> None:
        image = os.environ.get(_READONLY_PROBE_IMAGE_ENV)
        if not image:
            self.skipTest(f"{_READONLY_PROBE_IMAGE_ENV} is not configured")
        docker_socket = Path("/var/run/docker.sock")
        if shutil.which("docker") is None or not docker_socket.is_socket():
            self.skipTest("Docker daemon is unavailable")

        engine_metadata = (_REPOSITORY_ROOT / "scripts" / "mail_human_uat_codex_engine.py").stat()
        runtime_uid = engine_metadata.st_uid
        runtime_gid = engine_metadata.st_gid
        if runtime_uid == 0:
            self.skipTest("readonly regression requires a non-root source owner")
        runtime_user = f"{runtime_uid}:{runtime_gid}"
        with tempfile.TemporaryDirectory(
            prefix="formowl-readonly-probe-regression-",
            dir="/tmp",
        ) as directory:
            root = Path(directory)
            state = root / "state"
            socket_dir = root / "socket"
            state.mkdir(mode=0o700)
            socket_dir.mkdir(mode=0o700)
            if os.geteuid() == 0:
                os.chown(state, runtime_uid, runtime_gid)
                os.chown(socket_dir, runtime_uid, runtime_gid)

            common = [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--user",
                runtime_user,
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=32m",
                *_engine_container_mount_args(),
                "-e",
                f"PYTHONPATH={_CONTAINER_PYTHON_ROOT}:/opt/formowl/scripts",
            ]
            auth_cache = json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "OPENAI_API_KEY": None,
                    "tokens": {
                        "access_token": "readonly-regression-access",
                        "account_id": "readonly-regression-account",
                        "id_token": "readonly-regression-id",
                        "refresh_token": "readonly-regression-refresh",
                    },
                }
            )
            init_result = subprocess.run(
                [
                    *common,
                    "-i",
                    "--mount",
                    f"type=bind,src={state},dst={_CONTAINER_STATE_PATH}",
                    image,
                    "python3",
                    _CONTAINER_ENGINE_PATH,
                    "init",
                    "--state-dir",
                    _CONTAINER_STATE_PATH,
                    "--runtime-role",
                    "private-planner",
                    "--chatgpt-auth-stdin",
                ],
                input=auth_cache,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)
            before = _metadata_snapshot(state)

            socket_path = socket_dir / "app-server.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            socket_path.chmod(0o666)
            listener.listen(1)
            listener.settimeout(10)
            accepted = threading.Event()
            server_errors: list[str] = []

            def close_after_handshake() -> None:
                try:
                    connection, _ = listener.accept()
                    accepted.set()
                    with connection:
                        connection.settimeout(5)
                        connection.recv(4096)
                except (OSError, TimeoutError) as exc:
                    server_errors.append(type(exc).__name__)

            server = threading.Thread(target=close_after_handshake, daemon=True)
            server.start()
            try:
                probe_result = subprocess.run(
                    [
                        *common,
                        "--mount",
                        (f"type=bind,src={state},dst={_CONTAINER_STATE_PATH}," "readonly"),
                        "--mount",
                        (f"type=bind,src={socket_dir}," "dst=/formowl/run/codex,readonly"),
                        "-e",
                        "TMPDIR=/tmp",
                        image,
                        "python3",
                        _CONTAINER_ENGINE_PATH,
                        "probe",
                        "--state-dir",
                        _CONTAINER_STATE_PATH,
                        "--runtime-role",
                        "private-planner",
                        "--socket-path",
                        _CONTAINER_SOCKET_PATH,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            finally:
                listener.close()
                server.join(timeout=12)

            after = _metadata_snapshot(state)
            self.assertEqual(probe_result.returncode, 2, probe_result.stderr)
            self.assertTrue(accepted.is_set(), probe_result.stderr)
            self.assertEqual(server_errors, [])
            self.assertNotIn("FORMOWL_CODEX_UAT_MODEL_READY", probe_result.stdout)
            self.assertNotIn("Read-only file system", probe_result.stderr)
            self.assertNotIn("Errno 30", probe_result.stderr)
            self.assertNotIn("PermissionError", probe_result.stderr)
            self.assertEqual(after, before)

    def test_start_probes_after_socket_before_downstream_and_ready(self) -> None:
        script = _DEPLOY_SCRIPT.read_text(encoding="utf-8")
        start_body = script[script.index("start() {") : script.index("\nstop() {")]
        expected_order = (
            "init_sidecar_state\n",
            "start_sidecar\n",
            'wait_for_running_container "$CODEX_CONTAINER"\n',
            'wait_for_socket "$CODEX_SOCKET_DIR_HOST/app-server.sock"\n',
            "run_model_readiness_probe\n",
            "start_document_mcp\n",
            "start_uat_http\n",
            "FORMOWL_DOCUMENT_UAT_READY",
        )
        positions = [start_body.index(item) for item in expected_order]

        self.assertEqual(positions, sorted(positions))
        self.assertIn("trap 'retain_failed_start_for_diagnostics", start_body)
        self.assertLess(
            start_body.index("run_model_readiness_probe\n"),
            start_body.index("trap - EXIT"),
        )
        probe_body = script[
            script.index("run_model_readiness_probe() {") : script.index(
                "\nwait_for_http_health() {"
            )
        ]
        self.assertIn("--network none", probe_body)
        self.assertIn("-e TMPDIR=/tmp", probe_body)
        self.assertIn('"$CODEX_ENGINE_CONTAINER_PATH" probe', probe_body)
        self.assertIn("--runtime-role private-planner", probe_body)
        self.assertNotIn("DOCUMENT_MCP_COMMAND", probe_body)
        self.assertNotIn("start_document_mcp", probe_body)

    def test_package_init_shim_supports_only_sidecar_orchestrator_import(self) -> None:
        package_name = "document_uat_formowl_mail_shim_test"
        python_root = _REPOSITORY_ROOT / "python"
        package_root = python_root / "formowl_mail"
        spec = importlib.util.spec_from_file_location(
            package_name,
            _PACKAGE_INIT_SHIM,
            submodule_search_locations=[str(package_root)],
        )
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        original_path = list(sys.path)
        sys.path.insert(0, str(python_root))
        sys.modules[package_name] = module
        try:
            spec.loader.exec_module(module)
            orchestrator = importlib.import_module(f"{package_name}.human_uat_orchestrator")
            self.assertTrue(hasattr(orchestrator, "CodexAppServerConversationModel"))
            self.assertFalse(hasattr(module, "MailEvidenceBundle"))
            self.assertFalse(hasattr(module, "MailEvidenceQueryGateway"))
            self.assertNotIn(f"{package_name}.query", sys.modules)
            self.assertNotIn(f"{package_name}.public_search_adapter", sys.modules)
        finally:
            sys.path[:] = original_path
            for imported_name in tuple(sys.modules):
                if imported_name == package_name or imported_name.startswith(f"{package_name}."):
                    sys.modules.pop(imported_name, None)

    def test_launcher_preserves_health_checks_stop_and_failed_start_rollback(self) -> None:
        script = _DEPLOY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'wait_for_http_health "$MCP_CONTAINER" "http://127.0.0.1:8090/health"',
            script,
        )
        self.assertIn(
            'wait_for_http_health "$UAT_CONTAINER" "http://127.0.0.1:8088/"',
            script,
        )
        self.assertIn(
            'for container in "$UAT_CONTAINER" "$CODEX_CONTAINER" "$MCP_CONTAINER"',
            script,
        )
        self.assertIn("stop >/dev/null 2>&1 || true", script)
        self.assertIn("rollback=completed", script)

    def test_document_command_and_launcher_seams_fail_closed(self) -> None:
        shell_command = _dry_run(command=["bash", "-c", "echo no"])
        module_command = _dry_run(command=["python3", "-m", "formowl_mail.document_uat_mcp"])
        arbitrary_script = _dry_run(command=["python3", "/opt/formowl/scripts/document_mcp.py"])
        missing_document_overlay = _dry_run(
            omitted_worktree_file="python/formowl_mail/document_uat_mcp.py"
        )
        missing_guard_overlay = _dry_run(omitted_worktree_file="python/formowl_mail/_guards.py")
        missing_package_init_shim = _dry_run(omit_package_init_shim=True)
        no_document_mode = _dry_run(
            launcher_replacements=(('"--document-first"', '"--removed-mode"'),)
        )

        self.assertNotEqual(shell_command.returncode, 0)
        self.assertIn("must not use a shell", shell_command.stderr)
        self.assertNotEqual(module_command.returncode, 0)
        self.assertIn(
            ("must invoke python3 " "/opt/formowl/python/formowl_mail/document_uat_mcp.py"),
            module_command.stderr,
        )
        self.assertNotEqual(arbitrary_script.returncode, 0)
        self.assertIn(
            ("must invoke python3 " "/opt/formowl/python/formowl_mail/document_uat_mcp.py"),
            arbitrary_script.stderr,
        )
        self.assertNotEqual(missing_document_overlay.returncode, 0)
        self.assertIn("worktree Python overlay", missing_document_overlay.stderr)
        self.assertNotEqual(missing_guard_overlay.returncode, 0)
        self.assertIn("worktree Python overlay", missing_guard_overlay.stderr)
        self.assertNotEqual(missing_package_init_shim.returncode, 0)
        self.assertIn(
            "document UAT package-init shim",
            missing_package_init_shim.stderr,
        )
        self.assertNotEqual(no_document_mode.returncode, 0)
        self.assertIn("lacks required document-first seam", no_document_mode.stderr)

    def test_root_execution_is_rejected_when_applicable(self) -> None:
        if os.geteuid() != 0:
            self.skipTest("root-only rejection check")

        result = _dry_run(run_as_unprivileged=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must run as a non-root user", result.stderr)


if __name__ == "__main__":
    unittest.main()
