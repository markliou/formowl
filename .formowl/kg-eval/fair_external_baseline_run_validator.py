#!/usr/bin/env python3
"""Fair external baseline run evidence validator.

This validator is the intake gate for the broad fair-baseline objective. It
does not create passing evidence. It only validates a real evidence packet when
one is supplied under ``inputs/fair_external_baseline_run_packet.json``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import external_literature_baseline_protocol_recovery as literature


ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
RESULTS = ROOT / "results"

PACKET_PATH = INPUTS / "fair_external_baseline_run_packet.json"
REAL_ARTIFACT_ROOT = "inputs/fair_baseline_real"
REAL_ARTIFACT_ROOT_PATH = ROOT / REAL_ARTIFACT_ROOT
REAL_ARTIFACT_ROOT_PARTS = tuple(Path(REAL_ARTIFACT_ROOT).parts)
REQUIRED_BASELINES = literature.REQUIRED_BASELINES
REQUIRED_SOURCE_IDS_BY_BASELINE = literature.REQUIRED_SOURCE_IDS_BY_BASELINE
REQUIRED_BASELINE_URLS = {
    "microsoft_graphrag": literature.REQUIRED_SOURCE_URLS["microsoft_graphrag_repo"],
    "lightrag": literature.REQUIRED_SOURCE_URLS["lightrag_repo"],
    "hipporag": literature.REQUIRED_SOURCE_URLS["hipporag_repo"],
}

HEX64_CHARS = set("0123456789abcdef")

RUN_ARTIFACT_FIELDS = (
    "package_lock_artifact",
    "config_artifact",
    "index_build_log_artifact",
    "query_run_log_artifact",
    "answer_output_artifact",
    "graph_output_artifact",
    "permission_probe_artifact",
)
EXPECTED_RUN_ARTIFACT_TYPES = {
    "package_lock_artifact": "fair_baseline_package_lock_v1",
    "config_artifact": "fair_baseline_config_v1",
    "index_build_log_artifact": "fair_baseline_index_build_log_v1",
    "query_run_log_artifact": "fair_baseline_query_run_log_v1",
    "answer_output_artifact": "fair_baseline_answer_output_v1",
    "graph_output_artifact": "fair_baseline_graph_output_v1",
    "permission_probe_artifact": "fair_baseline_permission_probe_v1",
}

EQUALIZED_FIELDS = (
    "corpus_export_sha256",
    "prompt_set_sha256",
    "evaluation_question_set_sha256",
    "access_policy_sha256",
    "completion_model_budget_sha256",
    "embedding_model_budget_sha256",
    "ontology_mapping_sha256",
)

REQUIRED_PERMISSION_PROBES = (
    "revoked_grant_content_denied",
    "private_content_not_returned",
    "raw_asset_access_denied",
    "entity_match_does_not_grant_access",
)
PACKET_ALLOWED_FIELDS = {
    "artifact_id",
    "evidence_kind",
    "recovered_after_tmp_loss",
    "run_environment",
    "source_lock_sha256",
    "baseline_runs",
    "human_answer_adjudication",
    "graph_quality_validation",
    "permission_probes",
    "claim_boundary",
}
CLAIM_BOUNDARY_ALLOWED_FIELDS = {
    "supports_fair_external_baseline_comparison_claim",
    "supports_production_ready_claim",
    "supports_top_tier_scientific_validation_claim",
    "supports_unreviewed_business_judgment_claim",
    "supports_unreviewed_canonical_merge_claim",
}


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strong_hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in HEX64_CHARS for char in value)
        and len(set(value)) > 1
    )


def _is_test_or_sandbox_path_parts(parts: tuple[str, ...]) -> bool:
    return any(
        part == "assembler_test"
        or part.startswith("test_")
        or part.endswith("_test")
        or part.startswith("preflight_test")
        or part == "validator_fixture"
        for part in parts
    )


def _is_template_path_parts(parts: tuple[str, ...]) -> bool:
    return any(part == "templates" or part.endswith(".template.json") for part in parts)


def _path_has_symlink_component(path: Path) -> bool:
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def safe_relative_artifact_path(
    value: object,
    *,
    allow_test_artifacts: bool = False,
) -> Path | None:
    if artifact_path_rejection_reason(value, allow_test_artifacts=allow_test_artifacts):
        return None
    path = Path(str(value))
    candidate = (ROOT / path).resolve()
    try:
        candidate.relative_to(REAL_ARTIFACT_ROOT_PATH.resolve())
    except ValueError:
        return None
    return candidate


def artifact_path_rejection_reason(
    value: object,
    *,
    allow_test_artifacts: bool = False,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "path missing or malformed"
    if value.startswith(("/", "\\", "file://", "s3://", "gs://", "object://")):
        return f"path must be under {REAL_ARTIFACT_ROOT}"
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return f"path must be under {REAL_ARTIFACT_ROOT}"
    if (
        len(path.parts) <= len(REAL_ARTIFACT_ROOT_PARTS)
        or path.parts[: len(REAL_ARTIFACT_ROOT_PARTS)] != REAL_ARTIFACT_ROOT_PARTS
    ):
        return f"path must be under {REAL_ARTIFACT_ROOT}"
    real_root_relative_parts = path.parts[len(REAL_ARTIFACT_ROOT_PARTS) :]
    if _is_template_path_parts(real_root_relative_parts):
        return f"template artifacts are not accepted under {REAL_ARTIFACT_ROOT}"
    if not allow_test_artifacts and _is_test_or_sandbox_path_parts(real_root_relative_parts):
        return f"test or sandbox artifacts are not accepted under {REAL_ARTIFACT_ROOT}"
    if _path_has_symlink_component(path):
        return f"artifact symlinks are not accepted under {REAL_ARTIFACT_ROOT}"
    candidate = (ROOT / path).resolve()
    try:
        resolved_relative_parts = candidate.relative_to(REAL_ARTIFACT_ROOT_PATH.resolve()).parts
    except ValueError:
        return f"path must be under {REAL_ARTIFACT_ROOT}"
    if _is_template_path_parts(resolved_relative_parts):
        return f"template artifacts are not accepted under {REAL_ARTIFACT_ROOT}"
    if not allow_test_artifacts and _is_test_or_sandbox_path_parts(resolved_relative_parts):
        return f"test or sandbox artifacts are not accepted under {REAL_ARTIFACT_ROOT}"
    return None


def artifact_matches_sha256(
    path_value: object,
    digest_value: object,
    *,
    allow_test_artifacts: bool = False,
) -> bool:
    path = safe_relative_artifact_path(
        path_value,
        allow_test_artifacts=allow_test_artifacts,
    )
    return (
        path is not None
        and strong_hex64(digest_value)
        and path.exists()
        and sha256_file(path) == digest_value
    )


def load_artifact(
    path_value: object,
    digest_value: object,
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    if not artifact_matches_sha256(
        path_value,
        digest_value,
        allow_test_artifacts=allow_test_artifacts,
    ):
        return {}
    path = safe_relative_artifact_path(
        path_value,
        allow_test_artifacts=allow_test_artifacts,
    )
    if path is None:
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def load_input_packet() -> dict[str, Any]:
    if not PACKET_PATH.exists():
        return {}
    loaded = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _validate_claim_boundary(packet: dict[str, Any], blockers: list[str]) -> None:
    claims = packet.get("claim_boundary")
    if not isinstance(claims, dict):
        blockers.append("fair baseline packet claim boundary missing")
        claims = {}
    unsupported_fields = sorted(set(claims) - CLAIM_BOUNDARY_ALLOWED_FIELDS)
    if unsupported_fields:
        blockers.append(
            "fair baseline packet claim boundary has unsupported fields: "
            + ", ".join(unsupported_fields)
        )
    if claims.get("supports_fair_external_baseline_comparison_claim") is not True:
        blockers.append("fair baseline packet does not claim fair-baseline completion")
    for flag in (
        "supports_production_ready_claim",
        "supports_top_tier_scientific_validation_claim",
        "supports_unreviewed_business_judgment_claim",
        "supports_unreviewed_canonical_merge_claim",
    ):
        if claims.get(flag) is not False:
            blockers.append(f"fair baseline packet overclaims unsupported claim: {flag}")


def _validate_run_environment(packet: dict[str, Any], blockers: list[str]) -> None:
    environment = packet.get("run_environment")
    if not isinstance(environment, dict):
        blockers.append("fair baseline run environment missing")
        return
    if environment.get("non_synthetic_benchmark_context") is not True:
        blockers.append("fair baseline run environment is not non-synthetic")
    if environment.get("uses_real_external_packages") is not True:
        blockers.append("fair baseline run environment did not use real external packages")
    if environment.get("uses_mocked_llm_or_retrieval") is not False:
        blockers.append("fair baseline run environment allows mocked LLM/retrieval")
    for field in ("container_image_digest_sha256", "run_manifest_sha256"):
        if not strong_hex64(environment.get(field)):
            blockers.append(f"fair baseline run environment {field} missing or weak")


def _validate_source_lock(packet: dict[str, Any], blockers: list[str]) -> None:
    source_lock_sha256 = packet.get("source_lock_sha256")
    expected = literature.required_baseline_source_lock_sha256()
    if not strong_hex64(source_lock_sha256):
        blockers.append("fair baseline source lock hash missing or weak")
    elif source_lock_sha256 != expected:
        blockers.append("fair baseline source lock hash does not match literature protocol")


def _validate_run_artifact_common(
    *,
    baseline_id: str,
    artifact_field: str,
    artifact: dict[str, Any],
    run: dict[str, Any],
    packet: dict[str, Any],
    blockers: list[str],
) -> None:
    if not artifact:
        blockers.append(f"{baseline_id} {artifact_field} artifact content is not a JSON object")
        return
    if artifact.get("artifact_type") != EXPECTED_RUN_ARTIFACT_TYPES[artifact_field]:
        blockers.append(f"{baseline_id} {artifact_field} artifact type mismatch")
    if artifact.get("baseline_id") != baseline_id:
        blockers.append(f"{baseline_id} {artifact_field} baseline binding mismatch")
    if artifact.get("source_lock_sha256") != packet.get("source_lock_sha256"):
        blockers.append(f"{baseline_id} {artifact_field} source lock binding mismatch")
    if artifact.get("source_ids") != run.get("source_ids"):
        blockers.append(f"{baseline_id} {artifact_field} source id binding mismatch")
    if artifact.get("package_source_url") != run.get("package_source_url"):
        blockers.append(f"{baseline_id} {artifact_field} package source binding mismatch")
    if artifact.get("package_version") != run.get("package_version"):
        blockers.append(f"{baseline_id} {artifact_field} package version binding mismatch")
    if artifact.get("real_package_execution") is not True:
        blockers.append(f"{baseline_id} {artifact_field} is not bound to real package execution")
    if artifact.get("mock_or_dry_run") is not False:
        blockers.append(f"{baseline_id} {artifact_field} allows mock or dry-run output")
    if artifact.get("synthetic_corpus") is not False:
        blockers.append(f"{baseline_id} {artifact_field} is bound to synthetic corpus")
    if artifact.get("uses_mocked_llm_or_retrieval") is not False:
        blockers.append(f"{baseline_id} {artifact_field} allows mocked LLM or retrieval")
    run_environment = packet.get("run_environment", {})
    expected_run_manifest = (
        run_environment.get("run_manifest_sha256") if isinstance(run_environment, dict) else None
    )
    if artifact.get("run_manifest_sha256") != expected_run_manifest:
        blockers.append(f"{baseline_id} {artifact_field} run manifest binding mismatch")


def _validate_run_artifact_specific(
    *,
    baseline_id: str,
    artifact_field: str,
    artifact: dict[str, Any],
    run: dict[str, Any],
    blockers: list[str],
) -> None:
    if artifact_field == "package_lock_artifact":
        if not strong_hex64(artifact.get("package_lock_sha256")):
            blockers.append(f"{baseline_id} package lock artifact package lock hash missing")
        if artifact.get("package_resolved") is not True:
            blockers.append(f"{baseline_id} package lock artifact is not resolved")
        return

    if artifact_field == "config_artifact":
        for field in EQUALIZED_FIELDS:
            if artifact.get(field) != run.get(field):
                blockers.append(
                    f"{baseline_id} config artifact does not bind equalized field: {field}"
                )
        return

    if artifact_field == "index_build_log_artifact":
        if artifact.get("index_build_completed") is not True:
            blockers.append(f"{baseline_id} index build log is not complete")
        if not _positive_int(artifact.get("indexed_document_count")):
            blockers.append(f"{baseline_id} index build log indexed document count missing")
        return

    if artifact_field == "query_run_log_artifact":
        if artifact.get("query_run_completed") is not True:
            blockers.append(f"{baseline_id} query run log is not complete")
        if artifact.get("evaluation_question_set_sha256") != run.get(
            "evaluation_question_set_sha256"
        ):
            blockers.append(f"{baseline_id} query run log question set binding mismatch")
        if not _positive_int(artifact.get("query_count")):
            blockers.append(f"{baseline_id} query run log query count missing")
        return

    if artifact_field == "answer_output_artifact":
        if artifact.get("generated_by_real_package") is not True:
            blockers.append(f"{baseline_id} answer output is not generated by real package")
        if artifact.get("evaluation_question_set_sha256") != run.get(
            "evaluation_question_set_sha256"
        ):
            blockers.append(f"{baseline_id} answer output question set binding mismatch")
        if not _positive_int(artifact.get("answer_count")):
            blockers.append(f"{baseline_id} answer output answer count missing")
        return

    if artifact_field == "graph_output_artifact":
        if artifact.get("generated_by_real_package") is not True:
            blockers.append(f"{baseline_id} graph output is not generated by real package")
        if not _positive_int(artifact.get("entity_count")):
            blockers.append(f"{baseline_id} graph output entity count missing")
        if not _positive_int(artifact.get("relation_count")):
            blockers.append(f"{baseline_id} graph output relation count missing")
        return

    if artifact_field == "permission_probe_artifact":
        for probe in REQUIRED_PERMISSION_PROBES:
            if artifact.get(probe) is not True:
                blockers.append(
                    f"{baseline_id} permission probe artifact failed or missing: {probe}"
                )
        if artifact.get("private_content_leak_count") != 0:
            blockers.append(f"{baseline_id} permission probe artifact leaked private content")
        if artifact.get("raw_asset_access_count") != 0:
            blockers.append(f"{baseline_id} permission probe artifact exposed raw asset access")


def _validate_run_artifact_content(
    *,
    baseline_id: str,
    artifact_field: str,
    run: dict[str, Any],
    packet: dict[str, Any],
    blockers: list[str],
    allow_test_artifacts: bool = False,
) -> None:
    artifact = load_artifact(
        run.get(artifact_field),
        run.get(f"{artifact_field}_sha256"),
        allow_test_artifacts=allow_test_artifacts,
    )
    _validate_run_artifact_common(
        baseline_id=baseline_id,
        artifact_field=artifact_field,
        artifact=artifact,
        run=run,
        packet=packet,
        blockers=blockers,
    )
    if artifact:
        _validate_run_artifact_specific(
            baseline_id=baseline_id,
            artifact_field=artifact_field,
            artifact=artifact,
            run=run,
            blockers=blockers,
        )


def _validate_baseline_runs(
    packet: dict[str, Any],
    blockers: list[str],
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, dict[str, Any]]:
    runs = packet.get("baseline_runs")
    if not isinstance(runs, list):
        blockers.append("fair baseline package runs missing")
        return {}
    by_baseline: dict[str, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict):
            blockers.append("fair baseline package run row is not an object")
            continue
        baseline_id = run.get("baseline_id")
        if baseline_id not in REQUIRED_BASELINES:
            blockers.append(f"unexpected fair baseline package id: {baseline_id}")
            continue
        if baseline_id in by_baseline:
            blockers.append(f"duplicate fair baseline package run: {baseline_id}")
        by_baseline[baseline_id] = run

        if run.get("package_source_url") != REQUIRED_BASELINE_URLS[baseline_id]:
            blockers.append(f"{baseline_id} package source URL does not match locked reference")
        if run.get("source_ids") != list(REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]):
            blockers.append(f"{baseline_id} source ids do not match locked literature source list")
        if run.get("real_package_execution") is not True:
            blockers.append(f"{baseline_id} real package execution flag missing")
        if run.get("mock_or_dry_run") is not False:
            blockers.append(f"{baseline_id} run is marked as mock or dry run")
        if run.get("synthetic_corpus") is not False:
            blockers.append(f"{baseline_id} run used synthetic corpus")
        if not isinstance(run.get("package_version"), str) or not run["package_version"]:
            blockers.append(f"{baseline_id} package version missing")

        for field in RUN_ARTIFACT_FIELDS:
            digest_field = f"{field}_sha256"
            path_blocker = artifact_path_rejection_reason(
                run.get(field),
                allow_test_artifacts=allow_test_artifacts,
            )
            if path_blocker:
                if path_blocker == "path missing or malformed":
                    blockers.append(f"{baseline_id} {field} missing or hash mismatch")
                else:
                    blockers.append(f"{baseline_id} {field} {path_blocker}")
            elif not artifact_matches_sha256(
                run.get(field),
                run.get(digest_field),
                allow_test_artifacts=allow_test_artifacts,
            ):
                blockers.append(f"{baseline_id} {field} missing or hash mismatch")
            else:
                _validate_run_artifact_content(
                    baseline_id=baseline_id,
                    artifact_field=field,
                    run=run,
                    packet=packet,
                    blockers=blockers,
                    allow_test_artifacts=allow_test_artifacts,
                )

        for field in EQUALIZED_FIELDS:
            if not strong_hex64(run.get(field)):
                blockers.append(f"{baseline_id} equalized field missing or weak: {field}")

    missing = sorted(set(REQUIRED_BASELINES) - set(by_baseline))
    if missing:
        blockers.append("fair baseline package runs missing baselines: " + ", ".join(missing))

    for field in EQUALIZED_FIELDS:
        values = {run.get(field) for run in by_baseline.values() if strong_hex64(run.get(field))}
        if len(values) != 1:
            blockers.append(f"fair baseline runs are not equalized for {field}")
    return by_baseline


def _validate_human_answer_adjudication(
    packet: dict[str, Any],
    run_by_baseline: dict[str, dict[str, Any]],
    blockers: list[str],
) -> None:
    adjudication = packet.get("human_answer_adjudication")
    if not isinstance(adjudication, dict):
        blockers.append("human answer-quality adjudication packet missing")
        return
    if adjudication.get("artifact_id") != "human_answer_adjudication_results_v1":
        blockers.append("human answer-quality adjudication artifact id mismatch")
    if adjudication.get("completed") is not True:
        blockers.append("human answer-quality adjudication is not complete")
    if adjudication.get("synthetic_or_agent_generated") is not False:
        blockers.append("human answer-quality adjudication is synthetic or agent-generated")
    adjudication_question_set = adjudication.get("question_set_sha256")
    if not strong_hex64(adjudication_question_set):
        blockers.append("human answer-quality adjudication question set hash missing")
    run_question_sets = {
        run.get("evaluation_question_set_sha256")
        for run in run_by_baseline.values()
        if strong_hex64(run.get("evaluation_question_set_sha256"))
    }
    if len(run_question_sets) == 1 and adjudication_question_set not in run_question_sets:
        blockers.append(
            "human answer-quality question set is not bound to package evaluation question set"
        )

    reviewers = adjudication.get("reviewers")
    if not isinstance(reviewers, list) or len(reviewers) < 2:
        blockers.append("human answer-quality adjudication needs at least two first-pass reviewers")
        reviewers = []
    reviewer_ids = set()
    for reviewer in reviewers:
        if not isinstance(reviewer, dict):
            blockers.append("human answer-quality reviewer row is not an object")
            continue
        reviewer_id = reviewer.get("reviewer_id")
        if not isinstance(reviewer_id, str) or not reviewer_id:
            blockers.append("human answer-quality reviewer id missing")
        else:
            reviewer_ids.add(reviewer_id)
        if reviewer.get("reviewer_type") != "human":
            blockers.append("human answer-quality reviewer is not marked human")
        if reviewer.get("independent_first_pass") is not True:
            blockers.append("human answer-quality reviewer is not independent first pass")
        if not strong_hex64(reviewer.get("sealed_submission_sha256")):
            blockers.append("human answer-quality sealed submission hash missing")
    if len(reviewer_ids) < 2:
        blockers.append("human answer-quality independent reviewer identities are not distinct")

    if (
        not isinstance(adjudication.get("adjudicator_id"), str)
        or not adjudication["adjudicator_id"]
    ):
        blockers.append("human answer-quality adjudicator id missing")
    if not strong_hex64(adjudication.get("final_adjudication_sha256")):
        blockers.append("human answer-quality final adjudication hash missing")
    if not strong_hex64(adjudication.get("custody_receipt_sha256")):
        blockers.append("human answer-quality custody receipt hash missing")

    rows = adjudication.get("per_baseline_rows")
    if not isinstance(rows, list):
        blockers.append("human answer-quality per-baseline rows missing")
        return
    baselines = {row.get("baseline_id") for row in rows if isinstance(row, dict)}
    if baselines != set(REQUIRED_BASELINES):
        blockers.append("human answer-quality rows do not cover every baseline")
    for row in rows:
        if not isinstance(row, dict):
            blockers.append("human answer-quality row is not an object")
            continue
        baseline_id = row.get("baseline_id")
        if baseline_id not in run_by_baseline:
            blockers.append(
                f"human answer-quality row references missing baseline run: {baseline_id}"
            )
        if (
            not isinstance(row.get("question_count"), int)
            or isinstance(row.get("question_count"), bool)
            or row["question_count"] <= 0
        ):
            blockers.append(f"{baseline_id} human answer-quality question count missing")
        if not strong_hex64(row.get("answer_output_artifact_sha256")):
            blockers.append(f"{baseline_id} human answer-quality answer output hash missing")
        elif baseline_id in run_by_baseline and row.get(
            "answer_output_artifact_sha256"
        ) != run_by_baseline[baseline_id].get("answer_output_artifact_sha256"):
            blockers.append(
                f"{baseline_id} human answer-quality row is not bound to package answer output"
            )


def _validate_graph_quality(
    packet: dict[str, Any], run_by_baseline: dict[str, dict[str, Any]], blockers: list[str]
) -> None:
    graph_quality = packet.get("graph_quality_validation")
    if not isinstance(graph_quality, dict):
        blockers.append("graph-quality validation packet missing")
        return
    if graph_quality.get("completed") is not True:
        blockers.append("graph-quality validation is not complete")
    if graph_quality.get("human_reviewed") is not True:
        blockers.append("graph-quality validation is not human reviewed")
    rows = graph_quality.get("per_baseline_rows")
    if not isinstance(rows, list):
        blockers.append("graph-quality per-baseline rows missing")
        return
    baselines = {row.get("baseline_id") for row in rows if isinstance(row, dict)}
    if baselines != set(REQUIRED_BASELINES):
        blockers.append("graph-quality rows do not cover every baseline")
    for row in rows:
        if not isinstance(row, dict):
            blockers.append("graph-quality row is not an object")
            continue
        baseline_id = row.get("baseline_id")
        if baseline_id not in run_by_baseline:
            blockers.append(f"graph-quality row references missing baseline run: {baseline_id}")
        if not strong_hex64(row.get("graph_output_artifact_sha256")):
            blockers.append(f"{baseline_id} graph-quality graph output hash missing")
        elif baseline_id in run_by_baseline and row.get(
            "graph_output_artifact_sha256"
        ) != run_by_baseline[baseline_id].get("graph_output_artifact_sha256"):
            blockers.append(f"{baseline_id} graph-quality row is not bound to package graph output")
        if (
            not isinstance(row.get("reviewed_entity_count"), int)
            or row.get("reviewed_entity_count", 0) <= 0
        ):
            blockers.append(f"{baseline_id} graph-quality reviewed entity count missing")
        if (
            not isinstance(row.get("reviewed_relation_count"), int)
            or row.get("reviewed_relation_count", 0) <= 0
        ):
            blockers.append(f"{baseline_id} graph-quality reviewed relation count missing")


def _validate_permission_probes(
    packet: dict[str, Any], run_by_baseline: dict[str, dict[str, Any]], blockers: list[str]
) -> None:
    probes = packet.get("permission_probes")
    if not isinstance(probes, list):
        blockers.append("fair baseline permission probes missing")
        return
    baselines = {row.get("baseline_id") for row in probes if isinstance(row, dict)}
    if baselines != set(REQUIRED_BASELINES):
        blockers.append("fair baseline permission probes do not cover every baseline")
    for row in probes:
        if not isinstance(row, dict):
            blockers.append("fair baseline permission probe row is not an object")
            continue
        baseline_id = row.get("baseline_id")
        if baseline_id not in run_by_baseline:
            blockers.append(f"permission probe references missing baseline run: {baseline_id}")
        if not strong_hex64(row.get("permission_probe_artifact_sha256")):
            blockers.append(f"{baseline_id} permission probe artifact hash missing")
        elif baseline_id in run_by_baseline and row.get(
            "permission_probe_artifact_sha256"
        ) != run_by_baseline[baseline_id].get("permission_probe_artifact_sha256"):
            blockers.append(
                f"{baseline_id} permission probe row is not bound to package probe artifact"
            )
        for probe in REQUIRED_PERMISSION_PROBES:
            if row.get(probe) is not True:
                blockers.append(f"{baseline_id} permission probe failed or missing: {probe}")
        if row.get("private_content_leak_count") != 0:
            blockers.append(f"{baseline_id} permission probe leaked private content")
        if row.get("raw_asset_access_count") != 0:
            blockers.append(f"{baseline_id} permission probe exposed raw asset access")


def validate_packet(
    packet: dict[str, Any],
    *,
    allow_test_artifacts: bool = False,
) -> list[str]:
    blockers: list[str] = []
    if not packet:
        return [
            "fair external baseline run packet missing",
            "real Microsoft GraphRAG/LightRAG/HippoRAG package runs are not present",
            "human answer-quality adjudication packet is not present",
            "graph-quality validation packet is not present",
            "permission leak probe results are not present",
        ]
    if packet.get("artifact_id") != "fair_external_baseline_run_packet_v1":
        blockers.append("fair baseline run packet artifact id mismatch")
    if packet.get("evidence_kind") != "non_synthetic_external_baseline_run":
        blockers.append("fair baseline run packet evidence kind mismatch")
    unsupported_fields = sorted(set(packet) - PACKET_ALLOWED_FIELDS)
    if unsupported_fields:
        blockers.append(
            "fair baseline run packet has unsupported fields: " + ", ".join(unsupported_fields)
        )
    if packet.get("recovered_after_tmp_loss") is not False:
        blockers.append("fair baseline run packet cannot rely on lost /tmp artifacts")

    _validate_claim_boundary(packet, blockers)
    _validate_run_environment(packet, blockers)
    _validate_source_lock(packet, blockers)
    run_by_baseline = _validate_baseline_runs(
        packet,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    _validate_human_answer_adjudication(packet, run_by_baseline, blockers)
    _validate_graph_quality(packet, run_by_baseline, blockers)
    _validate_permission_probes(packet, run_by_baseline, blockers)
    return sorted(set(blockers))


def build_report(
    packet: dict[str, Any] | None = None,
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    packet = load_input_packet() if packet is None else packet
    blockers = validate_packet(packet, allow_test_artifacts=allow_test_artifacts)
    baseline_runs = packet.get("baseline_runs", []) if isinstance(packet, dict) else []
    report = {
        "artifact_id": "fair_external_baseline_run_validator_recovery_v1",
        "input_packet": "inputs/fair_external_baseline_run_packet.json",
        "passed": not blockers,
        "blockers": blockers,
        "metrics": {
            "baseline_run_count": len(baseline_runs) if isinstance(baseline_runs, list) else 0,
            "required_baseline_count": len(REQUIRED_BASELINES),
            "human_answer_adjudication_present": isinstance(
                packet.get("human_answer_adjudication"), dict
            )
            if isinstance(packet, dict)
            else False,
            "graph_quality_validation_present": isinstance(
                packet.get("graph_quality_validation"), dict
            )
            if isinstance(packet, dict)
            else False,
            "permission_probe_count": len(packet.get("permission_probes", []))
            if isinstance(packet, dict) and isinstance(packet.get("permission_probes"), list)
            else 0,
            "source_lock_bound": packet.get("source_lock_sha256")
            == literature.required_baseline_source_lock_sha256()
            if isinstance(packet, dict)
            else False,
            "run_artifact_content_validation_required": True,
        },
        "claim_boundary": {
            "supports_fair_external_baseline_comparison_claim": not blockers,
            "supports_real_package_execution_claim": not blockers,
            "supports_human_adjudicated_answer_quality_claim": not blockers,
            "supports_graph_quality_validation_claim": not blockers,
            "supports_permission_probe_claim": not blockers,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }
    if packet:
        report["packet_sha256"] = sha256_json(packet)
    return report


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "fair_external_baseline_run_validator.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
