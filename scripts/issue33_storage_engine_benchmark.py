#!/usr/bin/env python3
"""Run the bounded, disposable Issue #33 PostgreSQL/Neo4j comparison.

The benchmark is deliberately source-free and diagnostic-only.  It carries the
blocked methodology authority state forward and cannot produce a methodology
readiness or production-migration claim.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from formowl_graph.storage.benchmark_contract import (  # noqa: E402
    DependencyPin,
    EngineProfile,
    StorageEngineBenchmarkPackage,
    canonical_json_sha256,
    execute_fault_conformance,
    generate_storage_engine_benchmark_package,
    methodology_authority_state_from_check,
    seal_dependency_lock,
    seal_engine_profile,
    seal_evaluator_profile,
    verify_case_execution,
)

NEO4J_IMAGE = (
    "neo4j:2025.06.0-community@"
    "sha256:b39586218dfab88e37fb2f7557bba474d5ee2af000e8e9fbb767a37ed58b20d7"
)
NEO4J_IMAGE_DIGEST = "sha256:b39586218dfab88e37fb2f7557bba474d5ee2af000e8e9fbb767a37ed58b20d7"
POSTGRES_IMAGE = (
    "postgres:17.5@sha256:5fdd7ebaa553af131db4021414d753791dce12e0b5ac1e27ca9ac57e3982e78a"
)
POSTGRES_IMAGE_DIGEST = "sha256:5fdd7ebaa553af131db4021414d753791dce12e0b5ac1e27ca9ac57e3982e78a"
NEO4J_DRIVER_VERSION = "5.28.1"

_CASE_ORDER = (
    "candidate_stage_cross_scope_reject",
    "candidate_stage_write",
    "review_commit",
    "effective_view_allow",
    "effective_view_deny",
    "property_permission_matching",
    "property_permission_missing",
    "property_permission_mutable",
    "property_permission_nonmatching",
    "property_permission_null",
    "property_permission_wrong_type",
    "bounded_traversal_allow",
    "bounded_traversal_deny",
    "lifecycle_resolution_split_merge",
    "structured_set_handoff",
    "schema_and_ontology_reject",
    "backup_restore",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live", action="store_true", help="provision disposable engine containers"
    )
    parser.add_argument("--inside-network", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--postgres-host", default="")
    parser.add_argument("--neo4j-host", default="")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument(
        "--fixture-profile",
        choices=("conformance_r1", "workload_r1"),
        default="workload_r1",
        help="sealed governed fixture size; conformance_r1 is the bounded correctness slice",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.cycles < 3 or args.samples < 1:
        raise SystemExit("--cycles must be at least 3 and --samples must be positive")

    if args.inside_network:
        report = _run_inside_network(args)
    elif args.live:
        report = _run_live(args)
    else:
        report = _preflight_report(args)
    _write_report(report, args.output)
    return 0


def _authority_and_package(
    fixture_profile: str = "workload_r1",
) -> StorageEngineBenchmarkPackage:
    checked = _run([sys.executable, "scripts/methodology_authority_check.py", "--check"])
    required = subprocess.run(
        [sys.executable, "scripts/methodology_authority_check.py", "--require-ready"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    authority = methodology_authority_state_from_check(
        json.loads(checked.stdout),
        require_ready_exit_code=required.returncode,
    )
    dependency_lock = seal_dependency_lock(
        "issue33_live_dependency_lock_r1",
        (
            DependencyPin(
                "neo4j_driver",
                NEO4J_DRIVER_VERSION,
                _installed_distribution_hash("neo4j"),
            ),
            DependencyPin(
                "psycopg",
                importlib.metadata.version("psycopg"),
                _installed_distribution_hash("psycopg"),
            ),
        ),
    )
    profiles = _engine_profiles(dependency_lock)
    return generate_storage_engine_benchmark_package(
        fixture_profile,
        seed=33,
        authority_state=authority,
        engine_profiles=profiles,
        evaluator_profile=seal_evaluator_profile(
            evaluator_id="issue33_storage_engine_benchmark_r1",
            module_id="scripts.issue33_storage_engine_benchmark",
            entrypoint_id="main",
            source_revision=_git_revision(),
            source_hash=_source_hash(),
        ),
        dependency_lock=dependency_lock,
    )


def _engine_profiles(lock) -> tuple[EngineProfile, ...]:
    pins = {pin.package_name: pin for pin in lock.dependencies}
    return (
        seal_engine_profile(
            profile_id="neo4j_profile_r1",
            engine_id="neo4j",
            product_name="neo4j",
            product_version="2025.06.0",
            edition="community",
            image_reference=NEO4J_IMAGE,
            image_digest=NEO4J_IMAGE_DIGEST,
            driver_package="neo4j_driver",
            driver_version=NEO4J_DRIVER_VERSION,
            driver_artifact_hash=pins["neo4j_driver"].artifact_hash,
            deployment_mode="disposable_single_instance",
            license_declaration="community benchmark only; native RBAC not authority",
            settings_profile_id="neo4j_settings_r1",
            settings=(
                {"setting_name": "query_workers", "value_json": "1"},
                {"setting_name": "transaction_timeout_milliseconds", "value_json": "1000"},
            ),
            index_profile_id="governed_graph_indexes_r1",
        ),
        seal_engine_profile(
            profile_id="postgresql_profile_r1",
            engine_id="postgresql",
            product_name="postgresql",
            product_version="17.5",
            edition="community",
            image_reference=POSTGRES_IMAGE,
            image_digest=POSTGRES_IMAGE_DIGEST,
            driver_package="psycopg",
            driver_version=pins["psycopg"].version,
            driver_artifact_hash=pins["psycopg"].artifact_hash,
            deployment_mode="disposable_single_instance",
            license_declaration="community benchmark only",
            settings_profile_id="postgresql_settings_r1",
            settings=(
                {"setting_name": "statement_timeout_milliseconds", "value_json": "1000"},
                {"setting_name": "worker_count", "value_json": "1"},
            ),
            index_profile_id="governed_graph_indexes_r1",
        ),
    )


def _preflight_report(args: argparse.Namespace) -> dict[str, Any]:
    package = _authority_and_package(args.fixture_profile)
    return _safe_report(
        package,
        verdict="decision_blocked",
        blockers=(
            "live_disposable_engine_campaign_not_requested",
            "cgroup_memory_peak_telemetry_not_observed",
            "fresh_server_provisioning_samples_not_observed",
        ),
        cycles=args.cycles,
        samples=args.samples,
    )


def _run_live(args: argparse.Namespace) -> dict[str, Any]:
    """Provision source-free containers, then execute the client on their private network."""

    _authority_and_package(args.fixture_profile)
    run_id = uuid4().hex[:12]
    network = f"issue33-benchmark-{run_id}"
    postgres_name = f"issue33-postgres-{run_id}"
    neo4j_name = f"issue33-neo4j-{run_id}"
    _run(["docker", "network", "create", network])
    try:
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                postgres_name,
                "--network",
                network,
                "--cpus",
                "2",
                "--memory",
                "4g",
                "--memory-swap",
                "4g",
                "--pids-limit",
                "256",
                "--tmpfs",
                "/var/lib/postgresql/data",
                "--env",
                "POSTGRES_DB=issue33",
                "--env",
                "POSTGRES_USER=issue33",
                "--env",
                "POSTGRES_PASSWORD=issue33",
                POSTGRES_IMAGE,
            ]
        )
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                neo4j_name,
                "--network",
                network,
                "--cpus",
                "2",
                "--memory",
                "4g",
                "--memory-swap",
                "4g",
                "--pids-limit",
                "256",
                "--tmpfs",
                "/data",
                "--env",
                "NEO4J_AUTH=neo4j/issue33benchmark",
                "--env",
                "NEO4J_server_memory_heap_initial__size=256m",
                "--env",
                "NEO4J_server_memory_heap_max__size=256m",
                NEO4J_IMAGE,
            ]
        )
        _wait_for_postgres(postgres_name)
        _wait_for_neo4j(neo4j_name)
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "--volume",
            f"{ROOT}:/workspace:ro",
            "--workdir",
            "/workspace",
            "formowl-dev:local",
            "python",
            "scripts/issue33_storage_engine_benchmark.py",
            "--inside-network",
            "--postgres-host",
            postgres_name,
            "--neo4j-host",
            neo4j_name,
            "--cycles",
            str(args.cycles),
            "--samples",
            str(args.samples),
            "--fixture-profile",
            args.fixture_profile,
        ]
        client = _run(command)
        report = json.loads(client.stdout)
        report["resource_limits_verified"] = _container_limit_summary((postgres_name, neo4j_name))
        report["cgroup_memory_peak_bytes"] = {
            "postgresql": _container_memory_peak_bytes(postgres_name),
            "neo4j": _container_memory_peak_bytes(neo4j_name),
        }
        report["verdict"] = "decision_blocked"
        decision_blockers = set(report["decision_blockers"])
        decision_blockers.discard(
            "cgroup_memory_peak_telemetry_not_available_inside_client_container"
        )
        decision_blockers.add("fresh_server_per_cold_sample_not_observed")
        report["decision_blockers"] = sorted(decision_blockers)
        return report
    finally:
        for name in (neo4j_name, postgres_name):
            subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)


def _run_inside_network(args: argparse.Namespace) -> dict[str, Any]:
    if not args.postgres_host or not args.neo4j_host:
        raise SystemExit("--inside-network requires both engine host names")
    package = _authority_and_package(args.fixture_profile)
    from formowl_graph.storage.benchmark_neo4j import Neo4jBenchmarkPort
    from formowl_graph.storage.benchmark_postgres import PostgreSQLBenchmarkPort

    ports: dict[str, Any] = {
        "postgresql": PostgreSQLBenchmarkPort.connect(
            f"postgresql://issue33:issue33@{args.postgres_host}:5432/issue33?sslmode=disable"
        ),
        "neo4j": Neo4jBenchmarkPort.connect(
            f"bolt://{args.neo4j_host}:7687",
            "neo4j",
            "issue33benchmark",
        ),
    }
    try:
        cycles = []
        for cycle in range(args.cycles):
            order = ("postgresql", "neo4j") if cycle % 2 == 0 else ("neo4j", "postgresql")
            runs = {}
            for engine_id in order:
                runs[engine_id] = _exercise_engine(ports[engine_id], package, samples=args.samples)
            cycles.append({"cycle_index": cycle + 1, "engine_order": list(order), "runs": runs})
        return _safe_report(
            package,
            verdict="decision_blocked",
            blockers=(
                "cgroup_memory_peak_telemetry_not_available_inside_client_container",
                "fresh_server_per_cold_sample_not_observed",
            ),
            cycles=args.cycles,
            samples=args.samples,
            cycle_results=cycles,
        )
    finally:
        for port in ports.values():
            port.close()


def _exercise_engine(
    port: Any, package: StorageEngineBenchmarkPackage, *, samples: int
) -> dict[str, Any]:
    faults: list[str] = []
    fault_started = time.monotonic_ns()
    try:
        for fault in package.faults:
            execute_fault_conformance(port, package, fault.fault_id)
            faults.append(fault.fault_id)
    except Exception as exc:
        return _failed_engine_run("fault_conformance", exc, faults)
    fault_duration = _elapsed_ms(fault_started)

    try:
        cold = [_sequence_sample(port, package) for _ in range(samples)]
        _sequence_sample(port, package)  # unmeasured declared warm-up
        warm = [_sequence_sample(port, package) for _ in range(samples)]
        rebuild = _sequence_sample(port, package)
        restore_evidence = port.inspect_last_restore_execution()
        if restore_evidence is None or not restore_evidence.restore_verified:
            raise RuntimeError("benchmark restore verification is unavailable")
    except Exception as exc:
        return _failed_engine_run("governed_sequence", exc, faults)
    return {
        "correctness_passed": True,
        "cold_ms": cold,
        "warm_ms": warm,
        "cold_summary": _summary(cold),
        "warm_summary": _summary(warm),
        "fault_case_count": len(faults),
        "fault_duration_ms": fault_duration,
        "rebuild_ms": rebuild,
        "restore_verified": restore_evidence.restore_verified,
        "restore_evidence_hash": restore_evidence.evidence_hash,
        "operational_failures": [],
        "measurement_limitations": [
            "cold samples reset storage state but do not provision a fresh server process",
            "maximum RSS/cgroup memory.peak is not available inside the client container",
        ],
    }


def _failed_engine_run(
    phase: str,
    exc: Exception,
    verified_fault_ids: list[str],
) -> dict[str, Any]:
    error_type = type(exc).__name__
    return {
        "correctness_passed": False,
        "cold_ms": [],
        "warm_ms": [],
        "cold_summary": {},
        "warm_summary": {},
        "fault_case_count": len(verified_fault_ids),
        "fault_duration_ms": 0.0,
        "rebuild_ms": 0.0,
        "restore_verified": False,
        "restore_evidence_hash": "",
        "operational_failures": [
            {
                "phase": phase,
                "error_type": error_type,
                "error_hash": canonical_json_sha256({"phase": phase, "error_type": error_type}),
            }
        ],
        "measurement_limitations": [
            "performance samples are ineligible because correctness did not pass"
        ],
    }


def _sequence_sample(port: Any, package: StorageEngineBenchmarkPackage) -> float:
    started = time.monotonic_ns()
    port.load_sealed_package(package)
    for case_id in _CASE_ORDER:
        verify_case_execution(port, package, case_id)
    return _elapsed_ms(started)


def _safe_report(
    package: StorageEngineBenchmarkPackage,
    *,
    verdict: str,
    blockers: tuple[str, ...],
    cycles: int,
    samples: int,
    cycle_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    live_correctness = (
        cycle_results is not None
        and bool(cycle_results)
        and all(
            run.get("correctness_passed") is True
            for cycle in cycle_results
            for run in cycle["runs"].values()
        )
    )
    live_restore = live_correctness and all(
        run.get("restore_verified") is True
        for cycle in cycle_results or []
        for run in cycle["runs"].values()
    )
    effective_blockers = set(blockers)
    if cycle_results is not None and not live_correctness:
        effective_blockers.add("hard_correctness_or_fault_conformance_failed")
    if cycle_results is not None and not live_restore:
        effective_blockers.add("backup_restore_not_verified")
    invariant_status = (
        "pending_live_execution"
        if cycle_results is None
        else ("passed" if live_correctness else "failed")
    )
    return {
        "report_schema_version": "issue33_storage_engine_safe_report_r1",
        "status": "diagnostic_only",
        "input_kind": package.input_kind,
        "package_hash": package.package_hash,
        "fixture_hash": package.fixture.content_hash,
        "fixture_profile": package.fixture_profile,
        "raw_pst_read_count": package.raw_pst_read_count,
        "pst_parser_invocation_count": package.pst_parser_invocation_count,
        "new_extractor_run_count": package.new_extractor_run_count,
        "authority_state": {
            "authority_state_fingerprint": package.authority_state.authority_state_fingerprint,
            "execution_fingerprint": package.authority_state.execution_fingerprint,
            "status": package.authority_state.status,
            "methodology_ready": package.authority_state.methodology_ready,
            "current_tokenizer_id": package.authority_state.current_tokenizer_id,
            "target_tokenizer_id": package.authority_state.target_tokenizer_id,
            "require_ready_exit_code": package.authority_state.require_ready_exit_code,
        },
        "engine_profiles": [
            {
                "engine_id": profile.engine_id,
                "product_version": profile.product_version,
                "edition": profile.edition,
                "image_digest": profile.image_digest,
                "driver_version": profile.driver_version,
                "profile_hash": profile.profile_hash,
            }
            for profile in package.engine_profiles
        ],
        "hard_invariants": {
            "semantic_equality": invariant_status,
            "permission_and_provenance": invariant_status,
            "rollback_lifecycle_schema": invariant_status,
            "structured_set_determinism": invariant_status,
            "rebuild_restore": (
                "pending_live_execution"
                if cycle_results is None
                else ("passed" if live_restore else "failed")
            ),
        },
        "planned_clean_rebuild_cycles": cycles,
        "planned_samples_per_temperature": samples,
        "cycle_results": cycle_results or [],
        "verdict": verdict,
        "decision_blockers": sorted(effective_blockers),
        "limitations": [
            "source-free fixture validates governed storage semantics only",
            "no result establishes methodology readiness, KG-versus-ontology quality, or production migration",
            "Neo4j Community native RBAC is not permission authority",
        ],
        "report_hash": "",
    } | {
        "report_hash": canonical_json_sha256(
            {
                "package_hash": package.package_hash,
                "verdict": verdict,
                "blockers": sorted(effective_blockers),
                "cycle_results": cycle_results or [],
            }
        )
    }


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": ordered[(len(ordered) - 1) // 2],
        "p95_ms": ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)],
        "median_ms": ordered[len(ordered) // 2],
    }


def _container_limit_summary(names: tuple[str, ...]) -> list[dict[str, Any]]:
    result = []
    for name in names:
        inspected = _run(["docker", "inspect", name, "--format", "{{json .HostConfig}}"])
        config = json.loads(inspected.stdout)
        result.append(
            {
                "container_name_hash": canonical_json_sha256({"name": name}),
                "nano_cpus": config["NanoCpus"],
                "memory": config["Memory"],
                "memory_swap": config["MemorySwap"],
                "pids_limit": config["PidsLimit"],
            }
        )
    return result


def _container_memory_peak_bytes(name: str) -> int:
    completed = _run(
        [
            "docker",
            "exec",
            name,
            "sh",
            "-lc",
            "cat /sys/fs/cgroup/memory.peak",
        ]
    )
    try:
        value = int(completed.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("benchmark cgroup memory.peak is unavailable") from exc
    if value <= 0:
        raise RuntimeError("benchmark cgroup memory.peak is invalid")
    return value


def _wait_for_postgres(name: str) -> None:
    for _ in range(60):
        completed = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "issue33", "-d", "issue33"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("benchmark PostgreSQL did not become ready")


def _wait_for_neo4j(name: str) -> None:
    for _ in range(60):
        completed = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "cypher-shell",
                "-u",
                "neo4j",
                "-p",
                "issue33benchmark",
                "RETURN 1",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("benchmark Neo4j did not become ready")


def _installed_distribution_hash(name: str) -> str:
    distribution = importlib.metadata.distribution(name)
    digest = hashlib.sha256()
    selected = sorted(
        item
        for item in distribution.files or ()
        if str(item).endswith((".py", "METADATA", "RECORD"))
    )
    if not selected:
        raise RuntimeError("benchmark dependency artifact files are unavailable")
    for item in selected:
        path = distribution.locate_file(item)
        if not path.is_file():
            raise RuntimeError("benchmark dependency artifact file is unavailable")
        payload = path.read_bytes()
        digest.update(str(item).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _git_revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0 and len(completed.stdout.strip()) == 40:
        return completed.stdout.strip()
    return "0" * 40


def _source_hash() -> str:
    values = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            ROOT / "scripts/issue33_storage_engine_benchmark.py",
            ROOT / "python/formowl_graph/storage/benchmark_contract.py",
            ROOT / "python/formowl_graph/storage/benchmark_postgres.py",
            ROOT / "python/formowl_graph/storage/benchmark_neo4j.py",
        )
    }
    return canonical_json_sha256(values)


def _elapsed_ms(started_ns: int) -> float:
    return round((time.monotonic_ns() - started_ns) / 1_000_000, 3)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
