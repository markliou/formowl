#!/usr/bin/env python3
"""Public reproducible evidence manifest validation helpers.

Public URLs are useful only when they are bound to immutable local evidence
artifacts. This module validates that binding without fetching network content
or promoting canonical packets.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any


PUBLIC_MODE = "public_reproducible"
PRIVATE_MODE = "operator_private"
ALLOWED_MODES = {PRIVATE_MODE, PUBLIC_MODE}
MANIFEST_ARTIFACT_TYPE = "public_reproducible_evidence_sources_v1"
CLAIM_FIELD = "supports_public_reproducible_evidence_claim"
PACKET_FIELDS = {
    "evidence_source_mode",
    "public_evidence_manifest_artifact",
    "public_evidence_manifest_artifact_sha256",
}
MANIFEST_ALLOWED_FIELDS = {
    "artifact_type",
    "gate_id",
    "evidence_source_mode",
    "retrieved_at",
    "source_count",
    "public_sources",
    "source_index_sha256",
    "covered_artifact_sha256s",
}
SOURCE_ALLOWED_FIELDS = {
    "source_id",
    "source_url",
    "source_type",
    "source_usage_role",
    "license",
    "version_or_snapshot",
    "retrieved_at",
    "content_sha256",
    "archive_sha256",
    "derived_artifact_sha256s",
    "publicly_accessible",
    "permission_allows_research_evaluation",
    "non_synthetic",
    "raw_private_payload",
}
SAFE_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,128}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PLACEHOLDER_MARKERS = (
    "OPERATOR_",
    "FILL_WITH",
    "fill-with",
    "path-to-real",
    "template",
    "unknown",
    "tbd",
)
FORBIDDEN_LICENSE_VALUES = {"", "unknown", "n/a", "none", "tbd", "unverified"}
FORBIDDEN_PUBLIC_URL_PREFIXES = (
    "https://localhost",
    "https://127.",
    "https://10.",
    "https://192.168.",
    "https://169.254.",
)
HEX64_CHARS = set("0123456789abcdef")


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_index_sha256(sources: list[dict[str, Any]]) -> str:
    return sha256_json(sources)


def build_manifest(
    *,
    gate_id: str,
    retrieved_at: str,
    public_sources: list[dict[str, Any]],
    covered_artifact_sha256s: list[str],
) -> dict[str, Any]:
    return {
        "artifact_type": MANIFEST_ARTIFACT_TYPE,
        "gate_id": gate_id,
        "evidence_source_mode": PUBLIC_MODE,
        "retrieved_at": retrieved_at,
        "source_count": len(public_sources),
        "public_sources": public_sources,
        "source_index_sha256": source_index_sha256(public_sources),
        "covered_artifact_sha256s": sorted(set(covered_artifact_sha256s)),
    }


def strong_hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in HEX64_CHARS for char in value)
        and len(set(value)) > 1
    )


def evidence_source_mode(packet: dict[str, Any]) -> str:
    mode = packet.get("evidence_source_mode", PRIVATE_MODE)
    return mode if isinstance(mode, str) else ""


def _string_has_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in PLACEHOLDER_MARKERS)


def _validate_public_source(row: object, blockers: list[str], source_ids: set[str]) -> set[str]:
    covered_hashes: set[str] = set()
    if not isinstance(row, dict):
        blockers.append("public evidence source row is not an object")
        return covered_hashes
    unsupported = sorted(set(row) - SOURCE_ALLOWED_FIELDS)
    if unsupported:
        blockers.append(
            "public evidence source row has unsupported fields: " + ", ".join(unsupported)
        )
    source_id = row.get("source_id")
    if not isinstance(source_id, str) or not SAFE_SOURCE_ID_RE.match(source_id):
        blockers.append("public evidence source id missing or unsafe")
    elif source_id in source_ids:
        blockers.append("duplicate public evidence source id")
    else:
        source_ids.add(source_id)
    source_url = row.get("source_url")
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        blockers.append("public evidence source URL must be an https URL")
    elif source_url.lower().startswith(FORBIDDEN_PUBLIC_URL_PREFIXES):
        blockers.append("public evidence source URL must not target local/private hosts")
    elif _string_has_placeholder(source_url):
        blockers.append("public evidence source URL contains placeholder text")
    for field in ("source_type", "source_usage_role", "version_or_snapshot"):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip() or _string_has_placeholder(value):
            blockers.append(f"public evidence source {field} missing or placeholder")
    license_value = row.get("license")
    if (
        not isinstance(license_value, str)
        or license_value.strip().lower() in FORBIDDEN_LICENSE_VALUES
        or _string_has_placeholder(license_value)
    ):
        blockers.append("public evidence source license missing or unverified")
    for field in ("retrieved_at",):
        value = row.get(field)
        if not isinstance(value, str) or not UTC_TIMESTAMP_RE.match(value):
            blockers.append(f"public evidence source {field} must be UTC timestamp")
    for field in ("content_sha256", "archive_sha256"):
        if not strong_hex64(row.get(field)):
            blockers.append(f"public evidence source {field} missing or weak")
    for flag in (
        "publicly_accessible",
        "permission_allows_research_evaluation",
        "non_synthetic",
    ):
        if row.get(flag) is not True:
            blockers.append(f"public evidence source flag must be true: {flag}")
    if row.get("raw_private_payload") is not False:
        blockers.append("public evidence source must not contain raw private payload")
    derived = row.get("derived_artifact_sha256s")
    if not isinstance(derived, list) or not derived:
        blockers.append("public evidence source derived artifact hashes missing")
        return covered_hashes
    for digest in derived:
        if not strong_hex64(digest):
            blockers.append("public evidence source derived artifact hash missing or weak")
        else:
            covered_hashes.add(digest)
    return covered_hashes


def validate_manifest_payload(
    manifest: dict[str, Any],
    blockers: list[str],
    *,
    gate_id: str,
    expected_artifact_sha256s: list[str] | None = None,
) -> None:
    unsupported = sorted(set(manifest) - MANIFEST_ALLOWED_FIELDS)
    if unsupported:
        blockers.append(
            "public evidence manifest has unsupported fields: " + ", ".join(unsupported)
        )
    if manifest.get("artifact_type") != MANIFEST_ARTIFACT_TYPE:
        blockers.append("public evidence manifest artifact type mismatch")
    if manifest.get("gate_id") != gate_id:
        blockers.append("public evidence manifest gate id mismatch")
    if manifest.get("evidence_source_mode") != PUBLIC_MODE:
        blockers.append("public evidence manifest mode mismatch")
    retrieved_at = manifest.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not UTC_TIMESTAMP_RE.match(retrieved_at):
        blockers.append("public evidence manifest retrieved_at must be UTC timestamp")
    sources = manifest.get("public_sources")
    if not isinstance(sources, list) or not sources:
        blockers.append("public evidence manifest sources missing")
        sources = []
    if manifest.get("source_count") != len(sources):
        blockers.append("public evidence manifest source count mismatch")
    if manifest.get("source_index_sha256") != source_index_sha256(sources):
        blockers.append("public evidence manifest source index hash mismatch")
    source_ids: set[str] = set()
    derived_hashes: set[str] = set()
    for row in sources:
        derived_hashes.update(_validate_public_source(row, blockers, source_ids))
    covered = manifest.get("covered_artifact_sha256s")
    if not isinstance(covered, list) or not covered:
        blockers.append("public evidence manifest covered artifact hashes missing")
        covered_hashes: set[str] = set()
    else:
        covered_hashes = set()
        for digest in covered:
            if not strong_hex64(digest):
                blockers.append("public evidence covered artifact hash missing or weak")
            else:
                covered_hashes.add(digest)
    if not covered_hashes.issubset(derived_hashes):
        blockers.append("public evidence manifest covers hashes not derived from sources")
    expected_hashes = {digest for digest in expected_artifact_sha256s or [] if strong_hex64(digest)}
    missing = sorted(expected_hashes - covered_hashes)
    if missing:
        blockers.append("public evidence manifest does not cover expected artifact hashes")


def validate_public_evidence_packet(
    packet: dict[str, Any],
    blockers: list[str],
    *,
    gate_id: str,
    artifact_path_rejection_reason: Callable[..., str | None],
    artifact_matches_sha256: Callable[..., bool],
    load_artifact: Callable[..., dict[str, Any]],
    allow_test_artifacts: bool = False,
    expected_artifact_sha256s: list[str] | None = None,
) -> None:
    mode = evidence_source_mode(packet)
    claims = packet.get("claim_boundary") if isinstance(packet.get("claim_boundary"), dict) else {}
    if mode not in ALLOWED_MODES:
        blockers.append("evidence_source_mode must be operator_private or public_reproducible")
        return
    has_public_fields = any(field in packet for field in PACKET_FIELDS - {"evidence_source_mode"})
    if mode == PRIVATE_MODE:
        if has_public_fields:
            blockers.append("operator-private evidence packet must not include public manifest")
        if claims.get(CLAIM_FIELD) is True:
            blockers.append("operator-private evidence packet must not claim public evidence")
        return
    if claims.get(CLAIM_FIELD) is not True:
        blockers.append("public evidence packet missing public reproducible evidence claim")
    artifact = packet.get("public_evidence_manifest_artifact")
    digest = packet.get("public_evidence_manifest_artifact_sha256")
    path_blocker = artifact_path_rejection_reason(
        artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    if path_blocker:
        if path_blocker == "path missing or malformed":
            blockers.append("public evidence manifest artifact missing or hash mismatch")
        else:
            blockers.append("public evidence manifest artifact " + path_blocker)
        return
    if not artifact_matches_sha256(
        artifact,
        digest,
        allow_test_artifacts=allow_test_artifacts,
    ):
        blockers.append("public evidence manifest artifact missing or hash mismatch")
        return
    manifest = load_artifact(
        artifact,
        digest,
        allow_test_artifacts=allow_test_artifacts,
    )
    validate_manifest_payload(
        manifest,
        blockers,
        gate_id=gate_id,
        expected_artifact_sha256s=expected_artifact_sha256s,
    )
