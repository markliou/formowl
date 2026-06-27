#!/usr/bin/env python3
"""Multimodal enterprise validation recovery controls.

This deterministic fixture validates the control shape needed for finance
tables, mail, meetings, video/OCR, business decisions, and cross-modal
permission probes. It does not claim real enterprise pilot evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
REQUIRED_MODALITIES = {"spreadsheet", "mail", "meeting_audio", "video_ocr"}


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def row_hash(row: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in row.items() if key != "row_sha256"})


def with_row_hash(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["row_sha256"] = row_hash(payload)
    return payload


def default_fixture() -> dict[str, Any]:
    source_artifacts = [
        {
            "source_id": "src_xlsx_finance_001",
            "modality": "spreadsheet",
            "artifact_sha256": "1" * 64,
            "text_proxy_only": False,
            "enterprise_real_data": False,
        },
        {
            "source_id": "src_mail_invoice_001",
            "modality": "mail",
            "artifact_sha256": "2" * 64,
            "text_proxy_only": False,
            "enterprise_real_data": False,
        },
        {
            "source_id": "src_meeting_audio_001",
            "modality": "meeting_audio",
            "artifact_sha256": "3" * 64,
            "text_proxy_only": False,
            "enterprise_real_data": False,
        },
        {
            "source_id": "src_video_keyframe_001",
            "modality": "video_ocr",
            "artifact_sha256": "4" * 64,
            "text_proxy_only": False,
            "enterprise_real_data": False,
        },
    ]
    source_by_modality = {row["modality"]: row for row in source_artifacts}
    validation_rows = [
        with_row_hash(
            {
                "validation_id": "val_finance_amount_due",
                "modality": "spreadsheet",
                "source_id": source_by_modality["spreadsheet"]["source_id"],
                "source_artifact_sha256": source_by_modality["spreadsheet"]["artifact_sha256"],
                "task": "financial_table_amount_due",
                "candidate_id": "cand_obligation_001",
                "human_adjudicated": False,
            }
        ),
        with_row_hash(
            {
                "validation_id": "val_mail_invoice_chain",
                "modality": "mail",
                "source_id": source_by_modality["mail"]["source_id"],
                "source_artifact_sha256": source_by_modality["mail"]["artifact_sha256"],
                "task": "mail_thread_obligation_evidence",
                "candidate_id": "cand_mail_claim_001",
                "human_adjudicated": False,
            }
        ),
        with_row_hash(
            {
                "validation_id": "val_meeting_decision_audio",
                "modality": "meeting_audio",
                "source_id": source_by_modality["meeting_audio"]["source_id"],
                "source_artifact_sha256": source_by_modality["meeting_audio"]["artifact_sha256"],
                "task": "meeting_decision_transcript",
                "candidate_id": "cand_decision_001",
                "human_adjudicated": False,
            }
        ),
        with_row_hash(
            {
                "validation_id": "val_video_keyframe_status",
                "modality": "video_ocr",
                "source_id": source_by_modality["video_ocr"]["source_id"],
                "source_artifact_sha256": source_by_modality["video_ocr"]["artifact_sha256"],
                "task": "video_keyframe_ocr_status",
                "candidate_id": "cand_status_001",
                "human_adjudicated": False,
            }
        ),
    ]
    business_decision_rows = [
        with_row_hash(
            {
                "decision_candidate_id": "cand_decision_001",
                "source_validation_ids": [
                    "val_finance_amount_due",
                    "val_mail_invoice_chain",
                    "val_meeting_decision_audio",
                    "val_video_keyframe_status",
                ],
                "adjudication_status": "requires_human_review",
                "autonomous_business_judgment": False,
            }
        )
    ]
    return {
        "artifact_id": "multimodal_enterprise_fixture_v1",
        "real_enterprise_pilot_present": False,
        "source_artifacts": source_artifacts,
        "validation_rows": validation_rows,
        "business_decision_rows": business_decision_rows,
        "permission_probe": {
            "probe_id": "cross_modal_permission_probe_001",
            "grant_id": "grant_finance_snippet_001",
            "revoked_grant_visible_count": 0,
            "cross_modal_private_leak_count": 0,
            "raw_asset_access_observed": False,
        },
        "human_adjudication_packet_present": False,
    }


def validate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    source_artifacts = fixture.get("source_artifacts", [])
    if not isinstance(source_artifacts, list) or not source_artifacts:
        blockers.append("multimodal source artifacts missing")
        source_artifacts = []
    source_by_id = {}
    modalities = set()
    for row in source_artifacts:
        if not isinstance(row, dict):
            blockers.append("source artifact row malformed")
            continue
        source_id = row.get("source_id")
        if source_id in source_by_id:
            blockers.append("duplicate source artifact id")
        source_by_id[source_id] = row
        modality = row.get("modality")
        modalities.add(modality)
        if modality not in REQUIRED_MODALITIES:
            blockers.append("source artifact modality unsupported")
        if not isinstance(row.get("artifact_sha256"), str) or len(row["artifact_sha256"]) != 64:
            blockers.append("source artifact sha256 missing")
        if row.get("text_proxy_only") is not False:
            blockers.append("source artifact is text-proxy-only")
    missing_modalities = sorted(REQUIRED_MODALITIES - modalities)
    if missing_modalities:
        blockers.append("missing required modalities: " + ", ".join(missing_modalities))

    validation_rows = fixture.get("validation_rows", [])
    if not isinstance(validation_rows, list) or not validation_rows:
        blockers.append("multimodal validation rows missing")
        validation_rows = []
    validation_ids = set()
    row_modalities = set()
    for row in validation_rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("validation row hash mismatch")
            continue
        validation_id = row.get("validation_id")
        if validation_id in validation_ids:
            blockers.append("duplicate validation id")
        validation_ids.add(validation_id)
        modality = row.get("modality")
        row_modalities.add(modality)
        source = source_by_id.get(row.get("source_id"))
        if not source:
            blockers.append("validation row references unknown source artifact")
        else:
            if row.get("source_artifact_sha256") != source.get("artifact_sha256"):
                blockers.append("validation row source artifact hash mismatch")
            if row.get("modality") != source.get("modality"):
                blockers.append("validation row modality/source mismatch")
        if not isinstance(row.get("candidate_id"), str) or not row["candidate_id"]:
            blockers.append("validation row candidate id missing")
    missing_validation_modalities = sorted(REQUIRED_MODALITIES - row_modalities)
    if missing_validation_modalities:
        blockers.append(
            "validation rows missing modalities: " + ", ".join(missing_validation_modalities)
        )

    decision_rows = fixture.get("business_decision_rows", [])
    if not isinstance(decision_rows, list) or not decision_rows:
        blockers.append("business decision candidate rows missing")
        decision_rows = []
    for row in decision_rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("business decision row hash mismatch")
            continue
        source_validation_ids = row.get("source_validation_ids")
        if not isinstance(source_validation_ids, list) or not source_validation_ids:
            blockers.append("business decision row lacks source validation ids")
        elif not set(source_validation_ids).issubset(validation_ids):
            blockers.append("business decision row references unknown validation id")
        if row.get("adjudication_status") != "requires_human_review":
            blockers.append("business decision row does not require human review")
        if row.get("autonomous_business_judgment") is not False:
            blockers.append("business decision row allows autonomous judgment")

    probe = fixture.get("permission_probe", {})
    if not isinstance(probe, dict) or not probe:
        blockers.append("cross-modal permission probe missing")
        probe = {}
    if probe.get("revoked_grant_visible_count") != 0:
        blockers.append("cross-modal permission probe exposes revoked grant content")
    if probe.get("cross_modal_private_leak_count") != 0:
        blockers.append("cross-modal permission probe leaks private content")
    if probe.get("raw_asset_access_observed") is not False:
        blockers.append("cross-modal permission probe exposes raw asset access")

    metrics = {
        "source_artifact_count": len(source_artifacts),
        "covered_modality_count": len(modalities & REQUIRED_MODALITIES),
        "validation_row_count": len(validation_rows),
        "business_decision_row_count": len(decision_rows),
        "cross_modal_private_leak_count": probe.get("cross_modal_private_leak_count"),
        "real_enterprise_pilot_present": fixture.get("real_enterprise_pilot_present") is True,
        "human_adjudication_packet_present": fixture.get("human_adjudication_packet_present")
        is True,
    }
    return {
        "passed": not blockers,
        "blockers": sorted(set(blockers)),
        "metrics": metrics,
    }


def build_report(fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    fixture = fixture or default_fixture()
    validation = validate_fixture(fixture)
    return {
        "artifact_id": "multimodal_enterprise_recovery_v1",
        "fixture_sha256": sha256_json(fixture),
        "passed": validation["passed"],
        "metrics": validation["metrics"],
        "blockers": validation["blockers"],
        "claim_boundary": {
            "supports_multimodal_control_fixture_claim": validation["passed"],
            "supports_real_enterprise_multimodal_claim": False,
            "supports_multimodal_human_adjudication_completed_claim": False,
            "supports_financial_advice_or_autonomous_business_judgment_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "multimodal_enterprise_recovery.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
