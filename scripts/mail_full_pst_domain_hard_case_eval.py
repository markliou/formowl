#!/usr/bin/env python3
"""Run or validate a domain-hard FormOwl #21 full-PST mail evidence eval.

This evaluator is stricter than ``mail_full_pst_100_case_eval.py`` on case
shape. It still measures governed evidence retrieval, not final natural
language business reasoning:

full PST import -> normalized MailEvidenceBundle -> governed JSON-RPC
``query_mail_evidence`` -> 100 domain-hard evidence-retrieval cases.

The private manifest kept in the work directory may contain query text and
source observation ids for follow-up debugging. The public report is
hash/status/count/timing-only and must not expose prompts, query text, snippets,
subjects, senders, message ids, observation ids, attachment names, upload
locators, parser commands, scratch paths, SQL, or environment values.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Sequence
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = Path(__file__).resolve().parent
PYTHON_ROOT = ROOT / "python"
for import_path in (PYTHON_ROOT, SCRIPT_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import mail_full_pst_100_case_eval as baseline_eval  # noqa: E402
import mail_real_pst_smoke as sampled_smoke  # noqa: E402
from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_contract import PermissionScope, assert_no_public_raw_references, sha256_json  # noqa: E402
from formowl_gateway import (  # noqa: E402
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
    validate_public_gateway_payload,
)
from formowl_evaluator.report_validation import (  # noqa: E402
    dict_or_empty as _dict_or_empty,
    public_outputs_are_safe,
    require_sha256 as _require_sha256,
    validate_exact_keys as _validate_exact_keys,
)
from formowl_ingestion.extractors import PstMailArchiveExtractor  # noqa: E402
from formowl_ingestion.storage import (  # noqa: E402
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
    UploadSessionStore,
)
from formowl_ingestion.uploads import create_upload_session  # noqa: E402
from formowl_mail import (  # noqa: E402
    MailEvidenceBundle,
    PostgreSQLMailEvidenceStore,
    build_mail_evidence_query_handler,
    receive_mail_archive_upload,
    run_upload_session_mail_import,
)

DEFAULT_OUTPUT = ROOT / ".test-tmp" / "formowl-mail-domain-hard-case-eval.json"
DEFAULT_PST_FIXTURE = ROOT / "tests" / "pst-exm" / "archive.pst"
NOW = "2026-07-07T12:00:00+00:00"
SESSION_ID = "session_full_pst_domain_hard_case_eval"
ACTOR_USER_ID = "user_full_pst_domain_hard_case_eval_owner"
DENIED_USER_ID = "user_full_pst_domain_hard_case_eval_denied"
WORKSPACE_ID = "workspace_formowl"
PROJECT_ID = "project_formowl"
STORAGE_BACKEND_ID = "storage_full_pst_domain_hard_case_eval"
UPLOAD_FILENAME = "mail-import.pst"
PST_MIME_TYPE = "application/vnd.ms-outlook"
REPORT_TYPE = "mail_full_pst_domain_hard_case_eval"
CASE_POLICY_VERSION = "formowl_full_pst_domain_hard_case_eval_v1"
FULL_EVAL_OPT_IN_ENV = "FORMOWL_RUN_FULL_PST_DOMAIN_HARD_CASE_EVAL"
WORK_DIR_SENTINEL_NAME = ".formowl-mail-domain-hard-case-workdir"
WORK_DIR_SENTINEL_VALUE = "formowl-mail-domain-hard-case-eval-v1"
PRIVATE_MANIFEST_NAME = "domain_hard_case_manifest.private.json"
CASE_COUNT = 100
DOMAIN_CASE_COUNT = 10

DOMAINS = (
    "production_management",
    "warehouse_management",
    "financial_accounting",
    "engineering",
    "research_and_development",
    "project_management",
    "product_management",
    "business_development",
    "sales",
    "distribution_channel",
)
PATTERNS = (
    "multi_message",
    "actor_topic",
    "chronology",
    "conflict",
    "no_match",
    "permission_denied",
)
RESULT_KINDS = ("owner_match", "no_match", "permission_denied")
BLOCKED_REASONS = {
    "domain_hard_eval_requires_explicit_opt_in",
    "domain_hard_case_eval_failed",
    "missing_fixture",
}

DOMAIN_VOCABULARY: dict[str, set[str]] = {
    "production_management": {
        "build",
        "change",
        "component",
        "delay",
        "hold",
        "line",
        "machine",
        "manufacturing",
        "material",
        "overtime",
        "plan",
        "production",
        "purchase",
        "quality",
        "rework",
        "run",
        "schedule",
        "scrap",
        "shift",
        "shortage",
        "substitute",
    },
    "warehouse_management": {
        "allocation",
        "backorder",
        "bin",
        "carrier",
        "component",
        "cycle",
        "delivery",
        "dock",
        "inbound",
        "inventory",
        "location",
        "lot",
        "material",
        "order",
        "outbound",
        "pick",
        "purchase",
        "receipt",
        "replenishment",
        "shipment",
        "stock",
        "transfer",
        "warehouse",
        "wave",
    },
    "financial_accounting": {
        "accrual",
        "amount",
        "audit",
        "balance",
        "budget",
        "close",
        "cost",
        "expense",
        "finance",
        "invoice",
        "margin",
        "order",
        "payment",
        "price",
        "purchase",
        "reconciliation",
        "revenue",
        "tax",
        "vendor",
        "variance",
        "year",
    },
    "engineering": {
        "api",
        "build",
        "bug",
        "cause",
        "component",
        "dependency",
        "deploy",
        "design",
        "drawing",
        "engineering",
        "failure",
        "fix",
        "integration",
        "migration",
        "regression",
        "release",
        "reliability",
        "security",
        "test",
        "version",
    },
    "research_and_development": {
        "ai",
        "benchmark",
        "data",
        "experiment",
        "feasibility",
        "hypothesis",
        "lab",
        "llm",
        "method",
        "model",
        "prototype",
        "research",
        "result",
        "sample",
        "test",
        "development",
        "design",
        "trial",
        "validation",
    },
    "project_management": {
        "action",
        "approval",
        "blocked",
        "decision",
        "deadline",
        "deliverable",
        "dependency",
        "meeting",
        "milestone",
        "owner",
        "overdue",
        "pending",
        "progress",
        "project",
        "risk",
        "scope",
        "status",
        "task",
        "update",
    },
    "product_management": {
        "agent",
        "beta",
        "cohort",
        "competitor",
        "customer",
        "design",
        "feature",
        "feedback",
        "flag",
        "launch",
        "market",
        "package",
        "pricing",
        "product",
        "release",
        "requirement",
        "roadmap",
    },
    "business_development": {
        "account",
        "alliance",
        "contract",
        "customer",
        "deal",
        "expansion",
        "intro",
        "legal",
        "market",
        "opportunity",
        "order",
        "partner",
        "partnership",
        "pipeline",
        "procurement",
        "renewal",
        "strategic",
    },
    "sales": {
        "account",
        "agent",
        "approval",
        "buyer",
        "commit",
        "competitor",
        "customer",
        "deal",
        "discount",
        "forecast",
        "opportunity",
        "order",
        "poc",
        "procurement",
        "quote",
        "renewal",
        "sales",
    },
    "distribution_channel": {
        "agent",
        "allocation",
        "authorized",
        "backorder",
        "bid",
        "channel",
        "customer",
        "dealer",
        "delivery",
        "deal",
        "distributor",
        "inventory",
        "mdf",
        "order",
        "partner",
        "price",
        "product",
        "rebate",
        "registration",
        "representative",
        "reseller",
        "sales",
        "shipment",
        "territory",
    },
}

CONFLICT_TERMS = {
    "approved",
    "blocked",
    "cancel",
    "change",
    "conflict",
    "delay",
    "denied",
    "exception",
    "fail",
    "failed",
    "fixed",
    "hold",
    "issue",
    "pending",
    "problem",
    "rejected",
    "revised",
    "risk",
    "shortage",
    "slip",
    "urgent",
    "waiver",
}

_TOP_LEVEL_KEYS = {
    "report_type",
    "generated_at",
    "metrics",
    "safe_outputs",
    "claim_boundary",
}
_FORBIDDEN_TRUE_CLAIMS = {
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_real_upload_iframe_claim",
    "supports_general_full_pst_parser_readiness_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_business_answer_generation_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_raw_mail_access_claim",
    "supports_production_ready_claim",
}
_REQUIRED_SUCCESS_METRICS = {
    "fixture_present",
    "fixture_stream_hash_succeeded",
    "pst_signature_verified",
    "full_parse_executed",
    "no_sampling_config_used",
    "real_parser_invoked",
    "mail_observations_persisted",
    "mail_evidence_rows_persisted",
    "domain_case_manifest_generated",
    "domain_case_count_is_100",
    "each_domain_has_10_cases",
    "each_domain_has_no_match_case",
    "each_domain_has_permission_denied_case",
    "each_domain_has_positive_patterns",
    "positive_cases_require_multi_evidence",
    "pattern_coverage_met",
    "scored_case_count_is_100",
    "pass_rate_recorded",
    "row_derived_validation_recomputed",
    "permission_denied_cases_redacted",
    "no_match_cases_non_leaking",
    "private_manifest_preserved",
    "raw_archive_retention_decision_recorded",
    "kg_wiki_side_effects_absent",
    "cleanup_policy_respected",
    "raw_leak_guard_passed",
    "domain_hard_case_baseline_completed",
}
_MEASURED_CASE_QUALITY_METRICS = {
    "permission_denied_cases_redacted",
    "no_match_cases_non_leaking",
}


@dataclass(frozen=True)
class _Stores:
    upload_session_store: UploadSessionStore
    asset_store: AssetStore
    job_store: JobStore
    extractor_run_store: ExtractorRunStore
    observation_store: ObservationStore
    object_store: FileObjectStore
    audit_store: FileAuditLogStore


@dataclass(frozen=True)
class _SegmentInfo:
    source_observation_id: str
    email_message_id: str
    sender: str | None
    sent_at: str | None
    tokens: frozenset[str]
    sender_tokens: frozenset[str]


@dataclass(frozen=True)
class _DomainCase:
    case_id: str
    domain: str
    intent_kind: str
    pattern: str
    result_kind: str
    query_text: str
    requester_user_id: str
    required_source_observation_ids: tuple[str, ...]
    required_logical_source_item_ids: tuple[str, ...] = ()
    forbidden_source_observation_ids: tuple[str, ...] = ()
    required_match_count: int = 2
    limit: int = 10

    def private_fingerprint(self) -> str:
        return sha256_json(
            {
                "case_id": self.case_id,
                "domain": self.domain,
                "intent_kind": self.intent_kind,
                "pattern": self.pattern,
                "result_kind": self.result_kind,
                "query_text": self.query_text,
                "requester_user_id": self.requester_user_id,
                "required_source_observation_ids": self.required_source_observation_ids,
                "required_logical_source_item_ids": self.required_logical_source_item_ids,
                "forbidden_source_observation_ids": self.forbidden_source_observation_ids,
                "required_match_count": self.required_match_count,
                "limit": self.limit,
            }
        )

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "domain": self.domain,
            "intent_kind": self.intent_kind,
            "pattern": self.pattern,
            "result_kind": self.result_kind,
            "query_text": self.query_text,
            "requester_user_id": self.requester_user_id,
            "required_source_observation_ids": list(self.required_source_observation_ids),
            "required_logical_source_item_ids": list(self.required_logical_source_item_ids),
            "forbidden_source_observation_ids": list(self.forbidden_source_observation_ids),
            "required_match_count": self.required_match_count,
            "limit": self.limit,
            "private_fingerprint": self.private_fingerprint(),
        }


@dataclass(frozen=True)
class _DomainScore:
    case: _DomainCase
    passed: bool
    row: dict[str, Any]


class _DomainCaseQueryRunner:
    """Reusable governed JSON-RPC query path for domain-hard evaluation."""

    def __init__(self, bundle: MailEvidenceBundle) -> None:
        self._bundle = bundle
        self._semantic_gateway = SemanticMcpGateway(
            mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=NOW)
        )
        self._gateways_by_requester: dict[str, SemanticMcpJsonRpcGateway] = {}

    def query(self, case: _DomainCase) -> dict[str, Any]:
        gateway = self._gateways_by_requester.get(case.requester_user_id)
        if gateway is None:
            gateway = SemanticMcpJsonRpcGateway(
                semantic_gateway=self._semantic_gateway,
                session=SemanticGatewaySession(
                    session_id=SESSION_ID,
                    actor_user_id=case.requester_user_id,
                    workspace_id=WORKSPACE_ID,
                ),
            )
            self._gateways_by_requester[case.requester_user_id] = gateway
        return gateway.handle_json_rpc(_json_rpc_request_for_case(self._bundle, case))


def run_domain_hard_case_eval(
    work_dir: Path,
    *,
    pst_fixture: Path = DEFAULT_PST_FIXTURE,
    cleanup_work_dir: bool = False,
) -> dict[str, Any]:
    if os.environ.get(FULL_EVAL_OPT_IN_ENV) != "1":
        return _blocked_report(
            "domain_hard_eval_requires_explicit_opt_in",
            work_dir_cleaned=True,
        )

    try:
        report = _run_domain_hard_case_eval_inner(work_dir, pst_fixture=pst_fixture)
    except FileNotFoundError:
        report = _blocked_report("missing_fixture", work_dir_cleaned=False)
    except Exception:
        report = _blocked_report("domain_hard_case_eval_failed", work_dir_cleaned=False)

    is_blocked_report = bool(report.get("metrics", {}).get("blocked_reason"))
    if cleanup_work_dir:
        cleaned = _cleanup(work_dir)
        report["safe_outputs"]["work_dir_cleaned"] = cleaned
        if not is_blocked_report:
            report["metrics"]["cleanup_policy_respected"] = cleaned
    else:
        report["safe_outputs"]["work_dir_cleaned"] = False
        if not is_blocked_report:
            report["metrics"]["cleanup_policy_respected"] = True
    report["metrics"]["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
    report["metrics"]["domain_hard_case_baseline_completed"] = _domain_hard_baseline_completed(
        report
    )
    report["claim_boundary"]["supports_operator_provided_full_pst_domain_hard_baseline_claim"] = (
        report["metrics"]["domain_hard_case_baseline_completed"]
    )
    report["validation"] = validate_report(report)
    return report


def _run_domain_hard_case_eval_inner(work_dir: Path, *, pst_fixture: Path) -> dict[str, Any]:
    fixture = pst_fixture.resolve()
    fixture_start = time.monotonic()
    fixture_size, fixture_hash, fixture_header_ok = sampled_smoke._fixture_properties(fixture)
    fixture_elapsed_ms = int((time.monotonic() - fixture_start) * 1000)
    _prepare_work_dir(work_dir)
    stores = _stores(work_dir / "data", work_dir / "object-root")

    upload_started = time.monotonic()
    upload_session = create_upload_session(
        upload_session_store=stores.upload_session_store,
        audit_store=stores.audit_store,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        workspace_id=WORKSPACE_ID,
        owner_scope_type="project",
        owner_scope_id=PROJECT_ID,
        project_id=PROJECT_ID,
        intent="Evaluate PST mail evidence retrieval across ten business domains.",
        intended_asset_type="pst",
        ingestion_profile="mail_archive_phase1",
        visibility_scope="workspace",
        permission_scope=PermissionScope.project(PROJECT_ID),
        expires_at="2026-07-08T00:00:00+00:00",
        created_at=NOW,
    )
    receipt = receive_mail_archive_upload(
        fixture,
        upload_session_id=upload_session.upload_session_id,
        upload_session_store=stores.upload_session_store,
        object_store=stores.object_store,
        asset_store=stores.asset_store,
        audit_store=stores.audit_store,
        storage_backend_id=STORAGE_BACKEND_ID,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        original_filename=UPLOAD_FILENAME,
        content_type=PST_MIME_TYPE,
        expected_content_hash=fixture_hash,
        submitted_fields={
            "upload_session_id": upload_session.upload_session_id,
            "actor_user_id": ACTOR_USER_ID,
            "session_id": SESSION_ID,
            "workspace_id": WORKSPACE_ID,
            "original_filename": UPLOAD_FILENAME,
            "content_type": PST_MIME_TYPE,
            "expected_content_hash": fixture_hash,
        },
        received_at=NOW,
    )
    upload_elapsed_ms = int((time.monotonic() - upload_started) * 1000)

    connection = sampled_smoke._RecordingMailConnection()
    adapter = PstMailArchiveExtractor(scratch_parent=work_dir / "pst-scratch")
    extraction_config = {
        "timeout_seconds": 3600,
        "body_segment_max_chars": 4000,
        "max_body_segments_per_message": None,
        "max_attachment_text_bytes": 5 * 1024 * 1024,
        "preserve_private_body_text": True,
        "parser_workers": max(1, min(os.cpu_count() or 1, 8)),
    }
    import_started = time.monotonic()
    import_result = run_upload_session_mail_import(
        None,
        upload_session_id=upload_session.upload_session_id,
        upload_session_store=stores.upload_session_store,
        object_store=stores.object_store,
        asset_store=stores.asset_store,
        job_store=stores.job_store,
        extractor_run_store=stores.extractor_run_store,
        observation_store=stores.observation_store,
        mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
        storage_backend_id=STORAGE_BACKEND_ID,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        query_text=None,
        created_at=NOW,
        adapter=adapter,
        extraction_config=extraction_config,
        parser_name=adapter.name(),
        parser_version=adapter.version(),
    )
    import_elapsed_ms = int((time.monotonic() - import_started) * 1000)

    bundle_read_started = time.monotonic()
    stored_bundle = PostgreSQLMailEvidenceStore(connection).get_bundle(
        mail_import_session_id=import_result.mail_import_session_id,
    )
    if stored_bundle is None:
        raise RuntimeError("mail evidence bundle was not persisted")
    bundle_read_elapsed_ms = int((time.monotonic() - bundle_read_started) * 1000)

    report = _build_report_for_bundle(
        stored_bundle,
        work_dir=work_dir,
        archive_sha256=fixture_hash,
        parser_version=adapter.version(),
        fixture_size_bytes=fixture_size,
        fixture_header_ok=fixture_header_ok,
        receipt_uploaded=receipt.status == "uploaded",
        asset_count=len(stores.asset_store.list()),
        job_count=len(stores.job_store.list()),
        extractor_run_count=len(stores.extractor_run_store.list()),
        observation_count=len(stores.observation_store.list()),
        mail_evidence_table_count=len(connection.rows),
        mail_evidence_row_count=sampled_smoke._mail_evidence_row_count(connection),
        mail_evidence_statement_count=len(connection.statements),
        parser_worker_count=extraction_config["parser_workers"],
        extraction_config_shape_hash=sha256_json(
            {
                "timeout_seconds": extraction_config["timeout_seconds"],
                "body_segment_max_chars": extraction_config["body_segment_max_chars"],
                "max_body_segments_per_message": extraction_config["max_body_segments_per_message"],
                "max_messages_present": False,
                "parser_workers": extraction_config["parser_workers"],
            }
        ),
        fixture_hash_elapsed_ms=fixture_elapsed_ms,
        upload_elapsed_ms=upload_elapsed_ms,
        import_elapsed_ms=import_elapsed_ms,
        bundle_read_elapsed_ms=bundle_read_elapsed_ms,
        staging_leftover_count=sampled_smoke._leftover_entry_count(work_dir / "staging"),
        scratch_leftover_count=sampled_smoke._leftover_entry_count(work_dir / "pst-scratch"),
    )
    return report


def _build_report_for_bundle(
    bundle: MailEvidenceBundle,
    *,
    work_dir: Path,
    archive_sha256: str,
    parser_version: str,
    fixture_size_bytes: int,
    fixture_header_ok: bool,
    receipt_uploaded: bool,
    asset_count: int,
    job_count: int,
    extractor_run_count: int,
    observation_count: int,
    mail_evidence_table_count: int,
    mail_evidence_row_count: int,
    mail_evidence_statement_count: int,
    parser_worker_count: int,
    extraction_config_shape_hash: str,
    fixture_hash_elapsed_ms: int,
    upload_elapsed_ms: int,
    import_elapsed_ms: int,
    bundle_read_elapsed_ms: int,
    staging_leftover_count: int = 0,
    scratch_leftover_count: int = 0,
    fixed_cases: Sequence[_DomainCase] | None = None,
    fixed_private_manifest_hash: str | None = None,
) -> dict[str, Any]:
    manifest_started = time.monotonic()
    cases = (
        list(fixed_cases)
        if fixed_cases is not None
        else _generate_domain_case_manifest(
            bundle,
            archive_sha256=archive_sha256,
            parser_version=parser_version,
        )
    )
    manifest_elapsed_ms = int((time.monotonic() - manifest_started) * 1000)
    private_manifest_path = work_dir / "artifacts" / PRIVATE_MANIFEST_NAME
    if fixed_cases is None:
        private_manifest_started = time.monotonic()
        private_manifest_hash = _write_private_manifest(
            private_manifest_path,
            bundle=bundle,
            cases=cases,
            archive_sha256=archive_sha256,
            parser_version=parser_version,
        )
        private_manifest_elapsed_ms = int((time.monotonic() - private_manifest_started) * 1000)
    else:
        if not private_manifest_path.is_file() or not fixed_private_manifest_hash:
            raise RuntimeError("fixed private manifest is unavailable")
        private_manifest_hash = fixed_private_manifest_hash
        private_manifest_elapsed_ms = 0

    scoring_started = time.monotonic()
    scores, query_runner_setup_elapsed_ms, case_query_loop_elapsed_ms = _score_domain_cases(
        bundle, cases
    )
    scoring_elapsed_ms = int((time.monotonic() - scoring_started) * 1000)
    case_rows = [score.row for score in scores]
    aggregate = _aggregate_scores(case_rows)
    domain_counts = _row_counts(case_rows, "domain_hash")
    domain_passed_counts = _passed_row_counts(case_rows, "domain_hash")
    pattern_counts = _row_counts(case_rows, "pattern_hash")
    pattern_passed_counts = _passed_row_counts(case_rows, "pattern_hash")
    result_kind_counts = _row_counts(case_rows, "result_kind")
    response_hashes = [row["response_hash"] for row in case_rows]
    positive_rows = [row for row in case_rows if row.get("result_kind") == "owner_match"]
    artifact_entry_count, artifact_size_bytes = _tree_stats(work_dir / "artifacts")
    staging_entry_count, staging_size_bytes = _tree_stats(work_dir / "staging")
    scratch_entry_count, scratch_size_bytes = _tree_stats(work_dir / "pst-scratch")

    metrics = {
        "fixture_present": True,
        "fixture_stream_hash_succeeded": bool(archive_sha256),
        "pst_signature_verified": fixture_header_ok,
        "full_parse_executed": True,
        "no_sampling_config_used": True,
        "real_parser_invoked": True,
        "mail_observations_persisted": observation_count > 0,
        "mail_evidence_rows_persisted": mail_evidence_row_count > 0,
        "domain_case_manifest_generated": len(cases) == CASE_COUNT,
        "domain_case_count_is_100": aggregate["case_count"] == CASE_COUNT,
        "each_domain_has_10_cases": _each_domain_has_count(domain_counts, DOMAIN_CASE_COUNT),
        "each_domain_has_no_match_case": _each_domain_has_result_kind(case_rows, "no_match"),
        "each_domain_has_permission_denied_case": _each_domain_has_result_kind(
            case_rows, "permission_denied"
        ),
        "each_domain_has_positive_patterns": _each_domain_has_positive_patterns(case_rows),
        "positive_cases_require_multi_evidence": bool(positive_rows)
        and all(row.get("required_evidence_count", 0) >= 2 for row in positive_rows),
        "pattern_coverage_met": all(
            pattern_counts.get(sha256_json(pattern), 0) > 0 for pattern in PATTERNS
        ),
        "scored_case_count_is_100": aggregate["scored_case_count"] == CASE_COUNT,
        "pass_rate_recorded": aggregate["scored_case_count"] == CASE_COUNT,
        "row_derived_validation_recomputed": _aggregate_consistent(aggregate),
        "permission_denied_cases_redacted": _permission_denied_cases_redacted(case_rows),
        "no_match_cases_non_leaking": _no_match_cases_non_leaking(case_rows),
        "private_manifest_preserved": private_manifest_path.is_file(),
        "raw_archive_retention_decision_recorded": (
            bundle.mail_import_session.retention_policy == "retain_7_days"
            and bundle.mail_import_session.raw_archive_retention_decision == "retained_by_policy"
        ),
        "kg_wiki_side_effects_absent": True,
        "cleanup_policy_respected": True,
        "raw_leak_guard_passed": True,
        "domain_hard_case_baseline_completed": False,
    }
    safe_outputs = {
        "fixture_id_hash": sha256_json("tests/pst-exm/archive.pst"),
        "fixture_sha256": archive_sha256,
        "fixture_size_bytes": fixture_size_bytes,
        "full_parse_executed": True,
        "sample_message_limit": 0,
        "sampling_config_used": False,
        "parser_adapter_contract_hash": sha256_json(
            {
                "name": "pst_mail_archive_extractor",
                "version": parser_version,
                "domain_hard_eval": True,
            }
        ),
        "parser_version_hash": sha256_json(parser_version),
        "extraction_config_shape_hash": extraction_config_shape_hash,
        "asset_count": asset_count,
        "job_count": job_count,
        "extractor_run_count": extractor_run_count,
        "observation_count": observation_count,
        "message_count": len(bundle.messages),
        "folder_occurrence_count": len(bundle.folder_occurrences),
        "body_segment_count": len(bundle.body_segments),
        "attachment_occurrence_count": len(bundle.attachment_occurrences),
        "parse_warning_count": len(bundle.parse_warnings),
        "parse_warning_codes_hash": sha256_json(
            [warning.warning_code for warning in bundle.parse_warnings]
        ),
        "mail_evidence_table_count": mail_evidence_table_count,
        "mail_evidence_row_count": mail_evidence_row_count,
        "mail_evidence_statement_count": mail_evidence_statement_count,
        "parser_worker_count": parser_worker_count,
        "case_policy_hash": sha256_json(CASE_POLICY_VERSION),
        "case_manifest_hash": sha256_json([case.private_fingerprint() for case in cases]),
        "case_result_hash": sha256_json(case_rows),
        "private_manifest_hash": private_manifest_hash,
        "private_manifest_case_count": len(cases),
        "private_manifest_write_elapsed_ms": private_manifest_elapsed_ms,
        "fixture_hash_elapsed_ms": fixture_hash_elapsed_ms,
        "upload_elapsed_ms": upload_elapsed_ms,
        "import_elapsed_ms": import_elapsed_ms,
        "bundle_read_elapsed_ms": bundle_read_elapsed_ms,
        "case_manifest_elapsed_ms": manifest_elapsed_ms,
        "scoring_elapsed_ms": scoring_elapsed_ms,
        "query_runner_setup_elapsed_ms": query_runner_setup_elapsed_ms,
        "case_query_loop_elapsed_ms": case_query_loop_elapsed_ms,
        "case_count": aggregate["case_count"],
        "scored_case_count": aggregate["scored_case_count"],
        "passed_case_count": aggregate["passed_case_count"],
        "failed_case_count": aggregate["failed_case_count"],
        "pass_rate_basis_points": aggregate["pass_rate_basis_points"],
        "positive_case_count": result_kind_counts.get("owner_match", 0),
        "permission_denied_case_count": result_kind_counts.get("permission_denied", 0),
        "no_match_case_count": result_kind_counts.get("no_match", 0),
        "unique_case_id_hash_count": len({row["case_id_hash"] for row in case_rows}),
        "unique_response_hash_count": len(set(response_hashes)),
        "duplicate_response_hash_count": len(response_hashes) - len(set(response_hashes)),
        "domain_hash_counts": domain_counts,
        "domain_hash_passed_counts": domain_passed_counts,
        "pattern_hash_counts": pattern_counts,
        "pattern_hash_passed_counts": pattern_passed_counts,
        "result_kind_counts": result_kind_counts,
        "case_rows": case_rows,
        "artifact_retained_entry_count": artifact_entry_count,
        "artifact_retained_size_bytes": artifact_size_bytes,
        "staging_leftover_count": staging_leftover_count,
        "scratch_leftover_count": scratch_leftover_count,
        "staging_retained_entry_count": staging_entry_count,
        "staging_retained_size_bytes": staging_size_bytes,
        "scratch_retained_entry_count": scratch_entry_count,
        "scratch_retained_size_bytes": scratch_size_bytes,
        "work_dir_cleaned": False,
    }
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": _claim_boundary(False),
    }
    return report


def _generate_domain_case_manifest(
    bundle: MailEvidenceBundle,
    *,
    archive_sha256: str,
    parser_version: str,
) -> list[_DomainCase]:
    seed = sha256_json(
        {
            "case_policy_version": CASE_POLICY_VERSION,
            "archive_sha256": archive_sha256,
            "parser_version": parser_version,
            "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
        }
    )
    segments = _segment_infos(bundle)
    token_sources = _token_sources(segments)
    logical_source_by_observation_id = {
        segment.source_observation_id: segment.email_message_id for segment in segments
    }
    all_cases: list[_DomainCase] = []
    for domain in DOMAINS:
        positives = _positive_domain_cases(
            domain,
            segments=segments,
            token_sources=token_sources,
            seed=seed,
        )
        if len(positives) < 8:
            raise RuntimeError("insufficient_domain_evidence")
        selected = [
            replace(
                case,
                required_logical_source_item_ids=tuple(
                    dict.fromkeys(
                        logical_source_by_observation_id[observation_id]
                        for observation_id in case.required_source_observation_ids
                        if observation_id in logical_source_by_observation_id
                    )
                ),
            )
            for case in positives[:8]
        ]
        if any(
            len(case.required_logical_source_item_ids) < 1
            for case in selected
            if case.result_kind == "owner_match"
        ):
            raise RuntimeError("logical_source_gold_missing")
        all_cases.extend(selected)
        all_cases.extend(_negative_domain_cases(domain, selected[0], seed=seed))
    if len(all_cases) != CASE_COUNT or len({case.case_id for case in all_cases}) != CASE_COUNT:
        raise RuntimeError("domain hard case manifest did not produce 100 unique cases")
    return _rank_cases(all_cases, seed=seed)


def _positive_domain_cases(
    domain: str,
    *,
    segments: Sequence[_SegmentInfo],
    token_sources: Mapping[str, tuple[str, ...]],
    seed: str,
) -> list[_DomainCase]:
    candidates: list[_DomainCase] = []
    candidates.extend(
        _candidate_cases_for_pattern(
            domain,
            "multi_message",
            _multi_message_queries(domain, segments=segments, token_sources=token_sources),
            seed=seed,
        )
    )
    candidates.extend(
        _candidate_cases_for_pattern(
            domain,
            "actor_topic",
            _actor_topic_queries(domain, segments=segments),
            seed=seed,
        )
    )
    candidates.extend(
        _candidate_cases_for_pattern(
            domain,
            "chronology",
            _chronology_queries(domain, segments=segments, token_sources=token_sources),
            seed=seed,
        )
    )
    candidates.extend(
        _candidate_cases_for_pattern(
            domain,
            "conflict",
            _conflict_queries(domain, segments=segments),
            seed=seed,
        )
    )
    selected: list[_DomainCase] = []
    used: set[str] = set()
    pattern_targets = {
        "multi_message": 2,
        "actor_topic": 2,
        "chronology": 2,
        "conflict": 2,
    }
    for pattern, target in pattern_targets.items():
        pattern_candidates = [item for item in candidates if item.pattern == pattern]
        ranked = _rank_cases(pattern_candidates, seed=seed)
        if len(ranked) < target:
            return []
        for case in ranked[:target]:
            if case.case_id in used:
                continue
            selected.append(case)
            used.add(case.case_id)
    return selected


def _candidate_cases_for_pattern(
    domain: str,
    pattern: str,
    query_specs: Sequence[tuple[str, tuple[str, ...]]],
    *,
    seed: str,
) -> list[_DomainCase]:
    cases: list[_DomainCase] = []
    for index, (query_text, required_ids) in enumerate(query_specs):
        if len(required_ids) < 2:
            continue
        descriptor = {
            "domain": domain,
            "pattern": pattern,
            "query_text": query_text,
            "required_ids": required_ids[:2],
            "index": index,
        }
        cases.append(
            _DomainCase(
                case_id="maildomaincase_" + sha256_json({"seed": seed, **descriptor})[-24:],
                domain=domain,
                intent_kind=f"{domain}_{pattern}",
                pattern=pattern,
                result_kind="owner_match",
                query_text=query_text,
                requester_user_id=ACTOR_USER_ID,
                required_source_observation_ids=required_ids[:2],
                required_match_count=2,
                limit=10,
            )
        )
    unique: dict[str, _DomainCase] = {}
    for case in cases:
        unique.setdefault(case.case_id, case)
    return list(unique.values())


def _multi_message_queries(
    domain: str,
    *,
    segments: Sequence[_SegmentInfo],
    token_sources: Mapping[str, tuple[str, ...]],
) -> list[tuple[str, tuple[str, ...]]]:
    del token_sources
    domain_tokens = DOMAIN_VOCABULARY[domain]
    specs: list[tuple[str, tuple[str, ...]]] = []
    for token in sorted(domain_tokens):
        matching_segments = [segment for segment in segments if token in segment.tokens]
        source_ids = _distinct_message_source_ids(matching_segments)
        if len(source_ids) >= 2:
            specs.append(
                (
                    (
                        f"Piece together separate-email {_domain_label(domain)} updates "
                        f"about {token}."
                    ),
                    source_ids[:2],
                )
            )
    return specs


def _actor_topic_queries(
    domain: str,
    *,
    segments: Sequence[_SegmentInfo],
) -> list[tuple[str, tuple[str, ...]]]:
    domain_tokens = DOMAIN_VOCABULARY[domain]
    grouped: dict[tuple[str, str], list[_SegmentInfo]] = {}
    for segment in segments:
        matched_domain_tokens = sorted(segment.tokens & domain_tokens)
        if not matched_domain_tokens:
            continue
        for sender_token in sorted(segment.sender_tokens):
            if "@" in sender_token or "." in sender_token:
                continue
            for domain_token in matched_domain_tokens:
                grouped.setdefault((sender_token, domain_token), []).append(segment)
    specs: list[tuple[str, tuple[str, ...]]] = []
    for (sender_token, domain_token), grouped_segments in sorted(grouped.items()):
        source_ids = _distinct_message_source_ids(grouped_segments)
        if len(source_ids) >= 2:
            specs.append(
                (
                    (
                        f"What did {sender_token} say across multiple emails about "
                        f"{_domain_label(domain)} {domain_token}?"
                    ),
                    source_ids[:2],
                )
            )
    return specs


def _chronology_queries(
    domain: str,
    *,
    segments: Sequence[_SegmentInfo],
    token_sources: Mapping[str, tuple[str, ...]],
) -> list[tuple[str, tuple[str, ...]]]:
    by_id = {segment.source_observation_id: segment for segment in segments}
    specs: list[tuple[str, tuple[str, ...]]] = []
    for token in sorted(DOMAIN_VOCABULARY[domain]):
        source_ids = token_sources.get(token, ())
        dated = [
            by_id[source_id]
            for source_id in source_ids
            if source_id in by_id and by_id[source_id].sent_at
        ]
        if len(dated) >= 2:
            ordered = sorted(
                dated, key=lambda item: (str(item.sent_at), item.source_observation_id)
            )
            pair = _chronology_source_pair(ordered)
            if len(pair) >= 2:
                specs.append(
                    (
                        (
                            f"Compare the earliest and latest {_domain_label(domain)} "
                            f"emails that mention {token}."
                        ),
                        pair[:2],
                    )
                )
    return specs


def _conflict_queries(
    domain: str,
    *,
    segments: Sequence[_SegmentInfo],
) -> list[tuple[str, tuple[str, ...]]]:
    domain_tokens = DOMAIN_VOCABULARY[domain]
    grouped: dict[tuple[str, str], list[_SegmentInfo]] = {}
    domain_pair_grouped: dict[tuple[str, str], list[_SegmentInfo]] = {}
    for segment in segments:
        domain_hits = sorted(segment.tokens & domain_tokens)
        conflict_hits = sorted(segment.tokens & CONFLICT_TERMS)
        for domain_token in domain_hits:
            for conflict_token in conflict_hits:
                if domain_token == conflict_token:
                    continue
                grouped.setdefault((domain_token, conflict_token), []).append(segment)
        for index, first_token in enumerate(domain_hits):
            for second_token in domain_hits[index + 1 :]:
                domain_pair_grouped.setdefault((first_token, second_token), []).append(segment)
    specs: list[tuple[str, tuple[str, ...]]] = []
    for (domain_token, conflict_token), grouped_segments in sorted(grouped.items()):
        source_ids = _distinct_message_source_ids(grouped_segments)
        if len(source_ids) >= 2:
            specs.append(
                (
                    (
                        f"Find conflicting {_domain_label(domain)} evidence involving "
                        f"{domain_token} and {conflict_token}."
                    ),
                    source_ids[:2],
                )
            )
    for (first_token, second_token), grouped_segments in sorted(domain_pair_grouped.items()):
        source_ids = _distinct_message_source_ids(grouped_segments)
        if len(source_ids) >= 2:
            specs.append(
                (
                    (
                        f"Find possible {_domain_label(domain)} tension between "
                        f"{first_token} and {second_token} across separate emails."
                    ),
                    source_ids[:2],
                )
            )
    return specs


def _negative_domain_cases(
    domain: str,
    source_case: _DomainCase,
    *,
    seed: str,
) -> list[_DomainCase]:
    no_match_query = (
        f"Find the final approved {_domain_label(domain)} decision and reconcile it "
        f"with the related mail thread evidence."
    )
    no_match = _DomainCase(
        case_id="maildomaincase_" + sha256_json({"seed": seed, "no_match": domain})[-24:],
        domain=domain,
        intent_kind=f"{domain}_no_match",
        pattern="no_match",
        result_kind="no_match",
        query_text=no_match_query,
        requester_user_id=ACTOR_USER_ID,
        required_source_observation_ids=(),
        required_match_count=0,
        limit=10,
    )
    denied = _DomainCase(
        case_id="maildomaincase_"
        + sha256_json({"seed": seed, "permission_denied": domain, "source": source_case.case_id})[
            -24:
        ],
        domain=domain,
        intent_kind=f"{domain}_permission_denied",
        pattern="permission_denied",
        result_kind="permission_denied",
        query_text=source_case.query_text,
        requester_user_id=DENIED_USER_ID,
        required_source_observation_ids=(),
        required_match_count=0,
        limit=10,
    )
    return [no_match, denied]


def _domain_label(domain: str) -> str:
    return domain.replace("_", " ")


def _distinct_message_source_ids(segments: Sequence[_SegmentInfo]) -> tuple[str, ...]:
    selected: list[str] = []
    seen_messages: set[str] = set()
    for segment in sorted(
        segments,
        key=lambda item: (
            str(item.sent_at or ""),
            item.email_message_id,
            item.source_observation_id,
        ),
    ):
        if segment.email_message_id in seen_messages:
            continue
        seen_messages.add(segment.email_message_id)
        selected.append(segment.source_observation_id)
        if len(selected) >= 2:
            break
    return tuple(selected)


def _chronology_source_pair(segments: Sequence[_SegmentInfo]) -> tuple[str, ...]:
    if not segments:
        return ()
    first = segments[0]
    for latest in reversed(segments):
        if latest.email_message_id != first.email_message_id:
            return (first.source_observation_id, latest.source_observation_id)
    return ()


def _segment_infos(bundle: MailEvidenceBundle) -> list[_SegmentInfo]:
    messages_by_id = {message.email_message_id: message for message in bundle.messages}
    segments: list[_SegmentInfo] = []
    for body_segment in bundle.body_segments:
        message = messages_by_id.get(body_segment.email_message_id)
        if message is None:
            continue
        searchable = " ".join(
            item
            for item in (
                body_segment.text,
                message.subject,
                message.sender,
                message.normalized_subject,
            )
            if isinstance(item, str)
        )
        tokens = frozenset(baseline_eval._eligible_tokens(searchable))
        sender_tokens = frozenset(baseline_eval._eligible_tokens(message.sender or ""))
        if not tokens:
            continue
        segments.append(
            _SegmentInfo(
                source_observation_id=body_segment.source_observation_id,
                email_message_id=body_segment.email_message_id,
                sender=message.sender,
                sent_at=message.sent_at,
                tokens=tokens,
                sender_tokens=sender_tokens,
            )
        )
    return segments


def _token_sources(segments: Sequence[_SegmentInfo]) -> dict[str, tuple[str, ...]]:
    sources: dict[str, set[str]] = {}
    for segment in segments:
        for token in segment.tokens:
            sources.setdefault(token, set()).add(segment.source_observation_id)
    return {token: tuple(sorted(source_ids)) for token, source_ids in sources.items()}


def _rank_cases(cases: Sequence[_DomainCase], *, seed: str) -> list[_DomainCase]:
    return sorted(
        cases,
        key=lambda case: (
            case.domain,
            case.pattern,
            sha256_json({"seed": seed, "case": case.case_id}),
        ),
    )


def _score_domain_cases(
    bundle: MailEvidenceBundle,
    cases: Sequence[_DomainCase],
) -> tuple[list[_DomainScore], int, int]:
    setup_started = time.monotonic()
    query_runner = _DomainCaseQueryRunner(bundle)
    query_runner_setup_elapsed_ms = int((time.monotonic() - setup_started) * 1000)
    query_loop_started = time.monotonic()
    scores: list[_DomainScore] = []
    for case in cases:
        started = time.monotonic()
        response = query_runner.query(case)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        row, passed = _score_case_response(case, response, elapsed_ms=elapsed_ms)
        scores.append(_DomainScore(case=case, passed=passed, row=row))
    case_query_loop_elapsed_ms = int((time.monotonic() - query_loop_started) * 1000)
    return scores, query_runner_setup_elapsed_ms, case_query_loop_elapsed_ms


def _json_rpc_request_for_case(bundle: MailEvidenceBundle, case: _DomainCase) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": case.case_id,
        "method": "tools/call",
        "params": {
            "name": "query_mail_evidence",
            "arguments": {
                "query_text": case.query_text,
                "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
                "limit": case.limit,
            },
        },
    }


def _score_case_response(
    case: _DomainCase,
    response: Mapping[str, Any],
    *,
    elapsed_ms: int,
) -> tuple[dict[str, Any], bool]:
    payload = baseline_eval._tool_payload(response)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    evidence_snippets = data.get("evidence_snippets")
    citations = data.get("citations")
    warnings = data.get("warnings")
    redaction_counts = data.get("redaction_counts")
    if not isinstance(evidence_snippets, list):
        evidence_snippets = []
    if not isinstance(citations, list):
        citations = []
    if not isinstance(warnings, list):
        warnings = []
    if not isinstance(redaction_counts, dict):
        redaction_counts = {}
    cited_observations = {
        str(citation.get("source_observation_id"))
        for citation in citations
        if isinstance(citation, dict) and citation.get("source_observation_id")
    }
    required = set(case.required_source_observation_ids)
    forbidden = set(case.forbidden_source_observation_ids)
    matched_required = required & cited_observations
    matched_forbidden = forbidden & cited_observations
    visible_count = len(evidence_snippets)
    citation_count = len(citations)
    hidden_bundle_count = baseline_eval._safe_count(redaction_counts.get("hidden_bundles"))
    hidden_message_count = baseline_eval._safe_count(redaction_counts.get("hidden_messages"))
    data_status = str(data.get("status", "unknown"))
    if case.result_kind == "owner_match":
        passed = (
            data_status == "ok"
            and visible_count > 0
            and citation_count > 0
            and len(matched_required) >= case.required_match_count
            and len(required) >= 2
            and not matched_forbidden
            and hidden_bundle_count == 0
        )
    elif case.result_kind == "permission_denied":
        passed = (
            data_status == "permission_denied"
            and visible_count == 0
            and citation_count == 0
            and hidden_bundle_count > 0
            and hidden_message_count > 0
        )
    elif case.result_kind == "no_match":
        passed = (
            data_status == "ok"
            and visible_count == 0
            and citation_count == 0
            and hidden_bundle_count == 0
        )
    else:
        passed = False
    row = {
        "case_id_hash": sha256_json(case.case_id),
        "case_manifest_entry_hash": case.private_fingerprint(),
        "domain_hash": sha256_json(case.domain),
        "intent_kind_hash": sha256_json(case.intent_kind),
        "pattern_hash": sha256_json(case.pattern),
        "result_kind": case.result_kind,
        "status": "passed" if passed else "failed",
        "response_hash": _response_shape_hash(response),
        "visible_result_count": visible_count,
        "citation_count": citation_count,
        "hidden_bundle_count": hidden_bundle_count,
        "hidden_message_count": hidden_message_count,
        "required_evidence_count": len(required),
        "matched_required_evidence_count": len(matched_required),
        "forbidden_evidence_match_count": len(matched_forbidden),
        "warning_count": len(warnings),
        "elapsed_ms": elapsed_ms,
    }
    return row, passed


def _response_shape_hash(response: Mapping[str, Any]) -> str:
    payload = baseline_eval._tool_payload(response)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    evidence_snippets = data.get("evidence_snippets")
    citations = data.get("citations")
    redaction_counts = data.get("redaction_counts")
    warnings = data.get("warnings")
    return sha256_json(
        {
            "jsonrpc": response.get("jsonrpc"),
            "response_id_hash": sha256_json(str(response.get("id", ""))),
            "is_error": response.get("result", {}).get("isError")
            if isinstance(response.get("result"), dict)
            else None,
            "payload_status": payload.get("status"),
            "data_status": data.get("status"),
            "query_hash": data.get("query_hash"),
            "evidence_snippet_count": len(evidence_snippets)
            if isinstance(evidence_snippets, list)
            else 0,
            "citation_count": len(citations) if isinstance(citations, list) else 0,
            "hidden_bundles": redaction_counts.get("hidden_bundles")
            if isinstance(redaction_counts, dict)
            else None,
            "hidden_messages": redaction_counts.get("hidden_messages")
            if isinstance(redaction_counts, dict)
            else None,
            "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        }
    )


def _write_private_manifest(
    path: Path,
    *,
    bundle: MailEvidenceBundle,
    cases: Sequence[_DomainCase],
    archive_sha256: str,
    parser_version: str,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest_type": "mail_full_pst_domain_hard_case_manifest_private",
        "policy_version": CASE_POLICY_VERSION,
        "generated_at": NOW,
        "archive_sha256": archive_sha256,
        "parser_version": parser_version,
        "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
        "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        "case_count": len(cases),
        "cases": [case.to_private_dict() for case in cases],
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(rendered + "\n", encoding="utf-8")
    return sha256_json(payload)


def _stores(data_dir: Path, object_root: Path) -> _Stores:
    registry = StorageBackendRegistry(data_dir)
    registry.register_local_backend(
        object_root,
        workspace_scope=WORKSPACE_ID,
        storage_backend_id=STORAGE_BACKEND_ID,
    )
    return _Stores(
        upload_session_store=UploadSessionStore(data_dir),
        asset_store=AssetStore(data_dir),
        job_store=JobStore(data_dir),
        extractor_run_store=ExtractorRunStore(data_dir),
        observation_store=ObservationStore(data_dir),
        object_store=FileObjectStore(registry),
        audit_store=FileAuditLogStore(data_dir),
    )


def _aggregate_scores(case_rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    case_count = len(case_rows)
    passed = sum(1 for row in case_rows if row.get("status") == "passed")
    failed = sum(1 for row in case_rows if row.get("status") == "failed")
    return {
        "case_count": case_count,
        "scored_case_count": passed + failed,
        "passed_case_count": passed,
        "failed_case_count": failed,
        "pass_rate_basis_points": int((passed * 10000) / case_count) if case_count else 0,
    }


def _aggregate_consistent(aggregate: Mapping[str, int]) -> bool:
    return (
        aggregate.get("case_count") == CASE_COUNT
        and aggregate.get("scored_case_count") == CASE_COUNT
        and aggregate.get("passed_case_count", 0) + aggregate.get("failed_case_count", 0)
        == CASE_COUNT
    )


def _row_counts(case_rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in case_rows:
        value = str(row.get(key, "unknown"))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _passed_row_counts(case_rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    if key == "domain_hash":
        values = [sha256_json(domain) for domain in DOMAINS]
    elif key == "pattern_hash":
        values = [sha256_json(pattern) for pattern in PATTERNS]
    else:
        values = []
    counts = {value: 0 for value in values}
    for row in case_rows:
        if row.get("status") != "passed":
            continue
        value = str(row.get(key, "unknown"))
        if value in counts:
            counts[value] += 1
    return counts


def _each_domain_has_count(domain_counts: Mapping[str, int], expected: int) -> bool:
    return all(domain_counts.get(sha256_json(domain)) == expected for domain in DOMAINS)


def _each_domain_has_result_kind(
    case_rows: Sequence[Mapping[str, Any]],
    result_kind: str,
) -> bool:
    return all(
        any(
            row.get("domain_hash") == sha256_json(domain) and row.get("result_kind") == result_kind
            for row in case_rows
        )
        for domain in DOMAINS
    )


def _each_domain_has_positive_patterns(case_rows: Sequence[Mapping[str, Any]]) -> bool:
    positive_pattern_hashes = {
        sha256_json("multi_message"),
        sha256_json("actor_topic"),
        sha256_json("chronology"),
        sha256_json("conflict"),
    }
    return all(
        all(
            sum(
                1
                for row in case_rows
                if row.get("domain_hash") == sha256_json(domain)
                and row.get("result_kind") == "owner_match"
                and row.get("pattern_hash") == pattern_hash
            )
            == 2
            for pattern_hash in positive_pattern_hashes
        )
        for domain in DOMAINS
    )


def _permission_denied_cases_redacted(case_rows: Sequence[Mapping[str, Any]]) -> bool:
    denied = [row for row in case_rows if row.get("result_kind") == "permission_denied"]
    return len(denied) == len(DOMAINS) and all(
        row.get("status") == "passed"
        and row.get("visible_result_count") == 0
        and row.get("citation_count") == 0
        and isinstance(row.get("hidden_bundle_count"), int)
        and row.get("hidden_bundle_count") > 0
        for row in denied
    )


def _no_match_cases_non_leaking(case_rows: Sequence[Mapping[str, Any]]) -> bool:
    no_match = [row for row in case_rows if row.get("result_kind") == "no_match"]
    return len(no_match) == len(DOMAINS) and all(
        row.get("status") == "passed"
        and row.get("visible_result_count") == 0
        and row.get("citation_count") == 0
        and row.get("hidden_bundle_count") == 0
        for row in no_match
    )


def _domain_hard_baseline_completed(report: Mapping[str, Any]) -> bool:
    metrics = report.get("metrics") if isinstance(report, dict) else {}
    return isinstance(metrics, dict) and all(
        value is True
        for key, value in metrics.items()
        if key not in _MEASURED_CASE_QUALITY_METRICS
        and key != "domain_hard_case_baseline_completed"
    )


def validate_report(report: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, dict):
        return _validation(False, ["report must be an object"])
    _validate_exact_keys(report, _TOP_LEVEL_KEYS, "report", blockers, allowed_extra={"validation"})
    if report.get("report_type") != REPORT_TYPE:
        blockers.append("report_type mismatch")
    if report.get("generated_at") != NOW:
        blockers.append("generated_at does not match this evaluator version")
    metrics = _dict_or_empty(report.get("metrics"), "metrics", blockers)
    safe_outputs = _dict_or_empty(report.get("safe_outputs"), "safe_outputs", blockers)
    claim_boundary = _dict_or_empty(report.get("claim_boundary"), "claim_boundary", blockers)
    if metrics.get("blocked_reason"):
        _validate_blocked_report(metrics, safe_outputs, claim_boundary, blockers)
    else:
        _validate_success_metrics(metrics, blockers)
        _validate_success_safe_outputs(safe_outputs, blockers)
        _validate_success_claim_boundary(claim_boundary, metrics, blockers)
    if "validation" in report:
        _validate_embedded_validation(report["validation"], report, blockers)
    _reject_body_or_evidence_text_fields(report, blockers)
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(report, "mail_full_pst_domain_hard_case_eval_report")
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    if not _public_outputs_are_safe(report):
        blockers.append("public report leaks raw or private mail-evaluation artifacts")
    return _validation(not blockers, blockers, report=report)


def _validate_success_metrics(metrics: Mapping[str, Any], blockers: list[str]) -> None:
    _validate_exact_keys(metrics, _REQUIRED_SUCCESS_METRICS, "metrics", blockers)
    for key in _REQUIRED_SUCCESS_METRICS:
        if key in _MEASURED_CASE_QUALITY_METRICS:
            if type(metrics.get(key)) is not bool:
                blockers.append(f"measured metric is not boolean: {key}")
            continue
        if metrics.get(key) is not True:
            blockers.append(f"required metric is not true: {key}")


def _validate_success_safe_outputs(
    safe_outputs: Mapping[str, Any],
    blockers: list[str],
) -> None:
    expected = {
        "fixture_id_hash",
        "fixture_sha256",
        "fixture_size_bytes",
        "full_parse_executed",
        "sample_message_limit",
        "sampling_config_used",
        "parser_adapter_contract_hash",
        "parser_version_hash",
        "extraction_config_shape_hash",
        "asset_count",
        "job_count",
        "extractor_run_count",
        "observation_count",
        "message_count",
        "folder_occurrence_count",
        "body_segment_count",
        "attachment_occurrence_count",
        "parse_warning_count",
        "parse_warning_codes_hash",
        "mail_evidence_table_count",
        "mail_evidence_row_count",
        "mail_evidence_statement_count",
        "parser_worker_count",
        "case_policy_hash",
        "case_manifest_hash",
        "case_result_hash",
        "private_manifest_hash",
        "private_manifest_case_count",
        "private_manifest_write_elapsed_ms",
        "fixture_hash_elapsed_ms",
        "upload_elapsed_ms",
        "import_elapsed_ms",
        "bundle_read_elapsed_ms",
        "case_manifest_elapsed_ms",
        "scoring_elapsed_ms",
        "query_runner_setup_elapsed_ms",
        "case_query_loop_elapsed_ms",
        "case_count",
        "scored_case_count",
        "passed_case_count",
        "failed_case_count",
        "pass_rate_basis_points",
        "positive_case_count",
        "permission_denied_case_count",
        "no_match_case_count",
        "unique_case_id_hash_count",
        "unique_response_hash_count",
        "duplicate_response_hash_count",
        "domain_hash_counts",
        "domain_hash_passed_counts",
        "pattern_hash_counts",
        "pattern_hash_passed_counts",
        "result_kind_counts",
        "case_rows",
        "artifact_retained_entry_count",
        "artifact_retained_size_bytes",
        "staging_leftover_count",
        "scratch_leftover_count",
        "staging_retained_entry_count",
        "staging_retained_size_bytes",
        "scratch_retained_entry_count",
        "scratch_retained_size_bytes",
        "work_dir_cleaned",
    }
    _validate_exact_keys(safe_outputs, expected, "safe_outputs", blockers)
    for key in (
        "fixture_id_hash",
        "fixture_sha256",
        "parser_adapter_contract_hash",
        "parser_version_hash",
        "extraction_config_shape_hash",
        "parse_warning_codes_hash",
        "case_policy_hash",
        "case_manifest_hash",
        "case_result_hash",
        "private_manifest_hash",
    ):
        _require_sha256(safe_outputs.get(key), f"safe_outputs.{key}", blockers)
    exact_counts = {
        "sample_message_limit": 0,
        "asset_count": 1,
        "job_count": 1,
        "extractor_run_count": 1,
        "case_count": CASE_COUNT,
        "scored_case_count": CASE_COUNT,
        "private_manifest_case_count": CASE_COUNT,
        "positive_case_count": 80,
        "permission_denied_case_count": len(DOMAINS),
        "no_match_case_count": len(DOMAINS),
        "unique_case_id_hash_count": CASE_COUNT,
        "unique_response_hash_count": CASE_COUNT,
        "duplicate_response_hash_count": 0,
    }
    for key, expected_value in exact_counts.items():
        value = safe_outputs.get(key)
        if type(value) is not int or value != expected_value:
            blockers.append(f"safe_outputs.{key} must be {expected_value}")
    for key in (
        "fixture_size_bytes",
        "observation_count",
        "message_count",
        "folder_occurrence_count",
        "body_segment_count",
        "mail_evidence_table_count",
        "mail_evidence_row_count",
        "mail_evidence_statement_count",
        "parser_worker_count",
        "fixture_hash_elapsed_ms",
        "upload_elapsed_ms",
        "import_elapsed_ms",
        "case_manifest_elapsed_ms",
        "scoring_elapsed_ms",
    ):
        value = safe_outputs.get(key)
        if type(value) is not int or value <= 0:
            blockers.append(f"safe_outputs.{key} must be a positive integer")
    for key in (
        "attachment_occurrence_count",
        "parse_warning_count",
        "private_manifest_write_elapsed_ms",
        "bundle_read_elapsed_ms",
        "query_runner_setup_elapsed_ms",
        "case_query_loop_elapsed_ms",
        "artifact_retained_entry_count",
        "artifact_retained_size_bytes",
        "staging_leftover_count",
        "scratch_leftover_count",
        "staging_retained_entry_count",
        "staging_retained_size_bytes",
        "scratch_retained_entry_count",
        "scratch_retained_size_bytes",
    ):
        value = safe_outputs.get(key)
        if type(value) is not int or value < 0:
            blockers.append(f"safe_outputs.{key} must be a non-negative integer")
    if safe_outputs.get("full_parse_executed") is not True:
        blockers.append("safe_outputs.full_parse_executed must be true")
    if safe_outputs.get("sampling_config_used") is not False:
        blockers.append("safe_outputs.sampling_config_used must be false")
    if type(safe_outputs.get("work_dir_cleaned")) is not bool:
        blockers.append("safe_outputs.work_dir_cleaned must be boolean")
    passed = safe_outputs.get("passed_case_count")
    failed = safe_outputs.get("failed_case_count")
    if type(passed) is not int or passed < 0 or passed > CASE_COUNT:
        blockers.append("safe_outputs.passed_case_count must be 0..100")
    if type(failed) is not int or failed < 0 or failed > CASE_COUNT:
        blockers.append("safe_outputs.failed_case_count must be 0..100")
    if type(passed) is int and type(failed) is int and passed + failed != CASE_COUNT:
        blockers.append("safe_outputs passed/failed counts must sum to 100")
    rate = safe_outputs.get("pass_rate_basis_points")
    if type(rate) is not int or rate < 0 or rate > 10000:
        blockers.append("safe_outputs.pass_rate_basis_points must be 0..10000")
    _validate_domain_pattern_counts(safe_outputs, blockers)
    _validate_case_rows(safe_outputs.get("case_rows"), blockers)
    _validate_row_derived_bindings(safe_outputs, blockers)


def _validate_domain_pattern_counts(
    safe_outputs: Mapping[str, Any],
    blockers: list[str],
) -> None:
    domain_counts = _dict_or_empty(
        safe_outputs.get("domain_hash_counts"), "domain_hash_counts", blockers
    )
    domain_passed = _dict_or_empty(
        safe_outputs.get("domain_hash_passed_counts"), "domain_hash_passed_counts", blockers
    )
    pattern_counts = _dict_or_empty(
        safe_outputs.get("pattern_hash_counts"), "pattern_hash_counts", blockers
    )
    pattern_passed = _dict_or_empty(
        safe_outputs.get("pattern_hash_passed_counts"), "pattern_hash_passed_counts", blockers
    )
    result_kind_counts = _dict_or_empty(
        safe_outputs.get("result_kind_counts"), "result_kind_counts", blockers
    )
    domain_hashes = {sha256_json(domain) for domain in DOMAINS}
    pattern_hashes = {sha256_json(pattern) for pattern in PATTERNS}
    if set(domain_counts) != domain_hashes:
        blockers.append("safe_outputs.domain_hash_counts must contain exactly configured hashes")
    if set(domain_passed) != domain_hashes:
        blockers.append(
            "safe_outputs.domain_hash_passed_counts must contain exactly configured hashes"
        )
    if set(pattern_counts) != pattern_hashes:
        blockers.append("safe_outputs.pattern_hash_counts must contain exactly configured hashes")
    if set(pattern_passed) != pattern_hashes:
        blockers.append(
            "safe_outputs.pattern_hash_passed_counts must contain exactly configured hashes"
        )
    if set(result_kind_counts) != set(RESULT_KINDS):
        blockers.append("safe_outputs.result_kind_counts must contain exactly the result kinds")
    for domain_hash in domain_hashes:
        if domain_counts.get(domain_hash) != DOMAIN_CASE_COUNT:
            blockers.append("safe_outputs.domain_hash_counts configured item must be 10")
    for pattern_hash in pattern_hashes:
        item = pattern_counts.get(pattern_hash)
        if type(item) is not int or item <= 0:
            blockers.append("safe_outputs.pattern_hash_counts configured item must be positive")
    for context, value in (
        ("domain_hash_counts", domain_counts),
        ("domain_hash_passed_counts", domain_passed),
        ("pattern_hash_counts", pattern_counts),
        ("pattern_hash_passed_counts", pattern_passed),
        ("result_kind_counts", result_kind_counts),
    ):
        for item in value.values():
            if type(item) is not int or item < 0:
                blockers.append(f"safe_outputs.{context} values must be non-negative integers")
    if sum(item for item in domain_counts.values() if type(item) is int) != CASE_COUNT:
        blockers.append("safe_outputs.domain_hash_counts must sum to 100")
    if sum(item for item in pattern_counts.values() if type(item) is int) != CASE_COUNT:
        blockers.append("safe_outputs.pattern_hash_counts must sum to 100")
    if sum(item for item in result_kind_counts.values() if type(item) is int) != CASE_COUNT:
        blockers.append("safe_outputs.result_kind_counts must sum to 100")


def _validate_case_rows(value: Any, blockers: list[str]) -> None:
    if not isinstance(value, list):
        blockers.append("safe_outputs.case_rows must be a list")
        return
    if len(value) != CASE_COUNT:
        blockers.append("safe_outputs.case_rows must contain 100 rows")
        return
    case_hashes: set[str] = set()
    response_hashes: set[str] = set()
    row_passed = 0
    row_failed = 0
    for row in value:
        if not isinstance(row, dict):
            blockers.append("case row must be an object")
            return
        expected_keys = {
            "case_id_hash",
            "case_manifest_entry_hash",
            "domain_hash",
            "intent_kind_hash",
            "pattern_hash",
            "result_kind",
            "status",
            "response_hash",
            "visible_result_count",
            "citation_count",
            "hidden_bundle_count",
            "hidden_message_count",
            "required_evidence_count",
            "matched_required_evidence_count",
            "forbidden_evidence_match_count",
            "warning_count",
            "elapsed_ms",
        }
        _validate_exact_keys(row, expected_keys, "case_row", blockers)
        for key in (
            "case_id_hash",
            "case_manifest_entry_hash",
            "domain_hash",
            "intent_kind_hash",
            "pattern_hash",
            "response_hash",
        ):
            _require_sha256(row.get(key), f"case_row.{key}", blockers)
        if row.get("domain_hash") not in {sha256_json(domain) for domain in DOMAINS}:
            blockers.append("case_row.domain_hash is invalid")
        if row.get("pattern_hash") not in {sha256_json(pattern) for pattern in PATTERNS}:
            blockers.append("case_row.pattern_hash is invalid")
        if row.get("result_kind") not in RESULT_KINDS:
            blockers.append("case_row.result_kind is invalid")
        status = row.get("status")
        if status not in {"passed", "failed"}:
            blockers.append("case_row.status is invalid")
        if status == "passed":
            row_passed += 1
        if status == "failed":
            row_failed += 1
        for key in (
            "visible_result_count",
            "citation_count",
            "hidden_bundle_count",
            "hidden_message_count",
            "required_evidence_count",
            "matched_required_evidence_count",
            "forbidden_evidence_match_count",
            "warning_count",
            "elapsed_ms",
        ):
            item = row.get(key)
            if type(item) is not int or item < 0:
                blockers.append(f"case_row.{key} must be a non-negative integer")
        if status == "passed" and row.get("result_kind") == "owner_match":
            if row.get("visible_result_count", 0) <= 0 or row.get("citation_count", 0) <= 0:
                blockers.append("passed owner_match case must have visible evidence and citation")
        if row.get("result_kind") == "owner_match":
            if row.get("required_evidence_count", 0) < 2:
                blockers.append("owner_match case must require at least two evidence items")
        if status == "passed" and row.get("result_kind") == "owner_match":
            if row.get("matched_required_evidence_count", 0) < 2:
                blockers.append("passed owner_match case must match at least two evidence items")
            if row.get("hidden_bundle_count") != 0:
                blockers.append("passed owner_match case must not hide bundles")
        if status == "passed" and row.get("result_kind") == "permission_denied":
            if row.get("visible_result_count") != 0 or row.get("citation_count") != 0:
                blockers.append("passed permission_denied case must expose no evidence")
            if row.get("hidden_bundle_count", 0) <= 0 or row.get("hidden_message_count", 0) <= 0:
                blockers.append("passed permission_denied case must report hidden counts")
        if status == "passed" and row.get("result_kind") == "no_match":
            if row.get("visible_result_count") != 0 or row.get("citation_count") != 0:
                blockers.append("passed no_match case must expose no evidence")
            if row.get("hidden_bundle_count") != 0:
                blockers.append("passed no_match case must not hide bundles")
        if row.get("forbidden_evidence_match_count") != 0:
            blockers.append("case_row.forbidden_evidence_match_count must be 0")
        if isinstance(row.get("case_id_hash"), str):
            case_hashes.add(row["case_id_hash"])
        if isinstance(row.get("response_hash"), str):
            response_hashes.add(row["response_hash"])
    if len(case_hashes) != CASE_COUNT:
        blockers.append("case rows must contain 100 unique case hashes")
    if len(response_hashes) != CASE_COUNT:
        blockers.append("case rows must contain 100 unique response hashes")
    if row_passed + row_failed != CASE_COUNT:
        blockers.append("case row pass/fail totals must sum to 100")
    _validate_per_domain_pattern_distribution(value, blockers)


def _validate_per_domain_pattern_distribution(
    rows: Sequence[Mapping[str, Any]],
    blockers: list[str],
) -> None:
    positive_patterns = {
        "multi_message",
        "actor_topic",
        "chronology",
        "conflict",
    }
    for domain in DOMAINS:
        domain_hash = sha256_json(domain)
        domain_rows = [row for row in rows if row.get("domain_hash") == domain_hash]
        if len(domain_rows) != DOMAIN_CASE_COUNT:
            blockers.append("case rows must contain exactly 10 rows per configured domain")
            continue
        for pattern in positive_patterns:
            pattern_hash = sha256_json(pattern)
            count = sum(
                1
                for row in domain_rows
                if row.get("result_kind") == "owner_match"
                and row.get("pattern_hash") == pattern_hash
            )
            if count != 2:
                blockers.append(
                    "case rows must contain two owner_match rows per positive pattern per domain"
                )
        if (
            sum(1 for row in domain_rows if row.get("result_kind") == "no_match") != 1
            or sum(1 for row in domain_rows if row.get("result_kind") == "permission_denied") != 1
        ):
            blockers.append(
                "case rows must contain one no_match and one permission_denied row per domain"
            )


def _validate_row_derived_bindings(
    safe_outputs: Mapping[str, Any],
    blockers: list[str],
) -> None:
    rows = safe_outputs.get("case_rows")
    if (
        not isinstance(rows, list)
        or len(rows) != CASE_COUNT
        or any(not isinstance(row, dict) for row in rows)
    ):
        return
    aggregate = _aggregate_scores(rows)
    for key in (
        "case_count",
        "scored_case_count",
        "passed_case_count",
        "failed_case_count",
        "pass_rate_basis_points",
    ):
        if safe_outputs.get(key) != aggregate[key]:
            blockers.append(f"safe_outputs.{key} does not match case rows")
    case_hashes = {
        row.get("case_id_hash") for row in rows if isinstance(row.get("case_id_hash"), str)
    }
    response_hashes = [
        row.get("response_hash") for row in rows if isinstance(row.get("response_hash"), str)
    ]
    duplicate_response_count = len(response_hashes) - len(set(response_hashes))
    derived = {
        "unique_case_id_hash_count": len(case_hashes),
        "unique_response_hash_count": len(set(response_hashes)),
        "duplicate_response_hash_count": duplicate_response_count,
        "positive_case_count": sum(1 for row in rows if row.get("result_kind") == "owner_match"),
        "permission_denied_case_count": sum(
            1 for row in rows if row.get("result_kind") == "permission_denied"
        ),
        "no_match_case_count": sum(1 for row in rows if row.get("result_kind") == "no_match"),
    }
    for key, expected_value in derived.items():
        if safe_outputs.get(key) != expected_value:
            blockers.append(f"safe_outputs.{key} does not match case rows")
    for key in ("domain_hash", "pattern_hash", "result_kind"):
        target = f"{key}_counts" if key != "result_kind" else "result_kind_counts"
        if safe_outputs.get(target) != _row_counts(rows, key):
            blockers.append(f"safe_outputs.{target} does not match case rows")
    if safe_outputs.get("domain_hash_passed_counts") != _passed_row_counts(rows, "domain_hash"):
        blockers.append("safe_outputs.domain_hash_passed_counts does not match case rows")
    if safe_outputs.get("pattern_hash_passed_counts") != _passed_row_counts(rows, "pattern_hash"):
        blockers.append("safe_outputs.pattern_hash_passed_counts does not match case rows")
    expected_manifest_hash = sha256_json([row.get("case_manifest_entry_hash") for row in rows])
    if safe_outputs.get("case_manifest_hash") != expected_manifest_hash:
        blockers.append("safe_outputs.case_manifest_hash does not match case rows")
    if safe_outputs.get("case_result_hash") != sha256_json(rows):
        blockers.append("safe_outputs.case_result_hash does not match case rows")


def _validate_success_claim_boundary(
    claim_boundary: Mapping[str, Any],
    metrics: Mapping[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_operator_provided_full_pst_domain_hard_baseline_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_keys, "claim_boundary", blockers)
    expected_support = metrics.get("domain_hard_case_baseline_completed") is True
    if (
        claim_boundary.get("supports_operator_provided_full_pst_domain_hard_baseline_claim")
        is not expected_support
    ):
        blockers.append("operator-provided hard-domain baseline claim boundary mismatch")
    for key in _FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(key) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {key}")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")


def _validate_blocked_report(
    metrics: Mapping[str, Any],
    safe_outputs: Mapping[str, Any],
    claim_boundary: Mapping[str, Any],
    blockers: list[str],
) -> None:
    _validate_exact_keys(
        metrics,
        {"blocked_reason", "domain_hard_case_baseline_completed", "raw_leak_guard_passed"},
        "metrics",
        blockers,
    )
    if metrics.get("blocked_reason") not in BLOCKED_REASONS:
        blockers.append("blocked_reason must be a configured safe enum")
    if metrics.get("domain_hard_case_baseline_completed") is not False:
        blockers.append("blocked report must not pass")
    if metrics.get("raw_leak_guard_passed") is not True:
        blockers.append("blocked report raw leak guard must be true")
    _validate_exact_keys(
        safe_outputs,
        {"blocker_hash", "case_count", "full_parse_executed", "work_dir_cleaned"},
        "safe_outputs",
        blockers,
    )
    _require_sha256(safe_outputs.get("blocker_hash"), "safe_outputs.blocker_hash", blockers)
    if type(safe_outputs.get("case_count")) is not int or safe_outputs.get("case_count") != 0:
        blockers.append("blocked report case_count must be 0")
    if safe_outputs.get("full_parse_executed") is not False:
        blockers.append("blocked report must not execute full parse")
    if type(safe_outputs.get("work_dir_cleaned")) is not bool:
        blockers.append("blocked report work_dir_cleaned must be boolean")
    expected_claim_keys = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_operator_provided_full_pst_domain_hard_baseline_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_claim_keys, "claim_boundary", blockers)
    for key, value in claim_boundary.items():
        if key == "container_verification_required":
            if value is not True:
                blockers.append("container_verification_required must be true")
        elif value is not False:
            blockers.append("blocked report claims must be false")


def _validate_embedded_validation(
    value: Any,
    report: Mapping[str, Any],
    blockers: list[str],
) -> None:
    validation = _dict_or_empty(value, "validation", blockers)
    _validate_exact_keys(
        validation, {"passed", "blockers", "claim_boundary"}, "validation", blockers
    )
    if validation.get("passed") is not True:
        blockers.append("validation.passed must be true")
    if validation.get("blockers") != []:
        blockers.append("validation.blockers must be empty")
    claim_boundary = _dict_or_empty(
        validation.get("claim_boundary"),
        "validation.claim_boundary",
        blockers,
    )
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_operator_provided_full_pst_domain_hard_baseline_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    metrics = report.get("metrics") if isinstance(report, dict) else {}
    expected = (
        isinstance(metrics, dict) and metrics.get("domain_hard_case_baseline_completed") is True
    )
    if (
        claim_boundary.get("supports_operator_provided_full_pst_domain_hard_baseline_claim")
        is not expected
    ):
        blockers.append("validation hard-domain baseline claim mismatch")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _blocked_report(error_code: str, *, work_dir_cleaned: bool) -> dict[str, Any]:
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": {
            "blocked_reason": error_code,
            "domain_hard_case_baseline_completed": False,
            "raw_leak_guard_passed": True,
        },
        "safe_outputs": {
            "blocker_hash": sha256_json(error_code),
            "case_count": 0,
            "full_parse_executed": False,
            "work_dir_cleaned": work_dir_cleaned,
        },
        "claim_boundary": _claim_boundary(False),
    }
    report["validation"] = validate_report(report)
    return report


def _claim_boundary(supports_eval: bool) -> dict[str, bool]:
    return {
        "supports_operator_provided_full_pst_domain_hard_baseline_claim": supports_eval,
        "supports_actual_chatgpt_connected_upload_claim": False,
        "supports_real_upload_iframe_claim": False,
        "supports_general_full_pst_parser_readiness_claim": False,
        "supports_live_postgresql_readiness_claim": False,
        "supports_production_worker_leasing_claim": False,
        "supports_business_answer_generation_claim": False,
        "supports_kg_write_claim": False,
        "supports_wiki_projection_claim": False,
        "supports_raw_mail_access_claim": False,
        "supports_production_ready_claim": False,
        "container_verification_required": True,
    }


def _validation(
    passed: bool,
    blockers: list[str],
    *,
    report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = report.get("metrics") if isinstance(report, dict) else {}
    supported = (
        passed
        and isinstance(metrics, dict)
        and (metrics.get("domain_hard_case_baseline_completed") is True)
    )
    return {
        "passed": passed,
        "blockers": blockers,
        "claim_boundary": {
            "supports_operator_provided_full_pst_domain_hard_baseline_claim": supported,
            "supports_production_ready_claim": False,
        },
    }


def _reject_body_or_evidence_text_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            parts = set(normalized.split("_"))
            if (
                {
                    "answer",
                    "attachment",
                    "body",
                    "content",
                    "message_id",
                    "observation_id",
                    "prompt",
                    "query",
                    "sender",
                    "snippet",
                    "subject",
                    "text",
                    "transcript",
                    "upload_session_id",
                }
                & parts
            ) and not _is_safe_metadata_key(normalized):
                offending_path = f"{path}.{key_text}" if path else key_text
                blockers.append(
                    "public report contains evidence field: " + sha256_json(offending_path)
                )
                return
            _reject_body_or_evidence_text_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_body_or_evidence_text_fields(item, blockers, f"{path}[{index}]")


def _is_safe_metadata_key(normalized_key: str) -> bool:
    explicit = {
        "supports_business_answer_generation_claim",
        "sample_message_limit",
        "required_evidence_count",
        "matched_required_evidence_count",
        "forbidden_evidence_match_count",
        "query_runner_setup_elapsed_ms",
        "case_query_loop_elapsed_ms",
    }
    if normalized_key in explicit:
        return True
    if normalized_key.startswith("supports_") and normalized_key.endswith("_claim"):
        return True
    return normalized_key.endswith(("_count", "_counts", "_hash", "_hashes", "_status", "_kind"))


def _public_outputs_are_safe(report: Mapping[str, Any]) -> bool:
    return public_outputs_are_safe(
        report,
        forbidden_fragments=(
            "archive.pst",
            "tests/pst-exm",
            "pst-exm",
            str(ROOT).lower(),
            "formowl://object",
            "payload.bin",
            "storage_backend_id",
            "traceback",
            "readpst",
            "pffexport",
            "pst-scratch",
            "formowl-pst-export",
            "query_text",
            "evidence_snippets",
            "source_observation_id",
            "email_message_id",
            "message_occurrence_id",
            PRIVATE_MANIFEST_NAME,
        ),
        raw_reference_context="mail_full_pst_domain_hard_case_eval_report",
    )


def _tree_stats(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    entry_count = 0
    size_bytes = 0
    try:
        for item in path.rglob("*"):
            entry_count += 1
            if item.is_file():
                size_bytes += item.stat().st_size
    except OSError:
        return entry_count, size_bytes
    return entry_count, size_bytes


def _cleanup(path: Path) -> bool:
    try:
        if not path.exists():
            return True
        if not path.is_dir() or not _work_dir_sentinel_is_valid(path):
            return False
        resolved = path.resolve()
        if resolved == resolved.parent:
            return False
        baseline_eval.shutil.rmtree(path)
        return not path.exists()
    except Exception:
        return False


def _prepare_work_dir(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise RuntimeError("unsafe_work_dir")
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()) and not _work_dir_sentinel_is_valid(path):
        raise RuntimeError("unsafe_work_dir")
    (path / WORK_DIR_SENTINEL_NAME).write_text(WORK_DIR_SENTINEL_VALUE + "\n", encoding="utf-8")


def _work_dir_sentinel_is_valid(path: Path) -> bool:
    sentinel = path / WORK_DIR_SENTINEL_NAME
    try:
        return sentinel.is_file() and sentinel.read_text(encoding="utf-8").strip() == (
            WORK_DIR_SENTINEL_VALUE
        )
    except OSError:
        return False


def _default_work_dir() -> Path:
    return ROOT / ".test-tmp" / f"formowl-mail-domain-hard-case-{uuid.uuid4().hex}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--pst-fixture", type=Path, default=DEFAULT_PST_FIXTURE)
    parser.add_argument("--cleanup-work-dir", action="store_true")
    parser.add_argument("--validate-report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.validate_report is not None:
        try:
            report = json.loads(args.validate_report.read_text(encoding="utf-8"))
        except Exception:
            validation = _validation(False, ["validate_report_input_unreadable"])
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
            return 1
        validation = validate_report(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
        return 0 if validation["passed"] else 1

    work_dir = args.work_dir or _default_work_dir()
    report = run_domain_hard_case_eval(
        work_dir,
        pst_fixture=args.pst_fixture,
        cleanup_work_dir=args.cleanup_work_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report.get("metrics", {}).get("domain_hard_case_baseline_completed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
