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
from formowl_contract import (
    ContractValidationError,
    Observation,
    SessionIdentity,
    User,
    WorkspaceMember,
    sha256_json,
)
from formowl_gateway.issue56_sealed_source_loader import APPROVER_ACTOR, WORKSPACE_ID
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import validate_public_gateway_payload
from test_connected_runtime import (
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)


class ConnectedRuntimeSemanticMailE2ETests(unittest.IsolatedAsyncioTestCase):
    def test_participant_authorization_extends_lineage_without_reindexing(self) -> None:
        from formowl_mail import (
            build_authorized_semantic_mail_session,
            build_authorized_source_backed_effective_graph_view,
        )
        from scripts.issue56_semantic_execution_smoke import (
            REQUESTER_USER_ID,
            WORKSPACE_ID as SYNTHETIC_WORKSPACE_ID,
            build_semantic_poc_inputs,
        )
        from test_issue56_semantic_execution_e2e import _contract_only_runtime

        inputs = build_semantic_poc_inputs()
        bundle = inputs.current_bundle
        observations = tuple(
            inputs.observations_by_bundle_id[bundle.mail_evidence_bundle_id]
        )
        source = next(
            observation
            for observation in observations
            if observation.observation_type == "email_message"
        )
        header = Observation(
            observation_id=source.observation_id + "_participant_header",
            extractor_run_id=source.extractor_run_id,
            observation_type="email_header",
            modality="mail",
            location=dict(source.location),
            confidence=1.0,
            permission_scope=source.permission_scope,
            created_at=source.created_at,
            asset_id=source.asset_id,
            payload={
                "header_name": "From",
                "header_value": "source-authored@example.test",
            },
        )
        indexed = {bundle.mail_evidence_bundle_id: observations}
        authorized = {bundle.mail_evidence_bundle_id: (*observations, header)}
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=_contract_only_runtime(),
        ):
            baseline = build_authorized_semantic_mail_session(
                observations_by_bundle_id=indexed,
                bundles=(bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=SYNTHETIC_WORKSPACE_ID,
            )
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=indexed,
                authorization_observations_by_bundle_id=authorized,
                bundles=(bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=SYNTHETIC_WORKSPACE_ID,
            )
        self.assertEqual(session.index.index_fingerprint, baseline.index.index_fingerprint)
        self.assertEqual(len(session.index.candidates), len(baseline.index.candidates))
        self.assertEqual(
            len(session.authorized_observations),
            len(baseline.authorized_observations) + 1,
        )
        header_hash = sha256_json(header.to_dict())
        self.assertEqual(dict(session.authorized_observation_hashes)[header.observation_id], header_hash)
        header_lineage = next(
            lineage
            for lineage in session.occurrence_lineages
            if lineage.source_observation_id == header.observation_id
        )
        self.assertEqual(
            header_lineage.occurrence_id,
            source.location["message_occurrence_id"],
        )
        source_binding = sha256_json("participant_authorization_graph_subset")
        expanded_graph = build_authorized_source_backed_effective_graph_view(
            session=session,
            observations_by_bundle_id=indexed,
            source_binding_fingerprint=source_binding,
        )
        self.assertEqual(expanded_graph.source_observation_count, len(observations))
        with self.assertRaisesRegex(
            ContractValidationError,
            "source-backed graph Observation lineage mismatch",
        ):
            build_authorized_source_backed_effective_graph_view(
                session=session,
                observations_by_bundle_id=authorized,
                source_binding_fingerprint=source_binding,
            )

    async def test_opt_in_real_source_exact_set_cursor_union(self) -> None:
        if os.environ.get("FORMOWL_RUN_ISSUE56_REAL_PRODUCTION_SEMANTIC_E2E") != "1":
            self.skipTest("real production semantic E2E is explicitly opt-in")

        private_inputs = []
        for environment_name, maximum_bytes in (
            ("FORMOWL_ISSUE56_PRODUCTION_QUERY_FILE", 4096),
            ("FORMOWL_ISSUE56_PRODUCTION_EXPECTED_COUNT_FILE", 32),
        ):
            value = os.environ.get(environment_name)
            if not value:
                self.fail("production private input is required")
            path = Path(value)
            try:
                file_stat = path.lstat()
                content = path.read_bytes()
            except OSError:
                self.fail("production private input is unavailable")
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or stat.S_IMODE(file_stat.st_mode) != 0o600
                or not content
                or len(content) > maximum_bytes
            ):
                self.fail("production private input contract is invalid")
            private_inputs.append((path, content))
        query_file, query_bytes = private_inputs[0]
        count_file, count_bytes = private_inputs[1]
        try:
            private_query = query_bytes.decode("utf-8").strip()
            expected_count = int(count_bytes.decode("ascii").strip())
        except (UnicodeError, ValueError):
            self.fail("production private input encoding is invalid")
        if not private_query or "\x00" in private_query or expected_count < 0:
            self.fail("production private input is invalid")

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
                ).json()
                tool = next(
                    tool
                    for tool in listed["result"]["tools"]
                    if tool["name"] == "query_effective_graph_view"
                )
                self.assertTrue(
                    {
                        "query_text",
                        "exact_inventory_kind",
                        "page_size",
                        "cursor",
                    }
                    <= set(tool["inputSchema"]["properties"])
                )
                exact_schema = tool["outputSchema"]["properties"]["data"]["properties"][
                    "exact_inventory"
                ]
                self.assertTrue(
                    {
                        "plan",
                        "total_count",
                        "returned_count",
                        "coverage_status",
                        "next_cursor",
                        "redacted_count",
                        "unsupported_count",
                        "unresolved_count",
                        "items",
                    }
                    <= set(exact_schema["required"])
                )

                cursor = None
                item_hashes: set[str] = set()
                returned_count = 0
                total_count = None
                final_page = None
                while True:
                    arguments = {
                        "query_text": private_query,
                        "exact_inventory_kind": "mail_message_occurrence",
                        "page_size": 100,
                    }
                    if cursor is not None:
                        arguments["cursor"] = cursor
                    queried = client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": "query",
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": arguments,
                            },
                        },
                    ).json()["result"]
                    if queried["isError"]:
                        self.fail("production exact-set MCP call failed")
                    structured = queried["structuredContent"]
                    validate_public_gateway_payload(structured)
                    data = structured["data"]
                    page = data["exact_inventory"]
                    final_page = page
                    self.assertEqual(page["returned_count"], len(page["items"]))
                    citation_hashes = set(data["citations"])
                    for item in page["items"]:
                        references = item["governed_references"]
                        self.assertTrue(references)
                        for reference in references:
                            self.assertIn(reference["citation_hash"], citation_hashes)
                            self.assertRegex(
                                reference["occurrence_lineage_fingerprint"],
                                r"^sha256:[0-9a-f]{64}$",
                            )
                    current = {item["item_hash"] for item in page["items"]}
                    self.assertTrue(item_hashes.isdisjoint(current))
                    item_hashes.update(current)
                    returned_count += page["returned_count"]
                    total_count = page["total_count"] if total_count is None else total_count
                    self.assertEqual(page["total_count"], total_count)
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break

            assert final_page is not None
            self.assertEqual(
                (
                    final_page["redacted_count"],
                    final_page["unsupported_count"],
                    final_page["unresolved_count"],
                ),
                (0, 0, 0),
            )
            self.assertEqual(final_page["coverage_status"], "complete")
            self.assertEqual(total_count, expected_count)
            self.assertEqual(returned_count, expected_count)
            self.assertEqual(len(item_hashes), expected_count)
            rendered = repr(structured)
            self.assertFalse(temporary_directory in rendered)
            self.assertFalse(str(query_file) in rendered)
            self.assertFalse(str(count_file) in rendered)
            self.assertFalse("tenant" in rendered.lower())
            self.assertFalse("semantic.runtime.token" in rendered)
            self.assertFalse(private_query in rendered)
