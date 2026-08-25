from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    Observation,
    PermissionScope,
    SourceInventory,
    SourceInventoryItem,
    SourceInventoryProcessingState,
    SourceInventoryRawRetentionState,
    sha256_json,
)
from formowl_core import ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
from formowl_ingestion.storage.records import ObservationStore

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import issue56_source_identifier_candidates as candidates  # noqa: E402
from scripts import issue56_identity_scope_attestation as identity_attestation  # noqa: E402
from scripts import issue56_materialize_development_uat_observations as materializer  # noqa: E402


CREATED_AT = "2026-08-19T10:00:00+00:00"
TENANT_ID = "tenant_issue56_candidates"
WORKSPACE_ID = "workspace_issue56_candidates"


class Issue56SourceIdentifierCandidatesE2ETests(unittest.TestCase):
    def test_workspace_only_candidate_artifact_binds_canonical_456_record_work_dir(
        self,
    ) -> None:
        texts = [
            "已核對 BOUND-0001。",
            "核准聯絡 owner@example.com。",
            *["一般郵件內容。" for _ in range(454)],
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(root / "inputs", texts=texts)
            materialized = _write_materialized_subset(
                root / "development-work",
                inputs=inputs,
            )
            identity = _write_identity_attestation(
                root / "identity",
                inputs=inputs,
                mode=identity_attestation.WORKSPACE_ONLY_MODE,
                tenant_id=None,
                workspace_id="workspace_formowl",
                spec_approval_id="spec_issue56_workspace_only_materialized_fixture",
            )
            output = root / "candidate-output"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = candidates.main(
                    [
                        "--retrieval-snapshot",
                        str(inputs.snapshot_path),
                        "--expected-retrieval-snapshot-sha256",
                        inputs.snapshot_sha256,
                        "--retrieval-report",
                        str(inputs.report_path),
                        "--expected-retrieval-report-sha256",
                        inputs.report_sha256,
                        "--identity-scope-attestation",
                        str(identity.path),
                        "--expected-identity-scope-attestation-sha256",
                        identity.sha256,
                        "--materialized-work-dir",
                        str(materialized.root),
                        "--expected-materialization-artifact-sha256",
                        materialized.private_sha256,
                        "--expected-materialization-safe-report-sha256",
                        materialized.safe_sha256,
                        "--output-root",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            safe = json.loads(stdout.getvalue())
            private = json.loads(
                (output / candidates.PRIVATE_ARTIFACT_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                private["observation_selection_binding"]["mode"],
                candidates.MATERIALIZED_SELECTION_MODE,
            )
            self.assertEqual(
                private["observation_selection_binding"]["materialization_artifact_byte_sha256"],
                materialized.private_sha256,
            )
            self.assertEqual(
                private["observation_selection_binding"]["materialization_safe_report_byte_sha256"],
                materialized.safe_sha256,
            )
            self.assertEqual(private["counts"]["source_observation_count"], 456)
            self.assertEqual(
                private["counts"]["candidate_source_observation_count"],
                456,
            )
            self.assertEqual(
                safe["observation_selection_status"], candidates.MATERIALIZED_SELECTION_MODE
            )
            self.assertEqual(safe["counts"]["source_observation_count"], 456)
            self.assertEqual(safe["counts"]["overflow_count"], 0)
            self.assertGreater(safe["counts"]["identifier_occurrence_count"], 0)
            self.assertNotIn(
                '"tenant_id"',
                (output / candidates.PRIVATE_ARTIFACT_FILENAME).read_text(encoding="utf-8"),
            )
            candidates.validate_private_identifier_candidate_artifact(private)
            candidates.validate_safe_identifier_candidate_report(
                safe,
                private_artifact_bytes=(output / candidates.PRIVATE_ARTIFACT_FILENAME).read_bytes(),
            )

            first_record = next(
                (materialized.root / materializer.OBSERVATION_RELATIVE_DIRECTORY).glob("*.json")
            )
            first_record.write_bytes(first_record.read_bytes() + b" ")
            failed_output = root / "candidate-tampered-output"
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "materialization_observation_record_byte_seal_mismatch",
            ):
                _build_with_identity(
                    inputs,
                    failed_output,
                    identity,
                    materialized=materialized,
                )
            self.assertFalse(failed_output.exists())

    def test_cli_builds_full_candidate_only_artifact_without_first_24_loss(self) -> None:
        identifiers = [f"CASE-{index:04d}" for index in range(1, 31)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=[
                    "完整清單 " + " ".join(identifiers),
                    "第二封郵件再次引用 CASE-0001 與 owner@example.com。",
                ],
            )
            output_root = root / "candidate-artifact"
            identity = _write_identity_attestation(
                root / "identity-scope",
                inputs=inputs,
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = candidates.main(
                    [
                        "--retrieval-snapshot",
                        str(inputs.snapshot_path),
                        "--expected-retrieval-snapshot-sha256",
                        inputs.snapshot_sha256,
                        "--retrieval-report",
                        str(inputs.report_path),
                        "--expected-retrieval-report-sha256",
                        inputs.report_sha256,
                        "--identity-scope-attestation",
                        str(identity.path),
                        "--expected-identity-scope-attestation-sha256",
                        identity.sha256,
                        "--output-root",
                        str(output_root),
                    ]
                )

            self.assertEqual(exit_code, 0)
            public = json.loads(stdout.getvalue())
            private = json.loads(
                (output_root / candidates.PRIVATE_ARTIFACT_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(public["counts"]["identifier_occurrence_count"], 32)
            self.assertEqual(public["counts"]["resolved_candidate_count"], 31)
            self.assertEqual(public["counts"]["overflow_count"], 0)
            self.assertTrue(private["candidate_only"])
            self.assertFalse(private["canonical_write_allowed"])
            self.assertEqual(private["created_at"], CREATED_AT)
            self.assertEqual(
                private["mention_batch"]["tokenizer_profile_fingerprint"],
                ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
            )
            self.assertEqual(
                {
                    mention["created_at"]
                    for mention in private["mention_batch"]["candidate_mentions"]
                },
                {CREATED_AT},
            )
            self.assertEqual(
                public["private_artifact_byte_sha256"],
                _sha256_path(output_root / candidates.PRIVATE_ARTIFACT_FILENAME),
            )
            candidates.validate_private_identifier_candidate_artifact(private)
            candidates.validate_safe_identifier_candidate_report(
                public,
                private_artifact_bytes=(
                    output_root / candidates.PRIVATE_ARTIFACT_FILENAME
                ).read_bytes(),
            )

    def test_same_sealed_inputs_are_byte_deterministic_and_safe_report_is_private_free(
        self,
    ) -> None:
        raw_identifier = "CONFIDENTIAL-771"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=[
                    f"專案追蹤 {raw_identifier} 與 protected@example.com。",
                    f"另一 occurrence 再次引用 {raw_identifier}。",
                ],
            )
            first = _build(inputs, root / "first")
            second = _build(inputs, root / "second")

            self.assertEqual(first.private_artifact, second.private_artifact)
            self.assertEqual(first.safe_report, second.safe_report)
            self.assertEqual(
                first.private_artifact_path.read_bytes(),
                second.private_artifact_path.read_bytes(),
            )
            self.assertEqual(
                first.safe_report_path.read_bytes(),
                second.safe_report_path.read_bytes(),
            )
            rendered_safe = first.safe_report_path.read_text(encoding="utf-8")
            for forbidden in (
                raw_identifier,
                "protected@example.com",
                "obs_message_0001",
                "source_message_0001",
                TENANT_ID,
                WORKSPACE_ID,
                str(root),
                "oracle",
            ):
                self.assertNotIn(forbidden, rendered_safe)
            self.assertEqual(
                set(first.safe_report),
                candidates._SAFE_REPORT_KEYS,
            )

    def test_input_tamper_profile_and_snapshot_report_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=["請處理 DRIFT-101。"],
            )
            tampered_bytes = inputs.snapshot_path.read_bytes() + b" "
            inputs.snapshot_path.write_bytes(tampered_bytes)
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "retrieval_snapshot_byte_seal_mismatch",
            ):
                _build(inputs, root / "tampered")

            profile_drift = _write_retrieval_inputs(
                root / "profile-drift",
                texts=["請處理 DRIFT-202。"],
                tokenizer_profile_fingerprint=sha256_json("wrong-profile"),
            )
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "target_tokenizer_profile_drift",
            ):
                _build(profile_drift, root / "profile-output")

            cross_drift = _write_retrieval_inputs(
                root / "cross-drift",
                texts=["請處理 DRIFT-303。"],
                report_source_snapshot_fingerprint=sha256_json("wrong-source"),
            )
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "retrieval_snapshot_report_binding_drift",
            ):
                _build(cross_drift, root / "cross-output")

    def test_explicit_overflow_blocks_before_any_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=[" ".join(f"OVERFLOW-{index:04d}" for index in range(25))],
            )
            output_root = root / "overflow-output"
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "source_bound_identifier_occurrence_overflow",
            ):
                _build(
                    inputs,
                    output_root,
                    max_identifier_occurrences=24,
                )
            self.assertFalse(output_root.exists())

    def test_permission_and_identity_scope_bindings_isolate_exact_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            alpha = _write_retrieval_inputs(
                root / "alpha-input",
                texts=["共同識別碼 SHARED-501。"],
                permission_scope=PermissionScope.project("project_alpha"),
            )
            beta = _write_retrieval_inputs(
                root / "beta-input",
                texts=["共同識別碼 SHARED-501。"],
                permission_scope=PermissionScope.project("project_beta"),
            )
            alpha_artifacts = _build(alpha, root / "alpha-output")
            beta_artifacts = _build(beta, root / "beta-output")
            other_workspace = _build(
                alpha,
                root / "other-workspace-output",
                workspace_id="workspace_issue56_other",
            )

            alpha_candidate = alpha_artifacts.private_artifact["resolution"]["candidates"][0]
            beta_candidate = beta_artifacts.private_artifact["resolution"]["candidates"][0]
            other_candidate = other_workspace.private_artifact["resolution"]["candidates"][0]
            self.assertNotEqual(
                alpha_candidate["permission_boundary_fingerprint"],
                beta_candidate["permission_boundary_fingerprint"],
            )
            self.assertNotEqual(
                alpha_candidate["candidate_resolution_id"],
                beta_candidate["candidate_resolution_id"],
            )
            self.assertNotEqual(
                alpha_candidate["candidate_resolution_id"],
                other_candidate["candidate_resolution_id"],
            )
            self.assertNotEqual(
                alpha_artifacts.safe_report["identity_scope_fingerprint"],
                other_workspace.safe_report["identity_scope_fingerprint"],
            )

    def test_existing_output_and_second_staged_write_failure_leave_no_partial_pair(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=["原子寫入 ATOMIC-101。"],
            )
            existing_root = root / "existing"
            existing_root.mkdir()
            marker = existing_root / "marker"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "immutable_output_already_exists",
            ):
                _build(inputs, existing_root)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

            failed_root = root / "failed"
            call_count = 0

            def fail_second(path: Path, payload: bytes) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise candidates.SourceIdentifierCandidateError("injected_second_write_failure")
                candidates._write_file_exclusive(path, payload)

            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "injected_second_write_failure",
            ):
                candidates.build_source_identifier_candidate_artifacts(
                    retrieval_snapshot_path=inputs.snapshot_path,
                    expected_retrieval_snapshot_sha256=inputs.snapshot_sha256,
                    retrieval_report_path=inputs.report_path,
                    expected_retrieval_report_sha256=inputs.report_sha256,
                    identity_scope_attestation_path=(
                        _write_identity_attestation(
                            root / "failed-identity-scope",
                            inputs=inputs,
                        ).path
                    ),
                    expected_identity_scope_attestation_sha256=(
                        _sha256_path(
                            root
                            / "failed-identity-scope"
                            / identity_attestation.PRIVATE_ARTIFACT_FILENAME
                        )
                    ),
                    output_root=failed_root,
                    _write_staged_file=fail_second,
                )
            self.assertEqual(call_count, 2)
            self.assertFalse(failed_root.exists())
            self.assertEqual(
                list(root.glob(f".{failed_root.name}.staging-*")),
                [],
            )

    def test_builder_supports_both_attested_modes_and_rejects_attestation_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=["驗證 ATTESTED-101。"],
            )
            mismatches = (
                (
                    "source",
                    {"source_fingerprint": sha256_json("different-source")},
                    "identity_scope_attestation_source_mismatch",
                ),
                (
                    "permission",
                    {"permission_fingerprint": sha256_json("different-permission")},
                    "identity_scope_attestation_permission_mismatch",
                ),
                (
                    "asset",
                    {"asset_id": "asset_issue56_different_fixture"},
                    "identity_scope_attestation_asset_mismatch",
                ),
            )
            for label, overrides, reason_code in mismatches:
                mismatched = _write_identity_attestation(
                    root / f"mismatched-{label}",
                    inputs=inputs,
                    **overrides,
                )
                with (
                    self.subTest(label=label),
                    self.assertRaisesRegex(
                        candidates.SourceIdentifierCandidateError,
                        reason_code,
                    ),
                ):
                    _build_with_identity(
                        inputs,
                        root / f"mismatch-{label}-output",
                        mismatched,
                    )

            workspace_only = _write_identity_attestation(
                root / "workspace-only",
                inputs=inputs,
                mode=identity_attestation.WORKSPACE_ONLY_MODE,
                tenant_id=None,
                spec_approval_id="spec_approval_issue56_candidate_fixture",
            )
            workspace_first = _build_with_identity(
                inputs,
                root / "workspace-only-output",
                workspace_only,
            )
            workspace_second = _build_with_identity(
                inputs,
                root / "workspace-only-output-second",
                workspace_only,
            )
            self.assertEqual(
                workspace_first.private_artifact,
                workspace_second.private_artifact,
            )
            self.assertEqual(
                workspace_first.safe_report,
                workspace_second.safe_report,
            )
            self.assertEqual(
                workspace_first.safe_report["identity_scope_mode_status"],
                identity_attestation.WORKSPACE_ONLY_MODE,
            )
            workspace_private_text = workspace_first.private_artifact_path.read_text(
                encoding="utf-8"
            )
            self.assertNotIn('"tenant_id"', workspace_private_text)
            tenant_artifacts = _build(inputs, root / "tenant-mode-output")
            self.assertNotEqual(
                workspace_first.private_artifact["resolution"]["candidates"][0][
                    "candidate_resolution_id"
                ],
                tenant_artifacts.private_artifact["resolution"]["candidates"][0][
                    "candidate_resolution_id"
                ],
            )
            approval_tamper = deepcopy(workspace_first.private_artifact)
            approval_tamper["identity_scope_binding"]["operator_approval_fingerprint"] = (
                sha256_json("different-operator-approval")
            )
            approval_tamper["artifact_fingerprint"] = candidates._payload_fingerprint(
                approval_tamper,
                "artifact_fingerprint",
            )
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "private_artifact_mention_batch_binding_drift",
            ):
                candidates.validate_private_identifier_candidate_artifact(approval_tamper)

            tampered_path = root / "tampered-attestation.json"
            valid = _write_identity_attestation(root / "valid", inputs=inputs)
            tampered_path.write_bytes(valid.path.read_bytes() + b" ")
            tampered = _IdentityAttestationInput(
                path=tampered_path,
                sha256=valid.sha256,
            )
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "identity_scope_attestation_byte_seal_mismatch",
            ):
                _build_with_identity(inputs, root / "tampered-output", tampered)

    def test_private_artifact_round_trip_tamper_rejects_resolution_and_byte_seal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=["驗證 TAMPER-901。"],
            )
            artifacts = _build(inputs, root / "output")
            tampered = deepcopy(artifacts.private_artifact)
            tampered["resolution"]["candidates"][0]["permission_boundary_fingerprint"] = (
                sha256_json("tampered")
            )
            tampered["artifact_fingerprint"] = candidates._payload_fingerprint(
                tampered,
                "artifact_fingerprint",
            )
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "private_artifact_resolution_replay_drift",
            ):
                candidates.validate_private_identifier_candidate_artifact(tampered)

            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "safe_report_private_byte_seal_mismatch",
            ):
                candidates.validate_safe_identifier_candidate_report(
                    artifacts.safe_report,
                    private_artifact_bytes=artifacts.private_artifact_path.read_bytes() + b" ",
                )
            safe_tamper = deepcopy(artifacts.safe_report)
            safe_tamper["counts"]["identifier_occurrence_count"] += 1
            safe_tamper["report_fingerprint"] = candidates._payload_fingerprint(
                safe_tamper,
                "report_fingerprint",
            )
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "safe_report_private_count_drift",
            ):
                candidates.validate_safe_identifier_candidate_report(
                    safe_tamper,
                    private_artifact_bytes=artifacts.private_artifact_path.read_bytes(),
                )

            legacy = deepcopy(artifacts.private_artifact)
            legacy["artifact_id"] = "formowl_issue56_source_identifier_candidates_private_v2"
            legacy["schema_version"] = 2
            legacy["artifact_fingerprint"] = candidates._payload_fingerprint(
                legacy,
                "artifact_fingerprint",
            )
            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "private_artifact_id_invalid",
            ):
                candidates.validate_private_identifier_candidate_artifact(legacy)

    def test_resealed_safe_report_rejects_retrieval_snapshot_byte_seal_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=["驗證 SNAPSHOT-SEAL-901。"],
            )
            artifacts = _build(inputs, root / "output")
            tampered = deepcopy(artifacts.safe_report)
            tampered["retrieval_snapshot_byte_sha256"] = sha256_json(
                "different-retrieval-snapshot-bytes"
            )
            tampered["report_fingerprint"] = candidates._payload_fingerprint(
                tampered,
                "report_fingerprint",
            )

            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "safe_report_private_binding_drift",
            ):
                candidates.validate_safe_identifier_candidate_report(
                    tampered,
                    private_artifact_bytes=artifacts.private_artifact_path.read_bytes(),
                )

    def test_resealed_safe_report_rejects_retrieval_report_byte_seal_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs = _write_retrieval_inputs(
                root / "inputs",
                texts=["驗證 REPORT-SEAL-901。"],
            )
            artifacts = _build(inputs, root / "output")
            tampered = deepcopy(artifacts.safe_report)
            tampered["retrieval_report_byte_sha256"] = sha256_json(
                "different-retrieval-report-bytes"
            )
            tampered["report_fingerprint"] = candidates._payload_fingerprint(
                tampered,
                "report_fingerprint",
            )

            with self.assertRaisesRegex(
                candidates.SourceIdentifierCandidateError,
                "safe_report_private_binding_drift",
            ):
                candidates.validate_safe_identifier_candidate_report(
                    tampered,
                    private_artifact_bytes=artifacts.private_artifact_path.read_bytes(),
                )


class _RetrievalInputs:
    def __init__(
        self,
        *,
        snapshot_path: Path,
        report_path: Path,
        snapshot_sha256: str,
        report_sha256: str,
        source_asset_id: str,
        source_asset_sha256: str,
        source_snapshot_fingerprint: str,
        permission_fingerprint: str,
    ) -> None:
        self.snapshot_path = snapshot_path
        self.report_path = report_path
        self.snapshot_sha256 = snapshot_sha256
        self.report_sha256 = report_sha256
        self.source_asset_id = source_asset_id
        self.source_asset_sha256 = source_asset_sha256
        self.source_snapshot_fingerprint = source_snapshot_fingerprint
        self.permission_fingerprint = permission_fingerprint


class _IdentityAttestationInput:
    def __init__(self, *, path: Path, sha256: str) -> None:
        self.path = path
        self.sha256 = sha256


class _MaterializedSubsetInput:
    def __init__(
        self,
        *,
        root: Path,
        private_sha256: str,
        safe_sha256: str,
    ) -> None:
        self.root = root
        self.private_sha256 = private_sha256
        self.safe_sha256 = safe_sha256


def _write_retrieval_inputs(
    root: Path,
    *,
    texts: list[str],
    permission_scope: PermissionScope | None = None,
    tokenizer_profile_fingerprint: str = (ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT),
    report_source_snapshot_fingerprint: str | None = None,
) -> _RetrievalInputs:
    root.mkdir(parents=True)
    permission_scope = permission_scope or PermissionScope.project("project_issue56")
    source_asset_id = "asset_issue56_source_identifier_fixture"
    source_asset_sha256 = sha256_json("source-asset")
    parser_fingerprint = sha256_json("parser")
    provenance_fingerprint = sha256_json("source-provenance")
    items: list[SourceInventoryItem] = []
    observations: list[Observation] = []
    for ordinal, text in enumerate(texts, start=1):
        message_content_hash = sha256_json(
            {
                "ordinal": ordinal,
                "text": text,
                "permission": permission_scope.to_dict(),
            }
        )
        source_local_key = f"source_message_{ordinal:04d}"
        item = SourceInventoryItem.create(
            source_asset_id=source_asset_id,
            structure_kind="email_message_occurrence",
            content_type="message/rfc822",
            ordinal=ordinal,
            processing_state=SourceInventoryProcessingState.PARSED,
            raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
            source_fingerprint=source_asset_sha256,
            parser_fingerprint=parser_fingerprint,
            permission_scope=permission_scope.to_dict(),
            location={
                "source_local_key": source_local_key,
                "message_content_hash": message_content_hash,
            },
        )
        items.append(item)
        message_occurrence_id = f"message_occurrence_{ordinal:04d}"
        observations.append(
            Observation.from_dict(
                {
                    "observation_id": f"obs_message_{ordinal:04d}",
                    "asset_id": source_asset_id,
                    "extractor_run_id": "run_issue56_native_mail_fixture",
                    "observation_type": "email_body_segment",
                    "modality": "mail",
                    "location": {
                        "source_inventory_item_id": item.source_inventory_item_id,
                        "source_local_key": source_local_key,
                        "source_content_hash": message_content_hash,
                        "source_provenance_fingerprint": provenance_fingerprint,
                        "message_occurrence_id": message_occurrence_id,
                        "segment_ordinal": 1,
                    },
                    "text": text,
                    "payload": {
                        "canonical_fact_status": "not_asserted",
                        "message_occurrence_id": message_occurrence_id,
                    },
                    "confidence": 1.0,
                    "permission_scope": permission_scope.to_dict(),
                    "created_at": CREATED_AT,
                }
            )
        )
    inventory = SourceInventory.create(
        source_asset_id=source_asset_id,
        items=items,
        source_fingerprint=source_asset_sha256,
        parser_fingerprint=parser_fingerprint,
        created_at=CREATED_AT,
    )
    counts = {
        "source_inventory_item_count": len(items),
        "source_occurrence_observation_count": 0,
        "parsed_observation_count": len(observations),
        "retrieval_snapshot_observation_count": len(observations),
        "missing_source_inventory_binding_count": 0,
        "missing_source_local_key_binding_count": 0,
        "missing_content_hash_binding_count": 0,
        "missing_permission_binding_count": 0,
        "unexplained_loss_count": 0,
        "blocker_count": 0,
    }
    source_snapshot_fingerprint = sha256_json("source-snapshot")
    snapshot = {
        "artifact_id": candidates.RETRIEVAL_SNAPSHOT_ARTIFACT_ID,
        "schema_version": candidates.SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": "retrieval_ready_evidence_not_canonical_fact",
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "source_asset_sha256": source_asset_sha256,
        "native_manifest_fingerprint": sha256_json("native-manifest"),
        "source_inventory_fingerprint": sha256_json(inventory.to_dict()),
        "source_provenance_fingerprint": provenance_fingerprint,
        "permission_fingerprint": sha256_json(permission_scope.to_dict()),
        "parsed_observation_fingerprint": sha256_json(
            [observation.to_dict() for observation in observations]
        ),
        "mail_evidence_bundle_fingerprint": sha256_json("bundle"),
        "tokenizer_profile_fingerprint": tokenizer_profile_fingerprint,
        "observation_snapshot_fingerprint": sha256_json("observation-snapshot"),
        "candidate_manifest_fingerprint": sha256_json("candidate-manifest"),
        "index_fingerprint": sha256_json("index"),
        "query_fingerprint": sha256_json("query"),
        "authorized_result_fingerprint": sha256_json("authorized-result"),
        "denied_result_fingerprint": sha256_json("denied-result"),
        "created_at": CREATED_AT,
        "source_inventory": inventory.to_dict(),
        "source_occurrence_observations": [],
        "parsed_mail_observations": [observation.to_dict() for observation in observations],
        "counts": counts,
        "blocker_fingerprints": [],
    }
    snapshot["snapshot_fingerprint"] = candidates._payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    )
    report = {
        "artifact_id": candidates.RETRIEVAL_REPORT_ARTIFACT_ID,
        "schema_version": candidates.SCHEMA_VERSION,
        "status": "passed",
        "source_completeness_status": "passed",
        "retrieval_ready_status": "passed",
        "target_profile_status": "passed_no_ascii_fallback",
        "canonical_fact_status": "not_asserted",
        "methodology_readiness_status": "blocked",
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "source_snapshot_fingerprint": (
            report_source_snapshot_fingerprint or source_snapshot_fingerprint
        ),
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "parsed_observation_fingerprint": snapshot["parsed_observation_fingerprint"],
        "candidate_admission_profile_fingerprint": (tokenizer_profile_fingerprint),
        "index_fingerprint": snapshot["index_fingerprint"],
        "counts": counts,
        "blocker_fingerprints": [],
    }
    report["report_fingerprint"] = candidates._payload_fingerprint(
        report,
        "report_fingerprint",
    )
    snapshot_path = root / "retrieval-snapshot.private.json"
    report_path = root / "retrieval-report.safe.json"
    snapshot_path.write_bytes(_json_bytes(snapshot))
    report_path.write_bytes(_json_bytes(report))
    return _RetrievalInputs(
        snapshot_path=snapshot_path,
        report_path=report_path,
        snapshot_sha256=_sha256_path(snapshot_path),
        report_sha256=_sha256_path(report_path),
        source_asset_id=source_asset_id,
        source_asset_sha256=source_asset_sha256,
        source_snapshot_fingerprint=source_snapshot_fingerprint,
        permission_fingerprint=sha256_json(permission_scope.to_dict()),
    )


def _build(
    inputs: _RetrievalInputs,
    output_root: Path,
    *,
    mode: str = identity_attestation.TENANT_WORKSPACE_MODE,
    tenant_id: str | None = TENANT_ID,
    workspace_id: str = WORKSPACE_ID,
    spec_approval_id: str | None = None,
    max_identifier_occurrences: int | None = None,
) -> candidates.SourceIdentifierCandidateArtifacts:
    identity = _write_identity_attestation(
        output_root.parent / f"{output_root.name}-identity-scope",
        inputs=inputs,
        mode=mode,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        spec_approval_id=spec_approval_id,
    )
    return _build_with_identity(
        inputs,
        output_root,
        identity,
        max_identifier_occurrences=max_identifier_occurrences,
    )


def _build_with_identity(
    inputs: _RetrievalInputs,
    output_root: Path,
    identity: _IdentityAttestationInput,
    *,
    max_identifier_occurrences: int | None = None,
    materialized: _MaterializedSubsetInput | None = None,
) -> candidates.SourceIdentifierCandidateArtifacts:
    return candidates.build_source_identifier_candidate_artifacts(
        retrieval_snapshot_path=inputs.snapshot_path,
        expected_retrieval_snapshot_sha256=inputs.snapshot_sha256,
        retrieval_report_path=inputs.report_path,
        expected_retrieval_report_sha256=inputs.report_sha256,
        identity_scope_attestation_path=identity.path,
        expected_identity_scope_attestation_sha256=identity.sha256,
        materialized_work_dir=(materialized.root if materialized is not None else None),
        expected_materialization_artifact_sha256=(
            materialized.private_sha256 if materialized is not None else None
        ),
        expected_materialization_safe_report_sha256=(
            materialized.safe_sha256 if materialized is not None else None
        ),
        output_root=output_root,
        max_identifier_occurrences=max_identifier_occurrences,
    )


def _write_identity_attestation(
    root: Path,
    *,
    inputs: _RetrievalInputs,
    mode: str = identity_attestation.TENANT_WORKSPACE_MODE,
    tenant_id: str | None = TENANT_ID,
    workspace_id: str = WORKSPACE_ID,
    source_fingerprint: str | None = None,
    permission_fingerprint: str | None = None,
    asset_id: str | None = None,
    spec_approval_id: str | None = None,
) -> _IdentityAttestationInput:
    identity_attestation.create_identity_scope_attestation_artifacts(
        output_root=root,
        mode=mode,
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        asset_id=asset_id or inputs.source_asset_id,
        asset_content_hash=inputs.source_asset_sha256,
        source_fingerprint=(source_fingerprint or inputs.source_snapshot_fingerprint),
        permission_fingerprint=(permission_fingerprint or inputs.permission_fingerprint),
        approver_actor="actor_issue56_candidate_fixture_operator",
        authority_source="authority_issue56_candidate_fixture_decision",
        approved_at=CREATED_AT,
        reason="Fixture operator approved this bounded candidate source identity scope.",
        operator_approved=True,
        spec_approval_id=spec_approval_id,
    )
    path = root / identity_attestation.PRIVATE_ARTIFACT_FILENAME
    return _IdentityAttestationInput(path=path, sha256=_sha256_path(path))


def _write_materialized_subset(
    root: Path,
    *,
    inputs: _RetrievalInputs,
) -> _MaterializedSubsetInput:
    snapshot = json.loads(inputs.snapshot_path.read_text(encoding="utf-8"))
    retrieval_report = json.loads(inputs.report_path.read_text(encoding="utf-8"))
    observations = [Observation.from_dict(row) for row in snapshot["parsed_mail_observations"]]
    if len(observations) != materializer.EXPECTED_MATERIALIZED_OBSERVATION_COUNT:
        raise AssertionError("fixture must contain exactly 456 Observations")
    observation_by_id = {item.observation_id: item for item in observations}
    selected_ids = tuple(sorted(observation_by_id))
    adjudicated_ids = selected_ids[: materializer.EXPECTED_ADJUDICATED_OBSERVATION_COUNT]
    decoy_ids = selected_ids[materializer.EXPECTED_ADJUDICATED_OBSERVATION_COUNT :]
    observation_store = ObservationStore(root / "data")
    for observation_id in selected_ids:
        observation_store.create(observation_by_id[observation_id])
    records = materializer._validated_staged_record_inventory(
        staging=root,
        selected_ids=selected_ids,
        adjudicated_ids=frozenset(adjudicated_ids),
        observation_by_id=observation_by_id,
    )
    bundle_artifact = {
        "artifact_fingerprint": sha256_json("materialized-bundle-artifact"),
        "bundle_fingerprint": sha256_json("materialized-mail-bundle"),
    }
    manifest = {"manifest_fingerprint": sha256_json("development-manifest")}
    private = materializer._private_artifact(
        snapshot=snapshot,
        snapshot_byte_sha256=inputs.snapshot_sha256,
        bundle_artifact=bundle_artifact,
        bundle_byte_sha256=sha256_json("bundle-bytes"),
        retrieval_report=retrieval_report,
        retrieval_report_byte_sha256=inputs.report_sha256,
        manifest=manifest,
        manifest_byte_sha256=sha256_json("manifest-bytes"),
        adjudicated_ids=adjudicated_ids,
        decoy_ids=decoy_ids,
        eligible_decoy_count=len(decoy_ids),
        records=records,
        record_inventory_fingerprint=sha256_json(records),
        selection_proof_fingerprint=sha256_json(
            {
                "selected_observation_ids": list(selected_ids),
                "fixture_policy": "sealed_source_only_v1",
            }
        ),
    )
    materializer.validate_private_materialization_artifact(private)
    private_bytes = _json_bytes(private)
    safe = materializer._safe_report(
        snapshot=snapshot,
        bundle_artifact=bundle_artifact,
        retrieval_report=retrieval_report,
        manifest=manifest,
        private_artifact=private,
        private_artifact_bytes=private_bytes,
    )
    materializer.validate_safe_materialization_report(
        safe,
        private_artifact_bytes=private_bytes,
    )
    (root / materializer.PRIVATE_ARTIFACT_FILENAME).write_bytes(private_bytes)
    (root / materializer.SAFE_REPORT_FILENAME).write_bytes(_json_bytes(safe))
    return _MaterializedSubsetInput(
        root=root,
        private_sha256=_sha256_path(root / materializer.PRIVATE_ARTIFACT_FILENAME),
        safe_sha256=_sha256_path(root / materializer.SAFE_REPORT_FILENAME),
    )


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256_path(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


if __name__ == "__main__":
    unittest.main()
