#!/usr/bin/env python3
"""Rebuild complete May-PST evidence and replay the frozen domain-hard 100.

The source PST, source work directory, original private manifest, remapped
manifest, and normalized observations remain private operator artifacts.
Public output contains only hashes, counts, statuses, and claim boundaries.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts"
PYTHON_ROOT = ROOT / "python"
for import_path in (PYTHON_ROOT, SCRIPT_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import mail_full_pst_domain_hard_case_eval as hard_eval  # noqa: E402
import mail_real_pst_smoke as sampled_smoke  # noqa: E402
import real_pst_domain_hard_100_lock as lock_script  # noqa: E402
from formowl_contract import Observation, assert_no_public_raw_references, sha256_json  # noqa: E402
from formowl_core.tokenization import (  # noqa: E402
    configured_mail_candidate_admission_tokens,
    validate_configured_mail_tokenizer,
)
from formowl_ingestion.extractors import PstMailArchiveExtractor  # noqa: E402
from formowl_ingestion.storage import (  # noqa: E402
    AssetStore,
    ObservationStore,
    UploadSessionStore,
)
from formowl_mail import (  # noqa: E402
    MailEvidenceBundle,
    MailEvidenceQueryGateway,
    PostgreSQLMailEvidenceStore,
    build_mail_evidence_bundle,
    run_upload_session_mail_import,
)


REPORT_TYPE = "formowl_real_pst_domain_hard_100_complete_evidence_rebuild_v1"
DERIVED_MANIFEST_NAME = hard_eval.PRIVATE_MANIFEST_NAME
BASELINE_REPORT_NAME = "fixed-domain-hard-100-baseline.json"
EXECUTED_PIPELINE_ID = "complete_mail_evidence_rebuild_diagnostic_v1"
TARGET_METHOD_ID = "evidence_to_knowledge_kg_ontology_v2_hybrid_v1"
IMMUTABLE_CASE_FIELDS = (
    "case_id",
    "domain",
    "pattern",
    "intent_kind",
    "result_kind",
    "query_text",
    "requester_user_id",
    "limit",
    "required_match_count",
)
SOURCE_FILES = (
    "python/formowl_core/tokenization.py",
    "python/formowl_ingestion/extractors/mail/pst.py",
    "python/formowl_mail/bundle.py",
    "python/formowl_mail/query.py",
    "python/formowl_mail/postgres.py",
    "scripts/mail_full_pst_domain_hard_case_eval.py",
    "scripts/mail_full_pst_domain_hard_kg_fusion_eval.py",
    "scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py",
    "scripts/real_pst_domain_hard_100_lock.py",
    "scripts/real_pst_domain_hard_100_rebuild.py",
)
_REDACTED_BODY_SEGMENT = re.compile(r"^redacted_mail_body_segment (sha256:[0-9a-f]{64})$")


@dataclass(frozen=True)
class _MappedManifest:
    payload: dict[str, Any]
    cases: list[hard_eval._DomainCase]
    mapping: dict[str, str]
    strategy_counts: dict[str, int]
    source_manifest_hash: str
    derived_manifest_hash: str
    immutable_case_hash: str


class FrozenManifestMappingError(RuntimeError):
    """Fail-closed manifest mapping error with count-only diagnostics."""

    def __init__(self, diagnostics: Mapping[str, Any]) -> None:
        super().__init__("frozen evidence could not be mapped without approximation")
        self.diagnostics = dict(diagnostics)


class _DirectVerifiedPstObjectStore:
    """Read one already-verified PST without copying its 21 GB payload."""

    def __init__(
        self,
        *,
        path: Path,
        object_uri: str,
        content_hash: str,
        file_size: int,
    ) -> None:
        self._path = path.resolve()
        self._object_uri = object_uri
        self._content_hash = content_hash
        self._file_size = file_size
        self._stat_identity = self._stat()

    def resolve_object_path(self, object_uri: str) -> Path | None:
        if object_uri != self._object_uri or not self._unchanged():
            return None
        return self._path

    def verify_object(
        self,
        object_uri: str,
        expected_content_hash: str | None = None,
    ) -> bool:
        return (
            object_uri == self._object_uri
            and (expected_content_hash is None or expected_content_hash == self._content_hash)
            and self._unchanged()
        )

    def _stat(self) -> tuple[int, int, int, int]:
        stat = self._path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def _unchanged(self) -> bool:
        try:
            return self._stat() == self._stat_identity and self._stat_identity[2] == self._file_size
        except OSError:
            return False


def rebuild_complete_evidence(
    *,
    pst_path: Path,
    source_work_dir: Path,
    source_manifest_path: Path,
    lock_path: Path,
    work_dir: Path,
    resume_existing_work: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    tokenizer_id = validate_configured_mail_tokenizer()
    source_manifest = _read_json(source_manifest_path)
    lock = _read_json(lock_path)
    manifest_lock_report = lock_script.validate_frozen_manifest(source_manifest, lock)
    if manifest_lock_report.get("status") != "passed":
        raise RuntimeError("frozen manifest validation failed")

    fixture_started = time.monotonic()
    fixture_report = lock_script.verify_pst_fixture(pst_path, lock)
    fixture_elapsed_ms = int((time.monotonic() - fixture_started) * 1000)
    if fixture_report.get("status") != "passed":
        raise RuntimeError("PST fixture validation failed")
    fixture_safe = _mapping(fixture_report.get("safe_outputs"), "fixture safe outputs")
    archive_sha256 = _required_str(fixture_safe, "fixture_sha256")
    fixture_size = _required_int(fixture_safe, "fixture_size_bytes")
    fixture_header_ok = _pst_header_ok(pst_path)

    adapter = PstMailArchiveExtractor(scratch_parent=work_dir / "pst-scratch")
    extraction_config = {
        "timeout_seconds": 3600,
        "body_segment_max_chars": 4000,
        "max_body_segments_per_message": None,
        "max_attachment_text_bytes": 5 * 1024 * 1024,
        "preserve_private_body_text": True,
        "parser_workers": max(1, min(os.cpu_count() or 1, 8)),
    }
    if resume_existing_work:
        stores = hard_eval._stores(work_dir / "data", work_dir / "object-root")
        source_asset, source_session = _load_source_asset_and_session(
            work_dir,
            archive_sha256=archive_sha256,
        )
        bundle_started = time.monotonic()
        bundle = _bundle_from_existing_observations(
            stores=stores,
            source_asset=source_asset,
            source_session=source_session,
        )
        import_elapsed_ms = 0
        bundle_read_elapsed_ms = int((time.monotonic() - bundle_started) * 1000)
        mail_evidence_table_count = 0
        mail_evidence_row_count = 0
        mail_evidence_statement_count = 0
    else:
        _prepare_work_dir(work_dir)
        stores = hard_eval._stores(work_dir / "data", work_dir / "object-root")
        source_asset, source_session = _load_source_asset_and_session(
            source_work_dir,
            archive_sha256=archive_sha256,
        )
        stores.asset_store.create(source_asset)
        reset_session = replace(
            source_session,
            status="uploading",
            processing_status="archive_uploaded",
            ingestion_job_id=None,
            completed_at=None,
        )
        stores.upload_session_store.create(reset_session)
        direct_store = _DirectVerifiedPstObjectStore(
            path=pst_path,
            object_uri=source_asset.object_uri,
            content_hash=source_asset.content_hash,
            file_size=fixture_size,
        )

        connection = sampled_smoke._RecordingMailConnection()
        import_started = time.monotonic()
        import_result = run_upload_session_mail_import(
            None,
            upload_session_id=reset_session.upload_session_id,
            upload_session_store=stores.upload_session_store,
            object_store=direct_store,
            asset_store=stores.asset_store,
            job_store=stores.job_store,
            extractor_run_store=stores.extractor_run_store,
            observation_store=stores.observation_store,
            mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
            storage_backend_id=hard_eval.STORAGE_BACKEND_ID,
            actor_user_id=reset_session.actor_user_id,
            session_id=reset_session.session_id or hard_eval.SESSION_ID,
            query_text=None,
            created_at=hard_eval.NOW,
            adapter=adapter,
            extraction_config=extraction_config,
            asset_mime_type=source_asset.mime_type,
            parser_name=adapter.name(),
            parser_version=adapter.version(),
        )
        import_elapsed_ms = int((time.monotonic() - import_started) * 1000)

        bundle_started = time.monotonic()
        bundle = PostgreSQLMailEvidenceStore(connection).get_bundle(
            mail_import_session_id=import_result.mail_import_session_id,
        )
        if bundle is None:
            raise RuntimeError("mail evidence bundle was not persisted")
        bundle_read_elapsed_ms = int((time.monotonic() - bundle_started) * 1000)
        mail_evidence_table_count = len(connection.rows)
        mail_evidence_row_count = sampled_smoke._mail_evidence_row_count(connection)
        mail_evidence_statement_count = len(connection.statements)

    try:
        mapped = remap_frozen_manifest(
            source_manifest,
            source_observation_store=ObservationStore(source_work_dir / "data"),
            bundle=bundle,
        )
    except FrozenManifestMappingError as exc:
        canaries = _run_canaries(bundle, ())
        _write_public_json(
            work_dir / "artifacts" / "mapping-blocked-canaries.safe.json",
            {
                "report_type": "formowl_mapping_blocked_canary_checkpoint_v1",
                "mapping_diagnostics": exc.diagnostics,
                "canary_rows": canaries["rows"],
                "blocking_canary_ids": canaries["blocking_canary_ids"],
            },
        )
        return _mapping_blocked_report(
            tokenizer_id=tokenizer_id,
            archive_sha256=archive_sha256,
            fixture_size=fixture_size,
            fixture_elapsed_ms=fixture_elapsed_ms,
            fixture_header_ok=fixture_header_ok,
            bundle=bundle,
            mapping_diagnostics=exc.diagnostics,
            canaries=canaries,
            import_elapsed_ms=import_elapsed_ms,
            bundle_read_elapsed_ms=bundle_read_elapsed_ms,
            started=started,
        )
    derived_manifest_path = work_dir / "artifacts" / DERIVED_MANIFEST_NAME
    _write_private_json(derived_manifest_path, mapped.payload)

    baseline_report = hard_eval._build_report_for_bundle(
        bundle,
        work_dir=work_dir,
        archive_sha256=archive_sha256,
        parser_version=adapter.version(),
        fixture_size_bytes=fixture_size,
        fixture_header_ok=fixture_header_ok,
        receipt_uploaded=True,
        asset_count=len(stores.asset_store.list()),
        job_count=len(stores.job_store.list()),
        extractor_run_count=len(stores.extractor_run_store.list()),
        observation_count=len(stores.observation_store.list()),
        mail_evidence_table_count=mail_evidence_table_count,
        mail_evidence_row_count=mail_evidence_row_count,
        mail_evidence_statement_count=mail_evidence_statement_count,
        parser_worker_count=extraction_config["parser_workers"],
        extraction_config_shape_hash=sha256_json(
            {
                **extraction_config,
                "max_messages_present": False,
            }
        ),
        fixture_hash_elapsed_ms=fixture_elapsed_ms,
        upload_elapsed_ms=0,
        import_elapsed_ms=import_elapsed_ms,
        bundle_read_elapsed_ms=bundle_read_elapsed_ms,
        staging_leftover_count=0,
        scratch_leftover_count=sampled_smoke._leftover_entry_count(work_dir / "pst-scratch"),
        fixed_cases=mapped.cases,
        fixed_private_manifest_hash=mapped.derived_manifest_hash,
    )
    baseline_report["metrics"]["raw_leak_guard_passed"] = hard_eval._public_outputs_are_safe(
        baseline_report
    )
    baseline_report["metrics"]["domain_hard_case_baseline_completed"] = (
        hard_eval._domain_hard_baseline_completed(baseline_report)
    )
    baseline_report["claim_boundary"][
        "supports_operator_provided_full_pst_domain_hard_baseline_claim"
    ] = baseline_report["metrics"]["domain_hard_case_baseline_completed"]
    baseline_report["validation"] = hard_eval.validate_report(baseline_report)
    baseline_path = work_dir / "artifacts" / BASELINE_REPORT_NAME
    _write_public_json(baseline_path, baseline_report)

    canaries = _run_canaries(bundle, mapped.cases)
    body_states = Counter(message.body_evidence_state for message in bundle.messages)
    execution_fingerprint = sha256_json(
        {
            "executed_pipeline_id": EXECUTED_PIPELINE_ID,
            "target_method_id": TARGET_METHOD_ID,
            "tokenizer_id": tokenizer_id,
            "tokenizer_model_sha256": os.environ.get("FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"),
            "archive_sha256": archive_sha256,
            "source_manifest_hash": mapped.source_manifest_hash,
            "derived_manifest_hash": mapped.derived_manifest_hash,
            "immutable_case_hash": mapped.immutable_case_hash,
            "extraction_config": extraction_config,
            "resume_existing_work": resume_existing_work,
            "implementation_source_hash": _implementation_source_hash(),
        }
    )
    baseline_safe = _mapping(baseline_report.get("safe_outputs"), "baseline safe outputs")
    report = {
        "report_type": REPORT_TYPE,
        "status": (
            "passed"
            if baseline_report.get("validation", {}).get("passed") is True
            and not canaries["blocking_canary_ids"]
            else "blocked"
        ),
        "safe_outputs": {
            "executed_pipeline_id_hash": sha256_json(EXECUTED_PIPELINE_ID),
            "target_method_id_hash": sha256_json(TARGET_METHOD_ID),
            "lexical_profile_id_hash": sha256_json(tokenizer_id),
            "lexical_profile_artifact_hash": os.environ.get(
                "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"
            ),
            "execution_fingerprint": execution_fingerprint,
            "archive_sha256": archive_sha256,
            "fixture_size_bytes": fixture_size,
            "source_manifest_hash": mapped.source_manifest_hash,
            "derived_manifest_hash": mapped.derived_manifest_hash,
            "immutable_case_hash": mapped.immutable_case_hash,
            "mapped_observation_count": len(mapped.mapping),
            "mapping_strategy_counts": mapped.strategy_counts,
            "mapping_hash": sha256_json(mapped.mapping),
            "asset_identity_reused": source_asset.asset_id == stores.asset_store.list()[0].asset_id,
            "raw_pst_copy_count": 0,
            "message_count": len(bundle.messages),
            "body_segment_count": len(
                [
                    segment
                    for segment in bundle.body_segments
                    if segment.segment_source_type == "message_body"
                ]
            ),
            "attachment_text_segment_count": len(
                [
                    segment
                    for segment in bundle.body_segments
                    if segment.segment_source_type == "attachment_text"
                ]
            ),
            "body_evidence_state_counts": dict(sorted(body_states.items())),
            "source_body_char_count": sum(
                message.source_body_char_count or 0 for message in bundle.messages
            ),
            "stored_body_char_count": sum(
                message.stored_body_char_count or 0 for message in bundle.messages
            ),
            "unresolved_attachment_count": sum(
                message.unresolved_attachment_count for message in bundle.messages
            ),
            "baseline_report_hash": sha256_json(baseline_report),
            "baseline_passed_case_count": baseline_safe.get("passed_case_count"),
            "baseline_pass_rate_basis_points": baseline_safe.get("pass_rate_basis_points"),
            "canary_rows": canaries["rows"],
            "blocking_canary_ids": canaries["blocking_canary_ids"],
            "fixture_validation_elapsed_ms": fixture_elapsed_ms,
            "import_elapsed_ms": import_elapsed_ms,
            "bundle_read_elapsed_ms": bundle_read_elapsed_ms,
            "total_elapsed_ms": int((time.monotonic() - started) * 1000),
        },
        "claim_boundary": {
            "same_original_private_questions_locked": True,
            "complete_source_reingestion_diagnostic": True,
            "fixed_100_replayed": True,
            "target_method_executed": False,
            "methodology_ready": False,
            "kg_outperforms_ontology_claim": False,
            "ontology_outperforms_kg_claim": False,
            "production_ready": False,
            "raw_content_included": False,
            "private_path_included": False,
        },
    }
    assert_no_public_raw_references(report, "real_pst_domain_hard_100_complete_rebuild")
    return report


def _mapping_blocked_report(
    *,
    tokenizer_id: str,
    archive_sha256: str,
    fixture_size: int,
    fixture_elapsed_ms: int,
    fixture_header_ok: bool,
    bundle: MailEvidenceBundle,
    mapping_diagnostics: Mapping[str, Any],
    canaries: Mapping[str, Any],
    import_elapsed_ms: int,
    bundle_read_elapsed_ms: int,
    started: float,
) -> dict[str, Any]:
    body_states = Counter(message.body_evidence_state for message in bundle.messages)
    report = {
        "report_type": REPORT_TYPE,
        "status": "blocked",
        "safe_outputs": {
            "executed_pipeline_id_hash": sha256_json(EXECUTED_PIPELINE_ID),
            "target_method_id_hash": sha256_json(TARGET_METHOD_ID),
            "lexical_profile_id_hash": sha256_json(tokenizer_id),
            "lexical_profile_artifact_hash": os.environ.get(
                "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256"
            ),
            "archive_sha256": archive_sha256,
            "fixture_size_bytes": fixture_size,
            "fixture_header_ok": fixture_header_ok,
            "mapping_diagnostics": dict(mapping_diagnostics),
            "message_count": len(bundle.messages),
            "body_segment_count": len(
                [
                    segment
                    for segment in bundle.body_segments
                    if segment.segment_source_type == "message_body"
                ]
            ),
            "attachment_text_segment_count": len(
                [
                    segment
                    for segment in bundle.body_segments
                    if segment.segment_source_type == "attachment_text"
                ]
            ),
            "body_evidence_state_counts": dict(sorted(body_states.items())),
            "source_body_char_count": sum(
                message.source_body_char_count or 0 for message in bundle.messages
            ),
            "stored_body_char_count": sum(
                message.stored_body_char_count or 0 for message in bundle.messages
            ),
            "unresolved_attachment_count": sum(
                message.unresolved_attachment_count for message in bundle.messages
            ),
            "canary_rows": list(canaries.get("rows", [])),
            "blocking_canary_ids": sorted(
                {
                    "fixed_manifest_mapping",
                    *[str(value) for value in canaries.get("blocking_canary_ids", [])],
                }
            ),
            "fixture_validation_elapsed_ms": fixture_elapsed_ms,
            "import_elapsed_ms": import_elapsed_ms,
            "bundle_read_elapsed_ms": bundle_read_elapsed_ms,
            "total_elapsed_ms": int((time.monotonic() - started) * 1000),
        },
        "claim_boundary": {
            "same_original_private_questions_locked": True,
            "complete_source_reingestion_diagnostic": True,
            "fixed_100_replayed": False,
            "target_method_executed": False,
            "methodology_ready": False,
            "kg_outperforms_ontology_claim": False,
            "ontology_outperforms_kg_claim": False,
            "production_ready": False,
            "raw_content_included": False,
            "private_path_included": False,
        },
    }
    assert_no_public_raw_references(report, "real_pst_domain_hard_100_mapping_blocked")
    return report


def remap_frozen_manifest(
    source_manifest: Mapping[str, Any],
    *,
    source_observation_store: ObservationStore,
    bundle: MailEvidenceBundle,
) -> _MappedManifest:
    source_cases = source_manifest.get("cases")
    if not isinstance(source_cases, list) or len(source_cases) != hard_eval.CASE_COUNT:
        raise RuntimeError("source manifest must contain exactly 100 cases")
    required_ids = {
        str(observation_id)
        for case in source_cases
        if isinstance(case, Mapping)
        for field_name in (
            "required_source_observation_ids",
            "forbidden_source_observation_ids",
        )
        for observation_id in case.get(field_name, [])
    }
    old_observations: dict[str, Observation] = {}
    for observation_id in sorted(required_ids):
        observation = source_observation_store.get(observation_id)
        if observation is None or observation.observation_type != "email_body_segment":
            raise RuntimeError("frozen evidence observation is unavailable")
        old_observations[observation_id] = observation

    new_segments_by_occurrence: dict[str, list[Any]] = defaultdict(list)
    for segment in bundle.body_segments:
        if segment.segment_source_type == "message_body":
            new_segments_by_occurrence[segment.message_occurrence_id].append(segment)
    for segments in new_segments_by_occurrence.values():
        segments.sort(
            key=lambda item: (
                item.body_segment_index or 0,
                item.char_start or 0,
                item.email_body_segment_id,
            )
        )

    mapping: dict[str, str] = {}
    strategy_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    failed_observation_ids: set[str] = set()
    historical_evidence_keys = {
        key
        for observation in old_observations.values()
        if (key := _historical_evidence_key(observation)) is not None
    }
    global_historical_index: dict[tuple[int, str], list[tuple[str, str]]] | None = None
    missing_identity_source_occurrence_ids = {
        _observation_occurrence_id(observation)
        for observation in old_observations.values()
        if _observation_occurrence_id(observation) not in new_segments_by_occurrence
        and not _observation_has_message_identity(observation)
    }
    source_message_by_occurrence: dict[str, Observation] = {}
    if missing_identity_source_occurrence_ids:
        source_message_by_occurrence = {
            _observation_occurrence_id(observation): observation
            for observation in source_observation_store.list()
            if observation.observation_type == "email_message"
            and _observation_occurrence_id(observation) in missing_identity_source_occurrence_ids
        }
    new_identity_indexes = _new_message_identity_indexes(bundle)
    for observation_id, observation in old_observations.items():
        old_occurrence_id = _observation_occurrence_id(observation)
        try:
            occurrence_id, identity_strategy = _resolve_complete_message_occurrence(
                observation,
                source_message=source_message_by_occurrence.get(old_occurrence_id),
                new_segments_by_occurrence=new_segments_by_occurrence,
                new_identity_indexes=new_identity_indexes,
            )
        except RuntimeError:
            if global_historical_index is None:
                global_historical_index = _build_global_historical_evidence_index(
                    new_segments_by_occurrence,
                    required_keys=historical_evidence_keys,
                )
            global_mapping = _map_from_global_historical_evidence_index(
                observation,
                global_historical_index,
            )
            if global_mapping is not None:
                mapping[observation_id] = global_mapping
                strategy_counts["global_historical_segment_content_hash"] += 1
                continue
            global_mapping = _map_from_global_unique_exact_content(
                observation,
                new_segments_by_occurrence,
            )
            if global_mapping is not None:
                mapping[observation_id] = global_mapping
                strategy_counts["global_unique_exact_content"] += 1
                continue
            failure_counts["message_identity_unavailable"] += 1
            failed_observation_ids.add(observation_id)
            continue
        candidates = new_segments_by_occurrence.get(occurrence_id, [])
        try:
            mapped_id, segment_strategy = _map_observation_to_complete_segment(
                observation,
                candidates,
            )
        except RuntimeError:
            if global_historical_index is None:
                global_historical_index = _build_global_historical_evidence_index(
                    new_segments_by_occurrence,
                    required_keys=historical_evidence_keys,
                )
            global_mapping = _map_from_global_historical_evidence_index(
                observation,
                global_historical_index,
            )
            if global_mapping is not None:
                mapping[observation_id] = global_mapping
                strategy_counts["global_historical_segment_content_hash"] += 1
                continue
            global_mapping = _map_from_global_unique_exact_content(
                observation,
                new_segments_by_occurrence,
            )
            if global_mapping is not None:
                mapping[observation_id] = global_mapping
                strategy_counts["global_unique_exact_content"] += 1
                continue
            failure_counts["exact_segment_mapping_unavailable"] += 1
            failed_observation_ids.add(observation_id)
            continue
        mapping[observation_id] = mapped_id
        strategy = (
            segment_strategy
            if identity_strategy == "same_occurrence"
            else f"{identity_strategy}_{segment_strategy}"
        )
        strategy_counts[strategy] += 1
    if failed_observation_ids:
        affected_case_count = sum(
            bool(
                failed_observation_ids
                & {
                    *_case_string_list(case, "required_source_observation_ids"),
                    *_case_string_list(case, "forbidden_source_observation_ids"),
                }
            )
            for case in source_cases
            if isinstance(case, Mapping)
        )
        raise FrozenManifestMappingError(
            {
                "required_observation_count": len(required_ids),
                "mapped_observation_count": len(mapping),
                "unmapped_observation_count": len(failed_observation_ids),
                "affected_case_count": affected_case_count,
                "mapping_strategy_counts": dict(sorted(strategy_counts.items())),
                "mapping_failure_counts": dict(sorted(failure_counts.items())),
            }
        )

    derived_cases: list[dict[str, Any]] = []
    domain_cases: list[hard_eval._DomainCase] = []
    immutable_source_rows: list[dict[str, Any]] = []
    immutable_derived_rows: list[dict[str, Any]] = []
    for source_case in source_cases:
        if not isinstance(source_case, Mapping):
            raise RuntimeError("source manifest case must be an object")
        immutable_source_rows.append(
            {field: source_case.get(field) for field in IMMUTABLE_CASE_FIELDS}
        )
        domain_case = hard_eval._DomainCase(
            case_id=_required_case_str(source_case, "case_id"),
            domain=_required_case_str(source_case, "domain"),
            intent_kind=_required_case_str(source_case, "intent_kind"),
            pattern=_required_case_str(source_case, "pattern"),
            result_kind=_required_case_str(source_case, "result_kind"),
            query_text=_required_case_str(source_case, "query_text"),
            requester_user_id=_required_case_str(source_case, "requester_user_id"),
            required_source_observation_ids=tuple(
                mapping[str(value)]
                for value in _case_string_list(
                    source_case,
                    "required_source_observation_ids",
                )
            ),
            forbidden_source_observation_ids=tuple(
                mapping[str(value)]
                for value in _case_string_list(
                    source_case,
                    "forbidden_source_observation_ids",
                )
            ),
            required_match_count=_required_case_int(
                source_case,
                "required_match_count",
            ),
            limit=_required_case_int(source_case, "limit"),
        )
        derived_case = domain_case.to_private_dict()
        derived_case["source_private_fingerprint"] = source_case.get("private_fingerprint")
        derived_cases.append(derived_case)
        domain_cases.append(domain_case)
        immutable_derived_rows.append(
            {field: derived_case.get(field) for field in IMMUTABLE_CASE_FIELDS}
        )
    immutable_source_hash = sha256_json(immutable_source_rows)
    immutable_derived_hash = sha256_json(immutable_derived_rows)
    if immutable_source_hash != immutable_derived_hash:
        raise RuntimeError("frozen case prompts changed during evidence remap")

    source_manifest_hash = sha256_json(source_manifest)
    derived_manifest = {
        "manifest_type": source_manifest.get("manifest_type"),
        "archive_sha256": source_manifest.get("archive_sha256"),
        "case_count": len(derived_cases),
        "cases": derived_cases,
        "generated_at": hard_eval.NOW,
        "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
        "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        "parser_version": bundle.mail_parse_run.parser_version,
        "policy_version": source_manifest.get("policy_version"),
        "lineage": {
            "source_manifest_hash": source_manifest_hash,
            "observation_mapping_hash": sha256_json(mapping),
            "immutable_case_hash": immutable_source_hash,
        },
    }
    return _MappedManifest(
        payload=derived_manifest,
        cases=domain_cases,
        mapping=mapping,
        strategy_counts=dict(sorted(strategy_counts.items())),
        source_manifest_hash=source_manifest_hash,
        derived_manifest_hash=sha256_json(derived_manifest),
        immutable_case_hash=immutable_source_hash,
    )


def _new_message_identity_indexes(
    bundle: MailEvidenceBundle,
) -> dict[str, dict[tuple[Any, ...], set[str]]]:
    message_by_id = {
        message.email_message_id: message for message in getattr(bundle, "messages", ())
    }
    indexes: dict[str, dict[tuple[Any, ...], set[str]]] = {
        "fingerprint_message_folder": defaultdict(set),
        "message_folder": defaultdict(set),
        "stable_content": defaultdict(set),
    }
    for occurrence in getattr(bundle, "message_occurrences", ()):
        message = message_by_id.get(occurrence.email_message_id)
        if message is None:
            continue
        occurrence_id = occurrence.message_occurrence_id
        indexes["fingerprint_message_folder"][
            (
                message.message_fingerprint,
                message.message_id,
                occurrence.folder_path_hash,
            )
        ].add(occurrence_id)
        indexes["message_folder"][
            (
                message.message_id,
                occurrence.folder_path_hash,
            )
        ].add(occurrence_id)
        indexes["stable_content"][
            (
                occurrence.folder_path_hash,
                message.normalized_subject,
                message.sender,
                message.sent_at,
                message.body_hash,
            )
        ].add(occurrence_id)
    return indexes


def _resolve_complete_message_occurrence(
    old_observation: Observation,
    *,
    source_message: Observation | None,
    new_segments_by_occurrence: Mapping[str, Sequence[Any]],
    new_identity_indexes: Mapping[str, Mapping[tuple[Any, ...], set[str]]],
) -> tuple[str, str]:
    old_occurrence_id = _observation_occurrence_id(old_observation)
    if old_occurrence_id in new_segments_by_occurrence:
        return old_occurrence_id, "same_occurrence"

    old_location = dict(old_observation.location)
    old_payload = dict(old_observation.payload or {})
    if source_message is not None:
        old_location.update(source_message.location)
        old_payload.update(source_message.payload or {})
    keys = (
        (
            "stable_message_fingerprint",
            "fingerprint_message_folder",
            (
                old_payload.get("message_fingerprint"),
                old_location.get("message_id"),
                old_location.get("folder_path_hash"),
            ),
        ),
        (
            "stable_message_id",
            "message_folder",
            (
                old_location.get("message_id"),
                old_location.get("folder_path_hash"),
            ),
        ),
        (
            "stable_message_content",
            "stable_content",
            (
                old_location.get("folder_path_hash"),
                old_payload.get("normalized_subject"),
                old_payload.get("sender"),
                old_payload.get("sent_at"),
                old_payload.get("body_hash"),
            ),
        ),
    )
    for strategy, index_name, key in keys:
        if any(value is None for value in key):
            continue
        candidates = new_identity_indexes.get(index_name, {}).get(key, set())
        if len(candidates) == 1:
            return next(iter(candidates)), strategy
    raise RuntimeError("complete message identity is unavailable")


def _map_observation_to_complete_segment(
    old_observation: Observation,
    candidates: Sequence[Any],
) -> tuple[str, str]:
    if not candidates:
        raise RuntimeError("message occurrence is unavailable after complete reingestion")
    old_text = old_observation.text
    if not isinstance(old_text, str) or not old_text:
        raise RuntimeError("frozen observation text is unavailable")
    old_hash = sha256_json(old_text)
    old_index = old_observation.location.get("body_segment_index")
    exact_index = [
        candidate
        for candidate in candidates
        if candidate.body_segment_index == old_index and sha256_json(candidate.text) == old_hash
    ]
    if len(exact_index) == 1:
        return exact_index[0].source_observation_id, "same_index_content_hash"
    exact_hash = [candidate for candidate in candidates if sha256_json(candidate.text) == old_hash]
    if len(exact_hash) == 1:
        return exact_hash[0].source_observation_id, "same_occurrence_content_hash"

    joined, offsets = _candidate_text_stream(candidates)
    start = joined.find(old_text)
    if start < 0:
        normalized_old = old_text.replace("\r\n", "\n").replace("\r", "\n")
        normalized_joined, normalized_offsets = _candidate_text_stream(
            candidates,
            normalize_newlines=True,
        )
        start = normalized_joined.find(normalized_old)
        if start >= 0:
            joined = normalized_joined
            offsets = normalized_offsets
            old_text = normalized_old
        else:
            reconstructed = _reconstruct_historical_redacted_span(
                old_text,
                old_index=old_index,
                complete_body=normalized_joined,
            )
            if reconstructed is None:
                raise RuntimeError("frozen evidence could not be mapped without approximation")
            start, end = reconstructed
            return (
                _candidate_for_span(offsets, start=start, end=end).source_observation_id,
                "historical_redacted_content_hash",
            )
    end = start + len(old_text)
    return (
        _candidate_for_span(offsets, start=start, end=end).source_observation_id,
        "same_occurrence_substring_overlap",
    )


def _candidate_text_stream(
    candidates: Sequence[Any],
    *,
    normalize_newlines: bool = False,
) -> tuple[str, list[tuple[int, int, Any]]]:
    parts: list[str] = []
    offsets: list[tuple[int, int, Any]] = []
    cursor = 0
    for candidate in candidates:
        text = str(candidate.text)
        if normalize_newlines:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        candidate_end = cursor + len(text)
        parts.append(text)
        offsets.append((cursor, candidate_end, candidate))
        cursor = candidate_end
    return "".join(parts), offsets


def _candidate_for_span(
    offsets: Sequence[tuple[int, int, Any]],
    *,
    start: int,
    end: int,
) -> Any:
    ranked = sorted(
        (
            (
                -max(0, min(end, candidate_end) - max(start, candidate_start)),
                candidate.body_segment_index or 0,
                candidate.source_observation_id,
                candidate,
            )
            for candidate_start, candidate_end, candidate in offsets
            if min(end, candidate_end) > max(start, candidate_start)
        )
    )
    if not ranked or ranked[0][0] == 0:
        raise RuntimeError("frozen evidence overlap mapping failed")
    return ranked[0][3]


def _reconstruct_historical_redacted_span(
    old_text: str,
    *,
    old_index: Any,
    complete_body: str,
) -> tuple[int, int] | None:
    match = _REDACTED_BODY_SEGMENT.fullmatch(old_text)
    if match is None or not isinstance(old_index, int) or isinstance(old_index, bool):
        return None
    historical_segments = _historical_body_segment_spans(complete_body, max_chars=4000)
    if old_index <= 0 or old_index > len(historical_segments):
        return None
    start, end, historical_text = historical_segments[old_index - 1]
    if sha256_json(historical_text) != match.group(1):
        return None
    return start, end


def _historical_evidence_key(observation: Observation) -> tuple[int, str] | None:
    index = observation.location.get("body_segment_index")
    text = observation.text
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or index <= 0
        or not isinstance(text, str)
        or not text
    ):
        return None
    redacted_match = _REDACTED_BODY_SEGMENT.fullmatch(text)
    content_hash = redacted_match.group(1) if redacted_match else sha256_json(text)
    return index, content_hash


def _build_global_historical_evidence_index(
    segments_by_occurrence: Mapping[str, Sequence[Any]],
    *,
    required_keys: set[tuple[int, str]],
) -> dict[tuple[int, str], list[tuple[str, str]]]:
    index: dict[tuple[int, str], list[tuple[str, str]]] = defaultdict(list)
    if not required_keys:
        return index
    max_required_index = max(segment_index for segment_index, _ in required_keys)
    for occurrence_id, candidates in segments_by_occurrence.items():
        complete_body, offsets = _candidate_text_stream(
            candidates,
            normalize_newlines=True,
        )
        historical_segments = _historical_body_segment_spans(
            complete_body,
            max_chars=4000,
        )
        for segment_index, (start, end, text) in enumerate(
            historical_segments[:max_required_index],
            start=1,
        ):
            key = (segment_index, sha256_json(text))
            if key not in required_keys:
                continue
            mapped_candidate = _candidate_for_span(offsets, start=start, end=end)
            index[key].append(
                (
                    occurrence_id,
                    str(mapped_candidate.source_observation_id),
                )
            )
    return index


def _map_from_global_historical_evidence_index(
    observation: Observation,
    index: Mapping[tuple[int, str], Sequence[tuple[str, str]]],
) -> str | None:
    key = _historical_evidence_key(observation)
    if key is None:
        return None
    matches = index.get(key, ())
    if len(matches) != 1:
        return None
    return str(matches[0][1])


def _map_from_global_unique_exact_content(
    observation: Observation,
    segments_by_occurrence: Mapping[str, Sequence[Any]],
) -> str | None:
    old_text = observation.text
    if (
        not isinstance(old_text, str)
        or not old_text
        or _REDACTED_BODY_SEGMENT.fullmatch(old_text) is not None
    ):
        return None
    normalized_old = old_text.replace("\r\n", "\n").replace("\r", "\n")
    mapped_candidate_ids: set[str] = set()
    for candidates in segments_by_occurrence.values():
        complete_body, offsets = _candidate_text_stream(
            candidates,
            normalize_newlines=True,
        )
        start = 0
        while True:
            start = complete_body.find(normalized_old, start)
            if start < 0:
                break
            end = start + len(normalized_old)
            mapped_candidate_ids.add(
                str(
                    _candidate_for_span(
                        offsets,
                        start=start,
                        end=end,
                    ).source_observation_id
                )
            )
            if len(mapped_candidate_ids) > 1:
                return None
            start += max(1, len(normalized_old))
    if len(mapped_candidate_ids) != 1:
        return None
    return next(iter(mapped_candidate_ids))


def _historical_body_segment_spans(
    complete_body: str,
    *,
    max_chars: int,
) -> list[tuple[int, int, str]]:
    normalized = str(complete_body or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", normalized) if item.strip()]
    if not paragraphs:
        single = normalized.strip()
        paragraphs = [single] if single else []
    spans: list[tuple[int, int, str]] = []
    paragraph_cursor = 0
    for paragraph in paragraphs:
        paragraph_start = normalized.find(paragraph, paragraph_cursor)
        if paragraph_start < 0:
            raise RuntimeError("historical body segmentation could not be reconstructed")
        paragraph_cursor = paragraph_start + len(paragraph)
        for chunk_start in range(0, len(paragraph), max_chars):
            raw_chunk = paragraph[chunk_start : chunk_start + max_chars]
            chunk = raw_chunk.strip()
            if not chunk:
                continue
            leading_chars = len(raw_chunk) - len(raw_chunk.lstrip())
            start = paragraph_start + chunk_start + leading_chars
            spans.append((start, start + len(chunk), chunk))
    return spans


def _run_canaries(
    bundle: MailEvidenceBundle,
    cases: Sequence[hard_eval._DomainCase],
) -> dict[str, Any]:
    gateway = MailEvidenceQueryGateway([bundle])
    rows: list[dict[str, Any]] = []
    blocking: list[str] = []
    body_segments = [
        segment for segment in bundle.body_segments if segment.segment_source_type == "message_body"
    ]
    snippet_index = gateway._snippet_index_by_bundle_id[bundle.mail_evidence_bundle_id]
    token_counts = {
        token: len(indexes) for token, indexes in snippet_index.snippet_indexes_by_token.items()
    }

    long_tail = _long_tail_canary(body_segments, token_counts)
    rows.append(
        _execute_query_canary(
            "long_mail_tail",
            long_tail,
            gateway=gateway,
            bundle=bundle,
        )
    )
    cross_segment = _cross_segment_canary(body_segments, token_counts)
    rows.append(
        _execute_query_canary(
            "cross_segment",
            cross_segment,
            gateway=gateway,
            bundle=bundle,
            read_full_messages=True,
        )
    )
    attachment = _attachment_canary(bundle, token_counts)
    rows.append(
        _execute_query_canary(
            "text_attachment",
            attachment,
            gateway=gateway,
            bundle=bundle,
        )
    )
    owner_case = next(
        (
            case
            for case in cases
            if case.result_kind == "owner_match" and len(case.required_source_observation_ids) >= 2
        ),
        None,
    )
    rows.append(
        _execute_query_canary(
            "cross_message",
            (
                (
                    owner_case.query_text,
                    set(owner_case.required_source_observation_ids),
                )
                if owner_case is not None
                else None
            ),
            gateway=gateway,
            bundle=bundle,
        )
    )
    coo_query = "有03.80503G301的COO或產地嗎"
    coo_targets = _coo_canary_target_ids(snippet_index)
    rows.append(
        _execute_query_canary(
            "coo_item_query",
            (coo_query, coo_targets),
            gateway=gateway,
            bundle=bundle,
        )
    )
    negative = gateway.query_mail_evidence(
        query_text="formowl_absence_probe_7f3ea70d4f8b",
        requester_user_id=bundle.mail_import_session.owner_user_id,
        workspace_id=bundle.mail_import_session.workspace_id,
        session_id=hard_eval.SESSION_ID,
        mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
        limit=10,
    )
    negative_passed = (
        negative.status == "ok"
        and not negative.evidence_snippets
        and negative.answerability_state == "source_incomplete"
    )
    rows.append(
        {
            "canary_id": "negative_claim_fail_closed",
            "status": "passed" if negative_passed else "failed",
            "target_count": 0,
            "matched_target_count": 0,
            "citation_count": len(negative.citations),
            "evidence_completeness": negative.evidence_completeness,
            "answerability_state": negative.answerability_state,
            "response_hash": sha256_json(negative.to_dict()),
        }
    )

    for row in rows:
        if (
            row["canary_id"] in {"text_attachment", "cross_message"}
            and row["status"] == "not_applicable"
        ):
            continue
        if row["status"] != "passed":
            blocking.append(str(row["canary_id"]))
    return {"rows": rows, "blocking_canary_ids": sorted(blocking)}


def _coo_canary_target_ids(snippet_index: Any) -> set[str]:
    identifier_token = "03.80503g301"
    origin_tokens = {"coo", "產地", "origin"}
    return {
        str(indexed.payload["source_observation_id"])
        for indexed in snippet_index.snippets
        if indexed.payload.get("segment_source_type") == "message_body"
        and identifier_token in indexed.searchable_tokens
        and origin_tokens.intersection(indexed.searchable_tokens)
    }


def _execute_query_canary(
    canary_id: str,
    canary: tuple[str, set[str]] | None,
    *,
    gateway: MailEvidenceQueryGateway,
    bundle: MailEvidenceBundle,
    read_full_messages: bool = False,
) -> dict[str, Any]:
    if canary is None:
        return {
            "canary_id": canary_id,
            "status": "not_applicable",
            "target_count": 0,
            "matched_target_count": 0,
            "citation_count": 0,
            "evidence_completeness": "unknown",
            "answerability_state": "unknown",
            "response_hash": sha256_json({"canary_id": canary_id, "status": "not_applicable"}),
        }
    query_text, target_ids = canary
    result = gateway.query_mail_evidence(
        query_text=query_text,
        requester_user_id=bundle.mail_import_session.owner_user_id,
        workspace_id=bundle.mail_import_session.workspace_id,
        session_id=hard_eval.SESSION_ID,
        mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
        limit=10,
    )
    evidence_ids = {
        str(citation.get("source_observation_id"))
        for citation in result.citations
        if isinstance(citation, Mapping) and citation.get("source_observation_id")
    }
    evidence_completeness = result.evidence_completeness
    answerability_state = result.answerability_state
    response_payload: dict[str, Any] = {"query": result.to_dict()}
    read_status: str | None = None
    if read_full_messages and result.status == "ok":
        message_ids = sorted(
            {
                str(snippet.get("email_message_id"))
                for snippet in result.evidence_snippets
                if isinstance(snippet, Mapping) and snippet.get("email_message_id")
            }
        )
        if message_ids:
            read_result = gateway.read_mail_evidence(
                requester_user_id=bundle.mail_import_session.owner_user_id,
                workspace_id=bundle.mail_import_session.workspace_id,
                session_id=hard_eval.SESSION_ID,
                mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
                email_message_ids=message_ids,
            )
            read_status = read_result.status
            evidence_ids = {
                str(segment.get("source_observation_id"))
                for segment in read_result.evidence_segments
                if isinstance(segment, Mapping) and segment.get("source_observation_id")
            }
            evidence_completeness = read_result.evidence_completeness
            answerability_state = read_result.answerability_state
            response_payload["read"] = read_result.to_dict()
    matched = target_ids & evidence_ids
    passed = (
        result.status == "ok"
        and (not read_full_messages or read_status == "ok")
        and bool(target_ids)
        and matched == target_ids
    )
    return {
        "canary_id": canary_id,
        "status": "passed" if passed else "failed",
        "target_count": len(target_ids),
        "matched_target_count": len(matched),
        "citation_count": len(result.citations),
        "evidence_completeness": evidence_completeness,
        "answerability_state": answerability_state,
        "response_hash": sha256_json(response_payload),
    }


def _long_tail_canary(
    body_segments: Sequence[Any],
    token_counts: Mapping[str, int],
) -> tuple[str, set[str]] | None:
    for segment in body_segments:
        if (segment.body_segment_index or 0) <= 3:
            continue
        tokens = sorted(
            token
            for token in configured_mail_candidate_admission_tokens(segment.text)
            if token_counts.get(token, 0) <= 2
        )
        if tokens:
            return tokens[0], {segment.source_observation_id}
    return None


def _cross_segment_canary(
    body_segments: Sequence[Any],
    token_counts: Mapping[str, int],
) -> tuple[str, set[str]] | None:
    by_message: dict[str, list[Any]] = defaultdict(list)
    for segment in body_segments:
        by_message[segment.email_message_id].append(segment)
    for segments in by_message.values():
        segments.sort(key=lambda item: item.body_segment_index or 0)
        for left, right in zip(segments, segments[1:]):
            left_tokens = sorted(
                token
                for token in configured_mail_candidate_admission_tokens(left.text)
                if token_counts.get(token, 0) <= 2
            )
            right_tokens = sorted(
                token
                for token in configured_mail_candidate_admission_tokens(right.text)
                if token_counts.get(token, 0) <= 2 and token not in left_tokens
            )
            if left_tokens and right_tokens:
                return (
                    f"{left_tokens[0]} {right_tokens[0]}",
                    {left.source_observation_id, right.source_observation_id},
                )
    return None


def _attachment_canary(
    bundle: MailEvidenceBundle,
    token_counts: Mapping[str, int],
) -> tuple[str, set[str]] | None:
    for segment in bundle.body_segments:
        if segment.segment_source_type != "attachment_text":
            continue
        tokens = sorted(
            token
            for token in configured_mail_candidate_admission_tokens(segment.text)
            if token_counts.get(token, 0) <= 2
        )
        if tokens:
            return tokens[0], {segment.source_observation_id}
    return None


def _bundle_from_existing_observations(
    *,
    stores: Any,
    source_asset: Any,
    source_session: Any,
) -> MailEvidenceBundle:
    jobs = [
        job
        for job in stores.job_store.list()
        if job.asset_id == source_asset.asset_id and job.status == "succeeded"
    ]
    if len(jobs) != 1:
        raise RuntimeError("resume work directory must contain one succeeded ingestion job")
    job = jobs[0]
    observation_ids = set(job.observation_ids)
    observations = [
        observation
        for observation in stores.observation_store.list()
        if observation.observation_id in observation_ids
    ]
    if len(observations) != len(observation_ids):
        raise RuntimeError("resume work directory observations are incomplete")
    extractor_run_ids = set(job.extractor_run_ids)
    extractor_runs = [
        extractor_run
        for extractor_run in stores.extractor_run_store.list()
        if extractor_run.extractor_run_id in extractor_run_ids
    ]
    if len(extractor_runs) != 1:
        raise RuntimeError("resume work directory must contain one extractor run")
    extractor_run = extractor_runs[0]
    return build_mail_evidence_bundle(
        observations,
        workspace_id=source_session.workspace_id,
        owner_user_id=source_session.actor_user_id,
        source_asset_id=source_asset.asset_id,
        archive_sha256=source_asset.content_hash,
        producer_type="server_side_parser",
        parser_name=extractor_run.extractor_name,
        parser_version=extractor_run.extractor_version,
        upload_session_id=source_session.upload_session_id,
        retention_policy="retain_7_days",
        raw_archive_retention_decision="retained_by_policy",
        created_at=source_session.created_at,
        started_at=extractor_run.started_at,
        completed_at=extractor_run.completed_at,
        parse_warnings=extractor_run.warnings,
    )


def _load_source_asset_and_session(
    source_work_dir: Path,
    *,
    archive_sha256: str,
) -> tuple[Any, Any]:
    source_data_dir = source_work_dir / "data"
    assets = [
        asset
        for asset in AssetStore(source_data_dir).list()
        if asset.content_hash == archive_sha256
    ]
    if len(assets) != 1:
        raise RuntimeError("source work directory must contain one matching asset")
    sessions = [
        session
        for session in UploadSessionStore(source_data_dir).list()
        if session.asset_id == assets[0].asset_id
    ]
    if len(sessions) != 1:
        raise RuntimeError("source work directory must contain one matching upload session")
    return assets[0], sessions[0]


def _observation_occurrence_id(observation: Observation) -> str:
    location_value = observation.location.get("message_occurrence_id")
    payload_value = (
        observation.payload.get("message_occurrence_id")
        if isinstance(observation.payload, Mapping)
        else None
    )
    value = location_value or payload_value
    if not isinstance(value, str) or not value:
        raise RuntimeError("frozen observation lacks message occurrence identity")
    return value


def _observation_has_message_identity(observation: Observation) -> bool:
    payload = observation.payload if isinstance(observation.payload, Mapping) else {}
    return all(
        isinstance(value, str) and bool(value)
        for value in (
            payload.get("message_fingerprint"),
            observation.location.get("message_id"),
            observation.location.get("folder_path_hash"),
        )
    )


def _required_case_str(case: Mapping[str, Any], field_name: str) -> str:
    value = case.get(field_name)
    if not isinstance(value, str) or not value:
        raise RuntimeError("frozen case field is invalid")
    return value


def _required_case_int(case: Mapping[str, Any], field_name: str) -> int:
    value = case.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError("frozen case integer field is invalid")
    return value


def _case_string_list(case: Mapping[str, Any], field_name: str) -> list[str]:
    value = case.get(field_name, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise RuntimeError("frozen case evidence ids are invalid")
    return value


def _prepare_work_dir(path: Path) -> None:
    hard_eval._prepare_work_dir(path)


def _pst_header_ok(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) == b"!BDN"


def _implementation_source_hash() -> str:
    hashes = {}
    for relative in SOURCE_FILES:
        path = ROOT / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[relative] = "sha256:" + digest
    return sha256_json(hashes)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("JSON root must be an object")
    return payload


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(rendered, encoding="utf-8")
    temp_path.replace(path)


def _write_public_json(path: Path, payload: Mapping[str, Any]) -> None:
    assert_no_public_raw_references(payload, "real_pst_domain_hard_100_rebuild_output")
    _write_private_json(path, payload)


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{context} must be an object")
    return value


def _required_str(value: Mapping[str, Any], field_name: str) -> str:
    item = value.get(field_name)
    if not isinstance(item, str) or not item:
        raise RuntimeError(f"{field_name} must be a string")
    return item


def _required_int(value: Mapping[str, Any], field_name: str) -> int:
    item = value.get(field_name)
    if not isinstance(item, int) or isinstance(item, bool):
        raise RuntimeError(f"{field_name} must be an integer")
    return item


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pst", type=Path, required=True)
    parser.add_argument("--source-work-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=lock_script.DEFAULT_LOCK)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume-existing-work", action="store_true")
    args = parser.parse_args(argv)

    report = rebuild_complete_evidence(
        pst_path=args.pst,
        source_work_dir=args.source_work_dir,
        source_manifest_path=args.source_manifest,
        lock_path=args.lock,
        work_dir=args.work_dir,
        resume_existing_work=args.resume_existing_work,
    )
    _write_public_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
