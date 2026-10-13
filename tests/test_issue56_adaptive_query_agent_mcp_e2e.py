from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import _paths  # noqa: F401
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

import formowl_gateway.runtime as runtime_module
import formowl_mail.hybrid as hybrid_module
from formowl_auth import FileAuditLogStore
from formowl_contract import Observation, PermissionScope, sha256_json
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_gateway.remote import build_remote_tool_descriptors
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import SemanticMcpGateway, validate_public_gateway_payload
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail import build_mail_upload_session_handler
from formowl_mail import semantic_plan
from formowl_mail.query import (
    _REVISION_SOURCE_QUERY_TIME_BUDGET_MS,
    _REVISION_SOURCE_REQUEST_TIME_BUDGET_MS,
    _source_mail_observation_match,
    MailMessageOccurrenceLineage,
    RevisionOwnedMailSourceScan,
    build_revision_owned_mail_evidence_query_handler,
)
from formowl_retrieval.gateway import SOURCE_EVIDENCE_TIME_BUDGET_MS
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
from test_issue56_semantic_execution_e2e import _contract_only_runtime
import test_issue56_supplemental_attachment_table_loader_e2e as supplemental_fixture
from test_issue56_supplemental_attachment_table_loader_e2e import (
    _ALTERNATE_HEADER,
    _ALTERNATE_VALUE,
    _HEADER,
    _IDENTIFIER,
    _PERMISSION_SCOPE,
    _SPARSE_IDENTIFIER,
    _VALUE,
    _oauth_context,
    _write_supplemental_partition,
)
import test_issue56_sealed_source_loader_e2e as sealed_fixture


class Issue56AdaptiveQueryAgentMcpE2ETests(unittest.IsolatedAsyncioTestCase):
    def test_source_mail_match_without_required_terms_uses_lexical_overlap(self) -> None:
        permission_scope = PermissionScope.project("project_formowl")
        observation = Observation(
            observation_id="observation_overlap_match",
            extractor_run_id="extractor_overlap_match",
            observation_type="email_body_segment",
            modality="mail",
            location={
                "archive_id": "archive_overlap_match",
                "mailbox_id": "mailbox_overlap_match",
                "message_occurrence_id": "message_overlap_match",
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-10-07T00:00:00+00:00",
            asset_id="asset_overlap_match",
            text="交期更新內容",
            payload={"subject": "交期更新"},
        )
        tokenizer = SimpleNamespace(
            analyze=lambda value: SimpleNamespace(
                tokens=frozenset({"交期"} if "交期" in value else set()),
                protected_identifiers=(),
            )
        )
        self.assertEqual(
            _source_mail_observation_match(
                observation,
                query_terms={"嘉值", "交期", "調閱", "出來"},
                required_terms=None,
                protected_query_tokens=set(),
                tokenizer_profile=tokenizer,
            ),
            ("交期",),
        )

    def test_source_mail_match_with_required_terms_remains_conjunctive(self) -> None:
        permission_scope = PermissionScope.project("project_formowl")
        observation = Observation(
            observation_id="observation_conjunctive_match",
            extractor_run_id="extractor_conjunctive_match",
            observation_type="email_body_segment",
            modality="mail",
            location={
                "archive_id": "archive_conjunctive_match",
                "mailbox_id": "mailbox_conjunctive_match",
                "message_occurrence_id": "message_conjunctive_match",
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-10-07T00:00:00+00:00",
            asset_id="asset_conjunctive_match",
            text="交期更新內容",
            payload={"subject": "交期更新"},
        )
        tokenizer = SimpleNamespace(
            analyze=lambda value: SimpleNamespace(
                tokens=frozenset({"交期"} if "交期" in value else set()),
                protected_identifiers=(),
            )
        )
        self.assertIsNone(
            _source_mail_observation_match(
                observation,
                query_terms={"嘉值", "交期"},
                required_terms=("嘉值", "交期"),
                protected_query_tokens=set(),
                tokenizer_profile=tokenizer,
            )
        )

    def test_remote_descriptor_exposes_server_bound_request_contract(self) -> None:
        descriptor = next(
            tool
            for tool in build_remote_tool_descriptors(
                required_scope="formowl.use",
                enabled_tool_names={
                    "whoami",
                    "query_effective_graph_view",
                },
            )
            if tool.name == "query_effective_graph_view"
        )
        request_contract = descriptor.inputSchema["properties"]["request_contract"]
        self.assertEqual(
            request_contract["properties"]["query_class"]["enum"],
            [
                "evidence_lookup",
                "relation_reasoning",
                "exact_set_or_inventory",
                "global_summarization",
            ],
        )
        source_items = request_contract["properties"]["source_family_scope"]["items"]
        self.assertNotIn("enum", source_items)
        self.assertEqual(source_items["pattern"], r"^[a-z][a-z0-9_]{0,63}$")

    def test_revision_owned_source_fallback_budget_boundary(self) -> None:
        permission_scope = PermissionScope.project("project_formowl")
        authorized_source = semantic_plan.validated_authorized_semantic_source(
            source_kind=semantic_plan.AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id="workspace_formowl",
            source_scope_ids=("project_formowl",),
            authorized_permission_scopes=(permission_scope,),
        )
        observation = Observation(
            observation_id="observation_mail_budget_boundary",
            extractor_run_id="extractor_mail_budget_boundary",
            observation_type="email_body_segment",
            modality="mail",
            location={
                "archive_id": "archive_budget_boundary",
                "mailbox_id": "mailbox_budget_boundary",
                "message_occurrence_id": "message_occurrence_budget_boundary",
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id="asset_mail_budget_boundary",
            text="劉一帆 project update",
            payload={
                "message_fingerprint": "sha256:" + ("1" * 64),
                "subject": "劉一帆 project update",
            },
        )
        observation_hash = sha256_json(observation.to_dict())
        selector = "mailimport:" + ("2" * 64)
        lineage = MailMessageOccurrenceLineage(
            source_observation_id=observation.observation_id,
            message_occurrence_id="message_occurrence_budget_boundary",
        )
        source_records = Mock()
        source_records.authorized_mail_import_session_ids = (selector,)
        source_records.observation_for_hash.side_effect = (
            lambda value: observation if value == observation_hash else None
        )
        source_records.observation_hash.side_effect = (
            lambda value: observation_hash
            if value == observation.observation_id
            else None
        )
        source_records.lineage.return_value = lineage
        source_records.mail_import_session_id_for_observation.return_value = selector
        session = SimpleNamespace(
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            authorized_source=authorized_source,
            source_session_binding_fingerprint="sha256:" + ("3" * 64),
            query=Mock(),
        )
        handler = build_revision_owned_mail_evidence_query_handler(
            session=session,
            effective_graph_view=SimpleNamespace(),
            source_records=source_records,
            safe_binding={
                "extraction_coverage": {
                    "source_completeness_certified": False,
                },
            },
        )
        request = {
            "query_text": "劉一帆",
            "requester_user_id": "user_yifan",
            "workspace_id": "workspace_formowl",
            "session_id": "revision-session",
            "mail_import_session_id": selector,
        }

        clock = [0.0]

        def slow_graph_query(**kwargs):
            self.assertEqual(
                kwargs["limits"].max_time_budget_ms,
                _REVISION_SOURCE_QUERY_TIME_BUDGET_MS,
            )
            clock[0] = (
                _REVISION_SOURCE_QUERY_TIME_BUDGET_MS + 100
            ) / 1000
            self.assertGreater(
                clock[0],
                _REVISION_SOURCE_QUERY_TIME_BUDGET_MS / 1000,
            )
            self.assertLess(
                clock[0],
                _REVISION_SOURCE_REQUEST_TIME_BUDGET_MS / 1000,
            )
            return SimpleNamespace(
                status="incomplete",
                warnings=("semantic_query_time_budget_exhausted",),
                answer_citation_hashes=(),
                scores=(),
            )

        def fallback_scan(**kwargs):
            self.assertGreater(kwargs["deadline_monotonic"], clock[0])
            self.assertAlmostEqual(
                kwargs["deadline_monotonic"] - clock[0],
                SOURCE_EVIDENCE_TIME_BUDGET_MS / 1000,
            )
            self.assertTrue(kwargs["observation_callback"](observation, selector))
            return RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=1,
                complete=False,
                stop_reason="deadline",
            )

        session.query.side_effect = slow_graph_query
        source_records.scan_authorized_mail_observations = Mock(
            side_effect=fallback_scan
        )
        with (
            patch(
                "formowl_retrieval.gateway.time.monotonic",
                side_effect=lambda: clock[0],
            ),
            patch(
                "formowl_mail.query._source_mail_observation_match",
                return_value={"劉一帆"},
            ),
        ):
            fallback_result = handler(request)

        self.assertEqual(fallback_result["status"], "ok")
        self.assertTrue(fallback_result["citations"])
        self.assertIn(
            "semantic_query_time_budget_exhausted",
            fallback_result["warnings"],
        )
        self.assertIn(
            "mail_evidence_source_fallback_used",
            fallback_result["warnings"],
        )
        self.assertIn(
            "mail_evidence_source_fallback_incomplete",
            fallback_result["warnings"],
        )
        source_records.scan_authorized_mail_observations.assert_called_once()

        for semantic_status in ("permission_denied", "error", "replan_required"):
            with self.subTest(semantic_status=semantic_status):
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status=semantic_status,
                    warnings=(f"semantic_{semantic_status}",),
                    answer_citation_hashes=(),
                    scores=(),
                )
                scan = Mock()
                source_records.scan_authorized_mail_observations = scan

                result = handler(request)

                self.assertEqual(result["citations"], [])
                self.assertNotIn(
                    "mail_evidence_source_fallback_used",
                    result["warnings"],
                )
                scan.assert_not_called()

        session.query.return_value = SimpleNamespace(
            status="not_found",
            warnings=("semantic_no_hit",),
            answer_citation_hashes=(),
            scores=(),
        )
        incomplete_scan = Mock(
            return_value=RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=1,
                complete=False,
                stop_reason="deadline",
            )
        )
        source_records.scan_authorized_mail_observations = incomplete_scan
        incomplete_result = handler(request)

        self.assertEqual(incomplete_result["status"], "pending_review")
        self.assertEqual(incomplete_result["citations"], [])
        self.assertNotEqual(incomplete_result["status"], "not_found")
        self.assertIn(
            "mail_evidence_source_fallback_incomplete",
            incomplete_result["warnings"],
        )
        incomplete_scan.assert_called_once()

    async def test_external_agent_replans_from_capabilities_over_normal_mcp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            collision_field = "PART"
            context_field = "PartNumber"
            requested_fields = (
                (_HEADER, _VALUE),
                (_ALTERNATE_HEADER, _ALTERNATE_VALUE),
            )
            projection_value_collision = _HEADER
            with (
                patch.object(
                    sealed_fixture,
                    "WORKSPACE_PERMISSION_SCOPE",
                    _PERMISSION_SCOPE,
                ),
                patch.object(
                    supplemental_fixture,
                    "_BLANK_HEADER",
                    collision_field,
                ),
                patch.object(
                    supplemental_fixture,
                    "_BLANK_IDENTIFIER",
                    projection_value_collision,
                ),
            ):
                package = _prepare_package(root / "sealed")
                supplemental_path, parent_path = _write_supplemental_partition(
                    root,
                    package,
                )
            # A separately sealed table export need not reuse base mail IDs.
            supplemental = json.loads(supplemental_path.read_text())
            supplemental_occurrence_id = "message_supplemental_partition_only"
            self.assertNotIn(
                supplemental_occurrence_id,
                {
                    occurrence["message_occurrence_id"]
                    for occurrence in package.fixture.bundle_artifact["bundle"][
                        "message_occurrences"
                    ]
                },
            )
            for observation in supplemental["observations"]:
                if observation["observation_type"] == "email_attachment_occurrence":
                    observation["location"]["message_occurrence_id"] = (
                        supplemental_occurrence_id
                    )
                    observation["payload"]["message_occurrence_id"] = (
                        supplemental_occurrence_id
                    )
                else:
                    observation["payload"]["lineage"]["message_occurrence_id"] = (
                        supplemental_occurrence_id
                    )
            supplemental_path.write_text(json.dumps(supplemental))
            environment = _loader_environment(package)
            environment.update(
                {
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_PATH": str(
                        supplemental_path
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_SHA256": (
                        _sha256_path(supplemental_path)
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_PATH": str(
                        parent_path
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_SHA256": (
                        _sha256_path(parent_path)
                    ),
                }
            )
            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(
                    hybrid_module,
                    "_load_pinned_issue56_runtime_components",
                    return_value=_contract_only_runtime(),
                ),
            ):
                retrieval_handler = (
                    gateway_loader.build_issue56_production_semantic_retrieval_handler()
                )
            self.assertEqual(
                set(retrieval_handler.authorized_capability_summary["source_families"]),
                {"mail", "attachment_table"},
            )
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            config = ConnectedRuntimeConfig.from_env_and_secrets(
                _write_runtime_environment(runtime_root)
            )
            semantic_gateway = SemanticMcpGateway(
                upload_session_handler=build_mail_upload_session_handler(
                    upload_session_store=UploadSessionStore(config.data_dir),
                    audit_store=FileAuditLogStore(config.data_dir),
                    expires_at_provider=lambda: "2030-01-01T00:00:00+00:00",
                ),
                retrieval_handler=retrieval_handler,
            )
            with patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=_FakeRepository(),
            ):
                runtime = await ConnectedRuntime.compose(
                    config,
                    semantic_gateway=semantic_gateway,
                    http_client=_FakeHttpClient(),
                )
            runtime.preflight = AsyncMock(return_value={"status": "ready"})
            principal, actor = _oauth_context(config)
            try:
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
                    TestClient(
                        runtime.application.app,
                        raise_server_exceptions=False,
                    ) as client,
                ):
                    request_count = 0

                    def post_query(
                        query_text,
                        *,
                        table_query=None,
                        request_contract=None,
                    ):
                        nonlocal request_count
                        request_count += 1
                        arguments = {"query_text": query_text}
                        if table_query is not None:
                            arguments["table_query"] = table_query
                        if request_contract is not None:
                            arguments["request_contract"] = request_contract
                        return client.post(
                            "/mcp",
                            headers={
                                "Authorization": "Bearer synthetic.token",
                                "Accept": "application/json, text/event-stream",
                                "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                            },
                            json={
                                "jsonrpc": "2.0",
                                "id": sha256_json(query_text),
                                "method": "tools/call",
                                "params": {
                                    "name": "query_effective_graph_view",
                                    "arguments": arguments,
                                },
                            },
                        )

                    collision_query = (
                        f"有{projection_value_collision}的{collision_field}呢？"
                    )
                    rejected_collision_response = post_query(collision_query)
                    self.assertEqual(rejected_collision_response.status_code, 200)
                    rejected_collision_result = (
                        rejected_collision_response.json()["result"]
                    )
                    self.assertFalse(
                        rejected_collision_result["isError"],
                        rejected_collision_result,
                    )
                    rejected_collision_data = rejected_collision_result[
                        "structuredContent"
                    ]["data"]
                    self.assertEqual(rejected_collision_data["status"], "ok")
                    self.assertTrue(rejected_collision_data["citations"])
                    self.assertNotIn("exact_inventory", rejected_collision_data)
                    self.assertEqual(
                        rejected_collision_data["query_agent"]["subqueries"][0][
                            "validation_status"
                        ],
                        "validated_existing_scope_schema_permission",
                    )

                    structured_collision_response = post_query(
                        collision_query,
                        table_query={
                            "filters": [
                                {
                                    "field": context_field,
                                    "value": projection_value_collision,
                                }
                            ],
                            "projection_fields": [collision_field],
                        },
                        request_contract={
                            "original_query_hash": sha256_json(collision_query),
                            "query_class": "evidence_lookup",
                            "source_family_scope": [
                                "mail",
                                "attachment_table",
                            ],
                            "requested_fields": [collision_field],
                            "maximum_claim_strength": "cited_evidence",
                        },
                    )
                    self.assertEqual(structured_collision_response.status_code, 200)
                    structured_collision_result = (
                        structured_collision_response.json()["result"]
                    )
                    self.assertFalse(
                        structured_collision_result["isError"],
                        structured_collision_result,
                    )
                    structured_collision_data = structured_collision_result[
                        "structuredContent"
                    ]["data"]
                    validate_public_gateway_payload(structured_collision_data)
                    structured_inventory = structured_collision_data[
                        "exact_inventory"
                    ]
                    self.assertEqual(
                        structured_inventory["coverage_status"],
                        "complete",
                    )
                    self.assertEqual(
                        structured_inventory["plan"]["claim_strength"],
                        "cited_evidence",
                    )
                    self.assertEqual(structured_inventory["returned_count"], 1)
                    self.assertEqual(
                        [
                            (value["field"], value["value"])
                            for value in structured_inventory["items"][0][
                                "structured_values"
                            ]
                        ],
                        [(collision_field, "")],
                    )
                    self.assertTrue(structured_collision_data["citations"])
                    self.assertEqual(
                        structured_collision_data["query_agent"][
                            "request_contract"
                        ]["query_class"],
                        "evidence_lookup",
                    )

                    mail_query = "CASE-0001 的 Synthetic evidence"
                    mail_response = post_query(
                        mail_query,
                        request_contract={
                            "original_query_hash": sha256_json(mail_query),
                            "query_class": "evidence_lookup",
                            "source_family_scope": ["mail"],
                            "requested_fields": [],
                            "maximum_claim_strength": "cited_evidence",
                        },
                    )
                    self.assertEqual(mail_response.status_code, 200)
                    mail_result = mail_response.json()["result"]
                    self.assertFalse(mail_result["isError"], mail_result)
                    mail_data = mail_result["structuredContent"]["data"]
                    self.assertTrue(mail_data["citations"])
                    self.assertNotIn("exact_inventory", mail_data)
                    self.assertEqual(
                        mail_data["query_agent"]["subqueries"][0][
                            "validation_status"
                        ],
                        "validated_existing_scope_schema_permission",
                    )

                    mail_observations = {
                        sha256_json(row): row
                        for row in package.fixture.snapshot["parsed_mail_observations"]
                    }
                    for query, expected_fields in (
                        (
                            "list all fixture@example.invalid messages",
                            {"subject", "sender", "sent_at"},
                        ),
                        ("list all CASE-0001 messages", {"body_excerpt"}),
                    ):
                        response = post_query(
                            query,
                            request_contract={
                                "original_query_hash": sha256_json(query),
                                "query_class": "exact_set_or_inventory",
                                "source_family_scope": ["mail"],
                                "requested_fields": [],
                                "maximum_claim_strength": "complete_authorized_scope",
                            },
                        )
                        self.assertEqual(response.status_code, 200)
                        result = response.json()["result"]
                        self.assertFalse(result["isError"], result)
                        projected = result["structuredContent"]["data"]
                        validate_public_gateway_payload(projected)
                        inventory = projected["exact_inventory"]
                        self.assertGreater(inventory["returned_count"], 0)
                        if expected_fields == {"body_excerpt"}:
                            self.assertEqual(inventory["coverage_status"], "incomplete")
                            self.assertGreater(inventory["unresolved_count"], 0)
                        for item in inventory["items"]:
                            self.assertEqual(item["structure_status"], "source_provided")
                            self.assertEqual(
                                {value["field"] for value in item["structured_values"]},
                                expected_fields,
                            )
                            occurrence_ids = set()
                            for value in item["structured_values"]:
                                source = mail_observations[value["citation_hash"]]
                                occurrence_ids.add(
                                    source["location"]["message_occurrence_id"]
                                )
                                expected = (
                                    source["text"]
                                    if value["field"] == "body_excerpt"
                                    else source["payload"][value["field"]]
                                )
                                self.assertEqual(value["value"], expected[:400])
                                self.assertIn(
                                    {
                                        "citation_hash": value["citation_hash"],
                                        "occurrence_lineage_fingerprint": value[
                                            "occurrence_lineage_fingerprint"
                                        ],
                                    },
                                    item["governed_references"],
                                )
                            self.assertEqual(len(occurrence_ids), 1)
                        self.assertNotIn(str(root), str(projected))
                        self.assertNotIn("object_uri", str(projected))
                        self.assertNotIn("tenant_id", str(projected))

                    rejected_field_response = post_query(
                        "generic structured source lookup",
                        table_query={
                            "filters": [
                                {
                                    "field": "UnknownSourceField",
                                    "value": projection_value_collision,
                                }
                            ],
                            "projection_fields": [collision_field],
                        },
                    )
                    self.assertEqual(rejected_field_response.status_code, 200)
                    rejected_field_data = rejected_field_response.json()["result"][
                        "structuredContent"
                    ]["data"]
                    self.assertEqual(rejected_field_data["citations"], [])
                    self.assertEqual(
                        rejected_field_data["query_agent"]["external_replan"][
                            "rejection_reason_codes"
                        ],
                        ["filter_field_not_authorized"],
                    )

                    rejected_value_response = post_query(
                        "generic structured source lookup",
                        table_query={
                            "filters": [
                                {
                                    "field": context_field,
                                    "value": "SYN-NOT-PRESENT-907",
                                }
                            ],
                            "projection_fields": [collision_field],
                        },
                    )
                    self.assertEqual(rejected_value_response.status_code, 200)
                    rejected_value_data = rejected_value_response.json()["result"][
                        "structuredContent"
                    ]["data"]
                    self.assertEqual(rejected_value_data["citations"], [])
                    self.assertEqual(
                        rejected_value_data["query_agent"]["external_replan"][
                            "rejection_reason_codes"
                        ],
                        ["filter_value_not_found_in_authorized_field"],
                    )

                    zero_response = post_query(
                        f"有{_IDENTIFIER} {_SPARSE_IDENTIFIER}的"
                        f"{collision_field}呢？"
                    )
                    self.assertEqual(zero_response.status_code, 200)
                    zero_result = zero_response.json()["result"]
                    self.assertFalse(zero_result["isError"], zero_result)
                    zero_data = zero_result["structuredContent"]["data"]
                    zero_agent = zero_data["query_agent"]
                    self.assertEqual(zero_agent["status"], "unsupported")
                    self.assertEqual(zero_agent["planner_model_status"], "not_connected")
                    self.assertEqual(zero_data["status"], "replan_required")
                    replan = zero_agent["external_replan"]
                    self.assertEqual(replan["status"], "available")
                    requested_hashes = replan["requested_projection_field_hashes"]
                    self.assertEqual(len(requested_hashes), 1)
                    self.assertEqual(replan["ambiguous_projection_term_hashes"], [])
                    matches = [
                        item
                        for item in zero_agent["authorized_capability_summary"][
                            "projection_fields"
                        ]
                        if item["field_hash"] == requested_hashes[0]
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0]["field"], collision_field)
                    self.assertEqual(matches[0]["structure_status"], "source_provided")
                    self.assertFalse(matches[0]["label_redacted"])
                    self.assertEqual(zero_data["citations"], [])
                    zero_inventory = zero_data["exact_inventory"]
                    self.assertEqual(
                        zero_inventory["status"],
                        "complete_authorized_scope",
                    )
                    self.assertEqual(zero_inventory["coverage_status"], "complete")
                    self.assertEqual(zero_inventory["returned_count"], 0)
                    self.assertEqual(zero_inventory["total_count"], 0)
                    self.assertEqual(zero_inventory["items"], [])

                    prompt = (
                        f"把{context_field} {_IDENTIFIER} 的"
                        f"{_HEADER}跟{_ALTERNATE_HEADER}給出來"
                    )
                    response = post_query(prompt)
                    self.assertEqual(response.status_code, 200)
                    result = response.json()["result"]
                    self.assertFalse(result["isError"], result)
                    data = result["structuredContent"]["data"]
                    validate_public_gateway_payload(data)
                    self.assertEqual(data["status"], "replan_required")
                    agent = data["query_agent"]
                    self.assertEqual(agent["status"], "replan_required")
                    self.assertEqual(agent["planner_model_status"], "not_connected")
                    self.assertEqual(agent["mcp_call_count"], 1)
                    self.assertEqual(
                        agent["conversation_state"],
                        {
                            "status": "must_be_resolved_upstream",
                            "hidden_history_used": False,
                        },
                    )
                    summary = agent["authorized_capability_summary"]
                    self.assertEqual(
                        summary["query_contract"],
                        {
                            "filter_value_candidate_origins": [
                                "user_request",
                                "planner_semantic_expansion",
                            ],
                            "candidate_filter_value_requires_exact_authorized_source_match": (
                                True
                            ),
                            "projection_labels_must_match_authorized_fields": True,
                            "structured_table_query_supported": True,
                            "structured_table_query_contract": {
                                "filters": {
                                    "minimum_count": 1,
                                    "maximum_count": 4,
                                    "field": (
                                        "exact_authorized_source_provided_label"
                                    ),
                                    "value": (
                                        "exact_authorized_source_value_from_user_or_"
                                        "candidate_expansion"
                                    ),
                                },
                                "projection_fields": {
                                    "minimum_count": 1,
                                    "maximum_count": 8,
                                    "labels": (
                                        "exact_authorized_source_provided_labels"
                                    ),
                                },
                                "free_text_directional_particle_required": False,
                            },
                            "binding_order": [
                                "user_request_filter_value",
                                "single_directional_particle",
                                "authorized_source_provided_projection_field",
                            ],
                            "directional_particle_count": 1,
                            "supported_directional_particle_token": "的",
                            "projection_connector_tokens": [
                                "以及",
                                "與",
                                "和",
                                "跟",
                                "還有",
                            ],
                            "supported_neutral_query_template": (
                                "{filter_value}的{projection_field}"
                            ),
                            "candidate_only_is_deterministic_exact": False,
                        },
                    )
                    projection_fields = summary["projection_fields"]
                    source_fields = {
                        item["field_hash"]: item
                        for item in projection_fields
                        if item["structure_status"] == "source_provided"
                    }
                    requested_hashes = agent["external_replan"][
                        "requested_projection_field_hashes"
                    ]
                    self.assertEqual(
                        agent["external_replan"]["ambiguous_projection_term_hashes"],
                        [],
                    )
                    selected = [source_fields[field_hash] for field_hash in requested_hashes]
                    self.assertEqual(
                        [item["field"] for item in selected],
                        [field for field, _value in requested_fields],
                    )
                    self.assertTrue(
                        {collision_field, context_field}
                        <= {item["field"] for item in source_fields.values()}
                    )
                    self.assertTrue(
                        {collision_field, context_field}.isdisjoint(
                            item["field"] for item in selected
                        )
                    )
                    self.assertFalse(
                        any(
                            key in item
                            for item in projection_fields
                            for key in ("value", "text", "snippet")
                        )
                    )
                    summary_text = str(summary)
                    self.assertNotIn(_VALUE, summary_text)
                    self.assertNotIn(_ALTERNATE_VALUE, summary_text)

                    for (header, expected_value), selected_item in zip(
                        requested_fields, selected, strict=True
                    ):
                        self.assertEqual(selected_item["field"], header)
                        follow_up = f"有{_IDENTIFIER}的{header}呢？"
                        follow_up_response = post_query(follow_up)
                        self.assertEqual(follow_up_response.status_code, 200)
                        follow_up_result = follow_up_response.json()["result"]
                        self.assertFalse(
                            follow_up_result["isError"],
                            follow_up_result,
                        )
                        follow_up_data = follow_up_result["structuredContent"]["data"]
                        validate_public_gateway_payload(follow_up_data)
                        inventory = follow_up_data["exact_inventory"]
                        self.assertEqual(
                            inventory["status"],
                            "incomplete",
                        )
                        self.assertEqual(inventory["coverage_status"], "incomplete")
                        self.assertEqual(inventory["returned_count"], 1)
                        self.assertEqual(inventory["unsupported_count"], 0)
                        self.assertEqual(
                            inventory["candidate_only_occurrence_count"],
                            0,
                        )
                        item = inventory["items"][0]
                        self.assertEqual(item["structure_status"], "source_provided")
                        self.assertEqual(
                            [
                                (value["field"], value["value"])
                                for value in item["structured_values"]
                            ],
                            [(header, expected_value)],
                        )
                        self.assertTrue(follow_up_data["citations"])
                        self.assertEqual(follow_up_data["status"], "replan_required")
                        follow_up_agent = follow_up_data["query_agent"]
                        self.assertEqual(follow_up_agent["status"], "replan_required")
                        self.assertEqual(follow_up_agent["mcp_call_count"], 1)
                        self.assertEqual(
                            follow_up_agent["executed_subquery_count"],
                            1,
                        )
                        self.assertEqual(
                            follow_up_agent["planner_model_status"],
                            "not_connected",
                        )
                        context = follow_up_agent["context_bundle"]
                        self.assertTrue(context["citation_hashes"])
                        self.assertTrue(context["lineage_fingerprints"])
                        snippets = [
                            evidence["snippet"]
                            for successful in context["successful_subqueries"]
                            for evidence in successful["evidence"]
                        ]
                        self.assertTrue(
                            any(expected_value in snippet for snippet in snippets)
                        )
                        rendered = str((data, follow_up_data))
                        self.assertNotIn(str(root), rendered)
                        self.assertNotIn("object_uri", rendered)
                        self.assertNotIn("tenant_id", rendered)

                    combined_response = post_query(
                        f"{_IDENTIFIER}的{_HEADER}跟{_ALTERNATE_HEADER}"
                    )
                    self.assertEqual(combined_response.status_code, 200)
                    combined_result = combined_response.json()["result"]
                    self.assertFalse(combined_result["isError"], combined_result)
                    combined_data = combined_result["structuredContent"]["data"]
                    validate_public_gateway_payload(combined_data)
                    combined_inventory = combined_data["exact_inventory"]
                    self.assertEqual(combined_inventory["status"], "incomplete")
                    self.assertEqual(
                        combined_inventory["coverage_status"],
                        "incomplete",
                    )
                    self.assertEqual(combined_inventory["returned_count"], 2)
                    self.assertEqual(
                        {
                            (value["field"], value["value"])
                            for item in combined_inventory["items"]
                            for value in item["structured_values"]
                        },
                        set(requested_fields),
                    )
                    self.assertTrue(combined_data["citations"])
                    self.assertEqual(request_count, 10 + len(requested_fields))
            finally:
                await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
