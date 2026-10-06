from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

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
from formowl_mail import build_mail_evidence_bundle

from scripts import issue56_materialize_development_uat_observations as materializer
from scripts import issue56_simulated_uat as simulated_uat
from scripts import issue56_source_development_uat_manifest as development_manifest


CREATED_AT = "2026-08-19T10:00:00+00:00"


class Issue56DevelopmentUatObservationMaterializationE2ETests(unittest.TestCase):
    def test_cli_materializes_exact_200_plus_256_and_runner_loads_456(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = _write_fixture(root / "inputs")
            output = root / "materialized"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = materializer.main(_cli_args(fixture=fixture, output=output))

            self.assertEqual(exit_code, 0)
            safe_report = json.loads(stdout.getvalue())
            self.assertEqual(safe_report["status"], "passed")
            self.assertEqual(
                safe_report["counts"]["adjudicated_observation_count"],
                200,
            )
            self.assertEqual(
                safe_report["counts"]["decoy_observation_count"],
                256,
            )
            self.assertEqual(
                safe_report["counts"]["materialized_observation_count"],
                456,
            )
            observation_paths = sorted(
                (output / materializer.OBSERVATION_RELATIVE_DIRECTORY).glob("*.json")
            )
            self.assertEqual(len(observation_paths), 456)

            private_bytes = (output / materializer.PRIVATE_ARTIFACT_FILENAME).read_bytes()
            private = json.loads(private_bytes)
            materializer.validate_private_materialization_artifact(private)
            materializer.validate_safe_materialization_report(
                safe_report,
                private_artifact_bytes=private_bytes,
            )
            bundle, subset = simulated_uat._bounded_preserved_projection(
                bundle_payload=fixture.bundle_artifact["bundle"],
                manifest=fixture.manifest,
                manifest_byte_hash=fixture.manifest_sha256,
                observations_directory=(output / materializer.OBSERVATION_RELATIVE_DIRECTORY),
            )
            loaded = subset[bundle.mail_evidence_bundle_id]
            self.assertEqual(subset.selected_observation_count, 456)
            self.assertEqual(subset.loaded_observation_count, 456)
            self.assertEqual(len(loaded), 456)
            self.assertEqual(
                len(subset.source_observation_hash_by_id),
                456,
            )
            safe_serialized = json.dumps(
                safe_report,
                ensure_ascii=True,
                sort_keys=True,
            )
            self.assertNotIn("obs_body_", safe_serialized)
            self.assertNotIn("Synthetic evidence", safe_serialized)
            self.assertNotIn(str(root), safe_serialized)

    def test_identical_sealed_inputs_are_byte_deterministic_across_roots(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = _write_fixture(root / "inputs")
            first = materializer.materialize_development_uat_observations(
                **_build_kwargs(fixture, root / "first")
            )
            second = materializer.materialize_development_uat_observations(
                **_build_kwargs(fixture, root / "second")
            )

            first_files = _tree_bytes(first.work_dir)
            second_files = _tree_bytes(second.work_dir)
            self.assertEqual(first_files, second_files)
            self.assertEqual(first.private_artifact, second.private_artifact)
            self.assertEqual(first.safe_report, second.safe_report)
            self.assertEqual(
                first.private_artifact["selection_proof_fingerprint"],
                second.private_artifact["selection_proof_fingerprint"],
            )

    def test_each_external_byte_seal_tamper_fails_closed(self) -> None:
        input_fields = (
            (
                "retrieval_snapshot_path",
                "expected_retrieval_snapshot_sha256",
                "retrieval_snapshot_byte_seal_mismatch",
            ),
            (
                "bundle_artifact_path",
                "expected_bundle_artifact_sha256",
                "bundle_artifact_byte_seal_mismatch",
            ),
            (
                "retrieval_report_path",
                "expected_retrieval_report_sha256",
                "retrieval_report_byte_seal_mismatch",
            ),
            (
                "development_manifest_path",
                "expected_development_manifest_sha256",
                "development_manifest_byte_seal_mismatch",
            ),
        )
        for path_field, _seal_field, reason in input_fields:
            with self.subTest(path_field=path_field):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    fixture = _write_fixture(root / "inputs")
                    kwargs = _build_kwargs(fixture, root / "output")
                    path = kwargs[path_field]
                    path.write_bytes(path.read_bytes() + b" ")
                    with self.assertRaisesRegex(
                        materializer.DevelopmentObservationMaterializationError,
                        f"^{reason}$",
                    ):
                        materializer.materialize_development_uat_observations(**kwargs)
                    self.assertFalse((root / "output").exists())

    def test_missing_required_id_and_duplicate_adjudicated_id_fail_closed(
        self,
    ) -> None:
        mutations = (
            ("missing", "development_required_observation_missing"),
            (
                "duplicate",
                "development_adjudicated_observation_count_invalid",
            ),
        )
        for mutation, reason in mutations:
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    fixture = _write_fixture(root / "inputs")
                    manifest = deepcopy(fixture.manifest)
                    if mutation == "missing":
                        manifest["cases"][0]["required_source_observation_ids"][0] = (
                            "obs_body_missing"
                        )
                    else:
                        manifest["cases"][0]["required_source_observation_ids"][0] = manifest[
                            "cases"
                        ][1]["required_source_observation_ids"][0]
                        _refresh_case_source_binding(
                            manifest["cases"][0],
                            fixture.snapshot,
                        )
                    _refresh_case_fingerprint(manifest["cases"][0])
                    _refresh_manifest_fingerprint(manifest)
                    fixture = _replace_manifest(fixture, manifest)

                    with self.assertRaisesRegex(
                        materializer.DevelopmentObservationMaterializationError,
                        f"^{reason}$",
                    ):
                        materializer.materialize_development_uat_observations(
                            **_build_kwargs(fixture, root / "output")
                        )
                    self.assertFalse((root / "output").exists())

    def test_fewer_than_256_source_decoys_fails_without_redistribution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = _write_fixture(root / "inputs", body_count=455)
            with self.assertRaisesRegex(
                materializer.DevelopmentObservationMaterializationError,
                "^development_decoy_capacity_insufficient$",
            ):
                materializer.materialize_development_uat_observations(
                    **_build_kwargs(fixture, root / "output")
                )
            self.assertFalse((root / "output").exists())

    def test_occurrence_hash_provenance_permission_and_profile_drift_fail(
        self,
    ) -> None:
        mutations = (
            ("occurrence", "bundle_snapshot_body_lineage_mismatch"),
            ("content_hash", "retrieval_snapshot_contract_invalid"),
            ("provenance", "retrieval_snapshot_contract_invalid"),
            ("permission", "retrieval_snapshot_contract_invalid"),
            ("profile", "target_tokenizer_profile_binding_invalid"),
        )
        for mutation, reason in mutations:
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    fixture = _write_fixture(root / "inputs")
                    snapshot = deepcopy(fixture.snapshot)
                    report = deepcopy(fixture.retrieval_report)
                    manifest = deepcopy(fixture.manifest)
                    body = next(
                        row
                        for row in snapshot["parsed_mail_observations"]
                        if row["observation_id"] == "obs_body_0001"
                    )
                    if mutation == "occurrence":
                        body["location"]["message_occurrence_id"] = "message_occurrence_changed"
                        body["payload"]["message_occurrence_id"] = "message_occurrence_changed"
                    elif mutation == "content_hash":
                        body["location"]["source_content_hash"] = sha256_json("changed-content")
                    elif mutation == "provenance":
                        body["location"]["source_provenance_fingerprint"] = sha256_json(
                            "changed-provenance"
                        )
                    elif mutation == "permission":
                        body["permission_scope"] = PermissionScope.project(
                            "different-project"
                        ).to_dict()
                    else:
                        changed_profile = sha256_json("changed-profile")
                        snapshot["tokenizer_profile_fingerprint"] = changed_profile
                        report["candidate_admission_profile_fingerprint"] = changed_profile
                        manifest["source_bindings"]["tokenizer_profile_fingerprint"] = (
                            changed_profile
                        )

                    fixture = _reseal_source_fixture(
                        fixture,
                        snapshot=snapshot,
                        report=report,
                        manifest=manifest,
                    )
                    with self.assertRaisesRegex(
                        materializer.DevelopmentObservationMaterializationError,
                        f"^{reason}$",
                    ):
                        materializer.materialize_development_uat_observations(
                            **_build_kwargs(fixture, root / "output")
                        )
                    self.assertFalse((root / "output").exists())

    def test_existing_or_symlink_work_dir_fails_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = _write_fixture(root / "inputs")
            existing = root / "existing"
            existing.mkdir()
            marker = existing / "marker"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(
                materializer.DevelopmentObservationMaterializationError,
                "^immutable_work_dir_already_exists$",
            ):
                materializer.materialize_development_uat_observations(
                    **_build_kwargs(fixture, existing)
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

            symlink = root / "symlink-output"
            symlink.symlink_to(existing, target_is_directory=True)
            with self.assertRaisesRegex(
                materializer.DevelopmentObservationMaterializationError,
                "^immutable_work_dir_already_exists$",
            ):
                materializer.materialize_development_uat_observations(
                    **_build_kwargs(fixture, symlink)
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_staged_store_failure_leaves_no_target_or_partial_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = _write_fixture(root / "inputs")
            output = root / "atomic-output"
            real_create = materializer.ObservationStore.create
            invocation_count = 0

            def fail_after_ten(
                store: materializer.ObservationStore,
                observation: Observation,
            ) -> Observation:
                nonlocal invocation_count
                invocation_count += 1
                if invocation_count == 11:
                    raise OSError("synthetic private staged write fault")
                return real_create(store, observation)

            with mock.patch.object(
                materializer.ObservationStore,
                "create",
                new=fail_after_ten,
            ):
                with self.assertRaisesRegex(
                    materializer.DevelopmentObservationMaterializationError,
                    "^atomic_materialization_failed$",
                ):
                    materializer.materialize_development_uat_observations(
                        **_build_kwargs(fixture, output)
                    )

            self.assertEqual(invocation_count, 11)
            self.assertFalse(output.exists())
            self.assertEqual(
                list(root.glob(".atomic-output.staging-*")),
                [],
            )


class _Fixture:
    def __init__(
        self,
        *,
        snapshot_path: Path,
        bundle_path: Path,
        report_path: Path,
        manifest_path: Path,
        snapshot: dict[str, object],
        bundle_artifact: dict[str, object],
        retrieval_report: dict[str, object],
        manifest: dict[str, object],
    ) -> None:
        self.snapshot_path = snapshot_path
        self.bundle_path = bundle_path
        self.report_path = report_path
        self.manifest_path = manifest_path
        self.snapshot = snapshot
        self.bundle_artifact = bundle_artifact
        self.retrieval_report = retrieval_report
        self.manifest = manifest
        self.snapshot_sha256 = _sha256_path(snapshot_path)
        self.bundle_sha256 = _sha256_path(bundle_path)
        self.report_sha256 = _sha256_path(report_path)
        self.manifest_sha256 = _sha256_path(manifest_path)


def _write_fixture(root: Path, *, body_count: int = 500) -> _Fixture:
    root.mkdir(parents=True)
    (
        snapshot_bytes,
        bundle_bytes,
        report_bytes,
        manifest_bytes,
    ) = _fixture_bytes(body_count)
    snapshot_path = root / "retrieval-ready-snapshot.private.json"
    bundle_path = root / "mail-evidence-bundle.private.json"
    report_path = root / "retrieval-ready-report.safe.json"
    manifest_path = root / "development-manifest.private.json"
    snapshot_path.write_bytes(snapshot_bytes)
    bundle_path.write_bytes(bundle_bytes)
    report_path.write_bytes(report_bytes)
    manifest_path.write_bytes(manifest_bytes)
    return _Fixture(
        snapshot_path=snapshot_path,
        bundle_path=bundle_path,
        report_path=report_path,
        manifest_path=manifest_path,
        snapshot=json.loads(snapshot_bytes),
        bundle_artifact=json.loads(bundle_bytes),
        retrieval_report=json.loads(report_bytes),
        manifest=json.loads(manifest_bytes),
    )


@lru_cache(maxsize=2)
def _fixture_bytes(body_count: int) -> tuple[bytes, bytes, bytes, bytes]:
    permission_scope = PermissionScope.project("project_issue56_materializer")
    source_asset_id = "asset_issue56_materializer_fixture"
    source_asset_sha256 = sha256_json("source-asset")
    parser_fingerprint = sha256_json("parser")
    provenance_fingerprint = sha256_json("source-provenance")
    archive_id = "archive_issue56_materializer"
    mailbox_id = "mailbox_issue56_materializer"
    extractor_run_id = "run_issue56_materializer_fixture"
    items: list[SourceInventoryItem] = []
    parsed_observations: list[Observation] = []
    body_observations: list[Observation] = []
    for ordinal in range(1, body_count + 1):
        message_content_hash = sha256_json({"ordinal": ordinal, "source": "materializer-fixture"})
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
        occurrence_id = f"message_occurrence_{ordinal:04d}"
        message_fingerprint = sha256_json({"ordinal": ordinal, "kind": "message"})
        common_location = {
            "source_inventory_item_id": item.source_inventory_item_id,
            "source_local_key": source_local_key,
            "source_content_hash": message_content_hash,
            "source_provenance_fingerprint": provenance_fingerprint,
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": sha256_json({"folder": ordinal % 7}),
            "message_id": f"message-{ordinal:04d}@example.invalid",
            "message_occurrence_id": occurrence_id,
        }
        message = Observation.from_dict(
            {
                "observation_id": f"obs_message_{ordinal:04d}",
                "asset_id": source_asset_id,
                "extractor_run_id": extractor_run_id,
                "observation_type": "email_message",
                "modality": "mail",
                "location": common_location,
                "payload": {
                    "canonical_fact_status": "not_asserted",
                    "message_occurrence_id": occurrence_id,
                    "message_fingerprint": message_fingerprint,
                    "subject": f"Synthetic subject {ordinal:04d}",
                    "normalized_subject": (f"synthetic subject {ordinal:04d}"),
                    "sender": "fixture@example.invalid",
                    "sent_at": "2026-08-19T09:00:00+00:00",
                    "body_hash": sha256_json({"body": ordinal}),
                    "thread_id": f"thread_{ordinal:04d}",
                    "fingerprint_policy": "formowl_mail_fingerprint_v1",
                },
                "confidence": 1.0,
                "permission_scope": permission_scope.to_dict(),
                "created_at": CREATED_AT,
            }
        )
        text = f"Synthetic evidence segment {ordinal:04d} " f"references CASE-{ordinal:04d}."
        body = Observation.from_dict(
            {
                "observation_id": f"obs_body_{ordinal:04d}",
                "asset_id": source_asset_id,
                "extractor_run_id": extractor_run_id,
                "observation_type": "email_body_segment",
                "modality": "mail",
                "location": {
                    **common_location,
                    "body_segment_index": 0,
                },
                "text": text,
                "payload": {
                    "canonical_fact_status": "not_asserted",
                    "message_occurrence_id": occurrence_id,
                    "message_fingerprint": message_fingerprint,
                },
                "confidence": 1.0,
                "permission_scope": permission_scope.to_dict(),
                "created_at": CREATED_AT,
            }
        )
        parsed_observations.extend((message, body))
        body_observations.append(body)
    inventory = SourceInventory.create(
        source_asset_id=source_asset_id,
        items=items,
        source_fingerprint=source_asset_sha256,
        parser_fingerprint=parser_fingerprint,
        created_at=CREATED_AT,
    )
    bundle = build_mail_evidence_bundle(
        parsed_observations,
        workspace_id="workspace_issue56_materializer",
        owner_user_id="owner_issue56_materializer",
        source_asset_id=source_asset_id,
        archive_sha256=source_asset_sha256,
        producer_type="server_side_parser",
        parser_name="fixture_parser",
        parser_version="1",
        upload_session_id="upload_issue56_materializer",
        created_at=CREATED_AT,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
    )
    bundle_payload = bundle.to_dict()
    bundle_fingerprint = sha256_json(bundle_payload)
    source_snapshot_fingerprint = sha256_json("source-snapshot")
    bundle_artifact: dict[str, object] = {
        "artifact_id": "formowl_issue56_native_mail_evidence_bundle_v1",
        "schema_version": 1,
        "status": "passed",
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "source_inventory_fingerprint": sha256_json(inventory.to_dict()),
        "source_provenance_fingerprint": provenance_fingerprint,
        "bundle": bundle_payload,
        "bundle_fingerprint": bundle_fingerprint,
    }
    bundle_artifact["artifact_fingerprint"] = _payload_fingerprint(
        bundle_artifact,
        "artifact_fingerprint",
    )
    counts = {
        "source_inventory_item_count": len(items),
        "source_occurrence_observation_count": 0,
        "parsed_folder_observation_count": 0,
        "parsed_message_observation_count": body_count,
        "parsed_header_observation_count": 0,
        "parsed_body_segment_observation_count": body_count,
        "parsed_attachment_observation_count": 0,
        "parsed_observation_count": len(parsed_observations),
        "retrieval_snapshot_observation_count": len(parsed_observations),
        "mail_bundle_message_count": body_count,
        "mail_bundle_message_occurrence_count": body_count,
        "mail_bundle_body_segment_count": body_count,
        "mail_bundle_attachment_count": 0,
        "mail_bundle_attachment_occurrence_count": 0,
        "index_observation_count": body_count,
        "indexed_observation_count": body_count,
        "indexed_snippet_count": body_count,
        "admitted_candidate_count": body_count,
        "protected_identifier_count": body_count,
        "parser_warning_class_count": 0,
        "parser_warning_occurrence_count": 0,
        "authorized_result_count": 1,
        "denied_result_count": 0,
        "missing_source_inventory_binding_count": 0,
        "missing_source_local_key_binding_count": 0,
        "missing_content_hash_binding_count": 0,
        "missing_permission_binding_count": 0,
        "unexplained_loss_count": 0,
        "blocker_count": 0,
    }
    snapshot: dict[str, object] = {
        "artifact_id": ("formowl_issue56_native_source_complete_retrieval_ready_snapshot_v1"),
        "schema_version": 1,
        "status": "passed",
        "claim_boundary_status": ("retrieval_ready_evidence_not_canonical_fact"),
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "source_asset_sha256": source_asset_sha256,
        "native_manifest_fingerprint": sha256_json("native-manifest"),
        "source_inventory_fingerprint": sha256_json(inventory.to_dict()),
        "source_provenance_fingerprint": provenance_fingerprint,
        "permission_fingerprint": sha256_json(permission_scope.to_dict()),
        "parsed_observation_fingerprint": sha256_json(
            [observation.to_dict() for observation in parsed_observations]
        ),
        "mail_evidence_bundle_fingerprint": bundle_fingerprint,
        "tokenizer_profile_fingerprint": (ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT),
        "observation_snapshot_fingerprint": sha256_json("observation-snapshot"),
        "candidate_manifest_fingerprint": sha256_json("candidate-manifest"),
        "index_fingerprint": sha256_json("index"),
        "query_fingerprint": sha256_json("query"),
        "authorized_result_fingerprint": sha256_json("authorized-result"),
        "denied_result_fingerprint": sha256_json("denied-result"),
        "created_at": CREATED_AT,
        "source_inventory": inventory.to_dict(),
        "source_occurrence_observations": [],
        "parsed_mail_observations": [observation.to_dict() for observation in parsed_observations],
        "index_build_manifest": {"artifact_fingerprint": sha256_json("index-build")},
        "parser_warning_counts": {},
        "counts": counts,
        "blocker_fingerprints": [],
    }
    snapshot["snapshot_fingerprint"] = _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    )
    report: dict[str, object] = {
        "artifact_id": ("formowl_issue56_native_source_complete_retrieval_ready_report_v1"),
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
        "source_asset_fingerprint": source_asset_sha256,
        "native_manifest_fingerprint": snapshot["native_manifest_fingerprint"],
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": provenance_fingerprint,
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "parsed_observation_fingerprint": snapshot["parsed_observation_fingerprint"],
        "mail_evidence_bundle_fingerprint": bundle_fingerprint,
        "candidate_admission_profile_fingerprint": (
            ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT
        ),
        "observation_snapshot_fingerprint": snapshot["observation_snapshot_fingerprint"],
        "candidate_manifest_fingerprint": snapshot["candidate_manifest_fingerprint"],
        "index_fingerprint": snapshot["index_fingerprint"],
        "query_fingerprint": snapshot["query_fingerprint"],
        "authorized_result_fingerprint": snapshot["authorized_result_fingerprint"],
        "authorized_cited_observation_fingerprint": sha256_json("obs_body_0001"),
        "denied_result_fingerprint": snapshot["denied_result_fingerprint"],
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
        "counts": counts,
        "blocker_fingerprints": [],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    manifest = _development_manifest(
        body_observations=body_observations,
        bundle_artifact=bundle_artifact,
        snapshot=snapshot,
        report=report,
        bundle_bytes=_json_bytes(bundle_artifact),
        snapshot_bytes=_json_bytes(snapshot),
        report_bytes=_json_bytes(report),
    )
    return (
        _json_bytes(snapshot),
        _json_bytes(bundle_artifact),
        _json_bytes(report),
        _json_bytes(manifest),
    )


def _development_manifest(
    *,
    body_observations: list[Observation],
    bundle_artifact: dict[str, object],
    snapshot: dict[str, object],
    report: dict[str, object],
    bundle_bytes: bytes,
    snapshot_bytes: bytes,
    report_bytes: bytes,
) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for case_index in range(100):
        selected = body_observations[case_index * 2 : case_index * 2 + 2]
        required_ids = sorted(observation.observation_id for observation in selected)
        case: dict[str, object] = {
            "case_id": f"issue56_development_case_{case_index:03d}",
            "domain": "mail_business_identifier",
            "intent_kind": "relation_reasoning",
            "pattern": "shared_protected_identifier_cross_message_relation_v1",
            "result_kind": "owner_match",
            "query_text": f"Synthetic sealed query {case_index:03d}",
            "requester_user_id": "owner_issue56_materializer",
            "required_source_observation_ids": required_ids,
            "forbidden_source_observation_ids": [],
            "required_match_count": 2,
            "limit": 10,
            "source_evidence_binding": {
                "candidate_fingerprint": sha256_json({"case": case_index}),
                "required_observation_hashes": sorted(
                    sha256_json(observation.to_dict()) for observation in selected
                ),
                "required_message_occurrence_hashes": sorted(
                    sha256_json(observation.location["message_occurrence_id"])
                    for observation in selected
                ),
            },
        }
        case["private_fingerprint"] = _payload_fingerprint(
            case,
            "private_fingerprint",
        )
        cases.append(case)
    manifest: dict[str, object] = {
        "artifact_id": development_manifest.ARTIFACT_ID,
        "schema_version": 1,
        "classification": development_manifest.CLASSIFICATION,
        "claim_boundary_status": ("development_cases_not_quality_or_holdout_evidence"),
        "quality_evaluation_status": "not_run",
        "holdout_content_consumed": False,
        "oracle_content_consumed": False,
        "mail_evidence_bundle_id": bundle_artifact["bundle"]["mail_evidence_bundle_id"],
        "mail_import_session_id": bundle_artifact["bundle"]["mail_import_session"][
            "mail_import_session_id"
        ],
        "archive_sha256": bundle_artifact["bundle"]["mail_import_session"]["archive_sha256"],
        "source_bindings": {
            "bundle_artifact_byte_hash": _sha256_bytes(bundle_bytes),
            "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
            "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
            "retrieval_snapshot_byte_hash": _sha256_bytes(snapshot_bytes),
            "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
            "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
            "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
            "permission_fingerprint": snapshot["permission_fingerprint"],
            "tokenizer_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
            "index_fingerprint": snapshot["index_fingerprint"],
            "retrieval_report_byte_hash": _sha256_bytes(report_bytes),
        },
        "selection_policy": development_manifest._SELECTION_POLICY,
        "selection_policy_fingerprint": (development_manifest.SELECTION_POLICY_FINGERPRINT),
        "case_count": 100,
        "case_strata_counts": {"business_identifier": 100},
        "required_evidence_reference_count": 200,
        "distinct_required_observation_count": 200,
        "distinct_required_message_occurrence_count": 200,
        "cases": cases,
    }
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    return manifest


def _reseal_source_fixture(
    fixture: _Fixture,
    *,
    snapshot: dict[str, object],
    report: dict[str, object],
    manifest: dict[str, object],
) -> _Fixture:
    parsed_rows = snapshot["parsed_mail_observations"]
    snapshot["parsed_observation_fingerprint"] = sha256_json(parsed_rows)
    snapshot["snapshot_fingerprint"] = _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    )
    report_bindings = {
        "retrieval_snapshot_fingerprint": "snapshot_fingerprint",
        "source_snapshot_fingerprint": "source_snapshot_fingerprint",
        "source_inventory_fingerprint": "source_inventory_fingerprint",
        "source_provenance_fingerprint": "source_provenance_fingerprint",
        "permission_fingerprint": "permission_fingerprint",
        "parsed_observation_fingerprint": "parsed_observation_fingerprint",
        "mail_evidence_bundle_fingerprint": ("mail_evidence_bundle_fingerprint"),
        "candidate_admission_profile_fingerprint": ("tokenizer_profile_fingerprint"),
        "observation_snapshot_fingerprint": ("observation_snapshot_fingerprint"),
        "candidate_manifest_fingerprint": "candidate_manifest_fingerprint",
        "index_fingerprint": "index_fingerprint",
    }
    for report_field, snapshot_field in report_bindings.items():
        report[report_field] = snapshot[snapshot_field]
    report["counts"] = snapshot["counts"]
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    snapshot_bytes = _json_bytes(snapshot)
    report_bytes = _json_bytes(report)
    manifest["source_bindings"]["retrieval_snapshot_byte_hash"] = _sha256_bytes(snapshot_bytes)
    manifest["source_bindings"]["retrieval_snapshot_fingerprint"] = snapshot["snapshot_fingerprint"]
    manifest["source_bindings"]["retrieval_report_byte_hash"] = _sha256_bytes(report_bytes)
    for field_name in (
        "source_snapshot_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "permission_fingerprint",
        "tokenizer_profile_fingerprint",
        "index_fingerprint",
    ):
        manifest["source_bindings"][field_name] = snapshot[field_name]
    _refresh_manifest_fingerprint(manifest)
    fixture.snapshot_path.write_bytes(snapshot_bytes)
    fixture.report_path.write_bytes(report_bytes)
    fixture.manifest_path.write_bytes(_json_bytes(manifest))
    return _Fixture(
        snapshot_path=fixture.snapshot_path,
        bundle_path=fixture.bundle_path,
        report_path=fixture.report_path,
        manifest_path=fixture.manifest_path,
        snapshot=snapshot,
        bundle_artifact=fixture.bundle_artifact,
        retrieval_report=report,
        manifest=manifest,
    )


def _replace_manifest(
    fixture: _Fixture,
    manifest: dict[str, object],
) -> _Fixture:
    fixture.manifest_path.write_bytes(_json_bytes(manifest))
    return _Fixture(
        snapshot_path=fixture.snapshot_path,
        bundle_path=fixture.bundle_path,
        report_path=fixture.report_path,
        manifest_path=fixture.manifest_path,
        snapshot=fixture.snapshot,
        bundle_artifact=fixture.bundle_artifact,
        retrieval_report=fixture.retrieval_report,
        manifest=manifest,
    )


def _refresh_case_fingerprint(case: dict[str, object]) -> None:
    case["private_fingerprint"] = _payload_fingerprint(
        case,
        "private_fingerprint",
    )


def _refresh_case_source_binding(
    case: dict[str, object],
    snapshot: dict[str, object],
) -> None:
    observations = {
        row["observation_id"]: Observation.from_dict(row)
        for row in snapshot["parsed_mail_observations"]
    }
    selected = [
        observations[observation_id] for observation_id in case["required_source_observation_ids"]
    ]
    case["source_evidence_binding"] = {
        "candidate_fingerprint": sha256_json({"case_id": case["case_id"], "mutation": "duplicate"}),
        "required_observation_hashes": sorted(
            sha256_json(observation.to_dict()) for observation in selected
        ),
        "required_message_occurrence_hashes": sorted(
            sha256_json(observation.location["message_occurrence_id"]) for observation in selected
        ),
    }


def _refresh_manifest_fingerprint(manifest: dict[str, object]) -> None:
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )


def _build_kwargs(fixture: _Fixture, output: Path) -> dict[str, object]:
    return {
        "retrieval_snapshot_path": fixture.snapshot_path,
        "expected_retrieval_snapshot_sha256": fixture.snapshot_sha256,
        "bundle_artifact_path": fixture.bundle_path,
        "expected_bundle_artifact_sha256": fixture.bundle_sha256,
        "retrieval_report_path": fixture.report_path,
        "expected_retrieval_report_sha256": fixture.report_sha256,
        "development_manifest_path": fixture.manifest_path,
        "expected_development_manifest_sha256": fixture.manifest_sha256,
        "work_dir": output,
    }


def _cli_args(fixture: _Fixture, output: Path) -> list[str]:
    kwargs = _build_kwargs(fixture, output)
    return [
        "--retrieval-snapshot",
        str(kwargs["retrieval_snapshot_path"]),
        "--expected-retrieval-snapshot-sha256",
        str(kwargs["expected_retrieval_snapshot_sha256"]),
        "--bundle-artifact",
        str(kwargs["bundle_artifact_path"]),
        "--expected-bundle-artifact-sha256",
        str(kwargs["expected_bundle_artifact_sha256"]),
        "--retrieval-report",
        str(kwargs["retrieval_report_path"]),
        "--expected-retrieval-report-sha256",
        str(kwargs["expected_retrieval_report_sha256"]),
        "--development-manifest",
        str(kwargs["development_manifest_path"]),
        "--expected-development-manifest-sha256",
        str(kwargs["expected_development_manifest_sha256"]),
        "--work-dir",
        str(output),
    ]


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _payload_fingerprint(
    payload: dict[str, object],
    fingerprint_field: str,
) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != fingerprint_field})


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


if __name__ == "__main__":
    unittest.main()
