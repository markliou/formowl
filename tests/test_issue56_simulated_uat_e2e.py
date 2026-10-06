from __future__ import annotations

from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
import io
import json
import inspect
import math
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from typing import Sequence

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation
from formowl_core import (
    Issue56TargetRuntimeComponents,
    SentenceTransformerDenseEncoder,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_graph.index import GraphProjectionEdge, GraphProjectionNode
from formowl_graph.resolution import (
    resolve_exact_protected_identifier_candidates,
)
from formowl_mail import (
    DEFAULT_SEMANTIC_PLAN_LIMITS,
    ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
    ISSUE56_TARGET_RUNTIME_METHOD_ID,
    build_authorized_semantic_mail_session,
    deterministic_query_class,
    render_governed_evidence_answer,
)
from formowl_mail.answer import _answer_text
from formowl_mail.candidates import (
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
    SourceIdentifierIdentityScope,
    TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    extract_source_bound_identifier_mentions,
)
from scripts.issue56_simulated_uat import (
    ARM_IDS,
    CITATION_PRECISION_MINIMUM_BASIS_POINTS,
    DEFAULT_BUNDLE_PATH,
    DEFAULT_WORK_DIR,
    DIRECT_REGRESSION_MAXIMUM_BASIS_POINTS,
    FULL_CASE_ARM_IDS,
    GRAPH_REQUIRED_GAIN_MINIMUM_BASIS_POINTS,
    PRIVATE_MANIFEST_RELATIVE,
    run_simulated_uat,
)
from scripts import issue56_simulated_uat as simulated_uat_module
from scripts.issue56_operational_budget import (
    FROZEN_CANONICAL_IMAGE_ID,
    FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    INTERNAL_COST_UNITS_PER_CASE_LIMIT,
    OperationalBudgetValidationError,
    ZERO_COST_GENERATION_MODE,
    _internal_cost_check,
    _model_cost_check,
    deterministic_zero_cost_attestation_fingerprint,
)
from scripts.issue56_source_identifier_candidates import (
    CANDIDATE_ARTIFACT_SCHEMA_VERSION as SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
    IDENTITY_SCOPE_POLICY_FINGERPRINT,
    PRIVATE_ARTIFACT_ID as SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
    RESOLUTION_POLICY_FINGERPRINT as SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT,
    RESOLUTION_POLICY_ID as SOURCE_IDENTIFIER_RESOLUTION_POLICY_ID,
)
from scripts.issue56_hybrid_v2_poc import build_poc_inputs
from scripts.issue56_semantic_execution_smoke import (
    ALLOWED_RELATIONS as SEMANTIC_ALLOWED_RELATIONS,
    REQUESTER_USER_ID as SEMANTIC_REQUESTER_USER_ID,
    WORKSPACE_ID as SEMANTIC_WORKSPACE_ID,
    build_semantic_poc_inputs,
)

ROOT = Path(__file__).resolve().parents[1]
PATH_PROOF_REASON_ENUMS = frozenset(
    (
        "bound_candidate_term_support_missing",
        "evidence_budget_rejection",
        "off_path_support",
        "path_property_match",
    )
)


class Issue56SimulatedHumanUatEndToEndTests(unittest.TestCase):
    def test_deterministic_answer_states_preserve_claims_with_bounded_cost(self) -> None:
        cases = (
            {
                "result_status": "permission_denied",
                "citation_count": 0,
                "exact_count": None,
                "answer_status": "permission_denied",
                "required_terms": ("Permission denied", "evidence"),
            },
            {
                "result_status": "no_answer",
                "citation_count": 0,
                "exact_count": None,
                "answer_status": "no_answer",
                "required_terms": ("Insufficient", "authorized evidence", "answer"),
            },
            {
                "result_status": "complete_authorized_scope",
                "citation_count": 7,
                "exact_count": 7,
                "answer_status": "exact_complete",
                "required_terms": ("Complete", "authorized count", "7"),
            },
            {
                "result_status": "complete_authorized_scope",
                "citation_count": 1,
                "exact_count": 0,
                "answer_status": "no_answer",
                "required_terms": ("Complete", "authorized count", "0"),
            },
            {
                "result_status": "complete_authorized_scope",
                "citation_count": 0,
                "exact_count": 7,
                "answer_status": "no_answer",
                "required_terms": ("7", "authorized citations missing", "unverified"),
            },
            {
                "result_status": "incomplete",
                "citation_count": 0,
                "exact_count": 12,
                "answer_status": "exact_incomplete",
                "required_terms": ("Incomplete", "authorized count", "12", "not definitive"),
            },
            {
                "result_status": "ok",
                "citation_count": 8,
                "exact_count": None,
                "answer_status": "answered",
                "required_terms": ("Supported", "8", "authorized citation"),
            },
        )
        for case in cases:
            with self.subTest(
                result_status=case["result_status"],
                exact_count=case["exact_count"],
            ):
                answer_status, answer_text = _answer_text(
                    result_status=case["result_status"],
                    citation_count=case["citation_count"],
                    exact_count=case["exact_count"],
                )
                self.assertEqual(answer_status, case["answer_status"])
                for required_term in case["required_terms"]:
                    self.assertIn(required_term, answer_text)
                self.assertLessEqual(
                    len(answer_text) + (8 * case["citation_count"]),
                    INTERNAL_COST_UNITS_PER_CASE_LIMIT,
                )

    def test_quality_runtime_helpers_are_module_bound(self) -> None:
        for helper_name in (
            "_rows_for_query_class",
            "_rows_for_positive_graph_required",
            "_positive_graph_required_owner_case_count",
            "_validate_external_manifest_seal",
            "_load_native_retrieval_ready_bundle_intake",
            "_load_source_identifier_candidate_intake",
            "_validate_native_mail_evidence_bundle_artifact",
            "_validate_native_retrieval_ready_report",
            "_validate_native_retrieval_ready_cross_binding",
            "_quality_gate_report",
            "_budget_fairness_report",
            "bind_completed_uat_operational_budget",
            "_validated_completed_uat_component_binding",
            "_quality_status_from_checks",
            "_operational_budget_content_fingerprint",
            "_safe_binding_rejection_report",
            "_build_private_relation_phase_trace",
            "_relation_trace_reason",
            "_relation_trace_behavior_fingerprint",
            "_safe_relation_trace_summary",
            "_persist_relation_trace_reports",
        ):
            self.assertTrue(callable(getattr(simulated_uat_module, helper_name)))
            self.assertNotIn(
                helper_name,
                inspect.getclosurevars(simulated_uat_module.run_simulated_uat).unbound,
            )

    def test_external_development_manifest_intake_is_hash_pinned(self) -> None:
        parser = simulated_uat_module._parser()
        args = parser.parse_args(
            [
                "--development-manifest",
                "source-authored.private.json",
                "--expected-development-manifest-sha256",
                "sha256:" + ("a" * 64),
                "--retrieval-ready-bundle-artifact",
                "retrieval-ready-bundle.private.json",
                "--expected-retrieval-ready-bundle-artifact-sha256",
                "sha256:" + ("b" * 64),
                "--retrieval-ready-report",
                "retrieval-ready-report.safe.json",
                "--expected-retrieval-ready-report-sha256",
                "sha256:" + ("c" * 64),
                "--source-identifier-candidate-artifact",
                "source-identifier-candidates.private.json",
                "--expected-source-identifier-candidate-artifact-sha256",
                "sha256:" + ("d" * 64),
                "--expected-identity-scope-fingerprint",
                "sha256:" + ("e" * 64),
            ]
        )
        self.assertEqual(
            args.development_manifest,
            Path("source-authored.private.json"),
        )
        self.assertEqual(
            args.expected_development_manifest_sha256,
            "sha256:" + ("a" * 64),
        )
        self.assertEqual(
            args.retrieval_ready_bundle_artifact,
            Path("retrieval-ready-bundle.private.json"),
        )
        self.assertEqual(
            args.expected_retrieval_ready_bundle_artifact_sha256,
            "sha256:" + ("b" * 64),
        )
        self.assertEqual(
            args.retrieval_ready_report,
            Path("retrieval-ready-report.safe.json"),
        )
        self.assertEqual(
            args.expected_retrieval_ready_report_sha256,
            "sha256:" + ("c" * 64),
        )
        self.assertEqual(
            args.source_identifier_candidate_artifact,
            Path("source-identifier-candidates.private.json"),
        )
        self.assertEqual(
            args.expected_source_identifier_candidate_artifact_sha256,
            "sha256:" + ("d" * 64),
        )
        self.assertEqual(
            args.expected_identity_scope_fingerprint,
            "sha256:" + ("e" * 64),
        )

        actual = simulated_uat_module._sha256_bytes(b"{}")
        simulated_uat_module._validate_external_manifest_seal(actual, actual)
        with self.assertRaisesRegex(
            ContractValidationError,
            "external development manifest seal is invalid",
        ):
            simulated_uat_module._validate_external_manifest_seal(
                actual,
                "not-a-seal",
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "external development manifest seal mismatch",
        ):
            simulated_uat_module._validate_external_manifest_seal(
                actual,
                "sha256:" + ("0" * 64),
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "external development manifest requires retrieval-ready bundle binding",
        ):
            run_simulated_uat(
                work_dir=Path("unused-work-dir"),
                bundle_path=Path("unused-bundle"),
                development_manifest_path=Path("source-authored.private.json"),
                expected_development_manifest_sha256="sha256:" + ("a" * 64),
            )

    def test_native_retrieval_ready_wrapper_intake_binds_report_and_rejects_tamper(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-uat-native-wrapper")
        fixture = _native_retrieval_wrapper_fixture(root)
        intake = simulated_uat_module._load_native_retrieval_ready_bundle_intake(
            bundle_artifact_path=fixture["artifact_path"],
            expected_bundle_artifact_sha256=fixture["artifact_byte_hash"],
            report_path=fixture["report_path"],
            expected_report_sha256=fixture["report_byte_hash"],
        )
        self.assertEqual(
            intake.bundle_payload,
            fixture["artifact"]["bundle"],
        )
        binding = intake.safe_binding
        self.assertEqual(binding["status"], "sealed_passed")
        self.assertEqual(
            binding["bundle_artifact_id"],
            simulated_uat_module.NATIVE_MAIL_EVIDENCE_BUNDLE_ARTIFACT_ID,
        )
        self.assertEqual(
            binding["source_snapshot_fingerprint"],
            fixture["report"]["source_snapshot_fingerprint"],
        )
        self.assertEqual(
            binding["index_fingerprint"],
            fixture["report"]["index_fingerprint"],
        )
        self.assertEqual(
            binding["candidate_admission_profile_fingerprint"],
            load_issue56_target_mail_tokenizer_profile().profile_fingerprint,
        )
        self.assertEqual(
            binding["permission_fingerprint"],
            fixture["report"]["permission_fingerprint"],
        )
        self.assertEqual(
            binding["mail_evidence_bundle_fingerprint"],
            fixture["report"]["mail_evidence_bundle_fingerprint"],
        )
        self.assertEqual(
            binding["retrieval_report_fingerprint"],
            fixture["report"]["report_fingerprint"],
        )
        self.assertRegex(
            binding["input_binding_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )

        base = simulated_uat_module._base_report(
            manifest_byte_hash=simulated_uat_module.sha256_json("synthetic-manifest-seal"),
            bundle_byte_hash=binding["bundle_artifact_byte_hash"],
            case_count=100,
            identity_matches=True,
            selected_observation_count=1,
            runtime_attestation="synthetic_intake_no_quality_run",
            manifest_intake_mode="external_hash_pinned",
            expected_seal_matches=True,
            positive_graph_required_owner_case_count=1,
            source_snapshot_fingerprint=binding["source_snapshot_fingerprint"],
            source_observation_hash_set_fingerprint=(
                simulated_uat_module.sha256_json(["synthetic-observation-hash"])
            ),
            selected_projection_fingerprint=simulated_uat_module.sha256_json(
                "synthetic-selected-projection"
            ),
            retrieval_ready_binding=binding,
            source_identifier_candidate_binding={
                "status": "sealed_passed",
                "binding_fingerprint": simulated_uat_module.sha256_json(
                    "synthetic-source-identifier-binding"
                ),
            },
            canonical_image_id=FROZEN_CANONICAL_IMAGE_ID,
            canonical_image_metadata_fingerprint=(FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
        )
        self.assertEqual(
            base["source"]["retrieval_ready_binding"],
            binding,
        )
        self.assertTrue(base["claim_boundary"]["retrieval_ready_bundle_artifact_bound"])
        self.assertFalse(base["claim_boundary"]["source_complete"])
        self.assertFalse(base["claim_boundary"]["methodology_ready"])
        simulated_uat_module.assert_no_public_raw_references(
            base,
            "issue56_synthetic_native_wrapper_uat_base",
        )

    def test_source_identifier_candidate_intake_is_sealed_projected_and_fail_closed(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-uat-source-identifier-intake")
        observations, bundle, _, _ = build_poc_inputs()
        retrieval_fixture = _native_retrieval_wrapper_fixture(root)
        retrieval_intake = simulated_uat_module._load_native_retrieval_ready_bundle_intake(
            bundle_artifact_path=retrieval_fixture["artifact_path"],
            expected_bundle_artifact_sha256=(retrieval_fixture["artifact_byte_hash"]),
            report_path=retrieval_fixture["report_path"],
            expected_report_sha256=retrieval_fixture["report_byte_hash"],
        )
        candidate_fixture = _source_identifier_candidate_fixture(
            root,
            observations=observations,
            workspace_id=bundle.mail_import_session.workspace_id,
            retrieval_binding=retrieval_intake.safe_binding,
        )
        selected_hashes = {
            observation.observation_id: simulated_uat_module.sha256_json(observation.to_dict())
            for observation in observations
        }
        intake = simulated_uat_module._load_source_identifier_candidate_intake(
            artifact_path=candidate_fixture["artifact_path"],
            expected_artifact_sha256=candidate_fixture["artifact_byte_hash"],
            expected_identity_scope_fingerprint=(candidate_fixture["identity_scope_fingerprint"]),
            expected_workspace_id=bundle.mail_import_session.workspace_id,
            selected_observations_by_id={
                observation.observation_id: observation for observation in observations
            },
            selected_observation_hash_by_id=selected_hashes,
            retrieval_ready_binding=retrieval_intake.safe_binding,
        )
        self.assertEqual(
            intake.projected_batch.occurrence_count,
            candidate_fixture["artifact"]["counts"]["identifier_occurrence_count"],
        )
        self.assertEqual(
            intake.safe_binding["selected_mention_batch_fingerprint"],
            intake.projected_batch.batch_fingerprint,
        )
        self.assertEqual(intake.safe_binding["overflow_count"], 0)
        self.assertTrue(intake.safe_binding["candidate_graph_only"])
        self.assertFalse(intake.safe_binding["canonical_write_allowed"])
        self.assertEqual(
            intake.safe_binding["candidate_artifact_schema_version"],
            SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
        )
        self.assertEqual(
            intake.safe_binding["identity_scope_mode_status"],
            TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
        )
        self.assertEqual(
            intake.safe_binding["identity_scope_fingerprint"],
            candidate_fixture["identity_scope_fingerprint"],
        )
        self.assertEqual(
            intake.safe_binding["relation_type_hashes"],
            sorted(
                simulated_uat_module.sha256_json(value)
                for value in simulated_uat_module.DIAGNOSTIC_RELATION_TYPES
            ),
        )

        tampered = deepcopy(candidate_fixture["artifact"])
        tampered["overflow_count"] = 1
        tampered["artifact_fingerprint"] = simulated_uat_module._payload_fingerprint(
            tampered,
            "artifact_fingerprint",
        )
        tampered_bytes = _serialized_json_bytes(tampered)
        tampered_path = root / "source-identifier-candidates-tampered.private.json"
        tampered_path.write_bytes(tampered_bytes)
        with self.assertRaises(ContractValidationError):
            simulated_uat_module._load_source_identifier_candidate_intake(
                artifact_path=tampered_path,
                expected_artifact_sha256=simulated_uat_module._sha256_bytes(tampered_bytes),
                expected_identity_scope_fingerprint=(
                    candidate_fixture["identity_scope_fingerprint"]
                ),
                expected_workspace_id=bundle.mail_import_session.workspace_id,
                selected_observations_by_id={
                    observation.observation_id: observation for observation in observations
                },
                selected_observation_hash_by_id=selected_hashes,
                retrieval_ready_binding=retrieval_intake.safe_binding,
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "identity scope binding mismatch",
        ):
            simulated_uat_module._load_source_identifier_candidate_intake(
                artifact_path=candidate_fixture["artifact_path"],
                expected_artifact_sha256=candidate_fixture["artifact_byte_hash"],
                expected_identity_scope_fingerprint=(
                    simulated_uat_module.sha256_json("other-tenant-workspace")
                ),
                expected_workspace_id=bundle.mail_import_session.workspace_id,
                selected_observations_by_id={
                    observation.observation_id: observation for observation in observations
                },
                selected_observation_hash_by_id=selected_hashes,
                retrieval_ready_binding=retrieval_intake.safe_binding,
            )
        permission_tampered_observations = {
            observation.observation_id: observation for observation in observations
        }
        permission_target = next(
            observation
            for observation in observations
            if observation.observation_type == "email_body_segment"
        )
        permission_tampered = replace(
            permission_target,
            permission_scope={
                "scope_type": "project",
                "visibility": "restricted",
                "scope_id": "project_issue56_other_permission",
            },
        )
        permission_tampered_observations[permission_tampered.observation_id] = permission_tampered
        permission_tampered_hashes = {
            observation_id: simulated_uat_module.sha256_json(observation.to_dict())
            for observation_id, observation in (permission_tampered_observations.items())
        }
        with self.assertRaises(ContractValidationError):
            simulated_uat_module._load_source_identifier_candidate_intake(
                artifact_path=candidate_fixture["artifact_path"],
                expected_artifact_sha256=candidate_fixture["artifact_byte_hash"],
                expected_identity_scope_fingerprint=(
                    candidate_fixture["identity_scope_fingerprint"]
                ),
                expected_workspace_id=bundle.mail_import_session.workspace_id,
                selected_observations_by_id=(permission_tampered_observations),
                selected_observation_hash_by_id=permission_tampered_hashes,
                retrieval_ready_binding=retrieval_intake.safe_binding,
            )

        workspace_fixture = _source_identifier_candidate_fixture(
            root,
            observations=observations,
            workspace_id=bundle.mail_import_session.workspace_id,
            retrieval_binding=retrieval_intake.safe_binding,
            identity_scope_mode=WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
            artifact_filename="source-identifier-candidates-workspace-only.private.json",
        )
        workspace_intake = simulated_uat_module._load_source_identifier_candidate_intake(
            artifact_path=workspace_fixture["artifact_path"],
            expected_artifact_sha256=workspace_fixture["artifact_byte_hash"],
            expected_identity_scope_fingerprint=workspace_fixture["identity_scope_fingerprint"],
            expected_workspace_id=bundle.mail_import_session.workspace_id,
            selected_observations_by_id={
                observation.observation_id: observation for observation in observations
            },
            selected_observation_hash_by_id=selected_hashes,
            retrieval_ready_binding=retrieval_intake.safe_binding,
        )
        self.assertEqual(
            workspace_intake.projected_batch.identity_scope_mode,
            WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        )
        self.assertIsNone(workspace_intake.projected_batch.tenant_id)
        self.assertNotIn("tenant_id", workspace_intake.safe_binding)
        self.assertRegex(
            workspace_intake.safe_binding["spec_approval_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )

        legacy = deepcopy(candidate_fixture["artifact"])
        legacy["artifact_id"] = "formowl_issue56_source_identifier_candidates_private_v2"
        legacy["schema_version"] = 2
        legacy["artifact_fingerprint"] = simulated_uat_module._payload_fingerprint(
            legacy,
            "artifact_fingerprint",
        )
        legacy_bytes = _serialized_json_bytes(legacy)
        legacy_path = root / "source-identifier-candidates-legacy-v2.private.json"
        legacy_path.write_bytes(legacy_bytes)
        with self.assertRaisesRegex(
            ContractValidationError,
            "artifact v3 identity-scope contract is required",
        ):
            simulated_uat_module._load_source_identifier_candidate_intake(
                artifact_path=legacy_path,
                expected_artifact_sha256=simulated_uat_module._sha256_bytes(legacy_bytes),
                expected_identity_scope_fingerprint=candidate_fixture["identity_scope_fingerprint"],
                expected_workspace_id=bundle.mail_import_session.workspace_id,
                selected_observations_by_id={
                    observation.observation_id: observation for observation in observations
                },
                selected_observation_hash_by_id=selected_hashes,
                retrieval_ready_binding=retrieval_intake.safe_binding,
            )

        tampered_artifact = deepcopy(retrieval_fixture["artifact"])
        tampered_artifact["bundle_fingerprint"] = simulated_uat_module.sha256_json(
            "tampered-bundle-fingerprint"
        )
        tampered_artifact_path = root / "tampered-bundle.private.json"
        tampered_artifact_bytes = _serialized_json_bytes(tampered_artifact)
        tampered_artifact_path.write_bytes(tampered_artifact_bytes)
        with self.assertRaisesRegex(
            ContractValidationError,
            "bundle artifact fingerprint mismatch",
        ):
            simulated_uat_module._load_native_retrieval_ready_bundle_intake(
                bundle_artifact_path=tampered_artifact_path,
                expected_bundle_artifact_sha256=(
                    simulated_uat_module._sha256_bytes(tampered_artifact_bytes)
                ),
                report_path=retrieval_fixture["report_path"],
                expected_report_sha256=retrieval_fixture["report_byte_hash"],
            )

        cross_bound_artifact = deepcopy(retrieval_fixture["artifact"])
        cross_bound_artifact["source_snapshot_fingerprint"] = simulated_uat_module.sha256_json(
            "other-source-snapshot"
        )
        cross_bound_artifact["artifact_fingerprint"] = simulated_uat_module._payload_fingerprint(
            cross_bound_artifact,
            "artifact_fingerprint",
        )
        cross_bound_path = root / "cross-bound-bundle.private.json"
        cross_bound_bytes = _serialized_json_bytes(cross_bound_artifact)
        cross_bound_path.write_bytes(cross_bound_bytes)
        with self.assertRaisesRegex(
            ContractValidationError,
            "artifact and report binding mismatch",
        ):
            simulated_uat_module._load_native_retrieval_ready_bundle_intake(
                bundle_artifact_path=cross_bound_path,
                expected_bundle_artifact_sha256=(
                    simulated_uat_module._sha256_bytes(cross_bound_bytes)
                ),
                report_path=retrieval_fixture["report_path"],
                expected_report_sha256=retrieval_fixture["report_byte_hash"],
            )

        tampered_report = deepcopy(retrieval_fixture["report"])
        tampered_report["permission_fingerprint"] = simulated_uat_module.sha256_json(
            "tampered-permission"
        )
        tampered_report_path = root / "tampered-report.safe.json"
        tampered_report_bytes = _serialized_json_bytes(tampered_report)
        tampered_report_path.write_bytes(tampered_report_bytes)
        with self.assertRaisesRegex(
            ContractValidationError,
            "report fingerprint mismatch",
        ):
            simulated_uat_module._load_native_retrieval_ready_bundle_intake(
                bundle_artifact_path=retrieval_fixture["artifact_path"],
                expected_bundle_artifact_sha256=retrieval_fixture["artifact_byte_hash"],
                report_path=tampered_report_path,
                expected_report_sha256=(simulated_uat_module._sha256_bytes(tampered_report_bytes)),
            )

        with self.assertRaisesRegex(
            ContractValidationError,
            "artifact seal mismatch",
        ):
            simulated_uat_module._load_native_retrieval_ready_bundle_intake(
                bundle_artifact_path=retrieval_fixture["artifact_path"],
                expected_bundle_artifact_sha256=simulated_uat_module.sha256_json("wrong-byte-seal"),
                report_path=retrieval_fixture["report_path"],
                expected_report_sha256=retrieval_fixture["report_byte_hash"],
            )

    def test_positive_graph_gate_excludes_negative_and_denial_cases(self) -> None:
        cases = (
            {
                "query_text": "positive",
                "result_kind": "owner_match",
                "required_source_observation_ids": ["opaque-evidence-ref"],
                "required_match_count": 1,
            },
            {
                "query_text": "negative",
                "result_kind": "no_match",
                "required_source_observation_ids": ["opaque-evidence-ref"],
                "required_match_count": 1,
            },
            {
                "query_text": "denied",
                "result_kind": "permission_denied",
                "required_source_observation_ids": ["opaque-evidence-ref"],
                "required_match_count": 1,
            },
            {
                "query_text": "no-required-evidence",
                "result_kind": "owner_match",
                "required_source_observation_ids": [],
                "required_match_count": 0,
            },
            {
                "query_text": "not-relation",
                "result_kind": "owner_match",
                "required_source_observation_ids": ["opaque-evidence-ref"],
                "required_match_count": 1,
            },
        )
        query_classes = {
            "positive": "relation_reasoning",
            "negative": "relation_reasoning",
            "denied": "relation_reasoning",
            "no-required-evidence": "relation_reasoning",
            "not-relation": "evidence_lookup",
        }
        with patch.object(
            simulated_uat_module,
            "deterministic_query_class",
            side_effect=query_classes.__getitem__,
        ):
            self.assertEqual(
                simulated_uat_module._positive_graph_required_owner_case_count(cases),
                1,
            )

        baseline_rows = (
            {
                "case_manifest_entry_hash": "positive-hash",
                "status": "failed",
                "positive_required_graph_case": True,
            },
            {
                "case_manifest_entry_hash": "negative-hash",
                "status": "failed",
                "positive_required_graph_case": False,
            },
            {
                "case_manifest_entry_hash": "denied-hash",
                "status": "failed",
                "positive_required_graph_case": False,
            },
        )
        candidate_rows = (
            {
                "case_manifest_entry_hash": "positive-hash",
                "status": "passed",
                "positive_required_graph_case": True,
            },
            {
                "case_manifest_entry_hash": "negative-hash",
                "status": "passed",
                "positive_required_graph_case": False,
            },
            {
                "case_manifest_entry_hash": "denied-hash",
                "status": "passed",
                "positive_required_graph_case": False,
            },
        )
        transition = simulated_uat_module._paired_transitions(
            simulated_uat_module._rows_for_positive_graph_required(baseline_rows),
            simulated_uat_module._rows_for_positive_graph_required(candidate_rows),
        )
        self.assertEqual(transition["paired_case_count"], 1)
        self.assertEqual(transition["improved_count"], 1)

    def test_relation_trace_is_hash_only_deterministic_and_behavior_neutral(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-uat-relation-trace")
        hashed_case_id = simulated_uat_module.sha256_json("generalized-case")
        first_row = {
            "hashed_case_id": hashed_case_id,
            "arm_id": "hybrid_v2_soft",
            "query_class": "relation_reasoning",
            "initial_candidate_path_count": 0,
            "strict_proof_status": "failed",
            "required_identifier_slot_count": 2,
            "covered_identifier_slot_count": 2,
            "required_concept_slot_count": 1,
            "covered_concept_slot_count": 0,
            "fallback_invoked": True,
            "targeted_retraversal_invoked": True,
            "repaired_path_count": 1,
            "final_citation_count": 0,
            "no_answer_reason": "fallback_concept_coverage_missing",
            "no_answer_reason_hash": simulated_uat_module.sha256_json(
                "fallback_concept_coverage_missing"
            ),
            "index_lookup_invocation_count": 1,
            "evidence_scoring_invocation_count": 2,
            "graph_traversal_invocation_count": 2,
            "strict_projection_invocation_count": 1,
            "fallback_repair_invocation_count": 1,
            "arm_elapsed_ms": 12.0,
            "answer_projection_elapsed_ms": 0.25,
            "phase_elapsed_ms": {
                "index_lookup": 2.0,
                "evidence_scoring": 3.0,
                "graph_traversal": 4.0,
                "strict_projection": 0.5,
                "fallback_repair": 4.5,
            },
        }
        second_row = deepcopy(first_row)
        second_row["arm_elapsed_ms"] = 99.0
        second_row["answer_projection_elapsed_ms"] = 7.0
        second_row["phase_elapsed_ms"]["graph_traversal"] = 88.0
        self.assertEqual(
            simulated_uat_module._relation_trace_behavior_fingerprint((first_row,)),
            simulated_uat_module._relation_trace_behavior_fingerprint((second_row,)),
        )

        report = {
            "artifact_id": "formowl_issue56_simulated_human_uat_v1",
            "status": "blocked",
            "execution_status": "passed",
            "quality_gate_status": "blocked",
            "arms": {
                "hybrid_v2_soft": {
                    "passed_case_count": 1,
                    "failed_case_count": 0,
                    "citation_count": 2,
                }
            },
            "quality_gate": {
                "status": "blocked",
                "gate_fingerprint": simulated_uat_module.sha256_json("unchanged-quality"),
            },
        }
        before = deepcopy(report)
        private_path = root / "relation-trace.private.json"
        safe_path = root / "relation-trace.safe.json"
        simulated_uat_module._persist_relation_trace_reports(
            report=report,
            private_trace_rows=(first_row,),
            private_report_path=private_path,
            safe_report_path=safe_path,
        )
        self.assertEqual(report, before)

        private_report = json.loads(private_path.read_text(encoding="utf-8"))
        safe_report = json.loads(safe_path.read_text(encoding="utf-8"))
        self.assertEqual(private_report["case_arm_traces"], [first_row])
        self.assertNotIn("case_arm_traces", safe_report)
        self.assertNotIn(hashed_case_id, json.dumps(safe_report, sort_keys=True))
        self.assertEqual(
            safe_report["reason_counts_by_arm"]["hybrid_v2_soft"]["no_answer_reason_counts"],
            {"fallback_concept_coverage_missing": 1},
        )
        self.assertEqual(
            safe_report["latency_distributions_by_arm"]["hybrid_v2_soft"]["graph_traversal"]["p95"],
            4.0,
        )
        simulated_uat_module.assert_no_public_raw_references(
            safe_report,
            "issue56_relation_trace_safe_test",
        )

        profile = load_issue56_target_mail_tokenizer_profile()
        probe = simulated_uat_module._RelationPhaseProbe()
        probe.record(
            phase="index_lookup",
            elapsed_ms=1.0,
            result=(),
        )
        trace = simulated_uat_module._build_private_relation_phase_trace(
            arm_id="rag_entity",
            hashed_case_id=hashed_case_id,
            query_text="PO-123 與交期的關係",
            result=SimpleNamespace(
                warnings=("graph_traversal_ablation_disabled",),
                answer_citation_hashes=(),
                graph_paths=(),
                rejected_hop_count=0,
            ),
            answer_status="no_answer",
            session=SimpleNamespace(
                index=SimpleNamespace(
                    candidates=(),
                    _runtime_components=SimpleNamespace(tokenizer_profile=profile),
                )
            ),
            effective_graph_view=SimpleNamespace(),
            probe=probe,
            arm_elapsed_ms=2.0,
            answer_projection_elapsed_ms=0.1,
        )
        self.assertEqual(trace["strict_proof_status"], "not_executed_graph_disabled")
        self.assertEqual(trace["no_answer_reason"], "graph_traversal_disabled")
        self.assertEqual(trace["index_lookup_invocation_count"], 1)
        self.assertNotIn("PO-123", json.dumps(trace, sort_keys=True))

    def test_path_proof_trace_is_hash_count_only_and_distinguishes_rejections(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-uat-path-proof-trace")
        session, inputs, runtime = _path_proof_session_fixture()
        positive_view = _view_with_complete_path_proof_support(
            inputs.effective_graph_view,
        )
        mismatched_view = _view_with_mismatched_path_proof_support(
            inputs.effective_graph_view,
        )
        off_path_view = _view_with_connected_off_path_proof_support(
            inputs.effective_graph_view,
            term="PO470002004",
            supporting_observation_id="obs_issue56_semantic_current_body_3",
        )
        constrained_limits = replace(
            DEFAULT_SEMANTIC_PLAN_LIMITS,
            max_evidence=2,
        )
        scenarios = (
            (
                "path_property_match",
                positive_view,
                DEFAULT_SEMANTIC_PLAN_LIMITS,
                "ok",
            ),
            (
                "bound_candidate_term_support_missing",
                mismatched_view,
                DEFAULT_SEMANTIC_PLAN_LIMITS,
                "no_answer",
            ),
            (
                "off_path_support",
                off_path_view,
                DEFAULT_SEMANTIC_PLAN_LIMITS,
                "no_answer",
            ),
            (
                "evidence_budget_rejection",
                positive_view,
                constrained_limits,
                "no_answer",
            ),
        )
        query_text = "PO470002004 與 ORIGIN-TAIWAN-01 的供應商資訊關係"
        private_rows: list[dict[str, object]] = []
        source_identifiers = {
            query_text,
            "PO470002004",
            "ORIGIN-TAIWAN-01",
            "node_issue56_po_current",
            "node_issue56_supplier",
            "node_issue56_origin",
            "node_issue56_path_proof_off_path",
            "edge_issue56_path_proof_off_path",
            "obs_issue56_semantic_current_body_1",
            "obs_issue56_semantic_current_body_2",
            "obs_issue56_semantic_current_body_3",
        }
        for ordinal, (expected_reason, view, limits, expected_status) in enumerate(
            scenarios,
            start=1,
        ):
            with self.subTest(reason=expected_reason):
                result, trace = _run_single_path_proof_trace(
                    session=session,
                    runtime=runtime,
                    effective_graph_view=view,
                    query_text=query_text,
                    limits=limits,
                    case_label=f"path-proof-{ordinal}",
                )
                self.assertEqual(result.status, expected_status)
                counts = _unique_path_proof_count_mapping(trace)
                self.assertEqual(frozenset(counts), PATH_PROOF_REASON_ENUMS)
                self.assertTrue(
                    all(
                        isinstance(count, int) and not isinstance(count, bool) and count >= 0
                        for count in counts.values()
                    )
                )
                self.assertGreater(counts[expected_reason], 0)
                self.assertGreater(sum(counts.values()), 0)
                _assert_hash_count_only_path_proof_payload(
                    self,
                    trace,
                    forbidden_values=source_identifiers,
                )
                private_rows.append(trace)

        report = {
            "artifact_id": "formowl_issue56_simulated_human_uat_v1",
            "status": "blocked",
            "execution_status": "passed",
            "quality_gate_status": "blocked",
            "quality_gate": {
                "status": "blocked",
                "gate_fingerprint": simulated_uat_module.sha256_json(
                    "path-proof-quality-unchanged"
                ),
            },
        }
        private_path = root / "path-proof.private.json"
        safe_path = root / "path-proof.safe.json"
        simulated_uat_module._persist_relation_trace_reports(
            report=report,
            private_trace_rows=private_rows,
            private_report_path=private_path,
            safe_report_path=safe_path,
        )
        private_report = json.loads(private_path.read_text(encoding="utf-8"))
        safe_report = json.loads(safe_path.read_text(encoding="utf-8"))

        self.assertEqual(
            set(private_report),
            {
                "artifact_id",
                "behavior_fingerprint",
                "case_arm_traces",
                "claim_boundary",
                "report_fingerprint",
                "schema_version",
                "source_report_fingerprint",
                "status",
            },
        )
        self.assertEqual(private_report["schema_version"], 1)
        self.assertEqual(private_report["status"], "diagnostic")
        self.assertEqual(len(private_report["case_arm_traces"]), len(scenarios))
        self.assertNotIn("case_arm_traces", safe_report)
        self.assertEqual(safe_report["case_arm_trace_count"], len(scenarios))
        self.assertEqual(
            safe_report["behavior_fingerprint"],
            private_report["behavior_fingerprint"],
        )
        self.assertEqual(
            safe_report["source_report_fingerprint"],
            private_report["source_report_fingerprint"],
        )
        self.assertEqual(
            private_report["source_report_fingerprint"],
            simulated_uat_module.sha256_json(report),
        )
        expected_private_fingerprint = simulated_uat_module.sha256_json(
            {key: value for key, value in private_report.items() if key != "report_fingerprint"}
        )
        expected_safe_fingerprint = simulated_uat_module.sha256_json(
            {key: value for key, value in safe_report.items() if key != "report_fingerprint"}
        )
        self.assertEqual(
            private_report["report_fingerprint"],
            expected_private_fingerprint,
        )
        self.assertEqual(safe_report["report_fingerprint"], expected_safe_fingerprint)

        expected_counts: Counter[str] = Counter()
        for row in private_report["case_arm_traces"]:
            expected_counts.update(_unique_path_proof_count_mapping(row))
        public_counts = _unique_path_proof_count_mapping(
            safe_report["reason_counts_by_arm"]["hybrid_v2_soft"]
        )
        self.assertEqual(public_counts, dict(expected_counts))
        self.assertTrue(set(public_counts) <= simulated_uat_module.RELATION_PATH_PROOF_REASON_ENUMS)
        _assert_hash_count_only_path_proof_payload(
            self,
            private_report,
            forbidden_values=source_identifiers,
        )
        _assert_hash_count_only_path_proof_payload(
            self,
            safe_report,
            forbidden_values=source_identifiers,
        )
        simulated_uat_module.assert_no_public_raw_references(
            safe_report,
            "issue56_path_proof_trace_safe_e2e",
        )

    def test_path_proof_instrumentation_does_not_change_hashable_behavior(
        self,
    ) -> None:
        session, inputs, _runtime = _path_proof_session_fixture()
        view = _view_with_complete_path_proof_support(
            inputs.effective_graph_view,
        )
        query_text = "PO470002004 與 ORIGIN-TAIWAN-01 的供應商資訊關係"
        without_trace = simulated_uat_module._run_case_arms(
            session=session,
            effective_graph_view=view,
            query_text=query_text,
            result_limit=5,
            relation_phase_probes=None,
        )
        probes: dict[str, object] = {}
        with_trace = simulated_uat_module._run_case_arms(
            session=session,
            effective_graph_view=view,
            query_text=query_text,
            result_limit=5,
            relation_phase_probes=probes,
        )

        self.assertEqual(
            _hashable_arm_behavior(without_trace),
            _hashable_arm_behavior(with_trace),
        )
        self.assertEqual(
            set(probes),
            {arm_id for arm_id, *_unused in with_trace},
        )
        traced_hybrid = next(
            result for arm_id, result, *_unused in with_trace if arm_id == "hybrid_v2_soft"
        )
        self.assertEqual(traced_hybrid.repair_attempt_count, 1)

    def test_path_proof_diagnostic_preaggregation_scans_graph_once(self) -> None:
        session, inputs, runtime = _path_proof_session_fixture()
        view = _view_with_complete_path_proof_support(
            inputs.effective_graph_view,
        )
        query_text = "PO470002004 與 ORIGIN-TAIWAN-01 的供應商資訊關係"
        result, _trace = _run_single_path_proof_trace(
            session=session,
            runtime=runtime,
            effective_graph_view=view,
            query_text=query_text,
            limits=DEFAULT_SEMANTIC_PLAN_LIMITS,
            case_label="preaggregation-source-path",
        )
        self.assertTrue(result.graph_paths)
        source_path = result.graph_paths[0]
        graph_paths = (
            source_path,
            replace(
                source_path,
                path_hash=simulated_uat_module.sha256_json(
                    {
                        "source_path_hash": source_path.path_hash,
                        "diagnostic_variant": 2,
                    }
                ),
            ),
        )
        candidates_by_hash = {
            candidate.source_observation_hash: candidate for candidate in session.index.candidates
        }
        selection = simulated_uat_module.hybrid_runtime._deterministic_relation_fallback_slots(
            query_text,
            tokenizer_profile=session.index._runtime_components.tokenizer_profile,
            document_frequency=dict(session.index.document_frequency),
            document_count=len(session.index.candidates),
            index_fingerprint=session.index.index_fingerprint,
            graph_revision_fingerprint=str(result.graph_revision_fingerprint),
            effective_graph_view=view,
            authorized_observation_hash_by_id=dict(session.authorized_observation_hashes),
            candidates_by_hash=candidates_by_hash,
        )
        self.assertIsNotNone(selection)
        counted_nodes = _IterationCountingSequence(view.visible_nodes)
        counted_edges = _IterationCountingSequence(view.visible_edges)
        counted_view = SimpleNamespace(
            visible_nodes=counted_nodes,
            visible_edges=counted_edges,
        )

        with (
            patch.object(
                simulated_uat_module,
                "_fallback_node_bound_candidate_slot_coverage",
                wraps=simulated_uat_module._fallback_node_bound_candidate_slot_coverage,
            ) as bound_support,
            patch.object(
                simulated_uat_module,
                "_connected_off_path_nodes",
                wraps=simulated_uat_module._connected_off_path_nodes,
            ) as off_path_scan,
        ):
            diagnostics = simulated_uat_module._fallback_path_proof_diagnostics(
                graph_paths=graph_paths,
                selection=selection,
                effective_graph_view=counted_view,
                authorized_observation_hash_by_id=dict(session.authorized_observation_hashes),
                candidates_by_hash=candidates_by_hash,
                evidence_budget=DEFAULT_SEMANTIC_PLAN_LIMITS.max_evidence,
            )

        self.assertEqual(len(diagnostics), len(graph_paths))
        self.assertEqual(
            bound_support.call_count,
            len(view.visible_nodes),
            "node-bound support must be preaggregated once, not once per path",
        )
        self.assertLessEqual(
            counted_nodes.iteration_count,
            2,
            "path diagnostics must not rescan every visible node for every path",
        )
        self.assertLessEqual(
            counted_edges.iteration_count,
            1,
            "path diagnostics must preaggregate graph adjacency once",
        )
        self.assertLessEqual(
            off_path_scan.call_count,
            1,
            "connected off-path support must not trigger a full edge scan per path",
        )

    def test_diagnostic_subset_cli_is_exact_hash_only_and_behavior_neutral(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-uat-diagnostic-subset")
        fixture = _synthetic_diagnostic_subset_fixture(root)
        selected_hashes = fixture["selected_case_hashes"]
        private_trace_path = root / "selected.private.json"
        safe_trace_path = root / "selected.safe.json"
        parser_args = simulated_uat_module._parser().parse_args(
            [
                "--diagnostic-case-hash",
                selected_hashes[0],
                "--diagnostic-case-hash",
                selected_hashes[1],
            ]
        )
        self.assertEqual(
            tuple(parser_args.diagnostic_case_hashes),
            selected_hashes,
        )

        common = {
            "work_dir": fixture["work_dir"],
            "bundle_path": fixture["bundle_path"],
            "runtime_attestation": "contract_only_diagnostic_subset_test",
            "canonical_image_id": FROZEN_CANONICAL_IMAGE_ID,
            "canonical_image_metadata_fingerprint": (FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
            "diagnostic_case_hashes": selected_hashes,
            "source_identifier_candidate_artifact_path": fixture[
                "source_identifier_candidate_artifact_path"
            ],
            "expected_source_identifier_candidate_artifact_sha256": fixture[
                "source_identifier_candidate_artifact_sha256"
            ],
            "expected_identity_scope_fingerprint": fixture["identity_scope_fingerprint"],
        }
        runtime = _contract_only_runtime()
        with (
            patch(
                "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
                return_value=runtime,
            ),
            patch.object(
                simulated_uat_module,
                "build_authorized_source_backed_effective_graph_view",
                wraps=(simulated_uat_module.build_authorized_source_backed_effective_graph_view),
            ) as graph_builder,
        ):
            without_instrumentation = run_simulated_uat(**common)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = simulated_uat_module.main(
                    [
                        "--work-dir",
                        str(fixture["work_dir"]),
                        "--bundle",
                        str(fixture["bundle_path"]),
                        "--diagnostic-case-hash",
                        selected_hashes[0],
                        "--diagnostic-case-hash",
                        selected_hashes[1],
                        "--private-relation-trace-report",
                        str(private_trace_path),
                        "--safe-relation-trace-report",
                        str(safe_trace_path),
                        "--source-identifier-candidate-artifact",
                        str(fixture["source_identifier_candidate_artifact_path"]),
                        "--expected-source-identifier-candidate-artifact-sha256",
                        str(fixture["source_identifier_candidate_artifact_sha256"]),
                        "--expected-identity-scope-fingerprint",
                        str(fixture["identity_scope_fingerprint"]),
                        "--canonical-image-id",
                        FROZEN_CANONICAL_IMAGE_ID,
                        "--canonical-image-metadata-fingerprint",
                        FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
                        "--allow-blocked",
                    ]
                )
        self.assertGreater(graph_builder.call_count, 0)
        for builder_call in graph_builder.call_args_list:
            self.assertEqual(
                builder_call.kwargs["source_graph_policy_id"],
                simulated_uat_module.SOURCE_GRAPH_POLICY_ID,
            )
            self.assertIsNotNone(builder_call.kwargs["identifier_mention_batch"])
        self.assertEqual(exit_code, 0)
        with_instrumentation = json.loads(stdout.getvalue())
        self.assertEqual(
            without_instrumentation["diagnostic_run_fingerprint"],
            with_instrumentation["diagnostic_run_fingerprint"],
        )
        subset = with_instrumentation["diagnostic_subset"]
        self.assertEqual(subset["status"], "diagnostic_only")
        self.assertEqual(subset["selection_basis"], "exact_private_manifest_entry_hash")
        self.assertEqual(subset["manifest_case_count"], 100)
        self.assertEqual(subset["selected_case_count"], len(selected_hashes))
        self.assertEqual(subset["selected_case_hash_count"], len(selected_hashes))
        self.assertEqual(
            subset["selected_case_hash_set_fingerprint"],
            simulated_uat_module.sha256_json(sorted(selected_hashes)),
        )
        self.assertFalse(subset["quality_claim_eligible"])
        self.assertFalse(subset["operational_budget_binding_eligible"])
        self.assertEqual(with_instrumentation["status"], "blocked")
        self.assertEqual(with_instrumentation["execution_status"], "passed")
        self.assertEqual(with_instrumentation["quality_gate_status"], "blocked")
        self.assertEqual(with_instrumentation["quality_gate"]["status"], "blocked")
        self.assertFalse(
            with_instrumentation["claim_boundary"]["supports_same_pipeline_diagnostic_claim"]
        )
        self.assertFalse(with_instrumentation["claim_boundary"]["supports_arm_superiority_claim"])
        graph_builds = with_instrumentation["shared_pipeline"]["graph_builds"]
        self.assertEqual(
            graph_builds["source_graph_policy_fingerprint"],
            simulated_uat_module.sha256_json(simulated_uat_module.SOURCE_GRAPH_POLICY_ID),
        )
        self.assertEqual(
            graph_builds["relation_type_hashes"],
            sorted(
                simulated_uat_module.sha256_json(value)
                for value in simulated_uat_module.DIAGNOSTIC_RELATION_TYPES
            ),
        )
        self.assertEqual(
            graph_builds["identifier_mention_count"],
            with_instrumentation["source"]["source_identifier_candidate_binding"][
                "selected_mention_count"
            ],
        )
        self.assertEqual(
            with_instrumentation["source"]["case_count"],
            len(selected_hashes),
        )
        for arm_id in FULL_CASE_ARM_IDS:
            self.assertEqual(
                with_instrumentation["arms"][arm_id]["scored_case_count"],
                len(selected_hashes),
            )
        self.assertEqual(
            with_instrumentation["arms"]["structured_exact"]["scored_case_count"],
            0,
        )

        private_trace = json.loads(private_trace_path.read_text(encoding="utf-8"))
        safe_trace = json.loads(safe_trace_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {row["hashed_case_id"] for row in private_trace["case_arm_traces"]},
            set(selected_hashes),
        )
        self.assertEqual(
            len(private_trace["case_arm_traces"]),
            len(selected_hashes) * len(FULL_CASE_ARM_IDS),
        )
        self.assertEqual(
            safe_trace["case_arm_trace_count"],
            len(private_trace["case_arm_traces"]),
        )
        safe_serialized = json.dumps(
            {
                "report": with_instrumentation,
                "safe_trace": safe_trace,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        private_trace_serialized = json.dumps(
            private_trace,
            ensure_ascii=False,
            sort_keys=True,
        )
        for forbidden in (
            *fixture["query_texts"],
            *fixture["case_ids"],
            *fixture["observation_ids"],
        ):
            self.assertNotIn(forbidden, safe_serialized)
            self.assertNotIn(forbidden, private_trace_serialized)
        for selected_hash in selected_hashes:
            self.assertNotIn(selected_hash, json.dumps(safe_trace, sort_keys=True))
        simulated_uat_module.assert_no_public_raw_references(
            with_instrumentation,
            "issue56_diagnostic_subset_safe_report",
        )
        simulated_uat_module.assert_no_public_raw_references(
            safe_trace,
            "issue56_diagnostic_subset_safe_trace",
        )

    def test_diagnostic_subset_missing_or_unknown_hash_fails_before_execution(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-uat-diagnostic-subset-rejection")
        fixture = _synthetic_diagnostic_subset_fixture(root)
        parser = simulated_uat_module._parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--diagnostic-case-hash"])

        invalid_hashes = (
            "not-a-sha256",
            simulated_uat_module.sha256_json("unknown-development-case"),
        )
        for invalid_hash in invalid_hashes:
            with self.subTest(invalid_hash=invalid_hash):
                stdout = io.StringIO()
                with (
                    patch.object(
                        simulated_uat_module,
                        "_run_case_arms",
                        side_effect=AssertionError(
                            "invalid subset selection reached UAT execution"
                        ),
                    ),
                    redirect_stdout(stdout),
                ):
                    exit_code = simulated_uat_module.main(
                        [
                            "--work-dir",
                            str(fixture["work_dir"]),
                            "--bundle",
                            str(fixture["bundle_path"]),
                            "--diagnostic-case-hash",
                            invalid_hash,
                            "--source-identifier-candidate-artifact",
                            str(fixture["source_identifier_candidate_artifact_path"]),
                            "--expected-source-identifier-candidate-artifact-sha256",
                            str(fixture["source_identifier_candidate_artifact_sha256"]),
                            "--expected-identity-scope-fingerprint",
                            str(fixture["identity_scope_fingerprint"]),
                            "--canonical-image-id",
                            FROZEN_CANONICAL_IMAGE_ID,
                            "--canonical-image-metadata-fingerprint",
                            FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
                        ]
                    )
                self.assertEqual(exit_code, 3)
                rejection = json.loads(stdout.getvalue())
                self.assertEqual(rejection["status"], "blocked")
                self.assertFalse(rejection["e2e_executed"])
                self.assertNotIn(invalid_hash, stdout.getvalue())
                simulated_uat_module.assert_no_public_raw_references(
                    rejection,
                    "issue56_diagnostic_subset_rejection",
                )

    def test_diagnostic_subset_report_cannot_bind_operational_budget(self) -> None:
        root = _paths.fresh_test_dir("issue56-uat-subset-budget-rejection")
        fixture = _completed_uat_budget_binding_fixture(root)
        report = deepcopy(fixture["report"])
        report["diagnostic_subset"] = {
            "status": "diagnostic_only",
            "selection_basis": "exact_private_manifest_entry_hash",
            "manifest_case_count": 100,
            "selected_case_count": 2,
            "selected_case_hash_count": 2,
            "selected_case_hash_set_fingerprint": simulated_uat_module.sha256_json(
                [
                    simulated_uat_module.sha256_json("case-1"),
                    simulated_uat_module.sha256_json("case-2"),
                ]
            ),
            "quality_claim_eligible": False,
            "operational_budget_binding_eligible": False,
        }
        report["claim_boundary"]["supports_same_pipeline_diagnostic_claim"] = False
        subset_report_bytes = _serialized_json_bytes(report)
        subset_report_path = root / "diagnostic-subset.safe.json"
        subset_report_path.write_bytes(subset_report_bytes)

        budget = deepcopy(fixture["budget"])
        budget["uat_report_fingerprint"] = simulated_uat_module._sha256_bytes(subset_report_bytes)
        budget["uat_content_fingerprint"] = (
            simulated_uat_module._operational_budget_content_fingerprint(report)
        )
        budget["uat_run_fingerprint"] = report["diagnostic_run_fingerprint"]
        budget["bundle_fingerprint"] = simulated_uat_module.sha256_json(
            {key: value for key, value in budget.items() if key != "bundle_fingerprint"}
        )
        budget_bytes = _serialized_json_bytes(budget)
        budget_path = root / "diagnostic-subset-budget.bundle.json"
        budget_path.write_bytes(budget_bytes)

        with self.assertRaisesRegex(
            ContractValidationError,
            "diagnostic subset",
        ):
            simulated_uat_module.bind_completed_uat_operational_budget(
                completed_report_path=subset_report_path,
                expected_completed_report_sha256=simulated_uat_module._sha256_bytes(
                    subset_report_bytes
                ),
                operational_budget_bundle_path=budget_path,
                expected_operational_budget_bundle_sha256=(
                    simulated_uat_module._sha256_bytes(budget_bytes)
                ),
            )

    def test_external_positive_graph_manifest_real_e5_intake(self) -> None:
        manifest_value = os.environ.get("FORMOWL_ISSUE56_SOURCE_AUTHORED_DEVELOPMENT_MANIFEST")
        manifest_sha256 = os.environ.get(
            "FORMOWL_ISSUE56_SOURCE_AUTHORED_DEVELOPMENT_MANIFEST_SHA256"
        )
        bundle_artifact_value = os.environ.get("FORMOWL_ISSUE56_RETRIEVAL_READY_BUNDLE_ARTIFACT")
        bundle_artifact_sha256 = os.environ.get(
            "FORMOWL_ISSUE56_RETRIEVAL_READY_BUNDLE_ARTIFACT_SHA256"
        )
        retrieval_report_value = os.environ.get("FORMOWL_ISSUE56_RETRIEVAL_READY_REPORT")
        retrieval_report_sha256 = os.environ.get("FORMOWL_ISSUE56_RETRIEVAL_READY_REPORT_SHA256")
        candidate_artifact_value = os.environ.get(
            "FORMOWL_ISSUE56_SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT"
        )
        candidate_artifact_sha256 = os.environ.get(
            "FORMOWL_ISSUE56_SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_SHA256"
        )
        identity_scope_fingerprint = os.environ.get("FORMOWL_ISSUE56_IDENTITY_SCOPE_FINGERPRINT")
        external_values = (
            manifest_value,
            manifest_sha256,
            bundle_artifact_value,
            bundle_artifact_sha256,
            retrieval_report_value,
            retrieval_report_sha256,
            candidate_artifact_value,
            candidate_artifact_sha256,
            identity_scope_fingerprint,
        )
        if all(value is None for value in external_values):
            self.skipTest("external source-authored development manifest unavailable")
        if any(value is None for value in external_values):
            self.fail(
                "external development manifest and retrieval-ready artifact/report "
                "plus source identifier candidate artifact bindings must be "
                "supplied together"
            )
        work_dir = Path(
            os.environ.get(
                "FORMOWL_ISSUE56_DEVELOPMENT_WORK_DIR",
                str(DEFAULT_WORK_DIR),
            )
        )
        bundle_path = Path(
            os.environ.get(
                "FORMOWL_ISSUE56_DEVELOPMENT_BUNDLE",
                str(DEFAULT_BUNDLE_PATH),
            )
        )
        report = run_simulated_uat(
            work_dir=work_dir,
            bundle_path=bundle_path,
            development_manifest_path=Path(manifest_value),
            expected_development_manifest_sha256=manifest_sha256,
            retrieval_ready_bundle_artifact_path=Path(bundle_artifact_value),
            expected_retrieval_ready_bundle_artifact_sha256=(bundle_artifact_sha256),
            retrieval_ready_report_path=Path(retrieval_report_value),
            expected_retrieval_ready_report_sha256=retrieval_report_sha256,
            source_identifier_candidate_artifact_path=Path(candidate_artifact_value),
            expected_source_identifier_candidate_artifact_sha256=(candidate_artifact_sha256),
            expected_identity_scope_fingerprint=(identity_scope_fingerprint),
            canonical_image_id=FROZEN_CANONICAL_IMAGE_ID,
            canonical_image_metadata_fingerprint=(FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
        )
        self.assertEqual(report["execution_status"], "passed")
        seal = report["manifest_seal"]
        self.assertEqual(seal["intake_mode"], "external_hash_pinned")
        self.assertTrue(seal["expected_seal_matches"])
        self.assertTrue(seal["unchanged_after_execution"])
        self.assertGreater(
            seal["positive_graph_required_owner_case_count"],
            0,
        )
        runtime_positive_count = report["arms"]["hybrid_v2_soft"]["path_metrics"][
            "positive_required_case_count"
        ]
        self.assertGreater(runtime_positive_count, 0)
        self.assertEqual(
            report["paired_transitions"]["hybrid_v2_soft_vs_strong_rag_graph_required"][
                "paired_case_count"
            ],
            runtime_positive_count,
        )

    def test_preserved_real_source_100_case_same_pipeline_diagnostic(self) -> None:
        manifest_path = DEFAULT_WORK_DIR / PRIVATE_MANIFEST_RELATIVE
        candidate_artifact_value = os.environ.get(
            "FORMOWL_ISSUE56_SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT"
        )
        candidate_artifact_sha256 = os.environ.get(
            "FORMOWL_ISSUE56_SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_SHA256"
        )
        identity_scope_fingerprint = os.environ.get("FORMOWL_ISSUE56_IDENTITY_SCOPE_FINGERPRINT")
        if (
            not manifest_path.exists()
            or not DEFAULT_BUNDLE_PATH.exists()
            or not all(
                (
                    candidate_artifact_value,
                    candidate_artifact_sha256,
                    identity_scope_fingerprint,
                )
            )
        ):
            self.skipTest("operator-authorized preserved diagnostic artifacts unavailable")
        trace_root = _paths.fresh_test_dir("issue56-uat-relation-trace-e2e")
        private_trace_path = trace_root / "relation-trace.private.json"
        safe_trace_path = trace_root / "relation-trace.safe.json"
        runtime = _contract_only_runtime()
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime,
        ):
            report = run_simulated_uat(
                work_dir=DEFAULT_WORK_DIR,
                bundle_path=DEFAULT_BUNDLE_PATH,
                runtime_attestation=("contract_only_test_double_not_real_e5_evidence"),
                source_identifier_candidate_artifact_path=Path(candidate_artifact_value),
                expected_source_identifier_candidate_artifact_sha256=(candidate_artifact_sha256),
                expected_identity_scope_fingerprint=(identity_scope_fingerprint),
                canonical_image_id=FROZEN_CANONICAL_IMAGE_ID,
                canonical_image_metadata_fingerprint=(FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
                private_relation_trace_report_path=private_trace_path,
                safe_relation_trace_report_path=safe_trace_path,
            )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["execution_status"], "passed")
        self.assertEqual(report["quality_gate_status"], "blocked")
        self.assertTrue(report["e2e_executed"])
        self.assertEqual(
            report["diagnostic_label"],
            "diagnostic_same_pipeline_not_independent_holdout",
        )
        self.assertEqual(report["source"]["case_count"], 100)
        self.assertTrue(report["source"]["manifest_bundle_identity_matches"])
        self.assertGreater(report["source"]["loaded_observation_count"], 0)
        self.assertEqual(
            report["source"]["loaded_observation_count"],
            report["source"]["source_observation_hash_count"],
        )
        self.assertRegex(
            report["source"]["source_snapshot_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(
            report["source"]["source_observation_hash_set_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertTrue(report["manifest_seal"]["sealed_before_execution"])
        self.assertTrue(report["manifest_seal"]["unchanged_after_execution"])
        self.assertEqual(
            report["manifest_seal"]["intake_mode"],
            "default_bound_manifest",
        )
        self.assertTrue(report["manifest_seal"]["expected_seal_matches"])
        self.assertEqual(set(report["arms"]), set(ARM_IDS))
        for arm_id in FULL_CASE_ARM_IDS:
            arm = report["arms"][arm_id]
            self.assertEqual(arm["scored_case_count"], 100)
            self.assertEqual(
                arm["passed_case_count"] + arm["failed_case_count"],
                100,
            )
            self.assertIn("citation_count", arm)
            self.assertIn("permission_denial_passed_count", arm)
            self.assertIn("no_answer_passed_count", arm)
            self.assertIn("exact_complete_answer_count", arm)
            self.assertIn("latency_ms", arm)
            self.assertIn("cost_units", arm)
            self.assertIsInstance(arm["cost_units"]["maximum"], int)
            self.assertGreaterEqual(arm["cost_units"]["maximum"], 0)
            self.assertLessEqual(
                arm["cost_units"]["maximum"],
                arm["cost_units"]["total"],
            )
        private_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        exact_case_count = sum(
            deterministic_query_class(str(case["query_text"])) == "exact_set_or_inventory"
            for case in private_manifest["cases"]
        )
        positive_required_graph_case_count = sum(
            deterministic_query_class(str(case["query_text"])) == "relation_reasoning"
            and case["result_kind"] == "owner_match"
            and bool(case["required_source_observation_ids"])
            for case in private_manifest["cases"]
        )
        routed_case_counts = {
            query_class: sum(
                deterministic_query_class(str(case["query_text"])) == query_class
                for case in private_manifest["cases"]
            )
            for query_class in (
                "evidence_lookup",
                "relation_reasoning",
            )
        }
        structured_exact = report["arms"]["structured_exact"]
        self.assertEqual(structured_exact["scored_case_count"], exact_case_count)
        self.assertEqual(
            structured_exact["passed_case_count"] + structured_exact["failed_case_count"],
            exact_case_count,
        )
        for transition_id, transition in report["paired_transitions"].items():
            if transition_id == "structured_exact_vs_strong_rag_exact_cases":
                expected_count = exact_case_count
            elif transition_id == "hybrid_v2_soft_vs_strong_rag_direct_cases":
                expected_count = routed_case_counts["evidence_lookup"]
            elif transition_id == "hybrid_v2_soft_vs_strong_rag_graph_required":
                expected_count = positive_required_graph_case_count
            else:
                expected_count = 100
            self.assertEqual(transition["paired_case_count"], expected_count)
            self.assertEqual(
                transition["improved_count"]
                + transition["regressed_count"]
                + transition["unchanged_pass_count"]
                + transition["unchanged_fail_count"],
                expected_count,
            )
        self.assertTrue(
            report["shared_pipeline"]["all_arms_share_answer_model_prompt_budget_evaluator"]
        )
        shared_pipeline = report["shared_pipeline"]
        self.assertEqual(
            shared_pipeline["lexical_profile_fingerprint"],
            load_issue56_target_mail_tokenizer_profile().profile_fingerprint,
        )
        self.assertEqual(
            shared_pipeline["query_lexical_profile_fingerprint"],
            shared_pipeline["lexical_profile_fingerprint"],
        )
        self.assertEqual(
            shared_pipeline["evidence_lexical_profile_fingerprint"],
            shared_pipeline["lexical_profile_fingerprint"],
        )
        self.assertEqual(
            shared_pipeline["runtime_method_id"],
            ISSUE56_TARGET_RUNTIME_METHOD_ID,
        )
        self.assertEqual(
            shared_pipeline["runtime_method_fingerprint"],
            ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        )
        self.assertEqual(
            shared_pipeline["execution_component_fingerprint_count"],
            1,
        )
        self.assertEqual(
            shared_pipeline["execution_component_fingerprint_set_hash"],
            simulated_uat_module.sha256_json([shared_pipeline["execution_component_fingerprint"]]),
        )
        execution_environment = report["execution_environment"]
        self.assertEqual(
            execution_environment["image_id"],
            FROZEN_CANONICAL_IMAGE_ID,
        )
        self.assertEqual(
            execution_environment["image_metadata_fingerprint"],
            FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
        )
        self.assertRegex(
            execution_environment["code_tree_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(
            execution_environment["authority_execution_fingerprint"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            execution_environment["source_completeness_gate_status"],
            "blocked",
        )
        self.assertEqual(
            execution_environment["real_source_ablation_gate_status"],
            "blocked",
        )
        self.assertEqual(
            execution_environment["methodology_ready_status"],
            "blocked",
        )
        budget_fairness = report["shared_pipeline"]["execution_budget_fairness"]
        self.assertTrue(budget_fairness["all_full_case_arms_match_per_case"])
        self.assertTrue(budget_fairness["structured_exact_matches_routed_cases"])
        full_arm_budget_set_hashes = {
            budget_fairness["per_arm_fingerprint_set_hashes"][arm_id]
            for arm_id in FULL_CASE_ARM_IDS
        }
        self.assertEqual(len(full_arm_budget_set_hashes), 1)
        self.assertEqual(
            quality_checks := report["quality_gate"]["checks"],
            report["quality_gate"]["checks"],
        )
        self.assertEqual(
            quality_checks["execution_budget_fairness"]["status"],
            "passed",
        )
        self.assertTrue(report["shared_pipeline"]["graph_signal_active"])
        self.assertTrue(report["shared_pipeline"]["ontology_signal_active"])
        shared_lineage = report["shared_pipeline"]["evidence_identity_lineage"]
        self.assertGreater(shared_lineage["authorized_evidence_count"], 0)
        self.assertGreater(shared_lineage["indexed_evidence_count"], 0)
        self.assertEqual(
            shared_lineage["indexed_evidence_count"],
            shared_lineage["occurrence_bound_evidence_count"],
        )
        self.assertTrue(shared_lineage["hash_only"])
        self.assertFalse(shared_lineage["adjudication_input"])
        for arm in report["arms"].values():
            lineage = arm["evidence_identity_lineage"]
            self.assertEqual(lineage["unresolved_runtime_count"], 0)
            self.assertLessEqual(
                lineage["final_citation_count"],
                lineage["required_evidence_count"],
            )
        direct_check = quality_checks["direct_regression"]
        self.assertEqual(
            direct_check["maximum_regression_basis_points"],
            DIRECT_REGRESSION_MAXIMUM_BASIS_POINTS,
        )
        self.assertEqual(
            direct_check["measured_delta_basis_points"],
            report["paired_transitions"]["hybrid_v2_soft_vs_strong_rag_direct_cases"][
                "paired_correctness_delta_basis_points"
            ],
        )
        graph_check = quality_checks["graph_required_gain"]
        self.assertEqual(
            graph_check["minimum_gain_basis_points"],
            GRAPH_REQUIRED_GAIN_MINIMUM_BASIS_POINTS,
        )
        self.assertEqual(
            graph_check["paired_ci_95_basis_points"],
            report["paired_transitions"]["hybrid_v2_soft_vs_strong_rag_graph_required"][
                "paired_ci_95_basis_points"
            ],
        )
        self.assertEqual(
            graph_check["positive_required_case_count"],
            positive_required_graph_case_count,
        )
        positive_graph_check = quality_checks["graph_required_positive_evidence"]
        self.assertEqual(
            positive_graph_check["positive_required_case_count"],
            positive_required_graph_case_count,
        )
        if positive_required_graph_case_count:
            self.assertNotEqual(positive_graph_check["status"], "blocked")
        else:
            self.assertEqual(positive_graph_check["status"], "blocked")
            self.assertEqual(graph_check["status"], "blocked")
        citation_check = quality_checks["citation_precision"]
        self.assertEqual(
            citation_check["minimum_basis_points"],
            CITATION_PRECISION_MINIMUM_BASIS_POINTS,
        )
        self.assertEqual(
            citation_check["measured_basis_points"],
            report["arms"]["hybrid_v2_soft"]["citation_metrics"]["precision_basis_points"],
        )
        permission_check = quality_checks["permission_leakage"]
        self.assertEqual(permission_check["cross_scope_match_count"], 0)
        self.assertEqual(
            permission_check["denial_passed_count"],
            permission_check["denial_case_count"],
        )
        graph_hop_check = quality_checks["graph_hop_evidence"]
        self.assertGreater(graph_hop_check["hop_count"], 0)
        self.assertEqual(
            graph_hop_check["authorized_evidence_hop_count"],
            graph_hop_check["hop_count"],
        )
        self.assertEqual(
            graph_hop_check["unresolved_evidence_hop_count"],
            0,
        )
        no_answer_check = quality_checks["no_answer_non_regression"]
        self.assertEqual(
            no_answer_check["baseline_true_positive_count"],
            report["arms"]["strong_rag"]["no_answer_metrics"]["true_positive_count"],
        )
        self.assertEqual(
            no_answer_check["candidate_true_positive_count"],
            report["arms"]["hybrid_v2_soft"]["no_answer_metrics"]["true_positive_count"],
        )
        operational_check = quality_checks["operational_budget"]
        self.assertEqual(operational_check["status"], "blocked")
        self.assertFalse(operational_check["latency_budget_frozen"])
        self.assertFalse(operational_check["cost_budget_frozen"])
        usage = report["resource_measurement"]["model_usage_cost"]
        self.assertEqual(usage["status"], "zero_cost_attested")
        self.assertEqual(
            usage["generation_mode"],
            ZERO_COST_GENERATION_MODE,
        )
        self.assertEqual(usage["external_generation_call_count"], 0)
        self.assertEqual(usage["input_token_count"], 0)
        self.assertEqual(usage["output_token_count"], 0)
        self.assertEqual(usage["monetary_cost_microusd"], 0)
        self.assertEqual(
            usage["attestation_fingerprint"],
            deterministic_zero_cost_attestation_fingerprint(),
        )
        self.assertEqual(
            _model_cost_check(
                resource_measurement=report["resource_measurement"],
                shared_pipeline=report["shared_pipeline"],
            )["status"],
            "passed",
        )
        self.assertIn(
            _internal_cost_check(report["arms"]["hybrid_v2_soft"])["status"],
            {"passed", "failed"},
        )
        self.assertFalse(report["claim_boundary"]["independent_holdout"])
        self.assertFalse(report["claim_boundary"]["real_source_authority_gate_passed"])
        self.assertFalse(report["claim_boundary"]["methodology_complete"])
        self.assertFalse(report["claim_boundary"]["issue56_complete"])
        self.assertFalse(report["claim_boundary"]["production_ready"])
        self.assertFalse(report["claim_boundary"]["supports_arm_superiority_claim"])
        self.assertTrue(report["claim_boundary"]["supports_same_pipeline_diagnostic_claim"])
        relation_trace = report["relation_phase_trace"]
        expected_trace_count = sum(arm["scored_case_count"] for arm in report["arms"].values())
        self.assertEqual(
            relation_trace["private_case_arm_trace_count"],
            expected_trace_count,
        )
        private_trace = json.loads(private_trace_path.read_text(encoding="utf-8"))
        safe_trace = json.loads(safe_trace_path.read_text(encoding="utf-8"))
        self.assertEqual(len(private_trace["case_arm_traces"]), expected_trace_count)
        self.assertNotIn("case_arm_traces", safe_trace)
        self.assertEqual(
            safe_trace["behavior_fingerprint"],
            relation_trace["behavior_fingerprint"],
        )
        self.assertEqual(
            safe_trace["summary_fingerprint"],
            relation_trace["safe_summary_fingerprint"],
        )
        simulated_uat_module.assert_no_public_raw_references(
            safe_trace,
            "issue56_relation_trace_safe_e2e",
        )

        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        for case in private_manifest["cases"]:
            self.assertNotIn(case["query_text"], serialized)
            self.assertNotIn(case["case_id"], serialized)
            for field_name in (
                "required_source_observation_ids",
                "forbidden_source_observation_ids",
            ):
                for observation_id in case[field_name]:
                    self.assertNotIn(observation_id, serialized)
        self.assertNotIn(str(DEFAULT_WORK_DIR), serialized)
        self.assertNotIn(str(DEFAULT_BUNDLE_PATH), serialized)
        simulated_uat_module._assert_safe_simulated_uat_report(report)

    def test_operational_measurement_tamper_and_missing_fail_closed(self) -> None:
        report = {
            "resource_measurement": {
                "model_usage_cost": (simulated_uat_module._deterministic_zero_cost_measurement())
            }
        }
        simulated_uat_module._assert_safe_simulated_uat_report(report)

        tampered_usage = deepcopy(report)
        tampered_usage["resource_measurement"]["model_usage_cost"][
            "external_generation_call_count"
        ] = 1
        with self.assertRaises(ContractValidationError):
            simulated_uat_module._assert_safe_simulated_uat_report(tampered_usage)
        with self.assertRaises(OperationalBudgetValidationError):
            _model_cost_check(
                resource_measurement=tampered_usage["resource_measurement"],
                shared_pipeline={
                    "answer_model_id": (simulated_uat_module.ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID)
                },
            )

        missing_attestation = deepcopy(report)
        del missing_attestation["resource_measurement"]["model_usage_cost"][
            "attestation_fingerprint"
        ]
        with self.assertRaises(ContractValidationError):
            simulated_uat_module._assert_safe_simulated_uat_report(missing_attestation)
        with self.assertRaises(OperationalBudgetValidationError):
            _model_cost_check(
                resource_measurement=missing_attestation["resource_measurement"],
                shared_pipeline={
                    "answer_model_id": (simulated_uat_module.ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID)
                },
            )

        valid_cost = {
            "scored_case_count": 2,
            "cost_units": {
                "total": 101,
                "average_milli": 50_500,
                "maximum": 100,
            },
        }
        self.assertEqual(_internal_cost_check(valid_cost)["status"], "passed")

        missing_maximum = deepcopy(valid_cost)
        del missing_maximum["cost_units"]["maximum"]
        self.assertEqual(
            _internal_cost_check(missing_maximum)["status"],
            "blocked",
        )

        tampered_maximum = deepcopy(valid_cost)
        tampered_maximum["cost_units"]["maximum"] = INTERNAL_COST_UNITS_PER_CASE_LIMIT + 1
        self.assertEqual(
            _internal_cost_check(tampered_maximum)["status"],
            "failed",
        )

    def test_completed_uat_operational_budget_binding_and_tamper_fail_closed(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-uat-operational-binding")
        fixture = _completed_uat_budget_binding_fixture(root)

        bound = simulated_uat_module.bind_completed_uat_operational_budget(
            completed_report_path=fixture["report_path"],
            expected_completed_report_sha256=fixture["report_byte_hash"],
            operational_budget_bundle_path=fixture["budget_path"],
            expected_operational_budget_bundle_sha256=fixture["budget_byte_hash"],
        )

        self.assertEqual(
            bound["quality_gate"]["checks"]["operational_budget"]["status"],
            "passed",
        )
        self.assertEqual(
            bound["quality_gate"]["checks"]["source_authority_prerequisites"]["status"],
            "blocked",
        )
        self.assertEqual(bound["quality_gate_status"], "blocked")
        self.assertEqual(bound["status"], "blocked")
        self.assertEqual(
            bound["diagnostic_run_fingerprint"],
            fixture["report"]["diagnostic_run_fingerprint"],
        )
        binding = bound["operational_budget_binding"]
        self.assertTrue(binding["projection_only"])
        self.assertEqual(
            binding["completed_report_byte_hash"],
            fixture["report_byte_hash"],
        )
        self.assertEqual(
            binding["budget_bundle_byte_hash"],
            fixture["budget_byte_hash"],
        )
        self.assertEqual(
            binding["budget_fingerprint"],
            simulated_uat_module.FROZEN_BUDGET_FINGERPRINT,
        )
        simulated_uat_module._assert_safe_simulated_uat_report(bound)

        tampered_report = deepcopy(fixture["report"])
        tampered_report["source"]["source_snapshot_fingerprint"] = simulated_uat_module.sha256_json(
            "different-source-snapshot"
        )
        tampered_report_bytes = _serialized_json_bytes(tampered_report)
        tampered_report_path = root / "tampered-completed-report.safe.json"
        tampered_report_path.write_bytes(tampered_report_bytes)
        with self.assertRaisesRegex(
            ContractValidationError,
            "source snapshot binding mismatch",
        ):
            simulated_uat_module.bind_completed_uat_operational_budget(
                completed_report_path=tampered_report_path,
                expected_completed_report_sha256=(
                    simulated_uat_module._sha256_bytes(tampered_report_bytes)
                ),
                operational_budget_bundle_path=fixture["budget_path"],
                expected_operational_budget_bundle_sha256=(fixture["budget_byte_hash"]),
            )

        missing_component_report = deepcopy(fixture["report"])
        del missing_component_report["source"]["retrieval_ready_binding"]["index_fingerprint"]
        missing_component_bytes = _serialized_json_bytes(missing_component_report)
        missing_component_path = root / "missing-component-report.safe.json"
        missing_component_path.write_bytes(missing_component_bytes)
        with self.assertRaisesRegex(
            ContractValidationError,
            "index_fingerprint is invalid",
        ):
            simulated_uat_module.bind_completed_uat_operational_budget(
                completed_report_path=missing_component_path,
                expected_completed_report_sha256=(
                    simulated_uat_module._sha256_bytes(missing_component_bytes)
                ),
                operational_budget_bundle_path=fixture["budget_path"],
                expected_operational_budget_bundle_sha256=(fixture["budget_byte_hash"]),
            )

        mismatched_budget = deepcopy(fixture["budget"])
        mismatched_budget["uat_report_fingerprint"] = simulated_uat_module.sha256_json(
            "different-completed-report"
        )
        mismatched_budget["bundle_fingerprint"] = simulated_uat_module.sha256_json(
            {key: value for key, value in mismatched_budget.items() if key != "bundle_fingerprint"}
        )
        mismatched_budget_bytes = _serialized_json_bytes(mismatched_budget)
        mismatched_budget_path = root / "mismatched-budget.bundle.json"
        mismatched_budget_path.write_bytes(mismatched_budget_bytes)
        with self.assertRaisesRegex(
            ContractValidationError,
            "operational budget UAT binding mismatch",
        ):
            simulated_uat_module.bind_completed_uat_operational_budget(
                completed_report_path=fixture["report_path"],
                expected_completed_report_sha256=fixture["report_byte_hash"],
                operational_budget_bundle_path=mismatched_budget_path,
                expected_operational_budget_bundle_sha256=(
                    simulated_uat_module._sha256_bytes(mismatched_budget_bytes)
                ),
            )

    def test_normal_script_has_no_diagnostic_or_ascii_dense_fallback(self) -> None:
        script_source = (ROOT / "scripts" / "issue56_simulated_uat.py").read_text(encoding="utf-8")
        self.assertNotIn("DeterministicDiagnosticDenseEncoder", script_source)
        self.assertNotIn("ascii_identifier_regex", script_source)
        self.assertNotIn("random", script_source)
        self.assertIn(
            "build_authorized_semantic_mail_session",
            script_source,
        )
        self.assertIn("render_governed_evidence_answer", script_source)


class _ContractOnlyUnicodeModel:
    """Test-only runtime double; unreachable from the normal harness CLI."""

    def encode(self, texts: Sequence[str], **_kwargs):
        rows = []
        for text in texts:
            vector = [0.0] * 384
            for character in text.casefold():
                vector[ord(character) % len(vector)] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            rows.append(_VectorRow(value / norm for value in vector))
        return rows


class _VectorRow(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class _IterationCountingSequence(Sequence[object]):
    def __init__(self, values: Sequence[object]) -> None:
        self._values = tuple(values)
        self.iteration_count = 0

    def __iter__(self):
        self.iteration_count += 1
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


def _synthetic_diagnostic_subset_fixture(root: Path) -> dict[str, object]:
    inputs = build_semantic_poc_inputs()
    bundle = inputs.current_bundle
    observations = inputs.observations_by_bundle_id[bundle.mail_evidence_bundle_id]
    body_observation_ids = tuple(
        observation.observation_id
        for observation in observations
        if observation.observation_type == "email_body_segment"
    )
    if len(body_observation_ids) < 3:
        raise AssertionError("synthetic subset fixture requires three body observations")

    work_dir = root / "work"
    observations_dir = work_dir / "data" / "ingestion" / "observations"
    observations_dir.mkdir(parents=True)
    for observation in observations:
        (observations_dir / f"{observation.observation_id}.json").write_bytes(
            _serialized_json_bytes(observation.to_dict())
        )

    query_texts = (
        "PO470002002",
        "PO470002002 與 SUPPLIER-ALPHA-01 的關係",
        "PO470002004",
    )
    cases = []
    for ordinal in range(100):
        query_index = ordinal if ordinal < 2 else 2
        required_observation_id = body_observation_ids[min(query_index, 2)]
        case_id = f"case_issue56_diagnostic_subset_{ordinal:03d}"
        case_payload = {
            "case_id": case_id,
            "domain": "synthetic_procurement",
            "intent_kind": "bounded_diagnostic",
            "pattern": f"synthetic_pattern_{ordinal % 3}",
            "result_kind": "owner_match",
            "query_text": query_texts[query_index],
            "requester_user_id": bundle.mail_import_session.owner_user_id,
            "required_source_observation_ids": [required_observation_id],
            "forbidden_source_observation_ids": [],
            "required_match_count": 1,
            "limit": 5,
        }
        case_payload["private_fingerprint"] = simulated_uat_module.sha256_json(
            {
                "fixture": "issue56_diagnostic_subset",
                "ordinal": ordinal,
                "case": case_payload,
            }
        )
        cases.append(case_payload)

    manifest = {
        "artifact_id": "formowl_issue56_synthetic_development_manifest_v1",
        "schema_version": 1,
        "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
        "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        "archive_sha256": bundle.mail_import_session.archive_sha256,
        "case_count": len(cases),
        "cases": cases,
    }
    manifest_path = work_dir / PRIVATE_MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(_serialized_json_bytes(manifest))
    bundle_path = root / "bundle.private.json"
    bundle_path.write_bytes(_serialized_json_bytes(bundle.to_dict()))
    source_identifier_fixture = _source_identifier_candidate_fixture(
        root,
        observations=observations,
        workspace_id=bundle.mail_import_session.workspace_id,
    )
    return {
        "work_dir": work_dir,
        "bundle_path": bundle_path,
        "manifest_path": manifest_path,
        "selected_case_hashes": tuple(str(cases[index]["private_fingerprint"]) for index in (0, 1)),
        "query_texts": query_texts,
        "case_ids": tuple(str(case["case_id"]) for case in cases),
        "observation_ids": tuple(observation.observation_id for observation in observations),
        "source_identifier_candidate_artifact_path": (source_identifier_fixture["artifact_path"]),
        "source_identifier_candidate_artifact_sha256": (
            source_identifier_fixture["artifact_byte_hash"]
        ),
        "identity_scope_fingerprint": source_identifier_fixture["identity_scope_fingerprint"],
    }


def _path_proof_session_fixture():
    inputs = build_semantic_poc_inputs()
    runtime = _contract_only_runtime()
    with patch(
        "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
        return_value=runtime,
    ):
        session = build_authorized_semantic_mail_session(
            observations_by_bundle_id=inputs.observations_by_bundle_id,
            bundles=inputs.bundles,
            requester_user_id=SEMANTIC_REQUESTER_USER_ID,
            workspace_id=SEMANTIC_WORKSPACE_ID,
        )
    return session, inputs, runtime


def _view_with_path_proof_term(
    view,
    *,
    node_id: str,
    property_name: str,
    term: str,
    supporting_observation_ids: Sequence[str] = (),
):
    nodes = []
    for node in view.visible_nodes:
        if node.node_id != node_id:
            nodes.append(node)
            continue
        properties = dict(node.properties)
        normalized_term = term.casefold() if property_name == "protected_term_hashes" else term
        properties[property_name] = sorted(
            {
                *properties.get(property_name, ()),
                simulated_uat_module.sha256_json(normalized_term),
            }
        )
        properties["source_observation_ids"] = sorted(
            {
                *properties.get("source_observation_ids", ()),
                *supporting_observation_ids,
            }
        )
        nodes.append(replace(node, properties=properties))
    return replace(view, visible_nodes=nodes)


def _view_with_required_path_proof_support(view):
    view = _view_with_path_proof_term(
        view,
        node_id="node_issue56_origin",
        property_name="protected_term_hashes",
        term="ORIGIN-TAIWAN-01",
        supporting_observation_ids=("obs_issue56_semantic_current_body_2",),
    )
    return _view_with_path_proof_term(
        view,
        node_id="node_issue56_supplier",
        property_name="source_term_hashes",
        term="供應商",
        supporting_observation_ids=("obs_issue56_semantic_current_body_1",),
    )


def _view_with_complete_path_proof_support(view):
    return _view_with_path_proof_term(
        _view_with_required_path_proof_support(view),
        node_id="node_issue56_po_current",
        property_name="protected_term_hashes",
        term="PO470002004",
        supporting_observation_ids=("obs_issue56_semantic_current_body_3",),
    )


def _view_with_mismatched_path_proof_support(view):
    return _view_with_path_proof_term(
        _view_with_required_path_proof_support(view),
        node_id="node_issue56_po_current",
        property_name="protected_term_hashes",
        term="PO470002004",
    )


def _view_with_connected_off_path_proof_support(
    view,
    *,
    term: str,
    supporting_observation_id: str,
):
    view = _view_with_mismatched_path_proof_support(view)
    off_path_node = GraphProjectionNode(
        node_id="node_issue56_path_proof_off_path",
        source_type="candidate_entity",
        source_id="entity_issue56_path_proof_off_path",
        labels=["redacted"],
        properties={
            "node_kind": "candidate_entity",
            "source_observation_ids": [supporting_observation_id],
            "temporal_state": "current",
            "protected_term_hashes": [simulated_uat_module.sha256_json(term.casefold())],
        },
        permission_scope={"scope_type": "public", "visibility": "public"},
    )
    off_path_edge = GraphProjectionEdge(
        edge_id="edge_issue56_path_proof_off_path",
        source_node_id="node_issue56_supplier",
        target_node_id=off_path_node.node_id,
        relation_type="unbounded_association",
        properties={"source_observation_ids": [supporting_observation_id]},
        permission_scope={"scope_type": "public", "visibility": "public"},
    )
    return replace(
        view,
        visible_nodes=[*view.visible_nodes, off_path_node],
        visible_edges=[*view.visible_edges, off_path_edge],
    )


def _run_single_path_proof_trace(
    *,
    session,
    runtime,
    effective_graph_view,
    query_text: str,
    limits,
    case_label: str,
):
    probes: dict[str, object] = {}
    result, elapsed_ms, _cpu_ms = simulated_uat_module._run_instrumented_arm(
        arm_id="hybrid_v2_soft",
        operation=lambda: session.query(
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            allowed_relation_types=SEMANTIC_ALLOWED_RELATIONS,
            limits=limits,
        ),
        relation_phase_probes=probes,
    )
    answer = render_governed_evidence_answer(result)
    trace = simulated_uat_module._build_private_relation_phase_trace(
        arm_id="hybrid_v2_soft",
        hashed_case_id=simulated_uat_module.sha256_json(case_label),
        query_text=query_text,
        result=result,
        answer_status=answer.status,
        session=session,
        effective_graph_view=effective_graph_view,
        probe=probes["hybrid_v2_soft"],
        arm_elapsed_ms=elapsed_ms,
        answer_projection_elapsed_ms=0.0,
    )
    self_profile = session.index._runtime_components.tokenizer_profile.profile_fingerprint
    if self_profile != runtime.tokenizer_profile.profile_fingerprint:
        raise AssertionError("path-proof test runtime profile mismatch")
    return result, trace


def _unique_path_proof_count_mapping(payload: object) -> dict[str, int]:
    matches: list[dict[str, int]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if frozenset(value) == PATH_PROOF_REASON_ENUMS and all(
                isinstance(count, int) and not isinstance(count, bool) and count >= 0
                for count in value.values()
            ):
                matches.append(dict(value))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if len(matches) != 1:
        raise AssertionError(
            "expected exactly one hash/count-only path-proof reason mapping, "
            f"found {len(matches)}"
        )
    return matches[0]


def _assert_hash_count_only_path_proof_payload(
    testcase: unittest.TestCase,
    payload: object,
    *,
    forbidden_values: set[str],
) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for forbidden in forbidden_values:
        testcase.assertNotIn(forbidden, serialized)
    forbidden_keys = {
        "expected_answer",
        "node_id",
        "observation_id",
        "oracle",
        "query",
        "query_text",
        "raw_query",
        "raw_text",
        "term",
        "text",
    }

    def visit(value: object) -> None:
        if isinstance(value, dict):
            testcase.assertTrue(forbidden_keys.isdisjoint(value))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)


def _hashable_arm_behavior(arm_results) -> str:
    projection = []
    for arm_id, result, _elapsed_ms, _cpu_ms, execution_budget_fingerprint in arm_results:
        answer = render_governed_evidence_answer(result)
        projection.append(
            {
                "arm_id": arm_id,
                "result": result.to_safe_dict(),
                "answer_status": answer.status,
                "answer_hash": answer.answer_hash,
                "answer_citation_hashes": list(answer.citation_hashes),
                "answer_source_result_fingerprint": answer.source_result_fingerprint,
                "answer_cost_units": answer.cost_units,
                "execution_budget_fingerprint": execution_budget_fingerprint,
            }
        )
    return simulated_uat_module.sha256_json(projection)


def _native_retrieval_wrapper_fixture(root: Path) -> dict[str, object]:
    _, bundle, _, _ = build_poc_inputs()
    bundle_payload = bundle.to_dict()
    source_snapshot_fingerprint = simulated_uat_module.sha256_json(
        "synthetic-native-source-snapshot"
    )
    source_inventory_fingerprint = simulated_uat_module.sha256_json(
        "synthetic-native-source-inventory"
    )
    source_provenance_fingerprint = simulated_uat_module.sha256_json(
        "synthetic-native-source-provenance"
    )
    artifact: dict[str, object] = {
        "artifact_id": (simulated_uat_module.NATIVE_MAIL_EVIDENCE_BUNDLE_ARTIFACT_ID),
        "schema_version": 1,
        "status": "passed",
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "source_inventory_fingerprint": source_inventory_fingerprint,
        "source_provenance_fingerprint": source_provenance_fingerprint,
        "bundle": bundle_payload,
        "bundle_fingerprint": simulated_uat_module.sha256_json(bundle_payload),
    }
    artifact["artifact_fingerprint"] = simulated_uat_module._payload_fingerprint(
        artifact,
        "artifact_fingerprint",
    )
    artifact_bytes = _serialized_json_bytes(artifact)
    artifact_path = root / "mail-evidence-bundle.private.json"
    artifact_path.write_bytes(artifact_bytes)

    fingerprint = simulated_uat_module.sha256_json
    report: dict[str, object] = {
        "artifact_id": (simulated_uat_module.NATIVE_RETRIEVAL_READY_REPORT_ARTIFACT_ID),
        "schema_version": 1,
        "status": "passed",
        "source_completeness_status": "passed",
        "retrieval_ready_status": "passed",
        "bundle_round_trip_status": "passed",
        "query_evidence_profile_binding_status": "passed",
        "target_profile_status": "passed_no_ascii_fallback",
        "authorized_query_status": "passed",
        "denied_query_status": "passed_fail_closed",
        "canonical_fact_status": "not_asserted",
        "methodology_readiness_status": "blocked",
        "source_asset_fingerprint": bundle.mail_import_session.archive_sha256,
        "native_manifest_fingerprint": fingerprint("synthetic-native-manifest"),
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "source_inventory_fingerprint": source_inventory_fingerprint,
        "source_provenance_fingerprint": source_provenance_fingerprint,
        "permission_fingerprint": fingerprint("synthetic-permission"),
        "parsed_observation_fingerprint": fingerprint("synthetic-parsed-observations"),
        "mail_evidence_bundle_fingerprint": artifact["bundle_fingerprint"],
        "candidate_admission_profile_fingerprint": (
            load_issue56_target_mail_tokenizer_profile().profile_fingerprint
        ),
        "observation_snapshot_fingerprint": fingerprint("synthetic-observation-snapshot"),
        "candidate_manifest_fingerprint": fingerprint("synthetic-candidate-manifest"),
        "index_fingerprint": fingerprint("synthetic-source-index"),
        "query_fingerprint": fingerprint("synthetic-query"),
        "authorized_result_fingerprint": fingerprint("synthetic-authorized-result"),
        "authorized_cited_observation_fingerprint": fingerprint("synthetic-authorized-citation"),
        "denied_result_fingerprint": fingerprint("synthetic-denied-result"),
        "retrieval_snapshot_fingerprint": fingerprint("synthetic-retrieval-snapshot"),
        "bundle_artifact_fingerprint": artifact["artifact_fingerprint"],
        "counts": {
            "missing_source_inventory_binding_count": 0,
            "missing_source_local_key_binding_count": 0,
            "missing_content_hash_binding_count": 0,
            "missing_permission_binding_count": 0,
            "unexplained_loss_count": 0,
            "blocker_count": 0,
        },
        "blocker_fingerprints": [],
    }
    report["report_fingerprint"] = simulated_uat_module._payload_fingerprint(
        report,
        "report_fingerprint",
    )
    report_bytes = _serialized_json_bytes(report)
    report_path = root / "retrieval-ready-report.safe.json"
    report_path.write_bytes(report_bytes)
    return {
        "artifact": artifact,
        "artifact_path": artifact_path,
        "artifact_byte_hash": simulated_uat_module._sha256_bytes(artifact_bytes),
        "report": report,
        "report_path": report_path,
        "report_byte_hash": simulated_uat_module._sha256_bytes(report_bytes),
    }


def _source_identifier_candidate_fixture(
    root: Path,
    *,
    observations: Sequence[Observation],
    workspace_id: str,
    retrieval_binding: dict[str, object] | None = None,
    identity_scope_mode: str = TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    artifact_filename: str = "source-identifier-candidates.private.json",
) -> dict[str, object]:
    tenant_id = (
        "tenant_issue56_simulated_uat_e2e"
        if identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE
        else None
    )
    scope_payload = {
        "mode": identity_scope_mode,
        "workspace_id": workspace_id,
        **({"tenant_id": tenant_id} if tenant_id is not None else {}),
    }
    operator_approval_fingerprint = simulated_uat_module.sha256_json(
        {
            "operator_approved": True,
            "approver_actor": "actor_issue56_simulated_uat_fixture",
            "authority_source": "synthetic_fixture_authority",
            "approved_at": "2026-08-18T07:00:00+00:00",
            "reason": "focused v3 identity-scope consumer fixture",
        }
    )
    spec_approval_fingerprint = (
        simulated_uat_module.sha256_json(
            {
                "approval_kind": "spec_and_operator_approval",
                "spec_approval_id": "spec_issue56_simulated_uat_workspace_only",
            }
        )
        if identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
        else None
    )
    identity_scope = SourceIdentifierIdentityScope(
        identity_scope_mode=identity_scope_mode,
        identity_scope_fingerprint=simulated_uat_module.sha256_json(scope_payload),
        workspace_id=workspace_id,
        identity_scope_attestation_fingerprint=simulated_uat_module.sha256_json(
            {"attestation": scope_payload, "fixture": "simulated_uat_v3"}
        ),
        identity_scope_policy_fingerprint=IDENTITY_SCOPE_POLICY_FINGERPRINT,
        operator_approval_fingerprint=operator_approval_fingerprint,
        tenant_id=tenant_id,
        spec_approval_fingerprint=spec_approval_fingerprint,
    )
    created_at = "2026-08-18T07:00:00+00:00"
    candidate_observations = tuple(
        observation
        for observation in observations
        if observation.observation_type in {"email_message", "email_header", "email_body_segment"}
        and isinstance(observation.text, str)
        and observation.text
    )
    batch = extract_source_bound_identifier_mentions(
        candidate_observations,
        identity_scope=identity_scope,
        extractor_run_id="run_issue56_simulated_uat_identifier_e2e",
        created_at=created_at,
    )
    resolution = resolve_exact_protected_identifier_candidates(batch.candidate_mentions)
    source_hashes = sorted(
        simulated_uat_module.sha256_json(observation.to_dict()) for observation in observations
    )
    occurrence_hashes = sorted(
        {
            simulated_uat_module.sha256_json(
                str(
                    (observation.payload or {}).get(
                        "message_occurrence_id",
                        observation.location.get("message_occurrence_id"),
                    )
                )
            )
            for observation in candidate_observations
        }
    )
    source_snapshot_fingerprint = (
        str(retrieval_binding["source_snapshot_fingerprint"])
        if retrieval_binding is not None
        else simulated_uat_module.sha256_json("synthetic-source-snapshot")
    )
    source_inventory_fingerprint = (
        str(retrieval_binding["source_inventory_fingerprint"])
        if retrieval_binding is not None
        else simulated_uat_module.sha256_json("synthetic-source-inventory")
    )
    retrieval_snapshot_fingerprint = (
        str(retrieval_binding["retrieval_snapshot_fingerprint"])
        if retrieval_binding is not None
        else simulated_uat_module.sha256_json("synthetic-retrieval-snapshot")
    )
    retrieval_report_fingerprint = (
        str(retrieval_binding["retrieval_report_fingerprint"])
        if retrieval_binding is not None
        else simulated_uat_module.sha256_json("synthetic-retrieval-report")
    )
    retrieval_report_byte_sha256 = (
        str(retrieval_binding["retrieval_report_byte_hash"])
        if retrieval_binding is not None
        else simulated_uat_module.sha256_json("synthetic-retrieval-report-bytes")
    )
    artifact: dict[str, object] = {
        "artifact_id": SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
        "schema_version": SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": "candidate_only_not_canonical_fact",
        "created_at": created_at,
        "candidate_only": True,
        "canonical_write_allowed": False,
        "overflow_count": 0,
        "retrieval_snapshot_byte_sha256": simulated_uat_module.sha256_json(
            "synthetic-retrieval-snapshot-bytes"
        ),
        "retrieval_report_byte_sha256": retrieval_report_byte_sha256,
        "retrieval_snapshot_fingerprint": retrieval_snapshot_fingerprint,
        "retrieval_report_fingerprint": retrieval_report_fingerprint,
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "source_inventory_fingerprint": source_inventory_fingerprint,
        "source_observation_hashes": source_hashes,
        "source_observation_hash_set_fingerprint": simulated_uat_module.sha256_json(source_hashes),
        "message_occurrence_fingerprints": occurrence_hashes,
        "message_occurrence_hash_set_fingerprint": simulated_uat_module.sha256_json(
            occurrence_hashes
        ),
        "tokenizer_id": batch.tokenizer_id,
        "tokenizer_profile_fingerprint": batch.tokenizer_profile_fingerprint,
        "extraction_policy_id": SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
        "extraction_policy_fingerprint": (SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT),
        "resolution_policy_id": SOURCE_IDENTIFIER_RESOLUTION_POLICY_ID,
        "resolution_policy_fingerprint": (SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT),
        "identity_scope_mode": identity_scope.identity_scope_mode,
        "identity_scope_attestation_byte_sha256": simulated_uat_module.sha256_json(
            {"attestation_bytes": identity_scope.to_dict()}
        ),
        "identity_scope_attestation_fingerprint": (
            identity_scope.identity_scope_attestation_fingerprint
        ),
        "identity_scope_policy_fingerprint": identity_scope.identity_scope_policy_fingerprint,
        "attested_asset_fingerprint": simulated_uat_module.sha256_json("synthetic-attested-asset"),
        "identity_scope_binding": identity_scope.to_dict(),
        "extractor_run_id": "run_issue56_simulated_uat_identifier_e2e",
        "mention_batch": batch.to_dict(),
        "resolution": resolution.to_dict(),
        "counts": {
            "source_inventory_item_count": len(observations),
            "source_observation_count": len(observations),
            "candidate_source_observation_count": len(candidate_observations),
            "message_occurrence_count": len(occurrence_hashes),
            "identifier_occurrence_count": batch.occurrence_count,
            "resolved_candidate_count": resolution.candidate_count,
            "permission_boundary_count": len(
                {
                    mention.metadata["permission_boundary_fingerprint"]
                    for mention in batch.candidate_mentions
                }
            ),
            "overflow_count": 0,
        },
    }
    artifact["artifact_fingerprint"] = simulated_uat_module._payload_fingerprint(
        artifact,
        "artifact_fingerprint",
    )
    artifact_bytes = _serialized_json_bytes(artifact)
    artifact_path = root / artifact_filename
    artifact_path.write_bytes(artifact_bytes)
    return {
        "artifact": artifact,
        "artifact_path": artifact_path,
        "artifact_byte_hash": simulated_uat_module._sha256_bytes(artifact_bytes),
        "identity_scope_mode": identity_scope.identity_scope_mode,
        "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
        "identity_scope": identity_scope,
    }


def _serialized_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _completed_uat_budget_binding_fixture(root: Path) -> dict[str, object]:
    fingerprint = simulated_uat_module.sha256_json
    source_snapshot_fingerprint = fingerprint("completed-source-snapshot")
    source_binding_fingerprint = fingerprint("completed-source-binding")
    lexical_profile_fingerprint = load_issue56_target_mail_tokenizer_profile().profile_fingerprint
    dense_profile = issue56_target_dense_embedding_profile()
    evaluator_fingerprint = fingerprint(
        {
            "evaluator_id": simulated_uat_module.EVALUATOR_ID,
            "case_count": simulated_uat_module.CASE_COUNT,
            "result_kinds": [
                "owner_match",
                "no_match",
                "permission_denied",
            ],
        }
    )
    retrieval_binding = {
        "status": "sealed_passed",
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "input_binding_fingerprint": fingerprint("retrieval-input-binding"),
        "bundle_artifact_fingerprint": fingerprint("retrieval-bundle-artifact"),
        "retrieval_report_fingerprint": fingerprint("retrieval-safe-report"),
        "index_fingerprint": fingerprint("retrieval-index"),
        "candidate_admission_profile_fingerprint": lexical_profile_fingerprint,
        "permission_fingerprint": fingerprint("retrieval-permission"),
    }
    report: dict[str, object] = {
        "artifact_id": "formowl_issue56_simulated_human_uat_v1",
        "schema_version": 1,
        "status": "blocked",
        "execution_status": "passed",
        "quality_gate_status": "blocked",
        "diagnostic_label": "diagnostic_same_pipeline_not_independent_holdout",
        "e2e_executed": True,
        "path_executed": ["safe_aggregate_report"],
        "manifest_seal": {
            "sealed_before_execution": True,
            "unchanged_after_execution": True,
            "expected_seal_matches": True,
        },
        "source": {
            "source_binding_fingerprint": source_binding_fingerprint,
            "source_snapshot_fingerprint": source_snapshot_fingerprint,
            "selected_projection_fingerprint": fingerprint("selected-projection"),
            "source_observation_hash_set_fingerprint": fingerprint("source-observation-set"),
            "manifest_bundle_identity_matches": True,
            "retrieval_ready_binding": retrieval_binding,
        },
        "shared_pipeline": {
            "lexical_profile_fingerprint": lexical_profile_fingerprint,
            "query_lexical_profile_fingerprint": lexical_profile_fingerprint,
            "evidence_lexical_profile_fingerprint": lexical_profile_fingerprint,
            "dense_model_id": dense_profile.model_id,
            "dense_model_revision": dense_profile.model_revision,
            "dense_profile_fingerprint": dense_profile.profile_fingerprint,
            "execution_component_fingerprint": fingerprint("execution-component"),
            "permission_policy_fingerprint": fingerprint(simulated_uat_module.PERMISSION_POLICY_ID),
            "permission_scoped_index_set_fingerprint": fingerprint("permission-scoped-index-set"),
            "graph_adapter_fingerprint": fingerprint(simulated_uat_module.GRAPH_ADAPTER_ID),
            "ontology_target_fingerprint": fingerprint(simulated_uat_module.ONTOLOGY_TARGET),
            "graph_builds": {
                "build_fingerprint_set_hash": fingerprint("graph-build-set"),
                "ontology_revision_fingerprint_set_hash": fingerprint("ontology-revision-set"),
            },
            "runtime_method_id": ISSUE56_TARGET_RUNTIME_METHOD_ID,
            "runtime_method_fingerprint": ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
            "answer_model_id": (simulated_uat_module.ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID),
            "answer_model_fingerprint": fingerprint(
                simulated_uat_module.ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID
            ),
            "answer_prompt_id": (simulated_uat_module.ISSUE56_DETERMINISTIC_ANSWER_PROMPT_ID),
            "answer_prompt_fingerprint": (
                simulated_uat_module.ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT
            ),
            "answer_budget_fingerprint": (simulated_uat_module.EvidenceAnswerBudget().fingerprint),
            "evaluator_id": simulated_uat_module.EVALUATOR_ID,
            "evaluator_fingerprint": evaluator_fingerprint,
        },
        "execution_environment": {
            "attestation_run_binding_fingerprint": source_binding_fingerprint,
            "code_attestation_fingerprint": fingerprint("code-attestation"),
            "code_tree_fingerprint": fingerprint("code-tree"),
            "image_attestation_fingerprint": fingerprint("image-attestation"),
            "image_id": FROZEN_CANONICAL_IMAGE_ID,
            "image_metadata_fingerprint": (FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
            "authority_attestation_fingerprint": fingerprint("authority-attestation"),
            "authority_execution_fingerprint": fingerprint("authority-execution"),
            "source_completeness_gate_status": "blocked",
            "real_source_ablation_gate_status": "blocked",
        },
        "quality_gate": {
            "gate_id": simulated_uat_module.QUALITY_GATE_ID,
            "gate_fingerprint": fingerprint("quality-gate"),
            "status": "blocked",
            "checks": {
                "citation_precision": {
                    "status": "failed",
                    "measured_basis_points": 8_512,
                },
                "operational_budget": {
                    "status": "blocked",
                    "reason_hash": fingerprint("operational-budget-unbound"),
                },
            },
        },
        "resource_measurement": {
            "model_usage_cost": (simulated_uat_module._deterministic_zero_cost_measurement())
        },
        "diagnostic_run_fingerprint": fingerprint("diagnostic-run"),
        "claim_boundary": {
            "independent_holdout": False,
            "methodology_ready": False,
            "methodology_complete": False,
            "issue56_complete": False,
            "production_ready": False,
            "supports_arm_superiority_claim": False,
        },
    }
    report_bytes = _serialized_json_bytes(report)
    report_path = root / "completed-uat.safe.json"
    report_path.write_bytes(report_bytes)

    checks = {
        "hybrid_v2_p95_latency": {"status": "passed"},
        "hybrid_v2_per_case_internal_cost": {"status": "passed"},
        "peak_rss": {"status": "passed"},
        "model_token_monetary_cost": {"status": "passed"},
    }
    budget: dict[str, object] = {
        "artifact_id": ("formowl_issue56_operational_budget_acceptance_bundle_v1"),
        "schema_version": 1,
        "status": "passed",
        "operational_budget_status": "passed",
        "full_quality_gate_status": "blocked",
        "pre_holdout_registration_status": "passed",
        "holdout_content_read_count": 0,
        "oracle_content_read_count": 0,
        "budget_fingerprint": simulated_uat_module.FROZEN_BUDGET_FINGERPRINT,
        "uat_report_fingerprint": simulated_uat_module._sha256_bytes(report_bytes),
        "uat_content_fingerprint": (
            simulated_uat_module._operational_budget_content_fingerprint(report)
        ),
        "uat_run_fingerprint": report["diagnostic_run_fingerprint"],
        "runtime_binding_fingerprint": fingerprint("budget-runtime-binding"),
        "check_set_fingerprint": fingerprint(checks),
        "check_count": len(checks),
        "check_status_counts": {
            "passed": len(checks),
            "failed": 0,
            "blocked": 0,
        },
        "blocking_status_ids": [],
        "failure_status_ids": [],
        "checks": checks,
    }
    budget["bundle_fingerprint"] = fingerprint(budget)
    budget_bytes = _serialized_json_bytes(budget)
    budget_path = root / "operational-budget.bundle.json"
    budget_path.write_bytes(budget_bytes)
    return {
        "report": report,
        "report_path": report_path,
        "report_byte_hash": simulated_uat_module._sha256_bytes(report_bytes),
        "budget": budget,
        "budget_path": budget_path,
        "budget_byte_hash": simulated_uat_module._sha256_bytes(budget_bytes),
    }


def _contract_only_runtime() -> Issue56TargetRuntimeComponents:
    tokenizer_profile = load_issue56_target_mail_tokenizer_profile()
    dense_profile = issue56_target_dense_embedding_profile()
    encoder = SentenceTransformerDenseEncoder(
        profile=dense_profile,
        _model=_ContractOnlyUnicodeModel(),
    )
    binding = build_issue56_execution_component_binding(
        tokenizer_profile=tokenizer_profile,
        dense_profile=dense_profile,
    )
    return Issue56TargetRuntimeComponents(
        tokenizer_profile=tokenizer_profile,
        dense_encoder=encoder,
        execution_binding=binding,
    )


if __name__ == "__main__":
    unittest.main()
