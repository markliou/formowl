#!/usr/bin/env python3
"""Validate the frozen private real-PST domain-hard 100-case manifest.

The private manifest and PST remain operator-controlled inputs. Public output
contains only hashes, counts, and validation status.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from formowl_contract import assert_no_public_raw_references, sha256_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = (
    ROOT / "experiments" / "kg_ontology_v2_coordination" / "real_pst_domain_hard_100.lock.json"
)
CASE_FIELDS = (
    "case_id",
    "domain",
    "pattern",
    "intent_kind",
    "result_kind",
    "query_text",
    "requester_user_id",
    "limit",
    "required_match_count",
    "required_source_observation_ids",
    "forbidden_source_observation_ids",
)


def validate_frozen_manifest(
    private_manifest: Mapping[str, Any],
    lock: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    case_lock = _mapping(lock.get("case_set"), "case_set", blockers)
    source_lock = _mapping(lock.get("source_fixture"), "source_fixture", blockers)
    policy_lock = _mapping(lock.get("policy"), "policy", blockers)
    cases = private_manifest.get("cases")
    if not isinstance(cases, list):
        blockers.append("private manifest cases must be a list")
        cases = []

    manifest_hash = sha256_json(private_manifest)
    projected_cases = [
        {field: case.get(field) for field in CASE_FIELDS}
        for case in cases
        if isinstance(case, Mapping)
    ]
    case_definition_hash = sha256_json(projected_cases)
    case_id_sequence_hash = sha256_json(
        [case.get("case_id") for case in cases if isinstance(case, Mapping)]
    )
    result_kind_counts = Counter(
        str(case.get("result_kind")) for case in cases if isinstance(case, Mapping)
    )

    _expect_equal(
        blockers,
        "private_manifest_sha256_json",
        manifest_hash,
        case_lock.get("private_manifest_sha256_json"),
    )
    _expect_equal(
        blockers,
        "case_definition_sha256_json",
        case_definition_hash,
        case_lock.get("case_definition_sha256_json"),
    )
    _expect_equal(
        blockers,
        "case_id_sequence_sha256_json",
        case_id_sequence_hash,
        case_lock.get("case_id_sequence_sha256_json"),
    )
    _expect_equal(blockers, "case_count", len(cases), case_lock.get("case_count"))
    _expect_equal(
        blockers,
        "positive_case_count",
        result_kind_counts.get("owner_match", 0),
        case_lock.get("positive_case_count"),
    )
    _expect_equal(
        blockers,
        "no_match_case_count",
        result_kind_counts.get("no_match", 0),
        case_lock.get("no_match_case_count"),
    )
    _expect_equal(
        blockers,
        "permission_denied_case_count",
        result_kind_counts.get("permission_denied", 0),
        case_lock.get("permission_denied_case_count"),
    )
    _expect_equal(
        blockers,
        "archive_sha256",
        private_manifest.get("archive_sha256"),
        source_lock.get("archive_sha256"),
    )
    _expect_equal(
        blockers,
        "case_policy_version",
        private_manifest.get("policy_version"),
        policy_lock.get("case_policy_version"),
    )
    if len(projected_cases) != len(cases):
        blockers.append("every case must be an object")
    if len({case.get("case_id") for case in cases if isinstance(case, Mapping)}) != len(cases):
        blockers.append("case ids must be unique")

    report = {
        "artifact_id": "formowl_real_pst_domain_hard_100_lock_validation_v1",
        "status": "passed" if not blockers else "blocked",
        "safe_outputs": {
            "manifest_hash": manifest_hash,
            "case_definition_hash": case_definition_hash,
            "case_id_sequence_hash": case_id_sequence_hash,
            "case_count": len(cases),
            "result_kind_counts": dict(sorted(result_kind_counts.items())),
            "blocker_hashes": sorted(sha256_json(blocker) for blocker in blockers),
        },
        "claim_boundary": {
            "same_private_questions_locked": not blockers,
            "raw_content_included": False,
            "private_path_included": False,
            "methodology_ready": False,
        },
    }
    assert_no_public_raw_references(report, "real_pst_domain_hard_100_lock_validation")
    return report


def verify_pst_fixture(path: Path, lock: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    source_lock = _mapping(lock.get("source_fixture"), "source_fixture", blockers)
    expected_size = source_lock.get("fixture_size_bytes")
    expected_hash = source_lock.get("archive_sha256")
    actual_size: int | None = None
    actual_hash: str | None = None
    try:
        actual_size = path.stat().st_size
        actual_hash = _sha256(path)
    except OSError:
        blockers.append("PST fixture is unavailable")
    if actual_size is not None:
        _expect_equal(blockers, "fixture_size_bytes", actual_size, expected_size)
    if actual_hash is not None:
        _expect_equal(blockers, "archive_sha256", actual_hash, expected_hash)
    report = {
        "artifact_id": "formowl_real_pst_domain_hard_100_fixture_validation_v1",
        "status": "passed" if not blockers else "blocked",
        "safe_outputs": {
            "fixture_size_bytes": actual_size,
            "fixture_sha256": actual_hash,
            "blocker_hashes": sorted(sha256_json(blocker) for blocker in blockers),
        },
        "claim_boundary": {
            "raw_content_included": False,
            "private_path_included": False,
            "source_fixture_matches_lock": not blockers,
        },
    }
    assert_no_public_raw_references(report, "real_pst_domain_hard_100_fixture_validation")
    return report


def _mapping(value: Any, name: str, blockers: list[str]) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    blockers.append(f"{name} must be an object")
    return {}


def _expect_equal(blockers: list[str], name: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        blockers.append(f"{name} does not match the frozen lock")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _write_report(path: Path | None, report: Mapping[str, Any]) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--pst", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    lock = _read_json(args.lock)
    report = validate_frozen_manifest(_read_json(args.private_manifest), lock)
    if report["status"] == "passed" and args.pst is not None:
        report["fixture_validation"] = verify_pst_fixture(args.pst, lock)
        if report["fixture_validation"]["status"] != "passed":
            report["status"] = "blocked"
    _write_report(args.output, report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
