#!/usr/bin/env python3
"""Build an immutable, proof-only PST SourceInventory rebind sidecar.

The script never runs ``readpst`` and never changes preserved Observations.  It
uses the independent ``lspst`` raw oracle plus deterministic preserved
occurrence/export fingerprints.  A binding is emitted only when one remaining
raw identity and one remaining Observation identity share a unique key.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    Asset,
    Observation,
    SourceInventory,
    SourceInventoryItem,
    SourceInventoryProcessingState,
    SourceInventoryRawRetentionState,
    assert_no_public_raw_references,
    sha256_json,
    stable_extractor_run_id,
    stable_observation_id,
    stable_resource_contract_id,
)
from formowl_core import (  # noqa: E402
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_ingestion.extractors.mail.pst import (  # noqa: E402
    NativePstAttachmentExport,
    NativePstMessageExport,
    parse_native_pst_message_exports,
)
from formowl_mail import (  # noqa: E402
    MailEvidenceBundle,
    MailEvidenceQueryGateway,
    build_existing_observation_snippet_index,
    build_mail_evidence_bundle,
)


ARTIFACT_ID = "formowl_issue56_source_complete_snapshot_rebind_report_v1"
SNAPSHOT_ARTIFACT_ID = "formowl_issue56_source_complete_snapshot_rebind_v1"
NATIVE_AUTHORIZED_SNAPSHOT_ARTIFACT_ID = (
    "formowl_issue56_native_source_complete_authorized_observation_snapshot_v1"
)
NATIVE_AUTHORIZED_REPORT_ARTIFACT_ID = (
    "formowl_issue56_native_source_complete_authorized_observation_report_v1"
)
NATIVE_RETRIEVAL_SNAPSHOT_ARTIFACT_ID = (
    "formowl_issue56_native_source_complete_retrieval_ready_snapshot_v1"
)
NATIVE_RETRIEVAL_REPORT_ARTIFACT_ID = (
    "formowl_issue56_native_source_complete_retrieval_ready_report_v1"
)
NATIVE_PRIVATE_MANIFEST_ARTIFACT_ID = "formowl_issue56_pst_native_lineage_private_manifest_v1"
GAP_FORENSICS_ARTIFACT_ID = "formowl_issue56_pst_gap_forensics_v1"
SCHEMA_VERSION = 1
REBIND_POLICY_ID = "issue56_lspst_unique_hierarchical_identity_rebind_v1"
GAP_FORENSICS_POLICY_ID = "issue56_existing_artifact_exact_gap_forensics_v1"
NEXT_PARSER_CONTRACT = {
    "command_profile": "readpst_separate_email_attachment_export_v1",
    "flags": ["-S", "-t", "ea"],
    "required_manifest_fields": [
        "source_local_key",
        "message_content_hash",
        "attachment_content_hash",
        "folder_occurrence_hash",
        "export_ordinal",
    ],
    "include_deleted_items": False,
}
REQUIRED_SOURCE_CAPTURE_CAPABILITY = {
    "contract_id": "issue56_pst_native_occurrence_export_lineage_v1",
    "shared_between": ["raw_oracle", "parser_export_manifest"],
    "required_fields": [
        "pst_folder_node_id",
        "pst_message_node_id",
        "pst_attachment_node_id",
        "export_disposition",
        "export_status",
        "export_reason_fingerprint",
        "message_content_hash",
        "attachment_content_hash",
    ],
    "public_projection": ["hash", "count", "status"],
}
PARSER_OBSERVATION_MATCH_STAGES = (
    (
        "parser_observation_message_fingerprint_unique_v1",
        ("observation_message_fingerprint",),
        ("exported_message_identity_fingerprint",),
    ),
    (
        "parser_observation_full_header_identity_unique_v1",
        (
            "folder_occurrence_hash",
            "message_id_fingerprint",
            "message_identity_fingerprint",
            "sender_identity_fingerprint",
            "date_identity_fingerprint",
        ),
        (
            "folder_occurrence_hash",
            "message_id_fingerprint",
            "message_identity_fingerprint",
            "sender_identity_fingerprint",
            "date_identity_fingerprint",
        ),
    ),
    (
        "parser_observation_body_message_id_unique_v1",
        ("body_hash", "message_id_fingerprint"),
        ("body_hash", "message_id_fingerprint"),
    ),
    (
        "parser_observation_body_subject_date_unique_v1",
        (
            "body_hash",
            "message_identity_fingerprint",
            "date_identity_fingerprint",
        ),
        (
            "body_hash",
            "message_identity_fingerprint",
            "date_identity_fingerprint",
        ),
    ),
    (
        "parser_observation_body_subject_unique_v1",
        ("body_hash", "message_identity_fingerprint"),
        ("body_hash", "message_identity_fingerprint"),
    ),
    (
        "parser_observation_folder_message_header_unique_v1",
        (
            "folder_occurrence_hash",
            "message_id_fingerprint",
            "message_identity_fingerprint",
            "date_identity_fingerprint",
        ),
        (
            "folder_occurrence_hash",
            "message_id_fingerprint",
            "message_identity_fingerprint",
            "date_identity_fingerprint",
        ),
    ),
)
KNOWN_PARSER_WARNING_CODES = (
    "pst_parser_large_message_file_skipped",
    "pst_parser_message_file_skipped",
    "pst_parser_header_redacted",
    "pst_parser_body_segment_limit_reached",
    "pst_parser_body_segment_redacted",
    "pst_parser_large_attachment_hash_skipped",
)
DEFAULT_PST = ROOT / "tests" / "pst-exm" / "archive.pst"
DEFAULT_PRESERVED_WORK_DIR = ROOT / ".test-tmp" / "exm-archive-domain-hard-work"
DEFAULT_OUTPUT_ROOT = Path(tempfile.gettempdir()) / "formowl-issue56-source-rebind"
DEFAULT_PARSER_MANIFEST = (
    ROOT / ".test-tmp" / "issue56-pst-parser-export-v1" / "private-parser-manifest.json"
)
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NODE_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_NATIVE_SOURCE_LOCAL_KEY_RE = re.compile(r"^pstnative_(?:message|attachment)_[0-9a-f]{32}$")
_PRIVATE_PROBE_MAX_POSTING_COUNT = 20
_PRIVATE_PROBE_MAX_PROTECTED_CANDIDATES = 64
_PRIVATE_PROBE_MAX_FALLBACK_SNIPPETS = 256
_PRIVATE_PROBE_MAX_LEXICAL_CANDIDATES_PER_SNIPPET = 8


def _load_reconciliation_module():
    path = ROOT / "scripts" / "issue56_full_pst_source_reconciliation.py"
    spec = importlib.util.spec_from_file_location(
        "issue56_full_pst_source_reconciliation",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("reconciliation_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reconciliation = _load_reconciliation_module()


@dataclass(frozen=True)
class SnapshotRebindArtifacts:
    snapshot: dict[str, Any]
    report: dict[str, Any]


@dataclass(frozen=True)
class NativeRetrievalReadyArtifacts:
    source_snapshot: dict[str, Any]
    retrieval_snapshot: dict[str, Any]
    bundle: dict[str, Any]
    report: dict[str, Any]


def run_native_retrieval_ready_mail_evidence(
    *,
    native_manifest_path: Path,
    native_export_root: Path,
    preserved_work_dir: Path,
    source_snapshot_output: Path,
    source_report_output: Path,
    retrieval_snapshot_output: Path,
    bundle_output: Path,
    report_output: Path,
    created_at: str | None = None,
) -> NativeRetrievalReadyArtifacts:
    """Build a retrieval-ready bundle from one source-complete native lineage.

    The old preserved Observation snapshot is not read or matched. Source
    occurrence identity comes only from the validated native manifest and the
    new source-complete SourceInventory snapshot. RFC822 content parsing is
    delegated to the existing PST mail extractor owner path.
    """

    manifest = _load_native_private_manifest(
        native_manifest_path,
        export_root=native_export_root,
    )
    source_artifacts = run_native_source_complete_snapshot(
        native_manifest_path=native_manifest_path,
        native_export_root=native_export_root,
        preserved_work_dir=preserved_work_dir,
        snapshot_output=source_snapshot_output,
        report_output=source_report_output,
        created_at=created_at,
        _validated_manifest=manifest,
    )
    if source_artifacts.report["status"] != "passed":
        raise RuntimeError("native_retrieval_source_snapshot_blocked")
    source_snapshot = source_artifacts.snapshot
    source_inventory = SourceInventory.from_dict(source_snapshot["source_inventory"])
    authorization = source_snapshot["authorization_binding"]
    permission_scope = dict(authorization["permission_scope"])
    resolved_created_at = str(source_snapshot["created_at"])
    provenance_fingerprint = sha256_json(
        {
            "source_asset_sha256": source_snapshot["source_asset_sha256"],
            "native_manifest_fingerprint": source_snapshot["native_manifest_fingerprint"],
            "source_ref_fingerprint": source_snapshot["source_ref_fingerprint"],
            "asset_binding_fingerprint": source_snapshot["asset_binding_fingerprint"],
            "parser_fingerprint": source_snapshot["parser_fingerprint"],
        }
    )
    item_by_source_key = {
        str(item.location.get("source_local_key")): item
        for item in source_inventory.items
        if isinstance(item.location.get("source_local_key"), str)
    }
    message_exports: list[NativePstMessageExport] = []
    export_root = native_export_root.resolve()
    for message in manifest["messages"]:
        message_source_key = str(message["source_local_key"])
        message_item = item_by_source_key.get(message_source_key)
        if message_item is None:
            raise RuntimeError("native_retrieval_message_inventory_item_missing")
        parent_folder_source_key = message_item.location.get("parent_source_local_key")
        if not isinstance(parent_folder_source_key, str) or not parent_folder_source_key:
            raise RuntimeError("native_retrieval_message_parent_missing")
        relative_output = _native_export_relative_output(
            message["relative_output_path"],
            allow_missing=False,
        )
        if relative_output is None:
            raise RuntimeError("native_retrieval_message_export_missing")
        attachments = tuple(
            NativePstAttachmentExport(
                source_local_key=str(attachment["source_local_key"]),
                parent_message_source_local_key=message_source_key,
                pst_attachment_node_id=str(attachment["pst_attachment_node_id"]),
                attachment_content_hash=str(attachment["attachment_content_hash"]),
                byte_count=int(attachment["byte_count"]),
                export_disposition=str(attachment["export_disposition"]),
                export_occurrence_ordinal=int(attachment["export_occurrence_ordinal"]),
            )
            for attachment in message["attachments"]
        )
        message_exports.append(
            NativePstMessageExport(
                source_local_key=message_source_key,
                parent_folder_source_local_key=parent_folder_source_key,
                pst_folder_node_id=str(message["pst_folder_node_id"]),
                pst_message_node_id=str(message["pst_message_node_id"]),
                pst_message_data_node_id=str(message["pst_message_data_node_id"]),
                message_content_hash=str(message["message_content_hash"]),
                byte_count=int(message["byte_count"]),
                export_path=export_root.joinpath(*relative_output.split("/")),
                attachments=attachments,
            )
        )

    parsed = parse_native_pst_message_exports(
        message_exports,
        source_inventory=source_inventory,
        source_asset_id=source_inventory.source_asset_id,
        source_asset_sha256=str(source_snapshot["source_asset_sha256"]),
        extractor_run_id=str(source_snapshot["extractor_run_binding"]["extractor_run_id"]),
        permission_scope=permission_scope,
        provenance_fingerprint=provenance_fingerprint,
        created_at=resolved_created_at,
    )
    source_occurrence_observations = [
        Observation.from_dict(row) for row in source_snapshot["observations"]
    ]
    parsed_observations = list(parsed.observations)
    all_observations = [*source_occurrence_observations, *parsed_observations]
    if len({row.observation_id for row in all_observations}) != len(all_observations):
        raise RuntimeError("native_retrieval_observation_id_duplicate")

    bundle = build_mail_evidence_bundle(
        parsed_observations,
        workspace_id=str(authorization["workspace_id"]),
        owner_user_id=str(authorization["owner_user_id"]),
        source_asset_id=source_inventory.source_asset_id,
        archive_sha256=str(source_snapshot["source_asset_sha256"]),
        producer_type="server_side_parser",
        parser_name="libpst_native_lineage_plus_formowl_rfc822",
        parser_version="libpst-0.6.76+formowl-native-lineage-v1",
        upload_session_id=stable_resource_contract_id(
            "uploadsession",
            "Issue56NativeSourceCompleteImport",
            {
                "source_snapshot_fingerprint": source_snapshot["snapshot_fingerprint"],
                "source_asset_id": source_inventory.source_asset_id,
            },
        ),
        retention_policy="retain_7_days",
        raw_archive_retention_decision="retained_by_policy",
        created_at=resolved_created_at,
        started_at=resolved_created_at,
        completed_at=resolved_created_at,
        parse_warnings=[
            f"{warning_code}:{warning_count}"
            for warning_code, warning_count in parsed.warning_counts.items()
        ],
    )
    bundle_payload = bundle.to_dict()
    bundle_fingerprint = sha256_json(bundle_payload)
    bundle_artifact: dict[str, Any] = {
        "artifact_id": "formowl_issue56_native_mail_evidence_bundle_v1",
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "source_snapshot_fingerprint": source_snapshot["snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(source_snapshot["source_inventory"]),
        "source_provenance_fingerprint": provenance_fingerprint,
        "bundle": bundle_payload,
        "bundle_fingerprint": bundle_fingerprint,
    }
    bundle_artifact["artifact_fingerprint"] = _payload_fingerprint(
        bundle_artifact,
        "artifact_fingerprint",
    )
    persisted_bundle = _persist_immutable(
        bundle_output,
        bundle_artifact,
        fingerprint_field="artifact_fingerprint",
    )
    round_trip_bundle = MailEvidenceBundle.from_dict(persisted_bundle["bundle"])
    if round_trip_bundle.to_dict() != bundle_payload:
        raise RuntimeError("native_retrieval_bundle_round_trip_failed")

    tokenizer_profile = load_issue56_target_mail_tokenizer_profile()
    if tokenizer_profile.tokenizer_id != JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID:
        raise RuntimeError("native_retrieval_target_tokenizer_unavailable")
    snippet_index, index_manifest = build_existing_observation_snippet_index(
        all_observations,
        bundle=round_trip_bundle,
        tokenizer_profile=tokenizer_profile,
    )
    if (
        index_manifest.query_profile_fingerprint != index_manifest.evidence_profile_fingerprint
        or index_manifest.query_profile_fingerprint != tokenizer_profile.profile_fingerprint
    ):
        raise RuntimeError("native_retrieval_tokenizer_binding_mismatch")

    query_text, expected_source_observation_id = _select_private_content_probe(
        snippet_index=snippet_index,
        tokenizer_profile=tokenizer_profile,
    )
    gateway = MailEvidenceQueryGateway(
        [round_trip_bundle],
        tokenizer_profile=tokenizer_profile,
        snippet_index_by_bundle_id={round_trip_bundle.mail_evidence_bundle_id: snippet_index},
    )
    authorized_result = gateway.query_mail_evidence(
        query_text=query_text,
        requester_user_id=str(authorization["owner_user_id"]),
        workspace_id=str(authorization["workspace_id"]),
        session_id="issue56_native_retrieval_authorized_probe",
        mail_evidence_bundle_id=round_trip_bundle.mail_evidence_bundle_id,
        limit=20,
    )
    denied_requester = "user_issue56_native_retrieval_denied"
    if denied_requester == authorization["owner_user_id"]:
        denied_requester = "user_issue56_native_retrieval_denied_alternate"
    denied_result = gateway.query_mail_evidence(
        query_text=query_text,
        requester_user_id=denied_requester,
        workspace_id=str(authorization["workspace_id"]),
        session_id="issue56_native_retrieval_denied_probe",
        mail_evidence_bundle_id=round_trip_bundle.mail_evidence_bundle_id,
        limit=20,
    )
    if authorized_result.status != "ok" or not authorized_result.citations:
        raise RuntimeError("native_retrieval_authorized_query_no_evidence")
    cited_observation_ids = {
        str(citation["source_observation_id"]) for citation in authorized_result.citations
    }
    if expected_source_observation_id not in cited_observation_ids:
        raise RuntimeError("native_retrieval_content_probe_lineage_mismatch")
    parsed_by_id = {observation.observation_id: observation for observation in parsed_observations}
    cited_observation = parsed_by_id.get(expected_source_observation_id)
    if (
        cited_observation is None
        or cited_observation.observation_type != "email_body_segment"
        or not isinstance(
            cited_observation.location.get("source_inventory_item_id"),
            str,
        )
        or not isinstance(
            cited_observation.location.get("source_local_key"),
            str,
        )
        or not _FINGERPRINT_RE.fullmatch(
            str(cited_observation.location.get("source_content_hash", ""))
        )
        or cited_observation.location.get("source_provenance_fingerprint") != provenance_fingerprint
    ):
        raise RuntimeError("native_retrieval_cited_observation_binding_invalid")
    if (
        denied_result.status != "permission_denied"
        or denied_result.evidence_snippets
        or denied_result.citations
    ):
        raise RuntimeError("native_retrieval_denied_query_not_fail_closed")

    retrieval_counts = {
        "source_inventory_item_count": len(source_inventory.items),
        "source_occurrence_observation_count": len(source_occurrence_observations),
        "parsed_folder_observation_count": sum(
            observation.observation_type == "mail_folder_occurrence"
            for observation in parsed_observations
        ),
        "parsed_message_observation_count": sum(
            observation.observation_type == "email_message" for observation in parsed_observations
        ),
        "parsed_header_observation_count": parsed.header_observation_count,
        "parsed_body_segment_observation_count": (parsed.body_segment_observation_count),
        "parsed_attachment_observation_count": (parsed.attachment_observation_count),
        "parsed_observation_count": len(parsed_observations),
        "retrieval_snapshot_observation_count": len(all_observations),
        "mail_bundle_message_count": len(round_trip_bundle.messages),
        "mail_bundle_message_occurrence_count": len(round_trip_bundle.message_occurrences),
        "mail_bundle_body_segment_count": len(round_trip_bundle.body_segments),
        "mail_bundle_attachment_count": len(round_trip_bundle.attachments),
        "mail_bundle_attachment_occurrence_count": len(round_trip_bundle.attachment_occurrences),
        "index_observation_count": index_manifest.observation_count,
        "indexed_observation_count": index_manifest.indexed_observation_count,
        "indexed_snippet_count": index_manifest.indexed_snippet_count,
        "admitted_candidate_count": index_manifest.admitted_candidate_count,
        "protected_identifier_count": index_manifest.protected_identifier_count,
        "parser_warning_class_count": len(parsed.warning_counts),
        "parser_warning_occurrence_count": sum(parsed.warning_counts.values()),
        "authorized_result_count": len(authorized_result.citations),
        "denied_result_count": len(denied_result.citations),
        "missing_source_inventory_binding_count": 0,
        "missing_source_local_key_binding_count": 0,
        "missing_content_hash_binding_count": 0,
        "missing_permission_binding_count": 0,
        "unexplained_loss_count": 0,
        "blocker_count": 0,
    }
    retrieval_snapshot: dict[str, Any] = {
        "artifact_id": NATIVE_RETRIEVAL_SNAPSHOT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": "retrieval_ready_evidence_not_canonical_fact",
        "source_snapshot_fingerprint": source_snapshot["snapshot_fingerprint"],
        "source_asset_sha256": source_snapshot["source_asset_sha256"],
        "native_manifest_fingerprint": source_snapshot["native_manifest_fingerprint"],
        "source_inventory_fingerprint": sha256_json(source_snapshot["source_inventory"]),
        "source_provenance_fingerprint": provenance_fingerprint,
        "permission_fingerprint": source_snapshot["permission_fingerprint"],
        "parsed_observation_fingerprint": sha256_json(
            [observation.to_dict() for observation in parsed_observations]
        ),
        "mail_evidence_bundle_fingerprint": bundle_fingerprint,
        "tokenizer_profile_fingerprint": tokenizer_profile.profile_fingerprint,
        "observation_snapshot_fingerprint": (index_manifest.observation_snapshot_fingerprint),
        "candidate_manifest_fingerprint": (index_manifest.candidate_manifest_fingerprint),
        "index_fingerprint": index_manifest.index_fingerprint,
        "query_fingerprint": sha256_json(query_text),
        "authorized_result_fingerprint": sha256_json(authorized_result.to_dict()),
        "denied_result_fingerprint": sha256_json(denied_result.to_dict()),
        "created_at": resolved_created_at,
        "source_inventory": source_snapshot["source_inventory"],
        "source_occurrence_observations": source_snapshot["observations"],
        "parsed_mail_observations": [observation.to_dict() for observation in parsed_observations],
        "index_build_manifest": index_manifest.to_safe_dict(),
        "parser_warning_counts": parsed.warning_counts,
        "counts": retrieval_counts,
        "blocker_fingerprints": [],
    }
    retrieval_snapshot["snapshot_fingerprint"] = _payload_fingerprint(
        retrieval_snapshot,
        "snapshot_fingerprint",
    )
    _validate_native_retrieval_snapshot(retrieval_snapshot)
    persisted_retrieval_snapshot = _persist_immutable(
        retrieval_snapshot_output,
        retrieval_snapshot,
        fingerprint_field="snapshot_fingerprint",
    )

    report: dict[str, Any] = {
        "artifact_id": NATIVE_RETRIEVAL_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "source_completeness_status": "passed",
        "retrieval_ready_status": "passed",
        "bundle_round_trip_status": "passed",
        "query_evidence_profile_binding_status": "passed",
        "target_profile_status": "passed_no_ascii_fallback",
        "authorized_query_status": "passed",
        "denied_query_status": "passed_fail_closed",
        "canonical_fact_status": "not_asserted",
        "methodology_readiness_status": "blocked",
        "source_asset_fingerprint": source_snapshot["source_asset_sha256"],
        "native_manifest_fingerprint": source_snapshot["native_manifest_fingerprint"],
        "source_snapshot_fingerprint": source_snapshot["snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(source_snapshot["source_inventory"]),
        "source_provenance_fingerprint": provenance_fingerprint,
        "permission_fingerprint": source_snapshot["permission_fingerprint"],
        "parsed_observation_fingerprint": persisted_retrieval_snapshot[
            "parsed_observation_fingerprint"
        ],
        "mail_evidence_bundle_fingerprint": bundle_fingerprint,
        "candidate_admission_profile_fingerprint": (tokenizer_profile.profile_fingerprint),
        "observation_snapshot_fingerprint": (index_manifest.observation_snapshot_fingerprint),
        "candidate_manifest_fingerprint": (index_manifest.candidate_manifest_fingerprint),
        "index_fingerprint": index_manifest.index_fingerprint,
        "query_fingerprint": sha256_json(query_text),
        "authorized_result_fingerprint": sha256_json(authorized_result.to_dict()),
        "authorized_cited_observation_fingerprint": sha256_json(expected_source_observation_id),
        "denied_result_fingerprint": sha256_json(denied_result.to_dict()),
        "retrieval_snapshot_fingerprint": persisted_retrieval_snapshot["snapshot_fingerprint"],
        "bundle_artifact_fingerprint": persisted_bundle["artifact_fingerprint"],
        "counts": retrieval_counts,
        "blocker_fingerprints": [],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    _validate_native_retrieval_report(report)
    persisted_report = _persist_immutable(
        report_output,
        report,
        fingerprint_field="report_fingerprint",
    )
    return NativeRetrievalReadyArtifacts(
        source_snapshot=source_snapshot,
        retrieval_snapshot=persisted_retrieval_snapshot,
        bundle=persisted_bundle,
        report=persisted_report,
    )


def run_native_source_complete_snapshot(
    *,
    native_manifest_path: Path,
    native_export_root: Path,
    preserved_work_dir: Path,
    snapshot_output: Path,
    report_output: Path,
    created_at: str | None = None,
    _validated_manifest: Mapping[str, Any] | None = None,
) -> SnapshotRebindArtifacts:
    """Build a new authorized snapshot directly from native source lineage.

    This path intentionally does not load, mutate, or attempt to repair the old
    Observation snapshot. The governed Asset record supplies authorization and
    provenance only when its content hash exactly matches the native manifest.
    """

    manifest = (
        dict(_validated_manifest)
        if _validated_manifest is not None
        else _load_native_private_manifest(
            native_manifest_path,
            export_root=native_export_root,
        )
    )
    asset, asset_binding_fingerprint = _load_governed_asset_binding(
        preserved_work_dir=preserved_work_dir,
        source_asset_sha256=str(manifest["source_asset_sha256"]),
    )
    snapshot_created_at = _snapshot_created_at(created_at)
    parser_fingerprint = _native_parser_fingerprint(manifest)
    extractor_run_id = stable_extractor_run_id(
        asset_id=asset.asset_id,
        extractor_name="libpst_native_lineage_readpst",
        extractor_version="libpst-0.6.76",
        extractor_type="mail_archive_native_lineage",
        input_hash=str(manifest["source_asset_sha256"]),
        config_hash=parser_fingerprint,
    )
    permission_scope = (
        asset.permission_scope.to_dict()
        if hasattr(asset.permission_scope, "to_dict")
        else dict(asset.permission_scope)
    )
    permission_fingerprint = sha256_json(permission_scope)
    source_ref = (
        asset.source_ref.to_dict()
        if hasattr(asset.source_ref, "to_dict")
        else dict(asset.source_ref or {})
    )

    (
        source_inventory,
        observations,
        lineage_rollups,
        counts,
    ) = _build_native_authorized_records(
        manifest=manifest,
        asset=asset,
        permission_scope=permission_scope,
        permission_fingerprint=permission_fingerprint,
        parser_fingerprint=parser_fingerprint,
        extractor_run_id=extractor_run_id,
        created_at=snapshot_created_at,
    )

    blocker_ids: list[str] = []
    if int(counts["unexplained_loss_count"]):
        blocker_ids.append("native_snapshot_unexplained_loss")
    if int(counts["missing_source_inventory_binding_count"]):
        blocker_ids.append("native_snapshot_inventory_binding_missing")
    if int(counts["missing_parent_lineage_count"]):
        blocker_ids.append("native_snapshot_parent_lineage_missing")
    if int(counts["missing_content_hash_count"]):
        blocker_ids.append("native_snapshot_content_hash_missing")
    if int(counts["failed_record_count"]):
        blocker_ids.append("native_snapshot_failed_record_present")
    blocker_ids = sorted(set(blocker_ids))
    status = "passed" if not blocker_ids else "blocked"

    snapshot: dict[str, Any] = {
        "artifact_id": NATIVE_AUTHORIZED_SNAPSHOT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "claim_boundary_status": "observation_evidence_not_canonical_fact",
        "source_asset_sha256": manifest["source_asset_sha256"],
        "native_manifest_fingerprint": manifest["manifest_fingerprint"],
        "asset_binding_fingerprint": asset_binding_fingerprint,
        "permission_fingerprint": permission_fingerprint,
        "source_ref_fingerprint": sha256_json(source_ref),
        "parser_fingerprint": parser_fingerprint,
        "extractor_run_binding": {
            "extractor_run_id": extractor_run_id,
            "extractor_name": "libpst_native_lineage_readpst",
            "extractor_version": "libpst-0.6.76",
            "extractor_type": "mail_archive_native_lineage",
            "input_hash": manifest["source_asset_sha256"],
            "config_hash": parser_fingerprint,
            "parser_source_commit_fingerprint": sha256_json(manifest["parser_source_commit"]),
            "parser_binary_sha256": manifest["parser_binary_sha256"],
            "runtime_library_sha256": manifest["runtime_library_sha256"],
            "parser_config_fingerprint": manifest["parser_config_fingerprint"],
            "sidecar_sha256": manifest["sidecar_sha256"],
            "execution_time_status": "not_recorded_by_native_manifest",
        },
        "authorization_binding": {
            "source_asset_id": asset.asset_id,
            "asset_binding_fingerprint": asset_binding_fingerprint,
            "owner_user_id": asset.owner_user_id,
            "workspace_id": asset.workspace_id,
            "project_id": asset.project_id,
            "permission_scope": permission_scope,
            "permission_fingerprint": permission_fingerprint,
            "source_ref": source_ref,
            "source_ref_fingerprint": sha256_json(source_ref),
            "source_registered_at": asset.registered_at,
        },
        "created_at": snapshot_created_at,
        "source_inventory": source_inventory.to_dict(),
        "observations": [observation.to_dict() for observation in observations],
        "lineage_rollups": lineage_rollups,
        "counts": counts,
        "blocker_fingerprints": [sha256_json(blocker_id) for blocker_id in blocker_ids],
    }
    snapshot["snapshot_fingerprint"] = _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    )
    _validate_native_authorized_snapshot(snapshot)
    persisted_snapshot = _persist_immutable(
        snapshot_output,
        snapshot,
        fingerprint_field="snapshot_fingerprint",
    )

    report: dict[str, Any] = {
        "artifact_id": NATIVE_AUTHORIZED_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source_completeness_gate_status": ("eligible" if status == "passed" else "blocked"),
        "claim_boundary_status": "source_complete_observation_snapshot_only",
        "methodology_readiness_status": "blocked",
        "canonical_fact_status": "not_asserted",
        "source_asset_sha256": persisted_snapshot["source_asset_sha256"],
        "native_manifest_fingerprint": persisted_snapshot["native_manifest_fingerprint"],
        "asset_binding_fingerprint": persisted_snapshot["asset_binding_fingerprint"],
        "permission_fingerprint": persisted_snapshot["permission_fingerprint"],
        "source_ref_fingerprint": persisted_snapshot["source_ref_fingerprint"],
        "parser_fingerprint": persisted_snapshot["parser_fingerprint"],
        "source_inventory_fingerprint": sha256_json(persisted_snapshot["source_inventory"]),
        "observation_snapshot_fingerprint": sha256_json(persisted_snapshot["observations"]),
        "message_lineage_fingerprint": persisted_snapshot["lineage_rollups"][
            "message_lineage_fingerprint"
        ],
        "attachment_lineage_fingerprint": persisted_snapshot["lineage_rollups"][
            "attachment_lineage_fingerprint"
        ],
        "folder_lineage_fingerprint": persisted_snapshot["lineage_rollups"][
            "folder_lineage_fingerprint"
        ],
        "unsupported_lineage_fingerprint": persisted_snapshot["lineage_rollups"][
            "unsupported_lineage_fingerprint"
        ],
        "snapshot_fingerprint": persisted_snapshot["snapshot_fingerprint"],
        "blocker_fingerprints": persisted_snapshot["blocker_fingerprints"],
        "round_trip_status": "passed",
        "counts": persisted_snapshot["counts"],
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    _validate_native_authorized_report(report)
    persisted_report = _persist_immutable(
        report_output,
        report,
        fingerprint_field="report_fingerprint",
    )
    return SnapshotRebindArtifacts(
        snapshot=persisted_snapshot,
        report=persisted_report,
    )


def run_source_complete_snapshot_rebind(
    *,
    pst_path: Path,
    preserved_work_dir: Path,
    output_root: Path,
    snapshot_output: Path,
    report_output: Path,
    lspst_command: str = "lspst",
    parser_manifest_path: Path | None = None,
) -> SnapshotRebindArtifacts:
    output_root.mkdir(parents=True, exist_ok=True)
    source_artifacts = reconciliation.run_full_pst_source_reconciliation(
        pst_path=pst_path,
        preserved_work_dir=preserved_work_dir,
        oracle_output=output_root / "raw-oracle.json",
        observation_output=output_root / "observation-manifest.json",
        report_output=output_root / "source-reconciliation.json",
        lspst_command=lspst_command,
    )
    private_binding = _load_private_binding(
        preserved_work_dir=preserved_work_dir,
        source_asset_sha256=source_artifacts.oracle_manifest["source_asset_sha256"],
    )
    folder_mapping = _unique_folder_mapping(
        oracle_folders=source_artifacts.oracle_manifest["folders"],
        observation_folders=source_artifacts.observation_manifest["folders"],
        oracle_messages=source_artifacts.oracle_manifest["messages"],
        observation_messages=source_artifacts.observation_manifest["messages"],
    )
    rebindings, stage_counts, unmatched_raw, unmatched_observations = _build_unique_rebindings(
        folder_mapping=folder_mapping,
        oracle_messages=source_artifacts.oracle_manifest["messages"],
        observation_messages=source_artifacts.observation_manifest["messages"],
    )
    parser_manifest = (
        _load_parser_manifest(
            parser_manifest_path,
            source_asset_sha256=source_artifacts.oracle_manifest["source_asset_sha256"],
        )
        if parser_manifest_path is not None
        else None
    )
    if parser_manifest is None:
        source_inventory, rebound_entries = _build_source_inventory(
            oracle_manifest=source_artifacts.oracle_manifest,
            rebindings=rebindings,
            private_binding=private_binding,
        )
        attachment_counts = _attachment_lineage_counts(
            preserved_work_dir=preserved_work_dir,
            rebound_observation_occurrence_fingerprints={
                entry["observation_occurrence_fingerprint"] for entry in rebound_entries
            },
        )
        parser_counts: dict[str, int] = {}
        attachment_rebound_entries: list[dict[str, str]] = []
        gap_forensics: dict[str, Any] | None = None
    else:
        (
            source_inventory,
            rebound_entries,
            attachment_rebound_entries,
            attachment_counts,
            parser_counts,
            gap_forensics,
        ) = _build_parser_backed_source_inventory(
            parser_manifest=parser_manifest,
            oracle_manifest=source_artifacts.oracle_manifest,
            observation_manifest=source_artifacts.observation_manifest,
            folder_mapping=folder_mapping,
            preserved_work_dir=preserved_work_dir,
            private_binding=private_binding,
        )

    observed_message_count = int(source_artifacts.observation_manifest["counts"]["message_count"])
    raw_message_count = int(source_artifacts.oracle_manifest["counts"]["message_count"])
    source_gap_repaired_count = len(rebound_entries)
    source_gap_remaining_count = observed_message_count - source_gap_repaired_count
    blocker_codes = []
    if parser_manifest is None:
        if unmatched_raw:
            blocker_codes.append("raw_occurrence_identity_not_uniquely_rebound")
        if unmatched_observations:
            blocker_codes.append("observation_identity_not_uniquely_rebound")
        if source_gap_remaining_count:
            blocker_codes.append("source_inventory_lineage_still_missing")
        if attachment_counts["attachment_inventory_gap_count"]:
            blocker_codes.append("attachment_export_manifest_missing")
    else:
        if parser_manifest["status"] != "passed":
            blocker_codes.append("parser_export_manifest_blocked")
        if parser_counts["unsupported_main_record_count"]:
            blocker_codes.append("parser_export_unsupported_main_record")
        if parser_counts["unmatched_raw_parser_message_count"]:
            blocker_codes.append("raw_occurrence_not_bound_to_parser_export")
        if parser_counts["unmatched_parser_raw_message_count"]:
            blocker_codes.append("parser_message_not_bound_to_raw_occurrence")
        if parser_counts["unmatched_parser_message_count"]:
            blocker_codes.append("parser_message_not_bound_to_observation")
        if parser_counts["unmatched_observation_message_count"]:
            blocker_codes.append("observation_not_bound_to_parser_message")
        if parser_counts["raw_parser_export_record_count_gap"]:
            blocker_codes.append("raw_oracle_parser_message_count_mismatch")
        if source_gap_remaining_count:
            blocker_codes.append("source_inventory_lineage_still_missing")
        if attachment_counts["attachment_inventory_gap_count"]:
            blocker_codes.append("attachment_observation_not_bound_to_parser_manifest")
        if attachment_counts["unmatched_parser_attachment_count"]:
            blocker_codes.append("parser_attachment_not_bound_to_observation")
        if gap_forensics["status"] != "passed":
            blocker_codes.append("source_native_occurrence_identity_capability_missing")
    if source_artifacts.report["counts"]["raw_only_message_identity_count"]:
        blocker_codes.append("raw_only_identity_unexplained")
    if source_artifacts.report["counts"]["observation_only_message_identity_count"]:
        blocker_codes.append("observation_only_identity_unexplained")
    blocker_codes = sorted(set(blocker_codes))

    snapshot: dict[str, Any] = {
        "artifact_id": SNAPSHOT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not blocker_codes else "blocked",
        "source_asset_sha256": source_artifacts.oracle_manifest["source_asset_sha256"],
        "raw_oracle_manifest_fingerprint": source_artifacts.oracle_manifest["manifest_fingerprint"],
        "observation_manifest_fingerprint": (
            source_artifacts.observation_manifest["manifest_fingerprint"]
        ),
        "prior_reconciliation_report_fingerprint": source_artifacts.report["report_fingerprint"],
        "rebind_policy_fingerprint": sha256_json(REBIND_POLICY_ID),
        "folder_mapping_fingerprint": sha256_json(
            [
                {
                    "raw_folder_ordinal": raw_ordinal,
                    "observation_folder_ordinal": observation_ordinal,
                }
                for raw_ordinal, observation_ordinal in sorted(folder_mapping.items())
            ]
        ),
        "source_inventory": source_inventory.to_dict(),
        "rebindings": rebound_entries,
        "counts": {
            "raw_message_count": raw_message_count,
            "observed_message_count": observed_message_count,
            "raw_source_inventory_item_count": len(source_inventory.items),
            "parsed_rebound_message_count": source_gap_repaired_count,
            "preserved_unparsed_raw_message_count": (
                len(unmatched_raw)
                if parser_manifest is None
                else parser_counts["raw_parser_export_record_count_gap"]
            ),
            "unrebound_observation_count": (
                len(unmatched_observations)
                if parser_manifest is None
                else parser_counts["unmatched_observation_message_count"]
            ),
            "source_inventory_gap_repaired_count": source_gap_repaired_count,
            "source_inventory_gap_remaining_count": (source_gap_remaining_count),
            "subject_unique_rebind_count": stage_counts["subject_unique"],
            "subject_sender_day_unique_rebind_count": stage_counts["subject_sender_day_unique"],
            "subject_sender_unique_rebind_count": stage_counts["subject_sender_unique"],
            "subject_day_unique_rebind_count": stage_counts["subject_day_unique"],
            **parser_counts,
            **attachment_counts,
        },
        "blocker_fingerprints": sorted(sha256_json(code) for code in blocker_codes),
        "next_required_parser_contract_fingerprint": sha256_json(NEXT_PARSER_CONTRACT),
    }
    if parser_manifest is not None:
        snapshot["parser_export_manifest_fingerprint"] = parser_manifest["manifest_fingerprint"]
        snapshot["attachment_rebindings"] = attachment_rebound_entries
        snapshot["gap_forensics"] = gap_forensics
    snapshot["snapshot_fingerprint"] = _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    )
    persisted_snapshot = _persist_immutable(
        snapshot_output,
        snapshot,
        fingerprint_field="snapshot_fingerprint",
    )

    report: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": persisted_snapshot["status"],
        "source_completeness_gate_status": (
            "eligible" if persisted_snapshot["status"] == "passed" else "blocked"
        ),
        "source_asset_sha256": persisted_snapshot["source_asset_sha256"],
        "snapshot_fingerprint": persisted_snapshot["snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(persisted_snapshot["source_inventory"]),
        "rebind_policy_fingerprint": persisted_snapshot["rebind_policy_fingerprint"],
        "rebind_rollup_fingerprint": sha256_json(persisted_snapshot["rebindings"]),
        "next_required_parser_contract_fingerprint": persisted_snapshot[
            "next_required_parser_contract_fingerprint"
        ],
        "blocker_fingerprints": persisted_snapshot["blocker_fingerprints"],
        "round_trip_status": {
            "raw_oracle": "passed",
            "observation_manifest": "passed",
            "source_inventory_snapshot": "passed",
            "public_report": "passed",
        },
        "counts": {
            **persisted_snapshot["counts"],
            "raw_only_message_identity_count": source_artifacts.report["counts"][
                "raw_only_message_identity_count"
            ],
            "observation_only_message_identity_count": (
                source_artifacts.report["counts"]["observation_only_message_identity_count"]
            ),
            "attachment_oracle_capability_gap_count": (
                source_artifacts.report["counts"]["attachment_oracle_capability_gap_count"]
            ),
            "blocker_count": len(blocker_codes),
        },
    }
    if parser_manifest is not None:
        report["parser_export_manifest_fingerprint"] = persisted_snapshot[
            "parser_export_manifest_fingerprint"
        ]
        report["attachment_rebind_rollup_fingerprint"] = sha256_json(
            persisted_snapshot["attachment_rebindings"]
        )
        report["gap_forensics_fingerprint"] = persisted_snapshot["gap_forensics"][
            "forensics_fingerprint"
        ]
        report["required_source_capture_capability_fingerprint"] = persisted_snapshot[
            "gap_forensics"
        ]["required_source_capture_capability_fingerprint"]
        report["gap_forensics_status"] = persisted_snapshot["gap_forensics"]["status"]
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    _validate_public_report(report)
    persisted_report = _persist_immutable(
        report_output,
        report,
        fingerprint_field="report_fingerprint",
    )
    return SnapshotRebindArtifacts(
        snapshot=persisted_snapshot,
        report=persisted_report,
    )


def _load_parser_manifest(
    path: Path,
    *,
    source_asset_sha256: str,
) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("artifact_id") != "formowl_issue56_pst_parser_export_private_manifest_v1":
        raise RuntimeError("parser_export_manifest_artifact_invalid")
    if manifest.get("source_asset_sha256") != source_asset_sha256:
        raise RuntimeError("parser_export_manifest_asset_binding_mismatch")
    if manifest.get("manifest_fingerprint") != _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    ):
        raise RuntimeError("parser_export_manifest_fingerprint_invalid")
    if not isinstance(manifest.get("messages"), list):
        raise RuntimeError("parser_export_manifest_messages_invalid")
    return manifest


def _load_native_private_manifest(
    path: Path,
    *,
    export_root: Path,
) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("artifact_id") != NATIVE_PRIVATE_MANIFEST_ARTIFACT_ID:
        raise RuntimeError("native_private_manifest_artifact_invalid")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("native_private_manifest_schema_invalid")
    if manifest.get("status") != "passed":
        raise RuntimeError("native_private_manifest_not_passed")
    for field in (
        "source_asset_sha256",
        "parser_binary_sha256",
        "runtime_library_sha256",
        "parser_config_fingerprint",
        "sidecar_sha256",
        "manifest_fingerprint",
    ):
        if not _FINGERPRINT_RE.fullmatch(str(manifest.get(field, ""))):
            raise RuntimeError(f"native_private_manifest_{field}_invalid")
    parser_config = manifest.get("parser_config")
    if not isinstance(parser_config, dict):
        raise RuntimeError("native_private_manifest_parser_config_invalid")
    if manifest["parser_config_fingerprint"] != _native_manifest_sha256_json(parser_config):
        raise RuntimeError("native_private_manifest_parser_config_drift")
    if manifest["manifest_fingerprint"] != _native_manifest_payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    ):
        raise RuntimeError("native_private_manifest_fingerprint_invalid")
    if (
        not isinstance(manifest.get("parser_source_commit"), str)
        or not manifest["parser_source_commit"]
    ):
        raise RuntimeError("native_private_manifest_parser_source_commit_invalid")
    if manifest.get("blocker_ids") != []:
        raise RuntimeError("native_private_manifest_blocked")

    messages = manifest.get("messages")
    unsupported_records = manifest.get("unsupported_non_message_records")
    counts = manifest.get("counts")
    if not isinstance(messages, list):
        raise RuntimeError("native_private_manifest_messages_invalid")
    if not isinstance(unsupported_records, list):
        raise RuntimeError("native_private_manifest_unsupported_records_invalid")
    if not isinstance(counts, dict) or any(
        not isinstance(value, int) or isinstance(value, bool) for value in counts.values()
    ):
        raise RuntimeError("native_private_manifest_counts_invalid")
    expected_count_fields = {
        "message_occurrence_count",
        "message_exported_count",
        "message_unexplained_count",
        "attachment_output_occurrence_count",
        "attachment_nonzero_node_id_count",
        "attachment_embedded_message_count",
        "attachment_synthetic_representation_count",
        "duplicate_attachment_identity_count",
        "unsupported_non_message_record_count",
        "failed_record_count",
    }
    if set(counts) != expected_count_fields:
        raise RuntimeError("native_private_manifest_count_fields_invalid")

    export_root = export_root.resolve()
    if not export_root.is_dir():
        raise RuntimeError("native_export_root_unavailable")
    referenced_outputs: set[str] = set()
    message_source_keys: set[str] = set()
    attachment_source_keys: set[str] = set()
    attachment_count = 0
    attachment_nonzero_node_count = 0
    embedded_message_count = 0
    synthetic_representation_count = 0
    duplicate_attachment_identity_count = 0
    for message in messages:
        if not isinstance(message, dict):
            raise RuntimeError("native_private_manifest_message_invalid")
        source_local_key = _native_source_local_key(
            message.get("source_local_key"),
            expected_kind="message",
        )
        if source_local_key in message_source_keys:
            raise RuntimeError("native_private_manifest_message_key_duplicate")
        message_source_keys.add(source_local_key)
        _native_node_id(message.get("pst_folder_node_id"), "folder")
        _native_node_id(message.get("pst_message_node_id"), "message")
        _native_node_id(message.get("pst_message_data_node_id"), "message_data")
        if (
            message.get("export_disposition") != "exported"
            or message.get("export_status") != "passed"
            or message.get("export_reason") != "none"
        ):
            raise RuntimeError("native_private_manifest_message_export_invalid")
        _native_fingerprint(message.get("message_content_hash"), "message_content_hash")
        _native_nonnegative_int(message.get("byte_count"), "message_byte_count")
        relative_output = _native_export_relative_output(
            message.get("relative_output_path"),
            allow_missing=False,
        )
        _validate_native_export_file(
            export_root=export_root,
            relative_output=relative_output,
            expected_hash=str(message["message_content_hash"]),
            expected_byte_count=int(message["byte_count"]),
        )
        if relative_output in referenced_outputs:
            raise RuntimeError("native_private_manifest_output_reused")
        referenced_outputs.add(relative_output)

        attachments = message.get("attachments")
        if not isinstance(attachments, list):
            raise RuntimeError("native_private_manifest_attachments_invalid")
        attachment_identity_counts: Counter[tuple[str, str, str]] = Counter()
        for attachment in attachments:
            if not isinstance(attachment, dict):
                raise RuntimeError("native_private_manifest_attachment_invalid")
            attachment_count += 1
            attachment_source_local_key = _native_source_local_key(
                attachment.get("source_local_key"),
                expected_kind="attachment",
            )
            if (
                attachment_source_local_key in message_source_keys
                or attachment_source_local_key in attachment_source_keys
            ):
                raise RuntimeError("native_private_manifest_attachment_key_duplicate")
            attachment_source_keys.add(attachment_source_local_key)
            attachment_node_id = _native_node_id(
                attachment.get("pst_attachment_node_id"),
                "attachment",
            )
            attachment_nonzero_node_count += int(attachment_node_id != "0000000000000000")
            disposition = attachment.get("export_disposition")
            if disposition not in {
                "separate_exported",
                "embedded_message_exported",
                "synthetic_body_exported",
            }:
                raise RuntimeError("native_private_manifest_attachment_disposition_invalid")
            if (
                attachment.get("export_status") != "passed"
                or attachment.get("export_reason") != "none"
            ):
                raise RuntimeError("native_private_manifest_attachment_export_invalid")
            embedded_message_count += int(disposition == "embedded_message_exported")
            synthetic_representation_count += int(disposition == "synthetic_body_exported")
            _native_fingerprint(
                attachment.get("attachment_content_hash"),
                "attachment_content_hash",
            )
            attachment_identity_counts[
                (
                    attachment_node_id,
                    str(disposition),
                    str(attachment["attachment_content_hash"]),
                )
            ] += 1
            _native_nonnegative_int(
                attachment.get("byte_count"),
                "attachment_byte_count",
            )
            _native_positive_int(
                attachment.get("export_occurrence_ordinal"),
                "attachment_export_occurrence_ordinal",
            )
            relative_attachment_output = _native_export_relative_output(
                attachment.get("relative_output_path"),
                allow_missing=disposition == "embedded_message_exported",
            )
            if relative_attachment_output is None:
                if disposition != "embedded_message_exported":
                    raise RuntimeError("native_private_manifest_attachment_output_missing")
                continue
            _validate_native_export_file(
                export_root=export_root,
                relative_output=relative_attachment_output,
                expected_hash=str(attachment["attachment_content_hash"]),
                expected_byte_count=int(attachment["byte_count"]),
            )
            if relative_attachment_output in referenced_outputs:
                raise RuntimeError("native_private_manifest_output_reused")
            referenced_outputs.add(relative_attachment_output)
        duplicate_attachment_identity_count += sum(
            count - 1 for count in attachment_identity_counts.values() if count > 1
        )

    for record in unsupported_records:
        if not isinstance(record, dict):
            raise RuntimeError("native_private_manifest_unsupported_record_invalid")
        _native_node_id(record.get("pst_folder_node_id"), "unsupported_folder")
        _native_node_id(record.get("pst_record_node_id"), "unsupported_record")
        _native_node_id(
            record.get("pst_record_data_node_id"),
            "unsupported_record_data",
        )
        if (
            record.get("export_disposition") != "not_exported"
            or record.get("export_status") != "passed"
            or record.get("export_reason") != "unsupported_item_type"
        ):
            raise RuntimeError("native_private_manifest_unsupported_record_state_invalid")

    actual_outputs = {
        candidate.relative_to(export_root).as_posix()
        for candidate in export_root.rglob("*")
        if candidate.is_file()
    }
    if actual_outputs != referenced_outputs:
        raise RuntimeError("native_private_manifest_export_coverage_mismatch")
    if counts["message_occurrence_count"] != len(messages):
        raise RuntimeError("native_private_manifest_message_count_drift")
    if counts["message_exported_count"] != len(messages):
        raise RuntimeError("native_private_manifest_exported_message_count_drift")
    if counts["message_unexplained_count"] != 0:
        raise RuntimeError("native_private_manifest_unexplained_message_present")
    if counts["attachment_output_occurrence_count"] != attachment_count:
        raise RuntimeError("native_private_manifest_attachment_count_drift")
    if counts["attachment_nonzero_node_id_count"] != attachment_nonzero_node_count:
        raise RuntimeError("native_private_manifest_attachment_node_count_drift")
    if counts["attachment_embedded_message_count"] != embedded_message_count:
        raise RuntimeError("native_private_manifest_embedded_message_count_drift")
    if counts["attachment_synthetic_representation_count"] != synthetic_representation_count:
        raise RuntimeError("native_private_manifest_synthetic_representation_count_drift")
    if counts["duplicate_attachment_identity_count"] != duplicate_attachment_identity_count:
        raise RuntimeError("native_private_manifest_duplicate_attachment_identity_count_drift")
    if counts["unsupported_non_message_record_count"] != len(unsupported_records):
        raise RuntimeError("native_private_manifest_unsupported_count_drift")
    if counts["failed_record_count"] != 0:
        raise RuntimeError("native_private_manifest_failed_record_present")
    return manifest


def _load_governed_asset_binding(
    *,
    preserved_work_dir: Path,
    source_asset_sha256: str,
) -> tuple[Asset, str]:
    ingestion_root = preserved_work_dir / "data" / "ingestion"
    matching_assets = [
        row
        for row in reconciliation._read_json_files(ingestion_root / "assets")
        if row.get("content_hash") == source_asset_sha256
    ]
    if len(matching_assets) != 1:
        raise RuntimeError("source_asset_binding_unavailable")
    asset = Asset.from_dict(matching_assets[0])
    if asset.content_hash != source_asset_sha256:
        raise RuntimeError("source_asset_binding_hash_mismatch")
    if asset.source_ref is None:
        raise RuntimeError("source_provenance_binding_unavailable")
    return asset, sha256_json(asset.to_dict())


def _snapshot_created_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("native_snapshot_created_at_invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("native_snapshot_created_at_timezone_missing")
    return value


def _native_parser_fingerprint(manifest: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            "parser_source_commit": manifest["parser_source_commit"],
            "parser_binary_sha256": manifest["parser_binary_sha256"],
            "runtime_library_sha256": manifest["runtime_library_sha256"],
            "parser_config_fingerprint": manifest["parser_config_fingerprint"],
            "sidecar_sha256": manifest["sidecar_sha256"],
        }
    )


def _build_native_authorized_records(
    *,
    manifest: Mapping[str, Any],
    asset: Asset,
    permission_scope: Mapping[str, Any],
    permission_fingerprint: str,
    parser_fingerprint: str,
    extractor_run_id: str,
    created_at: str,
) -> tuple[
    SourceInventory,
    list[Observation],
    dict[str, str],
    dict[str, int],
]:
    source_fingerprint = str(manifest["source_asset_sha256"])
    messages = sorted(
        list(manifest["messages"]),
        key=lambda message: str(message["source_local_key"]),
    )
    unsupported_records = sorted(
        list(manifest["unsupported_non_message_records"]),
        key=lambda record: (
            str(record["pst_folder_node_id"]),
            str(record["pst_record_node_id"]),
            str(record["pst_record_data_node_id"]),
        ),
    )
    folder_node_ids = sorted(
        {str(message["pst_folder_node_id"]) for message in messages}
        | {str(record["pst_folder_node_id"]) for record in unsupported_records}
    )
    folder_source_keys = {
        folder_node_id: stable_resource_contract_id(
            "pstfolder",
            "Issue56PstNativeFolderOccurrence",
            {
                "source_asset_sha256": source_fingerprint,
                "pst_folder_node_id": folder_node_id,
            },
        )
        for folder_node_id in folder_node_ids
    }
    unsupported_source_keys = {
        (
            str(record["pst_folder_node_id"]),
            str(record["pst_record_node_id"]),
            str(record["pst_record_data_node_id"]),
        ): stable_resource_contract_id(
            "pstunsupported",
            "Issue56PstNativeUnsupportedOccurrence",
            {
                "source_asset_sha256": source_fingerprint,
                "pst_folder_node_id": record["pst_folder_node_id"],
                "pst_record_node_id": record["pst_record_node_id"],
                "pst_record_data_node_id": record["pst_record_data_node_id"],
            },
        )
        for record in unsupported_records
    }

    item_specs: list[dict[str, Any]] = []
    for folder_node_id in folder_node_ids:
        item_specs.append(
            {
                "record_kind": "folder",
                "source_local_key": folder_source_keys[folder_node_id],
                "structure_kind": "mail_folder_descriptor_occurrence",
                "content_type": "application/x-libpst-folder-descriptor",
                "processing_state": SourceInventoryProcessingState.PARSED,
                "location": {
                    "source_local_key": folder_source_keys[folder_node_id],
                    "pst_folder_node_id": folder_node_id,
                },
                "record": {"pst_folder_node_id": folder_node_id},
            }
        )
    for message in messages:
        folder_node_id = str(message["pst_folder_node_id"])
        item_specs.append(
            {
                "record_kind": "message",
                "source_local_key": str(message["source_local_key"]),
                "structure_kind": "email_message_occurrence",
                "content_type": "message/rfc822",
                "processing_state": SourceInventoryProcessingState.PARSED,
                "location": {
                    "source_local_key": message["source_local_key"],
                    "parent_source_local_key": folder_source_keys[folder_node_id],
                    "pst_folder_node_id": folder_node_id,
                    "pst_message_node_id": message["pst_message_node_id"],
                    "pst_message_data_node_id": message["pst_message_data_node_id"],
                    "message_content_hash": message["message_content_hash"],
                },
                "record": message,
            }
        )
    for message in messages:
        for attachment in sorted(
            list(message["attachments"]),
            key=lambda row: str(row["source_local_key"]),
        ):
            disposition = str(attachment["export_disposition"])
            structure_kind = {
                "separate_exported": "email_attachment_occurrence",
                "embedded_message_exported": ("email_embedded_message_attachment_occurrence"),
                "synthetic_body_exported": "email_synthetic_body_export_occurrence",
            }[disposition]
            content_type = (
                "message/rfc822"
                if disposition == "embedded_message_exported"
                else "application/octet-stream"
            )
            item_specs.append(
                {
                    "record_kind": "attachment",
                    "source_local_key": str(attachment["source_local_key"]),
                    "structure_kind": structure_kind,
                    "content_type": content_type,
                    "processing_state": SourceInventoryProcessingState.PARSED,
                    "location": {
                        "source_local_key": attachment["source_local_key"],
                        "parent_source_local_key": message["source_local_key"],
                        "pst_folder_node_id": message["pst_folder_node_id"],
                        "pst_message_node_id": message["pst_message_node_id"],
                        "pst_message_data_node_id": message["pst_message_data_node_id"],
                        "pst_attachment_node_id": attachment["pst_attachment_node_id"],
                        "attachment_content_hash": attachment["attachment_content_hash"],
                        "export_occurrence_ordinal": attachment["export_occurrence_ordinal"],
                        "export_disposition": disposition,
                        "content_binding_status": (
                            "export_file_bound"
                            if attachment["relative_output_path"] is not None
                            else "source_descriptor_bound"
                        ),
                    },
                    "record": {
                        **attachment,
                        "parent_message_source_local_key": message["source_local_key"],
                    },
                }
            )
    for record in unsupported_records:
        identity = (
            str(record["pst_folder_node_id"]),
            str(record["pst_record_node_id"]),
            str(record["pst_record_data_node_id"]),
        )
        item_specs.append(
            {
                "record_kind": "unsupported",
                "source_local_key": unsupported_source_keys[identity],
                "structure_kind": "unsupported_pst_record_occurrence",
                "content_type": "application/x-libpst-unsupported-record",
                "processing_state": SourceInventoryProcessingState.UNSUPPORTED,
                "location": {
                    "source_local_key": unsupported_source_keys[identity],
                    "parent_source_local_key": folder_source_keys[identity[0]],
                    "pst_folder_node_id": identity[0],
                    "pst_record_node_id": identity[1],
                    "pst_record_data_node_id": identity[2],
                    "export_disposition": record["export_disposition"],
                    "export_status": record["export_status"],
                    "export_reason": record["export_reason"],
                },
                "record": record,
            }
        )

    inventory_items: list[SourceInventoryItem] = []
    for ordinal, spec in enumerate(item_specs, start=1):
        inventory_items.append(
            SourceInventoryItem.create(
                source_asset_id=asset.asset_id,
                structure_kind=str(spec["structure_kind"]),
                content_type=str(spec["content_type"]),
                ordinal=ordinal,
                processing_state=spec["processing_state"],
                raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
                source_fingerprint=source_fingerprint,
                parser_fingerprint=parser_fingerprint,
                permission_scope=permission_scope,
                location=spec["location"],
            )
        )
    source_inventory = SourceInventory.create(
        source_asset_id=asset.asset_id,
        items=inventory_items,
        source_fingerprint=source_fingerprint,
        parser_fingerprint=parser_fingerprint,
        created_at=created_at,
        permission_fingerprint=permission_fingerprint,
    )
    item_by_source_key = {
        str(item.location["source_local_key"]): item for item in source_inventory.items
    }

    folder_observations: dict[str, Observation] = {}
    message_observations: dict[str, Observation] = {}
    attachment_observations: list[Observation] = []
    unsupported_observations: list[Observation] = []
    for folder_node_id in folder_node_ids:
        source_local_key = folder_source_keys[folder_node_id]
        inventory_item = item_by_source_key[source_local_key]
        observation = _native_observation(
            asset_id=asset.asset_id,
            extractor_run_id=extractor_run_id,
            observation_type="mail_folder_occurrence",
            location={
                "source_local_key": source_local_key,
                "source_inventory_id": source_inventory.source_inventory_id,
                "source_inventory_item_id": inventory_item.source_inventory_item_id,
                "pst_folder_node_id": folder_node_id,
            },
            payload={
                "source_local_key": source_local_key,
                "source_inventory_id": source_inventory.source_inventory_id,
                "source_inventory_item_id": inventory_item.source_inventory_item_id,
                "pst_folder_node_id": folder_node_id,
                "parser_fingerprint": parser_fingerprint,
                "evidence_state": "source_observation",
                "canonical_fact_status": "not_asserted",
            },
            extracted_value={
                "source_native_descriptor_kind": "pst_folder",
                "pst_folder_node_id": folder_node_id,
            },
            permission_scope=permission_scope,
            created_at=created_at,
        )
        folder_observations[folder_node_id] = observation

    for message in messages:
        source_local_key = str(message["source_local_key"])
        inventory_item = item_by_source_key[source_local_key]
        parent_folder_observation = folder_observations[str(message["pst_folder_node_id"])]
        observation = _native_observation(
            asset_id=asset.asset_id,
            extractor_run_id=extractor_run_id,
            observation_type="email_message_occurrence",
            location={
                "source_local_key": source_local_key,
                "source_inventory_id": source_inventory.source_inventory_id,
                "source_inventory_item_id": inventory_item.source_inventory_item_id,
                "parent_folder_observation_id": (parent_folder_observation.observation_id),
                "pst_folder_node_id": message["pst_folder_node_id"],
                "pst_message_node_id": message["pst_message_node_id"],
                "pst_message_data_node_id": message["pst_message_data_node_id"],
            },
            payload={
                "source_local_key": source_local_key,
                "source_inventory_id": source_inventory.source_inventory_id,
                "source_inventory_item_id": inventory_item.source_inventory_item_id,
                "parent_folder_observation_id": (parent_folder_observation.observation_id),
                "message_content_hash": message["message_content_hash"],
                "byte_count": message["byte_count"],
                "export_disposition": message["export_disposition"],
                "export_status": message["export_status"],
                "export_reason": message["export_reason"],
                "parser_fingerprint": parser_fingerprint,
                "evidence_state": "source_observation",
                "canonical_fact_status": "not_asserted",
            },
            extracted_value={
                "content_hash": message["message_content_hash"],
                "content_binding": "native_manifest_source_local_key",
                "source_local_key": source_local_key,
            },
            permission_scope=permission_scope,
            created_at=created_at,
        )
        message_observations[source_local_key] = observation

    for message in messages:
        parent_message = message_observations[str(message["source_local_key"])]
        for attachment in sorted(
            list(message["attachments"]),
            key=lambda row: str(row["source_local_key"]),
        ):
            source_local_key = str(attachment["source_local_key"])
            inventory_item = item_by_source_key[source_local_key]
            attachment_observations.append(
                _native_observation(
                    asset_id=asset.asset_id,
                    extractor_run_id=extractor_run_id,
                    observation_type="email_native_export_occurrence",
                    location={
                        "source_local_key": source_local_key,
                        "source_inventory_id": source_inventory.source_inventory_id,
                        "source_inventory_item_id": (inventory_item.source_inventory_item_id),
                        "parent_message_observation_id": (parent_message.observation_id),
                        "pst_folder_node_id": message["pst_folder_node_id"],
                        "pst_message_node_id": message["pst_message_node_id"],
                        "pst_message_data_node_id": message["pst_message_data_node_id"],
                        "pst_attachment_node_id": attachment["pst_attachment_node_id"],
                        "export_occurrence_ordinal": attachment["export_occurrence_ordinal"],
                    },
                    payload={
                        "source_local_key": source_local_key,
                        "source_inventory_id": source_inventory.source_inventory_id,
                        "source_inventory_item_id": (inventory_item.source_inventory_item_id),
                        "parent_message_observation_id": (parent_message.observation_id),
                        "attachment_content_hash": attachment["attachment_content_hash"],
                        "byte_count": attachment["byte_count"],
                        "export_disposition": attachment["export_disposition"],
                        "export_status": attachment["export_status"],
                        "export_reason": attachment["export_reason"],
                        "content_binding_status": (
                            "export_file_bound"
                            if attachment["relative_output_path"] is not None
                            else "source_descriptor_bound"
                        ),
                        "parser_fingerprint": parser_fingerprint,
                        "evidence_state": "source_observation",
                        "canonical_fact_status": "not_asserted",
                    },
                    extracted_value={
                        "content_hash": attachment["attachment_content_hash"],
                        "content_binding": "native_manifest_source_local_key",
                        "source_local_key": source_local_key,
                    },
                    permission_scope=permission_scope,
                    created_at=created_at,
                )
            )

    for record in unsupported_records:
        identity = (
            str(record["pst_folder_node_id"]),
            str(record["pst_record_node_id"]),
            str(record["pst_record_data_node_id"]),
        )
        source_local_key = unsupported_source_keys[identity]
        inventory_item = item_by_source_key[source_local_key]
        parent_folder = folder_observations[identity[0]]
        unsupported_observations.append(
            _native_observation(
                asset_id=asset.asset_id,
                extractor_run_id=extractor_run_id,
                observation_type="unsupported_pst_record_occurrence",
                location={
                    "source_local_key": source_local_key,
                    "source_inventory_id": source_inventory.source_inventory_id,
                    "source_inventory_item_id": (inventory_item.source_inventory_item_id),
                    "parent_folder_observation_id": parent_folder.observation_id,
                    "pst_folder_node_id": identity[0],
                    "pst_record_node_id": identity[1],
                    "pst_record_data_node_id": identity[2],
                },
                payload={
                    "source_local_key": source_local_key,
                    "source_inventory_id": source_inventory.source_inventory_id,
                    "source_inventory_item_id": (inventory_item.source_inventory_item_id),
                    "parent_folder_observation_id": parent_folder.observation_id,
                    "export_disposition": record["export_disposition"],
                    "export_status": record["export_status"],
                    "export_reason": record["export_reason"],
                    "parser_fingerprint": parser_fingerprint,
                    "evidence_state": "source_observation",
                    "canonical_fact_status": "not_asserted",
                },
                extracted_value={
                    "source_native_descriptor_kind": "unsupported_pst_record",
                    "pst_record_node_id": identity[1],
                    "pst_record_data_node_id": identity[2],
                    "processing_state": "unsupported",
                },
                permission_scope=permission_scope,
                created_at=created_at,
            )
        )

    observations = [
        *[folder_observations[node_id] for node_id in folder_node_ids],
        *[message_observations[str(message["source_local_key"])] for message in messages],
        *attachment_observations,
        *unsupported_observations,
    ]
    lineage_rollups = _native_lineage_rollups(
        source_inventory=source_inventory,
        observations=observations,
    )
    attachment_count = sum(len(message["attachments"]) for message in messages)
    attachment_file_binding_count = sum(
        attachment["relative_output_path"] is not None
        for message in messages
        for attachment in message["attachments"]
    )
    counts = {
        "folder_occurrence_count": len(folder_node_ids),
        "message_occurrence_count": len(messages),
        "message_source_inventory_binding_count": len(messages),
        "message_parent_lineage_count": len(messages),
        "attachment_export_occurrence_count": attachment_count,
        "attachment_source_inventory_binding_count": attachment_count,
        "attachment_parent_lineage_count": attachment_count,
        "attachment_content_hash_count": attachment_count,
        "attachment_export_file_binding_count": attachment_file_binding_count,
        "attachment_source_descriptor_binding_count": (
            attachment_count - attachment_file_binding_count
        ),
        "attachment_separate_export_count": sum(
            attachment["export_disposition"] == "separate_exported"
            for message in messages
            for attachment in message["attachments"]
        ),
        "attachment_embedded_message_count": sum(
            attachment["export_disposition"] == "embedded_message_exported"
            for message in messages
            for attachment in message["attachments"]
        ),
        "attachment_synthetic_representation_count": sum(
            attachment["export_disposition"] == "synthetic_body_exported"
            for message in messages
            for attachment in message["attachments"]
        ),
        "unsupported_preserved_occurrence_count": len(unsupported_records),
        "source_inventory_item_count": len(source_inventory.items),
        "observation_count": len(observations),
        "missing_source_inventory_binding_count": 0,
        "missing_parent_lineage_count": 0,
        "missing_content_hash_count": 0,
        "unexplained_loss_count": 0,
        "failed_record_count": int(manifest["counts"]["failed_record_count"]),
        "blocker_count": 0,
    }
    return source_inventory, observations, lineage_rollups, counts


def _native_observation(
    *,
    asset_id: str,
    extractor_run_id: str,
    observation_type: str,
    location: dict[str, Any],
    payload: dict[str, Any],
    extracted_value: dict[str, Any],
    permission_scope: Mapping[str, Any],
    created_at: str,
) -> Observation:
    observation_id = stable_observation_id(
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        observation_type=observation_type,
        modality="mail",
        location=location,
        payload=payload,
        extracted_value=extracted_value,
    )
    return Observation(
        observation_id=observation_id,
        asset_id=asset_id,
        extractor_run_id=extractor_run_id,
        observation_type=observation_type,
        modality="mail",
        location=location,
        confidence=1.0,
        permission_scope=dict(permission_scope),
        created_at=created_at,
        payload=payload,
        extracted_value=extracted_value,
    )


def _native_lineage_rollups(
    *,
    source_inventory: SourceInventory,
    observations: Sequence[Observation],
) -> dict[str, str]:
    items_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
    rollups: dict[str, list[dict[str, Any]]] = {
        "folder": [],
        "message": [],
        "attachment": [],
        "unsupported": [],
    }
    type_to_rollup = {
        "mail_folder_occurrence": "folder",
        "email_message_occurrence": "message",
        "email_native_export_occurrence": "attachment",
        "unsupported_pst_record_occurrence": "unsupported",
    }
    for observation in observations:
        rollup_name = type_to_rollup[observation.observation_type]
        item_id = str(observation.location["source_inventory_item_id"])
        item = items_by_id[item_id]
        row: dict[str, Any] = {
            "observation_id": observation.observation_id,
            "source_inventory_item_id": item_id,
            "source_local_key": item.location["source_local_key"],
            "permission_fingerprint": item.permission_fingerprint,
        }
        for field in (
            "pst_folder_node_id",
            "pst_message_node_id",
            "pst_message_data_node_id",
            "pst_attachment_node_id",
            "pst_record_node_id",
            "pst_record_data_node_id",
            "message_content_hash",
            "attachment_content_hash",
            "export_occurrence_ordinal",
            "export_disposition",
        ):
            if field in item.location:
                row[field] = item.location[field]
        for field in (
            "parent_folder_observation_id",
            "parent_message_observation_id",
        ):
            if field in observation.location:
                row[field] = observation.location[field]
        rollups[rollup_name].append(row)
    return {
        f"{rollup_name}_lineage_fingerprint": sha256_json(rows)
        for rollup_name, rows in rollups.items()
    }


def _validate_native_authorized_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("artifact_id") != NATIVE_AUTHORIZED_SNAPSHOT_ARTIFACT_ID:
        raise RuntimeError("native_authorized_snapshot_artifact_invalid")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("native_authorized_snapshot_schema_invalid")
    if snapshot.get("status") != "passed":
        raise RuntimeError("native_authorized_snapshot_blocked")
    if snapshot.get("claim_boundary_status") != "observation_evidence_not_canonical_fact":
        raise RuntimeError("native_authorized_snapshot_claim_boundary_invalid")
    if snapshot.get("snapshot_fingerprint") != _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    ):
        raise RuntimeError("native_authorized_snapshot_fingerprint_invalid")
    for field in (
        "source_asset_sha256",
        "native_manifest_fingerprint",
        "asset_binding_fingerprint",
        "permission_fingerprint",
        "source_ref_fingerprint",
        "parser_fingerprint",
        "snapshot_fingerprint",
    ):
        _native_fingerprint(snapshot.get(field), field)
    if snapshot.get("blocker_fingerprints") != []:
        raise RuntimeError("native_authorized_snapshot_blockers_present")
    counts = snapshot.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(value, int) or isinstance(value, bool) for value in counts.values()
    ):
        raise RuntimeError("native_authorized_snapshot_counts_invalid")
    for field in (
        "missing_source_inventory_binding_count",
        "missing_parent_lineage_count",
        "missing_content_hash_count",
        "unexplained_loss_count",
        "failed_record_count",
        "blocker_count",
    ):
        if counts.get(field) != 0:
            raise RuntimeError(f"native_authorized_snapshot_{field}_nonzero")

    source_inventory = SourceInventory.from_dict(snapshot["source_inventory"])
    if source_inventory.source_fingerprint != snapshot["source_asset_sha256"]:
        raise RuntimeError("native_authorized_snapshot_asset_binding_mismatch")
    if source_inventory.parser_fingerprint != snapshot["parser_fingerprint"]:
        raise RuntimeError("native_authorized_snapshot_parser_binding_mismatch")
    if source_inventory.permission_fingerprint != snapshot["permission_fingerprint"]:
        raise RuntimeError("native_authorized_snapshot_permission_binding_mismatch")
    authorization_binding = snapshot.get("authorization_binding")
    if not isinstance(authorization_binding, dict):
        raise RuntimeError("native_authorized_snapshot_authorization_missing")
    if (
        authorization_binding.get("asset_binding_fingerprint")
        != snapshot["asset_binding_fingerprint"]
        or authorization_binding.get("permission_fingerprint") != snapshot["permission_fingerprint"]
    ):
        raise RuntimeError("native_authorized_snapshot_authorization_drift")
    if (
        sha256_json(authorization_binding.get("permission_scope"))
        != snapshot["permission_fingerprint"]
    ):
        raise RuntimeError("native_authorized_snapshot_permission_scope_drift")
    if sha256_json(authorization_binding.get("source_ref")) != snapshot["source_ref_fingerprint"]:
        raise RuntimeError("native_authorized_snapshot_source_ref_drift")
    if authorization_binding.get("source_asset_id") != source_inventory.source_asset_id:
        raise RuntimeError("native_authorized_snapshot_asset_id_drift")

    raw_observations = snapshot.get("observations")
    if not isinstance(raw_observations, list):
        raise RuntimeError("native_authorized_snapshot_observations_invalid")
    observations = [Observation.from_dict(row) for row in raw_observations]
    if len({observation.observation_id for observation in observations}) != len(observations):
        raise RuntimeError("native_authorized_snapshot_observation_id_duplicate")
    item_ids = {item.source_inventory_item_id for item in source_inventory.items}
    observation_item_ids = [
        str(observation.location.get("source_inventory_item_id") or "")
        for observation in observations
    ]
    if set(observation_item_ids) != item_ids or len(observation_item_ids) != len(item_ids):
        raise RuntimeError("native_authorized_snapshot_inventory_coverage_invalid")
    permission_scope = authorization_binding["permission_scope"]
    if any(
        sha256_json(observation.permission_scope) != snapshot["permission_fingerprint"]
        or observation.asset_id != source_inventory.source_asset_id
        or observation.payload is None
        or observation.payload.get("canonical_fact_status") != "not_asserted"
        for observation in observations
    ):
        raise RuntimeError("native_authorized_snapshot_observation_binding_invalid")
    if any(observation.permission_scope != permission_scope for observation in observations):
        raise RuntimeError("native_authorized_snapshot_observation_permission_drift")
    extractor_run_binding = snapshot.get("extractor_run_binding")
    if not isinstance(extractor_run_binding, dict):
        raise RuntimeError("native_authorized_snapshot_extractor_binding_missing")
    if any(
        observation.extractor_run_id != extractor_run_binding.get("extractor_run_id")
        or observation.observation_id
        != stable_observation_id(
            asset_id=observation.asset_id,
            evidence_snapshot_id=observation.evidence_snapshot_id,
            extractor_run_id=observation.extractor_run_id,
            observation_type=observation.observation_type,
            modality=observation.modality,
            location=observation.location,
            text=observation.text,
            caption=observation.caption,
            payload=observation.payload,
            extracted_value=observation.extracted_value,
        )
        for observation in observations
    ):
        raise RuntimeError("native_authorized_snapshot_observation_id_drift")

    folder_ids = {
        observation.observation_id
        for observation in observations
        if observation.observation_type == "mail_folder_occurrence"
    }
    message_ids = {
        observation.observation_id
        for observation in observations
        if observation.observation_type == "email_message_occurrence"
    }
    messages = [
        observation
        for observation in observations
        if observation.observation_type == "email_message_occurrence"
    ]
    attachments = [
        observation
        for observation in observations
        if observation.observation_type == "email_native_export_occurrence"
    ]
    unsupported = [
        observation
        for observation in observations
        if observation.observation_type == "unsupported_pst_record_occurrence"
    ]
    if any(
        observation.location.get("parent_folder_observation_id") not in folder_ids
        for observation in [*messages, *unsupported]
    ):
        raise RuntimeError("native_authorized_snapshot_folder_parent_invalid")
    if any(
        observation.location.get("parent_message_observation_id") not in message_ids
        for observation in attachments
    ):
        raise RuntimeError("native_authorized_snapshot_message_parent_invalid")
    if any(
        not _FINGERPRINT_RE.fullmatch(str(observation.payload.get("message_content_hash", "")))
        for observation in messages
    ):
        raise RuntimeError("native_authorized_snapshot_message_content_hash_invalid")
    if any(
        not _FINGERPRINT_RE.fullmatch(str(observation.payload.get("attachment_content_hash", "")))
        for observation in attachments
    ):
        raise RuntimeError("native_authorized_snapshot_attachment_content_hash_invalid")
    computed_counts = {
        "folder_occurrence_count": len(folder_ids),
        "message_occurrence_count": len(messages),
        "message_source_inventory_binding_count": len(messages),
        "message_parent_lineage_count": len(messages),
        "attachment_export_occurrence_count": len(attachments),
        "attachment_source_inventory_binding_count": len(attachments),
        "attachment_parent_lineage_count": len(attachments),
        "attachment_content_hash_count": len(attachments),
        "attachment_export_file_binding_count": sum(
            observation.payload["content_binding_status"] == "export_file_bound"
            for observation in attachments
        ),
        "attachment_source_descriptor_binding_count": sum(
            observation.payload["content_binding_status"] == "source_descriptor_bound"
            for observation in attachments
        ),
        "attachment_separate_export_count": sum(
            observation.payload["export_disposition"] == "separate_exported"
            for observation in attachments
        ),
        "attachment_embedded_message_count": sum(
            observation.payload["export_disposition"] == "embedded_message_exported"
            for observation in attachments
        ),
        "attachment_synthetic_representation_count": sum(
            observation.payload["export_disposition"] == "synthetic_body_exported"
            for observation in attachments
        ),
        "unsupported_preserved_occurrence_count": len(unsupported),
        "source_inventory_item_count": len(source_inventory.items),
        "observation_count": len(observations),
        "missing_source_inventory_binding_count": 0,
        "missing_parent_lineage_count": 0,
        "missing_content_hash_count": 0,
        "unexplained_loss_count": 0,
        "failed_record_count": 0,
        "blocker_count": 0,
    }
    if counts != computed_counts:
        raise RuntimeError("native_authorized_snapshot_count_drift")
    if snapshot.get("lineage_rollups") != _native_lineage_rollups(
        source_inventory=source_inventory,
        observations=observations,
    ):
        raise RuntimeError("native_authorized_snapshot_lineage_rollup_drift")
    if "relative_output_path" in json.dumps(snapshot, sort_keys=True):
        raise RuntimeError("native_authorized_snapshot_private_locator_copied")


def _validate_native_authorized_report(report: Mapping[str, Any]) -> None:
    if report.get("artifact_id") != NATIVE_AUTHORIZED_REPORT_ARTIFACT_ID:
        raise RuntimeError("native_authorized_report_artifact_invalid")
    if report.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("native_authorized_report_schema_invalid")
    if report.get("status") != "passed":
        raise RuntimeError("native_authorized_report_blocked")
    if report.get("source_completeness_gate_status") != "eligible":
        raise RuntimeError("native_authorized_report_gate_status_invalid")
    if report.get("methodology_readiness_status") != "blocked":
        raise RuntimeError("native_authorized_report_methodology_status_invalid")
    if report.get("canonical_fact_status") != "not_asserted":
        raise RuntimeError("native_authorized_report_canonical_status_invalid")
    if report.get("round_trip_status") != "passed":
        raise RuntimeError("native_authorized_report_round_trip_invalid")
    for field in (
        "source_asset_sha256",
        "native_manifest_fingerprint",
        "asset_binding_fingerprint",
        "permission_fingerprint",
        "source_ref_fingerprint",
        "parser_fingerprint",
        "source_inventory_fingerprint",
        "observation_snapshot_fingerprint",
        "message_lineage_fingerprint",
        "attachment_lineage_fingerprint",
        "folder_lineage_fingerprint",
        "unsupported_lineage_fingerprint",
        "snapshot_fingerprint",
        "report_fingerprint",
    ):
        _native_fingerprint(report.get(field), field)
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise RuntimeError("native_authorized_report_fingerprint_invalid")
    if report.get("blocker_fingerprints") != []:
        raise RuntimeError("native_authorized_report_blockers_present")
    counts = report.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(value, int) or isinstance(value, bool) for value in counts.values()
    ):
        raise RuntimeError("native_authorized_report_counts_invalid")
    if any(
        counts.get(field) != 0
        for field in (
            "missing_source_inventory_binding_count",
            "missing_parent_lineage_count",
            "missing_content_hash_count",
            "unexplained_loss_count",
            "failed_record_count",
            "blocker_count",
        )
    ):
        raise RuntimeError("native_authorized_report_gap_nonzero")
    serialized = json.dumps(report, sort_keys=True).casefold()
    if any(
        forbidden in serialized
        for forbidden in (
            "relative_output",
            "filename",
            "subject",
            "sender",
            "body",
            "payload",
            "object_uri",
        )
    ):
        raise RuntimeError("native_authorized_report_private_field_exposed")
    assert_no_public_raw_references(
        report,
        "issue56_native_source_complete_authorized_observation_report",
    )


def _select_private_content_probe(
    *,
    snippet_index: Any,
    tokenizer_profile: Any,
) -> tuple[str, str]:
    protected_candidates: dict[str, int] = {}
    for snippet_index_value, snippet in enumerate(snippet_index.snippets):
        for candidate_text in snippet.protected_identifier_tokens:
            postings = snippet_index.snippet_indexes_by_token.get(candidate_text, ())
            if (
                candidate_text.strip()
                and snippet_index_value in postings
                and 0 < len(postings) <= _PRIVATE_PROBE_MAX_POSTING_COUNT
            ):
                protected_candidates.setdefault(candidate_text, snippet_index_value)

    candidates: list[tuple[int, str, str, str]] = []
    ordered_protected_candidates = sorted(
        protected_candidates.items(),
        key=lambda item: (
            len(snippet_index.snippet_indexes_by_token[item[0]]),
            sha256_json(item[0]),
        ),
    )[:_PRIVATE_PROBE_MAX_PROTECTED_CANDIDATES]
    for candidate_text, source_snippet_index in ordered_protected_candidates:
        candidate = _private_content_probe_candidate(
            snippet_index=snippet_index,
            tokenizer_profile=tokenizer_profile,
            candidate_text=candidate_text,
            source_snippet_index=source_snippet_index,
        )
        if candidate is not None:
            candidates.append(candidate)
    if candidates:
        _, _, query_text, expected_source_observation_id = min(candidates)
        return query_text, expected_source_observation_id

    for snippet_index_value, snippet in enumerate(
        snippet_index.snippets[:_PRIVATE_PROBE_MAX_FALLBACK_SNIPPETS]
    ):
        candidate_texts = tuple(
            dict.fromkeys(
                match.group(0)
                for match in re.finditer(
                    r"[\u3400-\u9fff]{2,12}|[A-Za-z0-9][A-Za-z0-9._@:+-]{4,79}",
                    snippet.dense_evidence_text,
                )
                if match.group(0).strip()
            )
        )[:_PRIVATE_PROBE_MAX_LEXICAL_CANDIDATES_PER_SNIPPET]
        for candidate_text in candidate_texts:
            candidate = _private_content_probe_candidate(
                snippet_index=snippet_index,
                tokenizer_profile=tokenizer_profile,
                candidate_text=candidate_text,
                source_snippet_index=snippet_index_value,
            )
            if candidate is not None:
                candidates.append(candidate)
    if not candidates:
        raise RuntimeError("native_retrieval_content_probe_unavailable")
    _, _, query_text, expected_source_observation_id = min(candidates)
    return query_text, expected_source_observation_id


def _private_content_probe_candidate(
    *,
    snippet_index: Any,
    tokenizer_profile: Any,
    candidate_text: str,
    source_snippet_index: int,
) -> tuple[int, str, str, str] | None:
    try:
        assert_no_public_raw_references(
            candidate_text,
            "issue56_private_content_probe",
        )
        analysis = tokenizer_profile.analyze(candidate_text)
    except Exception:
        return None
    candidate_indexes: set[int] = set()
    for token in analysis.tokens:
        candidate_indexes.update(snippet_index.snippet_indexes_by_token.get(token, ()))
    if (
        source_snippet_index not in candidate_indexes
        or not candidate_indexes
        or len(candidate_indexes) > _PRIVATE_PROBE_MAX_POSTING_COUNT
    ):
        return None
    expected_index = min(
        candidate_indexes,
        key=lambda index: str(snippet_index.snippets[index].payload["source_observation_id"]),
    )
    return (
        len(candidate_indexes),
        sha256_json(candidate_text),
        candidate_text,
        str(snippet_index.snippets[expected_index].payload["source_observation_id"]),
    )


def _validate_native_retrieval_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("artifact_id") != NATIVE_RETRIEVAL_SNAPSHOT_ARTIFACT_ID:
        raise RuntimeError("native_retrieval_snapshot_artifact_invalid")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("native_retrieval_snapshot_schema_invalid")
    if snapshot.get("status") != "passed":
        raise RuntimeError("native_retrieval_snapshot_blocked")
    if snapshot.get("claim_boundary_status") != "retrieval_ready_evidence_not_canonical_fact":
        raise RuntimeError("native_retrieval_snapshot_claim_boundary_invalid")
    if snapshot.get("snapshot_fingerprint") != _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    ):
        raise RuntimeError("native_retrieval_snapshot_fingerprint_invalid")
    for field in (
        "source_snapshot_fingerprint",
        "source_asset_sha256",
        "native_manifest_fingerprint",
        "source_inventory_fingerprint",
        "source_provenance_fingerprint",
        "permission_fingerprint",
        "parsed_observation_fingerprint",
        "mail_evidence_bundle_fingerprint",
        "tokenizer_profile_fingerprint",
        "observation_snapshot_fingerprint",
        "candidate_manifest_fingerprint",
        "index_fingerprint",
        "query_fingerprint",
        "authorized_result_fingerprint",
        "denied_result_fingerprint",
        "snapshot_fingerprint",
    ):
        _native_fingerprint(snapshot.get(field), field)
    if snapshot.get("blocker_fingerprints") != []:
        raise RuntimeError("native_retrieval_snapshot_blockers_present")
    counts = snapshot.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(value, int) or isinstance(value, bool) for value in counts.values()
    ):
        raise RuntimeError("native_retrieval_snapshot_counts_invalid")
    for field in (
        "missing_source_inventory_binding_count",
        "missing_source_local_key_binding_count",
        "missing_content_hash_binding_count",
        "missing_permission_binding_count",
        "unexplained_loss_count",
        "blocker_count",
    ):
        if counts.get(field) != 0:
            raise RuntimeError(f"native_retrieval_snapshot_{field}_nonzero")

    source_inventory = SourceInventory.from_dict(snapshot["source_inventory"])
    if sha256_json(source_inventory.to_dict()) != snapshot["source_inventory_fingerprint"]:
        raise RuntimeError("native_retrieval_snapshot_inventory_fingerprint_drift")
    source_observations = [
        Observation.from_dict(row) for row in snapshot["source_occurrence_observations"]
    ]
    parsed_observations = [
        Observation.from_dict(row) for row in snapshot["parsed_mail_observations"]
    ]
    if counts.get("source_inventory_item_count") != len(source_inventory.items):
        raise RuntimeError("native_retrieval_snapshot_inventory_count_drift")
    if counts.get("source_occurrence_observation_count") != len(source_observations):
        raise RuntimeError("native_retrieval_snapshot_source_count_drift")
    if counts.get("parsed_observation_count") != len(parsed_observations):
        raise RuntimeError("native_retrieval_snapshot_parsed_count_drift")
    if counts.get("retrieval_snapshot_observation_count") != len(
        [*source_observations, *parsed_observations]
    ):
        raise RuntimeError("native_retrieval_snapshot_total_count_drift")
    all_observation_ids = [
        observation.observation_id for observation in [*source_observations, *parsed_observations]
    ]
    if len(set(all_observation_ids)) != len(all_observation_ids):
        raise RuntimeError("native_retrieval_snapshot_observation_id_duplicate")
    if (
        sha256_json([row.to_dict() for row in parsed_observations])
        != snapshot["parsed_observation_fingerprint"]
    ):
        raise RuntimeError("native_retrieval_snapshot_parsed_fingerprint_drift")

    inventory_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
    permission_fingerprint = str(snapshot["permission_fingerprint"])
    source_provenance_fingerprint = str(snapshot["source_provenance_fingerprint"])
    for observation in parsed_observations:
        payload = observation.payload or {}
        if (
            sha256_json(observation.permission_scope) != permission_fingerprint
            or observation.asset_id != source_inventory.source_asset_id
            or payload.get("canonical_fact_status") != "not_asserted"
            or observation.location.get("source_provenance_fingerprint")
            != source_provenance_fingerprint
        ):
            raise RuntimeError("native_retrieval_snapshot_permission_or_provenance_drift")
        item_id = observation.location.get("source_inventory_item_id")
        source_local_key = observation.location.get("source_local_key")
        item = inventory_by_id.get(str(item_id))
        if (
            item is None
            or not isinstance(source_local_key, str)
            or item.location.get("source_local_key") != source_local_key
        ):
            raise RuntimeError("native_retrieval_snapshot_inventory_binding_invalid")
        if observation.observation_type in {
            "email_message",
            "email_header",
            "email_body_segment",
        }:
            if item.structure_kind != "email_message_occurrence" or observation.location.get(
                "source_content_hash"
            ) != item.location.get("message_content_hash"):
                raise RuntimeError("native_retrieval_snapshot_message_binding_invalid")
        elif observation.observation_type == "email_attachment_occurrence":
            if not item.structure_kind.endswith("occurrence") or observation.location.get(
                "source_content_hash"
            ) != item.location.get("attachment_content_hash"):
                raise RuntimeError("native_retrieval_snapshot_attachment_binding_invalid")
        elif observation.observation_type != "mail_folder_occurrence":
            raise RuntimeError("native_retrieval_snapshot_observation_type_invalid")
    computed_type_counts = Counter(
        observation.observation_type for observation in parsed_observations
    )
    if (
        counts.get("parsed_folder_observation_count")
        != computed_type_counts["mail_folder_occurrence"]
    ):
        raise RuntimeError("native_retrieval_snapshot_folder_count_drift")
    if counts.get("parsed_message_observation_count") != computed_type_counts["email_message"]:
        raise RuntimeError("native_retrieval_snapshot_message_count_drift")
    if counts.get("parsed_header_observation_count") != computed_type_counts["email_header"]:
        raise RuntimeError("native_retrieval_snapshot_header_count_drift")
    if (
        counts.get("parsed_body_segment_observation_count")
        != computed_type_counts["email_body_segment"]
    ):
        raise RuntimeError("native_retrieval_snapshot_body_count_drift")
    if (
        counts.get("parsed_attachment_observation_count")
        != computed_type_counts["email_attachment_occurrence"]
    ):
        raise RuntimeError("native_retrieval_snapshot_attachment_count_drift")
    serialized_keys = json.dumps(
        {
            "source_inventory": snapshot["source_inventory"],
            "source_occurrence_observations": snapshot["source_occurrence_observations"],
            "parsed_mail_observations": snapshot["parsed_mail_observations"],
        },
        sort_keys=True,
    )
    if any(
        forbidden in serialized_keys
        for forbidden in (
            "relative_output_path",
            '"export_path"',
            ".issue56-private-native-lineage-v1",
        )
    ):
        raise RuntimeError("native_retrieval_snapshot_private_locator_exposed")


def _validate_native_retrieval_report(report: Mapping[str, Any]) -> None:
    if report.get("artifact_id") != NATIVE_RETRIEVAL_REPORT_ARTIFACT_ID:
        raise RuntimeError("native_retrieval_report_artifact_invalid")
    if report.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("native_retrieval_report_schema_invalid")
    if report.get("status") != "passed":
        raise RuntimeError("native_retrieval_report_blocked")
    if report.get("methodology_readiness_status") != "blocked":
        raise RuntimeError("native_retrieval_report_methodology_status_invalid")
    if report.get("canonical_fact_status") != "not_asserted":
        raise RuntimeError("native_retrieval_report_canonical_status_invalid")
    if report.get("target_profile_status") != "passed_no_ascii_fallback":
        raise RuntimeError("native_retrieval_report_tokenizer_status_invalid")
    if report.get("denied_query_status") != "passed_fail_closed":
        raise RuntimeError("native_retrieval_report_denied_status_invalid")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise RuntimeError("native_retrieval_report_fingerprint_invalid")
    if report.get("blocker_fingerprints") != []:
        raise RuntimeError("native_retrieval_report_blockers_present")
    counts = report.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(value, int) or isinstance(value, bool) for value in counts.values()
    ):
        raise RuntimeError("native_retrieval_report_counts_invalid")
    if any(
        counts.get(field) != 0
        for field in (
            "missing_source_inventory_binding_count",
            "missing_source_local_key_binding_count",
            "missing_content_hash_binding_count",
            "missing_permission_binding_count",
            "unexplained_loss_count",
            "blocker_count",
        )
    ):
        raise RuntimeError("native_retrieval_report_gap_nonzero")
    for key, value in report.items():
        if key.endswith("_fingerprint"):
            _native_fingerprint(value, key)
        elif key.endswith("_status"):
            if not isinstance(value, str) or not value:
                raise RuntimeError("native_retrieval_report_status_invalid")
        elif key not in {
            "artifact_id",
            "schema_version",
            "status",
            "counts",
            "blocker_fingerprints",
        }:
            raise RuntimeError("native_retrieval_report_field_not_safe")
    serialized = json.dumps(report, sort_keys=True).casefold()
    if any(
        forbidden in serialized
        for forbidden in (
            "relative_output",
            "filename",
            "subject",
            "sender",
            "payload",
            "query_text",
            ".issue56-private",
            ".test-tmp",
        )
    ):
        raise RuntimeError("native_retrieval_report_private_field_exposed")
    assert_no_public_raw_references(
        report,
        "issue56_native_source_complete_retrieval_ready_report",
    )


def _native_source_local_key(value: Any, *, expected_kind: str) -> str:
    if (
        not isinstance(value, str)
        or not _NATIVE_SOURCE_LOCAL_KEY_RE.fullmatch(value)
        or not value.startswith(f"pstnative_{expected_kind}_")
    ):
        raise RuntimeError(f"native_private_manifest_{expected_kind}_source_key_invalid")
    return value


def _native_node_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _NODE_ID_RE.fullmatch(value):
        raise RuntimeError(f"native_private_manifest_{field_name}_node_id_invalid")
    return value


def _native_fingerprint(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_RE.fullmatch(value):
        raise RuntimeError(f"native_{field_name}_invalid")
    return value


def _native_nonnegative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"native_private_manifest_{field_name}_invalid")
    return value


def _native_positive_int(value: Any, field_name: str) -> int:
    result = _native_nonnegative_int(value, field_name)
    if result == 0:
        raise RuntimeError(f"native_private_manifest_{field_name}_invalid")
    return result


def _native_export_relative_output(
    value: Any,
    *,
    allow_missing: bool,
) -> str | None:
    if value is None and allow_missing:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeError("native_private_manifest_output_reference_invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("native_private_manifest_output_reference_unsafe")
    return relative.as_posix()


def _validate_native_export_file(
    *,
    export_root: Path,
    relative_output: str,
    expected_hash: str,
    expected_byte_count: int,
) -> None:
    output_path = (export_root / relative_output).resolve()
    try:
        output_path.relative_to(export_root)
    except ValueError as exc:
        raise RuntimeError("native_private_manifest_output_outside_export_root") from exc
    if not output_path.is_file():
        raise RuntimeError("native_private_manifest_output_missing")
    if output_path.stat().st_size != expected_byte_count:
        raise RuntimeError("native_private_manifest_output_byte_count_drift")
    if _sha256_file(output_path) != expected_hash:
        raise RuntimeError("native_private_manifest_output_content_hash_drift")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _native_manifest_sha256_json(value: Any) -> str:
    """Match the native manifest's exact JSON contract, including null fields."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _native_manifest_payload_fingerprint(
    payload: Mapping[str, Any],
    field_name: str,
) -> str:
    return _native_manifest_sha256_json(
        {key: value for key, value in payload.items() if key != field_name}
    )


def _build_parser_backed_source_inventory(
    *,
    parser_manifest: Mapping[str, Any],
    oracle_manifest: Mapping[str, Any],
    observation_manifest: Mapping[str, Any],
    folder_mapping: Mapping[int, int],
    preserved_work_dir: Path,
    private_binding: Mapping[str, Any],
) -> tuple[
    SourceInventory,
    list[dict[str, str]],
    list[dict[str, str]],
    dict[str, int],
    dict[str, int],
    dict[str, Any],
]:
    parser_messages = list(parser_manifest["messages"])
    observation_rows = reconciliation._read_json_files(
        preserved_work_dir / "data" / "ingestion" / "observations"
    )
    observation_messages = _private_observation_message_rows(observation_rows)
    (
        parser_observation_matches,
        message_stage_counts,
        unmatched_parser_observation_indexes,
        unmatched_observation_indexes,
    ) = _unique_cross_field_matches(
        parser_messages,
        observation_messages,
        stages=PARSER_OBSERVATION_MATCH_STAGES,
    )
    parser_raw_by_source_key, parser_raw_counts = _bind_parser_messages_to_raw_oracle(
        parser_messages=parser_messages,
        raw_messages=list(oracle_manifest["messages"]),
        observation_folders=list(observation_manifest["folders"]),
        folder_mapping=folder_mapping,
    )

    inventory_items: list[SourceInventoryItem] = []
    inventory_item_by_source_key: dict[str, SourceInventoryItem] = {}
    item_ordinal = 0
    for message in sorted(
        parser_messages,
        key=lambda row: (
            int(row["export_ordinal"]),
            str(row["source_local_key"]),
        ),
    ):
        item_ordinal += 1
        source_local_key = str(message["source_local_key"])
        item = SourceInventoryItem.create(
            source_asset_id=str(private_binding["source_asset_id"]),
            structure_kind="exported_message_occurrence",
            content_type="message/rfc822",
            ordinal=item_ordinal,
            processing_state=SourceInventoryProcessingState.PARSED,
            raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
            source_fingerprint=str(parser_manifest["source_asset_sha256"]),
            parser_fingerprint=str(parser_manifest["manifest_fingerprint"]),
            permission_scope=private_binding["permission_scope"],
            location={
                "source_local_key": source_local_key,
                "message_content_hash": message["message_content_hash"],
                "folder_occurrence_hash": message["folder_occurrence_hash"],
                "export_ordinal": message["export_ordinal"],
                **(
                    {
                        "oracle_occurrence_fingerprint": parser_raw_by_source_key[source_local_key][
                            "oracle_occurrence_fingerprint"
                        ]
                    }
                    if source_local_key in parser_raw_by_source_key
                    else {}
                ),
            },
        )
        inventory_items.append(item)
        inventory_item_by_source_key[source_local_key] = item
        for attachment in sorted(
            message.get("attachments", []),
            key=lambda row: (
                int(row["attachment_ordinal"]),
                str(row["source_local_key"]),
            ),
        ):
            item_ordinal += 1
            attachment_source_local_key = str(attachment["source_local_key"])
            attachment_item = SourceInventoryItem.create(
                source_asset_id=str(private_binding["source_asset_id"]),
                structure_kind="regular_attachment_occurrence",
                content_type=str(attachment.get("content_type") or "application/octet-stream"),
                ordinal=item_ordinal,
                processing_state=SourceInventoryProcessingState.PARSED,
                raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
                source_fingerprint=str(parser_manifest["source_asset_sha256"]),
                parser_fingerprint=str(parser_manifest["manifest_fingerprint"]),
                permission_scope=private_binding["permission_scope"],
                location={
                    "source_local_key": attachment_source_local_key,
                    "parent_source_local_key": source_local_key,
                    "attachment_content_hash": attachment["attachment_content_hash"],
                    "attachment_id_fingerprint": attachment["attachment_id_fingerprint"],
                    "attachment_ordinal": attachment["attachment_ordinal"],
                    "folder_occurrence_hash": attachment["folder_occurrence_hash"],
                    "export_ordinal": attachment["export_ordinal"],
                },
            )
            inventory_items.append(attachment_item)
            inventory_item_by_source_key[attachment_source_local_key] = attachment_item
        for body_sidecar in sorted(
            message.get("body_sidecars", []),
            key=lambda row: (
                int(row["sidecar_ordinal"]),
                str(row["source_local_key"]),
            ),
        ):
            item_ordinal += 1
            body_source_local_key = str(body_sidecar["source_local_key"])
            body_item = SourceInventoryItem.create(
                source_asset_id=str(private_binding["source_asset_id"]),
                structure_kind="message_body_representation",
                content_type=str(body_sidecar.get("content_type") or "application/rtf"),
                ordinal=item_ordinal,
                processing_state=SourceInventoryProcessingState.PARSED,
                raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
                source_fingerprint=str(parser_manifest["source_asset_sha256"]),
                parser_fingerprint=str(parser_manifest["manifest_fingerprint"]),
                permission_scope=private_binding["permission_scope"],
                location={
                    "source_local_key": body_source_local_key,
                    "parent_source_local_key": source_local_key,
                    "body_representation_content_hash": body_sidecar[
                        "body_representation_content_hash"
                    ],
                    "folder_occurrence_hash": body_sidecar["folder_occurrence_hash"],
                    "export_ordinal": body_sidecar["export_ordinal"],
                    "representation_kind": body_sidecar["representation_kind"],
                },
            )
            inventory_items.append(body_item)
            inventory_item_by_source_key[body_source_local_key] = body_item

    unsupported_main_records = list(parser_manifest.get("unsupported_main_records", []))
    for unsupported in sorted(
        unsupported_main_records,
        key=lambda row: (
            int(row["export_ordinal"]),
            str(row["source_local_key"]),
        ),
    ):
        item_ordinal += 1
        unsupported_source_local_key = str(unsupported["source_local_key"])
        unsupported_item = SourceInventoryItem.create(
            source_asset_id=str(private_binding["source_asset_id"]),
            structure_kind="unsupported_parser_record",
            content_type="application/octet-stream",
            ordinal=item_ordinal,
            processing_state=SourceInventoryProcessingState.UNSUPPORTED,
            raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
            source_fingerprint=str(parser_manifest["source_asset_sha256"]),
            parser_fingerprint=str(parser_manifest["manifest_fingerprint"]),
            permission_scope=private_binding["permission_scope"],
            location={
                "source_local_key": unsupported_source_local_key,
                "message_content_hash": unsupported["message_content_hash"],
                "folder_occurrence_hash": unsupported["folder_occurrence_hash"],
                "export_ordinal": unsupported["export_ordinal"],
                "reason_fingerprint": unsupported["reason_fingerprint"],
            },
        )
        inventory_items.append(unsupported_item)
        inventory_item_by_source_key[unsupported_source_local_key] = unsupported_item
        for associated_file in unsupported.get("export_files", []):
            if associated_file.get("representation_kind") == ("unsupported_main_candidate"):
                continue
            item_ordinal += 1
            associated_source_local_key = stable_resource_contract_id(
                "pstunsupportedfilesrc",
                "Issue56ReadpstUnsupportedAssociatedFile",
                {
                    "parent_source_local_key": unsupported_source_local_key,
                    "content_hash": associated_file["content_hash"],
                    "export_file_ordinal": associated_file["export_file_ordinal"],
                    "representation_kind": associated_file["representation_kind"],
                },
            )
            associated_item = SourceInventoryItem.create(
                source_asset_id=str(private_binding["source_asset_id"]),
                structure_kind="unsupported_parser_sidecar",
                content_type="application/octet-stream",
                ordinal=item_ordinal,
                processing_state=SourceInventoryProcessingState.UNSUPPORTED,
                raw_retention_state=SourceInventoryRawRetentionState.RETAINED,
                source_fingerprint=str(parser_manifest["source_asset_sha256"]),
                parser_fingerprint=str(parser_manifest["manifest_fingerprint"]),
                permission_scope=private_binding["permission_scope"],
                location={
                    "source_local_key": associated_source_local_key,
                    "parent_source_local_key": unsupported_source_local_key,
                    "content_hash": associated_file["content_hash"],
                    "export_ordinal": associated_file["export_file_ordinal"],
                    "representation_kind": associated_file["representation_kind"],
                },
            )
            inventory_items.append(associated_item)
            inventory_item_by_source_key[associated_source_local_key] = associated_item

    source_inventory = SourceInventory.create(
        source_asset_id=str(private_binding["source_asset_id"]),
        items=inventory_items,
        source_fingerprint=str(parser_manifest["source_asset_sha256"]),
        parser_fingerprint=str(parser_manifest["manifest_fingerprint"]),
        created_at=str(private_binding["created_at"]),
    )
    observation_match_by_parser_index = {
        parser_index: (stage_id, observation_index)
        for stage_id, parser_index, observation_index in parser_observation_matches
    }
    message_rebindings: list[dict[str, str]] = []
    for parser_index in sorted(observation_match_by_parser_index):
        parser_message = parser_messages[parser_index]
        source_local_key = str(parser_message["source_local_key"])
        raw_message = parser_raw_by_source_key.get(source_local_key)
        stage_id, observation_index = observation_match_by_parser_index[parser_index]
        observation_message = observation_messages[observation_index]
        inventory_item = inventory_item_by_source_key[source_local_key]
        binding = {
            "identity_stage_fingerprint": sha256_json(stage_id),
            "parser_source_local_key_fingerprint": sha256_json(parser_message["source_local_key"]),
            "message_content_hash": str(parser_message["message_content_hash"]),
            "observation_occurrence_fingerprint": str(
                observation_message["message_occurrence_fingerprint"]
            ),
            "exported_message_identity_fingerprint": str(
                observation_message["exported_message_identity_fingerprint"]
            ),
            "source_inventory_id_fingerprint": sha256_json(source_inventory.source_inventory_id),
            "source_inventory_item_id_fingerprint": sha256_json(
                inventory_item.source_inventory_item_id
            ),
        }
        if raw_message is not None:
            binding.update(
                {
                    "raw_parser_identity_stage_fingerprint": sha256_json(
                        "readpst_separate_source_local_ordinal_identity_validated_v1"
                    ),
                    "oracle_occurrence_fingerprint": str(
                        raw_message["oracle_occurrence_fingerprint"]
                    ),
                }
            )
        message_rebindings.append(binding)

    complete_parent_observation_by_source_key = {
        str(parser_messages[parser_index]["source_local_key"]): str(
            observation_messages[observation_index]["message_occurrence_fingerprint"]
        )
        for parser_index, (_stage_id, observation_index) in (
            observation_match_by_parser_index.items()
        )
    }
    parser_attachments = _private_parser_attachment_rows(
        parser_messages=parser_messages,
        parent_observation_by_source_key=(complete_parent_observation_by_source_key),
    )
    observation_attachments = _private_observation_attachment_rows(observation_rows)
    (
        attachment_matches,
        attachment_stage_counts,
        unmatched_parser_attachment_indexes,
        unmatched_observation_attachment_indexes,
    ) = _unique_cross_field_matches(
        parser_attachments,
        observation_attachments,
        stages=(
            (
                "parser_observation_attachment_full_identity_unique_v1",
                (
                    "parent_observation_occurrence_fingerprint",
                    "attachment_id_fingerprint",
                    "attachment_content_hash",
                    "attachment_ordinal",
                ),
                (
                    "parent_observation_occurrence_fingerprint",
                    "attachment_id_fingerprint",
                    "attachment_content_hash",
                    "attachment_ordinal",
                ),
            ),
            (
                "parser_observation_attachment_content_name_unique_v1",
                (
                    "parent_observation_occurrence_fingerprint",
                    "attachment_content_hash",
                    "attachment_name_fingerprint",
                ),
                (
                    "parent_observation_occurrence_fingerprint",
                    "attachment_content_hash",
                    "attachment_name_fingerprint",
                ),
            ),
            (
                "parser_observation_attachment_content_unique_v1",
                (
                    "parent_observation_occurrence_fingerprint",
                    "attachment_content_hash",
                ),
                (
                    "parent_observation_occurrence_fingerprint",
                    "attachment_content_hash",
                ),
            ),
        ),
    )
    attachment_rebindings: list[dict[str, str]] = []
    for stage_id, parser_index, observation_index in attachment_matches:
        attachment = parser_attachments[parser_index]
        observation = observation_attachments[observation_index]
        inventory_item = inventory_item_by_source_key[str(attachment["source_local_key"])]
        attachment_rebindings.append(
            {
                "identity_stage_fingerprint": sha256_json(stage_id),
                "parser_source_local_key_fingerprint": sha256_json(attachment["source_local_key"]),
                "parent_parser_source_local_key_fingerprint": sha256_json(
                    attachment["parent_source_local_key"]
                ),
                "attachment_content_hash": str(attachment["attachment_content_hash"]),
                "observation_id_fingerprint": str(observation["observation_id_fingerprint"]),
                "source_inventory_id_fingerprint": sha256_json(
                    source_inventory.source_inventory_id
                ),
                "source_inventory_item_id_fingerprint": sha256_json(
                    inventory_item.source_inventory_item_id
                ),
            }
        )

    complete_parent_observation_fingerprints = set(
        complete_parent_observation_by_source_key.values()
    )
    attachment_parent_message_rebound_count = sum(
        1
        for attachment in observation_attachments
        if attachment["parent_observation_occurrence_fingerprint"]
        in complete_parent_observation_fingerprints
    )
    observed_attachment_count = len(observation_attachments)
    parser_attachment_parent_eligible_count = len(parser_attachments)
    parser_embedded_attachment_count = sum(
        len(message.get("embedded_attachments", [])) for message in parser_messages
    )
    parser_separate_attachment_count = sum(
        len(message.get("separate_attachments", [])) for message in parser_messages
    )
    parser_body_representation_count = sum(
        len(message.get("body_sidecars", [])) for message in parser_messages
    )
    parser_attachment_count = parser_embedded_attachment_count + parser_separate_attachment_count
    attachment_counts = {
        "observed_attachment_count": observed_attachment_count,
        "attachment_occurrence_identity_count": observed_attachment_count,
        "attachment_parent_message_rebound_count": (attachment_parent_message_rebound_count),
        "attachment_source_inventory_binding_count": len(attachment_rebindings),
        "attachment_inventory_gap_count": (observed_attachment_count - len(attachment_rebindings)),
        "parser_attachment_count": parser_attachment_count,
        "parser_attachment_parent_eligible_count": (parser_attachment_parent_eligible_count),
        "parser_attachment_parent_unbound_count": (
            parser_attachment_count - parser_attachment_parent_eligible_count
        ),
        "parser_embedded_attachment_count": parser_embedded_attachment_count,
        "parser_separate_attachment_count": parser_separate_attachment_count,
        "parser_body_representation_count": parser_body_representation_count,
        "unmatched_parser_attachment_count": (parser_attachment_count - len(attachment_rebindings)),
        "unmatched_observation_attachment_count": (len(unmatched_observation_attachment_indexes)),
        **{f"{stage_id}_count": count for stage_id, count in attachment_stage_counts.items()},
    }
    parser_message_count = len(parser_messages)
    raw_message_count = len(oracle_manifest["messages"])
    parser_main_export_record_count = parser_message_count + len(unsupported_main_records)
    parser_counts = {
        "parser_message_count": parser_message_count,
        "parser_main_export_record_count": parser_main_export_record_count,
        "unsupported_main_record_count": len(unsupported_main_records),
        "parser_source_inventory_item_count": len(source_inventory.items),
        "parser_observation_message_binding_count": len(parser_observation_matches),
        "parser_source_inventory_observation_binding_count": len(message_rebindings),
        "raw_parser_observation_message_binding_count": sum(
            "oracle_occurrence_fingerprint" in binding for binding in message_rebindings
        ),
        "unmatched_parser_message_count": (len(unmatched_parser_observation_indexes)),
        "unmatched_observation_message_count": (len(unmatched_observation_indexes)),
        "raw_parser_parsed_message_count_gap": max(
            raw_message_count - parser_message_count,
            0,
        ),
        "raw_parser_export_record_count_gap": max(
            raw_message_count - parser_main_export_record_count,
            0,
        ),
        **parser_raw_counts,
        **{f"{stage_id}_count": count for stage_id, count in message_stage_counts.items()},
    }
    gap_forensics = _build_gap_forensics(
        parser_manifest=parser_manifest,
        parser_messages=parser_messages,
        observation_messages=observation_messages,
        raw_messages=list(oracle_manifest["messages"]),
        observation_folders=list(observation_manifest["folders"]),
        folder_mapping=folder_mapping,
        unmatched_parser_observation_indexes=unmatched_parser_observation_indexes,
        unmatched_observation_indexes=unmatched_observation_indexes,
        parser_attachments=parser_attachments,
        observation_attachments=observation_attachments,
        unmatched_parser_attachment_indexes=unmatched_parser_attachment_indexes,
        unmatched_observation_attachment_indexes=unmatched_observation_attachment_indexes,
    )
    parser_counts.update(gap_forensics["counts"])
    return (
        source_inventory,
        message_rebindings,
        attachment_rebindings,
        attachment_counts,
        parser_counts,
        gap_forensics,
    )


def _build_gap_forensics(
    *,
    parser_manifest: Mapping[str, Any],
    parser_messages: Sequence[Mapping[str, Any]],
    observation_messages: Sequence[Mapping[str, Any]],
    raw_messages: Sequence[Mapping[str, Any]],
    observation_folders: Sequence[Mapping[str, Any]],
    folder_mapping: Mapping[int, int],
    unmatched_parser_observation_indexes: set[int],
    unmatched_observation_indexes: set[int],
    parser_attachments: Sequence[Mapping[str, Any]],
    observation_attachments: Sequence[Mapping[str, Any]],
    unmatched_parser_attachment_indexes: set[int],
    unmatched_observation_attachment_indexes: set[int],
) -> dict[str, Any]:
    counts = {
        **_partition_parser_observation_gaps(
            parser_messages=parser_messages,
            observation_messages=observation_messages,
            unmatched_parser_indexes=unmatched_parser_observation_indexes,
            unmatched_observation_indexes=unmatched_observation_indexes,
        ),
        **_partition_raw_parser_gaps(
            raw_messages=raw_messages,
            parser_messages=parser_messages,
            unsupported_main_record_count=len(parser_manifest.get("unsupported_main_records", [])),
            observation_folders=observation_folders,
            folder_mapping=folder_mapping,
        ),
        **_partition_attachment_gaps(
            parser_attachments=parser_attachments,
            observation_attachments=observation_attachments,
            unmatched_parser_indexes=unmatched_parser_attachment_indexes,
            unmatched_observation_indexes=unmatched_observation_attachment_indexes,
        ),
        **_parser_warning_forensic_counts(parser_manifest),
        "forensic_additional_uniquely_proven_binding_count": 0,
    }
    blocking_count_fields = (
        "forensic_raw_parser_export_record_gap_count",
        "forensic_parser_observation_unmatched_parser_count",
        "forensic_parser_observation_unmatched_observation_count",
        "forensic_attachment_unresolved_observation_count",
    )
    blocked = any(counts[field] for field in blocking_count_fields)
    reason_class_fingerprints = sorted(
        sha256_json(field)
        for field, count in counts.items()
        if count
        and (
            field.startswith("forensic_parser_observation_")
            or field.startswith("forensic_raw_parser_")
            or field.startswith("forensic_attachment_")
        )
    )
    forensics: dict[str, Any] = {
        "artifact_id": GAP_FORENSICS_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if blocked else "passed",
        "source_asset_sha256": parser_manifest["source_asset_sha256"],
        "parser_export_manifest_fingerprint": parser_manifest["manifest_fingerprint"],
        "forensics_policy_fingerprint": sha256_json(GAP_FORENSICS_POLICY_ID),
        "existing_artifact_binding_status": (
            "no_additional_unique_binding_proven" if blocked else "not_required"
        ),
        "required_source_capture_capability_status": "missing" if blocked else "not_required",
        "required_source_capture_capability_fingerprint": sha256_json(
            REQUIRED_SOURCE_CAPTURE_CAPABILITY
        ),
        "reason_class_fingerprints": reason_class_fingerprints,
        "counts": counts,
    }
    forensics["forensics_fingerprint"] = _payload_fingerprint(
        forensics,
        "forensics_fingerprint",
    )
    return forensics


def _partition_parser_observation_gaps(
    *,
    parser_messages: Sequence[Mapping[str, Any]],
    observation_messages: Sequence[Mapping[str, Any]],
    unmatched_parser_indexes: set[int],
    unmatched_observation_indexes: set[int],
) -> dict[str, int]:
    remaining_parser = set(unmatched_parser_indexes)
    remaining_observations = set(unmatched_observation_indexes)
    counts: dict[str, int] = {
        "forensic_parser_observation_unmatched_parser_count": len(remaining_parser),
        "forensic_parser_observation_unmatched_observation_count": len(remaining_observations),
    }
    forensic_stages = (
        (
            "exact_composite",
            (
                "folder_occurrence_hash",
                "message_id_fingerprint",
                "message_identity_fingerprint",
                "sender_identity_fingerprint",
                "date_identity_fingerprint",
                "body_hash",
            ),
        ),
        ("message_id", ("message_id_fingerprint",)),
        (
            "folder_subject",
            ("folder_occurrence_hash", "message_identity_fingerprint"),
        ),
        ("subject", ("message_identity_fingerprint",)),
    )
    for stage_id, fields in forensic_stages:
        (
            stage_counts,
            remaining_parser,
            remaining_observations,
        ) = _consume_shared_forensic_groups(
            stage_id=stage_id,
            parser_rows=parser_messages,
            observation_rows=observation_messages,
            parser_indexes=remaining_parser,
            observation_indexes=remaining_observations,
            fields=fields,
        )
        counts.update(stage_counts)

    required_fields = (
        "folder_occurrence_hash",
        "message_id_fingerprint",
        "message_identity_fingerprint",
        "sender_identity_fingerprint",
        "date_identity_fingerprint",
        "body_hash",
    )
    unavailable_parser = {
        index
        for index in remaining_parser
        if any(
            not _forensic_value_available(parser_messages[index].get(field))
            for field in required_fields
        )
    }
    unavailable_observations = {
        index
        for index in remaining_observations
        if any(
            not _forensic_value_available(observation_messages[index].get(field))
            for field in required_fields
        )
    }
    counts["forensic_parser_observation_identity_component_unavailable_parser_count"] = len(
        unavailable_parser
    )
    counts["forensic_parser_observation_identity_component_unavailable_observation_count"] = len(
        unavailable_observations
    )
    remaining_parser -= unavailable_parser
    remaining_observations -= unavailable_observations
    counts["forensic_parser_observation_no_shared_signature_parser_count"] = len(remaining_parser)
    counts["forensic_parser_observation_no_shared_signature_observation_count"] = len(
        remaining_observations
    )

    parser_partition_count = sum(
        count
        for field, count in counts.items()
        if field.endswith("_parser_count")
        and field != "forensic_parser_observation_unmatched_parser_count"
    )
    observation_partition_count = sum(
        count
        for field, count in counts.items()
        if field.endswith("_observation_count")
        and field != "forensic_parser_observation_unmatched_observation_count"
    )
    if parser_partition_count != len(unmatched_parser_indexes):
        raise RuntimeError("parser_observation_forensic_parser_partition_invalid")
    if observation_partition_count != len(unmatched_observation_indexes):
        raise RuntimeError("parser_observation_forensic_observation_partition_invalid")
    return counts


def _consume_shared_forensic_groups(
    *,
    stage_id: str,
    parser_rows: Sequence[Mapping[str, Any]],
    observation_rows: Sequence[Mapping[str, Any]],
    parser_indexes: set[int],
    observation_indexes: set[int],
    fields: Sequence[str],
) -> tuple[dict[str, int], set[int], set[int]]:
    parser_groups = _forensic_groups(
        rows=parser_rows,
        indexes=parser_indexes,
        fields=fields,
    )
    observation_groups = _forensic_groups(
        rows=observation_rows,
        indexes=observation_indexes,
        fields=fields,
    )
    shared_keys = set(parser_groups) & set(observation_groups)
    singleton_keys = {
        key
        for key in shared_keys
        if len(parser_groups[key]) == 1 and len(observation_groups[key]) == 1
    }
    duplicate_equal_keys = {
        key
        for key in shared_keys
        if len(parser_groups[key]) == len(observation_groups[key]) and len(parser_groups[key]) > 1
    }
    cardinality_mismatch_keys = shared_keys - singleton_keys - duplicate_equal_keys
    prefix = f"forensic_parser_observation_{stage_id}"
    counts = {
        f"{prefix}_singleton_parser_count": sum(len(parser_groups[key]) for key in singleton_keys),
        f"{prefix}_singleton_observation_count": sum(
            len(observation_groups[key]) for key in singleton_keys
        ),
        f"{prefix}_duplicate_equal_parser_count": sum(
            len(parser_groups[key]) for key in duplicate_equal_keys
        ),
        f"{prefix}_duplicate_equal_observation_count": sum(
            len(observation_groups[key]) for key in duplicate_equal_keys
        ),
        f"{prefix}_cardinality_mismatch_parser_count": sum(
            len(parser_groups[key]) for key in cardinality_mismatch_keys
        ),
        f"{prefix}_cardinality_mismatch_observation_count": sum(
            len(observation_groups[key]) for key in cardinality_mismatch_keys
        ),
        f"{prefix}_singleton_group_count": len(singleton_keys),
        f"{prefix}_duplicate_equal_group_count": len(duplicate_equal_keys),
        f"{prefix}_cardinality_mismatch_group_count": len(cardinality_mismatch_keys),
    }
    used_parser_indexes = {index for key in shared_keys for index in parser_groups[key]}
    used_observation_indexes = {index for key in shared_keys for index in observation_groups[key]}
    return (
        counts,
        parser_indexes - used_parser_indexes,
        observation_indexes - used_observation_indexes,
    )


def _forensic_groups(
    *,
    rows: Sequence[Mapping[str, Any]],
    indexes: set[int],
    fields: Sequence[str],
) -> dict[tuple[Any, ...], list[int]]:
    groups: dict[tuple[Any, ...], list[int]] = {}
    for index in indexes:
        values = tuple(rows[index].get(field) for field in fields)
        if any(not _forensic_value_available(value) for value in values):
            continue
        groups.setdefault(values, []).append(index)
    return groups


def _partition_raw_parser_gaps(
    *,
    raw_messages: Sequence[Mapping[str, Any]],
    parser_messages: Sequence[Mapping[str, Any]],
    unsupported_main_record_count: int,
    observation_folders: Sequence[Mapping[str, Any]],
    folder_mapping: Mapping[int, int],
) -> dict[str, int]:
    observation_folder_by_hash = {
        str(folder["folder_path_fingerprint"]): int(folder["folder_ordinal"])
        for folder in observation_folders
    }
    empty_coarse_identity = reconciliation._message_identity_fingerprint("")
    raw_groups: Counter[tuple[int, str]] = Counter()
    parser_groups: Counter[tuple[int, str]] = Counter()
    raw_identity_unavailable_count = 0
    parser_identity_unavailable_count = 0
    for message in raw_messages:
        mapped_folder = folder_mapping.get(int(message["folder_ordinal"]))
        identity = message.get("message_identity_fingerprint")
        if (
            mapped_folder is None
            or message.get("message_identity_status") != "passed"
            or not isinstance(identity, str)
            or not identity
        ):
            raw_identity_unavailable_count += 1
            continue
        raw_groups[(mapped_folder, identity)] += 1
    for message in parser_messages:
        mapped_folder = observation_folder_by_hash.get(
            str(message.get("folder_occurrence_hash", ""))
        )
        identity = message.get("oracle_message_identity_fingerprint")
        if (
            mapped_folder is None
            or not isinstance(identity, str)
            or not identity
            or identity == empty_coarse_identity
        ):
            parser_identity_unavailable_count += 1
            continue
        parser_groups[(mapped_folder, identity)] += 1

    shared_keys = set(raw_groups) & set(parser_groups)
    singleton_keys = {key for key in shared_keys if raw_groups[key] == parser_groups[key] == 1}
    duplicate_equal_keys = {
        key for key in shared_keys if raw_groups[key] == parser_groups[key] and raw_groups[key] > 1
    }
    cardinality_mismatch_keys = shared_keys - singleton_keys - duplicate_equal_keys
    raw_only_keys = set(raw_groups) - set(parser_groups)
    parser_only_keys = set(parser_groups) - set(raw_groups)
    counts = {
        "forensic_raw_parser_equal_singleton_raw_count": sum(
            raw_groups[key] for key in singleton_keys
        ),
        "forensic_raw_parser_equal_singleton_parser_count": sum(
            parser_groups[key] for key in singleton_keys
        ),
        "forensic_raw_parser_duplicate_equal_raw_count": sum(
            raw_groups[key] for key in duplicate_equal_keys
        ),
        "forensic_raw_parser_duplicate_equal_parser_count": sum(
            parser_groups[key] for key in duplicate_equal_keys
        ),
        "forensic_raw_parser_cardinality_mismatch_raw_count": sum(
            raw_groups[key] for key in cardinality_mismatch_keys
        ),
        "forensic_raw_parser_cardinality_mismatch_parser_count": sum(
            parser_groups[key] for key in cardinality_mismatch_keys
        ),
        "forensic_raw_parser_raw_only_coarse_identity_count": sum(
            raw_groups[key] for key in raw_only_keys
        ),
        "forensic_raw_parser_parser_only_coarse_identity_count": sum(
            parser_groups[key] for key in parser_only_keys
        ),
        "forensic_raw_parser_raw_identity_unavailable_count": (raw_identity_unavailable_count),
        "forensic_raw_parser_parser_identity_unavailable_count": (
            parser_identity_unavailable_count
        ),
        "forensic_raw_parser_equal_singleton_group_count": len(singleton_keys),
        "forensic_raw_parser_duplicate_equal_group_count": len(duplicate_equal_keys),
        "forensic_raw_parser_cardinality_mismatch_group_count": len(cardinality_mismatch_keys),
        "forensic_raw_parser_raw_only_group_count": len(raw_only_keys),
        "forensic_raw_parser_parser_only_group_count": len(parser_only_keys),
        "forensic_raw_parser_unsupported_main_record_count": (unsupported_main_record_count),
        "forensic_raw_parser_parsed_message_gap_count": max(
            len(raw_messages) - len(parser_messages),
            0,
        ),
        "forensic_raw_parser_export_record_gap_count": max(
            len(raw_messages) - len(parser_messages) - unsupported_main_record_count,
            0,
        ),
    }
    raw_partition_count = (
        counts["forensic_raw_parser_equal_singleton_raw_count"]
        + counts["forensic_raw_parser_duplicate_equal_raw_count"]
        + counts["forensic_raw_parser_cardinality_mismatch_raw_count"]
        + counts["forensic_raw_parser_raw_only_coarse_identity_count"]
        + counts["forensic_raw_parser_raw_identity_unavailable_count"]
    )
    parser_partition_count = (
        counts["forensic_raw_parser_equal_singleton_parser_count"]
        + counts["forensic_raw_parser_duplicate_equal_parser_count"]
        + counts["forensic_raw_parser_cardinality_mismatch_parser_count"]
        + counts["forensic_raw_parser_parser_only_coarse_identity_count"]
        + counts["forensic_raw_parser_parser_identity_unavailable_count"]
    )
    if raw_partition_count != len(raw_messages):
        raise RuntimeError("raw_parser_forensic_raw_partition_invalid")
    if parser_partition_count != len(parser_messages):
        raise RuntimeError("raw_parser_forensic_parser_partition_invalid")
    return counts


def _partition_attachment_gaps(
    *,
    parser_attachments: Sequence[Mapping[str, Any]],
    observation_attachments: Sequence[Mapping[str, Any]],
    unmatched_parser_indexes: set[int],
    unmatched_observation_indexes: set[int],
) -> dict[str, int]:
    parser_by_parent: dict[str, list[Mapping[str, Any]]] = {}
    for index in unmatched_parser_indexes:
        attachment = parser_attachments[index]
        parser_by_parent.setdefault(
            str(attachment["parent_observation_occurrence_fingerprint"]),
            [],
        ).append(attachment)

    reason_counts: Counter[str] = Counter()
    for index in unmatched_observation_indexes:
        observation = observation_attachments[index]
        candidates = parser_by_parent.get(
            str(observation["parent_observation_occurrence_fingerprint"]),
            [],
        )
        if not candidates:
            reason_counts["parent_without_parser_attachment"] += 1
        elif any(
            candidate["attachment_content_hash"] == observation["attachment_content_hash"]
            and candidate["attachment_id_fingerprint"] == observation["attachment_id_fingerprint"]
            and candidate["attachment_ordinal"] == observation["attachment_ordinal"]
            for candidate in candidates
        ):
            reason_counts["exact_full_identity_candidate"] += 1
        elif any(
            candidate["attachment_content_hash"] == observation["attachment_content_hash"]
            and candidate["attachment_name_fingerprint"]
            == observation["attachment_name_fingerprint"]
            for candidate in candidates
        ):
            reason_counts["content_name_candidate"] += 1
        elif any(
            candidate["attachment_content_hash"] == observation["attachment_content_hash"]
            for candidate in candidates
        ):
            reason_counts["content_only_candidate"] += 1
        elif any(
            candidate["attachment_name_fingerprint"] == observation["attachment_name_fingerprint"]
            for candidate in candidates
        ):
            reason_counts["name_only_candidate"] += 1
        elif any(
            candidate["attachment_ordinal"] == observation["attachment_ordinal"]
            for candidate in candidates
        ):
            reason_counts["ordinal_only_candidate"] += 1
        else:
            reason_counts["no_shared_signature"] += 1

    counts = {
        "forensic_attachment_unmatched_parser_count": len(unmatched_parser_indexes),
        "forensic_attachment_unresolved_observation_count": len(unmatched_observation_indexes),
        **{
            f"forensic_attachment_{reason}_observation_count": reason_counts[reason]
            for reason in (
                "parent_without_parser_attachment",
                "exact_full_identity_candidate",
                "content_name_candidate",
                "content_only_candidate",
                "name_only_candidate",
                "ordinal_only_candidate",
                "no_shared_signature",
            )
        },
    }
    observation_partition_count = sum(
        count
        for field, count in counts.items()
        if field.endswith("_observation_count")
        and field != "forensic_attachment_unresolved_observation_count"
    )
    if observation_partition_count != len(unmatched_observation_indexes):
        raise RuntimeError("attachment_forensic_observation_partition_invalid")
    return counts


def _parser_warning_forensic_counts(
    parser_manifest: Mapping[str, Any],
) -> dict[str, int]:
    warning_counts = Counter(parser_manifest.get("parse_warning_fingerprints", []))
    known_total = 0
    counts: dict[str, int] = {}
    for code in KNOWN_PARSER_WARNING_CODES:
        count = warning_counts[sha256_json(code)]
        known_total += count
        safe_name = code.removeprefix("pst_parser_")
        counts[f"forensic_parser_warning_{safe_name}_count"] = count
    counts["forensic_parser_warning_unmapped_count"] = sum(warning_counts.values()) - known_total
    counts["forensic_parser_warning_gap_attribution_count"] = 0
    return counts


def _forensic_value_available(value: Any) -> bool:
    return (
        value is not None
        and not isinstance(value, bool)
        and value != ""
        and value != sha256_json("")
    )


def _private_observation_message_rows(
    observation_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for row in observation_rows:
        if row.get("observation_type") != "email_message":
            continue
        location = row.get("location") or {}
        payload = row.get("payload") or {}
        message_occurrence_id = str(
            location.get("message_occurrence_id") or payload.get("message_occurrence_id") or ""
        )
        messages.append(
            {
                "message_occurrence_fingerprint": sha256_json(message_occurrence_id),
                "exported_message_identity_fingerprint": str(
                    payload.get("message_fingerprint") or ""
                ),
                "message_id_fingerprint": sha256_json(str(payload.get("message_id") or "")),
                "body_hash": str(payload.get("body_hash") or ""),
                "message_identity_fingerprint": sha256_json(
                    reconciliation._normalize_identity_text(str(payload.get("subject") or ""))
                ),
                "sender_identity_fingerprint": sha256_json(
                    reconciliation._normalize_identity_text(str(payload.get("sender") or ""))
                ),
                "date_identity_fingerprint": sha256_json(
                    reconciliation._normalize_identity_text(str(payload.get("sent_at") or ""))
                ),
                "folder_occurrence_hash": str(location.get("folder_path_hash") or ""),
            }
        )
    return messages


def _bind_parser_messages_to_raw_oracle(
    *,
    parser_messages: Sequence[Mapping[str, Any]],
    raw_messages: Sequence[Mapping[str, Any]],
    observation_folders: Sequence[Mapping[str, Any]],
    folder_mapping: Mapping[int, int],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, int]]:
    observation_folder_by_hash = {
        str(folder["folder_path_fingerprint"]): int(folder["folder_ordinal"])
        for folder in observation_folders
    }
    raw_groups: dict[tuple[int, int], list[Mapping[str, Any]]] = {}
    for raw_message in raw_messages:
        observation_folder_ordinal = folder_mapping.get(int(raw_message["folder_ordinal"]))
        if observation_folder_ordinal is None:
            continue
        key = (
            observation_folder_ordinal,
            int(raw_message["message_ordinal"]),
        )
        raw_groups.setdefault(key, []).append(raw_message)

    parser_groups: dict[
        tuple[int, int],
        list[Mapping[str, Any]],
    ] = {}
    parser_folder_identity_missing_count = 0
    for parser_message in parser_messages:
        folder_ordinal = observation_folder_by_hash.get(
            str(parser_message["folder_occurrence_hash"])
        )
        if folder_ordinal is None:
            parser_folder_identity_missing_count += 1
            continue
        key = (
            folder_ordinal,
            int(parser_message["source_local_ordinal"]),
        )
        parser_groups.setdefault(key, []).append(parser_message)

    parser_raw_by_source_key: dict[str, Mapping[str, Any]] = {}
    identity_mismatch_count = 0
    nonunique_ordinal_count = 0
    for key in sorted(set(parser_groups) & set(raw_groups)):
        if len(parser_groups[key]) != 1 or len(raw_groups[key]) != 1:
            nonunique_ordinal_count += 1
            continue
        parser_message = parser_groups[key][0]
        raw_message = raw_groups[key][0]
        if not _parser_raw_identity_matches(parser_message, raw_message):
            identity_mismatch_count += 1
            continue
        parser_raw_by_source_key[str(parser_message["source_local_key"])] = raw_message
    matched_raw_occurrences = {
        str(message["oracle_occurrence_fingerprint"])
        for message in parser_raw_by_source_key.values()
    }
    return parser_raw_by_source_key, {
        "raw_parser_message_binding_count": len(parser_raw_by_source_key),
        "unmatched_raw_parser_message_count": (len(raw_messages) - len(matched_raw_occurrences)),
        "unmatched_parser_raw_message_count": (
            len(parser_messages) - len(parser_raw_by_source_key)
        ),
        "parser_raw_identity_mismatch_count": identity_mismatch_count,
        "parser_raw_nonunique_ordinal_count": nonunique_ordinal_count,
        "parser_folder_identity_missing_count": (parser_folder_identity_missing_count),
    }


def _parser_raw_identity_matches(
    parser_message: Mapping[str, Any],
    raw_message: Mapping[str, Any],
) -> bool:
    if parser_message.get("oracle_message_identity_fingerprint") != raw_message.get(
        "message_identity_fingerprint"
    ):
        return False
    if raw_message.get("sender_identity_status") == "passed" and parser_message.get(
        "sender_identity_fingerprint"
    ) != raw_message.get("sender_identity_fingerprint"):
        return False
    empty_fingerprint = sha256_json("")
    parser_day = parser_message.get("date_day_identity_fingerprint")
    if (
        raw_message.get("date_day_identity_status") == "passed"
        and parser_day != empty_fingerprint
        and parser_day != raw_message.get("date_day_identity_fingerprint")
    ):
        return False
    return True


def _private_parser_attachment_rows(
    *,
    parser_messages: Sequence[Mapping[str, Any]],
    parent_observation_by_source_key: Mapping[str, str],
) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for message in parser_messages:
        parent_source_local_key = str(message["source_local_key"])
        parent_observation = parent_observation_by_source_key.get(parent_source_local_key)
        if parent_observation is None:
            continue
        for attachment in message.get("attachments", []):
            attachments.append(
                {
                    **attachment,
                    "parent_source_local_key": parent_source_local_key,
                    "parent_observation_occurrence_fingerprint": (parent_observation),
                }
            )
    return attachments


def _private_observation_attachment_rows(
    observation_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for row in observation_rows:
        if row.get("observation_type") != "email_attachment_occurrence":
            continue
        location = row.get("location") or {}
        payload = row.get("payload") or {}
        attachment_id = str(payload.get("attachment_id") or "")
        filename = str(payload.get("filename") or "")
        message_occurrence_id = str(
            location.get("message_occurrence_id") or payload.get("message_occurrence_id") or ""
        )
        attachment_ordinal = location.get("attachment_index")
        if not isinstance(attachment_ordinal, int) or isinstance(attachment_ordinal, bool):
            continue
        attachments.append(
            {
                "parent_observation_occurrence_fingerprint": sha256_json(message_occurrence_id),
                "attachment_id_fingerprint": sha256_json(attachment_id),
                "attachment_content_hash": str(payload.get("content_hash") or ""),
                "attachment_name_fingerprint": sha256_json(filename),
                "attachment_ordinal": attachment_ordinal,
                "observation_id_fingerprint": sha256_json(str(row.get("observation_id") or "")),
            }
        )
    return attachments


def _unique_cross_field_matches(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    *,
    stages: Sequence[tuple[str, tuple[str, ...], tuple[str, ...]]],
) -> tuple[
    list[tuple[str, int, int]],
    dict[str, int],
    set[int],
    set[int],
]:
    remaining_left = set(range(len(left_rows)))
    remaining_right = set(range(len(right_rows)))
    matches: list[tuple[str, int, int]] = []
    stage_counts = {stage_id: 0 for stage_id, _left, _right in stages}
    for stage_id, left_fields, right_fields in stages:
        left_groups = _cross_field_groups(
            rows=left_rows,
            indexes=remaining_left,
            fields=left_fields,
        )
        right_groups = _cross_field_groups(
            rows=right_rows,
            indexes=remaining_right,
            fields=right_fields,
        )
        unique_keys = {
            key
            for key in set(left_groups) & set(right_groups)
            if len(left_groups[key]) == 1 and len(right_groups[key]) == 1
        }
        stage_counts[stage_id] = len(unique_keys)
        for key in sorted(unique_keys, key=repr):
            left_index = left_groups[key][0]
            right_index = right_groups[key][0]
            matches.append((stage_id, left_index, right_index))
            remaining_left.remove(left_index)
            remaining_right.remove(right_index)
    return matches, stage_counts, remaining_left, remaining_right


def _cross_field_groups(
    *,
    rows: Sequence[Mapping[str, Any]],
    indexes: set[int],
    fields: Sequence[str],
) -> dict[tuple[Any, ...], list[int]]:
    groups: dict[tuple[Any, ...], list[int]] = {}
    for index in indexes:
        values = tuple(rows[index].get(field) for field in fields)
        if any(
            value is None or isinstance(value, bool) or (isinstance(value, str) and not value)
            for value in values
        ):
            continue
        groups.setdefault(values, []).append(index)
    return groups


def _load_private_binding(
    *,
    preserved_work_dir: Path,
    source_asset_sha256: str,
) -> dict[str, Any]:
    ingestion_root = preserved_work_dir / "data" / "ingestion"
    matching_assets = [
        row
        for row in reconciliation._read_json_files(ingestion_root / "assets")
        if row.get("content_hash") == source_asset_sha256
    ]
    if len(matching_assets) != 1:
        raise RuntimeError("source_asset_binding_unavailable")
    asset = matching_assets[0]
    permission_scope = asset.get("permission_scope")
    if not isinstance(permission_scope, dict):
        raise RuntimeError("source_permission_binding_unavailable")
    return {
        "source_asset_id": reconciliation._required_string(
            asset.get("asset_id"),
            "asset_id",
        ),
        "permission_scope": permission_scope,
        "created_at": reconciliation._required_string(
            asset.get("created_at"),
            "created_at",
        ),
    }


def _unique_folder_mapping(
    *,
    oracle_folders: Sequence[Mapping[str, Any]],
    observation_folders: Sequence[Mapping[str, Any]],
    oracle_messages: Sequence[Mapping[str, Any]],
    observation_messages: Sequence[Mapping[str, Any]],
) -> dict[int, int]:
    oracle_by_folder = reconciliation._messages_by_folder(oracle_messages)
    observation_by_folder = reconciliation._messages_by_folder(observation_messages)
    raw_ordinals = [int(folder["folder_ordinal"]) for folder in oracle_folders]
    observation_ordinals = [int(folder["folder_ordinal"]) for folder in observation_folders]
    if len(raw_ordinals) != len(observation_ordinals):
        raise RuntimeError("folder_count_identity_unresolved")
    scored: list[tuple[tuple[int, int], dict[int, int]]] = []
    for permutation in itertools.permutations(observation_ordinals):
        mapping = dict(zip(raw_ordinals, permutation, strict=True))
        overlap = 0
        count_delta = 0
        for raw_ordinal, observation_ordinal in mapping.items():
            raw_counter = Counter(
                message["message_identity_fingerprint"]
                for message in oracle_by_folder.get(raw_ordinal, [])
            )
            observation_counter = Counter(
                message["message_identity_fingerprint"]
                for message in observation_by_folder.get(
                    observation_ordinal,
                    [],
                )
            )
            overlap += sum((raw_counter & observation_counter).values())
            count_delta += abs(sum(raw_counter.values()) - sum(observation_counter.values()))
        scored.append(((overlap, -count_delta), mapping))
    best_score = max(score for score, _mapping in scored)
    best_mappings = [mapping for score, mapping in scored if score == best_score]
    if len(best_mappings) != 1:
        raise RuntimeError("folder_identity_mapping_not_unique")
    return best_mappings[0]


def _build_unique_rebindings(
    *,
    folder_mapping: Mapping[int, int],
    oracle_messages: Sequence[Mapping[str, Any]],
    observation_messages: Sequence[Mapping[str, Any]],
) -> tuple[
    list[dict[str, str]],
    dict[str, int],
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
]:
    remaining_raw = [
        {
            **message,
            "_mapped_folder_ordinal": folder_mapping.get(int(message["folder_ordinal"])),
        }
        for message in oracle_messages
    ]
    remaining_observations = [
        {**message, "_mapped_folder_ordinal": int(message["folder_ordinal"])}
        for message in observation_messages
    ]
    stages = (
        (
            "subject_unique",
            ("message_identity_fingerprint",),
            ("message_identity_status",),
        ),
        (
            "subject_sender_day_unique",
            (
                "message_identity_fingerprint",
                "sender_identity_fingerprint",
                "date_day_identity_fingerprint",
            ),
            (
                "message_identity_status",
                "sender_identity_status",
                "date_day_identity_status",
            ),
        ),
        (
            "subject_sender_unique",
            (
                "message_identity_fingerprint",
                "sender_identity_fingerprint",
            ),
            ("message_identity_status", "sender_identity_status"),
        ),
        (
            "subject_day_unique",
            (
                "message_identity_fingerprint",
                "date_day_identity_fingerprint",
            ),
            ("message_identity_status", "date_day_identity_status"),
        ),
    )
    rebindings: list[dict[str, str]] = []
    stage_counts = {stage_id: 0 for stage_id, _fields, _statuses in stages}
    for stage_id, fields, statuses in stages:
        raw_groups = _identity_groups(
            remaining_raw,
            fields=fields,
            statuses=statuses,
        )
        observation_groups = _identity_groups(
            remaining_observations,
            fields=fields,
            statuses=statuses,
        )
        unique_keys = {
            key
            for key in set(raw_groups) & set(observation_groups)
            if len(raw_groups[key]) == 1 and len(observation_groups[key]) == 1
        }
        matched_raw = set()
        matched_observations = set()
        for key in sorted(unique_keys):
            raw_message = raw_groups[key][0]
            observation_message = observation_groups[key][0]
            raw_occurrence = str(raw_message["oracle_occurrence_fingerprint"])
            observation_occurrence = str(observation_message["message_occurrence_fingerprint"])
            matched_raw.add(raw_occurrence)
            matched_observations.add(observation_occurrence)
            rebindings.append(
                {
                    "identity_stage_fingerprint": sha256_json(stage_id),
                    "oracle_occurrence_fingerprint": raw_occurrence,
                    "observation_occurrence_fingerprint": (observation_occurrence),
                    "exported_message_identity_fingerprint": str(
                        observation_message["exported_message_identity_fingerprint"]
                    ),
                }
            )
        stage_counts[stage_id] = len(unique_keys)
        remaining_raw = [
            message
            for message in remaining_raw
            if message["oracle_occurrence_fingerprint"] not in matched_raw
        ]
        remaining_observations = [
            message
            for message in remaining_observations
            if message["message_occurrence_fingerprint"] not in matched_observations
        ]
    return (
        rebindings,
        stage_counts,
        remaining_raw,
        remaining_observations,
    )


def _identity_groups(
    messages: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
    statuses: Sequence[str],
) -> dict[tuple[str, ...], list[Mapping[str, Any]]]:
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for message in messages:
        folder_ordinal = message.get("_mapped_folder_ordinal")
        if not isinstance(folder_ordinal, int):
            continue
        if any(message.get(status) != "passed" for status in statuses):
            continue
        key = (str(folder_ordinal),) + tuple(str(message[field]) for field in fields)
        groups.setdefault(key, []).append(message)
    return groups


def _build_source_inventory(
    *,
    oracle_manifest: Mapping[str, Any],
    rebindings: Sequence[Mapping[str, str]],
    private_binding: Mapping[str, Any],
) -> tuple[SourceInventory, list[dict[str, str]]]:
    rebound_by_oracle = {
        binding["oracle_occurrence_fingerprint"]: binding for binding in rebindings
    }
    items = []
    item_by_oracle: dict[str, SourceInventoryItem] = {}
    for ordinal, message in enumerate(
        oracle_manifest["messages"],
        start=1,
    ):
        oracle_occurrence = str(message["oracle_occurrence_fingerprint"])
        item = SourceInventoryItem.create(
            source_asset_id=str(private_binding["source_asset_id"]),
            structure_kind="pst_message_occurrence",
            content_type="message/rfc822",
            ordinal=ordinal,
            processing_state=(
                SourceInventoryProcessingState.PARSED
                if oracle_occurrence in rebound_by_oracle
                else SourceInventoryProcessingState.PRESERVED_UNPARSED
            ),
            raw_retention_state=(SourceInventoryRawRetentionState.EXTERNALLY_MANAGED),
            source_fingerprint=str(oracle_manifest["source_asset_sha256"]),
            parser_fingerprint=str(oracle_manifest["oracle_profile_fingerprint"]),
            permission_scope=private_binding["permission_scope"],
            location={
                "source_local_key": stable_resource_contract_id(
                    "pstoracle",
                    "Issue56PstOracleMessage",
                    {
                        "source_asset_sha256": oracle_manifest["source_asset_sha256"],
                        "oracle_occurrence_fingerprint": oracle_occurrence,
                    },
                ),
                "oracle_occurrence_fingerprint": oracle_occurrence,
                "folder_identity_fingerprint": message["folder_identity_fingerprint"],
                "message_identity_fingerprint": message["message_identity_fingerprint"],
                "sender_identity_fingerprint": message["sender_identity_fingerprint"],
                "date_day_identity_fingerprint": message["date_day_identity_fingerprint"],
            },
        )
        items.append(item)
        item_by_oracle[oracle_occurrence] = item
    inventory = SourceInventory.create(
        source_asset_id=str(private_binding["source_asset_id"]),
        items=items,
        source_fingerprint=str(oracle_manifest["source_asset_sha256"]),
        parser_fingerprint=str(oracle_manifest["oracle_profile_fingerprint"]),
        created_at=str(private_binding["created_at"]),
    )
    rebound_entries = []
    for binding in sorted(
        rebindings,
        key=lambda item: (
            item["oracle_occurrence_fingerprint"],
            item["observation_occurrence_fingerprint"],
        ),
    ):
        inventory_item = item_by_oracle[binding["oracle_occurrence_fingerprint"]]
        rebound_entries.append(
            {
                **binding,
                "source_inventory_id_fingerprint": sha256_json(inventory.source_inventory_id),
                "source_inventory_item_id_fingerprint": sha256_json(
                    inventory_item.source_inventory_item_id
                ),
            }
        )
    return inventory, rebound_entries


def _attachment_lineage_counts(
    *,
    preserved_work_dir: Path,
    rebound_observation_occurrence_fingerprints: set[str],
) -> dict[str, int]:
    observation_rows = reconciliation._read_json_files(
        preserved_work_dir / "data" / "ingestion" / "observations"
    )
    attachment_count = 0
    attachment_occurrence_identity_count = 0
    attachment_parent_rebound_count = 0
    attachment_source_inventory_binding_count = 0
    for row in observation_rows:
        if row.get("observation_type") != "email_attachment_occurrence":
            continue
        attachment_count += 1
        location = row.get("location") or {}
        payload = row.get("payload") or {}
        attachment_identity = (
            location.get("attachment_occurrence_id")
            or payload.get("attachment_occurrence_id")
            or location.get("attachment_id")
            or payload.get("attachment_id")
        )
        attachment_occurrence_identity_count += int(
            isinstance(attachment_identity, str) and bool(attachment_identity)
        )
        parent_occurrence = location.get("message_occurrence_id") or payload.get(
            "message_occurrence_id"
        )
        attachment_parent_rebound_count += int(
            isinstance(parent_occurrence, str)
            and sha256_json(parent_occurrence) in rebound_observation_occurrence_fingerprints
        )
        source_inventory_item_id = location.get("source_inventory_item_id") or payload.get(
            "source_inventory_item_id"
        )
        attachment_source_inventory_binding_count += int(
            isinstance(source_inventory_item_id, str) and bool(source_inventory_item_id)
        )
    return {
        "observed_attachment_count": attachment_count,
        "attachment_occurrence_identity_count": (attachment_occurrence_identity_count),
        "attachment_parent_message_rebound_count": (attachment_parent_rebound_count),
        "attachment_source_inventory_binding_count": (attachment_source_inventory_binding_count),
        "attachment_inventory_gap_count": (
            attachment_count - attachment_source_inventory_binding_count
        ),
    }


def _persist_immutable(
    path: Path,
    payload: Mapping[str, Any],
    *,
    fingerprint_field: str,
) -> dict[str, Any]:
    canonical = json.loads(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    if canonical.get(fingerprint_field) != _payload_fingerprint(
        canonical,
        fingerprint_field,
    ):
        raise RuntimeError("immutable_artifact_fingerprint_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(canonical, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if loaded != canonical:
            raise RuntimeError("immutable_artifact_conflict")
        return loaded
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if loaded != canonical:
        raise RuntimeError("immutable_artifact_round_trip_failed")
    return loaded


def _payload_fingerprint(
    payload: Mapping[str, Any],
    field_name: str,
) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != field_name})


def _validate_public_report(report: Mapping[str, Any]) -> None:
    if report.get("artifact_id") != ARTIFACT_ID:
        raise RuntimeError("rebind_report_artifact_invalid")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise RuntimeError("rebind_report_fingerprint_invalid")
    counts = report.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(value, int) or isinstance(value, bool) for value in counts.values()
    ):
        raise RuntimeError("rebind_report_counts_invalid")
    for key, value in report.items():
        if key.endswith("_fingerprint"):
            if not isinstance(value, str) or not _FINGERPRINT_RE.fullmatch(value):
                raise RuntimeError("rebind_report_fingerprint_field_invalid")
    assert_no_public_raw_references(
        report,
        "issue56_source_complete_snapshot_rebind_report",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pst", type=Path, default=DEFAULT_PST)
    parser.add_argument(
        "--preserved-work-dir",
        type=Path,
        default=DEFAULT_PRESERVED_WORK_DIR,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    parser.add_argument(
        "--snapshot-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "snapshot.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "report.json",
    )
    parser.add_argument("--lspst-command", default="lspst")
    parser.add_argument("--parser-manifest", type=Path)
    parser.add_argument("--native-manifest", type=Path)
    parser.add_argument("--native-export-root", type=Path)
    parser.add_argument("--snapshot-created-at")
    parser.add_argument(
        "--retrieval-ready-output-root",
        type=Path,
        help=(
            "Build the private parsed Observation snapshot, MailEvidenceBundle, "
            "target index proof, and hash/count/status-only report under this root"
        ),
    )
    args = parser.parse_args()
    if args.native_manifest is not None:
        if args.native_export_root is None:
            parser.error("--native-export-root is required with --native-manifest")
        if args.parser_manifest is not None:
            parser.error("--parser-manifest cannot be combined with --native-manifest")
        if args.retrieval_ready_output_root is None:
            artifacts = run_native_source_complete_snapshot(
                native_manifest_path=args.native_manifest,
                native_export_root=args.native_export_root,
                preserved_work_dir=args.preserved_work_dir,
                snapshot_output=args.snapshot_output,
                report_output=args.output,
                created_at=args.snapshot_created_at,
            )
            printable_report = artifacts.report
        else:
            retrieval_root = args.retrieval_ready_output_root
            retrieval_artifacts = run_native_retrieval_ready_mail_evidence(
                native_manifest_path=args.native_manifest,
                native_export_root=args.native_export_root,
                preserved_work_dir=args.preserved_work_dir,
                source_snapshot_output=args.snapshot_output,
                source_report_output=args.output,
                retrieval_snapshot_output=(
                    retrieval_root / "retrieval-ready-snapshot.private.json"
                ),
                bundle_output=(retrieval_root / "mail-evidence-bundle.private.json"),
                report_output=retrieval_root / "retrieval-ready-report.safe.json",
                created_at=args.snapshot_created_at,
            )
            printable_report = retrieval_artifacts.report
    else:
        if (
            args.native_export_root is not None
            or args.snapshot_created_at is not None
            or args.retrieval_ready_output_root is not None
        ):
            parser.error(
                "--native-export-root/--snapshot-created-at/"
                "--retrieval-ready-output-root require --native-manifest"
            )
        artifacts = run_source_complete_snapshot_rebind(
            pst_path=args.pst,
            preserved_work_dir=args.preserved_work_dir,
            output_root=args.output_root,
            snapshot_output=args.snapshot_output,
            report_output=args.output,
            lspst_command=args.lspst_command,
            parser_manifest_path=args.parser_manifest,
        )
        printable_report = artifacts.report
    print(json.dumps(printable_report, sort_keys=True))
    return 0 if printable_report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
