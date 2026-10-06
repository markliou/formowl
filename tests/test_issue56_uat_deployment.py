from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "compose.yaml"
UAT_COMPOSE = ROOT / "deploy" / "connected" / "compose.issue56-uat.yaml"
UAT_CADDY = ROOT / "deploy" / "connected" / "Caddyfile.issue56-uat.example"


class Issue56UatDeploymentTests(unittest.TestCase):
    def test_uat_overlay_renders_private_service_and_split_routes(self) -> None:
        caddy = UAT_CADDY.read_text(encoding="utf-8")
        active_lines = tuple(
            line for raw_line in caddy.splitlines() if (line := raw_line.split("#", 1)[0].strip())
        )
        self.assertIn(
            "@issue56_uat_browser path / /auth/start /auth/callback /auth/logout /api/*",
            active_lines,
        )
        self.assertIn(
            "@formowl_connected path /.well-known/* /oauth/* /mcp /healthz /readyz",
            active_lines,
        )
        self.assertEqual(
            tuple(line for line in active_lines if line.startswith("reverse_proxy ")),
            (
                "reverse_proxy 127.0.0.1:{$FORMOWL_ISSUE56_UAT_PUBLISH_PORT} {",
                "reverse_proxy 127.0.0.1:{$FORMOWL_CONNECTED_PUBLISH_PORT} {",
            ),
        )
        self.assertNotIn("handle_path", caddy)
        self.assertNotIn("rewrite", caddy)
        self.assertIn("respond 404", active_lines)

        with tempfile.TemporaryDirectory() as directory:
            operator_root = Path(directory)
            source_root = operator_root / "sealed-source"
            source_root.mkdir()
            sealed_environment = operator_root / "sealed.env"
            sealed_environment.write_text(
                "FORMOWL_ISSUE56_RETRIEVAL_SNAPSHOT_PATH=" "/issue56-source/retrieval.json\n",
                encoding="utf-8",
            )
            production_caddy = operator_root / "production-Caddyfile"
            production_caddy.write_text("production-placeholder\n", encoding="utf-8")
            secret_paths = {}
            for name in (
                "postgres-password",
                "database-dsn",
                "google-client-secret",
                "state-encryption-key",
                "signing-key-set.json",
                "signing-current.pem",
                "signing-previous.pem",
            ):
                path = operator_root / name
                path.write_text("safe-placeholder\n", encoding="utf-8")
                secret_paths[name] = path

            environment = {
                **os.environ,
                "COMPOSE_PROJECT_NAME": "formowl-issue56-uat-render",
                "FORMOWL_RUNTIME_IMAGE": f"sha256:{'1' * 64}",
                "FORMOWL_TLS_PROXY_IMAGE": f"sha256:{'2' * 64}",
                "FORMOWL_PUBLIC_HOST": "uat.example.test",
                "FORMOWL_ACME_EMAIL": "operator@example.test",
                "FORMOWL_OAUTH_ISSUER": "https://uat.example.test",
                "FORMOWL_MCP_RESOURCE": "https://uat.example.test/mcp",
                "FORMOWL_CHATGPT_CLIENT_ID": "formowl-issue56-uat-render",
                "FORMOWL_CHATGPT_REDIRECT_URI": ("https://uat.example.test/auth/callback"),
                "FORMOWL_GOOGLE_CLIENT_ID": "google-client-test",
                "FORMOWL_GOOGLE_REDIRECT_URI": ("https://uat.example.test/oauth/google/callback"),
                "FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID": "operator-test",
                "FORMOWL_CADDYFILE": str(production_caddy),
                "FORMOWL_CONNECTED_PUBLISH_PORT": "8000",
                "FORMOWL_ISSUE56_UAT_PUBLISH_PORT": "8766",
                "FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL": "https://uat.example.test",
                "FORMOWL_ISSUE56_UAT_SEALED_ENV_FILE": str(sealed_environment),
                "FORMOWL_ISSUE56_UAT_SOURCE_ROOT": str(source_root),
                "FORMOWL_POSTGRES_PASSWORD_FILE": str(secret_paths["postgres-password"]),
                "FORMOWL_DATABASE_DSN_FILE": str(secret_paths["database-dsn"]),
                "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": str(secret_paths["google-client-secret"]),
                "FORMOWL_STATE_ENCRYPTION_KEY_FILE": str(secret_paths["state-encryption-key"]),
                "FORMOWL_SIGNING_KEY_SET_FILE": str(secret_paths["signing-key-set.json"]),
                "FORMOWL_SIGNING_KEY_CURRENT_FILE": str(secret_paths["signing-current.pem"]),
                "FORMOWL_SIGNING_KEY_PREVIOUS_FILE": str(secret_paths["signing-previous.pem"]),
            }
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--profile",
                    "public-tls",
                    "--file",
                    str(BASE_COMPOSE),
                    "--file",
                    str(UAT_COMPOSE),
                    "config",
                    "--format",
                    "json",
                ],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

        services = json.loads(result.stdout)["services"]
        self.assertEqual(
            set(services),
            {
                "connected-mcp",
                "connected-migrate",
                "issue56-uat",
                "postgres",
                "project-mcp",
                "public-tls",
                "wiki-mcp",
            },
        )
        uat = services["issue56-uat"]
        connected = services["connected-mcp"]
        postgres = services["postgres"]
        public_tls = services["public-tls"]
        self.assertEqual(
            uat["ports"],
            [
                {
                    "mode": "ingress",
                    "host_ip": "127.0.0.1",
                    "target": 8766,
                    "published": "8766",
                    "protocol": "tcp",
                }
            ],
        )
        self.assertEqual(
            [
                name
                for name, service in services.items()
                if any(port.get("published") == "8766" for port in service.get("ports", ()))
            ],
            ["issue56-uat"],
        )
        self.assertNotIn("ports", postgres)
        self.assertEqual(
            connected["environment"]["FORMOWL_OAUTH_ALLOW_STANDALONE_UAT_HTTPS_REDIRECT"],
            "1",
        )
        self.assertEqual(
            uat["environment"]["FORMOWL_OAUTH_ALLOW_STANDALONE_UAT_HTTPS_REDIRECT"],
            "1",
        )
        self.assertEqual(public_tls["network_mode"], "host")
        self.assertEqual(public_tls["profiles"], ["public-tls"])
        self.assertEqual(
            public_tls["depends_on"]["connected-mcp"]["condition"],
            "service_healthy",
        )
        self.assertEqual(
            public_tls["depends_on"]["issue56-uat"]["condition"],
            "service_started",
        )
        mounts = {mount["target"]: mount for mount in public_tls["volumes"]}
        self.assertEqual(
            mounts["/etc/caddy/Caddyfile"]["source"],
            str(UAT_CADDY),
        )
        self.assertTrue(mounts["/etc/caddy/Caddyfile"]["read_only"])
        self.assertEqual(mounts["/data"]["type"], "volume")
        self.assertEqual(mounts["/config"]["type"], "volume")


if __name__ == "__main__":
    unittest.main()
