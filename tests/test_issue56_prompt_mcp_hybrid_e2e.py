from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import unittest
from unittest import mock

try:
    import _paths  # noqa: F401
    from formowl_contract import ContractValidationError, Observation, sha256_json
    from formowl_gateway import issue56_diagnostic as diagnostic_module
    from formowl_gateway.issue56_diagnostic import (
        ISSUE56_DIAGNOSTIC_CLAIM_STATUS,
        ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT,
        ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
        ISSUE56_DIAGNOSTIC_TOOL_NAME,
        ISSUE56_DIAGNOSTIC_USER_ID,
        ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_PROMPT,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
        ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID,
        Issue56SealedSourceDiagnosticInput,
        build_issue56_diagnostic_composition,
        build_issue56_sealed_source_diagnostic_input,
        build_safe_diagnostic_report,
        mcp_headers,
        mcp_initialize_request,
        mcp_list_tools_request,
        mcp_query_request,
    )
    from formowl_gateway.remote import _CONNECTED_TOOL_POLICIES
    from formowl_graph import EffectiveGraphView
    from formowl_graph.index import GraphProjectionEdge, GraphProjectionNode
    from formowl_mail import (
        ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        build_authorized_semantic_mail_session,
        build_mail_evidence_bundle,
    )
    from formowl_mail import hybrid as hybrid_module
    from formowl_mail.hybrid import AuthorizedSemanticMailSession
    from scripts import issue56_prompt_mcp_hybrid_diagnostic as diagnostic_runner
    from starlette.testclient import TestClient
except ModuleNotFoundError as exc:
    if exc.name not in {
        "authlib",
        "httpx",
        "mcp",
        "sentence_transformers",
        "starlette",
    }:
        raise
    _IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _IMPORT_ERROR = None


_PROJECT_SOURCE_SCOPE_ID = "project_issue56_sealed_source_fixture"
_CREATED_AT = "2026-08-20T08:00:00+00:00"


@unittest.skipIf(_IMPORT_ERROR is not None, f"focused E2E dependency unavailable: {_IMPORT_ERROR}")
class Issue56PromptMcpHybridE2ETests(unittest.TestCase):
    def test_prompt_crosses_real_http_oauth_dispatcher_gateway_and_hybrid(self) -> None:
        production_policy_names = frozenset(_CONNECTED_TOOL_POLICIES)
        composition = build_issue56_diagnostic_composition()
        self.assertIsInstance(composition.session, AuthorizedSemanticMailSession)
        expected_scope = {
            "scope_type": "workspace",
            "scope_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
            "visibility": "restricted",
        }
        self.assertTrue(composition.effective_graph_view.visible_nodes)
        self.assertTrue(composition.effective_graph_view.visible_edges)
        self.assertTrue(
            all(
                node.permission_scope == expected_scope
                for node in composition.effective_graph_view.visible_nodes
            )
        )
        self.assertTrue(
            all(
                edge.permission_scope == expected_scope
                for edge in composition.effective_graph_view.visible_edges
            )
        )

        started_at = time.perf_counter()
        with TestClient(
            composition.application.app,
            raise_server_exceptions=False,
        ) as client:
            initialized = client.post(
                "/mcp",
                json=mcp_initialize_request(),
                headers=mcp_headers(),
            )
            listed = client.post(
                "/mcp",
                json=mcp_list_tools_request(),
                headers=mcp_headers(),
            )
            queried = client.post(
                "/mcp",
                json=mcp_query_request(ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT),
                headers=mcp_headers(bearer=composition.bearer_token),
            )
        elapsed_ms = (time.perf_counter() - started_at) * 1_000.0

        self.assertEqual(initialized.status_code, 200, initialized.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(queried.status_code, 200, queried.text)
        tool_names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        self.assertEqual(tool_names, {"whoami", ISSUE56_DIAGNOSTIC_TOOL_NAME})
        rpc_result = queried.json()["result"]
        self.assertFalse(rpc_result["isError"], queried.text)
        structured = rpc_result["structuredContent"]
        self.assertEqual(structured["result_type"], "effective_graph_query")
        self.assertEqual(structured["status"], "ok")
        data = structured["data"]
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["answer"]["status"], "answered")
        self.assertGreaterEqual(data["answer"]["citation_count"], 2)
        self.assertGreaterEqual(data["graph_hits"]["count"], 1)
        self.assertEqual(
            data["diagnostic"]["runtime_method_fingerprint"],
            ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        )
        self.assertEqual(composition.state.authentication_count, 1)
        self.assertEqual(composition.state.actor_resolution_count, 1)
        self.assertEqual(composition.state.authorization_decision_count, 1)
        self.assertEqual(composition.state.semantic_handler_count, 1)
        self.assertEqual(composition.state.hybrid_query_count, 1)
        self.assertEqual(composition.state.answer_render_count, 1)
        self.assertEqual(
            composition.state.handler_requester_user_id,
            ISSUE56_DIAGNOSTIC_USER_ID,
        )
        self.assertEqual(
            composition.state.handler_workspace_id,
            ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
        )
        self.assertLess(
            composition.state.boundary_events.index("dispatcher_authorized"),
            composition.state.boundary_events.index("semantic_gateway_handler"),
        )
        self.assertLess(
            composition.state.boundary_events.index("semantic_gateway_handler"),
            composition.state.boundary_events.index("authorized_semantic_mail_session_query"),
        )
        self.assertEqual(
            data["diagnostic"]["phase_trace"]["terminal_status"],
            "completed",
        )
        self.assertGreater(
            data["diagnostic"]["phase_trace"]["phase_event_count"],
            0,
        )

        report = build_safe_diagnostic_report(
            composition=composition,
            prompt=ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT,
            initialize_response=initialized.json(),
            list_response=listed.json(),
            query_response=queried.json(),
            http_elapsed_ms=elapsed_ms,
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["claim_status"], ISSUE56_DIAGNOSTIC_CLAIM_STATUS)
        self.assertEqual(
            report["identity_scope_mode"],
            ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
        )
        self.assertEqual(report["methodology_authority_status"], "blocked")
        self.assertEqual(report["source_fixture_mode"], "synthetic_non_sealed")
        self.assertEqual(report["sealed_source_asset"], "not_exercised")
        self.assertEqual(
            report["external_google_oauth_exchange"],
            "not_exercised",
        )
        self.assertEqual(
            report["production_connected_tool_policy"],
            "not_exercised",
        )
        self.assertNotIn("oauth_principal", report["boundary_status"])
        self.assertEqual(
            report["boundary_status"]["synthetic_preverified_principal"],
            "passed",
        )
        self.assertEqual(report["counts"]["hybrid_query_count"], 1)
        self.assertNotIn(ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT, json.dumps(report))
        self._assert_no_legacy_identity_fields(report)
        self.assertEqual(frozenset(_CONNECTED_TOOL_POLICIES), production_policy_names)

    def test_invalid_bearer_fails_before_actor_and_hybrid(self) -> None:
        composition = build_issue56_diagnostic_composition()
        with TestClient(
            composition.application.app,
            raise_server_exceptions=False,
        ) as client:
            queried = client.post(
                "/mcp",
                json=mcp_query_request(ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT),
                headers=mcp_headers(bearer="invalid.synthetic.bearer"),
            )

        self.assertEqual(queried.status_code, 401, queried.text)
        self.assertEqual(composition.state.authentication_count, 1)
        self.assertEqual(composition.state.actor_resolution_count, 0)
        self.assertEqual(composition.state.semantic_handler_count, 0)
        self.assertEqual(composition.state.hybrid_query_count, 0)
        self.assertEqual(composition.state.answer_render_count, 0)

    def test_caller_controlled_identity_is_rejected_before_hybrid(self) -> None:
        composition = build_issue56_diagnostic_composition()
        request = mcp_query_request(ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT)
        request["params"]["arguments"]["requester_user_id"] = "user_injected"
        with TestClient(
            composition.application.app,
            raise_server_exceptions=False,
        ) as client:
            queried = client.post(
                "/mcp",
                json=request,
                headers=mcp_headers(bearer=composition.bearer_token),
            )

        self.assertEqual(queried.status_code, 200, queried.text)
        result = queried.json()["result"]
        self.assertTrue(result["isError"], queried.text)
        self.assertEqual(composition.state.authentication_count, 1)
        self.assertEqual(composition.state.actor_resolution_count, 1)
        self.assertEqual(composition.state.semantic_handler_count, 0)
        self.assertEqual(composition.state.hybrid_query_count, 0)
        self.assertIn("dispatcher_denied", composition.state.boundary_events)

    def test_workspace_mismatch_fails_closed_before_hybrid_query(self) -> None:
        composition = build_issue56_diagnostic_composition(
            actor_workspace_id="workspace_issue56_mismatch"
        )
        with TestClient(
            composition.application.app,
            raise_server_exceptions=False,
        ) as client:
            queried = client.post(
                "/mcp",
                json=mcp_query_request(ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT),
                headers=mcp_headers(bearer=composition.bearer_token),
            )

        self.assertEqual(queried.status_code, 200, queried.text)
        self.assertTrue(queried.json()["result"]["isError"], queried.text)
        self.assertEqual(composition.state.semantic_handler_count, 1)
        self.assertEqual(composition.state.hybrid_query_count, 0)
        self.assertEqual(composition.state.answer_render_count, 0)

    def test_report_rejects_prompt_binding_tamper(self) -> None:
        composition = build_issue56_diagnostic_composition()
        with TestClient(
            composition.application.app,
            raise_server_exceptions=False,
        ) as client:
            initialized = client.post(
                "/mcp",
                json=mcp_initialize_request(),
                headers=mcp_headers(),
            )
            listed = client.post(
                "/mcp",
                json=mcp_list_tools_request(),
                headers=mcp_headers(),
            )
            queried = client.post(
                "/mcp",
                json=mcp_query_request(ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT),
                headers=mcp_headers(bearer=composition.bearer_token),
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "prompt/result binding mismatch",
        ):
            build_safe_diagnostic_report(
                composition=composition,
                prompt="different synthetic prompt",
                initialize_response=initialized.json(),
                list_response=listed.json(),
                query_response=queried.json(),
                http_elapsed_ms=1.0,
            )

    def test_sealed_source_mode_executes_once_and_publishes_safe_report(self) -> None:
        source = self._build_temp_sealed_source()
        loader_calls = 0

        def loader() -> Issue56SealedSourceDiagnosticInput:
            nonlocal loader_calls
            loader_calls += 1
            return source

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with (
                mock.patch.object(
                    hybrid_module,
                    "precompute_evidence_identity_lineage_crosswalk",
                    side_effect=AssertionError(
                        "gateway must consume Worker A lineage precompute evidence "
                        "without reinvocation"
                    ),
                ),
                mock.patch.object(
                    hybrid_module,
                    "precompute_relation_projection_base",
                    side_effect=AssertionError(
                        "gateway must consume Worker A relation-base precompute "
                        "evidence without reinvocation"
                    ),
                ),
            ):
                report = diagnostic_runner.run_sealed_source_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json(
                        {
                            "loader_contract_id": ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID,
                            "loader_spec": "tests.temp_loader:load",
                        }
                    ),
                    state_root=state_root,
                )
            self.assertEqual(loader_calls, 1)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(
                report["diagnostic_mode_id"],
                ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            )
            self.assertEqual(report["source_fixture_mode"], "sealed_source")
            self.assertEqual(
                report["sealed_source_asset"],
                "validated_and_exercised",
            )
            self.assertEqual(report["version_guard"]["status"], "consumed_once")
            self.assertEqual(report["quality_claim"], "not_made")
            self.assertTrue(report["diagnostic_only"])
            self.assertEqual(report["real_llm"], "not_exercised")
            self.assertEqual(
                report["boundary_status"]["sealed_source_loader"],
                "passed",
            )
            self.assertEqual(
                report["boundary_status"]["lineage_crosswalk_precompute"],
                "passed",
            )
            self.assertEqual(
                report["boundary_status"]["lineage_crosswalk_cache_hit"],
                "passed",
            )
            self.assertEqual(
                report["lineage_crosswalk_precompute"]["status"],
                "passed",
            )
            self.assertEqual(
                report["lineage_crosswalk_precompute"]["cache_status"],
                "primed",
            )
            self.assertEqual(
                report["lineage_crosswalk_precompute"]["helper_invocation_count"],
                1,
            )
            self.assertEqual(
                report["lineage_crosswalk_query"],
                {
                    "cache_hit_status": "passed",
                    "query_binding_status": "passed",
                },
            )
            self.assertEqual(report["counts"]["lineage_crosswalk_precompute_count"], 1)
            self.assertEqual(
                report["counts"]["relation_projection_base_precompute_count"],
                1,
            )
            self.assertGreaterEqual(
                report["timing"]["lineage_crosswalk_precompute_elapsed_ms"],
                0,
            )
            self.assertGreaterEqual(
                report["timing"]["relation_projection_base_precompute_elapsed_ms"],
                0,
            )
            self.assertEqual(
                report["relation_projection_base_precompute"]["status"],
                "passed",
            )
            self.assertEqual(
                report["relation_projection_base_precompute"]["cache_status"],
                "primed",
            )
            self.assertEqual(
                report["relation_projection_base_precompute"]["helper_invocation_count"],
                1,
            )
            self.assertEqual(
                report["relation_projection_query"],
                {
                    "prequery_cache_status": "primed",
                    "timing_source": "semantic_phase_trace_relation_projection",
                },
            )
            self.assertEqual(
                report["boundary_status"]["relation_projection_base_precompute"],
                "passed",
            )
            self.assertGreaterEqual(
                report["timing"]["source_loader_elapsed_ms"],
                0,
            )
            self.assertTrue(report["safe_trace_binding_fingerprint"].startswith("sha256:"))
            self.assertEqual(
                report["counts"]["source_observation_count"],
                source.observation_count,
            )
            self.assertTrue(
                all(
                    dict(observation.permission_scope)
                    == {
                        "scope_type": "project",
                        "scope_id": _PROJECT_SOURCE_SCOPE_ID,
                        "visibility": "restricted",
                    }
                    for observation in source.session.authorized_observations
                )
            )
            self.assertTrue(
                report["source_binding"]["permission_lineage_fingerprint"].startswith("sha256:")
            )
            claim_path, report_path = diagnostic_runner._sealed_paths(state_root)
            self.assertTrue(claim_path.is_file())
            self.assertTrue(report_path.is_file())
            claim = json.loads(claim_path.read_text())
            self.assertEqual(
                claim["artifact_id"],
                "formowl_issue56_sealed_source_diagnostic_consumed_claim_v3",
            )
            self.assertEqual(claim["schema_version"], 3)
            self.assertEqual(
                claim["diagnostic_mode_id"],
                ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            )
            self.assertEqual(json.loads(report_path.read_text()), report)
            semantic_phases = {
                phase["phase"]: phase for phase in report["timing"]["semantic_phases"]["phases"]
            }
            self.assertIn("relation_projection", semantic_phases)
            self.assertGreaterEqual(
                semantic_phases["relation_projection"]["elapsed_ms"],
                0,
            )
            rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
            self.assertNotIn(ISSUE56_SEALED_SOURCE_DIAGNOSTIC_PROMPT, rendered)
            self.assertNotIn("SUPPLIER-ALPHA-01", rendered)
            self.assertNotIn(_PROJECT_SOURCE_SCOPE_ID, rendered)
            self.assertNotIn("permission_scope", rendered)
            self._assert_no_legacy_identity_fields(report)

            with self.assertRaisesRegex(
                ContractValidationError,
                "already consumed",
            ):
                diagnostic_runner.run_sealed_source_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json(
                        {
                            "loader_contract_id": (ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID),
                            "loader_spec": "tests.temp_loader:load",
                        }
                    ),
                    state_root=state_root,
                )
            self.assertEqual(loader_calls, 1)

    def test_sealed_v1_is_immutable_and_rejected_without_loader_or_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = diagnostic_runner.main(
                    [
                        "--mode",
                        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
                        "--sealed-source-loader",
                        "tests.must_not_load:load",
                        "--state-root",
                        str(state_root),
                    ]
                )
            blocked = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(
                blocked["diagnostic_mode_id"],
                ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
            )
            self.assertEqual(blocked["version_guard_status"], "consumed")
            self.assertEqual(list(state_root.iterdir()), [])
            self._assert_no_legacy_identity_fields(blocked)

    def test_sealed_v2_is_immutable_and_rejected_without_loader_or_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = diagnostic_runner.main(
                    [
                        "--mode",
                        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
                        "--sealed-source-loader",
                        "tests.must_not_load:load",
                        "--state-root",
                        str(state_root),
                    ]
                )
            blocked = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(
                blocked["diagnostic_mode_id"],
                ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
            )
            self.assertEqual(blocked["version_guard_status"], "consumed")
            self.assertEqual(list(state_root.iterdir()), [])
            self._assert_no_legacy_identity_fields(blocked)

    def test_sealed_source_failure_consumes_version_without_partial_output(self) -> None:
        source = self._build_temp_sealed_source()
        loader_calls = 0

        def loader() -> Issue56SealedSourceDiagnosticInput:
            nonlocal loader_calls
            loader_calls += 1
            return source

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with mock.patch.object(
                diagnostic_runner,
                "_run_http_diagnostic",
                side_effect=RuntimeError("synthetic_crash_after_claim"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "synthetic_crash_after_claim",
                ):
                    diagnostic_runner.run_sealed_source_diagnostic_once(
                        loader=loader,
                        loader_spec_fingerprint=sha256_json(
                            {
                                "loader_contract_id": (ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID),
                                "loader_spec": "tests.temp_loader:load",
                            }
                        ),
                        state_root=state_root,
                    )
            claim_path, report_path = diagnostic_runner._sealed_paths(state_root)
            self.assertTrue(claim_path.is_file())
            self.assertFalse(report_path.exists())
            self.assertEqual(loader_calls, 1)
            with self.assertRaisesRegex(
                ContractValidationError,
                "already consumed",
            ):
                diagnostic_runner.run_sealed_source_diagnostic_once(
                    loader=loader,
                    loader_spec_fingerprint=sha256_json(
                        {
                            "loader_contract_id": (ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID),
                            "loader_spec": "tests.temp_loader:load",
                        }
                    ),
                    state_root=state_root,
                )
            self.assertEqual(loader_calls, 1)

    def test_sealed_source_claim_race_has_one_winner_and_one_loader_call(self) -> None:
        source = self._build_temp_sealed_source()
        loader_calls: list[str] = []
        barrier = threading.Barrier(2)
        loader_spec_fingerprint = sha256_json(
            {
                "loader_contract_id": ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID,
                "loader_spec": "tests.temp_loader:load",
            }
        )

        def loader() -> Issue56SealedSourceDiagnosticInput:
            loader_calls.append("called")
            return source

        def attempt(state_root: Path) -> tuple[str, Any]:
            barrier.wait()
            try:
                return (
                    "passed",
                    diagnostic_runner.run_sealed_source_diagnostic_once(
                        loader=loader,
                        loader_spec_fingerprint=loader_spec_fingerprint,
                        state_root=state_root,
                    ),
                )
            except ContractValidationError as exc:
                return ("blocked", str(exc))

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: attempt(state_root), range(2)))
            self.assertEqual(
                sorted(status for status, _ in results),
                ["blocked", "passed"],
            )
            self.assertEqual(loader_calls, ["called"])
            blocked_reason = next(value for status, value in results if status == "blocked")
            self.assertIn("already exists", blocked_reason)
            claim_path, report_path = diagnostic_runner._sealed_paths(state_root)
            self.assertTrue(claim_path.is_file())
            self.assertTrue(report_path.is_file())

    def test_consumed_v3_rejects_prompt_tuning_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = diagnostic_runner.main(
                    [
                        "--mode",
                        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
                        "--prompt",
                        "caller supplied prompt",
                        "--sealed-source-loader",
                        "tests.does_not_exist:load",
                        "--state-root",
                        str(state_root),
                    ]
                )
            self.assertEqual(exit_code, 2)
            blocked = json.loads(stdout.getvalue())
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["version_guard_status"], "consumed")
            self.assertEqual(list(state_root.iterdir()), [])
            self.assertNotIn("caller supplied prompt", stdout.getvalue())
            self._assert_no_legacy_identity_fields(blocked)

    def test_sealed_source_binding_drift_fails_closed_before_http(self) -> None:
        source = self._build_temp_sealed_source()
        drifted = replace(source, observation_count=source.observation_count + 1)
        with self.assertRaisesRegex(
            ContractValidationError,
            "observation count mismatch",
        ):
            build_issue56_diagnostic_composition(
                diagnostic_mode_id=ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
                sealed_source=drifted,
            )

    def test_relation_projection_base_precompute_drift_fails_before_http(self) -> None:
        source = self._build_temp_sealed_source()
        drifted_precompute = replace(
            source.relation_projection_base_precompute,
            cache_binding_fingerprint=sha256_json("drifted relation projection base"),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "relation projection base precompute binding mismatch",
        ):
            build_issue56_diagnostic_composition(
                diagnostic_mode_id=ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
                sealed_source=replace(
                    source,
                    relation_projection_base_precompute=drifted_precompute,
                ),
            )

    def test_project_scoped_source_requires_the_authorized_workspace_session(
        self,
    ) -> None:
        source = self._build_temp_sealed_source()
        composition = build_issue56_diagnostic_composition(
            actor_workspace_id="workspace_issue56_mismatch",
            diagnostic_mode_id=ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            sealed_source=source,
        )
        with TestClient(
            composition.application.app,
            raise_server_exceptions=False,
        ) as client:
            queried = client.post(
                "/mcp",
                json=mcp_query_request(ISSUE56_SEALED_SOURCE_DIAGNOSTIC_PROMPT),
                headers=mcp_headers(bearer=composition.bearer_token),
            )

        self.assertEqual(queried.status_code, 200, queried.text)
        self.assertTrue(queried.json()["result"]["isError"], queried.text)
        self.assertEqual(composition.state.semantic_handler_count, 1)
        self.assertEqual(composition.state.hybrid_query_count, 0)

        drifted_session = replace(
            source.session,
            workspace_id="workspace_issue56_mismatch",
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "identity binding mismatch",
        ):
            build_issue56_diagnostic_composition(
                diagnostic_mode_id=ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
                sealed_source=replace(source, session=drifted_session),
            )

    def test_project_scoped_graph_permission_drift_fails_closed(self) -> None:
        source = self._build_temp_sealed_source()
        for item_kind, label in (
            ("node", "graph node permission lineage mismatch"),
            ("edge", "graph edge permission lineage mismatch"),
        ):
            with self.subTest(label=label):
                drifted_view = self._copy_effective_graph_view(
                    source.effective_graph_view,
                    drift_item_kind=item_kind,
                    permission_scope={
                        "scope_type": "project",
                        "scope_id": "project_issue56_drifted",
                        "visibility": "restricted",
                    },
                )
                with self.assertRaisesRegex(
                    ContractValidationError,
                    label,
                ):
                    build_issue56_diagnostic_composition(
                        diagnostic_mode_id=(ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID),
                        sealed_source=replace(
                            source,
                            effective_graph_view=drifted_view,
                        ),
                    )

    def test_project_scoped_observation_permission_drift_fails_closed(self) -> None:
        source = self._build_temp_sealed_source()
        permission_scope = source.session.authorized_observations[0].permission_scope
        original_scope_id = permission_scope["scope_id"]
        permission_scope["scope_id"] = "project_issue56_drifted"
        try:
            with self.assertRaisesRegex(
                ContractValidationError,
                "authorized observation seal mismatch",
            ):
                build_issue56_diagnostic_composition(
                    diagnostic_mode_id=ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
                    sealed_source=source,
                )
        finally:
            permission_scope["scope_id"] = original_scope_id

    def test_sealed_source_rejects_arbitrary_or_tenant_permission_scope(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "permission scope type is unsupported",
        ):
            self._build_temp_sealed_source(
                permission_scope={
                    "scope_type": "organization",
                    "scope_id": "organization_issue56_arbitrary",
                    "visibility": "restricted",
                }
            )

        source = self._build_temp_sealed_source()
        tenant_view = self._copy_effective_graph_view(
            source.effective_graph_view,
            drift_item_kind="node",
            permission_scope={
                "scope_type": "project",
                "scope_id": _PROJECT_SOURCE_SCOPE_ID,
                "visibility": "restricted",
                "tenant_id": "forbidden",
            },
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "legacy identity field is forbidden",
        ):
            build_issue56_diagnostic_composition(
                diagnostic_mode_id=ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
                sealed_source=replace(source, effective_graph_view=tenant_view),
            )

    def test_sealed_source_rejects_legacy_tenant_field(self) -> None:
        source = self._build_temp_sealed_source()
        tenant_view = self._copy_effective_graph_view(
            source.effective_graph_view,
            drift_item_kind="node",
            extra_properties={"tenant_id": "forbidden"},
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "legacy identity field is forbidden",
        ):
            build_issue56_diagnostic_composition(
                diagnostic_mode_id=ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
                sealed_source=replace(source, effective_graph_view=tenant_view),
            )

    def test_sealed_source_loader_spec_rejects_filesystem_paths(self) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "loader spec is invalid",
        ):
            diagnostic_runner.resolve_sealed_source_loader("/workspace/private_loader.py:load")

    def test_script_startup_resolves_real_sealed_source_loader_spec(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        probe = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                (
                    "import runpy; "
                    "namespace = runpy.run_path("
                    "'scripts/issue56_prompt_mcp_hybrid_diagnostic.py', "
                    "run_name='issue56_cli_startup_probe'"
                    "); "
                    "loader = namespace['resolve_sealed_source_loader']("
                    "'formowl_gateway.issue56_sealed_source_loader:"
                    "load_issue56_sealed_source_diagnostic_input'"
                    "); "
                    "assert callable(loader)"
                ),
            ],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            probe.returncode,
            0,
            msg=f"sealed loader startup probe failed: {probe.stderr}",
        )

    def test_canonical_dev_runtime_is_pinned_to_python_3_12_11(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        dockerfile = (repository_root / "containers" / "dev" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertTrue(
            dockerfile.startswith(
                "# syntax=docker/dockerfile:1\n\n" "FROM python:3.12.11-slim-trixie\n"
            )
        )

    def _build_temp_sealed_source(
        self,
        *,
        permission_scope: dict[str, Any] | None = None,
    ) -> Issue56SealedSourceDiagnosticInput:
        source_permission_scope = permission_scope or {
            "scope_type": "project",
            "scope_id": _PROJECT_SOURCE_SCOPE_ID,
            "visibility": "restricted",
        }
        observations = tuple(
            replace(
                observation,
                permission_scope=dict(source_permission_scope),
            )
            for observation in diagnostic_module._synthetic_observations()
        )
        bundle = build_mail_evidence_bundle(
            observations,
            workspace_id=ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
            owner_user_id=ISSUE56_DIAGNOSTIC_USER_ID,
            source_asset_id="asset_issue56_prompt_mcp_synthetic",
            archive_sha256=sha256_json("issue56_prompt_mcp_synthetic_archive"),
            producer_type="server_side_parser",
            parser_name="issue56_prompt_mcp_synthetic_fixture",
            parser_version="v1",
            upload_session_id="upload_issue56_prompt_mcp_synthetic",
            created_at=_CREATED_AT,
            started_at=_CREATED_AT,
            completed_at=_CREATED_AT,
        )
        session = build_authorized_semantic_mail_session(
            observations_by_bundle_id={
                bundle.mail_evidence_bundle_id: observations,
            },
            bundles=(bundle,),
            requester_user_id=ISSUE56_DIAGNOSTIC_USER_ID,
            workspace_id=ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
        )
        first_body = self._observation_by_id(
            observations,
            "obs_issue56_prompt_mcp_body_1",
        )
        second_body = self._observation_by_id(
            observations,
            "obs_issue56_prompt_mcp_body_2",
        )
        nodes = [
            GraphProjectionNode(
                node_id="node_issue56_prompt_mcp_po",
                source_type="canonical_entity",
                source_id="entity_node_issue56_prompt_mcp_po",
                labels=["PO470002002", "purchase order"],
                properties={
                    "label": "PO470002002",
                    "source_observation_ids": [first_body.observation_id],
                    "temporal_state": "current",
                    "core_supertype_id": "Artifact",
                    "type_confidence": 0.95,
                },
                permission_scope=dict(source_permission_scope),
            ),
            GraphProjectionNode(
                node_id="node_issue56_prompt_mcp_supplier",
                source_type="canonical_entity",
                source_id="entity_node_issue56_prompt_mcp_supplier",
                labels=["SUPPLIER-ALPHA-01", "supplier"],
                properties={
                    "label": "SUPPLIER-ALPHA-01",
                    "source_observation_ids": [first_body.observation_id],
                    "temporal_state": "current",
                    "core_supertype_id": "Organization",
                    "type_confidence": 0.95,
                },
                permission_scope=dict(source_permission_scope),
            ),
            GraphProjectionNode(
                node_id="node_issue56_prompt_mcp_origin",
                source_type="canonical_entity",
                source_id="entity_node_issue56_prompt_mcp_origin",
                labels=["ORIGIN-TAIWAN-01", "origin"],
                properties={
                    "label": "ORIGIN-TAIWAN-01",
                    "source_observation_ids": [second_body.observation_id],
                    "temporal_state": "current",
                    "core_supertype_id": "Location",
                    "type_confidence": 0.95,
                },
                permission_scope=dict(source_permission_scope),
            ),
        ]
        edges = [
            GraphProjectionEdge(
                edge_id="edge_issue56_prompt_mcp_supplied_by",
                source_node_id=nodes[0].node_id,
                target_node_id=nodes[1].node_id,
                relation_type="supplied_by",
                properties={
                    "canonical_relation_id": "edge_issue56_prompt_mcp_supplied_by",
                    "source_observation_ids": [first_body.observation_id],
                },
                permission_scope=dict(source_permission_scope),
            ),
            GraphProjectionEdge(
                edge_id="edge_issue56_prompt_mcp_origin_in",
                source_node_id=nodes[1].node_id,
                target_node_id=nodes[2].node_id,
                relation_type="origin_in",
                properties={
                    "canonical_relation_id": "edge_issue56_prompt_mcp_origin_in",
                    "source_observation_ids": [second_body.observation_id],
                },
                permission_scope=dict(source_permission_scope),
            ),
        ]
        effective_graph_view = EffectiveGraphView(
            requester_user_id=ISSUE56_DIAGNOSTIC_USER_ID,
            user_graph_revision_id="ugraph_issue56_prompt_mcp_v1",
            canonical_graph_revision_id="cgraph_issue56_prompt_mcp_v1",
            ontology_revision_id="ontology_issue56_prompt_mcp_v1",
            assembly_policy_id="assembly_issue56_prompt_mcp_v1",
            visible_nodes=nodes,
            visible_edges=edges,
        )
        lineage_crosswalk = hybrid_module.precompute_evidence_identity_lineage_crosswalk(
            session=session,
            effective_graph_view=effective_graph_view,
        )
        precompute_counts = {
            "authorized_evidence_count": lineage_crosswalk.authorized_evidence_count,
            "indexed_evidence_count": lineage_crosswalk.indexed_evidence_count,
            "occurrence_bound_evidence_count": (lineage_crosswalk.occurrence_bound_evidence_count),
            "graph_node_bound_evidence_count": (lineage_crosswalk.graph_node_bound_evidence_count),
            "graph_edge_bound_evidence_count": (lineage_crosswalk.graph_edge_bound_evidence_count),
        }
        precompute_binding = {
            "artifact_id": "formowl_issue56_lineage_crosswalk_precompute_safe_v1",
            "schema_version": 1,
            "status": "passed",
            "cache_status": "primed",
            "helper_invocation_count": 1,
            "elapsed_ms": 1.0,
            "crosswalk_fingerprint": lineage_crosswalk.crosswalk_fingerprint,
            "index_fingerprint": lineage_crosswalk.index_fingerprint,
            "graph_revision_fingerprint": (lineage_crosswalk.graph_revision_fingerprint),
            "cache_key_fingerprint": sha256_json(
                {
                    "artifact_id": ("formowl_issue56_evidence_identity_lineage_cache_key_v1"),
                    "index_fingerprint": lineage_crosswalk.index_fingerprint,
                    "graph_revision_fingerprint": (lineage_crosswalk.graph_revision_fingerprint),
                }
            ),
            "counts": precompute_counts,
        }
        relation_precompute = hybrid_module.precompute_relation_projection_base(
            session=session,
            effective_graph_view=effective_graph_view,
        )
        relation_precompute_binding = relation_precompute.to_safe_dict()
        relation_precompute_binding["helper_invocation_count"] = 1
        relation_precompute_binding["elapsed_ms"] = 2.0
        return build_issue56_sealed_source_diagnostic_input(
            session=session,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=("origin_in", "supplied_by"),
            source_asset_fingerprint=sha256_json("temporary sealed-source diagnostic fixture"),
            loader_contract_fingerprint=sha256_json(
                {
                    "loader_contract_id": ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID,
                    "fixture": "temporary_sealed_source",
                }
            ),
            graph_revision_fingerprint=(lineage_crosswalk.graph_revision_fingerprint),
            source_loader_binding_fingerprint=sha256_json(
                {
                    "fixture": "temporary_sealed_source_owner_binding",
                    "lineage_crosswalk_fingerprint": (lineage_crosswalk.crosswalk_fingerprint),
                }
            ),
            lineage_crosswalk_precompute=precompute_binding,
            relation_projection_base_precompute=relation_precompute_binding,
        )

    def _observation_by_id(
        self,
        observations: tuple[Observation, ...],
        observation_id: str,
    ) -> Observation:
        return next(
            observation
            for observation in observations
            if observation.observation_id == observation_id
        )

    def _copy_effective_graph_view(
        self,
        view: EffectiveGraphView,
        *,
        drift_item_kind: str,
        permission_scope: dict[str, Any] | None = None,
        extra_properties: dict[str, Any] | None = None,
    ) -> EffectiveGraphView:
        nodes = [GraphProjectionNode.from_dict(node.to_dict()) for node in view.visible_nodes]
        edges = [GraphProjectionEdge.from_dict(edge.to_dict()) for edge in view.visible_edges]
        if drift_item_kind == "node":
            item = nodes[0]
            nodes[0] = replace(
                item,
                permission_scope=(
                    dict(permission_scope)
                    if permission_scope is not None
                    else dict(item.permission_scope)
                ),
                properties=dict(item.properties) | (extra_properties or {}),
            )
        elif drift_item_kind == "edge":
            item = edges[0]
            edges[0] = replace(
                item,
                permission_scope=(
                    dict(permission_scope)
                    if permission_scope is not None
                    else dict(item.permission_scope)
                ),
                properties=dict(item.properties) | (extra_properties or {}),
            )
        else:
            self.fail(f"unsupported graph fixture item kind: {drift_item_kind}")
        return EffectiveGraphView(
            requester_user_id=view.requester_user_id,
            user_graph_revision_id=view.user_graph_revision_id,
            canonical_graph_revision_id=view.canonical_graph_revision_id,
            ontology_revision_id=view.ontology_revision_id,
            assembly_policy_id=view.assembly_policy_id,
            visible_nodes=nodes,
            visible_edges=edges,
            access_required=list(view.access_required),
            applied_grant_ids=list(view.applied_grant_ids),
        )

    def _assert_no_legacy_identity_fields(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                self.assertNotIn(str(key).lower(), {"tenant", "tenant_id"})
                self._assert_no_legacy_identity_fields(item)
        elif isinstance(value, list):
            for item in value:
                self._assert_no_legacy_identity_fields(item)


if __name__ == "__main__":
    unittest.main()
