#!/usr/bin/env python3
"""Focused fair-baseline config policy validator.

This is the durable recovery harness for the KG evaluation spike. It covers the
Raman finding that config artifacts must be parsed and bound to the policy row,
not merely checked for file existence and SHA256.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

REQUIRED_BASELINES = ("microsoft_graphrag", "lightrag", "hipporag")
HEX64_CHARS = set("0123456789abcdef")

REQUIRED_CONFIG_POLICY_FLAGS = (
    "same_corpus_and_prompts_for_all_baselines",
    "same_access_policy_for_all_baselines",
    "same_completion_model_or_budget_policy",
    "same_embedding_model_or_budget_policy",
    "same_index_refresh_policy",
    "same_context_window_or_token_budget",
    "selective_prompt_omission_forbidden",
)

REQUIRED_PER_BASELINE_HASH_FIELDS = (
    "prompt_template_sha256",
    "chunking_policy_sha256",
    "parser_policy_sha256",
    "retrieval_policy_sha256",
    "rerank_policy_sha256",
    "graph_builder_config_sha256",
    "ontology_mapping_config_sha256",
)

EQUALIZED_PER_BASELINE_HASH_FIELDS = (
    "prompt_template_sha256",
    "chunking_policy_sha256",
    "parser_policy_sha256",
    "retrieval_policy_sha256",
    "rerank_policy_sha256",
    "ontology_mapping_config_sha256",
)

CONFIG_ARTIFACT_POLICY_FIELDS = (
    "package_version",
    "package_source_commit_or_release",
    "model_budget_sha256",
    "embedding_budget_sha256",
    "context_window_tokens",
    "retrieval_top_k",
    "index_refresh_policy_id",
    "prompt_count",
    "handicapped_for_comparison",
    *REQUIRED_PER_BASELINE_HASH_FIELDS,
)

CONFIG_ARTIFACT_ALLOWED_FIELDS = {
    "artifact_type",
    "baseline_id",
    "config_role",
    "policy_config_fields_sha256",
    *CONFIG_ARTIFACT_POLICY_FIELDS,
}

CONFIG_ARTIFACT_SPECS = {
    "config_artifact": (
        "config_artifact_sha256",
        "effective",
        "fair_baseline_effective_config_v1",
    ),
    "package_default_config_artifact": (
        "package_default_config_sha256",
        "official default",
        "fair_baseline_package_default_config_v1",
    ),
    "equalized_tuning_artifact": (
        "equalized_tuning_artifact_sha256",
        "equalized tuning",
        "fair_baseline_equalized_tuning_config_v1",
    ),
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


def baseline_ids_match(value: object) -> bool:
    return isinstance(value, list) and sorted(value) == sorted(REQUIRED_BASELINES)


def safe_relative_artifact_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if value.startswith(("/", "\\", "file://", "s3://", "gs://", "object://")):
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return None
    if not path.parts or path.parts[0] not in {"results", "inputs"}:
        return None
    candidate = (ROOT / path).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return candidate


def artifact_matches_sha256(path_value: object, digest_value: object) -> bool:
    path = safe_relative_artifact_path(path_value)
    return (
        path is not None
        and strong_hex64(digest_value)
        and path.exists()
        and sha256_file(path) == digest_value
    )


def load_artifact_dict(path_value: object) -> dict[str, Any]:
    path = safe_relative_artifact_path(path_value)
    if path is None or not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def policy_config_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in CONFIG_ARTIFACT_POLICY_FIELDS}


def config_artifact_content_blockers(
    baseline_id: str,
    row: dict[str, Any],
    artifact_field: str,
) -> list[str]:
    digest_field, role, artifact_type = CONFIG_ARTIFACT_SPECS[artifact_field]
    blockers: list[str] = []
    if not artifact_matches_sha256(row.get(artifact_field), row.get(digest_field)):
        blockers.append(f"{baseline_id} {role} config artifact missing or hash mismatch")
        return blockers

    payload = load_artifact_dict(row.get(artifact_field))
    if payload.get("artifact_type") != artifact_type:
        blockers.append(f"{baseline_id} {role} config artifact type mismatch")
    if payload.get("baseline_id") != baseline_id:
        blockers.append(f"{baseline_id} {role} config artifact baseline mismatch")
    if payload.get("config_role") != role:
        blockers.append(f"{baseline_id} {role} config artifact role mismatch")

    unsupported_fields = sorted(set(payload) - CONFIG_ARTIFACT_ALLOWED_FIELDS)
    if unsupported_fields:
        blockers.append(
            f"{baseline_id} {role} config artifact has unsupported fields: "
            + ", ".join(unsupported_fields)
        )

    expected_fields = policy_config_fields(row)
    if payload.get("policy_config_fields_sha256") != sha256_json(expected_fields):
        blockers.append(f"{baseline_id} {role} config artifact policy field digest mismatch")
    for field, expected_value in expected_fields.items():
        if field not in payload:
            blockers.append(f"{baseline_id} {role} config artifact missing field: {field}")
        elif payload.get(field) != expected_value:
            blockers.append(f"{baseline_id} {role} config artifact field mismatch: {field}")
    return blockers


def baseline_config_fairness_policy_status(
    validator: dict[str, Any],
    prompt_count: int,
) -> dict[str, Any]:
    policy = validator.get("baseline_config_fairness_policy")
    blockers: list[str] = []
    if not isinstance(policy, dict):
        return {
            "passed": False,
            "blockers": ["fair baseline config fairness policy missing"],
            "policy_id": None,
        }

    policy_artifact = policy.get("policy_artifact")
    policy_artifact_sha256 = policy.get("policy_artifact_sha256")
    artifact_valid = artifact_matches_sha256(policy_artifact, policy_artifact_sha256)
    if not artifact_valid:
        blockers.append("fair baseline config fairness policy artifact missing or hash mismatch")

    artifact_policy = load_artifact_dict(policy_artifact)
    if artifact_valid and artifact_policy:
        for key in ("policy_id", "baseline_ids"):
            if artifact_policy.get(key) != policy.get(key):
                blockers.append(f"fair baseline config fairness policy summary mismatch: {key}")
        policy_payload = artifact_policy
    else:
        policy_payload = policy

    if policy_payload.get("artifact_type") != "fair_baseline_config_fairness_policy_v1":
        blockers.append("fair baseline config fairness policy artifact type mismatch")
    if not isinstance(policy_payload.get("policy_id"), str) or not policy_payload["policy_id"]:
        blockers.append("fair baseline config fairness policy id missing")
    if not baseline_ids_match(policy_payload.get("baseline_ids")):
        blockers.append("fair baseline config fairness policy baseline ids mismatch")
    for flag in REQUIRED_CONFIG_POLICY_FLAGS:
        if policy_payload.get(flag) is not True:
            blockers.append(f"fair baseline config fairness policy missing flag: {flag}")

    per_baseline = policy_payload.get("per_baseline_configs")
    if not isinstance(per_baseline, dict):
        blockers.append("fair baseline config fairness policy per-baseline configs missing")
        per_baseline = {}
    if set(per_baseline) != set(REQUIRED_BASELINES):
        blockers.append("fair baseline config fairness policy per-baseline coverage mismatch")

    model_budget_hashes: set[str] = set()
    embedding_budget_hashes: set[str] = set()
    context_windows: set[int] = set()
    index_refresh_policies: set[str] = set()
    retrieval_top_ks: set[int] = set()
    equalized_hashes_by_field: dict[str, set[str]] = {
        field: set() for field in EQUALIZED_PER_BASELINE_HASH_FIELDS
    }

    for baseline_id in REQUIRED_BASELINES:
        row = per_baseline.get(baseline_id)
        if not isinstance(row, dict):
            blockers.append(f"{baseline_id} fair baseline config row missing")
            continue

        config_source = row.get("config_source")
        if config_source not in {"official_default", "declared_tuned_equalized"}:
            blockers.append(f"{baseline_id} config source is not official/default or declared equalized tuning")

        blockers.extend(config_artifact_content_blockers(baseline_id, row, "config_artifact"))
        if config_source == "official_default":
            blockers.extend(
                config_artifact_content_blockers(
                    baseline_id,
                    row,
                    "package_default_config_artifact",
                )
            )
        if config_source == "declared_tuned_equalized":
            blockers.extend(
                config_artifact_content_blockers(
                    baseline_id,
                    row,
                    "equalized_tuning_artifact",
                )
            )

        for key in ("package_version", "package_source_commit_or_release"):
            if not isinstance(row.get(key), str) or not row[key]:
                blockers.append(f"{baseline_id} {key} missing")
        if row.get("handicapped_for_comparison") is not False:
            blockers.append(f"{baseline_id} config is marked or shaped as handicapped")
        if row.get("prompt_count") != prompt_count:
            blockers.append(f"{baseline_id} prompt count does not match locked prompt set")

        for key, target in (
            ("model_budget_sha256", model_budget_hashes),
            ("embedding_budget_sha256", embedding_budget_hashes),
        ):
            value = row.get(key)
            if not strong_hex64(value):
                blockers.append(f"{baseline_id} {key} missing or weak")
            else:
                target.add(value)

        context_window = row.get("context_window_tokens")
        if not isinstance(context_window, int) or isinstance(context_window, bool) or context_window <= 0:
            blockers.append(f"{baseline_id} context window token budget missing")
        else:
            context_windows.add(context_window)

        retrieval_top_k = row.get("retrieval_top_k")
        if not isinstance(retrieval_top_k, int) or isinstance(retrieval_top_k, bool) or retrieval_top_k <= 0:
            blockers.append(f"{baseline_id} retrieval top-k missing")
        else:
            retrieval_top_ks.add(retrieval_top_k)

        index_refresh_policy = row.get("index_refresh_policy_id")
        if not isinstance(index_refresh_policy, str) or not index_refresh_policy:
            blockers.append(f"{baseline_id} index refresh policy missing")
        else:
            index_refresh_policies.add(index_refresh_policy)

        for field in REQUIRED_PER_BASELINE_HASH_FIELDS:
            value = row.get(field)
            if not strong_hex64(value):
                blockers.append(f"{baseline_id} {field} missing or weak")
            elif field in equalized_hashes_by_field:
                equalized_hashes_by_field[field].add(value)

    if len(model_budget_hashes) != 1:
        blockers.append("fair baseline completion model budget is not equalized")
    if len(embedding_budget_hashes) != 1:
        blockers.append("fair baseline embedding budget is not equalized")
    if len(context_windows) != 1:
        blockers.append("fair baseline context window budget is not equalized")
    if len(index_refresh_policies) != 1:
        blockers.append("fair baseline index refresh policy is not equalized")
    if len(retrieval_top_ks) != 1:
        blockers.append("fair baseline retrieval top-k is not equalized")
    for field, values in equalized_hashes_by_field.items():
        if len(values) != 1:
            blockers.append(f"fair baseline {field} is not equalized")

    return {
        "passed": not blockers,
        "blockers": sorted(set(blockers)),
        "policy_id": policy_payload.get("policy_id"),
        "policy_artifact": policy_artifact,
        "policy_artifact_sha256": policy_artifact_sha256,
    }


def build_report() -> dict[str, Any]:
    validator_path = RESULTS / "external_baseline_run_validator.json"
    validator = {}
    if validator_path.exists():
        loaded = json.loads(validator_path.read_text(encoding="utf-8"))
        validator = loaded if isinstance(loaded, dict) else {}
    prompt_count = int(validator.get("metrics", {}).get("prompt_count") or 4)
    status = baseline_config_fairness_policy_status(validator, prompt_count)
    return {
        "artifact_id": "external_baseline_coverage_matrix_recovery_v1",
        "baseline_config_fairness_policy": status,
        "metrics": {
            "baseline_config_fairness_policy_passed": status["passed"],
        },
        "claim_boundary": {
            "supports_fair_external_baseline_comparison_claim": False,
            "supports_fair_protocol_coverage_requirements_claim": status["passed"],
        },
        "blockers_for_fair_baseline": status["blockers"],
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "external_baseline_coverage_matrix.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
