from __future__ import annotations

from contextvars import Context, copy_context
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import (
    Asset, ContractValidationError, Grant, Observation, PermissionScope, sha256_json, to_plain,
)
from formowl_core import load_default_mail_candidate_admission_tokenizer_profile
from formowl_graph import EffectiveGraphView
from formowl_graph.index import (
    FileVectorStore,
    GraphProjectionEdge,
    GraphProjectionNode,
    VectorRecord,
    VectorSearchResult,
    requester_has_graph_access,
)
from formowl_graph.storage import CandidateAtomStore, CanonicalGraphStore
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import StoredExtractionResult, run_extractor
from formowl_ingestion.extractors.text import PlainTextObservationExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)
from formowl_retrieval import ObservationStoreEvidenceResolver, RetrievalGateway
from formowl_retrieval.gateway import (
    DEVELOPMENT_POC_SOURCE_EVIDENCE_BOUNDARY_ID,
    SECURITY_REVIEW_SOURCE_EVIDENCE_BOUNDARY_ID,
    SOURCE_EVIDENCE_OBSERVATION_LIMIT,
    SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES,
    SourceEvidenceScan,
    SourceEvidenceExecutionPolicy,
    check_source_evidence_deadline,
    source_evidence_deadline_scope,
    source_evidence_double_check,
)

NOW = "2026-07-10T08:00:00+00:00"
PUBLIC_SCOPE = {"scope_type": "public", "visibility": "public"}


class KgFirstCrossResourceRetrievalTests(unittest.TestCase):
    def test_shared_double_check_all_missing_fields_override_unrelated_citations(self) -> None:
        for requested, supported, count, should_read in (
            (("deadline", "owner"), (), 1, True),
            (("deadline", "owner"), ("deadline",), 1, False),
            (("deadline",), ("deadline",), 1, False),
            ((" ｄｅａｄｌｉｎｅ ",), ("deadline",), 1, False),
            ((), (), 1, False),
            ((), (), 0, True),
        ):
            with self.subTest(requested=requested, supported=supported, count=count):
                reader = Mock(return_value=SourceEvidenceScan((), 0, False, "deadline"))
                project = Mock()
                result = source_evidence_double_check(
                    initial_status="partial", query_class="evidence_lookup",
                    result_query_class="evidence_lookup", initial_warnings=(),
                    verified_evidence_count=count, evidence_limit=2,
                    requested_fields=requested, supported_requested_fields=supported,
                    sealed_coverage_complete=False, read_source=reader,
                    project_observation=project,
                )
                self.assertEqual(reader.call_count, int(should_read))
                project.assert_not_called()
                if should_read:
                    self.assertEqual(result.status, "pending_review")
                    self.assertFalse(result.scan.complete)
                    self.assertNotIn("complete_no_match", result.warnings)
                else:
                    self.assertIsNone(result.scan)
                    self.assertIsNone(result.status)

    def test_shared_double_check_rejects_malformed_or_unbound_field_support(self) -> None:
        for requested, supported, count in (
            ("deadline", (), 1),
            (("deadline",), "deadline", 1),
            (("deadline",), ("owner",), 1),
            ((), ("deadline",), 1),
            (("deadline",), ("deadline",), 0),
            (("deadline", ""), (), 1),
            (("deadline", " deadline "), (), 1),
            (("deadline",), (None,), 1),
        ):
            with self.subTest(requested=requested, supported=supported, count=count):
                reader, project = Mock(), Mock()
                with self.assertRaises(ContractValidationError):
                    source_evidence_double_check(
                        initial_status="partial", query_class="evidence_lookup",
                        result_query_class="evidence_lookup", initial_warnings=(),
                        verified_evidence_count=count, evidence_limit=2,
                        requested_fields=requested, supported_requested_fields=supported,
                        sealed_coverage_complete=True, read_source=reader,
                        project_observation=project,
                    )
                reader.assert_not_called()
                project.assert_not_called()

    def test_shared_double_check_field_miss_unavailable_or_incomplete_is_not_absence(self) -> None:
        for reader, coverage in (
            (None, True),
            (Mock(return_value=SourceEvidenceScan((), 1, False, "deadline")), True),
            (Mock(return_value=SourceEvidenceScan((), 1, True)), False),
        ):
            with self.subTest(reader_available=reader is not None, coverage=coverage):
                result = source_evidence_double_check(
                    initial_status="partial", query_class="evidence_lookup",
                    result_query_class="evidence_lookup", initial_warnings=(),
                    verified_evidence_count=1, evidence_limit=2,
                    requested_fields=("deadline",), supported_requested_fields=(),
                    sealed_coverage_complete=coverage, read_source=reader,
                    project_observation=Mock(),
                )
                self.assertEqual(result.status, "pending_review")
                self.assertEqual(result.evidence, ())
                self.assertNotIn("complete_no_match", result.warnings)

    def test_shared_double_check_field_trigger_preserves_exclusions(self) -> None:
        for overrides in (
            {"initial_status": "error"},
            {"initial_status": "permission_denied"},
            {"initial_status": "replan_required"},
            {"query_class": "exact_set_or_inventory"},
            {"result_query_class": "exact_set_or_inventory"},
            {"initial_warnings": ("exact_query_requires_structured_binding",)},
        ):
            with self.subTest(overrides=overrides):
                reader, project = Mock(), Mock()
                result = source_evidence_double_check(**{
                    "initial_status": "partial", "query_class": "evidence_lookup",
                    "result_query_class": "evidence_lookup", "initial_warnings": (),
                    "verified_evidence_count": 1, "evidence_limit": 2,
                    "requested_fields": ("deadline",), "supported_requested_fields": (),
                    "sealed_coverage_complete": True, "read_source": reader,
                    "project_observation": project, **overrides,
                })
                reader.assert_not_called()
                project.assert_not_called()
                self.assertIsNone(result.scan)
                self.assertEqual(result.evidence, ())
                self.assertEqual(
                    result.status,
                    overrides["initial_status"]
                    if overrides.get("initial_status") in ("error", "permission_denied")
                    else "pending_review",
                )

    def test_shared_double_check_total_cap_includes_initial_unrelated_evidence(self) -> None:
        observation = Mock(spec=Observation)
        for initial_count, cap in ((1, 2), (2, 2), (127, 128), (128, 200)):
            with self.subTest(initial_count=initial_count, cap=cap):
                project = Mock(side_effect=lambda *_: (
                    sha256_json(project.call_count),
                    {"citation_hash": sha256_json(project.call_count)},
                ))
                reader = Mock(return_value=SourceEvidenceScan(
                    tuple((observation, "scope") for _ in range(5)), 5, True,
                ))
                result = source_evidence_double_check(
                    initial_status="partial", query_class="evidence_lookup",
                    result_query_class="evidence_lookup", initial_warnings=(),
                    verified_evidence_count=initial_count, evidence_limit=cap,
                    requested_fields=("deadline",), supported_requested_fields=(),
                    sealed_coverage_complete=True, read_source=reader,
                    project_observation=project,
                )
                self.assertLessEqual(initial_count + len(result.evidence), min(cap, 128))
                if initial_count < min(cap, 128):
                    reader.assert_called_once()
                    self.assertEqual(len(result.evidence), 1)
                else:
                    reader.assert_not_called()
                    project.assert_not_called()
                self.assertNotEqual(result.status, "not_found")

    def test_shared_double_check_optional_deadline_preserves_phase_cap(self) -> None:
        for supplied, scoped, expected in (
            (None, None, 10.7),
            (11, None, 10.7),
            (10.4, None, 10.4),
            (None, 10.5, 10.5),
            (10.4, 10.5, 10.4),
            (10.5, 10.4, 10.4),
        ):
            with self.subTest(deadline=supplied, scoped=scoped):
                clock = Mock(return_value=10.0)
                observation = Mock(spec=Observation)
                evidence = {"citation_hash": sha256_json("deadline-fixture")}
                project = Mock(return_value=(evidence["citation_hash"], evidence))
                begin = Mock()

                def prepare():
                    clock.return_value = 10.2

                def read_source(**kwargs):
                    self.assertEqual(kwargs["max_observations"], 8192)
                    self.assertEqual(kwargs["deadline_monotonic"], expected)
                    self.assertFalse(kwargs["observation_callback"](observation, "scope"))
                    return SourceEvidenceScan((), 1, True)

                reader = Mock(side_effect=read_source)
                with (
                    patch("formowl_retrieval.gateway.time.monotonic", clock),
                    source_evidence_deadline_scope(scoped),
                ):
                    result = source_evidence_double_check(
                        initial_status="no_answer", query_class="evidence_lookup",
                        result_query_class="evidence_lookup", initial_warnings=(),
                        verified_evidence_count=0, evidence_limit=1,
                        sealed_coverage_complete=True, read_source=reader,
                        project_observation=project, prepare=prepare, begin=begin,
                        deadline_monotonic=supplied,
                    )
                reader.assert_called_once()
                begin.assert_called_once_with(expected)
                project.assert_called_once_with(observation, "scope", expected)
                self.assertEqual(result.status, "ok")
                self.assertEqual(result.evidence, (evidence,))
                self.assertEqual(result.warnings, ("used", "incomplete"))
                self.assertFalse(result.scan.complete)
                self.assertEqual(result.scan.stop_reason, "callback")

    def test_shared_double_check_expired_deadline_skips_callbacks(self) -> None:
        for deadline in (9.0, 10.0):
            for overrides, status, warnings in (
                ({}, "pending_review", ("used", "incomplete")),
                ({"initial_status": "error"}, "error", ()),
                ({"initial_status": "permission_denied"}, "permission_denied", ()),
                (
                    {"initial_status": "replan_required"},
                    "pending_review", ("skipped_replan",),
                ),
                (
                    {"query_class": "exact_set_or_inventory"},
                    "pending_review", ("skipped_exact",),
                ),
                ({"verified_evidence_count": 1}, None, ()),
            ):
                with self.subTest(deadline=deadline, overrides=overrides):
                    reader, project, prepare, begin = Mock(), Mock(), Mock(), Mock()
                    bindings = {
                        "initial_status": "no_answer", "query_class": "evidence_lookup",
                        "result_query_class": "evidence_lookup", "initial_warnings": (),
                        "verified_evidence_count": 0, "evidence_limit": 1,
                        "sealed_coverage_complete": True, "read_source": reader,
                        "project_observation": project, "prepare": prepare, "begin": begin,
                        "deadline_monotonic": deadline,
                    }
                    with patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0):
                        result = source_evidence_double_check(**{**bindings, **overrides})
                    for callback in (reader, project, prepare, begin):
                        callback.assert_not_called()
                    self.assertEqual(result.status, status)
                    self.assertEqual(result.warnings, warnings)
                    self.assertEqual(result.evidence, ())
                    if overrides:
                        self.assertIsNone(result.scan)
                    else:
                        self.assertEqual(result.scan.scanned_observation_count, 0)
                        self.assertFalse(result.scan.complete)
                        self.assertEqual(result.scan.stop_reason, "deadline")

    def test_shared_double_check_prepare_cannot_reset_absolute_deadline(self) -> None:
        clock = Mock(return_value=10.0)
        reader, project, begin = Mock(), Mock(), Mock()

        def expire_during_prepare():
            clock.return_value = 10.25

        prepare = Mock(side_effect=expire_during_prepare)
        with patch("formowl_retrieval.gateway.time.monotonic", clock):
            result = source_evidence_double_check(
                initial_status="no_answer", query_class="evidence_lookup",
                result_query_class="evidence_lookup", initial_warnings=(),
                verified_evidence_count=0, evidence_limit=1, sealed_coverage_complete=True,
                read_source=reader, project_observation=project,
                prepare=prepare, begin=begin, deadline_monotonic=10.25,
            )
        prepare.assert_called_once()
        for callback in (reader, project, begin):
            callback.assert_not_called()
        self.assertEqual(result.status, "pending_review")
        self.assertEqual(result.warnings, ("used", "incomplete"))
        self.assertEqual(result.evidence, ())
        self.assertEqual(result.scan.scanned_observation_count, 0)
        self.assertFalse(result.scan.complete)
        self.assertEqual(result.scan.stop_reason, "deadline")

    def test_shared_double_check_reader_return_enforces_absolute_deadline(self) -> None:
        for observations in ((), ((Mock(spec=Observation), "scope"),)):
            with self.subTest(batch=bool(observations)):
                clock = Mock(return_value=10.0)
                project = Mock()

                def read_source(**kwargs):
                    self.assertEqual(kwargs["deadline_monotonic"], 10.25)
                    clock.return_value = 10.25
                    return SourceEvidenceScan(observations, len(observations), True)

                reader = Mock(side_effect=read_source)
                with patch("formowl_retrieval.gateway.time.monotonic", clock):
                    result = source_evidence_double_check(
                        initial_status="no_answer", query_class="evidence_lookup",
                        result_query_class="evidence_lookup", initial_warnings=(),
                        verified_evidence_count=0, evidence_limit=1,
                        sealed_coverage_complete=True, read_source=reader,
                        project_observation=project, deadline_monotonic=10.25,
                    )
                reader.assert_called_once()
                project.assert_not_called()
                self.assertEqual(result.status, "pending_review")
                self.assertEqual(result.warnings, ("used", "incomplete"))
                self.assertEqual(result.evidence, ())
                self.assertEqual(result.scan.scanned_observation_count, len(observations))
                self.assertFalse(result.scan.complete)
                self.assertEqual(result.scan.stop_reason, "deadline")

    def test_shared_double_check_rejects_invalid_absolute_deadline(self) -> None:
        reader, project, prepare, begin = Mock(), Mock(), Mock(), Mock()
        for deadline in (True, False, "10.25", [], float("nan"), float("inf"), -float("inf")):
            with self.subTest(deadline=deadline):
                with self.assertRaisesRegex(ContractValidationError, "source evidence deadline"):
                    source_evidence_double_check(
                        initial_status="no_answer", query_class="evidence_lookup",
                        result_query_class="evidence_lookup", initial_warnings=(),
                        verified_evidence_count=0, evidence_limit=1,
                        sealed_coverage_complete=True, read_source=reader,
                        project_observation=project, prepare=prepare, begin=begin,
                        deadline_monotonic=deadline,
                    )
                with self.assertRaisesRegex(ContractValidationError, "source evidence deadline"):
                    with source_evidence_deadline_scope(deadline):
                        self.fail("invalid deadline entered the scope")
        for callback in (reader, project, prepare, begin):
            callback.assert_not_called()

    def test_shared_double_check_deadline_scope_nesting_restores_after_error(self) -> None:
        reader = Mock(return_value=SourceEvidenceScan((), 0, True))
        project = Mock()

        def effective_deadline():
            result = source_evidence_double_check(
                initial_status="no_answer", query_class="evidence_lookup",
                result_query_class="evidence_lookup", initial_warnings=(),
                verified_evidence_count=0, evidence_limit=1, sealed_coverage_complete=True,
                read_source=reader, project_observation=project,
            )
            self.assertEqual(result.status, "not_found")
            return reader.call_args.kwargs["deadline_monotonic"]

        with patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0):
            self.assertEqual(effective_deadline(), 10.5)
            with source_evidence_deadline_scope(10.4):
                self.assertEqual(effective_deadline(), 10.4)
                for inherited in (None, 11):
                    with source_evidence_deadline_scope(inherited):
                        self.assertEqual(effective_deadline(), 10.4)
                with self.assertRaisesRegex(RuntimeError, "synthetic scope failure"):
                    with source_evidence_deadline_scope(10.2):
                        self.assertEqual(effective_deadline(), 10.2)
                        raise RuntimeError("synthetic scope failure")
                self.assertEqual(effective_deadline(), 10.4)
            self.assertEqual(effective_deadline(), 10.5)
        project.assert_not_called()

    def test_shared_double_check_deadline_scope_isolated_between_contexts(self) -> None:
        reader = Mock(return_value=SourceEvidenceScan((), 0, True))
        project, prepare, begin = Mock(), Mock(), Mock()

        def check():
            return source_evidence_double_check(
                initial_status="no_answer", query_class="evidence_lookup",
                result_query_class="evidence_lookup", initial_warnings=(),
                verified_evidence_count=0, evidence_limit=1, sealed_coverage_complete=True,
                read_source=reader, project_observation=project, prepare=prepare, begin=begin,
            )

        with patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0):
            with source_evidence_deadline_scope(10.0):
                captured = copy_context()
                result = check()
                self.assertEqual(result.status, "pending_review")
                self.assertEqual(result.scan.stop_reason, "deadline")
                for callback in (reader, project, prepare, begin):
                    callback.assert_not_called()
                self.assertEqual(Context().run(check).status, "not_found")
                self.assertEqual(reader.call_args.kwargs["deadline_monotonic"], 10.5)
                self.assertEqual(check().status, "pending_review")
                reader.assert_called_once()
            self.assertEqual(check().status, "not_found")
            self.assertEqual(reader.call_count, 2)
            self.assertEqual(captured.run(check).status, "pending_review")
            self.assertEqual(reader.call_count, 2)
            self.assertEqual(check().status, "not_found")
            self.assertEqual(reader.call_count, 3)
        project.assert_not_called()

    def test_shared_double_check_resolves_real_standalone_documents_locally(self) -> None:
        # Local diagnostic only: no revision-runtime/document-handler composition.
        for filename, mime_type in (("notes.md", "text/markdown"), ("notes.txt", "text/plain")):
            with self.subTest(mime_type=mime_type):
                temp_dir = _paths.fresh_test_dir(f"source-recheck-{filename}")
                bindings, asset, extraction, store = _document_recheck_bindings(
                    temp_dir, filename=filename, mime_type=mime_type
                )
                stored_before = [item.to_dict() for item in store.list()]
                with patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0):
                    result = source_evidence_double_check(**bindings)
                bindings["read_source"].assert_called_once()
                read_args = bindings["read_source"].call_args.kwargs
                self.assertEqual(read_args["max_observations"], 8192)
                self.assertEqual(read_args["deadline_monotonic"], 10.5)
                self.assertEqual(result.status, "ok")
                self.assertEqual(
                    result.execution_boundary_id,
                    DEVELOPMENT_POC_SOURCE_EVIDENCE_BOUNDARY_ID,
                )
                self.assertEqual(
                    result.supported_source_families,
                    SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES,
                )
                self.assertEqual(result.warnings, ("used", "incomplete"))
                self.assertEqual(len(result.evidence), 1)
                evidence = result.evidence[0]
                self.assertEqual(evidence["modality"], "text")
                self.assertEqual(evidence["asset_id"], asset.asset_id)
                self.assertEqual(evidence["location"], {"line_start": 3, "line_end": 4})
                self.assertEqual(evidence["snippet"], "ZX-421 requires review.\nApproval recorded.")
                self.assertEqual(evidence["source_revision"], asset.content_hash)
                self.assertEqual(evidence["extractor_run_id"], extraction.extractor_run.extractor_run_id)
                self.assertEqual(
                    evidence["source_observation_hash"],
                    sha256_json(store.get(evidence["observation_id"]).to_dict()),
                )
                self.assertNotIn("mail_import_session_id", json.dumps(result.evidence))
                self.assertNotIn("attachment", json.dumps(result.evidence))
                self.assertNotIn(str(temp_dir), json.dumps(result.evidence))
                self.assertEqual([item.to_dict() for item in store.list()], stored_before)

    def test_security_review_boundary_fails_closed_before_source_access(self) -> None:
        bindings, _, _, _ = _document_recheck_bindings(
            _paths.fresh_test_dir("source-recheck-security-boundary")
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "security review source evidence boundary requires",
        ):
            source_evidence_double_check(
                **bindings,
                execution_policy=SourceEvidenceExecutionPolicy(
                    boundary_id=SECURITY_REVIEW_SOURCE_EVIDENCE_BOUNDARY_ID,
                ),
            )
        bindings["read_source"].assert_not_called()

    def test_security_review_boundary_is_explicit_and_still_source_neutral(self) -> None:
        policy = SourceEvidenceExecutionPolicy.security_review(
            authority_ready=True,
            source_completeness_verified=True,
            execution_fingerprint_bound=True,
            same_pipeline_ablation_verified=True,
            final_answer_acceptance_verified=True,
            reviewer_agreement_count=3,
        )
        self.assertEqual(
            policy.supported_source_families,
            SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES,
        )
        self.assertEqual(policy.to_safe_dict()["claim_class"], "security_review_evidence_candidate")

    def test_document_double_check_empty_result_needs_scan_and_sealed_coverage(self) -> None:
        temp_dir = _paths.fresh_test_dir("source-recheck-document-miss")
        bindings, _, _, _ = _document_recheck_bindings(
            temp_dir, query_text="ZX-9999 review",
        )
        for sealed_coverage in (True, False):
            with self.subTest(sealed_coverage=sealed_coverage):
                result = source_evidence_double_check(
                    **{**bindings, "sealed_coverage_complete": sealed_coverage}
                )
                self.assertEqual(result.status, "not_found" if sealed_coverage else "pending_review")
                self.assertEqual(result.evidence, ())
                self.assertTrue(result.scan.complete)
                # A shared word cannot override the frozen protected identifier.
                self.assertEqual(result.scan.scanned_observation_count, 3)
        for overrides in (
            {"read_source": None},
            {"evidence_limit": 0},
            {"read_source": Mock(return_value=SourceEvidenceScan((), 1, False, "deadline"))},
        ):
            with self.subTest(overrides=overrides):
                result = source_evidence_double_check(**{**bindings, **overrides})
                self.assertEqual(result.status, "pending_review")
                self.assertEqual(result.evidence, ())

    def test_document_double_check_security_exceptions_are_not_softened(self) -> None:
        temp_dir = _paths.fresh_test_dir("source-recheck-document-denied")
        bindings, asset, extraction, store = _document_recheck_bindings(temp_dir, grants=[])
        with self.assertRaises(PermissionError):
            source_evidence_double_check(**bindings)
        bindings["project_observation"].assert_not_called()
        # The actual resolver also rechecks the grant, even for an incorrect reader.
        observation = store.get(extraction.observations[1].observation_id)
        bindings["read_source"] = Mock(
            return_value=SourceEvidenceScan(((observation, asset.asset_id),), 1, True)
        )
        with self.assertRaises(PermissionError):
            source_evidence_double_check(**bindings)

        bindings, asset, extraction, store = _document_recheck_bindings(
            _paths.fresh_test_dir("source-recheck-document-binding")
        )
        observation = store.get(extraction.observations[1].observation_id)
        for item, scope in (
            (observation, "asset_other"),
            (replace(observation, text="changed"), asset.asset_id),
            (replace(observation, extractor_run_id="extractor_other"), asset.asset_id),
        ):
            with self.subTest(scope=scope, observation=item.observation_id):
                bindings["read_source"] = Mock(
                    return_value=SourceEvidenceScan(((item, scope),), 1, True)
                )
                with self.assertRaises(ContractValidationError):
                    source_evidence_double_check(**bindings)

    def test_shared_double_check_caps_noncooperating_reader_and_does_not_replay(self) -> None:
        bindings, asset, extraction, store = _document_recheck_bindings(
            _paths.fresh_test_dir("source-recheck-bounds")
        )
        observation = store.get(extraction.observations[1].observation_id)
        project = Mock(return_value=None)

        def excessive_reader(**kwargs):
            for _ in range(SOURCE_EVIDENCE_OBSERVATION_LIMIT + 2):
                kwargs["observation_callback"](observation, asset.asset_id)
            return SourceEvidenceScan((), SOURCE_EVIDENCE_OBSERVATION_LIMIT + 2, True)

        with patch("formowl_retrieval.gateway.time.monotonic", return_value=10.0):
            result = source_evidence_double_check(
                **{**bindings, "read_source": excessive_reader, "project_observation": project}
            )
        self.assertEqual(project.call_count, 8192)
        self.assertEqual(result.status, "pending_review")
        self.assertFalse(result.scan.complete)
        self.assertEqual(result.scan.stop_reason, "observation_limit")

        def duplicate_reader(**kwargs):
            callback = kwargs["observation_callback"]
            self.assertFalse(callback(observation, asset.asset_id))
            self.assertFalse(callback(observation, asset.asset_id))
            # A noncooperating reader cannot override the core's early stop.
            return SourceEvidenceScan(((observation, asset.asset_id),), 2, True)

        result = source_evidence_double_check(**{**bindings, "read_source": duplicate_reader})
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.evidence), 1)
        self.assertFalse(result.scan.complete)
        self.assertEqual(result.scan.stop_reason, "callback")
        self.assertEqual(result.warnings, ("used", "incomplete"))
        bindings["project_observation"].assert_called_once()

        bindings["project_observation"].reset_mock()
        unread = store.get(extraction.observations[2].observation_id)
        batch_reader = Mock(return_value=SourceEvidenceScan(
            ((observation, asset.asset_id), (unread, asset.asset_id)), 2, True,
        ))
        result = source_evidence_double_check(**{**bindings, "read_source": batch_reader})
        self.assertEqual(len(result.evidence), 1)
        self.assertFalse(result.scan.complete)
        self.assertEqual(result.scan.stop_reason, "callback")
        self.assertEqual(result.warnings, ("used", "incomplete"))
        bindings["project_observation"].assert_called_once()

    def test_shared_double_check_rejects_invalid_plan_before_source_access(self) -> None:
        read_source, project, prepare, begin = Mock(), Mock(), Mock(), Mock()
        for query_class, result_class in (
            ("ordinary_chat", None),
            ("unknown", "evidence_lookup"),
            (None, "evidence_lookup"),
            ([], None),
            ("evidence_lookup", "ordinary_chat"),
            ("evidence_lookup", {}),
        ):
            with self.subTest(query_class=query_class, result_class=result_class):
                result = source_evidence_double_check(
                    initial_status="not_found", query_class=query_class,
                    result_query_class=result_class, initial_warnings=(),
                    verified_evidence_count=0, evidence_limit=5, sealed_coverage_complete=True,
                    read_source=read_source, project_observation=project,
                    prepare=prepare, begin=begin,
                )
                self.assertEqual(result.status, "pending_review")
                self.assertEqual(result.warnings, ("skipped_invalid_plan",))
                self.assertEqual(result.evidence, ())
                self.assertIsNone(result.scan)
        for callback in (read_source, project, prepare, begin):
            callback.assert_not_called()

    def test_observation_resolver_preserves_independently_extracted_text_line_ranges(self) -> None:
        for filename, mime_type, content, expected in (
            (
                "acceptance.md",
                "text/markdown",
                "# Acceptance notes\n\nReview must pass.\nApproval must be recorded.\n\nDone.\n",
                [(1, 1, "heading"), (3, 4, "paragraph"), (6, 6, "paragraph")],
            ),
            (
                "acceptance.txt",
                "text/plain",
                "\nAcceptance notes\n\nReview must pass.\nApproval must be recorded.\n\nDone.",
                [(2, 2, "paragraph"), (4, 5, "paragraph"), (7, 7, "paragraph")],
            ),
        ):
            with self.subTest(mime_type=mime_type):
                temp_dir = _paths.fresh_test_dir(f"kg-first-extracted-{filename}")
                asset, extraction, store = _extract_document(
                    temp_dir, filename=filename, mime_type=mime_type, content=content
                )
                self.assertEqual(extraction.extractor_run.status, "succeeded")
                self.assertEqual(extraction.extractor_run.input_hash, asset.content_hash)
                self.assertEqual(len(extraction.observations), len(expected))
                stored_before = [item.to_dict() for item in store.list()]
                resolver = ObservationStoreEvidenceResolver(ObservationStore(temp_dir))

                resolved, unresolved = resolver.resolve(
                    [item.observation_id for item in extraction.observations],
                    requester_user_id="user_pm",
                    grants=[_document_read_grant()],
                    now=NOW,
                )

                self.assertEqual(unresolved, [])
                self.assertEqual(len(resolved), len(expected))
                by_id = {item.observation_id: item for item in resolved}
                for observation, (start, end, kind) in zip(extraction.observations, expected):
                    evidence = by_id[observation.observation_id]
                    self.assertEqual(evidence.location, {"line_start": start, "line_end": end})
                    self.assertEqual(evidence.observation_type, kind)
                    self.assertEqual(evidence.modality, "text")
                    self.assertEqual(evidence.asset_id, asset.asset_id)
                    self.assertEqual(
                        evidence.evidence_locator,
                        f"formowl://observation/{observation.observation_id}",
                    )
                    self.assertEqual(
                        evidence.snippet, "\n".join(content.splitlines()[start - 1 : end])
                    )
                    self.assertEqual(
                        observation.extractor_run_id, extraction.extractor_run.extractor_run_id
                    )
                    self.assertEqual(observation.payload["source_ref"]["source_type"], "file")
                self.assertEqual([item.to_dict() for item in store.list()], stored_before)

    def test_observation_resolver_denies_extracted_document_without_matching_grant(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-extracted-document-denied")
        asset, extraction, store = _extract_document(
            temp_dir,
            filename="private.md",
            mime_type="text/markdown",
            content="Restricted acceptance condition.\n",
        )
        observation_ids = [item.observation_id for item in extraction.observations]
        self.assertEqual(len(observation_ids), 1)
        resolver = ObservationStoreEvidenceResolver(store)
        for grants in (
            [],
            [_document_read_grant(scope_id="project_other")],
            [_document_read_grant(grantee_user_id="user_other")],
            [_document_read_grant(expires_at="2026-07-09T00:00:00+00:00")],
        ):
            with self.subTest(grants=grants):
                resolved, unresolved = resolver.resolve(
                    observation_ids, requester_user_id="user_pm", grants=grants, now=NOW
                )
                self.assertEqual(resolved, [])
                self.assertEqual(unresolved, observation_ids)
                self.assertNotIn(asset.asset_id, json.dumps(unresolved))

    def test_observation_resolver_omits_invalid_or_unpaired_line_ranges(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-invalid-line-ranges")
        store = ObservationStore(temp_dir)
        resolver = ObservationStoreEvidenceResolver(store)
        invalid_ranges = [
            {"line_start": 1},
            {"line_end": 2},
            {"line_start": True, "line_end": 2},
            {"line_start": 1, "line_end": True},
            {"line_start": False, "line_end": 2},
            {"line_start": 1, "line_end": False},
            {"line_start": 0, "line_end": 2},
            {"line_start": 1, "line_end": 0},
            {"line_start": -1, "line_end": 2},
            {"line_start": 3, "line_end": 2},
            {"line_start": 1.0, "line_end": 2},
            {"line_start": 1, "line_end": 2.0},
            {"line_start": "1", "line_end": 2},
            {"line_start": 1, "line_end": "2"},
            {"line_start": None, "line_end": 2},
            {"line_start": 1, "line_end": None},
            {"line_start": [], "line_end": 2},
            {"line_start": 1, "line_end": {}},
            {"line_start": "/srv/private/document.txt", "line_end": 2},
        ]
        for index, line_range in enumerate(invalid_ranges):
            with self.subTest(line_range=line_range):
                observation = _observation(
                    f"obs_invalid_lines_{index}",
                    "asset_document",
                    "paragraph",
                    "text",
                    {**line_range, "page_number": 2, "section": "Acceptance"},
                    "Safe evidence remains available.",
                )
                stored = store.create(observation)
                resolved, unresolved = resolver.resolve(
                    [observation.observation_id],
                    requester_user_id="user_pm",
                    grants=[],
                    now=NOW,
                )
                self.assertEqual(unresolved, [])
                self.assertEqual(len(resolved), 1)
                self.assertEqual(resolved[0].location, {"page_number": 2, "section": "Acceptance"})
                self.assertEqual(resolved[0].snippet, observation.text)
                self.assertNotIn("/srv/private", json.dumps(resolved[0].to_dict()))
                self.assertEqual(store.get(observation.observation_id).to_dict(), stored.to_dict())

    def test_observation_resolver_keeps_path_filters_with_valid_line_ranges(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-line-range-path-filter")
        store = ObservationStore(temp_dir)
        observation = _observation(
            "obs_text_paths",
            "asset_document",
            "paragraph",
            "text",
            {
                "line_start": 3,
                "line_end": 4,
                "raw_path": "/srv/private/document.txt",
                "section": "nas/private/document.txt",
                "block_id": "block_safe",
            },
            "Source is /srv/private/document.txt",
        )
        store.create(observation)
        resolved, unresolved = ObservationStoreEvidenceResolver(store).resolve(
            [observation.observation_id], requester_user_id="user_pm", grants=[], now=NOW
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(len(resolved), 1)
        self.assertEqual(
            resolved[0].location, {"line_start": 3, "line_end": 4, "block_id": "block_safe"}
        )
        self.assertIsNone(resolved[0].snippet)
        rendered = json.dumps(resolved[0].to_dict())
        self.assertNotIn("/srv/private", rendered)
        self.assertNotIn("nas/private", rendered)
        self.assertNotIn("raw_path", rendered)

    def test_kg_first_hit_resolves_mail_slide_and_project_evidence_without_fallback(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-cross-resource")
        observation_store = ObservationStore(temp_dir)
        observations = [
            _observation(
                "obs_optoma_mail",
                "asset_optoma_mail",
                "mail_message",
                "mail",
                {"thread_id": "thread_optoma", "message_id": "msg_optoma"},
                "Optoma requested a revised quotation.",
            ),
            _observation(
                "obs_optoma_slide",
                "asset_optoma_slide",
                "slide_region",
                "slide",
                {"slide_number": 7, "shape_id": "shape_decision"},
                "Decision: accept the revised Optoma quotation.",
            ),
            _observation(
                "obs_optoma_project",
                "asset_optoma_project",
                "work_package_comment",
                "project",
                {"section_id": "work_package_42"},
                "The project owner confirmed the quotation decision.",
            ),
        ]
        for observation in observations:
            observation_store.create(observation)
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(_vector("vec_unused", "obs_optoma_mail"))
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
            minimum_evidence_count=3,
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="What was the final Optoma quotation decision?",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_kg_first",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=[item.observation_id for item in observations],
                    source_asset_ids=[str(item.asset_id) for item in observations],
                )
            ),
        )

        self.assertFalse(result.fallback_used, result.to_dict())
        self.assertIsNone(result.fallback_reason)
        self.assertEqual(result.evidence_coverage, 1.0)
        self.assertEqual(len(result.graph_hits), 1)
        self.assertEqual(
            result.graph_hits[0]["source_observation_ids"],
            ["obs_optoma_mail", "obs_optoma_project", "obs_optoma_slide"],
        )
        self.assertEqual(
            sorted(item["modality"] for item in result.evidence),
            ["mail", "project", "slide"],
        )
        self.assertEqual(
            sorted(result.graph_hits[0]["evidence_locators"]),
            [
                "formowl://observation/obs_optoma_mail",
                "formowl://observation/obs_optoma_project",
                "formowl://observation/obs_optoma_slide",
            ],
        )
        self.assertEqual(result.retrieval_trace.matched_vector_ids, [])
        self.assertEqual(result.candidate_graph_proposal_seeds, [])
        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(CanonicalGraphStore(temp_dir).list_atoms(), [])

    def test_incomplete_graph_evidence_triggers_fallback_and_reviewable_candidate_seed(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-fallback-seed")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_optoma_mail",
                "asset_optoma_mail",
                "mail_message",
                "mail",
                {"thread_id": "thread_optoma"},
                "Optoma requested a revised quotation.",
            )
        )
        observation_store.create(
            _observation(
                "obs_optoma_project_fallback",
                "asset_optoma_project",
                "work_package_comment",
                "project",
                {"section_id": "work_package_fallback"},
                "Project fallback confirms the final decision.",
            )
        )
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(
            _vector(
                "vec_project_fallback",
                "obs_optoma_project_fallback",
                metadata={
                    "evidence_snippet": "Project fallback confirms the final decision.",
                    "asset_id": "asset_untrusted_vector_metadata",
                    "source_observation_ids": ["obs_untrusted_metadata"],
                    "source_asset_ids": ["asset_untrusted_metadata"],
                },
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_fallback",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_optoma_mail", "obs_optoma_missing"],
                    source_asset_ids=["asset_optoma_mail"],
                )
            ),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_reason, "graph_evidence_incomplete_fallback_used")
        self.assertEqual(result.evidence_coverage, 0.5)
        self.assertEqual(result.retrieval_trace.matched_vector_ids, ["vec_project_fallback"])
        self.assertEqual(len(result.candidate_graph_proposal_seeds), 1)
        seed = result.candidate_graph_proposal_seeds[0]
        self.assertEqual(seed["status"], "pending_review")
        self.assertTrue(seed["requires_review"])
        self.assertFalse(seed["canonical_write_performed"])
        self.assertEqual(seed["source_observation_ids"], ["obs_optoma_project_fallback"])
        self.assertEqual(seed["source_asset_ids"], ["asset_optoma_project"])
        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(CanonicalGraphStore(temp_dir).list_atoms(), [])

    def test_unresolved_vector_metadata_lineage_does_not_create_candidate_seed(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-unresolved-fallback-seed")
        observation_store = ObservationStore(temp_dir)
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(
            _vector(
                "vec_unresolved_metadata",
                "obs_missing_authoritative",
                metadata={
                    "asset_id": "asset_untrusted_metadata",
                    "source_observation_ids": ["obs_untrusted_metadata"],
                    "source_asset_ids": ["asset_untrusted_metadata"],
                },
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_unresolved_seed",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=EffectiveGraphView(
                requester_user_id="user_pm",
                user_graph_revision_id="ugraph_empty",
                canonical_graph_revision_id="cgraph_empty",
                ontology_revision_id="ontology_empty",
                assembly_policy_id="policy_empty",
            ),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.candidate_graph_proposal_seeds, [])
        rendered = json.dumps(result.to_dict(), sort_keys=True)
        self.assertNotIn("obs_untrusted_metadata", rendered)
        self.assertNotIn("asset_untrusted_metadata", rendered)

    def test_graph_miss_and_low_confidence_hits_use_explicit_fallback_reasons(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-miss-low-confidence")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_optoma_mail",
                "asset_optoma_mail",
                "mail_message",
                "mail",
                {"thread_id": "thread_optoma"},
                "Optoma quotation decision.",
            )
        )
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(
            _vector(
                "vec_fallback",
                "obs_fallback",
                metadata={"asset_id": "asset_fallback"},
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )

        graph_miss = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="unrelated payroll policy",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_graph_miss",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_optoma_mail"],
                    source_asset_ids=["asset_optoma_mail"],
                )
            ),
        )
        low_confidence = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_low_confidence",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_optoma_mail"],
                    source_asset_ids=["asset_optoma_mail"],
                    confidence=0.3,
                )
            ),
        )

        self.assertEqual(graph_miss.fallback_reason, "graph_miss_fallback_used")
        self.assertEqual(
            low_confidence.fallback_reason,
            "graph_confidence_insufficient_fallback_used",
        )
        self.assertEqual(graph_miss.retrieval_trace.matched_vector_ids, ["vec_fallback"])
        self.assertEqual(low_confidence.retrieval_trace.matched_vector_ids, ["vec_fallback"])
        self.assertEqual(
            [log.metadata["fallback_used"] for log in FileAuditLogStore(temp_dir).list()],
            [True, True],
        )

    def test_permission_denied_or_unsafe_observation_content_is_not_exposed(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-permission-leak")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_private",
                "asset_private",
                "document_block",
                "document",
                {"raw_path": "/srv/private/secret.pdf", "page_number": 2},
                "/srv/private/secret.pdf select * from private_table",
                permission_scope=PermissionScope.project("project_private").to_dict(),
            )
        )
        vector_store = FileVectorStore(temp_dir)
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_denied",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_private"],
                    source_asset_ids=["asset_private"],
                )
            ),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.evidence, [])
        rendered = json.dumps(result.to_dict(), sort_keys=True).lower()
        self.assertNotIn("/srv/", rendered)
        self.assertNotIn("select *", rendered)
        self.assertNotIn("private_table", rendered)

    def test_visible_but_fully_redacted_observation_does_not_count_as_complete_evidence(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-redacted-evidence-coverage")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_redacted",
                "asset_redacted",
                "document_block",
                "document",
                {"page_number": 2, "raw_path": "/srv/private/source.pdf"},
                "/srv/private/source.pdf select * from private_table",
            )
        )
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(_vector("vec_safe_fallback", "obs_safe_fallback"))
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_redacted",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_redacted"],
                    source_asset_ids=["asset_redacted"],
                )
            ),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_reason, "graph_evidence_incomplete_fallback_used")
        self.assertEqual(result.evidence_coverage, 0.0)
        self.assertEqual(
            result.evidence[0]["evidence_locator"], "formowl://observation/obs_redacted"
        )
        self.assertNotIn("snippet", result.evidence[0])
        rendered = json.dumps(result.to_dict(), sort_keys=True).lower()
        self.assertNotIn("/srv/", rendered)
        self.assertNotIn("select *", rendered)

    def test_raw_asset_refs_from_graph_hits_require_explicit_grant(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-raw-asset")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_optoma_mail",
                "asset_optoma_mail",
                "mail_message",
                "mail",
                {"thread_id": "thread_optoma"},
                "Optoma quotation decision.",
            )
        )
        gateway = RetrievalGateway(
            vector_store=FileVectorStore(temp_dir),
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )
        common = {
            "query_embedding": [1.0, 0.0],
            "query_text": "Optoma quotation decision",
            "requester_user_id": "user_pm",
            "workspace_id": "workspace_main",
            "session_id": "session_raw",
            "mode": "raw_asset",
            "now": NOW,
            "effective_graph_view": _view(
                _concept_node(
                    source_observation_ids=["obs_optoma_mail"],
                    source_asset_ids=["asset_optoma_mail"],
                )
            ),
        }

        denied = gateway.query_effective_graph_view(**common)
        self.assertEqual(denied.status, "permission_denied")
        allowed = gateway.query_effective_graph_view(
            **common,
            grants=[_raw_asset_grant()],
        )
        self.assertFalse(allowed.fallback_used)
        self.assertEqual(
            allowed.raw_asset_refs,
            [
                {
                    "source_type": "graph_object",
                    "source_id": "node_optoma_decision",
                    "asset_locator": "formowl://asset/asset_optoma_mail",
                    "access": "explicit_grant_required",
                    "content_returned": False,
                }
            ],
        )

    def test_relation_hits_are_query_scored_and_view_identity_cannot_be_rebound(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-relation-view-identity")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_relation",
                "asset_relation",
                "work_package_relation",
                "project",
                {"section_id": "relation_42"},
                "The Optoma quotation decision supports milestone 42.",
            )
        )
        gateway = RetrievalGateway(
            vector_store=FileVectorStore(temp_dir),
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
        )
        view = EffectiveGraphView(
            requester_user_id="user_pm",
            user_graph_revision_id="ugraph_relation",
            canonical_graph_revision_id="cgraph_relation",
            ontology_revision_id="ontology_relation",
            assembly_policy_id="policy_relation",
            visible_nodes=[
                GraphProjectionNode(
                    node_id="node_optoma",
                    source_type="candidate_entity",
                    source_id="entity_optoma",
                    labels=["optoma", "vendor"],
                    properties={"label": "Optoma vendor"},
                    permission_scope=PUBLIC_SCOPE,
                ),
                GraphProjectionNode(
                    node_id="node_milestone",
                    source_type="candidate_milestone",
                    source_id="milestone_42",
                    labels=["milestone", "42"],
                    properties={"label": "Milestone 42"},
                    permission_scope=PUBLIC_SCOPE,
                ),
            ],
            visible_edges=[
                GraphProjectionEdge(
                    edge_id="edge_optoma_milestone",
                    source_node_id="node_optoma",
                    target_node_id="node_milestone",
                    relation_type="supports_milestone",
                    properties={
                        "label": "Optoma quotation decision supports milestone",
                        "confidence": 0.88,
                        "review_state": "candidate",
                        "source_observation_ids": ["obs_relation"],
                        "source_asset_ids": ["asset_relation"],
                    },
                    permission_scope=PUBLIC_SCOPE,
                )
            ],
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Which Optoma decision supports the milestone?",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_relation",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=view,
        )

        self.assertFalse(result.fallback_used)
        self.assertEqual(result.graph_hits[0]["graph_object_id"], "edge_optoma_milestone")
        self.assertEqual(result.graph_hits[0]["object_type"], "graph_relation")
        with self.assertRaises(ContractValidationError):
            gateway.query_effective_graph_view(
                query_embedding=[1.0, 0.0],
                query_text="Optoma milestone",
                requester_user_id="user_other",
                workspace_id="workspace_main",
                session_id="session_rebind",
                mode="evidence_snippet",
                now=NOW,
                effective_graph_view=view,
            )

    def test_caller_supplied_view_is_permission_filtered_before_matching(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-caller-view-permission-filter")
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(_vector("vec_safe_fallback", "obs_safe_fallback"))
        gateway = RetrievalGateway(vector_store=vector_store)
        private_scope = PermissionScope.project("project_private").to_dict()
        view = EffectiveGraphView(
            requester_user_id="user_pm",
            user_graph_revision_id="ugraph_untrusted",
            canonical_graph_revision_id="cgraph_untrusted",
            ontology_revision_id="ontology_untrusted",
            assembly_policy_id="policy_untrusted",
            visible_nodes=[
                GraphProjectionNode(
                    node_id="node_private_decision",
                    source_type="candidate_frame",
                    source_id="private_source_id",
                    labels=["secret", "merger", "decision"],
                    properties={
                        "label": "Secret merger decision",
                        "review_state": "private_review",
                        "source_observation_ids": ["obs_private"],
                        "source_asset_ids": ["asset_private"],
                    },
                    permission_scope=private_scope,
                ),
                GraphProjectionNode(
                    node_id="node_public_left",
                    source_type="candidate_entity",
                    source_id="public_left",
                    labels=["public", "left"],
                    properties={"label": "Public left"},
                    permission_scope=PUBLIC_SCOPE,
                ),
                GraphProjectionNode(
                    node_id="node_public_right",
                    source_type="candidate_entity",
                    source_id="public_right",
                    labels=["public", "right"],
                    properties={"label": "Public right"},
                    permission_scope=PUBLIC_SCOPE,
                ),
            ],
            visible_edges=[
                GraphProjectionEdge(
                    edge_id="edge_private_merger",
                    source_node_id="node_public_left",
                    target_node_id="node_public_right",
                    relation_type="secret_merger_relation",
                    properties={
                        "label": "Secret merger relation",
                        "review_state": "private_review",
                        "source_observation_ids": ["obs_private"],
                        "source_asset_ids": ["asset_private"],
                    },
                    permission_scope=private_scope,
                )
            ],
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="secret merger decision relation",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_untrusted_view",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=view,
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_reason, "graph_miss_fallback_used")
        self.assertEqual(result.graph_hits, [])
        self.assertEqual(result.visible_graph_snippets, [])
        self.assertEqual(
            result.retrieval_trace.visible_node_ids,
            ["node_public_left", "node_public_right"],
        )
        rendered = json.dumps(result.to_dict(), sort_keys=True).lower()
        for forbidden in (
            "node_private_decision",
            "edge_private_merger",
            "private_source_id",
            "private_review",
            "project_private",
            "obs_private",
            "asset_private",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_observation_asset_lineage_mismatch_forces_fallback_and_no_raw_ref(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-evidence-lineage-mismatch")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_lineage",
                "asset_actual",
                "mail_message",
                "mail",
                {"thread_id": "thread_lineage"},
                "Optoma quotation decision.",
            )
        )
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(_vector("vec_safe_fallback", "obs_safe_fallback"))
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )
        view = _view(
            _concept_node(
                source_observation_ids=["obs_lineage"],
                source_asset_ids=["asset_unrelated"],
            )
        )
        common = {
            "query_embedding": [1.0, 0.0],
            "query_text": "Optoma quotation decision",
            "requester_user_id": "user_pm",
            "workspace_id": "workspace_main",
            "session_id": "session_lineage",
            "now": NOW,
            "effective_graph_view": view,
        }

        evidence_result = gateway.query_effective_graph_view(
            **common,
            mode="evidence_snippet",
        )
        raw_result = gateway.query_effective_graph_view(
            **common,
            mode="raw_asset",
            grants=[_raw_asset_grant()],
        )

        self.assertTrue(evidence_result.fallback_used)
        self.assertEqual(
            evidence_result.fallback_reason,
            "graph_evidence_incomplete_fallback_used",
        )
        self.assertEqual(evidence_result.evidence_coverage, 0.0)
        self.assertEqual(evidence_result.evidence, [])
        self.assertEqual(evidence_result.graph_hits[0]["source_observation_ids"], [])
        self.assertEqual(evidence_result.graph_hits[0]["source_asset_ids"], [])
        self.assertTrue(raw_result.fallback_used)
        self.assertTrue(
            all(item.get("asset_locator") is None for item in raw_result.raw_asset_refs)
        )
        rendered = json.dumps(
            {"evidence": evidence_result.to_dict(), "raw": raw_result.to_dict()},
            sort_keys=True,
        )
        self.assertNotIn("formowl://asset/asset_unrelated", rendered)
        self.assertNotIn("formowl://asset/asset_actual", rendered)

    def test_raw_asset_mode_requires_audit_and_target_scoped_grant(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-raw-audit-scope")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_project_raw",
                "asset_project_raw",
                "work_package_comment",
                "project",
                {"section_id": "work_package_raw"},
                "Optoma quotation decision.",
                permission_scope=PermissionScope.project("project_formowl").to_dict(),
            )
        )
        view = _view(
            GraphProjectionNode(
                **{
                    **_concept_node(
                        source_observation_ids=["obs_project_raw"],
                        source_asset_ids=["asset_project_raw"],
                    ).to_dict(),
                    "permission_scope": PermissionScope.project("project_formowl").to_dict(),
                }
            )
        )
        common = {
            "query_embedding": [1.0, 0.0],
            "query_text": "Optoma quotation decision",
            "requester_user_id": "user_pm",
            "workspace_id": "workspace_main",
            "session_id": "session_raw_scope",
            "mode": "raw_asset",
            "now": NOW,
            "effective_graph_view": view,
            "grants": [
                Grant(
                    grant_id="grant_project_read",
                    owner_user_id="user_owner",
                    grantee_user_id="user_pm",
                    scope_type="project",
                    scope_id="project_formowl",
                    permission="read",
                    expires_at="2026-07-11T00:00:00+00:00",
                ),
                _raw_asset_grant(scope_type="project", scope_id="project_other"),
            ],
        }
        no_audit_gateway = RetrievalGateway(
            vector_store=FileVectorStore(temp_dir),
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
        )
        denied_without_audit = no_audit_gateway.query_effective_graph_view(**common)
        self.assertEqual(denied_without_audit.status, "permission_denied")
        self.assertEqual(
            denied_without_audit.warnings,
            ["raw_asset_mode_requires_audit_store"],
        )

        audit_store = FileAuditLogStore(temp_dir)
        gateway = RetrievalGateway(
            vector_store=FileVectorStore(temp_dir),
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=audit_store,
        )
        denied_wrong_scope = gateway.query_effective_graph_view(**common)
        self.assertEqual(denied_wrong_scope.status, "permission_denied")
        self.assertEqual(denied_wrong_scope.raw_asset_refs, [])
        self.assertEqual(denied_wrong_scope.warnings, ["raw_asset_scope_not_authorized"])
        self.assertEqual(audit_store.list()[-1].action, "retrieval_denied")

        allowed = gateway.query_effective_graph_view(
            **{
                **common,
                "grants": [
                    *common["grants"][:1],
                    _raw_asset_grant(scope_type="project", scope_id="project_formowl"),
                ],
            },
        )
        self.assertEqual(allowed.status, "ok")
        self.assertEqual(
            allowed.raw_asset_refs[0]["asset_locator"],
            "formowl://asset/asset_project_raw",
        )

    def test_relative_internal_paths_are_filtered_from_graph_and_fallback_payloads(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-relative-path-filter")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_relative_path",
                "asset_relative_path",
                "document_block",
                "document",
                {"page_number": 4},
                "path=nas/private/customer.pst",
            )
        )
        vector_store = _FixtureVectorSearchStore(
            _vector(
                "vec_relative_path",
                "obs_missing_fallback",
                metadata={
                    "evidence_snippet": r"(scratch\run-42\payload.txt)",
                    "answer_summary": "locator:object_store/private/payload.bin",
                },
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )
        unsafe_node = _concept_node(
            source_observation_ids=["obs_relative_path"],
            source_asset_ids=["asset_relative_path"],
        )
        unsafe_node = GraphProjectionNode(
            **{
                **unsafe_node.to_dict(),
                "properties": {
                    **unsafe_node.properties,
                    "summary": r"debug,workspace\private\graph.json",
                },
            }
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_relative_path",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(unsafe_node),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_reason, "graph_miss_fallback_used")
        self.assertEqual(result.graph_hits, [])
        rendered = json.dumps(result.to_dict(), sort_keys=True).lower()
        for forbidden in (
            "nas/private",
            r"scratch\\run-42",
            "object_store/private",
            r"workspace\\private",
        ):
            self.assertNotIn(forbidden, rendered)


def _document_recheck_bindings(
    temp_dir: Path, *, filename="notes.md", mime_type="text/markdown",
    query_text="ZX-421 review", grants=None,
):
    """Bind real extracted standalone evidence locally, not a runtime adapter."""
    asset, extraction, store = _extract_document(
        temp_dir, filename=filename, mime_type=mime_type,
        content="# Release notes\n\nZX-421 requires review.\nApproval recorded.\n\nZX-422 remains open.\n",
    )
    grants = [_document_read_grant()] if grants is None else grants
    requester_user_id, workspace_id = "user_pm", "workspace_main"
    snapshot = {
        item.observation_id: sha256_json(store.get(item.observation_id).to_dict())
        for item in extraction.observations
    }
    snapshot_seal = sha256_json(snapshot)
    resolver = ObservationStoreEvidenceResolver(store)
    profile = load_default_mail_candidate_admission_tokenizer_profile()
    query_terms, protected = set(), set()

    def begin(deadline):
        tokenization = profile.analyze(query_text)
        check_source_evidence_deadline(deadline)
        query_terms.update(tokenization.tokens)
        protected.update(span.exact_token for span in tokenization.protected_identifiers)

    def read_source(*, max_observations, deadline_monotonic, observation_callback):
        if asset.workspace_id != workspace_id or not requester_has_graph_access(
            to_plain(asset.permission_scope), requester_user_id=requester_user_id,
            grants=grants, now=NOW,
        ):
            raise PermissionError("document scope denied")
        if (
            sha256_json(snapshot) != snapshot_seal
            or extraction.extractor_run.input_hash != asset.content_hash
        ):
            raise ContractValidationError("document seal mismatch")
        scanned = 0
        for observation_id in snapshot:
            check_source_evidence_deadline(deadline_monotonic)
            if scanned >= max_observations:
                return SourceEvidenceScan((), scanned, False, "observation_limit")
            observation = store.get(observation_id)
            if not requester_has_graph_access(
                to_plain(observation.permission_scope), requester_user_id=requester_user_id,
                grants=grants, now=NOW,
            ):
                raise PermissionError("document Observation denied")
            scanned += 1
            if not observation_callback(observation, asset.asset_id):
                return SourceEvidenceScan((), scanned, False, "callback")
        return SourceEvidenceScan((), scanned, True)

    def project(observation, scope, deadline):
        observation_hash = sha256_json(observation.to_dict())
        if (
            scope != asset.asset_id
            or observation.asset_id != asset.asset_id
            or observation.extractor_run_id != extraction.extractor_run.extractor_run_id
            or observation_hash != snapshot.get(observation.observation_id)
            or observation_hash != sha256_json(store.get(observation.observation_id).to_dict())
        ):
            raise ContractValidationError("document source binding mismatch")
        resolved, unresolved = resolver.resolve(
            [observation.observation_id], requester_user_id=requester_user_id,
            grants=grants, now=NOW,
        )
        if unresolved:
            raise PermissionError("document projection denied")
        tokens = set(profile.analyze(observation.text or "").tokens)
        check_source_evidence_deadline(deadline)
        if not protected.issubset(tokens) or not query_terms.intersection(tokens):
            return None
        return observation_hash, {
            **resolved[0].to_dict(), "source_observation_hash": observation_hash,
            "source_revision": asset.content_hash,
            "extractor_run_id": observation.extractor_run_id,
        }

    return {
        "initial_status": "not_found", "query_class": "evidence_lookup",
        "result_query_class": "evidence_lookup", "initial_warnings": (),
        "verified_evidence_count": 0, "evidence_limit": 1, "sealed_coverage_complete": True,
        "read_source": Mock(side_effect=read_source),
        "project_observation": Mock(side_effect=project), "begin": begin,
    }, asset, extraction, store


def _extract_document(
    temp_dir: Path, *, filename: str, mime_type: str, content: str
) -> tuple[Asset, StoredExtractionResult, ObservationStore]:
    source = temp_dir / filename
    source.write_text(content, encoding="utf-8")
    registry = StorageBackendRegistry(temp_dir)
    backend = registry.register_local_backend(
        temp_dir / "object-store", workspace_scope="workspace_main"
    )
    object_store = FileObjectStore(registry)
    asset = register_asset_from_local_file(
        source,
        object_store=object_store,
        asset_store=AssetStore(temp_dir),
        storage_backend_id=backend.storage_backend_id,
        workspace_id="workspace_main",
        owner_user_id="user_owner",
        permission_scope=PermissionScope.project("project_document"),
        mime_type=mime_type,
        created_at=NOW,
        registered_at=NOW,
    )
    observation_store = ObservationStore(temp_dir)
    extraction = run_extractor(
        asset=asset,
        object_store=object_store,
        extractor_run_store=ExtractorRunStore(temp_dir),
        observation_store=observation_store,
        adapter=PlainTextObservationExtractor(),
        started_at=NOW,
        completed_at=NOW,
    )
    return asset, extraction, observation_store


def _document_read_grant(
    *,
    scope_id: str = "project_document",
    grantee_user_id: str = "user_pm",
    expires_at: str = "2026-07-11T00:00:00+00:00",
) -> Grant:
    return Grant(
        grant_id="grant_document_read",
        owner_user_id="user_owner",
        grantee_user_id=grantee_user_id,
        scope_type="project",
        scope_id=scope_id,
        permission="read",
        expires_at=expires_at,
    )


def _view(node: GraphProjectionNode) -> EffectiveGraphView:
    return EffectiveGraphView(
        requester_user_id="user_pm",
        user_graph_revision_id="ugraph_optoma",
        canonical_graph_revision_id="cgraph_optoma",
        ontology_revision_id="ontology_optoma",
        assembly_policy_id="policy_optoma",
        visible_nodes=[node],
    )


def _concept_node(
    *,
    source_observation_ids: list[str],
    source_asset_ids: list[str],
    confidence: float = 0.91,
) -> GraphProjectionNode:
    return GraphProjectionNode(
        node_id="node_optoma_decision",
        source_type="candidate_frame",
        source_id="cframe_optoma_decision",
        labels=["optoma", "quotation", "decision"],
        properties={
            "object_type": "candidate_decision_frame",
            "label": "Final Optoma quotation decision",
            "summary": "Optoma quotation final decision",
            "confidence": confidence,
            "review_state": "candidate",
            "source_observation_ids": sorted(source_observation_ids),
            "source_asset_ids": sorted(source_asset_ids),
        },
        permission_scope=PUBLIC_SCOPE,
    )


def _observation(
    observation_id: str,
    asset_id: str,
    observation_type: str,
    modality: str,
    location: dict,
    text: str,
    *,
    permission_scope: dict | None = None,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        extractor_run_id=f"run_{observation_id}",
        observation_type=observation_type,
        modality=modality,
        location=location,
        confidence=0.9,
        permission_scope=permission_scope or PUBLIC_SCOPE,
        created_at=NOW,
        asset_id=asset_id,
        text=text,
    )


def _vector(
    vector_id: str,
    source_id: str,
    *,
    metadata: dict | None = None,
) -> VectorRecord:
    return VectorRecord(
        vector_id=vector_id,
        source_type="observation",
        source_id=source_id,
        source_content_hash=f"sha256:{vector_id}",
        embedding_model="fixture-embedding-v1",
        embedding=[1.0, 0.0],
        permission_scope=PUBLIC_SCOPE,
        metadata=metadata or {},
    )


def _raw_asset_grant(
    *,
    scope_type: str = "workspace",
    scope_id: str = "workspace_main",
) -> Grant:
    return Grant(
        grant_id=f"grant_raw_asset_{scope_type}_{scope_id}",
        owner_user_id="user_owner",
        grantee_user_id="user_pm",
        scope_type=scope_type,
        scope_id=scope_id,
        permission="asset_scoped_access",
        expires_at="2026-07-11T00:00:00+00:00",
    )


class _FixtureVectorSearchStore:
    def __init__(self, record: VectorRecord) -> None:
        self.record = record

    def search(self, *args, **kwargs) -> list[VectorSearchResult]:
        return [VectorSearchResult(record=self.record, score=1.0, stale=False)]


if __name__ == "__main__":
    unittest.main()
