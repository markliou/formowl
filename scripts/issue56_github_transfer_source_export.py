#!/usr/bin/env python3
"""Capture and seal one source-complete GitHub issue/comment transfer snapshot.

The live source scope is deliberately narrow and closed:

* repository issue records #51 through #56;
* every top-level issue comment declared by those issue records.

Timeline events, reactions, pull-request records, and attachments are outside
the oracle scope. Their absence is never interpreted as a zero count. The
result is a private source-preserving Asset/SourceInventory/Observation packet,
plus hash/count/status-only public-safe reports and an unexecuted transfer
holdout manifest.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from typing import Any, Mapping, Protocol, Sequence
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    Asset,
    ContractValidationError,
    ExtractorRun,
    Observation,
    SourceInventory,
    SourceInventoryItem,
    SourceRef,
    assert_no_public_raw_references,
    sha256_json,
    stable_asset_id,
    stable_extractor_run_id,
    stable_observation_id,
    stable_resource_contract_id,
    stable_storage_backend_id,
)

ARTIFACT_ID = "formowl_issue56_github_transfer_source_export_v1"
COMPLETENESS_REPORT_ARTIFACT_ID = "formowl_issue56_github_transfer_source_completeness_report_v1"
HOLDOUT_ARTIFACT_ID = "formowl_issue56_github_transfer_holdout_manifest_v1"
HOLDOUT_REPORT_ARTIFACT_ID = "formowl_issue56_github_transfer_holdout_preflight_v1"
SCHEMA_VERSION = 1
REPOSITORY = "markliou/formowl"
ISSUE_NUMBERS = (51, 52, 53, 54, 55, 56)
API_VERSION = "2022-11-28"
SOURCE_KIND = "github_project_observation"
SOURCE_OCCURRENCE_SCHEMA_ID = "github_issue_comment_occurrence_v1"
CAPTURE_POLICY_ID = "issue56_github_issue_comment_source_capture_v1"
HOLDOUT_POLICY_ID = "issue56_github_project_transfer_holdout_authoring_v1"
ROUTING_PROFILE_ID = "issue56_github_transfer_source_authored_typed_routing_v1"
ROUTING_CONTRACT_SCHEMA_ID = "formowl_issue56_source_authored_query_route_v1"
ORACLE_FREE_PROJECTION_SCHEMA_ID = "formowl_issue56_github_transfer_oracle_free_projection_v1"
DIAGNOSTIC_CLASSIFICATION = "diagnostic_only_source_authored_transfer_fixture"
DIAGNOSTIC_CLAIM_BOUNDARY = "ten_case_diagnostic_not_final_acceptance"
DEFAULT_OUTPUT_ROOT = ROOT / ".test-tmp" / "issue56-transfer-github-project-v1"
PRIVATE_EXPORT_NAME = "source-export.private.json"
SAFE_COMPLETENESS_NAME = "source-completeness.safe.json"
PRIVATE_HOLDOUT_NAME = "transfer-holdout-manifest.private.json"
SAFE_HOLDOUT_NAME = "transfer-holdout-preflight.safe.json"
OWNER_USER_ID = "user_issue56_github_transfer_owner"
WORKSPACE_ID = "workspace_issue56_github_transfer"
PROJECT_ID = "project_issue56_github_transfer"
SHARED_PERMISSION_SCOPE = {
    "scope_type": "project",
    "visibility": "shared",
    "scope_id": PROJECT_ID,
}
RESTRICTED_PERMISSION_SCOPE = {
    "scope_type": "private_user",
    "visibility": "private",
    "scope_id": OWNER_USER_ID,
}
DENIED_REQUESTER_ID = "user_issue56_github_transfer_denied"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ISSUE_REFERENCE_RE = re.compile(r"(?<![A-Za-z0-9_])#([1-9][0-9]*)\b")
_SAFE_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_STRATA_COUNTS = {
    "direct": 2,
    "cross_issue_relation": 2,
    "temporal_status": 2,
    "exact_count_inventory": 2,
    "no_answer": 1,
    "permission_denied": 1,
}
_ROUTING_INTENT_BY_STRATUM = {
    "direct": "source_native_field_lookup",
    "cross_issue_relation": "source_native_relation_path",
    "temporal_status": "source_native_temporal_state",
    "exact_count_inventory": "complete_source_inventory",
    "no_answer": "complete_scope_absence_lookup",
    "permission_denied": "permission_boundary_lookup",
}
_QUERY_CLASS_BY_ROUTING_INTENT = {
    "source_native_field_lookup": "evidence_lookup",
    "source_native_relation_path": "relation_reasoning",
    "source_native_temporal_state": "relation_reasoning",
    "complete_source_inventory": "exact_set_or_inventory",
    "complete_scope_absence_lookup": "evidence_lookup",
    "permission_boundary_lookup": "evidence_lookup",
}
_QUERY_CLASS_BY_STRATUM = {
    stratum: _QUERY_CLASS_BY_ROUTING_INTENT[routing_intent]
    for stratum, routing_intent in _ROUTING_INTENT_BY_STRATUM.items()
}
_EXPECTED_QUERY_CLASS_COUNTS = dict(
    sorted(
        Counter(
            {
                query_class: sum(
                    _STRATA_COUNTS[stratum]
                    for stratum, routed_class in _QUERY_CLASS_BY_STRATUM.items()
                    if routed_class == query_class
                )
                for query_class in set(_QUERY_CLASS_BY_STRATUM.values())
            }
        ).items()
    )
)
_SOURCE_OCCURRENCE_SCHEMA = {
    "schema_id": SOURCE_OCCURRENCE_SCHEMA_ID,
    "source_kind": SOURCE_KIND,
    "record_kinds": {
        "issue_record": {"parent_rule": "absent"},
        "top_level_issue_comment": {"parent_rule": "required_exact_issue_source_local_key"},
    },
    "mixed_source_kinds_allowed": False,
}
SOURCE_OCCURRENCE_SCHEMA_FINGERPRINT = sha256_json(_SOURCE_OCCURRENCE_SCHEMA)
_ROUTING_PROFILE = {
    "profile_id": ROUTING_PROFILE_ID,
    "schema_version": 1,
    "source_family": "github_project_issue_comment",
    "classifier_kind": "source_authored_typed_intent_router",
    "typed_input_schema": {
        "field": "authored_intent_kind",
        "allowed_values": sorted(_QUERY_CLASS_BY_ROUTING_INTENT),
    },
    "query_class_by_authored_intent": dict(sorted(_QUERY_CLASS_BY_ROUTING_INTENT.items())),
    "stratum_to_authored_intent": dict(sorted(_ROUTING_INTENT_BY_STRATUM.items())),
    "query_text_inference_authoritative": False,
    "query_text_mutation_allowed": False,
    "runtime_parameter_tuning_allowed": False,
}
ROUTING_PROFILE_FINGERPRINT = sha256_json(_ROUTING_PROFILE)
_CAPTURE_POLICY = {
    "policy_id": CAPTURE_POLICY_ID,
    "repository": REPOSITORY,
    "issue_numbers": list(ISSUE_NUMBERS),
    "included_resource_kinds": ["issue_record", "top_level_issue_comment"],
    "excluded_resource_kinds": [
        "attachment",
        "event",
        "pull_request_record",
        "reaction",
        "timeline",
    ],
    "comment_pagination": "follow_next_link_or_short_page_until_terminal",
    "issue_comment_count_reconciliation": "required_exact_equality",
    "source_mutation": False,
}
CAPTURE_POLICY_FINGERPRINT = sha256_json(_CAPTURE_POLICY)
_HOLDOUT_POLICY = {
    "policy_id": HOLDOUT_POLICY_ID,
    "classification": DIAGNOSTIC_CLASSIFICATION,
    "claim_boundary_status": DIAGNOSTIC_CLAIM_BOUNDARY,
    "diagnostic_only": True,
    "final_acceptance_eligible": False,
    "source_family": "github_project_issue_comment",
    "source_scope_fingerprint": CAPTURE_POLICY_FINGERPRINT,
    "case_strata_counts": _STRATA_COUNTS,
    "selection": "source_native_fields_and_explicit_issue_reference_edges_only",
    "core_query_classes": [
        "evidence_lookup",
        "exact_set_or_inventory",
        "relation_reasoning",
    ],
    "routing_profile_id": ROUTING_PROFILE_ID,
    "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
    "routing_authority": "source_authored_typed_intent_router",
    "question_specific_aliases": False,
    "runtime_or_evaluator_tuning": False,
    "mail_source_consumed": False,
    "holdout_execution": False,
}
HOLDOUT_POLICY_FINGERPRINT = sha256_json(_HOLDOUT_POLICY)


class GitHubTransferError(RuntimeError):
    """Fail-closed transfer capture/authoring error with one stable reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class HttpJsonResponse:
    payload: Any
    headers: Mapping[str, str]


class GitHubReadClient(Protocol):
    def get_json(self, endpoint: str, query: Mapping[str, str] | None = None) -> HttpJsonResponse:
        """Read one GitHub REST response without source-system mutation."""


class UrllibGitHubReadClient:
    """Minimal unauthenticated reader for one public repository snapshot."""

    def __init__(self, *, api_root: str = "https://api.github.com") -> None:
        self.api_root = api_root.rstrip("/")

    def get_json(
        self,
        endpoint: str,
        query: Mapping[str, str] | None = None,
    ) -> HttpJsonResponse:
        suffix = urllib.parse.urlencode(dict(query or {}))
        request_url = f"{self.api_root}{endpoint}"
        if suffix:
            request_url = f"{request_url}?{suffix}"
        request = urllib.request.Request(
            request_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "formowl-issue56-transfer-source-capture-v1",
                "X-GitHub-Api-Version": API_VERSION,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
                headers = {key.lower(): value for key, value in response.headers.items()}
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise GitHubTransferError("github_read_failed") from exc
        return HttpJsonResponse(payload=payload, headers=headers)


@dataclass(frozen=True)
class TransferArtifacts:
    output_root: Path
    private_export_path: Path
    safe_completeness_path: Path
    private_holdout_path: Path
    safe_holdout_path: Path
    private_export_sha256: str
    private_holdout_sha256: str
    safe_completeness: dict[str, Any]
    safe_holdout: dict[str, Any]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--api-root", default="https://api.github.com")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        capture = acquire_github_scope(UrllibGitHubReadClient(api_root=args.api_root))
        artifacts = build_and_persist_transfer_artifacts(
            capture=capture,
            output_root=args.output_root,
        )
    except (ContractValidationError, GitHubTransferError, RuntimeError) as exc:
        reason_code = getattr(exc, "reason_code", str(exc))
        print(json.dumps(_blocked_report(str(reason_code)), indent=2, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "passed",
                "counts": artifacts.safe_completeness["counts"],
                "holdout_counts": artifacts.safe_holdout["counts"],
                "strata_counts": artifacts.safe_holdout["strata_counts"],
                "hashes": {
                    "private_export_sha256": artifacts.private_export_sha256,
                    "private_holdout_sha256": artifacts.private_holdout_sha256,
                    "safe_completeness_sha256": _sha256_file(artifacts.safe_completeness_path),
                    "safe_holdout_sha256": _sha256_file(artifacts.safe_holdout_path),
                },
                "execution_status": "not_run",
                "diagnostic_only": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def acquire_github_scope(client: GitHubReadClient) -> dict[str, Any]:
    """Acquire the frozen issue/comment scope and prove pagination completeness."""

    issue_records: list[dict[str, Any]] = []
    comments_by_issue: dict[str, list[dict[str, Any]]] = {}
    pagination: dict[str, dict[str, Any]] = {}
    for issue_number in ISSUE_NUMBERS:
        detail_response = client.get_json(
            f"/repos/{REPOSITORY}/issues/{issue_number}",
        )
        issue = _normalize_issue_record(detail_response.payload, issue_number)
        issue_records.append(issue)
        comments, page_evidence = _read_all_comments(client, issue_number)
        if len(comments) != issue["declared_comment_count"]:
            raise GitHubTransferError("github_comment_count_mismatch")
        comments_by_issue[str(issue_number)] = comments
        pagination[str(issue_number)] = page_evidence

    if [item["issue_number"] for item in issue_records] != list(ISSUE_NUMBERS):
        raise GitHubTransferError("github_issue_inventory_mismatch")
    _validate_comment_identity(issue_records, comments_by_issue)
    capture: dict[str, Any] = {
        "artifact_id": "formowl_issue56_github_read_capture_v1",
        "schema_version": SCHEMA_VERSION,
        "capture_policy": _CAPTURE_POLICY,
        "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
        "issue_records": issue_records,
        "comments_by_issue": comments_by_issue,
        "comment_pagination": pagination,
    }
    capture["capture_fingerprint"] = _payload_fingerprint(
        capture,
        "capture_fingerprint",
    )
    _validate_capture(capture)
    return capture


def build_and_persist_transfer_artifacts(
    *,
    capture: Mapping[str, Any],
    output_root: Path,
) -> TransferArtifacts:
    """Build owner-bound source records and an unexecuted transfer holdout."""

    _validate_capture(capture)
    if output_root.exists():
        raise GitHubTransferError("immutable_output_root_exists")
    private_export = _build_private_export(capture)
    _validate_private_export(private_export)
    private_export_bytes = _canonical_pretty_bytes(private_export)
    private_export_sha256 = _sha256_bytes(private_export_bytes)
    safe_completeness = _build_safe_completeness(
        private_export=private_export,
        private_export_sha256=private_export_sha256,
    )
    holdout = _build_transfer_holdout(
        private_export=private_export,
        private_export_sha256=private_export_sha256,
    )
    _validate_transfer_holdout(holdout, private_export=private_export)
    holdout_bytes = _canonical_pretty_bytes(holdout)
    holdout_sha256 = _sha256_bytes(holdout_bytes)
    safe_holdout = _build_safe_holdout(
        private_export=private_export,
        private_export_sha256=private_export_sha256,
        holdout=holdout,
        holdout_sha256=holdout_sha256,
    )
    _validate_safe_report(safe_completeness, COMPLETENESS_REPORT_ARTIFACT_ID)
    _validate_safe_report(safe_holdout, HOLDOUT_REPORT_ARTIFACT_ID)

    staging = output_root.with_name(f".{output_root.name}.staging")
    if staging.exists():
        raise GitHubTransferError("immutable_staging_root_exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_created = False
    try:
        staging.mkdir(mode=0o700)
        staging_created = True
        paths_and_bytes = (
            (staging / PRIVATE_EXPORT_NAME, private_export_bytes, 0o400),
            (
                staging / SAFE_COMPLETENESS_NAME,
                _canonical_pretty_bytes(safe_completeness),
                0o444,
            ),
            (staging / PRIVATE_HOLDOUT_NAME, holdout_bytes, 0o400),
            (
                staging / SAFE_HOLDOUT_NAME,
                _canonical_pretty_bytes(safe_holdout),
                0o444,
            ),
        )
        for path, payload, mode in paths_and_bytes:
            with path.open("xb") as file_handle:
                file_handle.write(payload)
                file_handle.flush()
                os.fsync(file_handle.fileno())
            path.chmod(mode)
        os.replace(staging, output_root)
        output_root.chmod(0o500)
        _fsync_directory(output_root)
        _fsync_directory(output_root.parent)
    except Exception:
        if staging_created and staging.exists():
            shutil.rmtree(staging)
        raise

    artifacts = TransferArtifacts(
        output_root=output_root,
        private_export_path=output_root / PRIVATE_EXPORT_NAME,
        safe_completeness_path=output_root / SAFE_COMPLETENESS_NAME,
        private_holdout_path=output_root / PRIVATE_HOLDOUT_NAME,
        safe_holdout_path=output_root / SAFE_HOLDOUT_NAME,
        private_export_sha256=private_export_sha256,
        private_holdout_sha256=holdout_sha256,
        safe_completeness=safe_completeness,
        safe_holdout=safe_holdout,
    )
    _validate_persisted_artifacts(artifacts)
    return artifacts


def _read_all_comments(
    client: GitHubReadClient,
    issue_number: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    page_hashes: list[str] = []
    page = 1
    terminal_reason = ""
    while page <= 20:
        response = client.get_json(
            f"/repos/{REPOSITORY}/issues/{issue_number}/comments",
            {"per_page": "100", "page": str(page)},
        )
        if not isinstance(response.payload, list):
            raise GitHubTransferError("github_comment_page_invalid")
        normalized_page = [
            _normalize_comment_record(item, issue_number) for item in response.payload
        ]
        comments.extend(normalized_page)
        page_hashes.append(sha256_json(normalized_page))
        next_page = _next_page_number(response.headers.get("link"))
        if next_page is not None:
            if next_page != page + 1:
                raise GitHubTransferError("github_comment_pagination_discontinuous")
            page = next_page
            continue
        if len(normalized_page) < 100:
            terminal_reason = "terminal_short_page_without_next_link"
            break
        page += 1
    else:
        raise GitHubTransferError("github_comment_pagination_unbounded")
    if not terminal_reason:
        raise GitHubTransferError("github_comment_pagination_not_terminal")
    comment_ids = [comment["comment_id"] for comment in comments]
    if len(comment_ids) != len(set(comment_ids)):
        raise GitHubTransferError("github_comment_identity_duplicate")
    return comments, {
        "status": "complete",
        "page_count": len(page_hashes),
        "record_count": len(comments),
        "terminal_reason": terminal_reason,
        "page_fingerprints": page_hashes,
    }


def _normalize_issue_record(value: Any, expected_issue_number: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GitHubTransferError("github_issue_detail_invalid")
    if "pull_request" in value:
        raise GitHubTransferError("github_scope_contains_pull_request")
    required = {
        "id",
        "node_id",
        "number",
        "title",
        "body",
        "state",
        "comments",
        "created_at",
        "updated_at",
        "user",
    }
    if not required.issubset(value):
        raise GitHubTransferError("github_issue_detail_missing_field")
    if value["number"] != expected_issue_number:
        raise GitHubTransferError("github_issue_number_mismatch")
    user = value["user"]
    if not isinstance(user, Mapping) or not user.get("login"):
        raise GitHubTransferError("github_issue_author_missing")
    labels = value.get("labels", [])
    if not isinstance(labels, list):
        raise GitHubTransferError("github_issue_labels_invalid")
    normalized = {
        "issue_id": str(value["id"]),
        "issue_node_id": str(value["node_id"]),
        "issue_number": expected_issue_number,
        "title": _string(value["title"], "github_issue_title_invalid"),
        "body": _nullable_string(value["body"], "github_issue_body_invalid"),
        "state": _string(value["state"], "github_issue_state_invalid"),
        "state_reason": _nullable_string(
            value.get("state_reason"),
            "github_issue_state_reason_invalid",
        ),
        "locked": bool(value.get("locked", False)),
        "declared_comment_count": _nonnegative_int(
            value["comments"],
            "github_issue_comment_count_invalid",
        ),
        "created_at": _timestamp(value["created_at"], "github_issue_created_at_invalid"),
        "updated_at": _timestamp(value["updated_at"], "github_issue_updated_at_invalid"),
        "closed_at": _nullable_timestamp(
            value.get("closed_at"),
            "github_issue_closed_at_invalid",
        ),
        "author_login": str(user["login"]),
        "author_node_id": str(user.get("node_id") or user.get("id")),
        "author_association": str(value.get("author_association") or "NONE"),
        "label_names": sorted(
            str(label.get("name"))
            for label in labels
            if isinstance(label, Mapping) and label.get("name")
        ),
    }
    normalized["source_record_fingerprint"] = _payload_fingerprint(
        normalized,
        "source_record_fingerprint",
    )
    return normalized


def _normalize_comment_record(value: Any, issue_number: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GitHubTransferError("github_comment_record_invalid")
    required = {"id", "node_id", "body", "created_at", "updated_at", "user"}
    if not required.issubset(value):
        raise GitHubTransferError("github_comment_record_missing_field")
    user = value["user"]
    if not isinstance(user, Mapping) or not user.get("login"):
        raise GitHubTransferError("github_comment_author_missing")
    normalized = {
        "comment_id": str(value["id"]),
        "comment_node_id": str(value["node_id"]),
        "issue_number": issue_number,
        "body": _string(value["body"], "github_comment_body_invalid"),
        "created_at": _timestamp(
            value["created_at"],
            "github_comment_created_at_invalid",
        ),
        "updated_at": _timestamp(
            value["updated_at"],
            "github_comment_updated_at_invalid",
        ),
        "author_login": str(user["login"]),
        "author_node_id": str(user.get("node_id") or user.get("id")),
        "author_association": str(value.get("author_association") or "NONE"),
    }
    normalized["source_record_fingerprint"] = _payload_fingerprint(
        normalized,
        "source_record_fingerprint",
    )
    return normalized


def _build_private_export(capture: Mapping[str, Any]) -> dict[str, Any]:
    records = _source_records(capture)
    source_payload = {
        "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
        "records": records,
    }
    source_snapshot_fingerprint = sha256_json(source_payload)
    parser_fingerprint = sha256_json(
        {
            "adapter_id": CAPTURE_POLICY_ID,
            "adapter_version": "1",
            "api_version": API_VERSION,
            "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
        }
    )
    source_updated_at = max(record["updated_at"] for record in records)
    source_created_at = min(record["created_at"] for record in records)
    source_ref = SourceRef(
        source_system="github",
        source_type="project_issue_comment_snapshot",
        source_id=REPOSITORY,
        source_instance="github_public",
        source_key=CAPTURE_POLICY_FINGERPRINT,
    )
    storage_backend_id = stable_storage_backend_id(
        backend_type="external_source_snapshot",
        workspace_scope=WORKSPACE_ID,
        display_name="Issue56 GitHub transfer source",
    )
    object_uri = "formowl://object/github-transfer/" + source_snapshot_fingerprint.removeprefix(
        "sha256:"
    )
    asset_id = stable_asset_id(
        storage_backend_id=storage_backend_id,
        object_uri=object_uri,
        content_hash=source_snapshot_fingerprint,
        workspace_id=WORKSPACE_ID,
        source_ref=source_ref,
    )
    asset = Asset(
        asset_id=asset_id,
        storage_backend_id=storage_backend_id,
        object_uri=object_uri,
        content_hash=source_snapshot_fingerprint,
        file_size=len(_canonical_bytes(source_payload)),
        mime_type="application/vnd.github+json",
        created_at=source_created_at,
        registered_at=source_updated_at,
        owner_user_id=OWNER_USER_ID,
        workspace_id=WORKSPACE_ID,
        permission_scope=SHARED_PERMISSION_SCOPE,
        lifecycle_state="active",
        source_ref=source_ref,
        project_id=PROJECT_ID,
    )
    asset = Asset.from_dict(asset.to_dict())
    extractor_run_id = stable_extractor_run_id(
        asset_id=asset.asset_id,
        extractor_name="github_issue_comment_source_capture",
        extractor_version="1",
        extractor_type="project_issue_comment",
        input_hash=source_snapshot_fingerprint,
        config_hash=parser_fingerprint,
    )
    extractor_run = ExtractorRun(
        extractor_run_id=extractor_run_id,
        asset_id=asset.asset_id,
        extractor_name="github_issue_comment_source_capture",
        extractor_version="1",
        extractor_type="project_issue_comment",
        input_hash=source_snapshot_fingerprint,
        config_hash=parser_fingerprint,
        status="succeeded",
        started_at=source_created_at,
        completed_at=source_updated_at,
        warnings=[],
        errors=[],
    )
    extractor_run = ExtractorRun.from_dict(extractor_run.to_dict())

    inventory_items: list[SourceInventoryItem] = []
    observations: list[Observation] = []
    record_bindings: list[dict[str, Any]] = []
    issue_local_keys: dict[int, str] = {}
    for ordinal, record in enumerate(records):
        record_kind = str(record["record_kind"])
        issue_number = int(record["issue_number"])
        source_local_key = _source_local_key(record)
        if record_kind == "issue_record":
            issue_local_keys[issue_number] = source_local_key
        parent_source_local_key = (
            None if record_kind == "issue_record" else issue_local_keys.get(issue_number)
        )
        if record_kind == "top_level_issue_comment" and not parent_source_local_key:
            raise GitHubTransferError("github_comment_parent_lineage_missing")
        location: dict[str, Any] = {
            "source_local_key": source_local_key,
            "source_record_fingerprint": record["source_record_fingerprint"],
            "record_kind": record_kind,
        }
        if record_kind == "top_level_issue_comment":
            location["parent_source_local_key"] = parent_source_local_key
        item = SourceInventoryItem.create(
            source_asset_id=asset.asset_id,
            structure_kind=record_kind,
            content_type="application/vnd.github+json",
            ordinal=ordinal,
            processing_state="parsed",
            raw_retention_state="externally_managed",
            source_fingerprint=source_snapshot_fingerprint,
            parser_fingerprint=parser_fingerprint,
            permission_scope=SHARED_PERMISSION_SCOPE,
            location=location,
        )
        inventory_items.append(item)
        text = _record_text(record)
        payload = _observation_payload(
            record,
            source_local_key=source_local_key,
            parent_source_local_key=parent_source_local_key,
        )
        observation_id = stable_observation_id(
            asset_id=asset.asset_id,
            extractor_run_id=extractor_run.extractor_run_id,
            observation_type=record_kind,
            modality="project",
            location=location,
            text=text,
            payload=payload,
        )
        observation = Observation(
            observation_id=observation_id,
            asset_id=asset.asset_id,
            extractor_run_id=extractor_run.extractor_run_id,
            observation_type=record_kind,
            modality="project",
            location=location,
            confidence=1.0,
            permission_scope=SHARED_PERMISSION_SCOPE,
            created_at=str(record["updated_at"]),
            text=text,
            payload=payload,
        )
        observation = Observation.from_dict(observation.to_dict())
        observations.append(observation)
        binding: dict[str, Any] = {
            "source_local_key": source_local_key,
            "source_record_fingerprint": record["source_record_fingerprint"],
            "source_inventory_item_id": item.source_inventory_item_id,
            "observation_id": observation.observation_id,
            "record_kind": record_kind,
        }
        if parent_source_local_key is not None:
            binding["parent_source_local_key"] = parent_source_local_key
        binding["source_occurrence_fingerprint"] = sha256_json(
            {
                "source_kind": SOURCE_KIND,
                "occurrence_schema_id": SOURCE_OCCURRENCE_SCHEMA_ID,
                **binding,
            }
        )
        record_bindings.append(binding)
    inventory = SourceInventory.create(
        source_asset_id=asset.asset_id,
        items=inventory_items,
        source_fingerprint=source_snapshot_fingerprint,
        parser_fingerprint=parser_fingerprint,
        created_at=source_updated_at,
    )
    issue_count = sum(record["record_kind"] == "issue_record" for record in records)
    comment_count = len(records) - issue_count
    export: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": "source_observations_not_canonical_fact",
        "source_scope": {
            "capture_policy": _CAPTURE_POLICY,
            "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
            "capture_fingerprint": capture["capture_fingerprint"],
            "source_updated_at": source_updated_at,
        },
        "source_records": records,
        "source_kind": SOURCE_KIND,
        "source_occurrence_schema": _SOURCE_OCCURRENCE_SCHEMA,
        "source_occurrence_schema_fingerprint": (SOURCE_OCCURRENCE_SCHEMA_FINGERPRINT),
        "asset": asset.to_dict(),
        "extractor_run": extractor_run.to_dict(),
        "source_inventory": inventory.to_dict(),
        "observations": [observation.to_dict() for observation in observations],
        "record_bindings": record_bindings,
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "parser_fingerprint": parser_fingerprint,
        "permission_fingerprint": sha256_json(SHARED_PERMISSION_SCOPE),
        "counts": {
            "issue_record_count": issue_count,
            "comment_record_count": comment_count,
            "source_record_count": len(records),
            "source_inventory_item_count": len(inventory.items),
            "observation_count": len(observations),
            "unexplained_loss_count": 0,
            "missing_inventory_binding_count": 0,
            "missing_observation_binding_count": 0,
            "excluded_resource_kind_count": len(_CAPTURE_POLICY["excluded_resource_kinds"]),
        },
        "lineage_fingerprint": sha256_json(record_bindings),
        "blocker_ids": [],
    }
    export["export_fingerprint"] = _payload_fingerprint(export, "export_fingerprint")
    return export


def _build_transfer_holdout(
    *,
    private_export: Mapping[str, Any],
    private_export_sha256: str,
) -> dict[str, Any]:
    observations = {
        str(observation["observation_id"]): observation
        for observation in private_export["observations"]
    }
    bindings = {
        str(binding["source_local_key"]): binding for binding in private_export["record_bindings"]
    }
    records = list(private_export["source_records"])
    issue_records = [record for record in records if record["record_kind"] == "issue_record"]
    issue_records.sort(key=lambda record: int(record["issue_number"]))
    issue_observations = {
        int(record["issue_number"]): observations[
            bindings[_source_local_key(record)]["observation_id"]
        ]
        for record in issue_records
    }
    observation_by_source_local_key = {
        str(observation["location"]["source_local_key"]): observation
        for observation in observations.values()
    }
    cases: list[dict[str, Any]] = []

    direct_records = sorted(
        issue_records,
        key=lambda record: (
            record["source_record_fingerprint"],
            record["issue_number"],
        ),
    )[:2]
    direct_fields = ("state", "title")
    for record, field_name in zip(direct_records, direct_fields, strict=True):
        issue_number = int(record["issue_number"])
        observation = issue_observations[issue_number]
        query = (
            f"What is the source-native {field_name} of GitHub issue "
            f"#{issue_number} in the frozen transfer scope?"
        )
        cases.append(
            _case(
                stratum="direct",
                private_query=query,
                expected_private={
                    "claim_state": "FOUND",
                    "value": record[field_name],
                },
                required_observations=[observation],
            )
        )

    relation_edges = _relation_edges(
        records,
        observation_by_source_local_key=observation_by_source_local_key,
    )
    if len(relation_edges) < _STRATA_COUNTS["cross_issue_relation"]:
        raise GitHubTransferError("github_cross_issue_relation_coverage_missing")
    for edge in relation_edges[: _STRATA_COUNTS["cross_issue_relation"]]:
        source_number, target_number, evidence_observation = edge
        cases.append(
            _case(
                stratum="cross_issue_relation",
                private_query=(
                    "What source-native reference connects GitHub issue "
                    f"#{source_number} to issue #{target_number} in the frozen scope?"
                ),
                expected_private={
                    "claim_state": "FOUND",
                    "relation_kind": "source_native_issue_reference",
                    "source_issue_number": source_number,
                    "target_issue_number": target_number,
                },
                required_observations=[
                    evidence_observation,
                    issue_observations[target_number],
                ],
            )
        )

    closed_records = [record for record in issue_records if record["state"] == "closed"]
    if not closed_records:
        raise GitHubTransferError("github_temporal_closed_record_missing")
    latest_closed = max(
        closed_records,
        key=lambda record: (record["closed_at"] or "", record["source_record_fingerprint"]),
    )
    open_records = [record for record in issue_records if record["state"] == "open"]
    if not open_records:
        raise GitHubTransferError("github_temporal_open_record_missing")
    latest_open_update = max(
        open_records,
        key=lambda record: (record["updated_at"], record["source_record_fingerprint"]),
    )
    cases.append(
        _case(
            stratum="temporal_status",
            private_query=(
                "Which issue in the frozen transfer scope closed most recently, "
                "and what source timestamp records that transition?"
            ),
            expected_private={
                "claim_state": "FOUND",
                "issue_number": latest_closed["issue_number"],
                "state": "closed",
                "closed_at": latest_closed["closed_at"],
            },
            required_observations=[issue_observations[int(latest_closed["issue_number"])]],
        )
    )
    cases.append(
        _case(
            stratum="temporal_status",
            private_query=(
                "Which open issue in the frozen transfer scope has the latest "
                "source-native update timestamp?"
            ),
            expected_private={
                "claim_state": "FOUND",
                "issue_number": latest_open_update["issue_number"],
                "state": "open",
                "updated_at": latest_open_update["updated_at"],
            },
            required_observations=[issue_observations[int(latest_open_update["issue_number"])]],
        )
    )

    all_observations = list(observations.values())
    cases.append(
        _case(
            stratum="exact_count_inventory",
            private_query=(
                "How many issue records are in the complete frozen GitHub " "transfer scope?"
            ),
            expected_private={
                "claim_state": "FOUND",
                "count": len(issue_records),
                "complete_set": [record["issue_number"] for record in issue_records],
            },
            required_observations=[
                issue_observations[int(record["issue_number"])] for record in issue_records
            ],
        )
    )
    comment_observations = [
        observation
        for observation in all_observations
        if observation["observation_type"] == "top_level_issue_comment"
    ]
    cases.append(
        _case(
            stratum="exact_count_inventory",
            private_query=(
                "How many top-level issue comments are in the complete frozen "
                "GitHub transfer scope?"
            ),
            expected_private={
                "claim_state": "FOUND",
                "count": len(comment_observations),
            },
            required_observations=comment_observations,
        )
    )

    absent_issue_number = max(int(record["issue_number"]) for record in issue_records) + 1
    cases.append(
        _case(
            stratum="no_answer",
            private_query=(
                f"Find GitHub issue #{absent_issue_number} within the frozen " "transfer scope."
            ),
            expected_private={
                "claim_state": "NOT_FOUND_WITHIN_COMPLETE_SCOPE",
                "complete_scope_fingerprint": private_export["source_snapshot_fingerprint"],
            },
            required_observations=[
                issue_observations[int(record["issue_number"])] for record in issue_records
            ],
        )
    )

    restricted_source = issue_observations[int(direct_records[0]["issue_number"])]
    permission_fixture = {
        "fixture_id": stable_resource_contract_id(
            "scopefixture",
            "Issue56GitHubTransferPermissionFixture",
            {
                "source_record_fingerprint": restricted_source["payload"][
                    "source_record_fingerprint"
                ],
                "shared_permission_scope": SHARED_PERMISSION_SCOPE,
                "restricted_permission_scope": RESTRICTED_PERMISSION_SCOPE,
            },
        ),
        "source_record_fingerprint": restricted_source["payload"]["source_record_fingerprint"],
        "shared_permission_scope": SHARED_PERMISSION_SCOPE,
        "restricted_permission_scope": RESTRICTED_PERMISSION_SCOPE,
        "shared_permission_fingerprint": sha256_json(SHARED_PERMISSION_SCOPE),
        "restricted_permission_fingerprint": sha256_json(RESTRICTED_PERMISSION_SCOPE),
        "source_content_reused_without_modification": True,
    }
    cases.append(
        _case(
            stratum="permission_denied",
            private_query=(
                "Return the selected issue evidence through the restricted "
                "transfer-scope fixture."
            ),
            expected_private={
                "outer_status": "permission_denied",
                "claim_state": None,
                "requester_id": DENIED_REQUESTER_ID,
                "permission_fixture_id": permission_fixture["fixture_id"],
            },
            required_observations=[restricted_source],
            permission_fixture_id=str(permission_fixture["fixture_id"]),
        )
    )
    strata = Counter(str(case["stratum"]) for case in cases)
    if dict(sorted(strata.items())) != dict(sorted(_STRATA_COUNTS.items())):
        raise GitHubTransferError("github_transfer_strata_coverage_mismatch")
    manifest: dict[str, Any] = {
        "artifact_id": HOLDOUT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "classification": DIAGNOSTIC_CLASSIFICATION,
        "claim_boundary_status": DIAGNOSTIC_CLAIM_BOUNDARY,
        "diagnostic_only": True,
        "final_acceptance_eligible": False,
        "status": "sealed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "runtime_freeze_status": "pending_master_confirmation",
        "seal_required_before_execution": True,
        "source_family": "github_project_issue_comment",
        "mail_source_consumed": False,
        "source_export_binding": {
            "private_export_sha256": private_export_sha256,
            "private_export_fingerprint": private_export["export_fingerprint"],
            "source_snapshot_fingerprint": private_export["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": sha256_json(private_export["source_inventory"]),
            "observation_snapshot_fingerprint": sha256_json(private_export["observations"]),
            "permission_fingerprint": private_export["permission_fingerprint"],
            "lineage_fingerprint": private_export["lineage_fingerprint"],
            "source_occurrence_schema_fingerprint": private_export[
                "source_occurrence_schema_fingerprint"
            ],
        },
        "holdout_policy": _HOLDOUT_POLICY,
        "holdout_policy_fingerprint": HOLDOUT_POLICY_FINGERPRINT,
        "routing_profile": _ROUTING_PROFILE,
        "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
        "routing_binding_set_fingerprint": sha256_json(
            sorted(str(case["routing_contract"]["routing_contract_fingerprint"]) for case in cases)
        ),
        "permission_fixture": permission_fixture,
        "case_count": len(cases),
        "strata_counts": dict(sorted(strata.items())),
        "query_class_counts": dict(
            sorted(Counter(str(case["query_class"]) for case in cases).items())
        ),
        "cases": cases,
        "blocker_ids": [],
    }
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    return manifest


def _source_authored_query_class(stratum: str) -> str:
    routing_intent = _ROUTING_INTENT_BY_STRATUM.get(stratum)
    if routing_intent is None:
        raise GitHubTransferError("github_holdout_typed_stratum_unsupported")
    return _QUERY_CLASS_BY_ROUTING_INTENT[routing_intent]


def _build_routing_contract(
    *,
    stratum: str,
    query_class: str,
    private_query: str,
) -> dict[str, Any]:
    if query_class != _source_authored_query_class(stratum):
        raise GitHubTransferError("github_holdout_authored_query_class_drift")
    authored_intent_kind = _ROUTING_INTENT_BY_STRATUM[stratum]
    contract: dict[str, Any] = {
        "schema_id": ROUTING_CONTRACT_SCHEMA_ID,
        "routing_profile_id": ROUTING_PROFILE_ID,
        "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
        "typed_stratum": stratum,
        "authored_intent_kind": authored_intent_kind,
        "authored_query_class": query_class,
        "private_query_hash": sha256_json(private_query),
        "query_text_inference_authoritative": False,
    }
    contract["routing_contract_fingerprint"] = _payload_fingerprint(
        contract,
        "routing_contract_fingerprint",
    )
    return contract


def _case(
    *,
    stratum: str,
    private_query: str,
    expected_private: Mapping[str, Any],
    required_observations: Sequence[Mapping[str, Any]],
    permission_fixture_id: str | None = None,
) -> dict[str, Any]:
    query_class = _source_authored_query_class(stratum)
    routing_contract = _build_routing_contract(
        stratum=stratum,
        query_class=query_class,
        private_query=private_query,
    )
    observation_ids = sorted(
        {str(observation["observation_id"]) for observation in required_observations}
    )
    source_record_fingerprints = sorted(
        {
            str(observation["payload"]["source_record_fingerprint"])
            for observation in required_observations
        }
    )
    payload: dict[str, Any] = {
        "stratum": stratum,
        "query_class": query_class,
        "private_query": private_query,
        "expected_private": dict(expected_private),
        "required_source_observation_ids": observation_ids,
        "required_source_record_fingerprints": source_record_fingerprints,
        "execution_status": "not_run",
        "question_specific_aliases": False,
        "routing_contract": routing_contract,
    }
    if permission_fixture_id is not None:
        payload["permission_fixture_id"] = permission_fixture_id
    payload["case_id"] = stable_resource_contract_id(
        "transfercase",
        "Issue56GitHubTransferHoldoutCase",
        payload,
    )
    payload["case_fingerprint"] = _payload_fingerprint(
        payload,
        "case_fingerprint",
    )
    return payload


def _relation_edges(
    records: Sequence[Mapping[str, Any]],
    *,
    observation_by_source_local_key: Mapping[str, Mapping[str, Any]],
) -> list[tuple[int, int, Mapping[str, Any]]]:
    edges: dict[
        tuple[int, int, str],
        tuple[int, int, Mapping[str, Any]],
    ] = {}
    scope = set(ISSUE_NUMBERS)
    for record in records:
        source_number = int(record["issue_number"])
        text = _record_text(record)
        for target_number in sorted(
            {int(match) for match in _ISSUE_REFERENCE_RE.findall(text)} & scope
        ):
            if source_number == target_number:
                continue
            evidence = observation_by_source_local_key.get(_source_local_key(record))
            if evidence is None:
                raise GitHubTransferError("github_reference_observation_lineage_missing")
            key = (
                source_number,
                target_number,
                str(evidence["payload"]["source_record_fingerprint"]),
            )
            edges[key] = (source_number, target_number, evidence)
    return [
        edges[key]
        for key in sorted(
            edges,
            key=lambda value: sha256_json(
                {"source": value[0], "target": value[1], "evidence": value[2]}
            ),
        )
    ]


def _source_records(capture: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for issue in capture["issue_records"]:
        issue_record = dict(issue)
        issue_record["record_kind"] = "issue_record"
        records.append(issue_record)
        for comment in capture["comments_by_issue"][str(issue["issue_number"])]:
            comment_record = dict(comment)
            comment_record["record_kind"] = "top_level_issue_comment"
            records.append(comment_record)
    return records


def _source_local_key(record: Mapping[str, Any]) -> str:
    return stable_resource_contract_id(
        "srclocal",
        "Issue56GitHubTransferSourceLocalKey",
        {
            "record_kind": record["record_kind"],
            "issue_number": record["issue_number"],
            "source_record_fingerprint": record["source_record_fingerprint"],
        },
    )


def _record_text(record: Mapping[str, Any]) -> str:
    if record["record_kind"] == "issue_record":
        body = str(record.get("body") or "")
        return f"{record['title']}\n\n{body}".strip()
    return str(record["body"])


def _observation_payload(
    record: Mapping[str, Any],
    *,
    source_local_key: str,
    parent_source_local_key: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_record_fingerprint": record["source_record_fingerprint"],
        "source_local_key": source_local_key,
        "record_kind": record["record_kind"],
        "issue_number": record["issue_number"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "source_native_issue_references": sorted(
            {
                int(match)
                for match in _ISSUE_REFERENCE_RE.findall(_record_text(record))
                if int(match) in ISSUE_NUMBERS and int(match) != int(record["issue_number"])
            }
        ),
    }
    if parent_source_local_key is not None:
        payload["parent_source_local_key"] = parent_source_local_key
    if record["record_kind"] == "issue_record":
        payload.update(
            {
                "state": record["state"],
                "state_reason": record["state_reason"],
                "closed_at": record["closed_at"],
                "declared_comment_count": record["declared_comment_count"],
                "label_names": list(record["label_names"]),
            }
        )
    return payload


def _validate_capture(capture: Mapping[str, Any]) -> None:
    if capture.get("artifact_id") != "formowl_issue56_github_read_capture_v1":
        raise GitHubTransferError("github_capture_artifact_invalid")
    if capture.get("capture_policy") != _CAPTURE_POLICY:
        raise GitHubTransferError("github_capture_policy_drift")
    if capture.get("capture_policy_fingerprint") != CAPTURE_POLICY_FINGERPRINT:
        raise GitHubTransferError("github_capture_policy_fingerprint_drift")
    if capture.get("capture_fingerprint") != _payload_fingerprint(
        capture,
        "capture_fingerprint",
    ):
        raise GitHubTransferError("github_capture_fingerprint_drift")
    issue_records = capture.get("issue_records")
    comments_by_issue = capture.get("comments_by_issue")
    pagination = capture.get("comment_pagination")
    if not isinstance(issue_records, list) or not isinstance(comments_by_issue, Mapping):
        raise GitHubTransferError("github_capture_records_invalid")
    if not isinstance(pagination, Mapping):
        raise GitHubTransferError("github_capture_pagination_invalid")
    if [record.get("issue_number") for record in issue_records] != list(ISSUE_NUMBERS):
        raise GitHubTransferError("github_capture_issue_inventory_drift")
    _validate_comment_identity(issue_records, comments_by_issue)
    for issue in issue_records:
        issue_number = str(issue["issue_number"])
        evidence = pagination.get(issue_number)
        if not isinstance(evidence, Mapping) or evidence.get("status") != "complete":
            raise GitHubTransferError("github_comment_pagination_incomplete")
        comments = comments_by_issue.get(issue_number)
        if not isinstance(comments, list):
            raise GitHubTransferError("github_comment_collection_missing")
        if evidence.get("record_count") != len(comments):
            raise GitHubTransferError("github_comment_page_count_drift")
        if issue["declared_comment_count"] != len(comments):
            raise GitHubTransferError("github_comment_count_mismatch")


def _validate_private_export(export: Mapping[str, Any]) -> None:
    if export.get("artifact_id") != ARTIFACT_ID or export.get("status") != "passed":
        raise GitHubTransferError("github_private_export_status_invalid")
    if export.get("export_fingerprint") != _payload_fingerprint(
        export,
        "export_fingerprint",
    ):
        raise GitHubTransferError("github_private_export_fingerprint_drift")
    if export.get("claim_boundary_status") != "source_observations_not_canonical_fact":
        raise GitHubTransferError("github_observation_claim_boundary_invalid")
    if export.get("blocker_ids") != []:
        raise GitHubTransferError("github_private_export_blocked")
    if (
        export.get("source_kind") != SOURCE_KIND
        or export.get("source_occurrence_schema") != _SOURCE_OCCURRENCE_SCHEMA
        or export.get("source_occurrence_schema_fingerprint")
        != SOURCE_OCCURRENCE_SCHEMA_FINGERPRINT
    ):
        raise GitHubTransferError("github_source_occurrence_schema_drift")
    asset = Asset.from_dict(dict(export["asset"]))
    run = ExtractorRun.from_dict(dict(export["extractor_run"]))
    inventory = SourceInventory.from_dict(export["source_inventory"])
    observations = [
        Observation.from_dict(dict(observation)) for observation in export["observations"]
    ]
    if run.asset_id != asset.asset_id or inventory.source_asset_id != asset.asset_id:
        raise GitHubTransferError("github_owner_asset_binding_mismatch")
    if asset.content_hash != export["source_snapshot_fingerprint"]:
        raise GitHubTransferError("github_asset_source_fingerprint_mismatch")
    if inventory.source_fingerprint != export["source_snapshot_fingerprint"]:
        raise GitHubTransferError("github_inventory_source_fingerprint_mismatch")
    if inventory.parser_fingerprint != export["parser_fingerprint"]:
        raise GitHubTransferError("github_inventory_parser_fingerprint_mismatch")
    if any(observation.asset_id != asset.asset_id for observation in observations):
        raise GitHubTransferError("github_observation_asset_binding_mismatch")
    if any(observation.extractor_run_id != run.extractor_run_id for observation in observations):
        raise GitHubTransferError("github_observation_run_binding_mismatch")
    inventory_keys = {str(item.location["source_local_key"]) for item in inventory.items}
    observation_keys = {
        str(observation.location["source_local_key"]) for observation in observations
    }
    record_keys = {_source_local_key(record) for record in export["source_records"]}
    if inventory_keys != observation_keys or observation_keys != record_keys:
        raise GitHubTransferError("github_record_lineage_reconciliation_failed")
    issue_key_by_number = {
        int(record["issue_number"]): _source_local_key(record)
        for record in export["source_records"]
        if record["record_kind"] == "issue_record"
    }
    observation_by_key = {
        str(observation.location["source_local_key"]): observation for observation in observations
    }
    binding_by_key = {
        str(binding["source_local_key"]): binding for binding in export["record_bindings"]
    }
    for record in export["source_records"]:
        source_local_key = _source_local_key(record)
        observation = observation_by_key.get(source_local_key)
        binding = binding_by_key.get(source_local_key)
        if observation is None or not isinstance(binding, Mapping):
            raise GitHubTransferError("github_typed_occurrence_lineage_missing")
        location = observation.location
        payload = observation.payload or {}
        record_kind = str(record["record_kind"])
        if (
            location.get("record_kind") != record_kind
            or payload.get("record_kind") != record_kind
            or payload.get("source_local_key") != source_local_key
            or binding.get("record_kind") != record_kind
        ):
            raise GitHubTransferError("github_typed_occurrence_lineage_mismatch")
        if record_kind == "issue_record":
            if (
                "parent_source_local_key" in location
                or "parent_source_local_key" in payload
                or "parent_source_local_key" in binding
            ):
                raise GitHubTransferError("github_issue_occurrence_parent_invalid")
        else:
            expected_parent = issue_key_by_number.get(int(record["issue_number"]))
            if (
                not expected_parent
                or location.get("parent_source_local_key") != expected_parent
                or payload.get("parent_source_local_key") != expected_parent
                or binding.get("parent_source_local_key") != expected_parent
            ):
                raise GitHubTransferError("github_comment_parent_lineage_mismatch")
        expected_occurrence_fingerprint = sha256_json(
            {
                "source_kind": SOURCE_KIND,
                "occurrence_schema_id": SOURCE_OCCURRENCE_SCHEMA_ID,
                **{
                    key: value
                    for key, value in binding.items()
                    if key != "source_occurrence_fingerprint"
                },
            }
        )
        if binding.get("source_occurrence_fingerprint") != expected_occurrence_fingerprint:
            raise GitHubTransferError("github_source_occurrence_fingerprint_drift")
    counts = export["counts"]
    if (
        counts["source_record_count"] != len(export["source_records"])
        or counts["source_inventory_item_count"] != len(inventory.items)
        or counts["observation_count"] != len(observations)
        or counts["unexplained_loss_count"] != 0
        or counts["missing_inventory_binding_count"] != 0
        or counts["missing_observation_binding_count"] != 0
    ):
        raise GitHubTransferError("github_source_completeness_count_drift")
    if export["lineage_fingerprint"] != sha256_json(export["record_bindings"]):
        raise GitHubTransferError("github_lineage_fingerprint_drift")


def _validate_transfer_holdout(
    manifest: Mapping[str, Any],
    *,
    private_export: Mapping[str, Any],
) -> None:
    if manifest.get("artifact_id") != HOLDOUT_ARTIFACT_ID:
        raise GitHubTransferError("github_holdout_artifact_invalid")
    if (
        manifest.get("classification") != DIAGNOSTIC_CLASSIFICATION
        or manifest.get("claim_boundary_status") != DIAGNOSTIC_CLAIM_BOUNDARY
        or manifest.get("diagnostic_only") is not True
        or manifest.get("final_acceptance_eligible") is not False
        or manifest.get("execution_status") != "not_run"
        or manifest.get("quality_result_status") != "not_read"
        or manifest.get("runtime_freeze_status") != "pending_master_confirmation"
    ):
        raise GitHubTransferError("github_holdout_execution_boundary_invalid")
    if manifest.get("manifest_fingerprint") != _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    ):
        raise GitHubTransferError("github_holdout_manifest_fingerprint_drift")
    if manifest.get("holdout_policy") != _HOLDOUT_POLICY:
        raise GitHubTransferError("github_holdout_policy_drift")
    if manifest.get("holdout_policy_fingerprint") != HOLDOUT_POLICY_FINGERPRINT:
        raise GitHubTransferError("github_holdout_policy_fingerprint_drift")
    if (
        manifest.get("routing_profile") != _ROUTING_PROFILE
        or manifest.get("routing_profile_fingerprint") != ROUTING_PROFILE_FINGERPRINT
    ):
        raise GitHubTransferError("github_holdout_routing_profile_drift")
    expected_source_binding = {
        "private_export_sha256": _sha256_bytes(_canonical_pretty_bytes(private_export)),
        "private_export_fingerprint": private_export["export_fingerprint"],
        "source_snapshot_fingerprint": private_export["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(private_export["source_inventory"]),
        "observation_snapshot_fingerprint": sha256_json(private_export["observations"]),
        "permission_fingerprint": private_export["permission_fingerprint"],
        "lineage_fingerprint": private_export["lineage_fingerprint"],
        "source_occurrence_schema_fingerprint": private_export[
            "source_occurrence_schema_fingerprint"
        ],
    }
    source_binding = manifest.get("source_export_binding")
    if (
        not isinstance(source_binding, Mapping)
        or dict(source_binding) != expected_source_binding
        or not _is_sha256(source_binding.get("private_export_sha256"))
    ):
        raise GitHubTransferError("github_holdout_source_binding_drift")
    if manifest.get("strata_counts") != dict(sorted(_STRATA_COUNTS.items())):
        raise GitHubTransferError("github_holdout_strata_drift")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != sum(_STRATA_COUNTS.values()):
        raise GitHubTransferError("github_holdout_case_count_drift")
    observation_ids = {
        str(observation["observation_id"]) for observation in private_export["observations"]
    }
    case_ids: set[str] = set()
    routing_fingerprints: list[str] = []
    query_class_counts: Counter[str] = Counter()
    for case in cases:
        if case.get("case_fingerprint") != _payload_fingerprint(
            case,
            "case_fingerprint",
        ):
            raise GitHubTransferError("github_holdout_case_fingerprint_drift")
        if case.get("execution_status") != "not_run":
            raise GitHubTransferError("github_holdout_case_executed")
        stratum = str(case.get("stratum") or "")
        query_class = str(case.get("query_class") or "")
        private_query = case.get("private_query")
        routing_contract = case.get("routing_contract")
        if (
            not isinstance(private_query, str)
            or not isinstance(routing_contract, Mapping)
            or query_class != _source_authored_query_class(stratum)
            or routing_contract
            != _build_routing_contract(
                stratum=stratum,
                query_class=query_class,
                private_query=private_query,
            )
        ):
            raise GitHubTransferError("github_holdout_authored_query_class_drift")
        routing_fingerprints.append(str(routing_contract["routing_contract_fingerprint"]))
        query_class_counts[query_class] += 1
        if not set(case["required_source_observation_ids"]).issubset(observation_ids):
            raise GitHubTransferError("github_holdout_case_lineage_missing")
        case_id = str(case["case_id"])
        if case_id in case_ids:
            raise GitHubTransferError("github_holdout_case_identity_duplicate")
        case_ids.add(case_id)
    if manifest.get("routing_binding_set_fingerprint") != sha256_json(
        sorted(routing_fingerprints)
    ) or manifest.get("query_class_counts") != dict(sorted(query_class_counts.items())):
        raise GitHubTransferError("github_holdout_routing_binding_drift")
    fixture = manifest.get("permission_fixture")
    if not isinstance(fixture, Mapping):
        raise GitHubTransferError("github_permission_fixture_missing")
    if fixture.get("source_content_reused_without_modification") is not True:
        raise GitHubTransferError("github_permission_fixture_content_invalid")
    if fixture.get("shared_permission_fingerprint") != sha256_json(SHARED_PERMISSION_SCOPE):
        raise GitHubTransferError("github_shared_permission_fixture_drift")
    if fixture.get("restricted_permission_fingerprint") != sha256_json(RESTRICTED_PERMISSION_SCOPE):
        raise GitHubTransferError("github_restricted_permission_fixture_drift")


def _build_safe_completeness(
    *,
    private_export: Mapping[str, Any],
    private_export_sha256: str,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "artifact_id": COMPLETENESS_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "scope_status": "passed",
        "pagination_status": "passed",
        "detail_status": "passed",
        "comment_reconciliation_status": "passed",
        "owner_boundary_status": "passed",
        "source_completeness_status": "passed",
        "event_scope_status": "excluded",
        "attachment_scope_status": "excluded",
        "canonical_fact_status": "not_asserted",
        "counts": dict(private_export["counts"]),
        "hashes": {
            "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
            "source_snapshot_fingerprint": private_export["source_snapshot_fingerprint"],
            "parser_fingerprint": private_export["parser_fingerprint"],
            "permission_fingerprint": private_export["permission_fingerprint"],
            "source_inventory_fingerprint": sha256_json(private_export["source_inventory"]),
            "observation_snapshot_fingerprint": sha256_json(private_export["observations"]),
            "lineage_fingerprint": private_export["lineage_fingerprint"],
            "source_occurrence_schema_fingerprint": private_export[
                "source_occurrence_schema_fingerprint"
            ],
            "private_export_sha256": private_export_sha256,
            "private_export_fingerprint": private_export["export_fingerprint"],
        },
        "blocker_count": 0,
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    return report


def _build_safe_holdout(
    *,
    private_export: Mapping[str, Any],
    private_export_sha256: str,
    holdout: Mapping[str, Any],
    holdout_sha256: str,
) -> dict[str, Any]:
    manifest_projection = _build_oracle_free_holdout_projection(holdout)
    report: dict[str, Any] = {
        "artifact_id": HOLDOUT_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "classification": DIAGNOSTIC_CLASSIFICATION,
        "claim_boundary_status": DIAGNOSTIC_CLAIM_BOUNDARY,
        "diagnostic_only": True,
        "final_acceptance_eligible": False,
        "source_lineage_status": "passed",
        "strata_coverage_status": "passed",
        "seal_before_execution_status": "passed",
        "permission_fixture_status": "passed",
        "routing_contract_status": "passed",
        "oracle_free_projection_status": "passed",
        "execution_status": "not_run",
        "quality_result_status": "not_read",
        "runtime_freeze_status": "pending_master_confirmation",
        "counts": {
            "case_count": holdout["case_count"],
            "source_record_count": private_export["counts"]["source_record_count"],
            "source_observation_count": private_export["counts"]["observation_count"],
            "blocker_count": 0,
        },
        "strata_counts": dict(holdout["strata_counts"]),
        "query_class_counts": dict(holdout["query_class_counts"]),
        "manifest_projection": manifest_projection,
        "hashes": {
            "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
            "holdout_policy_fingerprint": HOLDOUT_POLICY_FINGERPRINT,
            "source_snapshot_fingerprint": private_export["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": sha256_json(private_export["source_inventory"]),
            "observation_snapshot_fingerprint": sha256_json(private_export["observations"]),
            "source_occurrence_schema_fingerprint": private_export[
                "source_occurrence_schema_fingerprint"
            ],
            "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
            "routing_binding_set_fingerprint": holdout["routing_binding_set_fingerprint"],
            "manifest_projection_fingerprint": manifest_projection["projection_fingerprint"],
            "private_export_sha256": private_export_sha256,
            "private_export_fingerprint": private_export["export_fingerprint"],
            "private_holdout_sha256": holdout_sha256,
            "private_holdout_fingerprint": holdout["manifest_fingerprint"],
        },
        "blocker_count": 0,
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    return report


def _build_oracle_free_holdout_projection(
    holdout: Mapping[str, Any],
) -> dict[str, Any]:
    cases = holdout.get("cases")
    if not isinstance(cases, list):
        raise GitHubTransferError("github_holdout_projection_case_shape_invalid")
    case_routes = sorted(
        (
            {
                "case_entry_hash": sha256_json(str(case["case_id"])),
                "stratum": str(case["stratum"]),
                "query_class": str(case["query_class"]),
                "routing_contract_fingerprint": str(
                    case["routing_contract"]["routing_contract_fingerprint"]
                ),
            }
            for case in cases
        ),
        key=lambda item: item["case_entry_hash"],
    )
    projection: dict[str, Any] = {
        "schema_id": ORACLE_FREE_PROJECTION_SCHEMA_ID,
        "classification": DIAGNOSTIC_CLASSIFICATION,
        "claim_boundary_status": DIAGNOSTIC_CLAIM_BOUNDARY,
        "diagnostic_only": True,
        "final_acceptance_eligible": False,
        "routing_profile_id": ROUTING_PROFILE_ID,
        "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
        "case_count": int(holdout["case_count"]),
        "strata_counts": dict(holdout["strata_counts"]),
        "query_class_counts": dict(holdout["query_class_counts"]),
        "case_routes": case_routes,
    }
    projection["projection_fingerprint"] = _payload_fingerprint(
        projection,
        "projection_fingerprint",
    )
    _assert_oracle_free_projection(projection)
    return projection


def _validate_safe_report(report: Mapping[str, Any], artifact_id: str) -> None:
    if report.get("artifact_id") != artifact_id or report.get("status") != "passed":
        raise GitHubTransferError("github_safe_report_status_invalid")
    if report.get("blocker_count") != 0:
        raise GitHubTransferError("github_safe_report_blocked")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise GitHubTransferError("github_safe_report_fingerprint_drift")
    if artifact_id == HOLDOUT_REPORT_ARTIFACT_ID:
        projection = report.get("manifest_projection")
        hashes = report.get("hashes")
        if (
            report.get("classification") != DIAGNOSTIC_CLASSIFICATION
            or report.get("claim_boundary_status") != DIAGNOSTIC_CLAIM_BOUNDARY
            or report.get("diagnostic_only") is not True
            or report.get("final_acceptance_eligible") is not False
            or report.get("routing_contract_status") != "passed"
            or report.get("oracle_free_projection_status") != "passed"
            or report.get("query_class_counts") != _EXPECTED_QUERY_CLASS_COUNTS
            or not isinstance(projection, Mapping)
            or not isinstance(hashes, Mapping)
        ):
            raise GitHubTransferError("github_holdout_safe_projection_invalid")
        _assert_oracle_free_projection(projection)
        if (
            projection.get("schema_id") != ORACLE_FREE_PROJECTION_SCHEMA_ID
            or projection.get("classification") != DIAGNOSTIC_CLASSIFICATION
            or projection.get("claim_boundary_status") != DIAGNOSTIC_CLAIM_BOUNDARY
            or projection.get("diagnostic_only") is not True
            or projection.get("final_acceptance_eligible") is not False
            or projection.get("routing_profile_id") != ROUTING_PROFILE_ID
            or projection.get("routing_profile_fingerprint") != ROUTING_PROFILE_FINGERPRINT
            or projection.get("query_class_counts") != _EXPECTED_QUERY_CLASS_COUNTS
            or projection.get("projection_fingerprint")
            != _payload_fingerprint(projection, "projection_fingerprint")
            or hashes.get("manifest_projection_fingerprint")
            != projection.get("projection_fingerprint")
            or hashes.get("routing_profile_fingerprint") != ROUTING_PROFILE_FINGERPRINT
        ):
            raise GitHubTransferError("github_holdout_safe_projection_binding_drift")
    assert_no_public_raw_references(report, artifact_id)
    serialized = _canonical_bytes(report).decode("utf-8")
    forbidden_fragments = (
        "private_query",
        "expected_private",
        "issue_number",
        "author_login",
        "comment_id",
        "source_records",
        "observations",
    )
    if any(fragment in serialized for fragment in forbidden_fragments):
        raise GitHubTransferError("github_safe_report_private_field_leak")


def _assert_oracle_free_projection(value: Any) -> None:
    forbidden_keys = {
        "expected_private",
        "private_query",
        "required_source_observation_ids",
        "required_source_record_fingerprints",
        "source_records",
        "observations",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in forbidden_keys:
                raise GitHubTransferError("github_holdout_projection_oracle_field_present")
            _assert_oracle_free_projection(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_oracle_free_projection(nested)


def _validate_persisted_artifacts(artifacts: TransferArtifacts) -> None:
    expected_names = sorted(
        [
            PRIVATE_EXPORT_NAME,
            SAFE_COMPLETENESS_NAME,
            PRIVATE_HOLDOUT_NAME,
            SAFE_HOLDOUT_NAME,
        ]
    )
    if sorted(path.name for path in artifacts.output_root.iterdir()) != expected_names:
        raise GitHubTransferError("github_persisted_file_set_invalid")
    if stat.S_IMODE(artifacts.output_root.stat().st_mode) != 0o500:
        raise GitHubTransferError("github_output_root_mode_invalid")
    for path in (artifacts.private_export_path, artifacts.private_holdout_path):
        if stat.S_IMODE(path.stat().st_mode) != 0o400:
            raise GitHubTransferError("github_private_artifact_mode_invalid")
    for path in (artifacts.safe_completeness_path, artifacts.safe_holdout_path):
        if stat.S_IMODE(path.stat().st_mode) != 0o444:
            raise GitHubTransferError("github_safe_artifact_mode_invalid")
    if _sha256_file(artifacts.private_export_path) != artifacts.private_export_sha256:
        raise GitHubTransferError("github_persisted_export_hash_drift")
    if _sha256_file(artifacts.private_holdout_path) != artifacts.private_holdout_sha256:
        raise GitHubTransferError("github_persisted_holdout_hash_drift")
    persisted_export = json.loads(artifacts.private_export_path.read_bytes())
    persisted_holdout = json.loads(artifacts.private_holdout_path.read_bytes())
    persisted_completeness = json.loads(artifacts.safe_completeness_path.read_bytes())
    persisted_holdout_projection = json.loads(artifacts.safe_holdout_path.read_bytes())
    _validate_private_export(persisted_export)
    _validate_transfer_holdout(persisted_holdout, private_export=persisted_export)
    _validate_safe_report(
        persisted_completeness,
        COMPLETENESS_REPORT_ARTIFACT_ID,
    )
    _validate_safe_report(
        persisted_holdout_projection,
        HOLDOUT_REPORT_ARTIFACT_ID,
    )
    _validate_safe_completeness_binding(
        persisted_completeness,
        private_export=persisted_export,
        private_export_sha256=artifacts.private_export_sha256,
    )
    _validate_safe_holdout_binding(
        persisted_holdout_projection,
        private_export=persisted_export,
        private_export_sha256=artifacts.private_export_sha256,
        holdout=persisted_holdout,
        holdout_sha256=artifacts.private_holdout_sha256,
    )


def _validate_safe_completeness_binding(
    report: Mapping[str, Any],
    *,
    private_export: Mapping[str, Any],
    private_export_sha256: str,
) -> None:
    expected_hashes = {
        "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
        "source_snapshot_fingerprint": private_export["source_snapshot_fingerprint"],
        "parser_fingerprint": private_export["parser_fingerprint"],
        "permission_fingerprint": private_export["permission_fingerprint"],
        "source_inventory_fingerprint": sha256_json(private_export["source_inventory"]),
        "observation_snapshot_fingerprint": sha256_json(private_export["observations"]),
        "lineage_fingerprint": private_export["lineage_fingerprint"],
        "source_occurrence_schema_fingerprint": private_export[
            "source_occurrence_schema_fingerprint"
        ],
        "private_export_sha256": private_export_sha256,
        "private_export_fingerprint": private_export["export_fingerprint"],
    }
    if (
        report.get("counts") != private_export.get("counts")
        or report.get("hashes") != expected_hashes
    ):
        raise GitHubTransferError("github_safe_completeness_cross_binding_drift")


def _validate_safe_holdout_binding(
    report: Mapping[str, Any],
    *,
    private_export: Mapping[str, Any],
    private_export_sha256: str,
    holdout: Mapping[str, Any],
    holdout_sha256: str,
) -> None:
    expected_projection = _build_oracle_free_holdout_projection(holdout)
    expected_hashes = {
        "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
        "holdout_policy_fingerprint": HOLDOUT_POLICY_FINGERPRINT,
        "source_snapshot_fingerprint": private_export["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(private_export["source_inventory"]),
        "observation_snapshot_fingerprint": sha256_json(private_export["observations"]),
        "source_occurrence_schema_fingerprint": private_export[
            "source_occurrence_schema_fingerprint"
        ],
        "routing_profile_fingerprint": ROUTING_PROFILE_FINGERPRINT,
        "routing_binding_set_fingerprint": holdout["routing_binding_set_fingerprint"],
        "manifest_projection_fingerprint": expected_projection["projection_fingerprint"],
        "private_export_sha256": private_export_sha256,
        "private_export_fingerprint": private_export["export_fingerprint"],
        "private_holdout_sha256": holdout_sha256,
        "private_holdout_fingerprint": holdout["manifest_fingerprint"],
    }
    if (
        report.get("manifest_projection") != expected_projection
        or report.get("strata_counts") != holdout.get("strata_counts")
        or report.get("query_class_counts") != holdout.get("query_class_counts")
        or report.get("hashes") != expected_hashes
    ):
        raise GitHubTransferError("github_safe_holdout_cross_binding_drift")


def _validate_comment_identity(
    issue_records: Sequence[Mapping[str, Any]],
    comments_by_issue: Mapping[str, Any],
) -> None:
    comment_ids: set[str] = set()
    issue_numbers = {int(issue["issue_number"]) for issue in issue_records}
    for issue in issue_records:
        issue_number = int(issue["issue_number"])
        comments = comments_by_issue.get(str(issue_number))
        if not isinstance(comments, list):
            raise GitHubTransferError("github_comment_collection_missing")
        for comment in comments:
            if comment.get("issue_number") != issue_number:
                raise GitHubTransferError("github_comment_parent_mismatch")
            comment_id = str(comment.get("comment_id"))
            if comment_id in comment_ids:
                raise GitHubTransferError("github_comment_identity_duplicate")
            comment_ids.add(comment_id)
    if set(int(key) for key in comments_by_issue) != issue_numbers:
        raise GitHubTransferError("github_comment_issue_set_mismatch")


def _next_page_number(link_header: str | None) -> int | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' not in part:
            continue
        match = re.search(r"[?&]page=([0-9]+)", part)
        if not match:
            raise GitHubTransferError("github_comment_next_link_invalid")
        return int(match.group(1))
    return None


def _payload_fingerprint(payload: Mapping[str, Any], field_name: str) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != field_name})


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _string(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not value:
        raise GitHubTransferError(reason_code)
    return value


def _nullable_string(value: Any, reason_code: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GitHubTransferError(reason_code)
    return value


def _nonnegative_int(value: Any, reason_code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GitHubTransferError(reason_code)
    return value


def _timestamp(value: Any, reason_code: str) -> str:
    text = _string(value, reason_code)
    if not (text.endswith("Z") or "+" in text[10:]):
        raise GitHubTransferError(reason_code)
    return text


def _nullable_timestamp(value: Any, reason_code: str) -> str | None:
    if value is None:
        return None
    return _timestamp(value, reason_code)


def _blocked_report(reason_code: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "artifact_id": COMPLETENESS_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "scope_status": "blocked",
        "counts": {"blocker_count": 1},
        "hashes": {
            "capture_policy_fingerprint": CAPTURE_POLICY_FINGERPRINT,
            "blocker_fingerprint": sha256_json(reason_code),
        },
        "blocker_count": 1,
    }
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )
    assert_no_public_raw_references(report, COMPLETENESS_REPORT_ARTIFACT_ID)
    return report


__all__ = [
    "CAPTURE_POLICY_FINGERPRINT",
    "COMPLETENESS_REPORT_ARTIFACT_ID",
    "DEFAULT_OUTPUT_ROOT",
    "GitHubTransferError",
    "HOLDOUT_POLICY_FINGERPRINT",
    "HOLDOUT_REPORT_ARTIFACT_ID",
    "HttpJsonResponse",
    "ISSUE_NUMBERS",
    "ORACLE_FREE_PROJECTION_SCHEMA_ID",
    "REPOSITORY",
    "ROUTING_PROFILE_FINGERPRINT",
    "ROUTING_PROFILE_ID",
    "SOURCE_KIND",
    "SOURCE_OCCURRENCE_SCHEMA_FINGERPRINT",
    "SOURCE_OCCURRENCE_SCHEMA_ID",
    "TransferArtifacts",
    "acquire_github_scope",
    "build_and_persist_transfer_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
