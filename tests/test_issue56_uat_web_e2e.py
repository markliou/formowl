from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import _paths  # noqa: F401
from formowl_auth import GoogleIdentity, OAuthInvitation
from formowl_auth.security import normalize_verified_email
import formowl_gateway.runtime as runtime_module
from formowl_contract import (
    User,
    WorkspaceMember,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_gateway.issue56_uat_runtime import (
    Issue56UatQueryService,
    _follow_up_queries,
)
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_mail.human_uat_http import create_mail_human_uat_http_server
import formowl_mail.issue56_sealed_source as sealed_source
from oauth_harness import TransactionAwareMemoryRepository
from test_connected_runtime import (
    _FakeConnection,
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)
from test_oauth_bridge_service import StubGoogleClient
from test_issue56_sealed_source_loader_e2e import (
    _loader_environment,
    _prepare_package,
    _sha256_path,
)
import test_issue56_sealed_source_loader_e2e as sealed_fixture
from test_issue56_supplemental_attachment_table_loader_e2e import (
    _HEADER,
    _IDENTIFIER,
    _PERMISSION_SCOPE,
    _VALUE,
    _write_supplemental_partition,
)


class Issue56UatWebE2ETests(unittest.TestCase):
    def test_safe_label_precedes_noisy_projection_particle(self) -> None:
        label = "MetricField"
        field_hash = sha256_json(["source_column", label])
        prompt = f"有SYN-KEY-731的{label.casefold()}或玄地嗎？"
        data = {
            "status": "replan_required",
            "query_agent": {
                "external_replan": {
                    "requested_projection_field_hashes": [field_hash],
                    "ambiguous_projection_term_hashes": [sha256_json("玄地")],
                },
                "authorized_capability_summary": {
                    "listing_status": "complete",
                    "projection_fields": [
                        {
                            "field": label,
                            "field_hash": field_hash,
                            "structure_status": "source_provided",
                            "label_redacted": False,
                        }
                    ],
                },
            },
        }

        self.assertEqual(
            _follow_up_queries(prompt, data),
            (f"有SYN-KEY-731的{label}？",),
        )

    def test_real_sealed_source_over_browser_and_normal_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch.object(
                sealed_fixture,
                "WORKSPACE_PERMISSION_SCOPE",
                _PERMISSION_SCOPE,
            ):
                package = _prepare_package(root / "sealed")
            supplemental_path, parent_path = _write_supplemental_partition(
                root,
                package,
            )
            prompt = f"有{_IDENTIFIER}的{_HEADER}呢？"
            environment = dict(__import__("os").environ)
            environment.update(_loader_environment(package))
            environment.update(
                {
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_PATH": str(
                        supplemental_path
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_SHA256": (
                        _sha256_path(supplemental_path)
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_PATH": str(parent_path),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_SHA256": (
                        _sha256_path(parent_path)
                    ),
                }
            )
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            environment.update(_write_runtime_environment(runtime_root))
            environment["FORMOWL_ISSUE56_PRODUCTION_SEMANTIC_ENABLED"] = "1"
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                browser_port = reservation.getsockname()[1]
            public_base_url = f"http://127.0.0.1:{browser_port}"
            environment["FORMOWL_CHATGPT_REDIRECT_URI"] = f"{public_base_url}/auth/callback"
            environment["FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL"] = public_base_url
            repository = TransactionAwareMemoryRepository()
            repository.connection = _FakeConnection()
            runtime_repository = _FakeRepository()
            repository.health_check = runtime_repository.health_check
            repository.apply_migrations = runtime_repository.apply_migrations
            repository.close = runtime_repository.close
            oauth_email = "browser-uat@example.test"
            created_at = datetime.now(timezone.utc)
            with repository.transaction() as transaction:
                repository.insert_user(
                    User(
                        user_id=sealed_source.APPROVER_ACTOR,
                        display_name="Browser UAT owner",
                        email=oauth_email,
                        status="active",
                        created_at=created_at.isoformat(),
                    )
                )
                repository.insert_workspace_member(
                    WorkspaceMember(
                        workspace_id=sealed_source.WORKSPACE_ID,
                        user_id=sealed_source.APPROVER_ACTOR,
                        role="owner",
                    ),
                    created_at=created_at.isoformat(),
                )
                repository.insert_invitation(
                    OAuthInvitation(
                        invitation_id="invite_issue56_browser_uat",
                        normalized_email=normalize_verified_email(oauth_email),
                        workspace_id=sealed_source.WORKSPACE_ID,
                        role="owner",
                        status="pending",
                        expires_at=(created_at + timedelta(hours=1)).isoformat(),
                        created_at=created_at.isoformat(),
                        intended_user_id=sealed_source.APPROVER_ACTOR,
                    )
                )
                transaction.commit()
            with (
                patch.dict(__import__("os").environ, environment, clear=True),
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                    return_value=repository,
                ),
            ):
                config = ConnectedRuntimeConfig.from_env_and_secrets(environment)
                runtime = asyncio.run(
                    ConnectedRuntime.compose(
                        config,
                        http_client=_FakeHttpClient(),
                    )
                )
            google = StubGoogleClient(
                GoogleIdentity(
                    issuer="https://accounts.google.com",
                    subject="browser-uat-google-subject",
                    email=oauth_email,
                    email_verified=True,
                    display_name="Browser UAT owner",
                )
            )
            with (
                patch.object(
                    runtime.google_client,
                    "build_authorization_url",
                    side_effect=google.build_authorization_url,
                ),
                patch.object(
                    runtime.google_client,
                    "authenticate_code",
                    side_effect=google.authenticate_code,
                ),
                Issue56UatQueryService(
                    runtime,
                    public_base_url=public_base_url,
                ) as query_service,
            ):
                server = create_mail_human_uat_http_server(
                    "127.0.0.1",
                    browser_port,
                    query_service,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    body = json.dumps({"prompt": prompt}, ensure_ascii=False).encode()
                    origin = f"http://{server.server_address[0]}:" f"{server.server_address[1]}"
                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "POST",
                        "/api/chat",
                        body=body,
                        headers={
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": origin,
                        },
                    )
                    unauthenticated = connection.getresponse()
                    unauthenticated_payload = json.loads(unauthenticated.read())
                    connection.close()

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request("GET", "/")
                    page_response = connection.getresponse()
                    page = page_response.read().decode("utf-8")
                    connection.close()
                    self.assertEqual(page_response.status, 200)
                    self.assertIn('id="login-link"', page)
                    self.assertIn('data-authenticated="false"', page)

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request("GET", "/auth/start")
                    start_response = connection.getresponse()
                    start_response.read()
                    authorization_url = urlparse(start_response.getheader("Location"))
                    pre_auth_set_cookie = start_response.getheader("Set-Cookie")
                    connection.close()
                    authorization_parameters = parse_qs(authorization_url.query)
                    self.assertEqual(start_response.status, 302)
                    self.assertEqual(
                        f"{authorization_url.scheme}://"
                        f"{authorization_url.netloc}{authorization_url.path}",
                        config.oauth.authorization_endpoint,
                    )
                    self.assertEqual(
                        authorization_parameters["code_challenge_method"],
                        ["S256"],
                    )
                    self.assertNotIn("code_verifier", authorization_parameters)
                    self.assertIsInstance(pre_auth_set_cookie, str)
                    assert isinstance(pre_auth_set_cookie, str)
                    for required in (
                        "formowl_uat_pre_auth=",
                        "HttpOnly",
                        "SameSite=Lax",
                        "Path=/",
                    ):
                        self.assertIn(required, pre_auth_set_cookie)
                    pre_auth_cookie = pre_auth_set_cookie.split(";", 1)[0]

                    authorize_response = query_service._client.get(
                        authorization_url.path + "?" + authorization_url.query,
                        follow_redirects=False,
                    )
                    self.assertEqual(authorize_response.status_code, 302)
                    google_state = parse_qs(urlparse(authorize_response.headers["location"]).query)[
                        "state"
                    ][0]
                    callback_response = query_service._client.get(
                        "/oauth/google/callback",
                        params={
                            "state": google_state,
                            "code": "google-browser-uat-code",
                        },
                        follow_redirects=False,
                    )
                    self.assertEqual(callback_response.status_code, 302)
                    browser_callback = urlparse(callback_response.headers["location"])
                    self.assertEqual(
                        f"{browser_callback.scheme}://{browser_callback.netloc}"
                        f"{browser_callback.path}",
                        f"{public_base_url}/auth/callback",
                    )

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        browser_callback.path + "?" + browser_callback.query,
                    )
                    missing_cookie_response = connection.getresponse()
                    missing_cookie_response.read()
                    connection.close()

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        browser_callback.path + "?" + browser_callback.query,
                        headers={"Cookie": "formowl_uat_pre_auth=wrong-browser"},
                    )
                    wrong_browser_response = connection.getresponse()
                    wrong_browser_response.read()
                    connection.close()

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        browser_callback.path + "?" + browser_callback.query,
                        headers={"Cookie": pre_auth_cookie},
                    )
                    login_response = connection.getresponse()
                    login_response.read()
                    set_cookies = [
                        value
                        for name, value in login_response.getheaders()
                        if name.casefold() == "set-cookie"
                    ]
                    connection.close()
                    self.assertEqual(missing_cookie_response.status, 400)
                    self.assertEqual(wrong_browser_response.status, 400)
                    self.assertIsNone(missing_cookie_response.getheader("Set-Cookie"))
                    self.assertIsNone(wrong_browser_response.getheader("Set-Cookie"))
                    self.assertEqual(login_response.status, 303)
                    self.assertEqual(len(set_cookies), 2)
                    self.assertTrue(
                        any(
                            "formowl_uat_pre_auth=" in value and "Max-Age=0" in value
                            for value in set_cookies
                        )
                    )
                    session_set_cookie = next(
                        value for value in set_cookies if value.startswith("formowl_uat_session=")
                    )
                    for required in (
                        "HttpOnly",
                        "SameSite=Lax",
                        "Path=/",
                        f"Max-Age={config.oauth.access_token_lifetime_seconds}",
                    ):
                        self.assertIn(required, session_set_cookie)
                    for forbidden in ("access_token", "code_verifier", "tenant_id"):
                        self.assertNotIn(forbidden, repr(set_cookies))
                    session_cookie = session_set_cookie.split(";", 1)[0]

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "POST",
                        "/api/chat",
                        body=body,
                        headers={
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": origin,
                            "Cookie": session_cookie,
                        },
                    )
                    response = connection.getresponse()
                    payload = json.loads(response.read())
                    connection.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

                self.assertEqual(unauthenticated.status, 401)
                self.assertEqual(
                    unauthenticated_payload["error_code"],
                    "auth_required",
                )
                self.assertEqual(response.status, 200)
                self.assertIn(payload["status"], {"complete", "partial"})
                self.assertGreaterEqual(query_service.request_count, 1)
                self.assertLessEqual(query_service.request_count, 3)
                self.assertNotIn("mcp_failed", query_service.last_mcp_statuses)
                self.assertTrue(payload["answer"])
                self.assertIn(_VALUE, payload["answer"])
                self.assertGreater(payload["citation_count"], 0)
                assert_no_public_raw_references(payload, "issue56_uat_web_response")
                rendered = json.dumps(payload, ensure_ascii=False).lower()
                for forbidden in (
                    "object_uri",
                    "tenant_id",
                    "/tmp/",
                    "/workspace/",
                ):
                    self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
