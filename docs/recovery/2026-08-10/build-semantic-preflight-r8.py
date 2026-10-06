#!/usr/bin/env python3
"""Bind an exact offline semantic acceptance report to the r8 deployment gate."""

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
EXPECTED_FINGERPRINT = (
    "sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705"
)
EXPECTED_VALIDATION_KEYS = frozenset(
    {
        "expected_values_valid",
        "semantic_profile_valid",
        "authority_root_valid",
        "aggregate_complete",
        "profile_scope_bound",
        "every_shard_bound",
        "typed_execution_complete",
    }
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


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
    validation = report.get("validation_status")
    checks = (
        report.get("artifact_type") == "formowl_aggregate_semantic_acceptance_report_v1",
        report.get("status") == "passed",
        report.get("release_decision") == "AGREE",
        type(report.get("expected_distinct_projection_count")) is int,
        report.get("expected_distinct_projection_count") == EXPECTED_COUNT,
        type(report.get("observed_distinct_projection_count")) is int,
        report.get("observed_distinct_projection_count") == EXPECTED_COUNT,
        report.get("count_match") is True,
        report.get("expected_fingerprint") == EXPECTED_FINGERPRINT,
        report.get("observed_fingerprint") == EXPECTED_FINGERPRINT,
        report.get("fingerprint_match") is True,
        report.get("failure_categories") == [],
        isinstance(validation, dict),
        isinstance(validation, dict) and set(validation) == EXPECTED_VALIDATION_KEYS,
        isinstance(validation, dict)
        and all(validation.get(key) is True for key in EXPECTED_VALIDATION_KEYS),
        isinstance(report.get("implementation_source_commitments"), dict),
        bool(report.get("implementation_source_commitments")),
    )
    if not all(checks):
        raise PreflightFailure("offline semantic acceptance is incomplete")
    binding_sha256 = _sha256(binding)
    if _SHA256.fullmatch(binding_sha256) is None:
        raise PreflightFailure("binding commitment is invalid")
    return {
        "artifact_type": "formowl_r8_semantic_deployment_preflight_v1",
        "status": "passed",
        "retrieval_path": "mail_authorized_structured_set",
        "claim_state": "CANDIDATE_MATCHES",
        "canonical_kg": False,
        "citation_count": 0,
        "source_count": 0,
        "observed_distinct_projection_count": EXPECTED_COUNT,
        "observed_fingerprint": EXPECTED_FINGERPRINT,
        "acceptance_report_sha256": _sha256(acceptance_report),
        "candidate_binding_sha256": binding_sha256,
        "diagnostic_only": True,
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
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
