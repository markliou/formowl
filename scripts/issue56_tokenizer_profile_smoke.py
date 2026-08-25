#!/usr/bin/env python3
"""Run the bounded Issue #56 packaged tokenizer Observation-to-index POC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import Observation, sha256_json  # noqa: E402
from formowl_core import (  # noqa: E402
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_core.methodology_authority import check_methodology_authority  # noqa: E402
from formowl_mail import (  # noqa: E402
    MailEvidenceQueryGateway,
    build_mail_evidence_bundle,
    build_mail_evidence_pack,
    search_mail_evidence,
)
from formowl_mail import evidence as mail_evidence_runtime  # noqa: E402
from formowl_mail import query as mail_query_runtime  # noqa: E402
from formowl_mail.query import build_existing_observation_snippet_index  # noqa: E402

_CREATED_AT = "2026-08-18T00:00:00+00:00"
_PROFILE_DIRECTORY = (
    PYTHON_ROOT
    / "formowl_core"
    / "tokenizer_profiles"
    / JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
)
_OBSERVATION_TEXT = (
    "授權觀察記錄採購單 ZX-2048-ALPHA 的交期更新，"
    "責任人 owner42@example.test，截止 2026-09-30，"
    "證據 www.example.test/cases/ZX-2048-ALPHA。"
)
_QUERY_TEXT = "查詢 ZX-2048-ALPHA 的交期與 2026-09-30 截止日期"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = run_smoke()
    serialized = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


def run_smoke() -> dict[str, Any]:
    """Execute one synthetic authorized Observation through the packaged index."""

    profile = load_issue56_target_mail_tokenizer_profile()
    observations = _synthetic_authorized_observations()
    bundle = build_mail_evidence_bundle(
        observations,
        workspace_id="workspace_issue56_tokenizer_poc",
        owner_user_id="user_issue56_tokenizer_owner",
        source_asset_id="asset_issue56_synthetic_observation",
        archive_sha256="sha256:" + ("a" * 64),
        producer_type="fixture_parser",
        parser_name="existing_observation_bridge_no_parser",
        parser_version="issue56_tokenizer_profile_poc_v1",
        created_at=_CREATED_AT,
        started_at=_CREATED_AT,
        completed_at=_CREATED_AT,
    )
    first_index, first_manifest = build_existing_observation_snippet_index(
        observations,
        bundle=bundle,
        tokenizer_profile=profile,
    )
    second_index, second_manifest = build_existing_observation_snippet_index(
        observations,
        bundle=bundle,
        tokenizer_profile=profile,
    )
    if first_manifest.to_safe_dict() != second_manifest.to_safe_dict():
        raise RuntimeError("Issue #56 tokenizer index rerun was not deterministic")
    if first_index.index_fingerprint != second_index.index_fingerprint:
        raise RuntimeError("Issue #56 tokenizer index fingerprint drifted on rerun")

    first_pack = build_mail_evidence_pack(observations, created_at=_CREATED_AT)
    second_pack = build_mail_evidence_pack(observations, created_at=_CREATED_AT)
    first_gateway = MailEvidenceQueryGateway([bundle])
    second_gateway = MailEvidenceQueryGateway([bundle])
    query_result = first_gateway.query_mail_evidence(
        query_text=_QUERY_TEXT,
        requester_user_id=bundle.mail_import_session.owner_user_id,
        workspace_id=bundle.mail_import_session.workspace_id,
        session_id="session_issue56_tokenizer_poc",
        mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
        now=_CREATED_AT,
    )
    evidence_results = search_mail_evidence(first_pack, query=_QUERY_TEXT)
    if query_result.status != "ok" or not query_result.evidence_snippets:
        raise RuntimeError("Issue #56 tokenizer E2E query did not resolve evidence")
    if not evidence_results:
        raise RuntimeError("Issue #56 tokenizer E2E evidence pack did not resolve evidence")

    first_gateway_index_fingerprint = first_gateway.index_fingerprints[
        bundle.mail_evidence_bundle_id
    ]
    second_gateway_index_fingerprint = second_gateway.index_fingerprints[
        bundle.mail_evidence_bundle_id
    ]
    if first_gateway_index_fingerprint != second_gateway_index_fingerprint:
        raise RuntimeError("Issue #56 generic query index fingerprint drifted on rerun")
    if first_pack.index_fingerprint != second_pack.index_fingerprint:
        raise RuntimeError("Issue #56 generic evidence index fingerprint drifted on rerun")
    runtime_profile_fingerprints = {
        profile.profile_fingerprint,
        first_gateway.tokenizer_profile_fingerprint,
        first_pack.profile_fingerprint,
        mail_query_runtime.MAIL_TOKENIZER_PROFILE_FINGERPRINT,
        mail_evidence_runtime.MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    }
    if runtime_profile_fingerprints != {profile.profile_fingerprint}:
        raise RuntimeError("Issue #56 generic query/evidence profile fingerprints differ")
    if {
        mail_query_runtime.MAIL_TOKENIZER_ID,
        mail_evidence_runtime.MAIL_TOKENIZER_ID,
        first_pack.analysis_profile_id,
    } != {JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID}:
        raise RuntimeError("Issue #56 generic mail runtime did not load the target profile")
    query_runtime_tokens = mail_query_runtime._tokenize(_QUERY_TEXT)
    evidence_runtime_tokens = mail_evidence_runtime._tokenize(_QUERY_TEXT)
    if query_runtime_tokens != evidence_runtime_tokens or not {
        "zx-2048-alpha",
        "交期",
    }.issubset(query_runtime_tokens):
        raise RuntimeError("Issue #56 generic runtime used a non-target tokenization path")

    analysis = profile.analyze(_OBSERVATION_TEXT)
    protected_by_kind = {
        span.identifier_kind: span.exact_token for span in analysis.protected_identifiers
    }
    expected_protected = {
        "business_identifier": "zx-2048-alpha",
        "date": "2026-09-30",
        "email": "owner42@example.test",
        "url": "www.example.test/cases/zx-2048-alpha",
    }
    if protected_by_kind != expected_protected:
        raise RuntimeError("Issue #56 protected identifier admission is incomplete")

    manifest = first_manifest.to_safe_dict()
    if (
        manifest["input_kind"] != "existing_observations_only"
        or manifest["query_profile_fingerprint"] != profile.profile_fingerprint
        or manifest["evidence_profile_fingerprint"] != profile.profile_fingerprint
        or manifest["raw_pst_read_count"] != 0
        or manifest["pst_parser_invocation_count"] != 0
        or manifest["new_extractor_run_count"] != 0
        or manifest["missing_lineage_count"] != 0
    ):
        raise RuntimeError("Issue #56 tokenizer index violated the POC boundary")

    authority = check_methodology_authority(repository_root=ROOT).to_safe_dict()
    if not authority["authority_valid"] or authority["methodology_ready"]:
        raise RuntimeError("Issue #56 tokenizer POC requires valid blocked authority")

    return {
        "artifact_id": "formowl_issue56_tokenizer_profile_smoke_v1",
        "schema_version": 1,
        "issue": 56,
        "work_package": "A",
        "slice": "packaged_frozen_tokenizer_profile_poc_v1",
        "status": "passed",
        "claim_state": "diagnostic_poc_only",
        "profile": {
            "tokenizer_id": profile.tokenizer_id,
            "profile_fingerprint": profile.profile_fingerprint,
            "fingerprint_payload_sha256": sha256_json(profile.fingerprint_payload()),
            "artifact_manifest_sha256": profile.artifact_manifest_sha256,
            "calibration_corpus_sha256": profile.calibration_corpus_sha256,
            "jieba_dictionary_sha256": profile.jieba_dictionary_sha256,
            "jieba_user_dictionary_sha256": profile.jieba_user_dictionary_sha256,
            "sentencepiece_model_sha256": profile.model_sha256,
            "sentencepiece_vocabulary_artifact_sha256": (
                profile.sentencepiece_vocabulary_artifact_sha256
            ),
            "dependency_requirements_sha256": profile.dependency_requirements_sha256,
            "dependency_versions_sha256": profile.dependency_versions_sha256,
        },
        "e2e": {
            "source_kind": "tracked_synthetic_authorized_observations",
            "observation_count": manifest["observation_count"],
            "input_kind": manifest["input_kind"],
            "query_status": query_result.status,
            "evidence_snippet_count": len(query_result.evidence_snippets),
            "evidence_pack_result_count": len(evidence_results),
            "query_profile_fingerprint": first_gateway.tokenizer_profile_fingerprint,
            "evidence_profile_fingerprint": first_pack.profile_fingerprint,
            "observation_index_fingerprint": manifest["index_fingerprint"],
            "rerun_observation_index_fingerprint": second_manifest.index_fingerprint,
            "query_index_fingerprint": first_gateway_index_fingerprint,
            "rerun_query_index_fingerprint": second_gateway_index_fingerprint,
            "evidence_index_fingerprint": first_pack.index_fingerprint,
            "rerun_evidence_index_fingerprint": second_pack.index_fingerprint,
            "rerun_deterministic": True,
            "ascii_fallback_used": False,
            "query_runtime_tokens": sorted(query_runtime_tokens),
            "raw_source_read_count": manifest["raw_pst_read_count"],
            "parser_invocation_count": manifest["pst_parser_invocation_count"],
            "new_extractor_run_count": manifest["new_extractor_run_count"],
            "protected_identifier_kinds": sorted(expected_protected),
        },
        "drift_probe": {
            "artifact_drift_rejected": _artifact_drift_is_rejected(),
        },
        "methodology_authority": {
            "status": authority["status"],
            "methodology_ready": authority["methodology_ready"],
            "blocking_gate_ids": authority["blocking_gate_ids"],
        },
        "limitations": [
            "synthetic_authorized_observations_only",
            "no_raw_source_or_oracle_completeness_claim",
            "no_strong_rag_or_hybrid_comparison",
            "no_production_or_issue56_completion_claim",
        ],
    }


def _synthetic_authorized_observations() -> list[Observation]:
    permission_scope = {
        "scope_type": "project",
        "visibility": "restricted",
        "scope_id": "project_issue56_tokenizer_poc",
    }
    common_location = {
        "archive_id": "archive_issue56_synthetic",
        "mailbox_id": "mailbox_issue56_synthetic",
        "folder_path_hash": "sha256:" + ("b" * 64),
        "message_id": "issue56-synthetic-001@example.test",
        "message_occurrence_id": "mailocc_issue56_synthetic_001",
    }
    message_fingerprint = sha256_json(
        {
            "message_id": "issue56-synthetic-001@example.test",
            "body": _OBSERVATION_TEXT,
        }
    )
    return [
        Observation.from_dict(
            {
                "observation_id": "obs_issue56_synthetic_message",
                "extractor_run_id": "extractor_run_issue56_synthetic_existing",
                "observation_type": "email_message",
                "modality": "mail",
                "location": {
                    **common_location,
                    "message_id": "issue56-synthetic-001@example.test",
                    "message_index": 1,
                },
                "confidence": 1.0,
                "permission_scope": permission_scope,
                "created_at": _CREATED_AT,
                "asset_id": "asset_issue56_synthetic_observation",
                "text": "Issue 56 synthetic authorized tokenizer observation",
                "payload": {
                    "subject": "採購單交期更新",
                    "normalized_subject": "採購單交期更新",
                    "sender": "owner42@example.test",
                    "sent_at": _CREATED_AT,
                    "message_fingerprint": message_fingerprint,
                    "body_hash": sha256_json(_OBSERVATION_TEXT),
                },
            }
        ),
        Observation.from_dict(
            {
                "observation_id": "obs_issue56_synthetic_body",
                "extractor_run_id": "extractor_run_issue56_synthetic_existing",
                "observation_type": "email_body_segment",
                "modality": "mail",
                "location": {
                    **common_location,
                    "body_segment_index": 0,
                },
                "confidence": 1.0,
                "permission_scope": permission_scope,
                "created_at": _CREATED_AT,
                "asset_id": "asset_issue56_synthetic_observation",
                "text": _OBSERVATION_TEXT,
            }
        ),
    ]


def _artifact_drift_is_rejected() -> bool:
    with tempfile.TemporaryDirectory(prefix="formowl-issue56-tokenizer-drift-") as temp_dir:
        copied_profile = Path(temp_dir) / "profile"
        shutil.copytree(_PROFILE_DIRECTORY, copied_profile)
        model_path = copied_profile / "sentencepiece.model"
        model = bytearray(model_path.read_bytes())
        model[-1] ^= 1
        model_path.write_bytes(model)
        try:
            load_issue56_target_mail_tokenizer_profile(artifact_directory=copied_profile)
        except RuntimeError as exc:
            return str(exc) == "frozen tokenizer profile is unavailable"
    return False


if __name__ == "__main__":
    raise SystemExit(main())
