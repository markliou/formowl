#!/usr/bin/env python3
"""Freeze and validate the Issue #56 local-CPU POC operational budget.

The validator consumes only the existing safe aggregate UAT report. It does not
read case manifests, holdout questions, oracle answers, or source payloads.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
BUDGET_ARTIFACT_ID = "formowl_issue56_operational_budget_v1"
BUNDLE_ARTIFACT_ID = "formowl_issue56_operational_budget_acceptance_bundle_v1"
REPORT_ARTIFACT_ID = "formowl_issue56_operational_budget_public_report_v1"
ERROR_ARTIFACT_ID = "formowl_issue56_operational_budget_rejection_v1"
UAT_ARTIFACT_ID = "formowl_issue56_simulated_human_uat_v1"

BUDGET_POLICY_ID = "issue56_pre_holdout_local_cpu_poc_budget_v1"
MEASUREMENT_POLICY_ID = "issue56_safe_aggregate_operational_measurement_v1"
DEVELOPMENT_BOUNDARY_ID = "diagnostic_same_pipeline_not_independent_holdout"
HYBRID_ARM_ID = "hybrid_v2_soft"

LATENCY_P95_LIMIT_MICROS = 3_000_000
INTERNAL_COST_UNITS_PER_CASE_LIMIT = 100
PEAK_RSS_LIMIT_KIB = 2 * 1024 * 1024

FROZEN_HARDWARE_RUNTIME_CLASS = "linux_amd64_x86_64_local_cpu_poc_v1"
FROZEN_PYTHON_IMPLEMENTATION = "CPython"
FROZEN_PYTHON_VERSION = "3.12.11"
FROZEN_MACHINE = "x86_64"
FROZEN_POINTER_BITS = 64
FROZEN_CANONICAL_IMAGE_REFERENCE = "formowl-kg-bert-cpu:issue56"
FROZEN_CANONICAL_IMAGE_ID = (
    "sha256:8696894cefb9ec2e3564c955a077a83cb7ed7f00083c86b79cd74aebac57cf9a"
)
IMAGE_METADATA_POLICY_ID = "docker_image_inspect_safe_content_attestation_v1"
FROZEN_CANONICAL_IMAGE_OS = "linux"
FROZEN_CANONICAL_IMAGE_ARCHITECTURE = "amd64"
FROZEN_CANONICAL_IMAGE_VARIANT = ""
FROZEN_CANONICAL_IMAGE_ROOTFS_TYPE = "layers"
FROZEN_CANONICAL_IMAGE_ROOTFS_LAYER_COUNT = 10
FROZEN_CANONICAL_IMAGE_ROOTFS_LAYERS_FINGERPRINT = (
    "sha256:af6890ce9296371629fd16aba1cfd2cd10e4bb4eae53b50496f899bfffc84917"
)
FROZEN_CANONICAL_IMAGE_CONFIG_FINGERPRINT = (
    "sha256:e67d76a45bc106df3a347ff077489bcab32eac0ad7c3eac4d80dd40504585f4b"
)
FROZEN_CANONICAL_IMAGE_ENVIRONMENT_COUNT = 16
FROZEN_CANONICAL_IMAGE_LABEL_COUNT = 0
FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT = (
    "sha256:cc3640efdfcd58b3e7c8d0b58063f657d1f301dda5ac803e765ea1f1702be6c7"
)

FROZEN_DENSE_MODEL_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
FROZEN_DENSE_PROFILE_FINGERPRINT = (
    "sha256:39185d72bbf32944bd5498e7ac105311db90ca724f790d0bb123499691ae2b54"
)
FROZEN_DENSE_RUNTIME_ATTESTATION = "pinned_real_e5_normal_path"
FROZEN_ANSWER_MODEL_ID = "formowl_deterministic_evidence_answer_v1"
FROZEN_ANSWER_PROMPT_FINGERPRINT = (
    "sha256:1729824f3ecab2106e36e184a035f13f71e6e45cc094a98cf6b4a4712d4c5ab4"
)
FROZEN_ANSWER_BUDGET_FINGERPRINT = (
    "sha256:a2fa76e5fe612518811badf4cde452aac0fd34d27ebe1e3fc5fb9281e853d99f"
)

ZERO_COST_ATTESTATION_ID = "issue56_deterministic_no_external_generation_v1"
ZERO_COST_GENERATION_MODE = "deterministic_no_external_generation"

CHECK_IDS = (
    "hybrid_v2_p95_latency",
    "hybrid_v2_per_case_internal_cost",
    "peak_rss",
    "model_token_monetary_cost",
)
_STATUS_VALUES = {"passed", "failed", "blocked"}
_MAX_INPUT_BYTES = 4 * 1024 * 1024
_HASH_LENGTH = 71


class OperationalBudgetValidationError(RuntimeError):
    """Fail-closed validation error with a stable public reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def frozen_canonical_image_metadata_attestation() -> dict[str, Any]:
    """Return the safe deterministic projection of Docker image inspect."""

    return {
        "policy_id": IMAGE_METADATA_POLICY_ID,
        "image_id": FROZEN_CANONICAL_IMAGE_ID,
        "os": FROZEN_CANONICAL_IMAGE_OS,
        "architecture": FROZEN_CANONICAL_IMAGE_ARCHITECTURE,
        "variant": FROZEN_CANONICAL_IMAGE_VARIANT,
        "rootfs_type": FROZEN_CANONICAL_IMAGE_ROOTFS_TYPE,
        "rootfs_layer_count": FROZEN_CANONICAL_IMAGE_ROOTFS_LAYER_COUNT,
        "rootfs_layers_fingerprint": (FROZEN_CANONICAL_IMAGE_ROOTFS_LAYERS_FINGERPRINT),
        "config_fingerprint": FROZEN_CANONICAL_IMAGE_CONFIG_FINGERPRINT,
        "environment_count": FROZEN_CANONICAL_IMAGE_ENVIRONMENT_COUNT,
        "label_count": FROZEN_CANONICAL_IMAGE_LABEL_COUNT,
    }


def fingerprint_canonical_image_metadata_attestation(
    attestation: Mapping[str, Any],
) -> str:
    """Fingerprint one exact safe Docker-inspect metadata attestation."""

    required_keys = {
        "policy_id",
        "image_id",
        "os",
        "architecture",
        "variant",
        "rootfs_type",
        "rootfs_layer_count",
        "rootfs_layers_fingerprint",
        "config_fingerprint",
        "environment_count",
        "label_count",
    }
    if set(attestation) != required_keys:
        raise OperationalBudgetValidationError("canonical_image_metadata_attestation_invalid")
    if attestation.get("policy_id") != IMAGE_METADATA_POLICY_ID:
        raise OperationalBudgetValidationError("canonical_image_metadata_policy_mismatch")
    _require_sha256_value(
        attestation.get("image_id"),
        "canonical_image_metadata_attestation_invalid",
    )
    _require_sha256_value(
        attestation.get("rootfs_layers_fingerprint"),
        "canonical_image_metadata_attestation_invalid",
    )
    _require_sha256_value(
        attestation.get("config_fingerprint"),
        "canonical_image_metadata_attestation_invalid",
    )
    for field in (
        "rootfs_layer_count",
        "environment_count",
        "label_count",
    ):
        _nonnegative_int(
            attestation.get(field),
            "canonical_image_metadata_attestation_invalid",
        )
    for field in (
        "os",
        "architecture",
        "variant",
        "rootfs_type",
    ):
        if not isinstance(attestation.get(field), str):
            raise OperationalBudgetValidationError("canonical_image_metadata_attestation_invalid")
    return _sha256_json(dict(attestation))


def deterministic_zero_cost_attestation_fingerprint() -> str:
    """Return the required explicit deterministic/no-generation attestation."""

    return _sha256_json(
        {
            "attestation_id": ZERO_COST_ATTESTATION_ID,
            "answer_model_fingerprint": _sha256_json(FROZEN_ANSWER_MODEL_ID),
            "generation_mode": ZERO_COST_GENERATION_MODE,
            "external_generation_call_count": 0,
            "input_token_count": 0,
            "output_token_count": 0,
            "monetary_cost_microusd": 0,
        }
    )


def frozen_budget_payload() -> dict[str, Any]:
    """Return the immutable safe budget definition."""

    payload = {
        "artifact_id": BUDGET_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "frozen",
        "pre_holdout_registration_status": "passed",
        "development_evidence_only_status": "passed",
        "holdout_content_read_count": 0,
        "oracle_content_read_count": 0,
        "latency_p95_limit_micros": LATENCY_P95_LIMIT_MICROS,
        "internal_cost_units_per_case_limit": INTERNAL_COST_UNITS_PER_CASE_LIMIT,
        "peak_rss_limit_kib": PEAK_RSS_LIMIT_KIB,
        "hardware_runtime_class_fingerprint": _sha256_json(FROZEN_HARDWARE_RUNTIME_CLASS),
        "python_runtime_fingerprint": _sha256_json(
            {
                "implementation": FROZEN_PYTHON_IMPLEMENTATION,
                "version": FROZEN_PYTHON_VERSION,
                "machine": FROZEN_MACHINE,
                "pointer_bits": FROZEN_POINTER_BITS,
            }
        ),
        "container_reference_fingerprint": _sha256_json(FROZEN_CANONICAL_IMAGE_REFERENCE),
        "container_image_id": FROZEN_CANONICAL_IMAGE_ID,
        "container_image_metadata_fingerprint": (FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
        "container_image_metadata_policy_fingerprint": _sha256_json(IMAGE_METADATA_POLICY_ID),
        "container_image_os_fingerprint": _sha256_json(FROZEN_CANONICAL_IMAGE_OS),
        "container_image_architecture_fingerprint": _sha256_json(
            FROZEN_CANONICAL_IMAGE_ARCHITECTURE
        ),
        "container_image_rootfs_layer_count": (FROZEN_CANONICAL_IMAGE_ROOTFS_LAYER_COUNT),
        "container_image_environment_count": (FROZEN_CANONICAL_IMAGE_ENVIRONMENT_COUNT),
        "container_image_label_count": FROZEN_CANONICAL_IMAGE_LABEL_COUNT,
        "dense_model_revision_fingerprint": _sha256_json(FROZEN_DENSE_MODEL_REVISION),
        "dense_profile_fingerprint": FROZEN_DENSE_PROFILE_FINGERPRINT,
        "dense_runtime_attestation_fingerprint": _sha256_json(FROZEN_DENSE_RUNTIME_ATTESTATION),
        "answer_model_fingerprint": _sha256_json(FROZEN_ANSWER_MODEL_ID),
        "answer_prompt_fingerprint": FROZEN_ANSWER_PROMPT_FINGERPRINT,
        "answer_budget_fingerprint": FROZEN_ANSWER_BUDGET_FINGERPRINT,
        "zero_cost_attestation_fingerprint": (deterministic_zero_cost_attestation_fingerprint()),
        "measurement_policy_fingerprint": _sha256_json(
            {
                "policy_id": MEASUREMENT_POLICY_ID,
                "arm_id": HYBRID_ARM_ID,
                "latency_statistic": "p95_wall_clock_milliseconds",
                "internal_cost_statistic": "maximum_per_case_cost_units",
                "memory_statistic": "process_peak_rss_kib",
                "zero_cost_requires": ZERO_COST_ATTESTATION_ID,
                "nonzero_generation_requires": (
                    "explicit_input_output_token_counts_and_monetary_microusd"
                ),
                "development_boundary_id": DEVELOPMENT_BOUNDARY_ID,
            }
        ),
        "budget_policy_fingerprint": _sha256_json(BUDGET_POLICY_ID),
    }
    payload["budget_fingerprint"] = _sha256_json(payload)
    return payload


FROZEN_BUDGET_FINGERPRINT = frozen_budget_payload()["budget_fingerprint"]


def validate_uat_report(
    *,
    report_path: Path,
    expected_report_fingerprint: str,
    canonical_image_id: str | None,
    canonical_image_metadata_fingerprint: str | None,
) -> dict[str, Any]:
    """Validate one safe development UAT report against the frozen budget."""

    _require_sha256(
        expected_report_fingerprint,
        "expected_uat_report_fingerprint_missing_or_invalid",
    )
    report_bytes, report = _read_json_object(
        report_path,
        invalid_reason="uat_report_missing_or_invalid",
    )
    report_fingerprint = _sha256_bytes(report_bytes)
    if report_fingerprint != expected_report_fingerprint:
        raise OperationalBudgetValidationError("uat_report_fingerprint_mismatch")

    _validate_current_runtime(
        canonical_image_id=canonical_image_id,
        canonical_image_metadata_fingerprint=(canonical_image_metadata_fingerprint),
    )
    _validate_uat_identity_and_boundary(report)
    shared = _require_mapping(report, "shared_pipeline")
    _validate_frozen_pipeline_bindings(shared)

    arm = _require_mapping(_require_mapping(report, "arms"), HYBRID_ARM_ID)
    resource_measurement = _require_mapping(report, "resource_measurement")
    checks = {
        "hybrid_v2_p95_latency": _latency_check(arm),
        "hybrid_v2_per_case_internal_cost": _internal_cost_check(arm),
        "peak_rss": _peak_rss_check(resource_measurement),
        "model_token_monetary_cost": _model_cost_check(
            resource_measurement=resource_measurement,
            shared_pipeline=shared,
        ),
    }
    status_counts = {
        status: sum(check["status"] == status for check in checks.values())
        for status in ("passed", "failed", "blocked")
    }
    if status_counts["blocked"]:
        status = "blocked"
    elif status_counts["failed"]:
        status = "failed"
    else:
        status = "passed"

    blocker_ids = sorted(
        check_id for check_id, check in checks.items() if check["status"] == "blocked"
    )
    failure_ids = sorted(
        check_id for check_id, check in checks.items() if check["status"] == "failed"
    )
    runtime_binding_fingerprint = _sha256_json(
        {
            "hardware_runtime_class_fingerprint": frozen_budget_payload()[
                "hardware_runtime_class_fingerprint"
            ],
            "python_runtime_fingerprint": frozen_budget_payload()["python_runtime_fingerprint"],
            "container_image_id": FROZEN_CANONICAL_IMAGE_ID,
            "container_image_metadata_fingerprint": (FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT),
            "dense_model_revision_fingerprint": _sha256_json(FROZEN_DENSE_MODEL_REVISION),
            "dense_profile_fingerprint": FROZEN_DENSE_PROFILE_FINGERPRINT,
            "answer_model_fingerprint": _sha256_json(FROZEN_ANSWER_MODEL_ID),
            "answer_prompt_fingerprint": FROZEN_ANSWER_PROMPT_FINGERPRINT,
            "answer_budget_fingerprint": FROZEN_ANSWER_BUDGET_FINGERPRINT,
        }
    )
    bundle = {
        "artifact_id": BUNDLE_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "operational_budget_status": status,
        "full_quality_gate_status": "blocked",
        "pre_holdout_registration_status": "passed",
        "holdout_content_read_count": 0,
        "oracle_content_read_count": 0,
        "budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
        "uat_report_fingerprint": report_fingerprint,
        "uat_content_fingerprint": _sha256_json(report),
        "uat_run_fingerprint": _require_sha256_value(
            report.get("diagnostic_run_fingerprint"),
            "uat_run_fingerprint_missing_or_invalid",
        ),
        "runtime_binding_fingerprint": runtime_binding_fingerprint,
        "check_set_fingerprint": _sha256_json(checks),
        "check_count": len(checks),
        "check_status_counts": status_counts,
        "blocking_status_ids": blocker_ids,
        "failure_status_ids": failure_ids,
        "checks": checks,
    }
    bundle["bundle_fingerprint"] = _sha256_json(bundle)
    _validate_bundle(bundle)
    return bundle


def persist_bundle(bundle: Mapping[str, Any], output_path: Path) -> dict[str, Any]:
    """Persist once, read back, and prove the immutable round trip."""

    _validate_bundle(bundle)
    _write_new_json(output_path, bundle)
    _, persisted = _read_json_object(
        output_path,
        invalid_reason="persisted_bundle_round_trip_failed",
    )
    _validate_bundle(persisted)
    if persisted != bundle:
        raise OperationalBudgetValidationError("persisted_bundle_round_trip_failed")
    return _public_report(persisted, round_trip_status="passed")


def validate_persisted_bundle(bundle_path: Path) -> dict[str, Any]:
    """Validate a previously persisted acceptance bundle."""

    _, bundle = _read_json_object(
        bundle_path,
        invalid_reason="persisted_bundle_missing_or_invalid",
    )
    _validate_bundle(bundle)
    return _public_report(bundle, round_trip_status="passed")


def _validate_current_runtime(
    *,
    canonical_image_id: str | None,
    canonical_image_metadata_fingerprint: str | None,
) -> None:
    derived_metadata_fingerprint = fingerprint_canonical_image_metadata_attestation(
        frozen_canonical_image_metadata_attestation()
    )
    if derived_metadata_fingerprint != FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT:
        raise OperationalBudgetValidationError("frozen_image_metadata_attestation_drift")
    if canonical_image_id is None or canonical_image_metadata_fingerprint is None:
        raise OperationalBudgetValidationError("canonical_image_attestation_missing_or_invalid")
    _require_sha256(
        canonical_image_id,
        "canonical_image_attestation_missing_or_invalid",
    )
    _require_sha256(
        canonical_image_metadata_fingerprint,
        "canonical_image_attestation_missing_or_invalid",
    )
    if (
        canonical_image_id != FROZEN_CANONICAL_IMAGE_ID
        or canonical_image_metadata_fingerprint != FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT
    ):
        raise OperationalBudgetValidationError("canonical_image_attestation_mismatch")

    current = {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "machine": platform.machine(),
        "pointer_bits": 64 if sys.maxsize > 2**32 else 32,
    }
    expected = {
        "implementation": FROZEN_PYTHON_IMPLEMENTATION,
        "version": FROZEN_PYTHON_VERSION,
        "machine": FROZEN_MACHINE,
        "pointer_bits": FROZEN_POINTER_BITS,
    }
    if current != expected:
        raise OperationalBudgetValidationError("python_runtime_attestation_stale")
    if platform.system() != "Linux":
        raise OperationalBudgetValidationError("hardware_runtime_class_mismatch")
    if _accelerator_device_count() != 0:
        raise OperationalBudgetValidationError("hardware_runtime_class_mismatch")


def _validate_uat_identity_and_boundary(report: Mapping[str, Any]) -> None:
    if report.get("artifact_id") != UAT_ARTIFACT_ID:
        raise OperationalBudgetValidationError("uat_artifact_id_mismatch")
    if report.get("schema_version") != 1:
        raise OperationalBudgetValidationError("uat_schema_version_mismatch")
    if report.get("diagnostic_label") != DEVELOPMENT_BOUNDARY_ID:
        raise OperationalBudgetValidationError("uat_not_development_evidence")
    if report.get("execution_status") != "passed" or report.get("e2e_executed") is not True:
        raise OperationalBudgetValidationError("uat_execution_not_passed")

    claim_boundary = _require_mapping(report, "claim_boundary")
    required_false = (
        "independent_holdout",
        "methodology_ready",
        "methodology_complete",
        "issue56_complete",
        "production_ready",
        "supports_arm_superiority_claim",
    )
    if any(claim_boundary.get(field) is not False for field in required_false):
        raise OperationalBudgetValidationError("uat_claim_boundary_mismatch")
    manifest_seal = _require_mapping(report, "manifest_seal")
    if (
        manifest_seal.get("sealed_before_execution") is not True
        or manifest_seal.get("unchanged_after_execution") is not True
    ):
        raise OperationalBudgetValidationError("uat_manifest_seal_invalid")


def _validate_frozen_pipeline_bindings(shared: Mapping[str, Any]) -> None:
    expected = {
        "dense_model_revision": FROZEN_DENSE_MODEL_REVISION,
        "dense_profile_fingerprint": FROZEN_DENSE_PROFILE_FINGERPRINT,
        "dense_runtime_attestation": FROZEN_DENSE_RUNTIME_ATTESTATION,
        "answer_model_id": FROZEN_ANSWER_MODEL_ID,
        "answer_prompt_fingerprint": FROZEN_ANSWER_PROMPT_FINGERPRINT,
        "answer_budget_fingerprint": FROZEN_ANSWER_BUDGET_FINGERPRINT,
    }
    for field, expected_value in expected.items():
        if field not in shared:
            raise OperationalBudgetValidationError("uat_pipeline_binding_field_missing")
        if shared[field] != expected_value:
            raise OperationalBudgetValidationError(f"uat_pipeline_binding_mismatch_{field}")
    if shared.get("all_arms_share_answer_model_prompt_budget_evaluator") is not True:
        raise OperationalBudgetValidationError("uat_shared_answer_binding_invalid")


def _latency_check(arm: Mapping[str, Any]) -> dict[str, Any]:
    latency = _require_mapping(arm, "latency_ms")
    measured_micros = _milliseconds_to_micros(
        latency.get("p95"),
        "uat_latency_p95_missing_or_invalid",
    )
    return {
        "status": ("passed" if measured_micros <= LATENCY_P95_LIMIT_MICROS else "failed"),
        "measured_count": measured_micros,
        "limit_count": LATENCY_P95_LIMIT_MICROS,
    }


def _internal_cost_check(arm: Mapping[str, Any]) -> dict[str, Any]:
    cost = _require_mapping(arm, "cost_units")
    scored_case_count = _nonnegative_int(
        arm.get("scored_case_count"),
        "uat_scored_case_count_missing_or_invalid",
    )
    if scored_case_count == 0:
        raise OperationalBudgetValidationError("uat_scored_case_count_missing_or_invalid")
    total = _nonnegative_int(
        cost.get("total"),
        "uat_internal_cost_total_missing_or_invalid",
    )
    average_milli = _nonnegative_int(
        cost.get("average_milli"),
        "uat_internal_cost_average_missing_or_invalid",
    )
    expected_average = round(total * 1_000 / scored_case_count)
    if average_milli != expected_average:
        raise OperationalBudgetValidationError("uat_internal_cost_aggregate_mismatch")

    maximum = cost.get("maximum")
    if maximum is None:
        return {
            "status": "blocked",
            "measured_case_count": scored_case_count,
            "missing_measurement_count": 1,
            "limit_count": INTERNAL_COST_UNITS_PER_CASE_LIMIT,
            "reason_fingerprint": _sha256_json("maximum_per_case_internal_cost_not_reported"),
        }
    measured_maximum = _nonnegative_int(
        maximum,
        "uat_internal_cost_maximum_invalid",
    )
    return {
        "status": (
            "passed" if measured_maximum <= INTERNAL_COST_UNITS_PER_CASE_LIMIT else "failed"
        ),
        "measured_case_count": scored_case_count,
        "measured_count": measured_maximum,
        "limit_count": INTERNAL_COST_UNITS_PER_CASE_LIMIT,
    }


def _peak_rss_check(resource_measurement: Mapping[str, Any]) -> dict[str, Any]:
    measured = _nonnegative_int(
        resource_measurement.get("peak_memory_kib"),
        "uat_peak_rss_missing_or_invalid",
    )
    return {
        "status": "passed" if measured <= PEAK_RSS_LIMIT_KIB else "failed",
        "measured_count": measured,
        "limit_count": PEAK_RSS_LIMIT_KIB,
    }


def _model_cost_check(
    *,
    resource_measurement: Mapping[str, Any],
    shared_pipeline: Mapping[str, Any],
) -> dict[str, Any]:
    usage = _require_mapping(resource_measurement, "model_usage_cost")
    status = usage.get("status")
    if status == "zero_cost_attested":
        if shared_pipeline.get("answer_model_id") != FROZEN_ANSWER_MODEL_ID:
            raise OperationalBudgetValidationError("zero_cost_answer_model_mismatch")
        required_zero_fields = {
            "external_generation_call_count": 0,
            "input_token_count": 0,
            "output_token_count": 0,
            "monetary_cost_microusd": 0,
        }
        if usage.get("generation_mode") != ZERO_COST_GENERATION_MODE:
            raise OperationalBudgetValidationError("zero_cost_generation_mode_invalid")
        for field, expected in required_zero_fields.items():
            if usage.get(field) != expected:
                raise OperationalBudgetValidationError("zero_cost_measurement_invalid")
        if usage.get("attestation_fingerprint") != (
            deterministic_zero_cost_attestation_fingerprint()
        ):
            raise OperationalBudgetValidationError("zero_cost_attestation_invalid")
        return {
            "status": "passed",
            "external_generation_call_count": 0,
            "input_token_count": 0,
            "output_token_count": 0,
            "monetary_cost_microusd": 0,
            "attestation_fingerprint": (deterministic_zero_cost_attestation_fingerprint()),
        }

    if status == "measured":
        external_calls = _nonnegative_int(
            usage.get("external_generation_call_count"),
            "model_usage_measurement_missing_or_invalid",
        )
        input_tokens = _nonnegative_int(
            usage.get("input_token_count"),
            "model_usage_measurement_missing_or_invalid",
        )
        output_tokens = _nonnegative_int(
            usage.get("output_token_count"),
            "model_usage_measurement_missing_or_invalid",
        )
        monetary_cost = _nonnegative_int(
            usage.get("monetary_cost_microusd"),
            "model_usage_measurement_missing_or_invalid",
        )
        if external_calls <= 0 or input_tokens + output_tokens <= 0:
            raise OperationalBudgetValidationError("model_usage_measurement_missing_or_invalid")
        if monetary_cost == 0:
            return {
                "status": "failed",
                "external_generation_call_count": external_calls,
                "input_token_count": input_tokens,
                "output_token_count": output_tokens,
                "monetary_cost_microusd": monetary_cost,
                "reason_fingerprint": _sha256_json(
                    "zero_monetary_cost_requires_deterministic_no_external_generation"
                ),
            }
        return {
            "status": "passed",
            "external_generation_call_count": external_calls,
            "input_token_count": input_tokens,
            "output_token_count": output_tokens,
            "monetary_cost_microusd": monetary_cost,
        }

    if status in {None, "missing"}:
        return {
            "status": "blocked",
            "missing_measurement_count": 1,
            "reason_fingerprint": _sha256_json(
                "model_token_monetary_measurement_or_zero_cost_attestation_missing"
            ),
        }
    raise OperationalBudgetValidationError("model_usage_status_invalid")


def _validate_bundle(bundle: Mapping[str, Any]) -> None:
    if bundle.get("artifact_id") != BUNDLE_ARTIFACT_ID:
        raise OperationalBudgetValidationError("bundle_artifact_id_invalid")
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise OperationalBudgetValidationError("bundle_schema_version_invalid")
    if bundle.get("status") not in _STATUS_VALUES:
        raise OperationalBudgetValidationError("bundle_status_invalid")
    if bundle.get("operational_budget_status") != bundle.get("status"):
        raise OperationalBudgetValidationError("bundle_status_mismatch")
    if bundle.get("full_quality_gate_status") != "blocked":
        raise OperationalBudgetValidationError("full_quality_gate_claim_invalid")
    if bundle.get("budget_fingerprint") != FROZEN_BUDGET_FINGERPRINT:
        raise OperationalBudgetValidationError("budget_fingerprint_mismatch")
    if bundle.get("holdout_content_read_count") != 0:
        raise OperationalBudgetValidationError("holdout_content_boundary_invalid")
    if bundle.get("oracle_content_read_count") != 0:
        raise OperationalBudgetValidationError("oracle_content_boundary_invalid")
    _require_sha256_value(
        bundle.get("uat_report_fingerprint"),
        "bundle_uat_report_fingerprint_invalid",
    )
    _require_sha256_value(
        bundle.get("uat_content_fingerprint"),
        "bundle_uat_content_fingerprint_invalid",
    )
    _require_sha256_value(
        bundle.get("uat_run_fingerprint"),
        "bundle_uat_run_fingerprint_invalid",
    )
    _require_sha256_value(
        bundle.get("runtime_binding_fingerprint"),
        "bundle_runtime_binding_fingerprint_invalid",
    )
    checks = _require_mapping(bundle, "checks")
    if set(checks) != set(CHECK_IDS):
        raise OperationalBudgetValidationError("bundle_check_set_invalid")
    for check in checks.values():
        if not isinstance(check, Mapping) or check.get("status") not in _STATUS_VALUES:
            raise OperationalBudgetValidationError("bundle_check_invalid")
    if bundle.get("check_count") != len(CHECK_IDS):
        raise OperationalBudgetValidationError("bundle_check_count_invalid")
    expected_status_counts = {
        status: sum(check["status"] == status for check in checks.values())
        for status in ("passed", "failed", "blocked")
    }
    if bundle.get("check_status_counts") != expected_status_counts:
        raise OperationalBudgetValidationError("bundle_status_counts_invalid")
    if bundle.get("check_set_fingerprint") != _sha256_json(checks):
        raise OperationalBudgetValidationError("bundle_check_fingerprint_invalid")
    expected_fingerprint = _sha256_json(
        {key: value for key, value in bundle.items() if key != "bundle_fingerprint"}
    )
    if bundle.get("bundle_fingerprint") != expected_fingerprint:
        raise OperationalBudgetValidationError("bundle_fingerprint_invalid")
    _assert_safe_output(bundle)


def _public_report(
    bundle: Mapping[str, Any],
    *,
    round_trip_status: str,
) -> dict[str, Any]:
    report = {
        "artifact_id": REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": bundle["status"],
        "operational_budget_status": bundle["operational_budget_status"],
        "full_quality_gate_status": "blocked",
        "pre_holdout_registration_status": "passed",
        "bundle_round_trip_status": round_trip_status,
        "budget_fingerprint": bundle["budget_fingerprint"],
        "bundle_fingerprint": bundle["bundle_fingerprint"],
        "uat_report_fingerprint": bundle["uat_report_fingerprint"],
        "uat_run_fingerprint": bundle["uat_run_fingerprint"],
        "runtime_binding_fingerprint": bundle["runtime_binding_fingerprint"],
        "check_set_fingerprint": bundle["check_set_fingerprint"],
        "check_count": bundle["check_count"],
        "check_status_counts": bundle["check_status_counts"],
        "blocking_status_ids": bundle["blocking_status_ids"],
        "failure_status_ids": bundle["failure_status_ids"],
        "checks": bundle["checks"],
        "holdout_content_read_count": 0,
        "oracle_content_read_count": 0,
    }
    report["report_fingerprint"] = _sha256_json(report)
    _assert_safe_output(report)
    return report


def _read_json_object(
    path: Path,
    *,
    invalid_reason: str,
) -> tuple[bytes, dict[str, Any]]:
    try:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise OperationalBudgetValidationError(invalid_reason)
        if file_stat.st_size <= 0 or file_stat.st_size > _MAX_INPUT_BYTES:
            raise OperationalBudgetValidationError(invalid_reason)
        raw = path.read_bytes()
        payload = json.loads(raw)
    except OperationalBudgetValidationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationalBudgetValidationError(invalid_reason) from exc
    if not isinstance(payload, dict):
        raise OperationalBudgetValidationError(invalid_reason)
    return raw, payload


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise OperationalBudgetValidationError("output_already_exists")
        serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except OperationalBudgetValidationError:
        raise
    except OSError as exc:
        raise OperationalBudgetValidationError("output_write_failed") from exc


def _require_mapping(
    payload: Mapping[str, Any],
    field: str,
) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise OperationalBudgetValidationError(f"uat_{field}_missing_or_invalid")
    return value


def _nonnegative_int(value: Any, reason: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OperationalBudgetValidationError(reason)
    return value


def _milliseconds_to_micros(value: Any, reason: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise OperationalBudgetValidationError(reason)
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise OperationalBudgetValidationError(reason) from exc
    if not decimal.is_finite() or decimal < 0:
        raise OperationalBudgetValidationError(reason)
    micros = decimal * 1_000
    if micros != micros.to_integral_value():
        raise OperationalBudgetValidationError(reason)
    return int(micros)


def _require_sha256(value: str, reason: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != _HASH_LENGTH
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise OperationalBudgetValidationError(reason)


def _require_sha256_value(value: Any, reason: str) -> str:
    if not isinstance(value, str):
        raise OperationalBudgetValidationError(reason)
    _require_sha256(value, reason)
    return value


def _accelerator_device_count() -> int:
    candidates = (
        Path("/dev/nvidia0"),
        Path("/dev/nvidiactl"),
        Path("/dev/dri/renderD128"),
    )
    return sum(path.exists() for path in candidates)


def _assert_safe_output(payload: Mapping[str, Any]) -> None:
    forbidden_key_fragments = (
        "path",
        "filename",
        "subject",
        "sender",
        "recipient",
        "body",
        "query_text",
        "answer_text",
        "oracle_answer",
        "secret",
        "token_value",
        "command",
    )

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                lowered = str(key).lower()
                if any(fragment in lowered for fragment in forbidden_key_fragments):
                    raise OperationalBudgetValidationError("public_output_field_not_safe")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            if value.startswith(("/", "./", "../", "~")) or "://" in value:
                raise OperationalBudgetValidationError("public_output_value_not_safe")

    walk(payload)


def _rejection_report(reason_code: str) -> dict[str, Any]:
    report = {
        "artifact_id": ERROR_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "rejected",
        "rejection_status_id": reason_code,
        "rejection_count": 1,
        "budget_fingerprint": FROZEN_BUDGET_FINGERPRINT,
        "holdout_content_read_count": 0,
        "oracle_content_read_count": 0,
    }
    report["report_fingerprint"] = _sha256_json(report)
    _assert_safe_output(report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--uat-report", type=Path)
    mode.add_argument("--validate-bundle", type=Path)
    parser.add_argument("--expected-uat-report-fingerprint")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--canonical-image-id",
        default=os.environ.get("FORMOWL_CANONICAL_IMAGE_ID"),
    )
    parser.add_argument(
        "--canonical-image-metadata-fingerprint",
        default=os.environ.get("FORMOWL_CANONICAL_IMAGE_METADATA_FINGERPRINT"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.uat_report is not None:
            if args.output is None:
                raise OperationalBudgetValidationError("output_missing")
            if args.expected_uat_report_fingerprint is None:
                raise OperationalBudgetValidationError(
                    "expected_uat_report_fingerprint_missing_or_invalid"
                )
            bundle = validate_uat_report(
                report_path=args.uat_report,
                expected_report_fingerprint=args.expected_uat_report_fingerprint,
                canonical_image_id=args.canonical_image_id,
                canonical_image_metadata_fingerprint=(args.canonical_image_metadata_fingerprint),
            )
            report = persist_bundle(bundle, args.output)
        else:
            if args.output is not None:
                raise OperationalBudgetValidationError("validate_bundle_output_not_allowed")
            report = validate_persisted_bundle(args.validate_bundle)
    except OperationalBudgetValidationError as exc:
        print(
            json.dumps(
                _rejection_report(exc.reason_code),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 3

    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
