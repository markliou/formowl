#!/usr/bin/env python3
"""Production adapter path evidence intake validator.

This validator backs the broad ``production_adapter_paths`` gate. It accepts
only a supplied ``inputs/production_adapter_evidence_packet.json`` packet.
Synthetic control fixtures remain useful for guard testing, but they do not
count as non-synthetic production adapter path evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import llm_subagent_adjudication as llm_panel
import public_reproducible_evidence as public_evidence


ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
RESULTS = ROOT / "results"
PACKET_PATH = INPUTS / "production_adapter_evidence_packet.json"
REAL_ARTIFACT_ROOT = "inputs/production_adapter_real"
REAL_ARTIFACT_ROOT_PATH = ROOT / REAL_ARTIFACT_ROOT
REAL_ARTIFACT_ROOT_PARTS = tuple(Path(REAL_ARTIFACT_ROOT).parts)

HEX64_CHARS = set("0123456789abcdef")
REQUIRED_COMPONENTS = (
    "postgres_metadata_store",
    "pgvector_index",
    "retrieval_gateway",
    "semantic_gateway",
    "rapidfuzz_candidate_adapter",
    "splink_candidate_adapter",
    "wiki_projection_adapter",
)
REQUIRED_AUDIT_ACTIONS = (
    "deploy_started",
    "migration_applied",
    "grant_check_before_content",
    "revoked_grant_blocks_content",
    "private_candidate_redacted",
    "entity_match_without_grant_denied",
    "raw_asset_read_guard_rejected",
    "canonical_merge_guard_rejected",
    "wiki_projection_draft_not_published",
    "rollback_smoke_completed",
    "deploy_completed",
)
EXPECTED_AUDIT_DECISIONS = {
    "deploy_started": "allow",
    "migration_applied": "allow",
    "grant_check_before_content": "allow",
    "revoked_grant_blocks_content": "deny",
    "private_candidate_redacted": "deny",
    "entity_match_without_grant_denied": "deny",
    "raw_asset_read_guard_rejected": "deny",
    "canonical_merge_guard_rejected": "deny",
    "wiki_projection_draft_not_published": "allow",
    "rollback_smoke_completed": "allow",
    "deploy_completed": "allow",
}
FALSE_MERGE_ADAPTERS = ("rapidfuzz_candidate_adapter", "splink_candidate_adapter")
FORBIDDEN_RAW_PREFIXES = (
    "/",
    "\\",
    "file://",
    "s3://",
    "gs://",
    "object://",
    "nas://",
    "smb://",
    "nfs://",
    "webdav://",
    "minio://",
    "postgres://",
    "postgresql://",
    "jdbc:",
    "redis://",
    "mongodb://",
    "mysql://",
    "mssql://",
)
FORBIDDEN_RAW_SCHEMES = {
    "file",
    "s3",
    "gs",
    "object",
    "nas",
    "smb",
    "nfs",
    "webdav",
    "minio",
    "postgres",
    "postgresql",
    "jdbc",
    "redis",
    "mongodb",
    "mysql",
    "mssql",
}

PACKET_ALLOWED_FIELDS = {
    "artifact_id",
    "evidence_kind",
    "recovered_after_tmp_loss",
    "deployment_manifest_artifact",
    "deployment_manifest_artifact_sha256",
    "adapter_artifacts",
    "human_false_merge_label_artifact",
    "human_false_merge_label_artifact_sha256",
    "llm_subagent_adjudication_artifact",
    "llm_subagent_adjudication_artifact_sha256",
    "audit_trail_artifact",
    "audit_trail_artifact_sha256",
    "permission_probe_artifact",
    "permission_probe_artifact_sha256",
    "rollback_smoke_artifact",
    "rollback_smoke_artifact_sha256",
    "claim_boundary",
    *public_evidence.PACKET_FIELDS,
}
CLAIM_BOUNDARY_ALLOWED_FIELDS = {
    "supports_production_adapter_paths_claim",
    "supports_non_synthetic_deployment_claim",
    "supports_human_reviewed_false_merge_labels_claim",
    "supports_llm_subagent_deployment_approval_claim",
    "supports_llm_subagent_reviewed_false_merge_labels_claim",
    "supports_permission_probe_claim",
    "supports_rollback_smoke_claim",
    "supports_full_product_production_ready_claim",
    "supports_top_tier_scientific_validation_claim",
    "supports_canonical_write_claim",
    "supports_raw_access_claim",
    public_evidence.CLAIM_FIELD,
}
ARTIFACT_REF_ALLOWED_FIELDS = {
    "component_id",
    "artifact",
    "artifact_sha256",
}
DEPLOYMENT_MANIFEST_ALLOWED_FIELDS = {
    "artifact_type",
    "deployment_id",
    "environment_id",
    "non_synthetic_deployment",
    "synthetic_or_demo",
    "release_artifact_sha256",
    "container_image_digest_sha256",
    "migration_manifest_sha256",
    "adapter_stack_sha256",
    "deployment_approved_by_human",
    "deployment_approved_by_llm_subagent_panel",
    "raw_path_exposed",
}
ADAPTER_ARTIFACT_ALLOWED_FIELDS = {
    "artifact_type",
    "component_id",
    "component_kind",
    "deployment_id",
    "non_synthetic_deployment",
    "synthetic_or_demo",
    "package_or_image_sha256",
    "config_sha256",
    "policy_sha256",
    "permission_filter_enabled",
    "raw_path_exposed",
    "canonical_write_enabled",
}
FALSE_MERGE_LABEL_ARTIFACT_ALLOWED_FIELDS = {
    "artifact_type",
    "completed",
    "reviewer_type",
    "llm_subagent_panel_reviewed",
    "synthetic_or_agent_generated",
    "deployment_id",
    "rows",
}
FALSE_MERGE_LABEL_ROW_ALLOWED_FIELDS = {
    "label_id",
    "adapter_component_id",
    "candidate_pair_id",
    "human_reviewer_id",
    "llm_subagent_panel_id",
    "reviewer_type",
    "human_reviewed",
    "llm_subagent_reviewed",
    "false_merge_label",
    "candidate_pair_sha256",
    "source_candidate_sha256s",
    "row_sha256",
}
AUDIT_TRAIL_ALLOWED_FIELDS = {
    "artifact_type",
    "deployment_id",
    "policy_id",
    "rows",
}
AUDIT_ROW_ALLOWED_FIELDS = {
    "event_id",
    "sequence",
    "action",
    "deployment_id",
    "request_id",
    "actor_id",
    "resource_ref",
    "policy_id",
    "decision",
    "grant_state",
    "denial_reason",
    "published",
    "rollback_verified",
    "event_sha256",
    "row_sha256",
}
PERMISSION_PROBE_ALLOWED_FIELDS = {
    "artifact_type",
    "completed",
    "deployment_id",
    "component_ids",
    "revoked_grant_content_denied",
    "private_content_not_returned",
    "raw_asset_access_denied",
    "entity_match_does_not_grant_access",
    "canonical_merge_without_review_denied",
    "private_leak_count",
    "raw_asset_access_count",
    "entity_match_access_count",
    "canonical_write_count",
}
ROLLBACK_SMOKE_ALLOWED_FIELDS = {
    "artifact_type",
    "completed",
    "deployment_id",
    "non_synthetic_deployment",
    "migration_rollback_verified",
    "partial_failure_rollback_verified",
    "audit_append_only_verified",
    "idempotent_retry_verified",
    "rollback_run_sha256",
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


def row_hash(row: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in row.items() if key != "row_sha256"})


def with_row_hash(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["row_sha256"] = row_hash(payload)
    return payload


def adapter_stack_digest(
    component_artifacts: dict[str, dict[str, Any]],
    component_artifact_hashes: dict[str, str],
) -> str:
    rows = []
    for component_id in sorted(component_artifacts):
        artifact = component_artifacts[component_id]
        rows.append(
            {
                "component_id": component_id,
                "artifact_sha256": component_artifact_hashes.get(component_id),
                "package_or_image_sha256": artifact.get("package_or_image_sha256"),
                "config_sha256": artifact.get("config_sha256"),
                "policy_sha256": artifact.get("policy_sha256"),
            }
        )
    return sha256_json(rows)


def raw_source_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    if len(stripped) >= 3 and stripped[1:3] in {":\\", ":/"}:
        return True
    lowered = stripped.lower()
    if lowered.startswith(FORBIDDEN_RAW_PREFIXES):
        return True
    if ":" not in lowered:
        return False
    scheme = lowered.split(":", 1)[0]
    base_scheme = scheme.split("+", 1)[0]
    return scheme in FORBIDDEN_RAW_SCHEMES or base_scheme in FORBIDDEN_RAW_SCHEMES


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
    if raw_source_value(value):
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
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def load_input_packet() -> dict[str, Any]:
    if PACKET_PATH.is_symlink():
        return {"__input_packet_error": ("production adapter evidence packet symlink not accepted")}
    if not PACKET_PATH.exists():
        return {}
    if not PACKET_PATH.is_file():
        return {"__input_packet_error": "production adapter evidence packet is not a file"}
    if PACKET_PATH.stat().st_nlink > 1:
        return {
            "__input_packet_error": (
                "production adapter evidence packet hardlink alias not accepted"
            )
        }
    loaded = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _reject_unsupported_fields(
    artifact: dict[str, Any],
    allowed_fields: set[str],
    label: str,
    blockers: list[str],
) -> None:
    unsupported = sorted(set(artifact) - allowed_fields)
    if unsupported:
        blockers.append(f"{label} has unsupported fields: " + ", ".join(unsupported))
    for field, value in artifact.items():
        if raw_source_value(value):
            blockers.append(f"{label} contains raw/internal value: {field}")


def _load_required_artifact(
    packet: dict[str, Any],
    artifact_field: str,
    expected_type: str,
    allowed_fields: set[str],
    blockers: list[str],
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    digest_field = f"{artifact_field}_sha256"
    path_blocker = artifact_path_rejection_reason(
        packet.get(artifact_field),
        allow_test_artifacts=allow_test_artifacts,
    )
    if path_blocker:
        if path_blocker == "path missing or malformed":
            blockers.append(f"{artifact_field} missing or hash mismatch")
        else:
            blockers.append(f"{artifact_field} {path_blocker}")
        return {}
    if not artifact_matches_sha256(
        packet.get(artifact_field),
        packet.get(digest_field),
        allow_test_artifacts=allow_test_artifacts,
    ):
        blockers.append(f"{artifact_field} missing or hash mismatch")
        return {}
    artifact = load_artifact(
        packet.get(artifact_field),
        packet.get(digest_field),
        allow_test_artifacts=allow_test_artifacts,
    )
    _reject_unsupported_fields(artifact, allowed_fields, artifact_field, blockers)
    if artifact.get("artifact_type") != expected_type:
        blockers.append(f"{artifact_field} artifact type mismatch")
    return artifact


def _validate_claim_boundary(
    packet: dict[str, Any], blockers: list[str], *, llm_route: bool
) -> None:
    claims = packet.get("claim_boundary")
    if not isinstance(claims, dict):
        blockers.append("production adapter packet claim boundary missing")
        claims = {}
    _reject_unsupported_fields(
        claims,
        CLAIM_BOUNDARY_ALLOWED_FIELDS,
        "production adapter packet claim boundary",
        blockers,
    )
    for flag in (
        "supports_production_adapter_paths_claim",
        "supports_non_synthetic_deployment_claim",
        "supports_permission_probe_claim",
        "supports_rollback_smoke_claim",
    ):
        if claims.get(flag) is not True:
            blockers.append(f"production adapter packet missing claim: {flag}")
    if llm_route:
        for flag in (
            "supports_llm_subagent_deployment_approval_claim",
            "supports_llm_subagent_reviewed_false_merge_labels_claim",
        ):
            if claims.get(flag) is not True:
                blockers.append(f"production adapter packet missing claim: {flag}")
        if claims.get("supports_human_reviewed_false_merge_labels_claim") is not False:
            blockers.append(
                "production adapter packet must not claim human-reviewed false-merge labels "
                "when using LLM subagent adjudication"
            )
    else:
        if claims.get("supports_human_reviewed_false_merge_labels_claim") is not True:
            blockers.append(
                "production adapter packet missing claim: "
                "supports_human_reviewed_false_merge_labels_claim"
            )
        for flag in (
            "supports_llm_subagent_deployment_approval_claim",
            "supports_llm_subagent_reviewed_false_merge_labels_claim",
        ):
            if claims.get(flag) not in {None, False}:
                blockers.append(f"production adapter packet overclaims unsupported claim: {flag}")
    for flag in (
        "supports_full_product_production_ready_claim",
        "supports_top_tier_scientific_validation_claim",
        "supports_canonical_write_claim",
        "supports_raw_access_claim",
    ):
        if claims.get(flag) is not False:
            blockers.append(f"production adapter packet overclaims unsupported claim: {flag}")


def _validate_deployment_manifest(
    manifest: dict[str, Any], blockers: list[str], *, llm_route: bool
) -> str | None:
    if manifest.get("non_synthetic_deployment") is not True:
        blockers.append("production adapter deployment manifest is not non-synthetic")
    if manifest.get("synthetic_or_demo") is not False:
        blockers.append("production adapter deployment manifest is synthetic or demo")
    if llm_route:
        if manifest.get("deployment_approved_by_llm_subagent_panel") is not True:
            blockers.append("production adapter deployment is not LLM subagent approved")
        if manifest.get("deployment_approved_by_human") is True:
            blockers.append(
                "production adapter deployment must not claim human approval "
                "when using LLM subagent approval"
            )
    elif manifest.get("deployment_approved_by_human") is not True:
        blockers.append("production adapter deployment is not human approved")
    if manifest.get("raw_path_exposed") is not False:
        blockers.append("production adapter deployment exposes raw paths")
    deployment_id = manifest.get("deployment_id")
    if not isinstance(deployment_id, str) or not deployment_id:
        blockers.append("production adapter deployment id missing")
        deployment_id = None
    if not isinstance(manifest.get("environment_id"), str) or not manifest["environment_id"]:
        blockers.append("production adapter environment id missing")
    for field in (
        "release_artifact_sha256",
        "container_image_digest_sha256",
        "migration_manifest_sha256",
        "adapter_stack_sha256",
    ):
        if not strong_hex64(manifest.get(field)):
            blockers.append(f"production adapter deployment manifest {field} missing or weak")
    return deployment_id


def _validate_adapter_artifacts(
    packet: dict[str, Any],
    deployment_id: str | None,
    blockers: list[str],
    *,
    allow_test_artifacts: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    refs = packet.get("adapter_artifacts")
    if not isinstance(refs, list) or not refs:
        blockers.append("production adapter component artifacts missing")
        refs = []
    by_component: dict[str, dict[str, Any]] = {}
    artifact_hashes: dict[str, str] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            blockers.append("production adapter artifact reference malformed")
            continue
        _reject_unsupported_fields(
            ref,
            ARTIFACT_REF_ALLOWED_FIELDS,
            "production adapter artifact reference",
            blockers,
        )
        path_blocker = artifact_path_rejection_reason(
            ref.get("artifact"),
            allow_test_artifacts=allow_test_artifacts,
        )
        if path_blocker:
            if path_blocker == "path missing or malformed":
                blockers.append("production adapter component artifact missing or hash mismatch")
            else:
                blockers.append(f"production adapter component artifact {path_blocker}")
            continue
        if not artifact_matches_sha256(
            ref.get("artifact"),
            ref.get("artifact_sha256"),
            allow_test_artifacts=allow_test_artifacts,
        ):
            blockers.append("production adapter component artifact missing or hash mismatch")
            continue
        artifact = load_artifact(
            ref.get("artifact"),
            ref.get("artifact_sha256"),
            allow_test_artifacts=allow_test_artifacts,
        )
        _reject_unsupported_fields(
            artifact,
            ADAPTER_ARTIFACT_ALLOWED_FIELDS,
            "production adapter component artifact",
            blockers,
        )
        if artifact.get("artifact_type") != "production_adapter_component_artifact_v1":
            blockers.append("production adapter component artifact type mismatch")
        component_id = artifact.get("component_id")
        if ref.get("component_id") != component_id:
            blockers.append("production adapter component reference mismatch")
        if component_id not in REQUIRED_COMPONENTS:
            blockers.append(f"unexpected production adapter component id: {component_id}")
            continue
        if component_id in by_component:
            blockers.append(f"duplicate production adapter component artifact: {component_id}")
        by_component[component_id] = artifact
        artifact_hashes[component_id] = ref["artifact_sha256"]
        if artifact.get("deployment_id") != deployment_id:
            blockers.append(f"{component_id} deployment binding mismatch")
        if artifact.get("non_synthetic_deployment") is not True:
            blockers.append(f"{component_id} is not marked non-synthetic")
        if artifact.get("synthetic_or_demo") is not False:
            blockers.append(f"{component_id} is synthetic or demo")
        if artifact.get("permission_filter_enabled") is not True:
            blockers.append(f"{component_id} permission filter is not enabled")
        if artifact.get("raw_path_exposed") is not False:
            blockers.append(f"{component_id} exposes raw path")
        if artifact.get("canonical_write_enabled") is not False:
            blockers.append(f"{component_id} enables canonical writes")
        for field in ("package_or_image_sha256", "config_sha256", "policy_sha256"):
            if not strong_hex64(artifact.get(field)):
                blockers.append(f"{component_id} {field} missing or weak")
    missing = sorted(set(REQUIRED_COMPONENTS) - set(by_component))
    if missing:
        blockers.append(
            "production adapter component artifacts missing components: " + ", ".join(missing)
        )
    return by_component, artifact_hashes


def _validate_false_merge_labels(
    artifact: dict[str, Any],
    deployment_id: str | None,
    blockers: list[str],
    *,
    llm_route: bool,
) -> None:
    if artifact.get("completed") is not True:
        blockers.append("production adapter false-merge label review is not complete")
    if llm_route:
        if artifact.get("reviewer_type") != "four_specialist_llm_subagent_panel":
            blockers.append("production adapter false-merge reviewer is not LLM subagent panel")
        if artifact.get("llm_subagent_panel_reviewed") is not True:
            blockers.append("production adapter false-merge labels are not LLM subagent reviewed")
    elif artifact.get("reviewer_type") != "human":
        blockers.append("production adapter false-merge reviewer is not human")
    if artifact.get("synthetic_or_agent_generated") is not False:
        blockers.append("production adapter false-merge labels are synthetic or agent-generated")
    if artifact.get("deployment_id") != deployment_id:
        blockers.append("production adapter false-merge labels deployment binding mismatch")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or not rows:
        blockers.append("production adapter false-merge label rows missing")
        rows = []
    adapters_with_false_merge: set[str] = set()
    label_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("production adapter false-merge label row hash mismatch")
            continue
        _reject_unsupported_fields(
            row,
            FALSE_MERGE_LABEL_ROW_ALLOWED_FIELDS,
            "production adapter false-merge label row",
            blockers,
        )
        label_id = row.get("label_id")
        if not isinstance(label_id, str) or not label_id:
            blockers.append("production adapter false-merge label id missing")
        elif label_id in label_ids:
            blockers.append("duplicate production adapter false-merge label id")
        else:
            label_ids.add(label_id)
        adapter_id = row.get("adapter_component_id")
        if adapter_id not in FALSE_MERGE_ADAPTERS:
            blockers.append("production adapter false-merge label adapter unsupported")
        if llm_route:
            if row.get("human_reviewed") not in {None, False}:
                blockers.append(
                    "production adapter false-merge row must not claim human review " "on LLM route"
                )
            human_reviewer_id = row.get("human_reviewer_id")
            if isinstance(human_reviewer_id, str) and human_reviewer_id:
                blockers.append(
                    "production adapter false-merge row must not retain a human reviewer id "
                    "on LLM route"
                )
            if (
                row.get("reviewer_type") != "four_specialist_llm_subagent_panel"
                or row.get("llm_subagent_reviewed") is not True
            ):
                blockers.append("production adapter false-merge row is not LLM subagent reviewed")
            if (
                not isinstance(row.get("llm_subagent_panel_id"), str)
                or not row["llm_subagent_panel_id"]
            ):
                blockers.append("production adapter false-merge LLM panel id missing")
        elif row.get("reviewer_type") != "human" or row.get("human_reviewed") is not True:
            blockers.append("production adapter false-merge row is not human reviewed")
        if row.get("false_merge_label") is True:
            adapters_with_false_merge.add(adapter_id)
        if not llm_route and (
            not isinstance(row.get("human_reviewer_id"), str) or not row["human_reviewer_id"]
        ):
            blockers.append("production adapter false-merge human reviewer id missing")
        if not strong_hex64(row.get("candidate_pair_sha256")):
            blockers.append("production adapter false-merge candidate pair hash missing")
        source_hashes = row.get("source_candidate_sha256s")
        if (
            not isinstance(source_hashes, list)
            or len(source_hashes) != 2
            or not all(strong_hex64(v) for v in source_hashes)
        ):
            blockers.append("production adapter false-merge source candidate hashes missing")
    missing = sorted(set(FALSE_MERGE_ADAPTERS) - adapters_with_false_merge)
    if missing:
        blockers.append(
            "production adapter false-merge labels missing adapters: " + ", ".join(missing)
        )


def _validate_audit_trail(
    artifact: dict[str, Any],
    deployment_id: str | None,
    blockers: list[str],
) -> None:
    if artifact.get("deployment_id") != deployment_id:
        blockers.append("production adapter audit trail deployment binding mismatch")
    if not isinstance(artifact.get("policy_id"), str) or not artifact["policy_id"]:
        blockers.append("production adapter audit policy id missing")
    policy_id = artifact.get("policy_id")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or not rows:
        blockers.append("production adapter audit rows missing")
        rows = []
    actions = []
    request_ids: set[str] = set()
    resource_refs: set[str] = set()
    event_ids: set[str] = set()
    by_action: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("production adapter audit row hash mismatch")
            continue
        _reject_unsupported_fields(
            row, AUDIT_ROW_ALLOWED_FIELDS, "production adapter audit row", blockers
        )
        action = row.get("action")
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            blockers.append("production adapter audit event id missing")
        elif event_id in event_ids:
            blockers.append("duplicate production adapter audit event id")
        else:
            event_ids.add(event_id)
        actions.append(action)
        by_action[action] = row
        if action in REQUIRED_AUDIT_ACTIONS and row.get("sequence") != REQUIRED_AUDIT_ACTIONS.index(
            action
        ):
            blockers.append(f"production adapter audit row sequence mismatch: {action}")
        if isinstance(row.get("request_id"), str) and row["request_id"]:
            request_ids.add(row["request_id"])
        if isinstance(row.get("resource_ref"), str) and row["resource_ref"]:
            resource_refs.add(row["resource_ref"])
        for field in ("deployment_id", "request_id", "actor_id", "resource_ref", "policy_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                blockers.append(f"production adapter audit row {field} missing")
        if row.get("deployment_id") != deployment_id:
            blockers.append("production adapter audit row deployment mismatch")
        if isinstance(policy_id, str) and policy_id and row.get("policy_id") != policy_id:
            blockers.append("production adapter audit row policy mismatch")
        expected_decision = EXPECTED_AUDIT_DECISIONS.get(action)
        if expected_decision is not None and row.get("decision") != expected_decision:
            blockers.append(f"production adapter audit row decision mismatch: {action}")
        if not strong_hex64(row.get("event_sha256")):
            blockers.append("production adapter audit event hash missing")
    if actions != list(REQUIRED_AUDIT_ACTIONS):
        blockers.append("production adapter audit control sequence mismatch")
    if len(request_ids) != 1:
        blockers.append("production adapter audit rows do not bind one request id")
    if len(resource_refs) != 1:
        blockers.append("production adapter audit rows do not bind one resource ref")
    for action in (
        "revoked_grant_blocks_content",
        "private_candidate_redacted",
        "entity_match_without_grant_denied",
        "raw_asset_read_guard_rejected",
        "canonical_merge_guard_rejected",
    ):
        row = by_action.get(action, {})
        if row.get("decision") != "deny" or not row.get("denial_reason"):
            blockers.append(f"{action} is not an explicit deny guard")
    if by_action.get("revoked_grant_blocks_content", {}).get("grant_state") != "revoked":
        blockers.append("production adapter revoked grant audit row does not bind revoked state")
    if by_action.get("wiki_projection_draft_not_published", {}).get("published") is not False:
        blockers.append("production adapter wiki projection did not remain draft-only")
    if by_action.get("rollback_smoke_completed", {}).get("rollback_verified") is not True:
        blockers.append("production adapter rollback smoke audit event missing")


def _validate_permission_probe(
    artifact: dict[str, Any],
    deployment_id: str | None,
    blockers: list[str],
) -> None:
    if artifact.get("completed") is not True:
        blockers.append("production adapter permission probe is not complete")
    if artifact.get("deployment_id") != deployment_id:
        blockers.append("production adapter permission probe deployment binding mismatch")
    if artifact.get("component_ids") != sorted(REQUIRED_COMPONENTS):
        blockers.append("production adapter permission probe component coverage mismatch")
    for flag in (
        "revoked_grant_content_denied",
        "private_content_not_returned",
        "raw_asset_access_denied",
        "entity_match_does_not_grant_access",
        "canonical_merge_without_review_denied",
    ):
        if artifact.get(flag) is not True:
            blockers.append(f"production adapter permission probe failed or missing: {flag}")
    for field in (
        "private_leak_count",
        "raw_asset_access_count",
        "entity_match_access_count",
        "canonical_write_count",
    ):
        if artifact.get(field) != 0:
            blockers.append(
                f"production adapter permission probe positive leak/write count: {field}"
            )


def _validate_rollback_smoke(
    artifact: dict[str, Any],
    deployment_id: str | None,
    blockers: list[str],
) -> None:
    if artifact.get("completed") is not True:
        blockers.append("production adapter rollback smoke is not complete")
    if artifact.get("deployment_id") != deployment_id:
        blockers.append("production adapter rollback smoke deployment binding mismatch")
    if artifact.get("non_synthetic_deployment") is not True:
        blockers.append("production adapter rollback smoke is not non-synthetic")
    for flag in (
        "migration_rollback_verified",
        "partial_failure_rollback_verified",
        "audit_append_only_verified",
        "idempotent_retry_verified",
    ):
        if artifact.get(flag) is not True:
            blockers.append(f"production adapter rollback smoke missing verification: {flag}")
    if not strong_hex64(artifact.get("rollback_run_sha256")):
        blockers.append("production adapter rollback smoke run hash missing")


def _load_llm_panel_artifact(
    packet: dict[str, Any],
    blockers: list[str],
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    path_blocker = artifact_path_rejection_reason(
        packet.get("llm_subagent_adjudication_artifact"),
        allow_test_artifacts=allow_test_artifacts,
    )
    if path_blocker:
        if path_blocker == "path missing or malformed":
            blockers.append(
                "production adapter four-specialist LLM subagent adjudication artifact "
                "missing or hash mismatch"
            )
        else:
            blockers.append(
                "production adapter four-specialist LLM subagent adjudication artifact "
                + path_blocker
            )
        return {}
    if not artifact_matches_sha256(
        packet.get("llm_subagent_adjudication_artifact"),
        packet.get("llm_subagent_adjudication_artifact_sha256"),
        allow_test_artifacts=allow_test_artifacts,
    ):
        blockers.append(
            "production adapter four-specialist LLM subagent adjudication artifact "
            "missing or hash mismatch"
        )
        return {}
    return load_artifact(
        packet.get("llm_subagent_adjudication_artifact"),
        packet.get("llm_subagent_adjudication_artifact_sha256"),
        allow_test_artifacts=allow_test_artifacts,
    )


def _validate_llm_panel(
    packet: dict[str, Any],
    component_artifact_hashes: dict[str, str],
    blockers: list[str],
    *,
    allow_test_artifacts: bool = False,
) -> None:
    panel = _load_llm_panel_artifact(
        packet,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    expected_hashes = [
        digest
        for digest in (
            packet.get("deployment_manifest_artifact_sha256"),
            *component_artifact_hashes.values(),
            packet.get("human_false_merge_label_artifact_sha256"),
            packet.get("audit_trail_artifact_sha256"),
            packet.get("permission_probe_artifact_sha256"),
            packet.get("rollback_smoke_artifact_sha256"),
        )
        if strong_hex64(digest)
    ]
    llm_panel.validate_four_specialist_panel(
        panel,
        blockers,
        label="production adapter",
        expected_target="production_adapter_paths",
        expected_input_sha256s=expected_hashes,
    )


def _public_evidence_hashes(
    packet: dict[str, Any],
    component_artifact_hashes: dict[str, str],
) -> list[str]:
    hashes = []
    for field in (
        "deployment_manifest_artifact_sha256",
        "human_false_merge_label_artifact_sha256",
        "llm_subagent_adjudication_artifact_sha256",
        "audit_trail_artifact_sha256",
        "permission_probe_artifact_sha256",
        "rollback_smoke_artifact_sha256",
    ):
        digest = packet.get(field)
        if strong_hex64(digest):
            hashes.append(digest)
    hashes.extend(digest for digest in component_artifact_hashes.values() if strong_hex64(digest))
    return sorted(set(hashes))


def validate_packet(
    packet: dict[str, Any],
    *,
    allow_test_artifacts: bool = False,
) -> list[str]:
    blockers: list[str] = []
    if isinstance(packet.get("__input_packet_error"), str):
        return [packet["__input_packet_error"]]
    if not packet:
        return [
            "production adapter evidence packet missing",
            "non-synthetic production deployment validation is not present",
            "human or LLM-subagent-reviewed false-merge labels are not present",
            "permission probes, rollback smoke, and production audit artifacts are not present",
        ]
    llm_route = bool(packet.get("llm_subagent_adjudication_artifact"))
    _reject_unsupported_fields(
        packet, PACKET_ALLOWED_FIELDS, "production adapter evidence packet", blockers
    )
    if packet.get("artifact_id") != "production_adapter_evidence_packet_v1":
        blockers.append("production adapter evidence packet artifact id mismatch")
    if packet.get("evidence_kind") != "non_synthetic_production_adapter_validation":
        blockers.append("production adapter evidence kind mismatch")
    if packet.get("recovered_after_tmp_loss") is not False:
        blockers.append("production adapter packet cannot rely on lost /tmp artifacts")
    _validate_claim_boundary(packet, blockers, llm_route=llm_route)

    manifest = _load_required_artifact(
        packet,
        "deployment_manifest_artifact",
        "production_adapter_deployment_manifest_v1",
        DEPLOYMENT_MANIFEST_ALLOWED_FIELDS,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    labels = _load_required_artifact(
        packet,
        "human_false_merge_label_artifact",
        "production_adapter_false_merge_labels_v1",
        FALSE_MERGE_LABEL_ARTIFACT_ALLOWED_FIELDS,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    audit = _load_required_artifact(
        packet,
        "audit_trail_artifact",
        "production_adapter_audit_trail_v1",
        AUDIT_TRAIL_ALLOWED_FIELDS,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    permission_probe = _load_required_artifact(
        packet,
        "permission_probe_artifact",
        "production_adapter_permission_probe_v1",
        PERMISSION_PROBE_ALLOWED_FIELDS,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    rollback = _load_required_artifact(
        packet,
        "rollback_smoke_artifact",
        "production_adapter_rollback_smoke_v1",
        ROLLBACK_SMOKE_ALLOWED_FIELDS,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )

    deployment_id = _validate_deployment_manifest(manifest, blockers, llm_route=llm_route)
    component_artifacts, component_artifact_hashes = _validate_adapter_artifacts(
        packet,
        deployment_id,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    if set(component_artifacts) == set(REQUIRED_COMPONENTS):
        actual_stack_digest = adapter_stack_digest(component_artifacts, component_artifact_hashes)
        if manifest.get("adapter_stack_sha256") != actual_stack_digest:
            blockers.append("production adapter manifest adapter stack digest mismatch")
    _validate_false_merge_labels(labels, deployment_id, blockers, llm_route=llm_route)
    _validate_audit_trail(audit, deployment_id, blockers)
    _validate_permission_probe(permission_probe, deployment_id, blockers)
    _validate_rollback_smoke(rollback, deployment_id, blockers)
    if llm_route:
        _validate_llm_panel(
            packet,
            component_artifact_hashes,
            blockers,
            allow_test_artifacts=allow_test_artifacts,
        )
    public_evidence.validate_public_evidence_packet(
        packet,
        blockers,
        gate_id="production_adapter_paths",
        artifact_path_rejection_reason=artifact_path_rejection_reason,
        artifact_matches_sha256=artifact_matches_sha256,
        load_artifact=load_artifact,
        allow_test_artifacts=allow_test_artifacts,
        expected_artifact_sha256s=_public_evidence_hashes(packet, component_artifact_hashes),
    )
    return sorted(set(blockers))


def build_report(
    packet: dict[str, Any] | None = None,
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    packet = load_input_packet() if packet is None else packet
    blockers = validate_packet(packet, allow_test_artifacts=allow_test_artifacts)
    adapter_refs = packet.get("adapter_artifacts", []) if isinstance(packet, dict) else []
    has_llm_panel = isinstance(packet, dict) and bool(
        packet.get("llm_subagent_adjudication_artifact")
    )
    report = {
        "artifact_id": "production_adapter_path_validator_recovery_v1",
        "input_packet": "inputs/production_adapter_evidence_packet.json",
        "passed": not blockers,
        "blockers": blockers,
        "metrics": {
            "required_component_count": len(REQUIRED_COMPONENTS),
            "adapter_artifact_count": len(adapter_refs) if isinstance(adapter_refs, list) else 0,
            "deployment_manifest_present": bool(packet.get("deployment_manifest_artifact"))
            if isinstance(packet, dict)
            else False,
            "human_false_merge_label_artifact_present": bool(
                packet.get("human_false_merge_label_artifact")
            )
            if isinstance(packet, dict)
            else False,
            "llm_subagent_adjudication_present": has_llm_panel,
            "audit_trail_artifact_present": bool(packet.get("audit_trail_artifact"))
            if isinstance(packet, dict)
            else False,
            "permission_probe_artifact_present": bool(packet.get("permission_probe_artifact"))
            if isinstance(packet, dict)
            else False,
            "rollback_smoke_artifact_present": bool(packet.get("rollback_smoke_artifact"))
            if isinstance(packet, dict)
            else False,
            "evidence_source_mode": public_evidence.evidence_source_mode(packet)
            if isinstance(packet, dict)
            else public_evidence.PRIVATE_MODE,
            "public_evidence_manifest_present": bool(
                packet.get("public_evidence_manifest_artifact")
            )
            if isinstance(packet, dict)
            else False,
        },
        "claim_boundary": {
            "supports_production_adapter_paths_claim": not blockers,
            "supports_non_synthetic_deployment_claim": not blockers,
            "supports_human_reviewed_false_merge_labels_claim": (
                not blockers and not has_llm_panel
            ),
            "supports_llm_subagent_deployment_approval_claim": (not blockers and has_llm_panel),
            "supports_llm_subagent_reviewed_false_merge_labels_claim": (
                not blockers and has_llm_panel
            ),
            "supports_permission_probe_claim": not blockers,
            "supports_rollback_smoke_claim": not blockers,
            public_evidence.CLAIM_FIELD: (
                not blockers
                and public_evidence.evidence_source_mode(packet) == public_evidence.PUBLIC_MODE
            )
            if isinstance(packet, dict)
            else False,
            "supports_full_product_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_canonical_write_claim": False,
            "supports_raw_access_claim": False,
        },
    }
    if packet:
        report["packet_sha256"] = sha256_json(packet)
    return report


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "production_adapter_path_validator.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
