#!/usr/bin/env python3
"""Real enterprise multimodal validation evidence intake.

This validator is the intake gate for the broad multimodal semantic validation
objective. It accepts only a supplied
``inputs/enterprise_multimodal_validation_packet.json`` packet; deterministic
control fixtures are not counted as real enterprise pilot evidence.
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
PACKET_PATH = INPUTS / "enterprise_multimodal_validation_packet.json"
REAL_ARTIFACT_ROOT = "inputs/enterprise_multimodal_real"
REAL_ARTIFACT_ROOT_PATH = ROOT / REAL_ARTIFACT_ROOT
REAL_ARTIFACT_ROOT_PARTS = tuple(Path(REAL_ARTIFACT_ROOT).parts)

REQUIRED_MODALITIES = ("spreadsheet", "mail", "meeting_audio", "video_ocr")
HEX64_CHARS = set("0123456789abcdef")
FORBIDDEN_SOURCE_FIELDS = {
    "raw_path",
    "local_path",
    "filesystem_path",
    "nas_path",
    "storage_uri",
    "object_uri",
    "bucket",
    "object_key",
    "worker_scratch_path",
}
FORBIDDEN_RAW_SOURCE_PREFIXES = (
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
)
PACKET_ALLOWED_FIELDS = {
    "artifact_id",
    "evidence_kind",
    "recovered_after_tmp_loss",
    "pilot_manifest_artifact",
    "pilot_manifest_artifact_sha256",
    "validation_artifacts",
    "human_adjudication_artifact",
    "human_adjudication_artifact_sha256",
    "llm_subagent_adjudication_artifact",
    "llm_subagent_adjudication_artifact_sha256",
    "business_decision_review_artifact",
    "business_decision_review_artifact_sha256",
    "permission_probe_artifact",
    "permission_probe_artifact_sha256",
    "claim_boundary",
    *public_evidence.PACKET_FIELDS,
}
CLAIM_BOUNDARY_ALLOWED_FIELDS = {
    "supports_real_enterprise_multimodal_claim",
    "supports_multimodal_human_adjudication_completed_claim",
    "supports_multimodal_llm_subagent_adjudication_completed_claim",
    "supports_cross_modal_permission_probe_claim",
    "supports_business_decision_review_claim",
    "supports_financial_advice_or_autonomous_business_judgment_claim",
    "supports_production_ready_claim",
    "supports_top_tier_scientific_validation_claim",
    "supports_raw_asset_access_claim",
    public_evidence.CLAIM_FIELD,
}
SOURCE_ARTIFACT_ROW_ALLOWED_FIELDS = {
    "source_id",
    "modality",
    "asset_id",
    "asset_sha256",
    "formowl_locator",
    "permission_scope_id",
    "real_enterprise_data",
    "text_proxy_only",
    "raw_path_exposed",
    "row_sha256",
}
MANIFEST_ARTIFACT_ALLOWED_FIELDS = {
    "artifact_type",
    "real_enterprise_pilot",
    "synthetic_or_demo",
    "source_artifacts",
}
VALIDATION_ARTIFACT_ALLOWED_FIELDS = {
    "artifact_type",
    "modality",
    "rows",
}
VALIDATION_ARTIFACT_REF_ALLOWED_FIELDS = {
    "modality",
    "artifact",
    "artifact_sha256",
}
ADJUDICATION_ARTIFACT_ALLOWED_FIELDS = {
    "artifact_type",
    "completed",
    "reviewer_id",
    "reviewer_type",
    "synthetic_or_agent_generated",
    "validation_artifact_sha256s",
    "rows",
}
BUSINESS_REVIEW_ARTIFACT_ALLOWED_FIELDS = {
    "artifact_type",
    "human_reviewed",
    "llm_subagent_reviewed",
    "autonomous_business_judgment",
    "financial_advice_or_execution",
    "adjudication_artifact_sha256",
    "decision_rows",
}
BUSINESS_DECISION_ROW_ALLOWED_FIELDS = {
    "decision_candidate_id",
    "source_validation_ids",
    "requires_human_review",
    "autonomous_business_judgment",
    "row_sha256",
}
VALIDATION_ROW_ALLOWED_FIELDS = {
    "validation_id",
    "modality",
    "source_id",
    "source_asset_sha256",
    "observation_id",
    "extractor_run_id",
    "candidate_id",
    "task",
    "human_adjudicated",
    "llm_subagent_adjudicated",
    "row_sha256",
}
ADJUDICATION_ROW_ALLOWED_FIELDS = {
    "adjudication_id",
    "validation_id",
    "validation_row_sha256",
    "modality",
    "final_label",
    "row_sha256",
}
PERMISSION_PROBE_ALLOWED_FIELDS = {
    "artifact_type",
    "completed",
    "source_ids",
    "revoked_grant_content_denied",
    "private_content_not_returned",
    "raw_asset_access_denied",
    "entity_match_does_not_grant_access",
    "cross_modal_private_leak_count",
    "raw_asset_access_count",
}
PERMISSION_PROBE_FORBIDDEN_POSITIVE_COUNTS = (
    "revoked_grant_visible_count",
    "entity_match_access_count",
    "private_content_returned_count",
)


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


def raw_source_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    if len(stripped) >= 3 and stripped[1:3] in {":\\", ":/"}:
        return True
    return stripped.lower().startswith(FORBIDDEN_RAW_SOURCE_PREFIXES)


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
        return {
            "__input_packet_error": ("enterprise multimodal validation packet symlink not accepted")
        }
    if not PACKET_PATH.exists():
        return {}
    if not PACKET_PATH.is_file():
        return {"__input_packet_error": "enterprise multimodal validation packet is not a file"}
    if PACKET_PATH.stat().st_nlink > 1:
        return {
            "__input_packet_error": (
                "enterprise multimodal validation packet hardlink alias not accepted"
            )
        }
    loaded = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _load_required_artifact(
    packet: dict[str, Any],
    artifact_field: str,
    expected_type: str,
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
    if artifact.get("artifact_type") != expected_type:
        blockers.append(f"{artifact_field} artifact type mismatch")
    return artifact


def _reject_unsupported_artifact_fields(
    artifact: dict[str, Any],
    allowed_fields: set[str],
    label: str,
    blockers: list[str],
) -> None:
    unsupported_fields = sorted(set(artifact) - allowed_fields)
    if unsupported_fields:
        blockers.append(f"{label} has unsupported fields: " + ", ".join(unsupported_fields))
    for field, value in artifact.items():
        if raw_source_value(value):
            blockers.append(f"{label} contains raw/internal value: {field}")


def _validate_manifest(manifest: dict[str, Any], blockers: list[str]) -> dict[str, dict[str, Any]]:
    _reject_unsupported_artifact_fields(
        manifest,
        MANIFEST_ARTIFACT_ALLOWED_FIELDS,
        "enterprise multimodal pilot manifest",
        blockers,
    )
    if manifest.get("real_enterprise_pilot") is not True:
        blockers.append("enterprise multimodal pilot manifest is not real enterprise data")
    if manifest.get("synthetic_or_demo") is not False:
        blockers.append("enterprise multimodal pilot manifest is synthetic or demo data")
    rows = manifest.get("source_artifacts")
    if not isinstance(rows, list) or not rows:
        blockers.append("enterprise multimodal source artifacts missing")
        rows = []
    by_source: dict[str, dict[str, Any]] = {}
    modalities = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("enterprise multimodal source artifact row hash mismatch")
            continue
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            blockers.append("enterprise multimodal source id missing")
            continue
        if source_id in by_source:
            blockers.append("duplicate enterprise multimodal source id")
        by_source[source_id] = row
        unsupported_fields = sorted(set(row) - SOURCE_ARTIFACT_ROW_ALLOWED_FIELDS)
        if unsupported_fields:
            blockers.append(
                "enterprise multimodal source artifact row has unsupported fields: "
                + ", ".join(unsupported_fields)
            )
        for field, value in row.items():
            if field in FORBIDDEN_SOURCE_FIELDS:
                blockers.append(
                    f"{source_id} contains forbidden raw/internal source field: {field}"
                )
            elif field != "formowl_locator" and raw_source_value(value):
                blockers.append(
                    f"{source_id} contains forbidden raw/internal source value: {field}"
                )
        modality = row.get("modality")
        modalities.add(modality)
        if modality not in REQUIRED_MODALITIES:
            blockers.append("enterprise multimodal source modality unsupported")
        if row.get("real_enterprise_data") is not True:
            blockers.append(f"{source_id} is not marked real enterprise data")
        if row.get("text_proxy_only") is not False:
            blockers.append(f"{source_id} is text-proxy-only")
        if row.get("raw_path_exposed") is not False:
            blockers.append(f"{source_id} exposes raw path")
        locator = row.get("formowl_locator")
        asset_id = row.get("asset_id")
        if not isinstance(locator, str) or not locator.startswith("formowl://asset/"):
            blockers.append(f"{source_id} FormOwl asset locator missing")
        elif isinstance(asset_id, str) and locator != f"formowl://asset/{asset_id}":
            blockers.append(f"{source_id} FormOwl asset locator does not match asset_id")
        if not strong_hex64(row.get("asset_sha256")):
            blockers.append(f"{source_id} asset sha256 missing or weak")
        for field in ("asset_id", "permission_scope_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                blockers.append(f"{source_id} {field} missing")
    missing = sorted(set(REQUIRED_MODALITIES) - modalities)
    if missing:
        blockers.append("enterprise multimodal pilot missing modalities: " + ", ".join(missing))
    return by_source


def _validate_validation_artifacts(
    packet: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
    blockers: list[str],
    *,
    llm_route: bool,
    allow_test_artifacts: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    refs = packet.get("validation_artifacts")
    if not isinstance(refs, list) or not refs:
        blockers.append("enterprise multimodal validation artifacts missing")
        refs = []
    all_rows: list[dict[str, Any]] = []
    artifact_hashes: list[str] = []
    modalities = set()
    validation_ids = set()
    for ref in refs:
        if not isinstance(ref, dict):
            blockers.append("enterprise multimodal validation artifact reference malformed")
            continue
        unsupported_fields = sorted(set(ref) - VALIDATION_ARTIFACT_REF_ALLOWED_FIELDS)
        if unsupported_fields:
            blockers.append(
                "enterprise multimodal validation artifact reference has unsupported fields: "
                + ", ".join(unsupported_fields)
            )
        for field, value in ref.items():
            if field != "artifact" and raw_source_value(value):
                blockers.append(
                    f"enterprise multimodal validation artifact reference contains raw/internal value: {field}"
                )
        path_blocker = artifact_path_rejection_reason(
            ref.get("artifact"),
            allow_test_artifacts=allow_test_artifacts,
        )
        if path_blocker:
            if path_blocker == "path missing or malformed":
                blockers.append(
                    "enterprise multimodal validation artifact missing or hash mismatch"
                )
            else:
                blockers.append(f"enterprise multimodal validation artifact {path_blocker}")
            continue
        if not artifact_matches_sha256(
            ref.get("artifact"),
            ref.get("artifact_sha256"),
            allow_test_artifacts=allow_test_artifacts,
        ):
            blockers.append("enterprise multimodal validation artifact missing or hash mismatch")
            continue
        artifact_hashes.append(ref["artifact_sha256"])
        artifact = load_artifact(
            ref.get("artifact"),
            ref.get("artifact_sha256"),
            allow_test_artifacts=allow_test_artifacts,
        )
        _reject_unsupported_artifact_fields(
            artifact,
            VALIDATION_ARTIFACT_ALLOWED_FIELDS,
            "enterprise multimodal validation artifact",
            blockers,
        )
        if artifact.get("artifact_type") != "enterprise_multimodal_validation_rows_v1":
            blockers.append("enterprise multimodal validation artifact type mismatch")
        modality = artifact.get("modality")
        if ref.get("modality") != modality:
            blockers.append("enterprise multimodal validation artifact modality reference mismatch")
        modalities.add(modality)
        if modality not in REQUIRED_MODALITIES:
            blockers.append("enterprise multimodal validation modality unsupported")
        rows = artifact.get("rows")
        if not isinstance(rows, list) or not rows:
            blockers.append(f"{modality} validation rows missing")
            rows = []
        for row in rows:
            if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
                blockers.append("enterprise multimodal validation row hash mismatch")
                continue
            unsupported_fields = sorted(set(row) - VALIDATION_ROW_ALLOWED_FIELDS)
            if unsupported_fields:
                blockers.append(
                    "enterprise multimodal validation row has unsupported fields: "
                    + ", ".join(unsupported_fields)
                )
            for field, value in row.items():
                if field not in {"row_sha256"} and raw_source_value(value):
                    blockers.append(
                        f"enterprise multimodal validation row contains raw/internal value: {field}"
                    )
            validation_id = row.get("validation_id")
            if not isinstance(validation_id, str) or not validation_id:
                blockers.append("enterprise multimodal validation id missing or malformed")
                continue
            if validation_id in validation_ids:
                blockers.append("duplicate enterprise multimodal validation id")
            validation_ids.add(validation_id)
            source = sources_by_id.get(row.get("source_id"))
            if not source:
                blockers.append("enterprise multimodal validation references unknown source")
            else:
                if row.get("source_asset_sha256") != source.get("asset_sha256"):
                    blockers.append("enterprise multimodal validation source asset hash mismatch")
                if row.get("modality") != source.get("modality"):
                    blockers.append("enterprise multimodal validation modality/source mismatch")
            if row.get("modality") != modality:
                blockers.append("enterprise multimodal validation row/artifact modality mismatch")
            for field in ("observation_id", "extractor_run_id", "candidate_id", "task"):
                if not isinstance(row.get(field), str) or not row[field]:
                    blockers.append(f"enterprise multimodal validation {field} missing")
            if llm_route:
                if row.get("llm_subagent_adjudicated") is not True:
                    blockers.append(
                        "enterprise multimodal validation row is not LLM subagent adjudicated"
                    )
                if row.get("human_adjudicated") not in {None, False}:
                    blockers.append(
                        "enterprise multimodal validation row must not claim human "
                        "adjudication on LLM route"
                    )
            else:
                if row.get("human_adjudicated") is not True:
                    blockers.append("enterprise multimodal validation row is not human adjudicated")
                if row.get("llm_subagent_adjudicated") not in {None, False}:
                    blockers.append(
                        "enterprise multimodal validation row must not claim LLM "
                        "adjudication on human route"
                    )
            all_rows.append(row)
    missing = sorted(set(REQUIRED_MODALITIES) - modalities)
    if missing:
        blockers.append(
            "enterprise multimodal validation artifacts missing modalities: " + ", ".join(missing)
        )
    return all_rows, artifact_hashes


def _validate_human_adjudication(
    artifact: dict[str, Any],
    validation_rows: list[dict[str, Any]],
    validation_artifact_hashes: list[str],
    blockers: list[str],
) -> None:
    _reject_unsupported_artifact_fields(
        artifact,
        ADJUDICATION_ARTIFACT_ALLOWED_FIELDS,
        "enterprise multimodal human adjudication artifact",
        blockers,
    )
    if artifact.get("completed") is not True:
        blockers.append("enterprise multimodal human adjudication is not complete")
    if artifact.get("reviewer_type") != "human":
        blockers.append("enterprise multimodal adjudicator is not human")
    if artifact.get("synthetic_or_agent_generated") is not False:
        blockers.append("enterprise multimodal adjudication is synthetic or agent-generated")
    if artifact.get("validation_artifact_sha256s") != sorted(validation_artifact_hashes):
        blockers.append("enterprise multimodal adjudication validation artifact binding mismatch")
    rows = artifact.get("rows")
    if not isinstance(rows, list):
        blockers.append("enterprise multimodal adjudication rows missing")
        rows = []
    validation_by_id = {row.get("validation_id"): row for row in validation_rows}
    row_ids = set()
    valid_bound_row_count = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("enterprise multimodal adjudication row hash mismatch")
            continue
        unsupported_fields = sorted(set(row) - ADJUDICATION_ROW_ALLOWED_FIELDS)
        if unsupported_fields:
            blockers.append(
                "enterprise multimodal adjudication row has unsupported fields: "
                + ", ".join(unsupported_fields)
            )
        for field, value in row.items():
            if field not in {"row_sha256"} and raw_source_value(value):
                blockers.append(
                    f"enterprise multimodal adjudication row contains raw/internal value: {field}"
                )
        validation_id = row.get("validation_id")
        duplicate_validation_id = validation_id in row_ids
        if duplicate_validation_id:
            blockers.append("enterprise multimodal adjudication duplicate validation row")
        row_ids.add(validation_id)
        source_row = validation_by_id.get(validation_id)
        row_bound = False
        modality_bound = False
        if not source_row:
            blockers.append("enterprise multimodal adjudication references unknown validation row")
        else:
            row_bound = row.get("validation_row_sha256") == source_row.get("row_sha256")
            modality_bound = row.get("modality") == source_row.get("modality")
            if not row_bound:
                blockers.append(
                    "enterprise multimodal adjudication validation row binding mismatch"
                )
            if not modality_bound:
                blockers.append("enterprise multimodal adjudication modality mismatch")
        final_label_valid = isinstance(row.get("final_label"), str) and bool(row["final_label"])
        if not final_label_valid:
            blockers.append("enterprise multimodal adjudication final label missing")
        if row_bound and modality_bound and final_label_valid and not duplicate_validation_id:
            valid_bound_row_count += 1
    if row_ids != set(validation_by_id):
        blockers.append("enterprise multimodal adjudication does not cover every validation row")
    if valid_bound_row_count != len(validation_by_id):
        blockers.append("enterprise multimodal adjudication valid row count mismatch")


def _validate_business_review(
    artifact: dict[str, Any],
    validation_rows: list[dict[str, Any]],
    adjudication_artifact_sha256: object,
    blockers: list[str],
    *,
    llm_route: bool,
) -> None:
    _reject_unsupported_artifact_fields(
        artifact,
        BUSINESS_REVIEW_ARTIFACT_ALLOWED_FIELDS,
        "enterprise business decision review artifact",
        blockers,
    )
    if llm_route:
        if artifact.get("llm_subagent_reviewed") is not True:
            blockers.append("enterprise business decision review is not LLM subagent reviewed")
        if artifact.get("human_reviewed") not in {None, False}:
            blockers.append(
                "enterprise business decision review must not claim human review on LLM route"
            )
    else:
        if artifact.get("human_reviewed") is not True:
            blockers.append("enterprise business decision review is not human reviewed")
        if artifact.get("llm_subagent_reviewed") not in {None, False}:
            blockers.append(
                "enterprise business decision review must not claim LLM subagent review "
                "on human route"
            )
    if artifact.get("autonomous_business_judgment") is not False:
        blockers.append("enterprise business decision review allows autonomous judgment")
    if artifact.get("financial_advice_or_execution") is not False:
        blockers.append("enterprise business decision review claims financial advice or execution")
    if artifact.get("adjudication_artifact_sha256") != adjudication_artifact_sha256:
        blockers.append("enterprise business decision review adjudication binding mismatch")
    known_validation_ids = {row.get("validation_id") for row in validation_rows}
    rows = artifact.get("decision_rows")
    if not isinstance(rows, list) or not rows:
        blockers.append("enterprise business decision rows missing")
        rows = []
    reviewed_validation_ids: set[object] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("enterprise business decision row hash mismatch")
            continue
        unsupported_fields = sorted(set(row) - BUSINESS_DECISION_ROW_ALLOWED_FIELDS)
        if unsupported_fields:
            blockers.append(
                "enterprise business decision row has unsupported fields: "
                + ", ".join(unsupported_fields)
            )
        for field, value in row.items():
            if field not in {"row_sha256"} and raw_source_value(value):
                blockers.append(
                    f"enterprise business decision row contains raw/internal value: {field}"
                )
        refs = row.get("source_validation_ids")
        refs_valid = False
        if not isinstance(refs, list) or not refs:
            blockers.append("enterprise business decision row lacks validation sources")
        elif not set(refs).issubset(known_validation_ids):
            blockers.append("enterprise business decision row references unknown validation")
        else:
            refs_valid = True
        if row.get("requires_human_review") is not True:
            blockers.append("enterprise business decision row does not require human review")
        if row.get("autonomous_business_judgment") is not False:
            blockers.append("enterprise business decision row allows autonomous judgment")
        if row.get("financial_advice_or_execution") is True:
            blockers.append("enterprise business decision row claims financial advice or execution")
        if (
            refs_valid
            and row.get("requires_human_review") is True
            and row.get("autonomous_business_judgment") is False
        ):
            reviewed_validation_ids.update(refs)
    if known_validation_ids and reviewed_validation_ids != known_validation_ids:
        blockers.append("enterprise business decision review does not cover every validation row")


def _validate_permission_probe(
    artifact: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
    blockers: list[str],
) -> None:
    _reject_unsupported_artifact_fields(
        artifact,
        PERMISSION_PROBE_ALLOWED_FIELDS,
        "enterprise multimodal permission probe",
        blockers,
    )
    for field in PERMISSION_PROBE_FORBIDDEN_POSITIVE_COUNTS:
        value = artifact.get(field)
        if isinstance(value, int) and value > 0:
            blockers.append(
                f"enterprise multimodal permission probe has positive leak count: {field}"
            )
    if artifact.get("completed") is not True:
        blockers.append("enterprise multimodal permission probe is not complete")
    if artifact.get("source_ids") != sorted(sources_by_id):
        blockers.append("enterprise multimodal permission probe source coverage mismatch")
    for flag in (
        "revoked_grant_content_denied",
        "private_content_not_returned",
        "raw_asset_access_denied",
        "entity_match_does_not_grant_access",
    ):
        if artifact.get(flag) is not True:
            blockers.append(f"enterprise multimodal permission probe failed or missing: {flag}")
    if artifact.get("cross_modal_private_leak_count") != 0:
        blockers.append("enterprise multimodal permission probe leaked private content")
    if artifact.get("raw_asset_access_count") != 0:
        blockers.append("enterprise multimodal permission probe exposed raw asset access")


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
                "enterprise multimodal four-specialist LLM subagent adjudication artifact "
                "missing or hash mismatch"
            )
        else:
            blockers.append(
                "enterprise multimodal four-specialist LLM subagent adjudication artifact "
                + path_blocker
            )
        return {}
    if not artifact_matches_sha256(
        packet.get("llm_subagent_adjudication_artifact"),
        packet.get("llm_subagent_adjudication_artifact_sha256"),
        allow_test_artifacts=allow_test_artifacts,
    ):
        blockers.append(
            "enterprise multimodal four-specialist LLM subagent adjudication artifact "
            "missing or hash mismatch"
        )
        return {}
    return load_artifact(
        packet.get("llm_subagent_adjudication_artifact"),
        packet.get("llm_subagent_adjudication_artifact_sha256"),
        allow_test_artifacts=allow_test_artifacts,
    )


def _validate_llm_adjudication(
    packet: dict[str, Any],
    validation_artifact_hashes: list[str],
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
        for digest in [packet.get("pilot_manifest_artifact_sha256"), *validation_artifact_hashes]
        if strong_hex64(digest)
    ]
    llm_panel.validate_four_specialist_panel(
        panel,
        blockers,
        label="enterprise multimodal",
        expected_target="multimodal_semantic_validation",
        expected_input_sha256s=expected_hashes,
    )


def _public_evidence_hashes(packet: dict[str, Any]) -> list[str]:
    hashes = []
    for field in (
        "pilot_manifest_artifact_sha256",
        "human_adjudication_artifact_sha256",
        "llm_subagent_adjudication_artifact_sha256",
        "business_decision_review_artifact_sha256",
        "permission_probe_artifact_sha256",
    ):
        digest = packet.get(field)
        if strong_hex64(digest):
            hashes.append(digest)
    for ref in packet.get("validation_artifacts", []):
        if isinstance(ref, dict) and strong_hex64(ref.get("artifact_sha256")):
            hashes.append(ref["artifact_sha256"])
    return sorted(set(hashes))


def _validate_claim_boundary(
    packet: dict[str, Any], blockers: list[str], *, llm_route: bool
) -> None:
    claims = packet.get("claim_boundary")
    if not isinstance(claims, dict):
        blockers.append("enterprise multimodal packet claim boundary missing")
        claims = {}
    unsupported_fields = sorted(set(claims) - CLAIM_BOUNDARY_ALLOWED_FIELDS)
    if unsupported_fields:
        blockers.append(
            "enterprise multimodal packet claim boundary has unsupported fields: "
            + ", ".join(unsupported_fields)
        )
    for field, value in claims.items():
        if raw_source_value(value):
            blockers.append(
                f"enterprise multimodal packet claim boundary contains raw/internal value: {field}"
            )
    for flag in (
        "supports_real_enterprise_multimodal_claim",
        "supports_cross_modal_permission_probe_claim",
        "supports_business_decision_review_claim",
    ):
        if claims.get(flag) is not True:
            blockers.append(f"enterprise multimodal packet missing claim: {flag}")
    if llm_route:
        if claims.get("supports_multimodal_llm_subagent_adjudication_completed_claim") is not True:
            blockers.append(
                "enterprise multimodal packet missing claim: "
                "supports_multimodal_llm_subagent_adjudication_completed_claim"
            )
        if claims.get("supports_multimodal_human_adjudication_completed_claim") is not False:
            blockers.append(
                "enterprise multimodal packet must not claim human adjudication "
                "when using LLM subagent adjudication"
            )
    else:
        if claims.get("supports_multimodal_human_adjudication_completed_claim") is not True:
            blockers.append(
                "enterprise multimodal packet missing claim: "
                "supports_multimodal_human_adjudication_completed_claim"
            )
        if claims.get("supports_multimodal_llm_subagent_adjudication_completed_claim") not in {
            None,
            False,
        }:
            blockers.append(
                "enterprise multimodal packet overclaims unsupported claim: "
                "supports_multimodal_llm_subagent_adjudication_completed_claim"
            )
    for flag in (
        "supports_financial_advice_or_autonomous_business_judgment_claim",
        "supports_production_ready_claim",
        "supports_top_tier_scientific_validation_claim",
        "supports_raw_asset_access_claim",
    ):
        if claims.get(flag) is not False:
            blockers.append(f"enterprise multimodal packet overclaims unsupported claim: {flag}")


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
            "enterprise multimodal validation packet missing",
            "real enterprise multimodal pilot manifest is not present",
            "enterprise spreadsheet/mail/meeting/video validation packets are not present",
            "multimodal human adjudication and cross-modal permission leak probe are not present",
        ]
    if packet.get("artifact_id") != "enterprise_multimodal_validation_packet_v1":
        blockers.append("enterprise multimodal validation packet artifact id mismatch")
    if packet.get("evidence_kind") != "real_enterprise_multimodal_validation":
        blockers.append("enterprise multimodal evidence kind mismatch")
    if packet.get("recovered_after_tmp_loss") is not False:
        blockers.append("enterprise multimodal packet cannot rely on lost /tmp artifacts")
    unsupported_fields = sorted(set(packet) - PACKET_ALLOWED_FIELDS)
    if unsupported_fields:
        blockers.append(
            "enterprise multimodal validation packet has unsupported fields: "
            + ", ".join(unsupported_fields)
        )
    for field, value in packet.items():
        if field not in {
            "pilot_manifest_artifact",
            "validation_artifacts",
            "human_adjudication_artifact",
            "llm_subagent_adjudication_artifact",
            "business_decision_review_artifact",
            "permission_probe_artifact",
        } and raw_source_value(value):
            blockers.append(
                f"enterprise multimodal validation packet contains raw/internal value: {field}"
            )
    llm_route = bool(packet.get("llm_subagent_adjudication_artifact"))
    _validate_claim_boundary(packet, blockers, llm_route=llm_route)

    manifest = _load_required_artifact(
        packet,
        "pilot_manifest_artifact",
        "enterprise_multimodal_pilot_manifest_v1",
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    decision_review = _load_required_artifact(
        packet,
        "business_decision_review_artifact",
        "enterprise_business_decision_review_v1",
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    permission_probe = _load_required_artifact(
        packet,
        "permission_probe_artifact",
        "enterprise_multimodal_permission_probe_v1",
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )

    sources_by_id = _validate_manifest(manifest, blockers)
    validation_rows, validation_artifact_hashes = _validate_validation_artifacts(
        packet,
        sources_by_id,
        blockers,
        llm_route=llm_route,
        allow_test_artifacts=allow_test_artifacts,
    )
    if llm_route:
        if packet.get("human_adjudication_artifact"):
            blockers.append(
                "enterprise multimodal packet must not mix human and LLM adjudication routes"
            )
        _validate_llm_adjudication(
            packet,
            validation_artifact_hashes,
            blockers,
            allow_test_artifacts=allow_test_artifacts,
        )
        adjudication_artifact_sha256 = packet.get("llm_subagent_adjudication_artifact_sha256")
    else:
        adjudication = _load_required_artifact(
            packet,
            "human_adjudication_artifact",
            "enterprise_multimodal_human_adjudication_v1",
            blockers,
            allow_test_artifacts=allow_test_artifacts,
        )
        _validate_human_adjudication(
            adjudication,
            validation_rows,
            validation_artifact_hashes,
            blockers,
        )
        adjudication_artifact_sha256 = packet.get("human_adjudication_artifact_sha256")
    _validate_business_review(
        decision_review,
        validation_rows,
        adjudication_artifact_sha256,
        blockers,
        llm_route=llm_route,
    )
    _validate_permission_probe(permission_probe, sources_by_id, blockers)
    public_evidence.validate_public_evidence_packet(
        packet,
        blockers,
        gate_id="multimodal_semantic_validation",
        artifact_path_rejection_reason=artifact_path_rejection_reason,
        artifact_matches_sha256=artifact_matches_sha256,
        load_artifact=load_artifact,
        allow_test_artifacts=allow_test_artifacts,
        expected_artifact_sha256s=_public_evidence_hashes(packet),
    )
    return sorted(set(blockers))


def build_report(
    packet: dict[str, Any] | None = None,
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    packet = load_input_packet() if packet is None else packet
    blockers = validate_packet(packet, allow_test_artifacts=allow_test_artifacts)
    validation_refs = packet.get("validation_artifacts", []) if isinstance(packet, dict) else []
    has_llm_panel = isinstance(packet, dict) and bool(
        packet.get("llm_subagent_adjudication_artifact")
    )
    report = {
        "artifact_id": "enterprise_multimodal_validation_validator_recovery_v1",
        "input_packet": "inputs/enterprise_multimodal_validation_packet.json",
        "passed": not blockers,
        "blockers": blockers,
        "metrics": {
            "validation_artifact_count": len(validation_refs)
            if isinstance(validation_refs, list)
            else 0,
            "required_modality_count": len(REQUIRED_MODALITIES),
            "pilot_manifest_present": bool(packet.get("pilot_manifest_artifact"))
            if isinstance(packet, dict)
            else False,
            "human_adjudication_present": bool(packet.get("human_adjudication_artifact"))
            if isinstance(packet, dict)
            else False,
            "llm_subagent_adjudication_present": has_llm_panel,
            "business_decision_review_present": bool(
                packet.get("business_decision_review_artifact")
            )
            if isinstance(packet, dict)
            else False,
            "permission_probe_present": bool(packet.get("permission_probe_artifact"))
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
            "supports_real_enterprise_multimodal_claim": not blockers,
            "supports_multimodal_human_adjudication_completed_claim": (
                not blockers and not has_llm_panel
            ),
            "supports_multimodal_llm_subagent_adjudication_completed_claim": (
                not blockers and has_llm_panel
            ),
            "supports_cross_modal_permission_probe_claim": not blockers,
            "supports_business_decision_review_claim": not blockers,
            public_evidence.CLAIM_FIELD: (
                not blockers
                and public_evidence.evidence_source_mode(packet) == public_evidence.PUBLIC_MODE
            )
            if isinstance(packet, dict)
            else False,
            "supports_financial_advice_or_autonomous_business_judgment_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_raw_asset_access_claim": False,
        },
    }
    if packet:
        report["packet_sha256"] = sha256_json(packet)
    return report


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "enterprise_multimodal_validation_validator.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
