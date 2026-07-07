from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Grant, PermissionScope, SourceRef
from formowl_gateway import (
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
)
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors import FixtureMailArchiveExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)
import formowl_mail.query as mail_query
from formowl_mail import (
    MailCaseProgressGateway,
    MailEvidenceQueryGateway,
    build_mail_case_progress_handler,
    build_mail_evidence_bundle,
    build_mail_evidence_query_handler,
)

NOW = "2026-07-05T10:00:00+00:00"


class MailEvidenceMcpGatewayTests(unittest.TestCase):
    def test_mail_case_progress_answer_filters_before_returning_content(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-case-progress-permissions")
        bundle = _mail_bundle(temp_dir)
        gateway = MailCaseProgressGateway([bundle])

        denied = gateway.answer_case_progress(
            case_id="case_launch",
            requester_user_id="user_other",
            workspace_id="workspace_formowl",
            session_id="session_other",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            now=NOW,
            generated_at=NOW,
        ).to_dict()
        self.assertEqual(denied["status"], "permission_denied")
        self.assertEqual(denied["blockers"], [])
        self.assertEqual(denied["citations"], [])
        self.assertEqual(denied["redaction_counts"]["hidden_bundles"], 1)
        self.assertNotIn("Waiting on audit approval", str(denied))

        owner = gateway.answer_case_progress(
            case_id="case_launch",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            now=NOW,
            generated_at=NOW,
        ).to_dict()
        self.assertEqual(owner["status"], "ok")
        self.assertEqual(owner["blockers"][0]["text"], "Waiting on audit approval")
        self.assertIn(
            owner["blockers"][0]["observation_id"],
            {citation["observation_id"] for citation in owner["citations"]},
        )
        self.assertTrue(owner["claim_boundary"]["supports_mail_case_progress_answer_claim"])
        self.assertFalse(owner["claim_boundary"]["supports_kg_write_claim"])
        self.assertFalse(owner["claim_boundary"]["supports_wiki_projection_claim"])

        granted = gateway.answer_case_progress(
            case_id="case_launch",
            requester_user_id="user_other",
            workspace_id="workspace_formowl",
            session_id="session_granted",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            grants=[_mail_session_grant(bundle, grantee_user_id="user_other")],
            now=NOW,
            generated_at=NOW,
        ).to_dict()
        self.assertEqual(granted["status"], "ok")
        self.assertTrue(granted["citations"])

    def test_mail_case_progress_answer_safe_not_found_and_no_marker_paths(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-case-progress-input-guards")
        bundle = _mail_bundle(temp_dir)
        gateway = MailCaseProgressGateway([bundle])

        not_found = gateway.answer_case_progress(
            case_id="case_launch",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_import_session_id="mailimport_missing",
            now=NOW,
            generated_at=NOW,
        ).to_dict()
        self.assertEqual(not_found["status"], "not_found")
        self.assertEqual(not_found["blockers"], [])
        self.assertEqual(not_found["citations"], [])
        self.assertNotIn("Waiting on audit approval", str(not_found))

        with self.assertRaises(ContractValidationError):
            gateway.answer_case_progress(
                case_id="case_launch",
                requester_user_id="user_yifan",
                workspace_id="workspace_formowl",
                session_id="session_owner",
                now=NOW,
                generated_at=NOW,
            )

        no_marker_bundle = _mail_bundle(temp_dir / "no-marker", _mail_archive_no_markers())
        no_marker = (
            MailCaseProgressGateway([no_marker_bundle])
            .answer_case_progress(
                case_id="case_launch",
                requester_user_id="user_yifan",
                workspace_id="workspace_formowl",
                session_id="session_owner",
                mail_import_session_id=(
                    no_marker_bundle.mail_import_session.mail_import_session_id
                ),
                now=NOW,
                generated_at=NOW,
            )
            .to_dict()
        )
        self.assertEqual(no_marker["status"], "ok")
        self.assertEqual(no_marker["latest_updates"], [])
        self.assertEqual(no_marker["blockers"], [])
        self.assertEqual(no_marker["citations"], [])
        self.assertEqual(no_marker["warnings"], ["no_case_progress_evidence"])

    def test_mail_case_progress_answer_supports_bundle_id_and_denies_conflicts(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-case-progress-bundle-id")
        bundle = _mail_bundle(temp_dir)
        gateway = MailCaseProgressGateway([bundle])

        bundle_id_only = gateway.answer_case_progress(
            case_id="case_launch",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            now=NOW,
            generated_at=NOW,
        ).to_dict()
        self.assertEqual(bundle_id_only["status"], "ok")
        self.assertEqual(
            bundle_id_only["mail_import_session_id"],
            bundle.mail_import_session.mail_import_session_id,
        )
        self.assertTrue(bundle_id_only["citations"])

        matching_dual_ids = gateway.answer_case_progress(
            case_id="case_launch",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            now=NOW,
            generated_at=NOW,
        ).to_dict()
        self.assertEqual(matching_dual_ids["status"], "ok")

        conflicting_dual_ids = gateway.answer_case_progress(
            case_id="case_launch",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            mail_evidence_bundle_id="mailbundle_other",
            now=NOW,
            generated_at=NOW,
        ).to_dict()
        self.assertEqual(conflicting_dual_ids["status"], "not_found")
        self.assertEqual(conflicting_dual_ids["blockers"], [])
        self.assertEqual(conflicting_dual_ids["citations"], [])
        self.assertNotIn("Waiting on audit approval", str(conflicting_dual_ids))

    def test_mail_case_progress_answer_denies_invalid_grants_without_content(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-case-progress-invalid-grants")
        bundle = _mail_bundle(temp_dir)
        gateway = MailCaseProgressGateway([bundle])
        invalid_grants = {
            "expired": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                expires_at="2026-07-04T00:00:00+00:00",
            ),
            "revoked": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                revoked_at="2026-07-05T09:00:00+00:00",
            ),
            "wrong_permission": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                permission="graph_snippet",
            ),
            "wrong_scope_type": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                scope_type="project",
                scope_id="project_formowl",
            ),
            "wrong_scope_id": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                scope_id="mailimport_other",
            ),
            "wrong_owner": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                owner_user_id="user_wrong_owner",
            ),
        }

        for case_name, grant in invalid_grants.items():
            with self.subTest(case_name=case_name):
                denied = gateway.answer_case_progress(
                    case_id="case_launch",
                    requester_user_id="user_other",
                    workspace_id="workspace_formowl",
                    session_id=f"session_{case_name}",
                    mail_import_session_id=(bundle.mail_import_session.mail_import_session_id),
                    grants=[grant],
                    now=NOW,
                    generated_at=NOW,
                ).to_dict()

                self.assertEqual(denied["status"], "permission_denied")
                self.assertEqual(denied["blockers"], [])
                self.assertEqual(denied["citations"], [])
                self.assertEqual(denied["redaction_counts"]["hidden_bundles"], 1)
                self.assertEqual(denied["redaction_counts"]["hidden_messages"], 1)
                self.assertNotIn("Waiting on audit approval", str(denied))

    def test_mail_evidence_query_filters_before_returning_content(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-query-permissions")
        bundle = _mail_bundle(temp_dir)
        gateway = MailEvidenceQueryGateway([bundle])

        denied = gateway.query_mail_evidence(
            query_text="audit approval",
            requester_user_id="user_other",
            workspace_id="workspace_formowl",
            session_id="session_other",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            now=NOW,
        ).to_dict()
        self.assertEqual(denied["status"], "permission_denied")
        self.assertEqual(denied["evidence_snippets"], [])
        self.assertNotIn("Waiting on audit approval", str(denied))
        self.assertEqual(denied["redaction_counts"]["hidden_bundles"], 1)

        owner = gateway.query_mail_evidence(
            query_text="audit approval",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            now=NOW,
        ).to_dict()
        self.assertEqual(owner["status"], "ok")
        self.assertEqual(owner["evidence_snippets"][0]["source_type"], "mail_body_segment")
        self.assertIn("Waiting on audit approval", owner["evidence_snippets"][0]["snippet"])
        self.assertEqual(
            owner["citations"][0]["source_observation_id"],
            owner["evidence_snippets"][0]["source_observation_id"],
        )

        granted = gateway.query_mail_evidence(
            query_text="audit approval",
            requester_user_id="user_other",
            workspace_id="workspace_formowl",
            session_id="session_granted",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            grants=[_mail_session_grant(bundle, grantee_user_id="user_other")],
            now=NOW,
        ).to_dict()
        self.assertEqual(granted["status"], "ok")
        self.assertTrue(granted["evidence_snippets"])

    def test_mail_evidence_query_index_prunes_nonmatching_snippets(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-query-index-pruning")
        bundle = _mail_bundle(temp_dir)
        base_index = mail_query._build_snippet_index(bundle)
        audit_snippet = next(
            snippet for snippet in base_index.snippets if "audit" in snippet.searchable_tokens
        )

        class PoisonSnippet:
            @property
            def searchable_tokens(self):
                raise AssertionError("nonmatching snippet should not be scanned")

            @property
            def payload(self):
                raise AssertionError("nonmatching snippet should not be materialized")

        pruned_index = mail_query._MailSnippetIndex(
            snippets=(audit_snippet, PoisonSnippet()),
            snippet_indexes_by_token={"audit": (0,)},
        )

        matched = mail_query._search_visible_bundles(
            [bundle],
            query_text="audit",
            limit=5,
            snippet_index_by_bundle_id={bundle.mail_evidence_bundle_id: pruned_index},
        )
        missed = mail_query._search_visible_bundles(
            [bundle],
            query_text="not-present-in-index",
            limit=5,
            snippet_index_by_bundle_id={bundle.mail_evidence_bundle_id: pruned_index},
        )

        self.assertEqual(len(matched), 1)
        self.assertEqual(
            matched[0]["source_observation_id"],
            audit_snippet.payload["source_observation_id"],
        )
        self.assertEqual(missed, [])

    def test_mail_evidence_query_gateway_builds_index_once_per_bundle(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-query-index-cache")
        bundle = _mail_bundle(temp_dir)
        original = mail_query._build_snippet_index
        build_count = 0

        def spy(target_bundle):
            nonlocal build_count
            build_count += 1
            return original(target_bundle)

        mail_query._build_snippet_index = spy
        try:
            gateway = MailEvidenceQueryGateway([bundle])
            for query_text, requester_user_id in (
                ("audit approval", "user_yifan"),
                ("formowl-no-visible-match", "user_yifan"),
                ("audit approval", "user_other"),
            ):
                gateway.query_mail_evidence(
                    query_text=query_text,
                    requester_user_id=requester_user_id,
                    workspace_id="workspace_formowl",
                    session_id="session_index_cache",
                    mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
                    now=NOW,
                ).to_dict()
        finally:
            mail_query._build_snippet_index = original

        self.assertEqual(build_count, 1)

    def test_mail_evidence_query_rejects_raw_or_missing_inputs_without_content(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-query-input-guards")
        bundle = _mail_bundle(temp_dir)
        gateway = MailEvidenceQueryGateway([bundle])

        not_found = gateway.query_mail_evidence(
            query_text="audit approval",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_import_session_id="mailimport_missing",
            now=NOW,
        ).to_dict()
        self.assertEqual(not_found["status"], "not_found")
        self.assertEqual(not_found["evidence_snippets"], [])

        with self.assertRaises(ContractValidationError):
            gateway.query_mail_evidence(
                query_text="select * from mailbox_messages",
                requester_user_id="user_yifan",
                workspace_id="workspace_formowl",
                session_id="session_owner",
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
                now=NOW,
            )
        with self.assertRaises(ContractValidationError):
            gateway.query_mail_evidence(
                query_text="audit approval",
                requester_user_id="user_yifan",
                workspace_id="workspace_formowl",
                session_id="session_owner",
                now=NOW,
            )

    def test_mail_evidence_query_supports_bundle_id_and_denies_conflicts(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-query-bundle-id")
        bundle = _mail_bundle(temp_dir)
        gateway = MailEvidenceQueryGateway([bundle])

        bundle_id_only = gateway.query_mail_evidence(
            query_text="audit approval",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            now=NOW,
        ).to_dict()
        self.assertEqual(bundle_id_only["status"], "ok")
        self.assertEqual(
            bundle_id_only["mail_import_session_id"],
            bundle.mail_import_session.mail_import_session_id,
        )
        self.assertTrue(bundle_id_only["citations"])

        matching_dual_ids = gateway.query_mail_evidence(
            query_text="audit approval",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            now=NOW,
        ).to_dict()
        self.assertEqual(matching_dual_ids["status"], "ok")

        conflicting_dual_ids = gateway.query_mail_evidence(
            query_text="audit approval",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_owner",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            mail_evidence_bundle_id="mailbundle_other",
            now=NOW,
        ).to_dict()
        self.assertEqual(conflicting_dual_ids["status"], "not_found")
        self.assertEqual(conflicting_dual_ids["evidence_snippets"], [])
        self.assertEqual(conflicting_dual_ids["citations"], [])
        self.assertNotIn("Waiting on audit approval", str(conflicting_dual_ids))

    def test_mail_evidence_query_denies_invalid_grants_without_content(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-query-invalid-grants")
        bundle = _mail_bundle(temp_dir)
        gateway = MailEvidenceQueryGateway([bundle])
        invalid_grants = {
            "expired": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                expires_at="2026-07-04T00:00:00+00:00",
            ),
            "revoked": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                revoked_at="2026-07-05T09:00:00+00:00",
            ),
            "wrong_permission": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                permission="graph_snippet",
            ),
            "wrong_scope_type": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                scope_type="project",
                scope_id="project_formowl",
            ),
            "wrong_scope_id": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                scope_id="mailimport_other",
            ),
            "wrong_owner": _mail_session_grant(
                bundle,
                grantee_user_id="user_other",
                owner_user_id="user_wrong_owner",
            ),
        }

        for case_name, grant in invalid_grants.items():
            with self.subTest(case_name=case_name):
                denied = gateway.query_mail_evidence(
                    query_text="audit approval",
                    requester_user_id="user_other",
                    workspace_id="workspace_formowl",
                    session_id=f"session_{case_name}",
                    mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
                    grants=[grant],
                    now=NOW,
                ).to_dict()

                self.assertEqual(denied["status"], "permission_denied")
                self.assertEqual(denied["evidence_snippets"], [])
                self.assertEqual(denied["citations"], [])
                self.assertEqual(denied["redaction_counts"]["hidden_bundles"], 1)
                self.assertEqual(denied["redaction_counts"]["hidden_messages"], 1)
                self.assertNotIn("Waiting on audit approval", str(denied))

    def test_semantic_gateway_exposes_mail_evidence_tool_with_safe_handler(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-semantic-gateway")
        bundle = _mail_bundle(temp_dir)
        gateway = SemanticMcpGateway(
            mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=NOW)
        )

        schema = gateway.public_tool_schema()
        mail_schema = [
            tool for tool in schema["data"]["tools"] if tool["tool_name"] == "query_mail_evidence"
        ][0]
        self.assertEqual(mail_schema["workflow"], "mail_evidence")
        self.assertIn("mail_import_session_id", mail_schema["input_keys"])

        result = gateway.dispatch_tool(
            "query_mail_evidence",
            {
                "workspace_id": "workspace_formowl",
                "requester_user_id": "user_yifan",
                "session_id": "session_owner",
                "query_text": "audit approval",
                "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            },
        )
        self.assertEqual(result["result_type"], "mail_evidence_query")
        self.assertEqual(result["status"], "ok")
        self.assertIn("Waiting on audit approval", str(result["data"]["evidence_snippets"]))

        pending = SemanticMcpGateway().dispatch_tool(
            "query_mail_evidence",
            {
                "workspace_id": "workspace_formowl",
                "requester_user_id": "user_yifan",
                "query_text": "audit approval",
                "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            },
        )
        self.assertEqual(pending["status"], "pending_review")
        self.assertEqual(pending["data"]["evidence_snippets"], [])

        unsafe_gateway = SemanticMcpGateway(
            mail_evidence_handler=lambda _payload: {
                "status": "ok",
                "mail_import_session_id": "mailimport_001",
                "query_hash": "sha256:unsafe",
                "evidence_snippets": [{"snippet": "object://mail/raw/private"}],
            }
        )
        with self.assertRaises(ContractValidationError):
            unsafe_gateway.dispatch_tool(
                "query_mail_evidence",
                {
                    "workspace_id": "workspace_formowl",
                    "requester_user_id": "user_yifan",
                    "query_text": "audit approval",
                    "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
                },
            )

    def test_semantic_gateway_exposes_mail_case_progress_tool_with_safe_handler(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-case-progress-semantic-gateway")
        bundle = _mail_bundle(temp_dir)
        gateway = SemanticMcpGateway(
            mail_case_progress_handler=build_mail_case_progress_handler(
                [bundle],
                now=NOW,
                generated_at=NOW,
            )
        )

        schema = gateway.public_tool_schema()
        case_schema = [
            tool
            for tool in schema["data"]["tools"]
            if tool["tool_name"] == "answer_mail_case_progress"
        ][0]
        self.assertEqual(case_schema["workflow"], "mail_evidence")
        self.assertIn("case_id", case_schema["input_keys"])

        result = gateway.dispatch_tool(
            "answer_mail_case_progress",
            {
                "workspace_id": "workspace_formowl",
                "requester_user_id": "user_yifan",
                "session_id": "session_owner",
                "case_id": "case_launch",
                "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            },
        )
        self.assertEqual(result["result_type"], "mail_case_progress_answer")
        self.assertEqual(result["status"], "ok")
        self.assertIn("Waiting on audit approval", str(result["data"]["blockers"]))
        self.assertTrue(result["data"]["citations"])

        pending = SemanticMcpGateway().dispatch_tool(
            "answer_mail_case_progress",
            {
                "workspace_id": "workspace_formowl",
                "requester_user_id": "user_yifan",
                "case_id": "case_launch",
                "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            },
        )
        self.assertEqual(pending["status"], "pending_review")
        self.assertEqual(pending["data"]["blockers"], [])

        unsafe_gateway = SemanticMcpGateway(
            mail_case_progress_handler=lambda _payload: {
                "status": "ok",
                "mail_import_session_id": "mailimport_001",
                "mail_evidence_bundle_id": "mailbundle_001",
                "case_id": "case_launch",
                "latest_updates": [],
                "blockers": [{"text": "object://mail/raw/private"}],
                "responsible_parties": [],
                "next_actions": [],
                "deadlines": [],
                "citations": [],
                "redaction_counts": {"hidden_bundles": 0, "hidden_messages": 0},
                "warnings": [],
            }
        )
        with self.assertRaises(ContractValidationError):
            unsafe_gateway.dispatch_tool(
                "answer_mail_case_progress",
                {
                    "workspace_id": "workspace_formowl",
                    "requester_user_id": "user_yifan",
                    "case_id": "case_launch",
                    "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                },
            )

        overclaim_gateway = SemanticMcpGateway(
            mail_case_progress_handler=lambda _payload: {
                "status": "ok",
                "mail_import_session_id": "mailimport_001",
                "mail_evidence_bundle_id": "mailbundle_001",
                "case_id": "case_launch",
                "latest_updates": [],
                "blockers": [],
                "responsible_parties": [],
                "next_actions": [],
                "deadlines": [],
                "citations": [],
                "redaction_counts": {"hidden_bundles": 0, "hidden_messages": 0},
                "warnings": [],
                "claim_boundary": {
                    "supports_mail_case_progress_answer_claim": True,
                    "supports_actual_chatgpt_connected_upload_claim": False,
                    "supports_upload_ui_claim": False,
                    "supports_production_iframe_readiness_claim": False,
                    "supports_real_pst_parser_claim": False,
                    "supports_live_postgresql_readiness_claim": False,
                    "supports_production_worker_leasing_claim": True,
                    "supports_kg_write_claim": False,
                    "supports_wiki_projection_claim": False,
                    "supports_production_ready_claim": False,
                },
            }
        )
        with self.assertRaises(ContractValidationError):
            overclaim_gateway.dispatch_tool(
                "answer_mail_case_progress",
                {
                    "workspace_id": "workspace_formowl",
                    "requester_user_id": "user_yifan",
                    "case_id": "case_launch",
                    "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                },
            )

    def test_jsonrpc_mail_evidence_query_binds_session_and_hashes_transcript(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-jsonrpc")
        bundle = _mail_bundle(temp_dir)
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=NOW)
            ),
            session=SemanticGatewaySession(
                session_id="session_jsonrpc",
                actor_user_id="user_yifan",
                workspace_id="workspace_formowl",
            ),
        )

        tools = gateway.handle_json_rpc({"jsonrpc": "2.0", "id": "tools", "method": "tools/list"})
        self.assertIn(
            "query_mail_evidence",
            {tool["name"] for tool in tools["result"]["tools"]},
        )
        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_query",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "mail_import_session_id": (
                            bundle.mail_import_session.mail_import_session_id
                        ),
                    },
                },
            }
        )

        content = result["result"]["content"][0]["json"]
        self.assertFalse(result["result"]["isError"])
        self.assertEqual(content["status"], "ok")
        self.assertEqual(result["result"]["session"]["actor_user_id"], "user_yifan")
        self.assertIn("Waiting on audit approval", str(content["data"]["evidence_snippets"]))
        transcript = gateway.leak_transcript()
        self.assertEqual(set(transcript[0]), {"method", "request_hash", "response_hash", "status"})
        self.assertNotIn("audit approval", str(transcript))
        self.assertNotIn("Waiting on audit approval", str(transcript))

        unsafe = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_attack",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "select * from mailbox_messages",
                        "mail_import_session_id": (
                            bundle.mail_import_session.mail_import_session_id
                        ),
                    },
                },
            }
        )
        self.assertTrue(unsafe["result"]["isError"])
        self.assertNotIn("select *", str(unsafe).lower())

    def test_jsonrpc_mail_evidence_query_supports_bundle_id_without_session_id(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-jsonrpc-bundle-id")
        bundle = _mail_bundle(temp_dir)
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=NOW)
            ),
            session=SemanticGatewaySession(
                session_id="session_jsonrpc_bundle",
                actor_user_id="user_yifan",
                workspace_id="workspace_formowl",
            ),
        )

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_query_by_bundle",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
                    },
                },
            }
        )

        content = result["result"]["content"][0]["json"]
        self.assertFalse(result["result"]["isError"])
        self.assertEqual(content["status"], "ok")
        self.assertEqual(
            content["data"]["mail_import_session_id"],
            bundle.mail_import_session.mail_import_session_id,
        )
        self.assertEqual(
            content["data"]["citations"][0]["source_observation_id"],
            content["data"]["evidence_snippets"][0]["source_observation_id"],
        )
        self.assertEqual(result["result"]["session"]["actor_user_id"], "user_yifan")
        transcript = gateway.leak_transcript()
        self.assertEqual(set(transcript[0]), {"method", "request_hash", "response_hash", "status"})
        self.assertNotIn("audit approval", str(transcript))
        self.assertNotIn("Waiting on audit approval", str(transcript))

        missing = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_query_missing_bundle",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "mail_evidence_bundle_id": "mailbundle_missing",
                    },
                },
            }
        )
        missing_content = missing["result"]["content"][0]["json"]
        self.assertFalse(missing["result"]["isError"])
        self.assertEqual(missing_content["status"], "not_found")
        self.assertEqual(missing_content["data"]["evidence_snippets"], [])
        self.assertEqual(missing_content["data"]["citations"], [])
        self.assertNotIn("Waiting on audit approval", str(missing_content))

        conflicting = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_query_conflicting_ids",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "mail_import_session_id": (
                            bundle.mail_import_session.mail_import_session_id
                        ),
                        "mail_evidence_bundle_id": "mailbundle_other",
                    },
                },
            }
        )
        conflicting_content = conflicting["result"]["content"][0]["json"]
        self.assertFalse(conflicting["result"]["isError"])
        self.assertEqual(conflicting_content["status"], "not_found")
        self.assertEqual(conflicting_content["data"]["evidence_snippets"], [])
        self.assertEqual(conflicting_content["data"]["citations"], [])
        self.assertNotIn("Waiting on audit approval", str(conflicting_content))

    def test_jsonrpc_mail_evidence_query_rejects_argument_identity_override(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-jsonrpc-identity")
        bundle = _mail_bundle(temp_dir)
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=NOW)
            ),
            session=SemanticGatewaySession(
                session_id="session_jsonrpc_other",
                actor_user_id="user_other",
                workspace_id="workspace_formowl",
            ),
        )

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_impersonation",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "requester_user_id": "user_yifan",
                        "mail_import_session_id": (
                            bundle.mail_import_session.mail_import_session_id
                        ),
                    },
                },
            }
        )

        content = result["result"]["content"][0]["json"]
        self.assertFalse(result["result"]["isError"])
        self.assertEqual(content["status"], "permission_denied")
        self.assertEqual(content["data"]["evidence_snippets"], [])
        self.assertEqual(result["result"]["session"]["actor_user_id"], "user_other")
        self.assertNotIn("Waiting on audit approval", str(content))

    def test_jsonrpc_mail_evidence_query_rejects_unsupported_arguments_before_dispatch(
        self,
    ) -> None:
        calls = []
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=lambda payload: calls.append(payload) or {}
            ),
            session=SemanticGatewaySession(
                session_id="session_jsonrpc",
                actor_user_id="user_yifan",
                workspace_id="workspace_formowl",
            ),
        )

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_unsafe_extra_arg",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "mail_import_session_id": "mailimport_001",
                        "session_id": "session_owner",
                        "storage_backend_id": "private_backend",
                    },
                },
            }
        )

        content = result["result"]["content"][0]["json"]
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(content["status"], "error")
        self.assertEqual(content["data"]["error_code"], "unsafe_tool_payload")
        self.assertEqual(calls, [])
        rendered = str(result)
        self.assertNotIn("storage_backend_id", rendered)
        self.assertNotIn("private_backend", rendered)
        self.assertNotIn("session_owner", rendered)

    def test_jsonrpc_mail_evidence_query_rejects_forged_grants(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-jsonrpc-forged-grants")
        bundle = _mail_bundle(temp_dir)
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=NOW)
            ),
            session=SemanticGatewaySession(
                session_id="session_jsonrpc_other",
                actor_user_id="user_other",
                workspace_id="workspace_formowl",
            ),
        )

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_forged_grant",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "audit approval",
                        "mail_import_session_id": (
                            bundle.mail_import_session.mail_import_session_id
                        ),
                        "grants": [
                            _mail_session_grant(
                                bundle,
                                grantee_user_id="user_other",
                            ).to_dict()
                        ],
                    },
                },
            }
        )

        content = result["result"]["content"][0]["json"]
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(content["status"], "error")
        self.assertEqual(content["data"]["error_code"], "unsafe_tool_payload")
        self.assertEqual(result["result"]["session"]["actor_user_id"], "user_other")
        self.assertNotIn("Waiting on audit approval", str(content))

    def test_semantic_mail_evidence_handler_uses_trusted_grants_only(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-trusted-grants")
        bundle = _mail_bundle(temp_dir)
        denied_gateway = SemanticMcpGateway(
            mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=NOW)
        )
        allowed_gateway = SemanticMcpGateway(
            mail_evidence_handler=build_mail_evidence_query_handler(
                [bundle],
                grants=[_mail_session_grant(bundle, grantee_user_id="user_other")],
                now=NOW,
            )
        )
        arguments = {
            "workspace_id": "workspace_formowl",
            "requester_user_id": "user_other",
            "session_id": "session_other",
            "query_text": "audit approval",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        }

        denied = denied_gateway.dispatch_tool("query_mail_evidence", arguments)
        allowed = allowed_gateway.dispatch_tool("query_mail_evidence", arguments)

        self.assertEqual(denied["status"], "permission_denied")
        self.assertEqual(denied["data"]["evidence_snippets"], [])
        self.assertEqual(allowed["status"], "ok")
        self.assertIn("Waiting on audit approval", str(allowed["data"]["evidence_snippets"]))

    def test_semantic_mail_case_progress_handler_uses_trusted_grants_only(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-case-progress-trusted-grants")
        bundle = _mail_bundle(temp_dir)
        denied_gateway = SemanticMcpGateway(
            mail_case_progress_handler=build_mail_case_progress_handler(
                [bundle],
                now=NOW,
                generated_at=NOW,
            )
        )
        allowed_gateway = SemanticMcpGateway(
            mail_case_progress_handler=build_mail_case_progress_handler(
                [bundle],
                grants=[_mail_session_grant(bundle, grantee_user_id="user_other")],
                now=NOW,
                generated_at=NOW,
            )
        )
        arguments = {
            "workspace_id": "workspace_formowl",
            "requester_user_id": "user_other",
            "session_id": "session_other",
            "case_id": "case_launch",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            "grants": [
                _mail_session_grant(
                    bundle,
                    grantee_user_id="user_other",
                ).to_dict()
            ],
        }

        denied = denied_gateway.dispatch_tool("answer_mail_case_progress", arguments)
        allowed = allowed_gateway.dispatch_tool("answer_mail_case_progress", arguments)

        self.assertEqual(denied["status"], "permission_denied")
        self.assertEqual(denied["data"]["blockers"], [])
        self.assertEqual(denied["data"]["citations"], [])
        self.assertEqual(allowed["status"], "ok")
        self.assertIn("Waiting on audit approval", str(allowed["data"]["blockers"]))

    def test_jsonrpc_mail_case_progress_binds_session_and_rejects_forged_grants(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-case-progress-jsonrpc")
        bundle = _mail_bundle(temp_dir)
        owner_gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_case_progress_handler=build_mail_case_progress_handler(
                    [bundle],
                    now=NOW,
                    generated_at=NOW,
                )
            ),
            session=SemanticGatewaySession(
                session_id="session_jsonrpc_owner",
                actor_user_id="user_yifan",
                workspace_id="workspace_formowl",
            ),
        )

        owner_result = owner_gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "case_progress_owner",
                "method": "tools/call",
                "params": {
                    "name": "answer_mail_case_progress",
                    "arguments": {
                        "case_id": "case_launch",
                        "mail_import_session_id": (
                            bundle.mail_import_session.mail_import_session_id
                        ),
                    },
                },
            }
        )
        owner_content = owner_result["result"]["content"][0]["json"]
        self.assertFalse(owner_result["result"]["isError"])
        self.assertEqual(owner_content["status"], "ok")
        self.assertEqual(owner_content["data"]["blockers"][0]["text"], "Waiting on audit approval")
        transcript = owner_gateway.leak_transcript()
        self.assertEqual(set(transcript[0]), {"method", "request_hash", "response_hash", "status"})
        self.assertNotIn("case_launch", str(transcript))
        self.assertNotIn("Waiting on audit approval", str(transcript))

        other_gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_case_progress_handler=build_mail_case_progress_handler(
                    [bundle],
                    now=NOW,
                    generated_at=NOW,
                )
            ),
            session=SemanticGatewaySession(
                session_id="session_jsonrpc_other",
                actor_user_id="user_other",
                workspace_id="workspace_formowl",
            ),
        )
        forged = other_gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "case_progress_forged",
                "method": "tools/call",
                "params": {
                    "name": "answer_mail_case_progress",
                    "arguments": {
                        "case_id": "case_launch",
                        "requester_user_id": "user_yifan",
                        "session_id": "session_owner",
                        "mail_import_session_id": (
                            bundle.mail_import_session.mail_import_session_id
                        ),
                        "grants": [
                            _mail_session_grant(
                                bundle,
                                grantee_user_id="user_other",
                            ).to_dict()
                        ],
                    },
                },
            }
        )
        forged_content = forged["result"]["content"][0]["json"]
        self.assertTrue(forged["result"]["isError"])
        self.assertEqual(forged_content["status"], "error")
        self.assertEqual(forged_content["data"]["error_code"], "unsafe_tool_payload")
        self.assertNotIn("Waiting on audit approval", str(forged_content))


def _mail_bundle(temp_dir, archive: dict | None = None):
    stored = _run_mail_fixture(temp_dir, archive or _mail_archive())
    return build_mail_evidence_bundle(
        stored.observations,
        workspace_id="workspace_formowl",
        owner_user_id="user_yifan",
        source_asset_id=stored.extractor_run.asset_id,
        archive_sha256="sha256:archive-launch",
        upload_session_id="upload_session_mail_001",
        created_at=NOW,
    )


def _run_mail_fixture(temp_dir, archive: dict):
    source_path = temp_dir / "incoming" / "mail-archive.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps(archive, sort_keys=True), encoding="utf-8")
    registry = StorageBackendRegistry(temp_dir)
    backend = registry.register_local_backend(
        temp_dir / "object-root",
        workspace_scope="workspace_formowl",
    )
    object_store = FileObjectStore(registry)
    asset = register_asset_from_local_file(
        source_path,
        object_store=object_store,
        asset_store=AssetStore(temp_dir),
        storage_backend_id=backend.storage_backend_id,
        workspace_id="workspace_formowl",
        owner_user_id="user_yifan",
        permission_scope=PermissionScope.project("project_formowl"),
        source_ref=SourceRef(
            source_system="local",
            source_type="mail_archive",
            source_id="mail-archive.json",
        ),
        mime_type="application/vnd.formowl.mail-archive+json",
        created_at=NOW,
        registered_at=NOW,
    )
    return run_extractor(
        asset=asset,
        object_store=object_store,
        extractor_run_store=ExtractorRunStore(temp_dir),
        observation_store=ObservationStore(temp_dir),
        adapter=FixtureMailArchiveExtractor(),
        started_at=NOW,
        completed_at=NOW,
    )


def _mail_archive() -> dict:
    return {
        "archive_id": "archive_launch",
        "mailbox_id": "mailbox_yifan",
        "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
        "messages": [
            {
                "message_id": "<launch-001@example.test>",
                "thread_id": "thread_launch",
                "folder_path_hash": "sha256:folder-inbox",
                "subject": "Launch checklist",
                "sender": "pm@example.test",
                "sent_at": NOW,
                "body": "Update: Launch reviewed\n\nBlocker: Waiting on audit approval",
                "body_hash": "sha256:body-launch",
            }
        ],
    }


def _mail_archive_no_markers() -> dict:
    archive = _mail_archive()
    archive["messages"][0]["body"] = "Launch reviewed but no structured marker lines"
    archive["messages"][0]["body_hash"] = "sha256:body-launch-no-markers"
    return archive


def _mail_session_grant(
    bundle,
    *,
    owner_user_id: str = "user_yifan",
    grantee_user_id: str,
    scope_type: str = "mail_import_session",
    scope_id: str | None = None,
    permission: str = "evidence_snippet",
    expires_at: str = "2026-07-06T00:00:00+00:00",
    revoked_at: str | None = None,
) -> Grant:
    return Grant(
        grant_id=f"grant_mail_{grantee_user_id}",
        owner_user_id=owner_user_id,
        grantee_user_id=grantee_user_id,
        scope_type=scope_type,
        scope_id=scope_id or bundle.mail_import_session.mail_import_session_id,
        permission=permission,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


if __name__ == "__main__":
    unittest.main()
