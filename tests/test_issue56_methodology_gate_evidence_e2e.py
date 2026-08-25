from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any, Mapping

import _paths  # noqa: F401
from formowl_core.methodology_authority import (
    validate_methodology_gate_dependency_manifest,
)
from scripts.issue56_methodology_gate_evidence import (
    ENVELOPE_ARTIFACT_ID,
    GATE_IDS,
    INPUT_ARTIFACT_ID,
    REPORT_ARTIFACT_ID,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue56_methodology_gate_evidence.py"
OUTPUT_ROOT = Path("evidence/production/issue56-methodology-gates-v3")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _seal(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(field_name, None)
    result[field_name] = _fingerprint(result)
    return result


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    encoded = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _write_bytes(path: Path, value: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _source_dependency(
    *,
    artifact_id: str,
    payload: Mapping[str, Any],
    dependency_paths: list[str] | None = None,
) -> dict[str, Any]:
    return _seal(
        {
            "artifact_id": artifact_id,
            "dependency_paths": sorted(dependency_paths or []),
            "payload": dict(payload),
        },
        "artifact_fingerprint",
    )


def _gate_dependency(
    *,
    artifact_id: str,
    gate_id: str,
    execution_fingerprint: str,
    source_manifest_sha256: str,
    payload: Mapping[str, Any],
    dependency_paths: list[str] | None = None,
) -> dict[str, Any]:
    return _seal(
        {
            "artifact_id": artifact_id,
            "gate_id": gate_id,
            "execution_fingerprint": execution_fingerprint,
            "source_manifest_sha256": source_manifest_sha256,
            "status": "passed",
            "evidence_classification": "production",
            "dependency_paths": sorted(dependency_paths or []),
            "payload": dict(payload),
        },
        "artifact_fingerprint",
    )


class ProductionFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.execution_fingerprint = _fingerprint("execution-v1")
        self.authority_id = "formowl_methodology_authority_v1"
        self.source_manifest_path = Path("evidence/production/source-manifest.json")
        self.input_manifest_path = Path("evidence/production/authoring-input.json")
        self.common_references: list[dict[str, str]] = []
        self.gate_references: dict[str, list[dict[str, str]]] = {
            gate_id: [] for gate_id in GATE_IDS
        }
        self.role_paths: dict[tuple[str, str], Path] = {}
        self._build()

    def _reference(self, *, gate_id: str | None, role: str, path: Path) -> None:
        reference = {"role": role, "path": path.as_posix()}
        if gate_id is None:
            self.common_references.append(reference)
        else:
            self.gate_references[gate_id].append(reference)
        self.role_paths[(gate_id or "common", role)] = path

    def _build(self) -> None:
        source_item_path = Path("evidence/production/source-item.bin")
        model_path = Path("evidence/production/model.bin")
        package_lock_path = Path("evidence/production/package.lock")
        source_item_sha = _write_bytes(self.root / source_item_path, b"real-source")
        model_sha = _write_bytes(self.root / model_path, b"pinned-model")
        package_lock_sha = _write_bytes(self.root / package_lock_path, b"lock")
        for role, path in (
            ("model_artifact", model_path),
            ("package_lock", package_lock_path),
            ("source_item", source_item_path),
        ):
            self._reference(gate_id=None, role=role, path=path)

        case_path = Path("evidence/production/case-manifest.json")
        case = _source_dependency(
            artifact_id="formowl_methodology_case_manifest_dependency_v1",
            payload={
                "case_count": 100,
                "case_scope": "combined_independent_acceptance",
            },
        )
        case_sha = _write_json(self.root / case_path, case)
        self._reference(gate_id=None, role="case_manifest", path=case_path)

        configuration_path = Path("evidence/production/configuration-manifest.json")
        configuration = _source_dependency(
            artifact_id="formowl_methodology_configuration_manifest_dependency_v1",
            payload={
                "evaluation_policy_id": ("raw_source_oracle_same_pipeline_end_answer_v1"),
                "method_id": "evidence_to_knowledge_kg_ontology_v2_hybrid_v1",
                "tokenizer_id": ("jieba_sentencepiece_frozen_profile_candidate_admission_v1"),
            },
        )
        configuration_sha = _write_json(
            self.root / configuration_path,
            configuration,
        )
        self._reference(
            gate_id=None,
            role="configuration_manifest",
            path=configuration_path,
        )

        inventory_path = Path("evidence/production/source-inventory.json")
        inventory = _source_dependency(
            artifact_id="formowl_methodology_source_inventory_dependency_v1",
            dependency_paths=[source_item_path.as_posix()],
            payload={
                "source_count": 1,
                "source_item_count": 100,
                "source_hashes": [source_item_sha],
                "source_paths": [source_item_path.as_posix()],
            },
        )
        inventory_sha = _write_json(self.root / inventory_path, inventory)
        self._reference(
            gate_id=None,
            role="source_inventory_manifest",
            path=inventory_path,
        )

        source_manifest = _seal(
            {
                "artifact_id": "formowl_methodology_source_manifest_v1",
                "execution_fingerprint": self.execution_fingerprint,
                "source_kind": "real_source",
                "source_count": 1,
                "source_item_count": 100,
                "source_hashes": [source_item_sha],
                "case_manifest_sha256": case_sha,
                "configuration_manifest_sha256": configuration_sha,
                "model_artifact_hashes": [model_sha],
                "package_lock_sha256": package_lock_sha,
            },
            "manifest_fingerprint",
        )
        source_manifest_sha = _write_json(
            self.root / self.source_manifest_path,
            source_manifest,
        )

        source_gate = "source_completeness_compared_with_raw_oracle"
        raw_oracle_path = Path("evidence/production/raw-source-oracle.json")
        raw_oracle = _gate_dependency(
            artifact_id="formowl_methodology_raw_source_oracle_dependency_v1",
            gate_id=source_gate,
            execution_fingerprint=self.execution_fingerprint,
            source_manifest_sha256=source_manifest_sha,
            payload={
                "raw_source_unit_count": 100,
                "source_inventory_sha256": inventory_sha,
            },
        )
        raw_oracle_sha = _write_json(self.root / raw_oracle_path, raw_oracle)
        self._reference(
            gate_id=source_gate,
            role="raw_source_oracle_manifest",
            path=raw_oracle_path,
        )
        reconciliation_path = Path("evidence/production/observation-reconciliation.json")
        reconciliation = _gate_dependency(
            artifact_id=("formowl_methodology_observation_reconciliation_dependency_v1"),
            gate_id=source_gate,
            execution_fingerprint=self.execution_fingerprint,
            source_manifest_sha256=source_manifest_sha,
            payload={
                "raw_source_unit_count": 100,
                "emitted_observation_unit_count": 100,
                "policy_redacted_unit_count": 0,
                "unexplained_loss_unit_count": 0,
                "loss_taxonomy_counts": {},
                "raw_source_oracle_sha256": raw_oracle_sha,
                "source_inventory_sha256": inventory_sha,
            },
        )
        _write_json(self.root / reconciliation_path, reconciliation)
        self._reference(
            gate_id=source_gate,
            role="observation_reconciliation_report",
            path=reconciliation_path,
        )

        binding_gate = "evaluation_reports_bind_execution_fingerprint"
        report_path = Path("evidence/production/evaluation-report.json")
        report = _gate_dependency(
            artifact_id="formowl_methodology_evaluation_report_dependency_v1",
            gate_id=binding_gate,
            execution_fingerprint=self.execution_fingerprint,
            source_manifest_sha256=source_manifest_sha,
            payload={
                "case_manifest_sha256": case_sha,
                "evaluation_policy_fingerprint": configuration_sha,
                "execution_status": "passed",
                "quality_gate_status": "passed",
                "report_kind": "completed_quality_report",
            },
        )
        report_sha = _write_json(self.root / report_path, report)
        self._reference(
            gate_id=binding_gate,
            role="evaluation_report",
            path=report_path,
        )
        report_index_path = Path("evidence/production/evaluation-report-index.json")
        report_index = _gate_dependency(
            artifact_id=("formowl_methodology_evaluation_report_index_dependency_v1"),
            gate_id=binding_gate,
            execution_fingerprint=self.execution_fingerprint,
            source_manifest_sha256=source_manifest_sha,
            dependency_paths=[report_path.as_posix()],
            payload={
                "report_count": 1,
                "report_hashes": [report_sha],
                "report_paths": [report_path.as_posix()],
            },
        )
        _write_json(self.root / report_index_path, report_index)
        self._reference(
            gate_id=binding_gate,
            role="evaluation_report_index",
            path=report_index_path,
        )

        ablation_gate = "same_pipeline_real_source_ablation"
        for arm_id in ("kg_only", "kg_plus_ontology_hybrid_v2"):
            arm_path = Path(f"evidence/production/{arm_id}.json")
            arm = _gate_dependency(
                artifact_id=("formowl_methodology_ablation_arm_result_dependency_v1"),
                gate_id=ablation_gate,
                execution_fingerprint=self.execution_fingerprint,
                source_manifest_sha256=source_manifest_sha,
                payload={
                    "arm_id": arm_id,
                    "case_count": 100,
                    "completed_case_count": 100,
                    "adjudicated_case_count": 100,
                    "case_manifest_sha256": case_sha,
                    "evaluation_policy_fingerprint": configuration_sha,
                    "execution_status": "passed",
                    "quality_gate_status": "passed",
                },
            )
            _write_json(self.root / arm_path, arm)
            self._reference(
                gate_id=ablation_gate,
                role="ablation_arm_result",
                path=arm_path,
            )

        acceptance_gate = "real_user_end_answer_acceptance"
        acceptance_path = Path("evidence/production/final-answer-acceptance.json")
        acceptance = _gate_dependency(
            artifact_id=("formowl_methodology_final_answer_acceptance_dependency_v1"),
            gate_id=acceptance_gate,
            execution_fingerprint=self.execution_fingerprint,
            source_manifest_sha256=source_manifest_sha,
            payload={
                "acceptance_profile_id": "real_user_end_answer_strict_v1",
                "acceptance_scope": "independent_holdout_and_transfer",
                "case_count": 100,
                "adjudicated_case_count": 100,
                "answerable_case_count": 90,
                "correct_answer_count": 81,
                "citation_supported_correct_count": 81,
                "permission_denial_case_count": 10,
                "permission_denial_pass_count": 10,
                "observed_accuracy_ppm": 900_000,
                "observed_citation_support_ppm": 1_000_000,
                "case_manifest_sha256": case_sha,
                "evaluation_policy_fingerprint": configuration_sha,
                "execution_status": "passed",
                "quality_gate_status": "passed",
            },
        )
        _write_json(self.root / acceptance_path, acceptance)
        self._reference(
            gate_id=acceptance_gate,
            role="final_answer_acceptance_report",
            path=acceptance_path,
        )

        self.write_input()

    def input_payload(self) -> dict[str, Any]:
        return _seal(
            {
                "artifact_id": INPUT_ARTIFACT_ID,
                "authority_id": self.authority_id,
                "execution_fingerprint": self.execution_fingerprint,
                "source_manifest_path": self.source_manifest_path.as_posix(),
                "common_dependencies": sorted(
                    self.common_references,
                    key=lambda item: (item["role"], item["path"]),
                ),
                "gates": [
                    {
                        "gate_id": gate_id,
                        "dependencies": sorted(
                            self.gate_references[gate_id],
                            key=lambda item: (item["role"], item["path"]),
                        ),
                    }
                    for gate_id in sorted(GATE_IDS)
                ],
            },
            "manifest_fingerprint",
        )

    def write_input(self, payload: Mapping[str, Any] | None = None) -> None:
        _write_json(
            self.root / self.input_manifest_path,
            payload or self.input_payload(),
        )

    def artifact(self, gate_id: str, role: str) -> tuple[Path, dict[str, Any]]:
        relative_path = self.role_paths[(gate_id, role)]
        return relative_path, json.loads((self.root / relative_path).read_text(encoding="utf-8"))


def _run_cli(
    fixture: ProductionFixture,
    *,
    output_root: Path = OUTPUT_ROOT,
    preflight_only: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--repository-root",
        str(fixture.root),
        "--input-manifest",
        fixture.input_manifest_path.as_posix(),
        "--output-root",
        output_root.as_posix(),
        "--preflight-only" if preflight_only else "--author",
    ]
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class Issue56MethodologyGateEvidenceEndToEndTests(unittest.TestCase):
    def test_preflight_and_atomic_authoring_validate_with_production_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ProductionFixture(Path(temp_dir))
            preflight = _run_cli(fixture, preflight_only=True)
            self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
            preflight_report = json.loads(preflight.stdout)
            self.assertEqual(preflight_report["artifact_id"], REPORT_ARTIFACT_ID)
            self.assertEqual(preflight_report["status"], "passed")
            self.assertEqual(
                preflight_report["authoring_status"],
                "preflight_completed",
            )
            self.assertEqual(preflight_report["gate_count"], 4)
            self.assertFalse((fixture.root / OUTPUT_ROOT).exists())

            authored = _run_cli(fixture)
            self.assertEqual(authored.returncode, 0, authored.stdout + authored.stderr)
            report = json.loads(authored.stdout)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["authoring_status"], "authoring_completed")
            self.assertEqual(report["promotion_status"], "not_performed")
            self.assertEqual(report["result_artifact_count"], 4)
            self.assertEqual(report["dependency_manifest_count"], 4)
            self.assertEqual(report["envelope_count"], 4)
            self.assertRegex(report["bundle_fingerprint"], r"^sha256:[0-9a-f]{64}$")
            self.assertFalse(any("path" in key for key in report))

            source_manifest = json.loads(
                (fixture.root / fixture.source_manifest_path).read_text(encoding="utf-8")
            )
            for gate_id in GATE_IDS:
                gate_root = fixture.root / OUTPUT_ROOT / gate_id
                result_path = gate_root / "result.json"
                result = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertTrue(
                    validate_methodology_gate_dependency_manifest(
                        repository_root=fixture.root,
                        gate_id=gate_id,
                        source_manifest_path=(fixture.root / fixture.source_manifest_path),
                        result_artifact_path=result_path,
                        source_manifest=source_manifest,
                        result_artifact=result,
                        execution_fingerprint=fixture.execution_fingerprint,
                    )
                )
                envelope = json.loads((gate_root / "evidence-v3.json").read_text(encoding="utf-8"))
                self.assertEqual(envelope["artifact_id"], ENVELOPE_ARTIFACT_ID)
                self.assertEqual(envelope["gate_id"], gate_id)
                self.assertEqual(envelope["status"], "passed")
                self.assertEqual(envelope["promotion_status"], "not_performed")
                self.assertEqual(
                    envelope["envelope_fingerprint"],
                    _fingerprint(
                        {
                            key: value
                            for key, value in envelope.items()
                            if key != "envelope_fingerprint"
                        }
                    ),
                )

            retry = _run_cli(fixture)
            self.assertEqual(retry.returncode, 2)
            self.assertEqual(json.loads(retry.stdout)["rejection_status"], "output_exists")

    def test_blocked_diagnostic_and_preflight_dependencies_fail_closed(self) -> None:
        mutations = (
            ("status", "blocked"),
            ("evidence_classification", "diagnostic"),
            ("payload.quality_gate_status", "preflight"),
        )
        for field_name, value in mutations:
            with self.subTest(field_name=field_name), tempfile.TemporaryDirectory() as temp_dir:
                fixture = ProductionFixture(Path(temp_dir))
                relative_path, artifact = fixture.artifact(
                    "evaluation_reports_bind_execution_fingerprint",
                    "evaluation_report",
                )
                if field_name.startswith("payload."):
                    artifact["payload"][field_name.split(".", 1)[1]] = value
                else:
                    artifact[field_name] = value
                artifact = _seal(artifact, "artifact_fingerprint")
                _write_json(fixture.root / relative_path, artifact)

                result = _run_cli(fixture)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(
                    json.loads(result.stdout)["rejection_status"],
                    "dependency_disallowed_state",
                )
                self.assertFalse((fixture.root / OUTPUT_ROOT).exists())

    def test_unsafe_unsealed_missing_and_unlisted_inputs_leave_no_partial_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ProductionFixture(Path(temp_dir))
            payload = fixture.input_payload()
            payload["common_dependencies"][0]["path"] = "/tmp/private.json"
            fixture.write_input(_seal(payload, "manifest_fingerprint"))
            result = _run_cli(fixture)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                json.loads(result.stdout)["rejection_status"],
                "unsafe_artifact_path",
            )
            self.assertFalse((fixture.root / OUTPUT_ROOT).exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ProductionFixture(Path(temp_dir))
            relative_path, artifact = fixture.artifact(
                "evaluation_reports_bind_execution_fingerprint",
                "evaluation_report",
            )
            artifact["payload"]["report_kind"] = "tampered"
            _write_json(fixture.root / relative_path, artifact)
            result = _run_cli(fixture)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                json.loads(result.stdout)["rejection_status"],
                "dependency_unsealed",
            )
            self.assertFalse((fixture.root / OUTPUT_ROOT).exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ProductionFixture(Path(temp_dir))
            missing_path = fixture.role_paths[
                ("real_user_end_answer_acceptance", "final_answer_acceptance_report")
            ]
            (fixture.root / missing_path).unlink()
            result = _run_cli(fixture)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                json.loads(result.stdout)["rejection_status"],
                "artifact_missing",
            )
            self.assertFalse((fixture.root / OUTPUT_ROOT).exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ProductionFixture(Path(temp_dir))
            extra_path = Path("evidence/production/unlisted.json")
            _write_json(fixture.root / extra_path, {"safe": True})
            index_path, index = fixture.artifact(
                "evaluation_reports_bind_execution_fingerprint",
                "evaluation_report_index",
            )
            index["dependency_paths"] = sorted([*index["dependency_paths"], extra_path.as_posix()])
            index = _seal(index, "artifact_fingerprint")
            _write_json(fixture.root / index_path, index)
            result = _run_cli(fixture)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertEqual(
                json.loads(result.stdout)["rejection_status"],
                "production_dependency_validation_failed",
            )
            self.assertFalse((fixture.root / OUTPUT_ROOT).exists())

    def test_cross_run_cross_execution_and_self_asserted_hashes_are_rejected(
        self,
    ) -> None:
        mutations = ("cross_run", "cross_execution", "self_asserted_hash")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                fixture = ProductionFixture(Path(temp_dir))
                if mutation == "cross_run":
                    relative_path, artifact = fixture.artifact(
                        "evaluation_reports_bind_execution_fingerprint",
                        "evaluation_report",
                    )
                    artifact["source_manifest_sha256"] = _fingerprint("another-source-run")
                    artifact = _seal(artifact, "artifact_fingerprint")
                    _write_json(fixture.root / relative_path, artifact)
                elif mutation == "cross_execution":
                    relative_path, artifact = fixture.artifact(
                        "same_pipeline_real_source_ablation",
                        "ablation_arm_result",
                    )
                    artifact["execution_fingerprint"] = _fingerprint("another-execution")
                    artifact = _seal(artifact, "artifact_fingerprint")
                    _write_json(fixture.root / relative_path, artifact)
                else:
                    source_manifest = json.loads(
                        (fixture.root / fixture.source_manifest_path).read_text(encoding="utf-8")
                    )
                    source_manifest["source_hashes"] = [_fingerprint("self-asserted-source")]
                    source_manifest = _seal(
                        source_manifest,
                        "manifest_fingerprint",
                    )
                    _write_json(
                        fixture.root / fixture.source_manifest_path,
                        source_manifest,
                    )

                result = _run_cli(fixture)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(
                    json.loads(result.stdout)["rejection_status"],
                    "production_dependency_validation_failed",
                )
                self.assertFalse((fixture.root / OUTPUT_ROOT).exists())

    def test_missing_future_real_gate_evidence_fails_before_authoring(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = ProductionFixture(Path(temp_dir))
            payload = copy.deepcopy(fixture.input_payload())
            for gate in payload["gates"]:
                if gate["gate_id"] == "real_user_end_answer_acceptance":
                    gate["dependencies"] = []
            fixture.write_input(_seal(payload, "manifest_fingerprint"))

            result = _run_cli(fixture)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertEqual(
                json.loads(result.stdout)["rejection_status"],
                "dependency_role_missing",
            )
            self.assertFalse((fixture.root / OUTPUT_ROOT).exists())
            self.assertFalse(
                any(
                    path.name.endswith(".authoring.lock") or ".stage-" in path.name
                    for path in (fixture.root / OUTPUT_ROOT.parent).iterdir()
                )
            )


if __name__ == "__main__":
    unittest.main()
