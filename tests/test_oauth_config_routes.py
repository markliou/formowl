from __future__ import annotations

from cryptography.fernet import Fernet
from formowl_contract import ContractValidationError

import _paths  # noqa: F401
from formowl_auth import (
    CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
    OAuthBridgeConfig,
)
from formowl_auth.http import (
    authorization_server_metadata,
    oauth_routes,
    protected_resource_metadata,
)
from oauth_harness import (
    TransactionAwareMemoryRepository,
    generate_ephemeral_formowl_signing_key,
)
from test_oauth_bridge_service import BridgeFixture

import unittest


class OAuthConfigRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_key = Fernet.generate_key().decode("ascii")
        self.base = {
            "issuer": "https://auth.example.test",
            "resource": "https://auth.example.test/mcp",
            "chatgpt_client_id": "chatgpt-client",
            "chatgpt_redirect_uri": "https://chatgpt.com/connector/oauth/callback-id_01",
            "google_client_id": "google-client",
            "google_client_secret": "google-secret",
            "google_redirect_uri": "https://auth.example.test/oauth/google/callback",
            "state_encryption_key": self.state_key,
        }

    def test_valid_production_and_explicit_loopback_configs(self) -> None:
        production = OAuthBridgeConfig(**self.base)
        self.assertEqual(production.issuer, "https://auth.example.test")
        self.assertFalse(production.allow_loopback_http)
        self.assertEqual(production.chatgpt_callback_mode, "production_exact")
        self.assertEqual(
            production.to_public_dict()["chatgpt_callback_mode"],
            "production_exact",
        )

        discovery = OAuthBridgeConfig(
            **{
                **self.base,
                "chatgpt_redirect_uri": CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
            }
        )
        self.assertEqual(discovery.chatgpt_callback_mode, "discovery_only")

        loopback = OAuthBridgeConfig(
            issuer="http://127.0.0.1:8765",
            resource="http://127.0.0.1:8765/mcp",
            chatgpt_client_id="inspector-client",
            chatgpt_redirect_uri="http://localhost:9000/callback",
            google_client_id="google-client",
            google_client_secret="google-secret",
            google_redirect_uri="http://127.0.0.1:8765/oauth/google/callback",
            state_encryption_key=self.state_key,
            allow_loopback_http=True,
        )
        self.assertTrue(loopback.allow_loopback_http)
        self.assertEqual(loopback.resource, f"{loopback.issuer}/mcp")
        self.assertEqual(loopback.chatgpt_callback_mode, "loopback_test")

    def test_from_env_builds_exact_config_without_mutating_environment(self) -> None:
        environ = {
            "FORMOWL_OAUTH_ISSUER": self.base["issuer"],
            "FORMOWL_MCP_RESOURCE": self.base["resource"],
            "FORMOWL_CHATGPT_CLIENT_ID": self.base["chatgpt_client_id"],
            "FORMOWL_CHATGPT_REDIRECT_URI": self.base["chatgpt_redirect_uri"],
            "FORMOWL_GOOGLE_CLIENT_ID": self.base["google_client_id"],
            "FORMOWL_GOOGLE_CLIENT_SECRET": self.base["google_client_secret"],
            "FORMOWL_GOOGLE_REDIRECT_URI": self.base["google_redirect_uri"],
            "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY": self.base["state_encryption_key"],
            "FORMOWL_OAUTH_ALLOW_LOOPBACK_HTTP": "1",
        }
        snapshot = dict(environ)

        config = OAuthBridgeConfig.from_env(environ)

        self.assertEqual(config.issuer, self.base["issuer"])
        self.assertEqual(config.resource, self.base["resource"])
        self.assertEqual(config.chatgpt_client_id, self.base["chatgpt_client_id"])
        self.assertEqual(config.google_client_id, self.base["google_client_id"])
        self.assertTrue(config.allow_loopback_http)
        self.assertEqual(environ, snapshot)

    def test_from_env_missing_values_fail_closed_without_mutating_environment(self) -> None:
        environ = {
            "FORMOWL_OAUTH_ISSUER": self.base["issuer"],
            "FORMOWL_MCP_RESOURCE": self.base["resource"],
            "FORMOWL_CHATGPT_CLIENT_ID": self.base["chatgpt_client_id"],
            "FORMOWL_CHATGPT_REDIRECT_URI": self.base["chatgpt_redirect_uri"],
            "FORMOWL_GOOGLE_CLIENT_ID": self.base["google_client_id"],
            "FORMOWL_GOOGLE_CLIENT_SECRET": self.base["google_client_secret"],
            "FORMOWL_GOOGLE_REDIRECT_URI": self.base["google_redirect_uri"],
            "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY": self.base["state_encryption_key"],
        }
        missing_names = tuple(sorted(environ))
        for env_name in missing_names:
            with self.subTest(env_name=env_name):
                incomplete = {**environ, env_name: ""}
                snapshot = dict(incomplete)

                with self.assertRaises(ContractValidationError) as caught:
                    OAuthBridgeConfig.from_env(incomplete)

                self.assertEqual(
                    str(caught.exception),
                    f'OAuth configuration is incomplete: ["{env_name}"]',
                )
                self.assertEqual(incomplete, snapshot)

    def test_from_env_errors_and_repr_do_not_expose_environment_secrets(self) -> None:
        google_secret = "google-client-secret-must-remain-private"
        environ = {
            "FORMOWL_OAUTH_ISSUER": self.base["issuer"],
            "FORMOWL_MCP_RESOURCE": self.base["resource"],
            "FORMOWL_CHATGPT_CLIENT_ID": self.base["chatgpt_client_id"],
            "FORMOWL_CHATGPT_REDIRECT_URI": self.base["chatgpt_redirect_uri"],
            "FORMOWL_GOOGLE_CLIENT_ID": self.base["google_client_id"],
            "FORMOWL_GOOGLE_CLIENT_SECRET": google_secret,
            "FORMOWL_GOOGLE_REDIRECT_URI": self.base["google_redirect_uri"],
            "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY": self.base["state_encryption_key"],
        }

        config = OAuthBridgeConfig.from_env(environ)
        rendered_config = repr(config)
        self.assertNotIn(google_secret, rendered_config)
        self.assertNotIn(self.base["state_encryption_key"], rendered_config)

        invalid_state_key = "invalid-state-encryption-key-must-remain-private"
        with self.assertRaises(ContractValidationError) as caught:
            OAuthBridgeConfig.from_env(
                {
                    **environ,
                    "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY": invalid_state_key,
                }
            )
        rendered_error = str(caught.exception)
        self.assertNotIn(google_secret, rendered_error)
        self.assertNotIn(invalid_state_key, rendered_error)
        self.assertEqual(rendered_error, "OAuth state encryption key is invalid")

    def test_chatgpt_callback_shape_and_reserved_sentinel_matrix(self) -> None:
        valid_callbacks = (
            "https://chatgpt.com/connector/oauth/a",
            "https://chatgpt.com/connector/oauth/opaque-id_01",
            "https://chatgpt.com/connector/oauth/AZaz09._~-",
        )
        for callback in valid_callbacks:
            with self.subTest(valid=callback):
                config = OAuthBridgeConfig(**{**self.base, "chatgpt_redirect_uri": callback})
                self.assertEqual(config.chatgpt_callback_mode, "production_exact")

        discovery = OAuthBridgeConfig(
            **{
                **self.base,
                "chatgpt_redirect_uri": CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
            }
        )
        self.assertEqual(discovery.chatgpt_callback_mode, "discovery_only")

        invalid_client_ids = (
            "formowl-discovery-only",
            "formowl-chatgpt-replace-with-deployment-id",
            " leading-space",
            "trailing-space ",
            "contains/slash",
            "contains\nnewline",
            "",
        )
        for client_id in invalid_client_ids:
            for callback in (
                CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
                "https://chatgpt.com/connector/oauth/callback",
            ):
                with self.subTest(client_id=client_id, callback=callback):
                    with self.assertRaisesRegex(
                        ContractValidationError,
                        "client ids are required",
                    ):
                        OAuthBridgeConfig(
                            **{
                                **self.base,
                                "chatgpt_client_id": client_id,
                                "chatgpt_redirect_uri": callback,
                            }
                        )

        invalid_callbacks = (
            "https://attacker.example/callback",
            "https://invalid.example.invalid/other",
            "https://other.invalid/formowl-discovery-only",
            "https://invalid.example.invalid/formowl-discovery-only/",
            "https://invalid.example.invalid/formowl-discovery-only?mode=1",
            "https://chatgpt.com/connector/oauth/",
            "https://chatgpt.com/connector/oauth/one/two",
            "https://chatgpt.com/connector/oauth/%2F",
            "https://chatgpt.com/connector/oauth/.",
            "https://chatgpt.com/connector/oauth/..",
            "https://chatgpt.com:443/connector/oauth/callback",
            "https://user@chatgpt.com/connector/oauth/callback",
            "https://CHATGPT.com/connector/oauth/callback",
            "https://chatgpt.com/oauth/callback",
            "https://chatgpt.com/connector/oauth/callback?tenant=one",
            "https://chatgpt.com/connector/oauth/callback#fragment",
        )
        for callback in invalid_callbacks:
            with self.subTest(invalid=callback):
                with self.assertRaises(ContractValidationError):
                    OAuthBridgeConfig(
                        **{
                            **self.base,
                            "chatgpt_redirect_uri": callback,
                            "allow_loopback_http": True,
                        }
                    )

    def test_invalid_url_and_clock_skew_matrix_leaves_repository_unchanged(self) -> None:
        repository = TransactionAwareMemoryRepository()
        snapshot = repository.snapshot_bytes()
        cases = (
            ({"issuer": "https://auth.example.test/tenant"}, "issuer_path"),
            ({"issuer": "https://auth.example.test/"}, "issuer_trailing_slash"),
            ({"issuer": "https://auth.example.test?tenant=one"}, "issuer_query"),
            ({"resource": "https://auth.example.test/not-mcp"}, "resource_path"),
            ({"resource": "https://auth.example.test/mcp?tenant=one"}, "resource_query"),
            (
                {"google_redirect_uri": ("https://auth.example.test/oauth/google/other")},
                "google_callback_path",
            ),
            (
                {
                    "google_redirect_uri": (
                        "https://auth.example.test/oauth/google/callback?tenant=one"
                    )
                },
                "google_callback_query",
            ),
            (
                {
                    "chatgpt_redirect_uri": (
                        "https://chatgpt.com/connector/oauth/callback?tenant=one"
                    )
                },
                "chatgpt_query",
            ),
            (
                {"chatgpt_redirect_uri": ("https://chatgpt.com/connector/oauth/callback#fragment")},
                "chatgpt_fragment",
            ),
            (
                {"chatgpt_redirect_uri": "https://chatgpt.com/connector/oauth/*"},
                "chatgpt_wildcard",
            ),
            ({"clock_skew_seconds": 301}, "clock_skew_oversized"),
            ({"clock_skew_seconds": -1}, "clock_skew_negative"),
            ({"clock_skew_seconds": True}, "clock_skew_bool"),
            (
                {
                    "issuer": "http://127.0.0.1:8765",
                    "allow_loopback_http": "yes",
                },
                "loopback_flag_not_bool",
            ),
        )
        for overrides, label in cases:
            with self.subTest(label=label):
                with self.assertRaises(ContractValidationError):
                    OAuthBridgeConfig(**{**self.base, **overrides})
                repository.assert_unchanged(snapshot)

    def test_metadata_properties_and_starlette_routes_are_exact(self) -> None:
        fixture = BridgeFixture(
            generate_ephemeral_formowl_signing_key(kid="config-route-key"),
            seed="config-route-exactness",
        )
        config = fixture.config
        self.assertEqual(
            config.protected_resource_metadata_url,
            f"{config.issuer}/.well-known/oauth-protected-resource",
        )
        self.assertEqual(
            config.authorization_server_metadata_url,
            f"{config.issuer}/.well-known/oauth-authorization-server",
        )
        self.assertEqual(config.authorization_endpoint, f"{config.issuer}/oauth/authorize")
        self.assertEqual(config.token_endpoint, f"{config.issuer}/oauth/token")
        self.assertEqual(config.jwks_uri, f"{config.issuer}/.well-known/jwks.json")

        protected = protected_resource_metadata(config)
        server = authorization_server_metadata(config)
        self.assertEqual(protected["resource"], f"{config.issuer}/mcp")
        self.assertEqual(protected["authorization_servers"], [config.issuer])
        self.assertEqual(server["authorization_endpoint"], config.authorization_endpoint)
        self.assertEqual(server["token_endpoint"], config.token_endpoint)
        self.assertEqual(server["jwks_uri"], config.jwks_uri)
        self.assertEqual(
            [
                route.path
                for route in oauth_routes(
                    bridge=fixture.bridge,
                    config=config,
                    google_client=fixture.google_client,  # type: ignore[arg-type]
                    clock=fixture.clock.now,
                )
            ],
            [
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-authorization-server",
                "/oauth/authorize",
                "/oauth/google/callback",
                "/oauth/token",
                "/.well-known/jwks.json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
