from __future__ import annotations

import asyncio
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
import formowl_gateway.runtime as runtime_module
from formowl_contract import assert_no_public_raw_references, sha256_json
from formowl_gateway.issue56_uat_runtime import (
    Issue56UatQueryService,
    _follow_up_queries,
)
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_mail.human_uat_http import create_mail_human_uat_http_server
from test_connected_runtime import (
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)
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
    _oauth_context,
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
            with (
                patch.dict(__import__("os").environ, environment, clear=True),
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                    return_value=_FakeRepository(),
                ),
            ):
                config = ConnectedRuntimeConfig.from_env_and_secrets(environment)
                runtime = asyncio.run(
                    ConnectedRuntime.compose(
                        config,
                        http_client=_FakeHttpClient(),
                    )
                )
            principal, actor = _oauth_context(config)
            with (
                patch.object(
                    runtime.bridge,
                    "authenticate_access_token",
                    return_value=principal,
                ),
                patch.object(
                    runtime.bridge,
                    "resolve_actor_context",
                    return_value=actor,
                ),
                patch.object(
                    runtime.bridge,
                    "record_mcp_authorization_decision",
                    return_value=None,
                ),
                Issue56UatQueryService(
                    runtime,
                    bearer_token="explicit.test.uat.bearer",
                ) as query_service,
            ):
                server = create_mail_human_uat_http_server(
                    "127.0.0.1",
                    0,
                    query_service,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request("GET", "/")
                    page_response = connection.getresponse()
                    page = page_response.read().decode("utf-8")
                    connection.close()
                    self.assertEqual(page_response.status, 200)
                    self.assertIn('id="prompt-input"', page)

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
                    response = connection.getresponse()
                    payload = json.loads(response.read())
                    connection.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

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
