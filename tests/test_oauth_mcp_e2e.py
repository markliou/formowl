from __future__ import annotations

import copy
import inspect
from typing import Any
import unittest

import _paths  # noqa: F401
from oauth_harness import (
    AsgiHttpServer,
    DeterministicRng,
    DeterministicRsaKey,
    FakeClock,
    FakeGoogleOidcProvider,
    HttpClient,
    TransactionAwareMemoryRepository,
    _audit_lineage_is_complete,
    run_issue20_deterministic_e2e,
    sha256_json,
)


class OAuthMcpHarnessPrimitiveTests(unittest.TestCase):
    def test_official_mcp_client_api_and_protocol_constants_match_harness_contract(
        self,
    ) -> None:
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared.version import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS

        parameters = inspect.signature(streamable_http_client).parameters

        self.assertIn("http_client", parameters)
        self.assertNotIn("headers", parameters)
        self.assertEqual(LATEST_PROTOCOL_VERSION, "2025-11-25")
        self.assertIn(LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS)

    def test_asgi_http_server_runs_lifespan_and_http_on_one_background_loop(self) -> None:
        lifecycle: list[str] = []

        def app_factory(_base_url: str):
            async def app(scope, receive, send):
                if scope["type"] == "lifespan":
                    while True:
                        message = await receive()
                        if message["type"] == "lifespan.startup":
                            lifecycle.append("startup")
                            scope["state"]["ready"] = True
                            await send({"type": "lifespan.startup.complete"})
                        elif message["type"] == "lifespan.shutdown":
                            lifecycle.append("shutdown")
                            await send({"type": "lifespan.shutdown.complete"})
                            return
                self.assertTrue(scope["state"]["ready"])
                await receive()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"ready":true}',
                    }
                )

            return app

        with AsgiHttpServer(app_factory) as server:
            response = HttpClient().get(f"{server.base_url}/health")
            self.assertEqual(lifecycle, ["startup"])
            self.assertEqual(response.status, 200)
            self.assertEqual(response.json(), {"ready": True})
            self.assertEqual(
                server.request_history,
                [{"method": "GET", "path": "/health", "status": 200}],
            )

        self.assertEqual(lifecycle, ["startup", "shutdown"])

    def test_http_client_returns_responses_for_success_and_http_error(self) -> None:
        clock = FakeClock()
        key = DeterministicRsaKey.generate(
            "formowl-issue20-http-client-key",
            kid="http-client-key-1",
        )
        rng = DeterministicRng("formowl-issue20-http-client")

        with FakeGoogleOidcProvider(clock=clock, rng=rng, signing_key=key) as google:
            http = HttpClient()
            success = http.get(google.discovery_url)
            error = http.get(f"{google.base_url}/missing")

        self.assertEqual(success.status, 200)
        self.assertEqual(error.status, 404)
        self.assertIsInstance(success.body, bytes)
        self.assertIsInstance(error.body, bytes)

    def test_fake_google_jwks_and_authorization_use_real_http_with_synthetic_data(self) -> None:
        clock = FakeClock()
        key = DeterministicRsaKey.generate(
            "formowl-issue20-fake-google-key",
            kid="fake-google-key-1",
        )
        rng = DeterministicRng("formowl-issue20-fake-google-http")

        with FakeGoogleOidcProvider(clock=clock, rng=rng, signing_key=key) as google:
            http = HttpClient()
            discovery = http.get(google.discovery_url)
            jwks = http.get(google.jwks_uri)

        self.assertEqual(discovery.status, 200)
        self.assertEqual(discovery.json()["issuer"], google.issuer)
        self.assertEqual(jwks.status, 200)
        public_key = jwks.json()["keys"][0]
        self.assertEqual(public_key["kid"], "fake-google-key-1")
        self.assertEqual(public_key["alg"], "RS256")
        self.assertNotIn("d", public_key)
        self.assertNotIn("p", public_key)
        self.assertNotIn("q", public_key)

    def test_transaction_repository_failure_injection_restores_exact_snapshot(self) -> None:
        repository = TransactionAwareMemoryRepository()
        repository.put("users", "user_1", {"status": "active"}, operation="seed_user")
        baseline = repository.snapshot_bytes()
        repository.inject_failure_at(2)

        with self.assertRaises(RuntimeError):
            with repository.transaction():
                repository.put(
                    "external_identities",
                    "identity_1",
                    {"user_id": "user_1"},
                    operation="write_external_identity",
                )
                repository.put(
                    "audit",
                    "audit_1",
                    {"action": "identity_created"},
                    operation="write_audit",
                )

        repository.assert_unchanged(baseline)

    def test_audit_lineage_requires_every_identity_token_tool_and_upload_link(self) -> None:
        fixture = _valid_audit_lineage_fixture()

        self.assertTrue(_validate_lineage_fixture(fixture))

        mutations = (
            (
                "invitation_actor_not_service",
                lambda item: _first_audit_row(
                    item["rows"],
                    action="oauth_invitation_create",
                    target_id="invite_1",
                ).__setitem__("actor_type", "user"),
            ),
            (
                "invitation_approval_missing",
                lambda item: _first_audit_row(
                    item["rows"],
                    action="oauth_invitation_create",
                    target_id="invite_1",
                )["metadata"].__setitem__("approval_user_id", None),
            ),
            ("missing_external_identity", lambda item: item["external_identities"].clear()),
            (
                "identity_user_mismatch",
                lambda item: item["external_identities"][0].__setitem__("user_id", "user_other"),
            ),
            (
                "client_identity_mismatch",
                lambda item: item["client_authorizations"][0].__setitem__(
                    "external_identity_id", "identity_other"
                ),
            ),
            (
                "token_authorization_mismatch",
                lambda item: item["token_sessions"][0].__setitem__(
                    "oauth_client_authorization_id", "clientauth_other"
                ),
            ),
            (
                "missing_request_id",
                lambda item: _first_audit_row(
                    item["rows"],
                    action="mcp_authorization_allowed",
                    target_id="open_upload_session",
                ).__setitem__("request_id", None),
            ),
            (
                "denied_workspace_mismatch",
                lambda item: _first_audit_row(
                    item["rows"],
                    action="mcp_authorization_denied",
                    target_id="open_upload_session",
                ).__setitem__("workspace_id", "workspace_other"),
            ),
            (
                "upload_session_mismatch",
                lambda item: item["upload_calls"][0].__setitem__("session_id", "oauthsid_other"),
            ),
            (
                "upload_authorization_binding_mismatch",
                lambda item: item["upload_audit_rows"][0].__setitem__(
                    "authorization_tool_call_id", "mcp_call_other"
                ),
            ),
            (
                "tool_log_audit_reference_mismatch",
                lambda item: item["tool_call_logs"][0].__setitem__("audit_log_id", "audit_other"),
            ),
            (
                "tool_log_arguments_hash_mismatch",
                lambda item: item["tool_call_logs"][0].__setitem__(
                    "arguments_hash", "sha256:" + "a" * 64
                ),
            ),
            (
                "tool_log_response_hash_mismatch",
                lambda item: item["tool_call_logs"][0].__setitem__(
                    "response_hash", "sha256:" + "b" * 64
                ),
            ),
            (
                "missing_workspace_denial",
                lambda item: item["rows"].remove(
                    _first_audit_row(
                        item["rows"],
                        action="mcp_authorization_denied",
                        target_id="open_upload_session",
                    )
                ),
            ),
        )

        for name, mutate in mutations:
            with self.subTest(name=name):
                invalid = copy.deepcopy(fixture)
                mutate(invalid)
                self.assertFalse(_validate_lineage_fixture(invalid))


class OAuthMcpEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = run_issue20_deterministic_e2e()

    def test_oauth_discovery_and_challenges_match_protected_resource(self) -> None:
        self.assertTrue(self.evidence["metadata_and_jwks_verified"])
        self.assertTrue(self.evidence["protocol_negotiation_verified"])
        self.assertTrue(self.evidence["unauthenticated_challenges_verified"])
        self.assertTrue(self.evidence["bearer_streamable_http_mcp_verified"])
        self.assertGreaterEqual(self.evidence["http_exchange_count"], 10)

    def test_remote_http_invited_user_reconnect_revocation_and_workspace_boundary(
        self,
    ) -> None:
        for key in (
            "authorization_code_pkce_flow_verified",
            "google_identity_mapping_verified",
            "bearer_streamable_http_mcp_verified",
            "whoami_verified",
            "allowed_workspace_upload_session_verified",
            "cross_workspace_and_forgery_denied",
            "revocation_immediate",
            "same_subject_reconnect_verified",
            "audit_lineage_verified",
        ):
            with self.subTest(key=key):
                self.assertTrue(self.evidence[key])

    def test_oauth_negative_matrix_fails_closed_without_partial_state_or_leaks(self) -> None:
        self.assertTrue(self.evidence["negative_matrix_verified"])
        self.assertTrue(self.evidence["leak_scan_verified"])
        self.assertGreaterEqual(self.evidence["negative_case_count"], 20)

    def test_every_repository_write_and_audit_failure_rolls_back_byte_for_byte(self) -> None:
        self.assertTrue(self.evidence["rollback_matrix_verified"])
        self.assertGreaterEqual(self.evidence["rollback_case_count"], 1)

    def test_account_switch_requires_independent_invitation_and_membership(self) -> None:
        self.assertTrue(self.evidence["different_subject_isolated"])

    def test_runtime_and_public_reports_do_not_log_oauth_query_or_credentials(self) -> None:
        self.assertTrue(self.evidence["runtime_log_leak_scan_verified"])
        self.assertTrue(self.evidence["leak_scan_verified"])


def _validate_lineage_fixture(fixture: dict[str, Any]) -> bool:
    return _audit_lineage_is_complete(
        fixture["rows"],
        external_identities=fixture["external_identities"],
        client_authorizations=fixture["client_authorizations"],
        token_sessions=fixture["token_sessions"],
        upload_calls=fixture["upload_calls"],
        upload_results=fixture["upload_results"],
        upload_envelopes=fixture["upload_envelopes"],
        upload_audit_rows=fixture["upload_audit_rows"],
        tool_call_logs=fixture["tool_call_logs"],
        expected_user_id="user_1",
        expected_client_id="chatgpt_client",
        expected_workspace_id="workspace_1",
    )


def _valid_audit_lineage_fixture() -> dict[str, Any]:
    rows = [
        {
            **_audit_row(
                "oauth_invitation_create",
                actor_user_id=None,
                target_id="invite_1",
                session_id="invite_1",
            ),
            "actor_type": "service",
            "actor_service_id": "operator_service_1",
            "workspace_id": "workspace_1",
            "status": "ok",
            "reason_code": "invitation_created",
            "metadata": {
                "event_stage": "invitation",
                "lineage_source": "owner_approval",
                "approval_user_id": "user_admin",
            },
        },
        _audit_row(
            "oauth_authorization_started",
            actor_user_id=None,
            target_id="transaction_1",
            session_id="transaction_1",
            oauth_client_id="chatgpt_client",
        ),
        _audit_row(
            "oauth_authorization_started",
            actor_user_id=None,
            target_id="transaction_2",
            session_id="transaction_2",
            oauth_client_id="chatgpt_client",
        ),
    ]
    for action in (
        "oauth_external_identity_created",
        "oauth_invitation_accepted",
        "google_authentication_succeeded",
        "oauth_authorization_code_issued",
    ):
        rows.append(_identity_audit_row(action))
    for token_session_id in ("oauthsid_1", "oauthsid_2"):
        rows.append(_token_audit_row("oauth_token_session_issued", token_session_id))
        rows.append(_token_audit_row("oauth_token_session_revoked", token_session_id))
    rows.extend(
        [
            _mcp_decision_row(
                allowed=True,
                target_id="whoami",
                token_session_id="oauthsid_1",
                request_id="mcp_req_1",
                tool_call_id="mcp_call_1",
            ),
            _mcp_decision_row(
                allowed=True,
                target_id="open_upload_session",
                token_session_id="oauthsid_1",
                request_id="mcp_req_2",
                tool_call_id="mcp_call_2",
            ),
            _mcp_decision_row(
                allowed=False,
                target_id="open_upload_session",
                token_session_id="oauthsid_1",
                request_id="mcp_req_3",
                tool_call_id="mcp_call_3",
            ),
            _mcp_decision_row(
                allowed=False,
                target_id="open_upload_session",
                token_session_id="oauthsid_1",
                request_id="mcp_req_4",
                tool_call_id="mcp_call_4",
            ),
            _mcp_decision_row(
                allowed=True,
                target_id="whoami",
                token_session_id="oauthsid_2",
                request_id="mcp_req_5",
                tool_call_id="mcp_call_5",
            ),
        ]
    )
    upload_call = {
        "requester_user_id": "user_1",
        "workspace_id": "workspace_1",
        "owner_scope_type": "workspace",
        "owner_scope_id": "workspace_1",
        "session_id": "oauthsid_1",
    }
    upload_result = {
        "upload_session_id": "upload_1",
        "status": "ok",
        "audit_ref": "audit_upload_1",
    }
    upload_envelope = {
        "result_type": "upload_session_request",
        "status": "ok",
        "data": upload_result,
    }
    return {
        "rows": rows,
        "external_identities": [
            {
                "external_identity_id": "identity_1",
                "provider": "google",
                "user_id": "user_1",
                "status": "active",
            }
        ],
        "client_authorizations": [
            {
                "oauth_client_authorization_id": "clientauth_1",
                "client_id": "chatgpt_client",
                "external_identity_id": "identity_1",
                "user_id": "user_1",
                "default_workspace_id": "workspace_1",
                "revoked_at": None,
            }
        ],
        "token_sessions": [
            {
                "token_session_id": "oauthsid_1",
                "user_id": "user_1",
                "external_identity_id": "identity_1",
                "oauth_client_authorization_id": "clientauth_1",
                "client_id": "chatgpt_client",
                "current_workspace_id": "workspace_1",
                "revoked_at": "2026-07-12T04:01:00+00:00",
            },
            {
                "token_session_id": "oauthsid_2",
                "user_id": "user_1",
                "external_identity_id": "identity_1",
                "oauth_client_authorization_id": "clientauth_1",
                "client_id": "chatgpt_client",
                "current_workspace_id": "workspace_1",
                "revoked_at": "2026-07-12T04:02:00+00:00",
            },
        ],
        "upload_calls": [upload_call],
        "upload_results": [upload_result],
        "upload_envelopes": [upload_envelope],
        "upload_audit_rows": [
            {
                "audit_log_id": "audit_upload_1",
                "action": "upload_session_created",
                "actor_user_id": "user_1",
                "target_id": "upload_1",
                "session_id": "oauthsid_1",
                "workspace_id": "workspace_1",
                "status": "ok",
                "authorization_request_id": "mcp_req_2",
                "authorization_tool_call_id": "mcp_call_2",
                "evidence_mode": "deterministic_fake_upload_recorder",
            }
        ],
        "tool_call_logs": [
            {
                "tool_name": "open_upload_session",
                "audit_log_id": "audit_upload_1",
                "status": "ok",
                "arguments_hash": sha256_json(upload_call),
                "response_hash": sha256_json(upload_envelope),
            }
        ],
    }


def _audit_row(
    action: str,
    *,
    actor_user_id: str | None = "user_admin",
    target_id: str = "target_1",
    session_id: str = "session_1",
    oauth_client_id: str | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "actor_user_id": actor_user_id,
        "target_id": target_id,
        "session_id": session_id,
        "oauth_client_id": oauth_client_id,
        "reason_code": action,
        "timestamp": "2026-07-12T04:00:00+00:00",
    }


def _identity_audit_row(action: str) -> dict[str, Any]:
    return {
        **_audit_row(action, actor_user_id="user_1"),
        "external_identity_id": "identity_1",
        "oauth_client_id": "chatgpt_client",
        "workspace_id": "workspace_1",
    }


def _token_audit_row(action: str, token_session_id: str) -> dict[str, Any]:
    return {
        **_identity_audit_row(action),
        "target_id": token_session_id,
        "session_id": token_session_id,
        "oauth_token_session_id": token_session_id,
    }


def _mcp_decision_row(
    *,
    allowed: bool,
    target_id: str,
    token_session_id: str,
    request_id: str,
    tool_call_id: str,
) -> dict[str, Any]:
    return {
        **_token_audit_row(
            "mcp_authorization_allowed" if allowed else "mcp_authorization_denied",
            token_session_id,
        ),
        "target_type": "mcp_tool",
        "target_id": target_id,
        "request_id": request_id,
        "tool_call_id": tool_call_id,
        "reason_code": "tool_authorized" if allowed else "invalid_tool_arguments",
        "status": "ok" if allowed else "permission_denied",
        "metadata": {"workspace_decision": "allowed" if allowed else "denied"},
    }


def _first_audit_row(
    rows: list[dict[str, Any]],
    *,
    action: str,
    target_id: str,
) -> dict[str, Any]:
    return next(
        row for row in rows if row.get("action") == action and row.get("target_id") == target_id
    )


if __name__ == "__main__":
    unittest.main()
