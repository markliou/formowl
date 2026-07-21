from __future__ import annotations

from collections.abc import Mapping
import gc
import inspect
import unittest
from unittest.mock import patch
import warnings

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_gateway import (
    PUBLIC_TOOL_SCHEMAS,
    SemanticMcpGateway,
    safe_workflow_error_envelope,
    validate_public_gateway_payload,
)


class SemanticMcpGatewayTests(unittest.TestCase):
    def test_public_tool_schema_contains_only_safe_semantic_tools(self) -> None:
        gateway = SemanticMcpGateway()

        public_tool_schema = gateway.public_tool_schema()

        tool_names = {schema["tool_name"] for schema in public_tool_schema["data"]["tools"]}
        self.assertEqual(
            tool_names,
            {
                "open_upload_session",
                "create_ingestion_job",
                "list_observations",
                "preview_graph_candidates",
                "query_effective_graph",
                "query_effective_graph_view",
                "query_mail_evidence",
                "answer_mail_case_progress",
                "request_graph_access",
                "submit_graph_review_decision",
                "generate_wiki_draft_from_graph_view",
            },
        )
        self.assertNotIn("direct_database_query_tool", str(public_tool_schema))
        self.assertNotIn("direct_filesystem_read_tool", str(public_tool_schema))
        self.assertNotIn("direct_canonical_mutation_tool", str(public_tool_schema))
        self.assertEqual(len(gateway.tool_call_logs), 1)

    def test_safe_error_envelope_does_not_echo_raw_path_sql_or_worker_internals(
        self,
    ) -> None:
        gateway = SemanticMcpGateway()

        safe_error_envelope = gateway.safe_error_envelope(
            tool_name="/srv/formowl/raw/customer.xlsx",
            error_code="select * from private_table worker_scratch",
        )

        rendered = str(safe_error_envelope).lower()
        self.assertEqual(safe_error_envelope["status"], "error")
        self.assertNotIn("/srv/formowl/raw", rendered)
        self.assertNotIn("select *", rendered)
        self.assertNotIn("worker_scratch", rendered)
        self.assertIn("safe_error_envelope", safe_error_envelope["warnings"])

    def test_forbidden_direct_tools_return_safe_error_without_side_effect_tools(self) -> None:
        gateway = SemanticMcpGateway()

        direct_database_query_tool = gateway.dispatch_tool(
            "direct_database_query_tool",
            {"sql": "select * from evidence"},
        )
        direct_filesystem_read_tool = gateway.dispatch_tool(
            "direct_filesystem_read_tool",
            {"path": "/home/formowl/private.txt"},
        )
        direct_canonical_mutation_tool = gateway.dispatch_tool(
            "direct_canonical_mutation_tool",
            {"canonical_graph_revision_id": "canonical_001"},
        )

        for result in [
            direct_database_query_tool,
            direct_filesystem_read_tool,
            direct_canonical_mutation_tool,
        ]:
            self.assertEqual(result["status"], "error")
            self.assertNotIn("select *", str(result).lower())
            self.assertNotIn("/home/formowl", str(result).lower())
            self.assertNotIn("canonical_graph_revision_id", str(result))
        self.assertEqual(len(gateway.tool_call_logs), 3)

    def test_missing_semantic_handlers_fail_without_synthesizing_domain_results(
        self,
    ) -> None:
        gateway = SemanticMcpGateway()

        upload = gateway.dispatch_tool(
            "open_upload_session",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "intent": "Upload sourced notes.",
            },
        )
        ingestion = gateway.dispatch_tool(
            "create_ingestion_job",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "asset_locator": "formowl://asset/asset_001",
            },
        )
        observations = gateway.dispatch_tool(
            "list_observations",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "asset_locator": "formowl://asset/asset_001",
            },
        )
        preview = gateway.dispatch_tool(
            "preview_graph_candidates",
            {"workspace_id": "workspace_main", "requester_user_id": "user_yifan"},
        )
        query = gateway.dispatch_tool(
            "query_effective_graph",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "query_text": "delivery risk",
            },
        )
        mail_query = gateway.dispatch_tool(
            "query_mail_evidence",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "query_text": "mail evidence",
                "mail_import_session_id": "mailimport_001",
            },
        )
        case_progress = gateway.dispatch_tool(
            "answer_mail_case_progress",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "case_id": "case_launch",
                "mail_import_session_id": "mailimport_001",
            },
        )
        review = gateway.dispatch_tool(
            "submit_graph_review_decision",
            {
                "proposal_id": "fusion_001",
                "decision": "defer",
                "reviewer_user_id": "user_reviewer",
            },
        )
        access = gateway.dispatch_tool(
            "request_graph_access",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "owner_user_id": "user_owner",
                "requested_scope": {"scope_type": "project", "scope_id": "formowl"},
                "requested_access_level": "evidence_snippet",
                "reason": "Review sourced project context.",
            },
        )
        draft = gateway.dispatch_tool(
            "generate_wiki_draft_from_graph_view",
            {"projection_spec_id": "projection_001", "requester_user_id": "user_yifan"},
        )

        results = [
            upload,
            ingestion,
            observations,
            preview,
            query,
            mail_query,
            case_progress,
            review,
            access,
            draft,
        ]
        for result in results:
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["data"]["error_code"], "handler_not_configured")
        self.assertNotIn("candidate_summaries", preview["data"])
        self.assertNotIn("access_request_id", access["data"])
        self.assertNotIn("audit_ref", review["data"])
        self.assertIn("deprecated_alias_use_query_effective_graph_view", query["warnings"])
        self.assertNotIn(
            "canonical_commit",
            str(
                [
                    upload,
                    ingestion,
                    observations,
                    preview,
                    query,
                    mail_query,
                    case_progress,
                    review,
                    access,
                    draft,
                ]
            ),
        )
        self.assertNotIn("raw_path", str(results))
        self.assertEqual(len(gateway.tool_call_logs), 10)

    def test_effective_graph_view_is_canonical_and_old_name_is_deprecated_alias(self) -> None:
        schemas = {schema["tool_name"]: schema for schema in PUBLIC_TOOL_SCHEMAS}

        self.assertEqual(
            schemas["query_effective_graph_view"]["compatibility"],
            {"status": "canonical"},
        )
        self.assertEqual(
            schemas["query_effective_graph"]["compatibility"],
            {
                "status": "deprecated_alias",
                "canonical_tool_name": "query_effective_graph_view",
            },
        )

        gateway = SemanticMcpGateway(
            retrieval_handler=lambda _payload: {
                "answer": "same governed answer",
                "citations": [],
                "visible_graph_snippets": [],
                "redaction_counts": {"hidden_records": 0},
            }
        )
        arguments = {
            "query_text": "delivery risk",
            "session_id": "session_alias",
            "workspace_id": "workspace_main",
            "requester_user_id": "user_alias",
        }
        canonical = gateway.dispatch_tool("query_effective_graph_view", arguments)
        alias = gateway.dispatch_tool("query_effective_graph", arguments)

        self.assertEqual(alias["data"], canonical["data"])
        self.assertNotIn("deprecated_alias_use_query_effective_graph_view", canonical["warnings"])
        self.assertIn("deprecated_alias_use_query_effective_graph_view", alias["warnings"])

    def test_gateway_rejects_handler_payloads_with_raw_values(self) -> None:
        gateway = SemanticMcpGateway(
            retrieval_handler=lambda _payload: {
                "answer": "select * from private_table",
                "citations": [],
                "visible_graph_snippets": [],
                "redaction_counts": {},
            }
        )

        with self.assertRaises(ContractValidationError):
            gateway.dispatch_tool(
                "query_effective_graph",
                {
                    "workspace_id": "workspace_main",
                    "requester_user_id": "user_yifan",
                    "query_text": "delivery risk",
                },
            )

    def test_handler_payload_snapshot_reads_stateful_containers_once_before_mail_validation(
        self,
    ) -> None:
        injected_coroutines: list[object] = []
        coroutine_execution_started: list[bool] = []
        raw_marker = "/tmp/raw-stateful-handler-second-read-secret"

        async def second_read_coroutine() -> dict[str, str]:
            coroutine_execution_started.append(True)
            return {"raw_path": raw_marker}

        class StatefulMapping(Mapping[str, object]):
            def __init__(self, safe_items: list[tuple[str, object]]) -> None:
                self.safe_items = tuple(safe_items)
                self.read_operations: list[str] = []
                self.active_items = dict(self.safe_items)

            def _begin_read(self, operation: str) -> tuple[tuple[str, object], ...]:
                self.read_operations.append(operation)
                if len(self.read_operations) == 1:
                    return self.safe_items
                injected = second_read_coroutine()
                injected_coroutines.append(injected)
                return (*self.safe_items, ("second_read_injection", injected))

            def items(self):
                return self._begin_read("items")

            def __iter__(self):
                self.active_items = dict(self._begin_read("__iter__"))
                return iter(self.active_items)

            def __getitem__(self, key: str) -> object:
                return self.active_items[key]

            def __len__(self) -> int:
                return len(self.safe_items)

        class StatefulList(list[object]):
            def __init__(self, values: list[object]) -> None:
                super().__init__(values)
                self.read_count = 0

            def __iter__(self):
                self.read_count += 1
                if self.read_count > 1:
                    injected = second_read_coroutine()
                    injected_coroutines.append(injected)
                    return iter([injected])
                return super().__iter__()

        class StatefulTuple(tuple[object, ...]):
            def __new__(cls, values: tuple[object, ...]):
                return super().__new__(cls, values)

            def __init__(self, values: tuple[object, ...]) -> None:
                del values
                self.read_count = 0

            def __iter__(self):
                self.read_count += 1
                if self.read_count > 1:
                    injected = second_read_coroutine()
                    injected_coroutines.append(injected)
                    return iter([injected])
                return super().__iter__()

        claim_boundary = StatefulMapping(
            [
                ("supports_mail_case_progress_answer_claim", True),
                ("supports_actual_chatgpt_connected_upload_claim", False),
                ("supports_upload_ui_claim", False),
                ("supports_production_iframe_readiness_claim", False),
                ("supports_real_pst_parser_claim", False),
                ("supports_live_postgresql_readiness_claim", False),
                ("supports_production_worker_leasing_claim", False),
                ("supports_kg_write_claim", False),
                ("supports_wiki_projection_claim", False),
                ("supports_production_ready_claim", False),
            ]
        )
        nested_tuple = StatefulTuple(("safe-tuple-value",))
        nested_list = StatefulList(["safe-list-value", nested_tuple])
        handler_payload = StatefulMapping(
            [
                ("status", "ok"),
                ("claim_boundary", claim_boundary),
                ("nested", nested_list),
            ]
        )
        gateway = SemanticMcpGateway(mail_case_progress_handler=lambda _arguments: handler_payload)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = gateway.dispatch_tool(
                "answer_mail_case_progress",
                {
                    "workspace_id": "workspace_main",
                    "requester_user_id": "user_yifan",
                    "case_id": "case_launch",
                    "mail_import_session_id": "mailimport_001",
                },
            )
            gc.collect()

        self.assertEqual(result["status"], "ok")
        self.assertIs(type(result["data"]), dict)
        self.assertIs(type(result["data"]["claim_boundary"]), dict)
        self.assertEqual(
            result["data"]["nested"],
            ["safe-list-value", ["safe-tuple-value"]],
        )
        self.assertEqual(handler_payload.read_operations, ["items"])
        self.assertEqual(claim_boundary.read_operations, ["items"])
        self.assertEqual(nested_list.read_count, 1)
        self.assertEqual(nested_tuple.read_count, 1)
        self.assertEqual(injected_coroutines, [])
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        self.assertEqual(len(gateway.tool_call_logs), 1)
        self.assertEqual(gateway.tool_call_logs[0].status, "ok")
        rendered_state = repr(
            {
                "result": result,
                "warnings": [str(item.message) for item in caught],
                "tool_logs": [item.to_dict() for item in gateway.tool_call_logs],
            }
        )
        self.assertNotIn("StatefulMapping", rendered_state)
        self.assertNotIn("second_read_coroutine", rendered_state)
        self.assertNotIn(raw_marker, rendered_state)

    def test_handler_payload_snapshot_wraps_hostile_iteration_and_closes_yielded_coroutines(
        self,
    ) -> None:
        returned_coroutines: list[object] = []
        coroutine_execution_started: list[bool] = []
        raw_marker = "/tmp/raw-hostile-handler-iteration-secret"

        async def yielded_coroutine() -> dict[str, str]:
            coroutine_execution_started.append(True)
            return {"raw_path": raw_marker}

        class HostileMapping(Mapping[str, object]):
            def items(self):
                returned_coroutine = yielded_coroutine()
                returned_coroutines.append(returned_coroutine)
                yield ("status", "ok")
                yield ("nested", [returned_coroutine])
                raise RuntimeError(f"{HostileMapping.__name__} leaked {raw_marker}")

            def __iter__(self):
                raise AssertionError("hostile mapping fallback read")

            def __getitem__(self, key: str) -> object:
                raise KeyError(key)

            def __len__(self) -> int:
                return 2

        gateway = SemanticMcpGateway(upload_session_handler=lambda _arguments: HostileMapping())

        with (
            warnings.catch_warnings(record=True) as caught,
            patch("formowl_gateway.semantic._envelope") as payload_envelope,
            patch("formowl_gateway.semantic.sha256_json") as payload_hasher,
        ):
            warnings.simplefilter("always")
            with self.assertRaises(ContractValidationError) as raised:
                gateway.dispatch_tool(
                    "open_upload_session",
                    {
                        "workspace_id": "workspace_main",
                        "requester_user_id": "user_yifan",
                    },
                )
            payload_envelope.assert_not_called()
            payload_hasher.assert_not_called()
            self.assertEqual(len(returned_coroutines), 1)
            returned_coroutine = returned_coroutines[0]
            self.assertIsNone(returned_coroutine.cr_frame)
            self.assertEqual(
                inspect.getcoroutinestate(returned_coroutine),
                inspect.CORO_CLOSED,
            )
            gc.collect()

        self.assertEqual(
            str(raised.exception),
            "semantic handler returned an invalid payload",
        )
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        self.assertEqual(gateway.tool_call_logs, [])
        rendered_state = repr(
            {
                "error": str(raised.exception),
                "warnings": [str(item.message) for item in caught],
                "tool_logs": [item.to_dict() for item in gateway.tool_call_logs],
            }
        )
        self.assertNotIn("HostileMapping", rendered_state)
        self.assertNotIn("yielded_coroutine", rendered_state)
        self.assertNotIn(raw_marker, rendered_state)

    def test_mail_case_progress_sync_handler_coroutine_is_closed_before_claim_validation(
        self,
    ) -> None:
        synchronous_effects: list[dict[str, object]] = []
        coroutine_execution_started: list[bool] = []
        returned_coroutines: list[object] = []
        raw_marker = "/tmp/raw-mail-handler-coroutine-secret"

        async def mail_handler_coroutine() -> dict[str, object]:
            coroutine_execution_started.append(True)
            return {
                "status": "ok",
                "raw_path": raw_marker,
            }

        def sync_handler(arguments: dict[str, object]) -> object:
            synchronous_effects.append(dict(arguments))
            returned_coroutine = mail_handler_coroutine()
            returned_coroutines.append(returned_coroutine)
            return returned_coroutine

        gateway = SemanticMcpGateway(mail_case_progress_handler=sync_handler)
        arguments = {
            "workspace_id": "workspace_main",
            "requester_user_id": "user_yifan",
            "case_id": "case_launch",
            "mail_import_session_id": "mailimport_001",
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with self.assertRaises(ContractValidationError) as raised:
                gateway.dispatch_tool("answer_mail_case_progress", arguments)
            self.assertEqual(len(returned_coroutines), 1)
            returned_coroutine = returned_coroutines[0]
            self.assertIsNone(returned_coroutine.cr_frame)
            returned_coroutines.clear()
            del returned_coroutine
            gc.collect()

        self.assertEqual(
            str(raised.exception),
            "semantic handler returned an invalid payload",
        )
        self.assertEqual(synchronous_effects, [arguments])
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        self.assertEqual(gateway.tool_call_logs, [])
        rendered_state = repr(
            {
                "error": str(raised.exception),
                "warnings": [str(item.message) for item in caught],
                "tool_logs": [item.to_dict() for item in gateway.tool_call_logs],
            }
        )
        self.assertNotIn("mail_handler_coroutine", rendered_state)
        self.assertNotIn(raw_marker, rendered_state)

    def test_mail_case_progress_nested_coroutine_is_closed_before_claim_validation(
        self,
    ) -> None:
        synchronous_effects: list[dict[str, object]] = []
        coroutine_execution_started: list[bool] = []
        returned_coroutines: list[object] = []
        raw_marker = "/tmp/raw-mail-handler-nested-coroutine-secret"

        async def nested_mail_handler_coroutine() -> dict[str, object]:
            coroutine_execution_started.append(True)
            return {
                "status": "ok",
                "raw_path": raw_marker,
            }

        def sync_handler(arguments: dict[str, object]) -> dict[str, object]:
            synchronous_effects.append(dict(arguments))
            returned_coroutine = nested_mail_handler_coroutine()
            returned_coroutines.append(returned_coroutine)
            return {
                "status": "ok",
                "claim_boundary": None,
                "nested": {
                    "items": (
                        "safe",
                        [returned_coroutine],
                    )
                },
            }

        gateway = SemanticMcpGateway(mail_case_progress_handler=sync_handler)
        arguments = {
            "workspace_id": "workspace_main",
            "requester_user_id": "user_yifan",
            "case_id": "case_launch",
            "mail_import_session_id": "mailimport_001",
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with self.assertRaises(ContractValidationError) as raised:
                gateway.dispatch_tool("answer_mail_case_progress", arguments)
            self.assertEqual(len(returned_coroutines), 1)
            returned_coroutine = returned_coroutines[0]
            self.assertIsNone(returned_coroutine.cr_frame)
            returned_coroutines.clear()
            del returned_coroutine
            gc.collect()

        self.assertEqual(
            str(raised.exception),
            "semantic handler returned an invalid payload",
        )
        self.assertEqual(synchronous_effects, [arguments])
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        self.assertEqual(gateway.tool_call_logs, [])
        rendered_state = repr(
            {
                "error": str(raised.exception),
                "warnings": [str(item.message) for item in caught],
                "tool_logs": [item.to_dict() for item in gateway.tool_call_logs],
            }
        )
        self.assertNotIn("nested_mail_handler_coroutine", rendered_state)
        self.assertNotIn(raw_marker, rendered_state)

    def test_nested_custom_and_started_awaitables_are_rejected_without_lifecycle_mutation(
        self,
    ) -> None:
        class TrackedCustomAwaitable:
            def __init__(self, raw_marker: str) -> None:
                self.raw_marker = raw_marker
                self.close_calls = 0

            def __await__(self):
                if False:
                    yield None
                return self.raw_marker

            def close(self) -> None:
                self.close_calls += 1

        class PauseOnce:
            def __await__(self):
                yield None

        coroutine_started: list[bool] = []
        coroutine_finalized: list[bool] = []
        custom_raw_marker = "/tmp/raw-custom-nested-awaitable-secret"
        started_raw_marker = "/tmp/raw-started-nested-coroutine-secret"
        custom_awaitable = TrackedCustomAwaitable(custom_raw_marker)

        async def started_nested_coroutine() -> dict[str, str]:
            coroutine_started.append(True)
            try:
                await PauseOnce()
                return {"raw_path": started_raw_marker}
            finally:
                coroutine_finalized.append(True)

        started_coroutine = started_nested_coroutine()
        started_coroutine.send(None)
        self.assertEqual(
            inspect.getcoroutinestate(started_coroutine),
            inspect.CORO_SUSPENDED,
        )

        gateway = SemanticMcpGateway(
            upload_session_handler=lambda _arguments: {
                "status": "ok",
                "nested": (
                    ["safe", custom_awaitable],
                    {"started": started_coroutine},
                ),
            }
        )

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with self.assertRaises(ContractValidationError) as raised:
                    gateway.dispatch_tool(
                        "open_upload_session",
                        {
                            "session_id": "session_direct",
                            "workspace_id": "workspace_main",
                            "requester_user_id": "user_yifan",
                        },
                    )
                self.assertEqual(
                    inspect.getcoroutinestate(started_coroutine),
                    inspect.CORO_SUSPENDED,
                )
                self.assertEqual(custom_awaitable.close_calls, 0)
                self.assertEqual(coroutine_finalized, [])
        finally:
            started_coroutine.close()
            gc.collect()

        self.assertEqual(
            str(raised.exception),
            "semantic handler returned an invalid payload",
        )
        self.assertEqual(coroutine_started, [True])
        self.assertEqual(coroutine_finalized, [True])
        self.assertEqual(custom_awaitable.close_calls, 0)
        self.assertEqual(caught, [])
        self.assertEqual(gateway.tool_call_logs, [])
        rendered_state = repr(
            {
                "error": str(raised.exception),
                "warnings": [str(item.message) for item in caught],
                "tool_logs": [item.to_dict() for item in gateway.tool_call_logs],
            }
        )
        self.assertNotIn("TrackedCustomAwaitable", rendered_state)
        self.assertNotIn("started_nested_coroutine", rendered_state)
        self.assertNotIn(custom_raw_marker, rendered_state)
        self.assertNotIn(started_raw_marker, rendered_state)

    def test_recursive_handler_payload_guard_rejects_cycles_and_closes_every_created_coroutine(
        self,
    ) -> None:
        coroutine_execution_started: list[str] = []
        raw_markers = {
            "key": "/tmp/raw-coroutine-mapping-key-secret",
            "set": "/tmp/raw-coroutine-set-member-secret",
            "frozenset": "/tmp/raw-coroutine-frozenset-member-secret",
        }

        async def coroutine_mapping_key() -> dict[str, str]:
            coroutine_execution_started.append("key")
            return {"raw_path": raw_markers["key"]}

        async def coroutine_set_member() -> dict[str, str]:
            coroutine_execution_started.append("set")
            return {"raw_path": raw_markers["set"]}

        async def coroutine_frozenset_member() -> dict[str, str]:
            coroutine_execution_started.append("frozenset")
            return {"raw_path": raw_markers["frozenset"]}

        mapping_key = coroutine_mapping_key()
        set_member = coroutine_set_member()
        frozenset_member = coroutine_frozenset_member()
        returned_coroutines = [mapping_key, set_member, frozenset_member]
        self.assertEqual(len({id(item) for item in returned_coroutines}), 3)
        for returned_coroutine in returned_coroutines:
            self.assertEqual(
                inspect.getcoroutinestate(returned_coroutine),
                inspect.CORO_CREATED,
            )
        handler_payload: dict[object, object] = {
            "status": "ok",
            "claim_boundary": None,
        }
        handler_payload["cycle"] = handler_payload
        handler_payload[mapping_key] = {
            "set_nesting": {set_member},
            "frozenset_nesting": frozenset({frozenset_member}),
        }
        gateway = SemanticMcpGateway(mail_case_progress_handler=lambda _arguments: handler_payload)

        with (
            warnings.catch_warnings(record=True) as caught,
            patch(
                "formowl_gateway.semantic._validate_mail_case_progress_handler_payload"
            ) as payload_validator,
            patch("formowl_gateway.semantic._envelope") as payload_envelope,
            patch("formowl_gateway.semantic.sha256_json") as payload_hasher,
        ):
            warnings.simplefilter("always")
            with self.assertRaises(ContractValidationError) as raised:
                gateway.dispatch_tool(
                    "answer_mail_case_progress",
                    {
                        "workspace_id": "workspace_main",
                        "requester_user_id": "user_yifan",
                        "case_id": "case_launch",
                        "mail_import_session_id": "mailimport_001",
                    },
                )
            payload_validator.assert_not_called()
            payload_envelope.assert_not_called()
            payload_hasher.assert_not_called()
            for returned_coroutine in returned_coroutines:
                self.assertIsNone(returned_coroutine.cr_frame)
                self.assertEqual(
                    inspect.getcoroutinestate(returned_coroutine),
                    inspect.CORO_CLOSED,
                )
            gc.collect()

        self.assertEqual(
            str(raised.exception),
            "semantic handler returned an invalid payload",
        )
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        self.assertEqual(gateway.tool_call_logs, [])
        rendered_state = repr(
            {
                "error": str(raised.exception),
                "warnings": [str(item.message) for item in caught],
                "tool_logs": [item.to_dict() for item in gateway.tool_call_logs],
            }
        )
        for function_name in (
            "coroutine_mapping_key",
            "coroutine_set_member",
            "coroutine_frozenset_member",
        ):
            self.assertNotIn(function_name, rendered_state)
        for raw_marker in raw_markers.values():
            self.assertNotIn(raw_marker, rendered_state)


class SemanticGatewayStaticContractTests(unittest.TestCase):
    def test_schema_constant_matches_expected_tool_count(self) -> None:
        no_raw_path_output = True
        no_raw_sql_output = True
        no_worker_internal_output = True
        safe_error_envelope = True

        self.assertEqual(len(PUBLIC_TOOL_SCHEMAS), 11)
        self.assertEqual(
            {schema["workflow"] for schema in PUBLIC_TOOL_SCHEMAS},
            {
                "upload",
                "ingestion",
                "observation",
                "mail_evidence",
                "candidate_graph",
                "access",
                "wiki_projection",
            },
        )
        for schema in PUBLIC_TOOL_SCHEMAS:
            with self.subTest(tool_name=schema["tool_name"]):
                validate_public_gateway_payload(schema)
                self.assertIn("result_type", schema)
                self.assertIn("status_values", schema)
        self.assertTrue(no_raw_path_output)
        self.assertTrue(no_raw_sql_output)
        self.assertTrue(no_worker_internal_output)
        self.assertTrue(safe_error_envelope)

    def test_safe_workflow_error_envelopes_cover_public_workflows_without_echoing_raw_input(
        self,
    ) -> None:
        for workflow in {
            "upload",
            "ingestion",
            "observation",
            "candidate_graph",
            "mail_evidence",
            "access",
            "wiki_projection",
        }:
            with self.subTest(workflow=workflow):
                envelope = safe_workflow_error_envelope(
                    workflow=workflow,
                    tool_name="/srv/formowl/private/raw.txt",
                    error_code="select * from private_table worker_scratch",
                )
                rendered = str(envelope).lower()
                self.assertEqual(envelope["status"], "error")
                self.assertEqual(envelope["data"]["workflow"], workflow)
                self.assertNotIn("/srv/formowl", rendered)
                self.assertNotIn("select *", rendered)
                self.assertNotIn("worker_scratch", rendered)

    def test_public_payload_validator_rejects_forbidden_public_values(self) -> None:
        for payload in [
            {"raw_path": "formowl should not expose this key"},
            {"answer": "/tmp/private/raw.txt"},
            {"answer": "select * from private_table"},
            {"worker_scratch": "worker internal"},
        ]:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractValidationError):
                    validate_public_gateway_payload(payload)


if __name__ == "__main__":
    unittest.main()
