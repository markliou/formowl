#!/usr/bin/env python3
"""Run or validate the main-repo PostgreSQL/pgvector live smoke.

This is an explicit live-adapter smoke harness. It validates the main repo
migrations and pgvector permission/stale-vector behavior against a real
PostgreSQL/pgvector container, but it does not claim production readiness or
end-to-end gateway readiness.
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
DEFAULT_OUTPUT = Path("/tmp/formowl-kg-eval/results/main_repo_pgvector_live_smoke.json")
PGVECTOR_IMAGE = (
    "pgvector/pgvector@" "sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
)
FORBIDDEN_TEXT = (
    "postgresql://",
    "SELECT ",
    "INSERT ",
    "UPDATE ",
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
    files = [
        "python/formowl_graph/storage/migrations/001_metadata_store.sql",
        "python/formowl_graph/storage/migrations/002_vector_index.sql",
    ]
    return {
        "migration_files": [
            {
                "path": path,
                "sha256": sha256_file(ROOT / path),
            }
            for path in files
        ]
    }


def bind_output_manifest(report: dict[str, Any]) -> dict[str, Any]:
    bound = dict(report)
    bound["output_manifest_sha256"] = sha256_json(bound.get("safe_outputs", {}))
    return bound


def run_live_smoke(output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = f"main-repo-pgvector-live-{uuid.uuid4().hex[:12]}"
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
        f"FORMOWL_PGVECTOR_LIVE_RUN_ID={run_id}",
        "-e",
        f"FORMOWL_PGVECTOR_IMAGE={PGVECTOR_IMAGE}",
        "-e",
        f"FORMOWL_PGVECTOR_RUNNER_SCRIPT_SHA256={sha256_file(Path(__file__))}",
        "-e",
        "FORMOWL_PGVECTOR_CONTAINER_ENTRYPOINT_SHA256="
        f"{sha256_file(ROOT / 'scripts/pgvector_repository_live_smoke_container.sh')}",
        "-e",
        f"FORMOWL_PGVECTOR_MIGRATION_MANIFEST_SHA256={sha256_json(manifest)}",
        PGVECTOR_IMAGE,
        "bash",
        "/workspace/scripts/pgvector_repository_live_smoke_container.sh",
        f"/out/{output_path.name}",
    ]
    subprocess.run(command, check=True)
    report = bind_output_manifest(load_report(output_path))
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validate_report(report)
    return report


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    metrics = report.get("metrics", {})
    claims = report.get("claim_boundary", {})
    safe_outputs = report.get("safe_outputs", {})
    expected_migration_manifest = migration_manifest()

    if report.get("artifact_id") != "main_repo_pgvector_repository_live_smoke_v1":
        blockers.append("unexpected artifact id")
    if report.get("image_reference") != PGVECTOR_IMAGE:
        blockers.append("image reference does not match locked pgvector image")
    if report.get("repo_reference") != "main_repo_workspace":
        blockers.append("repo reference must be main_repo_workspace")
    if report.get("repo_path_redacted") is not True:
        blockers.append("repo path must remain redacted")
    if report.get("runner_script_sha256") != sha256_file(Path(__file__)):
        blockers.append("runner script hash mismatch")
    if report.get("container_entrypoint_sha256") != sha256_file(
        ROOT / "scripts/pgvector_repository_live_smoke_container.sh"
    ):
        blockers.append("container entrypoint hash mismatch")
    if report.get("migration_manifest_sha256") != sha256_json(expected_migration_manifest):
        blockers.append("migration manifest hash mismatch")
    if report.get("migration_files_applied") != [
        "001_metadata_store.sql",
        "002_vector_index.sql",
    ]:
        blockers.append("migration file list mismatch")
    if report.get("output_manifest_sha256") != sha256_json(safe_outputs):
        blockers.append("output manifest hash mismatch")
    for key in [
        "live_postgres_pgvector_repository_smoke_executed",
        "migration_replay_applied",
        "permission_filtered_sql_vector_query_tests",
        "stale_vector_regression_against_pgvector",
        "private_ungranted_vector_excluded",
        "revoked_grant_regression",
    ]:
        if metrics.get(key) is not True:
            blockers.append(f"required metric failed: {key}")
    for key in ["canonical_graph_writes", "raw_access_expanded", "raw_sql_exposed"]:
        if metrics.get(key) is not False:
            blockers.append(f"forbidden metric true: {key}")
    if safe_outputs.get("ready_result_source_ids") != ["obs_workspace_decision"]:
        blockers.append("ready result source ids do not prove permission filtering")
    if safe_outputs.get("post_revoke_result_source_ids") != []:
        blockers.append("post-revoke result source ids should be empty")
    if claims.get("supports_production_adapter_ready_claim") is not False:
        blockers.append("production readiness claim must remain false")
    if claims.get("supports_end_to_end_gateway_claim") is not False:
        blockers.append("end-to-end gateway claim must remain false")
    if _contains_forbidden_text(report):
        blockers.append("public artifact leaks raw paths or SQL")
    passed = not blockers
    return {
        "passed": passed,
        "blockers": blockers,
        "metrics": metrics,
        "claim_boundary": claims,
    }


def write_markdown(report: dict[str, Any], validation: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Main-Repo pgvector Live Smoke",
        "",
        "This validates a narrow PostgreSQL/pgvector live smoke for the main-repo schema.",
        "It is not production adapter readiness and does not exercise end-to-end gateway wiring.",
        "",
        f"- Passed: {validation['passed']}",
        f"- Artifact: {output_path.name}",
        f"- PostgreSQL version: {report.get('postgres_version')}",
        f"- pgvector extension version: {report.get('extension_version')}",
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
