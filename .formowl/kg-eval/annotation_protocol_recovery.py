#!/usr/bin/env python3
"""Human annotation/adjudication protocol recovery validator.

This validates protocol mechanics on deterministic fixtures. It does not claim
real human labels are present.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


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
    manifest_rows = [
        {
            "item_id": "ann_item_invoice_001",
            "task_id": "evidence_supported_claim",
            "source_ref": "obs_mail_invoice_001",
            "gold_label": "supported",
        },
        {
            "item_id": "ann_item_decision_001",
            "task_id": "business_decision_candidate",
            "source_ref": "obs_meeting_segment_004",
            "gold_label": "needs_review",
        },
    ]
    manifest_rows = [with_row_hash(row) for row in manifest_rows]
    manifest_sha256 = sha256_json(manifest_rows)
    work_order_rows = [
        with_row_hash(
            {
                "work_order_id": "wo_alpha_item_invoice",
                "reviewer_id": "reviewer_alpha",
                "role": "first_pass",
                "item_id": "ann_item_invoice_001",
                "manifest_row_sha256": manifest_rows[0]["row_sha256"],
            }
        ),
        with_row_hash(
            {
                "work_order_id": "wo_beta_item_invoice",
                "reviewer_id": "reviewer_beta",
                "role": "first_pass",
                "item_id": "ann_item_invoice_001",
                "manifest_row_sha256": manifest_rows[0]["row_sha256"],
            }
        ),
        with_row_hash(
            {
                "work_order_id": "wo_alpha_item_decision",
                "reviewer_id": "reviewer_alpha",
                "role": "first_pass",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_rows[1]["row_sha256"],
            }
        ),
        with_row_hash(
            {
                "work_order_id": "wo_beta_item_decision",
                "reviewer_id": "reviewer_beta",
                "role": "first_pass",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_rows[1]["row_sha256"],
            }
        ),
        with_row_hash(
            {
                "work_order_id": "wo_adjudicator_item_decision",
                "reviewer_id": "reviewer_gamma",
                "role": "adjudicator",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_rows[1]["row_sha256"],
            }
        ),
    ]
    first_pass_rows = [
        with_row_hash(
            {
                "submission_id": "alpha_invoice",
                "reviewer_id": "reviewer_alpha",
                "item_id": "ann_item_invoice_001",
                "work_order_id": "wo_alpha_item_invoice",
                "label": "supported",
                "generated_by_llm": False,
                "template_source": None,
            }
        ),
        with_row_hash(
            {
                "submission_id": "beta_invoice",
                "reviewer_id": "reviewer_beta",
                "item_id": "ann_item_invoice_001",
                "work_order_id": "wo_beta_item_invoice",
                "label": "supported",
                "generated_by_llm": False,
                "template_source": None,
            }
        ),
        with_row_hash(
            {
                "submission_id": "alpha_decision",
                "reviewer_id": "reviewer_alpha",
                "item_id": "ann_item_decision_001",
                "work_order_id": "wo_alpha_item_decision",
                "label": "supported",
                "generated_by_llm": False,
                "template_source": None,
            }
        ),
        with_row_hash(
            {
                "submission_id": "beta_decision",
                "reviewer_id": "reviewer_beta",
                "item_id": "ann_item_decision_001",
                "work_order_id": "wo_beta_item_decision",
                "label": "needs_review",
                "generated_by_llm": False,
                "template_source": None,
            }
        ),
    ]
    disagreement_set = [
        {
            "item_id": "ann_item_decision_001",
            "alpha_row_sha256": first_pass_rows[2]["row_sha256"],
            "beta_row_sha256": first_pass_rows[3]["row_sha256"],
        }
    ]
    disagreement_set_sha256 = sha256_json(disagreement_set)
    adjudication_rows = [
        with_row_hash(
            {
                "adjudication_id": "adj_decision",
                "adjudicator_id": "reviewer_gamma",
                "item_id": "ann_item_decision_001",
                "work_order_id": "wo_adjudicator_item_decision",
                "final_label": "needs_review",
                "sealed_disagreement_set_sha256": disagreement_set_sha256,
                "generated_by_llm": False,
                "template_source": None,
            }
        )
    ]
    return {
        "artifact_id": "annotation_protocol_fixture_v1",
        "real_human_packet_present": False,
        "manifest_sha256": manifest_sha256,
        "manifest_rows": manifest_rows,
        "work_order_rows": work_order_rows,
        "first_pass_rows": first_pass_rows,
        "first_pass_submission_artifacts": [
            {
                "reviewer_id": "reviewer_alpha",
                "sealed": True,
                "submission_row_sha256s": [
                    first_pass_rows[0]["row_sha256"],
                    first_pass_rows[2]["row_sha256"],
                ],
                "submission_set_sha256": sha256_json(
                    sorted(
                        [
                            first_pass_rows[0]["row_sha256"],
                            first_pass_rows[2]["row_sha256"],
                        ]
                    )
                ),
            },
            {
                "reviewer_id": "reviewer_beta",
                "sealed": True,
                "submission_row_sha256s": [
                    first_pass_rows[1]["row_sha256"],
                    first_pass_rows[3]["row_sha256"],
                ],
                "submission_set_sha256": sha256_json(
                    sorted(
                        [
                            first_pass_rows[1]["row_sha256"],
                            first_pass_rows[3]["row_sha256"],
                        ]
                    )
                ),
            },
        ],
        "adjudication_open_receipt": {
            "receipt_id": "adj_open_001",
            "opened_after_first_pass_seal": True,
            "manifest_sha256": manifest_sha256,
            "sealed_disagreement_set_sha256": disagreement_set_sha256,
        },
        "disagreement_set": disagreement_set,
        "adjudication_rows": adjudication_rows,
        "custody_receipt": {
            "receipt_id": "custody_001",
            "manifest_sha256": manifest_sha256,
            "first_pass_rows_sha256": sha256_json(first_pass_rows),
            "adjudication_rows_sha256": sha256_json(adjudication_rows),
            "sealed_disagreement_set_sha256": disagreement_set_sha256,
        },
    }


def validate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    manifest_rows = fixture.get("manifest_rows", [])
    if not isinstance(manifest_rows, list) or not manifest_rows:
        blockers.append("annotation manifest rows missing")
        manifest_rows = []
    manifest_by_id = {}
    for row in manifest_rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("annotation manifest row hash mismatch")
            continue
        if row.get("item_id") in manifest_by_id:
            blockers.append("duplicate manifest item id")
        manifest_by_id[row.get("item_id")] = row
    if fixture.get("manifest_sha256") != sha256_json(manifest_rows):
        blockers.append("annotation manifest sha256 mismatch")

    work_orders = fixture.get("work_order_rows", [])
    if not isinstance(work_orders, list) or not work_orders:
        blockers.append("reviewer work-order rows missing")
        work_orders = []
    work_order_by_id = {}
    for row in work_orders:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("work-order row hash mismatch")
            continue
        if row.get("work_order_id") in work_order_by_id:
            blockers.append("duplicate work-order id")
        work_order_by_id[row.get("work_order_id")] = row
        manifest_row = manifest_by_id.get(row.get("item_id"))
        if not manifest_row or row.get("manifest_row_sha256") != manifest_row.get("row_sha256"):
            blockers.append("work-order row manifest binding mismatch")

    first_pass_rows = fixture.get("first_pass_rows", [])
    if not isinstance(first_pass_rows, list) or not first_pass_rows:
        blockers.append("first-pass label rows missing")
        first_pass_rows = []
    first_pass_by_item: dict[str, list[dict[str, Any]]] = {}
    for row in first_pass_rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("first-pass row hash mismatch")
            continue
        if row.get("generated_by_llm") is not False or row.get("template_source") is not None:
            blockers.append("first-pass row is synthetic or template-derived")
        work_order = work_order_by_id.get(row.get("work_order_id"))
        if not work_order:
            blockers.append("first-pass row references unknown work order")
        elif (
            work_order.get("reviewer_id") != row.get("reviewer_id")
            or work_order.get("role") != "first_pass"
        ):
            blockers.append("first-pass row work-order binding mismatch")
        elif work_order.get("item_id") != row.get("item_id"):
            blockers.append("first-pass row work-order item mismatch")
        elif work_order.get("manifest_row_sha256") != manifest_by_id.get(
            row.get("item_id"), {}
        ).get("row_sha256"):
            blockers.append("first-pass row work-order manifest binding mismatch")
        first_pass_by_item.setdefault(row.get("item_id"), []).append(row)

    for item_id in manifest_by_id:
        rows = first_pass_by_item.get(item_id, [])
        reviewers = {row.get("reviewer_id") for row in rows}
        if len(rows) != 2 or len(reviewers) != 2:
            blockers.append(f"{item_id} does not have two distinct first-pass reviewers")

    first_pass_reviewers = {
        row.get("reviewer_id") for rows in first_pass_by_item.values() for row in rows
    }
    first_pass_hashes_by_reviewer: dict[str, list[str]] = {}
    for rows in first_pass_by_item.values():
        for row in rows:
            first_pass_hashes_by_reviewer.setdefault(row.get("reviewer_id"), []).append(
                row.get("row_sha256")
            )

    submissions = fixture.get("first_pass_submission_artifacts", [])
    if not isinstance(submissions, list) or len(submissions) < 2:
        blockers.append("external first-pass submission artifacts missing")
        submissions = []
    submission_reviewers = set()
    for row in submissions:
        if not isinstance(row, dict):
            blockers.append("external first-pass submission artifact malformed")
            continue
        reviewer_id = row.get("reviewer_id")
        submission_reviewers.add(reviewer_id)
        if row.get("sealed") is not True:
            blockers.append("external first-pass submission artifacts are not sealed")
        if reviewer_id not in first_pass_reviewers:
            blockers.append("sealed submission reviewer/submission binding mismatch")
        expected_hashes = sorted(first_pass_hashes_by_reviewer.get(reviewer_id, []))
        submitted_hashes = sorted(row.get("submission_row_sha256s", []))
        if submitted_hashes != expected_hashes:
            blockers.append("sealed submission reviewer/submission binding mismatch")
        if row.get("submission_set_sha256") != sha256_json(submitted_hashes):
            blockers.append("sealed submission set hash mismatch")
    if submission_reviewers != first_pass_reviewers:
        blockers.append("sealed submission reviewer set mismatch")

    disagreement_set = fixture.get("disagreement_set", [])
    if not isinstance(disagreement_set, list):
        blockers.append("disagreement set malformed")
        disagreement_set = []
    expected_disagreements = []
    for item_id, rows in first_pass_by_item.items():
        if len(rows) == 2 and rows[0].get("label") != rows[1].get("label"):
            ordered = sorted(rows, key=lambda row: str(row.get("reviewer_id")))
            expected_disagreements.append(
                {
                    "item_id": item_id,
                    "alpha_row_sha256": ordered[0]["row_sha256"],
                    "beta_row_sha256": ordered[1]["row_sha256"],
                }
            )
    if disagreement_set != expected_disagreements:
        blockers.append("sealed disagreement set does not match first-pass rows")
    if not disagreement_set:
        blockers.append("annotation protocol fixture does not exercise adjudication disagreement")
    disagreement_set_sha256 = sha256_json(disagreement_set)

    open_receipt = fixture.get("adjudication_open_receipt", {})
    if not isinstance(open_receipt, dict) or not open_receipt:
        blockers.append("adjudication-open receipt missing")
        open_receipt = {}
    if open_receipt.get("opened_after_first_pass_seal") is not True:
        blockers.append("adjudication opened before first-pass seal")
    if open_receipt.get("manifest_sha256") != fixture.get("manifest_sha256"):
        blockers.append("adjudication-open receipt manifest mismatch")
    if open_receipt.get("sealed_disagreement_set_sha256") != disagreement_set_sha256:
        blockers.append("adjudication-open receipt disagreement-set mismatch")

    adjudication_rows = fixture.get("adjudication_rows", [])
    if not isinstance(adjudication_rows, list):
        blockers.append("adjudication rows malformed")
        adjudication_rows = []
    if not adjudication_rows:
        blockers.append("adjudication rows missing for disagreement exercise")
    adjudicated_items = []
    for row in adjudication_rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("adjudication row hash mismatch")
            continue
        if row.get("generated_by_llm") is not False or row.get("template_source") is not None:
            blockers.append("adjudication row is synthetic or template-derived")
        work_order = work_order_by_id.get(row.get("work_order_id"))
        if not work_order:
            blockers.append("adjudication row references unknown work order")
        elif (
            work_order.get("reviewer_id") != row.get("adjudicator_id")
            or work_order.get("role") != "adjudicator"
        ):
            blockers.append("adjudication row work-order binding mismatch")
        elif work_order.get("item_id") != row.get("item_id"):
            blockers.append("adjudication row work-order item mismatch")
        elif work_order.get("manifest_row_sha256") != manifest_by_id.get(
            row.get("item_id"), {}
        ).get("row_sha256"):
            blockers.append("adjudication row work-order manifest binding mismatch")
        if row.get("adjudicator_id") in first_pass_reviewers:
            blockers.append("adjudicator is not distinct from first-pass reviewers")
        if row.get("sealed_disagreement_set_sha256") != disagreement_set_sha256:
            blockers.append("adjudication row disagreement-set mismatch")
        adjudicated_items.append(row.get("item_id"))

    disagreement_items = {row.get("item_id") for row in disagreement_set if isinstance(row, dict)}
    duplicate_items = {
        item_id for item_id in adjudicated_items if adjudicated_items.count(item_id) > 1
    }
    if duplicate_items:
        blockers.append("duplicate adjudication row for sealed disagreement item")
    if set(adjudicated_items) != disagreement_items or len(adjudicated_items) != len(
        disagreement_items
    ):
        blockers.append("adjudication rows do not cover exactly the sealed disagreement set")

    custody = fixture.get("custody_receipt", {})
    if not isinstance(custody, dict) or not custody:
        blockers.append("final custody receipt missing")
        custody = {}
    if custody.get("manifest_sha256") != fixture.get("manifest_sha256"):
        blockers.append("custody receipt manifest mismatch")
    if custody.get("first_pass_rows_sha256") != sha256_json(first_pass_rows):
        blockers.append("custody receipt first-pass rows mismatch")
    if custody.get("adjudication_rows_sha256") != sha256_json(adjudication_rows):
        blockers.append("custody receipt adjudication rows mismatch")
    if custody.get("sealed_disagreement_set_sha256") != disagreement_set_sha256:
        blockers.append("custody receipt disagreement-set mismatch")

    metrics = {
        "manifest_item_count": len(manifest_by_id),
        "first_pass_row_count": len(first_pass_rows),
        "distinct_first_pass_reviewer_count": len(first_pass_reviewers),
        "disagreement_count": len(disagreement_set),
        "adjudication_row_count": len(adjudication_rows),
        "protocol_controls_passed": not blockers,
        "real_human_packet_present": fixture.get("real_human_packet_present") is True,
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
        "artifact_id": "annotation_protocol_recovery_v1",
        "fixture_sha256": sha256_json(fixture),
        "passed": validation["passed"],
        "metrics": validation["metrics"],
        "blockers": validation["blockers"],
        "claim_boundary": {
            "supports_annotation_protocol_controls_claim": validation["passed"],
            "supports_human_annotation_completed_claim": False,
            "supports_human_adjudication_completed_claim": False,
            "supports_synthetic_label_generation_claim": False,
            "supports_template_as_human_evidence_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_production_ready_claim": False,
        },
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "annotation_protocol_recovery.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
