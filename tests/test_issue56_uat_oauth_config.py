from __future__ import annotations

import unittest

from cryptography.fernet import Fernet
from formowl_contract import ContractValidationError

import _paths  # noqa: F401
from formowl_auth import OAuthBridgeConfig


class Issue56UatOAuthConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = {
            "issuer": "https://auth.example.test",
            "resource": "https://auth.example.test/mcp",
            "chatgpt_client_id": "chatgpt-client",
            "chatgpt_redirect_uri": "https://uat.example.test/oauth/callback",
            "google_client_id": "google-client",
            "google_client_secret": "google-secret",
            "google_redirect_uri": "https://auth.example.test/oauth/google/callback",
            "state_encryption_key": Fernet.generate_key().decode("ascii"),
        }

    def test_default_rejects_standalone_https_redirect(self) -> None:
        with self.assertRaises(ContractValidationError):
            OAuthBridgeConfig(**self.base)

    def test_opt_in_accepts_exact_standalone_https_redirect(self) -> None:
        environ = {
            "FORMOWL_OAUTH_ISSUER": self.base["issuer"],
            "FORMOWL_MCP_RESOURCE": self.base["resource"],
            "FORMOWL_CHATGPT_CLIENT_ID": self.base["chatgpt_client_id"],
            "FORMOWL_CHATGPT_REDIRECT_URI": self.base["chatgpt_redirect_uri"],
            "FORMOWL_GOOGLE_CLIENT_ID": self.base["google_client_id"],
            "FORMOWL_GOOGLE_CLIENT_SECRET": self.base["google_client_secret"],
            "FORMOWL_GOOGLE_REDIRECT_URI": self.base["google_redirect_uri"],
            "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY": self.base["state_encryption_key"],
            "FORMOWL_OAUTH_ALLOW_STANDALONE_UAT_HTTPS_REDIRECT": "1",
        }

        config = OAuthBridgeConfig.from_env(environ)

        self.assertTrue(config.allow_standalone_uat_https_redirect)
        self.assertEqual(config.chatgpt_redirect_uri, self.base["chatgpt_redirect_uri"])
        self.assertEqual(config.chatgpt_callback_mode, "standalone_uat_exact")
        self.assertTrue(config.to_public_dict()["allow_standalone_uat_https_redirect"])

    def test_opt_in_still_rejects_wildcard_and_query(self) -> None:
        for redirect_uri in (
            "https://uat.example.test/oauth/*",
            "https://uat.example.test/oauth/callback?mode=uat",
        ):
            with self.subTest(redirect_uri=redirect_uri):
                with self.assertRaises(ContractValidationError):
                    OAuthBridgeConfig(
                        **{
                            **self.base,
                            "chatgpt_redirect_uri": redirect_uri,
                            "allow_standalone_uat_https_redirect": True,
                        }
                    )


if __name__ == "__main__":
    unittest.main()
