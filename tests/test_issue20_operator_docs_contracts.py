from __future__ import annotations

from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from deploy.connected import operator_config


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "connected"
RUNBOOK = ROOT / "docs" / "closed-beta-runbook.md"
EVIDENCE_RUNBOOK = ROOT / "docs" / "issue20-oauth-evidence-runbook.md"


def _env_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise AssertionError(f"invalid env-template line: {raw_line!r}")
        entries[key] = value
    return entries


def _active_caddy_lines(path: Path) -> tuple[str, ...]:
    return tuple(
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.split("#", 1)[0].strip())
    )


def _run_git(*arguments: str, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={ROOT}",
            *arguments,
        ],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


class Issue20OperatorDocsContractsTest(unittest.TestCase):
    def test_operator_config_validation_and_compose_helpers_run_in_process(self) -> None:
        image_id = f"sha256:{'1' * 64}"
        callback = "https://chatgpt.com/connector/oauth/callback-id"
        google_redirect = "https://formowl.example.com/oauth/google/callback"
        args = Namespace(
            project_name="formowl_issue20",
            runtime_image=image_id,
            tls_proxy_image=f"sha256:{'2' * 64}",
            public_host="formowl.example.com",
            acme_email="operator@example.com",
            chatgpt_client_id="formowl-chatgpt-issue20-campaign-001",
            chatgpt_redirect_uri=callback,
            google_client_id="google-client-001",
            owner_bootstrap_operator_service_id="operator-service-001",
        )

        self.assertEqual(operator_config._require_text("value", "label"), "value")
        self.assertEqual(operator_config._require_image_id(image_id, "image"), image_id)
        self.assertEqual(
            operator_config._require_public_host("formowl.example.com"),
            "formowl.example.com",
        )
        self.assertEqual(
            operator_config._require_identifier("client_001", "client"),
            "client_001",
        )
        self.assertEqual(
            operator_config._require_chatgpt_client_id(args.chatgpt_client_id),
            args.chatgpt_client_id,
        )
        self.assertEqual(operator_config._require_callback(callback), callback)
        self.assertEqual(
            operator_config._require_google_redirect_uri(google_redirect),
            google_redirect,
        )
        self.assertEqual(operator_config._unique_object([("one", 1)]), {"one": 1})
        with self.assertRaises(operator_config.OperatorConfigError):
            operator_config._unique_object([("one", 1), ("one", 2)])

        compose_environment = operator_config._compose_environment(args).decode("utf-8")
        self.assertIn("FORMOWL_PUBLIC_HOST=formowl.example.com\n", compose_environment)
        self.assertIn(
            "FORMOWL_CHATGPT_CLIENT_ID=formowl-chatgpt-issue20-campaign-001\n",
            compose_environment,
        )
        self.assertIn(f"FORMOWL_CHATGPT_REDIRECT_URI={callback}\n", compose_environment)
        self.assertNotIn("client_secret", compose_environment)
        invalid_compose_args = Namespace(**vars(args))
        invalid_compose_args.chatgpt_client_id = "formowl-discovery-only"
        with self.assertRaisesRegex(
            operator_config.OperatorConfigError,
            "chatgpt_client_id_invalid",
        ):
            operator_config._compose_environment(invalid_compose_args)

        parsed = operator_config._parser().parse_args(
            [
                "predefined-client-id",
                "--deployment-id",
                "issue20-campaign-001",
            ]
        )
        self.assertEqual(parsed.command, "predefined-client-id")
        self.assertEqual(parsed.deployment_id, "issue20-campaign-001")

        invalid_calls = (
            lambda: operator_config._require_text("bad\nvalue", "label"),
            lambda: operator_config._require_image_id(f"sha256:{'0' * 64}", "image"),
            lambda: operator_config._require_public_host("reserved.example"),
            lambda: operator_config._require_identifier("contains/slash", "client"),
            lambda: operator_config._require_chatgpt_client_id("formowl-discovery-only"),
            lambda: operator_config._require_callback("https://attacker.example/callback"),
            lambda: operator_config._require_google_redirect_uri(
                "https://reserved.example/oauth/google/callback"
            ),
        )
        for invalid_call in invalid_calls:
            with self.subTest(invalid_call=invalid_call):
                with self.assertRaises(operator_config.OperatorConfigError):
                    invalid_call()

    def test_operator_config_io_public_and_cli_helpers_run_in_process(self) -> None:
        origin = "https://formowl.example.com"
        callback = "https://chatgpt.com/connector/oauth/callback-id"
        public_payloads = {
            f"{origin}/healthz": (200, {"status": "ok"}),
            f"{origin}/readyz": (200, {"status": "ready"}),
            f"{origin}/.well-known/oauth-protected-resource": (
                200,
                {
                    "authorization_servers": [origin],
                    "resource": f"{origin}/mcp",
                },
            ),
            f"{origin}/.well-known/oauth-authorization-server": (
                200,
                {
                    "authorization_endpoint": f"{origin}/oauth/authorize",
                    "code_challenge_methods_supported": ["S256"],
                    "issuer": origin,
                    "jwks_uri": f"{origin}/.well-known/jwks.json",
                    "token_endpoint": f"{origin}/oauth/token",
                },
            ),
        }

        class FakeResponse:
            def __init__(self, url: str, status: int, payload: object) -> None:
                self._url = url
                self.status = status
                self._payload = json.dumps(payload).encode("utf-8")

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return self._url

            def read(self, _limit: int) -> bytes:
                return self._payload

        def fake_urlopen(url: str, *, timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 10)
            status, payload = public_payloads[url]
            return FakeResponse(url, status, payload)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            exclusive = root / "exclusive"
            operator_config._write_exclusive(exclusive, b"first\n", mode=0o600)
            self.assertEqual(exclusive.read_bytes(), b"first\n")
            self.assertEqual(exclusive.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(
                operator_config.OperatorConfigError,
                "output_already_exists",
            ):
                operator_config._write_exclusive(exclusive, b"second\n", mode=0o600)

            operator_config._write_replace(exclusive, b"replaced\n", mode=0o600)
            self.assertEqual(exclusive.read_bytes(), b"replaced\n")
            with self.assertRaisesRegex(
                operator_config.OperatorConfigError,
                "replace_target_invalid",
            ):
                operator_config._write_replace(
                    root / "missing",
                    b"missing\n",
                    mode=0o600,
                )

            credential = root / "google-client.json"
            credential.write_text(
                json.dumps(
                    {
                        "web": {
                            "client_id": "google-client-001",
                            "client_secret": "google-secret-value",
                            "redirect_uris": ["https://formowl.example.com/oauth/google/callback"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            credential.chmod(0o600)
            self.assertEqual(
                operator_config._read_json_file(credential)["web"]["client_id"],
                "google-client-001",
            )
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"web":{},"web":{}}', encoding="utf-8")
            duplicate.chmod(0o600)
            with self.assertRaisesRegex(
                operator_config.OperatorConfigError,
                "google_credential_json_invalid",
            ):
                operator_config._read_json_file(duplicate)

            google_secret = root / "google-client-secret"
            operator_config._import_google_secret(
                Namespace(
                    credential_json=credential,
                    expected_client_id="google-client-001",
                    expected_redirect_uri=("https://formowl.example.com/oauth/google/callback"),
                    output=google_secret,
                )
            )
            self.assertEqual(google_secret.read_text(encoding="utf-8"), "google-secret-value\n")
            self.assertEqual(google_secret.stat().st_mode & 0o777, 0o400)
            mismatched_secret = root / "mismatched-google-client-secret"
            with self.assertRaisesRegex(
                operator_config.OperatorConfigError,
                "google_client_id_mismatch",
            ):
                operator_config._import_google_secret(
                    Namespace(
                        credential_json=credential,
                        expected_client_id="other-google-client",
                        expected_redirect_uri=("https://formowl.example.com/oauth/google/callback"),
                        output=mismatched_secret,
                    )
                )
            self.assertFalse(mismatched_secret.exists())

            compose_output = root / "compose.env"
            operator_config._write_compose_env(
                Namespace(
                    project_name="formowl_issue20",
                    runtime_image=f"sha256:{'1' * 64}",
                    tls_proxy_image=f"sha256:{'2' * 64}",
                    public_host="formowl.example.com",
                    acme_email="operator@example.com",
                    chatgpt_client_id="formowl-chatgpt-issue20-campaign-001",
                    chatgpt_redirect_uri=callback,
                    google_client_id="google-client-001",
                    owner_bootstrap_operator_service_id="operator-service-001",
                    output=compose_output,
                    replace=False,
                )
            )
            self.assertIn(
                "FORMOWL_CHATGPT_CLIENT_ID=formowl-chatgpt-issue20-campaign-001\n",
                compose_output.read_text(encoding="utf-8"),
            )
            with self.assertRaisesRegex(
                operator_config.OperatorConfigError,
                "output_already_exists",
            ):
                operator_config._write_compose_env(
                    Namespace(
                        project_name="formowl_issue20",
                        runtime_image=f"sha256:{'1' * 64}",
                        tls_proxy_image=f"sha256:{'2' * 64}",
                        public_host="formowl.example.com",
                        acme_email="operator@example.com",
                        chatgpt_client_id="formowl-chatgpt-issue20-campaign-001",
                        chatgpt_redirect_uri=callback,
                        google_client_id="google-client-001",
                        owner_bootstrap_operator_service_id="operator-service-001",
                        output=compose_output,
                        replace=False,
                    )
                )

            direct_client = operator_config._predefined_client_id(
                Namespace(
                    client_id=None,
                    deployment_id="issue20-campaign-001",
                    output=None,
                )
            )
            self.assertEqual(
                direct_client["chatgpt_client_id"],
                "formowl-chatgpt-issue20-campaign-001",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                return_code = operator_config.main(
                    [
                        "predefined-client-id",
                        "--deployment-id",
                        "issue20-campaign-001",
                    ]
                )
            self.assertEqual(return_code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), direct_client)

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                return_code = operator_config.main(
                    [
                        "predefined-client-id",
                        "--client-id",
                        "formowl-discovery-only",
                    ]
                )
            self.assertEqual(return_code, 1)
            self.assertEqual(
                json.loads(stderr.getvalue()),
                {"error": "chatgpt_client_id_invalid", "status": "error"},
            )

        with patch.object(operator_config, "urlopen", side_effect=fake_urlopen):
            self.assertEqual(
                operator_config._read_public_json(f"{origin}/healthz"),
                (200, {"status": "ok"}),
            )
            self.assertEqual(
                operator_config._read_public_status(f"{origin}/readyz"),
                (200, "ready"),
            )
            operator_config._check_public(
                Namespace(
                    attempts=1,
                    delay_seconds=0.0,
                    mode="ready",
                    origin=origin,
                )
            )
        with patch.object(
            operator_config,
            "urlopen",
            return_value=FakeResponse(f"{origin}/healthz", 200, []),
        ):
            with self.assertRaisesRegex(
                operator_config.OperatorConfigError,
                "public_route_response_invalid",
            ):
                operator_config._read_public_json(f"{origin}/healthz")
        invalid_payloads = {
            **public_payloads,
            f"{origin}/readyz": (503, {"status": "not-ready"}),
        }

        def invalid_urlopen(url: str, *, timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 10)
            status, payload = invalid_payloads[url]
            return FakeResponse(url, status, payload)

        with patch.object(operator_config, "urlopen", side_effect=invalid_urlopen):
            with self.assertRaisesRegex(
                operator_config.OperatorConfigError,
                "public_route_response_invalid",
            ):
                operator_config._check_public(
                    Namespace(
                        attempts=1,
                        delay_seconds=0.0,
                        mode="ready",
                        origin=origin,
                    )
                )

        operator_config._wait_until_expired(Namespace(expires_at="2020-01-01T00:00:00+00:00"))
        with self.assertRaisesRegex(operator_config.OperatorConfigError, "expires_at_invalid"):
            operator_config._wait_until_expired(Namespace(expires_at="2020-01-01T00:00:00"))

    def test_tracked_compose_env_template_is_non_secret_and_complete(self) -> None:
        template = DEPLOY / "compose.env.example"
        template_text = template.read_text(encoding="utf-8")
        entries = _env_entries(template)

        self.assertTrue(
            {
                "FORMOWL_RUNTIME_IMAGE",
                "FORMOWL_POSTGRES_IMAGE",
                "FORMOWL_TLS_PROXY_IMAGE",
                "FORMOWL_PUBLIC_HOST",
                "FORMOWL_OAUTH_ISSUER",
                "FORMOWL_MCP_RESOURCE",
                "FORMOWL_CHATGPT_CLIENT_ID",
                "FORMOWL_CHATGPT_REDIRECT_URI",
                "FORMOWL_GOOGLE_CLIENT_ID",
                "FORMOWL_GOOGLE_REDIRECT_URI",
                "FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID",
                "FORMOWL_CADDYFILE",
                "FORMOWL_CONNECTED_PUBLISH_PORT",
            }.issubset(entries)
        )
        self.assertEqual(
            entries["FORMOWL_CHATGPT_CLIENT_ID"],
            "formowl-chatgpt-replace-with-deployment-id",
        )
        self.assertEqual(
            entries["FORMOWL_CHATGPT_REDIRECT_URI"],
            "https://invalid.example.invalid/formowl-discovery-only",
        )
        self.assertEqual(
            entries["FORMOWL_POSTGRES_IMAGE"],
            "pgvector/pgvector@sha256:"
            "131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6",
        )
        self.assertEqual(
            entries["FORMOWL_CADDYFILE"],
            "./.formowl/issue20/Caddyfile",
        )
        self.assertIn(".formowl/issue20/compose.env", template_text)
        self.assertIn("stable non-secret predefined client ID before discovery", template_text)
        self.assertNotIn("Intentionally blank", template_text)

        forbidden_value_fragments = (
            "postgresql://",
            "-----BEGIN",
            "client_secret=",
            "bearer ",
        )
        for key, value in entries.items():
            with self.subTest(key=key):
                self.assertFalse(
                    any(fragment in value.lower() for fragment in forbidden_value_fragments)
                )
                if key.endswith("_FILE"):
                    self.assertTrue(value.startswith("./deploy/connected/secrets/"))

        self.assertNotIn("FORMOWL_DATABASE_DSN", entries)
        self.assertNotIn("FORMOWL_GOOGLE_CLIENT_SECRET", entries)
        self.assertNotIn("FORMOWL_OAUTH_STATE_ENCRYPTION_KEY", entries)

    def test_operator_helper_derives_and_validates_safe_predefined_client_id(self) -> None:
        script = DEPLOY / "operator_config.py"
        generated = subprocess.run(
            [
                sys.executable,
                str(script),
                "predefined-client-id",
                "--deployment-id",
                "issue20-campaign-001",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        generated_payload = json.loads(generated.stdout)
        self.assertEqual(
            generated_payload,
            {
                "chatgpt_client_id": "formowl-chatgpt-issue20-campaign-001",
                "command": "predefined-client-id",
                "status": "valid",
            },
        )

        validated = subprocess.run(
            [
                sys.executable,
                str(script),
                "predefined-client-id",
                "--client-id",
                generated_payload["chatgpt_client_id"],
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(validated.stdout), generated_payload)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "chatgpt-client-id"
            written = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "predefined-client-id",
                    "--deployment-id",
                    "issue20-campaign-001",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(written.stdout),
                {"command": "predefined-client-id", "status": "written"},
            )
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "formowl-chatgpt-issue20-campaign-001\n",
            )
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

        for unsafe_client_id in (
            "formowl-discovery-only",
            "formowl-chatgpt-replace-with-deployment-id",
            "contains/slash",
        ):
            with self.subTest(unsafe_client_id=unsafe_client_id):
                rejected = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "predefined-client-id",
                        "--client-id",
                        unsafe_client_id,
                    ],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(rejected.returncode, 1)
                self.assertEqual(rejected.stdout, "")
                self.assertEqual(
                    json.loads(rejected.stderr),
                    {"error": "chatgpt_client_id_invalid", "status": "error"},
                )

        placeholder_deployment = subprocess.run(
            [
                sys.executable,
                str(script),
                "predefined-client-id",
                "--deployment-id",
                "formowl-issue20-replace-with-unique-campaign",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(placeholder_deployment.returncode, 1)
        self.assertEqual(placeholder_deployment.stdout, "")
        self.assertEqual(
            json.loads(placeholder_deployment.stderr),
            {"error": "deployment_id_invalid", "status": "error"},
        )

    def test_operator_env_and_generated_secrets_are_ignored(self) -> None:
        ignored_env = ".formowl/issue20/compose.env"
        check = _run_git("check-ignore", "--quiet", ignored_env, check=False)
        self.assertEqual(check.returncode, 0)

        tracked = _run_git(
            "ls-files",
            "--cached",
            "--",
            "deploy/connected/secrets",
            check=True,
        ).stdout.splitlines()
        self.assertLessEqual(
            set(tracked),
            {"deploy/connected/secrets/README.md"},
        )

    def test_caddy_and_compose_keep_backends_private(self) -> None:
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

        for caddy_name in ("Caddyfile", "Caddyfile.example"):
            with self.subTest(caddy_name=caddy_name):
                active_caddy_lines = _active_caddy_lines(DEPLOY / caddy_name)
                reverse_proxy_lines = tuple(
                    line for line in active_caddy_lines if line.startswith("reverse_proxy ")
                )
                self.assertEqual(
                    reverse_proxy_lines,
                    ("reverse_proxy " "127.0.0.1:{$FORMOWL_CONNECTED_PUBLISH_PORT} {",),
                )
                active_text = "\n".join(active_caddy_lines)
                self.assertNotIn("connected-mcp:", active_text)
                self.assertNotIn("postgres", active_text.lower())

        postgres = compose.split("  postgres:", 1)[1].split("\n  connected-migrate:", 1)[0]
        connected = compose.split("  connected-mcp:", 1)[1].split("\n  public-tls:", 1)[0]
        self.assertNotIn("\n    ports:", postgres)
        self.assertIn(
            '"127.0.0.1:${FORMOWL_CONNECTED_PUBLISH_PORT:-8000}:8000"',
            connected,
        )
        public_tls = compose.split("  public-tls:", 1)[1].split("\n  project-mcp:", 1)[0]
        self.assertIn("    network_mode: host", public_tls)
        self.assertNotIn("\n    ports:", public_tls)
        self.assertIn(
            "${FORMOWL_CADDYFILE:?set the ignored operator Caddyfile path}:"
            "/etc/caddy/Caddyfile:ro",
            public_tls,
        )
        self.assertIn(
            "os.environ.get('FORMOWL_CHATGPT_REDIRECT_URI') == "
            "'https://invalid.example.invalid/formowl-discovery-only'",
            connected,
        )
        self.assertNotIn(
            "os.environ.get('FORMOWL_CHATGPT_CLIENT_ID') == 'formowl-discovery-only'",
            connected,
        )

    def test_compose_render_uses_exact_host_network_tls_topology(self) -> None:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--file",
                str(ROOT / "compose.yaml"),
                "--env-file",
                str(DEPLOY / "compose.env.example"),
                "--profile",
                "public-tls",
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        rendered = json.loads(result.stdout)
        services = rendered["services"]
        public_tls = services["public-tls"]
        connected = services["connected-mcp"]
        postgres = services["postgres"]

        self.assertEqual(public_tls["network_mode"], "host")
        self.assertNotIn("ports", public_tls)
        self.assertNotIn("networks", public_tls)
        caddy_mounts = [
            mount for mount in public_tls["volumes"] if mount["target"] == "/etc/caddy/Caddyfile"
        ]
        self.assertEqual(len(caddy_mounts), 1)
        self.assertEqual(caddy_mounts[0]["type"], "bind")
        self.assertEqual(
            caddy_mounts[0]["source"],
            str(ROOT / ".formowl" / "issue20" / "Caddyfile"),
        )
        self.assertTrue(caddy_mounts[0]["read_only"])
        self.assertEqual(
            connected["ports"],
            [
                {
                    "mode": "ingress",
                    "host_ip": "127.0.0.1",
                    "target": 8000,
                    "published": "8000",
                    "protocol": "tcp",
                }
            ],
        )
        self.assertNotIn("ports", postgres)

    def test_runbook_orders_discovery_before_stateful_startup(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")

        required = (
            'FORMOWL_OPERATOR_DIR="$PWD/.formowl/issue20"',
            'FORMOWL_COMPOSE_ENV="$FORMOWL_OPERATOR_DIR/compose.env"',
            'FORMOWL_CADDYFILE="$FORMOWL_OPERATOR_DIR/Caddyfile"',
            'COMPOSE_ENV="$FORMOWL_COMPOSE_ENV"',
            "export FORMOWL_OPERATOR_DIR FORMOWL_COMPOSE_ENV FORMOWL_CADDYFILE COMPOSE_ENV",
            '--env-file "$COMPOSE_ENV"',
            'FORMOWL_CHATGPT_CLIENT_ID_FILE="$FORMOWL_OPERATOR_DIR/'
            'chatgpt-predefined-client-id"',
            "predefined-client-id",
            '--deployment-id "$FORMOWL_PROJECT_NAME"',
            "--output /operator/chatgpt-predefined-client-id",
            'FORMOWL_CHATGPT_CLIENT_ID="$(',
            "FORMOWL_CHATGPT_REDIRECT_URI='https://invalid.example.invalid/formowl-discovery-only'",
            "'FORMOWL_CADDYFILE=./.formowl/issue20/Caddyfile'",
            "run --detach --name formowl-discovery-only",
            "--no-deps --service-ports connected-mcp serve",
            "--profile public-tls up -d --no-deps public-tls",
            "docker inspect --format '{{.State.Running}}' formowl-discovery-only",
            "HTTP 200",
            "HTTP 503",
            "--profile public-tls stop public-tls",
            "--profile public-tls rm -f public-tls",
            "docker stop formowl-discovery-only",
            "docker rm formowl-discovery-only",
            "chatgpt_predefined_client_configuration_unavailable",
            "FORMOWL_CHATGPT_REDIRECT_URI='https://chatgpt.com/connector/oauth/<callback-id>'",
            ".test-tmp/issue20-compose-final.json",
            "up -d postgres",
            "run --rm connected-migrate",
            "run --rm connected-mcp preflight",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, runbook)

        env_references = set(re.findall(r'--env-file "(\$[A-Z_]+)"', runbook))
        self.assertTrue(env_references)
        self.assertLessEqual(
            env_references,
            {"$FORMOWL_COMPOSE_ENV", "$COMPOSE_ENV"},
        )
        if "$COMPOSE_ENV" in env_references:
            self.assertIn('COMPOSE_ENV="$FORMOWL_COMPOSE_ENV"', runbook)
            self.assertRegex(
                runbook,
                r"export [^\n]*\bCOMPOSE_ENV\b",
            )
        self.assertNotIn(
            "$PWD/deploy/connected/Caddyfile.example:/etc/caddy/Caddyfile:ro",
            runbook,
        )
        self.assertNotIn("formowl-discovery-caddy", runbook)

        copied_env = runbook.index(
            "install -m 0600 deploy/connected/compose.env.example " '"$FORMOWL_COMPOSE_ENV"'
        )
        copied_caddy = runbook.index(
            "install -m 0600 deploy/connected/Caddyfile.example " '"$FORMOWL_CADDYFILE"',
            copied_env,
        )
        client_file = runbook.index(
            'FORMOWL_CHATGPT_CLIENT_ID_FILE="$FORMOWL_OPERATOR_DIR/'
            'chatgpt-predefined-client-id"',
            copied_caddy,
        )
        client_helper = runbook.index("predefined-client-id", client_file)
        client_loaded = runbook.index('FORMOWL_CHATGPT_CLIENT_ID="$(', client_helper)
        discovery_redirect = runbook.index(
            "FORMOWL_CHATGPT_REDIRECT_URI='https://invalid.example.invalid/"
            "formowl-discovery-only'",
            client_loaded,
        )
        first_env_write = runbook.index("write-compose-env", discovery_redirect)
        first_caddy_path = runbook.index(
            "'FORMOWL_CADDYFILE=./.formowl/issue20/Caddyfile'",
            first_env_write,
        )
        discovery = runbook.index(
            "run --detach --name formowl-discovery-only",
            first_caddy_path,
        )
        public_tls = runbook.index(
            "--profile public-tls up -d --no-deps public-tls",
            discovery,
        )
        app_creation = runbook.index(
            "If app management supports predefined-client",
            public_tls,
        )
        stopped = runbook.index("--profile public-tls stop public-tls", app_creation)
        production_callback = runbook.index(
            "FORMOWL_CHATGPT_REDIRECT_URI='https://chatgpt.com/connector/oauth/" "<callback-id>'",
            stopped,
        )
        finalized = runbook.index(".test-tmp/issue20-compose-final.json")
        postgres = runbook.index("up -d postgres", finalized)
        migration = runbook.index("run --rm connected-migrate", postgres)
        preflight = runbook.index("run --rm connected-mcp preflight", migration)
        bootstrap = runbook.index("run --rm connected-mcp bootstrap-owner", preflight)
        self.assertLess(copied_env, copied_caddy)
        self.assertLess(copied_caddy, client_file)
        self.assertLess(client_file, client_helper)
        self.assertLess(client_helper, client_loaded)
        self.assertLess(client_loaded, discovery_redirect)
        self.assertLess(discovery_redirect, first_env_write)
        self.assertLess(first_env_write, first_caddy_path)
        self.assertLess(first_caddy_path, discovery)
        self.assertLess(discovery, public_tls)
        self.assertLess(public_tls, app_creation)
        self.assertLess(app_creation, stopped)
        self.assertLess(stopped, production_callback)
        self.assertLess(production_callback, finalized)
        self.assertLess(finalized, postgres)
        self.assertLess(postgres, migration)
        self.assertLess(migration, preflight)
        self.assertLess(preflight, bootstrap)
        self.assertEqual(
            runbook.count("'FORMOWL_CADDYFILE=./.formowl/issue20/Caddyfile'"),
            2,
        )

    def test_ui_values_inspector_and_expiry_contracts_are_exact(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        evidence = EVIDENCE_RUNBOOK.read_text(encoding="utf-8")
        combined = f"{runbook}\n{evidence}"
        inspector = runbook.split(
            "## 11. Remote MCP Inspector Journey",
            1,
        )[1].split("## 12.", 1)[0]

        self.assertIn("ChatGPT Apps", combined)
        self.assertIn("developer-mode app", combined)
        self.assertIn("formowl-discovery-only", combined)
        self.assertIn("redirect sentinel alone selects discovery", combined)
        self.assertIn("network_mode: host", combined)
        self.assertNotIn("Settings → Plugins", combined)
        self.assertNotIn("chatgpt.com/plugins", combined)
        self.assertIn("never claim", combined)
        self.assertIn("external live blocker", combined)
        self.assertRegex(combined, r"replace only\s+the redirect\s+sentinel")
        self.assertIn("The client ID must remain unchanged", combined)
        self.assertIn("predefined-client design", combined)
        self.assertNotIn("CIMD migration", combined)
        self.assertNotIn("FORMOWL_CHATGPT_CLIENT_ID='formowl-discovery-only'", combined)
        self.assertNotIn("exact-UI-supplied-predefined-client-id", combined)
        self.assertNotIn("paired `formowl-discovery-only`", combined)
        self.assertNotIn("ChatGPT shows the exact predefined client ID", combined)
        self.assertIn("npx @modelcontextprotocol/inspector@latest", inspector)
        self.assertIn("npx @modelcontextprotocol/inspector@latest", evidence)
        self.assertIn("public-only", inspector)
        self.assertNotIn("ghcr.io/modelcontextprotocol/inspector", combined)
        self.assertNotIn("docker pull", inspector)
        self.assertNotIn("docker image inspect", inspector)
        self.assertNotIn("docker run", inspector)
        self.assertIn("fixed at exactly 3600 seconds", runbook)
        self.assertIn("fixed 30-second clock skew", runbook)
        self.assertIn("strictly later than `expires_at + 30 seconds`", combined)
        self.assertIn("must not shorten the lifetime", evidence)
        self.assertIn(
            "Normal FormOwl deployment does not require host Python",
            evidence,
        )
        self.assertIn("governed outer custody", evidence)
        self.assertIn("one explicit host prerequisite", evidence)
        self.assertIn("executable `/usr/bin/python3`", evidence)

    def test_live_postgresql_and_failure_docs_match_production_contracts(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        evidence = EVIDENCE_RUNBOOK.read_text(encoding="utf-8")
        live_source = (ROOT / "scripts" / "connected_runtime_postgres_live_e2e.py").read_text(
            encoding="utf-8"
        )
        operator_source = (
            ROOT / "scripts" / "connected_operator_postgres_live_journey.py"
        ).read_text(encoding="utf-8")

        artifact_match = re.search(
            r'^ARTIFACT_ID = "(?P<artifact_id>[^"]+)"$',
            live_source,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(artifact_match)
        artifact_id = artifact_match.group("artifact_id")
        self.assertEqual(artifact_id, "formowl_connected_runtime_postgres_live_e2e_v2")

        report_fields_match = re.search(
            r"_exact_keys\(\s*report,\s*\{(?P<fields>.*?)\},\s*\"report\"",
            live_source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(report_fields_match)
        report_fields = tuple(re.findall(r'"([a-z0-9_]+)"', report_fields_match.group("fields")))
        self.assertEqual(
            set(report_fields),
            {
                "artifact_id",
                "status",
                "protocol_version",
                "metrics",
                "safe_counts",
                "safe_hashes",
                "live_postgresql_layer",
                "claim_boundary",
            },
        )

        documented_shape_match = re.search(
            r"The authoritative raw live-PostgreSQL source report is artifact\s+"
            r"`(?P<artifact_id>[^`]+)`\. Its exact top-level shape is:\s+"
            r"```text\n(?P<fields>.*?)\n```",
            evidence,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(documented_shape_match)
        self.assertEqual(documented_shape_match.group("artifact_id"), artifact_id)
        self.assertEqual(
            set(documented_shape_match.group("fields").splitlines()),
            set(report_fields),
        )
        documents = {
            "closed-beta-runbook": runbook,
            "issue20-oauth-evidence-runbook": evidence,
        }
        for name, document in documents.items():
            with self.subTest(document=name):
                self.assertIn(artifact_id, document)
                self.assertRegex(
                    document,
                    r"no\s+standalone `schema_version` field",
                )
                self.assertIn("formowl_connected_runtime_postgres_live_e2e_v1", document)
                self.assertIn("`schema_version: 1`", document)

        production_stages_match = re.search(
            r"FAILURE_DIAGNOSTIC_STAGES = \(\n(?P<stages>.*?)\n\)",
            operator_source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(production_stages_match)
        production_stages = tuple(
            re.findall(r'"([a-z0-9_]+)"', production_stages_match.group("stages"))
        )
        for name, document in documents.items():
            with self.subTest(failure_stages_document=name):
                documented_stages_match = re.search(
                    r"`stage` must be exactly one\s+of:\s+```text\n" r"(?P<stages>.*?)\n```",
                    document,
                    flags=re.DOTALL,
                )
                self.assertIsNotNone(documented_stages_match)
                self.assertEqual(
                    tuple(documented_stages_match.group("stages").splitlines()),
                    production_stages,
                )
        self.assertIn("outer_runtime_cleanup", production_stages)

        expected_incomplete_layers = (
            "live_postgresql",
            "operator_cli_postgresql",
            "production_container_lifecycle",
            "mcp_inspector",
            "live_chatgpt_google",
            "reviewer_gate",
            "completion_audit",
        )
        for name, document in documents.items():
            with self.subTest(incomplete_document=name):
                for layer_name in expected_incomplete_layers:
                    self.assertIn(f"{layer_name} = not_supplied", document)
                self.assertIn("Issue #20 remains open", document)

    def test_authority_docs_assign_client_id_to_operator_and_callback_to_chatgpt(
        self,
    ) -> None:
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
        combined = "\n".join(documents.values())

        for relative_path, document in documents.items():
            with self.subTest(relative_path=relative_path):
                self.assertIn("predefined", document)
                self.assertRegex(document, r"client\s+ID")
                self.assertRegex(document, r"production\s+callback")

        self.assertIn("stable non-secret", combined)
        self.assertIn("selected and recorded", combined)
        self.assertRegex(combined, r"deployment\s+operator before discovery")
        self.assertIn("external live blocker", combined)
        self.assertIn("supplies and displays only", combined)
        self.assertIn("requires no host Python", combined)
        self.assertNotIn("UI-supplied predefined client ID", combined)
        self.assertNotIn("client ID and production callback are UI-supplied", combined)
        self.assertNotIn("client ID and production callback come from ChatGPT", combined)
        self.assertNotIn("client ID and production callback are copied exactly", combined)
        self.assertNotIn("client ID and production callback are external values supplied", combined)

    def test_secret_directory_and_evidence_commands_are_clean_clone_safe(self) -> None:
        secret_readme = (DEPLOY / "secrets" / "README.md").read_text(encoding="utf-8")
        evidence = EVIDENCE_RUNBOOK.read_text(encoding="utf-8")

        self.assertIn("tracked `README.md` may already exist", secret_readme)
        self.assertIn("no generated target", secret_readme)
        self.assertIn("initializer lock or staging", secret_readme)
        self.assertIn("recovery/quarantine", secret_readme)
        self.assertNotIn("compose.env", secret_readme)
        self.assertIn(
            "docker build --file containers/dev/Dockerfile " "--tag formowl-dev:local .",
            evidence,
        )
        self.assertIn("issue20_dev formowl-issue20-evidence", evidence)
        self.assertIn(
            "scripts/issue20_containerized_evidence_runner.sh operator",
            evidence,
        )
        self.assertIsNone(
            re.search(r"(?m)^(?:python scripts/|formowl-issue20-evidence )", evidence)
        )

    def test_final_closure_commands_artifacts_and_order_are_pinned(self) -> None:
        evidence = EVIDENCE_RUNBOOK.read_text(encoding="utf-8")
        runbook = RUNBOOK.read_text(encoding="utf-8")

        artifact_paths = (
            ".test-tmp/issue20-external-evidence.json",
            ".test-tmp/issue20-oauth-mcp-harness.json",
            ".test-tmp/issue20-preclosure-manifest.json",
            ".test-tmp/issue20-preclosure-manifest-validation.json",
            ".test-tmp/issue20-completion-transition.json",
            ".test-tmp/issue20-completion-transition-validation.json",
        )
        for path in artifact_paths:
            with self.subTest(path=path):
                self.assertIn(path, evidence)

        subcommands = (
            "build-preclosure-manifest",
            "validate-preclosure-manifest",
            "build-completion-transition",
            "validate-completion-transition",
        )
        command_positions = [evidence.index(subcommand) for subcommand in subcommands]
        self.assertEqual(command_positions, sorted(command_positions))
        self.assertIn("--operator-attest-finalization", evidence)
        self.assertIn("--preclosure-manifest", evidence)
        self.assertIn("--completion-transition", evidence)
        self.assertIn("--external-evidence", evidence)
        self.assertIn("--operator-cli-postgresql-authority-pin", evidence)
        self.assertIn("--expected-local-harness-report-hash", evidence)

        apply_transition = evidence.index(
            "### 2. Apply the exact five-document completion transition"
        )
        self.assertLess(command_positions[1], apply_transition)
        self.assertLess(apply_transition, command_positions[2])
        for path in (
            "README.md",
            "docs/implementation-task-breakdown.md",
            "docs/agent-goals/system-backbone-agent.md",
            "docs/agent-goals/handoff-log.md",
            "docs/issue20-account-system-verification-status.md",
        ):
            with self.subTest(completion_path=path):
                self.assertIn(path, evidence[apply_transition : command_positions[2]])

        self.assertIn("All seven\npacket layers must be `passed`", evidence)
        self.assertIn("exactly 3/3 `AGREE`", evidence)
        self.assertIn("distinct\nindependent completion auditor", evidence)
        self.assertIn("supports_issue20_closure_claim: true", evidence)
        self.assertIn("does not\ncreate a Git commit, push a branch", evidence)
        self.assertIn("close GitHub Issue", evidence)
        self.assertIn("clean, reviewed source state", evidence)
        self.assertIn("required authorization", evidence)

        handoff = runbook.index("## 13. Governed Final Closure Handoff")
        preclosure = runbook.index(
            ".test-tmp/issue20-preclosure-manifest.json",
            handoff,
        )
        five_documents = runbook.index(
            "five completion-state documents",
            preclosure,
        )
        transition = runbook.index(
            ".test-tmp/issue20-completion-transition.json",
            five_documents,
        )
        publication = runbook.index(
            "separate operator\npublication actions",
            transition,
        )
        self.assertLess(preclosure, five_documents)
        self.assertLess(five_documents, transition)
        self.assertLess(transition, publication)


if __name__ == "__main__":
    unittest.main()
