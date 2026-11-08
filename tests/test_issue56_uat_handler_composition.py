from __future__ import annotations

import json
import hashlib
import copy
import shutil
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
import unicodedata
from unittest.mock import AsyncMock, Mock, call, patch

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient
from formowl_contract import (
    ContractValidationError,
    Observation,
    PermissionScope,
    SourceRef,
    sha256_json,
    stable_resource_contract_id,
    to_plain,
)
import formowl_gateway.runtime as runtime_module
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors.text import PlainTextObservationExtractor
from formowl_ingestion.extractors.mail import FixtureMailArchiveExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
    UploadSessionStore,
)
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_gateway.issue56_uat_runtime import (
    _mcp_query_request,
    _query_agent_runtime_context,
    _run_gpt_query_agent,
    create_issue56_temporary_lan_query_service,
)
from formowl_gateway.jsonrpc import SemanticMcpJsonRpcGateway
from formowl_gateway.remote import _successful_tool_result
from formowl_gateway.semantic import SemanticMcpGateway, validate_public_gateway_payload
from formowl_gateway.protocol import McpSession
from formowl_gateway.remote import build_remote_tool_descriptors
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_mail import build_mail_upload_session_handler
from formowl_mail import hybrid, human_uat_orchestrator, semantic_plan
from formowl_mail.query import (
    _REVISION_SOURCE_FALLBACK_OBSERVATION_LIMIT,
    _REVISION_SOURCE_FALLBACK_TIME_BUDGET_MS,
    _REVISION_SOURCE_QUERY_TIME_BUDGET_MS,
    _REVISION_SOURCE_REQUEST_TIME_BUDGET_MS,
    MailMessageOccurrenceLineage,
    TextDocumentOccurrenceLineage,
    REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES,
    RevisionOwnedMailSourceScan,
    build_authorized_observation_snippet_index,
    build_revision_owned_mail_evidence_query_handler,
    source_occurrence_lineage_from_observation,
)
from formowl_mail import issue56_sealed_source
from formowl_mail.issue56_sealed_source import (
    IngestionRevisionSourceRecords,
    build_issue56_ingestion_revision,
)
from formowl_mail.import_workflow import open_completed_ingestion_job_reader
from formowl_retrieval.gateway import (
    source_evidence_double_check,
    source_evidence_deadline_scope,
    source_evidence_query_terms_scope,
)
from test_issue56_semantic_execution_e2e import _contract_only_runtime
from test_connected_runtime import _FakeHttpClient, _FakeRepository, _write_runtime_environment
from test_issue56_supplemental_attachment_table_loader_e2e import _oauth_context
from test_mail_evidence_mcp_gateway import _mail_bundle
from test_issue56_codex_provider_bridge import _binding_attempt
from test_mail_human_uat_http import _RunningSurface


class Issue56UatHandlerCompositionTests(unittest.IsolatedAsyncioTestCase):
    def test_graph_source_recovery_requires_an_uncited_validated_lookup_miss(self) -> None:
        result = SimpleNamespace(
            query_class="evidence_lookup",
            status="pending_review",
            answer_citation_hashes=(),
            exact_result=None,
            query_hash="sha256:" + ("2" * 64),
            plan_fingerprint="sha256:" + ("3" * 64),
            result_fingerprint="sha256:" + ("1" * 64),
        )
        arguments = {"query_text": "bounded evidence"}
        request_contract_summary = {
            "request_contract_fingerprint": "sha256:" + ("4" * 64),
        }
        payload = {
            "status": "pending_review",
            "stop_reason": "planner_stopped_partial",
            "subqueries": [{
                "validation_status": "validated_existing_scope_schema_permission",
                "status": "pending_review",
                "result_fingerprint": result.result_fingerprint,
            }],
        }
        self.assertTrue(
            loader._graph_source_recovery_is_eligible(
                arguments=arguments,
                request_query_class="evidence_lookup",
                result=result,
                request_contract_summary=request_contract_summary,
                query_agent_payload=payload,
                requested_fields=("subject",),
                supported_requested_fields=(),
            )
        )
        self.assertFalse(loader._graph_source_recovery_is_eligible(
            arguments=arguments,
            request_query_class="evidence_lookup",
            result=result,
            request_contract_summary=request_contract_summary,
            query_agent_payload=payload,
            requested_fields=(),
            supported_requested_fields=(),
        ))
        for status in ("unsupported", "permission_denied", "error", "replan_required"):
            with self.subTest(status=status):
                rejected_values = vars(result).copy()
                rejected_values["status"] = status
                rejected = SimpleNamespace(**rejected_values)
                self.assertFalse(
                    loader._graph_source_recovery_is_eligible(
                        arguments=arguments,
                        request_query_class="evidence_lookup",
                        result=rejected,
                        request_contract_summary=request_contract_summary,
                        query_agent_payload=payload,
                        requested_fields=("subject",),
                        supported_requested_fields=(),
                    )
                )
        self.assertFalse(
            loader._graph_source_recovery_is_eligible(
                arguments={**arguments, "exact_field": "subject"},
                request_query_class="evidence_lookup",
                result=result,
                request_contract_summary=request_contract_summary,
                query_agent_payload=payload,
                requested_fields=("subject",),
                supported_requested_fields=(),
            )
        )
        self.assertFalse(
            loader._graph_source_recovery_is_eligible(
                arguments=arguments,
                request_query_class="evidence_lookup",
                result=result,
                request_contract_summary=request_contract_summary,
                query_agent_payload={
                    **payload,
                    "stop_reason": "provider_error",
                },
                requested_fields=("subject",),
                supported_requested_fields=(),
            )
        )
        self.assertFalse(
            loader._graph_source_recovery_is_eligible(
                arguments=arguments,
                request_query_class="evidence_lookup",
                result=result,
                request_contract_summary=request_contract_summary,
                query_agent_payload={
                    **payload,
                    "subqueries": [{
                        **payload["subqueries"][0],
                        "status": "unsupported",
                    }],
                },
                requested_fields=("subject",),
                supported_requested_fields=(),
            )
        )
        omitted_fingerprint = {
            **payload,
            "subqueries": [{
                **{
                    key: value
                    for key, value in payload["subqueries"][0].items()
                    if key != "result_fingerprint"
                },
                "query_hash": result.query_hash,
                "plan_fingerprint": result.plan_fingerprint,
                "request_contract_fingerprint": (
                    request_contract_summary["request_contract_fingerprint"]
                ),
            }],
        }
        self.assertTrue(
            loader._graph_source_recovery_is_eligible(
                arguments=arguments,
                request_query_class="evidence_lookup",
                result=result,
                request_contract_summary=request_contract_summary,
                query_agent_payload=omitted_fingerprint,
                requested_fields=("subject",),
                supported_requested_fields=(),
            )
        )
        for key in ("query_hash", "plan_fingerprint", "request_contract_fingerprint"):
            with self.subTest(binding=key):
                tampered = {
                    **omitted_fingerprint,
                    "subqueries": [{
                        **omitted_fingerprint["subqueries"][0],
                        key: "sha256:" + ("9" * 64),
                    }],
                }
                self.assertFalse(
                    loader._graph_source_recovery_is_eligible(
                        arguments=arguments,
                        request_query_class="evidence_lookup",
                        result=result,
                        request_contract_summary=request_contract_summary,
                        query_agent_payload=tampered,
                        requested_fields=("subject",),
                        supported_requested_fields=(),
                    )
                )

    def test_loaded_sealed_source_reader_keeps_mail_selector_bound(self) -> None:
        _, session, records, selector, other_selector, _ = (
            self._revision_owned_mail_fixture()
        )
        loaded = SimpleNamespace(
            observations=(records.observation,),
            session=session,
            query_bundle=SimpleNamespace(
                mail_import_session=SimpleNamespace(
                    mail_import_session_id=selector,
                ),
            ),
        )
        source_records = loader._LoadedSealedSourceRecords(loaded)
        seen: list[tuple[Observation, str]] = []
        scan = source_records.scan_authorized_observations(
            source_family="mail",
            mail_import_session_id=selector,
            max_observations=1,
            observation_callback=lambda observation, scope: (
                seen.append((observation, scope)) or True
            ),
        )
        self.assertTrue(scan.complete)
        self.assertEqual(scan.scanned_observation_count, 1)
        self.assertEqual(seen, [(records.observation, selector)])
        with self.assertRaisesRegex(ContractValidationError, "mail scope"):
            source_records.scan_authorized_observations(
                source_family="mail",
                mail_import_session_id=other_selector,
                max_observations=1,
            )

    def test_graph_recovery_shares_budget_across_families_and_selectors_without_field_upgrade(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("graph-source-recovery")
        asset, documents, authority = _completed_registered_text_revision_fixture(
            root, owner_user_id=loader.APPROVER_ACTOR,
        )
        heading = next(item for item in documents if item.observation_type == "heading")
        _, _, records, first_selector, second_selector, _ = self._revision_owned_mail_fixture(
            source_text=(
                "Synthetic CASE-421 and CASE-422 approval background. "
                + "This paragraph records preliminary discussion only. " * 30
                + "The approval deadline: 2030-01-02."
            ),
            subject="Synthetic approval",
        )
        support = records.observation
        self.assertGreater(support.text.index("deadline:"), 400)
        decoy = replace(
            support, observation_id="observation_mail_decoy",
            text="Synthetic approval was discussed; no scheduling detail was recorded.",
        )
        calls = []
        wrong_selector = False

        class Sources:
            authorized_mail_import_session_ids = (first_selector, second_selector)

            def scan_authorized_observations(self, **kwargs):
                calls.append(kwargs)
                if kwargs["source_family"] == "document_text":
                    return RevisionOwnedMailSourceScan(
                        (), kwargs["max_observations"], False, "observation_limit",
                    )
                if kwargs["mail_import_session_id"] == first_selector:
                    return RevisionOwnedMailSourceScan(
                        (), kwargs["max_observations"], False, "observation_limit",
                    )
                selector = first_selector if wrong_selector else second_selector
                for observation in (decoy, support):
                    kwargs["observation_callback"](observation, selector)
                return RevisionOwnedMailSourceScan((), 2, True)

        runtime = _contract_only_runtime()
        seal = sha256_json({"asset_id": asset.asset_id, "job": authority.job_fingerprint})
        with (
            patch.object(issue56_sealed_source, "load_issue56_target_runtime_components",
                         return_value=runtime),
            patch.object(hybrid, "_load_pinned_issue56_runtime_components", return_value=runtime),
        ):
            revision = build_issue56_ingestion_revision(
                observations=(support, *documents), bundles=(),
                source_binding={
                    "source_authority_fingerprint": seal,
                    "extraction_coverage": {"source_completeness_certified": False},
                },
                requester_user_id=loader.APPROVER_ACTOR, workspace_id=loader.WORKSPACE_ID,
                source_authority_fingerprint=seal,
                retrieval_observation_ids=(heading.observation_id,),
            )
            revision = replace(revision, source_records=Sources(), job_authorities=(authority,))
            handler = loader.build_issue56_production_semantic_retrieval_handler(
                ingestion_revision=revision,
            )
        query = "synthetic approval deadline"
        arguments = {
            "query_text": query, "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID, "session_id": "graph-source-test",
            "required_terms": ["synthetic", "deadline"],
            "request_contract": {
                "original_query_hash": sha256_json(query), "query_class": "evidence_lookup",
                "source_family_scope": ["mail", "document_text"],
                "requested_fields": ["deadline"], "maximum_claim_strength": "cited_evidence",
            },
        }
        executed = []
        real_execute = loader.execute_bounded_adaptive_query

        def execute(**kwargs):
            value = real_execute(**kwargs)
            executed.append(value)
            return value

        with patch.object(loader, "execute_bounded_adaptive_query", side_effect=execute):
            payload = handler(arguments)
        self.assertEqual(
            [(call["source_family"], call["mail_import_session_id"]) for call in calls],
            [("document_text", None), ("mail", first_selector), ("mail", second_selector)],
        )
        self.assertEqual([call["max_observations"] for call in calls], [4096, 2048, 2048])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual([item["citation_hash"] for item in payload["evidence"]],
                         [sha256_json(support.to_dict())])
        self.assertEqual(
            payload["evidence"][0]["source_scope_fingerprint"], sha256_json(second_selector),
        )
        recovery = payload["query_agent"]["context_bundle"]["source_recovery"]
        self.assertFalse(recovery["scan"]["complete"])
        self.assertLessEqual(recovery["scan"]["scanned_observation_count"], 8192)
        presented = human_uat_orchestrator.compact_evidence_for_model(payload)
        self.assertIn("deadline: 2030-01-02", presented["evidence"][0]["snippet"])
        self.assertLessEqual(len(presented["evidence"][0]["snippet"]), 400)
        self.assertIn(presented["evidence"][0]["snippet"], support.text)
        self.assertEqual(presented["citations"], [sha256_json(support.to_dict())])
        self.assertEqual(
            presented["evidence"][0]["occurrence_lineage_fingerprint"],
            payload["evidence"][0]["occurrence_lineage_fingerprint"],
        )
        self.assertEqual(
            presented["query_agent"]["context_bundle"]["missing_field_hashes"],
            [sha256_json("deadline")],
        )
        result, successes, trace = executed[0]
        for failure in ("provider_error", "rejected_existing_validator"):
            failed_trace = {**trace, "stop_reason": "provider_error"}
            if failure == "rejected_existing_validator":
                failed_trace = {
                    **trace, "subqueries": [
                        {**step, "validation_status": failure} for step in trace["subqueries"]
                    ],
                }
            calls.clear()
            with patch.object(loader, "execute_bounded_adaptive_query",
                              return_value=(result, successes, failed_trace)):
                failed = handler(arguments)
            self.assertEqual(calls, [])
            self.assertEqual(failed["citations"], [])
        calls.clear()
        wrong_selector = True
        with patch.object(loader, "execute_bounded_adaptive_query",
                          return_value=(result, successes, trace)):
            with self.assertRaisesRegex(ContractValidationError, "mail source scope"):
                handler(arguments)
        calls.clear()
        with self.assertRaisesRegex(ContractValidationError, "actor binding"):
            handler({**arguments, "requester_user_id": "another_actor"})
        self.assertEqual(calls, [])

    def test_graph_source_recovery_replan_marker_requires_incomplete_projection_scan(
        self,
    ) -> None:
        """Loader emits one replan marker only for an incomplete empty scan."""
        root = _paths.fresh_test_dir("graph-source-replan-marker")
        asset, documents, authority = _completed_registered_text_revision_fixture(
            root, owner_user_id=loader.APPROVER_ACTOR,
        )
        heading = next(item for item in documents if item.observation_type == "heading")
        _, _, records, selector, _, _ = self._revision_owned_mail_fixture(
            source_text=(
                "Synthetic clienta review background. "
                "No甲社專案 result is asserted by this fixture."
            ),
            subject="Synthetic replan fixture",
        )
        support = records.observation
        runtime = _contract_only_runtime()
        seal = sha256_json({"asset_id": asset.asset_id, "job": authority.job_fingerprint})
        with (
            patch.object(issue56_sealed_source, "load_issue56_target_runtime_components",
                         return_value=runtime),
            patch.object(hybrid, "_load_pinned_issue56_runtime_components", return_value=runtime),
        ):
            revision = build_issue56_ingestion_revision(
                observations=(support, *documents), bundles=(),
                source_binding={
                    "source_authority_fingerprint": seal,
                    "extraction_coverage": {"source_completeness_certified": False},
                },
                requester_user_id=loader.APPROVER_ACTOR, workspace_id=loader.WORKSPACE_ID,
                source_authority_fingerprint=seal,
                retrieval_observation_ids=(heading.observation_id,),
            )

        query = "Find synthetic clienta status"
        request_contract = {
            "original_query_hash": sha256_json(query),
            "query_class": "evidence_lookup",
            "source_family_scope": ["mail"],
            "requested_fields": ["status"],
            "maximum_claim_strength": "cited_evidence",
        }
        arguments = {
            "query_text": query,
            "required_terms": ["clienta", "甲社專案"],
            "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID,
            "session_id": "graph-source-replan-marker",
            "request_contract": request_contract,
        }
        plan_fingerprint = sha256_json({"plan": "synthetic-replan"})

        class Sources:
            authorized_mail_import_session_ids = (selector,)

            def __init__(self, complete: bool) -> None:
                self.complete = complete

            def scan_authorized_observations(self, **kwargs):
                return RevisionOwnedMailSourceScan(
                    (),
                    kwargs["max_observations"] if self.complete else 0,
                    self.complete,
                    None if self.complete else "observation_limit",
                )

        def execute_result(*, complete: bool):
            result = SimpleNamespace(
                status="pending_review", query_class="evidence_lookup",
                claim_strength="cited_evidence", answer_citation_hashes=(),
                exact_result=None, query_hash=sha256_json(query),
                plan_fingerprint=plan_fingerprint,
                result_fingerprint=sha256_json({"result": complete}),
                index_fingerprint=None, materialized_candidate_count=0,
                graph_path_count=0, scores=(), graph_paths=(), warnings=(
                    "retrieval_projection_unavailable",
                ),
            )
            trace = {
                "status": "pending_review",
                "stop_reason": "retrieval_projection_unavailable",
                "original_query_hash": request_contract["original_query_hash"],
                "request_contract": {
                    "request_contract_fingerprint": sha256_json(request_contract),
                    "query_class": request_contract["query_class"],
                    "source_family_scope": request_contract["source_family_scope"],
                },
                "warnings": ["retrieval_projection_unavailable"],
                "subqueries": [{
                    "status": "pending_review",
                    "validation_status": "validated_existing_scope_schema_permission",
                    "query_hash": result.query_hash,
                    "plan_fingerprint": plan_fingerprint,
                    "request_contract_fingerprint": sha256_json(request_contract),
                }],
                "context_bundle": {
                    "citation_hashes": [], "lineage_fingerprints": [],
                    "missing_field_hashes": [sha256_json("status")],
                    "successful_subqueries": [],
                },
            }
            return result, (result,), trace

        for complete in (False, True):
            with self.subTest(scan_complete=complete):
                current = replace(
                    revision, source_records=Sources(complete),
                    job_authorities=(authority,),
                )
                handler = loader.build_issue56_production_semantic_retrieval_handler(
                    ingestion_revision=current,
                )
                with (
                    patch.object(
                        loader, "execute_bounded_adaptive_query",
                        return_value=execute_result(complete=complete),
                    ),
                    patch.object(
                        loader,
                        "render_governed_evidence_answer",
                        return_value=SimpleNamespace(
                            status="pending_review",
                            answer_text="",
                            answer_hash=sha256_json("synthetic-answer"),
                            citation_hashes=(),
                        ),
                    ),
                ):
                    payload = handler(arguments)
                recovery = payload["query_agent"]["context_bundle"]["source_recovery"]
                self.assertEqual(recovery["scan"]["complete"], complete)
                self.assertEqual(
                    recovery["replan_required"],
                    not complete,
                )
                if complete:
                    self.assertIsNone(recovery["replan_reason"])
                    self.assertEqual(recovery["joint_candidate_count_state"], "complete_zero")
                else:
                    self.assertEqual(
                        recovery["replan_reason"],
                        "projection_unavailable_scan_incomplete_no_evidence",
                    )
                    self.assertEqual(payload["status"], "replan_required")

    def test_source_start_recovery_replan_marker_uses_shared_summary(self) -> None:
        """Source-start misses expose the same guarded replan marker."""
        root = _paths.fresh_test_dir("source-start-replan-marker")
        asset, documents, authority = _completed_registered_text_revision_fixture(
            root, owner_user_id=loader.APPROVER_ACTOR,
        )
        heading = next(item for item in documents if item.observation_type == "heading")
        _, _, records, selector, _, _ = self._revision_owned_mail_fixture(
            source_text=(
                "Synthetic clienta review background. "
                "No甲社專案 result is asserted by this fixture."
            ),
            subject="Synthetic source-start replan fixture",
        )
        support = records.observation
        runtime = _contract_only_runtime()
        seal = sha256_json({"asset_id": asset.asset_id, "job": authority.job_fingerprint})
        with (
            patch.object(issue56_sealed_source, "load_issue56_target_runtime_components",
                         return_value=runtime),
            patch.object(hybrid, "_load_pinned_issue56_runtime_components", return_value=runtime),
        ):
            revision = build_issue56_ingestion_revision(
                observations=(support, *documents), bundles=(),
                source_binding={
                    "source_authority_fingerprint": seal,
                    "extraction_coverage": {"source_completeness_certified": False},
                },
                requester_user_id=loader.APPROVER_ACTOR, workspace_id=loader.WORKSPACE_ID,
                source_authority_fingerprint=seal,
                retrieval_observation_ids=(heading.observation_id,),
            )

        query = "Find clienta 甲社專案 latest status"
        request_contract = {
            "original_query_hash": "sha256:" + hashlib.sha256(query.encode()).hexdigest(),
            "query_class": "evidence_lookup",
            "source_family_scope": ["mail"],
            "requested_fields": ["status"],
            "maximum_claim_strength": "cited_evidence",
        }
        arguments = {
            "query_text": query,
            "required_terms": ["clienta", "甲社專案"],
            "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID,
            "session_id": "source-start-replan-marker",
            "request_contract": request_contract,
        }

        class Sources:
            authorized_mail_import_session_ids = (selector,)

        current = replace(
            revision,
            session=None,
            source_records=Sources(),
            authorized_source=revision.session.authorized_source,
            safe_binding={
                **dict(revision.safe_binding),
                "source_revision_sha256": "sha256:" + ("a" * 64),
                "snapshot_sha256": "sha256:" + ("b" * 64),
            },
            job_authorities=(authority,),
        )
        handler = loader.build_issue56_production_semantic_retrieval_handler(
            ingestion_revision=current,
        )
        scan = RevisionOwnedMailSourceScan((), 0, False, "indexed_token_scope")
        with patch.object(
            loader,
            "source_evidence_double_check",
            return_value=SimpleNamespace(
                evidence=(), warnings=("retrieval_projection_unavailable",),
                status=None, scan=scan,
            ),
        ):
            public_arguments = {
                key: value for key, value in arguments.items()
                if key not in {"requester_user_id", "workspace_id", "session_id"}
            }
            date_binding = issue56_sealed_source.bind_mail_date_priority(
                user_text=query,
                arguments=public_arguments,
                tool_name="query_effective_graph_view",
            )
            self.assertIsNotNone(date_binding)
            with issue56_sealed_source.mail_date_priority_scope(date_binding):
                payload = handler(arguments)

        recovery = payload["query_agent"]["context_bundle"]["source_recovery"]
        self.assertEqual(recovery["required_term_count"], 2)
        self.assertEqual(recovery["joint_candidate_count_state"], "unknown")
        self.assertEqual(recovery["scan"]["stop_reason"], "indexed_token_scope")
        self.assertTrue(recovery["replan_required"])
        self.assertEqual(
            recovery["replan_reason"],
            "projection_unavailable_scan_incomplete_no_evidence",
        )
        self.assertEqual(payload["status"], "replan_required")

    async def test_standalone_text_revision_recovers_via_connected_mcp_with_native_citation(
        self,
    ) -> None:
        await self._check_standalone_text_connected_recovery(initial_unrelated_citation=False)

    async def test_standalone_text_all_fields_missing_rechecks_with_unrelated_mcp_citation(
        self,
    ) -> None:
        await self._check_standalone_text_connected_recovery(initial_unrelated_citation=True)

    async def test_standalone_text_all_fields_missing_rechecks_with_ok_unrelated_mcp_citation(
        self,
    ) -> None:
        await self._check_standalone_text_connected_recovery(
            initial_unrelated_citation=True, initial_unrelated_status="ok",
        )

    async def _check_standalone_text_connected_recovery(
        self, *, initial_unrelated_citation: bool, initial_unrelated_status: str = "partial",
    ) -> None:
        temp_dir = _paths.fresh_test_dir("issue56-native-text-handler")
        asset, observations, job_authority = _completed_registered_text_revision_fixture(
            temp_dir,
            owner_user_id=loader.APPROVER_ACTOR,
        )
        paragraph = next(item for item in observations if item.observation_type == "paragraph")
        heading = next(item for item in observations if item.observation_type == "heading")
        source_references = [
            [0, item.observation_id, sha256_json(item.to_dict())]
            for item in observations
        ]
        source_authority_fingerprint = sha256_json(
            {
                "asset_id": asset.asset_id,
                "asset_content_hash": asset.content_hash,
                "completed_job_fingerprint": job_authority.job_fingerprint,
                "observation_hashes": sorted(sha256_json(item.to_dict()) for item in observations),
            }
        )
        runtime = _contract_only_runtime()
        with (
            patch.object(
                issue56_sealed_source,
                "load_issue56_target_runtime_components",
                return_value=runtime,
            ),
            patch.object(
                hybrid,
                "_load_pinned_issue56_runtime_components",
                return_value=runtime,
            ),
        ):
            revision = build_issue56_ingestion_revision(
                # The completed source contains the paragraph, but the
                # canary session/index admits only the heading.
                observations=(heading,),
                bundles=(),
                source_binding={
                    "source_authority_fingerprint": source_authority_fingerprint,
                    "registered_asset_revision_fingerprint": (source_authority_fingerprint),
                    "extraction_coverage": {
                        "source_completeness_certified": False,
                    },
                },
                requester_user_id=loader.APPROVER_ACTOR,
                workspace_id=loader.WORKSPACE_ID,
                source_authority_fingerprint=source_authority_fingerprint,
                retrieval_observation_ids=(heading.observation_id,),
            )
            source_records = IngestionRevisionSourceRecords(
                runtime_store=SimpleNamespace(
                    workspace_id=loader.WORKSPACE_ID,
                ),
                job_authorities=(job_authority,),
                requester_user_id=loader.APPROVER_ACTOR,
                workspace_id=loader.WORKSPACE_ID,
                observation_references=source_references,
            )
            self.assertIs(source_records.observation_references, source_references)
            revision = replace(
                revision,
                job_authorities=(job_authority,),
                source_records=source_records,
            )
            retrieval_handler, mail_handler = loader.build_issue56_production_semantic_handlers(
                ingestion_revision=revision,
                query_agent_planner=lambda original, steps, _profile, _limit: (
                    original if not steps else None
                ),
            )

        self.assertIsNone(mail_handler)
        runtime_root = temp_dir / "runtime"
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
            connected_runtime = await ConnectedRuntime.compose(
                config,
                semantic_gateway=semantic_gateway,
                http_client=_FakeHttpClient(),
            )
        connected_runtime.preflight = AsyncMock(return_value={"status": "ready"})
        principal, actor = _oauth_context(config)
        query_text = "written owner approval explanation"
        request_contract = {
            "original_query_hash": sha256_json(query_text),
            "query_class": "evidence_lookup",
            "source_family_scope": ["document_text"],
            "requested_fields": ["acceptance_condition"],
            "maximum_claim_strength": "cited_evidence",
        }
        # Exercise the real graph adapter and normal MCP composition with an
        # initial, authorized but field-unrelated heading citation. Citation
        # count must not suppress the all-requested-fields-missing recheck.
        real_execute = loader.execute_bounded_adaptive_query

        def execute_with_unrelated_heading(**kwargs):
            result, successes, trace = real_execute(**kwargs)
            if not initial_unrelated_citation:
                return result, successes, trace
            self.assertIsNotNone(result)
            citation = sha256_json(heading.to_dict())
            result = replace(
                result, status=initial_unrelated_status, answer_citation_hashes=(citation,),
                result_fingerprint=sha256_json({
                    "initial_result": result.result_fingerprint, "heading": citation,
                }),
            )
            trace = {
                **trace,
                "subqueries": [
                    {**step, "status": initial_unrelated_status,
                     "result_fingerprint": result.result_fingerprint}
                    for step in trace["subqueries"]
                ],
            }
            return result, (*successes[:-1], result), trace

        try:
            with (
                patch.object(
                    connected_runtime.bridge,
                    "authenticate_access_token",
                    return_value=principal,
                ),
                patch.object(
                    connected_runtime.bridge,
                    "resolve_actor_context",
                    return_value=actor,
                ),
                patch.object(
                    connected_runtime.bridge,
                    "record_mcp_authorization_decision",
                    return_value=None,
                ),
                TestClient(
                    connected_runtime.application.app,
                    raise_server_exceptions=False,
                ) as client,
                patch.object(
                    loader,
                    "source_evidence_double_check",
                    wraps=source_evidence_double_check,
                ) as source_double_check,
                patch.object(loader, "execute_bounded_adaptive_query",
                             side_effect=execute_with_unrelated_heading),
            ):
                response = client.post(
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
                            "arguments": {
                                "query_text": query_text,
                                "request_contract": request_contract,
                            },
                        },
                    },
                )
            self.assertEqual(response.status_code, 200)
            tool_result = response.json()["result"]
            self.assertFalse(tool_result["isError"], tool_result)
            payload = tool_result["structuredContent"]["data"]
            self.assertEqual(source_double_check.call_count, 1)
            self.assertEqual(
                source_double_check.call_args.kwargs["verified_evidence_count"],
                int(initial_unrelated_citation),
            )
            self.assertEqual(
                tuple(source_double_check.call_args.kwargs["requested_fields"]),
                ("acceptance_condition",),
            )
            self.assertEqual(
                tuple(source_double_check.call_args.kwargs["supported_requested_fields"]), (),
            )
        finally:
            await connected_runtime.aclose()

        self.assertTrue(
            any(
                "written owner approval" in item.get("snippet", "") for item in payload["evidence"]
            ),
            json.dumps(payload, ensure_ascii=False, default=str),
        )
        citation = next(
            item for item in payload["evidence"] if "written owner approval" in item["snippet"]
        )
        self.assertEqual(
            citation["citation_hash"],
            sha256_json(paragraph.to_dict()),
        )
        self.assertEqual(
            citation["document_locator"],
            {
                "block_type": "paragraph",
                "asset_id": asset.asset_id,
                "extractor_run_id": paragraph.extractor_run_id,
                "line_start": paragraph.location["line_start"],
                "line_end": paragraph.location["line_end"],
            },
        )
        tampered_references = [list(reference) for reference in source_references]
        tampered_reference = next(
            reference
            for reference in tampered_references
            if reference[1] == paragraph.observation_id
        )
        tampered_reference[2] = sha256_json({"tampered": True})
        tampered_records = IngestionRevisionSourceRecords(
            runtime_store=SimpleNamespace(workspace_id=loader.WORKSPACE_ID),
            job_authorities=(job_authority,),
            requester_user_id=loader.APPROVER_ACTOR,
            workspace_id=loader.WORKSPACE_ID,
            observation_references=tampered_references,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "completed ingestion indexed Observation binding is invalid",
        ):
            tampered_records.scan_authorized_observations(
                source_family="document_text",
                source_scope_ids=(dict(job_authority.permission_scope)["scope_id"],),
                max_observations=_REVISION_SOURCE_FALLBACK_OBSERVATION_LIMIT,
            )
        self.assertEqual(
            citation["revision_binding"],
            {
                "source_authority_fingerprint": source_authority_fingerprint,
                "source_session_binding_fingerprint": (
                    revision.session.source_session_binding_fingerprint
                ),
            },
        )
        self.assertEqual(
            payload["query_agent"]["request_contract"]["source_family_scope"],
            ["document_text"],
        )
        source_recovery = payload["query_agent"]["context_bundle"]["source_recovery"]
        self.assertEqual(source_recovery["status"], "ok")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["answer"]["status"], "answered")
        self.assertIn("Supported:", payload["answer"]["text"])
        self.assertTrue(source_recovery["attempted"])
        self.assertTrue(source_recovery["scan"]["complete"])
        initial_subqueries = payload["query_agent"]["context_bundle"]["successful_subqueries"]
        self.assertTrue(initial_subqueries)
        self.assertTrue(all(
            [item["citation_hash"] for item in subquery["evidence"]]
            == ([sha256_json(heading.to_dict())] if initial_unrelated_citation else [])
            for subquery in initial_subqueries
        ))
        self.assertEqual(
            source_recovery["initial_status"],
            initial_subqueries[-1]["status"],
        )
        self.assertIn(citation, source_recovery["evidence"])
        presented = human_uat_orchestrator.compact_evidence_for_model(payload)
        self.assertIn(citation, presented["evidence"])
        self.assertIn(citation["citation_hash"], presented["citations"])
        self.assertEqual(
            presented["query_agent"]["context_bundle"]["missing_field_hashes"],
            [sha256_json("acceptance_condition")],
        )
        self.assertIn("used", source_recovery["warnings"])
        self.assertIn("used", payload["query_agent"]["warnings"])
        self.assertEqual(
            source_recovery["recovery_fingerprint"],
            sha256_json(
                {
                    key: value
                    for key, value in source_recovery.items()
                    if key != "recovery_fingerprint"
                }
            ),
        )
        self.assertEqual(
            payload["query_agent"]["context_bundle"]["bundle_fingerprint"],
            sha256_json(
                {
                    key: value
                    for key, value in payload["query_agent"]["context_bundle"].items()
                    if key != "bundle_fingerprint"
                }
            ),
        )

    def test_revision_admits_real_standalone_text_and_mixed_native_lineage(self) -> None:
        temp_dir = _paths.fresh_test_dir("issue56-native-text-revision")
        asset, extraction = _registered_text_revision_fixture(temp_dir)
        text_observations = tuple(extraction.observations)
        paragraph = next(item for item in text_observations if item.observation_type == "paragraph")
        registered_binding = {
            "asset_id": asset.asset_id,
            "asset_content_hash": asset.content_hash,
            "extractor_run_id": extraction.extractor_run.extractor_run_id,
            "observation_hashes": sorted(sha256_json(item.to_dict()) for item in text_observations),
        }
        text_authority_fingerprint = sha256_json(registered_binding)
        runtime = _contract_only_runtime()
        with (
            patch.object(
                issue56_sealed_source,
                "load_issue56_target_runtime_components",
                return_value=runtime,
            ),
            patch.object(
                hybrid,
                "_load_pinned_issue56_runtime_components",
                return_value=runtime,
            ),
        ):
            text_revision = build_issue56_ingestion_revision(
                observations=text_observations,
                bundles=(),
                source_binding={
                    "source_authority_fingerprint": text_authority_fingerprint,
                    "registered_asset_revision_fingerprint": text_authority_fingerprint,
                },
                requester_user_id="user_yifan",
                workspace_id="workspace_formowl",
                source_authority_fingerprint=text_authority_fingerprint,
            )

            text_lineage = next(
                item
                for item in text_revision.session.occurrence_lineages
                if item.source_observation_id == paragraph.observation_id
            )
            self.assertIsInstance(text_lineage, TextDocumentOccurrenceLineage)
            self.assertEqual(text_revision.bundles, ())
            self.assertEqual(
                text_revision.session.authorized_source.source_kind,
                semantic_plan.AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
            )
            self.assertEqual(
                hybrid._semantic_session_source_families(text_revision.session),
                ("document_text",),
            )
            self.assertEqual(text_lineage.asset_id, asset.asset_id)
            self.assertEqual(
                text_lineage.extractor_run_id,
                extraction.extractor_run.extractor_run_id,
            )
            self.assertEqual(
                (text_lineage.line_start, text_lineage.line_end),
                (3, 4),
            )
            self.assertFalse(hasattr(text_lineage, "message_occurrence_id"))
            self.assertEqual(
                text_revision.session.source_authority_fingerprint,
                text_authority_fingerprint,
            )
            table_provider = object()
            with patch.object(
                loader,
                "_build_attachment_table_row_provider",
                return_value=table_provider,
            ) as build_table_provider:
                providers = loader._build_ingestion_source_occurrence_providers(
                    text_revision.session
                )
            self.assertEqual(providers, (table_provider, table_provider))
            self.assertEqual(
                [call.kwargs["inline_tables"] for call in build_table_provider.call_args_list],
                [False, True],
            )

            mail_bundle = _mail_bundle(_paths.fresh_test_dir("issue56-native-text-mixed-mail"))
            mail_observation = Observation(
                observation_id="observation_mail_revision_fixture",
                extractor_run_id="extractor_mail_revision_fixture",
                observation_type="email_body_segment",
                modality="mail",
                location={"message_occurrence_id": "message_occurrence_fixture"},
                confidence=1.0,
                permission_scope=PermissionScope.project("project_formowl"),
                created_at="2026-09-01T00:00:00+00:00",
                asset_id=mail_bundle.mail_import_session.source_asset_id,
                text="synthetic mail evidence for mixed revision coverage",
                payload={"message_fingerprint": "sha256:" + "a" * 64},
            )
            mixed_authority_fingerprint = sha256_json(
                {
                    **registered_binding,
                    "mail_observation_hash": sha256_json(mail_observation.to_dict()),
                }
            )
            mixed_revision = build_issue56_ingestion_revision(
                observations=(mail_observation, *text_observations),
                bundles=(mail_bundle,),
                source_binding={
                    "source_authority_fingerprint": mixed_authority_fingerprint,
                    "registered_asset_revision_fingerprint": text_authority_fingerprint,
                    "mail_observation_hash": sha256_json(mail_observation.to_dict()),
                },
                requester_user_id=mail_bundle.mail_import_session.owner_user_id,
                workspace_id=mail_bundle.mail_import_session.workspace_id,
                source_authority_fingerprint=mixed_authority_fingerprint,
            )

        lineage_by_id = {
            item.source_observation_id: item for item in mixed_revision.session.occurrence_lineages
        }
        self.assertEqual(
            mixed_revision.session.authorized_source.source_kind,
            semantic_plan.AUTHORIZED_MULTISOURCE_OBSERVATION_SOURCE_KIND,
        )
        self.assertEqual(
            mixed_revision.session.authorized_source.authorized_source_kinds,
            (
                semantic_plan.AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
                semantic_plan.AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
            ),
        )
        self.assertIsInstance(
            lineage_by_id[mail_observation.observation_id],
            MailMessageOccurrenceLineage,
        )
        self.assertIsInstance(
            lineage_by_id[paragraph.observation_id],
            TextDocumentOccurrenceLineage,
        )
        self.assertEqual(
            hybrid._semantic_session_source_families(mixed_revision.session),
            ("document_text", "mail"),
        )
        self.assertEqual(
            mixed_revision.session.source_authority_fingerprint,
            mixed_authority_fingerprint,
        )

    def test_text_revision_rejects_invalid_lineage_authority_and_permission(self) -> None:
        temp_dir = _paths.fresh_test_dir("issue56-native-text-invalid-revision")
        asset, extraction = _registered_text_revision_fixture(temp_dir)
        paragraph = next(
            item for item in extraction.observations if item.observation_type == "paragraph"
        )
        authority_fingerprint = sha256_json(
            {"asset_id": asset.asset_id, "asset_content_hash": asset.content_hash}
        )
        source_binding = {"source_authority_fingerprint": authority_fingerprint}
        runtime = _contract_only_runtime()
        invalid_line_observations = (
            Observation.from_dict(
                {
                    **paragraph.to_dict(),
                    "location": {"line_start": True, "line_end": 4},
                }
            ),
            Observation.from_dict(
                {
                    **paragraph.to_dict(),
                    "location": {"line_start": 4, "line_end": 3},
                }
            ),
            Observation.from_dict(
                {
                    **paragraph.to_dict(),
                    "location": {"line_start": 3},
                }
            ),
        )
        text_source = semantic_plan.validated_authorized_semantic_source(
            source_kind=semantic_plan.AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
            workspace_id=asset.workspace_id,
            source_scope_ids=("project_other",),
            authorized_permission_scopes=(PermissionScope.project("project_other"),),
        )
        with self.assertRaisesRegex(ContractValidationError, "permission scope mismatch"):
            source_occurrence_lineage_from_observation(
                paragraph,
                authorized_source=text_source,
            )

        with (
            patch.object(
                issue56_sealed_source,
                "load_issue56_target_runtime_components",
                return_value=runtime,
            ),
            patch.object(
                hybrid,
                "_load_pinned_issue56_runtime_components",
                return_value=runtime,
            ),
        ):
            with self.assertRaisesRegex(ContractValidationError, "owner binding"):
                build_issue56_ingestion_revision(
                    observations=extraction.observations,
                    bundles=(),
                    source_binding={},
                    requester_user_id="user_yifan",
                    workspace_id=asset.workspace_id,
                )
            with self.assertRaisesRegex(ContractValidationError, "authority binding"):
                build_issue56_ingestion_revision(
                    observations=extraction.observations,
                    bundles=(),
                    source_binding={},
                    requester_user_id="user_yifan",
                    workspace_id=asset.workspace_id,
                    source_authority_fingerprint="not-a-seal",
                )
            for invalid_observation in invalid_line_observations:
                with self.subTest(location=invalid_observation.location):
                    with self.assertRaisesRegex(
                        ContractValidationError,
                        "line location|line range",
                    ):
                        build_issue56_ingestion_revision(
                            observations=(invalid_observation,),
                            bundles=(),
                            source_binding=source_binding,
                            requester_user_id="user_yifan",
                            workspace_id=asset.workspace_id,
                            source_authority_fingerprint=authority_fingerprint,
                        )

    def test_text_lineage_deserialization_rechecks_the_bound_observation(self) -> None:
        temp_dir = _paths.fresh_test_dir("issue56-native-text-reader-lineage")
        asset, extraction = _registered_text_revision_fixture(temp_dir)
        observation = next(
            item for item in extraction.observations if item.observation_type == "paragraph"
        )
        permission_scope = dict(asset.permission_scope)
        permission_scope_contract = PermissionScope(**permission_scope)
        authorized_source = semantic_plan.validated_authorized_semantic_source(
            source_kind=semantic_plan.AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
            workspace_id=asset.workspace_id,
            source_scope_ids=(permission_scope["scope_id"],),
            authorized_permission_scopes=(permission_scope_contract,),
        )
        lineage = source_occurrence_lineage_from_observation(
            observation,
            authorized_source=authorized_source,
        )
        observation_hash = sha256_json(observation.to_dict())
        job_fingerprint = sha256_json({"job": "local-text-reader-fixture"})

        class _BoundAuthority:
            def __init__(self):
                self.job_fingerprint = job_fingerprint
                self.permission_scope = permission_scope
                self.asset = asset

            @staticmethod
            def load_indexed_observation(
                observation_id,
                *,
                expected_observation_hash,
                expected_job_fingerprint,
            ):
                if (
                    observation_id != observation.observation_id
                    or expected_observation_hash != observation_hash
                    or expected_job_fingerprint != job_fingerprint
                ):
                    raise ContractValidationError("fixture source binding mismatch")
                return observation

        class _BoundRuntimeStore:
            def __init__(self, helper):
                self.workspace_id = asset.workspace_id
                self.helper = helper

            def get_helper(self, observation_id):
                return self.helper if observation_id == observation.observation_id else None

        helper = {
            "observation_id": observation.observation_id,
            "observation_hash": observation_hash,
            "reference": {"job_index": 0, "job_fingerprint": job_fingerprint},
            "permission_scope": permission_scope,
            "source_scope_id": permission_scope["scope_id"],
            "lineage": to_plain(lineage),
        }
        records = IngestionRevisionSourceRecords(
            runtime_store=_BoundRuntimeStore(helper),
            job_authorities=(_BoundAuthority(),),
            requester_user_id=asset.owner_user_id,
            workspace_id=asset.workspace_id,
        )
        self.assertEqual(records.lineage(observation.observation_id), lineage)

        tampered_helper = {
            **helper,
            "lineage": {**to_plain(lineage), "line_start": lineage.line_start + 1},
        }
        tampered_records = IngestionRevisionSourceRecords(
            runtime_store=_BoundRuntimeStore(tampered_helper),
            job_authorities=(_BoundAuthority(),),
            requester_user_id=asset.owner_user_id,
            workspace_id=asset.workspace_id,
        )
        with self.assertRaisesRegex(ContractValidationError, "lineage mismatch"):
            tampered_records.lineage(observation.observation_id)

    def _posting_shortlist_fixture(self, source_family, *, requester_user_id="user_yifan"):
        permission_scope = PermissionScope.project("project_formowl")
        observation = Observation(
            observation_id="observation_late_hit",
            extractor_run_id="extractor_late_hit",
            observation_type=(
                "email_body_segment" if source_family == "mail" else "paragraph"
            ),
            modality="mail" if source_family == "mail" else "text",
            location=(
                {"message_occurrence_id": "message_late_hit"}
                if source_family == "mail"
                else {"line_start": 9, "line_end": 9}
            ),
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id="asset_late_hit",
            text="late-token authorized evidence",
            payload={"message_fingerprint": "sha256:" + "1" * 64} if source_family == "mail" else {},
        )
        observation_hash = sha256_json(observation.to_dict())
        job_fingerprint = "sha256:" + ("a" * 64)
        asset = SimpleNamespace(
            owner_user_id=requester_user_id,
            workspace_id="workspace_formowl",
            lifecycle_state="active",
            asset_id=observation.asset_id,
            content_hash="sha256:" + ("c" * 64),
            source_ref={
                "source_system": "formowl_upload_session",
                "source_type": "mail_archive",
                "source_id": "synthetic_shortlist_upload",
                "source_key": "synthetic_shortlist_upload",
            } if source_family == "mail" else {},
        )
        # Place the indexed hit beyond the first 144 authoritative references.
        observations = [
            replace(observation, observation_id=f"observation_earlier_{index}",
                    text="unrelated evidence")
            for index in range(145)
        ] + [observation]
        by_id = {item.observation_id: item for item in observations}

        def load_observation(
            observation_id, *, expected_observation_hash, expected_job_fingerprint,
        ):
            item = by_id[observation_id]
            if (
                expected_job_fingerprint != job_fingerprint
                or expected_observation_hash != sha256_json(item.to_dict())
                or to_plain(item.permission_scope) != permission_scope.to_dict()
                or item.asset_id != asset.asset_id
            ):
                raise ContractValidationError("fixture source binding mismatch")
            return item

        authority = SimpleNamespace(
            permission_scope=permission_scope.to_dict(),
            asset=asset,
            job_fingerprint=job_fingerprint,
            load_indexed_observation=Mock(side_effect=load_observation),
        )

        helper = {
            "observation_id": observation.observation_id,
            "observation_hash": observation_hash,
            "reference": {"job_index": 0, "job_fingerprint": job_fingerprint},
            "permission_scope": permission_scope.to_dict(),
            "source_scope_id": "project_formowl",
            "lineage": {"source_observation_id": observation.observation_id},
        }

        runtime_store = SimpleNamespace(
            workspace_id="workspace_formowl",
            source_family_lexical_lookup=Mock(return_value=[observation_hash]),
            helper_for_hash=Mock(
                side_effect=lambda value: helper if value == observation_hash else None,
            ),
        )
        records = IngestionRevisionSourceRecords(
            runtime_store=runtime_store,
            job_authorities=(authority,),
            requester_user_id=requester_user_id,
            workspace_id="workspace_formowl",
            observation_references=[
                [0, item.observation_id, sha256_json(item.to_dict())]
                for item in observations
            ],
        )
        scope = (
            records.authorized_mail_import_session_ids[0]
            if source_family == "mail" else permission_scope.scope_id
        )
        arguments = {
            "source_family": source_family,
            "max_observations": 1,
            "deadline_monotonic": 10.5,
            **(
                {"mail_import_session_id": scope}
                if source_family == "mail" else {"source_scope_ids": (scope,)}
            ),
        }
        return SimpleNamespace(
            records=records, store=runtime_store, authority=authority,
            observation=observation, observation_hash=observation_hash,
            helper=helper, scope=scope, arguments=arguments,
            earlier=observations[0],
        )

    def test_legacy_mail_child_requires_its_genuine_parent_without_fingerprint(self) -> None:
        for use_shortlist in (False, True):
            for parent_kind in ("missing", "matching", "other_asset", "other_run"):
                with self.subTest(use_shortlist=use_shortlist, parent_kind=parent_kind):
                    fixture = self._posting_shortlist_fixture("mail")
                    child = replace(fixture.observation, payload={})
                    child_hash = sha256_json(child.to_dict())
                    items = [child]
                    if parent_kind != "missing":
                        parent = replace(
                            child, observation_id="genuine_parent",
                            observation_type="email_message",
                            asset_id="other_asset" if parent_kind == "other_asset" else child.asset_id,
                            extractor_run_id="other_run" if parent_kind == "other_run" else child.extractor_run_id,
                            payload={"message_fingerprint": "sha256:" + "1" * 64},
                        )
                        items.append(parent)
                    by_id = {item.observation_id: item for item in items}

                    def load(key, *, expected_observation_hash, expected_job_fingerprint):
                        item = by_id[key]
                        self.assertEqual(expected_observation_hash, sha256_json(item.to_dict()))
                        self.assertEqual(expected_job_fingerprint, fixture.authority.job_fingerprint)
                        return item

                    fixture.authority.load_indexed_observation.side_effect = load
                    fixture.store.helper_for_hash.side_effect = lambda value: (
                        {**fixture.helper, "observation_hash": child_hash} if value == child_hash else None
                    )
                    fixture.store.source_family_lexical_lookup.return_value = [child_hash] if use_shortlist else []
                    fixture.records.observation_references = [
                        [0, item.observation_id, sha256_json(item.to_dict())] for item in items
                    ]
                    fixture.arguments["max_observations"] = 8
                    delivered = []
                    with (source_evidence_query_terms_scope(("late-token",) if use_shortlist else ()),
                          patch("formowl_mail.issue56_sealed_source.time.monotonic", return_value=10.0)):
                        scan = fixture.records.scan_authorized_observations(
                            **fixture.arguments,
                            observation_callback=lambda item, scope: delivered.append(item.observation_id) or True,
                        )
                    if parent_kind == "matching":
                        self.assertEqual(delivered, [parent.observation_id, child.observation_id])
                        self.assertTrue(scan.complete)
                    else:
                        self.assertNotIn(child.observation_id, delivered)
                        self.assertFalse(scan.complete)
                        self.assertEqual(scan.stop_reason, "source_parent_binding_unresolved")

    def test_revision_source_reader_uses_posting_shortlist_for_late_hit(self) -> None:
        for family in ("mail", "document_text"):
            for max_observations in (1, 200):
                with self.subTest(
                    family=family,
                    max_observations=max_observations,
                ):
                    fixture = self._posting_shortlist_fixture(family)
                    fixture.arguments["max_observations"] = max_observations
                    callback = Mock(return_value=False)
                    with (
                        source_evidence_query_terms_scope(("late-token",)),
                        patch("formowl_mail.issue56_sealed_source.time.monotonic",
                              return_value=10.0),
                    ):
                        scan = fixture.records.scan_authorized_observations(
                            **fixture.arguments, observation_callback=callback,
                        )
                    fixture.store.source_family_lexical_lookup.assert_called_once_with(
                        ("late-token",),
                        source_family=family,
                        limit=max_observations,
                        timeout_ms=500,
                    )
                    fixture.store.helper_for_hash.assert_called_once_with(
                        fixture.observation_hash,
                    )
                    fixture.authority.load_indexed_observation.assert_called_once_with(
                        fixture.observation.observation_id,
                        expected_observation_hash=fixture.observation_hash,
                        expected_job_fingerprint=fixture.authority.job_fingerprint,
                    )
                    callback.assert_called_once_with(
                        fixture.observation, fixture.scope,
                    )
                    self.assertFalse(scan.complete)
                    self.assertEqual(scan.scanned_observation_count, 1)
                    self.assertEqual(scan.stop_reason, "callback")

    def test_graph_recovery_wrapper_passes_query_terms_to_source_family_shortlist(self) -> None:
        for family in ("mail", "document_text"):
            with self.subTest(source_family=family):
                fixture = self._posting_shortlist_fixture(
                    family, requester_user_id=loader.APPROVER_ACTOR,
                )
                runtime = _contract_only_runtime()
                seal = sha256_json({
                    "job_fingerprint": fixture.authority.job_fingerprint,
                    "source_references": fixture.records.observation_references,
                })
                with (
                    patch.object(issue56_sealed_source, "load_issue56_target_runtime_components",
                                 return_value=runtime),
                    patch.object(hybrid, "_load_pinned_issue56_runtime_components",
                                 return_value=runtime),
                ):
                    revision = build_issue56_ingestion_revision(
                        # The source-owned late hit is outside the admitted retrieval slice.
                        observations=(fixture.earlier,), bundles=(),
                        source_binding={
                            "source_authority_fingerprint": seal,
                            "extraction_coverage": {"source_completeness_certified": False},
                        },
                        requester_user_id=loader.APPROVER_ACTOR,
                        workspace_id=loader.WORKSPACE_ID,
                        source_authority_fingerprint=seal,
                    )
                    revision = replace(
                        revision, source_records=fixture.records,
                        job_authorities=(fixture.authority,),
                    )
                    handler = loader.build_issue56_production_semantic_retrieval_handler(
                        ingestion_revision=revision,
                        query_agent_planner=lambda original, steps, _profile, _limit: (
                            original if not steps else None
                        ),
                    )

                original_load = fixture.authority.load_indexed_observation.side_effect
                clock = [10.0]

                def load_observation(observation_id, **kwargs):
                    value = original_load(observation_id, **kwargs)
                    if observation_id != fixture.observation.observation_id:
                        # One unrelated hydration exhausts the existing phase.
                        # Without the wrapper hint, the late hit cannot be reached.
                        clock[0] = 10.5
                    return value

                fixture.authority.load_indexed_observation.side_effect = load_observation
                reader = Mock(wraps=fixture.records.scan_authorized_observations)
                fixture.records.scan_authorized_observations = reader
                binding = revision.session.source_session_binding_fingerprint
                for query in ("late-token", "authorized"):
                    with self.subTest(query=query):
                        clock[0] = 10.0
                        reader.reset_mock()
                        fixture.store.source_family_lexical_lookup.reset_mock()
                        fixture.authority.load_indexed_observation.reset_mock()
                        expected_terms = tuple(sorted(runtime.tokenizer_profile.analyze(query).tokens))
                        arguments = {
                            "query_text": query, "requester_user_id": loader.APPROVER_ACTOR,
                            "workspace_id": loader.WORKSPACE_ID, "session_id": "wrapper-source-test",
                            "required_terms": [query],
                            "request_contract": {
                                "original_query_hash": sha256_json(query),
                                "query_class": "evidence_lookup",
                                "source_family_scope": [family],
                                "requested_fields": ["source evidence"],
                                "maximum_claim_strength": "cited_evidence",
                            },
                        }
                        with patch("formowl_retrieval.gateway.time.monotonic",
                                   side_effect=lambda: clock[0]):
                            payload = handler(arguments)

                        fixture.store.source_family_lexical_lookup.assert_called_once_with(
                            expected_terms, source_family=family, limit=256, timeout_ms=500,
                        )
                        reader.assert_called_once()
                        reader_arguments = reader.call_args.kwargs
                        self.assertEqual(reader_arguments["max_observations"], 8192)
                        self.assertEqual(reader_arguments["deadline_monotonic"], 10.5)
                        self.assertEqual(
                            reader_arguments["mail_import_session_id"],
                            fixture.scope if family == "mail" else None,
                        )
                        self.assertEqual(
                            reader_arguments["source_scope_ids"],
                            (fixture.scope,) if family == "document_text" else (),
                        )
                        first_load = fixture.authority.load_indexed_observation.call_args_list[0]
                        self.assertEqual(first_load, call(
                            fixture.observation.observation_id,
                            expected_observation_hash=fixture.observation_hash,
                            expected_job_fingerprint=fixture.authority.job_fingerprint,
                        ))
                        self.assertEqual(payload["status"], "ok")
                        self.assertEqual(payload["citations"], [fixture.observation_hash])
                        self.assertEqual(
                            payload["evidence"][0]["source_scope_fingerprint"],
                            sha256_json(fixture.scope),
                        )
                        recovery = payload["query_agent"]["context_bundle"]["source_recovery"]
                        self.assertEqual(recovery["source_family"], family)
                        self.assertEqual(recovery["source_session_binding_fingerprint"], binding)
                        self.assertEqual(recovery["source_authority_fingerprint"], seal)
                        self.assertEqual(recovery["scan"], {
                            "scanned_observation_count": 2,
                            "complete": False, "stop_reason": "deadline",
                        })
                        self.assertEqual(revision.session.source_session_binding_fingerprint, binding)
                        if family == "document_text":
                            self.assertEqual(payload["evidence"][0]["document_locator"], {
                                "block_type": "paragraph", "asset_id": fixture.observation.asset_id,
                                "extractor_run_id": fixture.observation.extractor_run_id,
                                "line_start": 9, "line_end": 9,
                            })
                        validate_public_gateway_payload(payload)

                # A shortlist miss still requires the authoritative scan and
                # cannot establish absence when the same deadline is exhausted.
                clock[0] = 10.0
                reader.reset_mock()
                fixture.store.source_family_lexical_lookup.reset_mock()
                fixture.store.source_family_lexical_lookup.return_value = []
                with patch("formowl_retrieval.gateway.time.monotonic",
                           side_effect=lambda: clock[0]):
                    missed = handler(arguments)
                fixture.store.source_family_lexical_lookup.assert_called_once_with(
                    expected_terms, source_family=family, limit=256, timeout_ms=500,
                )
                reader.assert_called_once()
                self.assertEqual(missed["status"], "pending_review")
                self.assertEqual(missed["citations"], [])
                recovery = missed["query_agent"]["context_bundle"]["source_recovery"]
                self.assertEqual(recovery["scan"], {
                    "scanned_observation_count": 1, "complete": False, "stop_reason": "deadline",
                })

    def test_graph_recheck_keeps_identity_hard_and_ranks_topic_without_filtering(self) -> None:
        fixture = self._posting_shortlist_fixture(
            "document_text", requester_user_id=loader.APPROVER_ACTOR,
        )
        identity_only = replace(
            fixture.observation,
            observation_id="observation_identity_only",
            text="ZX-421 background evidence",
        )
        topic_hit = replace(
            fixture.observation,
            observation_id="observation_topic_hit",
            text="ZX-421 quarterly status evidence",
        )
        candidates = (identity_only, topic_hit)
        candidate_hashes = {sha256_json(item.to_dict()): item for item in candidates}
        original_load = fixture.authority.load_indexed_observation.side_effect

        def load_candidate(observation_id, *, expected_observation_hash, expected_job_fingerprint):
            candidate = next((item for item in candidates if item.observation_id == observation_id), None)
            if candidate is not None:
                self.assertEqual(expected_observation_hash, sha256_json(candidate.to_dict()))
                self.assertEqual(expected_job_fingerprint, fixture.authority.job_fingerprint)
                return candidate
            return original_load(
                observation_id,
                expected_observation_hash=expected_observation_hash,
                expected_job_fingerprint=expected_job_fingerprint,
            )

        fixture.authority.load_indexed_observation.side_effect = load_candidate
        original_helper = fixture.helper.copy()
        fixture.store.helper_for_hash.side_effect = lambda value: (
            {**original_helper, "observation_id": candidate_hashes[value].observation_id,
             "observation_hash": value}
            if value in candidate_hashes else None
        )
        fixture.store.source_family_lexical_lookup.return_value = sorted(candidate_hashes)
        fixture.records.observation_references = [
            reference for reference in fixture.records.observation_references
            if reference[1] != fixture.observation.observation_id
        ] + [
            [0, item.observation_id, sha256_json(item.to_dict())] for item in candidates
        ]
        runtime = _contract_only_runtime()
        seal = sha256_json({
            "job_fingerprint": fixture.authority.job_fingerprint,
            "source_references": fixture.records.observation_references,
        })
        with (
            patch.object(issue56_sealed_source, "load_issue56_target_runtime_components",
                         return_value=runtime),
            patch.object(hybrid, "_load_pinned_issue56_runtime_components",
                         return_value=runtime),
        ):
            revision = build_issue56_ingestion_revision(
                observations=(fixture.earlier,), bundles=(),
                source_binding={
                    "source_authority_fingerprint": seal,
                    "extraction_coverage": {"source_completeness_certified": False},
                },
                requester_user_id=loader.APPROVER_ACTOR,
                workspace_id=loader.WORKSPACE_ID,
                source_authority_fingerprint=seal,
            )
            revision = replace(
                revision,
                source_records=fixture.records,
                job_authorities=(fixture.authority,),
            )
            handler = loader.build_issue56_production_semantic_retrieval_handler(
                ingestion_revision=revision,
                query_agent_planner=lambda original, steps, _profile, _limit: (
                    original if not steps else None
                ),
            )

        query = "ZX-421 quarterly"
        payload = handler({
            "query_text": query,
            "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID,
            "session_id": "graph-recheck-identity-hard",
            "required_terms": ["ZX-421", "quarterly"],
            "request_contract": {
                "original_query_hash": sha256_json(query),
                "query_class": "evidence_lookup",
                "source_family_scope": ["document_text"],
                "requested_fields": ["status"],
                "maximum_claim_strength": "cited_evidence",
            },
        })
        expected_hard_lookup = tuple(sorted(runtime.tokenizer_profile.analyze("zx-421").tokens))
        lookup_call = fixture.store.source_family_lexical_lookup.call_args
        self.assertIsNotNone(lookup_call)
        self.assertEqual(lookup_call.args[0], expected_hard_lookup)
        self.assertEqual(lookup_call.kwargs["source_family"], "document_text")
        self.assertEqual(lookup_call.kwargs["limit"], 256)
        self.assertGreaterEqual(lookup_call.kwargs["timeout_ms"], 1)
        self.assertLessEqual(lookup_call.kwargs["timeout_ms"], 500)
        self.assertEqual(fixture.store.source_family_lexical_lookup.call_count, 1)
        recovery = payload["query_agent"]["context_bundle"]["source_recovery"]
        self.assertEqual(recovery["recheck_variant"], "identity_only")
        self.assertEqual((recovery["hard_term_count"], recovery["soft_term_count"]), (1, 1))
        self.assertNotEqual(
            recovery["initial_required_terms_fingerprint"],
            recovery["recheck_required_terms_fingerprint"],
        )
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["coverage"]["status"], "incomplete")
        self.assertIn("identity_only_recheck", payload["query_agent"]["warnings"])
        self.assertEqual(
            [item["citation_hash"] for item in payload["evidence"]],
            [sha256_json(topic_hit.to_dict()), sha256_json(identity_only.to_dict())],
        )

    def test_posting_shortlist_without_references_remains_incomplete(self) -> None:
        for family in ("mail", "document_text"):
            for hit in (False, True):
                with self.subTest(family=family, hit=hit):
                    fixture = self._posting_shortlist_fixture(family)
                    fixture.records.observation_references = None
                    if not hit:
                        fixture.store.source_family_lexical_lookup.return_value = []
                    callback = Mock(return_value=True)
                    with (
                        source_evidence_query_terms_scope(("late-token",)),
                        patch("formowl_mail.issue56_sealed_source.time.monotonic",
                              return_value=10.0),
                    ):
                        scan = fixture.records.scan_authorized_observations(
                            **fixture.arguments, observation_callback=callback,
                        )
                    self.assertFalse(scan.complete)
                    self.assertEqual(scan.scanned_observation_count, int(hit))
                    self.assertEqual(
                        scan.stop_reason,
                        "indexed_shortlist" if hit else "indexed_shortlist_miss",
                    )
                    self.assertEqual(callback.call_count, int(hit))
                    if hit:
                        callback.assert_called_once_with(
                            fixture.observation, fixture.scope,
                        )
                    else:
                        fixture.authority.load_indexed_observation.assert_not_called()

    def test_posting_shortlist_missing_helper_keeps_authoritative_read(self) -> None:
        for family in ("mail", "document_text"):
            with self.subTest(family=family):
                fixture = self._posting_shortlist_fixture(family)
                first_hash = sha256_json(fixture.earlier.to_dict())
                fixture.store.source_family_lexical_lookup.return_value = [
                    fixture.observation_hash
                ]
                fixture.store.helper_for_hash.side_effect = None
                fixture.store.helper_for_hash.return_value = None
                fixture.records.observation_references = [
                    [0, fixture.earlier.observation_id, first_hash],
                    [0, fixture.observation.observation_id, fixture.observation_hash],
                    [0, "observation_tail", "sha256:" + ("e" * 64)],
                ]
                fixture.arguments["max_observations"] = 2
                callback = Mock(return_value=True)
                with (
                    source_evidence_query_terms_scope(("late-token",)),
                    patch("formowl_mail.issue56_sealed_source.time.monotonic",
                          return_value=10.0),
                ):
                    scan = fixture.records.scan_authorized_observations(
                        **fixture.arguments, observation_callback=callback,
                    )
                self.assertEqual(
                    fixture.authority.load_indexed_observation.call_args_list,
                    [
                        call(
                            fixture.earlier.observation_id,
                            expected_observation_hash=first_hash,
                            expected_job_fingerprint=fixture.authority.job_fingerprint,
                        ),
                        call(
                            fixture.observation.observation_id,
                            expected_observation_hash=fixture.observation_hash,
                            expected_job_fingerprint=fixture.authority.job_fingerprint,
                        ),
                    ],
                )
                self.assertEqual(
                    callback.call_args_list,
                    [
                        call(fixture.earlier, fixture.scope),
                        call(fixture.observation, fixture.scope),
                    ],
                )
                self.assertEqual(scan.scanned_observation_count, 2)
                self.assertFalse(scan.complete)
                self.assertEqual(scan.stop_reason, "observation_limit")

    def test_posting_shortlist_checks_deadline_before_lookup_and_projection(self) -> None:
        for phase in ("next_iteration", "helper", "hydration"):
            with self.subTest(phase=phase):
                fixture = self._posting_shortlist_fixture("document_text")
                clock = [10.0]
                callback = Mock(return_value=True)
                original_load = fixture.authority.load_indexed_observation.side_effect

                class _Shortlist(list):
                    def __iter__(self):
                        yield "sha256:" + ("f" * 64)
                        clock[0] = 10.5
                        yield fixture.observation_hash

                def slow_helper(_hash):
                    clock[0] = 10.5
                    return fixture.helper

                def slow_load(*args, **kwargs):
                    value = original_load(*args, **kwargs)
                    clock[0] = 10.5
                    return value

                if phase == "next_iteration":
                    fixture.store.source_family_lexical_lookup.return_value = _Shortlist()
                elif phase == "helper":
                    fixture.store.helper_for_hash.side_effect = slow_helper
                else:
                    fixture.authority.load_indexed_observation.side_effect = slow_load
                with (
                    source_evidence_query_terms_scope(("late-token",)),
                    patch("formowl_mail.issue56_sealed_source.time.monotonic",
                          side_effect=lambda: clock[0]),
                ):
                    scan = fixture.records.scan_authorized_observations(
                        **fixture.arguments, observation_callback=callback,
                    )
                if phase == "next_iteration":
                    # A reader may materialize the bounded shortlist first and
                    # then stop before any helper lookup; at most one lookup.
                    self.assertLessEqual(fixture.store.helper_for_hash.call_count, 1)
                else:
                    fixture.store.helper_for_hash.assert_called_once()
                self.assertEqual(
                    fixture.authority.load_indexed_observation.call_count,
                    int(phase == "hydration"),
                )
                callback.assert_not_called()
                self.assertFalse(scan.complete)
                self.assertEqual(scan.stop_reason, "deadline")

    def test_observation_index_preserves_mail_workspace_scope_but_rejects_undeclared_text(
        self,
    ) -> None:
        runtime = _contract_only_runtime()
        workspace_id = "workspace_synthetic"

        def build_index(observation, authorized_source, lineages=()):
            return build_authorized_observation_snippet_index(
                (observation,),
                authorized_source=authorized_source,
                occurrence_lineages=lineages,
                authorized_observation_hash_by_id={
                    observation.observation_id: sha256_json(observation.to_dict()),
                },
                tokenizer_profile=runtime.tokenizer_profile,
            )

        mail_selector = "mailimport:" + "2" * 64
        mail_source = semantic_plan.validated_authorized_semantic_source(
            source_kind=semantic_plan.AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=workspace_id,
            source_scope_ids=(mail_selector,),
        )
        mail_observation = Observation(
            observation_id="observation_legacy_mail_workspace",
            extractor_run_id="extractor_synthetic",
            observation_type="email_body_segment",
            modality="mail",
            location={"message_occurrence_id": "occurrence_synthetic"},
            confidence=1.0,
            permission_scope=PermissionScope("workspace", "restricted", workspace_id),
            created_at="2026-09-01T00:00:00+00:00",
            asset_id="asset_synthetic",
            text="workspace-scoped mail evidence",
            payload={"message_fingerprint": "sha256:" + "1" * 64},
        )
        mail_index, mail_manifest = build_index(
            mail_observation,
            mail_source,
            (
                MailMessageOccurrenceLineage(
                    mail_observation.observation_id,
                    "occurrence_synthetic",
                ),
            ),
        )
        self.assertEqual(mail_manifest.indexed_observation_count, 1)
        self.assertEqual(len(mail_index.snippets), 1)

        declared_project = "project_declared"
        text_source = semantic_plan.validated_authorized_semantic_source(
            source_kind=semantic_plan.AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
            workspace_id=workspace_id,
            source_scope_ids=(declared_project,),
            authorized_permission_scopes=(PermissionScope.project(declared_project),),
        )
        text_observation = Observation(
            observation_id="observation_undeclared_text_scope",
            extractor_run_id="extractor_text",
            observation_type="paragraph",
            modality="text",
            location={"line_start": 1, "line_end": 1},
            confidence=1.0,
            permission_scope=PermissionScope(
                "workspace",
                "restricted",
                workspace_id,
            ),
            created_at="2026-09-01T00:00:00+00:00",
            asset_id="asset_text",
            text="standalone document evidence",
        )
        text_lineage = TextDocumentOccurrenceLineage(
            text_observation.observation_id,
            text_observation.asset_id,
            text_observation.extractor_run_id,
            1,
            1,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "text document permission scope mismatch",
        ):
            build_index(text_observation, text_source, (text_lineage,))

    def test_real_session_unbound_exact_mail_requires_clarification(self) -> None:
        runtime = _contract_only_runtime()
        permission = PermissionScope.project("project_synthetic")
        source = semantic_plan.validated_authorized_semantic_source(
            source_kind=semantic_plan.AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id="workspace_synthetic",
            source_scope_ids=("project_synthetic",),
            authorized_permission_scopes=(permission,),
        )
        observation = Observation(
            observation_id="observation_synthetic_mail",
            extractor_run_id="extractor_synthetic",
            observation_type="email_body_segment",
            modality="mail",
            location={"message_occurrence_id": "occurrence_synthetic"},
            confidence=1.0,
            permission_scope=permission,
            created_at="2026-09-01T00:00:00+00:00",
            asset_id="asset_synthetic",
            text="audit approval",
            payload={"message_fingerprint": "sha256:" + "1" * 64},
        )
        observation_hash = sha256_json(observation.to_dict())
        lineage = MailMessageOccurrenceLineage(
            observation.observation_id,
            "occurrence_synthetic",
        )
        index, manifest = build_authorized_observation_snippet_index(
            (observation,),
            authorized_source=source,
            occurrence_lineages=(lineage,),
            authorized_observation_hash_by_id={
                observation.observation_id: observation_hash,
            },
            tokenizer_profile=runtime.tokenizer_profile,
        )
        with patch.object(
            hybrid,
            "_load_pinned_issue56_runtime_components",
            return_value=runtime,
        ):
            session = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=index,
                authorized_observations=(observation,),
                occurrence_lineages=(lineage,),
                requester_user_id="user_synthetic",
            )
        self.assertIsInstance(session, hybrid.AuthorizedSemanticMailSession)
        self.assertEqual(session.source_occurrence_providers, ())
        view = hybrid.build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=manifest.index_fingerprint,
        ).effective_graph_view
        selector = "mailimport:" + "2" * 64
        records = SimpleNamespace(
            authorized_mail_import_session_ids=(selector,),
            observation_for_hash=lambda value: (observation if value == observation_hash else None),
            observation_hash=lambda _value: observation_hash,
            lineage=lambda _value: lineage,
            mail_import_session_id_for_observation=lambda _value: selector,
            scan_authorized_mail_observations=Mock(),
        )
        handler = build_revision_owned_mail_evidence_query_handler(
            session=session,
            effective_graph_view=view,
            source_records=records,
            safe_binding={"extraction_coverage": {"source_completeness_certified": True}},
        )
        original_query = hybrid.AuthorizedSemanticMailSession.query
        semantic_results = []

        def run_real_query(bound_session, **kwargs):
            self.assertEqual(
                kwargs["request_contract"]["query_class"],
                "exact_set_or_inventory",
            )
            result = original_query(bound_session, **kwargs)
            semantic_results.append(result.to_safe_dict())
            return result

        with patch.object(
            hybrid.AuthorizedSemanticMailSession,
            "query",
            autospec=True,
            side_effect=run_real_query,
        ):
            result = handler(
                {
                    "query_text": "List all mail messages and count them.",
                    "requester_user_id": "user_synthetic",
                    "workspace_id": "workspace_synthetic",
                    "mail_import_session_id": selector,
                    "limit": 100,
                }
            )
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(result["citations"], [])
        self.assertIn("exact_query_requires_structured_binding", result["warnings"])
        self.assertNotIn("mail_evidence_source_fallback_used", result["warnings"])
        records.scan_authorized_mail_observations.assert_not_called()
        self.assertEqual(len(semantic_results), 1)
        governed = semantic_results[0]
        self.assertEqual(governed["status"], "replan_required")
        self.assertEqual(governed["query_class"], "exact_set_or_inventory")
        self.assertEqual(governed["claim_strength"], "no_claim")
        self.assertEqual(governed["exact_executor_status"], "not_started")
        self.assertIsNone(governed["exact_result"])
        # An executable exact override still requires actual typed fields.
        with self.assertRaisesRegex(ContractValidationError, "override is invalid"):
            semantic_plan.route_semantic_query(
                query_text="List all mail messages and count them.",
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                effective_graph_view=view,
                authorized_source=source,
                query_class_override="exact_set_or_inventory",
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "provider selection is invalid",
        ):
            session.query(
                query_text="List all mail messages and count them.",
                effective_graph_view=view,
                exact_field="unregistered_field",
            )

    def _revision_owned_mail_fixture(
        self,
        *,
        complete: bool = True,
        source_text: str = "audit approval",
        subject: str = "Audit approval",
    ):
        permission_scope = PermissionScope.project("project_formowl")
        authorized_source = semantic_plan.validated_authorized_semantic_source(
            source_kind=semantic_plan.AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id="workspace_formowl",
            source_scope_ids=("project_formowl",),
            authorized_permission_scopes=(permission_scope,),
        )
        observation = Observation(
            observation_id="observation_mail_001",
            extractor_run_id="extractor_mail_001",
            observation_type="email_body_segment",
            modality="mail",
            location={
                "archive_id": "archive_001",
                "mailbox_id": "mailbox_001",
                "message_occurrence_id": "message_occurrence_001",
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id="asset_mail_001",
            text=source_text,
            payload={
                "message_fingerprint": "sha256:" + ("1" * 64),
                "subject": subject,
            },
        )
        observation_hash = sha256_json(observation.to_dict())
        selector = "mailimport:" + ("2" * 64)
        other_selector = "mailimport:" + ("4" * 64)
        lineage = MailMessageOccurrenceLineage(
            source_observation_id=observation.observation_id,
            message_occurrence_id="message_occurrence_001",
        )

        class _SourceRecords:
            authorized_mail_import_session_ids = (selector, other_selector)

            def __init__(self):
                self.lineage_value = lineage
                self.observation = observation

            def observation_for_hash(self, value):
                return observation if value == observation_hash else None

            def observation_hash(self, value):
                return observation_hash if value == observation.observation_id else None

            def lineage(self, value):
                if value != observation.observation_id:
                    raise AssertionError("unexpected lineage lookup")
                return self.lineage_value

            def mail_import_session_id_for_observation(self, value):
                if value != observation.observation_id:
                    raise AssertionError("unexpected selector lookup")
                return selector

        records = _SourceRecords()
        session = SimpleNamespace(
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            authorized_source=authorized_source,
            source_session_binding_fingerprint="sha256:" + ("3" * 64),
            query=Mock(
                side_effect=lambda **kwargs: (
                    semantic_plan.validate_semantic_request_contract(
                        kwargs["request_contract"],
                        available_source_families=("mail",),
                    )
                    and SimpleNamespace(
                        status="ok",
                        warnings=(),
                        answer_citation_hashes=(observation_hash,),
                        scores=(),
                    )
                )
            ),
        )
        safe_binding = {
            "extraction_coverage": {
                "source_completeness_certified": complete,
            },
        }
        handler = build_revision_owned_mail_evidence_query_handler(
            session=session,
            effective_graph_view=SimpleNamespace(),
            source_records=records,
            safe_binding=safe_binding,
        )
        return handler, session, records, selector, other_selector, observation_hash

    def test_source_double_check_retries_only_uncited_results_in_same_scope(self) -> None:
        for first_status in (
            "ok",
            "not_found",
            "no_answer",
            "partial",
            "pending_review",
            "incomplete",
            "unsupported",
        ):
            with self.subTest(first_status=first_status):
                handler, session, records, selector, other_selector, expected_hash = (
                    self._revision_owned_mail_fixture(
                        complete=False,
                        source_text="ZX-421 audit approval",
                    )
                )
                session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status=first_status,
                    warnings=("bounded_semantic_result",),
                    answer_citation_hashes=(),
                    scores=(),
                )

                def scan_source(**kwargs):
                    self.assertEqual(kwargs["mail_import_session_id"], selector)
                    self.assertEqual(
                        kwargs["max_observations"],
                        _REVISION_SOURCE_FALLBACK_OBSERVATION_LIMIT,
                    )
                    self.assertEqual(
                        kwargs["deadline_monotonic"],
                        10.0 + _REVISION_SOURCE_FALLBACK_TIME_BUDGET_MS / 1000,
                    )
                    callback = kwargs["observation_callback"]
                    self.assertTrue(callback(records.observation, other_selector))
                    self.assertFalse(callback(records.observation, selector))
                    return RevisionOwnedMailSourceScan((), 2, False, "callback")

                scan = Mock(side_effect=scan_source)
                records.scan_authorized_mail_observations = scan
                request = {
                    "query_text": "ZX-421 audit",
                    "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id,
                    "mail_import_session_id": selector,
                    "limit": 1,
                }
                with (
                    patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0),
                    patch(
                        "formowl_mail.query.source_evidence_double_check",
                        wraps=source_evidence_double_check,
                    ) as shared_core,
                ):
                    result = handler(request)
                shared_core.assert_called_once()
                self.assertEqual(shared_core.call_args.kwargs["verified_evidence_count"], 0)
                session.query.assert_called_once()
                self.assertEqual(
                    session.query.call_args.kwargs["query_text"], request["query_text"]
                )
                self.assertEqual(
                    session.query.call_args.kwargs["request_contract"]["source_family_scope"],
                    ["mail"],
                )
                scan.assert_called_once()
                self.assertEqual(result["status"], "ok")
                self.assertEqual(len(result["citations"]), 1)
                self.assertEqual(
                    result["evidence_snippets"][0]["source_observation_hash"], expected_hash
                )
                self.assertEqual(result["evidence_snippets"][0]["mail_import_session_id"], selector)
                self.assertIn("bounded_semantic_result", result["warnings"])
                self.assertIn(
                    "mail_evidence_source_fallback_used",
                    result["warnings"],
                )
                self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])
                # Verified citations must not trigger another source check.
                scan.reset_mock()
                session.query.return_value.answer_citation_hashes = (expected_hash,)
                handler(request)
                scan.assert_not_called()

    def test_mail_all_missing_requested_fields_rechecks_despite_unrelated_citation(self) -> None:
        handler, session, records, selector, _, initial_hash = self._revision_owned_mail_fixture(
            complete=False, source_text="ZX-421 audit background.",
        )
        session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="partial", query_class="evidence_lookup", warnings=(),
            answer_citation_hashes=(initial_hash,), scores=(), exact_result=None,
        )
        recovered = replace(
            records.observation, observation_id="observation_mail_recovered",
            text="ZX-421 audit deadline: 2030-01-02.",
            location={**records.observation.location, "message_occurrence_id": "occurrence_recovered"},
        )
        second_recovered = replace(
            recovered, observation_id="observation_mail_recovered_second",
            location={**recovered.location, "message_occurrence_id": "occurrence_recovered_second"},
        )
        bound_observations = {
            item.observation_id: item for item in (records.observation, recovered, second_recovered)
        }
        records.lineage = lambda observation_id: source_occurrence_lineage_from_observation(
            bound_observations[observation_id],
            authorized_source=session.authorized_source,
        )
        scan = Mock(return_value=RevisionOwnedMailSourceScan(
            ((recovered, selector), (second_recovered, selector)), 2, False, "observation_limit",
        ))
        records.scan_authorized_mail_observations = scan
        query = "ZX-421 audit"
        request = {
            "query_text": query, "requester_user_id": session.requester_user_id,
            "workspace_id": session.workspace_id, "mail_import_session_id": selector,
            "limit": 2,
            "request_contract": {
                "original_query_hash": sha256_json(query), "query_class": "evidence_lookup",
                "source_family_scope": ["mail"], "requested_fields": ["deadline", "owner"],
                "maximum_claim_strength": "cited_evidence",
            },
        }
        with patch("formowl_mail.query.source_evidence_double_check",
                   wraps=source_evidence_double_check) as shared_core:
            result = handler(request)
        scan.assert_called_once()
        session.query.assert_called_once()
        self.assertEqual(shared_core.call_args.kwargs["verified_evidence_count"], 1)
        self.assertEqual(tuple(shared_core.call_args.kwargs["requested_fields"]), ("deadline", "owner"))
        self.assertEqual(tuple(shared_core.call_args.kwargs["supported_requested_fields"]), ())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 2)
        self.assertEqual(
            {item["source_observation_hash"] for item in result["evidence_snippets"]},
            {initial_hash, sha256_json(recovered.to_dict())},
        )
        self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])

    def test_mail_partial_and_source_blank_support_skip_all_missing_scan(self) -> None:
        for value in ("2030-01-02", ""):
            with self.subTest(value=value):
                handler, session, records, selector, _, citation = self._revision_owned_mail_fixture(
                    source_text=f"ZX-421 audit deadline: {value}",
                )
                session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
                lineage = records.lineage(records.observation.observation_id).lineage_fingerprint
                item = SimpleNamespace(
                    structure_status="source_provided",
                    structured_values=(("deadline", value, citation, lineage),),
                    cited_observation_hashes=(citation,),
                )
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status="partial", query_class="evidence_lookup", warnings=(),
                    answer_citation_hashes=(citation,), scores=(),
                    exact_result=SimpleNamespace(items=(item,)),
                )
                scan = Mock()
                records.scan_authorized_mail_observations = scan
                query = "ZX-421 audit"
                with patch("formowl_mail.query.source_evidence_double_check",
                           wraps=source_evidence_double_check) as shared_core:
                    result = handler({
                        "query_text": query, "requester_user_id": session.requester_user_id,
                        "workspace_id": session.workspace_id, "mail_import_session_id": selector,
                        "request_contract": {
                            "original_query_hash": sha256_json(query),
                            "query_class": "evidence_lookup", "source_family_scope": ["mail"],
                            "requested_fields": ["deadline", "owner"],
                            "maximum_claim_strength": "cited_evidence",
                        },
                    })
                scan.assert_not_called()
                self.assertEqual(result["status"], "ok")
                self.assertEqual(tuple(shared_core.call_args.kwargs["supported_requested_fields"]),
                                 ("deadline",))
                self.assertNotIn("mail_evidence_source_fallback_used", result["warnings"])
                coverage = result["requested_field_coverage"]
                self.assertEqual(coverage["requested_fields"], ["deadline", "owner"])
                self.assertEqual(coverage["supported_fields"], ["deadline"])
                self.assertEqual(coverage["missing_fields"], ["owner"])
                self.assertEqual(coverage["status"], "incomplete")
                self.assertFalse(coverage["absence_claim"])
                self.assertEqual(coverage["evidence_citation_hashes"], [citation])
                self.assertEqual(
                    coverage["request_contract_fingerprint"],
                    sha256_json(session.query.call_args.kwargs["request_contract"]),
                )
                self.assertEqual(
                    coverage["coverage_fingerprint"],
                    sha256_json({key: value for key, value in coverage.items()
                                 if key != "coverage_fingerprint"}),
                )

    def test_mail_unbound_structured_support_cannot_suppress_source_recheck(self) -> None:
        for structure, field, citation_bound, lineage_bound in (
            ("candidate_only", "deadline", True, True),
            ("source_provided", "owner", True, True),
            ("source_provided", "deadline", False, True),
            ("source_provided", "deadline", True, False),
        ):
            with self.subTest(structure=structure, field=field,
                              citation_bound=citation_bound, lineage_bound=lineage_bound):
                handler, session, records, selector, _, citation = self._revision_owned_mail_fixture(
                    complete=False, source_text="ZX-421 audit background.",
                )
                session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
                lineage = records.lineage(records.observation.observation_id).lineage_fingerprint
                item = SimpleNamespace(
                    structure_status=structure,
                    structured_values=((field, "", citation if citation_bound else sha256_json("unbound"),
                                        lineage if lineage_bound else sha256_json("unbound")),),
                    cited_observation_hashes=(citation,),
                )
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status="partial", query_class="evidence_lookup", warnings=(),
                    answer_citation_hashes=(citation,), scores=(),
                    exact_result=SimpleNamespace(items=(item,)),
                )
                scan = Mock(return_value=RevisionOwnedMailSourceScan(
                    (), 1, False, "deadline",
                ))
                records.scan_authorized_mail_observations = scan
                query = "ZX-421 audit"
                result = handler({
                    "query_text": query, "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id, "mail_import_session_id": selector,
                    "request_contract": {
                        "original_query_hash": sha256_json(query), "query_class": "evidence_lookup",
                        "source_family_scope": ["mail"], "requested_fields": ["deadline"],
                        "maximum_claim_strength": "cited_evidence",
                    },
                })
                scan.assert_called_once()
                self.assertNotEqual(result["status"], "not_found")
                self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])

    def test_mail_field_trigger_preserves_failure_exact_and_replan_exclusions(self) -> None:
        for status, query_class, warnings in (
            ("error", "evidence_lookup", ()),
            ("permission_denied", "evidence_lookup", ()),
            ("replan_required", "evidence_lookup", ()),
            ("partial", "exact_set_or_inventory", ()),
            ("partial", "evidence_lookup", ("exact_query_requires_structured_binding",)),
        ):
            with self.subTest(status=status, query_class=query_class, warnings=warnings):
                handler, session, records, selector, _, citation = self._revision_owned_mail_fixture(
                    source_text="ZX-421 audit background.",
                )
                session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status=status, query_class=query_class, warnings=warnings,
                    answer_citation_hashes=(citation,), scores=(), exact_result=None,
                )
                scan = Mock()
                records.scan_authorized_mail_observations = scan
                query = "ZX-421 audit"
                result = handler({
                    "query_text": query, "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id, "mail_import_session_id": selector,
                    "request_contract": {
                        "original_query_hash": sha256_json(query), "query_class": "evidence_lookup",
                        "source_family_scope": ["mail"], "requested_fields": ["deadline"],
                        "maximum_claim_strength": "cited_evidence",
                    },
                })
                scan.assert_not_called()
                self.assertNotIn("mail_evidence_source_fallback_used", result["warnings"])
                if status in ("error", "permission_denied"):
                    self.assertEqual(result["status"], status)

    def test_source_double_check_unavailable_or_zero_limit_is_pending_review(self) -> None:
        for limit, warning in (
            (1, "mail_evidence_source_fallback_unavailable"),
            (0, "mail_evidence_source_fallback_skipped_zero_limit"),
        ):
            with self.subTest(limit=limit):
                handler, session, records, selector, _, _ = self._revision_owned_mail_fixture()
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status="not_found",
                    warnings=(),
                    answer_citation_hashes=(),
                )
                scan = Mock()
                if limit == 0:
                    records.scan_authorized_mail_observations = scan
                result = handler(
                    {
                        "query_text": "audit approval",
                        "requester_user_id": session.requester_user_id,
                        "workspace_id": session.workspace_id,
                        "mail_import_session_id": selector,
                        "limit": limit,
                    }
                )
                self.assertEqual(result["status"], "pending_review")
                self.assertEqual(result["citations"], [])
                self.assertIn(warning, result["warnings"])
                scan.assert_not_called()

    def test_source_double_check_does_not_retry_replan_exact_or_failure(self) -> None:
        for status, query_class, warnings, expected in (
            ("error", "evidence_lookup", (), "error"),
            ("permission_denied", "evidence_lookup", (), "permission_denied"),
            ("replan_required", "evidence_lookup", (), "pending_review"),
            ("no_answer", "exact_set_or_inventory", (), "pending_review"),
            (
                "no_answer",
                "evidence_lookup",
                ("exact_query_requires_structured_binding",),
                "pending_review",
            ),
        ):
            with self.subTest(status=status, query_class=query_class, warnings=warnings):
                handler, session, records, selector, _, _ = self._revision_owned_mail_fixture()
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status=status,
                    query_class=query_class,
                    warnings=warnings,
                    answer_citation_hashes=(),
                )
                scan = Mock()
                records.scan_authorized_mail_observations = scan
                result = handler(
                    {
                        "query_text": "audit approval",
                        "requester_user_id": session.requester_user_id,
                        "workspace_id": session.workspace_id,
                        "mail_import_session_id": selector,
                    }
                )
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["citations"], [])
                scan.assert_not_called()
                if query_class == "exact_set_or_inventory" or warnings:
                    self.assertIn(
                        "mail_evidence_source_fallback_skipped_exact",
                        result["warnings"],
                    )
                elif status == "replan_required":
                    self.assertIn(
                        "mail_evidence_source_fallback_skipped_replan",
                        result["warnings"],
                    )

    def test_source_double_check_empty_result_requires_complete_scan_and_coverage(self) -> None:
        for coverage, complete, stop in (
            (True, True, None),
            (False, True, None),
            (True, False, "deadline"),
            (True, False, "observation_limit"),
        ):
            with self.subTest(coverage=coverage, complete=complete, stop=stop):
                handler, session, records, selector, other_selector, _ = (
                    self._revision_owned_mail_fixture(
                        complete=coverage,
                    )
                )
                session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status="partial",
                    warnings=("bounded_semantic_result",),
                    answer_citation_hashes=(),
                )
                scan = Mock(return_value=RevisionOwnedMailSourceScan((), 1, complete, stop))
                records.scan_authorized_mail_observations = scan
                result = handler(
                    {
                        "query_text": "audit approval",
                        "requester_user_id": session.requester_user_id,
                        "workspace_id": session.workspace_id,
                        "mail_import_session_id": selector,
                    }
                )
                self.assertEqual(
                    result["status"],
                    "not_found" if coverage and complete else "pending_review",
                )
                self.assertEqual(result["citations"], [])
                self.assertIn("bounded_semantic_result", result["warnings"])
                self.assertIn("mail_evidence_source_fallback_used", result["warnings"])
                if not complete:
                    self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])
                expected_scan_calls = 2 if complete else 1
                self.assertEqual(scan.call_count, expected_scan_calls)
                self.assertEqual(
                    [call.kwargs["mail_import_session_id"] for call in scan.call_args_list],
                    [selector] + ([other_selector] if complete else []),
                )

    def test_source_double_check_reader_overrun_cannot_claim_complete_no_match(self) -> None:
        handler, session, records, selector, _, _ = self._revision_owned_mail_fixture()
        session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="not_found",
            warnings=(),
            answer_citation_hashes=(),
        )
        clock = [10.0]

        def scan_source(**kwargs):
            clock[0] = kwargs["deadline_monotonic"] + 0.001
            return RevisionOwnedMailSourceScan((), 0, True)

        scan = Mock(side_effect=scan_source)
        records.scan_authorized_mail_observations = scan
        with patch("formowl_retrieval.gateway.time.monotonic", side_effect=lambda: clock[0]):
            result = handler(
                {
                    "query_text": "audit approval",
                    "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id,
                    "mail_import_session_id": selector,
                }
            )
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(result["citations"], [])
        self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])
        self.assertNotIn("mail_evidence_source_fallback_complete_no_match", result["warnings"])
        scan.assert_called_once()

    def test_revision_owned_mail_handler_falls_back_to_source_on_graph_no_hit(
        self,
    ) -> None:
        handler, session, records, selector, _other_selector, observation_hash = (
            self._revision_owned_mail_fixture(
                complete=False,
                source_text="劉一帆 project update",
                subject="劉一帆 project update",
            )
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="ok",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )

        def scan_source(**kwargs):
            self.assertTrue(kwargs["observation_callback"](records.observation, selector))
            return RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=1,
                complete=False,
                stop_reason="deadline",
            )

        records.scan_authorized_mail_observations = scan_source

        result = handler(
            {
                "query_text": "劉一帆",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(
            result["evidence_snippets"][0]["source_observation_hash"],
            observation_hash,
        )
        self.assertIn("mail_evidence_source_fallback_used", result["warnings"])
        self.assertIn(
            "mail_evidence_source_fallback_incomplete",
            result["warnings"],
        )
        self.assertIn("mail_evidence_coverage_incomplete", result["warnings"])

    def test_revision_owned_mail_fallback_uses_sealed_selector_without_rehydration(
        self,
    ) -> None:
        handler, session, records, selector, _other_selector, observation_hash = (
            self._revision_owned_mail_fixture(
                complete=False,
                source_text="劉一帆 project update",
                subject="劉一帆 project update",
            )
        )
        session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="not_found",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )

        clock = [10.0]
        selector_lookups: list[str] = []

        def selector_lookup(value: str) -> str:
            selector_lookups.append(value)
            # The duplicate lookup in the old projection path consumed the
            # 500 ms source-evidence phase before the citation was appended.
            clock[0] = 10.501
            return selector

        records.mail_import_session_id_for_observation = selector_lookup

        def scan_source(**kwargs):
            self.assertEqual(kwargs["mail_import_session_id"], selector)
            self.assertTrue(
                kwargs["observation_callback"](records.observation, selector)
            )
            return RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=1,
                complete=True,
            )

        records.scan_authorized_mail_observations = scan_source
        with patch(
            "formowl_retrieval.gateway.time.monotonic",
            side_effect=lambda: clock[0],
        ):
            result = handler(
                {
                    "query_text": "劉一帆",
                    "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id,
                    "session_id": "revision-session",
                    "mail_import_session_id": selector,
                }
            )

        self.assertEqual(selector_lookups, [])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(
            result["evidence_snippets"][0]["source_observation_hash"],
            observation_hash,
        )
        self.assertEqual(
            result["evidence_snippets"][0]["mail_import_session_id"],
            selector,
        )

    def test_revision_owned_mail_fallback_tries_each_authorized_selector_after_selected_no_match(
        self,
    ) -> None:
        handler, session, records, selector, other_selector, _observation_hash = (
            self._revision_owned_mail_fixture(
                complete=True,
                source_text="劉一帆 project update",
                subject="劉一帆 project update",
            )
        )
        session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="not_found",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )
        other_observation = replace(
            records.observation,
            observation_id="observation_mail_002",
            location={
                **records.observation.location,
                "message_occurrence_id": "message_occurrence_002",
            },
            payload={
                **records.observation.payload,
                "message_fingerprint": "sha256:" + ("5" * 64),
            },
        )
        other_hash = sha256_json(other_observation.to_dict())
        other_lineage = MailMessageOccurrenceLineage(
            source_observation_id=other_observation.observation_id,
            message_occurrence_id="message_occurrence_002",
        )
        observations_by_hash = {
            sha256_json(records.observation.to_dict()): records.observation,
            other_hash: other_observation,
        }
        records.observation_for_hash = observations_by_hash.get
        records.observation_hash = {
            records.observation.observation_id: sha256_json(records.observation.to_dict()),
            other_observation.observation_id: other_hash,
        }.get
        records.lineage = {
            records.observation.observation_id: records.lineage_value,
            other_observation.observation_id: other_lineage,
        }.get
        records.mail_import_session_id_for_observation = {
            records.observation.observation_id: selector,
            other_observation.observation_id: other_selector,
        }.get
        scan_calls: list[str] = []

        def scan_source(**kwargs):
            candidate_selector = kwargs["mail_import_session_id"]
            scan_calls.append(candidate_selector)
            if candidate_selector == selector:
                return RevisionOwnedMailSourceScan((), 0, True)
            self.assertEqual(candidate_selector, other_selector)
            self.assertTrue(
                kwargs["observation_callback"](other_observation, other_selector)
            )
            return RevisionOwnedMailSourceScan((), 1, True)

        records.scan_authorized_mail_observations = scan_source
        with patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0):
            result = handler(
                {
                    "query_text": "劉一帆",
                    "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id,
                    "session_id": "revision-session",
                    "mail_import_session_id": selector,
                }
            )

        self.assertEqual(scan_calls, [selector, other_selector])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mail_import_session_id"], other_selector)
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(
            result["evidence_snippets"][0]["source_observation_hash"],
            other_hash,
        )
        self.assertEqual(
            result["evidence_snippets"][0]["mail_import_session_id"],
            other_selector,
        )
        self.assertIn("mail_evidence_source_fallback_used", result["warnings"])

    def test_revision_owned_mail_fallback_is_generic_and_selector_bound(self) -> None:
        scenarios = (
            (
                "synthetic_cjk_selector_a",
                "整理周岑禾的設備維護信件",
                "周岑禾 設備維護排程已確認",
                "設備維護排程",
                ["周岑禾", "設備維護"],
                0,
            ),
            (
                "synthetic_cjk_selector_b",
                "整理林予安的會議安排信件",
                "林予安 會議安排時間已確認",
                "會議安排",
                ["林予安", "會議安排"],
                1,
            ),
            (
                "synthetic_latin",
                "Organize Mira Quill's project planning email",
                "Mira Quill project planning notes were circulated",
                "Project planning notes",
                ["Mira Quill", "project planning"],
                1,
            ),
        )
        unapproved_selector = "mailimport:" + ("6" * 64)
        for case_id, query_text, body, subject, required_terms, selector_index in scenarios:
            with self.subTest(case_id=case_id):
                handler, session, records, selector_a, selector_b, _ = (
                    self._revision_owned_mail_fixture(
                        complete=False,
                        source_text=body,
                        subject=subject,
                    )
                )
                selected_selector = (selector_a, selector_b)[selector_index]
                session.requester_user_id = "user_synthetic"
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status="not_found",
                    warnings=("graph_no_match",),
                    answer_citation_hashes=(),
                    scores=(),
                )
                scanned_selectors: list[str] = []

                def scan_source(**kwargs):
                    scanned_selectors.append(kwargs["mail_import_session_id"])
                    self.assertEqual(kwargs["mail_import_session_id"], selected_selector)
                    kwargs["observation_callback"](records.observation, selected_selector)
                    return RevisionOwnedMailSourceScan((), 1, False, "deadline")

                records.scan_authorized_mail_observations = scan_source
                request = {
                    "query_text": query_text,
                    "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id,
                    "mail_import_session_id": selected_selector,
                    "required_terms": required_terms,
                    "limit": 1,
                }
                with patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0):
                    result = handler(request)

                self.assertEqual(session.query.call_count, 1)
                self.assertEqual(
                    session.query.call_args.kwargs["request_contract"]["source_family_scope"],
                    ["mail"],
                )
                self.assertEqual(scanned_selectors, [selected_selector])
                self.assertEqual(result["status"], "ok")
                self.assertEqual(len(result["citations"]), 1)
                self.assertEqual(
                    (
                        result["citations"][0]["source_observation_id"],
                        result["citations"][0]["mail_import_session_id"],
                        result["evidence_snippets"][0]["source_observation_hash"],
                    ),
                    (
                        records.observation.observation_id,
                        selected_selector,
                        sha256_json(records.observation.to_dict()),
                    ),
                )
                self.assertTrue(
                    {
                        "graph_no_match",
                        "mail_evidence_source_fallback_used",
                        "mail_evidence_source_fallback_incomplete",
                        "mail_evidence_coverage_incomplete",
                    }.issubset(result["warnings"])
                )

                denied = handler(
                    {
                        **request,
                        "mail_import_session_id": unapproved_selector,
                    }
                )
                self.assertEqual(denied["status"], "permission_denied")
                self.assertIn("mail_evidence_selector_denied", denied["warnings"])
                self.assertEqual(session.query.call_count, 1)
                self.assertEqual(scanned_selectors, [selected_selector])

    def test_revision_owned_mail_relevance_requires_all_grounded_terms(self) -> None:
        scenarios = (
            (
                "cjk_zhou",
                "查找周岑禾的設備維護信件",
                ["周岑禾", "設備維護"],
                "林予安 設備維護排程已確認",
                "周岑禾 設備維護排程已確認",
                "設備維護排程",
            ),
            (
                "cjk_lin",
                "查找林予安的會議安排信件",
                ["林予安", "會議安排"],
                "周岑禾 會議安排時間已確認",
                "林予安 會議安排時間已確認",
                "會議安排",
            ),
            (
                "legacy_all_query_terms",
                "ZX-421 audit approval",
                None,
                "ZX-421 audit only",
                "ZX-421 audit approval confirmed",
                "ZX-421 audit approval",
            ),
        )
        for case_id, query_text, required_terms, decoy_text, positive_text, subject in scenarios:
            with self.subTest(case_id=case_id):
                handler, session, records, selector, _, _ = self._revision_owned_mail_fixture(
                    complete=False,
                    source_text=positive_text,
                    subject=subject,
                )
                session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
                session.requester_user_id = "user_synthetic"
                base = records.observation
                decoy = replace(
                    base,
                    observation_id=f"observation_{case_id}_decoy",
                    text=decoy_text,
                    payload={**base.payload, "subject": decoy_text},
                )
                positive = replace(
                    base,
                    observation_id=f"observation_{case_id}_positive",
                    text=positive_text,
                    payload={**base.payload, "subject": subject},
                )
                observations = (decoy, positive)
                hashes = {sha256_json(item.to_dict()): item for item in observations}
                hash_by_id = {
                    item.observation_id: observation_hash
                    for observation_hash, item in hashes.items()
                }
                lineage_by_id = {
                    item.observation_id: source_occurrence_lineage_from_observation(
                        item,
                        authorized_source=session.authorized_source,
                    )
                    for item in observations
                }
                records.observation_for_hash = lambda value: hashes.get(value)
                records.observation_hash = lambda value: hash_by_id.get(value)
                records.lineage = lambda value: lineage_by_id.get(value)
                records.mail_import_session_id_for_observation = lambda _value: selector
                decoy_hash = sha256_json(decoy.to_dict())
                positive_hash = sha256_json(positive.to_dict())
                session.query.side_effect = None
                session.query.return_value = SimpleNamespace(
                    status="ok",
                    warnings=(),
                    answer_citation_hashes=(decoy_hash,),
                    scores=(),
                )
                scanned_selectors: list[str] = []

                def scan_source(**kwargs):
                    scanned_selectors.append(kwargs["mail_import_session_id"])
                    self.assertEqual(kwargs["mail_import_session_id"], selector)
                    callback = kwargs["observation_callback"]
                    self.assertTrue(callback(decoy, selector))
                    self.assertFalse(callback(positive, selector))
                    return RevisionOwnedMailSourceScan((), 2, False, "callback")

                records.scan_authorized_mail_observations = scan_source
                request = {
                    "query_text": query_text,
                    "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id,
                    "mail_import_session_id": selector,
                    "limit": 1,
                }
                if required_terms is not None:
                    request["required_terms"] = required_terms
                with patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0):
                    result = handler(request)

                self.assertEqual(scanned_selectors, [selector])
                self.assertEqual(
                    [item["source_observation_hash"] for item in result["evidence_snippets"]],
                    [positive_hash],
                )
                self.assertEqual(
                    [item["source_observation_id"] for item in result["citations"]],
                    [positive.observation_id],
                )
                self.assertEqual(
                    [item["mail_import_session_id"] for item in result["citations"]],
                    [selector],
                )
                self.assertNotIn(
                    decoy.observation_id,
                    {item["source_observation_id"] for item in result["citations"]},
                )
                self.assertIn("mail_evidence_source_fallback_used", result["warnings"])
                self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])

    def test_revision_owned_mail_initial_citation_accepts_all_required_terms(self) -> None:
        handler, session, records, selector, _, observation_hash = (
            self._revision_owned_mail_fixture(
                complete=False,
                source_text="周岑禾 設備維護排程已確認",
                subject="設備維護排程",
            )
        )
        session.tokenizer_profile = _contract_only_runtime().tokenizer_profile
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="ok",
            warnings=(),
            answer_citation_hashes=(observation_hash,),
            scores=(),
        )
        scan = Mock()
        records.scan_authorized_mail_observations = scan

        result = handler(
            {
                "query_text": "查找周岑禾的設備維護信件",
                "required_terms": ["周岑禾", "設備維護"],
                "requester_user_id": session.requester_user_id,
                "workspace_id": session.workspace_id,
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(
            result["citations"][0]["source_observation_id"],
            records.observation.observation_id,
        )
        self.assertEqual(
            result["evidence_snippets"][0]["source_observation_hash"],
            observation_hash,
        )
        scan.assert_not_called()

    def test_revision_owned_mail_fallback_rejects_same_scope_wrong_participant(
        self,
    ) -> None:
        handler, session, records, selector, _, _ = self._revision_owned_mail_fixture(
            complete=False,
            source_text="林予安 設備維護排程已確認",
            subject="林予安 設備維護排程",
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="not_found",
            warnings=("graph_no_match",),
            answer_citation_hashes=(),
            scores=(),
        )

        def scan_same_selector(**kwargs):
            self.assertEqual(kwargs["mail_import_session_id"], selector)
            self.assertTrue(
                kwargs["observation_callback"](records.observation, selector)
            )
            return RevisionOwnedMailSourceScan((), 1, False, "deadline")

        records.scan_authorized_mail_observations = scan_same_selector
        result = handler(
            {
                "query_text": "查找周岑禾的設備維護信件",
                "required_terms": ["周岑禾", "設備維護"],
                "requester_user_id": session.requester_user_id,
                "workspace_id": session.workspace_id,
                "mail_import_session_id": selector,
                "limit": 1,
            }
        )

        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["evidence_snippets"], [])
        self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])

    def test_relation_planning_requires_bound_paths_in_real_text_session(self) -> None:
        temp_dir = _paths.fresh_test_dir("issue56-relation-text-capabilities")
        source_text = "# Synthetic collaboration\n周岑禾與林予安共同審查同一份文件。\n"
        asset, extraction = _registered_text_revision_fixture(
            temp_dir,
            source_text=source_text,
        )
        observations = tuple(extraction.observations)
        registered_binding = {
            "asset_id": asset.asset_id,
            "asset_content_hash": asset.content_hash,
            "extractor_run_id": extraction.extractor_run.extractor_run_id,
            "observation_hashes": sorted(sha256_json(item.to_dict()) for item in observations),
        }
        source_authority_fingerprint = sha256_json(registered_binding)
        runtime = _contract_only_runtime()
        with (
            patch.object(
                issue56_sealed_source,
                "load_issue56_target_runtime_components",
                return_value=runtime,
            ),
            patch.object(
                hybrid,
                "_load_pinned_issue56_runtime_components",
                return_value=runtime,
            ),
        ):
            revision = build_issue56_ingestion_revision(
                observations=observations,
                bundles=(),
                source_binding={
                    "source_authority_fingerprint": source_authority_fingerprint,
                    "registered_asset_revision_fingerprint": source_authority_fingerprint,
                },
                requester_user_id=asset.owner_user_id,
                workspace_id=asset.workspace_id,
                source_authority_fingerprint=source_authority_fingerprint,
            )

        query_text = "周岑禾與林予安的關係"
        request_contract = {
            "original_query_hash": sha256_json(query_text),
            "query_class": "relation_reasoning",
            "source_family_scope": ["document_text"],
            "requested_fields": [],
            "maximum_claim_strength": "bounded_relation",
        }
        self.assertEqual(
            semantic_plan.deterministic_query_class(query_text),
            "relation_reasoning",
        )
        self.assertEqual(
            revision.session.authorized_source.source_kind,
            semantic_plan.AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "relation reasoning requires bounded paths",
        ):
            revision.session.query(
                query_text=query_text,
                request_contract=request_contract,
                effective_graph_view=revision.effective_graph_view,
                allowed_relation_types=(),
            )

        self.assertIn(
            "co_occurs_with",
            {edge.relation_type for edge in revision.effective_graph_view.visible_edges},
        )
        graph_revision_id = revision.effective_graph_view.canonical_graph_revision_id
        result = revision.session.query(
            query_text=query_text,
            request_contract=request_contract,
            effective_graph_view=revision.effective_graph_view,
            allowed_relation_types=("co_occurs_with",),
        )
        self.assertEqual(result.query_class, "relation_reasoning")
        self.assertEqual(result.claim_strength, "bounded_relation")
        self.assertEqual(
            revision.effective_graph_view.canonical_graph_revision_id,
            graph_revision_id,
        )

    def test_revision_owned_mail_composition_threads_bound_relation_capabilities(
        self,
    ) -> None:
        permission_scope = PermissionScope.project("project_formowl")
        observation = Observation(
            observation_id="observation_synthetic_mail_relation",
            extractor_run_id="extractor_synthetic_mail_relation",
            observation_type="email_body_segment",
            modality="mail",
            location={
                "archive_id": "archive_synthetic",
                "mailbox_id": "mailbox_synthetic",
                "message_occurrence_id": "occurrence_synthetic_relation",
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-09-01T00:00:00+00:00",
            asset_id="asset_synthetic_mail_relation",
            text="周岑禾與林予安共同審查同一份文件",
            payload={
                "message_fingerprint": "sha256:" + ("a" * 64),
                "subject": "周岑禾與林予安的文件審查",
            },
        )
        source_authority_fingerprint = sha256_json(
            {
                "asset_id": observation.asset_id,
                "observation_hash": sha256_json(observation.to_dict()),
            }
        )
        selector = "mailimport:" + ("b" * 64)
        runtime = _contract_only_runtime()
        with (
            patch.object(
                issue56_sealed_source,
                "load_issue56_target_runtime_components",
                return_value=runtime,
            ),
            patch.object(
                hybrid,
                "_load_pinned_issue56_runtime_components",
                return_value=runtime,
            ),
        ):
            revision = build_issue56_ingestion_revision(
                observations=(observation,),
                bundles=(),
                source_binding={
                    "source_authority_fingerprint": source_authority_fingerprint,
                    "extraction_coverage": {
                        "source_completeness_certified": False,
                    },
                },
                requester_user_id=loader.APPROVER_ACTOR,
                workspace_id=loader.WORKSPACE_ID,
                source_authority_fingerprint=source_authority_fingerprint,
            )

        observation_hash = sha256_json(observation.to_dict())
        lineage = source_occurrence_lineage_from_observation(
            observation,
            authorized_source=revision.session.authorized_source,
        )
        source_scan = Mock(
            return_value=RevisionOwnedMailSourceScan((), 0, True)
        )
        source_records = SimpleNamespace(
            authorized_mail_import_session_ids=(selector,),
            observation_for_hash=lambda value: (
                observation if value == observation_hash else None
            ),
            observation_hash=lambda value: (
                observation_hash
                if value == observation.observation_id
                else None
            ),
            lineage=lambda value: lineage,
            mail_import_session_id_for_observation=lambda value: (
                selector if value == observation.observation_id else None
            ),
            scan_authorized_mail_observations=source_scan,
        )
        revision = replace(revision, source_records=source_records)
        retrieval_handler, mail_handler = (
            loader.build_issue56_production_semantic_handlers(
                ingestion_revision=revision,
            )
        )
        self.assertIsNotNone(mail_handler)
        allowed_relation_types = tuple(
            sorted(
                {
                    edge.relation_type
                    for edge in revision.effective_graph_view.visible_edges
                }
            )
        )
        self.assertTrue(allowed_relation_types)
        self.assertEqual(
            retrieval_handler._issue56_allowed_relation_types,
            allowed_relation_types,
        )

        real_query = hybrid.AuthorizedSemanticMailSession.query
        query_calls = []

        def run_real_query(bound_session, **kwargs):
            query_calls.append(kwargs)
            return real_query(bound_session, **kwargs)

        request = {
            "query_text": "周岑禾與林予安的關係",
            "requester_user_id": revision.session.requester_user_id,
            "workspace_id": revision.session.workspace_id,
            "mail_import_session_id": selector,
        }
        assert mail_handler is not None
        real_route = hybrid.route_semantic_query
        validated_plans = []

        class _PlanValidated(Exception):
            pass

        def validate_then_stop(**kwargs):
            plan = real_route(**kwargs)
            validated_plans.append((kwargs, plan))
            raise _PlanValidated

        with patch.object(
            hybrid.AuthorizedSemanticMailSession,
            "query",
            autospec=True,
            side_effect=run_real_query,
        ):
            with patch.object(
                hybrid,
                "route_semantic_query",
                side_effect=validate_then_stop,
            ):
                with self.assertRaises(_PlanValidated):
                    mail_handler(request)
            self.assertEqual(len(query_calls), 1)
            self.assertEqual(
                query_calls[-1]["request_contract"]["query_class"],
                "relation_reasoning",
            )
            self.assertEqual(
                query_calls[-1]["allowed_relation_types"],
                allowed_relation_types,
            )
            self.assertEqual(len(validated_plans), 1)
            self.assertEqual(
                validated_plans[0][1].query_class,
                "relation_reasoning",
            )
            self.assertEqual(
                validated_plans[0][1].allowed_paths,
                tuple((relation_type, "out") for relation_type in allowed_relation_types),
            )

            source_scan.reset_mock()
            exact_result = mail_handler(
                {
                    **request,
                    "query_text": "列出周岑禾與林予安的全部信件",
                }
            )
            self.assertEqual(
                query_calls[-1]["request_contract"]["query_class"],
                "exact_set_or_inventory",
            )
            self.assertEqual(
                query_calls[-1]["allowed_relation_types"],
                allowed_relation_types,
            )
            self.assertEqual(exact_result["status"], "pending_review")
            self.assertEqual(exact_result["citations"], [])
            self.assertIn(
                "exact_query_requires_structured_binding",
                exact_result["warnings"],
            )
            source_scan.assert_not_called()

            source_scan.reset_mock()
            no_capability_handler = (
                build_revision_owned_mail_evidence_query_handler(
                    session=revision.session,
                    effective_graph_view=revision.effective_graph_view,
                    source_records=source_records,
                    safe_binding=revision.safe_binding,
                    allowed_relation_types=(),
                )
            )
            with self.assertRaisesRegex(
                ContractValidationError,
                "relation reasoning requires bounded paths",
            ):
                no_capability_handler(request)
            source_scan.assert_not_called()

        plan = semantic_plan.route_semantic_query(
            query_text=request["query_text"],
            requester_user_id=revision.session.requester_user_id,
            workspace_id=revision.session.workspace_id,
            source_scope_ids=revision.session.authorized_source_scope_ids,
            effective_graph_view=revision.effective_graph_view,
            allowed_relation_types=allowed_relation_types,
            authorized_source=revision.session.authorized_source,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "semantic query contains an unsupported hop",
        ):
            semantic_plan.validate_semantic_query_plan(
                replace(
                    plan,
                    allowed_paths=(("unbounded_association", "out"),),
                ),
                effective_graph_view=revision.effective_graph_view,
                authorized_workspace_id=revision.session.workspace_id,
                authorized_source_scope_ids=(
                    revision.session.authorized_source_scope_ids
                ),
                supported_relation_types=allowed_relation_types,
                authorized_source=revision.session.authorized_source,
            )

    def test_revision_owned_mail_fallback_ignores_inventory_without_lineage(
        self,
    ) -> None:
        handler, session, records, selector, _other_selector, observation_hash = (
            self._revision_owned_mail_fixture(complete=False)
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="ok",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )
        inventory_observation = Observation(
            observation_id="observation_mail_thread_001",
            extractor_run_id="extractor_mail_001",
            observation_type="email_thread",
            modality="mail",
            location={"thread_id": "thread_001"},
            confidence=1.0,
            permission_scope=records.observation.permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id=records.observation.asset_id,
            text="audit approval",
            payload={"thread_id": "thread_001"},
        )

        def scan_source(**kwargs):
            callback = kwargs["observation_callback"]
            self.assertTrue(callback(inventory_observation, selector))
            self.assertTrue(callback(records.observation, selector))
            return RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=2,
                complete=False,
                stop_reason="deadline",
            )

        records.scan_authorized_mail_observations = scan_source
        result = handler(
            {
                "query_text": "audit approval",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(
            result["evidence_snippets"][0]["source_observation_hash"],
            observation_hash,
        )

    def test_revision_owned_mail_fallback_consumes_returned_supported_observation(
        self,
    ) -> None:
        handler, session, records, selector, _other_selector, observation_hash = (
            self._revision_owned_mail_fixture(
                complete=False,
                source_text="劉一帆 project update",
                subject="劉一帆 project update",
            )
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="ok",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )

        # A bounded authorized reader may return its selected batch instead of
        # invoking the optional callback.  The handler must still run the same
        # matcher/lineage/citation path exactly once.
        records.scan_authorized_mail_observations = lambda **kwargs: (
            RevisionOwnedMailSourceScan(
                observations=((records.observation, selector),),
                scanned_observation_count=1,
                complete=False,
                stop_reason="deadline",
            )
        )

        result = handler(
            {
                "query_text": "劉一帆",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(
            result["evidence_snippets"][0]["source_observation_hash"],
            observation_hash,
        )
        self.assertIn("mail_evidence_source_fallback_used", result["warnings"])
        self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])

    def test_revision_source_reader_filters_inventory_reference_before_lineage_callback(
        self,
    ) -> None:
        permission_scope = PermissionScope.project("project_formowl")
        valid_observation = Observation(
            observation_id="observation_mail_body_001",
            extractor_run_id="extractor_mail_001",
            observation_type="email_body_segment",
            modality="mail",
            location={"message_occurrence_id": "message_occurrence_001"},
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id="asset_mail_001",
            text="audit approval",
            payload={"message_occurrence_id": "message_occurrence_001",
                     "message_fingerprint": "sha256:" + "1" * 64},
        )
        inventory_observation = Observation(
            observation_id="observation_mail_folder_001",
            extractor_run_id="extractor_mail_001",
            observation_type="mail_folder_occurrence",
            modality="mail",
            location={"folder_index": 1},
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id="asset_mail_001",
            text="audit approval",
            payload={"folder_label": "audit approval"},
        )
        source_observations = {
            item.observation_id: item
            for item in (inventory_observation, valid_observation)
        }
        job_fingerprint = "sha256:" + ("e" * 64)
        asset = SimpleNamespace(
            source_ref={
                "source_system": "formowl_upload_session",
                "source_type": "mail_archive",
                "source_id": "upload-session-001",
                "source_key": "upload-session-001",
            },
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            lifecycle_state="active",
            asset_id="asset_mail_001",
            content_hash="sha256:" + ("a" * 64),
        )

        def load_observation(
            observation_id,
            *,
            expected_observation_hash,
            expected_job_fingerprint,
        ):
            observation = source_observations[observation_id]
            if (
                expected_job_fingerprint != job_fingerprint
                or expected_observation_hash != sha256_json(observation.to_dict())
            ):
                raise ContractValidationError("fixture source binding mismatch")
            return observation

        authority = SimpleNamespace(
            asset=asset,
            job_fingerprint=job_fingerprint,
            permission_scope=permission_scope.to_dict(),
            load_indexed_observation=Mock(side_effect=load_observation),
            open_reader=Mock(side_effect=AssertionError("unbound reader must not be used")),
        )
        records = IngestionRevisionSourceRecords(
            runtime_store=SimpleNamespace(workspace_id="workspace_formowl"),
            job_authorities=(authority,),
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            observation_references=[
                [0, item.observation_id, sha256_json(item.to_dict())]
                for item in (inventory_observation, valid_observation)
            ],
        )
        callback = Mock(return_value=True)

        result = records.scan_authorized_mail_observations(
            max_observations=8,
            observation_callback=callback,
        )

        self.assertEqual(
            REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES,
            {"email_body_segment", "email_message", "email_header"},
        )
        self.assertEqual(result.scanned_observation_count, 2)
        self.assertTrue(result.complete)
        callback.assert_called_once_with(
            valid_observation,
            records.authorized_mail_import_session_ids[0],
        )
        authority.open_reader.assert_not_called()

    def test_document_reader_skips_same_authority_non_text_references(self) -> None:
        permission_scope = PermissionScope.project("project_formowl")
        non_text_observation = Observation(
            observation_id="observation_document_table_001",
            extractor_run_id="extractor_text_001",
            observation_type="table_row",
            modality="document",
            location={"row": 1},
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id="asset_text_001",
            text="unrelated row",
            payload={},
        )
        paragraph = Observation(
            observation_id="observation_document_paragraph_001",
            extractor_run_id="extractor_text_001",
            observation_type="paragraph",
            modality="text",
            location={"line_start": 1, "line_end": 1},
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id="asset_text_001",
            text="written owner approval",
            payload={},
        )
        observations = {
            item.observation_id: item
            for item in (non_text_observation, paragraph)
        }
        job_fingerprint = "sha256:" + ("f" * 64)
        asset = SimpleNamespace(
            source_ref={
                "source_system": "local",
                "source_type": "file",
                "source_id": "acceptance.md",
                "source_key": "acceptance.md",
            },
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            lifecycle_state="active",
            asset_id="asset_text_001",
            content_hash="sha256:" + ("a" * 64),
        )

        def load_observation(
            observation_id,
            *,
            expected_observation_hash,
            expected_job_fingerprint,
        ):
            observation = observations[observation_id]
            if (
                expected_job_fingerprint != job_fingerprint
                or expected_observation_hash != sha256_json(observation.to_dict())
            ):
                raise ContractValidationError("fixture source binding mismatch")
            return observation

        authority = SimpleNamespace(
            asset=asset,
            job_fingerprint=job_fingerprint,
            permission_scope=permission_scope.to_dict(),
            load_indexed_observation=Mock(side_effect=load_observation),
        )
        records = IngestionRevisionSourceRecords(
            runtime_store=SimpleNamespace(workspace_id="workspace_formowl"),
            job_authorities=(authority,),
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            observation_references=[
                [0, item.observation_id, sha256_json(item.to_dict())]
                for item in (non_text_observation, paragraph)
            ],
        )
        callback = Mock(return_value=True)

        result = records.scan_authorized_observations(
            source_family="document_text",
            source_scope_ids=(permission_scope.scope_id,),
            max_observations=2,
            observation_callback=callback,
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.scanned_observation_count, 2)
        callback.assert_called_once_with(paragraph, permission_scope.scope_id)

    def test_revision_source_reader_uses_sealed_refs_without_retrieval_helpers(
        self,
    ) -> None:
        permission_scope = PermissionScope.project("project_formowl")
        body_observation = Observation(
            observation_id="observation_mail_body_indexed_001",
            extractor_run_id="extractor_mail_001",
            observation_type="email_body_segment",
            modality="mail",
            location={"message_occurrence_id": "message_occurrence_indexed_001"},
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id="asset_mail_indexed_001",
            text="audit approval",
            payload={"message_fingerprint": "sha256:" + ("b" * 64)},
        )
        body_hash = sha256_json(body_observation.to_dict())
        asset = SimpleNamespace(
            source_ref={
                "source_system": "formowl_upload_session",
                "source_type": "mail_archive",
                "source_id": "upload-session-indexed-001",
                "source_key": "upload-session-indexed-001",
            },
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            lifecycle_state="active",
            asset_id="asset_mail_indexed_001",
            content_hash="sha256:" + ("c" * 64),
        )
        job_fingerprint = "sha256:" + ("d" * 64)
        authority = SimpleNamespace(
            asset=asset,
            job_fingerprint=job_fingerprint,
            permission_scope=permission_scope.to_dict(),
            load_indexed_observation=Mock(return_value=body_observation),
            open_reader=Mock(side_effect=AssertionError("unbound reader must not be used")),
        )
        runtime_store = SimpleNamespace(
            workspace_id="workspace_formowl",
            iter_helpers_for_source_family=Mock(
                side_effect=AssertionError("retrieval helper scan must not run")
            ),
            iter_helpers=Mock(side_effect=AssertionError("helper scan must not run")),
        )
        references = [[0, body_observation.observation_id, body_hash]]
        records = IngestionRevisionSourceRecords(
            runtime_store=runtime_store,
            job_authorities=(authority,),
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            observation_references=references,
        )
        self.assertIs(records.observation_references, references)
        selector = records.authorized_mail_import_session_ids[0]
        callback = Mock(return_value=True)

        with patch("formowl_mail.issue56_sealed_source.time.monotonic", return_value=10.0):
            result = records.scan_authorized_mail_observations(
                max_observations=_REVISION_SOURCE_FALLBACK_OBSERVATION_LIMIT,
                deadline_monotonic=10.0 + _REVISION_SOURCE_FALLBACK_TIME_BUDGET_MS / 1000,
                mail_import_session_id=selector,
                observation_callback=callback,
            )

        self.assertEqual(result.scanned_observation_count, 1)
        self.assertTrue(result.complete)
        self.assertIsNone(result.stop_reason)
        callback.assert_called_once_with(body_observation, selector)
        authority.open_reader.assert_not_called()
        authority.load_indexed_observation.assert_called_once_with(
            body_observation.observation_id,
            expected_observation_hash=body_hash,
            expected_job_fingerprint=job_fingerprint,
        )
        runtime_store.iter_helpers_for_source_family.assert_not_called()
        runtime_store.iter_helpers.assert_not_called()

        authority.load_indexed_observation.reset_mock()
        wrong_selector = records.scan_authorized_mail_observations(
            max_observations=_REVISION_SOURCE_FALLBACK_OBSERVATION_LIMIT,
            mail_import_session_id="mailimport:" + ("0" * 64),
        )
        self.assertTrue(wrong_selector.complete)
        self.assertEqual(wrong_selector.scanned_observation_count, 0)
        authority.load_indexed_observation.assert_not_called()

        with patch("formowl_mail.issue56_sealed_source.time.monotonic", return_value=20.0):
            expired = records.scan_authorized_mail_observations(
                max_observations=_REVISION_SOURCE_FALLBACK_OBSERVATION_LIMIT,
                deadline_monotonic=10.0,
                mail_import_session_id=selector,
            )
        self.assertFalse(expired.complete)
        self.assertEqual(expired.stop_reason, "deadline")
        authority.load_indexed_observation.assert_not_called()

        records.observation_references = None
        unavailable = records.scan_authorized_mail_observations(
            max_observations=_REVISION_SOURCE_FALLBACK_OBSERVATION_LIMIT,
            mail_import_session_id=selector,
        )
        self.assertFalse(unavailable.complete)
        self.assertEqual(unavailable.stop_reason, "source_reference_unavailable")
        authority.load_indexed_observation.assert_not_called()

        records.observation_references = [references[0], references[0]]
        capped = records.scan_authorized_mail_observations(
            max_observations=1,
            mail_import_session_id=selector,
        )
        self.assertFalse(capped.complete)
        self.assertEqual(capped.stop_reason, "observation_limit")
        self.assertEqual(capped.scanned_observation_count, 1)
        authority.load_indexed_observation.assert_called_once_with(
            body_observation.observation_id,
            expected_observation_hash=body_hash,
            expected_job_fingerprint=job_fingerprint,
        )

        records.observation_references = references
        authority.load_indexed_observation.reset_mock()
        callback.reset_mock()
        # Drive time from the work itself instead of a fixed monotonic call
        # sequence: the deadline expires while the indexed observation loads.
        clock = [10.0]

        def load_then_expire(*args, **kwargs):
            clock[0] = 11.0
            return body_observation

        authority.load_indexed_observation.side_effect = load_then_expire
        with patch(
            "formowl_mail.issue56_sealed_source.time.monotonic",
            side_effect=lambda: clock[0],
        ):
            overrun = records.scan_authorized_mail_observations(
                max_observations=1,
                deadline_monotonic=10.5,
                mail_import_session_id=selector,
                observation_callback=callback,
            )
        self.assertFalse(overrun.complete)
        self.assertEqual(overrun.stop_reason, "deadline")
        callback.assert_not_called()
        authority.load_indexed_observation.assert_called_once()

        authority.load_indexed_observation.reset_mock()
        authority.load_indexed_observation.side_effect = None
        authority.load_indexed_observation.return_value = body_observation
        callback.reset_mock()
        # The deadline expires while the callback consumes the observation.
        clock = [10.0]

        def consume_then_expire(*args, **kwargs):
            clock[0] = 11.0
            return True

        callback.side_effect = consume_then_expire
        with patch(
            "formowl_mail.issue56_sealed_source.time.monotonic",
            side_effect=lambda: clock[0],
        ):
            callback_overrun = records.scan_authorized_mail_observations(
                max_observations=1,
                deadline_monotonic=10.5,
                mail_import_session_id=selector,
                observation_callback=callback,
            )
        self.assertFalse(callback_overrun.complete)
        self.assertEqual(callback_overrun.stop_reason, "deadline")
        callback.assert_called_once_with(body_observation, selector)
        authority.load_indexed_observation.assert_called_once()

    def test_revision_owned_mail_fallback_rejects_supported_observation_without_lineage(
        self,
    ) -> None:
        handler, session, records, selector, other_selector, _observation_hash = (
            self._revision_owned_mail_fixture(complete=False)
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="ok",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )
        invalid_observation = Observation(
            observation_id="observation_mail_body_missing_lineage",
            extractor_run_id="extractor_mail_001",
            observation_type="email_body_segment",
            modality="mail",
            location={"body_segment_index": 1},
            confidence=1.0,
            permission_scope=records.observation.permission_scope,
            created_at="2026-08-20T09:00:00+00:00",
            asset_id=records.observation.asset_id,
            text="audit approval",
            payload={"subject": "audit approval"},
        )

        def scan_source(**kwargs):
            kwargs["observation_callback"](invalid_observation, selector)

        records.scan_authorized_mail_observations = scan_source
        with self.assertRaisesRegex(
            ContractValidationError,
            "mail source occurrence lineage is missing",
        ):
            handler(
                {
                    "query_text": "audit approval",
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_formowl",
                    "session_id": "revision-session",
                    "mail_import_session_id": selector,
                }
            )

    def test_revision_owned_mail_result_round_trips_as_successful_mcp_payload(self) -> None:
        handler, session, records, selector, _other_selector, observation_hash = (
            self._revision_owned_mail_fixture(
                complete=False,
                source_text="劉一帆 project update",
                subject="劉一帆 project update",
            )
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="ok",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )

        def scan_source(**kwargs):
            self.assertTrue(kwargs["observation_callback"](records.observation, selector))
            return RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=1,
                complete=False,
                stop_reason="deadline",
            )

        records.scan_authorized_mail_observations = scan_source
        gateway = SemanticMcpGateway(mail_evidence_handler=handler)
        envelope = gateway.dispatch_tool(
            "query_mail_evidence",
            {
                "query_text": "劉一帆",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            },
        )

        validate_public_gateway_payload(envelope)
        self.assertEqual(envelope["status"], "ok")
        data = envelope["data"]
        self.assertEqual(data["status"], "ok")
        self.assertEqual(len(data["citations"]), 1)
        self.assertEqual(
            data["evidence_snippets"][0]["source_observation_hash"],
            observation_hash,
        )
        strict_result = _successful_tool_result(envelope)
        self.assertFalse(strict_result.isError)

    def test_revision_owned_mail_source_fallback_reserves_time_after_slow_graph_query(
        self,
    ) -> None:
        handler, session, records, selector, _other_selector, observation_hash = (
            self._revision_owned_mail_fixture(
                complete=False,
                source_text="劉一帆 project update",
                subject="劉一帆 project update",
            )
        )
        clock = [0.0]

        def slow_graph_query(**kwargs):
            query_budget_ms = kwargs["limits"].max_time_budget_ms
            self.assertEqual(query_budget_ms, _REVISION_SOURCE_QUERY_TIME_BUDGET_MS)
            clock[0] = (query_budget_ms + 100) / 1000
            self.assertLess(
                clock[0],
                _REVISION_SOURCE_REQUEST_TIME_BUDGET_MS / 1000,
            )
            return SimpleNamespace(
                status="ok",
                warnings=(),
                answer_citation_hashes=(),
                scores=(),
            )

        session.query.side_effect = slow_graph_query

        def scan_source(**kwargs):
            self.assertEqual(
                kwargs["mail_import_session_id"],
                selector,
            )
            self.assertGreater(
                kwargs["deadline_monotonic"],
                clock[0],
            )
            self.assertTrue(kwargs["observation_callback"](records.observation, selector))
            return RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=1,
                complete=False,
                stop_reason="deadline",
            )

        records.scan_authorized_mail_observations = scan_source
        with patch(
            "formowl_retrieval.gateway.time.monotonic",
            side_effect=lambda: clock[0],
        ):
            result = handler(
                {
                    "query_text": "劉一帆",
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_formowl",
                    "session_id": "revision-session",
                    "mail_import_session_id": selector,
                }
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(
            result["evidence_snippets"][0]["source_observation_hash"],
            observation_hash,
        )
        self.assertIn("mail_evidence_source_fallback_incomplete", result["warnings"])

    def test_revision_owned_mail_source_fallback_binds_selector_before_scan(
        self,
    ) -> None:
        handler, session, records, selector, other_selector, _observation_hash = (
            self._revision_owned_mail_fixture(complete=False)
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="ok",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )
        scan = Mock(
            return_value=RevisionOwnedMailSourceScan(
                observations=(),
                scanned_observation_count=0,
                complete=True,
            )
        )
        records.scan_authorized_mail_observations = scan

        handler(
            {
                "query_text": "劉一帆",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(
            [call.kwargs["mail_import_session_id"] for call in scan.call_args_list],
            [selector, other_selector],
        )

    def test_revision_owned_mail_handler_does_not_fallback_after_permission_denial(
        self,
    ) -> None:
        handler, session, records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture(complete=False)
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="permission_denied",
            warnings=("mail_evidence_permission_denied",),
            answer_citation_hashes=(),
            scores=(),
        )
        scan = Mock()
        records.scan_authorized_mail_observations = scan

        result = handler(
            {
                "query_text": "劉一帆",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["citations"], [])
        scan.assert_not_called()

    def test_revision_owned_mail_source_fallback_deadline_covers_matching(
        self,
    ) -> None:
        handler, session, records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture(complete=False)
        )
        session.query.side_effect = None
        session.query.return_value = SimpleNamespace(
            status="ok",
            warnings=(),
            answer_citation_hashes=(),
            scores=(),
        )
        scan = Mock(
            return_value=RevisionOwnedMailSourceScan(
                observations=((records.observation, selector),),
                scanned_observation_count=1,
                complete=True,
            )
        )
        records.scan_authorized_mail_observations = scan
        matcher = Mock(side_effect=AssertionError("matching must not run after deadline"))

        with (
            patch("formowl_retrieval.gateway.time.monotonic", side_effect=(0.0, 2.1)),
            patch("formowl_mail.query._source_mail_observation_match", matcher),
        ):
            result = handler(
                {
                    "query_text": "劉一帆",
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_formowl",
                    "session_id": "revision-session",
                    "mail_import_session_id": selector,
                }
            )

        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(result["citations"], [])
        scan.assert_not_called()
        matcher.assert_not_called()

    def test_provider_obeys_shared_gate_without_a_greeting_override(self) -> None:
        self.assertIs(
            human_uat_orchestrator.requires_workspace_evidence,
            semantic_plan.requires_workspace_evidence,
        )
        prompt = "你好，今天過得如何？"
        # Force both shared-gate outcomes to catch a provider-local override,
        # independent of the shared classifier's current greeting vocabulary.
        for required in (True, False):
            with self.subTest(required=required):
                provider = human_uat_orchestrator.CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1",
                    api_key="synthetic-provider-key",
                )
                evidence_tool = Mock()
                with (
                    patch.object(
                        human_uat_orchestrator,
                        "requires_workspace_evidence",
                        return_value=required,
                    ) as gate,
                    patch.object(
                        provider,
                        "_request_response",
                        side_effect=TimeoutError,
                    ) as request,
                ):
                    provider.respond(
                        history=(),
                        user_text=prompt,
                        latest_evidence=None,
                        safety_identifier="shared-gate-test",
                        evidence_tool=evidence_tool,
                    )
                # The shared gate may be consulted more than once per turn, but
                # always with the same server-owned inputs and no local override.
                expected_gate_call = call(
                    prompt,
                    query_class=semantic_plan.deterministic_query_class(prompt),
                    prior_evidence_citeable=False,
                    prior_evidence_present=False,
                )
                self.assertEqual(gate.call_args_list[0], expected_gate_call)
                self.assertTrue(all(item.args == (prompt,) for item in gate.call_args_list))
                request.assert_called_once()
                payload = request.call_args.args[0]
                if required:
                    self.assertTrue(payload["tools"])
                    self.assertEqual(
                        payload["tool_choice"],
                        {"type": "function", "name": "query_effective_graph_view"},
                    )
                else:
                    self.assertEqual(payload["tools"], [])
                    self.assertEqual(payload["tool_choice"], "none")
                evidence_tool.assert_not_called()

    def test_empty_provider_body_retries_before_mcp_dispatch(self) -> None:
        descriptor = next(
            tool.model_dump(by_alias=True, exclude_none=True)
            for tool in build_remote_tool_descriptors(
                required_scope="formowl.use",
                enabled_tool_names={"whoami", "query_effective_graph_view"},
            )
            if tool.name == "query_effective_graph_view"
        )
        provider = human_uat_orchestrator.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-provider-key",
        )
        prompt = "Find evidence for the synthetic project deadline"
        provider_requests: list[dict[str, object]] = []
        evidence_tool = Mock(
            return_value={
                "status": "ok",
                "citations": ["citation-1"],
            }
        )
        function_call = {
            "type": "function_call",
            "call_id": "graph-call-after-empty-body",
            "name": "query_effective_graph_view",
            "arguments": json.dumps(
                {
                    "query_text": prompt,
                    "required_terms": ["deadline", "synthetic"],
                }
            ),
        }
        final_decision = {
            "response_kind": "answer",
            "answer_text": "The governed evidence is available.",
            "display_format": "markdown",
            "citation_ids": ["citation-1"],
            "coverage_status": "complete",
            "coverage_note": "",
        }

        def provider_response(payload: dict[str, object]) -> dict[str, object]:
            provider_requests.append(payload)
            if len(provider_requests) == 1:
                raise human_uat_orchestrator._UatProviderFailure(
                    reason_code="empty_response_body",
                    http_status=200,
                    body=b"",
                    headers={},
                )
            if len(provider_requests) == 2:
                return {"status": "completed", "output": [function_call]}
            return {
                "status": "completed",
                "output_text": json.dumps(final_decision),
            }

        with patch.object(
            provider,
            "_request_response",
            side_effect=provider_response,
        ):
            outcome = provider.respond(
                history=(),
                user_text=prompt,
                latest_evidence=None,
                safety_identifier="empty-provider-body-retry",
                evidence_tool=evidence_tool,
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary={
                    "source_families": ["mail", "document_text"],
                },
            )

        self.assertGreaterEqual(len(provider_requests), 3)
        self.assertEqual(
            provider_requests[0]["tool_choice"],
            provider_requests[1]["tool_choice"],
        )
        self.assertEqual(provider_requests[0]["tools"], provider_requests[1]["tools"])
        evidence_tool.assert_called_once()
        self.assertEqual(outcome.citation_ids, ("citation-1",))
        self.assertEqual(
            outcome.provider_diagnostic["provider_attempt_count"],
            len(provider_requests),
        )

    def test_mail_source_fallback_no_citation_stops_provider_replan(self) -> None:
        descriptor = next(
            tool.model_dump(by_alias=True, exclude_none=True)
            for tool in build_remote_tool_descriptors(
                required_scope="formowl.use",
                enabled_tool_names={"whoami", "query_mail_evidence"},
            )
            if tool.name == "query_mail_evidence"
        )
        provider = human_uat_orchestrator.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-provider-key",
        )
        provider_requests: list[dict[str, object]] = []
        evidence_tool = Mock(
            return_value={
                "status": "pending_review",
                "query_hash": "sha256:" + ("a" * 64),
                "mail_import_session_id": "mail-session-1",
                "evidence_snippets": [],
                "citations": [],
                "warnings": (
                    "mail_evidence_source_fallback_used",
                    "mail_evidence_source_fallback_incomplete",
                    "mail_evidence_no_verified_citations",
                ),
            }
        )

        def provider_response(payload: dict[str, object]) -> dict[str, object]:
            provider_requests.append(payload)
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "mail-fallback-call",
                        "name": "query_mail_evidence",
                        "arguments": json.dumps(
                            {
                                "query_text": "找出周岑禾的設備維護信件證據",
                                "required_terms": ["周岑禾", "設備維護"],
                                "mail_import_session_id": "mail-session-1",
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            }

        with patch.object(
            provider,
            "_request_response",
            side_effect=provider_response,
        ):
            outcome = provider.respond(
                history=(),
                user_text="把周岑禾的設備維護郵件整理出來",
                latest_evidence=None,
                safety_identifier="mail-fallback-terminal",
                evidence_tool=evidence_tool,
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["mail-session-1"],
                },
            )

        self.assertEqual(len(provider_requests), 1)
        evidence_tool.assert_called_once()
        self.assertEqual(
            evidence_tool.call_args.args[0].mail_import_session_id,
            "mail-session-1",
        )
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(outcome.citation_ids, ())
        self.assertIn("不代表資料不存在", outcome.answer_text)

    def test_default_composition_loads_once_and_uses_query_bundle_for_mail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle = _mail_bundle(Path(temporary_directory))
            loaded = SimpleNamespace(
                query_bundle=bundle,
                # A source bundle must not be consulted by this composition seam.
                source_bundle=object(),
                session=SimpleNamespace(
                    requester_user_id="user_yifan",
                    workspace_id="workspace_formowl",
                    authorized_source=SimpleNamespace(
                        source_kind=semantic_plan.AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
                    ),
                    source_session_binding_fingerprint="sha256:" + ("3" * 64),
                ),
                safe_binding={
                    "extraction_coverage": {
                        "source_completeness_certified": True,
                    },
                },
            )

            def graph_handler(_arguments: dict[str, object]) -> dict[str, object]:
                return {"status": "ok"}

            with (
                patch.object(
                    loader,
                    "_load_approved_sealed_source",
                    return_value=loaded,
                ) as load_source,
                patch.object(
                    loader,
                    "build_issue56_production_semantic_retrieval_handler",
                    return_value=graph_handler,
                ) as build_graph,
                patch.object(
                    loader,
                    "build_mail_evidence_query_handler",
                    wraps=loader.build_mail_evidence_query_handler,
                ) as build_mail,
            ):
                retrieval_handler, mail_handler = (
                    loader.build_issue56_production_semantic_handlers()
                )

            load_source.assert_called_once_with(include_participant_authorization_observations=True)
            build_graph.assert_called_once_with(
                query_agent_planner=None,
                _loaded_source=loaded,
            )
            build_mail.assert_called_once_with((bundle,))
            self.assertIs(retrieval_handler, graph_handler)
            self.assertIsNotNone(mail_handler)
            assert mail_handler is not None
            capability_summary = mail_handler.authorized_capability_summary
            self.assertEqual(
                capability_summary["source_families"],
                ["mail"],
            )
            self.assertEqual(
                capability_summary["authorized_mail_import_session_ids"],
                [bundle.mail_import_session.mail_import_session_id],
            )
            self.assertEqual(capability_summary["selector_count"], 1)

            query = mail_handler(
                {
                    "query_text": "audit approval",
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_formowl",
                    "session_id": "synthetic-owner-session",
                    "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                }
            )
            self.assertEqual(query["status"], "ok")
            self.assertTrue(query["citations"])

            denied_user = mail_handler(
                {
                    "query_text": "audit approval",
                    "requester_user_id": "user_other",
                    "workspace_id": "workspace_formowl",
                    "session_id": "synthetic-denied-user-session",
                    "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                }
            )
            self.assertEqual(denied_user["status"], "permission_denied")
            self.assertEqual(denied_user["citations"], [])

            denied_workspace = mail_handler(
                {
                    "query_text": "audit approval",
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_other",
                    "session_id": "synthetic-denied-workspace-session",
                    "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                }
            )
            self.assertEqual(denied_workspace["status"], "permission_denied")
            self.assertEqual(denied_workspace["citations"], [])

    def test_composed_mail_capability_binds_provider_omitted_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle = _mail_bundle(Path(temporary_directory))
            selector = bundle.mail_import_session.mail_import_session_id
            revision = SimpleNamespace(
                bundles=(bundle,),
                session=SimpleNamespace(
                    requester_user_id="user_yifan",
                    workspace_id="workspace_formowl",
                    authorized_source=SimpleNamespace(
                        source_kind=semantic_plan.AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
                    ),
                    source_session_binding_fingerprint="sha256:" + ("4" * 64),
                ),
                source_records=SimpleNamespace(
                    authorized_mail_import_session_ids=(selector,),
                ),
                safe_binding={
                    "extraction_coverage": {
                        "source_completeness_certified": True,
                    },
                },
                effective_graph_view=SimpleNamespace(),
                authorized_source=None,
            )
            graph_handler = Mock(return_value={"status": "ok"})
            with patch.object(
                loader,
                "build_issue56_production_semantic_retrieval_handler",
                return_value=graph_handler,
            ):
                _retrieval_handler, mail_handler = (
                    loader.build_issue56_production_semantic_handlers(
                        ingestion_revision=revision,
                    )
                )

            gateway = SemanticMcpGateway(mail_evidence_handler=mail_handler)
            dispatcher = SimpleNamespace(
                required_scope="formowl.use",
                enabled_tool_names=frozenset({"whoami", "query_mail_evidence"}),
                semantic_gateway=gateway,
            )
            application = SimpleNamespace(dispatcher=dispatcher)
            descriptor, capabilities = _query_agent_runtime_context(
                application,
                user_text="整理授權 audit approval 郵件",
            )
            self.assertIsNotNone(capabilities)
            assert capabilities is not None
            self.assertEqual(
                capabilities["authorized_mail_import_session_ids"],
                [selector],
            )

            binder = human_uat_orchestrator._UatTurnRequestContractBinder(
                user_text="整理授權 audit approval 郵件",
                authorized_capability_summary=capabilities,
            )
            request = human_uat_orchestrator._parse_tool_request(
                {
                    "query_text": "audit approval",
                    "required_terms": ["audit", "approval"],
                },
                tool_descriptor=descriptor,
                request_contract_binder=binder,
            )
            self.assertEqual(request.mail_import_session_id, selector)
            self.assertEqual(request.required_terms, ("approval", "audit"))
            transported = _mcp_query_request(request)["params"]["arguments"]
            self.assertEqual(transported["required_terms"], ["approval", "audit"])

            envelope = gateway.dispatch_tool(
                "query_mail_evidence",
                {
                    "query_text": request.query_text,
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_formowl",
                    "session_id": "provider-omitted-selector",
                    "mail_import_session_id": request.mail_import_session_id,
                    "required_terms": list(request.required_terms),
                },
            )
            self.assertEqual(envelope["status"], "ok")
            self.assertTrue(envelope["data"]["citations"])
            self.assertNotIn(
                "authorized_mail_import_session_ids",
                envelope["data"],
            )

    def test_mail_required_terms_are_grounded_and_frozen_before_mcp(self) -> None:
        user_text = "整理ＡＢＣ周岑禾的設備維護郵件"
        selector = "mailimport:" + ("a" * 64)
        capabilities = {
            "source_families": ["mail"],
            "mail_selector_kind": "mail_import_session_id",
            "authorized_mail_import_session_ids": [selector],
        }
        descriptor = {
            "name": "query_mail_evidence",
            "inputSchema": {
                "properties": {
                    "query_text": {},
                    "required_terms": {},
                    "mail_import_session_id": {},
                }
            },
        }
        binder = human_uat_orchestrator._UatTurnRequestContractBinder(
            user_text=user_text,
            authorized_capability_summary=capabilities,
        )
        with self.assertRaises(ContractValidationError):
            human_uat_orchestrator._parse_tool_request(
                {"query_text": "ABC周岑禾 設備維護", "mail_import_session_id": selector},
                tool_descriptor=descriptor,
                request_contract_binder=binder,
            )
        request = human_uat_orchestrator._parse_tool_request(
            {
                "query_text": "ABC周岑禾 設備維護",
                "required_terms": ["設備維護", "ＡＢＣ周岑禾"],
                "mail_import_session_id": selector,
            },
            tool_descriptor=descriptor,
            request_contract_binder=binder,
        )
        self.assertEqual(request.required_terms, ("abc周岑禾", "設備維護"))
        retry = human_uat_orchestrator._parse_tool_request(
            {
                "query_text": "ABC周岑禾 設備維護 郵件",
                "required_terms": ["abc周岑禾", "設備維護"],
                "mail_import_session_id": selector,
            },
            tool_descriptor=descriptor,
            request_contract_binder=binder,
        )
        self.assertEqual(retry.required_terms, request.required_terms)
        with self.assertRaises(ContractValidationError):
            human_uat_orchestrator._parse_tool_request(
                {
                    "query_text": "ABC周岑禾 郵件",
                    "required_terms": ["abc周岑禾", "郵件"],
                    "mail_import_session_id": selector,
                },
                tool_descriptor=descriptor,
                request_contract_binder=binder,
            )

        class _ParserBypassModel:
            def respond(self, *, evidence_tool, **_kwargs):
                evidence_tool(request)
                evidence_tool(replace(request, required_terms=("abc周岑禾", "郵件")))

        calls = []
        with self.assertRaises(ContractValidationError):
            _run_gpt_query_agent(
                _ParserBypassModel(),
                prompt=user_text,
                history=(),
                latest_evidence=None,
                safety_identifier="required-terms-test",
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary=capabilities,
                mcp_call=lambda item: calls.append(item) or {"status": "ok"},
            )
        self.assertEqual(calls, [request])

    def test_graph_runtime_retry_cannot_omit_frozen_required_terms(self) -> None:
        prompt = "Find evidence for the synthetic project deadline"
        request = human_uat_orchestrator.UatEvidenceToolRequest(
            query_text=prompt, required_terms=("deadline", "synthetic"),
        )

        class Model:
            def respond(self, *, evidence_tool, **_kwargs):
                evidence_tool(request)
                evidence_tool(replace(request, required_terms=None))
                evidence_tool(replace(request, required_terms=("synthetic",)))

        calls = []
        with self.assertRaisesRegex(ContractValidationError, "changed within the turn"):
            _run_gpt_query_agent(
                Model(), prompt=prompt, history=(), latest_evidence=None,
                safety_identifier="graph-required-terms-test", formowl_tool_descriptor=None,
                authorized_capability_summary={"source_families": ["mail", "document_text"]},
                mcp_call=lambda item: calls.append(item) or {"status": "ok"},
            )
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call.required_terms == request.required_terms for call in calls))

    def test_empty_bundle_revision_composes_revision_owned_mail_handler(self) -> None:
        revision = SimpleNamespace(
            bundles=(),
            session=SimpleNamespace(),
            effective_graph_view=SimpleNamespace(),
            source_records=SimpleNamespace(
                authorized_mail_import_session_ids=("mail-selector",),
            ),
            safe_binding={},
            authorized_source=None,
        )
        graph_handler = Mock(return_value={"status": "ok"})
        mail_handler = Mock(return_value={"status": "ok"})
        with (
            patch.object(
                loader,
                "build_issue56_production_semantic_retrieval_handler",
                return_value=graph_handler,
            ) as build_graph,
            patch.object(
                loader,
                "build_revision_owned_mail_evidence_query_handler",
                return_value=mail_handler,
            ) as build_mail,
        ):
            retrieval_handler, composed_mail_handler = (
                loader.build_issue56_production_semantic_handlers(
                    ingestion_revision=revision,
                )
            )

        self.assertIs(retrieval_handler, graph_handler)
        # The legacy mail handler is wrapped by the fail-closed placement guard.
        self.assertIn(mail_handler, [
            cell.cell_contents for cell in (getattr(composed_mail_handler, "__closure__", None) or ())
        ])
        build_graph.assert_called_once_with(
            query_agent_planner=None,
            ingestion_revision=revision,
        )
        build_mail.assert_called_once_with(
            session=revision.session,
            effective_graph_view=revision.effective_graph_view,
            source_records=revision.source_records,
            safe_binding=revision.safe_binding,
            allowed_relation_types=(),
        )

    def test_revision_owned_mail_handler_returns_owner_citation_without_bundle(self) -> None:
        handler, session, _records, selector, _other_selector, observation_hash = (
            self._revision_owned_mail_fixture()
        )

        result = handler(
            {
                "query_text": "audit approval",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(
            result["citations"][0]["source_observation_id"],
            "observation_mail_001",
        )
        self.assertEqual(
            result["evidence_snippets"][0]["source_observation_hash"],
            observation_hash,
        )
        session.query.assert_called_once()

    def test_revision_owned_mail_handler_routes_chinese_completion_to_evidence(
        self,
    ) -> None:
        handler, session, _records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture()
        )

        result = handler(
            {
                "query_text": "把 audit approval 郵件整理出來",
                "required_terms": ["audit", "approval"],
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)
        request_contract = session.query.call_args.kwargs["request_contract"]
        self.assertEqual(request_contract["query_class"], "evidence_lookup")

    def test_revision_owned_mail_handler_routes_unstructured_exact_lexical_mail_to_evidence(
        self,
    ) -> None:
        handler, session, _records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture()
        )

        result = handler(
            {
                "query_text": "調閱出來 audit approval 郵件",
                "required_terms": ["audit", "approval"],
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "ok")
        request_contract = session.query.call_args.kwargs["request_contract"]
        self.assertEqual(request_contract["query_class"], "evidence_lookup")

    def test_revision_owned_mail_handler_preserves_explicit_exact_mail_control(
        self,
    ) -> None:
        handler, session, _records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture()
        )

        result = handler(
            {
                "query_text": "把 audit approval 郵件全部整理出來",
                "required_terms": ["audit", "approval"],
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "ok")
        request_contract = session.query.call_args.kwargs["request_contract"]
        self.assertEqual(request_contract["query_class"], "exact_set_or_inventory")

    def test_bound_mail_intent_survives_opposite_provider_expansion_over_mcp(self) -> None:
        scenarios = (
            (
                "查找周岑禾的設備維護郵件",
                "列出周岑禾的所有設備維護郵件",
                "周岑禾 設備維護排程已確認",
                "設備維護排程",
                ["周岑禾", "設備維護"],
            ),
            (
                "列出林予安的所有會議安排郵件",
                "查詢林予安的會議安排郵件摘要",
                "林予安 會議安排時間已確認",
                "會議安排",
                ["林予安", "會議安排"],
            ),
        )
        for original_prompt, expanded_query, source_text, subject, terms in scenarios:
            with self.subTest(original_prompt=original_prompt):
                handler, session, _records, selector, _other_selector, _hash = (
                    self._revision_owned_mail_fixture(
                        complete=True,
                        source_text=source_text,
                        subject=subject,
                    )
                )
                gateway = SemanticMcpGateway(mail_evidence_handler=handler)
                dispatcher = SimpleNamespace(
                    required_scope="formowl.use",
                    enabled_tool_names=frozenset({"whoami", "query_mail_evidence"}),
                    semantic_gateway=gateway,
                )
                tool_descriptor, _capabilities = _query_agent_runtime_context(
                    SimpleNamespace(dispatcher=dispatcher),
                    user_text=original_prompt,
                )
                binder = human_uat_orchestrator._UatTurnRequestContractBinder(
                    user_text=original_prompt,
                    authorized_capability_summary=handler.authorized_capability_summary,
                )
                original_class = semantic_plan.deterministic_query_class(original_prompt)
                expansion_class = semantic_plan.deterministic_query_class(expanded_query)
                self.assertNotEqual(original_class, expansion_class)
                candidate_contract = {
                    "original_query_hash": "sha256:" + ("a" * 64),
                    "query_class": expansion_class,
                    "source_family_scope": ["mail"],
                    "requested_fields": [],
                    "maximum_claim_strength": (
                        semantic_plan.SEMANTIC_CLAIM_STRENGTH_BY_CLASS[expansion_class]
                    ),
                }
                request = human_uat_orchestrator._parse_tool_request(
                    {
                        "query_text": expanded_query,
                        "required_terms": terms,
                        "mail_import_session_id": selector,
                        "request_contract": candidate_contract,
                    },
                    tool_descriptor=tool_descriptor,
                    request_contract_binder=binder,
                )

                self.assertEqual(request.request_contract["query_class"], original_class)
                mcp_request = _mcp_query_request(request)
                mcp_arguments = mcp_request["params"]["arguments"]
                self.assertEqual(
                    mcp_arguments["request_contract"]["query_class"],
                    original_class,
                )
                self.assertEqual(mcp_arguments["query_text"], expanded_query)
                mcp_arguments.update(
                    {
                        "requester_user_id": session.requester_user_id,
                        "workspace_id": session.workspace_id,
                        "session_id": "revision-session",
                    }
                )
                handler(mcp_arguments)
                self.assertEqual(
                    session.query.call_args.kwargs["request_contract"]["query_class"],
                    original_class,
                )

    def test_revision_owned_mail_handler_denies_wrong_selector(self) -> None:
        handler, session, _records, _selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture()
        )

        result = handler(
            {
                "query_text": "audit approval",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": "mailimport:" + ("9" * 64),
            }
        )

        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["citations"], [])
        session.query.assert_not_called()

    def test_revision_owned_mail_handler_does_not_cross_bind_multiple_selectors(
        self,
    ) -> None:
        handler, session, _records, _selector, other_selector, _observation_hash = (
            self._revision_owned_mail_fixture()
        )

        result = handler(
            {
                "query_text": "audit approval",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": other_selector,
            }
        )

        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(result["citations"], [])
        self.assertIn("mail_evidence_source_fallback_unavailable", result["warnings"])
        self.assertIn("mail_evidence_no_verified_citations", result["warnings"])
        session.query.assert_called_once()

    def test_revision_owned_mail_handler_rejects_tampered_lineage(self) -> None:
        handler, _session, records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture()
        )
        records.lineage_value = MailMessageOccurrenceLineage(
            source_observation_id="observation_mail_001",
            message_occurrence_id="tampered_occurrence",
        )

        with self.assertRaisesRegex(
            ContractValidationError,
            "Observation lineage mismatch",
        ):
            handler(
                {
                    "query_text": "audit approval",
                    "requester_user_id": "user_yifan",
                    "workspace_id": "workspace_formowl",
                    "session_id": "revision-session",
                    "mail_import_session_id": selector,
                }
            )

    def test_revision_owned_mail_handler_marks_incomplete_without_fabricating_citation(
        self,
    ) -> None:
        handler, session, _records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture(complete=False)
        )

        def _unknown_result(**kwargs):
            semantic_plan.validate_semantic_request_contract(
                kwargs["request_contract"],
                available_source_families=("mail",),
            )
            return SimpleNamespace(
                status="ok",
                warnings=(),
                answer_citation_hashes=("sha256:" + ("f" * 64),),
                scores=(),
            )

        session.query.side_effect = _unknown_result

        result = handler(
            {
                "query_text": "audit approval",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(result["citations"], [])
        self.assertIn("mail_evidence_source_fallback_unavailable", result["warnings"])
        self.assertIn("mail_evidence_coverage_incomplete", result["warnings"])
        self.assertIn("mail_evidence_no_verified_citations", result["warnings"])

    def test_revision_owned_mail_handler_preserves_operational_error_status(
        self,
    ) -> None:
        handler, session, _records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture()
        )

        def _operational_error(**kwargs):
            semantic_plan.validate_semantic_request_contract(
                kwargs["request_contract"],
                available_source_families=("mail",),
            )
            return SimpleNamespace(
                status="error",
                warnings=("mail_query_operational_failure",),
                answer_citation_hashes=(),
                scores=(),
            )

        session.query.side_effect = _operational_error
        result = handler(
            {
                "query_text": "audit approval",
                "requester_user_id": "user_yifan",
                "workspace_id": "workspace_formowl",
                "session_id": "revision-session",
                "mail_import_session_id": selector,
            }
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["citations"], [])
        self.assertIn("mail_query_operational_failure", result["warnings"])

    def test_revision_owned_mail_replan_without_citation_stays_public_mcp_safe(
        self,
    ) -> None:
        handler, session, records, selector, _other_selector, _observation_hash = (
            self._revision_owned_mail_fixture()
        )
        scan = Mock()
        records.scan_authorized_mail_observations = scan

        malformed_statuses = (
            "replan_required",
            ["replan_required"],
            {"status": "replan_required"},
        )
        current_status: object = malformed_statuses[0]

        def _replan_result(**kwargs):
            semantic_plan.validate_semantic_request_contract(
                kwargs["request_contract"],
                available_source_families=("mail",),
            )
            return SimpleNamespace(
                status=current_status,
                warnings=("external_replan_required",),
                answer_citation_hashes=(),
                scores=(),
            )

        session.query.side_effect = _replan_result
        for index, current_status in enumerate(malformed_statuses):
            with self.subTest(status_type=type(current_status).__name__):
                gateway = SemanticMcpJsonRpcGateway(
                    semantic_gateway=SemanticMcpGateway(mail_evidence_handler=handler),
                    session=McpSession(
                        session_id="revision-session",
                        actor_user_id="user_yifan",
                        workspace_id="workspace_formowl",
                    ),
                )

                response = gateway.handle_json_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": f"mail-replan-safe-{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "query_mail_evidence",
                            "arguments": {
                                "query_text": "把劉一帆的信件整理出來",
                                "mail_import_session_id": selector,
                            },
                        },
                    },
                )

                payload = response["result"]["content"][0]["json"]
                self.assertFalse(response["result"]["isError"])
                self.assertEqual(
                    payload["status"],
                    "pending_review",
                )
                scan.assert_not_called()
                self.assertEqual(payload["data"]["citations"], [])
                self.assertIn(
                    "mail_evidence_no_verified_citations",
                    payload["data"]["warnings"],
                )

    def test_runtime_context_selects_mail_and_graph_descriptors(self) -> None:
        def graph_handler(_arguments: dict[str, object]) -> dict[str, object]:
            return {"status": "ok"}

        graph_handler.authorized_capability_summary = {
            "source_families": ["mail", "attachment_table"],
        }

        def mail_handler(_arguments: dict[str, object]) -> dict[str, object]:
            return {"status": "ok"}

        gateway = SemanticMcpGateway(
            retrieval_handler=graph_handler,
            mail_evidence_handler=mail_handler,
        )
        dispatcher = SimpleNamespace(
            required_scope="formowl.use",
            enabled_tool_names=frozenset(
                {
                    "whoami",
                    "query_effective_graph_view",
                    "query_mail_evidence",
                }
            ),
            semantic_gateway=gateway,
        )
        application = SimpleNamespace(dispatcher=dispatcher)

        mail_descriptor, _ = _query_agent_runtime_context(
            application,
            user_text="整理劉一帆的信件",
        )
        graph_descriptor, _ = _query_agent_runtime_context(
            application,
            user_text="請解釋什麼是知識圖譜",
        )

        self.assertEqual(mail_descriptor["name"], "query_mail_evidence")
        self.assertIn("required_terms", mail_descriptor["inputSchema"]["required"])
        description = mail_descriptor["description"].casefold()
        for phrase in (
            "identity and genuine topic anchors",
            "all terms are conjunctive",
            "same candidate evidence item",
            "authorized selector and validated request contract determine source-family/scope",
            "source-family and operation/action words are not content terms",
            "unless the user explicitly requests those literal words",
        ):
            with self.subTest(description_phrase=phrase):
                self.assertIn(phrase, description)
        self.assertEqual(graph_descriptor["name"], "query_effective_graph_view")
        for query_class in (
            "evidence_lookup", "relation_reasoning",
            "global_summarization", "exact_set_or_inventory",
        ):
            with self.subTest(query_class=query_class), patch(
                "formowl_gateway.issue56_uat_runtime.deterministic_query_class",
                return_value=query_class,
            ):
                descriptor, _ = _query_agent_runtime_context(
                    application, user_text="Find project evidence",
                )
                self.assertEqual(
                    "required_terms" in descriptor["inputSchema"]["required"],
                    query_class == "evidence_lookup",
                )


class ProjectionIndependentSourceMcpTests(unittest.IsolatedAsyncioTestCase):
    def _table_lookup(self, root, *, terms=("7812046639",), scope=("attachment_table",), page_size=10, attachment_csv=None):
        fixture = _source_start_preparation_fixture(
            root, families=("mail",), attachment_csv=attachment_csv or (
                "Code,Window,Capacity\n7812046639,2032-06-19,17\n"
                "8640391527,2034-11-23,29\nOrionWorkshop,review-pending,53\n"
            ),
        )
        from scripts.issue56_source_native_lookup import build_lookup
        lookup_directory = root / "lookup"
        build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                     output_directory=lookup_directory)
        for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
            shutil.copyfile(lookup_directory / name, fixture.directory / name)
        revision = issue56_sealed_source.load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
        )
        self.assertIsNone(revision.session)
        self.assertEqual(revision.exact_lookup_directory, fixture.directory / "exact-cells")
        handler = loader.build_issue56_production_semantic_retrieval_handler(ingestion_revision=revision)
        query = "Find native row values"
        arguments = {
            "query_text": query, "required_terms": list(terms), "page_size": page_size,
            "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
            "session_id": "synthetic-table-lookup",
            "request_contract": {
                "original_query_hash": sha256_json(query), "query_class": "evidence_lookup",
                "source_family_scope": list(scope), "requested_fields": ["Window", "Capacity"],
                "maximum_claim_strength": "cited_evidence",
            },
        }
        return fixture, revision, handler, arguments

    def test_numeric_attachment_anchor_uses_ordinary_tokens_and_verified_same_row_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments = self._table_lookup(Path(directory))
            profile = loader.load_issue56_target_mail_tokenizer_profile()
            self.assertFalse(profile.analyze("7812046639").protected_identifiers)
            self.assertTrue(profile.analyze("7812046639").tokens)
            self.assertIn("attachment_table", handler.authorized_capability_summary["source_families"])
            result = handler(arguments)
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["deterministic_exact"])
            evidence = result["evidence"]
            self.assertEqual({cell["value"] for item in evidence for cell in item["table_row"]["cells"]}, {"7812046639", "2032-06-19", "17"})
            native_rows = {sha256_json(item.to_dict()): item for item in fixture.observations if item.observation_type == "table_row"}
            native_cells = {sha256_json(item.to_dict()): item for item in fixture.observations if item.observation_type == "table_cell"}
            for item in evidence:
                row = native_rows[item["citation_hash"]]
                self.assertEqual(item["table_row"]["source_observation_id"], row.observation_id)
                for cell in item["table_row"]["cells"]:
                    native = native_cells[cell["citation_hash"]]
                    self.assertEqual(cell["coordinates"]["row_index"], row.location["row_index"])
                    self.assertEqual(cell["coordinates"]["cell_index"], native.location["cell_index"])
                    self.assertEqual(cell["value"], native.text)
                    self.assertTrue(cell["occurrence_lineage_fingerprint"].startswith("sha256:"))
                    self.assertFalse(cell["source_proven_field_schema"])
            self.assertEqual(set(result["citations"]), {item["citation_hash"] for item in evidence})
            self.assertEqual(result["coverage"]["status"], "incomplete")
            validate_public_gateway_payload(result)
            unrelated = handler({**arguments, "required_terms": ["OrionWorkshop"]})
            self.assertEqual({cell["value"] for item in unrelated["evidence"] for cell in item["table_row"]["cells"]}, {"OrionWorkshop", "review-pending", "53"})
            other_row = handler({**arguments, "required_terms": ["7812046639", "2034-11-23"]})
            self.assertFalse(other_row["evidence"])
            self.assertEqual(other_row["status"], "pending_review")

    def test_part_identifier_anchor_accepts_chinese_native_column_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments = self._table_lookup(
                Path(directory),
                terms=("03.80503G301",),
                attachment_csv=(
                    "料號,產地,製造商\n"
                    "03.80503G301,JAPAN,Murata\n"
                    "03.80503G302,TAIWAN,Other\n"
                ),
            )
            arguments["required_terms"] = ["03.80503G301"]
            result = handler(arguments)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(
                {cell["value"] for item in result["evidence"] for cell in item["table_row"]["cells"]},
                {"03.80503G301", "JAPAN", "Murata"},
            )
            self.assertEqual(result["citations"], [item["citation_hash"] for item in result["evidence"]])

    def test_attachment_timeout_caps_and_denial_do_not_become_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            _, revision, handler, arguments = self._table_lookup(Path(directory))
            with patch("formowl_retrieval.gateway.SOURCE_EVIDENCE_OBSERVATION_LIMIT", 2):
                capped = handler(arguments)
            self.assertEqual(capped["status"], "pending_review")
            scan = capped["query_agent"]["context_bundle"]["source_recovery"]["scan"]
            self.assertFalse(scan["complete"])
            self.assertLessEqual(scan["scanned_observation_count"], 2)
            with source_evidence_deadline_scope(loader.time.monotonic() - 1):
                expired = handler(arguments)
            self.assertEqual(expired["status"], "pending_review")
            self.assertFalse(expired["evidence"])
            denied = handler({**arguments, "requester_user_id": "synthetic-denied-user"})
            self.assertEqual(denied["status"], "permission_denied")
            self.assertFalse(denied["citations"])
            exact = handler({**arguments, "request_contract": {
                **arguments["request_contract"], "query_class": "exact_set_or_inventory",
                "maximum_claim_strength": "complete_authorized_scope",
            }})
            self.assertEqual(exact["status"], "partial")
            self.assertTrue(exact["citations"])
            self.assertEqual(exact["citations"], [item["citation_hash"] for item in exact["evidence"]])
            validate_public_gateway_payload(exact)
            original_contract = {
                **arguments["request_contract"], "query_class": "exact_set_or_inventory",
                "maximum_claim_strength": "complete_authorized_scope",
            }
            self.assertEqual(exact["query_agent"]["request_contract"], original_contract)
            downgrade = exact["execution_downgrade"]
            self.assertEqual(downgrade["request_contract_fingerprint"], sha256_json(original_contract))
            self.assertEqual(downgrade["executed_request_contract"], {
                **original_contract, "query_class": "evidence_lookup", "maximum_claim_strength": "cited_evidence",
            })
            self.assertEqual(downgrade["disclosure"], "無法做完整清單／確定性計算，以下為引用證據")
            self.assertEqual(exact["coverage"]["status"], "incomplete")
            self.assertFalse(exact["coverage"]["absence_claim"])
            self.assertFalse(exact["deterministic_exact"])
            self.assertIsNone(exact["exact_result"])
            self.assertNotIn("exact_inventory", exact)

    def test_attachment_shard_and_native_cell_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments = self._table_lookup(Path(directory))
            profile = loader.load_issue56_target_mail_tokenizer_profile()
            token_hash = sha256_json(next(iter(profile.analyze("7812046639").tokens)))
            shard = revision.exact_lookup_directory / "values" / f"{token_hash[7:9]}.jsonl"
            original = shard.read_bytes()
            shard.write_bytes(original + b"\n")
            with self.assertRaises(ContractValidationError):
                handler(arguments)
            shard.write_bytes(original)
            cell = next(item for item in fixture.observations if item.text == "2032-06-19")
            store = revision.job_authorities[0].observation_store
            path = store._store._record_path(cell.observation_id)
            payload = json.loads(path.read_text())
            payload["payload"]["lineage"]["child_asset_id"] = "synthetic-tampered-child"
            path.write_text(json.dumps(payload))
            with self.assertRaises(ContractValidationError):
                handler(arguments)

    def test_missing_parent_helper_never_starts_linear_source_hydration(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments = self._table_lookup(Path(directory))
            authority = revision.job_authorities[0]
            original = authority.load_indexed_observation
            with (patch.object(revision.source_records.runtime_store, "helper_for_attachment_asset", return_value=None),
                  patch.object(type(authority), "load_indexed_observation", autospec=True,
                               side_effect=lambda current, observation_id, **kwargs: original(observation_id, **kwargs)) as read):
                result = handler(arguments)
            self.assertEqual(result["status"], "pending_review")
            self.assertFalse(result["evidence"])
            self.assertLessEqual(read.call_count, 4)  # One sealed row and its three cells only.
            scan = result["query_agent"]["context_bundle"]["source_recovery"]["scan"]
            self.assertEqual(scan["stop_reason"], "source_parent_binding_unresolved")

    def test_table_deadline_preserves_ordinary_mail_family_time(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            _, revision, handler, arguments = self._table_lookup(Path(directory), scope=("attachment_table", "mail"))
            table_deadlines = []
            def exhaust_table(lookup, **kwargs):
                deadline = kwargs["deadline_monotonic"]
                table_deadlines.append(deadline)
                while time.monotonic() < deadline:
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))
                return RevisionOwnedMailSourceScan((), 0, False, "deadline")
            with (patch.object(loader._IngestionExactCellLookup, "scan_source_rows", autospec=True, side_effect=exhaust_table),
                  patch.object(revision.source_records, "scan_authorized_observations", wraps=revision.source_records.scan_authorized_observations) as mail_scan):
                result = handler({**arguments, "required_terms": ["Acceptance"]})
            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["evidence"])
            self.assertTrue(all("table_row" not in item for item in result["evidence"]))
            self.assertLess(table_deadlines[0], mail_scan.call_args.kwargs["deadline_monotonic"])
            self.assertFalse(result["query_agent"]["context_bundle"]["source_recovery"]["scan"]["complete"])

    def test_verified_rows_are_emitted_before_later_shard_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            _, revision, _, _ = self._table_lookup(Path(directory), attachment_csv=(
                "Code,State\n" + "".join(f"7812046639,phase-{index}\n" for index in range(16))
            ))
            lookup = loader._IngestionExactCellLookup(revision)
            original = lookup._read_matching_shard_records
            emitted, evidence, row_shards = [], {}, []
            expired = [False]
            def read(kind, shard, **kwargs):
                if kind == "row":
                    row_shards.append(shard)
                    if len(row_shards) == 2:
                        self.assertTrue(emitted)  # No preloading of later row shards.
                        expired[0] = True
                        kwargs["check"]()
                return original(kind, shard, **kwargs)
            with (patch.object(lookup, "_read_matching_shard_records", side_effect=read),
                  patch.object(loader.time, "monotonic", side_effect=lambda: 2.0 if expired[0] else 0.0)):
                scan = lookup.scan_source_rows(
                    required_terms=("7812046639",), query_text="Find row state",
                    source_families=("attachment_table",), mail_import_session_id=None,
                    max_observations=8192, deadline_monotonic=1.0,
                    observation_callback=lambda item, scope: emitted.append(item) is None,
                    evidence_by_id=evidence,
                )
            self.assertEqual(len(row_shards), 2)
            self.assertTrue(emitted)
            self.assertFalse(scan.complete)
            self.assertEqual(scan.stop_reason, "deadline")
            self.assertEqual(set(evidence), {item.observation_id for item in emitted})

    def test_numeric_inline_table_uses_existing_rows_and_mail_selector_without_graph(self):
        from scripts.issue56_source_native_lookup import build_lookup
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(root, families=("mail",), inline_html=(
                "<table><tr><th>Code</th><th>State</th></tr>"
                "<tr><td>7812046639</td><td>review-pending</td></tr>"
                "<tr><td>8640391527</td><td>complete</td></tr></table>"
            ))
            output = root / "lookup"
            build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                         output_directory=output)
            for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
                shutil.copyfile(output / name, fixture.directory / name)
            revision = issue56_sealed_source.load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            selector = revision.source_records.authorized_mail_import_session_ids[0]
            handler = loader._build_source_start_semantic_handler(revision, mail_tool=True)
            result = handler({
                "query_text": "Find inline row state", "required_terms": ["7812046639"],
                "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
                "session_id": "synthetic-inline", "mail_import_session_id": selector, "limit": 10,
            })
            self.assertEqual(result["status"], "ok")
            cells = result["evidence_snippets"]
            self.assertEqual({cell["value"] for item in cells for cell in item["table_row"]["cells"]}, {"7812046639", "review-pending"})
            self.assertTrue(all(item["mail_import_session_id"] == selector for item in cells))
            self.assertEqual(len(result["citations"]), 1)
            self.assertEqual(result["citations"][0]["source_observation_id"], cells[0]["table_row"]["source_observation_id"])
            compact = human_uat_orchestrator.compact_evidence_for_model(result, item_limit=1)
            presented = json.loads(compact["evidence_snippets"][0]["snippet"])
            self.assertEqual(presented["table_row"], cells[0]["table_row"])
            self.assertEqual(presented["citation_hash"], cells[0]["citation_hash"])
            self.assertEqual(len(compact["citations"]), 1)
            self.assertIsNone(revision.session)
            validate_public_gateway_payload(result)

    def test_preferred_native_members_can_exceed_ordinary_evidence_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            csv = "Code,State\n" + "".join(f"7812046639,phase-{i}\n" for i in range(18))
            fixture, revision, _, _ = self._table_lookup(Path(directory), attachment_csv=csv)
            lookup = loader._IngestionExactCellLookup(revision)
            hashes = {sha256_json(o.to_dict()) for o in fixture.observations
                      if o.observation_type in {"table_row", "table_cell"} and o.location["row_index"] > 1}
            self.assertTrue(1 < len(hashes) <= 128)
            for preferred in (tuple(sorted(hashes)), ()):
                with self.subTest(preferred=bool(preferred)):
                    evidence = {}
                    seen = []
                    scan = lookup.scan_source_rows(
                        required_terms=("7812046639",), query_text="Find row state",
                        source_families=("attachment_table",), mail_import_session_id=None,
                        max_observations=8192, deadline_monotonic=time.monotonic() + 30,
                        observation_callback=lambda item, scope: seen.append(sha256_json(item.to_dict())) is None,
                        evidence_by_id=evidence, preferred_observation_hashes=preferred,
                    )
                    size = sum(len(json.dumps(v, ensure_ascii=False).encode()) for v in evidence.values())
                    if preferred:
                        self.assertEqual(scan.stop_reason, "source_table_shortlist")
                        self.assertCountEqual(seen, preferred)
                        self.assertGreater(size, 16 * 1024)
                    else:
                        self.assertEqual(scan.stop_reason, "context_limit")
                        self.assertTrue(seen)
                        self.assertLessEqual(size, 16 * 1024)

    def test_native_row_context_cap_omits_entire_oversized_group(self):
        with tempfile.TemporaryDirectory() as directory:
            columns = ["Code", *(f"Field{index}" for index in range(24))]
            values = ["7812046639", *("syntheticvalue" * 80 for _ in range(24))]
            _, _, handler, arguments = self._table_lookup(Path(directory), page_size=128,
                attachment_csv=",".join(columns) + "\n" + ",".join(values) + "\n")
            result = handler(arguments)
            self.assertEqual(result["status"], "pending_review")
            self.assertFalse(result["evidence"])
            self.assertFalse(result["citations"])
            self.assertEqual(result["coverage"]["status"], "incomplete")
            scan = result["query_agent"]["context_bundle"]["source_recovery"]["scan"]
            self.assertFalse(scan["complete"])
            self.assertEqual(scan["stop_reason"], "context_limit")
            self.assertEqual(set(result["citations"]), {item["citation_hash"] for item in result["evidence"]})

    def _oversized_native_and_mail_lookup(self, root):
        columns = ["Code", *(f"Field{index}" for index in range(24))]
        values = ["Acceptance", *("syntheticvalue" * 80 for _ in range(24))]
        return self._table_lookup(
            root, terms=("Acceptance",), scope=("attachment_table", "mail"),
            attachment_csv=",".join(columns) + "\n" + ",".join(values) + "\n",
        )

    def test_native_local_context_cap_continues_guarded_mail_with_remaining_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments = self._oversized_native_and_mail_lookup(Path(directory))
            original_native = loader._IngestionExactCellLookup.scan_source_rows
            native_calls = []
            def native(lookup, **kwargs):
                scan = original_native(lookup, **kwargs)
                native_calls.append((kwargs, scan))
                return scan
            with (patch.object(loader._IngestionExactCellLookup, "scan_source_rows", autospec=True, side_effect=native),
                  patch.object(revision.source_records, "scan_authorized_observations",
                               wraps=revision.source_records.scan_authorized_observations) as mail_scan):
                result = handler(arguments)
            self.assertEqual(len(native_calls), 1)
            native_args, native_scan = native_calls[0]
            self.assertEqual(native_scan.stop_reason, "context_limit")
            self.assertFalse(native_scan.complete)
            mail_scan.assert_called_once()
            self.assertLessEqual(mail_scan.call_args.kwargs["max_observations"],
                                 native_args["max_observations"] - native_scan.scanned_observation_count)
            self.assertGreater(mail_scan.call_args.kwargs["deadline_monotonic"],
                               native_args["deadline_monotonic"])
            body = next(item for item in fixture.observations if item.observation_type == "email_body_segment")
            self.assertIn(sha256_json(body.to_dict()), result["citations"])
            self.assertTrue(all("table_row" not in item for item in result["evidence"]))
            scan = result["query_agent"]["context_bundle"]["source_recovery"]["scan"]
            self.assertFalse(scan["complete"])
            self.assertEqual(scan["stop_reason"], "context_limit")
            self.assertEqual(result["coverage"]["status"], "incomplete")
            self.assertEqual(result["status"], "ok")  # Cited partial scope, not source completeness.
            validate_public_gateway_payload(result)

    def test_native_local_context_cap_does_not_reset_total_read_or_time_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            _, revision, handler, arguments = self._oversized_native_and_mail_lookup(Path(directory))
            with (patch("formowl_retrieval.gateway.SOURCE_EVIDENCE_OBSERVATION_LIMIT", 3),
                  # Model a local overflow that has also spent every remaining
                  # read. A partial row may otherwise reserve zero reads.
                  patch.object(loader._IngestionExactCellLookup, "scan_source_rows", autospec=True,
                               side_effect=lambda lookup, **kwargs: RevisionOwnedMailSourceScan(
                                   (), kwargs["max_observations"], False, "context_limit")),
                  patch.object(revision.source_records, "scan_authorized_observations",
                               wraps=revision.source_records.scan_authorized_observations) as mail_scan):
                capped = handler(arguments)
            mail_scan.assert_not_called()
            scan = capped["query_agent"]["context_bundle"]["source_recovery"]["scan"]
            self.assertLessEqual(scan["scanned_observation_count"], 3)
            self.assertFalse(scan["complete"])
            self.assertIn(scan["stop_reason"], {"context_limit", "observation_limit"})
            self.assertFalse(capped["evidence"])
            original_native = loader._IngestionExactCellLookup.scan_source_rows
            clock = loader.time.monotonic()
            expired = [False]
            def native(lookup, **kwargs):
                scan = original_native(lookup, **kwargs)
                self.assertEqual(scan.stop_reason, "context_limit")
                expired[0] = True
                return scan
            with (patch.object(loader._IngestionExactCellLookup, "scan_source_rows", autospec=True, side_effect=native),
                  patch.object(loader.time, "monotonic", side_effect=lambda: clock + 10 if expired[0] else clock),
                  patch.object(revision.source_records, "scan_authorized_observations",
                               wraps=revision.source_records.scan_authorized_observations) as mail_scan):
                timed_out = handler(arguments)
            mail_scan.assert_not_called()
            self.assertFalse(timed_out["evidence"])
            self.assertFalse(timed_out["query_agent"]["context_bundle"]["source_recovery"]["scan"]["complete"])

    def test_native_local_context_cap_does_not_hide_later_source_or_permission_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments = self._oversized_native_and_mail_lookup(Path(directory))
            body = next(item for item in fixture.observations if item.observation_type == "email_body_segment")
            path = revision.job_authorities[0].observation_store._store._record_path(body.observation_id)
            original = path.read_bytes()
            for damage in ("source_hash", "permission"):
                with self.subTest(damage=damage):
                    data = json.loads(original)
                    if damage == "source_hash":
                        data["text"] += " Synthetic tampering."
                    else:
                        data["permission_scope"]["scope_id"] = "synthetic-denied-scope"
                    path.write_text(json.dumps(data))
                    try:
                        with self.assertRaises(ContractValidationError):
                            handler(arguments)
                    finally:
                        path.write_bytes(original)

    def test_anchor_last_row_is_atomic_at_page_and_callback_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments = self._table_lookup(
                Path(directory), page_size=1, attachment_csv=(
                    "Window,Capacity,Code\n2032-06-19,17,7812046639\n"
                    "2034-11-23,29,7812046639\n"
                ),
            )
            result = handler(arguments)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["evidence"]), 1)
            group = result["evidence"][0]
            self.assertEqual(len(group["table_row"]["cells"]), 3)
            self.assertEqual(group["table_row"]["cells"][-1]["value"], "7812046639")
            row = next(item for item in fixture.observations
                       if item.observation_id == group["table_row"]["source_observation_id"])
            self.assertEqual(group["citation_hash"], sha256_json(row.to_dict()))
            self.assertEqual(result["citations"], [group["citation_hash"]])
            lookup = loader._IngestionExactCellLookup(revision)
            emitted, evidence = [], {}
            scan = lookup.scan_source_rows(
                required_terms=("7812046639",), query_text="Find row values",
                source_families=("attachment_table",), mail_import_session_id=None,
                max_observations=8192, deadline_monotonic=loader.time.monotonic() + 0.5,
                observation_callback=lambda item, scope: emitted.append(item) or False,
                evidence_by_id=evidence,
            )
            self.assertEqual(scan.stop_reason, "callback")
            self.assertEqual(len(emitted), 1)
            self.assertEqual(emitted[0].observation_type, "table_row")
            self.assertEqual(len(evidence[emitted[0].observation_id]["table_row"]["cells"]), 3)

    def test_mid_row_staging_deadline_publishes_no_members(self):
        with tempfile.TemporaryDirectory() as directory:
            _, revision, _, _ = self._table_lookup(Path(directory), attachment_csv=(
                "Window,Capacity,Code\n2032-06-19,17,7812046639\n"
            ))
            lookup = loader._IngestionExactCellLookup(revision)
            emitted, evidence = [], {}
            expired = [False]
            original = loader.redact_public_raw_references

            def redact(value):
                if value == "2032-06-19":
                    expired[0] = True  # Deadline between first value and last anchor.
                return original(value)

            with (patch.object(loader, "redact_public_raw_references", side_effect=redact),
                  patch.object(loader.time, "monotonic", side_effect=lambda: 2.0 if expired[0] else 0.0)):
                scan = lookup.scan_source_rows(
                    required_terms=("7812046639",), query_text="Find row values",
                    source_families=("attachment_table",), mail_import_session_id=None,
                    max_observations=8192, deadline_monotonic=1.0,
                    observation_callback=lambda item, scope: emitted.append(item) is None,
                    evidence_by_id=evidence,
                )
            self.assertEqual(scan.stop_reason, "deadline")
            self.assertFalse(scan.complete)
            self.assertFalse(emitted)
            self.assertFalse(evidence)

    def test_remaining_context_bytes_never_split_second_row_group(self):
        with tempfile.TemporaryDirectory() as directory:
            columns = [*(f"Field{index}" for index in range(12)), "Code"]
            values = [*("syntheticvalue" * 40 for _ in range(12)), "7812046639"]
            _, _, handler, arguments = self._table_lookup(Path(directory), page_size=128,
                attachment_csv=",".join(columns) + "\n" + (",".join(values) + "\n") * 2)
            result = handler(arguments)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["evidence"]), 1)
            cells = result["evidence"][0]["table_row"]["cells"]
            self.assertEqual(len(cells), len(values))
            self.assertEqual(cells[-1]["value"], "7812046639")
            self.assertTrue(cells[0]["value_truncated"])
            self.assertLessEqual(len(json.dumps(result["evidence"][0], ensure_ascii=False).encode()), 16 * 1024)
            scan = result["query_agent"]["context_bundle"]["source_recovery"]["scan"]
            self.assertEqual(scan["stop_reason"], "context_limit")
            self.assertFalse(scan["complete"])
            self.assertEqual(result["citations"], [result["evidence"][0]["citation_hash"]])

    def test_source_shard_prefilter_decodes_only_keyed_records_and_seals_after_overflow(self):
        matching_key, unrelated_key, row_key = (sha256_json(value) for value in (
            "synthetic-anchor-token", "unrelated-token", "synthetic-row",
        ))
        for kind in ("value", "row"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = ([matching_key, row_key, False] if kind == "value" else
                          ["row", matching_key, 0, "synthetic-row-id", sha256_json("row-bytes"), False])
                other = list(target)
                other[0 if kind == "value" else 1] = unrelated_key
                # An escaped JSON key is valid and must take the parser fallback.
                escaped = json.dumps(target).encode().replace(
                    matching_key.encode(), matching_key.encode().replace(b"sha256", b"\\u0073ha256"), 1,
                ) + b"\n"
                target_line, other_line = (json.dumps(item).encode() + b"\n" for item in (target, other))
                payload = target_line + other_line * 12000 + escaped
                path = root / ("values" if kind == "value" else "rows") / "aa.jsonl"
                path.parent.mkdir()
                path.write_bytes(payload)
                lookup = object.__new__(loader._IngestionExactCellLookup)
                lookup._directory = root
                binding = {"size_bytes": len(payload), "record_count": 12002,
                           "sha256": "sha256:" + hashlib.sha256(payload).hexdigest()}
                lookup._shards = {(kind, "aa"): binding}
                original = loader.json.loads
                checks = []
                with (patch.object(loader.json, "loads", wraps=original) as decode,
                      patch.object(Path, "read_bytes", side_effect=AssertionError("must stream shard"))):
                    selected = lookup._read_matching_shard_records(
                        kind, "aa", matching_keys={matching_key}, maximum_matching_records=8192,
                        check=lambda: checks.append(True),
                    )
                self.assertEqual(selected, (target, target))
                self.assertEqual(decode.call_count, 2)
                self.assertGreater(len(checks), 2)
                self.assertLess(len(checks), 300)  # Bounded periodic checks, not per-record parsing.
                self.assertIsNone(lookup._read_matching_shard_records(
                    kind, "aa", matching_keys={matching_key}, maximum_matching_records=1,
                ))
                # Overflow must not bypass a late unmatched byte-seal failure.
                path.write_bytes(payload.replace(unrelated_key.encode(), row_key.encode(), 1))
                with self.assertRaisesRegex(ContractValidationError, "seal mismatch"):
                    lookup._read_matching_shard_records(
                        kind, "aa", matching_keys={matching_key}, maximum_matching_records=1,
                    )
                path.write_bytes(payload)
                binding["record_count"] += 1
                with self.assertRaisesRegex(ContractValidationError, "count mismatch"):
                    lookup._read_matching_shard_records(kind, "aa", matching_keys={matching_key})
                binding["record_count"] -= 1
                binding["size_bytes"] += 1
                with self.assertRaisesRegex(ContractValidationError, "seal mismatch"):
                    lookup._read_matching_shard_records(kind, "aa", matching_keys={matching_key})

    def test_source_shard_prefilter_deadline_never_returns_unsealed_shortlist(self):
        matching_key, other_key, row_key = (sha256_json(value) for value in ("anchor", "other", "row"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "values" / "aa.jsonl"
            path.parent.mkdir()
            payload = (json.dumps([matching_key, row_key, False]).encode() + b"\n"
                       + (json.dumps([other_key, row_key, False]).encode() + b"\n") * 1000)
            path.write_bytes(payload)
            lookup = object.__new__(loader._IngestionExactCellLookup)
            lookup._directory = root
            lookup._shards = {("value", "aa"): {"size_bytes": len(payload), "record_count": 1001,
                              "sha256": "sha256:" + hashlib.sha256(payload).hexdigest()}}
            checks = []

            def check():
                checks.append(True)
                if len(checks) == 4:
                    raise RuntimeError("synthetic deadline after shortlisted record")

            original = loader.json.loads
            with patch.object(loader.json, "loads", wraps=original) as decode:
                with self.assertRaisesRegex(RuntimeError, "synthetic deadline"):
                    lookup._read_matching_shard_records(
                        "value", "aa", matching_keys={matching_key}, maximum_matching_records=8192, check=check,
                    )
            self.assertEqual(decode.call_count, 1)

    def _assert_neighbor_context(self, *, family, mail_tool):
        identifier = "SYNTH-REQ-042"
        name = "Elara workshop"
        field = "Dispatch window: 2031-04-17."
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(
                Path(directory), families=(family,),
                mail_text=f"{identifier} {name}\n\n{field}",
                document_text=f"# {identifier} {name}\n\n{field}\n",
            )
            revision = issue56_sealed_source.load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            handler = loader._build_source_start_semantic_handler(revision, mail_tool=mail_tool)
            query = f"Find dispatch window for {identifier} {name}"
            arguments = {
                "query_text": query, "required_terms": [identifier, name],
                "requester_user_id": loader.APPROVER_ACTOR,
                "workspace_id": loader.WORKSPACE_ID, "session_id": "synthetic-context",
                "request_contract": {
                    "original_query_hash": sha256_json(query), "query_class": "evidence_lookup",
                    "source_family_scope": [family], "requested_fields": ["dispatch_window"],
                    "maximum_claim_strength": "cited_evidence",
                },
            }
            if mail_tool:
                arguments["mail_import_session_id"] = revision.source_records.authorized_mail_import_session_ids[0]
                arguments["limit"] = 8
            result = handler(arguments)
            self.assertEqual(result["status"], "ok")
            evidence = result["evidence_snippets" if mail_tool else "evidence"]
            anchor = next(item for item in fixture.observations if identifier in (item.text or ""))
            neighbor = next(item for item in fixture.observations if item.text == field)
            anchor_hash, neighbor_hash = (sha256_json(item.to_dict()) for item in (anchor, neighbor))
            context = next(item for item in evidence if item["citation_hash"] == neighbor_hash)
            self.assertEqual(context["source_context"], {
                "relationship": "same_source_neighbor", "anchor_citation_hash": anchor_hash,
                "anchor_source_observation_id": anchor.observation_id,
                "identifier_hit": False, "exact_field_proof": False,
            })
            self.assertIn(field, context["snippet"])
            self.assertTrue(context["occurrence_lineage_fingerprint"])
            self.assertTrue(any(item["citation_hash"] == anchor_hash and "source_context" not in item for item in evidence))
            if mail_tool:
                self.assertTrue(any(item["source_observation_id"] == neighbor.observation_id for item in result["citations"]))
                self.assertEqual(result["requested_field_coverage"]["supported_fields"], [])
            else:
                self.assertIn(neighbor_hash, result["citations"])
                self.assertEqual(context["document_locator"]["line_start"], 3)
                self.assertIsNone(result["exact_result"])
                self.assertEqual(result["coverage"]["status"], "incomplete")
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            compact_items = compact["evidence_snippets" if mail_tool else "evidence"]
            compact_context = next(item for item in compact_items if field in item.get("snippet", ""))
            self.assertIn(anchor.observation_id, compact_context["snippet"])
            self.assertIn("not an identifier hit or exact field proof", compact_context["snippet"])
            # Neighbor text cannot independently satisfy the anchor constraints.
            miss = handler({**arguments, "required_terms": [identifier, "unmatched synthetic name"]})
            self.assertFalse(miss["citations"])
            with patch.object(revision.source_records, "scan_neighbor_context") as context_reader:
                exact = handler({**arguments, "request_contract": {
                    **arguments["request_contract"], "query_class": "exact_set_or_inventory",
                    "maximum_claim_strength": "complete_authorized_scope",
                }})
                context_reader.assert_not_called()
            if family == "mail":
                # SPEC §7.5 mail-occurrence execution: one protected identifier in
                # mail-only scope may list found occurrences, never a complete set.
                self.assertIn(exact["status"], {"partial", "pending_review"})
                self.assertNotEqual((exact.get("coverage") or {}).get("status"), "complete")
                self.assertFalse((exact.get("coverage") or {}).get("absence_claim", False))
            else:
                self.assertEqual(exact["status"], "pending_review")
                self.assertFalse(exact["citations"])

    def test_source_start_mail_segment_anchor_gets_separately_cited_neighbor(self):
        self._assert_neighbor_context(family="mail", mail_tool=True)

    def test_source_start_real_plain_text_heading_gets_separately_cited_neighbor(self):
        self._assert_neighbor_context(family="document_text", mail_tool=False)

    def test_source_start_context_shares_shortlist_deadline_read_and_evidence_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(
                Path(directory), families=("document_text",),
                document_text="# SYNTH-REQ-083\n\nWindow: review pending.\n\nOwner: review team.\n\nState: draft.\n",
            )
            revision = issue56_sealed_source.load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            records = revision.source_records
            authority = records.job_authorities[0]
            # Put the anchored heading last: the lexical shortlist, not the
            # linear pass, must deliver its context while budget remains.
            records.observation_references.reverse()
            anchor = fixture.observations[0]
            anchor_hash = sha256_json(anchor.to_dict())
            records.runtime_store = SimpleNamespace(
                source_family_lexical_lookup=lambda *args, **kwargs: [anchor_hash],
                helper_for_hash=lambda value: {
                    "observation_id": anchor.observation_id, "observation_hash": anchor_hash,
                    "reference": {"job_index": 0, "job_fingerprint": authority.job_fingerprint},
                    "permission_scope": dict(authority.permission_scope),
                    "source_scope_id": dict(authority.permission_scope)["scope_id"],
                },
            )
            handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
            arguments = {
                "query_text": "SYNTH-REQ-083", "required_terms": ["SYNTH-REQ-083"],
                "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
                "session_id": "synthetic-context-caps", "page_size": 2,
            }
            get = authority.observation_store.get
            context_read = records.scan_neighbor_context
            with (
                patch.object(authority.observation_store, "get", wraps=get) as read,
                patch.object(records, "scan_authorized_observations", wraps=records.scan_authorized_observations) as scan,
                patch.object(records, "scan_neighbor_context", wraps=context_read) as context,
                patch("formowl_retrieval.gateway.SOURCE_EVIDENCE_OBSERVATION_LIMIT", 3),
            ):
                result = handler(arguments)
            self.assertEqual(len(result["evidence"]), 2)
            self.assertNotIn("source_context", result["evidence"][0])
            self.assertIn("source_context", result["evidence"][1])
            self.assertEqual(read.call_count, 2)
            self.assertEqual(context.call_count, 1)  # Never recurse on neighbors.
            self.assertEqual(context.call_args.kwargs["max_observations"], 2)
            recovery = result["query_agent"]["context_bundle"]["source_recovery"]
            self.assertEqual(recovery["scan"]["scanned_observation_count"], 2)
            self.assertFalse(recovery["scan"]["complete"])
            self.assertEqual(context.call_args.kwargs["deadline_monotonic"], scan.call_args.kwargs["deadline_monotonic"])
            with patch.object(authority.observation_store, "get", wraps=get) as read, patch("formowl_retrieval.gateway.SOURCE_EVIDENCE_OBSERVATION_LIMIT", 2):
                capped = handler({**arguments, "page_size": 10})
            self.assertEqual(read.call_count, 2)
            self.assertEqual(len(capped["evidence"]), 2)
            self.assertEqual(capped["coverage"]["status"], "incomplete")

    def test_source_start_shortlist_uses_tokenized_required_terms_for_both_families(self):
        from formowl_retrieval.gateway import current_source_evidence_query_terms

        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(Path(directory))
            revision = issue56_sealed_source.load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            profile = loader.load_issue56_target_mail_tokenizer_profile()
            focus = ["written owner", "approval"]
            expected_terms = tuple(sorted({
                token for term in focus for token in profile.analyze(term).tokens
            }))
            query = (
                "Find written owner approval evidence and organize the relevant "
                "records with dates, subjects, explanations and source citations."
            )
            original_scan = revision.source_records.scan_authorized_observations
            seen_terms = []

            def observe_scan(**kwargs):
                seen_terms.append(current_source_evidence_query_terms())
                return original_scan(**kwargs)

            for family in ("mail", "document_text"):
                with self.subTest(family=family):
                    handler = loader._build_source_start_semantic_handler(
                        revision, mail_tool=False,
                    )
                    arguments = {
                        "query_text": query,
                        "required_terms": focus,
                        "requester_user_id": loader.APPROVER_ACTOR,
                        "workspace_id": loader.WORKSPACE_ID,
                        "session_id": "source-focus-regression",
                        "request_contract": {
                            "original_query_hash": sha256_json(query),
                            "query_class": "evidence_lookup",
                            "source_family_scope": [family],
                            "requested_fields": ["acceptance_condition"],
                            "maximum_claim_strength": "cited_evidence",
                        },
                    }
                    with patch.object(
                        revision.source_records, "scan_authorized_observations",
                        side_effect=observe_scan,
                    ):
                        result = handler(arguments)
                    self.assertEqual(seen_terms[-1], expected_terms)
                    self.assertEqual(current_source_evidence_query_terms(), ())
                    self.assertEqual(result["status"], "ok")
                    self.assertTrue(result["citations"])
                    hashes = {sha256_json(item.to_dict()) for item in fixture.observations}
                    self.assertTrue(all(
                        item["citation_hash"] in hashes for item in result["evidence"]
                    ))
                    # Shortlist hints do not relax the conjunctive evidence matcher.
                    missed = handler({**arguments, "required_terms": [*focus, "absentphrase"]})
                    self.assertEqual(missed["status"], "pending_review")
                    self.assertFalse(missed["citations"])

    """Preparation loader -> production composition -> ordinary OAuth MCP."""

    async def test_source_start_exhaustion_stops_bound_provider_turn_after_one_mcp(self):
        for family, label in (("mail", "mail"), ("document_text", "document")):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                register_asset = register_asset_from_local_file

                def register_capture(*args, **kwargs):
                    kwargs.pop("source_ref", None)
                    return register_asset(*args, **kwargs)

                with patch(__name__ + ".register_asset_from_local_file", side_effect=register_capture):
                    fixture = _source_start_preparation_fixture(root, families=(family,))
                revision, runtime, principal, actor = await self._compose(root, fixture)
                prompt = f"Find {label} evidence for written owner approval"
                query = "written owner approval"
                original_hash = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
                contract = {
                    "original_query_hash": original_hash,
                    "query_class": "evidence_lookup",
                    "source_family_scope": [family],
                    "requested_fields": ["acceptance_condition"],
                    "maximum_claim_strength": "cited_evidence",
                }
                planned = {
                    "status": "completed", "output": [{
                        "type": "function_call", "call_id": "source-start-exhaustion",
                        "name": "query_effective_graph_view",
                        "arguments": json.dumps({
                            "query_text": query, "required_terms": [query],
                            "request_contract": contract,
                        }),
                    }],
                }
                provider = human_uat_orchestrator.CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1", api_key="synthetic-exhaustion-key",
                )
                requests, payloads = [], []
                reader = Mock(return_value=RevisionOwnedMailSourceScan((), 0, False, "deadline"))
                try:
                    descriptor, capabilities = _query_agent_runtime_context(
                        runtime.application, user_text=prompt,
                    )
                    self.assertEqual(descriptor["name"], "query_effective_graph_view")
                    with (
                        patch.object(runtime.bridge, "authenticate_access_token", return_value=principal),
                        patch.object(runtime.bridge, "resolve_actor_context", return_value=actor),
                        patch.object(runtime.bridge, "record_mcp_authorization_decision", return_value=None),
                        patch.object(revision.source_records, "scan_authorized_observations", reader),
                        TestClient(runtime.application.app, raise_server_exceptions=False) as client,
                        patch.object(provider, "_request_response", side_effect=[
                            planned, AssertionError("exhausted source must not continue provider"),
                        ]) as provider_call,
                    ):
                        def evidence_tool(request):
                            requests.append(request)
                            response = client.post(
                                "/mcp",
                                headers={
                                    "Authorization": "Bearer synthetic.token",
                                    "Accept": "application/json, text/event-stream",
                                    "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                                },
                                json=_mcp_query_request(request),
                            )
                            self.assertEqual(response.status_code, 200)
                            result = response.json()["result"]
                            self.assertFalse(result["isError"], result)
                            payload = result["structuredContent"]["data"]
                            payloads.append(payload)
                            return payload

                        outcome = provider.respond(
                            history=(), user_text=prompt, latest_evidence=None,
                            safety_identifier="source-start-exhaustion-test",
                            evidence_tool=evidence_tool, formowl_tool_descriptor=descriptor,
                            authorized_capability_summary=capabilities,
                        )
                    self.assertEqual(provider_call.call_count, 1)
                    self.assertEqual(len(requests), 1)
                    reader.assert_called_once()
                    payload = payloads[0]
                    agent = payload["query_agent"]
                    self.assertEqual(agent["original_query_hash"], original_hash)
                    self.assertEqual(agent["request_contract"], requests[0].request_contract)
                    self.assertNotEqual(agent["original_query_hash"], sha256_json(query))
                    recovery = agent["context_bundle"]["source_recovery"]
                    self.assertEqual(recovery["query_hash"], sha256_json(query))
                    self.assertEqual(recovery["source_family_scope"], [family])
                    self.assertEqual(recovery["scan"], {
                        "scanned_observation_count": 0, "complete": False, "stop_reason": "deadline",
                    })
                    self.assertEqual(payload["status"], "pending_review")
                    self.assertEqual(payload["citations"], [])
                    self.assertEqual(outcome.response_kind, "clarification")
                    self.assertEqual(outcome.coverage_status, "incomplete")
                    self.assertEqual(outcome.citation_ids, ())
                    self.assertIn("這不代表資料不存在", outcome.answer_text)
                    self.assertTrue(human_uat_orchestrator._source_fallback_exhausted(
                        requests[0], payload,
                    ))
                    for change in (
                        "missing_original", "wrong_original", "wrong_query", "wrong_scope",
                        "exact", "permission_denied", "provider_error", "unattempted",
                    ):
                        with self.subTest(family=family, change=change):
                            rejected = copy.deepcopy(payload)
                            candidate = requests[0]
                            changed_agent = rejected["query_agent"]
                            changed_recovery = changed_agent["context_bundle"]["source_recovery"]
                            if change == "missing_original":
                                changed_agent.pop("original_query_hash")
                            elif change == "wrong_original":
                                changed_agent["original_query_hash"] = sha256_json("unrelated request")
                            elif change == "wrong_query":
                                changed_recovery["query_hash"] = sha256_json("unrelated query")
                            elif change == "wrong_scope":
                                changed_recovery["source_family_scope"] = [
                                    "document_text" if family == "mail" else "mail",
                                ]
                            elif change == "exact":
                                candidate = replace(candidate, exact_field="synthetic_field")
                            elif change == "permission_denied":
                                rejected["status"] = "permission_denied"
                            elif change == "provider_error":
                                changed_agent["stop_reason"] = "provider_error"
                            else:
                                changed_recovery["attempted"] = False
                            self.assertFalse(human_uat_orchestrator._source_fallback_exhausted(
                                candidate, rejected,
                            ))
                finally:
                    provider.close()
                    await runtime.aclose()

    async def test_factory_freezes_validated_source_identity_across_mail_text_and_reporting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(root)
            model = Mock()
            selected_family = "mail"
            mcp_payloads = []
            arbitrary = "sha256:" + "e" * 64

            def respond(*, user_text, evidence_tool, **_kwargs):
                result = evidence_tool(human_uat_orchestrator.UatEvidenceToolRequest(
                    query_text="written owner approval", required_terms=("written owner approval",),
                    request_contract={
                        "original_query_hash": sha256_json(user_text), "query_class": "evidence_lookup",
                        "source_family_scope": [selected_family],
                        "requested_fields": ["acceptance_condition"],
                        "maximum_claim_strength": "cited_evidence",
                    },
                ))
                mcp_payloads.append(result)
                return human_uat_orchestrator.UatConversationOutcome(
                    response_kind="answer", answer_text="The source requires written owner approval.",
                    citation_ids=human_uat_orchestrator.evidence_citation_ids(result),
                    display_format="narrative", model_name="codex-responses:gpt-5.5",
                    coverage_status="incomplete", coverage_note="Bounded source evidence.",
                    provider_diagnostic={
                        "provider_attempt_count": 2,
                        "provider_attempts": [_binding_attempt(1), _binding_attempt(2, tool_choice="none")],
                        "source_binding_fingerprint": arbitrary,
                        "code_binding_fingerprint": arbitrary, "build_binding_fingerprint": arbitrary,
                        "diagnostic_comparability": {"status": "comparable", "claim_scope": "uat",
                                                     "missing_bindings": [], "missing_fields": []},
                        "raw": "binding-private-sentinel",
                    },
                )

            model.respond.side_effect = respond
            with (
                patch.object(issue56_sealed_source, "load_issue56_target_runtime_components",
                             return_value=fixture.runtime),
                patch.object(hybrid, "_load_pinned_issue56_runtime_components", return_value=fixture.runtime),
                patch.object(issue56_sealed_source, "build_issue56_ingestion_revision",
                             side_effect=AssertionError("reporting must not build a revision")),
                patch.object(hybrid, "build_authorized_semantic_observation_session",
                             side_effect=AssertionError("reporting must not rebuild retrieval")),
                patch.object(hybrid, "build_authorized_source_backed_effective_graph_view",
                             side_effect=AssertionError("reporting must not build graph")),
                patch.object(type(fixture.runtime.dense_encoder), "encode_evidence_batch",
                             side_effect=AssertionError("reporting must not embed")),
                patch.object(type(fixture.runtime.dense_encoder), "encode_query",
                             side_effect=AssertionError("source-only route must not embed")),
                patch.object(ObservationStore, "create",
                             side_effect=AssertionError("reporting must not rewrite Observations")),
            ):
                revision = issue56_sealed_source.load_issue56_ingestion_revision(
                    fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                )
                frozen = sha256_json(copy.deepcopy(dict(revision.safe_binding)))
                with create_issue56_temporary_lan_query_service(
                    model, ingestion_revision=revision,
                ) as service, _RunningSurface(service) as surface:
                    session_id, _ = service.ensure_browser_session(None)
                    cookie = f"formowl_uat_session={session_id}"
                    expected_diagnostics = []
                    for selected_family in ("mail", "document_text"):
                        with self.subTest(family=selected_family):
                            response, body = surface.request_json(
                                "/api/chat", {"prompt": f"Find {selected_family} evidence for written owner approval",
                                              "source_binding_fingerprint": arbitrary,
                                              "diagnostic_comparability": {"status": "comparable"}},
                                cookie=cookie,
                            )
                            self.assertEqual(response.status, 200)
                            result = json.loads(body)
                            self.assertEqual(result["status"], "partial", result)
                            self.assertTrue(result["citations"])
                            self.assertEqual(service.request_count, 1)
                            self.assertEqual(mcp_payloads[-1]["status"], "ok")
                            self.assertEqual(mcp_payloads[-1]["coverage"]["status"], "incomplete")
                            safe = result["diagnostic"]
                            self.assertEqual(safe["source_binding_fingerprint"], frozen)
                            self.assertEqual(safe["tool_choice"], safe["provider_attempts"][-1]["tool_choice"])
                            self.assertIs(safe["provider_attempts"][-1]["valid_attempt"], True)
                            comparison = safe["diagnostic_comparability"]
                            self.assertEqual(comparison["status"], "incomparable")
                            self.assertEqual(comparison["claim_scope"], "diagnostic_only")
                            self.assertEqual(set(comparison["missing_bindings"]), {"deployment", "code", "build"})
                            self.assertEqual(comparison["missing_fields"], [])
                            self.assertNotIn(arbitrary, json.dumps(safe))
                            self.assertNotIn("binding-private-sentinel", body.decode())
                            self.assertNotIn(str(root), body.decode())
                            expected_diagnostics.append(safe)
                            # Nested metadata remains mutable; the service's loaded identity must not.
                            revision.safe_binding["extraction_coverage"]["warning_count"] += 1
                            self.assertNotEqual(sha256_json(dict(revision.safe_binding)), frozen)
                            with (
                                patch.object(revision.source_records, "scan_authorized_observations",
                                             side_effect=AssertionError("transcript must not fetch source")),
                                patch.object(revision.source_records, "get_observation",
                                             side_effect=AssertionError("transcript must not load source")),
                            ):
                                reload_response, reloaded = surface.request(
                                    "GET", "/api/transcript", headers={"Cookie": cookie},
                                )
                                self.assertEqual(reload_response.status, 200)
                                turns = json.loads(reloaded)["turns"]
                                self.assertEqual([t["response"]["diagnostic"] for t in turns], expected_diagnostics)
                                self.assertNotIn(str(root), reloaded.decode())
                    # Source-binding reporting cannot turn ordinary chat into a source fetch/MCP call.
                    model.respond.side_effect = None
                    model.respond.return_value = human_uat_orchestrator.UatConversationOutcome(
                        response_kind="answer", answer_text="hello", citation_ids=(),
                        display_format="narrative", model_name="codex-responses:gpt-5.5",
                        coverage_status="not_applicable", coverage_note="",
                    )
                    with (
                        patch.object(service, "_call", side_effect=AssertionError("chat must be MCP0")),
                        patch.object(revision.source_records, "scan_authorized_observations",
                                     side_effect=AssertionError("chat reporting must not fetch source")),
                        patch.object(revision.source_records, "get_observation",
                                     side_effect=AssertionError("chat reporting must not load source")),
                    ):
                        chat = service.ask("hello", session_id=session_id)
                    self.assertEqual(chat["status"], "complete")
                    self.assertEqual(service.request_count, 0)
                    self.assertEqual(chat["diagnostic"]["source_binding_fingerprint"], frozen)
                    self.assertEqual(chat["diagnostic"]["diagnostic_comparability"]["status"], "incomparable")

    async def _compose(self, root, fixture):
        with (
            patch.object(issue56_sealed_source, "load_issue56_target_runtime_components",
                         return_value=fixture.runtime),
            patch.object(hybrid, "_load_pinned_issue56_runtime_components",
                         return_value=fixture.runtime),
        ):
            revision = issue56_sealed_source.load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            graph, mail = loader.build_issue56_production_semantic_handlers(
                ingestion_revision=revision,
            )
        runtime_root = root / "runtime"
        runtime_root.mkdir()
        config = ConnectedRuntimeConfig.from_env_and_secrets(
            _write_runtime_environment(runtime_root),
        )
        gateway = SemanticMcpGateway(
            retrieval_handler=graph, mail_evidence_handler=mail,
            upload_session_handler=build_mail_upload_session_handler(
                upload_session_store=UploadSessionStore(config.data_dir),
                audit_store=FileAuditLogStore(config.data_dir),
                expires_at_provider=lambda: "2030-01-01T00:00:00+00:00",
            ),
        )
        with patch.object(runtime_module.PostgreSQLOAuthRepository, "connect",
                          return_value=_FakeRepository()):
            runtime = await ConnectedRuntime.compose(
                config, semantic_gateway=gateway, http_client=_FakeHttpClient(),
            )
        runtime.preflight = AsyncMock(return_value={"status": "ready"})
        principal, actor = _oauth_context(config)
        return revision, runtime, principal, actor

    def _post(self, client, *, family, tool="query_effective_graph_view", selector=None,
              query="written owner approval", requested_fields=("acceptance_condition",),
              query_class="evidence_lookup"):
        arguments = {
            "query_text": query, "required_terms": [query],
            "request_contract": {
                "original_query_hash": sha256_json(query),
                "query_class": query_class,
                "source_family_scope": list(family),
                "requested_fields": list(requested_fields),
                "maximum_claim_strength": (
                    "complete_authorized_scope"
                    if query_class == "exact_set_or_inventory" else "cited_evidence"
                ),
            },
        }
        if selector is not None:
            arguments["mail_import_session_id"] = selector
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer synthetic.token",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
            },
            json={
                "jsonrpc": "2.0", "id": sha256_json({"tool": tool, "query": query}),
                "method": "tools/call", "params": {"name": tool, "arguments": arguments},
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["result"]

    async def test_preparation_mail_and_independent_text_return_source_bound_mcp_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(root)
            with (
                patch.object(issue56_sealed_source, "build_issue56_ingestion_revision",
                             side_effect=AssertionError("MCP must not build a revision")),
                patch.object(hybrid, "build_authorized_semantic_observation_session",
                             side_effect=AssertionError("MCP must not rebuild retrieval")),
                patch.object(hybrid, "build_authorized_source_backed_effective_graph_view",
                             side_effect=AssertionError("MCP must not build a graph")),
                patch.object(type(fixture.runtime.dense_encoder), "encode_evidence_batch",
                             side_effect=AssertionError("MCP must not embed source")),
                patch.object(type(fixture.runtime.dense_encoder), "encode_query",
                             side_effect=AssertionError("source-native route must not embed")),
                patch.object(ObservationStore, "create",
                             side_effect=AssertionError("MCP must not rewrite source Observations")),
            ):
                revision, runtime, principal, actor = await self._compose(root, fixture)
                try:
                    with (
                        patch.object(runtime.bridge, "authenticate_access_token", return_value=principal),
                        patch.object(runtime.bridge, "resolve_actor_context", return_value=actor),
                        patch.object(runtime.bridge, "record_mcp_authorization_decision", return_value=None),
                        TestClient(runtime.application.app, raise_server_exceptions=False) as client,
                    ):
                        for family in ("mail", "document_text"):
                            with self.subTest(source_family=family):
                                result = self._post(client, family=(family,))
                                self.assertFalse(result["isError"], result)
                                self.assertNotIn(str(root), json.dumps(result))
                                payload = result["structuredContent"]["data"]
                                self.assertEqual(payload["status"], "ok", payload)
                                self.assertEqual(payload["coverage"]["status"], "incomplete")
                                observation = next(
                                    item for item in fixture.observations
                                    if item.observation_type == (
                                        "email_body_segment" if family == "mail" else "paragraph"
                                    )
                                )
                                evidence = next(
                                    item for item in payload["evidence"]
                                    if item["citation_hash"] == sha256_json(observation.to_dict())
                                )
                                self.assertIn("written owner approval", evidence["snippet"])
                                self.assertEqual(
                                    evidence["occurrence_lineage_fingerprint"],
                                    source_occurrence_lineage_from_observation(
                                        observation, authorized_source=revision.authorized_source,
                                    ).lineage_fingerprint,
                                )
                                self.assertEqual(evidence["revision_binding"], {
                                    "source_authority_fingerprint": revision.safe_binding[
                                        "source_authority_fingerprint"
                                    ],
                                    "source_session_binding_fingerprint": revision.safe_binding[
                                        "source_session_binding_fingerprint"
                                    ],
                                })
                                if family == "mail":
                                    self.assertEqual(
                                        evidence["source_scope_fingerprint"],
                                        sha256_json(
                                            revision.source_records.authorized_mail_import_session_ids[0]
                                        ),
                                    )
                                recovery = payload["query_agent"]["context_bundle"]["source_recovery"]
                                self.assertTrue(recovery["attempted"])
                                # A free-text match is not structured field proof or exhaustive coverage.
                                self.assertIn(
                                    sha256_json("acceptance_condition"),
                                    payload["query_agent"]["context_bundle"]["missing_field_hashes"],
                                )
                                if family == "document_text":
                                    self.assertEqual(evidence["document_locator"], {
                                        "block_type": "paragraph", "asset_id": observation.asset_id,
                                        "extractor_run_id": observation.extractor_run_id,
                                        "line_start": 3, "line_end": 4,
                                    })
                                    self.assertNotIn("mail_import_session_id", evidence)
                        selector = revision.source_records.authorized_mail_import_session_ids[0]
                        result = self._post(
                            client, family=("mail",), tool="query_mail_evidence", selector=selector,
                        )
                        self.assertFalse(result["isError"], result)
                        mail = result["structuredContent"]["data"]
                        self.assertEqual(mail["status"], "ok", mail)
                        self.assertTrue(mail["citations"])
                        body = next(item for item in fixture.observations
                                    if item.observation_type == "email_body_segment")
                        self.assertEqual(
                            mail["evidence_snippets"][0]["source_observation_hash"],
                            sha256_json(body.to_dict()),
                        )
                        self.assertEqual(
                            mail["evidence_snippets"][0]["mail_import_session_id"], selector,
                        )
                        message = next(item for item in fixture.observations
                                       if item.observation_type == "email_message")
                        self.assertEqual(
                            mail["evidence_snippets"][0]["email_message_id"],
                            stable_resource_contract_id(
                                "emailmsg", "EmailMessage",
                                {"message_fingerprint": message.payload["message_fingerprint"]},
                            ),
                        )
                        self.assertFalse(mail["requested_field_coverage"]["absence_claim"])
                finally:
                    await runtime.aclose()

    async def test_captured_mail_uses_source_neutral_graph_fallback_without_selector(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            register_asset = register_asset_from_local_file

            def register_captured_source(*args, **kwargs):
                kwargs.pop("source_ref", None)
                return register_asset(*args, **kwargs)

            with patch(
                __name__ + ".register_asset_from_local_file",
                side_effect=register_captured_source,
            ):
                fixture = _source_start_preparation_fixture(root, families=("mail",))
            revision, runtime, principal, actor = await self._compose(root, fixture)
            try:
                self.assertEqual(
                    revision.source_records.authorized_mail_import_session_ids,
                    (),
                )
                self.assertNotIn(
                    "query_mail_evidence",
                    runtime.application.dispatcher.enabled_tool_names,
                )
                descriptor, capabilities = _query_agent_runtime_context(
                    runtime.application,
                    user_text="Find mail evidence for written owner approval",
                )
                self.assertEqual(descriptor["name"], "query_effective_graph_view")
                self.assertEqual(capabilities["selector_count"], 0)
                self.assertNotIn("authorized_mail_import_session_ids", capabilities)
                self.assertNotIn("mail_selector_kind", capabilities)

                with (
                    patch.object(runtime.bridge, "authenticate_access_token", return_value=principal),
                    patch.object(runtime.bridge, "resolve_actor_context", return_value=actor),
                    patch.object(runtime.bridge, "record_mcp_authorization_decision", return_value=None),
                    TestClient(runtime.application.app, raise_server_exceptions=False) as client,
                ):
                    result = self._post(
                        client,
                        family=("mail",),
                        tool="query_effective_graph_view",
                        requested_fields=(),
                        query="written owner approval",
                    )
                self.assertFalse(result["isError"], result)
                payload = result["structuredContent"]["data"]
                self.assertEqual(payload["status"], "ok", payload)
                observation = next(
                    item for item in fixture.observations
                    if item.observation_type == "email_body_segment"
                )
                evidence = next(
                    item for item in payload["evidence"]
                    if item["citation_hash"] == sha256_json(observation.to_dict())
                )
                self.assertIn("written owner approval", evidence["snippet"])
                self.assertNotIn("mail_import_session_id", evidence)
                self.assertEqual(
                    evidence["source_scope_fingerprint"],
                    sha256_json(to_plain(observation.permission_scope)["scope_id"]),
                )
                self.assertEqual(
                    evidence["occurrence_lineage_fingerprint"],
                    source_occurrence_lineage_from_observation(
                        observation, authorized_source=revision.authorized_source,
                    ).lineage_fingerprint,
                )
            finally:
                await runtime.aclose()

    async def test_preparation_mcp_shares_cap_deadline_and_never_turns_incomplete_into_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(root)
            revision, runtime, principal, actor = await self._compose(root, fixture)
            scans = []

            def scan_source(**kwargs):
                complete = kwargs["source_family"] == "mail"
                scan = RevisionOwnedMailSourceScan(
                    observations=(),
                    scanned_observation_count=1 if complete else kwargs["max_observations"],
                    complete=complete, stop_reason=None if complete else "observation_limit",
                )
                scans.append(scan)
                return scan

            reader = Mock(side_effect=scan_source)
            try:
                with (
                    patch.object(runtime.bridge, "authenticate_access_token", return_value=principal),
                    patch.object(runtime.bridge, "resolve_actor_context", return_value=actor),
                    patch.object(runtime.bridge, "record_mcp_authorization_decision", return_value=None),
                    patch.object(revision.source_records, "scan_authorized_observations", reader),
                    TestClient(runtime.application.app, raise_server_exceptions=False) as client,
                ):
                    result = self._post(client, family=("mail", "document_text"))
                    self.assertFalse(result["isError"], result)
                    payload = result["structuredContent"]["data"]
                    self.assertEqual(payload["status"], "pending_review", payload)
                    self.assertEqual(payload["citations"], [])
                    self.assertEqual(
                        {call.kwargs["source_family"] for call in reader.call_args_list},
                        {"mail", "document_text"},
                    )
                    self.assertLessEqual(sum(scan.scanned_observation_count for scan in scans), 8192)
                    self.assertLessEqual(
                        reader.call_args_list[-1].kwargs["max_observations"], 8191,
                    )
                    deadlines = [call.kwargs["deadline_monotonic"] for call in reader.call_args_list]
                    self.assertEqual(len(set(deadlines)), 1)
                    self.assertFalse(
                        payload["query_agent"]["context_bundle"]["source_recovery"]["scan"]["complete"],
                    )
                    self.assertEqual(
                        payload["query_agent"]["context_bundle"]["source_recovery"]["scan"][
                            "scanned_observation_count"
                        ],
                        sum(scan.scanned_observation_count for scan in scans),
                    )
                    reader.reset_mock()
                    with source_evidence_deadline_scope(0.0):
                        expired = self._post(client, family=("mail", "document_text"))
                    self.assertFalse(expired["isError"], expired)
                    self.assertEqual(expired["structuredContent"]["data"]["status"], "pending_review")
                    self.assertEqual(expired["structuredContent"]["data"]["citations"], [])
                    reader.assert_not_called()
                    exact = self._post(
                        client, family=("mail",), query="List all mail involving owner",
                        requested_fields=(), query_class="exact_set_or_inventory",
                    )
                    self.assertFalse(exact["isError"], exact)
                    self.assertEqual(exact["structuredContent"]["data"]["status"], "pending_review")
                    self.assertEqual(exact["structuredContent"]["data"]["citations"], [])
                    reader.assert_not_called()
                    reader.side_effect = RuntimeError("synthetic /tmp/private-source failure")
                    failed = self._post(client, family=("mail", "document_text"))
                    self.assertTrue(failed["isError"], failed)
                    self.assertNotIn("/tmp/private-source", json.dumps(failed))
                    self.assertNotIn("not_found", json.dumps(failed))
                    reader.reset_mock()
                    # Caller identity remains gateway-owned and source access
                    # fails before any reader invocation for a different actor.
                    denied_actor = replace(actor, user=replace(actor.user, user_id="user_unauthorized"))
                    with patch.object(runtime.bridge, "resolve_actor_context", return_value=denied_actor):
                        denied = self._post(client, family=("mail", "document_text"))
                    self.assertTrue(denied["isError"], denied)
                    reader.assert_not_called()
            finally:
                await runtime.aclose()

    async def test_preparation_mail_mcp_keeps_selected_selector_and_rejects_mixed_family(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(
                root, families=("mail", "mail_other", "document_text"),
            )
            revision, runtime, principal, actor = await self._compose(root, fixture)
            selectors = revision.source_records.authorized_mail_import_session_ids
            self.assertEqual(len(selectors), 2)
            selected = selectors[-1]
            reader = Mock(wraps=revision.source_records.scan_authorized_observations)
            try:
                with (
                    patch.object(runtime.bridge, "authenticate_access_token", return_value=principal),
                    patch.object(runtime.bridge, "resolve_actor_context", return_value=actor),
                    patch.object(runtime.bridge, "record_mcp_authorization_decision", return_value=None),
                    patch.object(revision.source_records, "scan_authorized_observations", reader),
                    TestClient(runtime.application.app, raise_server_exceptions=False) as client,
                ):
                    result = self._post(
                        client, family=("mail",), tool="query_mail_evidence", selector=selected,
                    )
                    self.assertFalse(result["isError"], result)
                    payload = result["structuredContent"]["data"]
                    self.assertEqual(payload["status"], "ok", payload)
                    self.assertTrue(reader.call_args_list)
                    self.assertEqual(
                        {call.kwargs["mail_import_session_id"] for call in reader.call_args_list},
                        {selected},
                    )
                    self.assertTrue(payload["evidence_snippets"])
                    self.assertEqual(
                        {item["mail_import_session_id"] for item in payload["evidence_snippets"]},
                        {selected},
                    )
                    field_coverage = payload["requested_field_coverage"]
                    self.assertEqual(field_coverage["supported_fields"], [])
                    self.assertEqual(field_coverage["missing_fields"], ["acceptance_condition"])
                    self.assertFalse(field_coverage["absence_claim"])
                    self.assertEqual(
                        field_coverage["evidence_citation_hashes"],
                        sorted(item["source_observation_hash"] for item in payload["evidence_snippets"]),
                    )
                    self.assertEqual(
                        field_coverage["coverage_fingerprint"],
                        sha256_json({
                            key: value for key, value in field_coverage.items()
                            if key != "coverage_fingerprint"
                        }),
                    )
                    reader.reset_mock()
                    mixed = self._post(
                        client, family=("mail", "document_text"),
                        tool="query_mail_evidence", selector=selected,
                    )
                    self.assertTrue(mixed["isError"], mixed)
                    reader.assert_not_called()
            finally:
                await runtime.aclose()

    async def test_preparation_mail_body_before_parent_recovers_but_missing_parent_stays_incomplete(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _source_start_preparation_fixture(
                root,
                families=("mail",),
                source_completeness_certified=True,
            )
            revision, runtime, principal, actor = await self._compose(root, fixture)
            records = revision.source_records
            observations = tuple(fixture.observations)
            body = next(
                item for item in observations
                if item.observation_type == "email_body_segment"
            )
            parent = next(
                item for item in observations
                if item.observation_type == "email_message"
            )
            references = list(records.observation_references)
            body_hash = sha256_json(body.to_dict())
            parent_hash = sha256_json(parent.to_dict())
            body_reference = next(
                reference for reference in references if reference[2] == body_hash
            )
            parent_reference = next(
                reference for reference in references if reference[2] == parent_hash
            )
            body_before_parent = [body_reference] + [
                reference for reference in references if reference != body_reference
            ]
            self.assertLess(references.index(parent_reference), references.index(body_reference))
            try:
                with (
                    patch.object(runtime.bridge, "authenticate_access_token", return_value=principal),
                    patch.object(runtime.bridge, "resolve_actor_context", return_value=actor),
                    patch.object(runtime.bridge, "record_mcp_authorization_decision", return_value=None),
                    TestClient(runtime.application.app, raise_server_exceptions=False) as client,
                ):
                    for current_references in (body_before_parent, [body_reference]):
                        with self.subTest(parent_present=len(current_references) > 1):
                            records.observation_references = current_references
                            result = self._post(
                                client,
                                family=("mail",),
                                tool="query_effective_graph_view",
                            )
                            self.assertFalse(result["isError"], result)
                            payload = result["structuredContent"]["data"]
                            self.assertEqual(payload["coverage"]["status"], "incomplete")
                            self.assertNotIn("not_found", json.dumps(payload))
                            recovery = payload["query_agent"]["context_bundle"]["source_recovery"]
                            if len(current_references) > 1:
                                self.assertEqual(payload["status"], "ok", payload)
                                self.assertTrue(payload["citations"])
                                evidence = next(item for item in payload["evidence"]
                                                if item["citation_hash"] == body_hash)
                                self.assertEqual(evidence["email_message_id"], stable_resource_contract_id(
                                    "emailmsg", "EmailMessage",
                                    {"message_fingerprint": parent.payload["message_fingerprint"]},
                                ))
                                self.assertEqual(recovery["status"], "ok")
                                self.assertTrue(recovery["scan"]["complete"])
                                continue
                            # A preceding successful request cannot lend its
                            # parent's identity to this parent-absent request.
                            self.assertEqual(payload["status"], "pending_review", payload)
                            self.assertEqual(payload["citations"], [])
                            self.assertEqual(payload["evidence"], [])
                            self.assertEqual(recovery["status"], "pending_review")
                            self.assertFalse(recovery["scan"]["complete"])
                            self.assertEqual(
                                recovery["scan"]["stop_reason"],
                                "source_parent_binding_unresolved",
                            )
            finally:
                await runtime.aclose()


def _registered_text_revision_fixture(
    temp_dir: Path,
    *,
    owner_user_id: str = "user_yifan",
    source_text: str = (
        "# Project acceptance\n\n"
        "Acceptance requires written owner approval.\n"
        "The final checklist must be complete.\n"
    ),
):
    source_path = temp_dir / "acceptance.md"
    source_path.write_text(source_text, encoding="utf-8")
    registry = StorageBackendRegistry(temp_dir)
    backend = registry.register_local_backend(
        temp_dir / "object-store",
        workspace_scope="workspace_formowl",
    )
    object_store = FileObjectStore(registry)
    asset = register_asset_from_local_file(
        source_path,
        object_store=object_store,
        asset_store=AssetStore(temp_dir),
        storage_backend_id=backend.storage_backend_id,
        workspace_id="workspace_formowl",
        owner_user_id=owner_user_id,
        permission_scope=PermissionScope.project("project_document"),
        mime_type="text/markdown",
        created_at="2026-09-01T00:00:00+00:00",
        registered_at="2026-09-01T00:00:00+00:00",
    )
    extraction = run_extractor(
        asset=asset,
        object_store=object_store,
        extractor_run_store=ExtractorRunStore(temp_dir),
        observation_store=ObservationStore(temp_dir),
        adapter=PlainTextObservationExtractor(),
        started_at="2026-09-01T00:00:00+00:00",
        completed_at="2026-09-01T00:00:00+00:00",
    )
    return asset, extraction


def _completed_registered_text_revision_fixture(
    temp_dir: Path,
    *,
    owner_user_id: str,
    source_text: str | None = None,
):
    source_path = temp_dir / "acceptance.md"
    source_path.write_text(
        source_text if source_text is not None else "# Project acceptance\n\n"
        "Acceptance requires written owner approval.\n"
        "The final checklist must be complete.\n",
        encoding="utf-8",
    )
    registry = StorageBackendRegistry(temp_dir)
    backend = registry.register_local_backend(
        temp_dir / "object-store",
        workspace_scope=loader.WORKSPACE_ID,
    )
    object_store = FileObjectStore(registry)
    asset_store = AssetStore(temp_dir)
    job_store = JobStore(temp_dir)
    run_store = ExtractorRunStore(temp_dir)
    observation_store = ObservationStore(temp_dir)
    asset = register_asset_from_local_file(
        source_path,
        object_store=object_store,
        asset_store=asset_store,
        storage_backend_id=backend.storage_backend_id,
        workspace_id=loader.WORKSPACE_ID,
        owner_user_id=owner_user_id,
        permission_scope=PermissionScope.project("project_document"),
        mime_type="text/markdown",
        created_at="2026-09-01T00:00:00+00:00",
        registered_at="2026-09-01T00:00:00+00:00",
    )
    adapter = PlainTextObservationExtractor()
    job = create_ingestion_job(
        asset=asset,
        job_store=job_store,
        requested_by=owner_user_id,
        extractor_adapters=(adapter,),
        created_at="2026-09-01T00:00:00+00:00",
    )
    completed_job = run_ingestion_job(
        ingestion_job_id=job.ingestion_job_id,
        asset_store=asset_store,
        job_store=job_store,
        object_store=object_store,
        extractor_run_store=run_store,
        observation_store=observation_store,
        extractor_adapters=(adapter,),
        started_at="2026-09-01T00:00:00+00:00",
        completed_at="2026-09-01T00:00:00+00:00",
    )
    completed_reader = open_completed_ingestion_job_reader(
        completed_job.ingestion_job_id,
        job_store=job_store,
        asset_store=asset_store,
        observation_store=observation_store,
        extractor_run_store=run_store,
        requester_user_id=owner_user_id,
        workspace_id=loader.WORKSPACE_ID,
    )
    observations = tuple(completed_reader.iter_observations())
    return asset, observations, completed_reader.authority



class CandidateFactRuntimeTests(unittest.TestCase):
    def _fixture(self, root, *, subject_only=False, family="document_text", subject_surface="ＺＸ-００７", filler_count=None, fixture_code="clienta"):
        from formowl_graph.ontology import CandidatePropertyMapping
        text = (
            f"{fixture_code.capitalize()} ZX-742 ticket R-007 expected 2031-04-02 " + ("filler " * (3000 if family == "document_text" else 0) if filler_count is None else "filler " * filler_count) +
            "\n\nTicket R-008\n\nExpected 2031-04-09" +
            ("\n\nSubject " + subject_surface if subject_only else ""))
        fixture = _source_start_preparation_fixture(root, families=(family,), document_text=text, mail_text=text)
        from scripts.issue56_source_native_lookup import build_lookup
        lookup = root / "lookup"
        build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                     output_directory=lookup)
        for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
            shutil.copyfile(lookup / name, fixture.directory / name)
        revision = issue56_sealed_source.load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256)
        mapping = CandidatePropertyMapping.from_dict({
            "artifact_id": "formowl_candidate_property_mapping_v1", "mapping_id": f"{fixture_code}_runtime",
            "review_status": "pending_review", "properties": ["asset_code", "ticket_code", "target_date"],
            "aliases": [{"label": prop, "property_id": prop, "qualifiers": {}} for prop in
                        ("asset_code", "ticket_code", "target_date")],
            "identity_groups": [{"name": "asset_ticket", "properties": ["asset_code", "ticket_code"]}]})
        annotation_revision = sha256_json("annotation-snapshot-separate-from-serving")
        rows = []
        observation_type = "paragraph" if family == "document_text" else "email_body_segment"
        observations = [o for o in fixture.observations if o.observation_type == observation_type]
        self.assertEqual(len(observations), 4 if subject_only else 3)
        for index, observation in enumerate(observations[:2]):
            digest = sha256_json(observation.to_dict())
            fields = {}
            for prop, value in (("asset_code", "ZX-742"), ("ticket_code", f"R-00{7 + index}"),
                                ("target_date", ("2031-04-02", "2031-04-09")[index])):
                source_observation = (observations[0] if index == 1 and prop == "asset_code" else
                                      observations[2] if index == 1 and prop == "target_date" else observation)
                digest = sha256_json(source_observation.to_dict())
                start = source_observation.text.index(value)
                fields[prop] = [{"value": value, "unit": None, "qualifiers": {"kind": "expected"},
                    "times": [], "unit_id": f"unit-{fixture_code}-{index}", "source_unit_id": f"su_{fixture_code}_{index}",
                    "source_revision_fingerprint": annotation_revision,
                    "permission_scope": source_observation.to_dict()["permission_scope"],
                    "permission_scope_fingerprint": sha256_json(source_observation.to_dict()["permission_scope"]),
                    "source_observation_ids": [source_observation.observation_id],
                    "observation_hashes": {source_observation.observation_id: digest},
                    "evidence_spans": [{"observation_id": source_observation.observation_id, "observation_hash": digest,
                        "field_path": ["text"], "quote": value, "occurrence_index": None,
                        "start": start, "end": start + len(value), "native_locator": source_observation.to_dict()["location"],
                        "source_extractor_run_id": source_observation.extractor_run_id}]}]
            rows.append({"artifact_id": "formowl_candidate_fact_row_v1", "row_id": f"factrow_{fixture_code}_{index}",
                "source_revision_fingerprint": annotation_revision, "mapping_fingerprint": mapping.fingerprint,
                "review_status": "pending_review", "semantic_correctness_verified": False,
                "item_or_row": str(index), "fields": fields, "identity_candidates": [],
                "outer_mail_date": {"value": "2099-12-31", "evidence": [{"quote": "unvalidated-outer-date"}] }})
        if subject_only:
            identity = observations[3]
            raw_surface = subject_surface
            start = identity.text.index(raw_surface)
            identity_hash = sha256_json(identity.to_dict())
            span = {"observation_id": identity.observation_id, "observation_hash": identity_hash,
                "field_path": ["text"], "quote": raw_surface, "occurrence_index": None,
                "start": start, "end": start + len(raw_surface), "native_locator": identity.to_dict()["location"],
                "source_extractor_run_id": identity.extractor_run_id}
            for index, row in enumerate(rows):
                row["fields"].pop("asset_code")
                sources = []
                for ordinal, typed in enumerate((False, True)):
                    target = {"value_surface": raw_surface, "evidence_spans": [span]}
                    if typed:
                        target["type_surface"] = "misleading classification"
                    sources.append({"value_surface": raw_surface, "target_identity": target, "evidence_spans": [span],
                        "candidate_atom_id": f"catom_subject_{index}_{ordinal}", "candidate_atom_hash": sha256_json([index, ordinal]),
                        "ledger_id": f"sem_subject_{index}", "ledger_hash": sha256_json([index, "ledger"]),
                        "unit_id": f"unit-{fixture_code}-{index}", "source_unit_id": f"su_{fixture_code}_{index}",
                        "source_revision_fingerprint": annotation_revision,
                        "permission_scope": identity.to_dict()["permission_scope"],
                        "permission_scope_fingerprint": sha256_json(identity.to_dict()["permission_scope"]),
                        "source_observation_ids": [identity.observation_id],
                        "observation_hashes": {identity.observation_id: identity_hash}, "unit_validation_status": "complete"})
                row["subject_identity"] = {"value": " ".join(unicodedata.normalize("NFKC", raw_surface).casefold().split()),
                    "type": None, "origin": "annotation_target",
                    "review_status": "pending_review", "semantic_correctness_verified": False, "sources": sources}
        export = root / "fact-export"
        export.mkdir()
        def write(path, value, raw=False):
            data = value if raw else json.dumps(value).encode()
            path.write_bytes(data)
            return "sha256:" + hashlib.sha256(data).hexdigest()
        rows_hash = write(export / "rows.jsonl", b"".join(json.dumps(row).encode() + b"\n" for row in rows), True)
        write(export / "mapping.snapshot.json", mapping.data)
        manifest_hash = write(export / "manifest.json", {"artifact_id": "formowl_candidate_fact_export_v1",
            "review_status": "pending_review", "semantic_correctness_verified": False,
            "source_revision": annotation_revision, "mapping_fingerprint": mapping.fingerprint,
            "rows_sha256": rows_hash, "row_count": len(rows)})
        config = {"artifact_id": "formowl_candidate_fact_runtime_config_v1",
            **{key: revision.safe_binding[key] for key in (
                "source_revision_sha256", "source_authority_fingerprint", "source_session_binding_fingerprint")},
            "exports": [{"manifest_path": str(export / "manifest.json"), "manifest_sha256": manifest_hash}]}
        config_path = root / "facts.json"
        config_hash = write(config_path, config)
        return revision, config_path, config_hash, export, observations

    @staticmethod
    def _arguments():
        return {"query_text": "Find Clienta R-008 expected date", "required_terms": ["R-008"],
            "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
            "session_id": "clienta-fact-fallback", "page_size": 10}

    def test_mail_candidate_group_uses_mail_scope_and_preserves_source_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            register_asset = register_asset_from_local_file
            def register_captured_source(*args, **kwargs):
                kwargs.pop("source_ref", None)
                return register_asset(*args, **kwargs)
            # Exercise the source-neutral captured-mail graph route used by
            # the replay; upload-session mail has a separate selector contract.
            with patch(__name__ + ".register_asset_from_local_file", side_effect=register_captured_source):
                revision, config, digest, _, observations = self._fixture(Path(directory), family="mail")
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=digest)
            self.assertTrue(bound.authorized_source.source_scope_ids)
            self.assertEqual(bound.source_records.authorized_mail_import_session_ids, ())
            with patch.object(bound.source_records, "scan_authorized_observations",
                              wraps=bound.source_records.scan_authorized_observations) as scan:
                arguments = {**self._arguments(), "required_terms": ["ZX-742"],
                    "query_text": "Find Clienta asset ZX-742 expected date"}
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(arguments)
                compact = human_uat_orchestrator.compact_evidence_for_model(result)
                # AS58 reserves the under-cap table before ordinary mail groups.
                self.assertIn("candidate_fact_group", json.dumps(compact))
                self.assertEqual(compact["evidence"][0]["source_type"], "candidate_fact_table")
                self.assertEqual(result["coverage"]["status"], "incomplete")
                for value in ("2031-04-02", "2031-04-09", "R-007", "R-008"):
                    self.assertIn(value, json.dumps(compact))
                self.assertTrue({sha256_json(o.to_dict()) for o in observations}.issubset(
                    human_uat_orchestrator.evidence_citation_ids(compact)))
                self.assertTrue(scan.call_args_list)
                for observed in scan.call_args_list:
                    self.assertEqual(observed.kwargs["source_family"], "mail")
                    self.assertEqual(observed.kwargs["source_scope_ids"], ())
                    self.assertIsNone(observed.kwargs["mail_import_session_id"])

    def test_candidate_contract_error_discards_group_and_uses_guarded_source_fallback(self):
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        with tempfile.TemporaryDirectory() as directory:
            revision, config, digest, _, _ = self._fixture(Path(directory))
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=digest)
            handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            original_scan = bound.source_records.scan_authorized_observations
            original_validate = loader.validate_public_gateway_payload
            for stage in ("scan", "payload"):
                trace = _SourcePhaseTrace({})
                injected = []
                def scan_source(**kwargs):
                    if stage == "scan" and kwargs.get("preferred_observation_hashes"):
                        callback = kwargs["observation_callback"]
                        def fail_after_projection(observation, scope):
                            callback(observation, scope)
                            injected.append(True)
                            raise ContractValidationError("synthetic /tmp/private-candidate-error")
                        kwargs = {**kwargs, "observation_callback": fail_after_projection}
                    return original_scan(**kwargs)
                def validate(payload):
                    if stage == "payload" and "evidence" in payload and "candidate_fact_group" in json.dumps(payload):
                        injected.append(True)
                        raise ContractValidationError("synthetic /tmp/private-candidate-error")
                    return original_validate(payload)
                with self.subTest(stage=stage), _source_phase_trace_scope(trace), patch.object(
                        bound.source_records, "scan_authorized_observations", side_effect=scan_source) as scan, patch.object(
                        loader, "validate_public_gateway_payload", side_effect=validate):
                    result = handler(self._arguments())
                    self.assertEqual(injected, [True])
                    self.assertTrue(result["citations"], result)
                    display = json.dumps(human_uat_orchestrator.compact_evidence_for_model(result), ensure_ascii=False)
                    self.assertIn("R-008", display)
                    self.assertNotIn("candidate_fact", display)
                    self.assertNotIn("候選事實", display)
                    self.assertNotEqual(result["status"], "not_found")
                    self.assertGreaterEqual(len(scan.call_args_list), 2)
                    first, last = scan.call_args_list[0].kwargs, scan.call_args_list[-1].kwargs
                    self.assertLess(last["max_observations"], first["max_observations"])
                    self.assertLessEqual(last["deadline_monotonic"], first["deadline_monotonic"])
                    snapshot = trace.snapshot()
                    self.assertIn("candidate_fact_contract_validation_failed", snapshot)
                    self.assertNotIn("private-candidate-error", snapshot)

    def test_candidate_fallback_does_not_swallow_other_branch_or_error_types(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, digest, _, _ = self._fixture(Path(directory))
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=digest)
            handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            def scan_source(**kwargs):
                if kwargs.get("preferred_observation_hashes"):
                    raise ContractValidationError("candidate-only rejection")
                raise ContractValidationError("ordinary source rejection")
            with patch.object(bound.source_records, "scan_authorized_observations", side_effect=scan_source), self.assertRaisesRegex(
                    ContractValidationError, "ordinary source rejection"):
                handler(self._arguments())
            with patch.object(bound.source_records, "scan_authorized_observations", side_effect=RuntimeError("other error")), self.assertRaisesRegex(
                    RuntimeError, "other error"):
                handler(self._arguments())

    def test_sealed_fact_export_to_guarded_handler_and_final_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config_path, config_hash, _, observations = self._fixture(Path(directory))
            self.assertFalse(revision.candidate_fact_rows)
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(revision,
                configuration_path=config_path, expected_sha256=config_hash)
            self.assertFalse(bound.reviewed_source_annotations)
            handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            arguments = {"query_text": "Find Clienta asset ZX-742 expected date", "required_terms": ["ZX-742"],
                "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
                "session_id": "clienta-fact-runtime", "page_size": 10}
            result = handler(arguments)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(set(result["citations"]), {sha256_json(o.to_dict()) for o in observations})
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            display = json.dumps(compact, ensure_ascii=False)
            for value in ("2031-04-02", "2031-04-09", "R-007", "R-008", "候選事實（由標註取得，未經人工審核）"):
                self.assertIn(value, display)
            self.assertNotIn("filler", display)
            self.assertNotIn("unvalidated-outer-date", display)
            self.assertNotIn("2099-12-31", display)
            self.assertFalse(issue56_sealed_source.lookup_issue56_candidate_fact_rows(
                bound, ["ZX-742"], deadline_monotonic=0))
            self.assertEqual(set(human_uat_orchestrator.evidence_citation_ids(compact)), set(result["citations"]))
            decision = {"response_kind": "answer", "citation_ids": result["citations"], "coverage_status": "incomplete"}
            human_uat_orchestrator._validate_evidence_bound_decision(decision, evidence_results=(compact,))
            with self.assertRaises(RuntimeError):
                human_uat_orchestrator._validate_evidence_bound_decision(
                    {**decision, "citation_ids": [sha256_json("unavailable-citation")]}, evidence_results=(compact,))
            single = human_uat_orchestrator.compact_evidence_for_model(result, item_limit=1)
            self.assertEqual(len(json.loads(single["evidence"][0]["snippet"].split("\n", 1)[1])["rows"]), 2)
            capped = handler({**arguments, "page_size": 1})
            self.assertEqual(len(capped["evidence"]), 1)
            self.assertEqual(len(json.loads(capped["evidence"][0]["snippet"].split("\n", 1)[1])["rows"]), 2)
            self.assertEqual(handler({**arguments, "requester_user_id": "other"})["status"], "permission_denied")
            lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
            self.assertEqual(len(lookup(bound, ["R-008"])), 1)
            self.assertEqual(len(lookup(bound, ["ZX-742", "unsupported-description"])), 2)
            self.assertFalse(lookup(bound, ["ZX742"]))
            fallback = handler({**arguments, "required_terms": ["R-008"]})
            self.assertTrue(fallback["citations"])
            miss = handler({**arguments, "query_text": "Find missing code K-999", "required_terms": ["K-999"]})
            self.assertNotIn("candidate_fact_group", json.dumps(miss))
            self.assertNotEqual(miss["status"], "not_found")
            tampered = dict(bound.candidate_fact_rows[0])
            tampered["fields"] = json.loads(json.dumps(tampered["fields"]))
            tampered["fields"]["target_date"][0]["evidence_spans"][0]["quote"] = "invented"
            damaged = replace(bound, candidate_fact_rows=(tampered,))
            fallback = loader._build_source_start_semantic_handler(damaged, mail_tool=False)(arguments)
            self.assertNotIn("candidate_fact_group", json.dumps(fallback))
            self.assertNotIn("invented", json.dumps(fallback))
            self.assertNotEqual(fallback["status"], "not_found")
            # Change original source bytes after sealing; the guarded owner must
            # reject them even though the candidate/export pins are unchanged.
            store = ObservationStore(Path(directory) / "document_text")
            path = store._store._record_path(observations[0].observation_id)
            data = json.loads(path.read_bytes())
            data["text"] += " changed"
            path.write_text(json.dumps(data))
            with self.assertRaises(ContractValidationError):
                handler(arguments)

    def test_export_tamper_and_serving_revision_pins_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config_path, config_hash, export, _ = self._fixture(Path(directory))
            binder = issue56_sealed_source.bind_issue56_candidate_fact_exports
            wrong = replace(revision, safe_binding={**revision.safe_binding, "source_revision_sha256": sha256_json("other")})
            with self.assertRaises(ContractValidationError):
                binder(wrong, configuration_path=config_path, expected_sha256=config_hash)
            with (export / "rows.jsonl").open("ab") as output:
                output.write(b" ")
            with self.assertRaises(ContractValidationError):
                binder(revision, configuration_path=config_path, expected_sha256=config_hash)



class CandidateSubjectRuntimeTests(unittest.TestCase):
    _fixture = CandidateFactRuntimeTests._fixture

    def _bound(self, directory):
        revision, path, digest, _, observations = self._fixture(Path(directory), subject_only=True)
        return issue56_sealed_source.bind_issue56_candidate_fact_exports(
            revision, configuration_path=path, expected_sha256=digest), observations

    @staticmethod
    def _arguments():
        return {"query_text": "Find Clienta ZX-007 expected date", "required_terms": ["ZX-007"],
            "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
            "session_id": "clienta-untyped-subject", "page_size": 10}

    def test_subject_only_lookup_keeps_identity_and_all_conflicting_source_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, observations = self._bound(directory)
            lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
            self.assertEqual(len(lookup(bound, [" ＺＸ-００７ "])), 2)
            self.assertFalse(lookup(bound, ["ZX007"]))
            self.assertFalse(lookup(bound, ["ZX-7"]))
            self.assertTrue(all("asset_code" not in row["fields"] for row in bound.candidate_fact_rows))
            handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            result = handler(self._arguments())
            self.assertEqual(set(result["citations"]), {sha256_json(o.to_dict()) for o in observations})
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            text = json.dumps(compact, ensure_ascii=False)
            for value in ("2031-04-02", "2031-04-09", "R-007", "R-008", "ＺＸ-００７"):
                self.assertIn(value, text)
            tables = [item for item in compact["evidence"] if item.get("source_type") == "candidate_fact_table"]
            self.assertEqual(len(tables), 1)
            table = json.loads(tables[0]["snippet"].split("\n", 1)[1])
            subjects = [row["subject"] for row in table["rows"]]
            self.assertEqual(len(subjects), 2)
            self.assertTrue(all(set(subject) == {"surfaces", "quotes"} for subject in subjects))
            self.assertNotIn("misleading classification", text)
            identity_hash = sha256_json(observations[3].to_dict())
            identity_citation = next(entry for entry in table["citations"] if entry["citation_hash"] == identity_hash)
            self.assertEqual(identity_citation["source_observation_id"], observations[3].observation_id)
            self.assertEqual(identity_citation["native_locator"], observations[3].to_dict()["location"])
            for row, subject in zip(table["rows"], subjects):
                self.assertEqual(subject["surfaces"], ["ＺＸ-００７"])
                quote_index, binding_index = subject["quotes"][0]
                self.assertEqual(row["quotes"][quote_index], ["ＺＸ-００７", [[identity_citation["ref"], 0]]])
                self.assertEqual(binding_index, 0)
            # Full original source and offset bindings remain server-side.
            for row in bound.candidate_fact_rows:
                for source in row["subject_identity"]["sources"]:
                    span = source["evidence_spans"][0]
                    self.assertTrue(source["unit_id"] and source["source_unit_id"])
                    self.assertEqual(span["start"], observations[3].text.index("ＺＸ-００７"))
                    self.assertEqual(span["end"] - span["start"], len(span["quote"]))
                    self.assertEqual(span["native_locator"], observations[3].to_dict()["location"])
                    self.assertEqual(span["source_extractor_run_id"], observations[3].extractor_run_id)
            tight = human_uat_orchestrator.compact_evidence_for_model(result, item_limit=3)
            self.assertEqual(tight["evidence"][0]["source_type"], "candidate_fact_table")
            self.assertLessEqual(len(tight["evidence"]), 3)
            fallback = handler({**self._arguments(), "required_terms": ["ZX-999"]})
            self.assertNotIn("candidate_fact_group", json.dumps(fallback))
            self.assertNotEqual(fallback["status"], "not_found")
            absent = replace(bound, candidate_fact_rows=tuple({k: v for k, v in row.items() if k != "subject_identity"}
                                                              for row in bound.candidate_fact_rows))
            self.assertFalse(lookup(absent, ["ZX-007"]))
            original_identity = observations[3]
            store = ObservationStore(Path(directory) / "document_text")
            path = store._store._record_path(original_identity.observation_id)
            changed = json.loads(path.read_bytes())
            changed["text"] += " altered identity"
            path.write_text(json.dumps(changed))
            with self.assertRaises(ContractValidationError):
                handler(self._arguments())

    def test_subject_source_quote_and_permission_damage_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture
            with patch.object(self, "_fixture", side_effect=lambda *args, **kwargs:
                              fixture(*args, **kwargs, fixture_code="code019")):
                bound, _ = self._bound(directory)
            arguments = {**self._arguments(), "query_text": "Code019 ZX-007 target date",
                         "session_id": "rc19-subject019"}
            for damage in ("quote", "permission", "surface"):
                with self.subTest(damage=damage):
                    rows = json.loads(json.dumps(list(bound.candidate_fact_rows)))
                    source = rows[0]["subject_identity"]["sources"][0]
                    if damage == "quote":
                        source["evidence_spans"][0]["quote"] = "invented identity"
                    elif damage == "permission":
                        source["permission_scope"]["scope_id"] = "different_scope"
                    else:
                        source["value_surface"] = "different identity"
                    damaged = replace(bound, candidate_fact_rows=tuple(rows))
                    fallback = loader._build_source_start_semantic_handler(damaged, mail_tool=False)(arguments)
                    tables = [item for item in fallback["evidence"]
                              if item.get("source_type") == "candidate_fact_table"]
                    self.assertEqual(len(tables), 1)
                    table = json.loads(tables[0]["snippet"].split("\n", 1)[1])
                    self.assertEqual([row["item"] for row in table["rows"]], ["1"])
                    good = rows[1]
                    sources = [field for fields in good["fields"].values() for field in fields]
                    sources += good["subject_identity"]["sources"]
                    required = {span["observation_hash"] for field in sources for span in field["evidence_spans"]}
                    self.assertEqual(set(tables[0]["source_context"]["required_citation_hashes"]), required)
                    self.assertEqual({entry["citation_hash"] for entry in table["citations"]}, required)
                    self.assertTrue(required.issubset(human_uat_orchestrator.evidence_citation_ids(fallback)))
                    self.assertNotIn("invented identity", json.dumps(table))
                    self.assertNotIn("different identity", json.dumps(table))
                    self.assertIn("1 rejected rows", table["disclosure"])
                    self.assertEqual(fallback["coverage"]["status"], "incomplete")
                    self.assertNotEqual(fallback["status"], "not_found")


class CandidateFactReachabilityTests(unittest.TestCase):
    _fixture = CandidateFactRuntimeTests._fixture

    def _captured(self, root, *, filler_count=None):
        register_asset = register_asset_from_local_file
        def register(*args, **kwargs):
            kwargs.pop("source_ref", None)
            return register_asset(*args, **kwargs)
        with patch(__name__ + ".register_asset_from_local_file", side_effect=register):
            revision, config, digest, _, observations = self._fixture(root, family="mail", filler_count=filler_count)
        return issue56_sealed_source.bind_issue56_candidate_fact_exports(
            revision, configuration_path=config, expected_sha256=digest), observations

    @staticmethod
    def _arguments(*, families=("mail",), query_class="evidence_lookup", terms=("ZX-742",)):
        query = "上一次 Clienta " + " ".join(terms) + " expected date"
        return {"query_text": query, "required_terms": list(terms),
            "request_contract": {"original_query_hash": "sha256:" + hashlib.sha256(query.encode()).hexdigest(),
                "query_class": query_class, "source_family_scope": list(families), "requested_fields": [],
                "maximum_claim_strength": "complete_authorized_scope" if query_class == "exact_set_or_inventory" else "cited_evidence"},
            "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
            "session_id": "clienta-reachability", "page_size": 20}

    def _native(self, root, *, cells=False, inline_html=None):
        template = root / "template"
        template.mkdir()
        _, config, _, export, _ = self._fixture(template)
        native = root / "native"
        native.mkdir()
        register_asset = register_asset_from_local_file
        def register(*args, **kwargs):
            kwargs.pop("source_ref", None)
            return register_asset(*args, **kwargs)
        with patch(__name__ + ".register_asset_from_local_file", side_effect=register):
            fixture = _source_start_preparation_fixture(native, families=("mail",),
                inline_html=inline_html, attachment_csv=None if inline_html is not None else
                "Asset,Ticket,Expected\nZX-742,R-007,2031-04-02\nZX-742,R-008,2031-04-09\n")
        from scripts.issue56_source_native_lookup import build_lookup
        lookup = native / "lookup"
        build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                     output_directory=lookup)
        for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
            shutil.copyfile(lookup / name, fixture.directory / name)
        revision = issue56_sealed_source.load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256)
        rows = [json.loads(line) for line in (export / "rows.jsonl").read_bytes().splitlines()]
        cited = {}
        for index, row in enumerate(rows):
            native_row = next(o for o in fixture.observations if o.observation_type == "table_row"
                              and f"R-00{index + 7}" in (o.text or ""))
            for values in row["fields"].values():
                field = values[0]
                obs = (next(o for o in fixture.observations if o.observation_type == "table_cell"
                    and loader._table_row_key(o) == loader._table_row_key(native_row)
                    and o.text == field["value"]) if cells else native_row)
                value = field["value"]
                start = obs.text.index(value)
                digest = sha256_json(obs.to_dict())
                field.update(permission_scope=obs.to_dict()["permission_scope"],
                    permission_scope_fingerprint=sha256_json(obs.to_dict()["permission_scope"]),
                    source_observation_ids=[obs.observation_id], observation_hashes={obs.observation_id: digest},
                    evidence_spans=[{"observation_id": obs.observation_id, "observation_hash": digest,
                        "field_path": ["text"], "quote": value, "occurrence_index": None,
                        "start": start, "end": start + len(value), "native_locator": obs.to_dict()["location"],
                        "source_extractor_run_id": obs.extractor_run_id}])
                cited[digest] = obs
        (export / "rows.jsonl").write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
        cfg = json.loads(config.read_bytes())
        cfg.update({key: revision.safe_binding[key] for key in (
            "source_revision_sha256", "source_authority_fingerprint", "source_session_binding_fingerprint")})
        config.write_text(json.dumps(cfg))
        digest = CandidateFactDiskIndexTests._reseal(config, export, len(rows))
        bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
            revision, configuration_path=config, expected_sha256=digest)
        return bound, cited

    def test_presentation_tiebreak_reaches_candidates_but_date_scan_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, _ = self._captured(Path(directory))
            args = self._arguments()
            public = {k: v for k, v in args.items() if k not in ("requester_user_id", "workspace_id", "session_id")}
            binding = issue56_sealed_source.bind_mail_date_priority(
                user_text=args["query_text"], arguments=public, tool_name="query_effective_graph_view")
            self.assertEqual(binding.mode, "presentation_tiebreak")
            handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            with issue56_sealed_source.mail_date_priority_scope(binding), patch.object(
                    issue56_sealed_source, "lookup_issue56_candidate_fact_rows",
                    wraps=issue56_sealed_source.lookup_issue56_candidate_fact_rows) as lookup:
                result = handler(args)
                lookup.assert_called_once()
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertIn("candidate_fact_group", json.dumps(compact))
            self.assertTrue(compact["evidence"])
            self.assertEqual(result["coverage"]["status"], "incomplete")
            with issue56_sealed_source.mail_date_priority_scope(replace(binding, mode="date_scan")), patch.object(
                    issue56_sealed_source, "lookup_issue56_candidate_fact_rows",
                    wraps=issue56_sealed_source.lookup_issue56_candidate_fact_rows) as lookup:
                handler(args)
                lookup.assert_not_called()

    def test_exact_downgrade_can_present_candidates_without_exact_or_absence_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, _ = self._native(Path(directory))
            args = self._arguments(families=("mail", "attachment_table"), query_class="exact_set_or_inventory")
            result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertIn("candidate_fact_group", json.dumps(compact))
            self.assertEqual(result["coverage"]["status"], "incomplete")
            self.assertIs(result["coverage"]["absence_claim"], False)
            self.assertFalse(result["deterministic_exact"])
            self.assertEqual(result["execution_downgrade"]["request_contract_fingerprint"],
                             sha256_json(args["request_contract"]))
            self.assertEqual(result["execution_downgrade"]["executed_request_contract"]["query_class"], "evidence_lookup")
            self.assertTrue(result["execution_downgrade"]["disclosure"])

    def test_inline_fact_citations_use_complete_ordered_headers_and_parent_date(self):
        for ticket_header in ("Ticket", ""):
            with self.subTest(ticket_header=ticket_header), tempfile.TemporaryDirectory() as directory:
                html = (f"<table><tr><th>Asset</th><th>{ticket_header}</th><th>Expected</th></tr>"
                        "<tr><td>ZX-742</td><td>R-007</td><td>2031-04-02</td></tr>"
                        "<tr><td>ZX-742</td><td>R-008</td><td>2031-04-09</td></tr></table>")
                sent_at = "2026-09-01T00:00:00+00:00"
                bound, cited = self._native(Path(directory), cells=True, inline_html=html)
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(self._arguments())
                compact = human_uat_orchestrator.compact_evidence_for_model(result)
                item = next(i for i in compact["evidence"] if i["source_type"] == "candidate_fact_table")
                table = json.loads(item["snippet"].split("\n", 1)[1])
                self.assertEqual(set(cited), {c["citation_hash"] for c in table["citations"]})
                self.assertEqual({c["mail_sent_at"] for c in table["citations"]}, {sent_at})
                if ticket_header:
                    self.assertEqual(table["headers"], {"h1": ["Asset", "Ticket", "Expected"]})
                    self.assertEqual({c["h"] for c in table["citations"]}, {"h1"})
                else:
                    self.assertNotIn("headers", table)
                    self.assertTrue(all("h" not in c for c in table["citations"]))

                if ticket_header:
                    # Force the real 48 KiB fitter to select one complete native row.
                    rows = tuple({**r, "item_or_row": r["item_or_row"] + "x" * 26000}
                                 for r in bound.candidate_fact_rows)
                    capped = loader._build_source_start_semantic_handler(
                        replace(bound, candidate_fact_rows=rows), mail_tool=False)(self._arguments())
                    kept = human_uat_orchestrator.compact_evidence_for_model(capped)["evidence"][0]
                    truncated = json.loads(kept["snippet"].split("\n", 1)[1])
                    self.assertLessEqual(len(json.dumps(kept, ensure_ascii=False).encode()), 48 * 1024)
                    self.assertEqual(len(truncated["rows"]), 1)
                    self.assertIn("Shown 1 of 2 answer-bearing rows", truncated["disclosure"])
                    self.assertEqual(truncated["headers"], table["headers"])
                    self.assertEqual({c["h"] for c in truncated["citations"]}, {"h1"})
                    self.assertEqual({c["mail_sent_at"] for c in truncated["citations"]}, {sent_at})
                    self.assertEqual(set(kept["source_context"]["required_citation_hashes"]),
                                     {c["citation_hash"] for c in truncated["citations"]})

    def test_native_row_and_cell_candidates_keep_all_rows_and_original_locators(self):
        for cells in (False, True):
            with self.subTest(cells=cells), tempfile.TemporaryDirectory() as directory:
                bound, cited = self._native(Path(directory), cells=cells)
                args = self._arguments(families=("mail", "attachment_table"))
                staged = {}
                scan = loader._IngestionExactCellLookup.scan_source_rows
                def observe_scan(lookup, **kwargs):
                    result = scan(lookup, **kwargs)
                    if kwargs.get("preferred_observation_hashes"):
                        staged.update(kwargs["evidence_by_id"])
                    return result
                with patch.object(loader._IngestionExactCellLookup, "scan_source_rows", new=observe_scan):
                    result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
                compact = human_uat_orchestrator.compact_evidence_for_model(result)
                table = json.loads(compact["evidence"][0]["snippet"].split("\n", 1)[1])
                self.assertTrue(all("mail_sent_at" not in c for c in table["citations"]))
                self.assertEqual({v["citation_hash"] for v in staged.values()}, set(cited))
                staged_snippets = {v["snippet"] for v in staged.values()}
                self.assertTrue(staged_snippets.isdisjoint(item["snippet"] for item in result["evidence"]))
                self.assertTrue(staged_snippets.isdisjoint(item["snippet"] for item in compact["evidence"]))
                self.assertIn("candidate_fact_group", json.dumps(compact))
                self.assertTrue(set(cited).issubset(human_uat_orchestrator.evidence_citation_ids(compact)))
                text = json.dumps(compact)
                for value in ("R-007", "R-008", "2031-04-02", "2031-04-09"):
                    self.assertIn(value, text)
                for obs in cited.values():
                    self.assertIn(str(obs.location["row_index"]), text)
                self.assertFalse(result.get("deterministic_exact"))
                single = human_uat_orchestrator.compact_evidence_for_model(result, item_limit=1)
                self.assertEqual(single["evidence"][0]["source_type"], "candidate_fact_table")
                self.assertEqual(len(single["evidence"]), 1)

    def test_candidate_lookup_uses_nonempty_postings_then_deterministic_rarest_key(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, digest, _, _ = self._fixture(Path(directory))
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=digest)
            lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
            for selected in (bound, replace(bound, candidate_fact_rows=tuple(bound.candidate_fact_rows))):
                with self.subTest(indexed=selected is bound):
                    self.assertEqual(len(lookup(selected, ["ZX-742", "clienta frame", "gen2"])), 2)
                    self.assertEqual(len(lookup(selected, ["ZX-742", "R-007", "gen2"])), 1)
                    # R-007 and R-008 have equally rare, disjoint postings.
                    # The full normalized key resolves ties, independent of input order.
                    for terms in (["R-007", "R-008"], ["R-008", "R-007"]):
                        result = lookup(selected, terms)
                        self.assertEqual([r["row_id"] for r in result], ["factrow_clienta_0"])
                    self.assertFalse(lookup(selected, ["ZX-74", "clienta frame", "gen2"]))
                    self.assertFalse(lookup(selected, ["ZX-742"], deadline_monotonic=0))

    def test_native_candidate_failure_discards_staging_and_charges_actual_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture
            with patch.object(self, "_fixture", side_effect=lambda *args, **kwargs:
                              fixture(*args, **kwargs, fixture_code="code019")):
                bound, _ = self._native(Path(directory))
            handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            original = loader._IngestionExactCellLookup.scan_source_rows
            calls, verified_sources = [], set()
            def scan(instance, **kwargs):
                calls.append(kwargs)
                if kwargs.get("preferred_observation_hashes"):
                    callback = kwargs["observation_callback"]
                    def reject(observation, scope):
                        callback(observation, scope)
                        verified_sources.add(sha256_json(observation.to_dict()))
                        raise ContractValidationError("fictional native candidate projection rejected")
                    return original(instance, **{**kwargs, "observation_callback": reject})
                return original(instance, **kwargs)
            with patch.object(loader._IngestionExactCellLookup, "scan_source_rows", new=scan):
                arguments = {**self._arguments(families=("mail", "attachment_table")),
                             "query_text": "Code019 ZX-742 target date", "session_id": "rc19-native019"}
                arguments["request_contract"] = {**arguments["request_contract"],
                    "original_query_hash": "sha256:" + hashlib.sha256(arguments["query_text"].encode()).hexdigest()}
                result = handler(arguments)
            preferred = next(call for call in calls if call.get("preferred_observation_hashes"))
            actual_reads = preferred["_phase_metrics"]["scanned_observation_count"]
            self.assertGreater(actual_reads, 1)
            ordinary = [call for call in calls if not call.get("preferred_observation_hashes")]
            self.assertTrue(ordinary)
            self.assertLessEqual(ordinary[0]["max_observations"], preferred["max_observations"] - actual_reads)
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            tables = [item for item in compact["evidence"] if item.get("source_type") == "candidate_fact_table"]
            self.assertEqual(len(tables), 1)
            display = json.loads(tables[0]["snippet"].split("\n", 1)[1])
            eligible = [row for row in bound.candidate_fact_rows if {
                span["observation_hash"] for fields in row["fields"].values()
                for field in fields for span in field["evidence_spans"]}.issubset(verified_sources)]
            self.assertTrue(eligible)
            self.assertLess(len(eligible), len(bound.candidate_fact_rows))
            self.assertEqual([row["item"] for row in display["rows"]], [row["item_or_row"] for row in eligible])
            required = set(tables[0]["source_context"]["required_citation_hashes"])
            self.assertTrue(required.issubset(verified_sources))
            self.assertEqual({entry["citation_hash"] for entry in display["citations"]}, required)
            self.assertTrue(required.issubset(human_uat_orchestrator.evidence_citation_ids(compact)))
            self.assertIn("withheld", display["disclosure"])
            self.assertEqual(result["coverage"]["status"], "incomplete")
            self.assertNotEqual(result["status"], "not_found")
            calls.clear()
            verified_sources.clear()
            with patch.object(loader, "SOURCE_EVIDENCE_OBSERVATION_LIMIT", 1), patch.object(
                    loader._IngestionExactCellLookup, "scan_source_rows", new=scan):
                capped = handler(arguments)
            self.assertNotIn("candidate_fact_group", json.dumps(capped))
            self.assertTrue(all(call.get("_phase_metrics", {}).get("scanned_observation_count", 0) <= 1
                                for call in calls if call.get("preferred_observation_hashes")))

    def test_repeated_fact_rows_merge_and_keep_source_bound_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, _, export, observations = self._fixture(Path(directory))
            originals = [json.loads(line) for line in (export / "rows.jsonl").read_bytes().splitlines()]
            rows = []
            for index in range(10):
                row = json.loads(json.dumps(originals[index % 2]))
                row["row_id"] = f"factrow_clienta_context_{index}"
                rows.append(row)
            (export / "rows.jsonl").write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
            digest = CandidateFactDiskIndexTests._reseal(config, export, len(rows))
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=digest)
            args = self._arguments(families=("document_text",))
            result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            facts = [item for item in compact["evidence"]
                     if item.get("source_context", {}).get("candidate_fact_group")]
            self.assertEqual(len(facts), 1)
            table = json.loads(facts[0]["snippet"].split("\n", 1)[1])
            self.assertEqual([entry["item"] for entry in table["rows"]], [row["item_or_row"] for row in originals])
            displayed = [cell for row in table["rows"] for cells in row["values"] for cell in cells]
            self.assertEqual(len(displayed), 6)
            self.assertIn("8 rows merged as duplicates/subsets", table["disclosure"])
            self.assertEqual({entry["value"] for entry in displayed},
                             {"ZX-742", "R-007", "R-008", "2031-04-02", "2031-04-09"})
            source_by_hash = {sha256_json(obs.to_dict()): obs for obs in observations}
            sources = {entry["ref"]: source_by_hash[entry["citation_hash"]] for entry in table["citations"]}
            for entry in table["citations"]:
                self.assertEqual(entry["native_locator"], sources[entry["ref"]].to_dict()["location"])
            for row in table["rows"]:
                for values in row["values"]:
                    for cell in values:
                        for quote_index, binding_index in cell["quotes"]:
                            quote, bindings = row["quotes"][quote_index]
                            reference, _ = bindings[binding_index]
                            self.assertIn(quote, sources[reference].text)
            self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False).encode()), 16 * 1024)
            tight = human_uat_orchestrator.compact_evidence_for_model(result, item_limit=2)
            self.assertEqual(len(json.loads(tight["evidence"][0]["snippet"].split("\n", 1)[1])["rows"]), 2)

    def test_fact_group_still_over_budget_never_releases_a_subset(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, _, export, observations = self._fixture(Path(directory), filler_count=9000)
            original = json.loads((export / "rows.jsonl").read_bytes().splitlines()[0])
            original["fields"]["asset_code"][0]["evidence_spans"][0].update(
                quote=observations[0].text, start=0, end=len(observations[0].text))
            self.assertGreater(len(observations[0].text.encode()), 48 * 1024)
            rows = [{**original, "row_id": f"factrow_clienta_large_{index}"} for index in range(128)]
            (export / "rows.jsonl").write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
            digest = CandidateFactDiskIndexTests._reseal(config, export, len(rows))
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=digest)
            result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(
                self._arguments(families=("document_text",)))
            display = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertNotIn("candidate_fact_group", json.dumps(display))
            self.assertNotEqual(result["status"], "not_found")


class CandidateFactTablePresentationTests(unittest.TestCase):
    def _fixture(self, root, *, overflow=False, adjacent=False, real_times=False, shared_source=False, overflow_contexts=2000):
        from formowl_graph.ontology import CandidatePropertyMapping
        paragraphs = [f"{'Clienta ZX-742 ' if index == 0 else ''}Ticket R-{index:03d} "
            f"PO date 2030-05-{index+1:02d} expected 2031-04-{index+1:02d} Quantity {index+1} pcs"
            for index in range(14)]
        if overflow:
            paragraphs[0] += " Supporting source context." * overflow_contexts
        paragraphs.append("Clienta ZX-742 ordinary independent source support must remain visible.")
        text = (" ".join(paragraphs[:14]) + "\n" * 70 + paragraphs[-1] if shared_source else
                ("\n\n" if adjacent else "\n" * 70).join(paragraphs))
        fixture = _source_start_preparation_fixture(root, families=("document_text",), document_text=text)
        from scripts.issue56_source_native_lookup import build_lookup
        lookup = root / "table-lookup"
        build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                     output_directory=lookup)
        for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
            shutil.copyfile(lookup / name, fixture.directory / name)
        revision = issue56_sealed_source.load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256)
        observations = [item for item in fixture.observations if item.observation_type == "paragraph"]
        self.assertEqual(len(observations), 2 if shared_source else 15)
        properties = ["asset_code", "ticket_code", "po_date", "target_date", "quantity"]
        mapping = CandidatePropertyMapping.from_dict({"artifact_id": "formowl_candidate_property_mapping_v1",
            "mapping_id": "clienta_fact_table", "review_status": "pending_review", "properties": properties,
            "aliases": [{"label": prop, "property_id": prop, "qualifiers": {}} for prop in properties],
            "identity_groups": [{"name": "asset", "properties": ["asset_code"]}]})
        annotation = sha256_json("fictional-table-annotation-separate-from-serving")
        rows = []
        for index, observation in enumerate([observations[0]] * 14 if shared_source else observations[:14]):
            fields = {}
            values = ("ZX-742", f"R-{index:03d}", f"2030-05-{index+1:02d}", f"2031-04-{index+1:02d}", index+1)
            for prop, value in zip(properties, values):
                source = observations[0] if prop == "asset_code" else observation
                quote = f"Quantity {value} pcs" if prop == "quantity" else value
                if overflow and prop == "asset_code":
                    quote = source.text
                if shared_source and prop != "asset_code":
                    quote = paragraphs[index].removeprefix("Clienta ZX-742 ")
                start = source.text.index(quote)
                digest = sha256_json(source.to_dict())
                fields[prop] = [{"value": value, "unit": "pcs" if prop == "quantity" else None,
                    "qualifiers": ({"notes": "x" * 2000} if overflow else {"kind": "expected"}) if prop == "target_date" else {},
                    "times": [], "unit_id": f"clienta-unit-{index}", "source_unit_id": f"clienta-source-{index}",
                    "source_revision_fingerprint": annotation, "permission_scope": source.to_dict()["permission_scope"],
                    "permission_scope_fingerprint": sha256_json(source.to_dict()["permission_scope"]),
                    "source_observation_ids": [source.observation_id], "observation_hashes": {source.observation_id: digest},
                    "evidence_spans": [{"observation_id": source.observation_id, "observation_hash": digest,
                        "field_path": ["text"], "quote": quote, "occurrence_index": None,
                        "start": start, "end": start + len(quote), "native_locator": source.to_dict()["location"],
                        "source_extractor_run_id": source.extractor_run_id}]}]
            if real_times:
                for prop in ("po_date", "target_date"):
                    fact = fields[prop][0]
                    fact["times"] = [{"normalized": fact["value"], "role": role, "raw": fact["value"],
                        "precision": "day", "property": prop, "evidence_spans": copy.deepcopy(fact["evidence_spans"])}
                        for role in ("recorded", "expected")]
            rows.append({"artifact_id": "formowl_candidate_fact_row_v1", "row_id": f"factrow_clienta_table_{index}",
                "source_revision_fingerprint": annotation, "mapping_fingerprint": mapping.fingerprint,
                "review_status": "pending_review", "semantic_correctness_verified": False,
                "item_or_row": str(index), "fields": fields, "identity_candidates": []})
        export = root / "table-export"
        export.mkdir()
        raw = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
        (export / "rows.jsonl").write_bytes(raw)
        (export / "mapping.snapshot.json").write_text(json.dumps(mapping.data))
        manifest = {"artifact_id": "formowl_candidate_fact_export_v1", "review_status": "pending_review",
            "semantic_correctness_verified": False, "source_revision": annotation,
            "mapping_fingerprint": mapping.fingerprint, "rows_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(), "row_count": 14}
        (export / "manifest.json").write_text(json.dumps(manifest))
        config = {"artifact_id": "formowl_candidate_fact_runtime_config_v1", **{key: revision.safe_binding[key] for key in (
            "source_revision_sha256", "source_authority_fingerprint", "source_session_binding_fingerprint")},
            "exports": [{"manifest_path": str(export / "manifest.json"),
                         "manifest_sha256": "sha256:" + hashlib.sha256((export / "manifest.json").read_bytes()).hexdigest()}]}
        path = root / "table-config.json"
        path.write_text(json.dumps(config))
        bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(revision,
            configuration_path=path, expected_sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
        return revision, bound, observations

    @staticmethod
    def _arguments():
        return {"query_text": "Find Clienta ZX-742 facts", "required_terms": ["ZX-742"],
            "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
            "session_id": "clienta-single-table", "page_size": 10}

    def test_candidate_48k_table_reservation_keeps_whole_rows_and_ordinary_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bound, _ = self._fixture(Path(directory), overflow=True, overflow_contexts=55)
            result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(self._arguments())
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            tables = [item for item in compact.get("evidence", ()) if item.get("source_type") == "candidate_fact_table"]
            self.assertEqual(len(tables), 1)
            table = tables[0]
            self.assertEqual(len(json.loads(table["snippet"].split("\n", 1)[1])["rows"]), 14)
            self.assertGreater(len(json.dumps(table, ensure_ascii=False).encode()), 24 * 1024)
            self.assertLessEqual(len(json.dumps(table, ensure_ascii=False).encode()), 48 * 1024)
            self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False).encode()), 54 * 1024)
            ordinary = {**result, "evidence": [{**table, "source_type": "document_text"}]}
            ordinary = human_uat_orchestrator.compact_evidence_for_model(ordinary)
            self.assertLessEqual(len(json.dumps(ordinary, ensure_ascii=False).encode()), 16 * 1024)
            malformed = copy.deepcopy(result)
            malformed["evidence"][0]["source_context"]["candidate_fact_pin"] = "invalid"
            rejected = human_uat_orchestrator.compact_evidence_for_model(malformed)
            self.assertNotIn("candidate_fact_table", json.dumps(rejected))
            self.assertLessEqual(len(json.dumps(rejected, ensure_ascii=False).encode()), 16 * 1024)

    def test_fourteen_rows_five_fields_over_reserved_cap_remain_whole_until_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, bound, observations = self._fixture(Path(directory), overflow=True)
            args = self._arguments()
            ordinary = human_uat_orchestrator.compact_evidence_for_model(
                loader._build_source_start_semantic_handler(revision, mail_tool=False)(args))
            tables = []
            build = loader._candidate_fact_table
            def capture(*values, **kwargs):
                table = build(*values, **kwargs)
                if kwargs.get("_counts") is None:
                    tables.append(table if table is not None else build(*values, **{**kwargs, "_counts": (len(values[0]), 0)}))
                return table
            with patch.object(loader, "_candidate_fact_table", side_effect=capture):
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertEqual(len(tables), 1)
            self.assertGreater(len(json.dumps(tables[0], ensure_ascii=False).encode()), 48 * 1024)
            self.assertNotIn("candidate_fact_group", json.dumps(compact))
            label, raw = tables[0]["snippet"].split("\n", 1)
            self.assertEqual(label, "候選事實（由標註取得，未經人工審核）")
            table = json.loads(raw)
            self.assertEqual(len(table["rows"]), 14)
            self.assertEqual(len(table["columns"]), 5)
            self.assertEqual(len(table["citations"]), 14)
            self.assertEqual(set(tables[0]["source_context"]["required_citation_hashes"]),
                             {entry["citation_hash"] for entry in table["citations"]})
            cells = [cell for row in table["rows"] for values in row["values"] for cell in values]
            self.assertEqual(len(cells), 70)
            self.assertEqual({cell["value"] for cell in cells if cell.get("unit") == "pcs"}, set(range(1, 15)))
            self.assertEqual({cell["value"] for row in table["rows"]
                for cell in row["values"][table["columns"].index("target_date")]},
                {f"2031-04-{index:02d}" for index in range(1, 15)})
            self.assertTrue(all("qualifiers" not in cell for cell in cells))
            sources = {sha256_json(obs.to_dict()): obs for obs in observations}
            references = {entry["ref"]: sources[entry["citation_hash"]] for entry in table["citations"]}
            for row in table["rows"]:
                for values in row["values"]:
                    for cell in values:
                        for quote_index, binding_index in cell["quotes"]:
                            quote, bindings = row["quotes"][quote_index]
                            reference, _ = bindings[binding_index]
                            self.assertIn(quote, references[reference].text)
            for entry in table["citations"]:
                self.assertEqual(entry["native_locator"], sources[entry["citation_hash"]].to_dict()["location"])
                self.assertEqual(entry["source_observation_id"], sources[entry["citation_hash"]].observation_id)
            ordinary_items = [item for item in compact["evidence"] if item not in tables]
            self.assertEqual(ordinary_items, ordinary["evidence"])
            self.assertEqual(human_uat_orchestrator.evidence_citation_ids(compact),
                             human_uat_orchestrator.evidence_citation_ids(ordinary))
            row_bytes = [len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()) for row in table["rows"]]
            envelope_bytes = len(json.dumps(compact, ensure_ascii=False).encode())
            print("AS58_OVER_CAP_14x5_BYTES", json.dumps({"rows": row_bytes, "table_item": len(json.dumps(tables[0], ensure_ascii=False).encode()),
                "full_envelope": envelope_bytes}), flush=True)
            self.assertEqual(len(raw.splitlines()), len(table["rows"]) + 2)
            self.assertLess(envelope_bytes, 16 * 1024)
            self.assertEqual(human_uat_orchestrator.compact_evidence_for_model(compact), compact)
            human_uat_orchestrator._validate_evidence_bound_decision({"response_kind": "answer",
                "citation_ids": list(human_uat_orchestrator.evidence_citation_ids(compact)), "coverage_status": "incomplete"},
                evidence_results=(compact,))

    def test_over_cap_table_preserves_existing_ordinary_citation_order(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, bound, _ = self._fixture(Path(directory), overflow=True, overflow_contexts=380)
            self.assertTrue(all(len(row["fields"]["asset_code"][0]["evidence_spans"][0]["quote"].encode()) > 10 * 1024
                                for row in bound.candidate_fact_rows))
            original = list(bound.candidate_fact_rows)
            rows = copy.deepcopy(original)
            for row in rows:
                row["item_or_row"] += "x" * (40 * 1024)
                # A lower bound on each whole rendered row already exceeds
                # 48 KiB, without consuming the ordinary source context budget.
                self.assertGreater(len(row["item_or_row"].encode()) + len(
                    row["fields"]["asset_code"][0]["evidence_spans"][0]["quote"].encode()), 48 * 1024)
            self.assertEqual([row["row_id"] for row in rows], [row["row_id"] for row in original])
            self.assertEqual([sha256_json(row["fields"]) for row in rows],
                             [sha256_json(row["fields"]) for row in original])
            bound = replace(bound, candidate_fact_rows=tuple(rows))
            admit = loader._admit_source_model_envelope
            def ordinary_support_first(payload, **kwargs):
                # Order only the already-guarded completed ordinary envelope;
                # source/quote/hash validation and retrieval remain unchanged.
                payload = admit(payload, **kwargs)
                items = list(reversed(payload["evidence"]))
                return {**payload, "evidence": items, "citations": [item["citation_hash"] for item in items]}
            with patch.object(loader, "_admit_source_model_envelope", side_effect=ordinary_support_first):
                ordinary = human_uat_orchestrator.compact_evidence_for_model(
                    loader._build_source_start_semantic_handler(revision, mail_tool=False)(self._arguments()))
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(self._arguments())
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertTrue(compact["evidence"])
            self.assertNotIn("candidate_fact_group", json.dumps(compact))
            self.assertEqual(compact["evidence"], ordinary["evidence"])
            self.assertGreaterEqual(len(ordinary["evidence"]), 2)
            self.assertGreaterEqual(len(ordinary["citations"]), 2)
            self.assertEqual(compact["citations"], ordinary["citations"])
            print("AS60_R2_PROOF", json.dumps({"ordinary_items": len(ordinary["evidence"]),
                "ordinary_citations": len(ordinary["citations"]),
                "ordinary_order": [sha256_json(item) for item in ordinary["evidence"]],
                "final_order": [sha256_json(item) for item in compact["evidence"]],
                "ordinary_citation_order": ordinary["citations"], "final_citation_order": compact["citations"],
                "min_fact_quote_bytes": min(len(row["fields"]["asset_code"][0]["evidence_spans"][0]["quote"].encode())
                                            for row in bound.candidate_fact_rows)}), flush=True)

    def test_table_overflow_or_bad_quote_keeps_whole_ordinary_fallback(self):
        for failure in ("overflow", "quote", "item_cap", "ordinary_saturated"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                revision, bound, _ = self._fixture(Path(directory), overflow=True, adjacent=failure == "ordinary_saturated")
                args = {**self._arguments(), **({"page_size": 1} if failure == "item_cap" else {})}
                if failure == "quote":
                    rows = copy.deepcopy(list(bound.candidate_fact_rows))
                    rows[-1]["fields"]["target_date"][0]["evidence_spans"][0]["quote"] = "invented quote"
                    bound = replace(bound, candidate_fact_rows=tuple(rows))
                ordinary = human_uat_orchestrator.compact_evidence_for_model(
                    loader._build_source_start_semantic_handler(revision, mail_tool=False)(args))
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
                compact = human_uat_orchestrator.compact_evidence_for_model(result)
                self.assertNotIn("candidate_fact_group", json.dumps(compact))
                self.assertEqual(compact["evidence"], ordinary["evidence"])
                self.assertTrue(compact["citations"])
                if failure == "ordinary_saturated":
                    print("AS57_SATURATED_BYTES", json.dumps({"ordinary_full_envelope": len(json.dumps(ordinary, ensure_ascii=False).encode()),
                        "retained_ordinary_items": len(ordinary["evidence"]), "final_envelope": len(json.dumps(compact, ensure_ascii=False).encode())}), flush=True)


class CandidateFactTablePriorityHandlerTests(unittest.TestCase):
    def test_guarded_mail_table_survives_saturated_ordinary_envelope(self):
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        with tempfile.TemporaryDirectory() as directory:
            bound, observations = CandidateFactReachabilityTests()._captured(Path(directory), filler_count=1400)
            rows = copy.deepcopy(list(bound.candidate_fact_rows))
            for row in rows:
                # Fill the larger table reservation without enlarging ordinary mail snippets.
                row["item_or_row"] += "x" * (12 * 1024)
                row["fields"]["asset_code"][0]["evidence_spans"][0].update(
                    quote=observations[0].text, start=0, end=len(observations[0].text))
            bound = replace(bound, candidate_fact_rows=tuple(rows))
            args = {**CandidateFactRuntimeTests._arguments(), "required_terms": ["ZX-742"],
                    "query_text": "Find Clienta asset ZX-742 expected date"}
            ordinary = human_uat_orchestrator.compact_evidence_for_model(loader._build_source_start_semantic_handler(
                replace(bound, candidate_fact_pin=None), mail_tool=False)(args))
            trace = _SourcePhaseTrace({})
            with _source_phase_trace_scope(trace):
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
                compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertEqual(compact["evidence"][0].get("source_type"), "candidate_fact_table")
            # Frozen replay performs final/default compaction outside trace scope.
            self.assertEqual(human_uat_orchestrator.compact_evidence_for_model(result), compact)
            self.assertEqual(human_uat_orchestrator.compact_evidence_for_model(compact), compact)
            table = json.loads(compact["evidence"][0]["snippet"].split("\n", 1)[1])
            self.assertEqual(len(table["rows"]), 2)
            self.assertLess(len(compact["evidence"]) - 1, len(ordinary["evidence"]))
            self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False).encode()), 54 * 1024)
            self.assertTrue(set(compact["evidence"][0]["source_context"]["required_citation_hashes"]).issubset(
                human_uat_orchestrator.evidence_citation_ids(compact)))

    def test_guarded_fourteen_row_table_over_cap_reports_reason_after_trace_fills(self):
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        class FillingTrace(_SourcePhaseTrace):
            def phase(self, name, **fields):
                cell = super().phase(name, **fields)
                if fields.get("candidate_fact_status"):
                    while len(self.details) < 256:
                        self.cell(kind="phase", name="project")
                return cell
        with tempfile.TemporaryDirectory() as directory:
            _, bound, _ = CandidateFactTablePresentationTests()._fixture(Path(directory), overflow=True)
            trace = FillingTrace({})
            with _source_phase_trace_scope(trace):
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(
                    CandidateFactTablePresentationTests._arguments())
                compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertNotIn("candidate_fact_group", json.dumps(compact))
            snapshot = json.loads(trace.snapshot())
            self.assertIn("table_over_reserved_budget", json.dumps(snapshot))
            self.assertEqual(len(snapshot["details"]), 256)



class CandidateFactCompactDisplayTests(unittest.TestCase):
    def test_fourteen_rows_with_full_time_evidence_fit_and_keep_paired_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bound, observations = CandidateFactTablePresentationTests()._fixture(Path(directory), real_times=True, shared_source=True)
            tables = []
            build = loader._candidate_fact_table
            def capture(*args, **kwargs):
                item = build(*args, **kwargs)
                tables.append(item)
                print("AS59_STAGED_TIME_BYTES", len(json.dumps(item, ensure_ascii=False).encode()), flush=True)
                return item
            with patch.object(loader, "_candidate_fact_table", side_effect=capture):
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(
                    CandidateFactTablePresentationTests._arguments())
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertEqual(compact["evidence"][0].get("source_type"), "candidate_fact_table")
            item = compact["evidence"][0]
            table = json.loads(item["snippet"].split("\n", 1)[1])
            self.assertEqual(len(table["rows"]), 14)
            self.assertEqual(len(table["citations"]), 1)
            self.assertEqual([row["item"] for row in table["rows"]], [str(index) for index in range(14)])
            cells = [cell for row in table["rows"] for values in row["values"] for cell in values]
            self.assertEqual(len(cells), 70)
            self.assertEqual({cell["value"] for cell in cells}, {"ZX-742", *range(1, 15),
                *(f"R-{index:03d}" for index in range(14)),
                *(f"2030-05-{index:02d}" for index in range(1, 15)),
                *(f"2031-04-{index:02d}" for index in range(1, 15))})
            self.assertEqual(sum(len(cell.get("times", ())) for cell in cells), 56)
            sources = {sha256_json(obs.to_dict()): obs for obs in observations}
            refs = {entry["ref"]: entry for entry in table["citations"]}
            used = set()
            for row in table["rows"]:
                quotes = row["quotes"]
                self.assertEqual(len({entry[0] for entry in quotes}), len(quotes))
                for cells in row["values"]:
                    for cell in cells:
                        self.assertLessEqual(set(cell), {"value", "unit", "times", "quotes"})
                        if "times" in cell:
                            self.assertEqual(cell["times"], [{"normalized": cell["value"], "role": role}
                                                           for role in ("recorded", "expected")])
                        for index, binding_index in cell["quotes"]:
                            quote, bindings = quotes[index]
                            reference, span_index = bindings[binding_index]
                            citation = refs[reference]
                            source = sources[citation["citation_hash"]]
                            start, end = citation["spans"][span_index]
                            self.assertEqual(source.text[start:end], quote)
                            self.assertEqual(citation["source_extractor_run_id"], source.extractor_run_id)
                            self.assertEqual(citation["native_locator"], source.to_dict()["location"])
                            used.add(reference)
            self.assertEqual(used, set(refs))
            self.assertLess(len(json.dumps(item, ensure_ascii=False).encode()), 10 * 1024)
            self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False).encode()), 16 * 1024)
            self.assertEqual(human_uat_orchestrator.compact_evidence_for_model(compact), compact)
            print("AS59_TIME_TABLE_BYTES", len(json.dumps(item, ensure_ascii=False).encode()),
                  len(json.dumps(compact, ensure_ascii=False).encode()), flush=True)

    def test_distinct_quote_full_time_table_remains_whole_overflow(self):
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        with tempfile.TemporaryDirectory() as directory:
            _, bound, _ = CandidateFactTablePresentationTests()._fixture(Path(directory), real_times=True, overflow=True)
            tables = []
            build = loader._candidate_fact_table
            def capture(*args, **kwargs):
                table = build(*args, **kwargs)
                if kwargs.get("_counts") is None:
                    tables.append(table if table is not None else build(*args, **{**kwargs, "_counts": (len(args[0]), 0)}))
                return table
            trace = _SourcePhaseTrace({})
            with patch.object(loader, "_candidate_fact_table", side_effect=capture), _source_phase_trace_scope(trace):
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(
                    CandidateFactTablePresentationTests._arguments())
            self.assertEqual(len(tables), 1)
            table = json.loads(tables[0]["snippet"].split("\n", 1)[1])
            self.assertEqual(len(table["rows"]), 14)
            self.assertEqual(len(table["citations"]), 14)
            cells = [cell for row in table["rows"] for values in row["values"] for cell in values]
            self.assertEqual(len(cells), 70)
            self.assertEqual(sum(len(cell.get("times", ())) for cell in cells), 56)
            self.assertGreater(len(json.dumps(tables[0], ensure_ascii=False).encode()), 48 * 1024)
            self.assertNotIn("candidate_fact_group", json.dumps(result))
            self.assertIn("table_over_reserved_budget", trace.snapshot())
            print("AS59_DISTINCT_QUOTE_OVERFLOW_BYTES", len(json.dumps(tables[0], ensure_ascii=False).encode()), flush=True)

    def test_same_cell_and_quote_keep_stable_native_representative(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bound, observations = CandidateFactTablePresentationTests()._fixture(Path(directory))
            rows = copy.deepcopy(list(bound.candidate_fact_rows))
            fields = []
            for source in observations[:2]:
                fact = copy.deepcopy(rows[0]["fields"]["ticket_code"][0])
                span = fact["evidence_spans"][0]
                digest = sha256_json(source.to_dict())
                start = source.text.index("Ticket")
                span.update(observation_id=source.observation_id, observation_hash=digest, quote="Ticket",
                    start=start, end=start+6, native_locator=source.to_dict()["location"],
                    source_extractor_run_id=source.extractor_run_id)
                fact.update(value="Ticket", source_observation_ids=[source.observation_id],
                            observation_hashes={source.observation_id: digest})
                fields.append(fact)
            rows[0]["fields"]["ticket_code"] = fields
            original_rows = copy.deepcopy(rows)
            result = loader._build_source_start_semantic_handler(replace(bound, candidate_fact_rows=tuple(rows[:1])),
                mail_tool=False)(CandidateFactTablePresentationTests._arguments())
            self.assertEqual(rows, original_rows)
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertEqual(compact["evidence"][0].get("source_type"), "candidate_fact_table")
            table = json.loads(compact["evidence"][0]["snippet"].split("\n", 1)[1])
            row = table["rows"][0]
            self.assertIn("quotes", row)
            self.assertEqual(sum(quote == "Ticket" for quote, _ in row["quotes"]), 1)
            cells = row["values"][table["columns"].index("ticket_code")]
            refs = {entry["ref"]: entry for entry in table["citations"]}
            self.assertEqual(len(cells), 1)
            self.assertEqual(len(cells[0]["quotes"]), 1)
            source = min(observations[:2], key=lambda obs: sha256_json(obs.to_dict()))
            pair = cells[0]["quotes"][0]
            quote_index, binding_index = pair
            quote, bindings = row["quotes"][quote_index]
            reference, span_index = bindings[binding_index]
            self.assertEqual(quote, "Ticket")
            self.assertEqual(refs[reference]["citation_hash"], sha256_json(source.to_dict()))
            self.assertEqual(refs[reference]["source_observation_id"], source.observation_id)
            self.assertEqual(refs[reference]["native_locator"], source.to_dict()["location"])
            self.assertEqual(refs[reference]["source_extractor_run_id"], source.extractor_run_id)
            self.assertEqual(refs[reference]["spans"][span_index], [source.text.index("Ticket"), source.text.index("Ticket")+6])

    @staticmethod
    def _generic_fixture(root):
        revision, config, _, export, _ = CandidateFactRuntimeTests()._fixture(root)
        rows_path = export / "rows.jsonl"
        rows = [json.loads(line) for line in rows_path.read_bytes().splitlines()]
        for row, generic in zip(rows, ("bracket", "frame")):
            row["fields"]["asset_code"][0]["value"] = generic
            row["fields"]["ticket_code"][0]["value"] = "ZX-742"
        rows_path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
        digest = CandidateFactDiskIndexTests._reseal(config, export, len(rows))
        return revision, issue56_sealed_source.bind_issue56_candidate_fact_exports(
            revision, configuration_path=config, expected_sha256=digest)

    def test_empty_intersection_fallback_uses_only_digit_identity_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bound = self._generic_fixture(Path(directory))
            for selected in (bound, replace(bound, candidate_fact_rows=tuple(bound.candidate_fact_rows))):
                with self.subTest(indexed=selected is bound):
                    lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
                    self.assertEqual(len(lookup(selected, ["bracket", "frame", "ZX-742"])), 2)
                    self.assertFalse(lookup(selected, ["bracket", "frame"]))
                    self.assertFalse(lookup(selected, ["bracket", "frame", "ZX742"]))
                    self.assertEqual(len(lookup(selected, ["bracket"])), 1)

    def test_no_digit_fallback_records_reason_in_actual_trace_and_keeps_ordinary(self):
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        with tempfile.TemporaryDirectory() as directory:
            revision, bound = self._generic_fixture(Path(directory))
            args = {**CandidateFactRuntimeTests._arguments(), "required_terms": ["bracket", "frame"]}
            ordinary = loader._build_source_start_semantic_handler(revision, mail_tool=False)(args)
            trace = _SourcePhaseTrace({})
            with _source_phase_trace_scope(trace):
                result = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
            self.assertEqual(result, ordinary)
            self.assertNotIn("candidate_fact_group", json.dumps(result))
            self.assertIn("no_identifier_term", trace.snapshot())



class CandidateFactCellGroupingTests(unittest.TestCase):
    def test_repeated_inherited_cells_fit_whole_table_and_keep_all_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bound, observations = CandidateFactTablePresentationTests()._fixture(Path(directory), real_times=True)
            rows = copy.deepcopy(list(bound.candidate_fact_rows)[:2])
            donors = []
            for source in observations[:3]:
                fact = copy.deepcopy(rows[0]["fields"]["ticket_code"][0])
                digest, start = sha256_json(source.to_dict()), source.text.index("Ticket")
                fact.update(value="Ticket", source_observation_ids=[source.observation_id],
                            observation_hashes={source.observation_id: digest})
                fact["evidence_spans"][0].update(observation_id=source.observation_id,
                    observation_hash=digest, quote=source.text[start:start+12], start=start, end=start+12,
                    native_locator=source.to_dict()["location"], source_extractor_run_id=source.extractor_run_id)
                donors.append(fact)
            for row in rows:
                row["fields"] = {prop: copy.deepcopy(facts * 12) for prop, facts in row["fields"].items()}
                row["fields"]["ticket_code"] = copy.deepcopy(donors * 12)
            original = copy.deepcopy(rows)
            staged = []
            build = loader._candidate_fact_table
            def capture(*args, **kwargs):
                if kwargs.get("_counts") is None:
                    staged.append(build(*args, **{**kwargs, "_counts": (len(args[0]), 0)}))
                    print("AS69_FULL_TABLE_BYTES", len(json.dumps(staged[-1], ensure_ascii=False).encode()), flush=True)
                return build(*args, **kwargs)
            with patch.object(loader, "_candidate_fact_table", side_effect=capture):
                result = loader._build_source_start_semantic_handler(
                    replace(bound, candidate_fact_rows=tuple(rows)), mail_tool=False)(
                        CandidateFactTablePresentationTests._arguments())
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertEqual(rows, original)
            self.assertEqual(len(staged), 1)
            item = compact["evidence"][0]
            self.assertEqual(item.get("source_type"), "candidate_fact_table")
            table = json.loads(item["snippet"].split("\n", 1)[1])
            self.assertEqual([row["item"] for row in table["rows"]], ["0", "1"])
            self.assertNotIn("disclosure", table)
            self.assertEqual(sum(len(cells) for row in table["rows"] for cells in row["values"]), 10)
            refs = {citation["ref"]: citation for citation in table["citations"]}
            for row in table["rows"]:
                cell = row["values"][table["columns"].index("ticket_code")][0]
                self.assertEqual(cell["value"], "Ticket")
                self.assertEqual(len(cell["quotes"]), 3)
                for (quote_index, binding_index), source in zip(cell["quotes"], observations[:3]):
                    quote, bindings = row["quotes"][quote_index]
                    reference, span_index = bindings[binding_index]
                    citation = refs[reference]
                    start = source.text.index("Ticket")
                    self.assertEqual(quote, source.text[start:start+12])
                    self.assertEqual(citation["citation_hash"], sha256_json(source.to_dict()))
                    self.assertEqual(citation["source_observation_id"], source.observation_id)
                    self.assertEqual(citation["native_locator"], source.to_dict()["location"])
                    self.assertEqual(citation["source_extractor_run_id"], source.extractor_run_id)
                    self.assertEqual(citation["spans"][span_index], [start, start+12])
            self.assertEqual(set(item["source_context"]["required_citation_hashes"]),
                             {citation["citation_hash"] for citation in table["citations"]})
            self.assertLessEqual(len(json.dumps(staged[0], ensure_ascii=False).encode()), 10240)
            self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False).encode()), 16384)
            self.assertEqual(human_uat_orchestrator.compact_evidence_for_model(compact), compact)

    def test_distinct_typed_values_units_and_exact_time_roles_do_not_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bound, _ = CandidateFactTablePresentationTests()._fixture(Path(directory))
            rows = copy.deepcopy(list(bound.candidate_fact_rows)[:2])
            recorded = {"normalized": "2030-05-01", "role": "recorded"}
            expected = {**recorded, "role": "expected"}
            specs = [{"value": True}, {"value": 1}, {"value": "1"}, {"value": 1.0},
                     {"value": 1, "unit": "pcs"}, {"value": 1, "unit": "kg"},
                     {"value": 1, "times": [recorded]}, {"value": 1, "times": [expected]},
                     {"value": 1, "times": [recorded, expected]},
                     {"value": 1, "times": [expected, recorded]}]
            for row in rows:
                template = row["fields"]["ticket_code"][0]
                row["fields"]["ticket_code"] = [{**copy.deepcopy(template), "unit": None, "times": [], **spec}
                                               for spec in specs for _ in range(2)]
            original = copy.deepcopy(rows)
            result = loader._build_source_start_semantic_handler(replace(bound, candidate_fact_rows=tuple(rows)),
                mail_tool=False)(CandidateFactTablePresentationTests._arguments())
            compact = human_uat_orchestrator.compact_evidence_for_model(result)
            table = json.loads(compact["evidence"][0]["snippet"].split("\n", 1)[1])
            self.assertEqual([row["item"] for row in table["rows"]], ["0", "1"])
            for row in table["rows"]:
                cells = row["values"][table["columns"].index("ticket_code")]
                self.assertEqual(len(cells), len(specs))
                self.assertEqual(json.dumps([{key: value for key, value in cell.items() if key != "quotes"}
                                             for cell in cells]), json.dumps(specs))
                self.assertTrue(all(len(cell["quotes"]) == 1 for cell in cells))
                self.assertEqual(len(row["values"][table["columns"].index("quantity")]), 1)
            self.assertEqual(rows, original)
            self.assertEqual(human_uat_orchestrator.compact_evidence_for_model(compact), compact)


class CandidateFactOrderedDisplayTests(unittest.TestCase):
    def test_duplicate_and_subset_rows_preserve_literal_values_and_their_source_bindings(self):
        # The subset precedes its survivor, and a second full row repeats it.
        rows, selected = [], {}
        for i, (amount, stamp) in enumerate([
                ("1,300", None), ("1,300", "2035/5/1"), ("1,300", "2035/5/1"),
                ("1300", "2035/5/1"), ("1,300", "2035-05-01")]):
            row = {"row_id": str(i), "item_or_row": str(i), "_identity_properties": ["identity"], "fields": {}}
            rows.append(row)
            for prop, value in [("identity", f"label-{i}"), ("amount", amount), ("stamp", stamp),
                                ("subject", f"label-{i}")]:
                if value is None:
                    continue
                digest = sha256_json([i, prop])
                quote = f"observed {value}" if (i, prop) == (2, "amount") else value
                span = {"quote": quote, "start": 0, "end": len(quote), "observation_hash": digest,
                        "observation_id": f"obs-{i}-{prop}", "source_extractor_run_id": "run-1",
                        "native_locator": {"paragraph": i}}
                if prop == "subject":
                    field = {"value_surface": value, "evidence_spans": [span]}
                    row["subject_identity"] = {"sources": [field]}
                else:
                    field = {"value": value, "evidence_spans": [span]}
                    row["fields"][prop] = [field]
                selected[digest] = [{"row": row, "property": prop, "field": field, "span": span}]
        original = copy.deepcopy(rows)
        item = loader._candidate_fact_table(rows, selected, sha256_json("pin"), deadline=time.monotonic()+5)
        self.assertEqual(rows, original)
        amount_sources = {sha256_json([i, "amount"]) for i in (0, 1)}
        stamp_sources = {sha256_json([i, "stamp"]) for i in (1, 2)}
        omitted = {max(amount_sources), max(stamp_sources)}
        required = set(selected) - omitted
        self.assertEqual(set(item["source_context"]["required_citation_hashes"]), required)
        self.assertEqual(human_uat_orchestrator._candidate_fact_table_refs(item, required), required)
        envelope = {"evidence": [item], "citations": list(required)}
        decision = {"response_kind": "answer", "coverage_status": "incomplete", "citation_ids": sorted(required)}
        human_uat_orchestrator._validate_evidence_bound_decision(decision, evidence_results=[envelope])
        with self.assertRaisesRegex(RuntimeError, "cited unavailable evidence"):
            human_uat_orchestrator._validate_evidence_bound_decision(
                {**decision, "citation_ids": sorted(omitted)}, evidence_results=[envelope])
        table = json.loads(item["snippet"].split("\n", 1)[1])
        self.assertEqual([r["item"] for r in table["rows"]], ["1", "3", "4"])
        self.assertIn("Shown 3 of 5 answer-bearing rows", table["disclosure"])
        self.assertIn("2 rows merged as duplicates/subsets", table["disclosure"])
        self.assertNotIn("Omitted rows exist", table["disclosure"])
        self.assertIn("2 duplicate source copies omitted", table["disclosure"])
        refs = {c["ref"]: c["citation_hash"] for c in table["citations"]}
        def bindings(row, cell):
            return {refs[row["quotes"][q][1][b][0]] for q, b in cell["quotes"]}
        merged, plain_amount, iso_date = table["rows"]
        def cells(row, prop):
            return row["values"][table["columns"].index(prop)]
        self.assertEqual(bindings(merged, cells(merged, "amount")[0]), {min(amount_sources), sha256_json([2, "amount"])})
        self.assertEqual(bindings(merged, cells(merged, "stamp")[0]), {min(stamp_sources)})
        self.assertEqual(bindings(merged, merged["subject"]), {sha256_json([i, "subject"]) for i in (0, 1, 2)})
        for cell in cells(merged, "identity"):
            i = int(cell["value"].split("-")[1])
            self.assertEqual(bindings(merged, cell), {sha256_json([i, "identity"])})
        self.assertEqual(cells(plain_amount, "amount")[0]["value"], "1300")
        self.assertEqual(cells(iso_date, "stamp")[0]["value"], "2035-05-01")

    def test_longest_fallback_term_and_safe_trace_hash(self):
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        with tempfile.TemporaryDirectory() as directory:
            revision, config, _, export, _ = CandidateFactRuntimeTests()._fixture(Path(directory))
            rows = [json.loads(line) for line in (export / "rows.jsonl").read_bytes().splitlines()]
            rows[0]["fields"]["ticket_code"][0]["value"] = "Q-02"
            rows[1]["fields"]["ticket_code"][0]["value"] = "frame"
            (export / "rows.jsonl").write_bytes(b"".join(json.dumps(row).encode()+b"\n" for row in rows))
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(revision, configuration_path=config,
                expected_sha256=CandidateFactDiskIndexTests._reseal(config, export, 2))
            for selected in (bound, replace(bound, candidate_fact_rows=tuple(bound.candidate_fact_rows))):
                trace = _SourcePhaseTrace({})
                with _source_phase_trace_scope(trace):
                    found = issue56_sealed_source.lookup_issue56_candidate_fact_rows(selected, ["ZX-742", "Q-02", "frame"],
                        reason_callback=human_uat_orchestrator._candidate_fact_table_status)
                self.assertEqual(len(found), 2)
                self.assertIn(sha256_json("zx-742"), trace.snapshot())
                self.assertNotIn("zx-742", trace.snapshot())

    def test_identity_only_rows_are_display_omissions_and_all_identity_falls_back(self):
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        with tempfile.TemporaryDirectory() as directory:
            bound, _ = CandidateFactReachabilityTests()._captured(Path(directory))
            rows = copy.deepcopy(list(bound.candidate_fact_rows))
            identity = {**rows[0], "row_id": "factrow_identity_only", "fields": {"asset_code": rows[0]["fields"]["asset_code"]}}
            for selected, expected in ((rows+[identity], 2), ([identity], 0)):
                trace = _SourcePhaseTrace({})
                with _source_phase_trace_scope(trace):
                    result = loader._build_source_start_semantic_handler(replace(bound, candidate_fact_rows=tuple(selected)),
                        mail_tool=False)({**CandidateFactRuntimeTests._arguments(), "required_terms": ["ZX-742"], "query_text": "Find Clienta ZX-742 expected date"})
                tables = [item for item in result["evidence"] if item.get("source_type") == "candidate_fact_table"]
                self.assertEqual(len(tables), int(bool(expected)))
                if tables:
                    table = json.loads(tables[0]["snippet"].split("\n", 1)[1])
                    self.assertEqual(len(table["rows"]), expected)
                    self.assertIn("identity-only", table["disclosure"])
                self.assertIn("identity_only_rows_omitted", trace.snapshot())
                notice = next(d for d in json.loads(trace.snapshot())["details"] if d.get("candidate_fact_status"))
                self.assertEqual(notice["identity_only_row_count"], 1)
                self.assertTrue(result["citations"])
                self.assertIsNot(result.get("coverage", {}).get("absence_claim"), True)
                self.assertEqual(len(selected), expected+1)

    def test_ordered_whole_row_prefix_fits_and_discloses_remaining_answer_rows(self):
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        with tempfile.TemporaryDirectory() as directory:
            _, bound, _ = CandidateFactTablePresentationTests()._fixture(Path(directory), real_times=True)
            rows = copy.deepcopy(list(bound.candidate_fact_rows))
            rows[-1]["fields"].pop("quantity")
            rows[0]["fields"]["target_date"][0]["times"].append({"normalized": "unknown", "role": "expected"})
            tied = {**rows[12], "fields": {**rows[12]["fields"], "ticket_code": rows[0]["fields"]["ticket_code"]},
                    "row_id": "factrow_tied_copy", "item_or_row": "12copy"}
            rows.extend([tied, {**rows[12], "row_id": "factrow_duplicate", "item_or_row": "duplicate"}])
            for row in rows:
                row["item_or_row"] += "x" * 3072
            trace = _SourcePhaseTrace({})
            with _source_phase_trace_scope(trace):
                result = loader._build_source_start_semantic_handler(replace(bound, candidate_fact_rows=tuple(rows)),
                    mail_tool=False)(CandidateFactTablePresentationTests._arguments())
                compact = human_uat_orchestrator.compact_evidence_for_model(result)
            self.assertEqual(compact["evidence"][0].get("source_type"), "candidate_fact_table")
            item = compact["evidence"][0]
            table = json.loads(item["snippet"].split("\n", 1)[1])
            shown = len(table["rows"])
            self.assertTrue(0 < shown < 15)
            self.assertIn("1 row merged as duplicate/subset", table["disclosure"])
            self.assertEqual([row["item"] for row in table["rows"]], [value + "x" * 3072 for value in (["12", "12copy"]+[str(i) for i in range(11, -1, -1)]+["13"])][:shown])
            self.assertIn(f"Shown {shown} of 16 answer-bearing rows", table["disclosure"])
            self.assertIn("not evidence of absence", table["disclosure"])
            self.assertTrue(all(len(row["values"]) == 5 and all(row["values"]) for row in table["rows"]))
            self.assertEqual(set(item["source_context"]["required_citation_hashes"]), {c["citation_hash"] for c in table["citations"]})
            self.assertLessEqual(len(json.dumps(item, ensure_ascii=False).encode()), 48 * 1024)
            self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False).encode()), 54 * 1024)
            self.assertIn("table_rows_truncated_to_budget", trace.snapshot())
            notice = next(d for d in json.loads(trace.snapshot())["details"] if d.get("candidate_fact_status"))
            self.assertEqual((notice["shown_row_count"], notice["answer_row_count"]), (shown, 16))
            self.assertEqual(human_uat_orchestrator.compact_evidence_for_model(compact), compact)


class CandidateFactDiskIndexTests(unittest.TestCase):
    _fixture = CandidateFactRuntimeTests._fixture

    @staticmethod
    def _reseal(config_path, export, count):
        manifest_path = export / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        digest = hashlib.sha256()
        with (export / "rows.jsonl").open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest.update(rows_sha256="sha256:" + digest.hexdigest(), row_count=count)
        manifest_path.write_text(json.dumps(manifest))
        config = json.loads(config_path.read_bytes())
        config["exports"][0]["manifest_sha256"] = "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        config_path.write_text(json.dumps(config))
        return "sha256:" + hashlib.sha256(config_path.read_bytes()).hexdigest()

    def test_quote_mentions_only_index_known_tokens_and_surface_as_weak_links(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, _, export, observations = self._fixture(Path(directory), filler_count=1)
            path = export / "rows.jsonl"
            rows = [json.loads(line) for line in path.read_bytes().splitlines()]
            # The only annotated identity is in a *later* row. The first
            # row's date is bound to a source quote that mentions it verbatim.
            field = rows[0]["fields"]["target_date"][0]
            rows[0]["fields"] = {"target_date": [field]}
            quote = observations[0].text.split(" filler", 1)[0]
            field["evidence_spans"][0].update(quote=quote, start=0, end=len(quote))
            path.write_bytes(b"".join(json.dumps(row).encode()+b"\n" for row in rows))
            with self.assertLogs("formowl_mail.issue56_sealed_source", level="WARNING") as logs:
                bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                    revision, configuration_path=config, expected_sha256=self._reseal(config, export, len(rows)))
            self.assertIn("mention_postings=1 ", " ".join(logs.output))
            self.assertEqual(set(bound.candidate_fact_rows.postings), {"zx-742", "r-008"})
            self.assertEqual(bound.candidate_fact_rows.postings["zx-742"], (0, 1))
            for backend in (bound, replace(bound, candidate_fact_rows=tuple(bound.candidate_fact_rows))):
                lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
                picks = lookup(backend, ["ＺＸ-７４２"])
                self.assertEqual([r["_quote_mention"] for r in picks], [True, False])
                self.assertNotIn("subject_identity", picks[0])
                self.assertFalse(lookup(backend, ["2031-04-02"]))
                args = {**CandidateFactRuntimeTests._arguments(), "required_terms": ["zx-742"],
                        "query_text": "Find Clienta ZX-742 expected dates"}
                result = loader._build_source_start_semantic_handler(backend, mail_tool=False)(args)
                item = human_uat_orchestrator.compact_evidence_for_model(result)["evidence"][0]
                table = json.loads(item["snippet"].split("\n", 1)[1])
                self.assertEqual([r.get("link") for r in table["rows"]], ["quote_mention", None])
                self.assertNotIn("subject", table["rows"][0])
                self.assertTrue(human_uat_orchestrator._candidate_fact_table_refs(item, set(result["citations"])))
                self.assertIn("quote_mention", table["disclosure"])

    def test_composite_identity_postings_use_whole_digit_tokens_and_same_row_intersection(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, _, export, _ = self._fixture(Path(directory))
            rows_path = export / "rows.jsonl"
            rows = [json.loads(line) for line in rows_path.read_bytes().splitlines()]
            value = "ZX-742 [redacted_path] Clienta bracket ZX-742 a Q9 123 1234"
            rows[0]["fields"]["asset_code"][0]["value"] = value
            rows[1]["fields"]["asset_code"][0]["value"] = "ZX-843 [redacted_path] Clienta bracket"
            rows_path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
            digest = self._reseal(config, export, len(rows))
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=digest)
            self.assertEqual(bound.candidate_fact_rows.postings.get("zx-742"), (0, 1))
            lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
            for selected in (bound, replace(bound, candidate_fact_rows=tuple(bound.candidate_fact_rows))):
                self.assertEqual(lookup(selected, [" ＺＸ-７４２ "])[0]["fields"]["asset_code"][0]["value"], value)
                self.assertEqual(len(lookup(selected, [value])), 1)
                self.assertEqual(len(lookup(selected, ["ZX-742", "R-007"])), 1)
                self.assertEqual(len(lookup(selected, ["1234"])), 1)
                hit = lookup(selected, ["ZX-742", "R-008"])[0]
                self.assertEqual(hit["row_id"], "factrow_clienta_1")
                self.assertTrue(hit["_quote_mention"])
                for terms in (["ZX742"], ["ZX-74"], ["742"], ["Clienta"],
                              ["a"], ["Q9"], ["123"], ["[redacted_path]"]):
                    with self.subTest(terms=terms, indexed=selected is bound):
                        self.assertFalse(lookup(selected, terms))
            self.assertEqual([json.loads(line) for line in rows_path.read_bytes().splitlines()], rows)

    def test_composite_subject_identity_adds_the_same_exact_token_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            value = "ZX-742 [redacted_path] Clienta bracket"
            revision, config, digest, _, _ = self._fixture(Path(directory), subject_only=True, subject_surface=value)
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=digest)
            lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
            self.assertEqual(len(lookup(bound, ["ZX-742"])), 2)
            self.assertEqual(len(lookup(bound, [value])), 2)
            self.assertEqual(len(lookup(bound, ["ZX-742", "R-008"])), 1)
            for term in ("Clienta", "a", "ZX-74", "ZX742", "[redacted_path]"):
                self.assertNotIn(term.casefold(), bound.candidate_fact_rows.postings)
                self.assertFalse(lookup(bound, [term]))

    def test_streamed_above_old_cap_indexes_exact_same_row_identities_without_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, _, export, _ = self._fixture(Path(directory))
            rows_path = export / "rows.jsonl"
            original = rows_path.read_bytes()
            filler = json.loads(original.splitlines()[0])
            filler["diagnostic_padding"] = "x" * (16 * 1024)
            with rows_path.open("wb") as output:
                for index in range(1100):
                    filler["row_id"] = f"factrow_clienta_extra_{index}"
                    asset = filler["fields"]["asset_code"][0]
                    asset["value"] = f"Clienta-{index:06d}"
                    asset["evidence_spans"][0]["quote"] = asset["value"]
                    output.write(json.dumps(filler).encode() + b"\n")
                output.write(original)
            self.assertGreater(rows_path.stat().st_size, 16 * 1024 * 1024)
            config_hash = self._reseal(config, export, 1102)
            read_bytes = Path.read_bytes
            def no_whole_rows_read(path):
                self.assertNotEqual(path, rows_path, "rows must stream, not read_bytes")
                return read_bytes(path)
            with patch.object(Path, "read_bytes", no_whole_rows_read), self.assertLogs(
                    "formowl_mail.issue56_sealed_source", level="WARNING") as logs:
                bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                    revision, configuration_path=config, expected_sha256=config_hash)
            self.assertEqual(len(bound.candidate_fact_rows), 1102)
            self.assertNotIsInstance(bound.candidate_fact_rows, (list, tuple))
            self.assertIn("estimated_index_bytes", " ".join(logs.output))
            self.assertNotIn("ZX-742", " ".join(logs.output))
            self.assertNotIn(directory, " ".join(logs.output))
            lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
            selected = lookup(bound, [" ＺＸ-７４２ ", "r-007"])
            self.assertEqual(len(selected), 1)
            selected[0]["fields"]["target_date"][0]["value"] = "locally mutated"
            self.assertEqual(lookup(bound, ["ZX-742", "R-007"])[0]["fields"]["target_date"][0]["value"], "2031-04-02")
            self.assertEqual(len(lookup(bound, ["ZX-742"])), 2)
            self.assertEqual(len(lookup(bound, ["R-008"])), 1)
            self.assertEqual(lookup(bound, ["Clienta-000000", "R-008"])[0]["row_id"], "factrow_clienta_extra_0")
            self.assertFalse(lookup(bound, ["ZX742"]))
            self.assertFalse(lookup(bound, ["ZX-742"], deadline_monotonic=0))

    def test_offset_row_tamper_and_io_failure_use_existing_guarded_source_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, config_hash, export, _ = self._fixture(Path(directory))
            bound = issue56_sealed_source.bind_issue56_candidate_fact_exports(
                revision, configuration_path=config, expected_sha256=config_hash)
            handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            arguments = {"query_text": "Find Clienta R-008 expected date", "required_terms": ["R-008"],
                "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
                "session_id": "clienta-disk-fallback", "page_size": 10}
            self.assertIn("candidate_fact_group", json.dumps(handler(arguments)))
            rows_path = export / "rows.jsonl"
            info = rows_path.lstat()
            sealed_identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            raw = rows_path.read_bytes()
            offset = len(raw.splitlines(keepends=True)[0])
            with rows_path.open("r+b") as output:
                output.seek(offset)
                output.write(raw[offset:].replace(b"2031-04-09", b"2031-04-08"))
            for mode in ("metadata", "row_sha", "missing"):
                if mode == "missing":
                    rows_path.unlink()
                stable_identity = (patch.object(issue56_sealed_source, "_candidate_fact_file_identity",
                    return_value=sealed_identity, create=True) if mode == "row_sha" else nullcontext())
                with self.subTest(mode=mode), stable_identity:
                    if mode == "row_sha":
                        # Hold only metadata stable: the offset row's own sealed
                        # hash must still reject changed bytes before projection.
                        with self.assertRaisesRegex(ContractValidationError, "row seal mismatch"):
                            bound.candidate_fact_rows[1]
                    self.assertFalse(issue56_sealed_source.lookup_issue56_candidate_fact_rows(bound, ["ZX-742"]))
                    result = handler(arguments)
                    self.assertTrue(result["citations"], result)
                    self.assertNotIn("candidate_fact_group", json.dumps(result))
                    self.assertNotEqual(result["status"], "not_found")

    def test_gib_file_and_total_preflight_reject_sparse_files_without_reading_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, config_hash, export, _ = self._fixture(Path(directory))
            rows_path = export / "rows.jsonl"
            with rows_path.open("r+b") as output:
                output.truncate(1024 ** 3 + 1)
            binder = issue56_sealed_source.bind_issue56_candidate_fact_exports
            with self.assertRaisesRegex(ContractValidationError, "unavailable or oversized"):
                binder(revision, configuration_path=config, expected_sha256=config_hash)
            with rows_path.open("r+b") as output:
                output.truncate(600 * 1024 ** 2)
            second = Path(directory) / "second-export"
            second.mkdir()
            for name in ("manifest.json", "mapping.snapshot.json"):
                shutil.copyfile(export / name, second / name)
            with (second / "rows.jsonl").open("wb") as output:
                output.truncate(600 * 1024 ** 2)
            data = json.loads(config.read_bytes())
            data["exports"].append({**data["exports"][0], "manifest_path": str(second / "manifest.json")})
            config.write_text(json.dumps(data))
            config_hash = "sha256:" + hashlib.sha256(config.read_bytes()).hexdigest()
            original_open = Path.open
            def no_rows_open(path, *args, **kwargs):
                self.assertNotEqual(path.name, "rows.jsonl", "size preflight must precede row reads")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", no_rows_open), self.assertRaisesRegex(
                    ContractValidationError, "export set exceeds the bounded intake"):
                binder(revision, configuration_path=config, expected_sha256=config_hash)

    def test_index_keeps_128_matched_rows_limit_and_duplicate_id_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            revision, config, _, export, _ = self._fixture(Path(directory))
            row = json.loads((export / "rows.jsonl").read_bytes().splitlines()[0])
            binder = issue56_sealed_source.bind_issue56_candidate_fact_exports
            lookup = issue56_sealed_source.lookup_issue56_candidate_fact_rows
            for count in (128, 129):
                with (export / "rows.jsonl").open("wb") as output:
                    for index in range(count):
                        row["row_id"] = f"factrow_clienta_{index}"
                        output.write(json.dumps(row).encode() + b"\n")
                config_hash = self._reseal(config, export, count)
                bound = binder(revision, configuration_path=config, expected_sha256=config_hash)
                self.assertEqual(len(lookup(bound, ["ZX-742"])), 128 if count == 128 else 0)
            with (export / "rows.jsonl").open("ab") as output:
                output.write(json.dumps(row).encode() + b"\n")
            config_hash = self._reseal(config, export, 130)
            with self.assertRaisesRegex(ContractValidationError, "row binding is invalid"):
                binder(revision, configuration_path=config, expected_sha256=config_hash)


def _source_start_preparation_fixture(
    root: Path, *, families=("mail", "document_text"),
    mail_text="Acceptance requires written owner approval.",
    source_completeness_certified=False,
    document_text=None,
    attachment_csv=None,
    attachment_content=None,
    inline_html=None,
):
    """Real completed jobs; only their immutable reference checkpoint is synthetic.

    No projection, embedding, graph, mail attachment or alternate source store
    is manufactured. The format mirrors the existing preembedding checkpoint.
    """
    authorities, observations, observation_groups, bindings, jobs = [], [], [], [], []
    for family in families:
        directory = root / family
        directory.mkdir()
        if family == "document_text":
            asset, items, authority = _completed_registered_text_revision_fixture(
                directory, owner_user_id=loader.APPROVER_ACTOR,
                source_text=document_text,
            )
        else:
            source_path = directory / "archive.json"
            source_path.write_text(json.dumps({
                "archive_id": "archive_source_start",
                "mailbox_id": "mailbox_source_start",
                "folders": [{"folder_path_hash": sha256_json("inbox"), "label": "Inbox"}],
                "messages": [{
                    "message_id": "<source-start@example.test>",
                    "folder_path_hash": sha256_json("inbox"),
                    "subject": "Project acceptance",
                    "sender": "owner@example.test",
                    "sent_at": "2026-09-01T00:00:00+00:00",
                    "body": mail_text,
                    "body_hash": sha256_json(mail_text),
                }],
            }), encoding="utf-8")
            registry = StorageBackendRegistry(directory)
            backend = registry.register_local_backend(
                directory / "object-store", workspace_scope=loader.WORKSPACE_ID,
            )
            object_store = FileObjectStore(registry)
            asset_store, job_store = AssetStore(directory), JobStore(directory)
            observation_store, run_store = ObservationStore(directory), ExtractorRunStore(directory)
            asset = register_asset_from_local_file(
                source_path, object_store=object_store, asset_store=asset_store,
                storage_backend_id=backend.storage_backend_id,
                workspace_id=loader.WORKSPACE_ID, owner_user_id=loader.APPROVER_ACTOR,
                permission_scope=PermissionScope.project("project_source_mail"),
                source_ref=SourceRef(
                    source_system="formowl_upload_session", source_type="mail_archive_upload",
                    source_id=f"upload_source_start_{family}",
                    source_key=f"upload_source_start_{family}",
                ),
                mime_type="application/vnd.formowl.mail-archive+json",
                created_at="2026-09-01T00:00:00+00:00",
                registered_at="2026-09-01T00:00:00+00:00",
            )
            class TableFixtureExtractor(FixtureMailArchiveExtractor):
                def extract(self, extraction_input):
                    result = super().extract(extraction_input)
                    if inline_html is not None:
                        from formowl_ingestion.extractors.mail.pst import _HtmlTextExtractor, _inline_table_observations
                        parser = _HtmlTextExtractor()
                        parser.feed(inline_html)
                        parser.close()
                        tables = [{**table, "mime_ordinal": 1, "parent_mime_ordinal": 0, "quoted_depth": 0}
                                  for table in parser.tables]
                        message = next(item for item in result.observations if item.observation_type == "email_message")
                        result.observations.extend(_inline_table_observations(
                            SimpleNamespace(html_tables=tables), message, 1,
                        ))
                    if attachment_csv is None and attachment_content is None:
                        return result
                    message = next(item for item in result.observations if item.observation_type == "email_message")
                    content, content_mime = (
                        attachment_content if attachment_content is not None
                        else (attachment_csv.encode("utf-8"), "text/csv")
                    )
                    child_id = extraction_input.attachment_materialization.materialize(
                        content=content, expected_content_hash="sha256:" + hashlib.sha256(content).hexdigest(),
                        mime_type=content_mime, source_ref=SourceRef(
                            source_system="formowl_mail_attachment", source_type="email_attachment_occurrence",
                            source_id="synthetic-native-table", source_key=message.location["message_occurrence_id"],
                        ),
                    )
                    result.observations.append(Observation(
                        observation_id="synthetic_table_parent", asset_id=extraction_input.asset.asset_id,
                        extractor_run_id=extraction_input.extractor_run_id,
                        observation_type="email_attachment_occurrence", modality="mail", text="Native table",
                        confidence=1.0,
                        location={"message_occurrence_id": message.location["message_occurrence_id"], "attachment_index": 1},
                        permission_scope=extraction_input.asset.permission_scope,
                        created_at=extraction_input.created_at,
                        payload={"child_asset_id": child_id, "attachment_extraction_status": "extracted",
                                 "content_hash": "sha256:" + hashlib.sha256(content).hexdigest()},
                    ))
                    return result

            adapter = TableFixtureExtractor()
            job = create_ingestion_job(
                asset=asset, job_store=job_store, requested_by=loader.APPROVER_ACTOR,
                extractor_adapters=(adapter,), created_at="2026-09-01T00:00:00+00:00",
            )
            completed = run_ingestion_job(
                ingestion_job_id=job.ingestion_job_id, asset_store=asset_store,
                job_store=job_store, object_store=object_store, extractor_run_store=run_store,
                observation_store=observation_store, extractor_adapters=(adapter,),
                attachment_asset_store=asset_store if attachment_csv is not None or attachment_content is not None else None,
                started_at="2026-09-01T00:00:00+00:00",
                completed_at="2026-09-01T00:00:00+00:00",
            )
            reader = open_completed_ingestion_job_reader(
                completed.ingestion_job_id, job_store=job_store, asset_store=asset_store,
                observation_store=observation_store, extractor_run_store=run_store,
                requester_user_id=loader.APPROVER_ACTOR, workspace_id=loader.WORKSPACE_ID,
            )
            items, authority = tuple(reader.iter_observations()), reader.authority
        index = len(authorities)
        authorities.append(authority)
        observations.extend(items)
        observation_groups.append(items)
        bindings.append({
            "job_index": index, "store_directory": str(directory.resolve()),
            "ingestion_job_id": authority.ingestion_job_id,
            "job_fingerprint": authority.job_fingerprint,
            "observation_count": authority.observation_count,
        })
        jobs.append({
            "root_asset_hash": asset.content_hash, "job_fingerprint": authority.job_fingerprint,
            "run_fingerprints": [
                sha256_json(run.to_dict()) for run in authority.runs
            ],
            "observation_count": authority.observation_count, "excluded_child_runs": [],
        })
    authority_hash = sha256_json({
        "artifact_id": "formowl_completed_ingestion_job_authority_v1",
        "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
        "jobs": jobs,
    })
    preparation = root / "prepared"
    exact = preparation / "exact-cells"
    exact.mkdir(parents=True)
    runtime = _contract_only_runtime()
    exact_core = {
        "artifact_id": "formowl_issue56_ingestion_exact_cell_lookup_v1",
        "schema_version": 1, "source_authority_fingerprint": authority_hash,
        "tokenizer_profile_fingerprint": runtime.tokenizer_profile.profile_fingerprint,
        "job_count": len(jobs),
        "counts": {key: 0 for key in (
            "table_row", "table_cell", "source_provided_row", "candidate_only_row",
            "unavailable_row", "attachment_authorized_row", "attachment_unresolved_row",
            "inline_authorized_row", "inline_unresolved_row",
        )},
        "columns": [], "shards": [],
    }
    shard_records = {}
    for job_index, items in enumerate(observation_groups):
        for item in items:
            if item.observation_type not in {"table_row", "table_cell"}:
                continue
            key = sha256_json(loader._table_row_key(item))
            kind = "row" if item.observation_type == "table_row" else "cell"
            inline = item.payload.get("lineage", {}).get("source_family") == "mail_inline_table"
            record = [kind, key, job_index, item.observation_id, sha256_json(item.to_dict())]
            exact_core["counts"][item.observation_type] += 1
            structure = item.payload["table_structure"]
            if kind == "row":
                exact_core["counts"][structure["structure_status"] + "_row"] += 1
                exact_core["counts"]["inline_authorized_row" if inline else "attachment_authorized_row"] += 1
            else:
                field = structure.get("column_name") or f"column_{item.location['cell_index']}"
                column_hash = loader.source_occurrence_column_capability_hash(
                    runtime.tokenizer_profile.normalize_exact_identifier_surface(field),
                )
                record.append(column_hash)
                column = {
                    "field": field, "column_hash": column_hash, "inline_table": inline,
                    "structure_status": structure["structure_status"],
                    "candidate_hashes": [sha256_json(field)],
                }
                if column not in exact_core["columns"]:
                    exact_core["columns"].append(column)
                value_hashes = {sha256_json(token) for token in runtime.tokenizer_profile.analyze(item.text or "").tokens}
                if item.text:
                    value_hashes.add(loader.source_occurrence_exact_cell_value_hash(column_hash, item.text))
                for value_hash in value_hashes:
                    shard_records.setdefault(("value", value_hash[7:9]), []).append([value_hash, key, inline])
            record.append(inline)
            shard_records.setdefault(("row", key[7:9]), []).append(record)
    for (kind, shard), records in sorted(shard_records.items()):
        path = exact / ("rows" if kind == "row" else "values") / f"{shard}.jsonl"
        path.parent.mkdir(exist_ok=True)
        payload = b"".join(json.dumps(record).encode() + b"\n" for record in records)
        path.write_bytes(payload)
        exact_core["shards"].append({
            "kind": kind, "shard": shard, "record_count": len(records), "size_bytes": len(payload),
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        })
    exact_bytes = json.dumps({
        **exact_core, "manifest_fingerprint": sha256_json(exact_core),
    }, sort_keys=True).encode()
    (exact / "manifest.json").write_bytes(exact_bytes)
    exact_hash = "sha256:" + hashlib.sha256(exact_bytes).hexdigest()
    source_binding = {
        "jobs": jobs, "source_authority_fingerprint": authority_hash,
        "exact_lookup_manifest_sha256": exact_hash,
        "extraction_coverage": {
            "scope": "declared_completed_jobs_only", "root_count": len(jobs),
            "warning_count": 0, "warning_code_counts": {},
            "source_completeness_certified": source_completeness_certified,
        },
    }
    references = [
        [index, item.observation_id, sha256_json(item.to_dict())]
        for index, items in enumerate(observation_groups) for item in items
    ]
    snapshot = {
        "bundles": [], "observation_references": references,
        "source_binding": source_binding, "job_store_bindings": bindings,
    }
    snapshot_bytes = json.dumps(snapshot, sort_keys=True).encode()
    (preparation / "observations.json").write_bytes(snapshot_bytes)
    core = {
        "artifact_id": "formowl_issue56_ingestion_revision_preparation_v1",
        "schema_version": 1,
        "requested_jobs": [[item["store_directory"], item["ingestion_job_id"]] for item in bindings],
        "sidecar_parent_job_id": None, "reference_repair_binding": None,
        "bound_child_failure_binding": None, "sidecar_parent_binding_sha256": None,
        "snapshot_sha256": "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest(),
        "snapshot_size_bytes": len(snapshot_bytes),
        "exact_lookup_manifest_sha256": exact_hash,
        "source_observation_count": len(observations),
        "observation_type_counts": {
            kind: sum(item.observation_type == kind for item in observations)
            for kind in sorted({item.observation_type for item in observations})
        },
        "job_count": len(jobs),
    }
    prepared_bytes = json.dumps({
        **core, "preparation_fingerprint": sha256_json(core),
    }, sort_keys=True).encode()
    (preparation / "preparation.json").write_bytes(prepared_bytes)
    return SimpleNamespace(
        directory=preparation,
        preparation_sha256="sha256:" + hashlib.sha256(prepared_bytes).hexdigest(),
        preparation_core=core, snapshot=snapshot, runtime=runtime,
        authorities=tuple(authorities), observations=tuple(observations),
    )


if __name__ == "__main__":
    unittest.main()
