from __future__ import annotations

from dataclasses import replace
import json
import re
import sys
from statistics import median
from time import perf_counter
import unicodedata
from unittest.mock import patch
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


def _raise_parallel_tokenization_failure(*_args, **_kwargs):
    raise RuntimeError("simulated parallel tokenization failure")


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

    def test_mail_case_progress_pack_id_generation_blocks_unsafe_future_stable_ids(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-case-progress-unsafe-pack-id")
        bundle = _mail_bundle(temp_dir)
        gateway = MailCaseProgressGateway([bundle])

        with patch(
            "formowl_mail.evidence.stable_resource_contract_id",
            return_value="mailpack:unsafe",
        ):
            with self.assertRaisesRegex(
                ContractValidationError,
                "mail_evidence_pack_id generator produced an unsafe file name",
            ):
                gateway.answer_case_progress(
                    case_id="case_launch",
                    requester_user_id="user_yifan",
                    workspace_id="workspace_formowl",
                    session_id="session_owner",
                    mail_import_session_id=(bundle.mail_import_session.mail_import_session_id),
                    now=NOW,
                    generated_at=NOW,
                )

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

    def test_mail_evidence_query_anchors_candidates_to_protected_identifier(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-query-identifier-anchor")
        bundle = _mail_bundle(temp_dir, _mail_archive_identifier_competition())
        gateway = MailEvidenceQueryGateway([bundle])

        matched = gateway.query_mail_evidence(
            query_text="有03.80503G301的COO或產地嗎",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_identifier_anchor",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            limit=3,
            now=NOW,
        ).to_dict()
        missing = gateway.query_mail_evidence(
            query_text="有03.99999Z999的COO或產地嗎",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_missing_identifier_anchor",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            limit=3,
            now=NOW,
        ).to_dict()

        self.assertEqual(matched["status"], "ok")
        self.assertEqual(len(matched["evidence_snippets"]), 1)
        self.assertIn("03.80503G301", matched["evidence_snippets"][0]["snippet"])
        self.assertIn(
            "03.80503g301",
            matched["evidence_snippets"][0]["matched_terms"],
        )
        self.assertNotIn("generic COO", str(matched["evidence_snippets"]))
        self.assertEqual(missing["status"], "ok")
        self.assertEqual(missing["evidence_snippets"], [])
        self.assertEqual(missing["citations"], [])
        self.assertIn("no_visible_mail_evidence_matched", missing["warnings"])

    def test_mail_evidence_read_expands_identifier_hit_to_complete_message(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-read-complete-message")
        archive = _mail_archive()
        archive["messages"][0]["body_segments"] = [
            "03.80503G301 shipment status",
            "COO origin is Taiwan",
        ]
        archive["messages"][0]["body_hash"] = "sha256:body-cross-segment"
        bundle = _mail_bundle(temp_dir, archive)
        gateway = MailEvidenceQueryGateway([bundle])

        query = gateway.query_mail_evidence(
            query_text="03.80503G301 COO origin",
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_cross_segment_query",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            limit=10,
            now=NOW,
        ).to_dict()
        self.assertEqual(query["status"], "ok")
        self.assertEqual(len(query["evidence_snippets"]), 1)
        self.assertIn("03.80503G301", query["evidence_snippets"][0]["snippet"])

        read = gateway.read_mail_evidence(
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_cross_segment_read",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            email_message_ids=[query["evidence_snippets"][0]["email_message_id"]],
            now=NOW,
        ).to_dict()
        self.assertEqual(read["status"], "ok")
        self.assertEqual(
            {segment["source_observation_id"] for segment in read["evidence_segments"]},
            {segment.source_observation_id for segment in bundle.body_segments},
        )

        denied = gateway.read_mail_evidence(
            requester_user_id="user_other",
            workspace_id="workspace_formowl",
            session_id="session_cross_segment_denied",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            email_message_ids=[query["evidence_snippets"][0]["email_message_id"]],
            now=NOW,
        ).to_dict()
        self.assertEqual(denied["status"], "permission_denied")
        self.assertEqual(denied["evidence_segments"], [])

    def test_mail_evidence_query_redacts_unsafe_spans_without_failing_whole_query(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-query-content-redaction")
        bundle = _mail_bundle(temp_dir)
        unsafe_segment = replace(
            bundle.body_segments[0],
            text=(
                "Audit approval is delayed. Debug export was /srv/formowl/private/a.csv "
                "and the note included select * from supplier_private. "
                "A copied note said copy supplier_private from /tmp/private.csv."
            ),
        )
        unsafe_message = replace(
            bundle.messages[0],
            subject="Audit follow-up with supplier_private as (select * from private_table)",
        )
        bundle = replace(
            bundle,
            messages=[unsafe_message],
            body_segments=[unsafe_segment],
        )

        result = (
            MailEvidenceQueryGateway([bundle])
            .query_mail_evidence(
                query_text="audit approval delayed",
                requester_user_id="user_yifan",
                workspace_id="workspace_formowl",
                session_id="session_owner",
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
                now=NOW,
            )
            .to_dict()
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["evidence_snippets"])
        self.assertTrue(result["evidence_snippets"][0]["content_redacted"])
        self.assertGreater(result["redaction_counts"]["unsafe_snippets"], 0)
        self.assertIn("unsafe_mail_evidence_content_redacted", result["warnings"])
        rendered = str(result).lower()
        self.assertNotIn("/srv/formowl", rendered)
        self.assertNotIn("/tmp/private.csv", rendered)
        self.assertNotIn("select * from", rendered)
        self.assertNotIn("copy supplier_private from", rendered)
        self.assertNotIn("with supplier_private as", rendered)

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
            gateway.execute_mail_evidence_query(
                query_text="audit approval",
                required_terms=("audit approval",),
                requester_user_id="user_yifan",
                workspace_id="workspace_formowl",
                session_id="session_index_cache_required",
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
                now=NOW,
            )
        finally:
            mail_query._build_snippet_index = original

        self.assertEqual(build_count, 1)

    @unittest.skipUnless(sys.platform == "linux", "fork index parity is Linux-only")
    def test_parallel_snippet_index_is_exactly_equal_to_single_process_index(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-parallel-index-parity")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())

        single_process = mail_query._build_snippet_index(bundle)
        multiprocess = mail_query._build_snippet_index(bundle, worker_count=2)

        self.assertEqual(multiprocess, single_process)
        self.assertEqual(mail_query._PARALLEL_INDEX_BUNDLE, None)
        self.assertEqual(mail_query._PARALLEL_INDEX_MESSAGES_BY_ID, None)

    @unittest.skipUnless(sys.platform == "linux", "fork query parity is Linux-only")
    def test_parallel_gateway_preserves_required_term_results_and_citations(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-parallel-query-parity")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())
        single_process = MailEvidenceQueryGateway([bundle])
        multiprocess = MailEvidenceQueryGateway([bundle], index_worker_count=2)
        query = {
            "query_text": "Program ORBIT",
            "required_terms": ("Alex Rivera", "DOC-2026-ABC9"),
            "requester_user_id": "user_yifan",
            "workspace_id": "workspace_formowl",
            "session_id": "session_parallel_query_parity",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            "limit": len(bundle.messages),
            "now": NOW,
            "collapse_source_items": True,
        }

        expected = single_process.execute_mail_evidence_query(**query)
        actual = multiprocess.execute_mail_evidence_query(**query)

        self.assertEqual(multiprocess.index_build_mode, "multiprocess")
        self.assertEqual(multiprocess.index_worker_count, 2)
        self.assertEqual(actual.result.to_dict(), expected.result.to_dict())
        self.assertEqual(
            actual.verified_source_item_keys,
            expected.verified_source_item_keys,
        )
        self.assertTrue(actual.result.evidence_snippets[0]["supporting_evidence"])
        self.assertEqual(
            actual.result.citations,
            expected.result.citations,
        )

    def test_parallel_gateway_falls_back_when_fork_is_unavailable(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-parallel-no-fork")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())

        with patch.object(
            mail_query.multiprocessing,
            "get_context",
            side_effect=ValueError("fork is unavailable"),
        ):
            gateway = MailEvidenceQueryGateway([bundle], index_worker_count=2)

        self.assertEqual(gateway.index_build_mode, "single_process")
        self.assertEqual(gateway.index_worker_count, 1)
        self.assertEqual(
            gateway._snippet_index_by_bundle_id[bundle.mail_evidence_bundle_id],
            mail_query._build_snippet_index(bundle),
        )

    def test_parallel_gateway_falls_back_outside_safe_fork_boundary(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-parallel-thread-guard")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())
        cases = (
            {
                "name": "non_main_thread",
                "current_thread": object(),
                "main_thread": object(),
                "active_count": 1,
            },
            {
                "name": "other_threads_active",
                "current_thread": None,
                "main_thread": None,
                "active_count": 2,
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                current_thread = case["current_thread"] or object()
                main_thread = case["main_thread"] or current_thread
                with (
                    patch.object(
                        mail_query.threading,
                        "current_thread",
                        return_value=current_thread,
                    ),
                    patch.object(
                        mail_query.threading,
                        "main_thread",
                        return_value=main_thread,
                    ),
                    patch.object(
                        mail_query.threading,
                        "active_count",
                        return_value=case["active_count"],
                    ),
                    patch.object(mail_query.multiprocessing, "get_context") as get_context,
                ):
                    gateway = MailEvidenceQueryGateway(
                        [bundle],
                        index_worker_count=2,
                    )

                self.assertEqual(gateway.index_build_mode, "single_process")
                self.assertEqual(gateway.index_worker_count, 1)
                get_context.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux", "fork failure path is Linux-only")
    def test_parallel_worker_failure_does_not_publish_partial_gateway(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-evidence-parallel-worker-failure")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())
        gateway = None

        with (
            patch.object(
                mail_query,
                "_tokenize_segment",
                _raise_parallel_tokenization_failure,
            ),
            patch.object(
                mail_query,
                "_immutable_posting_map",
                wraps=mail_query._immutable_posting_map,
            ) as freeze_postings,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "simulated parallel tokenization failure",
            ):
                gateway = MailEvidenceQueryGateway([bundle], index_worker_count=2)

        self.assertIsNone(gateway)
        freeze_postings.assert_not_called()
        self.assertEqual(mail_query._PARALLEL_INDEX_BUNDLE, None)
        self.assertEqual(mail_query._PARALLEL_INDEX_MESSAGES_BY_ID, None)

    def test_required_terms_match_exhaustive_source_oracle_across_domains(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-required-term-source-oracle")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())
        gateway = MailEvidenceQueryGateway([bundle])
        required_terms = ("Alex Rivera", "PART-AX9-004", "DOC-2026-ABC9")

        execution = gateway.execute_mail_evidence_query(
            query_text="Alex Rivera PART-AX9-004 DOC-2026-ABC9 ORBIT",
            required_terms=required_terms,
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_required_term_oracle",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            limit=len(bundle.messages),
            now=NOW,
            collapse_source_items=True,
        )
        result = execution.result.to_dict()
        oracle_source_ids, oracle_observation_ids = _exhaustive_required_term_oracle(
            bundle,
            required_terms,
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
        )
        result_source_ids = {snippet["email_message_id"] for snippet in result["evidence_snippets"]}

        # The oracle scans every complete logical source item directly.  It
        # intentionally does not call the production tokenizer, postings, or
        # source-assembly helpers.
        self.assertEqual(execution.verified_source_item_ids, oracle_source_ids)
        self.assertEqual(result_source_ids, oracle_source_ids)
        self.assertEqual(len(result["evidence_snippets"]), len(oracle_source_ids))
        self.assertEqual(len(result["citations"]), len(oracle_source_ids))
        self.assertEqual(
            {citation["email_message_id"] for citation in result["citations"]},
            oracle_source_ids,
        )
        self.assertEqual(
            {citation["source_observation_id"] for citation in result["citations"]},
            {snippet["source_observation_id"] for snippet in result["evidence_snippets"]},
        )
        for citation in result["citations"]:
            self.assertIn(
                citation["source_observation_id"],
                oracle_observation_ids[citation["email_message_id"]],
            )
        self.assertEqual(
            set(execution.timings_ms),
            {"posting_retrieval", "exact_verification", "ranking"},
        )
        self.assertTrue(all(value >= 0.0 for value in execution.timings_ms.values()))

    def test_required_terms_preserve_generic_typed_numeric_equivalence(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-required-term-typed-numeric")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())
        gateway = MailEvidenceQueryGateway([bundle])

        execution = gateway.execute_mail_evidence_query(
            query_text="470002002 change record",
            required_terms=("TYPE470002002",),
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_required_typed_numeric",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            limit=len(bundle.messages),
            now=NOW,
            collapse_source_items=True,
        )
        result = execution.result.to_dict()

        self.assertEqual(len(execution.verified_source_item_ids or ()), 1)
        self.assertEqual(len(result["evidence_snippets"]), 1)
        self.assertIn("470002002", result["evidence_snippets"][0]["snippet"])
        self.assertEqual(
            result["citations"][0]["email_message_id"],
            result["evidence_snippets"][0]["email_message_id"],
        )

    def test_required_term_oracle_matches_source_counts_and_permissions(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-required-term-permission-oracle")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())
        gateway = MailEvidenceQueryGateway([bundle])
        required_terms = ("Alex Rivera", "PART-AX9-004", "DOC-2026-ABC9")
        query_text = "Alex Rivera PART-AX9-004 DOC-2026-ABC9"

        cases = (
            ("owner", "user_yifan", (), "ok"),
            ("denied", "user_other", (), "permission_denied"),
            (
                "granted",
                "user_other",
                (_mail_session_grant(bundle, grantee_user_id="user_other"),),
                "ok",
            ),
        )
        for case_name, requester_user_id, grants, expected_status in cases:
            with self.subTest(case_name=case_name):
                execution = gateway.execute_mail_evidence_query(
                    query_text=query_text,
                    required_terms=required_terms,
                    requester_user_id=requester_user_id,
                    workspace_id="workspace_formowl",
                    session_id=f"session_required_oracle_{case_name}",
                    mail_import_session_id=(bundle.mail_import_session.mail_import_session_id),
                    grants=grants,
                    limit=10,
                    now=NOW,
                    collapse_source_items=True,
                )
                result = execution.result.to_dict()
                oracle_source_ids, oracle_observation_ids = _exhaustive_required_term_oracle(
                    bundle,
                    required_terms,
                    requester_user_id=requester_user_id,
                    workspace_id="workspace_formowl",
                    grants=grants,
                )
                result_source_ids = {
                    snippet["email_message_id"] for snippet in result["evidence_snippets"]
                }

                self.assertEqual(result["status"], expected_status)
                self.assertEqual(execution.verified_source_item_ids, oracle_source_ids)
                self.assertEqual(
                    len(result["evidence_snippets"]),
                    len(oracle_source_ids),
                )
                self.assertEqual(
                    len(result["citations"]),
                    len(oracle_source_ids),
                )
                self.assertEqual(result_source_ids, oracle_source_ids)
                if expected_status == "permission_denied":
                    self.assertEqual(result["evidence_snippets"], [])
                    self.assertEqual(result["citations"], [])
                    self.assertEqual(
                        result["redaction_counts"]["hidden_messages"],
                        len(bundle.messages),
                    )
                    self.assertEqual(
                        execution.timings_ms,
                        {
                            "posting_retrieval": 0.0,
                            "exact_verification": 0.0,
                            "ranking": 0.0,
                        },
                    )
                else:
                    for citation in result["citations"]:
                        self.assertIn(
                            citation["source_observation_id"],
                            oracle_observation_ids[citation["email_message_id"]],
                        )

    def test_required_term_postings_do_not_touch_noncandidate_snippets(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-required-term-poison-pruning")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())
        gateway = MailEvidenceQueryGateway([bundle])
        base_index = mail_query._build_snippet_index(bundle)
        target = next(
            snippet
            for snippet in base_index.snippets
            if "doc-2026-abc9" in snippet.searchable_tokens and "alex" in snippet.searchable_tokens
        )

        class PoisonSnippet:
            @property
            def source_item_id(self):
                raise AssertionError("noncandidate source should not be inspected")

            @property
            def searchable_tokens(self):
                raise AssertionError("noncandidate snippet should not be verified")

            @property
            def payload(self):
                raise AssertionError("noncandidate snippet should not be materialized")

        source_item_id = target.source_item_id
        gateway._snippet_index_by_bundle_id[bundle.mail_evidence_bundle_id] = (
            mail_query._MailSnippetIndex(
                snippets=(target, PoisonSnippet()),
                snippet_indexes_by_token={token: (0,) for token in target.searchable_tokens},
                source_item_ids_by_token={
                    token: frozenset({source_item_id}) for token in target.searchable_tokens
                },
                snippet_indexes_by_source_item_id={
                    source_item_id: (0,),
                    "emailmessage_poison": (1,),
                },
                subject_by_source_item_id={
                    source_item_id: str(target.payload.get("subject", "")),
                    "emailmessage_poison": "Poison source",
                },
            )
        )

        execution = gateway.execute_mail_evidence_query(
            query_text="DOC-2026-ABC9 Alex Rivera",
            required_terms=("Alex Rivera", "DOC-2026-ABC9"),
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_required_poison",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            limit=10,
            now=NOW,
            collapse_source_items=True,
        )

        self.assertEqual(execution.verified_source_item_ids, frozenset({source_item_id}))
        self.assertEqual(len(execution.result.evidence_snippets), 1)

    def test_required_term_query_collapses_repeated_chain_before_materialization(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-required-term-chain-collapse")
        bundle = _mail_bundle(temp_dir, _mail_archive_repeated_chain())
        gateway = MailEvidenceQueryGateway([bundle])

        with patch(
            "formowl_mail.query._safe_snippet",
            wraps=mail_query._safe_snippet,
        ) as safe_snippet:
            execution = gateway.execute_mail_evidence_query(
                query_text="Alex Rivera DOC-2026-ABC9",
                required_terms=("Alex Rivera", "DOC-2026-ABC9"),
                requester_user_id="user_yifan",
                workspace_id="workspace_formowl",
                session_id="session_required_chain",
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
                limit=len(bundle.messages),
                now=NOW,
                collapse_source_items=True,
            )

        self.assertEqual(len(execution.result.evidence_snippets), 1)
        self.assertEqual(len(execution.result.citations), 1)
        self.assertEqual(safe_snippet.call_count, 1)

    def test_required_term_latency_stays_bounded_on_synthetic_large_corpus(self) -> None:
        required_terms = ("Alex Rivera", "PART-AX9-004", "DOC-2026-ABC9")
        query_text = "Alex Rivera PART-AX9-004 DOC-2026-ABC9"

        small_bundle = _mail_bundle(
            _paths.fresh_test_dir("mail-required-term-latency-small"),
            _mail_archive_latency_corpus(16, noise_repetitions=16),
        )
        large_bundle = _mail_bundle(
            _paths.fresh_test_dir("mail-required-term-latency-large"),
            _mail_archive_latency_corpus(2048, noise_repetitions=128),
        )
        small_gateway = MailEvidenceQueryGateway([small_bundle])
        large_gateway = MailEvidenceQueryGateway([large_bundle])

        small_ms = _median_required_term_query_ms(
            small_gateway,
            small_bundle,
            query_text=query_text,
            required_terms=required_terms,
        )
        large_ms = _median_required_term_query_ms(
            large_gateway,
            large_bundle,
            query_text=query_text,
            required_terms=required_terms,
        )

        # This is a deterministic synthetic regression guard only.  It is not
        # a claim about private PST performance or a promise such as "under
        # ten seconds"; the large query should not reconstruct every source's
        # text after the index has already been built.
        self.assertLess(
            large_ms,
            max(25.0, small_ms * 20.0),
            f"synthetic query scaled from {small_ms:.3f}ms to {large_ms:.3f}ms",
        )

    def test_required_term_permission_denial_precedes_posting_lookup(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-required-term-permission")
        bundle = _mail_bundle(temp_dir, _mail_archive_required_term_oracle())
        gateway = MailEvidenceQueryGateway([bundle])

        with patch(
            "formowl_mail.query._resolve_verified_required_source_item_ids",
            side_effect=AssertionError("permission denial must precede postings"),
        ):
            execution = gateway.execute_mail_evidence_query(
                query_text="Alex Rivera DOC-2026-ABC9",
                required_terms=("Alex Rivera", "DOC-2026-ABC9"),
                requester_user_id="user_other",
                workspace_id="workspace_formowl",
                session_id="session_required_denied",
                mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
                limit=10,
                now=NOW,
                collapse_source_items=True,
            )

        result = execution.result.to_dict()
        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["evidence_snippets"], [])
        self.assertEqual(result["citations"], [])
        self.assertEqual(execution.verified_source_item_ids, frozenset())
        self.assertEqual(
            execution.timings_ms,
            {
                "posting_retrieval": 0.0,
                "exact_verification": 0.0,
                "ranking": 0.0,
            },
        )

    def test_required_terms_namespace_source_identity_across_bundles(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-required-term-bundle-collision")
        shared_message_id = "<shared-message@example.test>"
        bundle_a = _mail_bundle(
            temp_dir / "bundle-a",
            {
                "archive_id": "archive_bundle_a",
                "mailbox_id": "mailbox_yifan",
                "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
                "messages": [
                    {
                        "message_id": shared_message_id,
                        "thread_id": "thread_bundle_a",
                        "folder_path_hash": "sha256:folder-inbox",
                        "subject": "Alpha source",
                        "sender": "alpha@example.test",
                        "sent_at": NOW,
                        "body": "ALPHA only",
                        "body_hash": "sha256:body-bundle-a",
                    }
                ],
            },
        )
        bundle_b = _mail_bundle(
            temp_dir / "bundle-b",
            {
                "archive_id": "archive_bundle_b",
                "mailbox_id": "mailbox_yifan",
                "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
                "messages": [
                    {
                        "message_id": shared_message_id,
                        "thread_id": "thread_bundle_b",
                        "folder_path_hash": "sha256:folder-inbox",
                        "subject": "Common source",
                        "sender": "common@example.test",
                        "sent_at": NOW,
                        "body": "COMMON only",
                        "body_hash": "sha256:body-bundle-b",
                    }
                ],
            },
        )
        normalized_message_id = bundle_a.messages[0].email_message_id
        bundle_b = replace(
            bundle_b,
            mail_import_session=bundle_a.mail_import_session,
            messages=[replace(bundle_b.messages[0], email_message_id=normalized_message_id)],
            body_segments=[
                replace(segment, email_message_id=normalized_message_id)
                for segment in bundle_b.body_segments
            ],
        )
        gateway = MailEvidenceQueryGateway([bundle_a, bundle_b])

        execution = gateway.execute_mail_evidence_query(
            query_text="COMMON",
            required_terms=("ALPHA",),
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_required_term_bundle_collision",
            mail_import_session_id=bundle_a.mail_import_session.mail_import_session_id,
            limit=10,
            now=NOW,
            collapse_source_items=True,
        )

        expected_source_key = (
            bundle_a.mail_evidence_bundle_id,
            bundle_a.mail_import_session.mail_import_session_id,
            normalized_message_id,
        )
        self.assertEqual(execution.verified_source_item_keys, frozenset({expected_source_key}))
        self.assertEqual(
            execution.verified_source_item_ids,
            frozenset({normalized_message_id}),
        )
        self.assertEqual(execution.result.evidence_snippets, [])
        self.assertEqual(execution.result.citations, [])
        self.assertEqual(
            mail_query._build_snippet_index(bundle_a).source_item_ids_by_token["alpha"],
            frozenset({expected_source_key}),
        )
        self.assertEqual(
            mail_query._build_snippet_index(bundle_b).source_item_ids_by_token["common"],
            frozenset(
                {
                    (
                        bundle_b.mail_evidence_bundle_id,
                        bundle_a.mail_import_session.mail_import_session_id,
                        normalized_message_id,
                    )
                }
            ),
        )

    def test_required_terms_materialize_minimal_supporting_observations(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-required-term-supporting-evidence")
        bundle = _mail_bundle(
            temp_dir,
            {
                "archive_id": "archive_required_support",
                "mailbox_id": "mailbox_yifan",
                "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
                "messages": [
                    {
                        "message_id": "<required-support@example.test>",
                        "thread_id": "thread_required_support",
                        "folder_path_hash": "sha256:folder-inbox",
                        "subject": "Program evidence review",
                        "sender": "program@example.test",
                        "sent_at": NOW,
                        "body_segments": [
                            "Program ORBIT is ready for the evidence review.",
                            "Alex Rivera is the accountable reviewer.",
                            "The approved record is DOC-2026-ABC9.",
                            "UNRELATED-SEGMENT must not be materialized.",
                        ],
                        "body_hash": "sha256:body-required-support",
                    }
                ],
            },
        )
        gateway = MailEvidenceQueryGateway([bundle])
        observations_by_text = {
            segment.text: segment.source_observation_id for segment in bundle.body_segments
        }

        execution = gateway.execute_mail_evidence_query(
            query_text="ORBIT",
            required_terms=("Alex Rivera", "DOC-2026-ABC9"),
            requester_user_id="user_yifan",
            workspace_id="workspace_formowl",
            session_id="session_required_support",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            limit=10,
            now=NOW,
            collapse_source_items=True,
        )
        result = execution.result.to_dict()

        self.assertEqual(len(result["evidence_snippets"]), 1)
        primary = result["evidence_snippets"][0]
        self.assertIn("Program ORBIT", primary["snippet"])
        self.assertEqual(
            result["citations"][0]["source_observation_id"],
            primary["source_observation_id"],
        )
        supporting_evidence = primary["supporting_evidence"]
        self.assertEqual(
            {item["source_observation_id"] for item in supporting_evidence},
            {
                observations_by_text["Alex Rivera is the accountable reviewer."],
                observations_by_text["The approved record is DOC-2026-ABC9."],
            },
        )
        self.assertEqual(
            {term for item in supporting_evidence for term in item["matched_required_terms"]},
            {"Alex Rivera", "DOC-2026-ABC9"},
        )
        self.assertEqual(
            {item["citation"]["source_observation_id"] for item in supporting_evidence},
            {item["source_observation_id"] for item in supporting_evidence},
        )
        self.assertNotIn("UNRELATED-SEGMENT", str(result))

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

        missing_handler = SemanticMcpGateway().dispatch_tool(
            "query_mail_evidence",
            {
                "workspace_id": "workspace_formowl",
                "requester_user_id": "user_yifan",
                "query_text": "audit approval",
                "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            },
        )
        self.assertEqual(missing_handler["status"], "error")
        self.assertEqual(missing_handler["data"]["error_code"], "handler_not_configured")
        self.assertNotIn("evidence_snippets", missing_handler["data"])

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

        missing_handler = SemanticMcpGateway().dispatch_tool(
            "answer_mail_case_progress",
            {
                "workspace_id": "workspace_formowl",
                "requester_user_id": "user_yifan",
                "case_id": "case_launch",
                "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            },
        )
        self.assertEqual(missing_handler["status"], "error")
        self.assertEqual(missing_handler["data"]["error_code"], "handler_not_configured")
        self.assertNotIn("blockers", missing_handler["data"])

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
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(content["status"], "error")
        self.assertEqual(content["data"]["error_code"], "unsafe_tool_payload")
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


def _mail_archive_identifier_competition() -> dict:
    messages = [
        {
            "message_id": f"<generic-coo-{index}@example.test>",
            "thread_id": f"thread_generic_coo_{index}",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": f"Generic COO review {index}",
            "sender": "generic@example.test",
            "sent_at": NOW,
            "body": "generic COO 產地 origin information for another item",
            "body_hash": f"sha256:body-generic-coo-{index}",
        }
        for index in range(5)
    ]
    messages.append(
        {
            "message_id": "<target-origin@example.test>",
            "thread_id": "thread_target_origin",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": "Manufacturing-site confirmation",
            "sender": "target@example.test",
            "sent_at": NOW,
            "body": "03.80503G301 manufacturing site is Taiwan",
            "body_hash": "sha256:body-target-origin",
        }
    )
    return {
        "archive_id": "archive_identifier_competition",
        "mailbox_id": "mailbox_yifan",
        "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
        "messages": messages,
    }


def _mail_archive_required_term_oracle() -> dict:
    messages = [
        {
            "message_id": "<orbit-target@example.test>",
            "thread_id": "thread_orbit_target",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": "Alex Rivera quarterly review",
            "sender": "program@example.test",
            "sent_at": NOW,
            "body_segments": [
                "Program ORBIT readiness summary for part PART-AX9-004",
                "Document DOC-2026-ABC9 was approved.",
            ],
            "body_hash": "sha256:body-orbit-target",
        },
        {
            "message_id": "<orbit-wrong-document@example.test>",
            "thread_id": "thread_orbit_wrong_document",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": "Alex Rivera weekly review",
            "sender": "program@example.test",
            "sent_at": NOW,
            "body_segments": [
                "Program ORBIT readiness summary for part PART-AX9-004",
                "Document DOC-2026-XYZ8 remains under review.",
            ],
            "body_hash": "sha256:body-orbit-wrong-document",
        },
        {
            "message_id": "<document-only@example.test>",
            "thread_id": "thread_document_only",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": "Document control notice",
            "sender": "records@example.test",
            "sent_at": NOW,
            "body": "DOC-2026-ABC9 is archived without a named reviewer.",
            "body_hash": "sha256:body-document-only",
        },
        {
            "message_id": "<other-person@example.test>",
            "thread_id": "thread_other_person",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": "Avery Stone quarterly review",
            "sender": "program@example.test",
            "sent_at": NOW,
            "body": ("Program ORBIT uses part PART-AX9-004 and document " "DOC-2026-ABC9."),
            "body_hash": "sha256:body-other-person",
        },
        {
            "message_id": "<numeric-record@example.test>",
            "thread_id": "thread_numeric_record",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": "Generic change record",
            "sender": "records@example.test",
            "sent_at": NOW,
            "body": "Numeric record 470002002 is ready for review.",
            "body_hash": "sha256:body-numeric-record",
        },
    ]
    return {
        "archive_id": "archive_required_term_oracle",
        "mailbox_id": "mailbox_yifan",
        "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
        "messages": messages,
    }


def _mail_archive_repeated_chain() -> dict:
    repeated_segments = [
        "Quoted chain: Alex Rivera references DOC-2026-ABC9 for Program ORBIT.",
        ("-----Original Message----- Alex Rivera references " "DOC-2026-ABC9 for Program ORBIT."),
    ] * 20
    return {
        "archive_id": "archive_repeated_chain",
        "mailbox_id": "mailbox_yifan",
        "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
        "messages": [
            {
                "message_id": "<repeated-chain@example.test>",
                "thread_id": "thread_repeated_chain",
                "folder_path_hash": "sha256:folder-inbox",
                "subject": "Alex Rivera chain summary",
                "sender": "program@example.test",
                "sent_at": NOW,
                "body_segments": repeated_segments,
                "body_hash": "sha256:body-repeated-chain",
            }
        ],
    }


def _exhaustive_required_term_oracle(
    bundle,
    required_terms: tuple[str, ...],
    *,
    requester_user_id: str,
    workspace_id: str,
    grants=(),
) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    typed_numeric = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2,5}[\s#:_-]*([0-9]{8,})(?![0-9])")
    actor = bundle.mail_import_session
    has_access = actor.workspace_id == workspace_id and (
        requester_user_id == actor.owner_user_id
        or any(
            grant.owner_user_id == actor.owner_user_id
            and grant.grantee_user_id == requester_user_id
            and grant.permission in {"read", "evidence_snippet", "mail_evidence_read"}
            and not grant.revoked_at
            and grant.scope_type == "mail_import_session"
            and grant.scope_id == actor.mail_import_session_id
            and grant.expires_at > NOW
            for grant in grants
        )
    )
    if not has_access:
        return frozenset(), {}

    segments_by_message_id: dict[str, list[str]] = {}
    observations_by_message_id: dict[str, set[str]] = {}
    for segment in bundle.body_segments:
        segments_by_message_id.setdefault(segment.email_message_id, []).append(segment.text)
        observations_by_message_id.setdefault(segment.email_message_id, set()).add(
            segment.source_observation_id
        )
    matches: set[str] = set()
    matched_observations: dict[str, frozenset[str]] = {}
    for message in bundle.messages:
        source_text = unicodedata.normalize(
            "NFKC",
            "\n".join(
                [
                    message.subject or "",
                    *segments_by_message_id.get(message.email_message_id, ()),
                ]
            ),
        ).casefold()
        all_terms_match = True
        for required_term in required_terms:
            normalized = (
                unicodedata.normalize(
                    "NFKC",
                    required_term,
                )
                .casefold()
                .strip()
            )
            numeric_match = typed_numeric.fullmatch(normalized)
            alternatives = (
                (normalized, numeric_match.group(1)) if numeric_match is not None else (normalized,)
            )
            if not any(alternative in source_text for alternative in alternatives):
                all_terms_match = False
                break
        if all_terms_match:
            matches.add(message.email_message_id)
            matched_observations[message.email_message_id] = frozenset(
                observations_by_message_id.get(message.email_message_id, set())
            )
    return frozenset(matches), matched_observations


def _median_required_term_query_ms(
    gateway: MailEvidenceQueryGateway,
    bundle,
    *,
    query_text: str,
    required_terms: tuple[str, ...],
) -> float:
    query_kwargs = {
        "query_text": query_text,
        "required_terms": required_terms,
        "requester_user_id": "user_yifan",
        "workspace_id": "workspace_formowl",
        "session_id": "session_required_term_latency",
        "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        "limit": 2,
        "now": NOW,
        "collapse_source_items": True,
    }
    expected_target_id = next(
        message.email_message_id
        for message in bundle.messages
        if message.subject == "Alex Rivera evidence review"
    )
    for _ in range(2):
        gateway.execute_mail_evidence_query(**query_kwargs)
    samples: list[float] = []
    for _ in range(5):
        started = perf_counter()
        execution = gateway.execute_mail_evidence_query(**query_kwargs)
        samples.append((perf_counter() - started) * 1000.0)
        if execution.verified_source_item_ids != frozenset({expected_target_id}):
            raise AssertionError("latency corpus did not preserve its single target")
        if len(execution.result.evidence_snippets) != 1:
            raise AssertionError("latency corpus returned an unexpected source count")
    return float(median(samples))


def _mail_archive_latency_corpus(
    noise_source_count: int,
    *,
    noise_repetitions: int,
) -> dict:
    noise = "unrelated corpus context " * noise_repetitions
    messages = [
        {
            "message_id": f"<latency-noise-{index}@example.test>",
            "thread_id": f"thread_latency_noise_{index}",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": f"Unrelated source {index}",
            "sender": "noise@example.test",
            "sent_at": NOW,
            "body": f"{noise} noise-source-{index}",
            "body_hash": f"sha256:body-latency-noise-{index}",
        }
        for index in range(noise_source_count)
    ]
    messages.append(
        {
            "message_id": "<latency-target@example.test>",
            "thread_id": "thread_latency_target",
            "folder_path_hash": "sha256:folder-inbox",
            "subject": "Alex Rivera evidence review",
            "sender": "program@example.test",
            "sent_at": NOW,
            "body_segments": [
                "PART-AX9-004 is the selected part for Program ORBIT.",
                "DOC-2026-ABC9 was approved by Alex Rivera.",
            ],
            "body_hash": "sha256:body-latency-target",
        }
    )
    return {
        "archive_id": f"archive_latency_{noise_source_count}",
        "mailbox_id": "mailbox_yifan",
        "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
        "messages": messages,
    }


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
