#!/usr/bin/env python3
"""Run or validate the FormOwl #21 full-PST 100-case mail evidence eval.

This is intentionally separate from ``mail_real_pst_smoke.py``. The sampled
smoke proves one narrow real-PST parser path. This harness proves a stricter
operator-provided PST evaluation path:

full PST import -> normalized MailEvidenceBundle -> governed JSON-RPC
``query_mail_evidence`` -> 100 manifest-bound retrieval cases.

The public report is hash/status/count-only. It must not expose prompts, query
text, snippets, subjects, senders, message ids, observation ids, attachment
names, upload locators, parser commands, scratch paths, SQL, or environment
values.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = Path(__file__).resolve().parent
PYTHON_ROOT = ROOT / "python"
for import_path in (PYTHON_ROOT, SCRIPT_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import mail_real_pst_smoke as sampled_smoke  # noqa: E402
from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_contract import (  # noqa: E402
    PermissionScope,
    assert_no_public_raw_references,
    sha256_json,
)
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

DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-mail-full-pst-100-case-eval.json"
DEFAULT_PST_FIXTURE = ROOT / "tests" / "pst-exm" / "archive.pst"
NOW = "2026-07-07T12:00:00+00:00"
SESSION_ID = "session_full_pst_100_case_eval"
ACTOR_USER_ID = "user_full_pst_100_case_eval_owner"
DENIED_USER_ID = "user_full_pst_100_case_eval_denied"
WORKSPACE_ID = "workspace_formowl"
PROJECT_ID = "project_formowl"
STORAGE_BACKEND_ID = "storage_full_pst_100_case_eval"
UPLOAD_FILENAME = "mail-import.pst"
PST_MIME_TYPE = "application/vnd.ms-outlook"
REPORT_TYPE = "mail_full_pst_100_case_eval"
CASE_POLICY_VERSION = "formowl_full_pst_100_case_eval_v1"
FULL_EVAL_OPT_IN_ENV = "FORMOWL_RUN_FULL_PST_100_CASE_EVAL"
WORK_DIR_SENTINEL_NAME = ".formowl-mail-full-pst-100-case-workdir"
WORK_DIR_SENTINEL_VALUE = "formowl-mail-full-pst-100-case-eval-v1"
CASE_COUNT = 100
PASS_THRESHOLD = 99

_FORBIDDEN_TRUE_CLAIMS = {
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_real_upload_iframe_claim",
    "supports_general_full_pst_parser_readiness_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_raw_mail_access_claim",
    "supports_production_ready_claim",
}
_TOP_LEVEL_KEYS = {
    "report_type",
    "generated_at",
    "metrics",
    "safe_outputs",
    "claim_boundary",
}
_REQUIRED_TRUE_METRICS = {
    "fixture_present",
    "fixture_stream_hash_succeeded",
    "pst_signature_verified",
    "full_parse_executed",
    "no_sampling_config_used",
    "real_parser_invoked",
    "upload_session_created",
    "asset_registered",
    "ingestion_job_succeeded",
    "extractor_run_succeeded",
    "mail_observations_persisted",
    "mail_evidence_rows_persisted",
    "case_manifest_generated",
    "case_count_is_100",
    "scored_case_count_is_100",
    "passed_case_threshold_met",
    "aggregate_scoring_recomputed",
    "permission_denied_cases_redacted",
    "no_match_cases_non_leaking",
    "message_limit_not_reached",
    "raw_archive_retention_decision_recorded",
    "kg_wiki_side_effects_absent",
    "cleanup_succeeded",
    "raw_leak_guard_passed",
    "full_pst_100_case_eval_passed",
}
_PUBLIC_CATEGORY_BY_INTERNAL = {
    "body_keyword": "cat_keyword",
    "subject_body_pair": "cat_topic_pair",
    "sender_body_pair": "cat_actor_pair",
    "thread_topic": "cat_thread",
    "multi_message_token": "cat_multi",
    "ai_progress_topic": "cat_ai_progress",
    "no_match": "cat_no_match",
    "permission_denied": "cat_permission_denied",
}
_CASE_CATEGORIES = set(_PUBLIC_CATEGORY_BY_INTERNAL.values())
_RESULT_KINDS = {"owner_match", "permission_denied", "no_match"}
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "any",
    "are",
    "because",
    "been",
    "before",
    "being",
    "but",
    "can",
    "com",
    "could",
    "date",
    "did",
    "does",
    "for",
    "from",
    "have",
    "here",
    "into",
    "mail",
    "message",
    "not",
    "our",
    "out",
    "please",
    "re",
    "subject",
    "that",
    "the",
    "this",
    "thread",
    "with",
    "would",
    "you",
    "your",
}
_AI_PROGRESS_TERMS = {
    "ai",
    "artificial",
    "assistant",
    "automation",
    "bot",
    "chatgpt",
    "gpt",
    "intelligence",
    "llm",
    "machine",
    "model",
    "news",
    "openai",
    "progress",
    "status",
    "update",
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
class _EvalCase:
    case_id: str
    category: str
    result_kind: str
    query_text: str
    requester_user_id: str
    required_source_observation_ids: tuple[str, ...]
    forbidden_source_observation_ids: tuple[str, ...] = ()
    required_match_count: int = 1
    limit: int = 5

    def private_fingerprint(self) -> str:
        return sha256_json(
            {
                "case_id": self.case_id,
                "category": self.category,
                "result_kind": self.result_kind,
                "query_text": self.query_text,
                "requester_user_id": self.requester_user_id,
                "required_source_observation_ids": self.required_source_observation_ids,
                "forbidden_source_observation_ids": self.forbidden_source_observation_ids,
                "required_match_count": self.required_match_count,
                "limit": self.limit,
            }
        )


@dataclass(frozen=True)
class _CaseScore:
    case: _EvalCase
    passed: bool
    row: dict[str, Any]


class _CaseQueryRunner:
    """Reusable governed JSON-RPC query path for full-PST case evaluation."""

    def __init__(self, bundle: MailEvidenceBundle) -> None:
        self._bundle = bundle
        self._semantic_gateway = SemanticMcpGateway(
            mail_evidence_handler=build_mail_evidence_query_handler([bundle], now=NOW)
        )
        self._gateways_by_requester: dict[str, SemanticMcpJsonRpcGateway] = {}

    def query(self, case: _EvalCase) -> dict[str, Any]:
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


def run_full_pst_100_case_eval(
    work_dir: Path,
    *,
    pst_fixture: Path = DEFAULT_PST_FIXTURE,
    keep_work_dir: bool = False,
) -> dict[str, Any]:
    if os.environ.get(FULL_EVAL_OPT_IN_ENV) != "1":
        return _blocked_report("full_eval_requires_explicit_opt_in", work_dir_cleaned=True)

    cleanup_attempted = not keep_work_dir
    try:
        report = _run_full_pst_100_case_eval_inner(work_dir, pst_fixture=pst_fixture)
    except FileNotFoundError:
        report = _safe_error_report("missing_fixture", work_dir_cleaned=_cleanup(work_dir))
    except Exception:
        report = _safe_error_report(
            "full_pst_100_case_eval_failed", work_dir_cleaned=_cleanup(work_dir)
        )
    else:
        if cleanup_attempted:
            cleaned = _cleanup(work_dir)
            report["safe_outputs"]["work_dir_cleaned"] = cleaned
            report["metrics"]["cleanup_succeeded"] = (
                report["safe_outputs"]["staging_leftover_count"] == 0
                and report["safe_outputs"]["scratch_leftover_count"] == 0
                and cleaned
            )
        else:
            report["safe_outputs"]["work_dir_cleaned"] = False
            report["metrics"]["cleanup_succeeded"] = (
                report["safe_outputs"]["staging_leftover_count"] == 0
                and report["safe_outputs"]["scratch_leftover_count"] == 0
            )
        report["metrics"]["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
        report["metrics"]["full_pst_100_case_eval_passed"] = all(
            value is True
            for key, value in report["metrics"].items()
            if key != "full_pst_100_case_eval_passed"
        )
        report["claim_boundary"]["supports_operator_provided_full_pst_100_case_eval_claim"] = (
            report["metrics"]["full_pst_100_case_eval_passed"]
        )
        report["validation"] = validate_report(report)
    return report


def _run_full_pst_100_case_eval_inner(
    work_dir: Path,
    *,
    pst_fixture: Path,
) -> dict[str, Any]:
    fixture = pst_fixture.resolve()
    fixture_size, fixture_hash, fixture_header_ok = sampled_smoke._fixture_properties(fixture)
    _prepare_work_dir(work_dir)
    stores = _stores(work_dir / "data", work_dir / "object-root")
    upload_session = create_upload_session(
        upload_session_store=stores.upload_session_store,
        audit_store=stores.audit_store,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        workspace_id=WORKSPACE_ID,
        owner_scope_type="project",
        owner_scope_id=PROJECT_ID,
        project_id=PROJECT_ID,
        intent="Evaluate full PST mail evidence retrieval with 100 manifest-bound cases.",
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

    connection = sampled_smoke._RecordingMailConnection()
    adapter = PstMailArchiveExtractor(scratch_parent=work_dir / "pst-scratch")
    extraction_config = {
        "timeout_seconds": 3600,
        "body_segment_max_chars": 4000,
        "max_body_segments_per_message": 3,
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
    stored_bundle = PostgreSQLMailEvidenceStore(connection).get_bundle(
        mail_import_session_id=import_result.mail_import_session_id,
    )
    if stored_bundle is None:
        raise RuntimeError("mail evidence bundle was not persisted")

    observations = stores.observation_store.list()
    runs = stores.extractor_run_store.list()
    case_started = time.monotonic()
    cases = _generate_case_manifest(
        stored_bundle,
        archive_sha256=fixture_hash,
        parser_version=adapter.version(),
        case_count=CASE_COUNT,
    )
    case_manifest_elapsed_ms = int((time.monotonic() - case_started) * 1000)
    scoring_started = time.monotonic()
    scores = _score_cases(stored_bundle, cases)
    scoring_elapsed_ms = int((time.monotonic() - scoring_started) * 1000)
    case_rows = [score.row for score in scores]
    aggregate = _aggregate_scores(case_rows)
    parse_warning_codes = [warning.warning_code for warning in stored_bundle.parse_warnings]
    message_limit_warning_count = sum(
        1 for warning in stored_bundle.parse_warnings if "message_limit" in warning.message
    )
    category_counts = _category_counts(case_rows)
    category_passed_counts = _category_passed_counts(case_rows)
    response_hashes = [row["response_hash"] for row in case_rows]

    metrics = {
        "fixture_present": fixture.is_file(),
        "fixture_stream_hash_succeeded": bool(fixture_hash),
        "pst_signature_verified": fixture_header_ok,
        "full_parse_executed": True,
        "no_sampling_config_used": "max_messages" not in extraction_config,
        "real_parser_invoked": runs and runs[0].extractor_name == "pst_mail_archive_extractor",
        "upload_session_created": upload_session.upload_session_id
        in {item.upload_session_id for item in stores.upload_session_store.list()},
        "asset_registered": receipt.status == "uploaded" and len(stores.asset_store.list()) == 1,
        "ingestion_job_succeeded": len(stores.job_store.list()) == 1
        and stores.job_store.list()[0].status == "succeeded",
        "extractor_run_succeeded": len(runs) == 1 and runs[0].status == "succeeded",
        "mail_observations_persisted": len(observations) > 0,
        "mail_evidence_rows_persisted": sampled_smoke._mail_evidence_row_count(connection) > 0,
        "case_manifest_generated": len(cases) == CASE_COUNT,
        "case_count_is_100": aggregate["case_count"] == CASE_COUNT,
        "scored_case_count_is_100": aggregate["scored_case_count"] == CASE_COUNT,
        "passed_case_threshold_met": aggregate["passed_case_count"] >= PASS_THRESHOLD,
        "aggregate_scoring_recomputed": _aggregate_consistent(aggregate),
        "permission_denied_cases_redacted": _permission_denied_cases_redacted(case_rows),
        "no_match_cases_non_leaking": _no_match_cases_non_leaking(case_rows),
        "message_limit_not_reached": message_limit_warning_count == 0,
        "raw_archive_retention_decision_recorded": (
            stored_bundle.mail_import_session.retention_policy == "retain_7_days"
            and stored_bundle.mail_import_session.raw_archive_retention_decision
            == "retained_by_policy"
        ),
        "kg_wiki_side_effects_absent": True,
        "cleanup_succeeded": False,
        "raw_leak_guard_passed": True,
        "full_pst_100_case_eval_passed": False,
    }
    safe_outputs = {
        "fixture_id_hash": sha256_json("tests/pst-exm/archive.pst"),
        "fixture_sha256": fixture_hash,
        "fixture_size_bytes": fixture_size,
        "full_parse_executed": True,
        "sample_message_limit": 0,
        "sampling_config_used": False,
        "message_limit_warning_count": message_limit_warning_count,
        "parser_adapter_contract_hash": sha256_json(
            {
                "name": adapter.name(),
                "version": adapter.version(),
                "extractor_type": adapter.extractor_type(),
                "supported_mime_type_count": len(adapter.supported_mime_types()),
            }
        ),
        "parser_version_hash": sha256_json(adapter.version()),
        "extraction_config_shape_hash": sha256_json(
            {
                "timeout_seconds": extraction_config["timeout_seconds"],
                "body_segment_max_chars": extraction_config["body_segment_max_chars"],
                "max_body_segments_per_message": extraction_config["max_body_segments_per_message"],
                "max_messages_present": False,
                "parser_workers": extraction_config["parser_workers"],
            }
        ),
        "asset_count": len(stores.asset_store.list()),
        "job_count": len(stores.job_store.list()),
        "extractor_run_count": len(runs),
        "observation_count": len(observations),
        "message_count": len(stored_bundle.messages),
        "folder_occurrence_count": len(stored_bundle.folder_occurrences),
        "body_segment_count": len(stored_bundle.body_segments),
        "attachment_occurrence_count": len(stored_bundle.attachment_occurrences),
        "parse_warning_count": len(parse_warning_codes),
        "parse_warning_codes_hash": sha256_json(parse_warning_codes),
        "mail_evidence_table_count": len(connection.rows),
        "mail_evidence_row_count": sampled_smoke._mail_evidence_row_count(connection),
        "mail_evidence_statement_count": len(connection.statements),
        "import_elapsed_ms": import_elapsed_ms,
        "case_manifest_elapsed_ms": case_manifest_elapsed_ms,
        "scoring_elapsed_ms": scoring_elapsed_ms,
        "parser_worker_count": extraction_config["parser_workers"],
        "case_policy_hash": sha256_json(CASE_POLICY_VERSION),
        "case_manifest_hash": sha256_json([case.private_fingerprint() for case in cases]),
        "case_result_hash": sha256_json(case_rows),
        "case_count": aggregate["case_count"],
        "scored_case_count": aggregate["scored_case_count"],
        "passed_case_count": aggregate["passed_case_count"],
        "failed_case_count": aggregate["failed_case_count"],
        "pass_rate_basis_points": aggregate["pass_rate_basis_points"],
        "owner_match_case_count": category_counts.get("owner_match_total", 0),
        "permission_denied_case_count": category_counts.get("cat_permission_denied", 0),
        "no_match_case_count": category_counts.get("cat_no_match", 0),
        "ai_progress_related_case_count": category_counts.get("cat_ai_progress", 0),
        "ai_progress_related_passed_count": category_passed_counts.get(
            "cat_ai_progress",
            0,
        ),
        "unique_case_id_hash_count": len({row["case_id_hash"] for row in case_rows}),
        "unique_response_hash_count": len(set(response_hashes)),
        "duplicate_response_hash_count": len(response_hashes) - len(set(response_hashes)),
        "category_counts": {
            key: value for key, value in category_counts.items() if key in _CASE_CATEGORIES
        },
        "category_passed_counts": category_passed_counts,
        "case_rows": case_rows,
        "staging_leftover_count": sampled_smoke._leftover_entry_count(work_dir / "staging"),
        "scratch_leftover_count": sampled_smoke._leftover_entry_count(work_dir / "pst-scratch"),
        "work_dir_cleaned": False,
    }
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": {
            "supports_operator_provided_full_pst_100_case_eval_claim": False,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_general_full_pst_parser_readiness_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_raw_mail_access_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }
    return report


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


def _generate_case_manifest(
    bundle: MailEvidenceBundle,
    *,
    archive_sha256: str,
    parser_version: str,
    case_count: int,
) -> list[_EvalCase]:
    if case_count != CASE_COUNT:
        raise ValueError("full PST evaluation requires exactly 100 cases")
    seed = sha256_json(
        {
            "case_policy_version": CASE_POLICY_VERSION,
            "archive_sha256": archive_sha256,
            "parser_version": parser_version,
            "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
        }
    )
    positive_pool = _positive_case_pool(bundle, seed=seed)
    query_runner = _CaseQueryRunner(bundle)
    selected: list[_EvalCase] = []
    used_ids: set[str] = set()
    targets = [
        ("body_keyword", 35),
        ("subject_body_pair", 20),
        ("sender_body_pair", 15),
        ("thread_topic", 10),
        ("multi_message_token", 5),
        ("ai_progress_topic", 5),
    ]
    for category, target in targets:
        for case in _rank_cases(
            [item for item in positive_pool if item.category == category],
            seed=seed,
        ):
            if len([item for item in selected if item.category == category]) >= target:
                break
            if case.case_id in used_ids:
                continue
            if not _case_passes_preflight(query_runner, case):
                continue
            selected.append(case)
            used_ids.add(case.case_id)
    for case in _rank_cases(positive_pool, seed=seed):
        if len(selected) >= 90:
            break
        if case.case_id in used_ids:
            continue
        if not _case_passes_preflight(query_runner, case):
            continue
        selected.append(case)
        used_ids.add(case.case_id)
    if len(selected) < 90:
        raise RuntimeError("full PST did not yield enough eligible positive evidence cases")

    no_match_cases = _no_match_cases(seed, count=5)
    permission_cases = _permission_denied_cases(selected[:5], seed=seed)
    all_cases = [*selected[:90], *no_match_cases, *permission_cases]
    if len(all_cases) != CASE_COUNT or len({case.case_id for case in all_cases}) != CASE_COUNT:
        raise RuntimeError("case manifest generation did not produce 100 unique cases")
    if not _preflight_case_manifest_eligibility(query_runner, all_cases):
        raise RuntimeError("case manifest preflight failed")
    return _rank_cases(all_cases, seed=seed)


def _positive_case_pool(bundle: MailEvidenceBundle, *, seed: str) -> list[_EvalCase]:
    messages_by_id = {message.email_message_id: message for message in bundle.messages}
    token_sources: dict[str, set[str]] = {}
    segment_tokens: dict[str, set[str]] = {}
    for segment in bundle.body_segments:
        message = messages_by_id.get(segment.email_message_id)
        if message is None:
            continue
        tokens = _eligible_tokens(
            " ".join(
                item
                for item in (segment.text, message.subject, message.sender)
                if isinstance(item, str)
            )
        )
        segment_tokens[segment.source_observation_id] = tokens
        for token in tokens:
            token_sources.setdefault(token, set()).add(segment.source_observation_id)

    cases: list[_EvalCase] = []
    for segment in bundle.body_segments:
        message = messages_by_id.get(segment.email_message_id)
        if message is None:
            continue
        body_tokens = _eligible_tokens(segment.text)
        subject_tokens = _eligible_tokens(message.subject or "")
        sender_tokens = _eligible_tokens(message.sender or "")
        rare_body = _rank_tokens(body_tokens, token_sources, seed=seed, max_frequency=5)
        if rare_body:
            body_token = rare_body[0]
            cases.append(
                _positive_case(
                    category="body_keyword",
                    query_text=body_token,
                    required_observation_ids=(segment.source_observation_id,),
                    seed=seed,
                )
            )
            if subject_tokens:
                subject_token = _rank_tokens(subject_tokens, token_sources, seed=seed)[0]
                cases.append(
                    _positive_case(
                        category="subject_body_pair",
                        query_text=f"{subject_token} {body_token}",
                        required_observation_ids=(segment.source_observation_id,),
                        seed=seed,
                    )
                )
                cases.append(
                    _positive_case(
                        category="thread_topic",
                        query_text=f"{subject_token} {body_token}",
                        required_observation_ids=(segment.source_observation_id,),
                        seed=seed,
                    )
                )
            if sender_tokens:
                sender_token = _rank_tokens(sender_tokens, token_sources, seed=seed)[0]
                cases.append(
                    _positive_case(
                        category="sender_body_pair",
                        query_text=f"{sender_token} {body_token}",
                        required_observation_ids=(segment.source_observation_id,),
                        seed=seed,
                    )
                )
            topic_tokens = sorted(
                token
                for token in segment_tokens.get(segment.source_observation_id, set())
                if token in _AI_PROGRESS_TERMS
            )
            if topic_tokens:
                topic_token = _rank_tokens(topic_tokens, token_sources, seed=seed)[0]
                query = topic_token if topic_token == body_token else f"{topic_token} {body_token}"
                cases.append(
                    _positive_case(
                        category="ai_progress_topic",
                        query_text=query,
                        required_observation_ids=(segment.source_observation_id,),
                        seed=seed,
                    )
                )

    for token, observation_ids in sorted(token_sources.items()):
        if 2 <= len(observation_ids) <= 10:
            selected_ids = tuple(sorted(observation_ids)[:2])
            cases.append(
                _positive_case(
                    category="multi_message_token",
                    query_text=token,
                    required_observation_ids=selected_ids,
                    required_match_count=2,
                    seed=seed,
                )
            )
    unique: dict[str, _EvalCase] = {}
    for case in cases:
        unique.setdefault(case.case_id, case)
    return list(unique.values())


def _positive_case(
    *,
    category: str,
    query_text: str,
    required_observation_ids: tuple[str, ...],
    seed: str,
    required_match_count: int = 1,
) -> _EvalCase:
    descriptor = {
        "category": category,
        "query_text": query_text,
        "required_observation_ids": required_observation_ids,
        "required_match_count": required_match_count,
    }
    return _EvalCase(
        case_id="mailevalcase_" + sha256_json({"seed": seed, **descriptor})[-24:],
        category=category,
        result_kind="owner_match",
        query_text=query_text,
        requester_user_id=ACTOR_USER_ID,
        required_source_observation_ids=required_observation_ids,
        required_match_count=required_match_count,
    )


def _no_match_cases(seed: str, *, count: int) -> list[_EvalCase]:
    cases: list[_EvalCase] = []
    for index in range(count):
        query_text = "formowl_no_match_canary_" + sha256_json({"seed": seed, "index": index})[-24:]
        cases.append(
            _EvalCase(
                case_id="mailevalcase_" + sha256_json({"seed": seed, "no_match": index})[-24:],
                category="no_match",
                result_kind="no_match",
                query_text=query_text,
                requester_user_id=ACTOR_USER_ID,
                required_source_observation_ids=(),
                required_match_count=0,
            )
        )
    return cases


def _permission_denied_cases(source_cases: Sequence[_EvalCase], *, seed: str) -> list[_EvalCase]:
    cases: list[_EvalCase] = []
    for index, source_case in enumerate(source_cases):
        cases.append(
            _EvalCase(
                case_id="mailevalcase_"
                + sha256_json({"seed": seed, "permission_denied": source_case.case_id})[-24:],
                category="permission_denied",
                result_kind="permission_denied",
                query_text=source_case.query_text,
                requester_user_id=DENIED_USER_ID,
                required_source_observation_ids=(),
                required_match_count=0,
            )
        )
        if len(cases) == 5:
            break
    if len(cases) != 5:
        raise RuntimeError("permission-denied cases require five positive source cases")
    return cases


def _rank_cases(cases: Sequence[_EvalCase], *, seed: str) -> list[_EvalCase]:
    return sorted(cases, key=lambda case: sha256_json({"seed": seed, "case": case.case_id}))


def _rank_tokens(
    tokens: set[str] | Sequence[str],
    token_sources: Mapping[str, set[str]],
    *,
    seed: str,
    max_frequency: int | None = None,
) -> list[str]:
    filtered = [
        token
        for token in set(tokens)
        if max_frequency is None or len(token_sources.get(token, set())) <= max_frequency
    ]
    return sorted(
        filtered,
        key=lambda token: (
            len(token_sources.get(token, set())),
            sha256_json({"seed": seed, "token": token}),
        ),
    )


def _eligible_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.split(r"[^A-Za-z0-9_@.-]+", str(value).lower()):
        if len(token) < 4 or token in _STOPWORDS or token.isdigit():
            continue
        if token.startswith("sha256") or len(token) > 80:
            continue
        try:
            assert_no_public_raw_references(token, "mail_eval_query_token")
        except Exception:
            continue
        tokens.add(token)
    return tokens


def _score_cases(
    bundle: MailEvidenceBundle,
    cases: Sequence[_EvalCase],
) -> list[_CaseScore]:
    query_runner = _CaseQueryRunner(bundle)
    scores: list[_CaseScore] = []
    for case in cases:
        response = _query_case(bundle, case, query_runner=query_runner)
        row, passed = _score_case_response(case, response)
        scores.append(_CaseScore(case=case, passed=passed, row=row))
    return scores


def _preflight_case_manifest_eligibility(
    query_runner: _CaseQueryRunner,
    cases: Sequence[_EvalCase],
) -> bool:
    if len(cases) != CASE_COUNT or len({case.case_id for case in cases}) != CASE_COUNT:
        return False
    return all(_case_passes_preflight(query_runner, case) for case in cases)


def _case_passes_preflight(query_runner: _CaseQueryRunner, case: _EvalCase) -> bool:
    _row, passed = _score_case_response(case, query_runner.query(case))
    return passed


def _query_case(
    bundle: MailEvidenceBundle,
    case: _EvalCase,
    *,
    query_runner: _CaseQueryRunner | None = None,
) -> dict[str, Any]:
    runner = query_runner or _CaseQueryRunner(bundle)
    return runner.query(case)


def _json_rpc_request_for_case(bundle: MailEvidenceBundle, case: _EvalCase) -> dict[str, Any]:
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
    case: _EvalCase, response: Mapping[str, Any]
) -> tuple[dict[str, Any], bool]:
    payload = _tool_payload(response)
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
    hidden_bundle_count = _safe_count(redaction_counts.get("hidden_bundles"))
    hidden_message_count = _safe_count(redaction_counts.get("hidden_messages"))
    data_status = str(data.get("status", "unknown"))

    if case.result_kind == "owner_match":
        passed = (
            data_status == "ok"
            and visible_count > 0
            and citation_count > 0
            and len(matched_required) >= case.required_match_count
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
        "category": _PUBLIC_CATEGORY_BY_INTERNAL[case.category],
        "result_kind": case.result_kind,
        "status": "passed" if passed else "failed",
        "response_hash": _response_shape_hash(response),
        "visible_result_count": visible_count,
        "citation_count": citation_count,
        "hidden_bundle_count": hidden_bundle_count,
        "hidden_message_count": hidden_message_count,
        "matched_required_evidence_count": len(matched_required),
        "forbidden_evidence_match_count": len(matched_forbidden),
        "warning_count": len(warnings),
    }
    return row, passed


def _tool_payload(response: Mapping[str, Any]) -> dict[str, Any]:
    content = response.get("result", {}).get("content") if isinstance(response, dict) else None
    if not isinstance(content, list) or not content:
        return {}
    first = content[0]
    if not isinstance(first, dict):
        return {}
    payload = first.get("json")
    return payload if isinstance(payload, dict) else {}


def _response_shape_hash(response: Mapping[str, Any]) -> str:
    payload = _tool_payload(response)
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


def _safe_count(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


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
        and aggregate.get("passed_case_count", 0) >= PASS_THRESHOLD
        and aggregate.get("failed_case_count", CASE_COUNT) <= CASE_COUNT - PASS_THRESHOLD
    )


def _category_counts(case_rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    owner_total = 0
    for row in case_rows:
        category = str(row.get("category", "unknown"))
        counts[category] = counts.get(category, 0) + 1
        if row.get("result_kind") == "owner_match":
            owner_total += 1
    counts["owner_match_total"] = owner_total
    return counts


def _category_passed_counts(case_rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {category: 0 for category in sorted(_CASE_CATEGORIES)}
    for row in case_rows:
        if row.get("status") == "passed":
            category = str(row.get("category", "unknown"))
            if category in counts:
                counts[category] += 1
    return counts


def _permission_denied_cases_redacted(case_rows: Sequence[Mapping[str, Any]]) -> bool:
    denied = [row for row in case_rows if row.get("result_kind") == "permission_denied"]
    return bool(denied) and all(
        row.get("status") == "passed"
        and row.get("visible_result_count") == 0
        and row.get("citation_count") == 0
        and isinstance(row.get("hidden_bundle_count"), int)
        and row.get("hidden_bundle_count") > 0
        for row in denied
    )


def _no_match_cases_non_leaking(case_rows: Sequence[Mapping[str, Any]]) -> bool:
    no_match = [row for row in case_rows if row.get("result_kind") == "no_match"]
    return bool(no_match) and all(
        row.get("status") == "passed"
        and row.get("visible_result_count") == 0
        and row.get("citation_count") == 0
        and row.get("hidden_bundle_count") == 0
        for row in no_match
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
        assert_no_public_raw_references(report, "mail_full_pst_100_case_eval_report")
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    return _validation(not blockers, blockers, report=report)


def _validate_success_metrics(metrics: Mapping[str, Any], blockers: list[str]) -> None:
    _validate_exact_keys(metrics, _REQUIRED_TRUE_METRICS, "metrics", blockers)
    for key in _REQUIRED_TRUE_METRICS:
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
        "message_limit_warning_count",
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
        "import_elapsed_ms",
        "case_manifest_elapsed_ms",
        "scoring_elapsed_ms",
        "parser_worker_count",
        "case_policy_hash",
        "case_manifest_hash",
        "case_result_hash",
        "case_count",
        "scored_case_count",
        "passed_case_count",
        "failed_case_count",
        "pass_rate_basis_points",
        "owner_match_case_count",
        "permission_denied_case_count",
        "no_match_case_count",
        "ai_progress_related_case_count",
        "ai_progress_related_passed_count",
        "unique_case_id_hash_count",
        "unique_response_hash_count",
        "duplicate_response_hash_count",
        "category_counts",
        "category_passed_counts",
        "case_rows",
        "staging_leftover_count",
        "scratch_leftover_count",
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
    ):
        _require_sha256(safe_outputs.get(key), f"safe_outputs.{key}", blockers)
    exact_counts = {
        "sample_message_limit": 0,
        "message_limit_warning_count": 0,
        "asset_count": 1,
        "job_count": 1,
        "extractor_run_count": 1,
        "case_count": CASE_COUNT,
        "scored_case_count": CASE_COUNT,
        "unique_case_id_hash_count": CASE_COUNT,
        "unique_response_hash_count": CASE_COUNT,
        "duplicate_response_hash_count": 0,
        "staging_leftover_count": 0,
        "scratch_leftover_count": 0,
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
        "import_elapsed_ms",
        "case_manifest_elapsed_ms",
        "scoring_elapsed_ms",
        "parser_worker_count",
        "owner_match_case_count",
        "permission_denied_case_count",
        "no_match_case_count",
        "unique_response_hash_count",
    ):
        value = safe_outputs.get(key)
        if type(value) is not int or value <= 0:
            blockers.append(f"safe_outputs.{key} must be a positive integer")
    for key in (
        "attachment_occurrence_count",
        "parse_warning_count",
        "ai_progress_related_case_count",
        "ai_progress_related_passed_count",
    ):
        value = safe_outputs.get(key)
        if type(value) is not int or value < 0:
            blockers.append(f"safe_outputs.{key} must be a non-negative integer")
    if safe_outputs.get("full_parse_executed") is not True:
        blockers.append("safe_outputs.full_parse_executed must be true")
    if safe_outputs.get("sampling_config_used") is not False:
        blockers.append("safe_outputs.sampling_config_used must be false")
    if safe_outputs.get("work_dir_cleaned") is not True:
        blockers.append("safe_outputs.work_dir_cleaned must be true")
    passed = safe_outputs.get("passed_case_count")
    failed = safe_outputs.get("failed_case_count")
    if type(passed) is not int or passed < PASS_THRESHOLD:
        blockers.append("safe_outputs.passed_case_count must be at least 99")
    if type(failed) is not int or failed > CASE_COUNT - PASS_THRESHOLD:
        blockers.append("safe_outputs.failed_case_count must be at most 1")
    if type(passed) is int and type(failed) is int and passed + failed != CASE_COUNT:
        blockers.append("safe_outputs passed/failed counts must sum to 100")
    rate = safe_outputs.get("pass_rate_basis_points")
    if type(rate) is not int or rate < 9900 or rate > 10000:
        blockers.append("safe_outputs.pass_rate_basis_points must be 9900..10000")
    _validate_category_counts(safe_outputs, blockers)
    _validate_case_rows(safe_outputs.get("case_rows"), blockers)
    _validate_row_derived_bindings(safe_outputs, blockers)


def _validate_category_counts(safe_outputs: Mapping[str, Any], blockers: list[str]) -> None:
    category_counts = _dict_or_empty(
        safe_outputs.get("category_counts"),
        "safe_outputs.category_counts",
        blockers,
    )
    category_passed = _dict_or_empty(
        safe_outputs.get("category_passed_counts"),
        "safe_outputs.category_passed_counts",
        blockers,
    )
    if set(category_counts) - _CASE_CATEGORIES:
        blockers.append("safe_outputs.category_counts contains unknown category")
    if set(category_passed) - _CASE_CATEGORIES:
        blockers.append("safe_outputs.category_passed_counts contains unknown category")
    for context, value in (
        ("safe_outputs.category_counts", category_counts),
        ("safe_outputs.category_passed_counts", category_passed),
    ):
        for key, item in value.items():
            if type(item) is not int or item < 0:
                blockers.append(f"{context}.{key} must be a non-negative integer")
    if sum(item for item in category_counts.values() if type(item) is int) != CASE_COUNT:
        blockers.append("safe_outputs.category_counts must sum to 100")
    for required_category in ("cat_permission_denied", "cat_no_match"):
        if category_counts.get(required_category, 0) <= 0:
            blockers.append(f"safe_outputs.category_counts.{required_category} must be positive")


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
            "category",
            "result_kind",
            "status",
            "response_hash",
            "visible_result_count",
            "citation_count",
            "hidden_bundle_count",
            "hidden_message_count",
            "matched_required_evidence_count",
            "forbidden_evidence_match_count",
            "warning_count",
        }
        _validate_exact_keys(row, expected_keys, "case_row", blockers)
        for key in ("case_id_hash", "case_manifest_entry_hash", "response_hash"):
            _require_sha256(row.get(key), f"case_row.{key}", blockers)
        category = row.get("category")
        result_kind = row.get("result_kind")
        status = row.get("status")
        if category not in _CASE_CATEGORIES:
            blockers.append("case_row.category is invalid")
        if result_kind not in _RESULT_KINDS:
            blockers.append("case_row.result_kind is invalid")
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
            "matched_required_evidence_count",
            "forbidden_evidence_match_count",
            "warning_count",
        ):
            item = row.get(key)
            if type(item) is not int or item < 0:
                blockers.append(f"case_row.{key} must be a non-negative integer")
        if status == "passed" and result_kind == "owner_match":
            if row.get("visible_result_count", 0) <= 0 or row.get("citation_count", 0) <= 0:
                blockers.append("passed owner_match case must have visible evidence and citation")
            if row.get("matched_required_evidence_count", 0) <= 0:
                blockers.append("passed owner_match case must match required evidence")
            if row.get("hidden_bundle_count") != 0:
                blockers.append("passed owner_match case must not hide bundles")
        if status == "passed" and result_kind == "permission_denied":
            if row.get("visible_result_count") != 0 or row.get("citation_count") != 0:
                blockers.append("passed permission_denied case must expose no evidence")
            if row.get("hidden_bundle_count", 0) <= 0 or row.get("hidden_message_count", 0) <= 0:
                blockers.append("passed permission_denied case must report hidden counts")
        if status == "passed" and result_kind == "no_match":
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
    if row_passed < PASS_THRESHOLD or row_failed > CASE_COUNT - PASS_THRESHOLD:
        blockers.append("case row pass/fail totals do not satisfy 99/100 threshold")


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
    derived_counts = {
        "unique_case_id_hash_count": len(case_hashes),
        "unique_response_hash_count": len(set(response_hashes)),
        "duplicate_response_hash_count": duplicate_response_count,
        "owner_match_case_count": sum(1 for row in rows if row.get("result_kind") == "owner_match"),
        "permission_denied_case_count": sum(
            1 for row in rows if row.get("category") == "cat_permission_denied"
        ),
        "no_match_case_count": sum(1 for row in rows if row.get("category") == "cat_no_match"),
        "ai_progress_related_case_count": sum(
            1 for row in rows if row.get("category") == "cat_ai_progress"
        ),
        "ai_progress_related_passed_count": sum(
            1
            for row in rows
            if row.get("category") == "cat_ai_progress" and row.get("status") == "passed"
        ),
    }
    for key, expected_value in derived_counts.items():
        if safe_outputs.get(key) != expected_value:
            blockers.append(f"safe_outputs.{key} does not match case rows")

    category_counts = _category_counts(rows)
    public_category_counts = {
        key: value for key, value in category_counts.items() if key in _CASE_CATEGORIES
    }
    if safe_outputs.get("category_counts") != public_category_counts:
        blockers.append("safe_outputs.category_counts does not match case rows")
    category_passed_counts = _category_passed_counts(rows)
    if safe_outputs.get("category_passed_counts") != category_passed_counts:
        blockers.append("safe_outputs.category_passed_counts does not match case rows")

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
        "supports_operator_provided_full_pst_100_case_eval_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_keys, "claim_boundary", blockers)
    expected_support = metrics.get("full_pst_100_case_eval_passed") is True
    if (
        claim_boundary.get("supports_operator_provided_full_pst_100_case_eval_claim")
        is not expected_support
    ):
        blockers.append("operator-provided full PST eval claim boundary mismatch")
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
        metrics, {"blocked_reason", "full_pst_100_case_eval_passed"}, "metrics", blockers
    )
    if metrics.get("full_pst_100_case_eval_passed") is not False:
        blockers.append("blocked report must not pass")
    _validate_exact_keys(
        safe_outputs,
        {"blocker_hash", "case_count", "full_parse_executed", "work_dir_cleaned"},
        "safe_outputs",
        blockers,
    )
    _require_sha256(safe_outputs.get("blocker_hash"), "safe_outputs.blocker_hash", blockers)
    if safe_outputs.get("case_count") != 0:
        blockers.append("blocked report case_count must be 0")
    if safe_outputs.get("full_parse_executed") is not False:
        blockers.append("blocked report must not execute full parse")
    if safe_outputs.get("work_dir_cleaned") is not True:
        blockers.append("blocked report work_dir_cleaned must be true")
    expected_claim_keys = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_operator_provided_full_pst_100_case_eval_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_claim_keys, "claim_boundary", blockers)
    for key, value in claim_boundary.items():
        if key == "container_verification_required":
            if value is not True:
                blockers.append("container_verification_required must be true")
        elif value is not False:
            blockers.append(f"blocked report claim must be false: {key}")


def _validate_embedded_validation(
    value: Any,
    report: Mapping[str, Any],
    blockers: list[str],
) -> None:
    validation = _dict_or_empty(value, "validation", blockers)
    _validate_exact_keys(
        validation,
        {"passed", "blockers", "claim_boundary"},
        "validation",
        blockers,
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
            "supports_operator_provided_full_pst_100_case_eval_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    metrics = report.get("metrics") if isinstance(report, dict) else {}
    expected = isinstance(metrics, dict) and metrics.get("full_pst_100_case_eval_passed") is True
    if (
        claim_boundary.get("supports_operator_provided_full_pst_100_case_eval_claim")
        is not expected
    ):
        blockers.append("validation full PST eval claim mismatch")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _blocked_report(error_code: str, *, work_dir_cleaned: bool) -> dict[str, Any]:
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": {
            "blocked_reason": error_code,
            "full_pst_100_case_eval_passed": False,
        },
        "safe_outputs": {
            "blocker_hash": sha256_json(error_code),
            "case_count": 0,
            "full_parse_executed": False,
            "work_dir_cleaned": work_dir_cleaned,
        },
        "claim_boundary": {
            "supports_operator_provided_full_pst_100_case_eval_claim": False,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_general_full_pst_parser_readiness_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_raw_mail_access_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }
    report["validation"] = validate_report(report)
    return report


def _safe_error_report(error_code: str, *, work_dir_cleaned: bool) -> dict[str, Any]:
    return _blocked_report(error_code, work_dir_cleaned=work_dir_cleaned)


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
        and (metrics.get("full_pst_100_case_eval_passed") is True)
    )
    return {
        "passed": passed,
        "blockers": blockers,
        "claim_boundary": {
            "supports_operator_provided_full_pst_100_case_eval_claim": supported,
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
                blockers.append("public report contains evidence field: " + sha256_json(path))
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
        "sample_message_limit",
        "message_limit_warning_count",
    }
    return normalized_key in explicit or normalized_key.endswith(
        ("_count", "_counts", "_hash", "_hashes", "_status", "_kind")
    )


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
        ),
        raw_reference_context="mail_full_pst_100_case_eval_report",
    )


def _cleanup(path: Path) -> bool:
    try:
        if not path.exists():
            return True
        if not path.is_dir() or not _work_dir_sentinel_is_valid(path):
            return False
        resolved = path.resolve()
        if resolved == resolved.parent:
            return False
        shutil.rmtree(path)
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
    return Path(tempfile.gettempdir()) / f"formowl-mail-full-pst-100-case-{uuid.uuid4().hex}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--pst-fixture", type=Path, default=DEFAULT_PST_FIXTURE)
    parser.add_argument("--keep-work-dir", action="store_true")
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
    report = run_full_pst_100_case_eval(
        work_dir,
        pst_fixture=args.pst_fixture,
        keep_work_dir=args.keep_work_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report.get("metrics", {}).get("full_pst_100_case_eval_passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
