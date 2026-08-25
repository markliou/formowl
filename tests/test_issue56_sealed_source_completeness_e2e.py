from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    SourceInventory,
    SourceInventoryProcessingState,
    SourceInventoryRawRetentionState,
)
from formowl_core.methodology_authority import (
    methodology_gate_dependency_manifest_path,
    validate_methodology_gate_dependency_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "issue56_sealed_source_completeness_evidence.py"
REBIND_TEST_PATH = ROOT / "tests" / "test_issue56_source_complete_snapshot_rebind_e2e.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


evidence = _load_module(
    "issue56_sealed_source_completeness_evidence_tested",
    SCRIPT_PATH,
)
rebind_fixture = _load_module(
    "issue56_source_complete_snapshot_rebind_fixture_for_completeness",
    REBIND_TEST_PATH,
)
rebind = rebind_fixture.rebind


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _write_json(path: Path, value: dict[str, object]) -> str:
    encoded = evidence._canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return _sha256_bytes(encoded)


def _copy_and_reseal(
    source: Path,
    destination: Path,
    *,
    mutate,
    fingerprint_field: str,
) -> str:
    value = json.loads(source.read_bytes())
    mutate(value)
    value[fingerprint_field] = rebind._payload_fingerprint(value, fingerprint_field)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    return _sha256_bytes(destination.read_bytes())


class SealedCompletenessFixture:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self.execution_fingerprint = evidence._canonical_fingerprint("execution-integrated")
        fixture_root = repository_root / "private-fixture"
        (
            self.native_manifest_path,
            self.native_export_root,
            self.governed_work_dir,
        ) = rebind_fixture._native_fixture(fixture_root)

        self.source_asset_path = repository_root / "evidence/production/source-item.bin"
        self.source_asset_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_asset_path.write_bytes(b"sealed synthetic pst source bytes")
        self.source_asset_sha256 = _sha256_bytes(self.source_asset_path.read_bytes())

        native_manifest = json.loads(self.native_manifest_path.read_bytes())
        native_manifest["source_asset_sha256"] = self.source_asset_sha256
        native_manifest["manifest_fingerprint"] = rebind._native_manifest_payload_fingerprint(
            native_manifest,
            "manifest_fingerprint",
        )
        self.native_manifest_path.write_text(
            json.dumps(native_manifest, sort_keys=True),
            encoding="utf-8",
        )
        self.native_manifest_sha256 = _sha256_bytes(self.native_manifest_path.read_bytes())

        asset_path = self.governed_work_dir / "data/ingestion/assets/asset.json"
        asset = json.loads(asset_path.read_bytes())
        asset["content_hash"] = self.source_asset_sha256
        asset_path.write_text(json.dumps(asset, sort_keys=True), encoding="utf-8")

        existing_root = repository_root / "sealed/existing"
        approved_root = repository_root / "sealed/approved"
        existing_root.mkdir(parents=True)
        approved_root.mkdir(parents=True)
        rebind.run_native_source_complete_snapshot(
            native_manifest_path=self.native_manifest_path,
            native_export_root=self.native_export_root,
            preserved_work_dir=self.governed_work_dir,
            snapshot_output=existing_root / "snapshot.json",
            report_output=existing_root / "report.json",
            created_at="2026-08-24T01:00:00+00:00",
        )
        approved = rebind.run_native_source_complete_snapshot(
            native_manifest_path=self.native_manifest_path,
            native_export_root=self.native_export_root,
            preserved_work_dir=self.governed_work_dir,
            snapshot_output=approved_root / "snapshot.json",
            report_output=approved_root / "report.json",
            created_at="2026-08-25T01:00:00+00:00",
        )
        self.existing_snapshot_path = existing_root / "snapshot.json"
        self.existing_report_path = existing_root / "report.json"
        self.approved_snapshot_path = approved_root / "snapshot.json"
        self.approved_report_path = approved_root / "report.json"
        self.existing_snapshot_sha256 = _sha256_bytes(self.existing_snapshot_path.read_bytes())
        self.existing_report_sha256 = _sha256_bytes(self.existing_report_path.read_bytes())
        self.approved_snapshot_sha256 = _sha256_bytes(self.approved_snapshot_path.read_bytes())
        self.approved_report_sha256 = _sha256_bytes(self.approved_report_path.read_bytes())
        self.approved_snapshot = approved.snapshot
        self.approved_report = approved.report

        authorization = approved.snapshot["authorization_binding"]
        attestation_root = repository_root / "sealed/attestation"
        private, safe = evidence.identity_attestation.create_identity_scope_attestation_artifacts(
            output_root=attestation_root,
            mode="workspace_only_v1",
            workspace_id="workspace_formowl",
            tenant_id=None,
            asset_id=authorization["source_asset_id"],
            asset_content_hash=self.source_asset_sha256,
            source_fingerprint=approved.snapshot["snapshot_fingerprint"],
            permission_fingerprint=approved.snapshot["permission_fingerprint"],
            approver_actor="user_full_pst_domain_hard_case_eval_owner",
            authority_source="issue56_fixture_explicit_operator_approval_v1",
            approved_at="2026-08-25T02:00:00+00:00",
            reason="Synthetic source completeness contract fixture approval.",
            operator_approved=True,
            spec_approval_id="issue56_fixture_workspace_only_spec_v1",
        )
        self.attestation_private_path = (
            attestation_root / evidence.identity_attestation.PRIVATE_ARTIFACT_FILENAME
        )
        self.attestation_safe_path = (
            attestation_root / evidence.identity_attestation.SAFE_REPORT_FILENAME
        )
        self.attestation_private_sha256 = _sha256_bytes(self.attestation_private_path.read_bytes())
        self.attestation_safe_sha256 = _sha256_bytes(self.attestation_safe_path.read_bytes())
        self.identity_scope_fingerprint = safe["identity_scope_fingerprint"]
        self.private_attestation = private

        raw_source_unit_count = approved.snapshot["counts"]["source_inventory_item_count"]
        self.source_inventory_path = repository_root / "evidence/production/source-inventory.json"
        source_inventory = evidence._with_fingerprint(
            {
                "artifact_id": evidence.SOURCE_INVENTORY_ARTIFACT_ID,
                "dependency_paths": ["evidence/production/source-item.bin"],
                "payload": {
                    "source_count": 1,
                    "source_item_count": raw_source_unit_count,
                    "source_hashes": [self.source_asset_sha256],
                    "source_paths": ["evidence/production/source-item.bin"],
                },
            },
            "artifact_fingerprint",
        )
        self.source_inventory_sha256 = _write_json(
            self.source_inventory_path,
            source_inventory,
        )

        self.case_manifest_path = repository_root / "evidence/production/case-manifest.json"
        case_manifest = evidence._with_fingerprint(
            {
                "artifact_id": "formowl_methodology_case_manifest_dependency_v1",
                "dependency_paths": [],
                "payload": {
                    "case_count": 1,
                    "case_scope": "combined_independent_acceptance",
                },
            },
            "artifact_fingerprint",
        )
        self.case_manifest_sha256 = _write_json(
            self.case_manifest_path,
            case_manifest,
        )
        self.configuration_manifest_path = (
            repository_root / "evidence/production/configuration-manifest.json"
        )
        configuration_manifest = evidence._with_fingerprint(
            {
                "artifact_id": ("formowl_methodology_configuration_manifest_dependency_v1"),
                "dependency_paths": [],
                "payload": {
                    "evaluation_policy_id": ("raw_source_oracle_same_pipeline_end_answer_v1"),
                    "method_id": "evidence_to_knowledge_kg_ontology_v2_hybrid_v1",
                    "tokenizer_id": ("jieba_sentencepiece_frozen_profile_candidate_admission_v1"),
                },
            },
            "artifact_fingerprint",
        )
        self.configuration_manifest_sha256 = _write_json(
            self.configuration_manifest_path,
            configuration_manifest,
        )
        self.model_artifact_path = repository_root / "evidence/production/model-artifact.bin"
        self.model_artifact_path.write_bytes(b"model-artifact")
        self.model_artifact_sha256 = _sha256_bytes(self.model_artifact_path.read_bytes())
        self.package_lock_path = repository_root / "evidence/production/package.lock"
        self.package_lock_path.write_bytes(b"package-lock")
        self.package_lock_sha256 = _sha256_bytes(self.package_lock_path.read_bytes())

        self.source_manifest_path = repository_root / "evidence/production/source-manifest.json"
        source_manifest = evidence._with_fingerprint(
            {
                "artifact_id": evidence.SOURCE_MANIFEST_ARTIFACT_ID,
                "execution_fingerprint": self.execution_fingerprint,
                "source_kind": "real_source",
                "source_count": 1,
                "source_item_count": raw_source_unit_count,
                "source_hashes": [self.source_asset_sha256],
                "case_manifest_sha256": self.case_manifest_sha256,
                "configuration_manifest_sha256": self.configuration_manifest_sha256,
                "model_artifact_hashes": [self.model_artifact_sha256],
                "package_lock_sha256": self.package_lock_sha256,
            },
            "manifest_fingerprint",
        )
        self.source_manifest_sha256 = _write_json(
            self.source_manifest_path,
            source_manifest,
        )

    def kwargs(self, output_name: str) -> dict[str, object]:
        return {
            "repository_root": self.repository_root,
            "source_asset_path": self.source_asset_path,
            "expected_source_asset_sha256": self.source_asset_sha256,
            "native_manifest_path": self.native_manifest_path,
            "expected_native_manifest_sha256": self.native_manifest_sha256,
            "native_export_root": self.native_export_root,
            "existing_snapshot_path": self.existing_snapshot_path,
            "expected_existing_snapshot_sha256": self.existing_snapshot_sha256,
            "existing_report_path": self.existing_report_path,
            "expected_existing_report_sha256": self.existing_report_sha256,
            "approved_snapshot_path": self.approved_snapshot_path,
            "expected_approved_snapshot_sha256": self.approved_snapshot_sha256,
            "approved_report_path": self.approved_report_path,
            "expected_approved_report_sha256": self.approved_report_sha256,
            "attestation_private_path": self.attestation_private_path,
            "expected_attestation_private_sha256": self.attestation_private_sha256,
            "attestation_safe_path": self.attestation_safe_path,
            "expected_attestation_safe_sha256": self.attestation_safe_sha256,
            "expected_identity_scope_fingerprint": self.identity_scope_fingerprint,
            "expected_workspace_id": "workspace_formowl",
            "expected_approver_actor": "user_full_pst_domain_hard_case_eval_owner",
            "source_inventory_dependency_path": self.source_inventory_path,
            "expected_source_inventory_dependency_sha256": (self.source_inventory_sha256),
            "source_manifest_path": self.source_manifest_path,
            "expected_source_manifest_sha256": self.source_manifest_sha256,
            "execution_fingerprint": self.execution_fingerprint,
            "output_root": Path(f"evidence/production/issue56-source-completeness-{output_name}"),
        }

    def cli_args(self, output_name: str) -> list[str]:
        kwargs = self.kwargs(output_name)
        option_names = {
            "repository_root": "--repository-root",
            "source_asset_path": "--source-asset",
            "expected_source_asset_sha256": "--expected-source-asset-sha256",
            "native_manifest_path": "--native-manifest",
            "expected_native_manifest_sha256": "--expected-native-manifest-sha256",
            "native_export_root": "--native-export-root",
            "existing_snapshot_path": "--existing-snapshot",
            "expected_existing_snapshot_sha256": "--expected-existing-snapshot-sha256",
            "existing_report_path": "--existing-report",
            "expected_existing_report_sha256": "--expected-existing-report-sha256",
            "approved_snapshot_path": "--approved-snapshot",
            "expected_approved_snapshot_sha256": "--expected-approved-snapshot-sha256",
            "approved_report_path": "--approved-report",
            "expected_approved_report_sha256": "--expected-approved-report-sha256",
            "attestation_private_path": "--attestation-private",
            "expected_attestation_private_sha256": ("--expected-attestation-private-sha256"),
            "attestation_safe_path": "--attestation-safe",
            "expected_attestation_safe_sha256": "--expected-attestation-safe-sha256",
            "expected_identity_scope_fingerprint": ("--expected-identity-scope-fingerprint"),
            "expected_workspace_id": "--expected-workspace-id",
            "expected_approver_actor": "--expected-approver-actor",
            "source_inventory_dependency_path": "--source-inventory-dependency",
            "expected_source_inventory_dependency_sha256": (
                "--expected-source-inventory-dependency-sha256"
            ),
            "source_manifest_path": "--source-manifest",
            "expected_source_manifest_sha256": "--expected-source-manifest-sha256",
            "execution_fingerprint": "--execution-fingerprint",
            "output_root": "--output-root",
        }
        result: list[str] = []
        for key, option in option_names.items():
            result.extend((option, str(kwargs[key])))
        return result


class Issue56SealedSourceCompletenessE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="issue56-sealed-source-completeness-")
        cls.repository_root = Path(cls.temp_dir.name)
        cls.fixture = SealedCompletenessFixture(cls.repository_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_authors_safe_dependencies_and_passes_production_validator(self) -> None:
        artifacts = evidence.author_sealed_source_completeness_evidence(
            **self.fixture.kwargs("positive")
        )
        counts = artifacts.safe_report["counts"]
        self.assertEqual(counts["raw_source_unit_count"], 8)
        self.assertEqual(counts["emitted_observation_unit_count"], 8)
        self.assertEqual(counts["policy_redacted_unit_count"], 0)
        self.assertEqual(counts["unexplained_loss_unit_count"], 0)
        self.assertEqual(counts["preserved_unsupported_unit_count"], 1)

        output_root = self.repository_root / self.fixture.kwargs("positive")["output_root"]
        raw_path = output_root / evidence.RAW_ORACLE_FILENAME
        reconciliation_path = output_root / evidence.RECONCILIATION_FILENAME
        result_relative = Path("evidence/production/completeness-result.json")
        result = evidence._with_fingerprint(
            {
                "artifact_id": "formowl_raw_source_completeness_result_v1",
                "execution_fingerprint": self.fixture.execution_fingerprint,
                "source_manifest_sha256": self.fixture.source_manifest_sha256,
                "status": "passed",
                "raw_source_unit_count": counts["raw_source_unit_count"],
                "emitted_observation_unit_count": counts["emitted_observation_unit_count"],
                "policy_redacted_unit_count": 0,
                "unexplained_loss_unit_count": 0,
                "loss_taxonomy_counts": artifacts.safe_report["loss_taxonomy_counts"],
            },
            "result_fingerprint",
        )
        result_path = self.repository_root / result_relative
        result_sha256 = _write_json(result_path, result)
        dependency_manifest_path = methodology_gate_dependency_manifest_path(result_relative)
        dependencies = [
            {
                "role": "case_manifest",
                "path": self.fixture.case_manifest_path.relative_to(
                    self.repository_root
                ).as_posix(),
                "byte_sha256": self.fixture.case_manifest_sha256,
                "artifact_id": "formowl_methodology_case_manifest_dependency_v1",
                "internal_fingerprint_field": "artifact_fingerprint",
                "internal_fingerprint": json.loads(self.fixture.case_manifest_path.read_bytes())[
                    "artifact_fingerprint"
                ],
            },
            {
                "role": "configuration_manifest",
                "path": self.fixture.configuration_manifest_path.relative_to(
                    self.repository_root
                ).as_posix(),
                "byte_sha256": self.fixture.configuration_manifest_sha256,
                "artifact_id": ("formowl_methodology_configuration_manifest_dependency_v1"),
                "internal_fingerprint_field": "artifact_fingerprint",
                "internal_fingerprint": json.loads(
                    self.fixture.configuration_manifest_path.read_bytes()
                )["artifact_fingerprint"],
            },
            {
                "role": "model_artifact",
                "path": self.fixture.model_artifact_path.relative_to(
                    self.repository_root
                ).as_posix(),
                "byte_sha256": self.fixture.model_artifact_sha256,
                "artifact_id": None,
                "internal_fingerprint_field": None,
                "internal_fingerprint": None,
            },
            {
                "role": "observation_reconciliation_report",
                "path": reconciliation_path.relative_to(self.repository_root).as_posix(),
                "byte_sha256": _sha256_bytes(reconciliation_path.read_bytes()),
                "artifact_id": evidence.RECONCILIATION_ARTIFACT_ID,
                "internal_fingerprint_field": "artifact_fingerprint",
                "internal_fingerprint": artifacts.reconciliation["artifact_fingerprint"],
            },
            {
                "role": "package_lock",
                "path": self.fixture.package_lock_path.relative_to(self.repository_root).as_posix(),
                "byte_sha256": self.fixture.package_lock_sha256,
                "artifact_id": None,
                "internal_fingerprint_field": None,
                "internal_fingerprint": None,
            },
            {
                "role": "raw_source_oracle_manifest",
                "path": raw_path.relative_to(self.repository_root).as_posix(),
                "byte_sha256": _sha256_bytes(raw_path.read_bytes()),
                "artifact_id": evidence.RAW_ORACLE_ARTIFACT_ID,
                "internal_fingerprint_field": "artifact_fingerprint",
                "internal_fingerprint": artifacts.raw_oracle["artifact_fingerprint"],
            },
            {
                "role": "source_inventory_manifest",
                "path": self.fixture.source_inventory_path.relative_to(
                    self.repository_root
                ).as_posix(),
                "byte_sha256": self.fixture.source_inventory_sha256,
                "artifact_id": evidence.SOURCE_INVENTORY_ARTIFACT_ID,
                "internal_fingerprint_field": "artifact_fingerprint",
                "internal_fingerprint": json.loads(self.fixture.source_inventory_path.read_bytes())[
                    "artifact_fingerprint"
                ],
            },
            {
                "role": "source_item",
                "path": self.fixture.source_asset_path.relative_to(self.repository_root).as_posix(),
                "byte_sha256": self.fixture.source_asset_sha256,
                "artifact_id": None,
                "internal_fingerprint_field": None,
                "internal_fingerprint": None,
            },
        ]
        dependency_manifest = evidence._with_fingerprint(
            {
                "artifact_id": "formowl_methodology_gate_dependency_manifest_v1",
                "gate_id": evidence.GATE_ID,
                "execution_fingerprint": self.fixture.execution_fingerprint,
                "source_manifest_path": self.fixture.source_manifest_path.relative_to(
                    self.repository_root
                ).as_posix(),
                "source_manifest_sha256": self.fixture.source_manifest_sha256,
                "result_artifact_path": result_relative.as_posix(),
                "result_artifact_sha256": result_sha256,
                "dependencies": sorted(
                    dependencies,
                    key=lambda row: (row["role"], row["path"]),
                ),
            },
            "manifest_fingerprint",
        )
        _write_json(
            self.repository_root / dependency_manifest_path,
            dependency_manifest,
        )
        source_manifest = json.loads(self.fixture.source_manifest_path.read_bytes())
        self.assertTrue(
            validate_methodology_gate_dependency_manifest(
                repository_root=self.repository_root,
                gate_id=evidence.GATE_ID,
                source_manifest_path=self.fixture.source_manifest_path,
                result_artifact_path=result_path,
                source_manifest=source_manifest,
                result_artifact=result,
                execution_fingerprint=self.fixture.execution_fingerprint,
            )
        )

    def test_cli_stdout_is_hash_count_status_only(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *self.fixture.cli_args("cli")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "passed")
        rendered = completed.stdout.casefold()
        for forbidden in (
            str(self.repository_root).casefold(),
            "source-item.bin",
            "subject",
            "sender",
            "tenant_id",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_deterministic_bytes_and_no_overwrite(self) -> None:
        evidence.author_sealed_source_completeness_evidence(
            **self.fixture.kwargs("deterministic-a")
        )
        evidence.author_sealed_source_completeness_evidence(
            **self.fixture.kwargs("deterministic-b")
        )
        first = self.repository_root / self.fixture.kwargs("deterministic-a")["output_root"]
        second = self.repository_root / self.fixture.kwargs("deterministic-b")["output_root"]
        for filename in (
            evidence.RAW_ORACLE_FILENAME,
            evidence.RECONCILIATION_FILENAME,
            evidence.SAFE_REPORT_FILENAME,
        ):
            self.assertEqual(
                (first / filename).read_bytes(),
                (second / filename).read_bytes(),
            )
        with self.assertRaisesRegex(
            evidence.SourceCompletenessEvidenceError,
            "immutable_output_already_exists",
        ):
            evidence.author_sealed_source_completeness_evidence(
                **self.fixture.kwargs("deterministic-a")
            )

    def test_native_export_tamper_fails_without_partial_output(self) -> None:
        tampered_export_root = self.repository_root / "tamper/native-export"
        tampered_export_root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["cp", "-a", str(self.fixture.native_export_root), str(tampered_export_root)],
            check=True,
        )
        target = next(path for path in tampered_export_root.rglob("*") if path.is_file())
        target.write_bytes(target.read_bytes() + b"tamper")
        kwargs = self.fixture.kwargs("native-tamper")
        kwargs["native_export_root"] = tampered_export_root
        with self.assertRaises(evidence.SourceCompletenessEvidenceError):
            evidence.author_sealed_source_completeness_evidence(**kwargs)
        self.assertFalse((self.repository_root / kwargs["output_root"]).exists())

    def test_snapshot_cross_binding_and_report_tamper_fail_closed(self) -> None:
        tampered_snapshot = self.repository_root / "tamper/cross-snapshot.json"
        tampered_snapshot_sha = _copy_and_reseal(
            self.fixture.approved_snapshot_path,
            tampered_snapshot,
            mutate=lambda value: value.__setitem__(
                "permission_fingerprint",
                evidence._canonical_fingerprint("wrong-permission"),
            ),
            fingerprint_field="snapshot_fingerprint",
        )
        kwargs = self.fixture.kwargs("cross-snapshot")
        kwargs["approved_snapshot_path"] = tampered_snapshot
        kwargs["expected_approved_snapshot_sha256"] = tampered_snapshot_sha
        with self.assertRaises(evidence.SourceCompletenessEvidenceError):
            evidence.author_sealed_source_completeness_evidence(**kwargs)

        tampered_report = self.repository_root / "tamper/report.json"
        tampered_report.write_bytes(self.fixture.approved_report_path.read_bytes() + b" ")
        kwargs = self.fixture.kwargs("report-byte-tamper")
        kwargs["approved_report_path"] = tampered_report
        with self.assertRaisesRegex(
            evidence.SourceCompletenessEvidenceError,
            "approved_report_byte_seal_mismatch",
        ):
            evidence.author_sealed_source_completeness_evidence(**kwargs)

    def test_attestation_workspace_approver_and_tenant_drift_fail_closed(self) -> None:
        for field, value, reason in (
            ("expected_workspace_id", "workspace_other", "identity_scope_binding_mismatch"),
            ("expected_approver_actor", "user_other_approver", "identity_scope_binding_mismatch"),
        ):
            kwargs = self.fixture.kwargs(f"{field}-drift")
            kwargs[field] = value
            with self.assertRaisesRegex(
                evidence.SourceCompletenessEvidenceError,
                reason,
            ):
                evidence.author_sealed_source_completeness_evidence(**kwargs)

        tenant_safe = self.repository_root / "tamper/attestation-safe-tenant.json"
        safe_value = json.loads(self.fixture.attestation_safe_path.read_bytes())
        safe_value["tenant_id"] = "forbidden"
        tenant_safe_sha = _write_json(tenant_safe, safe_value)
        kwargs = self.fixture.kwargs("tenant-drift")
        kwargs["attestation_safe_path"] = tenant_safe
        kwargs["expected_attestation_safe_sha256"] = tenant_safe_sha
        with self.assertRaisesRegex(
            evidence.SourceCompletenessEvidenceError,
            "tenant_dimension_forbidden",
        ):
            evidence.author_sealed_source_completeness_evidence(**kwargs)

    def test_source_manifest_inventory_and_execution_drift_fail_closed(self) -> None:
        kwargs = self.fixture.kwargs("execution-drift")
        kwargs["execution_fingerprint"] = evidence._canonical_fingerprint("other")
        with self.assertRaisesRegex(
            evidence.SourceCompletenessEvidenceError,
            "source_manifest_binding_mismatch",
        ):
            evidence.author_sealed_source_completeness_evidence(**kwargs)

        inventory_path = self.repository_root / "tamper/source-inventory.json"
        inventory = json.loads(self.fixture.source_inventory_path.read_bytes())
        inventory["payload"]["source_item_count"] += 1
        inventory = evidence._with_fingerprint(inventory, "artifact_fingerprint")
        inventory_sha = _write_json(inventory_path, inventory)
        kwargs = self.fixture.kwargs("inventory-drift")
        kwargs["source_inventory_dependency_path"] = inventory_path
        kwargs["expected_source_inventory_dependency_sha256"] = inventory_sha
        with self.assertRaisesRegex(
            evidence.SourceCompletenessEvidenceError,
            "source_inventory_dependency_binding_mismatch",
        ):
            evidence.author_sealed_source_completeness_evidence(**kwargs)

    def test_policy_redaction_requires_complete_typed_contract(self) -> None:
        inventory = SourceInventory.from_dict(self.fixture.approved_snapshot["source_inventory"])
        item = inventory.items[0]
        redacted = replace(
            item,
            processing_state=SourceInventoryProcessingState.INTENTIONALLY_EXCLUDED,
            raw_retention_state=SourceInventoryRawRetentionState.DELETED_BY_POLICY,
            exclusion_policy_id="fixture_policy_v1",
            exclusion_policy_version="1.0.0",
            exclusion_authorized_actor_id="fixture_authorized_actor",
            exclusion_reason="Fixture policy removes one source unit.",
            exclusion_out_of_scope_proof_fingerprint=evidence._canonical_fingerprint(
                "fixture-policy-proof"
            ),
        )
        redacted_inventory = replace(
            inventory,
            items=(redacted, *inventory.items[1:]),
        )
        observation_item_ids = {item.source_inventory_item_id for item in inventory.items[1:]}
        self.assertEqual(
            evidence._typed_policy_redaction_count(
                redacted_inventory,
                observation_item_ids=observation_item_ids,
            ),
            1,
        )
        invalid = replace(redacted, exclusion_policy_id=None)
        with self.assertRaisesRegex(
            evidence.SourceCompletenessEvidenceError,
            "policy_redaction_contract_invalid",
        ):
            evidence._typed_policy_redaction_count(
                replace(inventory, items=(invalid, *inventory.items[1:])),
                observation_item_ids=observation_item_ids,
            )

    def test_safe_report_leak_scanner_and_output_scope_fail_closed(self) -> None:
        report = evidence.author_sealed_source_completeness_evidence(
            **self.fixture.kwargs("safe")
        ).safe_report
        leaked = copy.deepcopy(report)
        leaked["raw_path"] = "/private/source"
        leaked = evidence._with_fingerprint(leaked, "artifact_fingerprint")
        with self.assertRaises(evidence.SourceCompletenessEvidenceError):
            evidence._validate_safe_report(leaked)
        kwargs = self.fixture.kwargs("wrong-scope")
        kwargs["output_root"] = Path("temporary-output")
        with self.assertRaisesRegex(
            evidence.SourceCompletenessEvidenceError,
            "output_root_not_production_scoped",
        ):
            evidence.author_sealed_source_completeness_evidence(**kwargs)


if __name__ == "__main__":
    unittest.main()
