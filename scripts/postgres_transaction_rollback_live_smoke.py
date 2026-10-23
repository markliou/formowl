#!/usr/bin/env python3
"""Run or validate the main-repo PostgreSQL transaction rollback live smoke.

This harness validates the metadata-store migration and transaction rollback
behavior against a real PostgreSQL-compatible container. It is intentionally
narrow: it does not claim production adapter readiness, end-to-end gateway
readiness, or canonical graph commit readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("/tmp/formowl-kg-eval/results/main_repo_postgres_rollback_live_smoke.json")
POSTGRES_IMAGE = (
    "pgvector/pgvector@" "sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
)
FORBIDDEN_TEXT = (
    "postgresql://",
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "/home/",
    "/tmp/formowl",
    "/workspace/",
    "raw_path",
    "internal_sql",
)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def migration_manifest() -> dict[str, Any]:
    files = ["python/formowl_graph/storage/migrations/001_metadata_store.sql"]
    return {
        "migration_files": [
            {
                "path": path,
                "sha256": sha256_file(ROOT / path),
            }
            for path in files
        ]
    }


def run_live_smoke(output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = f"main-repo-postgres-rollback-{uuid.uuid4().hex[:12]}"
    manifest = migration_manifest()
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{ROOT}:/workspace:ro",
        "-v",
        f"{output_path.parent}:/out",
        "-e",
        f"FORMOWL_POSTGRES_ROLLBACK_LIVE_RUN_ID={run_id}",
        "-e",
        f"FORMOWL_POSTGRES_ROLLBACK_IMAGE={POSTGRES_IMAGE}",
        "-e",
        f"FORMOWL_POSTGRES_ROLLBACK_RUNNER_SCRIPT_SHA256={sha256_file(Path(__file__))}",
        "-e",
        "FORMOWL_POSTGRES_ROLLBACK_CONTAINER_ENTRYPOINT_SHA256="
        f"{sha256_file(ROOT / 'scripts/postgres_transaction_rollback_live_smoke_container.sh')}",
        "-e",
        f"FORMOWL_POSTGRES_ROLLBACK_MIGRATION_MANIFEST_SHA256={sha256_json(manifest)}",
        POSTGRES_IMAGE,
        "bash",
        "/workspace/scripts/postgres_transaction_rollback_live_smoke_container.sh",
        f"/out/{output_path.name}",
    ]
    subprocess.run(command, check=True)
    report = load_report(output_path)
    validate_report(report)
    return report


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    metrics = report.get("metrics", {})
    claims = report.get("claim_boundary", {})
    safe_outputs = report.get("safe_outputs", {})

    if report.get("artifact_id") != "main_repo_postgres_transaction_rollback_live_smoke_v1":
        blockers.append("unexpected artifact id")
    for key in [
        "live_postgres_transaction_rollback_smoke_executed",
        "metadata_migration_applied",
        "transactional_commit_persisted",
        "partial_failure_error_observed",
        "partial_failure_transaction_rolled_back",
        "graph_record_rollback_verified",
        "audit_log_rollback_verified",
    ]:
        if metrics.get(key) is not True:
            blockers.append(f"required metric failed: {key}")
    for key in [
        "canonical_graph_writes",
        "raw_access_expanded",
        "raw_sql_exposed",
        "raw_storage_path_exposed",
    ]:
        if metrics.get(key) is not False:
            blockers.append(f"forbidden metric true: {key}")
    if safe_outputs.get("committed_graph_record_count") != 1:
        blockers.append("committed graph record count does not prove commit control")
    if safe_outputs.get("rolled_back_graph_record_count") != 0:
        blockers.append("rolled-back graph record count should be zero")
    if safe_outputs.get("rolled_back_audit_log_count") != 0:
        blockers.append("rolled-back audit log count should be zero")
    if claims.get("supports_main_repo_postgres_transaction_rollback_claim") is not True:
        blockers.append("main-repo PostgreSQL rollback claim is not supported")
    if claims.get("supports_production_adapter_ready_claim") is not False:
        blockers.append("production readiness claim must remain false")
    if claims.get("supports_end_to_end_gateway_claim") is not False:
        blockers.append("end-to-end gateway claim must remain false")
    if claims.get("supports_canonical_graph_write_claim") is not False:
        blockers.append("canonical graph write claim must remain false")
    if _contains_forbidden_text(report):
        blockers.append("public artifact leaks raw paths or SQL")

    return {
        "passed": not blockers,
        "blockers": blockers,
        "metrics": metrics,
        "claim_boundary": claims,
    }


def write_markdown(report: dict[str, Any], validation: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Main-Repo PostgreSQL Transaction Rollback Live Smoke",
        "",
        "This validates a narrow metadata-store rollback smoke against a live PostgreSQL container.",
        "It is not production adapter readiness and does not exercise end-to-end gateway wiring.",
        "",
        f"- Passed: {validation['passed']}",
        f"- Artifact: {output_path.name}",
        f"- PostgreSQL version: {report.get('postgres_version')}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in sorted(validation["metrics"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Claim Boundary", ""])
    for key, value in sorted(validation["claim_boundary"].items()):
        lines.append(f"- {key}: {value}")
    if validation["blockers"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in validation["blockers"]:
            lines.append(f"- {blocker}")
    output_path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_forbidden_text(key) or _contains_forbidden_text(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_text(item) for item in value)
    if isinstance(value, str):
        return any(token in value for token in FORBIDDEN_TEXT)
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--from-existing", action="store_true")
    args = parser.parse_args()

    if args.from_existing:
        report = load_report(args.output)
    else:
        report = run_live_smoke(args.output)
    validation = validate_report(report)
    write_markdown(report, validation, args.output)
    if not validation["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
