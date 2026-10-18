#!/usr/bin/env python3
"""Bind a candidate-union exact offline report to the r8 deployment gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


EXPECTED_COUNT = 77
EXPECTED_FINGERPRINT = "sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705"
CANDIDATE_EXACT_REPORT_ARTIFACT_TYPE = "formowl_candidate_union_exact_oracle_acceptance_report_v1"
CANDIDATE_EXACT_RELEASE_DECISION = "CANDIDATE_EXACT_AGREE"
CANONICAL_SEMANTIC_REQUEST_SHA256 = (
    "sha256:20f30eb32c7525b9bedaf68b358fa0140c43cc6a77f2af03cec124a5e1dc012b"
)
CANDIDATE_EXACT_VALIDATION_KEYS = frozenset(
    {
        "candidate_union_admission_bound",
        "candidate_union_plan_valid",
        "candidate_union_execution_handoff_valid",
        "candidate_union_retained_lineage_valid",
        "candidate_only_claim_contract_valid",
        "deterministic_repeat_match",
        "runtime_projection_matches_handoff",
        "oracle_loaded_after_package_runtime_freeze",
        "oracle_exact_match",
        "expected_constants_match",
    }
)
CANDIDATE_EXACT_EXECUTION_BINDING_KEYS = frozenset(
    {
        "candidate_union_execution_handoff_sha256",
        "frozen_projection_fingerprint",
        "runtime_projection_fingerprint",
        "oracle_file_sha256",
        "semantic_request_sha256",
    }
)
CANDIDATE_EXACT_REQUIRED_COMMITMENTS = frozenset(
    {
        "runtime_module_sha256",
        "source_python_tree_sha256",
        "base_bridge_sha256",
        "base_profile_sha256",
        "base_authority_sha256",
        "semantic_profile_file_sha256",
        "semantic_profile_aliases_expected_commitment",
        "current_export_snapshot_sha256",
        "current_export_max_message_file_bytes_sha256",
        "current_export_scope_manifest_sha256",
        "current_export_selection_checkpoint_sha256",
        "snapshot_xlsx_augmentation_sha256",
        "augmentation_bridge_sha256",
        "augmentation_profile_sha256",
        "augmentation_authority_sha256",
        "reviewed_structural_binding_sha256",
        "candidate_union_runtime_admission_sha256",
        "candidate_union_plan_sha256",
        "candidate_union_execution_handoff_sha256",
        "candidate_union_ledger_module_sha256",
        "candidate_union_materializer_module_sha256",
        "private_oracle_sha256",
    }
)
CANDIDATE_DISCLAIMERS = {
    "source_complete": False,
    "current_state": False,
    "source_precedence": False,
    "occurrence_equivalence": False,
}
CANDIDATE_EXACT_REPORT_FIELDS = frozenset(
    {
        "artifact_type",
        "status",
        "release_decision",
        "expected_distinct_projection_count",
        "observed_distinct_projection_count",
        "count_match",
        "expected_fingerprint",
        "observed_fingerprint",
        "fingerprint_match",
        "oracle_intersection_count",
        "oracle_missing_count",
        "oracle_unexpected_count",
        "retrieval_path",
        "claim_state",
        "canonical_kg",
        "citation_count",
        "source_count",
        "deterministic_repeat_match",
        "runtime_projection_matches_handoff",
        "failure_categories",
        "validation_status",
        "implementation_source_commitments",
        "execution_bindings",
        "disclaimed_semantics",
        "diagnostic_only",
    }
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PreflightFailure(RuntimeError):
    """One non-leaking semantic-preflight failure."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-report", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _regular_file(path: Path) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            raise PreflightFailure("required input is unavailable")
    except OSError as error:
        raise PreflightFailure("required input is unavailable") from error


def _read_report(path: Path) -> dict[str, Any]:
    _regular_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreflightFailure("acceptance report is invalid") from error
    if not isinstance(payload, dict):
        raise PreflightFailure("acceptance report is invalid")
    return payload


def build_preflight(*, acceptance_report: Path, binding: Path) -> dict[str, Any]:
    report = _read_report(acceptance_report)
    _regular_file(binding)
    binding_sha256 = _sha256(binding)
    validation = report.get("validation_status")
    commitments = report.get("implementation_source_commitments")
    execution_bindings = report.get("execution_bindings")
    disclaimers = report.get("disclaimed_semantics")
    checks = (
        set(report) == CANDIDATE_EXACT_REPORT_FIELDS,
        report.get("artifact_type") == CANDIDATE_EXACT_REPORT_ARTIFACT_TYPE,
        report.get("status") == "passed",
        report.get("release_decision") == CANDIDATE_EXACT_RELEASE_DECISION,
        type(report.get("expected_distinct_projection_count")) is int,
        report.get("expected_distinct_projection_count") == EXPECTED_COUNT,
        type(report.get("observed_distinct_projection_count")) is int,
        report.get("observed_distinct_projection_count") == EXPECTED_COUNT,
        report.get("count_match") is True,
        report.get("expected_fingerprint") == EXPECTED_FINGERPRINT,
        report.get("observed_fingerprint") == EXPECTED_FINGERPRINT,
        report.get("fingerprint_match") is True,
        type(report.get("oracle_intersection_count")) is int,
        report.get("oracle_intersection_count") == EXPECTED_COUNT,
        type(report.get("oracle_missing_count")) is int,
        report.get("oracle_missing_count") == 0,
        type(report.get("oracle_unexpected_count")) is int,
        report.get("oracle_unexpected_count") == 0,
        report.get("retrieval_path") == "mail_authorized_structured_set",
        report.get("claim_state") == "CANDIDATE_MATCHES",
        report.get("canonical_kg") is False,
        type(report.get("citation_count")) is int,
        report.get("citation_count") == 0,
        type(report.get("source_count")) is int,
        report.get("source_count") == 0,
        report.get("deterministic_repeat_match") is True,
        report.get("runtime_projection_matches_handoff") is True,
        report.get("failure_categories") == [],
        isinstance(validation, dict),
        isinstance(validation, dict) and set(validation) == CANDIDATE_EXACT_VALIDATION_KEYS,
        isinstance(validation, dict)
        and all(validation.get(key) is True for key in CANDIDATE_EXACT_VALIDATION_KEYS),
        isinstance(commitments, dict),
        isinstance(commitments, dict) and set(commitments) == CANDIDATE_EXACT_REQUIRED_COMMITMENTS,
        isinstance(commitments, dict)
        and all(
            type(commitments.get(key)) is str and _SHA256.fullmatch(commitments[key]) is not None
            for key in CANDIDATE_EXACT_REQUIRED_COMMITMENTS
        ),
        isinstance(commitments, dict)
        and commitments.get("reviewed_structural_binding_sha256") == binding_sha256,
        isinstance(execution_bindings, dict),
        isinstance(execution_bindings, dict)
        and set(execution_bindings) == CANDIDATE_EXACT_EXECUTION_BINDING_KEYS,
        isinstance(execution_bindings, dict)
        and all(
            type(execution_bindings.get(key)) is str
            and _SHA256.fullmatch(execution_bindings[key]) is not None
            for key in CANDIDATE_EXACT_EXECUTION_BINDING_KEYS
        ),
        isinstance(commitments, dict)
        and isinstance(execution_bindings, dict)
        and execution_bindings.get("candidate_union_execution_handoff_sha256")
        == commitments.get("candidate_union_execution_handoff_sha256"),
        isinstance(execution_bindings, dict)
        and execution_bindings.get("frozen_projection_fingerprint")
        == report.get("observed_fingerprint"),
        isinstance(execution_bindings, dict)
        and execution_bindings.get("runtime_projection_fingerprint")
        == report.get("observed_fingerprint"),
        isinstance(commitments, dict)
        and isinstance(execution_bindings, dict)
        and execution_bindings.get("oracle_file_sha256")
        == commitments.get("private_oracle_sha256"),
        isinstance(execution_bindings, dict)
        and execution_bindings.get("semantic_request_sha256") == CANONICAL_SEMANTIC_REQUEST_SHA256,
        disclaimers == CANDIDATE_DISCLAIMERS,
        report.get("diagnostic_only") is True,
    )
    if not all(checks):
        raise PreflightFailure("offline candidate exact acceptance is incomplete")
    return {
        "artifact_type": "formowl_r8_semantic_deployment_preflight_v1",
        "status": "passed",
        "candidate_exact_report_artifact_type": report["artifact_type"],
        "candidate_exact_release_decision": report["release_decision"],
        "retrieval_path": report["retrieval_path"],
        "claim_state": report["claim_state"],
        "canonical_kg": False,
        "citation_count": 0,
        "source_count": 0,
        "observed_distinct_projection_count": EXPECTED_COUNT,
        "observed_fingerprint": EXPECTED_FINGERPRINT,
        "oracle_intersection_count": EXPECTED_COUNT,
        "oracle_missing_count": 0,
        "oracle_unexpected_count": 0,
        "deterministic_repeat_match": True,
        "runtime_projection_matches_handoff": True,
        "candidate_exact_validation_status": {
            key: True for key in sorted(CANDIDATE_EXACT_VALIDATION_KEYS)
        },
        "implementation_source_commitments": {
            key: commitments[key] for key in sorted(CANDIDATE_EXACT_REQUIRED_COMMITMENTS)
        },
        "execution_bindings": {
            key: execution_bindings[key] for key in sorted(CANDIDATE_EXACT_EXECUTION_BINDING_KEYS)
        },
        "candidate_disclaimed_semantics": dict(CANDIDATE_DISCLAIMERS),
        "acceptance_report_sha256": _sha256(acceptance_report),
        "candidate_binding_sha256": binding_sha256,
        "diagnostic_only": True,
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(encoded)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    args = _arguments()
    try:
        payload = build_preflight(
            acceptance_report=args.acceptance_report,
            binding=args.binding,
        )
    except PreflightFailure as error:
        _write(
            args.output,
            {
                "artifact_type": "formowl_r8_semantic_deployment_preflight_v1",
                "status": "failed",
                "reason": str(error),
            },
        )
        return 2
    _write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
