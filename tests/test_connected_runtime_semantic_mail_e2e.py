from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import _paths  # noqa: F401
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

import formowl_gateway.runtime as runtime_module
from formowl_auth import ActorContext, OAuthPrincipal
from formowl_contract import SessionIdentity, User, WorkspaceMember, sha256_json
from formowl_gateway.issue56_sealed_source_loader import APPROVER_ACTOR, WORKSPACE_ID
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import validate_public_gateway_payload
from test_connected_runtime import (
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)


class ConnectedRuntimeSemanticMailE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_opt_in_default_composition_injects_actor_and_returns_citation(self) -> None:
        if os.environ.get("FORMOWL_RUN_ISSUE56_REAL_PRODUCTION_SEMANTIC_E2E") != "1":
            self.skipTest("real production semantic E2E is explicitly opt-in")
        query_file_value = os.environ.get("FORMOWL_ISSUE56_PRODUCTION_QUERY_FILE")
        if not query_file_value:
            self.fail("production query file is required")
        query_file = Path(query_file_value)
        try:
            query_stat = query_file.lstat()
            query_bytes = query_file.read_bytes()
        except OSError:
            self.fail("production query file is unavailable")
        if (
            not stat.S_ISREG(query_stat.st_mode)
            or stat.S_IMODE(query_stat.st_mode) != 0o600
            or not query_bytes
            or len(query_bytes) > 4096
        ):
            self.fail("production query file contract is invalid")
        try:
            private_query = query_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            self.fail("production query file encoding is invalid")
        if not private_query or "\x00" in private_query:
            self.fail("production query is invalid")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            environment = dict(os.environ)
            environment.update(_write_runtime_environment(root))
            environment["FORMOWL_ISSUE56_PRODUCTION_SEMANTIC_ENABLED"] = "1"
            config = ConnectedRuntimeConfig.from_env_and_secrets(environment)
            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                    return_value=_FakeRepository(),
                ),
            ):
                runtime = await ConnectedRuntime.compose(config, http_client=_FakeHttpClient())

            runtime.preflight = AsyncMock(return_value={"status": "ready"})
            timestamp = "2026-08-27T00:00:00+00:00"
            principal = OAuthPrincipal(
                user_id=APPROVER_ACTOR,
                external_identity_id="extid_semantic_runtime",
                oauth_client_id="chatgpt_closed_beta",
                token_session_id="oauthsid_semantic_runtime",
                scopes=("formowl.use",),
                resource=config.oauth.resource,
            )
            actor = ActorContext(
                user=User(
                    user_id=APPROVER_ACTOR,
                    display_name="Approved evaluation owner",
                    status="active",
                    created_at=timestamp,
                ),
                session_identity=SessionIdentity(
                    session_id=principal.token_session_id,
                    selected_user_id=APPROVER_ACTOR,
                    selected_at=timestamp,
                    selection_method="google_oidc_oauth",
                ),
                workspace_memberships=[
                    WorkspaceMember(user_id=APPROVER_ACTOR, workspace_id=WORKSPACE_ID, role="owner")
                ],
                current_workspace_id=WORKSPACE_ID,
                current_workspace_role="owner",
                external_identity_id=principal.external_identity_id,
                oauth_client_id=principal.oauth_client_id,
                oauth_token_session_id=principal.token_session_id,
                auth_mode="google_oidc_oauth",
                production_authentication=True,
            )
            with (
                patch.object(runtime.bridge, "authenticate_access_token", return_value=principal),
                patch.object(runtime.bridge, "resolve_actor_context", return_value=actor),
                patch.object(
                    runtime.bridge,
                    "record_mcp_authorization_decision",
                    return_value=None,
                ),
                TestClient(runtime.application.app, raise_server_exceptions=False) as client,
            ):
                headers = {
                    "Authorization": "Bearer semantic.runtime.token",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                }
                listed = client.post(
                    "/mcp",
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": "list", "method": "tools/list"},
                )
                query_request = {
                    "jsonrpc": "2.0",
                    "id": "query",
                    "method": "tools/call",
                    "params": {
                        "name": "query_effective_graph_view",
                        "arguments": {"query_text": private_query},
                    },
                }
                queried = client.post(
                    "/mcp",
                    headers=headers,
                    json=query_request,
                )

            tool_names = [tool["name"] for tool in listed.json()["result"]["tools"]]
            self.assertIn("query_effective_graph_view", tool_names)
            self.assertFalse(queried.json()["result"]["isError"])
            structured = queried.json()["result"]["structuredContent"]
            validate_public_gateway_payload(structured)
            data = structured["data"]
            self.assertTrue(data["answer"]["text"])
            self.assertEqual(
                data["answer"]["answer_hash"],
                sha256_json(data["answer"]["text"]),
            )
            self.assertGreaterEqual(data["answer"]["citation_count"], 1)
            self.assertEqual(data["answer"]["citation_count"], len(data["citations"]))
            self.assertGreaterEqual(data["relationship"]["path_count"], 1)
            self.assertEqual(data["relationship"]["path_count"], data["graph_hits"]["count"])
            self.assertGreaterEqual(data["relationship"]["max_hops"], 1)
            self.assertTrue(data["relationship"]["relation_types"])
            rendered = repr(structured)
            self.assertFalse(temporary_directory in rendered)
            self.assertFalse(str(query_file) in rendered)
            self.assertFalse("tenant" in rendered.lower())
            self.assertFalse("semantic.runtime.token" in rendered)
            self.assertFalse(private_query in rendered)
