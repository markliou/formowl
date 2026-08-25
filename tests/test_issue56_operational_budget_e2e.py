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
from scripts.issue56_operational_budget import (
    BUNDLE_ARTIFACT_ID,
    FROZEN_ANSWER_BUDGET_FINGERPRINT,
    FROZEN_ANSWER_MODEL_ID,
    FROZEN_ANSWER_PROMPT_FINGERPRINT,
    FROZEN_BUDGET_FINGERPRINT,
    FROZEN_CANONICAL_IMAGE_ID,
    FROZEN_CANONICAL_IMAGE_ARCHITECTURE,
    FROZEN_CANONICAL_IMAGE_CONFIG_FINGERPRINT,
    FROZEN_CANONICAL_IMAGE_ENVIRONMENT_COUNT,
    FROZEN_CANONICAL_IMAGE_LABEL_COUNT,
    FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    FROZEN_CANONICAL_IMAGE_OS,
    FROZEN_CANONICAL_IMAGE_REFERENCE,
    FROZEN_CANONICAL_IMAGE_ROOTFS_LAYER_COUNT,
    FROZEN_CANONICAL_IMAGE_ROOTFS_LAYERS_FINGERPRINT,
    FROZEN_DENSE_MODEL_REVISION,
    FROZEN_DENSE_PROFILE_FINGERPRINT,
    FROZEN_DENSE_RUNTIME_ATTESTATION,
    PEAK_RSS_LIMIT_KIB,
    REPORT_ARTIFACT_ID,
    ZERO_COST_GENERATION_MODE,
    deterministic_zero_cost_attestation_fingerprint,
    fingerprint_canonical_image_metadata_attestation,
    frozen_budget_payload,
    frozen_canonical_image_metadata_attestation,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue56_operational_budget.py"


class Issue56OperationalBudgetEndToEndTests(unittest.TestCase):
    def test_frozen_neural_image_metadata_policy_is_deterministic(self) -> None:
        attestation = frozen_canonical_image_metadata_attestation()
        self.assertEqual(
            fingerprint_canonical_image_metadata_attestation(attestation),
            FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
        )
        self.assertEqual(attestation["image_id"], FROZEN_CANONICAL_IMAGE_ID)
        self.assertEqual(attestation["os"], FROZEN_CANONICAL_IMAGE_OS)
        self.assertEqual(
            attestation["architecture"],
            FROZEN_CANONICAL_IMAGE_ARCHITECTURE,
        )
        self.assertEqual(
            attestation["rootfs_layer_count"],
            FROZEN_CANONICAL_IMAGE_ROOTFS_LAYER_COUNT,
        )
        self.assertEqual(
            attestation["rootfs_layers_fingerprint"],
            FROZEN_CANONICAL_IMAGE_ROOTFS_LAYERS_FINGERPRINT,
        )
        self.assertEqual(
            attestation["config_fingerprint"],
            FROZEN_CANONICAL_IMAGE_CONFIG_FINGERPRINT,
        )
        self.assertEqual(
            attestation["environment_count"],
            FROZEN_CANONICAL_IMAGE_ENVIRONMENT_COUNT,
        )
        self.assertEqual(
            attestation["label_count"],
            FROZEN_CANONICAL_IMAGE_LABEL_COUNT,
        )
        reordered = dict(reversed(tuple(attestation.items())))
        self.assertEqual(
            fingerprint_canonical_image_metadata_attestation(reordered),
            FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
        )
        tampered = dict(attestation)
        tampered["rootfs_layer_count"] += 1
        self.assertNotEqual(
            fingerprint_canonical_image_metadata_attestation(tampered),
            FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
        )
        budget = frozen_budget_payload()
        self.assertEqual(
            budget["container_reference_fingerprint"],
            _sha256_json(FROZEN_CANONICAL_IMAGE_REFERENCE),
        )
        self.assertEqual(
            budget["container_image_metadata_fingerprint"],
            FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
        )

    def test_safe_uat_to_persisted_budget_acceptance_round_trip(self) -> None:
        uat = _valid_uat_report()
        result = _run_uat_cli(uat)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["artifact_id"], REPORT_ARTIFACT_ID)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["operational_budget_status"], "passed")
        self.assertEqual(report["full_quality_gate_status"], "blocked")
        self.assertEqual(report["bundle_round_trip_status"], "passed")
        self.assertEqual(report["budget_fingerprint"], FROZEN_BUDGET_FINGERPRINT)
        self.assertEqual(report["check_status_counts"]["passed"], 4)
        self.assertEqual(report["holdout_content_read_count"], 0)
        self.assertEqual(report["oracle_content_read_count"], 0)
        _assert_safe_report(self, report)

        bundle = json.loads(result.bundle_path.read_text(encoding="utf-8"))
        self.assertEqual(bundle["artifact_id"], BUNDLE_ARTIFACT_ID)
        self.assertEqual(bundle["status"], "passed")
        validation = _run_bundle_cli(result.bundle_path)
        self.assertEqual(validation.returncode, 0, validation.stderr)
        validated_report = json.loads(validation.stdout)
        self.assertEqual(
            validated_report["bundle_fingerprint"],
            report["bundle_fingerprint"],
        )
        self.assertEqual(
            validated_report["report_fingerprint"],
            report["report_fingerprint"],
        )

    def test_threshold_failures_are_explicit_without_quality_claim(self) -> None:
        uat = _valid_uat_report()
        hybrid = uat["arms"]["hybrid_v2_soft"]
        hybrid["latency_ms"]["p95"] = 3000.001
        hybrid["cost_units"]["maximum"] = 101
        uat["resource_measurement"]["peak_memory_kib"] = PEAK_RSS_LIMIT_KIB + 1
        uat["resource_measurement"]["model_usage_cost"] = {
            "status": "measured",
            "external_generation_call_count": 1,
            "input_token_count": 20,
            "output_token_count": 10,
            "monetary_cost_microusd": 0,
        }

        result = _run_uat_cli(uat)
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["full_quality_gate_status"], "blocked")
        self.assertEqual(report["check_status_counts"]["failed"], 4)
        self.assertEqual(
            report["failure_status_ids"],
            [
                "hybrid_v2_p95_latency",
                "hybrid_v2_per_case_internal_cost",
                "model_token_monetary_cost",
                "peak_rss",
            ],
        )
        _assert_safe_report(self, report)

    def test_r4_shape_blocks_on_missing_per_case_max_and_cost_attestation(self) -> None:
        uat = _valid_uat_report()
        del uat["arms"]["hybrid_v2_soft"]["cost_units"]["maximum"]
        uat["resource_measurement"]["model_usage_cost"] = {
            "status": "missing",
            "reason_hash": _sha256_json("usage-not-reported"),
        }

        result = _run_uat_cli(uat)
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            report["check_status_counts"],
            {
                "blocked": 2,
                "failed": 0,
                "passed": 2,
            },
        )
        self.assertEqual(
            report["blocking_status_ids"],
            [
                "hybrid_v2_per_case_internal_cost",
                "model_token_monetary_cost",
            ],
        )
        self.assertEqual(
            report["checks"]["hybrid_v2_p95_latency"]["status"],
            "passed",
        )
        self.assertEqual(report["checks"]["peak_rss"]["status"], "passed")

    def test_measured_generation_requires_tokens_and_positive_monetary_cost(self) -> None:
        uat = _valid_uat_report()
        uat["resource_measurement"]["model_usage_cost"] = {
            "status": "measured",
            "external_generation_call_count": 2,
            "input_token_count": 400,
            "output_token_count": 80,
            "monetary_cost_microusd": 25,
        }
        result = _run_uat_cli(uat)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            report["checks"]["model_token_monetary_cost"]["status"],
            "passed",
        )

    def test_tampered_stale_and_missing_bindings_fail_closed(self) -> None:
        baseline = _valid_uat_report()

        tampered = _run_uat_cli(
            baseline,
            expected_fingerprint=_sha256_json("different-report"),
        )
        _assert_rejected(self, tampered, "uat_report_fingerprint_mismatch")

        stale = copy.deepcopy(baseline)
        stale["shared_pipeline"]["dense_model_revision"] = "stale-revision"
        stale_result = _run_uat_cli(stale)
        _assert_rejected(
            self,
            stale_result,
            "uat_pipeline_binding_mismatch_dense_model_revision",
        )

        missing = copy.deepcopy(baseline)
        del missing["shared_pipeline"]["answer_prompt_fingerprint"]
        missing_result = _run_uat_cli(missing)
        _assert_rejected(
            self,
            missing_result,
            "uat_pipeline_binding_field_missing",
        )

        holdout = copy.deepcopy(baseline)
        holdout["claim_boundary"]["independent_holdout"] = True
        holdout_result = _run_uat_cli(holdout)
        _assert_rejected(
            self,
            holdout_result,
            "uat_claim_boundary_mismatch",
        )

        image_result = _run_uat_cli(
            baseline,
            image_id=_sha256_json("different-image"),
        )
        _assert_rejected(
            self,
            image_result,
            "canonical_image_attestation_mismatch",
        )

        metadata_result = _run_uat_cli(
            baseline,
            metadata_fingerprint=_sha256_json("different-metadata"),
        )
        _assert_rejected(
            self,
            metadata_result,
            "canonical_image_attestation_mismatch",
        )

    def test_persisted_bundle_tamper_is_rejected(self) -> None:
        result = _run_uat_cli(_valid_uat_report())
        self.assertEqual(result.returncode, 0, result.stderr)
        bundle = json.loads(result.bundle_path.read_text(encoding="utf-8"))
        bundle["checks"]["peak_rss"]["measured_count"] += 1
        result.bundle_path.write_text(
            json.dumps(bundle, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        validation = _run_bundle_cli(result.bundle_path)
        _assert_rejected(
            self,
            validation,
            "bundle_check_fingerprint_invalid",
        )


class _CliResult:
    def __init__(
        self,
        *,
        completed: subprocess.CompletedProcess[str],
        bundle_path: Path,
        cleanup: tempfile.TemporaryDirectory[str],
    ) -> None:
        self.returncode = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr
        self.bundle_path = bundle_path
        self._cleanup = cleanup

    def __del__(self) -> None:
        self._cleanup.cleanup()


def _valid_uat_report() -> dict[str, object]:
    zero_cost_attestation = deterministic_zero_cost_attestation_fingerprint()
    return {
        "artifact_id": "formowl_issue56_simulated_human_uat_v1",
        "schema_version": 1,
        "status": "blocked",
        "execution_status": "passed",
        "quality_gate_status": "blocked",
        "diagnostic_label": "diagnostic_same_pipeline_not_independent_holdout",
        "diagnostic_run_fingerprint": _sha256_json("diagnostic-run"),
        "e2e_executed": True,
        "manifest_seal": {
            "sealed_before_execution": True,
            "unchanged_after_execution": True,
            "manifest_byte_hash": _sha256_json("manifest"),
        },
        "shared_pipeline": {
            "dense_model_revision": FROZEN_DENSE_MODEL_REVISION,
            "dense_profile_fingerprint": FROZEN_DENSE_PROFILE_FINGERPRINT,
            "dense_runtime_attestation": FROZEN_DENSE_RUNTIME_ATTESTATION,
            "answer_model_id": FROZEN_ANSWER_MODEL_ID,
            "answer_prompt_fingerprint": FROZEN_ANSWER_PROMPT_FINGERPRINT,
            "answer_budget_fingerprint": FROZEN_ANSWER_BUDGET_FINGERPRINT,
            "all_arms_share_answer_model_prompt_budget_evaluator": True,
        },
        "arms": {
            "hybrid_v2_soft": {
                "scored_case_count": 100,
                "latency_ms": {
                    "p95": 2432.208,
                },
                "cost_units": {
                    "total": 8975,
                    "average_milli": 89750,
                    "maximum": 98,
                },
            }
        },
        "resource_measurement": {
            "peak_memory_kib": 1_477_052,
            "model_usage_cost": {
                "status": "zero_cost_attested",
                "generation_mode": ZERO_COST_GENERATION_MODE,
                "external_generation_call_count": 0,
                "input_token_count": 0,
                "output_token_count": 0,
                "monetary_cost_microusd": 0,
                "attestation_fingerprint": zero_cost_attestation,
            },
        },
        "claim_boundary": {
            "independent_holdout": False,
            "methodology_ready": False,
            "methodology_complete": False,
            "issue56_complete": False,
            "production_ready": False,
            "supports_arm_superiority_claim": False,
        },
    }


def _run_uat_cli(
    payload: dict[str, object],
    *,
    expected_fingerprint: str | None = None,
    image_id: str = FROZEN_CANONICAL_IMAGE_ID,
    metadata_fingerprint: str = FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
) -> _CliResult:
    cleanup = tempfile.TemporaryDirectory(prefix="issue56-operational-budget-")
    temp_root = Path(cleanup.name)
    input_path = temp_root / "uat.safe.json"
    bundle_path = temp_root / "operational-budget.safe.json"
    raw = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    input_path.write_bytes(raw)
    expected = expected_fingerprint or _sha256_bytes(raw)
    environment = os.environ.copy()
    environment.pop("FORMOWL_CANONICAL_IMAGE_ID", None)
    environment.pop("FORMOWL_CANONICAL_IMAGE_METADATA_FINGERPRINT", None)
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--uat-report",
            str(input_path),
            "--expected-uat-report-fingerprint",
            expected,
            "--output",
            str(bundle_path),
            "--canonical-image-id",
            image_id,
            "--canonical-image-metadata-fingerprint",
            metadata_fingerprint,
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return _CliResult(
        completed=completed,
        bundle_path=bundle_path,
        cleanup=cleanup,
    )


def _run_bundle_cli(bundle_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--validate-bundle",
            str(bundle_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_json(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _assert_rejected(
    test_case: unittest.TestCase,
    result: _CliResult | subprocess.CompletedProcess[str],
    reason: str,
) -> None:
    test_case.assertEqual(result.returncode, 3, result.stderr)
    report = json.loads(result.stdout)
    test_case.assertEqual(report["status"], "rejected")
    test_case.assertEqual(report["rejection_status_id"], reason)
    test_case.assertEqual(report["rejection_count"], 1)
    _assert_safe_report(test_case, report)


def _assert_safe_report(
    test_case: unittest.TestCase,
    report: dict[str, object],
) -> None:
    serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
    for forbidden in (
        str(ROOT),
        "/tmp/",
        "query_text",
        "answer_text",
        "subject",
        "sender",
        "filename",
    ):
        test_case.assertNotIn(forbidden, serialized)
    test_case.assertRegex(
        report["report_fingerprint"],
        r"^sha256:[0-9a-f]{64}$",
    )


if __name__ == "__main__":
    unittest.main()
