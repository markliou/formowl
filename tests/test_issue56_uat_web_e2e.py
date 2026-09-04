from __future__ import annotations

import asyncio
import base64
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import http.client
import io
import json
from pathlib import Path
import socket
import stat
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import _paths  # noqa: F401
from formowl_auth import GoogleIdentity, OAuthInvitation
from formowl_auth.security import normalize_verified_email
import formowl_gateway.issue56_uat_runtime as uat_runtime_module
import formowl_gateway.runtime as runtime_module
from formowl_contract import (
    User,
    WorkspaceMember,
    assert_no_public_raw_references,
)
from formowl_gateway.issue56_uat_runtime import (
    Issue56UatQueryService,
    create_issue56_temporary_lan_query_service,
)
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_mail.human_uat_http import create_mail_human_uat_http_server
from formowl_mail.human_uat_orchestrator import (
    UatConversationOutcome,
    UatEvidenceToolRequest,
)
import formowl_mail.issue56_sealed_source as sealed_source
from oauth_harness import TransactionAwareMemoryRepository
import scripts.issue56_uat_web as uat_web_script
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


class _RecordingGptQueryAgent:
    model_name = "codex:gpt-5.6-sol"

    def __init__(self, *, standalone_query: str) -> None:
        self.standalone_query = standalone_query
        self.user_texts: list[str] = []
        self.tool_queries: list[str] = []
        self.closed = False

    def respond(
        self,
        *,
        history,
        user_text,
        latest_evidence,
        safety_identifier,
        evidence_tool,
    ):
        del history, latest_evidence, safety_identifier
        self.user_texts.append(user_text)
        if user_text == "你好":
            return UatConversationOutcome(
                response_kind="answer",
                answer_text="你好，請告訴我想查詢的資料。",
                display_format="narrative",
                model_name=self.model_name,
            )
        request = UatEvidenceToolRequest(
            query_text=self.standalone_query,
        )
        evidence = evidence_tool(request)
        self.tool_queries.append(request.query_text)
        inventory = evidence.get("exact_inventory")
        items = inventory.get("items", ()) if isinstance(inventory, dict) else ()
        citations = tuple(evidence.get("citations", ()))
        if not items or not citations:
            return UatConversationOutcome(
                response_kind="clarification",
                answer_text="目前沒有可引用的來源結果，請補充查詢範圍。",
                display_format="narrative",
                model_name=self.model_name,
                coverage_status="incomplete",
                coverage_note="目前沒有足夠的可引用來源。",
                tool_requests=(request,),
                tool_results=(evidence,),
            )
        values = items[0]["structured_values"]
        answer = "\n".join(f"{value['field']}: {value['value']}" for value in values)
        coverage_complete = (
            evidence.get("status") == "complete" and inventory.get("coverage_status") == "complete"
        )
        return UatConversationOutcome(
            response_kind="answer",
            answer_text=answer,
            display_format="narrative",
            model_name=self.model_name,
            citation_ids=(citations[0],),
            coverage_status="complete" if coverage_complete else "incomplete",
            coverage_note="" if coverage_complete else "來源涵蓋範圍仍不完整。",
            tool_requests=(request,),
            tool_results=(evidence,),
        )

    def discard_conversation(self, safety_identifier) -> None:
        del safety_identifier

    def close(self) -> None:
        self.closed = True


class Issue56UatWebE2ETests(unittest.TestCase):
    def test_cli_binds_private_custom_provider_key_and_fails_closed(self) -> None:
        provider_env_key = "FORMOWL_TEST_CUSTOM_PROVIDER_KEY"
        provider_api_key = "synthetic-provider-key-never-public"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            key_path = root / "provider.key"
            key_path.write_text(provider_api_key, encoding="utf-8")
            key_path.chmod(0o600)
            runtime_paths = SimpleNamespace(
                codex_home=root / "codex-home",
                workspace=root / "workspace",
                provider_env_key=provider_env_key,
            )
            transport = MagicMock()
            conversation_model = MagicMock()
            query_service = MagicMock()
            query_service.__enter__.return_value = query_service
            server = MagicMock()
            arguments = [
                "issue56_uat_web.py",
                "--temporary-lan-diagnostic",
                "--temporary-access-code",
                "synthetic-access-code",
                "--codex-runtime-state-dir",
                str(root / "runtime"),
                "--codex-provider-api-key-file",
                str(key_path),
            ]
            standard_output = io.StringIO()
            standard_error = io.StringIO()
            with (
                patch.object(
                    uat_web_script, "validate_codex_runtime_state", return_value=runtime_paths
                ),
                patch.object(
                    uat_web_script,
                    "CodexAppServerStdioTransport",
                    return_value=transport,
                ) as transport_factory,
                patch.object(
                    uat_web_script,
                    "CodexAppServerConversationModel",
                    return_value=conversation_model,
                ),
                patch.object(
                    uat_web_script,
                    "create_issue56_temporary_lan_query_service",
                    return_value=query_service,
                ),
                patch.object(
                    uat_web_script,
                    "create_mail_human_uat_http_server",
                    return_value=server,
                ),
                patch.object(uat_web_script.sys, "argv", arguments),
                redirect_stdout(standard_output),
                redirect_stderr(standard_error),
            ):
                self.assertEqual(uat_web_script.main(), 0)

            transport_arguments = transport_factory.call_args.kwargs
            self.assertEqual(
                transport_arguments["environment"],
                {provider_env_key: provider_api_key},
            )
            self.assertEqual(
                transport_arguments["provider_env_key"],
                provider_env_key,
            )
            self.assertNotIn(
                provider_api_key,
                standard_output.getvalue() + standard_error.getvalue(),
            )
            server.serve_forever.assert_called_once_with()

            with patch.object(
                uat_web_script,
                "validate_codex_runtime_state",
                return_value=SimpleNamespace(
                    codex_home=root / "chatgpt-home",
                    workspace=root / "chatgpt-workspace",
                    provider_env_key=None,
                ),
            ):
                with (
                    patch.object(uat_web_script.sys, "argv", arguments),
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    uat_web_script.main()

            missing_key_arguments = [
                argument
                for argument in arguments
                if argument not in {"--codex-provider-api-key-file", str(key_path)}
            ]
            with (
                patch.object(
                    uat_web_script,
                    "validate_codex_runtime_state",
                    return_value=runtime_paths,
                ),
                patch.object(uat_web_script.sys, "argv", missing_key_arguments),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                uat_web_script.main()

            key_path.chmod(0o644)
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(key_path)
            key_path.chmod(0o600)
            symlink_path = root / "provider-link"
            symlink_path.symlink_to(key_path)
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(symlink_path)
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(Path("provider.key"))
            key_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(key_path)
            key_path.write_bytes(b"x" * (uat_web_script._MAX_PROVIDER_API_KEY_BYTES + 1))
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(key_path)

    def test_temporary_lan_uses_real_sealed_source_normal_mcp_and_opt_in_log(
        self,
    ) -> None:
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
            greeting = "你好"
            prompt = f"麻煩幫我確認一下 {_IDENTIFIER} 這筆的 {_HEADER}，謝謝。"
            standalone_query = f"有{_IDENTIFIER}的{_HEADER}呢？"
            conversation_model = _RecordingGptQueryAgent(
                standalone_query=standalone_query,
            )
            access_code = "synthetic-lan-access-731"
            basic_authorization = (
                "Basic " + base64.b64encode(f"formowl-uat:{access_code}".encode()).decode()
            )
            wrong_authorization = (
                "Basic " + base64.b64encode(f"formowl-uat:{access_code}-wrong".encode()).decode()
            )
            behavior_log = root / "consented-behavior.jsonl"
            handler_arguments: list[dict[str, object]] = []
            loader_build_count = 0
            cached_handler = None
            original_builder = (
                uat_runtime_module.build_issue56_production_semantic_retrieval_handler
            )

            def build_once():
                nonlocal cached_handler, loader_build_count
                if cached_handler is None:
                    loader_build_count += 1
                    real_handler = original_builder()

                    def observed_handler(arguments):
                        handler_arguments.append(dict(arguments))
                        return real_handler(arguments)

                    cached_handler = observed_handler
                return cached_handler

            def browser_request(
                server,
                method,
                path,
                *,
                prompt=None,
                authorization=None,
            ):
                body = (
                    json.dumps({"prompt": prompt}, ensure_ascii=False).encode()
                    if prompt is not None
                    else None
                )
                headers = {}
                if body is not None:
                    host, port = server.server_address
                    headers.update(
                        {
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": f"http://{host}:{port}",
                        }
                    )
                if authorization is not None:
                    headers["Authorization"] = authorization
                connection = http.client.HTTPConnection(
                    *server.server_address,
                    timeout=30,
                )
                try:
                    connection.request(method, path, body=body, headers=headers)
                    response = connection.getresponse()
                    return response, response.read()
                finally:
                    connection.close()

            with (
                patch.dict(__import__("os").environ, environment, clear=True),
                patch.object(
                    uat_runtime_module,
                    "build_issue56_production_semantic_retrieval_handler",
                    side_effect=build_once,
                ),
            ):
                with create_issue56_temporary_lan_query_service(
                    conversation_model,
                    behavior_log_path=behavior_log,
                    record_raw_uat_interactions=True,
                ) as query_service:
                    server = create_mail_human_uat_http_server(
                        "127.0.0.1",
                        0,
                        query_service,
                        temporary_access_code=access_code,
                    )
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        denied_responses = (
                            browser_request(server, "GET", "/")[0],
                            browser_request(
                                server,
                                "GET",
                                "/",
                                authorization=wrong_authorization,
                            )[0],
                            browser_request(
                                server,
                                "POST",
                                "/api/chat",
                                prompt=prompt,
                            )[0],
                            browser_request(
                                server,
                                "POST",
                                "/api/chat",
                                prompt=prompt,
                                authorization=wrong_authorization,
                            )[0],
                        )
                        self.assertEqual(query_service.request_count, 0)
                        self.assertFalse(behavior_log.exists())
                        page_response, page_body = browser_request(
                            server,
                            "GET",
                            "/",
                            authorization=basic_authorization,
                        )
                        greeting_response, greeting_body = browser_request(
                            server,
                            "POST",
                            "/api/chat",
                            prompt=greeting,
                            authorization=basic_authorization,
                        )
                        greeting_request_count = query_service.request_count
                        response, body = browser_request(
                            server,
                            "POST",
                            "/api/chat",
                            prompt=prompt,
                            authorization=basic_authorization,
                        )
                        source_request_count = query_service.request_count
                    finally:
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=5)

                page = page_body.decode()
                greeting_payload = json.loads(greeting_body)
                payload = json.loads(body)
                for denied in denied_responses:
                    self.assertEqual(denied.status, 401)
                    self.assertEqual(
                        denied.getheader("WWW-Authenticate"),
                        'Basic realm="FormOwl temporary UAT", charset="UTF-8"',
                    )
                self.assertEqual(page_response.status, 200)
                self.assertIn('data-authenticated="true"', page)
                self.assertIn('id="login-link" href="/auth/start" hidden', page)
                self.assertNotIn('id="chat-form" hidden', page)
                self.assertIsNone(page_response.getheader("Set-Cookie"))
                self.assertEqual(greeting_response.status, 200)
                self.assertEqual(greeting_payload["status"], "complete")
                self.assertTrue(greeting_payload["answer"])
                self.assertEqual(greeting_payload["citation_count"], 0)
                self.assertEqual(greeting_request_count, 0)
                self.assertEqual(response.status, 200)
                self.assertIsNone(response.getheader("Set-Cookie"))
                self.assertIn(payload["status"], {"complete", "partial"})
                self.assertTrue(payload["answer"])
                self.assertIn(_VALUE, payload["answer"])
                self.assertGreater(payload["citation_count"], 0)
                self.assertGreaterEqual(source_request_count, 1)
                self.assertLessEqual(source_request_count, 3)
                self.assertEqual(
                    conversation_model.user_texts,
                    [greeting, prompt],
                )
                self.assertEqual(
                    conversation_model.tool_queries,
                    [standalone_query],
                )
                self.assertNotEqual(prompt, standalone_query)
                assert_no_public_raw_references(
                    payload,
                    "issue56_temporary_lan_web_response",
                )
                self.assertEqual(loader_build_count, 1)

            self.assertEqual(loader_build_count, 1)
            self.assertTrue(conversation_model.closed)
            self.assertEqual(len(handler_arguments), 1)
            for arguments in handler_arguments:
                self.assertEqual(arguments["query_text"], standalone_query)
                self.assertNotEqual(arguments["query_text"], prompt)
                self.assertEqual(
                    arguments["requester_user_id"],
                    sealed_source.APPROVER_ACTOR,
                )
                self.assertEqual(
                    arguments["workspace_id"],
                    sealed_source.WORKSPACE_ID,
                )
                self.assertNotIn("tenant_id", arguments)

            self.assertEqual(stat.S_IMODE(behavior_log.stat().st_mode), 0o600)
            log_lines = behavior_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 2)
            records = tuple(json.loads(line) for line in log_lines)
            for record, recorded_prompt, recorded_payload in zip(
                records,
                (greeting, prompt),
                (greeting_payload, payload),
                strict=True,
            ):
                self.assertEqual(
                    set(record),
                    {
                        "elapsed_ms",
                        "mcp_statuses",
                        "prompt",
                        "request_count",
                        "result",
                        "timestamp",
                    },
                )
                self.assertEqual(record["prompt"], recorded_prompt)
                self.assertEqual(
                    record["result"],
                    {
                        key: recorded_payload.get(key)
                        for key in ("status", "answer", "clarification", "citations")
                    },
                )
                self.assertEqual(
                    set(record["result"]),
                    {"answer", "citations", "clarification", "status"},
                )
                self.assertEqual(record["request_count"], len(record["mcp_statuses"]))
                assert_no_public_raw_references(
                    record,
                    "issue56_temporary_lan_behavior_log",
                )
            rendered_log = json.dumps(records, ensure_ascii=False).casefold()
            for forbidden in (
                "synthetic-provider-key-never-public",
                access_code.casefold(),
                basic_authorization.casefold(),
                "authorization",
                "bearer",
                "cookie",
                "formowl-uat",
                "object_uri",
                "session_id",
                "tenant_id",
                str(root).casefold(),
                "/tmp/",
                "/workspace/",
            ):
                self.assertNotIn(forbidden, rendered_log)

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
            prompt = f"可以幫忙查一下 {_IDENTIFIER} 對應的 {_HEADER} 嗎？"
            standalone_query = f"有{_IDENTIFIER}的{_HEADER}呢？"
            conversation_model = _RecordingGptQueryAgent(
                standalone_query=standalone_query,
            )
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
                    conversation_model=conversation_model,
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
                self.assertEqual(
                    conversation_model.tool_queries,
                    [standalone_query],
                )
                self.assertNotEqual(prompt, standalone_query)
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
