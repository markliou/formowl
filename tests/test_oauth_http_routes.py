from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlencode, urlparse
import asyncio
import json
import unittest

from starlette.testclient import TestClient

import _paths  # noqa: F401
from formowl_auth import (
    CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
    OAuthAccessDenied,
)
from formowl_auth.http import _aware_now, create_oauth_asgi_app, oauth_routes
from oauth_harness import generate_ephemeral_formowl_signing_key
from test_oauth_bridge_service import BridgeFixture


class DetachedTimezone(tzinfo):
    def utcoffset(self, value: datetime | None) -> timedelta | None:
        del value
        return None


class OAuthHttpRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.signing_key = generate_ephemeral_formowl_signing_key(kid="http-test-key")

    def fixture(
        self,
        *,
        seed: str = "oauth-http",
        chatgpt_client_id: str = "chatgpt-client",
        chatgpt_redirect_uri: str = "https://chatgpt.com/connector/oauth/callback",
    ) -> BridgeFixture:
        return BridgeFixture(
            self.signing_key,
            seed=seed,
            chatgpt_client_id=chatgpt_client_id,
            chatgpt_redirect_uri=chatgpt_redirect_uri,
        )

    def client(self, fixture: BridgeFixture) -> TestClient:
        return TestClient(
            create_oauth_asgi_app(
                bridge=fixture.bridge,
                config=fixture.config,
                google_client=fixture.google_client,  # type: ignore[arg-type]
                clock=fixture.clock.now,
            )
        )

    def test_aware_now_rejects_detached_timezone_clock(self) -> None:
        detached_now = datetime(2026, 7, 14, 4, 0, tzinfo=DetachedTimezone())

        with self.assertRaisesRegex(RuntimeError, "timezone-aware"):
            _aware_now(lambda: detached_now)

    def test_route_dependencies_must_match_the_bridge_instances(self) -> None:
        fixture = self.fixture(seed="route-dependency-owner")
        other = self.fixture(
            seed="route-dependency-other",
            chatgpt_redirect_uri="https://chatgpt.com/connector/oauth/other-callback",
        )
        fixture_snapshot = fixture.repository.snapshot_bytes()
        other_snapshot = other.repository.snapshot_bytes()

        with self.assertRaisesRegex(ValueError, "share one bridge configuration"):
            oauth_routes(
                bridge=fixture.bridge,
                config=other.config,
                google_client=fixture.google_client,  # type: ignore[arg-type]
                clock=fixture.clock.now,
            )
        with self.assertRaisesRegex(ValueError, "share one bridge configuration"):
            oauth_routes(
                bridge=fixture.bridge,
                config=fixture.config,
                google_client=other.google_client,  # type: ignore[arg-type]
                clock=fixture.clock.now,
            )
        fixture.repository.assert_unchanged(fixture_snapshot)
        other.repository.assert_unchanged(other_snapshot)
        self.assertEqual(fixture.repository.write_operations, [])
        self.assertEqual(other.repository.write_operations, [])

    def test_route_set_metadata_jwks_and_urls_are_exact_and_host_independent(self) -> None:
        fixture = self.fixture()
        routes = oauth_routes(
            bridge=fixture.bridge,
            config=fixture.config,
            google_client=fixture.google_client,  # type: ignore[arg-type]
            clock=fixture.clock.now,
        )
        self.assertEqual(
            [route.path for route in routes],
            [
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-authorization-server",
                "/oauth/authorize",
                "/oauth/google/callback",
                "/oauth/token",
                "/.well-known/jwks.json",
            ],
        )
        self.assertFalse(any("bootstrap" in route.path for route in routes))

        with self.client(fixture) as client:
            protected = client.get(
                "/.well-known/oauth-protected-resource",
                headers={"host": "evil.example"},
            )
            server = client.get(
                "/.well-known/oauth-authorization-server",
                headers={"host": "evil.example"},
            )
            jwks = client.get("/.well-known/jwks.json", headers={"host": "evil.example"})

        self.assertEqual(protected.status_code, 200)
        self.assertEqual(protected.json()["resource"], fixture.config.resource)
        self.assertEqual(
            protected.json()["authorization_servers"],
            [fixture.config.issuer],
        )
        self.assertEqual(server.json()["issuer"], fixture.config.issuer)
        self.assertEqual(
            server.json()["authorization_endpoint"], fixture.config.authorization_endpoint
        )
        self.assertEqual(server.json()["token_endpoint"], fixture.config.token_endpoint)
        self.assertEqual(server.json()["jwks_uri"], fixture.config.jwks_uri)
        self.assertNotIn("evil.example", protected.text + server.text + jwks.text)
        self.assertEqual(jwks.status_code, 200)
        self.assertEqual(jwks.json()["keys"][0]["kid"], "http-test-key")
        self.assertEqual(protected.headers["referrer-policy"], "no-referrer")

    def test_full_http_authorization_callback_and_token_exchange(self) -> None:
        fixture = self.fixture()
        fixture.seed_owner()
        fixture.seed_invitation()

        with self.client(fixture) as client:
            authorize = client.get(
                "/oauth/authorize",
                params=fixture.authorization_request(),
                follow_redirects=False,
            )
            self.assertEqual(authorize.status_code, 302)
            self.assertTrue(
                authorize.headers["location"].startswith("https://accounts.google.test/")
            )
            self.assertEqual(authorize.headers["referrer-policy"], "no-referrer")
            self.assertEqual(authorize.headers["cache-control"], "no-store")

            callback = client.get(
                "/oauth/google/callback",
                params={"state": fixture.google_client.last_state, "code": "google-code"},
                follow_redirects=False,
            )
            self.assertEqual(callback.status_code, 302)
            callback_url = urlparse(callback.headers["location"])
            configured = urlparse(fixture.config.chatgpt_redirect_uri)
            self.assertEqual(
                (callback_url.scheme, callback_url.netloc, callback_url.path),
                (configured.scheme, configured.netloc, configured.path),
            )
            callback_query = parse_qs(callback_url.query)
            self.assertEqual(callback_query["state"], ["chatgpt-state"])
            authorization_code = callback_query["code"][0]

            token = client.post(
                "/oauth/token",
                data=fixture.token_request(authorization_code),
            )

        self.assertEqual(token.status_code, 200)
        self.assertEqual(token.json()["token_type"], "Bearer")
        self.assertEqual(token.json()["scope"], "formowl.use")
        self.assertEqual(token.json()["resource"], fixture.config.resource)
        self.assertEqual(token.headers["cache-control"], "no-store")
        self.assertEqual(token.headers["pragma"], "no-cache")
        self.assertEqual(token.headers["referrer-policy"], "no-referrer")
        self.assertNotIn("google-code", token.text)

    def test_discovery_only_http_is_no_write_and_exact_restart_restores_oauth(self) -> None:
        discovery = self.fixture(
            seed="oauth-http-discovery-only",
            chatgpt_redirect_uri=CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
        )
        discovery_snapshot = discovery.repository.snapshot_bytes()
        with self.client(discovery) as client:
            metadata = client.get("/.well-known/oauth-protected-resource")
            authorize = client.get(
                "/oauth/authorize",
                params=discovery.authorization_request(),
                follow_redirects=False,
            )
            callback = client.get(
                "/oauth/google/callback",
                params={"state": "discovery-state", "code": "discovery-code"},
                follow_redirects=False,
            )
            token = client.post(
                "/oauth/token",
                data=discovery.token_request("discovery-authorization-code"),
            )

        self.assertEqual(metadata.status_code, 200)
        for response in (authorize, callback, token):
            self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(response.json(), {"error": "access_denied"})
            self.assertNotIn("location", response.headers)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn(CHATGPT_DISCOVERY_ONLY_REDIRECT_URI, response.text)
        discovery.repository.assert_unchanged(discovery_snapshot)
        self.assertEqual(discovery.repository.write_operations, [])

        production = self.fixture(seed="oauth-http-after-discovery")
        production.seed_owner()
        production.seed_invitation()
        with self.client(production) as client:
            authorize = client.get(
                "/oauth/authorize",
                params=production.authorization_request(),
                follow_redirects=False,
            )
            callback = client.get(
                "/oauth/google/callback",
                params={
                    "state": production.google_client.last_state,
                    "code": "google-code-after-discovery",
                },
                follow_redirects=False,
            )
            authorization_code = parse_qs(urlparse(callback.headers["location"]).query)["code"][0]
            token = client.post(
                "/oauth/token",
                data=production.token_request(authorization_code),
            )

        self.assertEqual(authorize.status_code, 302)
        self.assertEqual(callback.status_code, 302)
        self.assertEqual(token.status_code, 200, token.text)
        self.assertEqual(token.json()["resource"], production.config.resource)

    def test_google_authorization_denial_redirects_generic_error_and_ignores_upstream_detail(
        self,
    ) -> None:
        fixture = self.fixture(seed="http-google-authorization-denial")
        fixture.seed_owner()
        fixture.seed_invitation()
        client_state = "private-chatgpt-client-state"
        state = fixture.start_authorization(client_state=client_state)
        protected_tables = (
            "users",
            "workspace_members",
            "oauth_invitations",
            "external_identities",
            "oauth_client_authorizations",
            "oauth_authorization_codes",
            "oauth_token_sessions",
        )
        protected_before = {table: fixture.repository.list(table) for table in protected_tables}
        audit_before = fixture.repository.audit_event_count
        audit_ids_before = {audit["audit_log_id"] for audit in fixture.repository.list("audit_log")}

        with self.client(fixture) as client:
            response = client.get(
                "/oauth/google/callback",
                params={
                    "error": "private_upstream_error",
                    "error_description": "private upstream account detail",
                    "error_uri": "https://evil.example/private-error",
                    "state": state,
                },
                follow_redirects=False,
            )
            denial_audits = [
                audit
                for audit in fixture.repository.list("audit_log")
                if audit["audit_log_id"] not in audit_ids_before
            ]
            self.assertEqual(len(denial_audits), 1)
            denial_audit = denial_audits[0]
            replay_audit_ids_before = {
                audit["audit_log_id"] for audit in fixture.repository.list("audit_log")
            }
            replay = client.get(
                "/oauth/google/callback",
                params={"error": "access_denied", "state": state},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response.headers["location"])
        configured = urlparse(fixture.config.chatgpt_redirect_uri)
        self.assertEqual(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.fragment),
            (
                configured.scheme,
                configured.netloc,
                configured.path,
                configured.params,
                configured.fragment,
            ),
        )
        self.assertEqual(
            parse_qs(parsed.query),
            {"error": ["access_denied"], "state": [client_state]},
        )
        rendered = response.headers["location"] + str(fixture.repository.list("audit_log"))
        for forbidden in (
            "private_upstream_error",
            "private upstream account detail",
            "evil.example",
            state,
        ):
            self.assertNotIn(forbidden, rendered)
        transaction = fixture.repository.list("oauth_transactions")[0]
        self.assertEqual(transaction["status"], "failed")
        self.assertEqual(transaction["consumed_at"], fixture.clock.now_iso())
        self.assertEqual(denial_audit["action"], "google_authentication_failed")
        self.assertEqual(denial_audit["reason_code"], "google_authorization_denied")
        self.assertEqual(fixture.repository.audit_event_count, audit_before + 2)
        audit = denial_audit
        self.assertEqual(audit["action"], "google_authentication_failed")
        self.assertEqual(audit["reason_code"], "google_authorization_denied")
        self.assertEqual(
            {table: fixture.repository.list(table) for table in protected_tables},
            protected_before,
        )
        self.assertEqual(fixture.google_client.authenticated_codes, [])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.json(), {"error": "access_denied"})
        self.assertNotIn("location", replay.headers)
        replay_audits = [
            audit
            for audit in fixture.repository.list("audit_log")
            if audit["audit_log_id"] not in replay_audit_ids_before
        ]
        self.assertEqual(len(replay_audits), 1)
        replay_audit = replay_audits[0]
        self.assertEqual(replay_audit["reason_code"], "oauth_state_replayed")
        self.assertNotIn(state, replay.text + str(replay_audit))
        self.assertEqual(transaction["status"], "failed")
        self.assertEqual(fixture.repository.list("external_identities"), [])
        self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
        self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])

    def test_google_authorization_denial_invalid_shapes_fail_closed_without_redirect(
        self,
    ) -> None:
        cases = (
            ("missing-state", lambda _state: "error=access_denied"),
            ("wrong-state", lambda _state: "error=access_denied&state=wrong-state"),
            (
                "duplicate-state",
                lambda state: urlencode(
                    [
                        ("error", "access_denied"),
                        ("state", state),
                        ("state", "other-state"),
                    ]
                ),
            ),
            (
                "error-and-code",
                lambda state: urlencode(
                    {
                        "error": "access_denied",
                        "state": state,
                        "code": "private-google-code",
                    }
                ),
            ),
            ("empty-error", lambda state: urlencode({"error": "", "state": state})),
        )
        for name, query_factory in cases:
            with self.subTest(name=name):
                fixture = self.fixture(seed=f"http-google-denial-{name}")
                state = fixture.start_authorization()
                mutable_before = fixture.repository.mutable_state_snapshot_bytes()

                with self.client(fixture) as client:
                    response = client.get(
                        "/oauth/google/callback?" + query_factory(state),
                        follow_redirects=False,
                    )

                self.assertEqual(response.status_code, 400)
                self.assertNotIn("location", response.headers)
                self.assertIn(response.json()["error"], {"access_denied", "invalid_request"})
                fixture.repository.assert_mutable_state_unchanged(mutable_before)
                self.assertEqual(
                    fixture.repository.list("oauth_transactions")[0]["status"],
                    "pending",
                )
                self.assertEqual(fixture.google_client.authenticated_codes, [])
                self.assertNotIn("private-google-code", response.text)

    def test_google_authorization_denial_write_failures_return_generic_500_and_roll_back(
        self,
    ) -> None:
        for write_index in (1, 2):
            with self.subTest(write_index=write_index):
                fixture = self.fixture(seed=f"http-google-denial-write-{write_index}")
                state = fixture.start_authorization()
                snapshot = fixture.repository.snapshot_bytes()
                audit_before = fixture.repository.audit_event_count
                fixture.repository.inject_failure_at(write_index)

                with self.client(fixture) as client:
                    response = client.get(
                        "/oauth/google/callback",
                        params={"error": "access_denied", "state": state},
                        follow_redirects=False,
                    )

                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json(), {"error": "server_error"})
                self.assertNotIn("location", response.headers)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
                fixture.repository.assert_unchanged(snapshot)
                self.assertEqual(fixture.repository.audit_event_count, audit_before)
                self.assertEqual(
                    fixture.repository.list("oauth_transactions")[0]["status"],
                    "pending",
                )

    def test_duplicate_authorize_callback_and_token_fields_only_add_one_redacted_audit(
        self,
    ) -> None:
        cases = (
            (
                "authorization",
                "/oauth/authorize?client_id=one&client_id=two",
                None,
                "oauth_parameter_duplicated",
            ),
            (
                "google_callback",
                "/oauth/google/callback?state=one&state=two&code=secret-google-code",
                None,
                "oauth_parameter_duplicated",
            ),
            (
                "token_exchange",
                "/oauth/token",
                "grant_type=authorization_code&code=secret-one&code=secret-two",
                "token_parameter_duplicated",
            ),
        )
        for event, path, body, reason_code in cases:
            with self.subTest(event=event):
                fixture = self.fixture(seed=f"duplicate-{event}")
                mutable_before = fixture.repository.mutable_state_snapshot_bytes()
                audit_before = fixture.repository.audit_event_count
                with self.client(fixture) as client:
                    if body is None:
                        response = client.get(path, follow_redirects=False)
                    else:
                        response = client.post(
                            path,
                            content=body,
                            headers={"content-type": "application/x-www-form-urlencoded"},
                        )

                self.assertEqual(response.status_code, 400)
                fixture.repository.assert_mutable_state_unchanged(mutable_before)
                self.assertEqual(fixture.repository.audit_event_count, audit_before + 1)
                audit = fixture.repository.list("audit_log")[-1]
                self.assertEqual(audit["reason_code"], reason_code)
                self.assertEqual(audit["metadata"], {"event_stage": event})
                self.assertEqual(audit["status"], "permission_denied")
                rendered = response.text + str(audit)
                for forbidden in ("secret-one", "secret-two", "secret-google-code"):
                    self.assertNotIn(forbidden, rendered)

    def test_token_form_rejects_transport_malformed_requests_without_state_mutation(
        self,
    ) -> None:
        cases = (
            (
                "wrong_content_type",
                "application/json",
                lambda body: body,
                "token_content_type_invalid",
            ),
            (
                "oversized_body",
                "application/x-www-form-urlencoded",
                lambda body: body + b"&padding=" + (b"x" * 16385),
                "token_request_too_large",
            ),
            (
                "invalid_utf8",
                "application/x-www-form-urlencoded",
                lambda body: body + b"\xff",
                "token_form_invalid",
            ),
        )
        for case_name, content_type, build_body, reason_code in cases:
            with self.subTest(case=case_name):
                fixture = self.fixture(seed=f"token-form-{case_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, code = fixture.authorize()
                body = build_body(urlencode(fixture.token_request(code)).encode("utf-8"))
                mutable_before = fixture.repository.mutable_state_snapshot_bytes()
                audit_ids_before = {
                    audit["audit_log_id"] for audit in fixture.repository.list("audit_log")
                }

                with self.client(fixture) as client:
                    response = client.post(
                        "/oauth/token",
                        content=body,
                        headers={"content-type": content_type},
                    )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"error": "invalid_request"})
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["pragma"], "no-cache")
                fixture.repository.assert_mutable_state_unchanged(mutable_before)
                new_audits = [
                    audit
                    for audit in fixture.repository.list("audit_log")
                    if audit["audit_log_id"] not in audit_ids_before
                ]
                self.assertEqual(len(new_audits), 1)
                self.assertEqual(new_audits[0]["reason_code"], reason_code)
                self.assertEqual(
                    new_audits[0]["metadata"],
                    {"event_stage": "token_exchange"},
                )
                self.assertIsNone(
                    fixture.repository.list("oauth_authorization_codes")[0].get("consumed_at")
                )
                self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])
                rendered = response.text + str(new_audits[0])
                self.assertNotIn(code, rendered)
                self.assertNotIn(body[:128].decode("utf-8", errors="ignore"), rendered)

    def test_token_form_stops_streaming_as_soon_as_the_body_limit_is_crossed(
        self,
    ) -> None:
        async def post_streamed(
            fixture: BridgeFixture,
            *,
            chunks: tuple[bytes, ...],
            content_length: bytes | None,
        ) -> tuple[list[dict[str, object]], int]:
            app = create_oauth_asgi_app(
                bridge=fixture.bridge,
                config=fixture.config,
                google_client=fixture.google_client,  # type: ignore[arg-type]
                clock=fixture.clock.now,
            )
            headers = [(b"content-type", b"application/x-www-form-urlencoded")]
            if content_length is not None:
                headers.append((b"content-length", content_length))
            receive_calls = 0
            sent: list[dict[str, object]] = []

            async def receive() -> dict[str, object]:
                nonlocal receive_calls
                chunk = chunks[receive_calls]
                receive_calls += 1
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": receive_calls < len(chunks),
                }

            async def send(message: dict[str, object]) -> None:
                sent.append(message)

            await app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "scheme": "https",
                    "method": "POST",
                    "server": ("testserver", 443),
                    "client": ("testclient", 50000),
                    "root_path": "",
                    "path": "/oauth/token",
                    "raw_path": b"/oauth/token",
                    "query_string": b"",
                    "headers": headers,
                    "state": {},
                },
                receive,
                send,
            )
            return sent, receive_calls

        for case_name, content_length, expected_receive_calls in (
            ("absent_content_length", None, 2),
            ("malformed_content_length", b"not-a-decimal-length", 2),
            ("declared_oversized", b"16385", 0),
        ):
            with self.subTest(case=case_name):
                fixture = self.fixture(seed=f"token-stream-limit-{case_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, code = fixture.authorize()
                token_body = urlencode(fixture.token_request(code)).encode("utf-8")
                prefix = token_body + b"&padding="
                self.assertLess(len(prefix), 16384)
                first_chunk = prefix + (b"x" * (16384 - len(prefix)))
                unread_marker = b"never-consume-private-marker"
                mutable_before = fixture.repository.mutable_state_snapshot_bytes()
                audit_ids_before = {
                    audit["audit_log_id"] for audit in fixture.repository.list("audit_log")
                }

                sent, receive_calls = asyncio.run(
                    post_streamed(
                        fixture,
                        chunks=(first_chunk, b"y", unread_marker),
                        content_length=content_length,
                    )
                )

                self.assertEqual(receive_calls, expected_receive_calls)
                response_start = next(
                    message for message in sent if message["type"] == "http.response.start"
                )
                response_body = b"".join(
                    message.get("body", b"")
                    for message in sent
                    if message["type"] == "http.response.body"
                )
                self.assertEqual(response_start["status"], 400)
                self.assertEqual(json.loads(response_body), {"error": "invalid_request"})
                response_headers = dict(response_start["headers"])
                self.assertEqual(response_headers[b"cache-control"], b"no-store")
                self.assertEqual(response_headers[b"pragma"], b"no-cache")
                fixture.repository.assert_mutable_state_unchanged(mutable_before)
                new_audits = [
                    audit
                    for audit in fixture.repository.list("audit_log")
                    if audit["audit_log_id"] not in audit_ids_before
                ]
                self.assertEqual(len(new_audits), 1)
                self.assertEqual(new_audits[0]["reason_code"], "token_request_too_large")
                self.assertEqual(
                    new_audits[0]["metadata"],
                    {"event_stage": "token_exchange"},
                )
                self.assertIsNone(
                    fixture.repository.list("oauth_authorization_codes")[0].get("consumed_at")
                )
                self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])
                rendered = response_body.decode("utf-8") + str(new_audits[0])
                self.assertNotIn(code, rendered)
                self.assertNotIn(unread_marker.decode("ascii"), rendered)
                self.assertNotIn(
                    token_body[:128].decode("utf-8", errors="ignore"),
                    rendered,
                )

    def test_token_pkce_verifier_errors_are_safe_audited_and_atomic(self) -> None:
        fixture = self.fixture(seed="http-pkce-verifier-matrix")
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, code = fixture.authorize()
        cases = (
            ("x" * 42, "pkce_verifier_invalid"),
            ("x" * 129, "pkce_verifier_invalid"),
            ("x" * 42 + "!", "pkce_verifier_invalid"),
            ("x" * 42 + "密", "pkce_verifier_invalid"),
            ("w" * 43, "pkce_verifier_mismatch"),
        )
        with self.client(fixture) as client:
            for verifier, reason_code in cases:
                with self.subTest(reason_code=reason_code, verifier_length=len(verifier)):
                    request = fixture.token_request(code)
                    request["code_verifier"] = verifier
                    mutable_before = fixture.repository.mutable_state_snapshot_bytes()
                    audit_ids_before = {
                        audit["audit_log_id"] for audit in fixture.repository.list("audit_log")
                    }

                    response = client.post("/oauth/token", data=request)

                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json(), {"error": "invalid_grant"})
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertEqual(response.headers["pragma"], "no-cache")
                    fixture.repository.assert_mutable_state_unchanged(mutable_before)
                    new_audits = [
                        audit
                        for audit in fixture.repository.list("audit_log")
                        if audit["audit_log_id"] not in audit_ids_before
                    ]
                    self.assertEqual(len(new_audits), 1)
                    self.assertEqual(new_audits[0]["reason_code"], reason_code)
                    rendered = response.text + str(new_audits[0])
                    self.assertNotIn(verifier, rendered)
                    self.assertNotIn(code, rendered)

            success = client.post("/oauth/token", data=fixture.token_request(code))
        self.assertEqual(success.status_code, 200)

        audit_failure = self.fixture(seed="http-pkce-audit-failure")
        audit_failure.seed_owner()
        audit_failure.seed_invitation()
        _state, code = audit_failure.authorize()
        snapshot = audit_failure.repository.snapshot_bytes()
        audit_failure.repository.inject_failure_at(1)
        request = audit_failure.token_request(code)
        request["code_verifier"] = "x" * 42

        with self.client(audit_failure) as client:
            response = client.post("/oauth/token", data=request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_grant"})
        audit_failure.repository.assert_unchanged(snapshot)

    def test_denial_audit_failure_keeps_all_other_state_unchanged(self) -> None:
        fixture = self.fixture()
        before = fixture.repository.snapshot_bytes()
        fixture.repository.inject_failure_at(1)

        with self.client(fixture) as client:
            response = client.get(
                "/oauth/authorize?client_id=one&client_id=two",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        fixture.repository.assert_unchanged(before)
        self.assertEqual(fixture.repository.audit_event_count, 0)
        self.assertEqual(response.json(), {"error": "invalid_request"})

    def test_invalid_encrypted_client_state_only_adds_one_redacted_denial_audit(
        self,
    ) -> None:
        fixture = self.fixture(seed="http-tampered-state")
        state = fixture.start_authorization()
        transaction = fixture.repository.list("oauth_transactions")[0]
        ciphertext = transaction["encrypted_client_state"]
        transaction["encrypted_client_state"] = "tampered-" + ciphertext
        fixture.repository.put(
            "oauth_transactions",
            transaction["transaction_id"],
            transaction,
            operation="test_tamper_encrypted_client_state",
        )
        mutable_before = fixture.repository.mutable_state_snapshot_bytes()
        audit_before = fixture.repository.audit_event_count

        with self.client(fixture) as client:
            response = client.get(
                "/oauth/google/callback",
                params={"state": state, "code": "must-not-reach-google"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "server_error"})
        fixture.repository.assert_mutable_state_unchanged(mutable_before)
        self.assertEqual(fixture.repository.audit_event_count, audit_before + 1)
        denial_audits = [
            audit
            for audit in fixture.repository.list("audit_log")
            if audit.get("reason_code") == "oauth_client_state_invalid"
        ]
        self.assertEqual(len(denial_audits), 1)
        audit = denial_audits[0]
        self.assertEqual(audit["action"], "google_authentication_failed")
        self.assertEqual(audit["reason_code"], "oauth_client_state_invalid")
        self.assertEqual(audit["metadata"], {"event_stage": "google_callback"})
        self.assertEqual(fixture.google_client.authenticated_codes, [])
        rendered = response.text + str(audit)
        for forbidden in (state, ciphertext, "must-not-reach-google"):
            self.assertNotIn(forbidden, rendered)

        audit_failure = self.fixture(seed="http-tampered-state-audit-failure")
        audit_failure_state = audit_failure.start_authorization()
        transaction = audit_failure.repository.list("oauth_transactions")[0]
        transaction["encrypted_client_state"] = "tampered-" + transaction["encrypted_client_state"]
        audit_failure.repository.put(
            "oauth_transactions",
            transaction["transaction_id"],
            transaction,
            operation="test_tamper_encrypted_client_state",
        )
        full_before = audit_failure.repository.snapshot_bytes()
        audit_failure.repository.inject_failure_at(1)

        with self.client(audit_failure) as client:
            response = client.get(
                "/oauth/google/callback",
                params={
                    "state": audit_failure_state,
                    "code": "must-not-reach-google",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "server_error"})
        audit_failure.repository.assert_unchanged(full_before)
        self.assertEqual(audit_failure.google_client.authenticated_codes, [])

    def test_callback_transaction_binding_mismatch_is_generic_and_no_write(self) -> None:
        fixture = self.fixture(seed="http-callback-transaction-binding")
        fixture.seed_owner()
        fixture.seed_invitation()
        state = fixture.start_authorization()
        transaction = fixture.repository.list("oauth_transactions")[0]
        transaction["redirect_uri"] = "https://evil.example/callback"
        fixture.repository.put(
            "oauth_transactions",
            transaction["transaction_id"],
            transaction,
            operation="test_misbind_callback_redirect",
        )
        mutable_before = fixture.repository.mutable_state_snapshot_bytes()
        audit_ids_before = {audit["audit_log_id"] for audit in fixture.repository.list("audit_log")}

        with self.client(fixture) as client:
            response = client.get(
                "/oauth/google/callback",
                params={"state": state, "code": "must-not-reach-google"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "server_error"})
        self.assertNotIn("location", response.headers)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        fixture.repository.assert_mutable_state_unchanged(mutable_before)
        self.assertEqual(fixture.google_client.authenticated_codes, [])
        stored = fixture.repository.list("oauth_transactions")[0]
        self.assertEqual(stored["status"], "pending")
        self.assertIsNone(stored.get("consumed_at"))
        self.assertEqual(fixture.repository.list("external_identities"), [])
        self.assertEqual(fixture.repository.list("oauth_client_authorizations"), [])
        self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
        self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])
        new_audits = [
            audit
            for audit in fixture.repository.list("audit_log")
            if audit["audit_log_id"] not in audit_ids_before
        ]
        self.assertEqual(len(new_audits), 1)
        self.assertEqual(
            new_audits[0]["reason_code"],
            "oauth_transaction_binding_invalid",
        )
        self.assertEqual(
            new_audits[0]["metadata"],
            {"event_stage": "google_callback"},
        )
        rendered = response.text + str(new_audits[0])
        for forbidden in (
            state,
            "must-not-reach-google",
            "evil.example",
            transaction["encrypted_client_state"],
        ):
            self.assertNotIn(forbidden, rendered)

    def test_untrusted_authorization_redirect_is_never_followed_or_reflected(self) -> None:
        fixture = self.fixture()
        parameters = fixture.authorization_request(client_state="private-client-state")
        parameters["redirect_uri"] = "https://evil.example/callback"
        parameters["resource"] = "https://evil.example/mcp"
        mutable_before = fixture.repository.mutable_state_snapshot_bytes()

        with self.client(fixture) as client:
            response = client.get(
                "/oauth/authorize?" + urlencode(parameters),
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("location", response.headers)
        self.assertEqual(response.json(), {"error": "invalid_request"})
        self.assertNotIn("evil.example", response.text)
        self.assertNotIn("private-client-state", response.text)
        fixture.repository.assert_mutable_state_unchanged(mutable_before)
        self.assertEqual(fixture.repository.audit_event_count, 1)

    def test_trusted_authorization_error_redirect_contains_only_error_and_client_state(
        self,
    ) -> None:
        fixture = self.fixture()
        parameters = fixture.authorization_request(client_state="client-state-001")
        parameters["resource"] = "https://auth.example.test/not-mcp"

        with self.client(fixture) as client:
            response = client.get(
                "/oauth/authorize?" + urlencode(parameters),
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response.headers["location"])
        expected = urlparse(fixture.config.chatgpt_redirect_uri)
        self.assertEqual(
            (parsed.scheme, parsed.netloc, parsed.path),
            (expected.scheme, expected.netloc, expected.path),
        )
        self.assertEqual(
            parse_qs(parsed.query),
            {"error": ["invalid_target"], "state": ["client-state-001"]},
        )
        self.assertNotIn("reason_code", response.headers["location"])
        self.assertNotIn("not-mcp", response.headers["location"])

    def test_callback_never_redirects_to_bridge_supplied_untrusted_location(self) -> None:
        fixture = self.fixture()
        fixture.bridge.complete_google_callback = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "redirect_uri": "https://evil.example/callback?code=secret-code",
                "user_id": "user_001",
            }
        )

        with self.client(fixture) as client:
            response = client.get(
                "/oauth/google/callback?state=safe-state&code=google-secret-code",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("location", response.headers)
        self.assertEqual(response.json(), {"error": "server_error"})
        self.assertNotIn("evil.example", response.text)
        self.assertNotIn("secret", response.text)

    def test_callback_redirect_requires_exact_internal_query_and_no_fragment(
        self,
    ) -> None:
        fixture = self.fixture(seed="callback-internal-query")
        valid_redirect = (
            fixture.config.chatgpt_redirect_uri
            + "?"
            + urlencode({"code": "opaque-code", "state": "opaque-state"})
        )
        cases = (
            ("valid_code_state", valid_redirect, 302),
            ("unexpected_query_key", valid_redirect + "&unexpected=private-value", 500),
            ("fragment", valid_redirect + "#private-fragment", 500),
        )
        for case_name, redirect_uri, expected_status in cases:
            with self.subTest(case=case_name):
                fixture.bridge.complete_google_callback = AsyncMock(  # type: ignore[method-assign]
                    return_value={
                        "redirect_uri": redirect_uri,
                        "user_id": "user_001",
                    }
                )
                snapshot = fixture.repository.snapshot_bytes()

                with self.client(fixture) as client:
                    response = client.get(
                        "/oauth/google/callback",
                        params={"state": "safe-state", "code": "google-code"},
                        follow_redirects=False,
                    )

                self.assertEqual(response.status_code, expected_status)
                fixture.repository.assert_unchanged(snapshot)
                if expected_status == 302:
                    self.assertEqual(response.headers["location"], valid_redirect)
                else:
                    self.assertNotIn("location", response.headers)
                    self.assertEqual(response.json(), {"error": "server_error"})
                    self.assertNotIn("private", response.text)

    def test_google_and_token_errors_do_not_reflect_inputs_or_backend_detail(self) -> None:
        fixture = self.fixture()
        fixture.bridge.complete_google_callback = AsyncMock(  # type: ignore[method-assign]
            side_effect=OAuthAccessDenied("access_denied", "google_code_exchange_failed", 400)
        )

        with self.client(fixture) as client:
            callback = client.get(
                "/oauth/google/callback?state=private-state&code=private-google-code",
                follow_redirects=False,
            )
            token = client.post(
                "/oauth/token",
                content="grant_type=authorization_code&code=private-code",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )

        self.assertEqual(callback.json(), {"error": "access_denied"})
        self.assertEqual(token.json(), {"error": "invalid_request"})
        rendered = callback.text + token.text + str(fixture.repository.list("audit_log"))
        for forbidden in ("private-state", "private-google-code", "private-code", "google-secret"):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(callback.headers["cache-control"], "no-store")
        self.assertEqual(token.headers["cache-control"], "no-store")
        self.assertEqual(token.headers["pragma"], "no-cache")

    def test_google_temporal_denial_has_at_most_one_redacted_audit_and_no_mutation(
        self,
    ) -> None:
        fixture = self.fixture(seed="http-google-temporal-denial")
        fixture.seed_owner()
        fixture.seed_invitation()
        state = fixture.start_authorization()
        fixture.google_client.authenticate_code = AsyncMock(  # type: ignore[method-assign]
            side_effect=OAuthAccessDenied("access_denied", "google_exp_invalid", 400)
        )
        mutable_before = fixture.repository.mutable_state_snapshot_bytes()
        audit_before = fixture.repository.audit_event_count

        with self.client(fixture) as client:
            response = client.get(
                "/oauth/google/callback",
                params={"state": state, "code": "private-google-code"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "access_denied"})
        fixture.repository.assert_mutable_state_unchanged(mutable_before)
        self.assertEqual(fixture.repository.audit_event_count, audit_before + 1)
        denial_audits = [
            audit
            for audit in fixture.repository.list("audit_log")
            if audit.get("reason_code") == "google_exp_invalid"
        ]
        self.assertEqual(len(denial_audits), 1)
        self.assertNotIn("private-google-code", str(denial_audits[0]))

        audit_failure = self.fixture(seed="http-google-temporal-audit-failure")
        audit_failure.seed_owner()
        audit_failure.seed_invitation()
        state = audit_failure.start_authorization()
        audit_failure.google_client.authenticate_code = AsyncMock(  # type: ignore[method-assign]
            side_effect=OAuthAccessDenied("access_denied", "google_exp_invalid", 400)
        )
        snapshot = audit_failure.repository.snapshot_bytes()
        audit_failure.repository.inject_failure_at(1)

        with self.client(audit_failure) as client:
            response = client.get(
                "/oauth/google/callback",
                params={"state": state, "code": "private-google-code"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        audit_failure.repository.assert_unchanged(snapshot)


if __name__ == "__main__":
    unittest.main()
