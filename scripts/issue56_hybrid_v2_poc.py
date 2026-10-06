#!/usr/bin/env python3
"""Run the bounded Issue #56 authorized Hybrid-RAG end-to-end POC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    Observation,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (  # noqa: E402
    DenseEmbeddingUnavailableError,
    issue56_target_dense_embedding_profile,
)
from formowl_core.tokenization import (  # noqa: E402
    MailCandidateAdmissionTokenizerProfile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_mail import (  # noqa: E402
    MailEvidenceBundle,
    build_authorized_hybrid_mail_index,
    build_mail_evidence_bundle,
    run_authorized_hybrid_mail_query,
)

WORKSPACE_ID = "workspace_issue56_hybrid_poc"
REQUESTER_USER_ID = "user_issue56_authorized"
AUTHORIZED_OWNER_USER_ID = REQUESTER_USER_ID
DENIED_OWNER_USER_ID = "user_issue56_denied_owner"
CREATED_AT = "2026-08-18T06:00:00+00:00"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Return zero while preserving an explicit missing-E5 blocker.",
    )
    args = parser.parse_args(argv)
    report = run_poc()
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    if report["status"] == "passed" or args.allow_blocked:
        return 0
    return 2


def run_poc() -> dict[str, Any]:
    """Execute Observation-to-governed-result scenarios and return safe evidence."""

    declared_dense_profile = issue56_target_dense_embedding_profile()
    base = {
        "artifact_id": "formowl_issue56_hybrid_rag_e2e_poc_v2",
        "schema_version": 2,
        "issue": 56,
        "claim_state": "poc_only_not_methodology_or_production_completion",
        "fallback_used": False,
        "dense_retrieval": {
            "encoder_id": declared_dense_profile.encoder_id,
            "model_id": declared_dense_profile.model_id,
            "model_revision": declared_dense_profile.model_revision,
            "profile_fingerprint": declared_dense_profile.profile_fingerprint,
            "dimension": declared_dense_profile.dimension,
            "status": "pinned_real_e5_required",
        },
        "completion": {
            "issue56_complete": False,
            "methodology_complete": False,
            "production_ready": False,
        },
    }
    (
        authorized_observations,
        authorized_bundle,
        denied_observations,
        denied_bundle,
    ) = build_poc_inputs()
    observations_by_bundle_id = {
        authorized_bundle.mail_evidence_bundle_id: authorized_observations,
        denied_bundle.mail_evidence_bundle_id: denied_observations,
    }
    try:
        combined_index = build_authorized_hybrid_mail_index(
            observations_by_bundle_id=observations_by_bundle_id,
            bundles=(authorized_bundle, denied_bundle),
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
        )
        authorized_only_index = build_authorized_hybrid_mail_index(
            observations_by_bundle_id={
                authorized_bundle.mail_evidence_bundle_id: authorized_observations,
            },
            bundles=(authorized_bundle,),
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
        )
    except DenseEmbeddingUnavailableError as exc:
        report = {
            **base,
            "status": "blocked",
            "e2e_executed": False,
            "blocker": exc.reason_code,
        }
        assert_no_public_raw_references(report, "issue56_hybrid_rag_e2e_poc")
        return report
    direct = combined_index.query(
        query_text="PO470002002 交期",
        query_class="evidence_lookup",
    )
    direct_without_denied_bundle = authorized_only_index.query(
        query_text="PO470002002 交期",
        query_class="evidence_lookup",
    )
    cross_message = combined_index.query(
        query_text="PO470002002 交期 產地",
        query_class="evidence_lookup",
    )
    near_miss = combined_index.query(
        query_text="PO470002003 交期",
        query_class="evidence_lookup",
    )
    permission_denied = run_authorized_hybrid_mail_query(
        observations_by_bundle_id=observations_by_bundle_id,
        bundles=(authorized_bundle, denied_bundle),
        query_text="ZX900001999 付款條件",
        query_class="evidence_lookup",
        requester_user_id=REQUESTER_USER_ID,
        workspace_id=WORKSPACE_ID,
        mail_evidence_bundle_id=denied_bundle.mail_evidence_bundle_id,
    )
    exact_set = run_authorized_hybrid_mail_query(
        observations_by_bundle_id=observations_by_bundle_id,
        bundles=(authorized_bundle, denied_bundle),
        query_text="列出全部採購單並計數",
        query_class="exact_set_or_inventory",
        requester_user_id=REQUESTER_USER_ID,
        workspace_id=WORKSPACE_ID,
    )
    report = {
        **base,
        "status": "passed",
        "e2e_executed": True,
        "path_executed": [
            "authorized_observation",
            "source_preserving_mail_evidence_bundle",
            "same_profile_candidate_index",
            "bm25_candidate_retrieval",
            "pinned_multilingual_e5_candidate_retrieval",
            "deterministic_rank_fusion",
            "evidence_bundle_reranking",
            "governed_safe_result",
        ],
        "candidate_admission_profile": {
            "profile_id": combined_index.tokenizer_id,
            "profile_fingerprint": combined_index.profile_fingerprint,
            "query_evidence_profile_match": True,
        },
        "dense_retrieval": {
            **base["dense_retrieval"],
            "status": combined_index.dense_encoder_status,
            "execution_component_fingerprint": (combined_index.execution_component_fingerprint),
        },
        "permission_filter_invariance": {
            "denied_observation_materialized": False,
            "authorized_index_fingerprint_unchanged": (
                combined_index.index_fingerprint == authorized_only_index.index_fingerprint
            ),
            "authorized_result_scores_unchanged": (
                direct.to_safe_dict()["results"]
                == direct_without_denied_bundle.to_safe_dict()["results"]
            ),
        },
        "scenarios": {
            "direct_lookup": direct.to_safe_dict(),
            "cross_message_join": cross_message.to_safe_dict(),
            "near_miss_no_answer": near_miss.to_safe_dict(),
            "permission_denied": permission_denied.to_safe_dict(),
            "exact_set_route": exact_set.to_safe_dict(),
        },
        "completion": {**base["completion"], "focused_e2e_poc_executed": True},
    }
    assert_no_public_raw_references(report, "issue56_hybrid_rag_e2e_poc")
    return report


def build_poc_inputs() -> (
    tuple[
        tuple[Observation, ...],
        MailEvidenceBundle,
        tuple[Observation, ...],
        MailEvidenceBundle,
    ]
):
    """Create safe source-free Observations and their real evidence bundles."""

    authorized_observations = _mail_observations(
        namespace="authorized",
        messages=(
            ("交期更新", "PO470002002 交期 2026-09-30"),
            ("產地更新", "PO470002002 產地 台灣"),
        ),
    )
    denied_observations = _mail_observations(
        namespace="denied",
        messages=(("付款更新", "ZX900001999 付款條件 RESTRICTED-NEBULA-742"),),
    )
    authorized_bundle = _build_bundle(
        observations=authorized_observations,
        namespace="authorized",
        owner_user_id=AUTHORIZED_OWNER_USER_ID,
    )
    denied_bundle = _build_bundle(
        observations=denied_observations,
        namespace="denied",
        owner_user_id=DENIED_OWNER_USER_ID,
    )
    return (
        authorized_observations,
        authorized_bundle,
        denied_observations,
        denied_bundle,
    )


def load_target_profile() -> MailCandidateAdmissionTokenizerProfile:
    """Expose the Worker A public fail-closed profile loader to focused tests."""

    return load_issue56_target_mail_tokenizer_profile()


def _mail_observations(
    *,
    namespace: str,
    messages: Sequence[tuple[str, str]],
) -> tuple[Observation, ...]:
    archive_id = f"archive_issue56_{namespace}"
    mailbox_id = f"mailbox_issue56_{namespace}"
    folder_path_hash = sha256_json({"folder": namespace})
    asset_id = f"asset_issue56_{namespace}"
    extractor_run_id = f"extractor_run_issue56_{namespace}"
    permission_scope = {
        "scope_type": "project",
        "visibility": "restricted",
        "scope_id": f"project_issue56_{namespace}",
    }
    observations = [
        Observation(
            observation_id=f"obs_issue56_{namespace}_folder",
            extractor_run_id=extractor_run_id,
            observation_type="mail_folder_occurrence",
            modality="mail",
            location={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_index": 1,
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at=CREATED_AT,
            asset_id=asset_id,
            text="POC",
            payload={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_label": "POC",
            },
        )
    ]
    for index, (subject, body) in enumerate(messages, start=1):
        message_id = f"issue56-{namespace}-{index}@example.test"
        occurrence_id = f"mailocc_issue56_{namespace}_{index}"
        message_fingerprint = sha256_json({"namespace": namespace, "message_index": index})
        base_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": folder_path_hash,
            "message_id": message_id,
            "message_occurrence_id": occurrence_id,
            "thread_id": f"thread_issue56_{namespace}",
        }
        observations.extend(
            (
                Observation(
                    observation_id=f"obs_issue56_{namespace}_message_{index}",
                    extractor_run_id=extractor_run_id,
                    observation_type="email_message",
                    modality="mail",
                    location={**base_location, "message_index": index},
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at=CREATED_AT,
                    asset_id=asset_id,
                    text=subject,
                    payload={
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": base_location["thread_id"],
                        "subject": subject,
                        "normalized_subject": subject,
                        "sender": f"supplier-{namespace}@example.test",
                        "sent_at": CREATED_AT,
                        "body_hash": sha256_json(body),
                        "message_fingerprint": message_fingerprint,
                        "fingerprint_policy": "formowl_mail_fingerprint_v1",
                    },
                ),
                Observation(
                    observation_id=f"obs_issue56_{namespace}_body_{index}",
                    extractor_run_id=extractor_run_id,
                    observation_type="email_body_segment",
                    modality="mail",
                    location={**base_location, "body_segment_index": 1},
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at=CREATED_AT,
                    asset_id=asset_id,
                    text=body,
                    payload={
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": base_location["thread_id"],
                        "body_segment_index": 1,
                        "message_fingerprint": message_fingerprint,
                    },
                ),
            )
        )
    return tuple(observations)


def _build_bundle(
    *,
    observations: Sequence[Observation],
    namespace: str,
    owner_user_id: str,
) -> MailEvidenceBundle:
    return build_mail_evidence_bundle(
        observations,
        workspace_id=WORKSPACE_ID,
        owner_user_id=owner_user_id,
        source_asset_id=f"asset_issue56_{namespace}",
        archive_sha256=sha256_json({"archive": namespace}),
        producer_type="server_side_parser",
        parser_name="existing_observation_issue56_poc",
        parser_version="issue56_poc_v1",
        upload_session_id=f"upload_issue56_{namespace}",
        created_at=CREATED_AT,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
