from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_contract import assert_no_public_raw_references, sha256_json
from scripts.issue56_execution_fingerprint import (
    ANSWER_COMPONENT_ID,
    EVALUATOR_ID,
    EVALUATION_COMPONENT_ID,
    GRAPH_ONTOLOGY_COMPONENT_ID,
    INPUT_ARTIFACT_ID,
    ISSUE56_TARGET_RUNTIME_METHOD_ID,
    LEXICAL_INDEX_COMPONENT_ID,
    READINESS_BLOCKER_IDS,
    REPORT_ARTIFACT_ID,
    SCHEMA_VERSION,
    SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
    SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
    SOURCE_COMPONENT_ID,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    UAT_ARTIFACT_ID,
    UAT_DEVELOPMENT_BOUNDARY_ID,
    _load_and_validate_completed_uat_report,
    build_current_authority_component,
    build_current_code_component,
    build_image_component,
    current_runtime_binding_fingerprints,
    load_and_validate_bundle,
    seal_safe_artifact,
)
from formowl_mail.answer import ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID
from formowl_core import load_issue56_target_mail_tokenizer_profile
from scripts.issue56_operational_budget import (
    FROZEN_CANONICAL_IMAGE_ID,
    FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue56_execution_fingerprint.py"
DEFAULT_TEST_IMAGE_ID = FROZEN_CANONICAL_IMAGE_ID
DEFAULT_TEST_IMAGE_METADATA = FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT


class Issue56ExecutionFingerprintEndToEndTests(unittest.TestCase):
    def test_safe_components_to_persisted_blocked_bundle_round_trip(self) -> None:
        image_id, image_metadata = _image_attestation()
        payload = _valid_input_payload(
            image_id=image_id,
            image_metadata=image_metadata,
        )
        first = _run_cli(
            payload,
            image_id=image_id,
            image_metadata=image_metadata,
        )
        self.assertEqual(first.returncode, 2, first.stderr)
        report = json.loads(first.stdout)
        self.assertEqual(report["artifact_id"], REPORT_ARTIFACT_ID)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["acceptance_status"], "blocked")
        self.assertEqual(report["bundle_round_trip_status"], "passed")
        self.assertEqual(report["public_report_round_trip_status"], "passed")
        self.assertEqual(
            report["blocking_status_ids"],
            sorted((*READINESS_BLOCKER_IDS, "methodology_authority_not_ready")),
        )
        self.assertEqual(report["component_count"], 8)
        self.assertGreater(report["accepted_component_count"], 0)
        self.assertGreater(report["blocked_component_count"], 0)
        self.assertRegex(report["execution_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(report["bundle_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(report["report_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        assert_no_public_raw_references(
            report,
            "issue56_execution_fingerprint_test_report",
        )

        bundle = load_and_validate_bundle(first.bundle_path)
        persisted_report = json.loads(first.public_path.read_text(encoding="utf-8"))
        self.assertEqual(bundle["status"], "blocked")
        for binding_name in (
            "source_identifier_candidate_schema",
            "source_identifier_identity_scope_mode",
            "source_identifier_identity_scope",
            "source_identifier_identity_scope_attestation",
            "source_identifier_identity_scope_policy",
            "source_identifier_operator_approval",
            "source_identifier_extraction_policy",
            "source_identifier_resolution_policy",
        ):
            self.assertRegex(
                bundle["bound_fingerprints"][binding_name],
                r"^sha256:[0-9a-f]{64}$",
            )
        self.assertEqual(
            bundle["execution_fingerprint"],
            report["execution_fingerprint"],
        )
        self.assertEqual(persisted_report, report)
        serialized = json.dumps(
            {"bundle": bundle, "report": report},
            ensure_ascii=True,
            sort_keys=True,
        )
        self.assertNotIn(str(first.temp_root), serialized)
        self.assertNotIn(str(ROOT), serialized)

        second = _run_cli(
            payload,
            image_id=image_id,
            image_metadata=image_metadata,
        )
        self.assertEqual(second.returncode, 2, second.stderr)
        second_report = json.loads(second.stdout)
        second_bundle = load_and_validate_bundle(second.bundle_path)
        self.assertEqual(
            second_bundle["execution_fingerprint"],
            bundle["execution_fingerprint"],
        )
        self.assertEqual(
            second_bundle["bundle_fingerprint"],
            bundle["bundle_fingerprint"],
        )
        self.assertEqual(
            second_report["report_fingerprint"],
            report["report_fingerprint"],
        )

    def test_missing_tampered_and_cross_run_inputs_fail_closed(self) -> None:
        image_id, image_metadata = _image_attestation()
        baseline = _valid_input_payload(
            image_id=image_id,
            image_metadata=image_metadata,
        )
        baseline_uat = _valid_uat_report(baseline)

        missing = copy.deepcopy(baseline)
        missing.pop("graph_ontology_component")
        missing = seal_safe_artifact(missing)
        missing_result = _run_cli(
            missing,
            image_id=image_id,
            image_metadata=image_metadata,
            uat_report=baseline_uat,
        )
        _assert_rejected(self, missing_result, "component_missing")

        tampered = copy.deepcopy(baseline)
        tampered["source_component"]["observation_count"] += 1
        tampered = seal_safe_artifact(tampered)
        tampered_result = _run_cli(
            tampered,
            image_id=image_id,
            image_metadata=image_metadata,
        )
        _assert_rejected(
            self,
            tampered_result,
            "component_artifact_fingerprint_invalid",
        )

        cross_run = copy.deepcopy(baseline)
        cross_run["graph_ontology_component"]["run_binding_fingerprint"] = sha256_json(
            "different-run"
        )
        cross_run["graph_ontology_component"] = seal_safe_artifact(
            cross_run["graph_ontology_component"]
        )
        cross_run = seal_safe_artifact(cross_run)
        cross_run_result = _run_cli(
            cross_run,
            image_id=image_id,
            image_metadata=image_metadata,
        )
        _assert_rejected(self, cross_run_result, "component_run_binding_mismatch")

        cross_source = copy.deepcopy(baseline)
        cross_source["answer_component"]["source_binding_fingerprint"] = sha256_json(
            "different-source"
        )
        cross_source["answer_component"] = seal_safe_artifact(cross_source["answer_component"])
        cross_source = seal_safe_artifact(cross_source)
        cross_source_result = _run_cli(
            cross_source,
            image_id=image_id,
            image_metadata=image_metadata,
        )
        _assert_rejected(
            self,
            cross_source_result,
            "component_source_binding_mismatch",
        )

        legacy_graph = copy.deepcopy(baseline)
        legacy_graph["graph_ontology_component"]["graph_adapter_fingerprint"] = sha256_json(
            "source_backed_mail_candidate_graph_v1"
        )
        legacy_graph["graph_ontology_component"] = seal_safe_artifact(
            legacy_graph["graph_ontology_component"]
        )
        legacy_graph = seal_safe_artifact(legacy_graph)
        legacy_result = _run_cli(
            legacy_graph,
            image_id=image_id,
            image_metadata=image_metadata,
        )
        _assert_rejected(
            self,
            legacy_result,
            "graph_ontology_binding_stale",
        )

    def test_stale_authority_code_and_image_attestations_fail_closed(self) -> None:
        image_id, image_metadata = _image_attestation()
        baseline = _valid_input_payload(
            image_id=image_id,
            image_metadata=image_metadata,
        )

        stale_authority = copy.deepcopy(baseline)
        stale_authority["authority_component"]["authority_state_fingerprint"] = sha256_json(
            "stale-authority"
        )
        stale_authority["authority_component"] = seal_safe_artifact(
            stale_authority["authority_component"]
        )
        stale_authority = seal_safe_artifact(stale_authority)
        stale_result = _run_cli(
            stale_authority,
            image_id=image_id,
            image_metadata=image_metadata,
        )
        _assert_rejected(self, stale_result, "authority_state_stale")

        stale_code = copy.deepcopy(baseline)
        stale_code["code_component"]["code_tree_fingerprint"] = sha256_json("stale-code")
        stale_code["code_component"] = seal_safe_artifact(stale_code["code_component"])
        stale_code = seal_safe_artifact(stale_code)
        code_result = _run_cli(
            stale_code,
            image_id=image_id,
            image_metadata=image_metadata,
        )
        _assert_rejected(self, code_result, "code_tree_attestation_mismatch")

        missing_image_result = _run_cli(
            baseline,
            image_id=None,
            image_metadata=None,
        )
        _assert_rejected(
            self,
            missing_image_result,
            "canonical_image_attestation_missing_or_invalid",
        )

        mismatched_image_result = _run_cli(
            baseline,
            image_id=sha256_json("different-image"),
            image_metadata=image_metadata,
        )
        _assert_rejected(
            self,
            mismatched_image_result,
            "canonical_image_attestation_mismatch",
        )

    def test_completed_uat_report_seal_and_component_bindings_fail_closed(self) -> None:
        image_id, image_metadata = _image_attestation()
        payload = _valid_input_payload(
            image_id=image_id,
            image_metadata=image_metadata,
        )

        missing_report = _run_cli(
            payload,
            image_id=image_id,
            image_metadata=image_metadata,
            include_uat_report=False,
            include_expected_uat_report_fingerprint=False,
        )
        _assert_rejected(self, missing_report, "uat_report_missing_or_invalid")

        wrong_seal = _run_cli(
            payload,
            image_id=image_id,
            image_metadata=image_metadata,
            expected_uat_report_fingerprint=sha256_json("wrong-uat-report"),
        )
        _assert_rejected(self, wrong_seal, "uat_report_fingerprint_mismatch")

        baseline_uat = _valid_uat_report(payload)
        legacy_uat = copy.deepcopy(baseline_uat)
        legacy_uat["source"].pop("source_identifier_candidate_binding")
        _assert_direct_uat_rejected(
            self,
            payload=payload,
            uat_report=legacy_uat,
            image_id=image_id,
            image_metadata=image_metadata,
            expected_reason=("uat_source_identifier_candidate_binding_missing_or_invalid"),
        )
        cases = (
            (
                ("manifest_seal", "sealed_before_execution"),
                False,
                "uat_manifest_seal_invalid",
            ),
            (
                ("execution_status",),
                "blocked",
                "uat_execution_not_passed",
            ),
            (
                ("source", "source_snapshot_fingerprint"),
                sha256_json("other-source-snapshot"),
                "uat_source_snapshot_mismatch",
            ),
            (
                ("shared_pipeline", "lexical_profile_fingerprint"),
                sha256_json("other-lexical-profile"),
                "uat_pipeline_binding_mismatch_lexical_profile_fingerprint",
            ),
            (
                ("shared_pipeline", "permission_scoped_index_set_fingerprint"),
                sha256_json("other-index"),
                "uat_pipeline_binding_mismatch_permission_scoped_index_set_fingerprint",
            ),
            (
                ("shared_pipeline", "graph_builds", "build_fingerprint_set_hash"),
                sha256_json("other-graph"),
                "uat_graph_binding_mismatch",
            ),
            (
                (
                    "source",
                    "source_identifier_candidate_binding",
                    "selected_mention_batch_fingerprint",
                ),
                sha256_json("other-selected-mention-batch"),
                ("uat_source_identifier_binding_mismatch_" "selected_mention_batch_fingerprint"),
            ),
            (
                ("shared_pipeline", "graph_adapter_fingerprint"),
                sha256_json("source_backed_mail_candidate_graph_v1"),
                "uat_pipeline_binding_mismatch_graph_adapter_fingerprint",
            ),
            (
                ("shared_pipeline", "relation_type_hash_set_fingerprint"),
                sha256_json([sha256_json("co_occurs_with")]),
                ("uat_pipeline_binding_mismatch_" "relation_type_hash_set_fingerprint"),
            ),
            (
                (
                    "shared_pipeline",
                    "graph_builds",
                    "identifier_resolution_fingerprint_set_hash",
                ),
                sha256_json("other-resolution-set"),
                ("uat_graph_binding_mismatch_" "identifier_resolution_fingerprint_set_hash"),
            ),
            (
                (
                    "shared_pipeline",
                    "graph_builds",
                    "ontology_revision_fingerprint_set_hash",
                ),
                sha256_json("other-ontology"),
                "uat_ontology_binding_mismatch",
            ),
            (
                ("shared_pipeline", "runtime_method_fingerprint"),
                sha256_json("other-method"),
                "uat_pipeline_binding_mismatch_runtime_method_fingerprint",
            ),
            (
                ("shared_pipeline", "answer_model_fingerprint"),
                sha256_json("other-answer-model"),
                "uat_pipeline_binding_mismatch_answer_model_fingerprint",
            ),
            (
                ("shared_pipeline", "answer_prompt_fingerprint"),
                sha256_json("other-answer-prompt"),
                "uat_pipeline_binding_mismatch_answer_prompt_fingerprint",
            ),
            (
                ("shared_pipeline", "evaluator_fingerprint"),
                sha256_json("other-evaluator"),
                "uat_pipeline_binding_mismatch_evaluator_fingerprint",
            ),
        )
        for field_path, replacement, expected_reason in cases:
            with self.subTest(field_path=field_path):
                tampered_uat = copy.deepcopy(baseline_uat)
                target = tampered_uat
                for field_name in field_path[:-1]:
                    target = target[field_name]
                target[field_path[-1]] = replacement
                _assert_direct_uat_rejected(
                    self,
                    payload=payload,
                    uat_report=tampered_uat,
                    image_id=image_id,
                    image_metadata=image_metadata,
                    expected_reason=expected_reason,
                )

        environment_cases = (
            (
                "code_tree_fingerprint",
                sha256_json("other-code-tree"),
                "uat_execution_environment_mismatch_code_tree_fingerprint",
            ),
            (
                "image_id",
                sha256_json("other-image"),
                "uat_execution_environment_mismatch_image_id",
            ),
            (
                "authority_execution_fingerprint",
                sha256_json("other-authority"),
                "uat_execution_environment_mismatch_authority_execution_fingerprint",
            ),
        )
        for field_name, replacement, expected_reason in environment_cases:
            with self.subTest(execution_environment_field=field_name):
                # Refresh the untampered current-tree attestation immediately
                # before isolating each environment-field mismatch. Other
                # disjoint workers may legitimately update code-scoped files
                # while this test process is running; the validator must still
                # fail closed, but this subtest should identify the field it
                # intentionally changed rather than an earlier tree revision.
                tampered_uat = _valid_uat_report(payload)
                tampered_uat["execution_environment"][field_name] = replacement
                bound_payload = _bind_uat_report(payload, tampered_uat)
                _assert_direct_uat_rejected(
                    self,
                    payload=bound_payload,
                    uat_report=tampered_uat,
                    image_id=image_id,
                    image_metadata=image_metadata,
                    expected_reason=expected_reason,
                )

    def test_current_blocked_authority_prevents_fake_ready_state(self) -> None:
        image_id, image_metadata = _image_attestation()
        payload = _valid_input_payload(
            image_id=image_id,
            image_metadata=image_metadata,
        )
        payload["source_component"]["status"] = "passed"
        payload["source_component"]["unexplained_loss_count"] = 0
        payload["source_component"] = seal_safe_artifact(payload["source_component"])
        payload["answer_component"]["final_answer_acceptance_status"] = "passed"
        payload["answer_component"] = seal_safe_artifact(payload["answer_component"])
        payload["evaluation_component"].update(
            {
                "status": "passed",
                "quality_gate_status": "passed",
                "operational_budget_status": "passed",
                "independent_holdout_status": "passed",
                "transfer_evaluation_status": "passed",
            }
        )
        payload["evaluation_component"] = seal_safe_artifact(payload["evaluation_component"])
        payload = seal_safe_artifact(payload)
        uat_report = _valid_uat_report(payload)
        uat_report["status"] = "passed"
        uat_report["quality_gate_status"] = "passed"
        uat_report["quality_gate"] = {
            "status": "passed",
            "check_set_fingerprint": sha256_json("all-diagnostic-checks-passed"),
        }

        result = _run_cli(
            payload,
            image_id=image_id,
            image_metadata=image_metadata,
            uat_report=uat_report,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            report["blocking_status_ids"],
            [
                "methodology_authority_not_ready",
                "real_source_ablation_authority_gate_not_passed",
                "source_completeness_authority_gate_not_passed",
            ],
        )


class _CliResult:
    def __init__(
        self,
        *,
        completed: subprocess.CompletedProcess[str],
        temp_root: Path,
        bundle_path: Path,
        public_path: Path,
        cleanup: tempfile.TemporaryDirectory[str],
    ) -> None:
        self.returncode = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr
        self.temp_root = temp_root
        self.bundle_path = bundle_path
        self.public_path = public_path
        self._cleanup = cleanup

    def __del__(self) -> None:
        self._cleanup.cleanup()


def _run_cli(
    payload: dict[str, object],
    *,
    image_id: str | None,
    image_metadata: str | None,
    uat_report: dict[str, object] | None = None,
    expected_uat_report_fingerprint: str | None = None,
    include_uat_report: bool = True,
    include_expected_uat_report_fingerprint: bool = True,
) -> _CliResult:
    cleanup = tempfile.TemporaryDirectory(prefix="issue56-execution-fingerprint-")
    temp_root = Path(cleanup.name)
    input_path = temp_root / "inputs.safe.json"
    uat_path = temp_root / "uat.safe.json"
    bundle_path = temp_root / "bundle.safe.json"
    public_path = temp_root / "report.safe.json"
    prepared_payload = copy.deepcopy(payload)
    prepared_uat = (
        _valid_uat_report(prepared_payload) if uat_report is None else copy.deepcopy(uat_report)
    )
    prepared_payload = _bind_uat_report(prepared_payload, prepared_uat)
    input_path.write_text(
        json.dumps(prepared_payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    uat_bytes = _serialized_json_bytes(prepared_uat)
    uat_path.write_bytes(uat_bytes)
    command = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(input_path),
        "--output",
        str(bundle_path),
        "--public-output",
        str(public_path),
    ]
    if include_uat_report:
        command.extend(("--uat-report", str(uat_path)))
    if include_expected_uat_report_fingerprint:
        command.extend(
            (
                "--expected-uat-report-fingerprint",
                expected_uat_report_fingerprint or _sha256_bytes(uat_bytes),
            )
        )
    if image_id is not None:
        command.extend(("--canonical-image-id", image_id))
    if image_metadata is not None:
        command.extend(("--canonical-image-metadata-fingerprint", image_metadata))
    environment = os.environ.copy()
    environment.pop("FORMOWL_CANONICAL_IMAGE_ID", None)
    environment.pop("FORMOWL_CANONICAL_IMAGE_METADATA_FINGERPRINT", None)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return _CliResult(
        completed=completed,
        temp_root=temp_root,
        bundle_path=bundle_path,
        public_path=public_path,
        cleanup=cleanup,
    )


def _valid_input_payload(
    *,
    image_id: str,
    image_metadata: str,
) -> dict[str, object]:
    run_binding = sha256_json("issue56-execution-fingerprint-e2e-run")
    source_binding = sha256_json("issue56-safe-source-binding")
    runtime = current_runtime_binding_fingerprints()
    identity_scope_mode = WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
    identity_scope_fingerprint = sha256_json(
        {
            "mode": identity_scope_mode,
            "workspace_id": "workspace_issue56_execution_fingerprint_fixture",
        }
    )
    operator_approval_fingerprint = sha256_json("operator-approval")
    spec_approval_fingerprint = sha256_json("spec-approval")
    identity_scope_attestation_fingerprint = sha256_json("identity-scope-attestation")
    identity_scope_binding_fingerprint = sha256_json("identity-scope-binding")
    identity_scope_mode_fingerprint = sha256_json(identity_scope_mode)
    identity_scope_attestation_byte_fingerprint = sha256_json("identity-scope-attestation-bytes")
    mode_approval_fingerprint = sha256_json(
        {
            "identity_scope_mode": identity_scope_mode,
            "operator_approval_fingerprint": operator_approval_fingerprint,
            "spec_approval_fingerprint": spec_approval_fingerprint,
        }
    )
    source_component = seal_safe_artifact(
        {
            "artifact_id": SOURCE_COMPONENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "run_binding_fingerprint": run_binding,
            "source_binding_fingerprint": source_binding,
            "source_snapshot_fingerprint": sha256_json("source-snapshot"),
            "completeness_report_fingerprint": sha256_json("completeness-report"),
            "source_inventory_fingerprint": sha256_json("source-inventory"),
            "source_item_count": 2793,
            "observation_count": 2668,
            "unexplained_loss_count": 157,
        }
    )
    lexical_index_component = seal_safe_artifact(
        {
            "artifact_id": LEXICAL_INDEX_COMPONENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "run_binding_fingerprint": run_binding,
            "source_binding_fingerprint": source_binding,
            "lexical_profile_fingerprint": runtime["lexical_profile_fingerprint"],
            "query_profile_fingerprint": runtime["lexical_profile_fingerprint"],
            "evidence_profile_fingerprint": runtime["lexical_profile_fingerprint"],
            "dense_profile_fingerprint": runtime["dense_profile_fingerprint"],
            "runtime_component_fingerprint": runtime["runtime_component_fingerprint"],
            "index_fingerprint": sha256_json("index-artifact"),
            "index_count": 1,
            "ascii_fallback_count": 0,
        }
    )
    graph_ontology_component = seal_safe_artifact(
        {
            "artifact_id": GRAPH_ONTOLOGY_COMPONENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "run_binding_fingerprint": run_binding,
            "source_binding_fingerprint": source_binding,
            "graph_artifact_fingerprint": sha256_json("graph-artifact"),
            "graph_adapter_fingerprint": runtime["graph_adapter_fingerprint"],
            "source_graph_policy_fingerprint": runtime["source_graph_policy_fingerprint"],
            "source_identifier_adapter_fingerprint": runtime[
                "source_identifier_adapter_fingerprint"
            ],
            "relation_type_hash_set_fingerprint": runtime["relation_type_hash_set_fingerprint"],
            "source_identifier_candidate_artifact_fingerprint": sha256_json(
                "source-identifier-candidate-artifact"
            ),
            "source_identifier_candidate_binding_fingerprint": sha256_json(
                "source-identifier-candidate-binding"
            ),
            "source_identifier_candidate_schema_fingerprint": runtime[
                "source_identifier_candidate_schema_fingerprint"
            ],
            "source_identifier_identity_scope_mode_fingerprint": (identity_scope_mode_fingerprint),
            "source_identifier_identity_scope_fingerprint": identity_scope_fingerprint,
            "source_identifier_identity_scope_binding_fingerprint": (
                identity_scope_binding_fingerprint
            ),
            "source_identifier_identity_scope_attestation_byte_fingerprint": (
                identity_scope_attestation_byte_fingerprint
            ),
            "source_identifier_identity_scope_attestation_fingerprint": (
                identity_scope_attestation_fingerprint
            ),
            "source_identifier_identity_scope_policy_fingerprint": runtime[
                "source_identifier_identity_scope_policy_fingerprint"
            ],
            "source_identifier_operator_approval_fingerprint": (operator_approval_fingerprint),
            "source_identifier_mode_approval_fingerprint": mode_approval_fingerprint,
            "source_identifier_extraction_policy_fingerprint": runtime[
                "source_identifier_extraction_policy_fingerprint"
            ],
            "source_identifier_resolution_policy_fingerprint": runtime[
                "source_identifier_resolution_policy_fingerprint"
            ],
            "source_identifier_identity_scope_graph_binding_set_fingerprint": sha256_json(
                [sha256_json("identity-scope-graph-binding")]
            ),
            "complete_identifier_mention_batch_fingerprint": sha256_json(
                "complete-identifier-mention-batch"
            ),
            "selected_identifier_mention_batch_fingerprint": sha256_json(
                "selected-identifier-mention-batch"
            ),
            "complete_identifier_mention_fingerprint_set_hash": sha256_json(
                "complete-identifier-mention-set"
            ),
            "authorized_identifier_mention_fingerprint_set_hash": sha256_json(
                "authorized-identifier-mention-set"
            ),
            "complete_identifier_resolution_fingerprint": sha256_json(
                "complete-identifier-resolution"
            ),
            "selected_identifier_resolution_fingerprint": sha256_json(
                "selected-identifier-resolution"
            ),
            "identifier_resolution_fingerprint_set_hash": sha256_json("identifier-resolution-set"),
            "ontology_artifact_fingerprint": sha256_json("ontology-artifact"),
            "ontology_target_fingerprint": runtime["ontology_target_fingerprint"],
            "graph_node_count": 42,
            "graph_edge_count": 17,
            "unresolved_evidence_hop_count": 0,
            "complete_identifier_mention_count": 20,
            "selected_identifier_mention_count": 12,
            "authorized_identifier_mention_count": 9,
            "complete_resolved_identifier_candidate_count": 8,
            "selected_resolved_identifier_candidate_count": 6,
        }
    )
    answer_component = seal_safe_artifact(
        {
            "artifact_id": ANSWER_COMPONENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "run_binding_fingerprint": run_binding,
            "source_binding_fingerprint": source_binding,
            "answer_model_fingerprint": runtime["answer_model_fingerprint"],
            "answer_prompt_fingerprint": runtime["answer_prompt_fingerprint"],
            "answer_budget_fingerprint": runtime["answer_budget_fingerprint"],
            "answer_count": 100,
            "final_answer_acceptance_status": "missing",
        }
    )
    evaluation_component = seal_safe_artifact(
        {
            "artifact_id": EVALUATION_COMPONENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "run_binding_fingerprint": run_binding,
            "source_binding_fingerprint": source_binding,
            "evaluator_fingerprint": runtime["evaluator_fingerprint"],
            "quality_gate_report_fingerprint": sha256_json("quality-gate-report"),
            "uat_report_fingerprint": sha256_json("uat-report"),
            "uat_content_fingerprint": sha256_json("uat-content"),
            "uat_run_fingerprint": sha256_json("uat-run"),
            "runtime_method_fingerprint": runtime["runtime_method_fingerprint"],
            "quality_gate_status": "blocked",
            "operational_budget_status": "missing",
            "independent_holdout_status": "missing",
            "transfer_evaluation_status": "missing",
            "evaluated_case_count": 100,
        }
    )
    code_component = build_current_code_component(
        repository_root=ROOT,
        run_binding_fingerprint=run_binding,
    )
    image_component = build_image_component(
        run_binding_fingerprint=run_binding,
        image_id=image_id,
        image_metadata_fingerprint=image_metadata,
    )
    authority_component = build_current_authority_component(
        repository_root=ROOT,
        run_binding_fingerprint=run_binding,
    )
    return seal_safe_artifact(
        {
            "artifact_id": INPUT_ARTIFACT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "candidate",
            "run_binding_fingerprint": run_binding,
            "source_component": source_component,
            "lexical_index_component": lexical_index_component,
            "graph_ontology_component": graph_ontology_component,
            "answer_component": answer_component,
            "evaluation_component": evaluation_component,
            "code_component": code_component,
            "image_component": image_component,
            "authority_component": authority_component,
        }
    )


def _valid_uat_report(payload: dict[str, object]) -> dict[str, object]:
    source = payload["source_component"]
    lexical = payload["lexical_index_component"]
    graph = payload["graph_ontology_component"]
    answer = payload["answer_component"]
    evaluation = payload["evaluation_component"]
    source_binding = source["source_binding_fingerprint"]
    tokenizer_profile = load_issue56_target_mail_tokenizer_profile()
    runtime = current_runtime_binding_fingerprints()
    code_attestation = build_current_code_component(
        repository_root=ROOT,
        run_binding_fingerprint=source_binding,
    )
    image_attestation = build_image_component(
        run_binding_fingerprint=source_binding,
        image_id=FROZEN_CANONICAL_IMAGE_ID,
        image_metadata_fingerprint=FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    )
    authority_attestation = build_current_authority_component(
        repository_root=ROOT,
        run_binding_fingerprint=source_binding,
    )
    quality_gate = {
        "status": "blocked",
        "check_set_fingerprint": sha256_json("diagnostic-quality-checks"),
    }
    return {
        "artifact_id": UAT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "execution_status": "passed",
        "quality_gate_status": "blocked",
        "diagnostic_label": UAT_DEVELOPMENT_BOUNDARY_ID,
        "diagnostic_run_fingerprint": sha256_json("diagnostic-run"),
        "e2e_executed": True,
        "manifest_seal": {
            "sealed_before_execution": True,
            "unchanged_after_execution": True,
            "expected_seal_matches": True,
            "manifest_byte_hash": sha256_json("manifest"),
        },
        "source": {
            "source_binding_fingerprint": source_binding,
            "source_snapshot_fingerprint": source["source_snapshot_fingerprint"],
            "source_observation_hash_set_fingerprint": sha256_json("observation-hash-set"),
            "source_identifier_candidate_binding": {
                "status": "sealed_passed",
                "binding_id": SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
                "candidate_artifact_schema_version": (SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION),
                "source_artifact_fingerprint": graph[
                    "source_identifier_candidate_artifact_fingerprint"
                ],
                "binding_fingerprint": graph["source_identifier_candidate_binding_fingerprint"],
                "candidate_artifact_schema_fingerprint": graph[
                    "source_identifier_candidate_schema_fingerprint"
                ],
                "identity_scope_mode_status": WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
                "identity_scope_mode_fingerprint": graph[
                    "source_identifier_identity_scope_mode_fingerprint"
                ],
                "identity_scope_fingerprint": graph["source_identifier_identity_scope_fingerprint"],
                "identity_scope_binding_fingerprint": graph[
                    "source_identifier_identity_scope_binding_fingerprint"
                ],
                "identity_scope_attestation_byte_sha256": graph[
                    "source_identifier_identity_scope_attestation_byte_fingerprint"
                ],
                "identity_scope_attestation_fingerprint": graph[
                    "source_identifier_identity_scope_attestation_fingerprint"
                ],
                "identity_scope_policy_fingerprint": graph[
                    "source_identifier_identity_scope_policy_fingerprint"
                ],
                "operator_approval_fingerprint": graph[
                    "source_identifier_operator_approval_fingerprint"
                ],
                "spec_approval_fingerprint": sha256_json("spec-approval"),
                "mode_approval_fingerprint": graph["source_identifier_mode_approval_fingerprint"],
                "workspace_scope_fingerprint": sha256_json(
                    "workspace_issue56_execution_fingerprint_fixture"
                ),
                "extraction_policy_fingerprint": graph[
                    "source_identifier_extraction_policy_fingerprint"
                ],
                "resolution_policy_fingerprint": graph[
                    "source_identifier_resolution_policy_fingerprint"
                ],
                "complete_mention_batch_fingerprint": graph[
                    "complete_identifier_mention_batch_fingerprint"
                ],
                "selected_mention_batch_fingerprint": graph[
                    "selected_identifier_mention_batch_fingerprint"
                ],
                "complete_resolution_fingerprint": graph[
                    "complete_identifier_resolution_fingerprint"
                ],
                "selected_resolution_fingerprint": graph[
                    "selected_identifier_resolution_fingerprint"
                ],
                "source_graph_policy_fingerprint": graph["source_graph_policy_fingerprint"],
                "source_identifier_adapter_fingerprint": graph[
                    "source_identifier_adapter_fingerprint"
                ],
                "relation_type_hash_set_fingerprint": graph["relation_type_hash_set_fingerprint"],
                "candidate_admission_profile_fingerprint": lexical["lexical_profile_fingerprint"],
                "complete_mention_count": graph["complete_identifier_mention_count"],
                "selected_mention_count": graph["selected_identifier_mention_count"],
                "complete_resolved_candidate_count": graph[
                    "complete_resolved_identifier_candidate_count"
                ],
                "selected_resolved_candidate_count": graph[
                    "selected_resolved_identifier_candidate_count"
                ],
                "overflow_count": 0,
                "candidate_graph_only": True,
                "canonical_write_allowed": False,
            },
            "manifest_bundle_identity_matches": True,
            "selected_observation_count": source["observation_count"],
            "loaded_observation_count": source["observation_count"],
            "source_observation_hash_count": source["observation_count"],
            "case_count": evaluation["evaluated_case_count"],
            "source_complete": False,
        },
        "shared_pipeline": {
            "lexical_profile_id": tokenizer_profile.tokenizer_id,
            "lexical_profile_fingerprint": lexical["lexical_profile_fingerprint"],
            "query_lexical_profile_fingerprint": lexical["query_profile_fingerprint"],
            "evidence_lexical_profile_fingerprint": lexical["evidence_profile_fingerprint"],
            "dense_model_id": runtime["dense_model_id"],
            "dense_model_revision": runtime["dense_model_revision"],
            "dense_profile_fingerprint": lexical["dense_profile_fingerprint"],
            "execution_component_fingerprint": lexical["runtime_component_fingerprint"],
            "execution_component_fingerprint_count": 1,
            "execution_component_fingerprint_set_hash": sha256_json(
                [lexical["runtime_component_fingerprint"]]
            ),
            "permission_scoped_index_count": lexical["index_count"],
            "permission_scoped_index_set_fingerprint": lexical["index_fingerprint"],
            "runtime_method_id": ISSUE56_TARGET_RUNTIME_METHOD_ID,
            "runtime_method_fingerprint": evaluation["runtime_method_fingerprint"],
            "graph_adapter_fingerprint": graph["graph_adapter_fingerprint"],
            "source_graph_policy_fingerprint": graph["source_graph_policy_fingerprint"],
            "source_identifier_adapter_fingerprint": graph["source_identifier_adapter_fingerprint"],
            "relation_type_hash_set_fingerprint": graph["relation_type_hash_set_fingerprint"],
            "ontology_target_fingerprint": graph["ontology_target_fingerprint"],
            "graph_builds": {
                "observation_node_count": graph["graph_node_count"],
                "entity_node_count": 0,
                "edge_count": graph["graph_edge_count"],
                "build_fingerprint_set_hash": graph["graph_artifact_fingerprint"],
                "ontology_revision_fingerprint_set_hash": graph["ontology_artifact_fingerprint"],
                "graph_adapter_fingerprint": graph["graph_adapter_fingerprint"],
                "source_graph_policy_fingerprint": graph["source_graph_policy_fingerprint"],
                "source_identifier_adapter_fingerprint": graph[
                    "source_identifier_adapter_fingerprint"
                ],
                "relation_type_hash_set_fingerprint": graph["relation_type_hash_set_fingerprint"],
                "source_identifier_candidate_artifact_fingerprint": graph[
                    "source_identifier_candidate_artifact_fingerprint"
                ],
                "source_identifier_candidate_binding_fingerprint": graph[
                    "source_identifier_candidate_binding_fingerprint"
                ],
                "candidate_artifact_schema_fingerprint": graph[
                    "source_identifier_candidate_schema_fingerprint"
                ],
                "identity_scope_mode_status": WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
                "identity_scope_mode_fingerprint": graph[
                    "source_identifier_identity_scope_mode_fingerprint"
                ],
                "identity_scope_fingerprint": graph["source_identifier_identity_scope_fingerprint"],
                "identity_scope_binding_fingerprint": graph[
                    "source_identifier_identity_scope_binding_fingerprint"
                ],
                "identity_scope_attestation_byte_sha256": graph[
                    "source_identifier_identity_scope_attestation_byte_fingerprint"
                ],
                "identity_scope_attestation_fingerprint": graph[
                    "source_identifier_identity_scope_attestation_fingerprint"
                ],
                "identity_scope_policy_fingerprint": graph[
                    "source_identifier_identity_scope_policy_fingerprint"
                ],
                "operator_approval_fingerprint": graph[
                    "source_identifier_operator_approval_fingerprint"
                ],
                "mode_approval_fingerprint": graph["source_identifier_mode_approval_fingerprint"],
                "extraction_policy_fingerprint": graph[
                    "source_identifier_extraction_policy_fingerprint"
                ],
                "resolution_policy_fingerprint": graph[
                    "source_identifier_resolution_policy_fingerprint"
                ],
                "identity_scope_graph_binding_fingerprint_set_hash": graph[
                    "source_identifier_identity_scope_graph_binding_set_fingerprint"
                ],
                "spec_approval_fingerprint": sha256_json("spec-approval"),
                "complete_identifier_mention_fingerprint_set_hash": graph[
                    "complete_identifier_mention_fingerprint_set_hash"
                ],
                "authorized_identifier_mention_fingerprint_set_hash": graph[
                    "authorized_identifier_mention_fingerprint_set_hash"
                ],
                "identifier_resolution_fingerprint_set_hash": graph[
                    "identifier_resolution_fingerprint_set_hash"
                ],
                "selected_identifier_mention_batch_fingerprint": graph[
                    "selected_identifier_mention_batch_fingerprint"
                ],
                "selected_identifier_resolution_fingerprint": graph[
                    "selected_identifier_resolution_fingerprint"
                ],
                "identifier_mention_count": graph["selected_identifier_mention_count"],
                "authorized_identifier_mention_count": graph["authorized_identifier_mention_count"],
                "selected_resolved_candidate_count": graph[
                    "selected_resolved_identifier_candidate_count"
                ],
                "candidate_graph_only": True,
                "human_review_complete": False,
            },
            "answer_model_id": ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID,
            "answer_model_fingerprint": answer["answer_model_fingerprint"],
            "answer_prompt_fingerprint": answer["answer_prompt_fingerprint"],
            "answer_budget_fingerprint": answer["answer_budget_fingerprint"],
            "evaluator_id": EVALUATOR_ID,
            "evaluator_fingerprint": evaluation["evaluator_fingerprint"],
            "all_arms_share_answer_model_prompt_budget_evaluator": True,
        },
        "quality_gate": quality_gate,
        "execution_environment": {
            "attestation_run_binding_fingerprint": source_binding,
            "code_attestation_fingerprint": code_attestation["artifact_fingerprint"],
            "code_tree_fingerprint": code_attestation["code_tree_fingerprint"],
            "code_tree_scope_fingerprint": code_attestation["code_tree_scope_fingerprint"],
            "image_attestation_fingerprint": image_attestation["artifact_fingerprint"],
            "image_reference_fingerprint": image_attestation["image_reference_fingerprint"],
            "image_id": image_attestation["image_id"],
            "image_metadata_fingerprint": image_attestation["image_metadata_fingerprint"],
            "authority_attestation_fingerprint": authority_attestation["artifact_fingerprint"],
            "authority_state_fingerprint": authority_attestation["authority_state_fingerprint"],
            "authority_execution_fingerprint": authority_attestation[
                "authority_execution_fingerprint"
            ],
            "authority_blocking_gate_set_fingerprint": authority_attestation[
                "blocking_gate_set_fingerprint"
            ],
            "authority_blocking_gate_count": authority_attestation["blocking_gate_count"],
            "source_completeness_gate_status": authority_attestation[
                "source_completeness_gate_status"
            ],
            "real_source_ablation_gate_status": authority_attestation[
                "real_source_ablation_gate_status"
            ],
            "methodology_ready_status": authority_attestation["methodology_ready_status"],
        },
        "claim_boundary": {
            "independent_holdout": False,
            "source_complete": False,
            "real_source_authority_gate_passed": False,
            "source_identifier_candidate_artifact_bound": True,
            "source_backed_candidate_graph_v2_bound": True,
            "methodology_ready": False,
            "methodology_complete": False,
            "issue56_complete": False,
            "production_ready": False,
            "supports_arm_superiority_claim": False,
        },
    }


def _bind_uat_report(
    payload: dict[str, object],
    uat_report: dict[str, object],
) -> dict[str, object]:
    bound = copy.deepcopy(payload)
    evaluation = bound["evaluation_component"]
    evaluation.update(
        {
            "quality_gate_report_fingerprint": sha256_json(uat_report["quality_gate"]),
            "uat_report_fingerprint": _sha256_bytes(_serialized_json_bytes(uat_report)),
            "uat_content_fingerprint": sha256_json(uat_report),
            "uat_run_fingerprint": uat_report["diagnostic_run_fingerprint"],
            "runtime_method_fingerprint": uat_report["shared_pipeline"][
                "runtime_method_fingerprint"
            ],
            "quality_gate_status": uat_report["quality_gate_status"],
        }
    )
    bound["evaluation_component"] = seal_safe_artifact(evaluation)
    return seal_safe_artifact(bound)


def _serialized_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _image_attestation() -> tuple[str, str]:
    return (
        os.environ.get("FORMOWL_CANONICAL_IMAGE_ID", DEFAULT_TEST_IMAGE_ID),
        os.environ.get(
            "FORMOWL_CANONICAL_IMAGE_METADATA_FINGERPRINT",
            DEFAULT_TEST_IMAGE_METADATA,
        ),
    )


def _assert_rejected(
    test_case: unittest.TestCase,
    result: _CliResult,
    expected_reason: str,
) -> None:
    test_case.assertEqual(result.returncode, 3, result.stderr)
    report = json.loads(result.stdout)
    test_case.assertEqual(report["status"], "rejected")
    test_case.assertEqual(report["rejection_status_id"], expected_reason)
    test_case.assertEqual(report["rejection_count"], 1)
    assert_no_public_raw_references(
        report,
        "issue56_execution_fingerprint_rejection_test",
    )


def _assert_direct_uat_rejected(
    test_case: unittest.TestCase,
    *,
    payload: dict[str, object],
    uat_report: dict[str, object],
    image_id: str,
    image_metadata: str,
    expected_reason: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="issue56-uat-binding-direct-") as temp_dir:
        report_path = Path(temp_dir) / "uat.safe.json"
        report_bytes = _serialized_json_bytes(uat_report)
        report_path.write_bytes(report_bytes)
        with test_case.assertRaisesRegex(
            RuntimeError,
            f"^{expected_reason}$",
        ):
            _load_and_validate_completed_uat_report(
                report_path=report_path,
                expected_report_fingerprint=_sha256_bytes(report_bytes),
                validated_components=payload,
                repository_root=ROOT,
                canonical_image_id=image_id,
                canonical_image_metadata_fingerprint=image_metadata,
            )


if __name__ == "__main__":
    unittest.main()
